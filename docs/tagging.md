# Tagging

`paperless-local-ai` provides two content-tag strategies. The strategy affects **content tags only**; title, document type, date and sender/issuer use the configured local LLM.

## Which strategy should I use?

### Hybrid tagging — recommended for small local models

Hybrid tagging combines a confidence-gated reviewed-document lookup with an LLM fallback.

For each document, `paperless-local-ai` compares the full Paperless text with documents that have already passed human review. A complete reviewed leaf-tag set is reused only when the nearest document is sufficiently similar **and** the nearest neighborhood agrees strongly enough on that exact set. The set may contain one or multiple tags. History never combines individually supported tags into a new, unseen combination. If any gate fails, the LLM chooses tags instead and receives the current Tag Guidance plus a small set of relevant reviewed examples.

This creates an explicit abstention/fallback path: uncertain historical evidence is not treated as a tag decision.

### LLM direct — suited to larger or more capable models

The configured model chooses tags directly for every document. Reviewed documents are not used for routing or retrieved prompt examples. Tag Guidance still applies.

## Why Hybrid tagging is the default

Understanding a document and mapping that understanding to a personal filing taxonomy are different tasks. Compact 4B-class models were generally capable of identifying the subject of the reference documents, but direct taxonomy mapping was not consistent enough across recurring and semantically similar document types.

### What was evaluated

The tagging design was tested with several established prompting approaches before settling on the Hybrid route:

- **Zero-shot constrained classification / direct taxonomy mapping:** document semantics were usually understood, but label selection across a personal taxonomy was inconsistent.
- **Label-description and decision-boundary prompting, including verbalizer-style wording:** clearer definitions fixed individual boundaries but introduced regressions elsewhere as prompt complexity grew.
- **Hierarchy-aware prompting:** explicit parent/child instructions did not provide a stable overall improvement.
- **Retrieval-augmented few-shot prompting with positive reviewed examples:** relevant labeled examples produced the clearest and most repeatable improvement for the LLM fallback.
- **Contrastive/negative examples and additional boundary rules:** added prompt cost without a reliable net improvement and are not part of the default fallback.

The resulting architecture uses deterministic reviewed evidence for familiar cases and reserves LLM taxonomy mapping for cases where the evidence gate abstains.

## Trusted reviewed documents

The configured **review tag** is the trust boundary and can have any name. Keep it on a document until human review is complete, then remove it. A document is eligible for Hybrid retrieval only after it has left that tag and no longer carries the classification queue or classification error tag. The recommended Paperless setup marks the chosen review tag as an **Inbox tag** so it is added automatically during import.

The document currently being previewed or classified is excluded by ID from its own lookup.

Paperless tag hierarchy is respected. If Paperless stores both a selected child and its automatically added parent, the parent is pruned for retrieval and evaluation so the example represents the most specific selected filing tag.

## Similarity and confidence gate

The retrieval index uses full Paperless document text. Its vector representation combines equal-weight cosine similarity from:

- TF-IDF word n-grams 1–2;
- TF-IDF `char_wb` character n-grams 3–5.

History treats each reviewed document's **complete leaf-tag set** as one decision unit. Parent tags automatically present alongside selected children are pruned first. Each of the five nearest reviewed documents casts one similarity-weighted vote for its complete set; History does not vote for labels independently and therefore cannot synthesize an unseen combination.

A reviewed set is reused only when **all** of these conditions hold:

- nearest reviewed-document similarity reaches the configured **Minimum similarity**; default `0.62`;
- the nearest document's complete leaf-tag set is also the weighted winning set among the five nearest reviewed documents;
- at least the configured **Minimum support** neighbors carry that exact set; default `2`;
- the winning set receives at least the configured **Minimum winner share** of the similarity-weighted set vote; default `0.50`;
- the complete set contains no more tags than the configured **Maximum LLM tags** limit.

