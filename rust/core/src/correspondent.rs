use crate::text::{collapse_whitespace, normalized_words};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, BTreeSet};

pub const FUZZY_MATCH_THRESHOLD: f64 = 0.93;
pub const FUZZY_MATCH_MARGIN: f64 = 0.04;
pub const FUZZY_MIN_NORMALIZED_LENGTH: usize = 8;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct CorrespondentResolution {
    pub extracted: String,
    pub status: String,
    pub resolved: String,
    pub suggestion: String,
    pub match_score: Option<f64>,
    pub runner_up_score: Option<f64>,
}

pub fn normalize_correspondent_name(value: &str) -> String {
    normalized_words(value)
}

pub fn clean_candidate(value: &str) -> String {
    collapse_whitespace(value).trim().to_owned()
}

fn plausible_candidate(candidate: &str) -> bool {
    if candidate.is_empty() || candidate.chars().count() > 255 {
        return false;
    }
    let normalized = normalize_correspondent_name(candidate);
    if normalized.chars().count() < 2 || normalized.split_whitespace().count() > 20 {
        return false;
    }
    if [
        "unknown",
        "unbekannt",
        "none",
        "null",
        "n a",
        "nicht erkennbar",
        "kein absender",
    ]
    .contains(&normalized.as_str())
    {
        return false;
    }
    candidate.chars().any(char::is_alphabetic)
}

pub fn resolve_correspondent(candidate: &str, existing: &[String]) -> CorrespondentResolution {
    let candidate = clean_candidate(candidate);
    if !plausible_candidate(&candidate) {
        return resolution(&candidate, "empty", "", "", None, None);
    }

    let normalized_candidate = normalize_correspondent_name(&candidate);
    let normalized_existing = existing
        .iter()
        .filter(|name| !clean_candidate(name).is_empty())
        .map(|name| (name.as_str(), normalize_correspondent_name(name)))
        .collect::<Vec<_>>();

    let exact = normalized_existing
        .iter()
        .filter(|(_, normalized)| normalized == &normalized_candidate)
        .map(|(name, _)| *name)
        .collect::<Vec<_>>();
    if exact.len() == 1 {
        return resolution(&candidate, "existing_exact", exact[0], "", Some(1.0), None);
    }

    let mut scored = normalized_existing
        .iter()
        .map(|(name, normalized)| {
            (
                sequence_matcher_ratio(&normalized_candidate, normalized),
                *name,
            )
        })
        .collect::<Vec<_>>();
    // Python: sorted((score, name), reverse=True): score descending, then name descending.
    scored.sort_by(|a, b| b.0.total_cmp(&a.0).then_with(|| b.1.cmp(a.1)));
    let (best_score, best_name) = scored.first().copied().unwrap_or((0.0, ""));
    let runner_up = scored.get(1).map_or(0.0, |item| item.0);
    let margin = best_score - runner_up;

    if normalized_candidate.chars().count() >= FUZZY_MIN_NORMALIZED_LENGTH
        && !best_name.is_empty()
        && best_score >= FUZZY_MATCH_THRESHOLD
        && margin >= FUZZY_MATCH_MARGIN
    {
        return resolution(
            &candidate,
            "existing_fuzzy",
            best_name,
            "",
            Some(round4(best_score)),
            Some(round4(runner_up)),
        );
    }

    resolution(
        &candidate,
        "new_suggestion",
        "",
        &candidate,
        scored.first().map(|item| round4(item.0)),
        scored.get(1).map(|item| round4(item.0)),
    )
}

fn resolution(
    extracted: &str,
    status: &str,
    resolved: &str,
    suggestion: &str,
    match_score: Option<f64>,
    runner_up_score: Option<f64>,
) -> CorrespondentResolution {
    CorrespondentResolution {
        extracted: extracted.to_owned(),
        status: status.to_owned(),
        resolved: resolved.to_owned(),
        suggestion: suggestion.to_owned(),
        match_score,
        runner_up_score,
    }
}

fn round4(value: f64) -> f64 {
    python_round(value, 4)
}

/// Python's `round(value, ndigits)` uses round-half-to-even, while Rust's
/// `f64::round()` uses half-away-from-zero. Scores are persisted in result
/// reports, so retain the Python behavior across the rewrite.
fn python_round(value: f64, digits: usize) -> f64 {
    // CPython's normal build rounds through its correctly-rounded dtoa path.
    // Rust's fixed-precision formatter likewise rounds the original binary64
    // value as a decimal representation; parsing that representation back
    // preserves the released report contract better than scaling + f64::round.
    format!("{value:.digits$}").parse().unwrap_or(value)
}

#[derive(Debug, Clone, Copy)]
struct Match {
    a: usize,
    b: usize,
    size: usize,
}

/// CPython `difflib.SequenceMatcher(None, a, b).ratio()` for character sequences.
///
/// Keeping this tiny implementation local is deliberate: sender matching already has
/// released thresholds calibrated against Python's algorithm, and swapping in a
/// Levenshtein/Jaro metric during the language rewrite would silently change behavior.
fn sequence_matcher_ratio(a: &str, b: &str) -> f64 {
    let a = a.chars().collect::<Vec<_>>();
    let b = b.chars().collect::<Vec<_>>();
    let blocks = matching_blocks(&a, &b);
    let matches = blocks.iter().map(|m| m.size).sum::<usize>();
    let total = a.len() + b.len();
    if total == 0 {
        1.0
    } else {
        2.0 * matches as f64 / total as f64
    }
}

