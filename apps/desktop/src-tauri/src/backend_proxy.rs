use crate::QueueDb;
use serde::{Deserialize, Serialize};
use std::collections::BTreeSet;
use tauri::State;

include!(concat!(env!("OUT_DIR"), "/backend_env.rs"));

const BACKEND_TRANSPORT_ERROR: &str = "Backend transport unavailable";
const MAX_BACKEND_BODY_BYTES: usize = 1024 * 1024;
const MAX_BACKEND_RESPONSE_BYTES: usize = 4 * 1024 * 1024;

/// B-4 受控转发（A 拍板，2026-09-29）：Backend 流量一律经本命令转发，WebView
/// 的 CSP 无任何直连出口；allowlist 的唯一事实源在 Rust 侧 = 构建期
/// `VITE_BACKEND_URL`（build.rs 注入）+ 用户显式添加并持久化的源。
#[derive(Default)]
pub struct BackendProxy {
    client: once_cell_proxy::Client,
    /// 课件上传专用长时限客户端（material_transfer：>10MB multipart 的
    /// 总时限 600s，30s 会掐断真实课件上传）。
    upload_client: once_cell_proxy::Client<true>,
}

impl BackendProxy {
    /// 语义与其余 Backend 流量一致：无 cookie、不跟随重定向、同一
    /// allowlist 谓词（在 material_transfer 内校验）。
    pub fn uploader(&self) -> &reqwest::Client {
        self.upload_client.get()
    }
}

/// 延迟构建的 reqwest Client（无 cookie、不跟随重定向——Authorization 永不
/// 跨源泄露）。手写 once_cell 语义避免新增依赖。
mod once_cell_proxy {
    use std::sync::OnceLock;

    pub struct Client<const LONG: bool = false>(OnceLock<reqwest::Client>);

    impl<const LONG: bool> Client<LONG> {
        pub fn new() -> Self {
            Self(OnceLock::new())
        }
        pub fn get(&self) -> &reqwest::Client {
            self.0.get_or_init(|| {
                let timeout = if LONG {
                    std::time::Duration::from_secs(600)
                } else {
                    std::time::Duration::from_secs(30)
                };
                reqwest::Client::builder()
                    .redirect(reqwest::redirect::Policy::none())
                    .timeout(timeout)
                    .build()
                    .expect("backend client builds")
            })
        }
    }

    impl<const LONG: bool> Default for Client<LONG> {
        fn default() -> Self {
            Self::new()
        }
    }
}

#[derive(Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct BackendRequest {
    url: String,
    method: String,
    headers: std::collections::HashMap<String, String>,
    body: Option<String>,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct BackendResponse {
    status: u16,
    headers: std::collections::HashMap<String, String>,
    body: String,
}

/// 规范化源串（`scheme://host[:port]`，默认端口省略——与 `url::Origin` 一致）。
pub fn normalize_origin(url: &url::Url) -> Option<String> {
    if url.username().is_empty() && url.password().is_none() {
        return Some(url.origin().ascii_serialization());
    }
    None
}

fn is_loopback(host: &str) -> bool {
    host == "localhost" || host == "127.0.0.1" || host == "[::1]" || host == "::1"
}

/// 本地明文例外（拍板第 4 点）：loopback host 允许 http（开发/自托管），
/// 非本地源必须 https。
pub fn origin_scheme_allowed(url: &url::Url) -> bool {
    let host = url.host_str().unwrap_or("");
    match url.scheme() {
        "https" => true,
        "http" => is_loopback(host),
        _ => false,
    }
}

/// 用户输入的源是否可入 allowlist：可解析、无凭据、https 或 loopback http。
pub fn acceptable_added_origin(raw: &str) -> Result<String, String> {
    let trimmed = raw.trim().trim_end_matches('/');
    let parsed = url::Url::parse(trimmed).map_err(|_| "Backend 源必须是合法 URL（如 https://api.example.com）".to_string())?;
    if !origin_scheme_allowed(&parsed) {
        return Err("非本地 Backend 源必须使用 https；http 仅允许 127.0.0.1/localhost".into());
    }
    normalize_origin(&parsed).ok_or_else(|| "Backend 源不得携带凭据".to_string())
}