If any condition fails, Hybrid tagging abstains and routes tag selection to the LLM. This includes plausible combinations whose individual tags have historical support but whose complete combination has not been established by reviewed History.

### Advanced History matching

The three confidence values above are exposed under **Control Center → Classification → Tagging → History health → Advanced History matching** and are saved as versioned App Settings. Lowering them increases automatic History coverage but also increases the risk of accepting an incorrect complete tag set. Supported ranges are `0.50?1.00` for similarity, `2?5` for support and `0.50?1.00` for winner share. The remaining retrieval, example-selection and inconsistency-diagnostic constants are implementation details rather than user-facing tuning knobs.

Changing one of these controls changes the History algorithm signature, so cached diagnostics are considered stale until the index is rebuilt automatically on the next Hybrid use or manually with **Refresh reviewed history**.

## LLM fallback and retrieved examples

A Hybrid fallback uses the same similarity index to select up to five relevant positive reviewed examples. Examples below the minimum relevance threshold are skipped, examples without a content tag are not injected, and no more than two examples with the same tag combination are used.

Retrieved examples are for **tag selection only**. Their text is treated as untrusted document content.

## Editable prompt composition

Prompt behavior is not hidden in a fixed tag-classification prompt. The Control Center exposes three editable components:

- **System prompt** — global instructions/security framing;
- **Base classification prompt** — title, document type, sender/issuer, date and document text;
- **Tagging prompt** — tag-selection instructions and placeholders for taxonomy/guidance/examples.

The application decides only **whether** the Tagging prompt is needed:

| Route | Prompt sent to the LLM | `tags` in output schema |
|---|---|---|
| Hybrid confident match | System + Base classification | omitted |
| Hybrid fallback | System + Base classification + Tagging | included |
| LLM direct | System + Base classification + Tagging | included |

On a confident Hybrid match, Tag Guidance, retrieved examples, the tag list, the Tagging prompt and the `tags` schema field are all omitted. The application inserts the complete reviewed leaf-tag set after validating the base LLM result.

**Preview prompts** shows the exact rendered system/user messages and schema for a selected Paperless document.

### Tagging-prompt placeholders

The Tagging prompt can use the normal classification placeholders plus:

- `{{TAGS_JSON}}` / `{{TAGS_LINES}}` — current allowed Paperless content tags;
- `{{MAX_TAGS}}` — configured maximum number of LLM-selected tags;
- `{{TAG_GUIDANCE}}` — current non-empty per-tag guidance lines;
- `{{TAG_EXAMPLES}}` — retrieved reviewed examples on a Hybrid fallback; empty for LLM direct.

## Tag Guidance

The Control Center dynamically lists every current Paperless content tag and provides an optional guidance field for each one. Guidance is stored by Paperless tag ID, so a rename keeps its description.

Use guidance for personal filing boundaries that a model cannot infer from a tag name alone. It is supplied whenever the LLM makes a tag decision and is absent from confident Hybrid routes.

## Reviewed-history lifecycle

There is no trained tag model inside the Hybrid retriever. The persistent Rust core stays lightweight and does not keep NumPy, SciPy or scikit-learn resident.

When Hybrid retrieval is needed, a lightweight broker starts a scientific helper subprocess. A source signature checks the eligible reviewed-document count/latest modification state, current tag taxonomy and configured exclusion tags. If the validated local cache matches that source and the exact runtime/algorithm versions, the helper loads the fitted TF-IDF vectorizers and sparse matrix; otherwise it rebuilds them from Paperless and atomically replaces the cache.

The helper is shared by Control Center requests and the metadata worker. Interactive preview/diagnostic work can keep it warm briefly to avoid repeated imports. Automatic metadata batches route queued documents together and then shut the helper down before Ollama starts. **Refresh reviewed history** forces an immediate rebuild.

The cache is local application state and is never accepted from uploads or network input. It uses pickle protocol 5, is integrity-checked before loading and is rebuilt on source, algorithm or Python/scientific-library version mismatch.

## History health

