# Changelog

## Unreleased

### Fixed

- separate Paddle worker teardown from OCR container recycle: the heavyweight worker and `ai.lock` are still released after the short warm-session idle timeout, while the lightweight OCR service remains available for five minutes after the heavyweight OCR session has ended before its clean cgroup recycle, avoiding normal batch imports colliding with an intentional restart.

## 0.3.6 - 2026-08-26

### Added

- Optional Paperless-ngx Settings shortcut to open `paperless-local-ai`, with Paperless-side setup verification and guided configuration from the Control Center, without a browser extension or additional service.
- Advanced Hybrid History matching controls for minimum similarity, neighborhood support and winner share, stored with versioned App Settings and documented directly from the Control Center.

### Fixed

- preserve required Paperless parent tags when writing nested content tags back to a document, while keeping LLM and Hybrid History decisions leaf-only.
- make the stale History notice cover both reviewed-document changes and matching-setting changes.

### Changed

- Hybrid History now votes on complete reviewed leaf-tag sets and can reuse reviewed multi-tag combinations; History never synthesizes new combinations, and cases without a confident observed-set match fall back to the LLM.
- raise the default confident-History similarity gate from `0.60` to `0.62`; the default support and weighted winner-share gates remain `2` and `0.50`.

## 0.3.5 - 2026-08-25

### Changed

- replace the persistent Python core runtime with a lightweight Rust 1.98 process while retaining the existing two-image architecture, public ports, mounted state and compatibility entry points;
- keep the scientific History engine disposable and on demand so NumPy, SciPy and scikit-learn are not resident during normal idle operation;
- use dedicated std-only Rust health probes for Core and OCR instead of starting Python for recurring health checks.

### Runtime lifecycle

- keep PaddleOCR in a short-lived subprocess with the existing five-second warm-session reuse window;
- recycle the OCR service cleanly after a completed warm session so Docker starts a fresh OCR cgroup at cold idle;
- recycle the unified Core cleanly after completed metadata batches and explicit History refreshes so transient helper/runtime file cache does not become the new idle baseline;
- retain `restart: unless-stopped` as part of the intended lifecycle for both services.

### Deployment

- existing ports, mounts, secrets and resource limits remain unchanged;
- existing 0.3.4-style Core commands remain compatible through `/app/core_service.py`, which execs the Rust core;
- existing TrueNAS/Docker deployments should use the std-only OCR healthcheck:
  `["CMD", "/usr/local/bin/plai-healthcheck", "--ocr"]`.

### Validation

Production-like TrueNAS validation passed real PaddleOCR inference, automatic OCR recycle, explicit History refresh, a real Paperless metadata writeback/restore cycle, Core recycling, Ollama unload and raw cgroup idle checks. The validated final idle footprint was approximately 18.6 MiB combined for Core and OCR on the reference system.


## 0.3.5-rc.6 - 2026-08-25

### Fixed

- make the std-only healthcheck consume the complete HTTP response before closing its localhost connection;
- prevent the OCR service from logging misleading `ConnectionResetError` tracebacks on successful recurring health probes.

### Validation

RC5 already passed the complete production-like TrueNAS functional, automatic-recycle and raw-cgroup idle gates. RC6 changes only the healthcheck response-drain behavior; the final validation therefore focuses on repeated health probes, clean OCR logs and unchanged cold-idle memory.


## 0.3.5-rc.5 - 2026-08-25

### Fixed

- replace the recurring OCR Python/urllib healthcheck with the existing std-only Rust probe, shipped as a static binary in the Paddle image;
- recycle the unified Rust core cleanly after a completed metadata batch so transient History/scientific-helper and heavy core file cache does not become the new idle baseline;
- recycle the core after an explicit History refresh has returned, while shutting the disposable History helper down before the recycle request;
- keep both intentional service recycle paths behind the existing 11-second Docker restart-policy activation guard.

### Deployment

- no new service, port, mount, secret, privilege or required environment variable is introduced;
- published Compose and TrueNAS templates now use `/usr/local/bin/plai-healthcheck --ocr` for the OCR healthcheck;
- existing deployments that keep the old Python OCR healthcheck remain functional, but should update that persisted healthcheck command to receive the full idle-memory benefit;
- existing `restart: unless-stopped` policies for both core and OCR are part of the intended lifecycle.


## 0.3.5-rc.4 - 2026-08-25

### Fixed

