use crate::app_config::AppConfigStore;
use crate::error::{Error, Result};
use crate::http::HttpClient;
use crate::text::casefold;
use reqwest::{Method, Response};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;
use std::time::Duration;
use tokio::time::sleep;

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq)]
pub struct PaperlessDocument {
    pub id: i64,
    #[serde(default)]
    pub title: Option<String>,
    #[serde(default)]
    pub created: Option<String>,
    #[serde(default)]
    pub content: Option<String>,
    #[serde(default)]
    pub tags: Vec<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct TagInfo {
    pub id: i64,
    pub name: String,
    pub parent: Option<i64>,
}

#[derive(Debug, Clone, Serialize, Deserialize, Default, PartialEq, Eq)]
pub struct Taxonomy {
    pub tag_by_name: BTreeMap<String, i64>,
    pub tag_by_id: BTreeMap<i64, String>,
    pub parent_by_id: BTreeMap<i64, Option<i64>>,
    pub content_tag_ids: Vec<i64>,
    pub content_tags: Vec<String>,
    pub tags: Vec<TagInfo>,
    pub correspondents: Vec<String>,
    pub document_types: Vec<String>,
}

#[derive(Debug, Clone)]
pub struct PaperlessClient {
    http: HttpClient,
    token: Arc<str>,
    config_store: Arc<AppConfigStore>,
    base_url_override: Option<Arc<str>>,
}

impl PaperlessClient {
    pub fn new(
        http: HttpClient,
        token: impl Into<String>,
        config_store: Arc<AppConfigStore>,
    ) -> Self {
        Self {
            http,
            token: Arc::from(token.into()),
            config_store,
            base_url_override: None,
        }
    }

    pub fn with_base_url(mut self, base_url: impl Into<String>) -> Self {
        let base_url = base_url.into().trim_end_matches('/').to_owned();
        self.base_url_override = Some(Arc::from(base_url));
        self
    }

    fn base_url(&self) -> Result<String> {
        if let Some(value) = &self.base_url_override {
            return Ok(value.to_string());
        }
        Ok(self.config_store.load()?.connections.paperless_url)
    }

    async fn send(
        &self,
        method: Method,
        path: &str,
        query: Option<&[(String, String)]>,
        json: Option<&Value>,
    ) -> Result<Response> {
        let mut last_error = None;
        for attempt in 1..=3 {
            let base_url = self.base_url()?;
            let mut request = self
                .http
                .inner()
                .request(method.clone(), format!("{base_url}{path}"))
                .header("Authorization", format!("Token {}", self.token))
                .header("Accept", "application/json")
                .timeout(Duration::from_secs(180));
            if let Some(query) = query {
                request = request.query(query);
            }
            if let Some(json) = json {
                request = request.json(json);
            }

            match request.send().await.and_then(Response::error_for_status) {
                Ok(response) => return Ok(response),
                Err(error) => {
                    last_error = Some(error);
                    if attempt < 3 {
                        sleep(Duration::from_secs(2)).await;
                    }
                }
            }
        }
        Err(Error::Http(
            last_error.expect("three attempts produce an error"),
        ))
    }

    pub async fn request_json(
        &self,
        method: Method,
        path: &str,
        query: Option<&[(String, String)]>,
        json: Option<&Value>,
    ) -> Result<Value> {
        Ok(self.send(method, path, query, json).await?.json().await?)
    }

    pub async fn all_objects(&self, path: &str) -> Result<Vec<Value>> {
        let mut objects = Vec::new();
        let mut page = 1u64;
        loop {
            let query = vec![
                ("page_size".into(), "1000".into()),
                ("page".into(), page.to_string()),
            ];
            let data = self
                .request_json(Method::GET, path, Some(&query), None)
                .await?;
            if let Some(items) = data.as_array() {
                return Ok(items.clone());
            }
            let object = data
                .as_object()
                .ok_or_else(|| Error::Invalid(format!("Unexpected API response from {path}")))?;
            let results = object
                .get("results")
                .and_then(Value::as_array)
                .ok_or_else(|| Error::Invalid(format!("Unexpected API response from {path}")))?;
            objects.extend(results.iter().cloned());
            if object.get("next").is_none_or(Value::is_null) {
                return Ok(objects);
            }
            page += 1;
        }
    }

