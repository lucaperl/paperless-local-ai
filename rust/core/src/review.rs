use crate::app_config::{atomic_write_json, utc_now_iso};
use crate::error::{Error, Result};
use crate::paperless::PaperlessDocument;
use crate::text::{collapse_whitespace, normalized_words};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::fs;
use std::path::{Path, PathBuf};

pub const SIGNATURE_WORDS: usize = 96;
pub const PAPERLESS_PROMPT_CONTENT_CHARS: usize = 4000;
pub const RECORD_VERSION: u64 = 4;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct ReviewRecord {
    pub version: u64,
    pub document_id: i64,
    pub generated_at: String,
    pub signature_words: usize,
    pub prompt_content_chars: usize,
    pub content_signature: String,
    pub prompt_content_signature: String,
    pub correspondent_suggestion: String,
    pub correspondent_meta: Value,
}

#[derive(Debug, Clone)]
pub struct ReviewStore {
    pub review_dir: PathBuf,
}

impl Default for ReviewStore {
    fn default() -> Self {
        Self {
            review_dir: "/data/correspondent-suggestions".into(),
        }
    }
}

pub fn normalize_signature_text(value: &str) -> String {
    normalized_words(value)
}

pub fn content_word_prefix(content: &str) -> String {
    normalize_signature_text(content)
        .split_whitespace()
        .take(SIGNATURE_WORDS)
        .collect::<Vec<_>>()
        .join(" ")
}

pub fn paperless_prompt_content(content: &str) -> String {
    let prefix = content
        .chars()
        .take(PAPERLESS_PROMPT_CONTENT_CHARS)
        .collect::<String>();
    normalize_signature_text(&prefix)
}

pub fn prompt_content_signature(content: &str) -> String {
    sha256_text(&paperless_prompt_content(content))
}

pub fn signature_material(filename: &str, content: &str) -> (String, String) {
    let normalized_filename = normalize_signature_text(filename);
    let prefix = content_word_prefix(content);
    let content_signature = sha256_text(&prefix);
    let document_signature = sha256_text(&format!("{normalized_filename}\0{prefix}"));
    (document_signature, content_signature)
}

pub fn build_review_record(
    document: &PaperlessDocument,
    correspondent_suggestion: &str,
    correspondent_meta: Value,
) -> Result<ReviewRecord> {
    let candidate = collapse_whitespace(correspondent_suggestion)
        .trim()
        .to_owned();
    if candidate.chars().count() > 255 {
        return Err(Error::Invalid(
            "Correspondent suggestion is longer than 255 characters".into(),
        ));
    }
    let content = document.content.as_deref().unwrap_or_default();
    Ok(ReviewRecord {
        version: RECORD_VERSION,
        document_id: document.id,
        generated_at: utc_now_iso(),
        signature_words: SIGNATURE_WORDS,
        prompt_content_chars: PAPERLESS_PROMPT_CONTENT_CHARS,
        content_signature: sha256_text(&content_word_prefix(content)),
        prompt_content_signature: prompt_content_signature(content),
        correspondent_suggestion: candidate,
        correspondent_meta,
    })
}

impl ReviewStore {
    pub fn write(
        &self,
        document: &PaperlessDocument,
        correspondent_suggestion: &str,
        correspondent_meta: Value,
    ) -> Result<ReviewRecord> {
        let record = build_review_record(document, correspondent_suggestion, correspondent_meta)?;
        atomic_write_json(
            &self.review_dir.join(format!("{}.json", record.document_id)),
            &record,
        )?;
        Ok(record)
    }

    pub fn load_records(&self) -> Result<Vec<Value>> {
        if !self.review_dir.exists() {
            return Ok(vec![]);
        }
        let mut paths = fs::read_dir(&self.review_dir)?
            .filter_map(std::result::Result::ok)
            .map(|entry| entry.path())
            .filter(|path| path.extension().and_then(|v| v.to_str()) == Some("json"))
            .collect::<Vec<_>>();
        paths.sort();
        let mut records = Vec::new();
        for path in paths {
            let Ok(text) = fs::read_to_string(&path) else {
                continue;
            };
            let Ok(mut data) = serde_json::from_str::<Value>(&text) else {
                continue;
            };
            if validate_loaded_record(&mut data) {
                records.push(data);
            }
        }
        Ok(records)
    }

