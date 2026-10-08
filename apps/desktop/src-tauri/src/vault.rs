use std::{path::Path, sync::Once};
use tauri_plugin_stronghold::stronghold::Stronghold;

const CAMPUS_CLIENT: &[u8] = b"agenthu-campus-v1";
const CAMPUS_RECORD: &[u8] = b"session";
const BACKEND_CLIENT: &[u8] = b"agenthu-backend-v1";
const BACKEND_RECORD: &[u8] = b"token";
const VAULT_ERROR: &str = "Secure session storage is unavailable";
static CONFIGURE_WORK_FACTOR: Once = Once::new();

fn configure_work_factor() {
    // Vault keys are generated randomly and stored in Windows Credential Manager,
    // rather than derived from a user password. Password-hardening work factors add
    // minutes of CPU time to every Stronghold snapshot without improving this key's
    // security. Existing snapshots retain and use their embedded work factor.
    CONFIGURE_WORK_FACTOR.call_once(|| {
        let _ = engine::snapshot::try_set_encrypt_work_factor(0);
    });
}

fn credential_name(slot: &str) -> String {
    format!("{slot}-vault-v1")
}

// Windows Credential Manager 在共享机器（CI runner）上会出现瞬时故障
// （实测：写入成功后紧接的读取偶发失败，同 SHA 双跑一绿一红）。有界重试
// 只覆盖瞬时类错误；NoEntry 等确定性结果直通，避免把"确实没有"重试成
// "可能有"。
#[cfg(windows)]
const KEYRING_ATTEMPTS: usize = 3;
#[cfg(windows)]
const KEYRING_RETRY_DELAY_MS: u64 = 150;

#[cfg(windows)]
fn keyring_transient(err: &keyring::Error) -> bool {
    matches!(err, keyring::Error::NoStorageAccess(_) | keyring::Error::PlatformFailure(_))
}

#[cfg(windows)]
fn with_keyring_retry<T>(mut op: impl FnMut() -> Result<T, keyring::Error>) -> Result<T, keyring::Error> {
    for attempt in 1..=KEYRING_ATTEMPTS {
        match op() {
            Ok(value) => return Ok(value),
            Err(err) if attempt < KEYRING_ATTEMPTS && keyring_transient(&err) => {
                std::thread::sleep(std::time::Duration::from_millis(KEYRING_RETRY_DELAY_MS));
            }
            Err(err) => return Err(err),
        }
    }
    unreachable!("retry loop returns on the final attempt");
}

// 保留底层错误便于诊断：CI 日志里 unwrap 只能看到泛化串时无从定位。
// 错误文本最多携带凭据 target 名，与本地回执文件名同敏感级，不含密钥本体。
#[cfg(windows)]
fn vault_unavailable(step: &str, err: &keyring::Error) -> String {
    format!("{VAULT_ERROR}: {step} ({err})")
}

#[cfg(windows)]
fn key(slot: &str, create: bool) -> Result<Vec<u8>, String> {
    use rand::RngCore;
    let entry = keyring::Entry::new("dev.agenthu.desktop", &credential_name(slot))
        .map_err(|err| vault_unavailable("open credential", &err))?;
    match with_keyring_retry(|| entry.get_secret()) {
        Ok(key) if key.len() == 32 => return Ok(key),
        // 持久化出的错误长度是损坏态，重试无意义
        Ok(key) => return Err(format!("{VAULT_ERROR}: stored key has {} bytes, expected 32", key.len())),
        Err(keyring::Error::NoEntry) if create => {}
        Err(keyring::Error::NoEntry) => return Err(String::from(VAULT_ERROR) + ": no stored key"),
        Err(err) => return Err(vault_unavailable("read key", &err)),
    }
    let mut key = zeroize::Zeroizing::new(vec![0u8; 32]);
    rand::rngs::OsRng.fill_bytes(&mut key);
    // 密钥只生成一次：重试始终写同一密钥，不留半写状态
    with_keyring_retry(|| entry.set_secret(&key))
        .map_err(|err| vault_unavailable("write key", &err))?;
    Ok(key.to_vec())
}

#[cfg(not(windows))]
fn key(_slot: &str, _create: bool) -> Result<Vec<u8>, String> {
    Err("Secure session storage is currently supported on Windows only".into())
}

