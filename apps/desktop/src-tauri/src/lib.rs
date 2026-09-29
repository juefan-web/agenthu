mod campus;
mod vault;

use rusqlite::{params, Connection};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Mutex;
use std::time::Duration;
use tauri::Manager;
use campus::CampusState;

/// 队列存储：单一长连接 + WAL + busy_timeout（B-2）。此前每次 invoke 都新开
/// `Connection` 且无 busy handler——采集 flush、手动重试与 online 监听并发打
/// 队列命令时会直接撞 "database is locked"。
struct QueueStore {
    connection: Connection,
}

impl QueueStore {
    fn open(path: &Path) -> Result<Self, String> {
        let connection = Connection::open(path).map_err(|error| error.to_string())?;
        // WAL：读写不互斥（写写仍由 SQLite 串行）；busy_timeout：锁竞争时等待
        // 而非立即失败。两者都是连接级设置，随本连接生命周期生效。
        connection.busy_timeout(Duration::from_millis(5_000)).map_err(|error| error.to_string())?;
        connection.pragma_update(None, "journal_mode", "WAL").map_err(|error| error.to_string())?;
        connection.execute_batch(
            "CREATE TABLE IF NOT EXISTS pending_events (
                client_event_id TEXT PRIMARY KEY NOT NULL,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY NOT NULL,
                value TEXT
            );
            CREATE TABLE IF NOT EXISTS focus_draft (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                payload TEXT NOT NULL
            );",
        ).map_err(|error| error.to_string())?;
        Ok(Self { connection })
    }

    fn add(&mut self, events: Vec<serde_json::Value>) -> Result<(), String> {
        let transaction = self.connection.transaction().map_err(|error| error.to_string())?;
        for event in events {
            let id = event.get("client_event_id")
                .and_then(serde_json::Value::as_str)
                .filter(|id| !id.is_empty())
                .ok_or("事件缺少 client_event_id")?;
            let payload = serde_json::to_string(&event).map_err(|error| error.to_string())?;
            transaction.execute(
                "INSERT OR IGNORE INTO pending_events (client_event_id, payload) VALUES (?1, ?2)",
                params![id, payload],
            ).map_err(|error| error.to_string())?;
        }
        transaction.commit().map_err(|error| error.to_string())
    }

    fn list(&self) -> Result<Vec<serde_json::Value>, String> {
        let mut statement = self.connection.prepare("SELECT payload FROM pending_events ORDER BY rowid")
            .map_err(|error| error.to_string())?;
        let rows = statement.query_map([], |row| row.get::<_, String>(0))
            .map_err(|error| error.to_string())?;
        Ok(collect_pending_events(rows))
    }

    fn remove(&mut self, client_event_ids: Vec<String>) -> Result<(), String> {
        let transaction = self.connection.transaction().map_err(|error| error.to_string())?;
        for id in client_event_ids {
            transaction.execute("DELETE FROM pending_events WHERE client_event_id = ?1", params![id])
                .map_err(|error| error.to_string())?;
        }
        transaction.commit().map_err(|error| error.to_string())
    }

    fn get_cursor(&self) -> Result<Option<String>, String> {
        let mut statement = self.connection.prepare("SELECT value FROM sync_state WHERE key = 'event_cursor'")
            .map_err(|error| error.to_string())?;
        let mut rows = statement.query([]).map_err(|error| error.to_string())?;
        match rows.next().map_err(|error| error.to_string())? {
            Some(row) => row.get(0).map_err(|error| error.to_string()),
            None => Ok(None),
        }
    }

    fn set_cursor(&mut self, cursor: Option<String>) -> Result<(), String> {
        self.connection.execute(
            "INSERT INTO sync_state (key, value) VALUES ('event_cursor', ?1)
             ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            params![cursor],
        ).map_err(|error| error.to_string())?;
        Ok(())
    }

    fn focus_get_draft(&self) -> Result<Option<serde_json::Value>, String> {
        let mut statement = self.connection.prepare("SELECT payload FROM focus_draft WHERE id = 1")
            .map_err(|error| error.to_string())?;
        let mut rows = statement.query([]).map_err(|error| error.to_string())?;
        match rows.next().map_err(|error| error.to_string())? {
            Some(row) => {
                let payload: String = row.get(0).map_err(|error| error.to_string())?;
                serde_json::from_str(&payload).map(Some).map_err(|error| error.to_string())
            }
            None => Ok(None),
        }
    }

    fn focus_set_draft(&mut self, draft: Option<serde_json::Value>) -> Result<(), String> {
        if let Some(draft) = draft {
            let payload = serde_json::to_string(&draft).map_err(|error| error.to_string())?;
            self.connection.execute(
                "INSERT INTO focus_draft (id, payload) VALUES (1, ?1)
                 ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
                params![payload],
            ).map_err(|error| error.to_string())?;
        } else {
            self.connection.execute("DELETE FROM focus_draft WHERE id = 1", [])
                .map_err(|error| error.to_string())?;
        }
        Ok(())
    }
}

