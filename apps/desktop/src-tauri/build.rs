use std::env;
use std::fs;
use std::path::PathBuf;

fn main() {
    // B-4 受控转发：把构建期 Backend 源交给 Rust allowlist 作为出厂默认。
    // 优先级：环境变量（tauri build 外层注入）> `apps/desktop/.env`（Vite 构建
    // 读取的同一文件）。两者都没有时 allowlist 仅含用户运行时添加的源。
    let build_time_origin = env::var("VITE_BACKEND_URL")
        .ok()
        .filter(|value| !value.trim().is_empty())
        .or_else(read_dotenv_backend_url);
    let escaped = build_time_origin
        .as_deref()
        .map(|value| format!("Some({:?})", value.trim_end_matches('/')))
        .unwrap_or_else(|| "None".to_string());
    let out_dir = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR is set by cargo"));
    fs::write(
        out_dir.join("backend_env.rs"),
        format!("pub const BUILD_TIME_BACKEND_ORIGIN: Option<&str> = {escaped};\n"),
    )
    .expect("writing backend_env.rs");
    println!("cargo:rerun-if-env-changed=VITE_BACKEND_URL");
    println!("cargo:rerun-if-changed=../.env");
    tauri_build::build()
}

fn read_dotenv_backend_url() -> Option<String> {
    let manifest = PathBuf::from(env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR is set"));
    let content = fs::read_to_string(manifest.join("../.env")).ok()?;
    content.lines().find_map(|line| {
        let trimmed = line.trim();
        trimmed
            .strip_prefix("VITE_BACKEND_URL=")
            .map(|value| value.trim().trim_matches(['"', '\'']).to_string())
            .filter(|value| !value.is_empty())
    })
}