fn read_record(path: &Path, slot: &str, client_id: &[u8], record: &[u8]) -> Result<Option<Vec<u8>>, String> {
    configure_work_factor();
    if !path.exists() { return Ok(None); }
    let vault = Stronghold::new(path, key(slot, false)?).map_err(|_| VAULT_ERROR)?;
    let client = vault.load_client(client_id).map_err(|_| VAULT_ERROR)?;
    client.store().get(record).map_err(|_| VAULT_ERROR.into())
}

fn write_record(path: &Path, slot: &str, client_id: &[u8], record: &[u8], payload: Vec<u8>) -> Result<(), String> {
    configure_work_factor();
    let vault = Stronghold::new(path, key(slot, !path.exists())?).map_err(|_| VAULT_ERROR)?;
    let client = if path.exists() {
        vault.load_client(client_id)
    } else {
        vault.create_client(client_id)
    }.map_err(|_| VAULT_ERROR)?;
    client.store().insert(record.to_vec(), payload, None).map_err(|_| VAULT_ERROR)?;
    vault.save().map_err(|_| VAULT_ERROR.into())
}

fn clear_record(path: &Path) -> Result<(), String> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(VAULT_ERROR.into()),
    }
}

pub fn read(path: &Path) -> Result<Option<Vec<u8>>, String> {
    read_record(path, "campus", CAMPUS_CLIENT, CAMPUS_RECORD)
}

pub fn write(path: &Path, payload: Vec<u8>) -> Result<(), String> {
    write_record(path, "campus", CAMPUS_CLIENT, CAMPUS_RECORD, payload)
}

pub fn clear(path: &Path) -> Result<(), String> {
    clear_record(path)
}

pub fn read_backend(path: &Path) -> Result<Option<Vec<u8>>, String> {
    read_record(path, "backend", BACKEND_CLIENT, BACKEND_RECORD)
}

pub fn write_backend(path: &Path, payload: Vec<u8>) -> Result<(), String> {
    write_record(path, "backend", BACKEND_CLIENT, BACKEND_RECORD, payload)
}

pub fn clear_backend(path: &Path) -> Result<(), String> {
    clear_record(path)
}

// P0-4 回执分槽（B 稿 §3）：每个 owner 一个独立命名槽（独立快照文件 +
// 独立 keyring 凭据），与业务 token 分槽——退出登录只清业务槽，回执按
// 90 天到期独立存续。owner 进入文件名与凭据名，必须先经字符校验。
const RECEIPT_CLIENT: &[u8] = b"agenthu-receipt-v1";
const RECEIPT_RECORD: &[u8] = b"receipt";

fn receipt_owner_valid(owner: &str) -> bool {
    (8..=64).contains(&owner.len()) && owner.bytes().all(|b| b.is_ascii_alphanumeric())
}

pub fn read_receipt(path: &Path, owner: &str) -> Result<Option<Vec<u8>>, String> {
    if !receipt_owner_valid(owner) {
        return Err("receipt owner key must be 8-64 ascii alphanumerics".into());
    }
    read_record(path, owner, RECEIPT_CLIENT, RECEIPT_RECORD)
}

pub fn write_receipt(path: &Path, owner: &str, payload: Vec<u8>) -> Result<(), String> {
    if !receipt_owner_valid(owner) {
        return Err("receipt owner key must be 8-64 ascii alphanumerics".into());
    }
    write_record(path, owner, RECEIPT_CLIENT, RECEIPT_RECORD, payload)
}

