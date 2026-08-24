# Prompt Engine

The schema-aware prompt engine builds provider-neutral prompts for the active Text-to-SQL generation workflow. It does not call an LLM, execute SQL, or expose an HTTP endpoint; provider adapters consume its structured prompt.

## Inputs

The engine consumes:

- the original natural-language question;
- a cached `SchemaCatalog`, including safe sample values and glossary metadata;
- a `SchemaRetrievalResult`, including selected tables, selected columns, glossary terms, and relationship paths.

Only retrieved schema context is rendered. Unselected tables and columns are intentionally absent.

## Prompt Contents

Each `SQLGenerationPrompt` includes:

- SQL dialect, defaulting to PostgreSQL;
- strict read-only instructions requiring SELECT-only SQL;
- structured JSON output requirements;
- selected tables and columns;
- safe sample values for selected sampled columns;
- direct foreign-key relationships among selected tables;
- selected relationship paths preserved from retrieval;
- relevant business-glossary definitions;
- relevant few-shot examples loaded from `backend/app/resources/few_shot_examples.json`.

The prompt model is inspectable in tests through provider-neutral messages and metadata. `safe_log_summary()` returns metadata only and intentionally excludes full prompt text.

## Few-Shot Selection

Few-shot examples are stored as JSON resources rather than embedded in Python. Selection is deterministic and based on overlap with retrieved tables, columns, glossary terms, tags, and question tokens. When retrieval has a precise glossary term, examples must match at least one selected glossary term.

## Context Budget

`TEXT_TO_SQL_PROMPT_CONTEXT_BUDGET_CHARS` limits the rendered context section. If context exceeds the budget, truncation is deterministic: the engine preserves a stable prefix and suffix with an explicit truncation marker.

## Configuration

- `TEXT_TO_SQL_PROMPT_SQL_DIALECT`: SQL dialect label, defaulting to `PostgreSQL`.
- `TEXT_TO_SQL_PROMPT_CONTEXT_BUDGET_CHARS`: rendered context budget, defaulting to 12000.
- `TEXT_TO_SQL_PROMPT_MAX_FEW_SHOT_EXAMPLES`: maximum selected examples, defaulting to 3.
