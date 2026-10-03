//! 课件转送（TASKS/m3-materials-upload-ui.md §3.2/§3.3）：learn 域下载 →
//! 临时文件 → 流式 multipart POST `/v1/files`。文件字节全程留在本进程
//! （Rust），不进 WebView；下载复用 campus cookie 会话（learn 文件 URL
//! 需要登录态），上传走 Backend 源 allowlist（B-4 语义）。
//!
//! 临时文件用 `tempfile::tempfile()`（仅句柄、无路径）：任何路径——包括
//! panic——句柄 drop 即删除（Windows 侧按句柄删除语义），满足「上传后
//! 临时目录无残留（含失败路径）」而不需要手工清理兜底。

use crate::backend_proxy::allowed_backend_url;
use crate::campus::allowed_campus_url;
use std::collections::BTreeSet;
use std::io::{Seek, SeekFrom, Write};
use std::time::Duration;

/// 单文件上限（课件 PDF/PPT 的量级；超出直接拒绝，不做断点续传）。
pub const MAX_MATERIAL_BYTES: u64 = 256 * 1024 * 1024;
/// 上传/下载的总时限：远大于 30s 常规请求（§5 实测：12MB loopback
/// <1s，真实网络按 256MB 上限给足 10 分钟）。
pub const TRANSFER_TIMEOUT: Duration = Duration::from_secs(600);

#[derive(serde::Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct MaterialTransferRequest {
    /// learn 文件下载 URL（会话态，来自当次列表响应；不落任何 Event/存储）。
    pub download_url: String,
    /// POST 目标完整 URL（`{backend}/v1/files`）；须经 B-4 源 allowlist。
    pub backend_url: String,
    /// Bearer JWT（WebView 已持有；与 backend_request 的头同信任域）。
    pub bearer_token: String,
    pub course_name: String,
    pub filename: String,
    /// 缺省时用下载响应的 Content-Type。
    pub content_type: Option<String>,
}

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct MaterialTransferResponse {
    pub status: u16,
    pub body: String,
}

/// §5.3 实测修正：`Body::from(File)` 默认 8KB 读块在 loopback 上只有
/// ~1.1MB/s（12MB ≈ 10.7s）；1MB BufReader + ReaderStream 后恢复线性
/// 吞吐。句柄仍由 Body 持有，请求结束即释放。
fn streaming_body(temp: std::fs::File, file_size: u64) -> (reqwest::Body, u64) {
    const CHUNK: usize = 1024 * 1024;
    let reader = tokio::io::BufReader::with_capacity(CHUNK, tokio::fs::File::from_std(temp));
    let stream = tokio_util::io::ReaderStream::with_capacity(reader, CHUNK);
    (reqwest::Body::wrap_stream(stream), file_size)
}

