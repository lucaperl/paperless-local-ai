use crate::error::{Error, Result};
use std::fs::{File, OpenOptions, TryLockError};
use std::path::{Path, PathBuf};
use std::time::Duration;

pub const DEFAULT_AI_LOCK_FILE: &str = "/coordination/ai.lock";

#[derive(Debug)]
pub struct FileLockGuard {
    file: File,
}

impl Drop for FileLockGuard {
    fn drop(&mut self) {
        let _ = self.file.unlock();
    }
}

pub fn configured_ai_lock_path() -> PathBuf {
    std::env::var_os("PLAI_AI_LOCK_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|| PathBuf::from(DEFAULT_AI_LOCK_FILE))
}

pub async fn acquire(path: impl AsRef<Path>) -> Result<FileLockGuard> {
    let path = path.as_ref();
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
            Ok(()) => return Ok(FileLockGuard { file }),
            Err(TryLockError::WouldBlock) => {
                tokio::time::sleep(Duration::from_millis(100)).await;
            }
            Err(TryLockError::Error(error)) => return Err(Error::Io(error)),
        }
    }
}
