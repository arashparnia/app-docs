# Search architecture for a zero-interaction paper archive (full-text, semantic, natural-language)

Research date: 2026-11-03. Primary sources fetched directly (vendor docs, Apple docs JSON, GitHub, papers). Web *search* was unavailable in this run (per-turn budget exhausted), so every fact below comes from a fetched primary page or is explicitly marked "from memory / unverified". Numbers are vendor claims unless marked "measured".

---

## 1. Executive summary

1. v1 search should be **entirely on-device**: SQLite FTS5 (BM25, porter + a trigram shadow table for fuzzy OCR text) + a structured metadata table + a small vector table. This is sub-10 ms for a personal archive of 10k–50k pages and works offline, which matters for the "guaranteed captured, searchable now" promise.
2. **Claude does the understanding at ingest, not at query time.** One Haiku 5.5 structured-output call per document yields doc_type, sender, dates, tax_year, amounts, people, account refs, tags, summary, and a canonical title; those fields become facets and FTS columns. Query-time Claude is optional.
3. **Natural-language queries** ("dentist bill from last spring") are translated by Claude Haiku 5.5 with `output_config.format` JSON schema into `{filters, keywords, semantic_query}`; a deterministic on-device parser (NSDataDetector + a small grammar + Apple Foundation Models where available) answers instantly and covers the 80% case without a network round-trip.
4. **Semantic search**: Voyage `voyage-4-lite` ($0.02/M tokens, 200M free tokens, 256–2048 dims, int8/binary output) for cloud embeddings; stored on device in `sqlite-vec` (brute-force is fine at this scale). On-device-only fallback: a 384-dim MiniLM/bge-small via `swift-embeddings` (MLTensor) or Apple `NLContextualEmbedding`.
5. **Hybrid ranking** = Reciprocal Rank Fusion (k=60) of BM25 and vector lists, then metadata filters as hard constraints. Anthropic's own contextual-retrieval study: BM25+embeddings+rerank cut retrieval failures 67% vs embeddings alone.
6. **Spotlight**: donate every page to Core Spotlight (`title` + `textContent`); iOS 18+ gives semantic search for free inside Spotlight and in-app via `CSUserQuery`.
7. **v2 service**: Postgres + pgvector + Postgres FTS (or ParadeDB BM25) in one database, tenant_id on every row, per-tenant namespace; Meilisearch/Typesense are good for scoped-key multi-tenancy but add a second datastore. Turbopuffer ($16/mo minimum) is the cheapest serverless vector option if you need it.
8. **Question answering** ("total medical spend 2024") = filter → retrieve → Claude with `citations.enabled` on text/PDF documents; cited_text does not count toward output tokens.
9. The archive stays searchable without the app: Google Drive auto-indexes PDF text (`fullText contains`), Synology Universal Search content-indexes PDFs (and does semantic indexing on PDFs up to 30 MB in Drive Team Folders), and a text-layer PDF is Spotlight-indexable on macOS.
10. Evaluate with a hand-labelled query set (≥150 queries) and nDCG@10 / Recall@20 via `ranx`; make the eval run in CI before touching rankers.

---

## 2. Findings

### 2a. On-device full-text search (SQLite FTS5, GRDB, Core Spotlight)