- recycle the long-lived OCR service process after a completed warm PaddleOCR session instead of relying on advisory page-cache reclaim to return the OCR cgroup to its cold idle footprint;
- keep the existing five-second warm-session behavior so consecutive OCR pages can reuse one loaded Paddle worker, then release `ai.lock`, stop the worker and exit the OCR service cleanly;
- rely on the stack's existing `restart: unless-stopped` policy to start a fresh OCR container/cgroup immediately after that clean exit;
- delay an intentional recycle exit until the OCR service has been up for at least 11 seconds, covering Docker's documented 10-second restart-policy activation window;
- remove the RC3 `mincore()`/temporary-remap cache sweep after production-path validation showed that accepted `MADV_PAGEOUT` calls did not reliably remove the remaining clean file cache.

### Deployment

- no new service, port, mount, secret, privilege or required environment variable is introduced;
- the existing published Compose and TrueNAS templates already configure `ocr-service` with `restart: unless-stopped`, which is now part of the OCR lifecycle requirement.


## 0.3.5-rc.3 - 2026-08-25

### Fixed

- extend disposable Paddle worker teardown with a second best-effort Linux reclaim pass for clean runtime-library pages that can remain in the OCR cgroup after the worker's original mappings are paged out;
- use `mincore()` to identify already-resident pages of files seen in the worker's read-only mappings, temporarily establish PTEs only for those pages, apply `MADV_PAGEOUT`, then immediately exit;
- keep cleanup fail-open and unprivileged: no cgroup `memory.reclaim`, global cache drop, extra service, port, mount, secret or required environment variable is introduced.

### Deployment

- image-only prerelease; existing Compose and TrueNAS Custom App deployment contracts remain unchanged.


## 0.3.5-rc.2 - 2026-08-25

### Fixed

- replace the OCR worker's Python `multiprocessing` spawn lifecycle with a normal short-lived subprocess and private socket IPC so no persistent multiprocessing resource-tracker process remains after OCR;
- page out read-only file-backed mappings immediately before disposable Paddle/OpenVINO and scientific History helpers exit, returning their cgroup memory close to the natural pre-run idle state without changing the warm-session behavior;
- add a dedicated std-only Rust core healthcheck binary that verifies the same Control Center and suggestion-bridge endpoints without launching Python or the full core process.

### Deployment

- no ports, mounts, secrets or required environment variables change; existing stored TrueNAS healthchecks remain functional, but updating the core healthcheck command to `/usr/local/bin/plai-healthcheck` is recommended to receive the lower idle-memory footprint.

## 0.3.5-rc.1 - 2026-08-25

### Changed

- replace the persistent Python core runtime with one Rust 1.98 process hosting metadata polling, the Control Center, the suggestion bridge and the lightweight History broker while preserving the two-service architecture and existing public ports and mounts;
- keep the scikit-learn History engine as an on-demand Python subprocess so NumPy, SciPy and scikit-learn remain outside the persistent core;
- retain the legacy `/app/core_service.py` command and standalone Python core entry points in the image for compatibility while new/default Compose deployments start `/usr/local/bin/plai-core`;
- build the core image with a pinned Rust multi-stage build, use a native Rust health check, and add Rust format/check/test/clippy gates to CI and release verification.

### Deployment

- existing 0.3.4 Docker/TrueNAS deployments remain compatible: no new ports, mounts, secrets or required environment variables are introduced, and the legacy `/app/core_service.py` command execs the Rust core; fresh Compose templates start the Rust binary directly.

## 0.3.4 - 2026-08-25

### Changed

- move Hybrid history retrieval into an on-demand scientific subprocess so persistent runtime processes do not keep NumPy, SciPy and scikit-learn resident;
- persist and validate a compact local TF-IDF history cache while preserving the existing cosine nearest-neighbor routing semantics, and rebuild on source/application/runtime mismatch;
- keep interactive history work warm briefly while releasing the helper before metadata/model-test Ollama inference;
- consolidate metadata polling, the Control Center, the optional suggestion bridge and the lightweight History broker into one persistent `core-service` process/container, while keeping OCR isolated and preserving the existing public ports and standalone core entry points.

## 0.3.3 - 2026-08-24

### Changed

- clarify Control Center wording, review-tag lifecycle, field help, test-result labels and configuration-version labels for first-time users;
- document the recommended Paperless Inbox-tag and `Matching algorithm: None` setup for metadata managed by paperless-local-ai;
- clarify that the Paperless Suggestions bridge is optional and document behavior without it;
- update reference OCR/metadata performance and RAM guidance from the current production measurements;
- make Control Center documentation links follow the built application version instead of always linking to `main`.

