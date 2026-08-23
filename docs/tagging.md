# Tagging

`paperless-local-ai` supports two tag strategies. The choice affects **content tags only**; title, document type, date and sender/issuer still use the configured LLM.

## Which strategy should I use?

### History-assisted — recommended for small local models

Use this as the default for 4B-class and other compact models.

For each new document, `paperless-local-ai` first compares the Paperless text with already reviewed documents. A historical tag is reused only when the match passes a deliberately strict confidence gate. If the document is unfamiliar or the historical neighborhood is ambiguous, the LLM decides the tags instead and receives a small set of relevant reviewed examples.

This gives repeating document types a deterministic path without preventing the model from handling new material.

### LLM only — suited to larger/more capable models

The configured model chooses tags for every document. Reviewed history is not used for routing or few-shot examples.

This option is intentionally retained because a larger model, different model family or future model may map semantic document understanding to a personal taxonomy more reliably than the 4B reference model.

## Why History-assisted is the default

In the reference archive, 4B-class models were good enough to identify what a document was about, but **not consistently reliable enough to apply a personal Paperless tag taxonomy across recurring and semantically similar document types**. The same kind of document could cross taxonomy boundaries between runs or prompt variants even when its semantics were understood correctly.

Adding explicit tag boundaries and relevant reviewed examples improved direct LLM tag selection substantially. Continuing to add prompt rules after that produced diminishing gains and regressions: rules that repaired one boundary could make previously correct cases worse.

Reference results with `qwen3.5:4b`, deterministic sampling and the evaluated archive:

| Evaluation | Exact tag result |
|---|---:|
| Direct small-model fallback baseline | 18 / 43 overall fallback documents* |
| Tag guidance + relevant reviewed examples | 33 / 43 |
| Strict historical route | 89 / 89 routed documents in retrospective leave-one-out testing |

\*The direct baseline completed 38 of the 43 calls successfully and was exact on 18 of those; five calls ended in technical errors. Counting the complete 43-document fallback set, that is 18/43.

The strict history route covered 89 of 132 reviewed documents at the selected threshold. Combining that historical route with the evaluated few-shot fallback yielded 122/132 exact tag results retrospectively in this archive. These results explain the default architecture; they are **not general accuracy guarantees**. The archive is personal, relatively small and some evaluation families are heavily concentrated in one tag.

## What counts as trusted history?

A document becomes eligible only after it has **left the review tag configured under App Settings → Pipeline & Tags**. Documents still carrying the classification queue or classification error tag are also excluded, so unfinished/failed processing cannot become trusted history.

The document currently being previewed/classified is excluded by ID from its own history lookup.

Paperless tag hierarchy is respected: if a child tag and its automatically added parent are both present, the parent is pruned for history decisions so the stored example represents the most specific selected filing tag.

## Matching logic

The index uses the full Paperless document text. Similarity is the equal-weight combination of cosine similarity from:

- TF-IDF word n-grams 1–2;
- TF-IDF `char_wb` character n-grams 3–5.

A history tag is accepted only when all of these conditions hold:

- nearest reviewed document similarity is at least `0.60`;
- the nearest document has exactly one leaf content tag;
- that tag is also the weighted winner among the five nearest reviewed documents;
- at least two of those neighbors support the winning tag;
- the winning tag receives at least `0.50` of the weighted tag vote.

If any condition fails, the LLM is used instead.

These thresholds are intentionally conservative. They came from retrospective calibration on the reference archive and are implementation constants, not user-facing tuning knobs in the current release.

## LLM fallback examples

When History-assisted routing cannot make a confident decision, the fallback reuses the same similarity index to select up to five relevant reviewed examples.

Only examples with a content tag are included, examples below the minimum relevance threshold are skipped, and no more than two examples with the same tag combination are used. This keeps the prompt focused and avoids a single repetitive family dominating the examples.

The examples are used for **tagging only**. Their text is treated as untrusted document content and is not a source for the new document's title, sender or date.

## Tag guidance

**Tag guidance is independent from History-assisted matching.**

The Control Center dynamically lists every current Paperless content tag and provides an optional description field for each one. Use it to explain personal filing boundaries, for example when two semantically related categories are used differently in your archive.

Guidance is supplied to the LLM:

- for every document in **LLM only**;
- only on LLM fallback documents in **History-assisted**.

A high-confidence history match ignores tag guidance completely. Descriptions are stored by Paperless tag ID so renaming a tag keeps its guidance.

## History refresh

There is no trained custom ML model to rebuild. Each process keeps a read-only TF-IDF history index in memory.

When History-assisted data is needed, the app checks at most every **five minutes** whether the count/latest modification state of reviewed documents or the current tag taxonomy changed. The expensive index is rebuilt only after a detected change. **Refresh history** in the Control Center requests an immediate rebuild and also notifies the metadata worker to refresh before its next history route.

For comparison, Paperless-ngx 3.0.5 retrains its own automatic classifier hourly by default. `paperless-local-ai` does not depend on that training schedule or model.

## History health

The Control Center intentionally shows metrics that are useful to a normal user rather than raw vector-space internals:

- **Reviewed documents** — documents currently eligible as trusted history.
- **Tags represented** — how many current content tags have at least one reviewed example.
- **Estimated reusable history** — a retrospective leave-one-out estimate: each reviewed document is temporarily treated as new and tested against the remaining history. A document counts as reusable only when the strict route fires **and reproduces its existing reviewed leaf-tag assignment**. This does not predict future accuracy.
- **Coverage by tag** — reviewed-example count plus a simple history-depth label.
- **Potential tag inconsistencies** — similar reviewed documents using different leaf-tag assignments.

### Potential tag inconsistencies

This diagnostic is intended to catch accidental historical inconsistencies before they become training examples. It groups highly similar documents and highlights groups containing more than one tag assignment.

A flagged group is **not proof that a tag is wrong**. Similar documents can intentionally be filed differently. The Control Center therefore shows the affected document IDs/titles and current tag sets for review and never changes historical tags automatically.

## Why not use Paperless' native automatic classifier?

Paperless-ngx 3.0.5 already contains an automatic classifier. `paperless-local-ai` does not replace or claim to outperform it universally.

The custom history layer exists because this integration needs an explicit similarity value and support/agreement gate before automatic reuse, and because the same nearest reviewed documents are needed for the LLM fallback examples. It also avoids depending on Paperless' internal sklearn model representation and does not require content tags to use Paperless' `Automatic` matching mode.

## Privacy

History text and few-shot examples remain inside the local stack and are sent only to the configured Ollama endpoint. `paperless-local-ai` does not add cloud inference or telemetry.