/// 进程级队列库：懒初始化的长连接，被全部 queue_*/focus_* 命令共享；
/// 失败语义与旧实现一致（逐命令返回 Err 字符串，而非启动即崩）。
struct QueueDb {
    path: PathBuf,
    store: Mutex<Option<QueueStore>>,
}

impl QueueDb {
    fn new(path: PathBuf) -> Self {
        Self { path, store: Mutex::new(None) }
    }

    fn with<T>(&self, run: impl FnOnce(&mut QueueStore) -> Result<T, String>) -> Result<T, String> {
        let mut guard = self.store.lock().map_err(|_| "Queue database unavailable".to_string())?;
        if guard.is_none() {
            *guard = Some(QueueStore::open(&self.path)?);
        }
        run(guard.as_mut().expect("queue store initialized"))
    }
}

#[tauri::command]
fn queue_add(db: tauri::State<QueueDb>, events: Vec<serde_json::Value>) -> Result<(), String> {
    db.with(|store| store.add(events))
}

#[tauri::command]
fn queue_list(db: tauri::State<QueueDb>) -> Result<Vec<serde_json::Value>, String> {
    db.with(|store| store.list())
}

#[tauri::command]
fn queue_remove(db: tauri::State<QueueDb>, client_event_ids: Vec<String>) -> Result<(), String> {
    db.with(|store| store.remove(client_event_ids))
}

#[tauri::command]
fn queue_get_cursor(db: tauri::State<QueueDb>) -> Result<Option<String>, String> {
    db.with(|store| store.get_cursor())
}

#[tauri::command]
fn queue_set_cursor(db: tauri::State<QueueDb>, cursor: Option<String>) -> Result<(), String> {
    db.with(|store| store.set_cursor(cursor))
}

#[tauri::command]
fn focus_get_draft(db: tauri::State<QueueDb>) -> Result<Option<serde_json::Value>, String> {
    db.with(|store| store.focus_get_draft())
}

#[tauri::command]
fn focus_set_draft(db: tauri::State<QueueDb>, draft: Option<serde_json::Value>) -> Result<(), String> {
    db.with(|store| store.focus_set_draft(draft))
}

/// One damaged row must not block the whole offline queue: unreadable or
/// unparseable payloads are skipped so list, flush and future syncs keep
/// working. Skipping is non-destructive; the row stays in SQLite.
fn collect_pending_events<E: std::fmt::Display>(
    rows: impl Iterator<Item = Result<String, E>>,
) -> Vec<serde_json::Value> {
    rows.filter_map(|row| {
        let payload = match row {
            Ok(payload) => payload,
            Err(error) => {
                eprintln!("agenthu: skipping unreadable pending event row: {error}");
                return None;
            }
        };
        match serde_json::from_str(&payload) {
            Ok(event) => Some(event),
            Err(error) => {
                eprintln!("agenthu: skipping corrupt pending event payload: {error}");
                None
            }
        }
    }).collect()
}

const BACKEND_STORAGE_ERROR: &str = "Backend token storage failed";
const MAX_BACKEND_TOKEN_BYTES: usize = 16 * 1024;

fn backend_token_path(app: &tauri::AppHandle) -> Result<std::path::PathBuf, String> {
    let dir = app.path().app_local_data_dir().map_err(|_| BACKEND_STORAGE_ERROR)?;
    fs::create_dir_all(&dir).map_err(|_| BACKEND_STORAGE_ERROR)?;
    Ok(dir.join("backend.hold"))
}

#[tauri::command]
fn backend_token_get(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let Some(payload) = vault::read_backend(&backend_token_path(&app)?)? else { return Ok(None); };
    if payload.len() > MAX_BACKEND_TOKEN_BYTES { return Err(BACKEND_STORAGE_ERROR.into()); }
    String::from_utf8(payload).map(Some).map_err(|_| BACKEND_STORAGE_ERROR.into())
}

