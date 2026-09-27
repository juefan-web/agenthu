use crate::vault;
use cookie_store::CookieStore;
use reqwest::header::{HeaderMap, HeaderName, HeaderValue};
use reqwest_cookie_store::CookieStoreMutex;
use serde::{Deserialize, Serialize};
use std::{collections::HashMap, path::PathBuf, sync::Arc, time::Duration};
use tauri::Manager;
use tokio::sync::Mutex;
use zeroize::Zeroizing;

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

struct CampusClients {
    follow: reqwest::Client,
    manual: reqwest::Client,
}

impl CampusClients {
    fn new(jar: Arc<CookieStoreMutex>) -> Result<Self, String> {
        let follow = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::custom(|attempt| {
                if attempt.previous().len() >= 10 || !allowed_campus_url(attempt.url()) {
                    attempt.error("Campus redirect rejected")
                } else {
                    attempt.follow()
                }
            }))
            .cookie_provider(Arc::clone(&jar))
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|_| "Campus transport unavailable")?;
        let manual = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .cookie_provider(jar)
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|_| "Campus transport unavailable")?;
        Ok(Self { follow, manual })
    }
}

#[derive(Default)]
struct CampusSession {
    jar: Arc<CookieStoreMutex>,
    metadata: Option<SessionMetadata>,
    clients: Option<CampusClients>,
    persisted_snapshot: Option<Zeroizing<Vec<u8>>>,
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

fn snapshot_payload(session: &CampusSession) -> Result<Option<Vec<u8>>, String> {
    if let Some(metadata) = &session.metadata {
        let cookies = session.jar.lock().map_err(|_| STORAGE_ERROR)?
            .iter_unexpired().cloned().collect();
        let payload = serde_json::to_vec(&Snapshot { version: 1, metadata: metadata.clone(), cookies })
            .map_err(|_| STORAGE_ERROR)?;
        return Ok(Some(payload));
    }
    Ok(None)
}

fn snapshot_changed(session: &CampusSession, payload: &[u8]) -> bool {
    !session.persisted_snapshot.as_deref().is_some_and(|saved| saved.as_slice() == payload)
}

fn persist(session: &mut CampusSession, path: &std::path::Path) -> Result<(), String> {
    let Some(payload) = snapshot_payload(session)? else { return Ok(()); };
    if !snapshot_changed(session, &payload) {
        return Ok(());
    }
    vault::write(path, payload.clone())?;
    session.persisted_snapshot = Some(Zeroizing::new(payload));
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
pub async fn campus_request(state: tauri::State<'_, CampusState>, request: CampusRequest) -> Result<CampusResponse, String> {
    let url = url::Url::parse(&request.url).map_err(|_| "Invalid campus URL")?;
    if !allowed_campus_url(&url) { return Err("Campus URL is not allowed".into()); }
    if !matches!(request.method.as_str(), "GET" | "POST" | "HEAD") {
        return Err("Campus method is not allowed".into());
    }
    if request.body.as_ref().is_some_and(|b| b.len() > 1024 * 1024) {
        return Err("Campus request is too large".into());
    }
    let manual_redirect = match request.redirect.as_deref() {
        Some("manual") => true,
        Some("follow") | None => false,
        _ => return Err("Unsupported redirect policy".into()),
    };
    let client = {
        let mut session = state.0.lock().await;
        let jar = Arc::clone(&session.jar);
        if session.clients.is_none() {
            session.clients = Some(CampusClients::new(Arc::clone(&jar))?);
        }
        let clients = session.clients.as_ref().expect("campus clients initialized");
        let client = if manual_redirect { &clients.manual } else { &clients.follow };
        client.clone()
    };
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
        session.clients = None;
        session.persisted_snapshot = Some(Zeroizing::new(payload));
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
    persist(&mut session, &snapshot_path(&app)?)
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

    #[test]
    fn only_changed_cookies_need_a_new_encrypted_snapshot() {
        let url = url::Url::parse("https://id.tsinghua.edu.cn/").unwrap();
        let mut session = CampusSession {
            metadata: Some(SessionMetadata {
                username: "fixture".into(), fingerprint: "fingerprint".into(), finger3: String::new(),
            }),
            ..CampusSession::default()
        };
        let initial = snapshot_payload(&session).unwrap().unwrap();
        assert!(snapshot_changed(&session, &initial));
        session.persisted_snapshot = Some(Zeroizing::new(initial.clone()));
        assert!(!snapshot_changed(&session, &initial));

        session.jar.lock().unwrap().parse("JSESSIONID=changed; Secure; Path=/", &url).unwrap();
        let changed = snapshot_payload(&session).unwrap().unwrap();
        assert!(snapshot_changed(&session, &changed));
    }
}
