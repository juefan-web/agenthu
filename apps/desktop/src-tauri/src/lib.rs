mod campus;
mod vault;

use rusqlite::{params, Connection};
use std::fs;
use tauri::Manager;
use campus::{campus_request, campus_restore, campus_save_session, campus_logout, CampusState};

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
pub fn queue_add(app: tauri::AppHandle, events: Vec<serde_json::Value>) -> Result<(), String> {
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
pub fn queue_list(app: tauri::AppHandle) -> Result<Vec<serde_json::Value>, String> {
    let connection = queue_connection(&app)?;
    let mut statement = connection.prepare("SELECT payload FROM pending_events ORDER BY rowid")
        .map_err(|error| error.to_string())?;
    let rows = statement.query_map([], |row| row.get::<_, String>(0))
        .map_err(|error| error.to_string())?;
    rows.map(|row| {
        let payload = row.map_err(|error| error.to_string())?;
        serde_json::from_str(&payload).map_err(|error| error.to_string())
    }).collect()
}

#[tauri::command]
pub fn queue_remove(app: tauri::AppHandle, client_event_ids: Vec<String>) -> Result<(), String> {
    let mut connection = queue_connection(&app)?;
    let transaction = connection.transaction().map_err(|error| error.to_string())?;
    for id in client_event_ids {
        transaction.execute("DELETE FROM pending_events WHERE client_event_id = ?1", params![id])
            .map_err(|error| error.to_string())?;
    }
    transaction.commit().map_err(|error| error.to_string())
}

#[tauri::command]
pub fn queue_get_cursor(app: tauri::AppHandle) -> Result<Option<String>, String> {
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
pub fn queue_set_cursor(app: tauri::AppHandle, cursor: Option<String>) -> Result<(), String> {
    let connection = queue_connection(&app)?;
    connection.execute(
        "INSERT INTO sync_state (key, value) VALUES ('event_cursor', ?1)
         ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        params![cursor],
    ).map_err(|error| error.to_string())?;
    Ok(())
}

#[tauri::command]
pub fn focus_get_draft(app: tauri::AppHandle) -> Result<Option<serde_json::Value>, String> {
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
pub fn focus_set_draft(app: tauri::AppHandle, draft: Option<serde_json::Value>) -> Result<(), String> {
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

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .manage(CampusState::default())
        .invoke_handler(tauri::generate_handler![
            campus_request, campus_restore, campus_save_session, campus_logout,
            queue_add, queue_list, queue_remove, queue_get_cursor, queue_set_cursor,
            focus_get_draft, focus_set_draft,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Agenthu");
}