#[tauri::command]
fn backend_token_set(app: tauri::AppHandle, token: String) -> Result<(), String> {
    if token.len() > MAX_BACKEND_TOKEN_BYTES || !token.trim_start().starts_with('{') {
        return Err(BACKEND_STORAGE_ERROR.into());
    }
    vault::write_backend(&backend_token_path(&app)?, token.into_bytes())
}

#[tauri::command]
fn backend_token_clear(app: tauri::AppHandle) -> Result<(), String> {
    vault::clear_backend(&backend_token_path(&app)?)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(CampusState::default())
        .setup(|app| {
            // 懒初始化只解析路径；真正的连接与 PRAGMA 在首个队列命令时建立。
            let dir = app.path().app_data_dir().map_err(|error| error.to_string())?;
            fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
            app.manage(QueueDb::new(dir.join("offline.sqlite3")));
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            campus::campus_request, campus::campus_restore, campus::campus_save_session, campus::campus_logout,
            queue_add, queue_list, queue_remove, queue_get_cursor, queue_set_cursor,
            focus_get_draft, focus_set_draft,
            backend_token_get, backend_token_set, backend_token_clear,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Agenthu");
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    fn event_json(id: &str) -> serde_json::Value {
        serde_json::json!({ "client_event_id": id, "type": "study.course.discovered" })
    }

    #[test]
    fn queue_store_round_trips_events_cursor_and_focus_draft() {
        let dir = tempfile::tempdir().unwrap();
        let mut store = QueueStore::open(&dir.path().join("offline.sqlite3")).unwrap();

        store.add(vec![event_json("event-a"), event_json("event-b")]).unwrap();
        store.add(vec![event_json("event-a")]).unwrap(); // 幂等
        let events = store.list().unwrap();
        let ids: Vec<&str> = events.iter()
            .filter_map(|event| event.get("client_event_id").and_then(serde_json::Value::as_str))
            .collect();
        assert_eq!(ids, ["event-a", "event-b"]);

        store.set_cursor(Some("cursor-1".into())).unwrap();
        assert_eq!(store.get_cursor().unwrap().as_deref(), Some("cursor-1"));

        store.focus_set_draft(Some(serde_json::json!({ "note": "fixture" }))).unwrap();
        assert_eq!(store.focus_get_draft().unwrap().unwrap()["note"], "fixture");
        store.focus_set_draft(None).unwrap();
        assert!(store.focus_get_draft().unwrap().is_none());

        store.remove(vec!["event-a".into(), "event-b".into()]).unwrap();
        assert!(store.list().unwrap().is_empty());
        store.set_cursor(None).unwrap();
        assert!(store.get_cursor().unwrap().is_none());
    }

    #[test]
    fn queue_store_runs_in_wal_mode_and_isolates_corrupt_rows() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("offline.sqlite3");
        let mut store = QueueStore::open(&path).unwrap();

        let mode: String = store.connection
            .query_row("PRAGMA journal_mode", [], |row| row.get(0))
            .unwrap();
        assert_eq!(mode.to_lowercase(), "wal");

        store.add(vec![event_json("event-good")]).unwrap();
        // 直接写入坏载荷（模拟历史损坏行），list 必须隔离而非整体报错
        store.connection.execute(
            "INSERT INTO pending_events (client_event_id, payload) VALUES ('bad', 'not-json')",
            [],
        ).unwrap();
        let events = store.list().unwrap();
        let ids: Vec<&str> = events.iter()
            .filter_map(|event| event.get("client_event_id").and_then(serde_json::Value::as_str))
            .collect();
        assert_eq!(ids, ["event-good"]);
    }

    #[test]
    fn queue_db_shares_one_connection_across_concurrent_commands() {
        let dir = tempfile::tempdir().unwrap();
        let db = Arc::new(QueueDb::new(dir.path().join("offline.sqlite3")));

        let mut workers = Vec::new();
        for worker in 0..4 {
            let db = Arc::clone(&db);
            workers.push(std::thread::spawn(move || {
                for i in 0..25 {
                    let id = format!("worker-{worker}-event-{i}");
                    db.with(|store| store.add(vec![event_json(&id)])).unwrap();
                    db.with(|store| store.list().map(|events| events.len())).unwrap();
                }
            }));
        }
        for worker in workers {
            worker.join().expect("queue worker must not panic");
        }

        let total = db.with(|store| store.list().map(|events| events.len())).unwrap();
        // 4 × 25 全部落库：锁竞争由 busy_timeout 吸收，无丢失无 locked 报错
        assert_eq!(total, 100);
    }
}