## 0.3.2 - 2026-08-24

### Fixes

- fix migration of the published v0.3.0 German prompt preset to the split System, Base classification and Tagging prompts.

## 0.3.1 - 2026-08-24

### Hybrid tagging and editable prompt composition

- rename the user-facing tag strategies to **Hybrid tagging** and **LLM direct** while keeping the existing internal config values stable;
- split model instructions into editable **System**, **Base classification** and **Tagging** prompts with English/German presets for all three;
- append the Tagging prompt only when the LLM is responsible for tags; confident Hybrid matches omit tag instructions, taxonomy, Tag Guidance, retrieved examples and the `tags` schema field entirely;
- keep the exact rendered request visible in Control Center preview and explain the dynamic composition directly in the UI;
- clarify History depth thresholds and Potential tag inconsistency diagnostics in the Control Center.

### Documentation

- rewrite README and core documentation as current-product documentation rather than release-history narration;
- expand the technical comparison with Paperless-ngx 3.0.5's native automatic classifier;
- document the evaluated prompting approaches for compact-model taxonomy mapping using standard technical terminology, without presenting archive-specific benchmark numbers as product guarantees.

### Deployment

- image-only patch release: no Compose service, port, mount, secret, dependency or Paperless OCR integration changes.

## 0.3.0 - 2026-08-23

### History-assisted tagging

- add **History-assisted** as the default tag strategy for compact local models while retaining **LLM only** for larger or more capable models;
- build a read-only in-memory history index from finished Paperless documents that have left the configured review tag and are no longer in the classification queue/error state;
- combine equal-weight word TF-IDF (1–2 grams) and `char_wb` TF-IDF (3–5 grams) over the full Paperless document text;
- reuse a historical tag only when the nearest reviewed document has exactly one leaf content tag, similarity is at least **0.60**, the same tag wins the weighted top-five neighborhood, at least two neighbors support it and winner share is at least **0.50**;
- fall back to the configured LLM when the strict history gate does not pass and include up to five relevant positive reviewed examples, with at most two examples per identical tag combination;
- respect Paperless tag hierarchy by pruning automatically added parent tags when a selected child is present;
- refresh history lazily, checking for relevant Paperless document/taxonomy changes at most every five minutes, with a manual **Refresh history** action in the Control Center.

### Tag guidance and diagnostics

- separate **Tagging strategy** from **Tag guidance** in the Control Center so first-time users can understand that they are independent;
- generate one optional guidance field per current Paperless content tag and store guidance by stable Paperless tag ID;
- use guidance only when the LLM is making the tag decision; high-confidence History-assisted matches ignore it;
- add **History health** with reviewed-document count, represented tags, per-tag history depth and a retrospective leave-one-out **Estimated reusable history** metric;
- add advisory **Potential tag inconsistencies** using complete-linkage groups at the calibrated 0.50 similarity threshold; diagnostics never modify historical Paperless metadata.

### Correspondents

- remove the separate correspondent-only LLM fallback and its Control Center/configuration surface;
- make the main structured classification request extract the actual sender/issuer as free text;
- resolve the extracted name locally with normalized exact matching and a deliberately conservative high-threshold fuzzy match;
- apply safe existing matches directly, route plausible new names through the existing Paperless Document Suggestions bridge and never auto-create correspondents;
- keep empty or unreliable sender extraction unresolved instead of forcing a nearest existing correspondent.

### Control Center and documentation

- redesign Classification around **Test → Tagging → Prompt → Output → Settings → History** and remove the separate Correspondent fallback page;
- explain History-assisted vs LLM-only model recommendations directly in the UI and link to the new `docs/tagging.md` architecture/evaluation guide;
- update README, architecture, configuration, installation, Paperless setup, compatibility, troubleshooting and TrueNAS documentation for the single-call metadata flow.

### Reference evaluation

- direct `qwen3.5:4b` fallback baseline: **18/43** exact over the full fallback set (18/38 successful model calls; five technical failures);
- tag guidance plus relevant reviewed examples: **33/43** exact;
- strict historical route: **89/89** routed documents exact in retrospective leave-one-out testing, covering 89 of 132 reviewed documents at the selected threshold;
- evaluated hybrid: **122/132 (92.4%)** exact retrospectively on the reference archive;
- these are archive-specific retrospective measurements, not accuracy guarantees; the held-family evaluation is strongly concentrated in work-related documents.

