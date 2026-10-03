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

/// 校园重定向策略：allowlist 内才跟随（follow 与 download 客户端共用）。
fn campus_redirect_policy() -> reqwest::redirect::Policy {
    reqwest::redirect::Policy::custom(|attempt| {
        if attempt.previous().len() >= 10 || !allowed_campus_url(attempt.url()) {
            attempt.error("Campus redirect rejected")
        } else {
            attempt.follow()
        }
    })
}

struct CampusClients {
    follow: reqwest::Client,
    manual: reqwest::Client,
    /// 课件下载（material_transfer）：大文件不给总时限（只留连接时限），
    /// 重定向同一 allowlist 策略，同一 cookie jar（learn 下载需登录态）。
    download: reqwest::Client,
}

impl CampusClients {
    fn new(jar: Arc<CookieStoreMutex>) -> Result<Self, String> {
        let follow = reqwest::Client::builder()
            .redirect(campus_redirect_policy())
            .cookie_provider(Arc::clone(&jar))
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|_| "Campus transport unavailable")?;
        let manual = reqwest::Client::builder()
            .redirect(reqwest::redirect::Policy::none())
            .cookie_provider(Arc::clone(&jar))
            .timeout(Duration::from_secs(30))
            .build()
            .map_err(|_| "Campus transport unavailable")?;
        let download = reqwest::Client::builder()
            .redirect(campus_redirect_policy())
            .cookie_provider(jar)
            .connect_timeout(Duration::from_secs(15))
            // 无总时限（大文件 + 慢网络）但必须有读超时：否则一条僵死
            // 连接（对端停止发送且不断开）会让课件下载无限挂起（#46 评审
            // 观察；30s 无任何字节进展即中止，慢而流动的传输不受影响）。
            .read_timeout(Duration::from_secs(30))
            .build()
            .map_err(|_| "Campus transport unavailable")?;
        Ok(Self { follow, manual, download })
    }

    pub fn downloader(&self) -> &reqwest::Client {
        &self.download
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

impl CampusState {
    /// 课件下载客户端（material_transfer）：与 campus_request 同一把锁内
    /// 惰性初始化；clone 的 Client 共享同一 cookie jar。
    pub async fn download_client(&self) -> Result<reqwest::Client, String> {
        let mut session = self.0.lock().await;
        if session.clients.is_none() {
            let jar = Arc::clone(&session.jar);
            session.clients = Some(CampusClients::new(jar)?);
        }
        Ok(session.clients.as_ref().expect("campus clients initialized").downloader().clone())
    }
}

pub fn allowed_campus_url(url: &url::Url) -> bool {
    let host = url.host_str().unwrap_or("");
    if url.username().is_empty() && url.password().is_none() {
        // 教务网关只监听 80：vendor 实测 webvpn 包装 zhjw 撞引导壳（教务 host
        // 的 wengine 票从未建立，http.ts PUBLIC_DIRECT_HOSTS 注释），上游
        // 2026-09-19 起教务访问统一直连——单 host 精确窄口，不做子域通配、
        // 不放开其他 http host；重定向策略复用本函数自然继承。
        if url.scheme() == "http"
            && url.port_or_known_default() == Some(80)
            && host == "zhjw.cic.tsinghua.edu.cn"
        {
            return true;
        }
        if url.scheme() == "https"
            && url.port_or_known_default() == Some(443)
            && (host == "tsinghua.edu.cn" || host.ends_with(".tsinghua.edu.cn"))
        {
            return true;
        }
    }
    false
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
    /// Read-only cookie mirror for the TS adapter layer: name/value/host
    /// triples for the touched campus hosts only. The native store stays
    /// authoritative; raw Set-Cookie lines and other attributes never cross
    /// the IPC boundary (privacy boundary change, see CURRENT_STATE.md).
    cookies: Vec<MirroredCookie>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
struct MirroredCookie {
    host: String,
    name: String,
    value: String,
    host_only: bool,
}

/// 投影受影响 URL 的 cookie（仅 *.tsinghua.edu.cn；匹配用 crate 自带的
/// RFC 6265 语义，域属性缺省 = host-only，带 Domain 的取其去点形式并标记
/// host_only=false 以保留子域匹配）。
fn mirror_cookies(store: &CookieStore, urls: &[&url::Url]) -> Vec<MirroredCookie> {
    store.iter_unexpired().filter_map(|cookie| {
        let matched = urls.iter().find(|url| cookie.matches(url))?;
        // cookie_store 约定：domain() 为 Some（去点形式）= 显式 Domain 属性
        // （子域可匹配）；None = host-only，归属到命中 URL 的 host。
        let (host, host_only) = match cookie.domain() {
            Some(domain) if !domain.is_empty() => (domain.trim_start_matches('.').to_lowercase(), false),
            _ => (matched.host_str().unwrap_or("").to_lowercase(), true),
        };
        let is_campus = host == "tsinghua.edu.cn" || host.ends_with(".tsinghua.edu.cn");
        if !is_campus {
            return None;
        }
        Some(MirroredCookie {
            host,
            name: cookie.name().to_string(),
            value: cookie.value().to_string(),
            host_only,
        })
    }).collect()
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
pub async fn campus_request(app: tauri::AppHandle, state: tauri::State<'_, CampusState>, request: CampusRequest) -> Result<CampusResponse, String> {
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
    let request_url = url.clone();
    let mut builder = client.request(method, url).headers(request_headers(request.headers)?);
    if let Some(body) = request.body { builder = builder.body(body); }
    let mut response = builder.send().await.map_err(|_| "Campus network request failed")?;
    let status = response.status().as_u16();
    let final_url = response.url().to_string();
    let final_url_obj = response.url().clone();
    let headers = response.headers().iter()
        .filter(|(name, _)| matches!(name.as_str(), "content-type" | "location"))
        .filter_map(|(name, value)| value.to_str().ok().map(|v| (name.to_string(), v.to_owned())))
        .collect();
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| "Campus response failed")? {
        if body.len() + chunk.len() > 16 * 1024 * 1024 { return Err("Campus response is too large".into()); }
        body.extend_from_slice(&chunk);
    }
    // Persist refreshed cookies after the response has updated the shared jar.
    // `persist` skips the encrypted write when the snapshot is unchanged.
    let mut session = state.0.lock().await;
    persist(&mut session, &snapshot_path(&app)?)?;
    let cookies = mirror_cookies(
        &*session.jar.lock().map_err(|_| STORAGE_ERROR)?,
        &[&request_url, &final_url_obj],
    );
    Ok(CampusResponse { status, headers, body: String::from_utf8_lossy(&body).into_owned(), final_url, cookies })
}

/// 解析快照载荷：版本不兼容或载荷损坏返回 None（调用方据此自清理）。
fn parse_snapshot(payload: &[u8]) -> Option<Snapshot> {
    let snapshot: Snapshot = serde_json::from_slice(payload).ok()?;
    (snapshot.version == 1).then_some(snapshot)
}

#[tauri::command]
pub async fn campus_restore(app: tauri::AppHandle, state: tauri::State<'_, CampusState>) -> Result<Option<SessionMetadata>, String> {
    let mut session = state.0.lock().await;
    if let Some(payload) = vault::read(&snapshot_path(&app)?)? {
        match parse_snapshot(&payload) {
            Some(snapshot) => {
                let store = CookieStore::from_cookies(snapshot.cookies.into_iter().map(Ok::<_, String>), false)?;
                session.jar = Arc::new(CookieStoreMutex::new(store));
                session.metadata = Some(snapshot.metadata);
                session.clients = None;
                session.persisted_snapshot = Some(Zeroizing::new(payload));
            }
            None => {
                // 版本不兼容/损坏的快照自清理（B-3.1）：留着只会让每次启动都在
                // 同一处失败，用户无从得知需要重新登录。清理后返回 None——网关
                // 视为无会话（idle），UI 落回登录表单即为明确引导。
                eprintln!("agenthu: clearing unreadable or unsupported campus snapshot");
                vault::clear(&snapshot_path(&app)?)?;
            }
        }
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
        // 教务网关单 host 窄口：http:80 仅放行精确 host
        assert!(allowed_campus_url(&url::Url::parse("http://zhjw.cic.tsinghua.edu.cn/jxmh_out.do?m=bks_jxrl").unwrap()));
        for url in [
            "http://learn.tsinghua.edu.cn/",
            "https://tsinghua.edu.cn.evil.test/",
            "https://evil-tsinghua.edu.cn/",
            "https://user:pass@id.tsinghua.edu.cn/",
            "https://id.tsinghua.edu.cn:8443/",
            // 其他 http host、zhjw 的其他端口、http 的子域伪造一律拒绝
            "http://id.tsinghua.edu.cn/",
            "http://zhjw.cic.tsinghua.edu.cn:8080/",
            "http://x.zhjw.cic.tsinghua.edu.cn/",
            "http://zhjw.cic.tsinghua.edu.cn.evil.test/",
        ] {
            assert!(!allowed_campus_url(&url::Url::parse(url).unwrap()), "{url} should be rejected");
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

    #[test]
    fn parses_only_supported_snapshot_versions() {
        let url = url::Url::parse("https://id.tsinghua.edu.cn/").unwrap();
        let mut store = CookieStore::default();
        store.parse("JSESSIONID=fixture; Path=/", &url).unwrap();
        let payload = serde_json::to_vec(&Snapshot {
            version: 1,
            metadata: SessionMetadata { username: "fixture".into(), fingerprint: "fp".into(), finger3: String::new() },
            cookies: store.iter_unexpired().cloned().collect(),
        }).unwrap();
        assert!(parse_snapshot(&payload).is_some());
        // 未来版本：不兼容但可识别 → 调用方自清理
        let future = serde_json::to_vec(&serde_json::json!({ "version": 2, "metadata": {}, "cookies": [] })).unwrap();
        assert!(parse_snapshot(&future).is_none());
        // 损坏载荷 → 同样自清理
        assert!(parse_snapshot(b"{ not json").is_none());
        assert!(parse_snapshot(b"").is_none());
    }

    #[test]
    fn mirrors_only_touched_campus_hosts_as_name_value_pairs() {
        let webvpn = url::Url::parse("https://webvpn.tsinghua.edu.cn/").unwrap();
        let learn = url::Url::parse("https://learn.tsinghua.edu.cn/").unwrap();
        let mut store = CookieStore::default();
        store.parse("XSRF-TOKEN=fixture-token; Path=/", &webvpn).unwrap();
        store.parse("JSESSIONID=learn-session; Path=/", &learn).unwrap();

        let mirrored = mirror_cookies(&store, &[&webvpn]);
        assert_eq!(mirrored.len(), 1);
        assert_eq!(mirrored[0].host, "webvpn.tsinghua.edu.cn");
        assert_eq!(mirrored[0].name, "XSRF-TOKEN");
        assert_eq!(mirrored[0].value, "fixture-token");
        assert!(mirrored[0].host_only);

        // domain cookie（Domain 属性）投影去点、host_only=false，URL 匹配交给 crate
        store.parse("wide=fanout; Domain=.tsinghua.edu.cn; Path=/", &webvpn).unwrap();
        let with_domain = mirror_cookies(&store, &[&webvpn]);
        let wide = with_domain.iter().find(|c| c.name == "wide").expect("domain cookie mirrored");
        assert_eq!(wide.host, "tsinghua.edu.cn");
        assert!(!wide.host_only);

        // 未触及的校园 host 不投影
        assert!(!with_domain.iter().any(|c| c.name == "JSESSIONID"));
    }
}