    pub fn records_for_content(
        &self,
        content: &str,
        records: Option<&[Value]>,
    ) -> Result<Vec<Value>> {
        let content_signature = sha256_text(&content_word_prefix(content));
        let owned;
        let source = if let Some(records) = records {
            records
        } else {
            owned = self.load_records()?;
            &owned
        };
        Ok(source
            .iter()
            .filter(|item| {
                item.get("content_signature").and_then(Value::as_str) == Some(&content_signature)
            })
            .cloned()
            .collect())
    }

    pub fn match_record(&self, _filename: &str, content: &str) -> Result<(Option<Value>, String)> {
        // Paperless 3.0.5's internal Document.filename is not exposed by the REST
        // serializer. Keep the API-compatible filename argument but fail closed on
        // content identity exactly like the Python bridge.
        let records = self.load_records()?;
        let strong_signature = prompt_content_signature(content);
        let strong = records
            .iter()
            .filter(|item| {
                item.get("prompt_content_signature").and_then(Value::as_str)
                    == Some(&strong_signature)
            })
            .cloned()
            .collect::<Vec<_>>();
        match strong.len() {
            1 => return Ok((Some(strong[0].clone()), "prompt_content_signature".into())),
            n if n > 1 => {
                return Ok((None, format!("prompt_content_signature ambiguous ({n})")));
            }
            _ => {}
        }

        let content_matches = self.records_for_content(content, Some(&records))?;
        match content_matches.len() {
            1 => Ok((Some(content_matches[0].clone()), "content_signature".into())),
            n if n > 1 => Ok((None, format!("content_signature ambiguous ({n})"))),
            _ => Ok((None, "no review record".into())),
        }
    }

    pub fn remove(&self, doc_id: i64) -> Result<()> {
        let path = self.review_dir.join(format!("{doc_id}.json"));
        match fs::remove_file(path) {
            Ok(()) => Ok(()),
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(()),
            Err(error) => Err(error.into()),
        }
    }

    pub fn dir(&self) -> &Path {
        &self.review_dir
    }
}

fn validate_loaded_record(data: &mut Value) -> bool {
    let Some(object) = data.as_object_mut() else {
        return false;
    };
    let Some(version) = object.get("version").and_then(Value::as_u64) else {
        return false;
    };
    if !matches!(version, 2 | 3 | RECORD_VERSION) {
        return false;
    }
    let document_id = object.get("document_id").and_then(|value| {
        value
            .as_i64()
            .or_else(|| value.as_str()?.parse::<i64>().ok())
    });
    let Some(document_id) = document_id else {
        return false;
    };
    object.insert("document_id".into(), Value::from(document_id));
    if !object
        .get("content_signature")
        .is_some_and(Value::is_string)
    {
        return false;
    }
    if matches!(version, 2 | 3)
        && !object
            .get("document_signature")
            .is_some_and(Value::is_string)
    {
        return false;
    }
    if version == RECORD_VERSION
        && !object
            .get("prompt_content_signature")
            .is_some_and(Value::is_string)
    {
        return false;
    }
    true
}

fn sha256_text(value: &str) -> String {
    format!("{:x}", Sha256::digest(value.as_bytes()))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn document(id: i64, content: &str) -> PaperlessDocument {
        PaperlessDocument {
            id,
            title: None,
            created: None,
            content: Some(content.into()),
            tags: vec![],
        }
    }

    #[test]
    fn signatures_are_normalization_stable() {
        assert_eq!(
            signature_material("Invoice  2026.PDF", "Hello   WORLD 123"),
            signature_material("invoice 2026.pdf", "hello world 123")
        );
        assert_eq!(
            prompt_content_signature("Hello   WORLD 123"),
            prompt_content_signature("hello world 123")
        );
    }

    #[test]
    fn v4_disambiguates_after_the_96_word_prefix() {
        let prefix = (0..96)
            .map(|i| format!("word{i}"))
            .collect::<Vec<_>>()
            .join(" ");
        let a = build_review_record(
            &document(10, &(prefix.clone() + " unique alpha ending")),
            "",
            Value::Object(Default::default()),
        )
        .unwrap();
        let b = build_review_record(
            &document(11, &(prefix + " unique beta ending")),
            "",
            Value::Object(Default::default()),
        )
        .unwrap();
        assert_eq!(a.content_signature, b.content_signature);
        assert_ne!(a.prompt_content_signature, b.prompt_content_signature);
    }
}