pub fn clear_receipt(path: &Path, owner: &str) -> Result<(), String> {
    if !receipt_owner_valid(owner) {
        return Err("receipt owner key must be 8-64 ascii alphanumerics".into());
    }
    clear_record(path)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_round_trip_is_encrypted_and_logout_removes_it() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("campus.hold");
        let secret = b"fixture-cookie-secret".to_vec();
        write_record(&path, "campus", CAMPUS_CLIENT, CAMPUS_RECORD, secret.clone()).unwrap();
        let bytes = std::fs::read(&path).unwrap();
        assert!(!bytes.windows(secret.len()).any(|s| s == secret));
        assert_eq!(read_record(&path, "campus", CAMPUS_CLIENT, CAMPUS_RECORD).unwrap(), Some(secret));
        assert!(read_record(&path, "backend", BACKEND_CLIENT, BACKEND_RECORD).is_err());
        clear_record(&path).unwrap();
        assert!(!path.exists());
    }

    #[test]
    fn receipt_slots_isolate_owners_and_reject_bad_keys() {
        let dir = tempfile::tempdir().unwrap();
        let owner_a = "a".repeat(16);
        let owner_b = "b".repeat(16);
        let slot = |owner: &str| dir.path().join(format!("receipt-{owner}.hold"));

        write_receipt(&slot(&owner_a), &owner_a, b"{\"cap\":\"x\"}".to_vec()).unwrap();
        write_receipt(&slot(&owner_b), &owner_b, b"{\"cap\":\"y\"}".to_vec()).unwrap();
        // 每槽独立快照与凭据：A 的键打不开 B 的槽
        assert_eq!(
            read_receipt(&slot(&owner_a), &owner_a).unwrap().unwrap(),
            b"{\"cap\":\"x\"}".to_vec()
        );
        assert!(read_receipt(&slot(&owner_b), &owner_a).is_err());
        // owner 进文件名/凭据名：拒绝路径危险字符与过短键
        assert!(write_receipt(&slot("x"), "../evil", Vec::new()).is_err());
        assert!(read_receipt(&slot("short"), "short").is_err());
        // 清除只影响本槽
        clear_receipt(&slot(&owner_a), &owner_a).unwrap();
        assert!(read_receipt(&slot(&owner_a), &owner_a).unwrap().is_none());
        assert!(read_receipt(&slot(&owner_b), &owner_b).unwrap().is_some());
    }

    #[test]
    fn backend_token_uses_a_separate_client_and_record() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("backend.hold");
        let token = b"fixture-access-token".to_vec();
        write_record(&path, "backend", BACKEND_CLIENT, BACKEND_RECORD, token.clone()).unwrap();
        let bytes = std::fs::read(&path).unwrap();
        assert!(!bytes.windows(token.len()).any(|s| s == token));
        assert_eq!(
            read_record(&path, "backend", BACKEND_CLIENT, BACKEND_RECORD).unwrap(),
            Some(token)
        );
        assert!(read_record(&path, "campus", CAMPUS_CLIENT, CAMPUS_RECORD).is_err());
        clear_record(&path).unwrap();
        assert!(!path.exists());
    }

    #[test]
    #[cfg(windows)]
    fn keyring_retry_retries_transient_and_passes_deterministic_through() {
        use std::cell::Cell;
        let transient = || -> Result<Vec<u8>, keyring::Error> {
            Err(keyring::Error::NoStorageAccess(Box::new(std::io::Error::other("ci blip"))))
        };
        // 瞬时错误耗尽有界次数：重试满额后仍然失败，且每次重试真实发生
        let attempts = Cell::new(0u32);
        let result = with_keyring_retry(|| {
            attempts.set(attempts.get() + 1);
            transient()
        });
        assert!(matches!(result, Err(keyring::Error::NoStorageAccess(_))));
        assert_eq!(attempts.get(), KEYRING_ATTEMPTS as u32);
        // NoEntry 与 Invalid 是确定性结果：直通，不做任何重试
        let deterministic: [fn() -> keyring::Error; 2] = [
            || keyring::Error::NoEntry,
            || keyring::Error::Invalid("attr".into(), "reason".into()),
        ];
        for build_deterministic in deterministic {
            attempts.set(0);
            let result: Result<Vec<u8>, keyring::Error> = with_keyring_retry(|| {
                attempts.set(attempts.get() + 1);
                Err(build_deterministic())
            });
            assert!(result.is_err());
            assert_eq!(attempts.get(), 1);
        }
    }

    #[test]
    #[cfg(windows)]
    fn keyring_retry_recovers_after_transient_failure() {
        use std::cell::Cell;
        let attempts = Cell::new(0u32);
        let result = with_keyring_retry(|| {
            let n = attempts.get();
            attempts.set(n + 1);
            if n == 0 {
                Err(keyring::Error::PlatformFailure(Box::new(std::io::Error::other("rpc hiccup"))))
            } else {
                Ok(b"recovered".to_vec())
            }
        });
        assert_eq!(result.unwrap(), b"recovered".to_vec());
        assert_eq!(attempts.get(), 2);
    }
}