/// 校验并转送一个课件：下载到无名临时文件 → 流式 multipart 上传。
/// 出错时临时句柄随错误路径一起 drop（RAII 清理，无残留）。
pub async fn transfer_material(
    downloader: &reqwest::Client,
    uploader: &reqwest::Client,
    origins: &BTreeSet<String>,
    request: &MaterialTransferRequest,
) -> Result<MaterialTransferResponse, String> {
    let download_url =
        url::Url::parse(&request.download_url).map_err(|_| "Invalid campus download URL")?;
    if !allowed_campus_url(&download_url) {
        return Err("Campus URL is not allowed".into());
    }
    let backend_url = url::Url::parse(&request.backend_url).map_err(|_| "Invalid backend URL")?;
    if !allowed_backend_url(&backend_url, origins) {
        return Err("Backend 源不在允许列表内：请先在设置中添加（https，或本地 http）".into());
    }

    // ---- 1. 下载到无名临时文件（仅句柄；drop 即删，含所有失败路径） ----
    let mut temp = tempfile::tempfile().map_err(|_| "Temporary file unavailable")?;
    let download = downloader
        .get(download_url)
        .send()
        .await
        .map_err(|_| "Course file download failed")?;
    if !download.status().is_success() {
        return Err(format!(
            "Course file download failed: HTTP {}",
            download.status().as_u16()
        ));
    }
    let content_type = request.content_type.clone().or_else(|| {
        download
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned)
    });
    let mut response = download;
    let mut written: u64 = 0;
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| "Course file download failed")?
    {
        written += chunk.len() as u64;
        if written > MAX_MATERIAL_BYTES {
            return Err("Course file exceeds the 256MB transfer limit".into());
        }
        temp.write_all(&chunk)
            .map_err(|_| "Temporary file write failed")?;
    }

    // ---- 2. 句柄回卷后流式上传（读句柄交给 multipart，请求结束即释放） ----
    let file_size = written;
    temp.seek(SeekFrom::Start(0))
        .map_err(|_| "Temporary file seek failed")?;
    let mime = content_type
        .as_deref()
        .and_then(|raw| raw.split(';').next())
        .map(str::trim);
    let (body, file_size) = streaming_body(temp, file_size);
    let part = match mime {
        Some(mime) => reqwest::multipart::Part::stream_with_length(body, file_size)
            .file_name(request.filename.clone())
            .mime_str(mime)
            .map_err(|_| "Invalid course file content type")?,
        None => reqwest::multipart::Part::stream_with_length(body, file_size)
            .file_name(request.filename.clone()),
    };
    let form = reqwest::multipart::Form::new()
        .text("course_name", request.course_name.clone())
        .part("file", part);

    let upload = uploader
        .post(backend_url)
        .header(
            reqwest::header::AUTHORIZATION,
            format!("Bearer {}", request.bearer_token),
        )
        .multipart(form)
        .send()
        .await
        .map_err(|_| "Backend upload failed")?;
    let status = upload.status().as_u16();
    let mut body = Vec::new();
    let mut response = upload;
    while let Some(chunk) = response
        .chunk()
        .await
        .map_err(|_| "Backend upload failed")?
    {
        if body.len() + chunk.len() > 4 * 1024 * 1024 {
            return Err("Backend response is too large".into());
        }
        body.extend_from_slice(&chunk);
    }
    Ok(MaterialTransferResponse {
        status,
        body: String::from_utf8_lossy(&body).into_owned(),
    })
}