/// 出厂默认（构建期）+ 用户持久化源的并集。
pub(crate) fn effective_origins(db: &QueueDb) -> Result<BTreeSet<String>, String> {
    let mut origins = BTreeSet::new();
    if let Some(build_time) = BUILD_TIME_BACKEND_ORIGIN {
        origins.insert(build_time.to_string());
    }
    for origin in db.with(|store| store.backend_origins())? {
        origins.insert(origin);
    }
    Ok(origins)
}

/// 转发谓词：无凭据 + 源在 allowlist + https/loopback-http。
pub fn allowed_backend_url(url: &url::Url, origins: &BTreeSet<String>) -> bool {
    let Some(origin) = normalize_origin(url) else { return false };
    origin_scheme_allowed(url) && origins.contains(&origin)
}

/// 请求头白名单：Authorization/Content-Type/Accept——沿用 campus 侧的
/// 敏感头剥离语义（Cookie 等一律不透传；Backend 会话是 Bearer JWT）。
fn forward_headers(values: std::collections::HashMap<String, String>) -> reqwest::header::HeaderMap {
    let mut headers = reqwest::header::HeaderMap::new();
    for (name, value) in values {
        if !matches!(name.to_ascii_lowercase().as_str(), "authorization" | "content-type" | "accept") {
            continue;
        }
        if let (Ok(name), Ok(value)) = (
            reqwest::header::HeaderName::try_from(name.as_str()),
            reqwest::header::HeaderValue::try_from(value.as_str()),
        ) {
            headers.insert(name, value);
        }
    }
    headers
}

/// 响应头白名单：正文类型、限流提示与 D-029 分页游标（tasks 列表经
/// `X-Next-Cursor` 携带下一页；缺省头 = 末页）；Set-Cookie 一律不进 WebView。
fn response_headers(response: &reqwest::Response) -> std::collections::HashMap<String, String> {
    response.headers().iter()
        .filter(|(name, _)| matches!(name.as_str(), "content-type" | "retry-after" | "location" | "x-next-cursor"))
        .filter_map(|(name, value)| value.to_str().ok().map(|v| (name.to_string(), v.to_owned())))
        .collect()
}

#[tauri::command]
pub fn backend_origin_list(db: State<'_, QueueDb>) -> Result<Vec<String>, String> {
    Ok(effective_origins(&db)?.into_iter().collect())
}

#[tauri::command]
pub fn backend_origin_add(db: State<'_, QueueDb>, origin: String) -> Result<(), String> {
    let normalized = acceptable_added_origin(&origin)?;
    db.with(|store| store.backend_origin_add(&normalized))
}

#[tauri::command]
pub fn backend_origin_remove(db: State<'_, QueueDb>, origin: String) -> Result<(), String> {
    // 构建期默认源不可移除（只删用户持久化项）
    db.with(|store| store.backend_origin_remove(origin.trim().trim_end_matches('/')))
}

