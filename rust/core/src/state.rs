use crate::app_config::AppConfigStore;
use crate::assets::render_control_center;
use crate::error::{Error, Result};
use crate::history::HistoryManager;
use crate::http::HttpClient;
use crate::ocr_recovery::OcrRecoveryStore;
use crate::ollama::OllamaClient;
use crate::paperless::PaperlessClient;
use crate::prompt::PromptConfigStore;
use crate::review::ReviewStore;
use serde_json::Value;
use std::sync::Arc;
use std::sync::atomic::{AtomicBool, Ordering};
use std::time::Instant;
use tokio::sync::{Mutex, Notify};

pub struct RecycleSignal {
    requested: AtomicBool,
    notify: Notify,
}

impl Default for RecycleSignal {
    fn default() -> Self {
        Self {
            requested: AtomicBool::new(false),
            notify: Notify::new(),
        }
    }
}

impl RecycleSignal {
    pub fn request(&self) -> bool {
        if self.requested.swap(true, Ordering::AcqRel) {
            return false;
        }
        self.notify.notify_one();
        true
    }

    pub async fn wait(&self) {
        if self.requested.load(Ordering::Acquire) {
            return;
        }
        self.notify.notified().await;
    }
}

pub struct CoreState {
    pub http: HttpClient,
    pub paperless: PaperlessClient,
    pub ollama: OllamaClient,
    pub app_config: Arc<AppConfigStore>,
    pub prompt_config: Arc<PromptConfigStore>,
    pub history: Arc<HistoryManager>,
    pub review: ReviewStore,
    pub ocr_recovery: OcrRecoveryStore,
    pub token: Arc<str>,
    pub app_version: Arc<str>,
    pub control_html: Arc<str>,
    pub bridge_cache: Mutex<Option<(Instant, Value)>>,
    pub recycle: RecycleSignal,
}

impl CoreState {
    pub fn from_env() -> Result<Arc<Self>> {
        let token = std::env::var("PAPERLESS_TOKEN").unwrap_or_default();
        if token.trim().is_empty() {
            return Err(Error::Config(
                "PAPERLESS_TOKEN is missing; paperless.env must be loaded".into(),
            ));
        }
        let app_version = std::env::var("APP_VERSION")
            .unwrap_or_else(|_| "dev".into())
            .trim()
            .to_owned();
        let app_version = if app_version.is_empty() {
            "dev".to_owned()
        } else {
            app_version
        };

        let http = HttpClient::new()?;
        let app_config = Arc::new(AppConfigStore::default());
        let prompt_config = Arc::new(PromptConfigStore::default());
        let paperless = PaperlessClient::new(http.clone(), token.clone(), app_config.clone());
        let ollama = OllamaClient::new(http.clone(), app_config.clone());
        let history = Arc::new(HistoryManager::from_env());
        let control_html = Arc::<str>::from(render_control_center(&app_version));

        Ok(Arc::new(Self {
            http,
            paperless,
            ollama,
            app_config,
            prompt_config,
            history,
            review: ReviewStore::default(),
            ocr_recovery: OcrRecoveryStore::default(),
            token: Arc::from(token),
            app_version: Arc::from(app_version),
            control_html,
            bridge_cache: Mutex::new(None),
            recycle: RecycleSignal::default(),
        }))
    }
}

#[cfg(test)]
mod tests {
    use super::RecycleSignal;

    #[tokio::test]
    async fn recycle_signal_is_idempotent_and_retains_early_notification() {
        let signal = RecycleSignal::default();
        assert!(signal.request());
        assert!(!signal.request());
        signal.wait().await;
    }
}