    pub async fn taxonomy(&self) -> Result<Taxonomy> {
        let tags = self.all_objects("/api/tags/").await?;
        let correspondents = self.all_objects("/api/correspondents/").await?;
        let document_types = self.all_objects("/api/document_types/").await?;
        let excluded = self.config_store.load()?.technical_tag_names();

        let mut tag_by_name = BTreeMap::new();
        let mut tag_by_id = BTreeMap::new();
        let mut parent_by_id = BTreeMap::new();
        let mut content_objects = Vec::new();

        for tag in &tags {
            let id = required_i64(tag, "id", "/api/tags/")?;
            let name = required_str(tag, "name", "/api/tags/")?.to_owned();
            let parent = tag.get("parent").and_then(Value::as_i64);
            tag_by_name.insert(name.clone(), id);
            tag_by_id.insert(id, name.clone());
            parent_by_id.insert(id, parent);
            if !excluded.contains(&name) {
                content_objects.push(TagInfo { id, name, parent });
            }
        }
        content_objects.sort_by_cached_key(|item| casefold(&item.name));

        let mut correspondent_names = names(&correspondents, "/api/correspondents/")?;
        correspondent_names.sort();
        let mut document_type_names = names(&document_types, "/api/document_types/")?;
        document_type_names.sort();

        Ok(Taxonomy {
            content_tag_ids: content_objects.iter().map(|item| item.id).collect(),
            content_tags: content_objects
                .iter()
                .map(|item| item.name.clone())
                .collect(),
            tags: content_objects,
            tag_by_name,
            tag_by_id,
            parent_by_id,
            correspondents: correspondent_names,
            document_types: document_type_names,
        })
    }

    pub async fn document(&self, doc_id: i64) -> Result<PaperlessDocument> {
        let value = self
            .request_json(
                Method::GET,
                &format!("/api/documents/{doc_id}/"),
                None,
                None,
            )
            .await?;
        Ok(serde_json::from_value(value)?)
    }

    pub async fn patch_document(&self, doc_id: i64, payload: &Value) -> Result<Value> {
        self.request_json(
            Method::PATCH,
            &format!("/api/documents/{doc_id}/"),
            None,
            Some(payload),
        )
        .await
    }

    pub async fn resolve_named_id(&self, path: &str, name: &str) -> Result<Option<i64>> {
        if name.is_empty() {
            return Ok(None);
        }
        for object in self.all_objects(path).await? {
            if object.get("name").and_then(Value::as_str) == Some(name) {
                return Ok(object.get("id").and_then(Value::as_i64));
            }
        }
        Err(Error::Invalid(format!(
            "Value {name:?} no longer exists in {path}"
        )))
    }
}

fn names(values: &[Value], source: &str) -> Result<Vec<String>> {
    values
        .iter()
        .map(|value| Ok(required_str(value, "name", source)?.to_owned()))
        .collect()
}

fn required_str<'a>(value: &'a Value, key: &str, source: &str) -> Result<&'a str> {
    value
        .get(key)
        .and_then(Value::as_str)
        .ok_or_else(|| Error::Invalid(format!("Missing string field {key:?} in {source}")))
}

fn required_i64(value: &Value, key: &str, source: &str) -> Result<i64> {
    value
        .get(key)
        .and_then(Value::as_i64)
        .ok_or_else(|| Error::Invalid(format!("Missing integer field {key:?} in {source}")))
}

pub fn leaf_names_from_ids(tag_ids: &[i64], tax: &Taxonomy) -> Vec<String> {
    let content_ids = tax.content_tag_ids.iter().copied().collect::<BTreeSet<_>>();
    let selected = tag_ids
        .iter()
        .copied()
        .filter(|id| content_ids.contains(id))
        .collect::<BTreeSet<_>>();
    let mut parents_to_remove = BTreeSet::new();
    for tag_id in &selected {
        let mut parent = tax.parent_by_id.get(tag_id).copied().flatten();
        while let Some(parent_id) = parent {
            if selected.contains(&parent_id) {
                parents_to_remove.insert(parent_id);
            }
            parent = tax.parent_by_id.get(&parent_id).copied().flatten();
        }
    }
    let mut result = selected
        .difference(&parents_to_remove)
        .filter_map(|id| tax.tag_by_id.get(id).cloned())
        .collect::<Vec<_>>();
    result.sort();
    result
}
