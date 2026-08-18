# paperless-local-ai Studio

The Studio is the central application UI. It has three clearly separated owners instead of one mixed settings page.

## App-Einstellungen

Shared runtime configuration for the whole application:

- **Verbindungen**: Paperless URL, Ollama URL and a safe token-presence indicator; includes a draft connection test.
- **Pipeline & Tags**: OCR queue/error, LLM queue/error, review tag and additional taxonomy-excluded tags.
- **OCR**: language, PaddleOCR generation and device.
- **Betrieb**: polling interval, review cleanup and dry-run.
- **Verlauf**: versioned app configuration and restore-as-new-version.

Saved values are written to `app-config.json` and are reloaded by workers while running.

The Paperless API token is deliberately not editable here. It is a secret and remains in deployment configuration (`.env` or a future Docker Secret).

## Klassifizierung

- **Prompt**: system prompt and classification template.
- **Test**: render the final prompt without inference, or run a real Ollama test without writing Paperless metadata.
- **Ausgabe & erlaubte Werte**: structured output contract and current Paperless taxonomy.
- **Einstellungen**: model/context/output/token/text-window parameters specific to stage 1.
- **Verlauf**: version history and restore-as-new-version.

## Korrespondent-Vorschlag

- **Prompt**: independent correspondent-only prompt.
- **Test**: isolated real model test; no Paperless write and no persistent review candidate.
- **Einstellungen**: model/request parameters specific to stage 2 and `Produktiv verwenden`.
- **Verlauf**: independent version history.

A fresh install starts the correspondent fallback disabled. Enable it only after document-ID tests look correct.

## Why model settings are not in App-Einstellungen

This is intentional rather than accidental duplication. Classification and correspondent fallback are independent LLM stages with different context/output needs. A saved version must keep each prompt together with the exact model parameters used to run that prompt.

## Save semantics

- `Konfiguration prüfen`: validate current draft only.
- `Änderungen speichern`: create a new active version.
- `Finalen Prompt anzeigen`: render only; no model call.
- `Mit Modell testen`: real Ollama request under the shared AI lock; no document metadata write.