### Runtime and deployment

- add `scikit-learn==1.9.0` to the core image for local TF-IDF/nearest-neighbor history indexing and complete-linkage diagnostics;
- no Compose service, port, mount, secret or Paperless OCR integration changes are required from v0.2.4;
- existing classification configuration files migrate in place: missing tagging settings default to `history_assisted` with empty per-tag guidance; the old correspondent configuration file is no longer read.

## 0.2.4 - 2026-08-22

### Control Center UX

- reorder the main navigation to **Overview → App Settings → Classification → Correspondent fallback** so first-time setup follows the same order as the UI;
- make **Test** the default tab for Classification and Correspondent fallback, keeping prompt editing available without making it the first screen a new user sees;
- use established Paperless/Ollama/PaddleOCR terminology throughout the visible UI, including **Context window**, **Maximum output tokens**, **Temperature**, **Thinking**, **Keep alive**, **PaddleOCR model**, **Inference device** and **Document Suggestions**;
- move advanced model parameters and worker timing behind expandable sections while keeping the settings fully available;
- add an explicit **Unsaved changes** state and remove config hashes/filenames from the normal history/configuration views;
- render Classification and Correspondent test results in a human-readable summary, with raw JSON, validation and performance data under **Technical details**;
- replace the static OCR Overview status with a real health check against the OCR service and current OCR recovery state.

### OCR recovery UX

- rename the retry setting to **Automatic OCR retries** and explain the default 15 s / 1 min / 5 min / 10 min schedule in normal language;
- keep raw exception text under **Technical details**, show actionable status text first and add simple guidance for memory, language, authentication and service-availability failures;
- rename the failure list to **Recent OCR failures**; **Dismiss** now confirms that it only hides the notice and never retries, modifies or deletes the document;
- clarify that **Retry now** skips the remaining delay for the next scheduled attempt without increasing the retry limit.

### RAM guidance

- add measured OCR peaks for PP-OCRv6 Medium at 3000 / 3200 / 4000 px and measured qwen3.5:4b memory at 4k / 8k / 16k context;
- include the real 16k Classification measurement (~4.2 GiB peak) and a short tuning guide for users with a constrained AI-memory budget;
- explain that heavy PaddleOCR and Ollama inference are serialized, so their peaks normally do not occur at the same time;
- document observed AI-workload memory directly, with practical tuning guidance for constrained systems.

### Deployment

- normal image update; existing Docker Compose and TrueNAS Custom App YAML remain valid;
- no OCR algorithm, retry algorithm, port, mount, secret or container resource-limit changes.

## 0.2.3 - 2026-08-22

### Automatic OCR recovery

- add bounded automatic retries for transient OCR failures with the default backoff **15 s → 1 min → 5 min → 10 min** after the initial attempt;
- expose the retry schedule under **Control Center → App Settings → OCR** as a simple comma-separated list; each value adds one retry, an empty list disables retries, and existing 0.2.2 configurations receive the default schedule automatically;
- keep deterministic authentication, language/configuration, malformed-input and ordinary Paddle errors fail-fast instead of repeatedly retrying failures that are unlikely to recover;
- tear down a failed Paddle subprocess and release the shared `ai.lock` before every delayed retry so Ollama and other work are not blocked during backoff;
- use a stateless 503/`Retry-After` protocol between the OCR service and OCRmyPDF bridge so long backoff periods do not keep one service-side HTTP request open;
- recover from temporary OCR-service/network unavailability in the bridge with the same bounded schedule;
- add a compact **OCR recovery** card to the Control Center with live Running/Waiting/Needs-attention state, **Retry now** while a retry is waiting, and bounded recent final-failure history with Dismiss;
- keep final failures visible instead of silently requeueing forever; Paperless-ngx 3.0.5 has no supported generic retry action for an already failed initial consume task, so final recovery remains an explicit user action after the underlying cause is fixed.

### Deployment

- image-only update from 0.2.2; no port, mount, secret or container resource-limit changes are required.

## 0.2.2 - 2026-08-21

### OCR memory safety

