use crate::error::{Error, Result};
use serde_json::json;
use std::fs::{File, OpenOptions, TryLockError};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{Duration, SystemTime, UNIX_EPOCH};

pub const DEFAULT_AI_LOCK_FILE: &str = "/coordination/ai.lock";

#[derive(Debug)]
pub struct FileLockGuard {
    file: File,
    status_path: Option<PathBuf>,
}

impl Drop for FileLockGuard {
    fn drop(&mut self) {
        if let Some(path) = &self.status_path {
            let _ = std::fs::remove_file(path);
        }
        let _ = self.file.unlock();
    }
}

pub fn configured_ai_lock_path() -> PathBuf {
    std::env::var_os("PLAI_AI_LOCK_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_AI_LOCK_FILE))
}

fn status_path(path: &Path) -> PathBuf {
    path.parent()
        .unwrap_or_else(|| Path::new("/coordination"))
        .join("ai-status.json")
}

fn now_ms() -> u128 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_millis()
}

fn write_activity(path: &Path, operation: &str, label: &str) -> Result<()> {
    let target = status_path(path);
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let tmp = target.with_extension(format!("tmp-{}-{}", std::process::id(), now_ms()));
    let payload = json!({
        "operation": operation,
        "label": label,
        "started_at_ms": now_ms()
    });
    let mut data = serde_json::to_vec_pretty(&payload)?;
    data.push(b'\n');
    {
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&tmp)?;
        file.write_all(&data)?;
        file.sync_all()?;
    }
    std::fs::rename(tmp, target)?;
    Ok(())
}

async fn acquire_inner(path: &Path, activity: Option<(&str, &str)>) -> Result<FileLockGuard> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let file = OpenOptions::new()
        .create(true)
        .truncate(false)
        .read(true)
        .write(true)
        .open(path)?;

    loop {
        match file.try_lock() {
            Ok(()) => {
                let activity_path = if let Some((operation, label)) = activity {
                    if let Err(error) = write_activity(path, operation, label) {
                        let _ = file.unlock();
                        return Err(error);
                    }
                    Some(status_path(path))
                } else {
                    None
                };
                return Ok(FileLockGuard {
                    file,
                    status_path: activity_path,
                });
            }
            Err(TryLockError::WouldBlock) => {
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            Err(TryLockError::Error(error)) => return Err(Error::Io(error)),
        }
    }
}

pub async fn acquire(path: impl AsRef<Path>) -> Result<FileLockGuard> {
    acquire_inner(path.as_ref(), None).await
}

pub async fn acquire_with_activity(
    path: impl AsRef<Path>,
    operation: &str,
    label: &str,
) -> Result<FileLockGuard> {
    acquire_inner(path.as_ref(), Some((operation, label))).await
}
