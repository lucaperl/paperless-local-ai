use unicase::UniCase;
use unicode_normalization::UnicodeNormalization;

pub fn casefold(value: &str) -> String {
    UniCase::unicode(value).to_folded_case()
}

/// Match Python's `unicodedata.normalize("NFKC", value).casefold()` closely.
pub fn nfkc_casefold(value: &str) -> String {
    let normalized = value.nfkc().collect::<String>();
    UniCase::unicode(normalized).to_folded_case()
}

/// Match the project's Python `re.findall(r"\\w+", ..., flags=re.UNICODE)`
/// for document/sender identity material: Unicode alphanumeric runs plus `_`.
pub fn normalized_words(value: &str) -> String {
    let folded = nfkc_casefold(value);
    let mut out = String::with_capacity(folded.len());
    let mut in_word = false;

    for ch in folded.chars() {
        let word = ch == '_' || ch.is_alphanumeric();
        if word {
            out.push(ch);
            in_word = true;
        } else if in_word {
            out.push(' ');
            in_word = false;
        }
    }

    if out.ends_with(' ') {
        out.pop();
    }
    out
}

pub fn collapse_whitespace(value: &str) -> String {
    value.split_whitespace().collect::<Vec<_>>().join(" ")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn normalization_is_nfkc_casefolded_and_tokenized() {
        assert_eq!(normalized_words("  Example-GmbH  "), "example gmbh");
        assert_eq!(normalized_words("Straße"), "strasse");
        assert_eq!(normalized_words("ＡＢＣ １２３"), "abc 123");
    }
}