History health is diagnostic information about the reviewed evidence available to Hybrid tagging.

- **Reviewed documents** — documents currently eligible as trusted retrieval history.
- **Tags represented** — how many current content tags have at least one reviewed example.
- **Retrospective history reuse** — leave-one-out evaluation. Each reviewed document is temporarily treated as new; it counts only when the strict Hybrid gate fires and reproduces its existing complete reviewed leaf-tag set. This is not a prediction of future accuracy.
- **History depth by tag** — how many reviewed examples currently exist for each tag.
- **Potential tag inconsistencies** — review hints for groups of strongly similar reviewed documents with different leaf-tag assignments.

### History depth by tag

History depth is **an example-count indicator, not an accuracy score or match probability**.

| Reviewed examples for a tag | History depth |
|---:|---|
| 0 | No history |
| 1 | Very limited |
| 2–4 | Limited |
| 5–9 | Good |
| 10+ | Strong |

More examples make it more likely that recurring document patterns are represented, but they do not guarantee that a new document will pass the confidence gate.

### Potential tag inconsistencies

This diagnostic groups reviewed documents whose **full text is strongly similar** but whose current leaf-tag assignments differ. A group is displayed only when it contains at least three documents and more than one tag set.

The diagnostic uses the same word + character TF-IDF document representation as retrieval. It calculates pairwise cosine similarity and uses **complete-linkage agglomerative clustering** with a minimum within-group similarity of `0.50`.

A finding is a **review hint, not an error detector**. Similar documents can legitimately require different tags. The diagnostic never changes historical tags and does not affect runtime routing by itself.

## Paperless native classifier vs Hybrid tagging

Paperless-ngx already includes its own automatic metadata classifier. `paperless-local-ai` does not claim that Hybrid tagging is universally more accurate. The two approaches solve the integration problem differently.

For Paperless-ngx **3.0.5**, the native classifier trains on non-Inbox documents. Tag labels come from tags whose matching algorithm is **Automatic**. Document text is vectorized with a word `CountVectorizer` using 1–2-grams (`min_df=0.01`), and tag labels are learned with scikit-learn's `MLPClassifier` through a label/multilabel binarizer. See the [Paperless 3.0.5 classifier source](https://github.com/paperless-ngx/paperless-ngx/blob/v3.0.5/src/documents/classifier.py).

| | Paperless native automatic classifier | `paperless-local-ai` Hybrid tagging |
|---|---|---|
| Core method | trained supervised classifier | confidence-gated nearest-reviewed-document retrieval + LLM fallback |
| Text features | word CountVectorizer, 1–2-grams | equal-weight word TF-IDF 1–2 + character `char_wb` TF-IDF 3–5 |
| Tag training/evidence | tags configured with Automatic matching | reviewed content tags; no Paperless Automatic matching requirement |
| Decision control | classifier prediction | explicit whole-tag-set similarity + neighborhood support/agreement gate |
| Uncertain historical evidence | native classifier behavior | explicit abstention to the configured LLM |
| LLM examples | not part of the native classifier | nearest reviewed documents become few-shot examples on fallback |
| Personal tag instructions | learned implicitly from labeled documents | optional explicit Tag Guidance plus reviewed examples |
| User-visible evidence | normal Paperless suggestion/prediction behavior | route, similarity, support, reuse diagnostics and retrieved examples in Control Center |
| Refresh model | Paperless classifier training lifecycle | lightweight source check; validated local TF-IDF cache, rebuilt only when reviewed data/taxonomy/runtime version changes |

The Hybrid layer exists because its **explicit evidence gate, abstention path, retrieved examples and diagnostics** are directly useful to this local-LLM workflow. Users who prefer Paperless' native automatic matching can continue to use that Paperless feature independently.

## Privacy

Reviewed text and retrieved examples remain inside the local stack and are sent only to the configured Ollama endpoint when an LLM tag decision is required. `paperless-local-ai` adds no cloud inference or telemetry.