- lower the default temporary OCR raster limit from 4000 to **3000 pixels** on the longest side after full-pipeline RAM and OCR-quality testing on high-resolution scans;
- expose `ocr.max_side_pixels` in **Control Center → App Settings → OCR** with a supported 2000–4000 px range and reference memory guidance;
- keep existing app configurations migration-free by defaulting a missing `ocr.max_side_pixels` to 3000;
- have the OCRmyPDF bridge read the current limit from `ocr-service` before OCR-only downsampling while preserving aspect ratio and proportional DPI;
- pass the same limit to PaddleOCR text detection with `text_det_limit_type=max` as a second safety boundary;
- log the OCR raster dimensions and active limit for future memory diagnostics;
- keep the original Paperless document, visible archive geometry, deployment topology, ports, mounts and 7 GiB OCR container limit unchanged.

### Validation

- full OCRmyPDF/Paperless pipeline tests on a two-page ~138 MP scan completed without OOM at 3000 px with an OCR-service peak around 4.4 GiB;
- a dense small-print contract page produced 99.38% character and 99.11% word similarity between 3200 and 3000 px while reducing the observed OCR-service peak from about 5.1 GiB to 4.65 GiB.

## 0.2.1 - 2026-08-21

### OCR model profiles

- add a Control Center selector for PP-OCRv6 **Medium**, **Small** and **Tiny** detection/recognition profiles, with Medium remaining the default;
- hot-reload profile changes by restarting the next OCR session with the selected matching model pair;
- keep existing saved configurations backward-compatible by defaulting missing `ocr.model_profile` to `medium`;
- reject the unsupported PP-OCRv6 Tiny + Japanese combination;
- align the Control Center pipeline overview with the current Paperless → selective OCR → one-request metadata classification → optional correspondent fallback flow.

### OCR robustness

- downsample only the temporary OCR raster when either side exceeds 4000 pixels, matching PaddleX 3.7's OCR detection `max_side_limit` while preserving aspect ratio and DPI so the visible Paperless page/original remains unchanged;
- tear down and reap a failed Paddle worker when its multiprocessing IPC channel closes unexpectedly, ensuring the shared `ai.lock` is released after worker crashes or OOM kills instead of blocking later OCR/LLM work;
- harden stale-session housekeeping and service shutdown so a dead worker cannot leave an externally active OCR session behind;
- add regression coverage for OCR-only large-image downsampling and the observed worker-EOF/lock-release failure mode;
- keep the 0.2.0 deployment contract unchanged: existing Compose/TrueNAS YAML, mounts, ports and required variables remain valid.

## 0.2.0 - 2026-08-21

### OCR architecture

- replace the separate tag-driven `ocr-worker` with an authenticated `ocr-service` used directly by Paperless' OCRmyPDF pipeline;
- add an OCRmyPDF 17 `OcrEngine.generate_ocr()` plugin that streams rasterized pages to the local service and returns native `OcrElement` geometry without an hOCR/XML roundtrip;
- preserve the Paperless original while OCRmyPDF creates the searchable archive/PDF-A representation and Paperless stores the resulting OCR text;
- remove the old PaddleOCR queue/error tags from the app configuration and keep metadata queuing as a normal Paperless **Document Added → LLM tag** workflow.

### PaddleOCR runtime

- use PaddleOCR 3.7.0 / PaddleX 3.7.2 with explicit **PP-OCRv6 Medium** detection and recognition models;
- enable PaddleX HPI/OpenVINO for the CPU reference deployment;
- use a persistent PaddleX/OpenVINO cache, 4 CPU threads, a 7 GiB OCR limit and a 5-second warm-session timeout by default;
- keep OCR and Ollama serialized through the shared `ai.lock`;
- make `/health.session_active` follow ownership of the global AI slot so the service cannot report idle before the lock is actually released.

### Metadata runtime

- keep the primary structured metadata request plus optional correspondent fallback as two distinct LLM stages;
- retain the configured Ollama model only across the current metadata transaction, then explicitly unload it;
- preserve a finite keep-alive as a crash fail-safe while ensuring normal processing ends with Ollama unloaded.

### Deployment and configuration

- keep four long-running services: `ocr-service`, `metadata-worker`, `prompt-ui` and `suggestion-bridge`;
- add the persistent `/integration` bridge path used to publish the OCRmyPDF plugin to Paperless;
- add deployment settings for the authenticated OCR endpoint, HPI/OpenVINO runtime, shared memory and OCR resource limits;
- document the required Paperless plugin mount and `PLAI_OCR_*` / `PAPERLESS_OCR_USER_ARGS` integration;
- update the Control Center and AppConfig contracts so OCR queue/error settings from 0.1.x are ignored instead of carried forward.