#[tauri::command]
pub async fn backend_request(
    db: State<'_, QueueDb>,
    proxy: State<'_, BackendProxy>,
    request: BackendRequest,
) -> Result<BackendResponse, String> {
    let url = url::Url::parse(&request.url).map_err(|_| "Invalid backend URL".to_string())?;
    let origins = effective_origins(&db)?;
    if !allowed_backend_url(&url, &origins) {
        return Err("Backend 源不在允许列表内：请先在设置中添加（https，或本地 http）".into());
    }
    if !matches!(request.method.as_str(), "GET" | "POST" | "PUT" | "PATCH" | "DELETE" | "HEAD") {
        return Err("Backend method is not allowed".into());
    }
    if request.body.as_ref().is_some_and(|body| body.len() > MAX_BACKEND_BODY_BYTES) {
        return Err("Backend request is too large".into());
    }
    let method = reqwest::Method::from_bytes(request.method.as_bytes())
        .map_err(|_| "Invalid backend method".to_string())?;
    let mut builder = proxy.client.get().request(method, url).headers(forward_headers(request.headers));
    if let Some(body) = request.body {
        builder = builder.body(body);
    }
    let mut response = builder.send().await.map_err(|_| BACKEND_TRANSPORT_ERROR.to_string())?;
    let headers = response_headers(&response);
    let mut body = Vec::new();
    while let Some(chunk) = response.chunk().await.map_err(|_| BACKEND_TRANSPORT_ERROR.to_string())? {
        if body.len() + chunk.len() > MAX_BACKEND_RESPONSE_BYTES {
            return Err("Backend response is too large".into());
        }
        body.extend_from_slice(&chunk);
    }
    Ok(BackendResponse {
        status: response.status().as_u16(),
        headers,
        body: String::from_utf8_lossy(&body).into_owned(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn origins(list: &[&str]) -> BTreeSet<String> {
        list.iter().map(|item| item.to_string()).collect()
    }

    #[test]
    fn allowlist_predicate_accepts_only_listed_and_scheme_valid_origins() {
        let allowed = origins(&["https://api.agenthu.dev", "http://127.0.0.1:8000"]);
        assert!(allowed_backend_url(&url::Url::parse("https://api.agenthu.dev/v1/tasks").unwrap(), &allowed));
        assert!(allowed_backend_url(&url::Url::parse("http://127.0.0.1:8000/v1/auth/login").unwrap(), &allowed));
        // 未列出的源（即便 https）、明文非本地、凭据注入一律拒绝
        assert!(!allowed_backend_url(&url::Url::parse("https://evil.example.com/v1").unwrap(), &allowed));
        assert!(!allowed_backend_url(&url::Url::parse("http://api.agenthu.dev/v1").unwrap(), &allowed));
        assert!(!allowed_backend_url(&url::Url::parse("https://user:pass@api.agenthu.dev/v1").unwrap(), &allowed));
        // 默认端口归一化：https 443 与无端口同源
        assert!(allowed_backend_url(&url::Url::parse("https://api.agenthu.dev:443/v1").unwrap(), &allowed));
    }

    #[test]
    fn added_origins_must_be_https_or_loopback_http() {
        assert_eq!(acceptable_added_origin("https://api.example.com/").unwrap(), "https://api.example.com");
        assert_eq!(acceptable_added_origin("http://localhost:9000").unwrap(), "http://localhost:9000");
        for rejected in ["http://api.example.com", "ftp://api.example.com", "not a url", "https://u:p@x.example.com"] {
            assert!(acceptable_added_origin(rejected).is_err(), "{rejected} should be rejected");
        }
    }

    #[test]
    fn response_headers_pass_the_keyset_cursor_but_never_cookies() {
        // D-029：tasks 列表经 X-Next-Cursor 携带下一页（缺省 = 末页），
        // 打包客户端的 IPC 代理必须透传；Set-Cookie 仍然一律拦截。
        let mut inner = http::Response::builder().status(200).body(Vec::new()).unwrap();
        inner.headers_mut().insert("X-Next-Cursor", "Y3Vyc29y".parse().unwrap());
        inner.headers_mut().insert("Set-Cookie", "session=secret".parse().unwrap());
        inner.headers_mut().insert("X-Dropped", "noise".parse().unwrap());
        let response = reqwest::Response::from(inner);
        let headers = response_headers(&response);
        assert_eq!(headers.get("x-next-cursor").map(String::as_str), Some("Y3Vyc29y"));
        assert!(!headers.contains_key("set-cookie"));
        assert!(!headers.contains_key("x-dropped"));
    }

    #[test]
    fn forward_headers_whitelist_and_response_header_filter() {
        let headers = forward_headers(std::collections::HashMap::from([
            ("Authorization".into(), "Bearer x".into()),
            ("Content-Type".into(), "application/json".into()),
            ("Cookie".into(), "secret".into()),
            ("X-Custom".into(), "anything".into()),
        ]));
        assert_eq!(headers.len(), 2);
        assert!(headers.contains_key("authorization"));
        assert!(!headers.contains_key("cookie"));
    }

    #[test]
    fn persisted_user_origins_join_and_leave_the_allowlist() {
        let dir = tempfile::tempdir().unwrap();
        let db = QueueDb::new(dir.path().join("offline.sqlite3"));
        db.with(|store| store.backend_origin_add("http://localhost:9000")).unwrap();
        assert!(effective_origins(&db).unwrap().contains("http://localhost:9000"));
        // 幂等：重复添加不产生重复项
        db.with(|store| store.backend_origin_add("http://localhost:9000")).unwrap();
        assert_eq!(effective_origins(&db).unwrap().iter().filter(|o| **o == "http://localhost:9000").count(), 1);
        db.with(|store| store.backend_origin_remove("http://localhost:9000")).unwrap();
        assert!(!effective_origins(&db).unwrap().contains("http://localhost:9000"));
    }
}
