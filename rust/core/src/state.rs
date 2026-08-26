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
use std::time::{Duration, Instant};
use tokio::sync::{Mutex, watch};

pub const CORE_CONTAINER_RECYCLE_IDLE_SECONDS: u64 = 300;

pub struct RecycleSignal {
    deadline: watch::Sender<Option<Instant>>,
}

impl Default for RecycleSignal {
    fn default() -> Self {
        let (deadline, _receiver) = watch::channel(None);
        Self { deadline }
    }
}

impl RecycleSignal {
    pub fn cancel(&self) {
        self.deadline.send_replace(None);
    }

    pub fn schedule(&self) {
        self.deadline.send_replace(Some(
            Instant::now() + Duration::from_secs(CORE_CONTAINER_RECYCLE_IDLE_SECONDS),
        ));
    }

    pub fn postpone_if_scheduled(&self) -> bool {
        if !self.is_scheduled() {
            return false;
        }
        self.schedule();
        true
    }

    pub fn is_scheduled(&self) -> bool {
        self.deadline.borrow().is_some()
    }

    pub fn subscribe(&self) -> watch::Receiver<Option<Instant>> {
        self.deadline.subscribe()
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
    use super::{CORE_CONTAINER_RECYCLE_IDLE_SECONDS, RecycleSignal};
    use std::time::{Duration, Instant};

    #[test]
    fn recycle_signal_supports_schedule_cancel_and_postpone() {
        let signal = RecycleSignal::default();
        let receiver = signal.subscribe();

        assert!(!signal.is_scheduled());
        assert!((*receiver.borrow()).is_none());

        signal.schedule();

        let first = (*receiver.borrow()).expect("scheduled deadline");
        let now = Instant::now();

        assert!(signal.is_scheduled());
        assert!(first > now);
        assert!(first <= now + Duration::from_secs(CORE_CONTAINER_RECYCLE_IDLE_SECONDS));

        assert!(signal.postpone_if_scheduled());

        let second = (*receiver.borrow()).expect("postponed deadline");
        assert!(second >= first);

        signal.cancel();

        assert!(!signal.is_scheduled());
        assert!((*receiver.borrow()).is_none());
        assert!(!signal.postpone_if_scheduled());

        signal.schedule();
        assert!(signal.is_scheduled());
    }
}
