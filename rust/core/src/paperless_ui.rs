use crate::app_config::{AppConfig, atomic_write_json};
use crate::error::{Error, Result};
use serde::Serialize;
use std::path::{Path, PathBuf};

const DEFAULT_STATE_FILE: &str = "/integration/paperless-local-ai-ui.json";
const DEFAULT_PACKAGE_FILE: &str = "/integration/paperless_local_ai_ui/apps.py";

#[derive(Debug, Serialize)]
struct PaperlessUiProjection<'a> {
    enabled: bool,
    control_center_url: &'a str,
}

fn state_file() -> PathBuf {
    std::env::var_os("PLAI_PAPERLESS_UI_STATE_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|| DEFAULT_STATE_FILE.into())
}

fn package_file() -> PathBuf {
    std::env::var_os("PLAI_PAPERLESS_UI_PACKAGE_FILE")
        .map(PathBuf::from)
        .unwrap_or_else(|| DEFAULT_PACKAGE_FILE.into())
}

fn sync_to(path: &Path, config: &AppConfig) -> Result<()> {
    if config.paperless_ui.enabled && config.paperless_ui.control_center_url.is_empty() {
        return Err(Error::Config(
            "paperless_ui.control_center_url is required when enabled".into(),
        ));
    }
    atomic_write_json(
        path,
        &PaperlessUiProjection {
            enabled: config.paperless_ui.enabled,
            control_center_url: &config.paperless_ui.control_center_url,
        },
    )
}

pub fn storage_ready() -> bool {
    state_file().parent().is_some_and(Path::is_dir)
}

pub fn integration_package_ready() -> bool {
    package_file().is_file()
}

pub fn sync_if_available(config: &AppConfig) -> Result<bool> {
    if !storage_ready() {
        return Ok(false);
    }
    sync_to(&state_file(), config)?;
    Ok(true)
}

pub fn sync_required(config: &AppConfig) -> Result<()> {
    if !storage_ready() {
        return Err(Error::Config(
            "Paperless UI integration storage is not mounted in core-service; update the deployment before enabling the shortcut".into(),
        ));
    }
    sync_to(&state_file(), config)
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::fs;
    use tempfile::tempdir;

    #[test]
    fn writes_disabled_projection() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("state.json");
        let cfg = AppConfig::default();
        sync_to(&path, &cfg).unwrap();
        let raw: serde_json::Value =
            serde_json::from_str(&fs::read_to_string(path).unwrap()).unwrap();
        assert_eq!(raw["enabled"], false);
        assert_eq!(raw["control_center_url"], "");
    }
}
