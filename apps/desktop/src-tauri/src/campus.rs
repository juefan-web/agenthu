use crate::vault;
use cookie_store::CookieStore;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use reqwest_cookie_store::CookieStoreMutex;
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, path::PathBuf, sync::Arc, time::Duration};
use tauri::Manager;
use tokio::sync::Mutex;

const STORAGE_ERROR: &str = "Campus session storage failed";

#[derive(Clone, Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct SessionMetadata {
    username: String,
    fingerprint: String,
    finger3: String,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Snapshot {
    version: u8,
    metadata: SessionMetadata,
    cookies: Vec<cookie_store::Cookie<'static>>,
}

#[derive(Default)]
struct CampusSession {
    jar: Arc<CookieStoreMutex>,
    metadata: Option<SessionMetadata>,
}

#[derive(Default)]
pub struct CampusState(Mutex<CampusSession>);

pub fn allowed_campus_url(url: &url::Url) -> bool {
    let host = url.host_str().unwrap_or("");
    url.scheme() == "https" && url.username().is_empty() && url.password().is_none()
        && url.port_or_known_default() == Some(443)
        && (host == "tsinghua.edu.cn" || host.ends_with(".tsinghua.edu.cn"))
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct CampusRequest {
    url: String,
    method: String,
    headers: HashMap<String, String>,
    body: Option<String>,
    redirect: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CampusResponse {
    status: u16,
    headers: HashMap<String, String>,
    body: String,
    final_url: String,
}

fn snapshot_path(app: &tauri::AppHandle) -> Result<PathBuf, String> {
    let dir = app.path().app_local_data_dir().map_err(|_| STORAGE_ERROR)?;
    std::fs::create_dir_all(&dir).map_err(|_| STORAGE_ERROR)?;
    Ok(dir.join("campus.hold"))
}

fn persist(session: &CampusSession, path: &std::path::Path) -> Result<(), String> {
    if let Some(metadata) = &session.metadata {
        let cookies = session.jar.lock().map_err(|_| STORAGE_ERROR)?
            .iter_unexpired().cloned().collect();
        let payload = serde_json::to_vec(&Snapshot { version: 1, metadata: metadata.clone(), cookies })
            .map_err(|_| STORAGE_ERROR)?;
        vault::write(path, payload)?;
    }
    Ok(())
}

fn request_headers(values: HashMap<String, String>) -> Result<HeaderMap, String> {
    let mut headers = HeaderMap::new();
    for (name, value) in values {
        // Session headers belong exclusively to the native cookie store.
        if !matches!(name.to_ascii_lowercase().as_str(), "accept" | "content-type" | "user-agent" | "x-requested-with" | "x-xsrf-token") {
            continue;
        }
        headers.insert(HeaderName::try_from(name).map_err(|_| "Invalid campus header")?,
            HeaderValue::try_from(value).map_err(|_| "Invalid campus header")?);
    }
    Ok(headers)
}

#[tauri::command]
pub async fn campus_request(app: tauri::AppHandle, state: tauri::State<'_, CampusState>, request: CampusRequest) -> Result<CampusResponse, String> {
    let url = url::Url::parse(&request.url).map_err(|_| "Invalid campus URL")?;
    if !allowed_campus_url(&url) { return Err("Campus URL is not allowed".into()); }
    if !matches!(request.method.as_str(), "GET" | "POST" | "HEAD") {
        return Err("Campus method is not allowed".into());
    }
    if request.body.as_ref().is_some_and(|b| b.len() > 1024 * 1024) {
        return Err("Campus request is too large".into());
    }
    let redirect = match request.redirect.as_deref() {
        Some("manual") => reqwest::redirect::Policy::none(),
        Some("follow") | None => reqwest::redirect::Policy::custom(|attempt| {
            if attempt.previous().len() >= 10 || !allowed_campus_url(attempt.url()) {
                attempt.error("Campus redirect rejected")
            } else { attempt.follow() }
        }),
        _ => return Err("Unsupported redirect policy".into()),
    };
    // Serialize requests with restore/logout so a late response cannot resurrect cookies.
    let session = state.0.lock().await;
    let client = reqwest::Client::builder().redirect(redirect)
        .cookie_provider(Arc::clone(&session.jar)).timeout(Duration::from_secs(30))
        .build().map_err(|_| "Campus transport unavailable")?;
    let method = reqwest::Method::from_bytes(request.method.as_bytes()).map_err(|_| "Invalid method")?;
    let mut builder = client.request(method, url).headers(request_headers(request.headers)?);
    if let Some(body) = request.body { builder = builder.body(body); }
    let mut response = builder.send().await.map_err(|_| "Campus network request failed")?;
    let status = response.status().as_u16();
    let final_url = response.url().to_string();
    let headers = response.headers().iter()
        .filter(|(name, _)| matches!(name.as_str(), "content-type" | "location"))
        .filter_map(|(name, value)| value.to_str().ok().map(|v| (name.to_string(), v.to_owned())))
        .collect();
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "Campus response failed")? {
        if body.len() + chunk.len() > 16 * 1024 * 1024 { return Err("Campus response is too large".into()); }
        body.extend_from_slice(&chunk);
    }
    persist(&session, &snapshot_path(&app)?)?;
    Ok(CampusResponse { status, headers, body: String::from_utf8_lossy(&body).into_owned(), final_url })
}

#[tauri::command]
pub async fn campus_restore(app: tauri::AppHandle, state: tauri::State<'_, CampusState>) -> Result<Option<SessionMetadata>, String> {
    let mut session = state.0.lock().await;
    if let Some(payload) = vault::read(&snapshot_path(&app)?)? {
        let snapshot: Snapshot = serde_json::from_slice(&payload).map_err(|_| STORAGE_ERROR)?;
        if snapshot.version != 1 { return Err("Unsupported campus snapshot version".into()); }
        let store = CookieStore::from_cookies(snapshot.cookies.into_iter().map(Ok::<_, String>), false)?;
        session.jar = Arc::new(CookieStoreMutex::new(store));
        session.metadata = Some(snapshot.metadata);
    }
    Ok(session.metadata.clone())
}

#[tauri::command]
pub async fn campus_save_session(app: tauri::AppHandle, state: tauri::State<'_, CampusState>, metadata: SessionMetadata) -> Result<(), String> {
    if metadata.username.is_empty() || metadata.username.len() > 64 || metadata.fingerprint.len() > 128 || metadata.finger3.len() > 8192 {
        return Err("Invalid campus session metadata".into());
    }
    let mut session = state.0.lock().await;
    session.metadata = Some(metadata);
    persist(&session, &snapshot_path(&app)?)
}

#[tauri::command]
pub async fn campus_logout(app: tauri::AppHandle, state: tauri::State<'_, CampusState>) -> Result<(), String> {
    let mut session = state.0.lock().await;
    *session = CampusSession::default();
    vault::clear(&snapshot_path(&app)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use reqwest::cookie::CookieStore as _;

    #[test]
    fn restricts_urls_and_secret_header_injection() {
        assert!(allowed_campus_url(&url::Url::parse("https://learn.tsinghua.edu.cn/").unwrap()));
        for url in ["http://learn.tsinghua.edu.cn/", "https://tsinghua.edu.cn.evil.test/", "https://evil-tsinghua.edu.cn/", "https://user:pass@id.tsinghua.edu.cn/", "https://id.tsinghua.edu.cn:8443/"] {
            assert!(!allowed_campus_url(&url::Url::parse(url).unwrap()));
        }
        let headers = request_headers(HashMap::from([("Cookie".into(), "secret".into()), ("Authorization".into(), "secret".into())])).unwrap();
        assert!(headers.is_empty());
    }

    #[test]
    fn restores_session_cookies_without_cross_domain_leaks() {
        let url = url::Url::parse("https://id.tsinghua.edu.cn/").unwrap();
        let mut jar = CookieStore::default();
        jar.parse("JSESSIONID=fixture; Secure; HttpOnly; Path=/", &url).unwrap();
        let bytes = serde_json::to_vec(&jar.iter_unexpired().cloned().collect::<Vec<_>>()).unwrap();
        let cookies: Vec<cookie_store::Cookie<'static>> = serde_json::from_slice(&bytes).unwrap();
        let restored = CookieStoreMutex::new(CookieStore::from_cookies(cookies.into_iter().map(Ok::<_, String>), false).unwrap());
        assert_eq!(restored.cookies(&url).unwrap(), "JSESSIONID=fixture");
        assert!(restored.cookies(&url::Url::parse("https://learn.tsinghua.edu.cn/").unwrap()).is_none());
    }
}