/// 单命令 = 下载 + 上传（中间不回 WebView）：临时句柄的生命周期完全
/// 封装在 `transfer_material` 内，RAII 清理覆盖所有失败路径。
#[tauri::command]
pub async fn material_upload(
    campus: tauri::State<'_, crate::campus::CampusState>,
    db: tauri::State<'_, crate::QueueDb>,
    proxy: tauri::State<'_, crate::backend_proxy::BackendProxy>,
    request: MaterialTransferRequest,
) -> Result<MaterialTransferResponse, String> {
    let downloader = campus.download_client().await?;
    let origins = crate::backend_proxy::effective_origins(&db)?;
    transfer_material(&downloader, proxy.uploader(), &origins, &request).await
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Read as _;
    use std::net::TcpListener;
    use std::time::Instant;

    /// §5.3 实测探针：>10MB 课件经 reqwest multipart（reader 流式，非
    /// bytes 整体载入）打到本地服务，全程无 IPC/无 WebView；同时验证
    /// Content-Length 已知（非 chunked）与总耗时量级。
    #[test]
    fn streams_a_12mb_multipart_upload_over_loopback() {
        let started = Instant::now();
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let port = listener.local_addr().unwrap().port();
        let server = std::thread::spawn(move || {
            use std::io::{Read as _, Write as _};
            let (mut stream, _) = listener.accept().unwrap();
            let mut buffer = [0u8; 262144];
            let mut head = Vec::new();
            loop {
                let read = stream.read(&mut buffer).unwrap();
                head.extend_from_slice(&buffer[..read]);
                if let Some(split) = find_head_end(&head) {
                    let (headers, _) = head.split_at(split);
                    let text = String::from_utf8_lossy(headers);
                    let content_length: usize = text
                        .lines()
                        .find_map(|line| {
                            let (name, value) = line.split_once(':')?;
                            name.trim()
                                .eq_ignore_ascii_case("content-length")
                                .then(|| value.trim().parse().ok())?
                        })
                        .unwrap();
                    let mut rest = head[split + 4..].to_vec();
                    while rest.len() < content_length {
                        let read = stream.read(&mut buffer).unwrap();
                        if read == 0 {
                            break;
                        }
                        rest.extend_from_slice(&buffer[..read]);
                    }
                    let body = rest;
                    let response = format!(
                        "HTTP/1.1 201 Created\r\nContent-Type: application/json\r\nContent-Length: 2\r\n\r\n{{}}"
                    );
                    stream.write_all(response.as_bytes()).unwrap();
                    return (text.to_string(), body);
                }
                if read == 0 {
                    panic!("client closed before sending headers");
                }
            }
        });

        // 12MB 已知模式 → 无名临时文件 → seek(0) → 流式 part
        let payload_size = 12 * 1024 * 1024 + 3;
        let mut temp = tempfile::tempfile().unwrap();
        let pattern = b"agenthu-probe-";
        let mut written = 0u64;
        while written < payload_size as u64 {
            let chunk = &pattern[..((payload_size as u64 - written).min(pattern.len() as u64)
                as usize)
                .min(pattern.len())];
            temp.write_all(chunk).unwrap();
            written += chunk.len() as u64;
        }
        temp.seek(SeekFrom::Start(0)).unwrap();

        let runtime = tokio::runtime::Builder::new_current_thread()
            .enable_all()
            .build()
            .unwrap();
        let response = runtime.block_on(async {
            let client = reqwest::Client::builder()
                .redirect(reqwest::redirect::Policy::none())
                .timeout(TRANSFER_TIMEOUT)
                .build()
                .unwrap();
            let form = reqwest::multipart::Form::new()
                .text("course_name", "信号与系统".to_string())
                .part(
                    "file",
                    reqwest::multipart::Part::stream_with_length(
                        streaming_body(temp, payload_size as u64).0,
                        payload_size as u64,
                    )
                    .file_name("probe.pdf")
                    .mime_str("application/pdf")
                    .unwrap(),
                );
            client
                .post(format!("http://127.0.0.1:{port}/v1/files"))
                .multipart(form)
                .send()
                .await
                .unwrap()
        });

        assert_eq!(response.status().as_u16(), 201);
        let (headers, body) = server.join().unwrap();
        // 表单域与文件名在 multipart 头里可见（course_name 随表单走）
        assert!(headers.contains("POST /v1/files"));
        assert!(body.windows(pattern.len()).any(|w| w == pattern));
        assert!(String::from_utf8_lossy(&body).contains("course_name"));
        assert!(String::from_utf8_lossy(&body).contains("probe.pdf"));
        // 已知长度（非 chunked）：服务端读到完整 body
        let declared: usize = headers
            .lines()
            .find_map(|line| {
                let (name, value) = line.split_once(':')?;
                name.trim()
                    .eq_ignore_ascii_case("content-length")
                    .then(|| value.trim().parse().ok())?
            })
            .unwrap();
        assert_eq!(body.len(), declared);
        // §5.3 结论数据：loopback 12MB 的量级（真实网络另计，用于定 600s 上限）
        println!(
            "12MB loopback multipart upload took {:?}",
            started.elapsed()
        );
        assert!(started.elapsed() < Duration::from_secs(30));
    }

    /// §5.2 实测探针：Windows 下句柄曾用于写+读流之后，drop 仍能删除
    /// （tempfile 的按句柄删除语义）；NamedTempFile 变体验证路径消失。
    #[test]
    fn windows_handle_used_for_write_then_read_still_deletes_on_drop() {
        let named = tempfile::NamedTempFile::new().unwrap();
        let path = named.path().to_path_buf();
        {
            let mut handle = named.reopen().unwrap();
            handle.write_all(b"probe").unwrap();
            handle.seek(SeekFrom::Start(0)).unwrap();
            let mut sink = Vec::new();
            handle.read_to_end(&mut sink).unwrap();
            assert_eq!(sink, b"probe");
        }
        drop(named);
        assert!(!path.exists(), "temp file must be gone after drop");
    }

    fn find_head_end(buffer: &[u8]) -> Option<usize> {
        buffer.windows(4).position(|w| w == b"\r\n\r\n")
    }
}
