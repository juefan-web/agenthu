mod backend_proxy;
mod campus;
mod material_transfer;
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

/// P0-2（D-036）：owner 维度上线迁移。旧库三表无 owner——历史行一律归
/// 'unowned' 命名空间，禁止自动归当前账号（无主数据的处置是用户的显式
/// 决定，走 queue_unowned_adopt / queue_unowned_discard）。重建表是因为
/// PK 必须纳入 owner：两个账号可采集同一上游事件（client_event_id 同值），
/// 全局唯一键会把后入队的静默丢掉。
fn migrate_owner(connection: &Connection) -> Result<(), String> {
    let has_owner = |table: &str| -> Result<bool, String> {
        let mut statement = connection
            .prepare(&format!("PRAGMA table_info({table})"))
            .map_err(|error| error.to_string())?;
        let rows = statement.query_map([], |row| row.get::<_, String>(1))
            .map_err(|error| error.to_string())?;
        let found = rows.filter_map(|row| row.ok()).any(|name| name == "owner");
        Ok(found)
    };
    if !has_owner("pending_events")? {
        connection.execute_batch(
            "ALTER TABLE pending_events RENAME TO pending_events_old;
             CREATE TABLE pending_events (
                 owner TEXT NOT NULL,
                 client_event_id TEXT NOT NULL,
                 payload TEXT NOT NULL,
                 PRIMARY KEY (owner, client_event_id)
             );
             INSERT OR IGNORE INTO pending_events SELECT 'unowned', client_event_id, payload FROM pending_events_old;
             DROP TABLE pending_events_old;",
        ).map_err(|error| error.to_string())?;
    }
    if !has_owner("sync_state")? {
        connection.execute_batch(
            "ALTER TABLE sync_state RENAME TO sync_state_old;
             CREATE TABLE sync_state (
                 owner TEXT NOT NULL,
                 key TEXT NOT NULL,
                 value TEXT,
                 PRIMARY KEY (owner, key)
             );
             INSERT OR IGNORE INTO sync_state SELECT 'unowned', key, value FROM sync_state_old;
             DROP TABLE sync_state_old;",
        ).map_err(|error| error.to_string())?;
    }
    if !has_owner("focus_draft")? {
        connection.execute_batch(
            "ALTER TABLE focus_draft RENAME TO focus_draft_old;
             CREATE TABLE focus_draft (
                 owner TEXT PRIMARY KEY,
                 payload TEXT NOT NULL
             );
             INSERT OR IGNORE INTO focus_draft SELECT 'unowned', payload FROM focus_draft_old;
             DROP TABLE focus_draft_old;",
        ).map_err(|error| error.to_string())?;
    }
    connection.execute_batch("CREATE INDEX IF NOT EXISTS idx_pending_events_owner ON pending_events(owner);")
        .map_err(|error| error.to_string())?;
    Ok(())
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
                owner TEXT NOT NULL,
                client_event_id TEXT NOT NULL,
                payload TEXT NOT NULL,
                PRIMARY KEY (owner, client_event_id)
            );
            CREATE TABLE IF NOT EXISTS sync_state (
                owner TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT,
                PRIMARY KEY (owner, key)
            );
            CREATE TABLE IF NOT EXISTS focus_draft (
                owner TEXT PRIMARY KEY,
                payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS backend_origins (
                origin TEXT PRIMARY KEY NOT NULL
            );",
        ).map_err(|error| error.to_string())?;
        migrate_owner(&connection)?;
        Ok(Self { connection })
    }

    fn add(&mut self, owner: &str, events: Vec<serde_json::Value>) -> Result<(), String> {
        let transaction = self.connection.transaction().map_err(|error| error.to_string())?;
        for event in events {
            let id = event.get("client_event_id")
                .and_then(serde_json::Value::as_str)
                .filter(|id| !id.is_empty())
                .ok_or("事件缺少 client_event_id")?;
            let payload = serde_json::to_string(&event).map_err(|error| error.to_string())?;
            transaction.execute(
                "INSERT OR IGNORE INTO pending_events (owner, client_event_id, payload) VALUES (?1, ?2, ?3)",
                params![owner, id, payload],
            ).map_err(|error| error.to_string())?;
        }
        transaction.commit().map_err(|error| error.to_string())
    }

    fn list(&self, owner: &str) -> Result<Vec<serde_json::Value>, String> {
        let mut statement = self.connection
            .prepare("SELECT payload FROM pending_events WHERE owner = ?1 ORDER BY rowid")
            .map_err(|error| error.to_string())?;
        let rows = statement.query_map(params![owner], |row| row.get::<_, String>(0))
            .map_err(|error| error.to_string())?;
        Ok(collect_pending_events(rows))
    }

    fn remove(&mut self, owner: &str, client_event_ids: Vec<String>) -> Result<(), String> {
        let transaction = self.connection.transaction().map_err(|error| error.to_string())?;
        for id in client_event_ids {
            transaction.execute(
                "DELETE FROM pending_events WHERE owner = ?1 AND client_event_id = ?2",
                params![owner, id],
            ).map_err(|error| error.to_string())?;
        }
        transaction.commit().map_err(|error| error.to_string())
    }

    fn get_cursor(&self, owner: &str) -> Result<Option<String>, String> {
        let mut statement = self.connection
            .prepare("SELECT value FROM sync_state WHERE owner = ?1 AND key = 'event_cursor'")
            .map_err(|error| error.to_string())?;
        let mut rows = statement.query(params![owner]).map_err(|error| error.to_string())?;
        match rows.next().map_err(|error| error.to_string())? {
            Some(row) => row.get(0).map_err(|error| error.to_string()),
            None => Ok(None),
        }
    }

    fn set_cursor(&mut self, owner: &str, cursor: Option<String>) -> Result<(), String> {
        self.connection.execute(
            "INSERT INTO sync_state (owner, key, value) VALUES (?1, 'event_cursor', ?2)
             ON CONFLICT(owner, key) DO UPDATE SET value = excluded.value",
            params![owner, cursor],
        ).map_err(|error| error.to_string())?;
        Ok(())
    }

    fn focus_get_draft(&self, owner: &str) -> Result<Option<serde_json::Value>, String> {
        let mut statement = self.connection
            .prepare("SELECT payload FROM focus_draft WHERE owner = ?1")
            .map_err(|error| error.to_string())?;
        let mut rows = statement.query(params![owner]).map_err(|error| error.to_string())?;
        match rows.next().map_err(|error| error.to_string())? {
            Some(row) => {
                let payload: String = row.get(0).map_err(|error| error.to_string())?;
                serde_json::from_str(&payload).map(Some).map_err(|error| error.to_string())
            }
            None => Ok(None),
        }
    }

    fn focus_set_draft(&mut self, owner: &str, draft: Option<serde_json::Value>) -> Result<(), String> {
        if let Some(draft) = draft {
            let payload = serde_json::to_string(&draft).map_err(|error| error.to_string())?;
            self.connection.execute(
                "INSERT INTO focus_draft (owner, payload) VALUES (?1, ?2)
                 ON CONFLICT(owner) DO UPDATE SET payload = excluded.payload",
                params![owner, payload],
            ).map_err(|error| error.to_string())?;
        } else {
            self.connection.execute("DELETE FROM focus_draft WHERE owner = ?1", params![owner])
                .map_err(|error| error.to_string())?;
        }
        Ok(())
    }

    /// 无主 Focus 草稿的显式处置（P0-4；与事件队列 adopt 同语义：目标
    /// 已有草稿优先，无主行随后移除——禁止自动归户的反面 = 用户显式归户）。
    fn focus_adopt_unowned(&mut self, target_owner: &str) -> Result<i64, String> {
        if target_owner == "unowned" {
            return Err("cannot adopt the unowned namespace into itself".into());
        }
        let adopted = self.connection.execute(
            "INSERT OR IGNORE INTO focus_draft (owner, payload)
             SELECT ?1, payload FROM focus_draft WHERE owner = 'unowned'",
            params![target_owner],
        ).map_err(|error| error.to_string())?;
        self.connection.execute("DELETE FROM focus_draft WHERE owner = 'unowned'", [])
            .map_err(|error| error.to_string())?;
        Ok(adopted as i64)
    }

    fn focus_discard_unowned(&mut self) -> Result<i64, String> {
        let removed = self.connection.execute("DELETE FROM focus_draft WHERE owner = 'unowned'", [])
            .map_err(|error| error.to_string())?;
        Ok(removed as i64)
    }

    /// 无主命名空间的显式处置（D-036：禁止自动归户）。adopt 把无主事件与
    /// cursor 并入目标 owner：目标既有事件/cursor 键优先（INSERT OR IGNORE），
    /// 服务端按 client_event_id 幂等，被丢弃的无主 cursor 只是顺序提示。
    fn unowned_count(&self) -> Result<i64, String> {
        self.connection.query_row(
            "SELECT COUNT(*) FROM pending_events WHERE owner = 'unowned'",
            [],
            |row| row.get(0),
        ).map_err(|error| error.to_string())
    }

    fn unowned_adopt(&mut self, target_owner: &str) -> Result<i64, String> {
        let transaction = self.connection.transaction().map_err(|error| error.to_string())?;
        let moved = transaction.execute(
            "INSERT OR IGNORE INTO pending_events (owner, client_event_id, payload)
             SELECT ?1, client_event_id, payload FROM pending_events WHERE owner = 'unowned'",
            params![target_owner],
        ).map_err(|error| error.to_string())? as i64;
        transaction.execute("DELETE FROM pending_events WHERE owner = 'unowned'", [])
            .map_err(|error| error.to_string())?;
        transaction.execute(
            "INSERT OR IGNORE INTO sync_state (owner, key, value)
             SELECT ?1, key, value FROM sync_state WHERE owner = 'unowned'",
            params![target_owner],
        ).map_err(|error| error.to_string())?;
        transaction.execute("DELETE FROM sync_state WHERE owner = 'unowned'", [])
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(moved)
    }

    fn unowned_discard(&mut self) -> Result<i64, String> {
        let transaction = self.connection.transaction().map_err(|error| error.to_string())?;
        let removed = transaction.execute("DELETE FROM pending_events WHERE owner = 'unowned'", [])
            .map_err(|error| error.to_string())? as i64;
        transaction.execute("DELETE FROM sync_state WHERE owner = 'unowned'", [])
            .map_err(|error| error.to_string())?;
        transaction.commit().map_err(|error| error.to_string())?;
        Ok(removed)
    }

    /// B-4：用户显式添加的 Backend 源（allowlist 的持久化部分；构建期默认由
    /// build.rs 常量提供，不落库）。
    fn backend_origins(&self) -> Result<Vec<String>, String> {
        let mut statement = self.connection.prepare("SELECT origin FROM backend_origins ORDER BY origin")
            .map_err(|error| error.to_string())?;
        let rows = statement.query_map([], |row| row.get::<_, String>(0))
            .map_err(|error| error.to_string())?;
        Ok(rows.filter_map(|row| row.ok()).collect())
    }

    fn backend_origin_add(&mut self, origin: &str) -> Result<(), String> {
        self.connection.execute(
            "INSERT OR IGNORE INTO backend_origins (origin) VALUES (?1)",
            params![origin],
        ).map_err(|error| error.to_string())?;
        Ok(())
    }

    fn backend_origin_remove(&mut self, origin: &str) -> Result<(), String> {
        self.connection.execute(
            "DELETE FROM backend_origins WHERE origin = ?1",
            params![origin],
        ).map_err(|error| error.to_string())?;
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
fn queue_add(db: tauri::State<QueueDb>, owner: String, events: Vec<serde_json::Value>) -> Result<(), String> {
    db.with(|store| store.add(&owner, events))
}

#[tauri::command]
fn queue_list(db: tauri::State<QueueDb>, owner: String) -> Result<Vec<serde_json::Value>, String> {
    db.with(|store| store.list(&owner))
}

#[tauri::command]
fn queue_remove(db: tauri::State<QueueDb>, owner: String, client_event_ids: Vec<String>) -> Result<(), String> {
    db.with(|store| store.remove(&owner, client_event_ids))
}

#[tauri::command]
fn queue_get_cursor(db: tauri::State<QueueDb>, owner: String) -> Result<Option<String>, String> {
    db.with(|store| store.get_cursor(&owner))
}

#[tauri::command]
fn queue_set_cursor(db: tauri::State<QueueDb>, owner: String, cursor: Option<String>) -> Result<(), String> {
    db.with(|store| store.set_cursor(&owner, cursor))
}

#[tauri::command]
fn queue_unowned_count(db: tauri::State<QueueDb>) -> Result<i64, String> {
    db.with(|store| store.unowned_count())
}

#[tauri::command]
fn queue_unowned_adopt(db: tauri::State<QueueDb>, target_owner: String) -> Result<i64, String> {
    db.with(|store| store.unowned_adopt(&target_owner))
}

#[tauri::command]
fn queue_unowned_discard(db: tauri::State<QueueDb>) -> Result<i64, String> {
    db.with(|store| store.unowned_discard())
}

#[tauri::command]
fn focus_adopt_unowned(db: tauri::State<QueueDb>, target_owner: String) -> Result<i64, String> {
    db.with(|store| store.focus_adopt_unowned(&target_owner))
}

#[tauri::command]
fn focus_discard_unowned(db: tauri::State<QueueDb>) -> Result<i64, String> {
    db.with(|store| store.focus_discard_unowned())
}

#[tauri::command]
fn focus_get_draft(db: tauri::State<QueueDb>, owner: String) -> Result<Option<serde_json::Value>, String> {
    db.with(|store| store.focus_get_draft(&owner))
}

#[tauri::command]
fn focus_set_draft(db: tauri::State<QueueDb>, owner: String, draft: Option<serde_json::Value>) -> Result<(), String> {
    db.with(|store| store.focus_set_draft(&owner, draft))
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

const RECEIPT_STORAGE_ERROR: &str = "Receipt slot storage failed";
const MAX_RECEIPT_BYTES: usize = 8 * 1024;

fn receipt_slot_path(app: &tauri::AppHandle, owner: &str) -> Result<std::path::PathBuf, String> {
    if owner.len() < 8 || owner.len() > 64 || !owner.bytes().all(|b| b.is_ascii_alphanumeric()) {
        return Err(RECEIPT_STORAGE_ERROR.into());
    }
    let dir = app.path().app_local_data_dir().map_err(|_| RECEIPT_STORAGE_ERROR)?;
    fs::create_dir_all(&dir).map_err(|_| RECEIPT_STORAGE_ERROR)?;
    Ok(dir.join(format!("receipt-{owner}.hold")))
}

#[tauri::command]
fn receipt_get(app: tauri::AppHandle, owner: String) -> Result<Option<String>, String> {
    let Some(payload) = vault::read_receipt(&receipt_slot_path(&app, &owner)?, &owner)? else {
        return Ok(None);
    };
    if payload.len() > MAX_RECEIPT_BYTES { return Err(RECEIPT_STORAGE_ERROR.into()); }
    String::from_utf8(payload).map(Some).map_err(|_| RECEIPT_STORAGE_ERROR.into())
}

#[tauri::command]
fn receipt_set(app: tauri::AppHandle, owner: String, payload: String) -> Result<(), String> {
    if payload.len() > MAX_RECEIPT_BYTES || !payload.trim_start().starts_with('{') {
        return Err(RECEIPT_STORAGE_ERROR.into());
    }
    vault::write_receipt(&receipt_slot_path(&app, &owner)?, &owner, payload.into_bytes())
}

#[tauri::command]
fn receipt_clear(app: tauri::AppHandle, owner: String) -> Result<(), String> {
    vault::clear_receipt(&receipt_slot_path(&app, &owner)?, &owner)
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(CampusState::default())
        .manage(backend_proxy::BackendProxy::default())
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
            queue_unowned_count, queue_unowned_adopt, queue_unowned_discard,
            focus_get_draft, focus_set_draft, focus_adopt_unowned, focus_discard_unowned,
            receipt_get, receipt_set, receipt_clear,
            backend_token_get, backend_token_set, backend_token_clear,
            backend_proxy::backend_request, backend_proxy::backend_origin_list,
            backend_proxy::backend_origin_add, backend_proxy::backend_origin_remove,
            material_transfer::material_upload,
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

        store.add("owner-a", vec![event_json("event-a"), event_json("event-b")]).unwrap();
        store.add("owner-a", vec![event_json("event-a")]).unwrap(); // 幂等
        let events = store.list("owner-a").unwrap();
        let ids: Vec<&str> = events.iter()
            .filter_map(|event| event.get("client_event_id").and_then(serde_json::Value::as_str))
            .collect();
        assert_eq!(ids, ["event-a", "event-b"]);

        store.set_cursor("owner-a", Some("cursor-1".into())).unwrap();
        assert_eq!(store.get_cursor("owner-a").unwrap().as_deref(), Some("cursor-1"));

        store.focus_set_draft("owner-a", Some(serde_json::json!({ "note": "fixture" }))).unwrap();
        assert_eq!(store.focus_get_draft("owner-a").unwrap().unwrap()["note"], "fixture");
        store.focus_set_draft("owner-a", None).unwrap();
        assert!(store.focus_get_draft("owner-a").unwrap().is_none());

        store.remove("owner-a", vec!["event-a".into(), "event-b".into()]).unwrap();
        assert!(store.list("owner-a").unwrap().is_empty());
        store.set_cursor("owner-a", None).unwrap();
        assert!(store.get_cursor("owner-a").unwrap().is_none());
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

        store.add("owner-a", vec![event_json("event-good")]).unwrap();
        // 直接写入坏载荷（模拟历史损坏行），list 必须隔离而非整体报错
        store.connection.execute(
            "INSERT INTO pending_events (owner, client_event_id, payload) VALUES ('owner-a', 'bad', 'not-json')",
            [],
        ).unwrap();
        let events = store.list("owner-a").unwrap();
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
            let owner = format!("owner-{worker}");
            workers.push(std::thread::spawn(move || {
                for i in 0..25 {
                    let id = format!("worker-{worker}-event-{i}");
                    db.with(|store| store.add(&owner, vec![event_json(&id)])).unwrap();
                    db.with(|store| store.list(&owner).map(|events| events.len())).unwrap();
                }
            }));
        }
        for worker in workers {
            worker.join().expect("queue worker must not panic");
        }

        // 4 × 25 全部落库：锁竞争由 busy_timeout 吸收，无丢失无 locked 报错；
        // 每个 owner 只见自己的 25 条（owner 隔离在并发下同样成立）。
        for worker in 0..4 {
            let owner = format!("owner-{worker}");
            let total = db.with(|store| store.list(&owner).map(|events| events.len())).unwrap();
            assert_eq!(total, 25);
        }
    }

    #[test]
    fn queue_db_dedupes_concurrent_same_owner_overlapping_ids() {
        let dir = tempfile::tempdir().unwrap();
        let db = Arc::new(QueueDb::new(dir.path().join("offline.sqlite3")));
        let owner = "owner-same".to_string();

        // 4 线程同 owner、完全重叠的 id 集：复合 PK (owner, client_event_id)
        // 上的 INSERT OR IGNORE 幂等在锁竞争下必须保持——总量 = 去重后 25，
        // 无丢失、无重复、无 locked 报错。
        let mut workers = Vec::new();
        for _ in 0..4 {
            let db = Arc::clone(&db);
            let owner = owner.clone();
            workers.push(std::thread::spawn(move || {
                for i in 0..25 {
                    let id = format!("shared-event-{i}");
                    db.with(|store| store.add(&owner, vec![event_json(&id)])).unwrap();
                }
            }));
        }
        for worker in workers {
            worker.join().expect("queue worker must not panic");
        }

        let total = db.with(|store| store.list(&owner).map(|events| events.len())).unwrap();
        assert_eq!(total, 25);
    }

    #[test]
    fn focus_draft_adoption_is_explicit_and_target_priority() {
        let dir = tempfile::tempdir().unwrap();
        let mut store = QueueStore::open(&dir.path().join("offline.sqlite3")).unwrap();

        store.focus_set_draft("unowned", Some(serde_json::json!({ "note": "legacy" }))).unwrap();
        // 未显式处置前：任何 owner 都看不见无主草稿
        assert!(store.focus_get_draft("owner-a").unwrap().is_none());

        // adopt：目标已有草稿优先（不被无主草稿覆盖），无主行随后移除
        store.focus_set_draft("owner-a", Some(serde_json::json!({ "note": "current" }))).unwrap();
        assert_eq!(store.focus_adopt_unowned("owner-a").unwrap(), 0);
        assert_eq!(store.focus_get_draft("owner-a").unwrap().unwrap()["note"], "current");
        assert!(store.focus_get_draft("unowned").unwrap().is_none());

        // 无目标时 adopt 落入目标命名空间；discard 直接清除
        store.focus_set_draft("unowned", Some(serde_json::json!({ "note": "orphan" }))).unwrap();
        assert_eq!(store.focus_adopt_unowned("owner-b").unwrap(), 1);
        assert_eq!(store.focus_get_draft("owner-b").unwrap().unwrap()["note"], "orphan");

        store.focus_set_draft("unowned", Some(serde_json::json!({ "note": "again" }))).unwrap();
        assert_eq!(store.focus_discard_unowned().unwrap(), 1);
        assert!(store.focus_get_draft("unowned").unwrap().is_none());
        // unowned 自身不是合法 adopt 目标
        assert!(store.focus_adopt_unowned("unowned").is_err());
    }

    #[test]
    fn owner_namespaces_isolate_events_cursor_and_draft() {
        let dir = tempfile::tempdir().unwrap();
        let mut store = QueueStore::open(&dir.path().join("offline.sqlite3")).unwrap();

        // 两 owner 采集同一上游事件（client_event_id 同值）——都必须保留
        store.add("owner-a", vec![event_json("same-upstream-event")]).unwrap();
        store.add("owner-b", vec![event_json("same-upstream-event")]).unwrap();
        assert_eq!(store.list("owner-a").unwrap().len(), 1);
        assert_eq!(store.list("owner-b").unwrap().len(), 1);

        // cursor 与草稿互不可见
        store.set_cursor("owner-a", Some("cursor-a".into())).unwrap();
        store.set_cursor("owner-b", Some("cursor-b".into())).unwrap();
        assert_eq!(store.get_cursor("owner-a").unwrap().as_deref(), Some("cursor-a"));
        assert_eq!(store.get_cursor("owner-b").unwrap().as_deref(), Some("cursor-b"));

        store.focus_set_draft("owner-a", Some(serde_json::json!({ "note": "a" }))).unwrap();
        store.focus_set_draft("owner-b", Some(serde_json::json!({ "note": "b" }))).unwrap();
        assert_eq!(store.focus_get_draft("owner-a").unwrap().unwrap()["note"], "a");
        assert_eq!(store.focus_get_draft("owner-b").unwrap().unwrap()["note"], "b");

        // 清一个 owner 不动另一个（「本地删除不清另一账号」）
        store.remove("owner-a", vec!["same-upstream-event".into()]).unwrap();
        store.set_cursor("owner-a", None).unwrap();
        store.focus_set_draft("owner-a", None).unwrap();
        assert!(store.list("owner-a").unwrap().is_empty());
        assert!(store.get_cursor("owner-a").unwrap().is_none());
        assert!(store.focus_get_draft("owner-a").unwrap().is_none());
        assert_eq!(store.list("owner-b").unwrap().len(), 1);
        assert_eq!(store.get_cursor("owner-b").unwrap().as_deref(), Some("cursor-b"));
        assert!(store.focus_get_draft("owner-b").unwrap().is_some());
    }

    #[test]
    fn legacy_rows_migrate_to_unowned_and_adoption_is_explicit() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("offline.sqlite3");
        {
            // 旧 schema（P0-2 之前）：无 owner 列、focus_draft 单行、cursor 无 owner
            let legacy = Connection::open(&path).unwrap();
            legacy.execute_batch(
                "CREATE TABLE pending_events (client_event_id TEXT PRIMARY KEY NOT NULL, payload TEXT NOT NULL);
                 CREATE TABLE sync_state (key TEXT PRIMARY KEY NOT NULL, value TEXT);
                 CREATE TABLE focus_draft (id INTEGER PRIMARY KEY CHECK (id = 1), payload TEXT NOT NULL);
                 INSERT INTO pending_events VALUES ('legacy-event', '{\"client_event_id\":\"legacy-event\"}');
                 INSERT INTO sync_state VALUES ('event_cursor', 'legacy-cursor');
                 INSERT INTO focus_draft VALUES (1, '{\"note\":\"legacy\"}');",
            ).unwrap();
        }

        let mut store = QueueStore::open(&path).unwrap();
        // 历史行全部归 unowned：任何 owner 的视图都不见它们
        assert!(store.list("owner-a").unwrap().is_empty());
        assert_eq!(store.unowned_count().unwrap(), 1);
        // 无主 draft 同样隔离（focus 表迁移后挂 unowned 名下）
        assert!(store.focus_get_draft("owner-a").unwrap().is_none());
        assert!(store.focus_get_draft("unowned").unwrap().is_some());

        // adopt：显式归户；目标既有 cursor（owner-a 已设）优先，无主 cursor 不覆盖
        store.set_cursor("owner-a", Some("cursor-a".into())).unwrap();
        store.add("owner-a", vec![event_json("legacy-event")]).unwrap(); // 目标已有同 id：保留目标行
        let moved = store.unowned_adopt("owner-a").unwrap();
        assert_eq!(moved, 0); // 同 id 未新增（目标优先），但无主侧已清空
        assert_eq!(store.unowned_count().unwrap(), 0);
        assert_eq!(store.get_cursor("owner-a").unwrap().as_deref(), Some("cursor-a"));

        // discard：显式丢弃
        store.add("unowned", vec![event_json("orphan-event")]).unwrap();
        assert_eq!(store.unowned_count().unwrap(), 1);
        let removed = store.unowned_discard().unwrap();
        assert_eq!(removed, 1);
        assert_eq!(store.unowned_count().unwrap(), 0);
    }
}
