use reqwest::header::{HeaderMap, HeaderName, HeaderValue, SET_COOKIE};
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::fs;
use std::time::Duration;
use tauri::Manager;

fn allowed_campus_url(url: &url::Url) -> bool {
    let host = url.host_str().unwrap_or("");
    url.scheme() == "https"
        && (host == "tsinghua.edu.cn" || host.ends_with(".tsinghua.edu.cn"))
}

#[derive(Debug, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CampusRequest {
    pub url: String,
    pub method: String,
    pub headers: HashMap<String, String>,
    pub body: Option<String>,
    pub redirect: Option<String>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CampusResponse {
    pub status: u16,
    pub headers: HashMap<String, String>,
    pub body: String,
    pub final_url: String,
}

#[derive(Debug, Deserialize)]
pub struct LoginInput {
    pub username: String,
    pub password: String,
}

#[derive(Debug, Deserialize)]
pub struct Verify2faInput {
    pub method: String,
    pub code: String,
    #[serde(rename = "trustDevice")]
    pub trust_device: bool,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "kebab-case")]
pub enum AuthState {
    Idle,
    #[serde(rename = "need-2fa")]
    Need2fa,
    Ready,
    Error,
}

#[derive(Debug, Serialize)]
pub struct AuthReply {
    pub state: AuthState,
    pub username: Option<String>,
    pub methods: Vec<String>,
    pub message: Option<String>,
}

fn auth_error(message: impl Into<String>) -> AuthReply {
    AuthReply {
        state: AuthState::Error,
        username: None,
        methods: Vec::new(),
        message: Some(message.into()),
    }
}

#[tauri::command]
pub async fn campus_request(request: CampusRequest) -> Result<CampusResponse, String> {
    let url = url::Url::parse(&request.url).map_err(|_| "无效的校园请求地址")?;
    if !allowed_campus_url(&url) {
        return Err("校园请求仅允许清华大学 HTTPS 域名".to_string());
    }
    let redirect = match request.redirect.as_deref() {
        Some("manual") => reqwest::redirect::Policy::none(),
        Some("follow") | None => reqwest::redirect::Policy::custom(|attempt| {
            if attempt.previous().len() >= 10 {
                return attempt.error("校园请求重定向超过 10 次");
            }
            if !allowed_campus_url(attempt.url()) {
                return attempt.stop();
            }
            attempt.follow()
        }),
        _ => return Err("不支持的重定向模式".to_string()),
    };
    let client = reqwest::Client::builder()
        .redirect(redirect)
        .cookie_store(true)
        .timeout(Duration::from_secs(30))
        .build()
        .map_err(|error| error.to_string())?;
    let method = reqwest::Method::from_bytes(request.method.as_bytes())
        .map_err(|error| error.to_string())?;
    let mut builder = client.request(method, &request.url);
    let mut headers = HeaderMap::new();
    for (name, value) in request.headers {
        let key = HeaderName::try_from(name).map_err(|error| error.to_string())?;
        let val = HeaderValue::try_from(value).map_err(|error| error.to_string())?;
        headers.insert(key, val);
    }
    builder = builder.headers(headers);
    if let Some(body) = request.body {
        builder = builder.body(body);
    }
    let response = builder.send().await.map_err(|_| "校园网络请求失败".to_string())?;
    let status = response.status().as_u16();
    let final_url = response.url().to_string();
    let mut response_headers = HashMap::new();
    let cookies: Vec<String> = response
        .headers()
        .get_all(SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok().map(ToOwned::to_owned))
        .collect();
    if !cookies.is_empty() {
        response_headers.insert("x-onethu-set-cookie".to_string(), serde_json::to_string(&cookies).unwrap_or_default());
    }
    for (name, value) in response.headers() {
        if name == SET_COOKIE {
            continue;
        }
        if let Ok(value) = value.to_str() {
            response_headers.insert(name.to_string(), value.to_string());
        }
    }
    let body = response.text().await.map_err(|_| "校园响应读取失败".to_string())?;
    Ok(CampusResponse {
        status,
        headers: response_headers,
        body,
        final_url,
    })
}

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

#[tauri::command]
pub fn campus_restore() -> AuthReply {
    AuthReply {
        state: AuthState::Idle,
        username: None,
        methods: Vec::new(),
        message: None,
    }
}

#[tauri::command]
pub fn campus_login(input: LoginInput) -> AuthReply {
    if input.username.trim().is_empty() || input.password.is_empty() {
        return auth_error("学号和密码不能为空");
    }
    // CAS/2FA 业务链由 CampusAuthGateway 接入；命令层不记录密码。
    AuthReply {
        state: AuthState::Error,
        username: Some(input.username),
        methods: Vec::new(),
        message: Some("校园认证链尚未配置，请接入 CAS provider".to_string()),
    }
}

#[tauri::command]
pub fn campus_verify_2fa(input: Verify2faInput) -> AuthReply {
    if input.method.trim().is_empty() || input.code.trim().is_empty() {
        return auth_error("2FA 方法和验证码不能为空");
    }
    AuthReply {
        state: AuthState::Error,
        username: None,
        methods: Vec::new(),
        message: Some("校园认证链尚未配置，请接入 CAS provider".to_string()),
    }
}

#[tauri::command]
pub fn campus_logout() -> AuthReply {
    AuthReply {
        state: AuthState::Idle,
        username: None,
        methods: Vec::new(),
        message: None,
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_stronghold::Builder::new(|password| {
            use argon2::Argon2;
            use argon2::password_hash::SaltString;
            let salt = SaltString::encode_b64(b"agenthu-v1-fixed-salt").expect("valid salt");
            let mut output = [0u8; 32];
            Argon2::default()
                .hash_password_into(password.as_bytes(), salt.as_str().as_bytes(), &mut output)
                .expect("stronghold key derivation failed");
            output.to_vec()
        }).build())
        .invoke_handler(tauri::generate_handler![
            campus_request,
            queue_add,
            queue_list,
            queue_remove,
            queue_get_cursor,
            queue_set_cursor,
            focus_get_draft,
            focus_set_draft,
            campus_restore,
            campus_login,
            campus_verify_2fa,
            campus_logout,
        ])
        .run(tauri::generate_context!())
        .expect("error while running Agenthu");
}

#[cfg(test)]
mod tests {
    use super::allowed_campus_url;

    #[test]
    fn campus_requests_accept_only_tsinghua_https_hosts() {
        for allowed in ["https://tsinghua.edu.cn/", "https://learn.tsinghua.edu.cn/"] {
            assert!(allowed_campus_url(&url::Url::parse(allowed).unwrap()));
        }
        for denied in [
            "http://learn.tsinghua.edu.cn/",
            "https://tsinghua.edu.cn.evil.test/",
            "https://evil-tsinghua.edu.cn/",
        ] {
            assert!(!allowed_campus_url(&url::Url::parse(denied).unwrap()));
        }
    }
}
