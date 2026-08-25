use serde_json::Value;

/// Serialize JSON exactly like the Python configuration hashing contract:
/// `json.dumps(..., ensure_ascii=False, sort_keys=True, separators=(",", ":"))`.
///
/// Object keys are sorted explicitly instead of relying on serde_json::Map's
/// current backing type, so enabling `preserve_order` elsewhere cannot silently
/// change persisted configuration hashes.
pub fn canonical_json_bytes(value: &Value) -> Vec<u8> {
    let mut out = Vec::new();
    write_value(value, &mut out);
    out
}

fn write_value(value: &Value, out: &mut Vec<u8>) {
    match value {
        Value::Null | Value::Bool(_) | Value::Number(_) | Value::String(_) => {
            let encoded = serde_json::to_vec(value).expect("JSON scalar serializes");
            out.extend_from_slice(&encoded);
        }
        Value::Array(items) => {
            out.push(b'[');
            for (index, item) in items.iter().enumerate() {
                if index != 0 {
                    out.push(b',');
                }
                write_value(item, out);
            }
            out.push(b']');
        }
        Value::Object(object) => {
            out.push(b'{');
            let mut keys = object.keys().collect::<Vec<_>>();
            keys.sort_unstable();
            for (index, key) in keys.into_iter().enumerate() {
                if index != 0 {
                    out.push(b',');
                }
                out.extend_from_slice(
                    &serde_json::to_vec(key).expect("JSON object key serializes"),
                );
                out.push(b':');
                write_value(&object[key], out);
            }
            out.push(b'}');
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonical_json_matches_python_compact_sorted_contract() {
        let value = serde_json::json!({
            "z": ["Straße", true, null],
            "a": {"β": 2, "A": 1},
        });
        assert_eq!(
            String::from_utf8(canonical_json_bytes(&value)).unwrap(),
            r#"{"a":{"A":1,"β":2},"z":["Straße",true,null]}"#,
        );
    }
}
