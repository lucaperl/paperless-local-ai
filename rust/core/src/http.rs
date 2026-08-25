use crate::error::Result;
use reqwest::Client;
use std::time::Duration;

#[derive(Debug, Clone)]
pub struct HttpClient {
    inner: Client,
}

impl HttpClient {
    pub fn new() -> Result<Self> {
        let inner = Client::builder()
            // The core only talks to a handful of local endpoints. Keep one warm
            // connection per host instead of retaining an unbounded idle pool.
            .pool_max_idle_per_host(1)
            .pool_idle_timeout(Duration::from_secs(30))
            .build()?;
        Ok(Self { inner })
    }

    pub fn inner(&self) -> &Client {
        &self.inner
    }
}