**FTS5 capabilities** (https://www.sqlite.org/fts5.html):
- Tokenizers: `unicode61` (default; `remove_diacritics` 0/1/2, `tokenchars`, `separators`), `ascii`, `porter` (stemming wrapper: "correction" matches "corrected"), `trigram` (substring matching; `case_sensitive` 0/1, `remove_diacritics` 0/1; **queries shorter than 3 characters match nothing**; trigram tables also accelerate `LIKE`/`GLOB`).
- Ranking: `bm25()` with k1=1.2, b=0.75, per-column weights (`ORDER BY bm25(ft, 10.0, 5.0)`); `ORDER BY rank` is the fast path. Lower is better (already negated).
- `highlight()` and `snippet()` (max 64 tokens) for result previews.
- `prefix='2 3'` indexes for prefix queries (type-ahead).
- External-content tables (`content='docs', content_rowid='id'`) keep the index in sync via triggers and avoid duplicating text; contentless-delete tables since 3.43.0.
- From memory, unverified in this run: the trigram tokenizer was added in SQLite 3.34.0 (2020-12). Any iOS 15+ system SQLite is newer than that; confirm at runtime with `sqlite3_libversion()`.

**Why it fits OCR'd mail**: OCR text has character-level errors ("Con Edlson"). A `porter unicode61` table gives stemmed word search; a second `trigram` FTS table over the same content catches misspellings and partial account numbers ("4471" inside "XXXX-4471"). Two indexes roughly double index size but page text is small (2–4 KB/page), so 50k pages is well under 1 GB.

**GRDB** (https://raw.githubusercontent.com/groue/GRDB.swift/master/README.md and .../Documentation/FullTextSearch.md): GRDB 7.12.0 (2026-11-01), iOS 13+, Swift 6.1 / Xcode 16.3+, uses the OS's system SQLite by default. It has first-class FTS5: `db.create(virtualTable:using: FTS5())`, `synchronize(withTable:)` creates the external-content triggers for you, `FTS5Pattern` builds safe `MATCH` strings (any/all tokens, phrase, prefix), `order(Column.rank)`, and custom tokenizers. Caveats: the GRDB FTS guide still says "To use FTS5, you'll need a custom SQLite build that activates `SQLITE_ENABLE_FTS5`" and lists only unicode61/ascii/porter. **Unverified in this run**: whether the iOS system SQLite is compiled with FTS5 (my recollection is yes since iOS 11; the founder has shipped SQLite on iOS and can check `PRAGMA compile_options` in a minute). If not, GRDB supports custom SQLite builds and SQLCipher, which both enable FTS5 and let you choose the trigram tokenizer.

**Core Spotlight** (https://developer.apple.com/tutorials/data/documentation/corespotlight/*.json; WWDC24 session 10131, https://developer.apple.com/videos/play/wwdc2024/10131/):
- `CSSearchableItem` + `CSSearchableItemAttributeSet` (iOS 9+). For text items set a valid `contentType` (UTType.pdf), `title`, and `textContent`; WWDC24 states title and textContent "will be processed in the semantic index". `contentDescription`, `keywords`, `contentCreationDate`, `contentURL` are also indexed. No documented size limit on `textContent`.
- Use a **named index** (`CSSearchableIndex(name:)`, optionally `protectionClass: .complete`), never `.default()` in production. Batch with `beginBatch()` / `endBatch(withClientState:)` (client state ≤ 250 bytes) so indexing can resume after a crash. Provide a `CSIndexExtensionRequestHandler` extension so Spotlight can ask for re-indexing when the app is not running. Set `expirationDate` for long-lived items or the system expires them.
- In-app search: `CSUserQuery` (iOS 16+) "combines lexical and semantic searches"; `CSUserQueryContext` has `enableRankedResults`, `maxRankedResultCount`, `maxResultCount`, `maxSuggestionCount`, `disableSemanticSearch`, inherited `filterQueries` (e.g. `contentTypeTree="com.adobe.pdf"`) and `fetchAttributes`. Call `CSUserQuery.prepare()` just before showing search (it loads the semantic models in-process and "increases your app's memory footprint"). Semantic search in Spotlight is iOS 18 / macOS 15+. Engagement feedback via `userEngaged(_:visibleItems:interaction:)` improves ranking.
- Implication: Core Spotlight gives system-wide discoverability and a free on-device semantic ranker, but it exposes no BM25 scores, no numeric range filters, and no control over the embedding, so it complements rather than replaces the app's own index.

### 2b. Metadata schema, facets, and how Claude extraction feeds it

Claude structured outputs (https://platform.claude.com/docs/en/build-with-claude/structured-outputs): enabled with `output_config.format = {type:"json_schema", schema}`; stable, no beta header; supported on `claude-haiku-5-5`, `claude-haiku-4-5-20251001`, Sonnet/Opus 4.5+. Schema rules that shape the design: objects must set `additionalProperties:false`; `enum`, `const`, `anyOf`, `$ref` (internal), string `format: date` / `date-time` / `uuid` supported; **no** `minimum`/`maximum`, `minLength`/`maxLength`, recursion; first use of a new schema compiles a grammar (extra latency; cached 24 h). Changing the schema invalidates the prompt cache. Compare enum values case-insensitively.

Proposed extraction schema (one Haiku 5.5 call per document, after OCR; see the OCR dimension report for the OCR side):

| Field | Type | Facet use | Notes |
|---|---|---|---|
| `doc_type` | enum: tax_form, bill, bank_statement, insurance, medical, legal, receipt, letter, government, payslip, other | primary facet | enum keeps classification stable |
| `doc_subtype` | string | secondary ("W-2", "1099-INT", "EOB") | free text; normalized later |
| `title` | string | display + FTS column (weight 10) | "Con Edison electricity bill, Mar 2025" |
| `sender_org` / `sender_person` | string? | facet (normalized key) | keep raw + `sender_key` (lowercased, punctuation stripped) |
| `recipient` | string? | facet (household member) | |
| `doc_date` | `format: date` | range filter, sort | the document's own date |
| `period_start`/`period_end` | date? | statements/bills | |
| `due_date` | date? | reminders | |
| `tax_year` | integer? | facet | derived if doc_type ∈ tax_* |
| `amount_total`, `amount_due`, `amount_paid`, `currency` | number?/string | numeric filter, aggregations | store as integer cents |
| `account_refs` | [string] | exact/trigram match | last-4 digits etc. |
| `people` | [string] | facet | |
| `tags` | [string] | facet, FTS column (weight 5) | 3–8 lowercase tags |
| `summary` | string | FTS column (weight 3), snippet | 1–2 sentences |
| `language` | string | tokenizer choice | |
| `confidence` | number 0–1 | review queue threshold | |

Storage: `documents` (one row per logical document, with the JSON blob plus denormalized columns above), `pages` (page_no, ocr_text, image_hash), `document_fts` (external-content FTS5 over `title, tags, summary, sender, ocr_text` with weights 10/5/3/3/1), `document_trgm` (trigram FTS5 over `ocr_text, account_refs`), `document_vec` (sqlite-vec vec0 with `doc_id`, `tax_year int`, `doc_type text` metadata columns), plus a `facets` materialized table for the counts shown in the UI. Apple `NSDataDetector` (iOS 4+, `.date` results carry `date`, `timeZone`, `duration`) and `NLTagger` `.nameType` (iOS 12+, person/place/organization) are useful as cheap pre-passes to seed candidate dates and org names before the Claude call, and as the fully offline fallback when the key is missing.

Cost: a 2-page letter is ~2–4k input tokens after OCR; at Haiku 5.5's $0.10/M input, $0.50/M output (prompts ≤100k tokens; https://platform.claude.com/docs/en/models/haiku-5-5/overview) one extraction is well under $0.001. Note that Haiku 5.5 uses the newer tokenizer (~30% more tokens than Haiku 4.5 for the same text) and that the PDF-input path costs 1,500–3,000 text tokens per page *plus* image tokens (https://platform.claude.com/docs/en/build-with-claude/pdf-support); sending OCR text instead of the PDF is cheaper and faster.

### 2c. Query understanding

**Cloud path, Claude Haiku 5.5 with JSON schema.** Output: `{ "filters": { "doc_type": [...], "sender_key": [...], "date_from": "2025-03-01", "date_to": "2025-06-30", "tax_year": 2024, "amount_min": null, "amount_max": null, "people": [...] }, "keywords": ["dentist", "bill"], "semantic_query": "dental invoice from spring 2025", "aggregate": null | {"op":"sum","field":"amount_total"} }`. Examples:

| Query | filters | keywords | semantic_query |
|---|---|---|---|
| "all my tax documents for 2024" | doc_type ∈ {tax_form}, tax_year=2024 | ["tax"] | "tax forms for tax year 2024" |
| "the dentist bill from last spring" | doc_type ∈ {bill, medical}, date 2025-03-01..2025-06-30 (relative to today) | ["dentist","dental"] | "dental office invoice" |
| "how much did I pay Con Edison in 2025" | sender_key="con edison", date 2025 | ["con edison"] | "Con Edison electricity bill payment" + aggregate sum(amount_paid) |

Latency: Anthropic documents Haiku 5.5 as "Fastest" and recommends `output_config.effort: "low"` for time-sensitive calls (https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency); no official TTFT numbers. Third-party measurement (https://artificialanalysis.ai/models/claude-haiku-5-5) shows 235 tokens/s output but an anomalous 333 s TTFT figure that almost certainly includes adaptive-thinking time under their default settings; treat as unreliable. Practical expectation (unmeasured): a 60-token JSON output at low effort should land in roughly 0.5–1.5 s end-to-end; pass today's date and the user's known `sender_key` vocabulary (prompt-cached, ≥512 tokens minimum cacheable) in the system prompt so the model normalizes to existing facets. Ship the on-device parse first and let the Claude parse refine results when it arrives.

**On-device fallback (instant, offline).**
- Apple Foundation Models (iOS 26+, Apple Intelligence devices only; `SystemLanguageModel.default.availability`; on-device context 4,096 tokens; https://developer.apple.com/tutorials/data/documentation/foundationmodels/*.json): `@Generable` guided generation returns a typed Swift struct with constrained sampling, which maps 1:1 onto the filter struct above. Keep `@Guide` descriptions short (they consume context and add latency). The `.contentTagging` use case produces topic/action/object/emotion tags and is useful for on-device auto-tagging when no API key is present. No published latency numbers.
- Deterministic grammar: `NSDataDetector` for explicit dates; a small rule set for relative periods ("last spring", "this year", "Q1 2025"); dictionary match against existing `sender_key`, `doc_type` synonyms ("bill"→bill, "EOB"→medical) and `tax_year` patterns (`\b(19|20)\d{2}\b` adjacent to "tax"). Remaining tokens become FTS keywords (with porter stemming) and the whole string becomes the semantic query. This covers nearly all of the founder's example queries without any model.

### 2d. Semantic / hybrid search

**Voyage AI** (https://docs.voyageai.com/docs/embeddings, https://docs.voyageai.com/docs/pricing):

| Model | Context | Dims | $/M tokens | Free tokens |
|---|---|---|---|---|
| voyage-4-large | 32k | 1024 default; 256/512/2048 | $0.12 | 200M |
| voyage-4 | 32k | same | $0.06 | 200M |
| voyage-4-lite | 32k | same | $0.02 | 200M |
| voyage-context-4 (contextualized chunks) | 32k/chunk, 120k total w/ auto-chunking | same | $0.12 | 200M |
| voyage-multimodal-3.5 (text + page images + video) | 32k | same | $0.12 | 200M text tokens + 150B pixels |
| rerank-3 / rerank-3-lite | 32k; ≤1,000 docs/query | – | $0.05 / $0.02 | 200M |
| voyage-4-nano | open weights on Hugging Face | same | self-host | – |

All 4-series models are cross-compatible; `output_dtype` supports float, int8/uint8, binary/ubinary (1/8 the length); `input_type: query|document` adds a retrieval prompt. The 200M-token free tier covers roughly 100k letter-size pages, so a single user never pays for embeddings. `voyage-multimodal-3.5` can embed the page image directly (every 560 pixels = 1 token; ≤16 MP per image) which is a cheap way to search handwritten or graphic-heavy pages the OCR misses.

**On-device embedding alternatives**:
- `NLContextualEmbedding` (iOS 17+; BERT-style contextual token vectors; assets downloaded via `requestAssets`; dimension not documented, read `.dimension` at runtime; Apple's doc explicitly says "for semantic similarity, use `NLEmbedding`"). `NLEmbedding.sentenceEmbedding(for:)` (iOS 13+) is the simpler sentence-level option; neither is documented against retrieval benchmarks, and the instance is not thread-safe.
- `sentence-transformers/all-MiniLM-L6-v2`: 384 dims, 22.7M params, Apache-2.0, truncates at 256 word pieces (https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2). `BAAI/bge-small-en-v1.5`: 384 dims, 33.4M params, 512 tokens, MIT, MTEB 62.17 (https://huggingface.co/BAAI/bge-small-en-v1.5). `google/embeddinggemma-300m`: 768 dims (MRL 512/256/128), 2,048 tokens, 100+ languages, MTEB multilingual 61.15, Gemma licence (https://huggingface.co/google/embeddinggemma-300m).
- Runtime: `swift-embeddings` (https://github.com/jkrukowski/swift-embeddings) runs BERT/MiniLM/XLM-R(e5)/Model2Vec/Qwen3 embeddings in Swift on MLTensor via SPM; min OS not stated. On-device latency: unknown (not published); expect tens of ms per page chunk on A17/M-class.
- Embeddings from different models are not comparable, so pick one per index and store `embedding_model` with each vector; re-embed in the background on a model change.

**On-device vector stores**:
- `sqlite-vec` (https://github.com/asg017/sqlite-vec, https://alexgarcia.xyz/sqlite-vec/features/vec0.html): pure C, MIT/Apache, v0.1.9 stable (2026-03-31), pre-v1 ("expect breaking changes"); v0.1.10 alphas add ANN (rescore, IVF experimental, DiskANN). `vec0` tables: float/int8/binary vectors, `distance_metric=cosine`, KNN via `MATCH ... AND k = N`, up to 16 metadata columns (TEXT/INTEGER/FLOAT/BOOLEAN; `=,!=,<,>` filters applied during KNN), up to 4 partition-key columns (pre-filtering by e.g. `user_id`), auxiliary `+` columns for payload. No official Swift package; community `SQLiteVec` SPM package exists (https://github.com/jkrukowski/SQLiteVec; API `SQLiteVec.initialize()`, `Database`, vec0 tables) but platform support is undocumented. Since it is a loadable/static extension, it must be compiled into the app with the SQLite it uses (GRDB custom build or the package's own build) because system SQLite is built with `SQLITE_OMIT_LOAD_EXTENSION`-style restrictions (from memory; verify).
- `USearch` (https://github.com/unum-cloud/usearch): HNSW, Apache-2.0, Swift/iOS via `Package.swift`, f16/bf16/i8/b1 quantization, memory-mapped on-disk indexes, predicate filtering supported in the Swift binding.
- `ObjectBox` (https://docs.objectbox.io/on-device-vector-search): HNSW inside an object database with Swift support; pricing/licensing for commercial use not on the docs page.
- Faiss: C++ and heavy; no reason to use it in-app.
- At personal scale (≤100k vectors × 256 int8 dims = 25 MB) brute-force in sqlite-vec is single-digit milliseconds; ANN is unnecessary until the service phase.

**Hybrid ranking**: Reciprocal Rank Fusion, `score(d) = Σ_r 1/(k + rank_r(d))`, k=60 (Cormack, Clarke, Büttcher, SIGIR 2009, http://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf). The paper reports RRF beat Condorcet Fuse and CombMNZ and the best single system by 4–5% MAP on TREC runs; the choice of k "was not critical". Anthropic's contextual-retrieval study (https://www.anthropic.com/news/contextual-retrieval) measured top-20 retrieval failure rates: 5.7% baseline → 3.7% with contextual embeddings (−35%) → 2.9% with contextual embeddings + contextual BM25 (−49%) → 1.9% adding a reranker (−67%); contextualizing chunks costs ≈ $1.02 per million document tokens with prompt caching; recommended "retrieve top 150, rerank to top 20". For this archive the natural "context" for each page chunk is the document's own title/sender/date line, which you already have from extraction, so prepend it to each chunk before embedding at zero LLM cost.

### 2e. Server-side search engines for the service phase

| Engine | Multi-tenancy | Hybrid | Cost signal (fetched) | Notes |
|---|---|---|---|---|
| Postgres FTS + pgvector 0.8.7 (https://github.com/pgvector/pgvector) | `tenant_id` column + RLS; partial indexes per tenant | FTS (`tsvector`, `ts_rank_cd`) + HNSW/IVFFlat, fused in SQL with RRF; iterative index scans (0.8.0) fix filtered-recall gaps | Supabase Free: 500 MB DB; Pro $25/mo incl. 8 GB; Micro compute $10/mo (https://supabase.com/pricing) | One datastore for everything; `vector` indexable ≤2,000 dims, `halfvec` ≤4,000, `bit` ≤64,000; tsvector ≤1 MB, positions ≤16,383 (https://www.postgresql.org/docs/current/textsearch-limitations.html) so index per page, not per document |
| ParadeDB pg_search (https://github.com/paradedb/paradedb) | same as Postgres | Tantivy BM25 + facets inside Postgres; hybrid with pgvector | AGPL-3.0 community; Enterprise commercial / ParadeDB Cloud | Better BM25 than built-in FTS; AGPL is fine for a SaaS backend you do not distribute |
| Meilisearch (https://www.meilisearch.com/docs/learn/security/multitenancy_tenant_tokens) | **Tenant tokens**: backend signs a search-only JWT embedding filter rules (`user_id = 123`); indexing/settings stay behind API keys | Embedders: `openAi`, `huggingFace`, `ollama`, `rest` (works with Voyage), `userProvided` (dimensions required); `semanticRatio` tuning | Self-host MIT free; Cloud from $20–30/mo (100k docs / 50k searches) or XS 0.5 vCPU/1 GB $23/mo | Easy typo-tolerance and facets out of the box |
| Typesense (https://typesense.org/docs/latest/api/api-keys.html, .../vector-search.html) | **Scoped search keys** generated client-side via HMAC embedding `filter_by`, with `expires_at`; parent key must be `documents:search` only | Built-in `ts/e5-small`, `ts/all-MiniLM-L12-v2`, remote OpenAI/Vertex, or user-provided `float[]`; hybrid rank fusion default 0.7 keyword / 0.3 vector (`alpha`), `rerank_hybrid_matches`, `flat_search_cutoff` | Cloud: 0.5 GB RAM smallest node, prices only in calculator; HA = 3–7 nodes | Very fast, but RAM-resident |
| Qdrant (https://qdrant.tech/documentation/guides/multiple-partitions/, .../hybrid-queries/) | One collection, `group_id` payload with `is_tenant: true` keyword index (v1.11+); tiered multitenancy v1.16+; ≤1,000 collections per cloud cluster | `prefetch` dense + sparse (BM25) with `rrf` (k default 2, weighted v1.17+) or `dbsf`; ColBERT rescoring; formula queries with date decay (v1.14+) | Free tier 0.5 vCPU / 1 GB / 4 GB forever (https://qdrant.tech/pricing/) | Strong vector-first option; still needs Postgres for metadata |
| Turbopuffer (https://turbopuffer.com/pricing) | One **namespace per user** (100K docs per namespace included) | BM25 + vector in one query | Storage ≤$0.33/GB, writes ≤$2/GB (10 KB min), queries ≤$1/PB; **$16/mo minimum** (Launch), $256 (Scale) | Object-storage backed; cheapest per-tenant isolation model for many tiny tenants |
| OpenSearch Serverless (https://aws.amazon.com/opensearch-service/pricing/) | index per tenant or filters | k-NN + BM25 + RRF/normalization processors | $0.24/OCU-hr; classic minimum 2 OCUs ≈ $350/mo, dev/test 1 OCU ≈ $175/mo; "NextGen" collections scale to zero | Overkill until thousands of tenants |

Claude Files API note for the service phase: files are **workspace-scoped**, not user-scoped; Anthropic recommends one workspace per tenant (≤100 workspaces/org) for hard isolation (https://platform.claude.com/docs/en/build-with-claude/files). So do not persist user PDFs in the Files API; send them per request (base64 ≤128 MB, ≤600 pages with 1M context) or with short `expires_in_seconds`.

### 2f. RAG / question answering over the archive

- Pipeline: NL query → filter+hybrid retrieval (top 150 chunks) → optional `rerank-3-lite` → top 20 chunks (or whole documents when ≤ ~30 pages) → Claude with `citations: {enabled: true}` on each `document` block.
- Citations (https://platform.claude.com/docs/en/build-with-claude/citations): supported on all active models incl. Haiku 5.5; document types plain text (`char_location`), PDF (`page_location`, 1-indexed, exclusive end), custom content blocks (`content_block_location`, you choose the chunk granularity); `cited_text` does not count toward output tokens, and citations work with prompt caching (`cache_control` on the document block) and the Batch API (50% off).
- For aggregations ("total medical spend in 2024") do not ask the model to add numbers from 40 PDFs. Use the extracted `amount_*` fields: the query parser emits `aggregate: sum(amount_paid) where doc_type=medical and date in 2024`, SQL computes it, and Claude (if invoked at all) only phrases the answer and cites the rows. Fall back to document-level RAG only when the aggregate field is missing or low-confidence.
- PDF input costs (https://platform.claude.com/docs/en/build-with-claude/pdf-support): 1,500–3,000 text tokens per page plus image tokens per page; max 600 pages / 128 MB per request on the 1M-context models (100 pages under 1M). Prefer sending the OCR text layer as `text` or `content` documents; send the PDF image only when visual understanding is needed.

### 2g. Searchability inside the destination storage

- **Google Drive**: `fullText contains 'x'` matches "name, description, indexableText properties, or text in the file's content or metadata" (https://developers.google.com/workspace/drive/api/guides/ref-search-terms). Drive "automatically indexes documents for search when it recognizes the file type, including text documents, PDFs, images with text" (https://developers.google.com/workspace/drive/api/guides/file). `files.create` accepts `ocrLanguage` (ISO 639-1 hint for image import) and `useContentAsIndexableText`; `contentHints.indexableText` is capped at 128 KB and is a good place to put the Claude summary + tags + sender so Drive search finds the document by concepts, not just OCR tokens. Also set `description` to the summary and `properties`/`appProperties` to doc_type, tax_year, sender_key for programmatic filtering.
- **Synology** (DSM 7.4 spec, https://www.synology.com/en-global/dsm/7.4/software_spec/search_indexing): Universal Search content-indexes PDF, Office, OpenDocument and plain text (plus media metadata); up to 1,000 indexed folders; files that need excessive memory fall back to filename indexing; **semantic indexing** of PDFs up to 30 MB (200 KB for plain text) is available only on Synology Drive Team Folders; OCR is not mentioned (so a text layer is mandatory); not available for cloud/remote/USB folders. Keep the folder tree and filename convention meaningful (`2025/Bills/ConEdison/2025-03-14_ConEdison_bill_$142.17.pdf`) so filename search works even without content indexing.
- **iCloud Drive / Files**: Apple's Files-app search docs could not be fetched in this run; from memory, Spotlight on macOS indexes PDF text via the built-in PDF importer and the iOS Files app search is primarily by name plus Spotlight content for locally present files (unverified). Embed the summary and tags in PDF metadata (`Title`, `Subject`, `Keywords`) and XMP so any indexer that reads metadata gets the semantics.
- Common denominator: an archival PDF/A-2b with an invisible OCR text layer, PDF metadata fields filled from the Claude extraction, and a sidecar `.json` next to each file (schema above) makes every destination searchable and lets a future version of the app rebuild its index from the files alone.

### 2h. Evaluating search quality

- Build a labelled set from real mail: 150–300 natural-language queries authored by 3+ people, each with the set of relevant doc_ids (graded 0/1/2). Keep ~30% "hard" cases: OCR-mangled names, relative dates, multi-constraint queries, aggregates.
- Metrics: nDCG@10 (ranking quality), Recall@20 (what the RAG step sees), MRR (single-answer queries), and for aggregate questions exact-match on the computed number. Use `ranx` (https://github.com/AmenRa/ranx; nDCG/MAP/MRR/Recall validated against trec_eval, RRF/CombSUM fusion, paired t-test, `optimize_fusion` for RRF weights).
- Measure latency separately: p50/p95 for on-device parse+search (target <50 ms), for the Claude query-parse (target <1.5 s), and end-to-end for QA.
- Track extraction quality upstream (field-level accuracy per doc_type on a 200-document gold set) because most search failures will be extraction failures.
- Red flags to test explicitly: duplicate detection (same page scanned twice must not appear twice), a sender renamed by OCR ("ConEd" vs "Con Edison"), and tax_year vs doc_date confusion (a 1099 dated Jan 2025 is tax_year 2024).

---

## 3. Options compared

| Decision | Option A | Option B | Option C | Pick for v1 | Pick for v2 |
|---|---|---|---|---|---|
| Lexical index | SQLite FTS5 (porter + trigram), via GRDB | Core Spotlight only | Server search engine | A (+ Spotlight donation) | Postgres FTS or ParadeDB BM25 |
| Query understanding | Deterministic grammar + NSDataDetector | Apple Foundation Models `@Generable` (iOS 26, AI devices) | Claude Haiku 5.5 JSON schema | A instantly, C async refine; B when available | C with prompt caching |
| Embeddings | Voyage voyage-4-lite 256-d int8 | On-device MiniLM/bge-small 384-d | Apple NLContextualEmbedding | A (free tier) with B as offline fallback | A (voyage-4 or context-4) |
| Vector store | sqlite-vec vec0 (brute force) | USearch HNSW | ObjectBox | A | pgvector (HNSW) or Turbopuffer |
| Fusion | RRF k=60 | Weighted linear (Typesense alpha) | Cross-encoder rerank | A | A + rerank-3-lite |
| Reranking | none | Voyage rerank-3-lite | Claude re-score | A | B |
| Tenant isolation (v2) | Postgres RLS + tenant_id | Meilisearch tenant tokens / Typesense scoped keys | Turbopuffer namespace per user | – | A, B only if facets/typo-tolerance UX needs it |
| QA | Fielded SQL aggregates + Claude phrasing | Full RAG with citations | Send whole PDFs | A, B fallback | A + B |

---

## 4. Recommendation for this project

**v1 (on-device, single user, iOS 17+ baseline, iOS 26 extras):**

1. **Schema first.** Implement the extraction JSON schema above as a Swift `Codable` + the Claude JSON schema (hand-written, `additionalProperties:false`, enums for `doc_type`). Version it (`schema_version`) in every row and in the sidecar JSON written next to each PDF.
2. **Indexing pipeline per captured page** (all off the main thread, each step idempotent and journaled so a crash never loses a page): perceptual hash + OCR → page row → when document boundary is confirmed, one Haiku 5.5 call (`effort: low`, structured output, OCR text in, prompt-cached system prompt with the user's existing sender vocabulary) → write `documents`, FTS (external-content, porter+unicode61, weights title 10 / tags 5 / summary 3 / sender 3 / text 1), trigram table, facets → Voyage `voyage-4-lite` embedding of `title + sender + date line + each ~300-token chunk`, stored int8 256-d in sqlite-vec with `doc_type`/`tax_year` metadata columns → Core Spotlight donation (`title`, `textContent` = summary + first 2k chars, `keywords` = tags, `contentURL`, named index with `.complete` protection) → PDF metadata + sidecar JSON → upload. If no network, mark `needs_enrichment` and search by OCR text alone; everything is re-runnable.
3. **Query path.** Parse locally (<10 ms): dates/relative periods, doc_type synonyms, known senders, amounts; remaining words → FTS `MATCH` (porter) OR trigram; semantic branch via on-device MiniLM/bge-small (swift-embeddings) if the query has ≥3 content words, else skip; RRF; apply filters as SQL `WHERE`. In parallel fire Haiku 5.5 for the structured parse plus a Voyage query embedding; when they return, re-run and animate the result list update only if the result set changed. Show facet chips (doc_type, year, sender) derived from the current result set so a "zero-typing" refinement is possible.
4. **QA.** "How much did I pay X in Y" is a SQL aggregate over `amount_paid` with the document list as evidence. Only free-form questions go to Claude with `citations` over the top 20 chunks (`content` documents with per-chunk blocks so citations point at page + chunk).
5. **Ship an eval harness on day one**: 150 labelled queries over the founder's own mail, `ranx` nDCG@10/Recall@20, run on a Mac in CI against the same SQLite file the app produces.
6. **Verify immediately** (cheap, decision-critical): `PRAGMA compile_options` on iOS 17/18/26 devices for `ENABLE_FTS5`, and whether the system SQLite version ≥3.34 (trigram). If FTS5 is missing, switch GRDB to its custom SQLite build (also the natural home for sqlite-vec).

**v2 (service, multi-tenant):**

1. Keep the on-device index as the primary UX (it is what makes search feel instant); the server index exists for web access, cross-device consistency and heavy QA.
2. Postgres (managed; Supabase or RDS) with `tenant_id` + RLS on every table, `pages.tsv` (`tsvector`, per page to stay under 1 MB), pgvector `halfvec(1024)` HNSW with `tenant_id` partial indexes or `iterative scan` enabled, RRF in SQL. Promote to ParadeDB `pg_search` if BM25 quality or faceting in Postgres FTS disappoints; move vectors to Turbopuffer (namespace = user) if the pgvector index outgrows RAM.
3. Embeddings: `voyage-4` or `voyage-context-4` (document-aware chunks), batch endpoint, int8; `rerank-3-lite` on the top 150 for QA.
4. Query parsing and QA: Haiku 5.5 with the same schema; Sonnet 5.5 only for multi-document synthesis. Prompt-cache the per-tenant vocabulary. Use the Batch API (50% off) for backfills and re-embeds.
5. Do not use the Anthropic Files API as a document store (workspace-scoped; 100 workspaces max per org).

---

## 5. Risks and unknowns

- **FTS5 / trigram availability in iOS system SQLite** is unverified in this run; worst case requires a custom SQLite build (adds ~1–2 MB, well-trodden path with GRDB).
- **sqlite-vec is pre-v1** with breaking changes and no official Swift package; the community `SQLiteVec` package's iOS support is undocumented. USearch is the safer fallback if integration stalls.
- **Haiku 5.5 latency** has no official numbers; the only third-party TTFT figure found is anomalous. Must be measured with `effort: low` and a 60-token schema before committing to "refine results in <1.5 s".
- **Adaptive thinking** is on by default on Haiku 5.5; forgetting `effort: low` (or leaving long `@Guide`-style descriptions in the schema) will quietly add seconds and tokens.
- **Voyage free tier terms** (200M tokens per model) are per-account, not per end user; in the service phase embeddings become a real (small) cost: $0.02–0.12 per million tokens ≈ $0.00005–0.0003 per page.
- **Apple Foundation Models** need Apple-Intelligence hardware and iOS 26; the 4,096-token on-device context rules out document-level extraction on-device, so it is a query-parser and tagger, not an extractor.
- **Core Spotlight semantic index** behaviour (what exactly is embedded, limits on `textContent`) is undocumented; treat it as best-effort discoverability, not the primary ranker.
- **Postgres FTS limits** (1 MB tsvector, 16,383 positions) require per-page indexing; built-in FTS lacks BM25 (ts_rank is not BM25) so quality may lag Meilisearch/Typesense/ParadeDB.
- **Drive/Synology content indexing is asynchronous and opaque** (no SLA, Synology falls back to filename indexing for memory-heavy files); never rely on destination search as the only index.
- **Semantic drift when changing embedding models**: vectors from different models are incompatible; plan background re-embedding and store the model id per vector.
- Information gathered here was limited to direct fetches; competitive benchmarks (MTEB leaderboard page would not render) and some Apple pages (Files app search) were not readable.

---

## 6. Open questions for the founder

1. Minimum iOS version for v1: iOS 17 (NLContextualEmbedding, broad base) or iOS 26 (Foundation Models, better Spotlight)? This decides whether the on-device NL parser is a grammar or an LLM.
2. Is a bring-your-own Voyage key acceptable for v1 (like your existing Keychain-stored Anthropic key), or should v1 be strictly Anthropic-key-only with on-device embeddings?
3. How large is your real archive (pages/year) and how many years of backlog will be scanned at once? This sets the embedding/extraction batch strategy and whether brute-force vectors suffice.
4. Which languages must be searchable? (Affects tokenizer choice, `NLTagger` NER coverage, and whether `voyage-4` multilingual matters.)
5. Is per-document (letter) or per-page the unit of search results you want to see? (Affects chunking, Spotlight items, and PDF splitting.)
6. Should search also cover the *images* of pages (handwritten notes, stamps) via multimodal embeddings, or is OCR text sufficient for v1?
7. For the service: single-region US hosting acceptable? Any requirement for customer-managed keys or on-prem (Synology-hosted) index for privacy-sensitive users?
8. Do you want Claude to be allowed to answer money questions from PDFs (RAG) or only from extracted fields with a "verify" link? (Trust/UX decision.)

---

## 7. Sources

- SQLite FTS5: https://www.sqlite.org/fts5.html
- GRDB README (7.12.0, iOS 13+, system SQLite): https://raw.githubusercontent.com/groue/GRDB.swift/master/README.md
- GRDB Full-Text Search guide: https://raw.githubusercontent.com/groue/GRDB.swift/master/Documentation/FullTextSearch.md
- Core Spotlight CSUserQuery: https://developer.apple.com/tutorials/data/documentation/corespotlight/csuserquery.json
- Core Spotlight CSUserQueryContext: https://developer.apple.com/tutorials/data/documentation/corespotlight/csuserquerycontext.json
- Core Spotlight CSSearchQueryContext: https://developer.apple.com/tutorials/data/documentation/corespotlight/cssearchquerycontext.json
- Core Spotlight: building a search interface: https://developer.apple.com/tutorials/data/documentation/corespotlight/building-a-search-interface-for-your-app.json
- Core Spotlight: adding content to indexes: https://developer.apple.com/tutorials/data/documentation/corespotlight/adding-your-app-s-content-to-spotlight-indexes.json
- Core Spotlight textContent: https://developer.apple.com/tutorials/data/documentation/corespotlight/cssearchableitemattributeset/textcontent.json
- WWDC24 "Support semantic search with Core Spotlight": https://developer.apple.com/videos/play/wwdc2024/10131/
- NLContextualEmbedding: https://developer.apple.com/tutorials/data/documentation/naturallanguage/nlcontextualembedding.json
- NLEmbedding: https://developer.apple.com/tutorials/data/documentation/naturallanguage/nlembedding.json
- NLTagger: https://developer.apple.com/tutorials/data/documentation/naturallanguage/nltagger.json
- NSDataDetector: https://developer.apple.com/tutorials/data/documentation/foundation/nsdatadetector.json
- Foundation Models framework: https://developer.apple.com/tutorials/data/documentation/foundationmodels.json
- Foundation Models context window (4,096 tokens): https://developer.apple.com/tutorials/data/documentation/foundationmodels/managing-the-context-window.json
- Foundation Models guided generation: https://developer.apple.com/tutorials/data/documentation/foundationmodels/generating-swift-data-structures-with-guided-generation.json
- Foundation Models SystemLanguageModel: https://developer.apple.com/tutorials/data/documentation/foundationmodels/systemlanguagemodel.json
- Foundation Models content tagging: https://developer.apple.com/tutorials/data/documentation/foundationmodels/categorizing-and-organizing-data-with-content-tags.json
- Claude structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Claude models overview: https://platform.claude.com/docs/en/about-claude/models/overview
- Claude Haiku 5.5 overview and pricing: https://platform.claude.com/docs/en/models/haiku-5-5/overview
- Claude reduce latency: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency
- Claude citations: https://platform.claude.com/docs/en/build-with-claude/citations
- Claude PDF support: https://platform.claude.com/docs/en/build-with-claude/pdf-support
- Claude Files API: https://platform.claude.com/docs/en/build-with-claude/files
- Anthropic contextual retrieval: https://www.anthropic.com/news/contextual-retrieval
- Artificial Analysis Haiku 5.5 (third-party, anomalous TTFT): https://artificialanalysis.ai/models/claude-haiku-5-5
- Voyage embeddings: https://docs.voyageai.com/docs/embeddings
- Voyage pricing: https://docs.voyageai.com/docs/pricing
- Voyage rerankers: https://docs.voyageai.com/docs/reranker
- Voyage multimodal: https://docs.voyageai.com/docs/multimodal-embeddings
- Voyage contextualized chunk embeddings: https://docs.voyageai.com/docs/contextualized-chunk-embeddings
- EmbeddingGemma: https://huggingface.co/google/embeddinggemma-300m
- all-MiniLM-L6-v2: https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2
- bge-small-en-v1.5: https://huggingface.co/BAAI/bge-small-en-v1.5
- swift-embeddings: https://github.com/jkrukowski/swift-embeddings
- sqlite-vec: https://github.com/asg017/sqlite-vec ; releases: https://github.com/asg017/sqlite-vec/releases ; vec0 docs: https://alexgarcia.xyz/sqlite-vec/features/vec0.html ; KNN: https://alexgarcia.xyz/sqlite-vec/features/knn.html
- SQLiteVec Swift package: https://github.com/jkrukowski/SQLiteVec
- USearch: https://github.com/unum-cloud/usearch
- ObjectBox vector search: https://docs.objectbox.io/on-device-vector-search
- RRF paper (Cormack, Clarke, Büttcher 2009): http://cormack.uwaterloo.ca/cormacksigir09-rrf.pdf
- pgvector: https://github.com/pgvector/pgvector
- Postgres FTS limitations: https://www.postgresql.org/docs/current/textsearch-limitations.html
- ParadeDB: https://github.com/paradedb/paradedb
- Supabase pricing: https://supabase.com/pricing
- Meilisearch tenant tokens: https://www.meilisearch.com/docs/learn/security/multitenancy_tenant_tokens ; settings/embedders: https://www.meilisearch.com/docs/reference/api/settings ; AI search: https://www.meilisearch.com/docs/learn/ai_powered_search/getting_started_with_ai_search ; pricing: https://www.meilisearch.com/pricing
- Typesense API keys (scoped): https://typesense.org/docs/latest/api/api-keys.html ; vector search: https://typesense.org/docs/latest/api/vector-search.html ; cloud pricing: https://cloud.typesense.org/pricing ; billing: https://cloud-help.typesense.org/article/billing-process
- Qdrant multitenancy: https://qdrant.tech/documentation/guides/multiple-partitions/ ; hybrid queries: https://qdrant.tech/documentation/concepts/hybrid-queries/ ; pricing: https://qdrant.tech/pricing/
- Turbopuffer pricing: https://turbopuffer.com/pricing
- LanceDB: https://docs.lancedb.com/
- OpenSearch Service pricing: https://aws.amazon.com/opensearch-service/pricing/
- Google Drive search terms: https://developers.google.com/workspace/drive/api/guides/ref-search-terms ; file guide / indexable text: https://developers.google.com/workspace/drive/api/guides/file ; files.create (ocrLanguage): https://developers.google.com/workspace/drive/api/reference/rest/v3/files/create
- Synology DSM 7.4 search & indexing spec: https://www.synology.com/en-global/dsm/7.4/software_spec/search_indexing
- ranx: https://github.com/AmenRa/ranx
