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

#[cfg(windows)]
fn key(slot: &str, create: bool) -> Result<Vec<u8>, String> {
    use rand::RngCore;
    let entry = keyring::Entry::new("dev.agenthu.desktop", &credential_name(slot))
        .map_err(|_| VAULT_ERROR)?;
    match entry.get_secret() {
        Ok(key) if key.len() == 32 => Ok(key),
        Err(keyring::Error::NoEntry) if create => {
            let mut key = zeroize::Zeroizing::new(vec![0u8; 32]);
            rand::rngs::OsRng.fill_bytes(&mut key);
            entry.set_secret(&key).map_err(|_| VAULT_ERROR)?;
            Ok(key.to_vec())
        }
        _ => Err(VAULT_ERROR.into()),
    }
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
}