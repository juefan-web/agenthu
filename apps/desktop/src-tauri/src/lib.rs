mod campus;
mod vault;

use rusqlite::{params, Connection};
use std::fs;
use tauri::Manager;
use campus::CampusState;

fn queue_connection(app: &tauri::AppHandle) -> Result<Connection, String> {
    let dir = app.path().app_data_dir().map_err(|error| error.to_string())?;
    fs::create_dir_all(&dir).map_err(|error| error.to_string())?;
    let connection = Connection::open(dir.join("offline.sqlite3")).map_err(|error| error.to_string())?;
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
    Ok(connection)
}

#[tauri::command]
fn queue_add(app: tauri::AppHandle, events: Vec<serde_json::Value>) -> Result<(), String> {
    let mut connection = queue_connection(&app)?;
    let transaction = connection.transaction().map_err(|error| error.to_string())?;
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

#[tauri::command]
fn queue_list(app: tauri::AppHandle) -> Result<Vec<serde_json::Value>, String> {
    let connection = queue_connection(&app)?;
    let mut statement = connection.prepare("SELECT payload FROM pending_events ORDER BY rowid")
        .map_err(|error| error.to_string())?;
    let rows = statement.query_map([], |row| row.get::<_, String>(0))
        .map_err(|error| error.to_string())?;
    Ok(collect_pending_events(rows))
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

#[tauri::command]
fn queue_remove(app: tauri::AppHandle, client_event_ids: Vec<String>) -> Result<(), String> {
    let mut connection = queue_connection(&app)?;
    let transaction = connection.transaction().map_err(|error| error.to_string())?;
    for id in client_event_ids {
        transaction.execute("DELETE FROM pending_events WHERE client_event_id = ?1", params![id])
            .map_err(|error| error.to_string())?;
    }
    transaction.commit().map_err(|error| error.to_string())
}

#[tauri::command]
fn queue_get_cursor(app: tauri::AppHandle) -> Result<Option<String>, String> {
    let connection = queue_connection(&app)?;
    let mut statement = connection.prepare("SELECT value FROM sync_state WHERE key = 'event_cursor'")
        .map_err(|error| error.to_string())?;
    let mut rows = statement.query([]).map_err(|error| error.to_string())?;
    match rows.next().map_err(|error| error.to_string())? {
        Some(row) => row.get(0).map_err(|error| error.to_string()),
        None => Ok(None),
    }
}

#[tauri::command]
fn queue_set_cursor(app: tauri::AppHandle, cursor: Option<String>) -> Result<(), String> {
    let connection = queue_connection(&app)?;
    connection.execute(
        "INSERT INTO sync_state (key, value) VALUES ('event_cursor', ?1)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        params![cursor],
    ).map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
fn focus_get_draft(app: tauri::AppHandle) -> Result<Option<serde_json::Value>, String> {
    let connection = queue_connection(&app)?;
    let mut statement = connection.prepare("SELECT payload FROM focus_draft WHERE id = 1")
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

#[tauri::command]
fn focus_set_draft(app: tauri::AppHandle, draft: Option<serde_json::Value>) -> Result<(), String> {
    let connection = queue_connection(&app)?;
    if let Some(draft) = draft {
        let payload = serde_json::to_string(&draft).map_err(|error| error.to_string())?;
        connection.execute(
            "INSERT INTO focus_draft (id, payload) VALUES (1, ?1)
             ON CONFLICT(id) DO UPDATE SET payload = excluded.payload",
            params![payload],
        ).map_err(|error| error.to_string())?;
    } else {
        connection.execute("DELETE FROM focus_draft WHERE id = 1", [])
            .map_err(|error| error.to_string())?;
    }
    Ok(())
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

    #[test]
    fn queue_listing_isolates_corrupt_rows() {
        let rows = vec![
            Ok(r#"{"client_event_id":"event-a"}"#.to_string()),
            Err(rusqlite::Error::QueryReturnedNoRows),
            Ok("{not json".to_string()),
            Ok(r#"{"client_event_id":"event-b"}"#.to_string()),
        ];
        let events = collect_pending_events(rows.into_iter());
        let ids: Vec<&str> = events.iter()
            .filter_map(|event| event.get("client_event_id").and_then(serde_json::Value::as_str))
            .collect();
        assert_eq!(ids, ["event-a", "event-b"]);
    }
}