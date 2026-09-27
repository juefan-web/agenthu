use std::{path::Path, sync::Once};
use tauri_plugin_stronghold::stronghold::Stronghold;

const CLIENT: &[u8] = b"agenthu-campus-v1";
const RECORD: &[u8] = b"session";
const VAULT_ERROR: &str = "Secure campus storage is unavailable";
static CONFIGURE_WORK_FACTOR: Once = Once::new();

fn configure_work_factor() {
    // The vault key is generated randomly and stored in Windows Credential Manager,
    // rather than derived from a user password. Password-hardening work factors add
    // minutes of CPU time to every Stronghold snapshot without improving this key's
    // security. Existing snapshots retain and use their embedded work factor.
    CONFIGURE_WORK_FACTOR.call_once(|| {
        let _ = engine::snapshot::try_set_encrypt_work_factor(0);
    });
}

#[cfg(windows)]
fn key(create: bool) -> Result<Vec<u8>, String> {
    use rand::RngCore;
    let entry = keyring::Entry::new("dev.agenthu.desktop", "campus-vault-v1")
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
fn key(_create: bool) -> Result<Vec<u8>, String> {
    Err("Secure campus storage is currently supported on Windows only".into())
}

pub fn read(path: &Path) -> Result<Option<Vec<u8>>, String> {
    configure_work_factor();
    if !path.exists() { return Ok(None); }
    read_with_key(path, key(false)?)
}

fn read_with_key(path: &Path, key: Vec<u8>) -> Result<Option<Vec<u8>>, String> {
    configure_work_factor();
    let vault = Stronghold::new(path, key).map_err(|_| VAULT_ERROR)?;
    let client = vault.load_client(CLIENT).map_err(|_| VAULT_ERROR)?;
    client.store().get(RECORD).map_err(|_| VAULT_ERROR.into())
}

pub fn write(path: &Path, payload: Vec<u8>) -> Result<(), String> {
    configure_work_factor();
    write_with_key(path, key(!path.exists())?, payload)
}

fn write_with_key(path: &Path, key: Vec<u8>, payload: Vec<u8>) -> Result<(), String> {
    configure_work_factor();
    let vault = Stronghold::new(path, key).map_err(|_| VAULT_ERROR)?;
    let client = if path.exists() {
        vault.load_client(CLIENT)
    } else {
        vault.create_client(CLIENT)
    }.map_err(|_| VAULT_ERROR)?;
    client.store().insert(RECORD.to_vec(), payload, None).map_err(|_| VAULT_ERROR)?;
    vault.save().map_err(|_| VAULT_ERROR.into())
}

pub fn clear(path: &Path) -> Result<(), String> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(_) => Err(VAULT_ERROR.into()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn snapshot_round_trip_is_encrypted_and_logout_removes_it() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("campus.hold");
        let secret = b"fixture-cookie-secret".to_vec();
        write_with_key(&path, vec![7; 32], secret.clone()).unwrap();
        let bytes = std::fs::read(&path).unwrap();
        assert!(!bytes.windows(secret.len()).any(|s| s == secret));
        assert_eq!(read_with_key(&path, vec![7; 32]).unwrap(), Some(secret));
        assert!(read_with_key(&path, vec![8; 32]).is_err());
        clear(&path).unwrap();
        assert!(!path.exists());
    }
}
