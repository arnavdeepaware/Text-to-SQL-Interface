# Schema Retrieval

The schema retrieval layer selects the database context that later SQL-generation and confidence-scoring components can inspect without parsing prompt text.

## Contracts

`SchemaRetriever` accepts a natural-language question, a `DatabaseSchema`, and a `BusinessGlossary`. It returns a `SchemaRetrievalResult` containing:

- ranked tables with scores, selected flags, bridge flags, and retrieval reasons;
- ranked columns with scores, selected flags, and retrieval reasons;
- matched glossary term names;
- selected foreign-key relationship paths with each hop preserved as an introspected `ForeignKeySchema`;
- fallback metadata when optional embedding retrieval cannot run.

The output is domain data, not a FastAPI response model.

## Lexical Scoring

`LexicalSchemaRetriever` is deterministic. It normalizes text with Unicode NFKC, case-folding, identifier splitting, token matching, and a small synonym map for seeded commerce concepts such as revenue, refunds, customers, regions, delivery, products, and categories.

Scores come from table names, table descriptions, column names, column descriptions, and matched glossary terms. Ties are broken by stable identifiers so repeated retrievals produce identical ordering.

## Embeddings

`EmbeddingProvider` is a small provider-neutral interface. `OpenAIEmbeddingProvider` is disabled unless `TEXT_TO_SQL_OPENAI_API_KEY` is configured. Embeddings are also gated by `TEXT_TO_SQL_SCHEMA_RETRIEVAL_USE_EMBEDDINGS`.

If embeddings are unavailable, disabled, malformed, or fail, retrieval returns the lexical result with `strategy="embedding_fallback"` and a non-secret fallback reason.

## Relationship Paths

Foreign keys are treated as an undirected graph for discovery, while each path step preserves the original foreign-key object and display path. When two selected tables require intermediate joins, bridge tables are included even if their direct lexical score is low, subject to configured hop and table limits.

## Configuration

- `TEXT_TO_SQL_SCHEMA_RETRIEVAL_MIN_TABLE_SCORE`
- `TEXT_TO_SQL_SCHEMA_RETRIEVAL_MIN_COLUMN_SCORE`
- `TEXT_TO_SQL_SCHEMA_RETRIEVAL_MAX_TABLES`
- `TEXT_TO_SQL_SCHEMA_RETRIEVAL_MAX_COLUMNS_PER_TABLE`
- `TEXT_TO_SQL_SCHEMA_RETRIEVAL_MAX_BRIDGE_HOPS`, defaulting to 4 so seeded
  customer-to-category paths can preserve `orders` and `order_items` bridges.
- `TEXT_TO_SQL_SCHEMA_RETRIEVAL_USE_EMBEDDINGS`
- `TEXT_TO_SQL_SCHEMA_RETRIEVAL_EMBEDDING_WEIGHT`
- `TEXT_TO_SQL_OPENAI_API_KEY`
- `TEXT_TO_SQL_OPENAI_EMBEDDING_MODEL`
- `TEXT_TO_SQL_OPENAI_TIMEOUT_SECONDS`

The retriever does not call an LLM, generate SQL, execute SQL, or collect sample values.
