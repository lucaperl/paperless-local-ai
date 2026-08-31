use crate::error::{Error, Result};
use crate::json_compat::canonical_json_bytes;
use crate::text::casefold;
use reqwest::Url;
use serde::{Deserialize, Serialize};
use serde_json::{Map, Value};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;
use std::fs::{self, File, OpenOptions};
use std::io::Write;
use std::path::{Path, PathBuf};
use std::time::{SystemTime, UNIX_EPOCH};

pub const OCR_MODEL_PROFILES: &[&str] = &["medium", "small", "tiny"];
pub const OCR_MAX_SIDE_PIXELS_DEFAULT: u32 = 3000;
pub const OCR_MAX_SIDE_PIXELS_MIN: u32 = 2000;
pub const OCR_MAX_SIDE_PIXELS_MAX: u32 = 4000;
pub const OCR_RETRY_DELAYS_DEFAULT: &[u32] = &[15, 60, 300, 600];
pub const OCR_RETRY_DELAYS_MAX_COUNT: usize = 10;
pub const OCR_RETRY_DELAY_MAX_SECONDS: u32 = 86_400;
pub const HISTORY_MATCH_SIMILARITY_DEFAULT: f64 = 0.62;
pub const HISTORY_MIN_SUPPORT_DEFAULT: u64 = 2;
pub const HISTORY_MIN_WINNER_SHARE_DEFAULT: f64 = 0.50;
pub const CORRESPONDENT_MATCH_SIMILARITY_DEFAULT: f64 = 0.91;
pub const CORRESPONDENT_MATCH_MARGIN_DEFAULT: f64 = 0.04;
pub const CORRESPONDENT_MATCH_SIMILARITY_MIN: f64 = 0.80;
pub const CORRESPONDENT_MATCH_MARGIN_MAX: f64 = 0.20;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct ConnectionsConfig {
    pub paperless_url: String,
    pub ollama_url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkflowConfig {
    pub llm_queue_tag: String,
    pub llm_error_tag: String,
    pub review_tag: String,
    pub extra_excluded_tags: Vec<String>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct HistoryConfig {
    pub match_similarity: f64,
    pub min_support: u64,
    pub min_winner_share: f64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CorrespondentMatchingConfig {
    pub minimum_similarity: f64,
    pub minimum_margin: f64,
}

impl Default for CorrespondentMatchingConfig {
    fn default() -> Self {
        Self {
            minimum_similarity: CORRESPONDENT_MATCH_SIMILARITY_DEFAULT,
            minimum_margin: CORRESPONDENT_MATCH_MARGIN_DEFAULT,
        }
    }
}

impl CorrespondentMatchingConfig {
    pub fn validate(&self) -> Result<()> {
        if !self.minimum_similarity.is_finite()
            || !(CORRESPONDENT_MATCH_SIMILARITY_MIN..=1.0).contains(&self.minimum_similarity)
        {
            return Err(Error::Config(format!(
                "correspondent_matching.minimum_similarity must be between {CORRESPONDENT_MATCH_SIMILARITY_MIN} and 1"
            )));
        }
        if !self.minimum_margin.is_finite()
            || !(0.0..=CORRESPONDENT_MATCH_MARGIN_MAX).contains(&self.minimum_margin)
        {
            return Err(Error::Config(format!(
                "correspondent_matching.minimum_margin must be between 0 and {CORRESPONDENT_MATCH_MARGIN_MAX}"
            )));
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct OcrConfig {
    pub language: String,
    pub version: String,
    pub model_profile: String,
    pub max_side_pixels: u32,
    pub retry_delays_seconds: Vec<u32>,
    pub device: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct RuntimeConfig {
    pub poll_interval_seconds: u32,
    pub review_prune_interval_seconds: u32,
    pub dry_run: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct PaperlessUiConfig {
    pub enabled: bool,
    pub control_center_url: String,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct AppConfig {
    pub version: u64,
    pub updated_at: Option<String>,
    pub connections: ConnectionsConfig,
    pub workflow: WorkflowConfig,
    pub history: HistoryConfig,
    pub correspondent_matching: CorrespondentMatchingConfig,
    pub ocr: OcrConfig,
    pub runtime: RuntimeConfig,
    pub paperless_ui: PaperlessUiConfig,
}

impl Default for AppConfig {
    fn default() -> Self {
        Self {
            version: 1,
            updated_at: None,
            connections: ConnectionsConfig {
                paperless_url: "http://paperless:8000".into(),
                ollama_url: "http://ollama:11434".into(),
            },
            workflow: WorkflowConfig {
                llm_queue_tag: "LLM".into(),
                llm_error_tag: "LLM Error".into(),
                review_tag: "Inbox".into(),
                extra_excluded_tags: vec!["TODO".into()],
            },
            history: HistoryConfig {
                match_similarity: HISTORY_MATCH_SIMILARITY_DEFAULT,
                min_support: HISTORY_MIN_SUPPORT_DEFAULT,
                min_winner_share: HISTORY_MIN_WINNER_SHARE_DEFAULT,
            },
            correspondent_matching: CorrespondentMatchingConfig::default(),
            ocr: OcrConfig {
                language: "en".into(),
                version: "PP-OCRv6".into(),
                model_profile: "medium".into(),
                max_side_pixels: OCR_MAX_SIDE_PIXELS_DEFAULT,
                retry_delays_seconds: OCR_RETRY_DELAYS_DEFAULT.to_vec(),
                device: "cpu".into(),
            },
            runtime: RuntimeConfig {
                poll_interval_seconds: 10,
                review_prune_interval_seconds: 3600,
                dry_run: false,
            },
            paperless_ui: PaperlessUiConfig {
                enabled: false,
                control_center_url: String::new(),
            },
        }
    }
}

fn nonempty(value: &str, name: &str) -> Result<String> {
    let value = value.trim();
    if value.is_empty() {
        return Err(Error::Config(format!("{name} must be a non-empty string")));
    }
    Ok(value.to_owned())
}

fn http_url(value: &str, name: &str) -> Result<String> {
    let value = nonempty(value, name)?.trim_end_matches('/').to_owned();
    let parsed = Url::parse(&value)
        .map_err(|_| Error::Config(format!("{name} must be a complete http(s) URL")))?;
    if !matches!(parsed.scheme(), "http" | "https") || parsed.host_str().is_none() {
        return Err(Error::Config(format!(
            "{name} must be a complete http(s) URL"
        )));
    }
    Ok(value)
}

fn copy_known_section(
    target: &mut Map<String, Value>,
    raw: &Map<String, Value>,
    name: &str,
) -> Result<()> {
    let Some(incoming) = raw.get(name) else {
        return Ok(());
    };
    let incoming = incoming
        .as_object()
        .ok_or_else(|| Error::Config(format!("{name} must be an object")))?;
    let current = target
        .get_mut(name)
        .and_then(Value::as_object_mut)
        .expect("default app config section is an object");
    let keys: Vec<String> = current.keys().cloned().collect();
    for key in keys {
        if let Some(value) = incoming.get(&key) {
            current.insert(key, value.clone());
        }
    }
    Ok(())
}

impl AppConfig {
    /// Validate exactly like the Python app-config layer: current known fields are
    /// copied over defaults while removed/unknown historical section keys are ignored.
    pub fn from_value(raw: &Value) -> Result<Self> {
        let raw = raw
            .as_object()
            .ok_or_else(|| Error::Config("App configuration must be a JSON object".into()))?;
        let mut merged = serde_json::to_value(Self::default())?
            .as_object()
            .cloned()
            .expect("default app config serializes to an object");

        for section in [
            "connections",
            "workflow",
            "history",
            "correspondent_matching",
            "ocr",
            "runtime",
            "paperless_ui",
        ] {
            copy_known_section(&mut merged, raw, section)?;
        }
        if let Some(version) = raw.get("version") {
            merged.insert("version".into(), version.clone());
        }
        if let Some(updated_at) = raw.get("updated_at") {
            merged.insert("updated_at".into(), updated_at.clone());
        }

        let mut cfg: Self = serde_json::from_value(Value::Object(merged))
            .map_err(|e| Error::Config(format!("invalid app configuration type: {e}")))?;
        cfg.validate()?;
        Ok(cfg)
    }

    pub fn validate(&mut self) -> Result<()> {
        if self.version == 0 {
            return Err(Error::Config("version must be >= 1".into()));
        }
        self.connections.paperless_url =
            http_url(&self.connections.paperless_url, "connections.paperless_url")?;
        self.connections.ollama_url =
            http_url(&self.connections.ollama_url, "connections.ollama_url")?;

        self.workflow.llm_queue_tag =
            nonempty(&self.workflow.llm_queue_tag, "workflow.llm_queue_tag")?;
        self.workflow.llm_error_tag =
            nonempty(&self.workflow.llm_error_tag, "workflow.llm_error_tag")?;
        self.workflow.review_tag = nonempty(&self.workflow.review_tag, "workflow.review_tag")?;
        let technical = [
            casefold(&self.workflow.llm_queue_tag),
            casefold(&self.workflow.llm_error_tag),
            casefold(&self.workflow.review_tag),
        ];
        if technical.into_iter().collect::<BTreeSet<_>>().len() != 3 {
            return Err(Error::Config(
                "Technical workflow tags must have distinct names".into(),
            ));
        }

        let mut seen = BTreeSet::new();
        let mut extra = Vec::with_capacity(self.workflow.extra_excluded_tags.len());
        for item in &self.workflow.extra_excluded_tags {
            let cleaned = nonempty(item, "workflow.extra_excluded_tags")?;
            let key = casefold(&cleaned);
            if seen.insert(key) {
                extra.push(cleaned);
            }
        }
        self.workflow.extra_excluded_tags = extra;

        if !self.history.match_similarity.is_finite()
            || !(0.5..=1.0).contains(&self.history.match_similarity)
        {
            return Err(Error::Config(
                "history.match_similarity must be between 0.5 and 1".into(),
            ));
        }
        if !(2..=5).contains(&self.history.min_support) {
            return Err(Error::Config(
                "history.min_support must be between 2 and 5".into(),
            ));
        }
        if !self.history.min_winner_share.is_finite()
            || !(0.5..=1.0).contains(&self.history.min_winner_share)
        {
            return Err(Error::Config(
                "history.min_winner_share must be between 0.5 and 1".into(),
            ));
        }

        self.correspondent_matching.validate()?;

        self.ocr.language = nonempty(&self.ocr.language, "ocr.language")?;
        self.ocr.version = nonempty(&self.ocr.version, "ocr.version")?;
        self.ocr.model_profile =
            nonempty(&self.ocr.model_profile, "ocr.model_profile")?.to_lowercase();
        self.ocr.device = nonempty(&self.ocr.device, "ocr.device")?;
        if !OCR_MODEL_PROFILES.contains(&self.ocr.model_profile.as_str()) {
            return Err(Error::Config(format!(
                "ocr.model_profile must be one of: {}",
                OCR_MODEL_PROFILES.join(", ")
            )));
        }
        if !(OCR_MAX_SIDE_PIXELS_MIN..=OCR_MAX_SIDE_PIXELS_MAX).contains(&self.ocr.max_side_pixels)
        {
            return Err(Error::Config(format!(
                "ocr.max_side_pixels must be >= {OCR_MAX_SIDE_PIXELS_MIN} and <= {OCR_MAX_SIDE_PIXELS_MAX}"
            )));
        }
        if self.ocr.retry_delays_seconds.len() > OCR_RETRY_DELAYS_MAX_COUNT {
            return Err(Error::Config(format!(
                "ocr.retry_delays_seconds may contain at most {OCR_RETRY_DELAYS_MAX_COUNT} values"
            )));
        }
        if self
            .ocr
            .retry_delays_seconds
            .iter()
            .any(|&delay| delay == 0 || delay > OCR_RETRY_DELAY_MAX_SECONDS)
        {
            return Err(Error::Config(
                "ocr.retry_delays_seconds must contain values from 1 through 86400".into(),
            ));
        }
        if self.ocr.version == "PP-OCRv6"
            && self.ocr.model_profile == "tiny"
            && matches!(
                self.ocr.language.to_lowercase().as_str(),
                "japan" | "ja" | "japanese"
            )
        {
            return Err(Error::Config(
                "PP-OCRv6 Tiny does not support Japanese".into(),
            ));
        }

        if !(5..=3600).contains(&self.runtime.poll_interval_seconds) {
            return Err(Error::Config(
                "runtime.poll_interval_seconds must be >= 5 and <= 3600".into(),
            ));
        }
        if !(60..=86_400).contains(&self.runtime.review_prune_interval_seconds) {
            return Err(Error::Config(
                "runtime.review_prune_interval_seconds must be >= 60 and <= 86400".into(),
            ));
        }

        self.paperless_ui.control_center_url =
            self.paperless_ui.control_center_url.trim().to_owned();
        if !self.paperless_ui.control_center_url.is_empty() {
            self.paperless_ui.control_center_url = http_url(
                &self.paperless_ui.control_center_url,
                "paperless_ui.control_center_url",
            )?;
        }
        if self.paperless_ui.enabled && self.paperless_ui.control_center_url.is_empty() {
            return Err(Error::Config(
                "paperless_ui.control_center_url is required when enabled".into(),
            ));
        }
        Ok(())
    }

    pub fn technical_tag_names(&self) -> BTreeSet<String> {
        let mut result = BTreeSet::from([
            self.workflow.llm_queue_tag.clone(),
            self.workflow.llm_error_tag.clone(),
            self.workflow.review_tag.clone(),
        ]);
        result.extend(self.workflow.extra_excluded_tags.iter().cloned());
        result
    }
}

#[derive(Debug, Clone)]
pub struct AppConfigStore {
    pub config_file: PathBuf,
    pub history_dir: PathBuf,
    pub lock_file: PathBuf,
}

impl Default for AppConfigStore {
    fn default() -> Self {
        Self {
            config_file: std::env::var_os("APP_CONFIG_FILE")
                .map(PathBuf::from)
                .unwrap_or_else(|| "/config/app-config.json".into()),
            history_dir: std::env::var_os("APP_CONFIG_HISTORY_DIR")
                .map(PathBuf::from)
                .unwrap_or_else(|| "/config/app-history".into()),
            lock_file: std::env::var_os("APP_CONFIG_LOCK_FILE")
                .map(PathBuf::from)
                .unwrap_or_else(|| "/config/app-config.lock".into()),
        }
    }
}

impl AppConfigStore {
    pub fn ensure(&self) -> Result<AppConfig> {
        if self.config_file.exists() {
            return self.load();
        }
        if let Some(parent) = self.config_file.parent() {
            fs::create_dir_all(parent)?;
        }
        fs::create_dir_all(&self.history_dir)?;
        let cfg = AppConfig {
            updated_at: Some(utc_now_iso()),
            ..AppConfig::default()
        };
        atomic_write_json(&self.config_file, &cfg)?;
        Ok(cfg)
    }

    pub fn load(&self) -> Result<AppConfig> {
        if !self.config_file.exists() {
            return AppConfig::from_value(&serde_json::to_value(AppConfig::default())?);
        }
        let text = fs::read_to_string(&self.config_file)
            .map_err(|e| Error::Config(format!("app-config.json is not readable: {e}")))?;
        let raw: Value = serde_json::from_str(&text)
            .map_err(|e| Error::Config(format!("app-config.json is not readable: {e}")))?;
        AppConfig::from_value(&raw)
    }

    pub fn save(&self, raw: &Value, source: &str) -> Result<AppConfig> {
        if let Some(parent) = self.lock_file.parent() {
            fs::create_dir_all(parent)?;
        }
        let lock = OpenOptions::new()
            .create(true)
            .truncate(false)
            .read(true)
            .write(true)
            .open(&self.lock_file)?;
        lock.lock()?;

        let current = self.load()?;
        let mut candidate = AppConfig::from_value(raw)?;
        candidate.version = current.version + 1;
        candidate.updated_at = Some(utc_now_iso());
        candidate.validate()?;

        let mut history = serde_json::to_value(&current)?;
        let object = history
            .as_object_mut()
            .expect("app config serializes as object");
        object.insert("history_saved_at".into(), Value::String(utc_now_iso()));
        object.insert("history_source".into(), Value::String(source.to_owned()));
        fs::create_dir_all(&self.history_dir)?;
        let history_path = self.history_dir.join(format!(
            "app-config-v{:04}-{}.json",
            current.version,
            utc_now_compact()
        ));
        atomic_write_json(&history_path, &history)?;
        atomic_write_json(&self.config_file, &candidate)?;
        Ok(candidate)
    }

    pub fn list_history(&self) -> Result<Vec<Value>> {
        fs::create_dir_all(&self.history_dir)?;
        let mut paths = fs::read_dir(&self.history_dir)?
            .filter_map(std::result::Result::ok)
            .map(|entry| entry.path())
            .filter(|path| {
                path.file_name()
                    .and_then(|v| v.to_str())
                    .is_some_and(|name| name.starts_with("app-config-v") && name.ends_with(".json"))
            })
            .collect::<Vec<_>>();
        paths.sort_by(|a, b| b.cmp(a));

        let mut items = Vec::with_capacity(paths.len());
        for path in paths {
            let filename = path
                .file_name()
                .and_then(|v| v.to_str())
                .unwrap_or_default();
            match fs::read_to_string(&path)
                .ok()
                .and_then(|text| serde_json::from_str::<Value>(&text).ok())
            {
                Some(data) => {
                    let runtime = data.get("runtime").and_then(Value::as_object);
                    let ocr = data.get("ocr").and_then(Value::as_object);
                    let dry_run = runtime
                        .and_then(|v| v.get("dry_run"))
                        .and_then(Value::as_bool)
                        .unwrap_or(false);
                    let version = ocr
                        .and_then(|v| v.get("version"))
                        .and_then(Value::as_str)
                        .unwrap_or("PP-OCRv6");
                    let profile = ocr
                        .and_then(|v| v.get("model_profile"))
                        .and_then(Value::as_str)
                        .unwrap_or("medium");
                    let profile = title_ascii(profile);
                    let pixels = ocr
                        .and_then(|v| v.get("max_side_pixels"))
                        .and_then(Value::as_u64)
                        .unwrap_or(u64::from(OCR_MAX_SIDE_PIXELS_DEFAULT));
                    items.push(serde_json::json!({
                        "file": filename,
                        "version": data.get("version"),
                        "updated_at": data.get("updated_at"),
                        "history_saved_at": data.get("history_saved_at"),
                        "history_source": data.get("history_source"),
                        "config_sha256": config_hash_value(&data),
                        "summary": format!("{} · {} {} · {} px",
                            if dry_run { "Metadata dry run" } else { "Metadata writes enabled" },
                            version,
                            profile,
                            pixels),
                    }));
                }
                None => items.push(serde_json::json!({"file": filename, "error": "not readable"})),
            }
        }
        Ok(items)
    }

    pub fn restore(&self, filename: &str) -> Result<AppConfig> {
        if Path::new(filename).file_name().and_then(|v| v.to_str()) != Some(filename)
            || !filename.starts_with("app-config-v")
        {
            return Err(Error::Config("Invalid history filename".into()));
        }
        let path = self.history_dir.join(filename);
        if !path.exists() {
            return Err(Error::Config("History version not found".into()));
        }
        let raw: Value = serde_json::from_str(&fs::read_to_string(path)?)?;
        self.save(&raw, &format!("restore:{filename}"))
    }
}

pub fn config_hash_value(value: &Value) -> String {
    format!("{:x}", Sha256::digest(canonical_json_bytes(value)))
}

pub fn atomic_write_json(path: &Path, value: &impl Serialize) -> Result<()> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)?;
    }
    let tmp = path.with_file_name(format!(
        "{}.tmp",
        path.file_name()
            .and_then(|v| v.to_str())
            .unwrap_or("config")
    ));
    let mut file = File::create(&tmp)?;
    serde_json::to_writer_pretty(&mut file, value)?;
    file.write_all(b"\n")?;
    file.sync_all()?;
    drop(file);
    fs::rename(&tmp, path)?;
    Ok(())
}

fn title_ascii(value: &str) -> String {
    let mut chars = value.chars();
    match chars.next() {
        None => String::new(),
        Some(first) => first.to_uppercase().collect::<String>() + chars.as_str(),
    }
}

pub fn utc_now_iso() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;
    format_unix_utc(secs, false)
}

pub fn utc_now_compact() -> String {
    let secs = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64;
    format_unix_utc(secs, true)
}

fn format_unix_utc(secs: i64, compact: bool) -> String {
    let days = secs.div_euclid(86_400);
    let day_secs = secs.rem_euclid(86_400);
    let (year, month, day) = civil_from_days(days);
    let hour = day_secs / 3600;
    let minute = (day_secs % 3600) / 60;
    let second = day_secs % 60;
    if compact {
        format!("{year:04}{month:02}{day:02}-{hour:02}{minute:02}{second:02}")
    } else {
        format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}+00:00")
    }
}

// Howard Hinnant's civil-from-days algorithm, epoch shifted to Unix 1970-01-01.
fn civil_from_days(days_since_unix_epoch: i64) -> (i64, i64, i64) {
    let z = days_since_unix_epoch + 719_468;
    let era = if z >= 0 { z } else { z - 146_096 } / 146_097;
    let doe = z - era * 146_097;
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let mut year = yoe + era * 400;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = mp + if mp < 10 { 3 } else { -9 };
    year += i64::from(month <= 2);
    (year, month, day)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_and_removed_ocr_keys_match_python_contract() {
        let raw = serde_json::json!({
            "workflow": {
                "ocr_queue_tag": "PaddleOCR",
                "ocr_error_tag": "PaddleOCR Error",
                "llm_error_tag": "LLM Fehler"
            },
            "ocr": {"language": "de"}
        });
        let cfg = AppConfig::from_value(&raw).unwrap();
        assert_eq!(cfg.workflow.llm_error_tag, "LLM Fehler");
        assert_eq!(cfg.ocr.language, "de");
        assert_eq!(cfg.ocr.model_profile, "medium");
        assert_eq!(cfg.ocr.max_side_pixels, 3000);
        assert_eq!(cfg.ocr.retry_delays_seconds, vec![15, 60, 300, 600]);
        assert_eq!(cfg.history.match_similarity, 0.62);
        assert_eq!(cfg.history.min_support, 2);
        assert_eq!(cfg.history.min_winner_share, 0.50);
        assert_eq!(cfg.correspondent_matching.minimum_similarity, 0.91);
        assert_eq!(cfg.correspondent_matching.minimum_margin, 0.04);
    }

    #[test]
    fn technical_tags_match_current_contract() {
        let cfg = AppConfig::default();
        let tags = cfg.technical_tag_names();
        for tag in ["LLM", "LLM Error", "Inbox", "TODO"] {
            assert!(tags.contains(tag));
        }
        assert!(!tags.contains("PaddleOCR"));
    }

    #[test]
    fn history_matching_bounds_are_enforced() {
        let mut cfg = AppConfig::default();
        cfg.history.match_similarity = 1.01;
        assert!(
            cfg.validate()
                .unwrap_err()
                .to_string()
                .contains("match_similarity")
        );

        let mut cfg = AppConfig::default();
        cfg.history.min_support = 6;
        assert!(
            cfg.validate()
                .unwrap_err()
                .to_string()
                .contains("min_support")
        );

        let mut cfg = AppConfig::default();
        cfg.history.min_winner_share = -0.01;
        assert!(
            cfg.validate()
                .unwrap_err()
                .to_string()
                .contains("min_winner_share")
        );
    }

    #[test]
    fn correspondent_matching_bounds_are_enforced() {
        let mut cfg = AppConfig::default();
        cfg.correspondent_matching.minimum_similarity = 0.79;
        assert!(
            cfg.validate()
                .unwrap_err()
                .to_string()
                .contains("correspondent_matching.minimum_similarity")
        );

        let mut cfg = AppConfig::default();
        cfg.correspondent_matching.minimum_margin = 0.21;
        assert!(
            cfg.validate()
                .unwrap_err()
                .to_string()
                .contains("correspondent_matching.minimum_margin")
        );
    }

    #[test]
    fn tiny_japanese_is_rejected() {
        let mut cfg = AppConfig::default();
        cfg.ocr.model_profile = "tiny".into();
        cfg.ocr.language = "japan".into();
        assert!(cfg.validate().unwrap_err().to_string().contains("Japanese"));
    }

    #[test]
    fn unix_epoch_conversion_is_correct() {
        assert_eq!(format_unix_utc(0, false), "1970-01-01T00:00:00+00:00");
        assert_eq!(
            format_unix_utc(1_704_067_200, false),
            "2024-01-01T00:00:00+00:00"
        );
    }
}