### Cleanup and validation

- remove the legacy direct PyMuPDF dependency from the OCR image while retaining the `requests` pin required by the PaddleOCR/PaddleX stack;
- add regression coverage for the OCR service, removed queue settings, public deployment contracts and session/lock state;
- validate the final local candidate end-to-end on Paperless-ngx 3.0.5: two-page API upload, searchable PDF/A-2b, byte-identical original, PP-OCRv6/OpenVINO OCR, metadata write-back, Inbox handoff, explicit Ollama unload and zero observed Paddle/Ollama overlap.

> [!IMPORTANT]
> 0.2.0 changes the deployment contract. Existing 0.1.x installations must update the app Compose/YAML **and** Paperless' OCRmyPDF integration before switching to the 0.2.0 images. See [Updating](docs/upgrading.md).

## 0.1.3 - 2026-08-19

- switch fresh-install OCR, technical error-tag and prompt defaults to English while preserving existing saved configurations;
- add English/German prompt presets for Classification and Correspondent fallback, improve PP-OCRv6 language selection in the Control Center and make runtime logs/errors English-facing;
- streamline first-time installation and configuration documentation, clarify container networking, workflow scope, Dry Run behavior and metadata write semantics, and remove duplicated Control Center guidance.

## 0.1.2 - 2026-08-19

- rename the TrueNAS portal button to **Control Center** in the published TrueNAS Custom App template and document the one-time YAML metadata change for existing installations that still show **Prompt UI**;
- redesign the Control Center around an Overview and persistent sidebar while keeping the existing configuration, testing and history workflows;
- add a visual end-to-end pipeline overview from Paperless import through OCR/classification, optional correspondent fallback and write-back to Paperless;
- keep the existing in-UI guidance while moving section and field details into collapsible help and info controls where appropriate;
- update the README workflow diagram and correspondent description to match the current Paperless → OCR → classification → optional fallback → write-back flow.

## 0.1.1 - 2026-08-19

- rename the web UI from Prompt Studio to **Control Center** to reflect its app-wide role;
- switch the Control Center interface and UI-facing validation messages to English;
- make safe pre-production testing explicit: connection tests, prompt previews, live LLM tests and Dry Run.

## 0.1.0 - 2026-08-18

Initial public release.

- ship one four-service Compose application using two images (`core` and `ocr`);
- production-test the unified deployment end-to-end with Paperless-ngx 3.0.5 on x86-64 Linux / TrueNAS SCALE 25.10.4;
- preserve selective per-page OCR, shared OCR/LLM serialization and text-only metadata classification;
- use review-record schema v4 for exact/fail-closed native Paperless correspondent suggestions;
- centralize shared runtime settings in versioned `app-config.json` while keeping secrets and Docker-owned settings in deployment configuration;
- set the default worker polling interval to 10 seconds and support runtime hot-reload;
- pin the validated PaddleOCR/PaddleX/OpenCV/Numpy runtime stack so rebuilding `0.1.0` does not silently change OCR behavior;
- publish release images to GHCR with exact version plus `stable`/`latest` tags for non-prerelease releases;
- add GitHub Actions tests, Compose validation, GHCR publication and build-provenance attestations;
- document generic Docker Compose and TrueNAS Custom App deployment from the same codebase;
- add an explicit third-party licensing notice for the OCR runtime instead of presenting the whole container image as MIT-only;
- document the `0.1.0` language scope explicitly: German Studio/default prompts, configurable OCR language, no untested multilingual claim.

## 0.1.0-alpha.4 - 2026-08-18

- introduce review-record schema v4 based on normalized Paperless AI prompt content;
- remove unsafe filename-based request identity assumptions;
- keep exact, fail-closed compatibility behavior for ambiguous requests;
- add regression coverage for prompt-content collisions.

## 0.1.0-alpha.3 - 2026-08-18

- clean up stale review records;
- test real filename collisions;
- keep review matching fail closed when identity is ambiguous.

## 0.1.0-alpha.2 - 2026-08-18

- unify PaddleOCR and metadata processing into one deployable project;
- add the Control Center configuration path and shared runtime configuration;
- add review persistence and the native Paperless correspondent suggestion bridge.

## 0.1.0-alpha.1 - 2026-08-18

- initial staged unified-app prototype.