fn chain_b(b: &[char]) -> BTreeMap<char, Vec<usize>> {
    let mut b2j = BTreeMap::<char, Vec<usize>>::new();
    for (index, ch) in b.iter().copied().enumerate() {
        b2j.entry(ch).or_default().push(index);
    }
    // Match SequenceMatcher's default autojunk heuristic exactly.
    if b.len() >= 200 {
        let ntest = b.len() / 100 + 1;
        let popular = b2j
            .iter()
            .filter(|(_, indexes)| indexes.len() > ntest)
            .map(|(ch, _)| *ch)
            .collect::<BTreeSet<_>>();
        for ch in popular {
            b2j.remove(&ch);
        }
    }
    b2j
}

fn find_longest_match(
    a: &[char],
    b: &[char],
    b2j: &BTreeMap<char, Vec<usize>>,
    alo: usize,
    ahi: usize,
    blo: usize,
    bhi: usize,
) -> Match {
    let (mut best_i, mut best_j, mut best_size) = (alo, blo, 0usize);
    let mut j2len = BTreeMap::<usize, usize>::new();
    for (i, ch) in a.iter().enumerate().take(ahi).skip(alo) {
        let mut new_j2len = BTreeMap::<usize, usize>::new();
        if let Some(indexes) = b2j.get(ch) {
            for &j in indexes {
                if j < blo {
                    continue;
                }
                if j >= bhi {
                    break;
                }
                let size = j
                    .checked_sub(1)
                    .and_then(|prev| j2len.get(&prev))
                    .copied()
                    .unwrap_or(0)
                    + 1;
                new_j2len.insert(j, size);
                if size > best_size {
                    best_i = i + 1 - size;
                    best_j = j + 1 - size;
                    best_size = size;
                }
            }
        }
        j2len = new_j2len;
    }

    // isjunk=None: CPython first extends across non-junk/popular elements. The
    // second extension pass for actual junk is a no-op because there is no junk set.
    while best_i > alo && best_j > blo && a[best_i - 1] == b[best_j - 1] {
        best_i -= 1;
        best_j -= 1;
        best_size += 1;
    }
    while best_i + best_size < ahi
        && best_j + best_size < bhi
        && a[best_i + best_size] == b[best_j + best_size]
    {
        best_size += 1;
    }
    Match {
        a: best_i,
        b: best_j,
        size: best_size,
    }
}

fn matching_blocks(a: &[char], b: &[char]) -> Vec<Match> {
    let b2j = chain_b(b);
    let mut queue = vec![(0usize, a.len(), 0usize, b.len())];
    let mut matches = Vec::new();
    while let Some((alo, ahi, blo, bhi)) = queue.pop() {
        let m = find_longest_match(a, b, &b2j, alo, ahi, blo, bhi);
        if m.size == 0 {
            continue;
        }
        if alo < m.a && blo < m.b {
            queue.push((alo, m.a, blo, m.b));
        }
        if m.a + m.size < ahi && m.b + m.size < bhi {
            queue.push((m.a + m.size, ahi, m.b + m.size, bhi));
        }
        matches.push(m);
    }
    matches.sort_by_key(|m| (m.a, m.b, m.size));

    let mut non_adjacent = Vec::new();
    let (mut a_start, mut b_start, mut size) = (0usize, 0usize, 0usize);
    for m in matches {
        if a_start + size == m.a && b_start + size == m.b {
            size += m.size;
        } else {
            if size != 0 {
                non_adjacent.push(Match {
                    a: a_start,
                    b: b_start,
                    size,
                });
            }
            a_start = m.a;
            b_start = m.b;
            size = m.size;
        }
    }
    if size != 0 {
        non_adjacent.push(Match {
            a: a_start,
            b: b_start,
            size,
        });
    }
    non_adjacent.push(Match {
        a: a.len(),
        b: b.len(),
        size: 0,
    });
    non_adjacent
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn current_python_contract_examples_match() {
        let r = resolve_correspondent("Example-GmbH", &["Example GmbH".into(), "Other AG".into()]);
        assert_eq!(r.status, "existing_exact");
        assert_eq!(r.resolved, "Example GmbH");

        let r = resolve_correspondent(
            "Example Consultng GmbH",
            &[
                "Example Consulting GmbH".into(),
                "Sample Insurance AG".into(),
            ],
        );
        assert_eq!(r.status, "existing_fuzzy");
        assert_eq!(r.resolved, "Example Consulting GmbH");

        let r = resolve_correspondent(
            "Example Regional Services North",
            &[
                "Example Regional Services".into(),
                "Sample Services North".into(),
            ],
        );
        assert_eq!(r.status, "new_suggestion");
    }

    #[test]
    fn sequence_matcher_known_ratios_match_cpython_docs() {
        assert!((sequence_matcher_ratio("abcd", "bcde") - 0.75).abs() < f64::EPSILON);
        assert!((sequence_matcher_ratio("", "") - 1.0).abs() < f64::EPSILON);
    }

    #[test]
    fn score_rounding_uses_python_ties_to_even() {
        assert_eq!(python_round(1.23445, 4), 1.2345);
        assert_eq!(python_round(1.23455, 4), 1.2346);
        assert_eq!(python_round(0.12355, 4), 0.1235);
    }

    #[test]
    fn unreliable_candidate_is_empty() {
        assert_eq!(
            resolve_correspondent("unknown", &["Existing AG".into()]).status,
            "empty"
        );
    }
}
