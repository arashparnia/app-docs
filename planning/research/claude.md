# Claude API pipeline design for the zero-interaction paper digitizer

Research date: 2026-11-03. Primary sources: the bundled `claude-api` skill on disk (`<bundled claude-api reference skill>`, files `shared/models.md`, `shared/prompt-caching.md`, `shared/platform-availability.md`, `shared/cost-optimization.md`, `shared/tool-use-concepts.md`, `curl/examples.md`, `shared/live-sources.md`) cross-checked against the live docs on platform.claude.com fetched today. Where the two disagree I say so and prefer the live page.

## 1. Executive summary

- Use **`claude-haiku-5-5`** ($0.10 in / $0.50 out per MTok for prompts ≤100K tokens) for per-page classification + extraction, with **`thinking: {"type":"disabled"}` and `output_config.effort: "low"`**; escalate to **`claude-sonnet-5-5`** ($2 / $10) only for pages the Haiku pass marks `needs_review` or for long multi-page packets. `claude-opus-5-5` ($4 / $20, thinking cannot be disabled) has no role in the hot path.
- Send **both** the downscaled page image (~1,000–1,800 visual tokens at 100–130 DPI) and the on-device Apple Vision OCR text; one Haiku call then costs about **$0.0006–0.001 per page**, Sonnet about **$0.012**, Opus about **$0.03+**.
- The Artificial Analysis numbers are a warning, not a comfort: at default (reasoning-on) settings Haiku 5.5 shows **9–14 s** time-to-first-token on a 10K-token prompt, while Sonnet 5.5 at `low` shows **1.2 s**. Sub-second *feedback* must come from the device (frame quality, perceptual-hash dedupe, on-device OCR); the Claude call runs asynchronously, streamed, with `doc_type` as the first required property in the schema so the label arrives first.
- Structured outputs (`output_config.format`, type `json_schema`) are GA, work on all three models, stream, and are ZDR-eligible; a complete document-record schema is in §2.3.
- Prompt caching: 512-token minimum on all three models; cache reads cost 0.1x base on Haiku ($0.01/MTok) and 0.05x on Sonnet/Opus 5.5 ($0.10 / $0.20). One explicit breakpoint on the fixed taxonomy system prompt; keep schema, effort and thinking settings byte-stable or the cache misses.
- Privacy: commercial API data is not used for training; default deletion within 30 days; ZDR is per-organization via sales and covers Messages + vision + inline PDF + structured outputs + caching, but **not** Batches (29-day retention) or the Files API. Haiku/Sonnet/Opus 5.5 are not Covered Models, so ZDR is possible; HIPAA BAA is self-serve in the Console. `inference_geo: "us"` costs 1.1x.
- Keys never ship in the app. Ship a thin proxy (server-held key, per-user auth, App Attest), keep the founder's Keychain-BYOK path as an opt-in for power users only.
- Embeddings: Voyage 4 series (Jan 2026). `voyage-4-lite` at $0.02/MTok with 200M free tokens is the default; `voyage-multimodal-3.5` lets you embed the page image directly for ~$0.0012/page.

## 2. Findings

### 2.1 Model choice per pipeline stage

Live model lineup (https://platform.claude.com/docs/en/about-claude/models/overview.md and https://platform.claude.com/docs/en/about-claude/pricing.md):

| Model | ID | Input / Output $/MTok | Cache write 5m / 1h | Cache read | Batch in / out | Default effort | Thinking off? | Comparative latency | Released |
|---|---|---|---|---|---|---|---|---|---|
| Claude Haiku 5.5 | `claude-haiku-5-5` | $0.10 / $0.50 (≤100K prompt); $0.50 / $2.50 (>100K) | $0.125 / $0.20 | $0.01 | $0.05 / $0.25 | `medium` | Yes: `{"type":"disabled"}` at effort ≤ `high` | Fastest | 2026-10-07 |
| Claude Sonnet 5.5 | `claude-sonnet-5-5` | $2 / $10 | $2.50 / $4 | $0.10 (0.05x) | $1 / $5 | `high` | No `disabled` (400); lowest is `{"type":"between_tools"}` at effort ≤ `high` | Fast | 2026-09-28 |
| Claude Opus 5.5 | `claude-opus-5-5` | $4 / $20 | $5 / $8 | $0.20 (0.05x) | $2 / $10 | `medium` | No: thinking always on, effort is the only control | Moderate | (current Opus) |

All three: 1M context, 128K max output, Jun 2026 knowledge cutoff, vision, structured outputs, adaptive thinking, prompt caching, Batches, Files API (https://platform.claude.com/docs/en/models/haiku-5-5/overview, https://platform.claude.com/docs/en/models/sonnet-5-5/overview, https://platform.claude.com/docs/en/build-with-claude/thinking.md). All three reject `temperature`/`top_p`/`top_k` and assistant prefill with a 400 (https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5). Sonnet 5.5 and Opus 5.5 also reject forced `tool_choice` (`any`/`tool`), which is one more reason to use `output_config.format` rather than a "fake tool" for JSON extraction (local skill `shared/tool-use-concepts.md`).

**Discrepancy, local skill vs live docs:** the local `shared/models.md` says Sonnet 5.5 cache reads are "$0.20"; the live pricing page says **$0.10/MTok** (0.05x of $2). The live value is used throughout. The local `curl/examples.md` sends `anthropic-version: 2026-10-21`; the live examples still show `2023-06-01`. Both are accepted today, but the local skill notes that under `2026-10-21` *any* sampling parameter is rejected, so pick one version header and pin it.

Anthropic's own positioning: Haiku 5.5 is "for high-volume, latency-sensitive tasks such as classification, extraction, and routing"; the reduce-latency guide's example is literally Haiku 5.5 at `effort: "low"` (https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency.md). Effort guidance for Haiku 5.5: "Use `low`, the cheapest and fastest level, for … simple, high-volume requests"; thinking can be turned off with `{"type":"disabled"}` at `low`/`medium`/`high` (https://platform.claude.com/docs/en/build-with-claude/effort.md, https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5). Two documented Haiku 5.5 caveats matter here: (a) with thinking off *and* `output_config.format` *and* tools, it may skip a needed tool call (we have no tools in the extraction call, so not applicable); (b) with thinking off or at `low` it "sometimes writes reasoning-like text in the reply" (the JSON grammar prevents this in the structured call). Haiku 5.5 runs safety classifiers that can return `stop_reason: "refusal"` with no server-side fallback, so the client must handle that (retrying the same request usually refuses again).

Stage-by-stage recommendation (details in §4):

| Stage | Model | Settings | Why |
|---|---|---|---|
| Fast page classify + full record extraction (one call) | Haiku 5.5 | thinking disabled, effort `low`, structured output, streaming | Cheapest, fastest; grammar guarantees JSON |
| Escalation for `needs_review=true`, low confidence, handwriting, >20 pages, or non-Latin scripts | Sonnet 5.5 | `between_tools`, effort `low`→`medium`, same schema | Higher accuracy at 20x the price but still ~$0.01/page |
| Backfill / re-index of the whole archive (schema changes, new taxonomy) | Haiku 5.5 via Batches | 50% off, 1h cache TTL | Not latency-sensitive |
| NL search query → filter JSON | Haiku 5.5 | thinking disabled, effort `low`, tiny schema | ~100 output tokens, well under 1 s generation |
| Summaries for export packs, cross-document questions | Sonnet 5.5 | default | Quality matters, volume is low |
| Opus 5.5 | none in the pipeline | — | Thinking cannot be disabled; ~40x Haiku's price |

### 2.2 Image sizing, tokens, and what to send

Vision limits (https://platform.claude.com/docs/en/build-with-claude/vision.md, https://platform.claude.com/docs/en/build-with-claude/vision-coordinates.md):

- Formats: JPEG, PNG, GIF, WebP. Max 10 MB per image (base64) on the Claude API; 8000x8000 px hard cap; 600 images per request on 1M-context models, but **above 20 images per request a stricter per-image limit applies** (keep every edge ≤ 3,000 px, or stay ≤ 20 image/document blocks). Request body limit 128 MB.
- Token formula: an image costs `⌈width/28⌉ × ⌈height/28⌉` visual tokens (28x28 patches). Two tiers: **Standard** (max long edge 1,568 px, max 1,568 tokens) and **High-resolution** ("Claude 4.7 and later models": max long edge 2,576 px, max 4,784 tokens). Haiku 5.5, Sonnet 5.5 and Opus 5.5 are post-4.7 releases and the page lists them under the feature, so they are high-res tier (the page names the tier by generation rather than listing each ID; verify with one `count_tokens` call). Oversized images are downscaled aspect-preserving to the largest size that fits *both* limits; the token limit, not the edge limit, usually binds. The docs' own example: an A4 scan at 130 DPI (1075x1520) costs 39x55 = 2,145 tokens and is *not* resized on a high-res model.
- `transformations: {"oversized_image": "error"}` on an image block makes the API reject rather than silently downscale; `count_tokens` honors it and is the way to verify tier/size before inference.
- Lossy compression (JPEG/WebP) cuts request size and latency, but "heavy JPEG compression can make text difficult to read"; the doc says to inspect the actual bytes sent.

Token cost of a US-letter page at common capture sizes (computed with the published formula):

| Capture size (px) | ≈ DPI (letter) | Visual tokens (high-res tier) | Haiku 5.5 input cost | Sonnet 5.5 | Opus 5.5 |
|---|---|---|---|---|---|
| 850 x 1100 | 100 | 31x40 = 1,240 | $0.000124 | $0.00248 | $0.00496 |
| 1024 x 1325 | ~120 | 37x48 = 1,776 | $0.000178 | $0.00355 | $0.0071 |
| 1275 x 1650 | 150 | 46x59 = 2,714 | $0.000271 | $0.00543 | $0.0109 |
| 1700 x 2200 | 200 | 61x79 = 4,819 → downscaled to ≤4,784 | $0.000478 | $0.00957 | $0.0191 |
| 2550 x 3300 | 300 | downscaled to ≈4,784 | same as 200 DPI | same | same |

Anything above ~200 DPI letter is wasted; the model never sees it. Phone cameras produce 12–48 MP frames, so the app must resize on-device before upload (the vision guide explicitly recommends pre-resizing "to minimize latency").

**Image, OCR text, or both?** Send both, for different reasons:
- Apple Vision OCR text (the founder already has it on-device) is nearly free in tokens (a dense letter is ~600–1,200 tokens on the new tokenizer, which counts ~30% more tokens than Haiku 4.5's), gives Claude exact strings for account numbers and amounts, and is what you store for full-text search anyway.
- The image gives layout, logos, checkboxes, stamps, handwriting, signatures, and lets Claude correct OCR errors in digits. Send it at ~1,000–1,800 tokens (100–130 DPI equivalent), not 4,784.
- Text-only is a valid fallback for the Batch backfill of already-OCR'd archives and costs ~1/3 as much.

The PDF document block is the wrong input for freshly captured pages: the API rasterizes each page server-side at dimensions you don't control and bills **both** the extracted text (1,500–3,000 tokens/page) **and** the page image (https://platform.claude.com/docs/en/build-with-claude/pdf-support.md). Use it only for backfilling existing PDFs (§2.7).

### 2.3 Structured outputs: the document record schema

`output_config.format` with `type: "json_schema"` is GA (no beta header), supported on Haiku 5.5 / Sonnet 5.5 / Opus 5.5, works with streaming, Batches, token counting and thinking; incompatible with citations and prefill (https://platform.claude.com/docs/en/build-with-claude/structured-outputs.md). Rules that shape the schema:
- Supported: object/array/string/integer/number/boolean/null, `enum` (primitives only), `const`, `anyOf`/`allOf`, `$ref`/`$defs`, `required`, `additionalProperties: false`, string `format` (`date`, `date-time`, `uuid`, `email`, `uri`, …), nullable via `"type": ["string","null"]`, array `minItems` only 0 or 1.
- Not supported: `minimum`/`maximum`, `minLength`/`maxLength`, recursive schemas, regex lookarounds/backreferences. The Python/TS SDKs strip these and validate client-side; raw HTTP gets a 400.
- Complexity limits: 24 optional parameters across strict schemas, 16 union-typed parameters, 20 strict tools; "Schema is too complex" 400 and a 180 s compile timeout exist. Design consequence: make **every property required and nullable** rather than optional.
- **Property order is required-first, then optional, each in schema order** and output streams. Put `doc_type` and `duplicate_of_hint` first so the UI can label the page before the rest of the JSON arrives.
- First use of a new schema pays a grammar-compile latency (unspecified ms); compiled grammars are cached 24 h from last use; changing `name`/`description` does not invalidate, changing structure does. Changing `output_config.format` also invalidates the prompt cache. Keep the schema frozen per app version and warm it at deploy time.
- Do not ask for "reasoning" fields; that can trigger a `reasoning_extraction` refusal. A short `review_reason` string is fine.
- Enum values can come back with different casing; compare case-insensitively.
- Refusal (`stop_reason: "refusal"`) returns 200 and may not match the schema; `max_tokens` cut-off returns partial JSON.

Proposed schema (compact; all fields required, nullable where appropriate):

```json
{"type":"object","additionalProperties":false,
 "required":["doc_type","doc_subtype","language","sender","recipient","document_date","due_date","period_start","period_end","tax_year","amounts","identifiers","people","organizations","tags","title","summary","page_role","confidence","needs_review","review_reason"],
 "properties":{
  "doc_type":{"type":"string","enum":["invoice","bill","receipt","bank_statement","credit_card_statement","tax_form","tax_notice","payslip","insurance_policy","insurance_claim","medical_record","medical_bill","prescription","legal_contract","legal_notice","court_document","government_letter","utility","mortgage_loan","investment_statement","pension_retirement","vehicle","property","education","employment","travel","subscription_membership","personal_letter","marketing","warranty_manual","id_document","certificate","other"]},
  "doc_subtype":{"type":["string","null"],"description":"Free text, e.g. 'W-2', 'Form 1098', 'Explanation of Benefits'"},
  "language":{"type":"string","description":"BCP-47, e.g. en, de, fr"},
  "sender":{"$ref":"#/$defs/party"},
  "recipient":{"$ref":"#/$defs/party"},
  "document_date":{"type":["string","null"],"format":"date"},
  "due_date":{"type":["string","null"],"format":"date"},
  "period_start":{"type":["string","null"],"format":"date"},
  "period_end":{"type":["string","null"],"format":"date"},
  "tax_year":{"type":["integer","null"]},
  "amounts":{"type":"array","items":{"type":"object","additionalProperties":false,
     "required":["label","value","currency"],
     "properties":{"label":{"type":"string","enum":["total","amount_due","subtotal","tax","paid","balance","refund","premium","deductible","other"]},"value":{"type":"number"},"currency":{"type":"string","description":"ISO 4217"}}}},
  "identifiers":{"type":"array","items":{"type":"object","additionalProperties":false,
     "required":["kind","value"],
     "properties":{"kind":{"type":"string","enum":["account_number","invoice_number","policy_number","claim_number","case_number","reference","member_id","order_number","tax_id_last4","other"]},"value":{"type":"string"}}}},
  "people":{"type":"array","items":{"type":"string"}},
  "organizations":{"type":"array","items":{"type":"string"}},
  "tags":{"type":"array","items":{"type":"string"},"description":"3-8 lowercase tags, prefer taxonomy tags listed in the system prompt"},
  "title":{"type":"string","description":"Filename-safe, <= 80 chars, e.g. '2025-03-14 ComEd electricity bill'"},
  "summary":{"type":"string","description":"2-3 sentences, no reasoning"},
  "page_role":{"type":"string","enum":["single","first","continuation","last","blank","envelope"]},
  "confidence":{"type":"number","description":"0.0-1.0 overall extraction confidence"},
  "needs_review":{"type":"boolean"},
  "review_reason":{"type":["string","null"]}
 },
 "$defs":{"party":{"type":"object","additionalProperties":false,
   "required":["name","address","email","phone"],
   "properties":{"name":{"type":["string","null"]},"address":{"type":["string","null"]},"email":{"type":["string","null"]},"phone":{"type":["string","null"]}}}}}
```

(`confidence` cannot be range-constrained server-side; clamp client-side. `page_role` is what lets the backend stitch a multi-page letter captured as consecutive frames.)

Search-query schema (second, tiny call): `{"doc_types":[enum…],"date_from":date|null,"date_to":date|null,"tax_year":int|null,"sender_contains":string|null,"amount_min":number|null,"amount_max":number|null,"tags":[string],"free_text":string|null,"sort":enum}`. Haiku 5.5, thinking disabled, ~150 input / ~80 output tokens.

### 2.4 Prompt-caching layout

Live caching page (https://platform.claude.com/docs/en/build-with-claude/prompt-caching.md), consistent with the local `shared/prompt-caching.md` on these points:
- Minimum cacheable prefix **512 tokens** on Haiku 5.5, Sonnet 5.5, Opus 5.5 (1,024 on Sonnet 5; 4,096 on Haiku 4.5). Shorter prefixes silently don't cache.
- Write 1.25x base (5-min TTL) or 2x (1-hour); read 0.1x base, except **0.05x on Opus 5.5 and Sonnet 5.5**. Haiku 5.5: write $0.125 / $0.20, read $0.01 per MTok.
- Render order `tools → system → messages`; a breakpoint on the last system block caches everything before it. Up to 4 breakpoints; automatic caching (top-level `cache_control`) uses one slot.
- Invalidators relevant here: changing `output_config.format`; changing `thinking` type or top-level `effort` (rendered into the prompt; message-level breakpoints always miss and system breakpoints can miss); adding/removing images invalidates the *messages* cache but not system/tools. The structured-output format injects an extra system prompt ("adds input tokens").
- Cache reads don't count toward ITPM rate limits on these models, so caching also raises effective throughput (https://platform.claude.com/docs/en/api/rate-limits.md).

Layout for this pipeline: `system = [ {taxonomy + extraction rules + 2-3 compact worked examples, ~1,500-3,000 tokens, cache_control: ephemeral} ]`, then `messages = [ user: [image block, text block with OCR text + "page N of capture session"] ]`. Per-request content (date, user name, locale) goes in the user turn, never in `system`. Keep `model`, `thinking`, `effort`, `output_config.format` byte-identical across requests. For a single user scanning in bursts with gaps > 5 min, the 1-hour TTL on Haiku costs $0.20 vs $0.125 per MTok written, i.e. +$0.0002 per cold start on a 2,500-token prefix; for the multi-tenant service continuous traffic keeps the 5-minute entry warm and the 1h TTL is unnecessary. Cost of the cached prefix per page on Haiku: 2,500 x $0.01/MTok = $0.000025.

### 2.5 Latency expectations

Anthropic publishes only relative latency ("Fastest / Fast / Moderate"). Measured third-party figures (Artificial Analysis, first-party Anthropic API, median of the last 72 h, default workload now **10,000 input tokens**; TTFT includes thinking for reasoning variants, https://artificialanalysis.ai/methodology/performance-benchmarking):

| Model / setting | Output speed | TTFT (incl. thinking) | Time to first answer token | E2E for 500 output tokens | Source |
|---|---|---|---|---|---|
| Haiku 5.5 `low` (reasoning) | 167 t/s | 8.95 s | not shown | not shown | https://artificialanalysis.ai/models/claude-haiku-5-5-low |
| Haiku 5.5 `medium` | 176 t/s | — | 13.81 s | 16.77 s | https://artificialanalysis.ai/models/claude-haiku-5-5-medium/providers |
| Haiku 5.5 `max` | 235 t/s | 333.7 s | — | — | https://artificialanalysis.ai/models/claude-haiku-5-5 |
| Haiku 5.5 thinking **disabled** | **unknown** (AA notes "a non-reasoning variant may also exist" but publishes no numbers) | | | | |
| Sonnet 5.5 `low` | 105.7 t/s | **1.20 s** | — | — | https://artificialanalysis.ai/models/claude-sonnet-5-5-low |
| Sonnet 5.5 `medium` | 101 t/s | — | 1.15–1.23 s | 6.24 s | https://artificialanalysis.ai/models/claude-sonnet-5-5-medium/providers |
| Sonnet 5.5 `high` | 103 t/s | 10.95 s | — | — | search result, AA page |

Read-across for our ~2.5K-token request (one ~1,700-token image + ~800 tokens text + cached system prompt): prompt processing is shorter than the 10K benchmark, so TTFT without thinking should be at or below Sonnet's 1.2 s figure; the dominant cost is **output generation**: a ~400-token record at ~170 t/s is ~2.4 s on Haiku, ~4 s on Sonnet at ~100 t/s. Realistic end-to-end for the full record is therefore **~3–4 s on Haiku with thinking off**, not sub-second. Hence: (1) the sub-second signal (page captured, duplicate detected, rough type from on-device heuristics) must be local; (2) stream the JSON and surface `doc_type` as the first property; (3) keep the record short (no long summaries in the hot path; summaries can be a Batch job); (4) measure Haiku-with-thinking-disabled yourself with `count_tokens` + wall-clock, because nobody publishes it. Priority Tier is no longer sold and never covered the 5.5 models (https://platform.claude.com/docs/en/api/service-tiers.md); Fast mode exists only for Opus (Opus 5.5 at $8/$40), so there is no paid latency lever for Haiku.

### 2.6 Message Batches for backfill

https://platform.claude.com/docs/en/build-with-claude/batch-processing.md: 50% off every token including cache reads/writes; up to 100,000 requests or 256 MB per batch; most finish < 1 h, hard 24 h expiry (expired requests not billed); results downloadable for 29 days; supports vision, PDFs, structured outputs, thinking, caching (best-effort hits; use the 1-hour TTL); not `stream`, not `speed`, not `max_tokens: 0`; the 300K-output beta exists. Batch rate limits are separate: Start tier 1,000 RPM, 200,000 requests in queue (https://platform.claude.com/docs/en/api/rate-limits.md). Batch prices: Haiku 5.5 $0.05 / $0.25, Sonnet 5.5 $1 / $5, Opus 5.5 $2 / $10 per MTok. Batches are **not ZDR-eligible and not HIPAA-eligible** (29-day retention). Use for: re-tagging the whole archive when the taxonomy changes, generating long summaries/embedding text, and importing a user's existing Drive/NAS PDF archive.

### 2.7 Files API and PDF input for multi-page documents

Files API (https://platform.claude.com/docs/en/build-with-claude/files.md): GA, no beta header; 500 MB per file, 1 TB per org; uploads/list/delete are free; file bytes are billed as input tokens when referenced; optional `expires_in_seconds` (1 h – 90 d); uploaded files are **not downloadable**; files are **workspace-scoped, not user-scoped** ("never accept `file_id` values from end users"; the doc recommends one workspace per tenant for hard isolation, max 100 workspaces per org); ~500 file requests/min; **not ZDR/HIPAA eligible**. PDF input (https://platform.claude.com/docs/en/build-with-claude/pdf-support.md): up to 600 pages per request (1M-context models), 128 MB request, each page = 1,500–3,000 text tokens + image tokens, inline PDFs via Messages are ZDR- and HIPAA-eligible (via Files API they are not). For a 60-page tax packet this is ~60 x (2,000 + ~2,700) ≈ 280K tokens, which on Haiku 5.5 crosses the 100K threshold and is billed at $0.50/$2.50 instead of $0.10/$0.50. Design: for captured paper, send pages as image blocks in groups of ≤ 20 per request with a `page_role` stitch; split long packets into ≤ 100K-token requests on Haiku or send them to Sonnet; reserve `document` blocks + Files API for backfilling existing PDFs through Batches.

### 2.8 Privacy, retention, ZDR, HIPAA, residency

- Default: "we automatically delete inputs and outputs on our backend within 30 days"; flagged policy violations kept up to 2 years, classifier scores 7 years, feedback submissions 5 years (https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data, dated 2026-07-01).
- Training: "we will not use your inputs or outputs from our commercial products" to train models, except explicit feedback/bug reports or opt-in (https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training, 2026-08-18). The vision FAQ repeats that uploaded images are not used for training.
- ZDR (https://platform.claude.com/docs/en/manage-claude/api-and-data-retention.md): enabled per organization by the sales/account team; covers `/v1/messages` and `count_tokens` for eligible features. Eligible: vision, inline PDF, structured outputs ("qualified": only the JSON schema is cached ≤ 24 h), prompt caching (KV cache in memory for the TTL), effort/thinking, data residency. **Not eligible**: Batches (29 days), Files API, code execution/programmatic tool calling. **Covered Models** that *require* 30-day retention and are excluded from ZDR: Claude Fable 5.1, Mythos 5.1, Fable 5, Mythos 5 — Haiku 5.5 / Sonnet 5.5 / Opus 5.5 are not on that list.
- HIPAA: standard BAA is self-serve in the Console (Data retention page → HIPAA compliance card); enablement is permanent and the API 400s on non-eligible features; PHI must not appear in JSON schema definitions (property names, enums, consts, patterns); not available on Claude Platform on AWS; beta features generally excluded. Relevant because the inbox contains medical bills/EOBs.
- Data residency (https://platform.claude.com/docs/en/manage-claude/data-residency.md): `inference_geo: "global"` (default) or `"us"` (1.1x on all token categories, including Haiku's >100K tier); workspace geo currently `"us"` only; no EU option; also accepted inside Batches; rate limits shared across geos.

### 2.9 Rate limits and usage tiers

https://platform.claude.com/docs/en/api/rate-limits.md: new orgs may start in an **Evaluation** tier with limits below the published ones. Standard tiers and monthly spend caps: Start $500, Build $1,000, Scale $200,000, Custom uncapped. Per-model limits for Haiku 5.5 and Sonnet 5.5 (separate buckets): Start 4,000 RPM / 2M ITPM / 400K OTPM; Build 10,000 / 5M / 1M; Scale 13,000 / 10M / 2M. Only uncached input tokens count toward ITPM. At ~2,700 uncached tokens and ~400 output tokens per page, Start tier allows roughly **700 pages/min** on ITPM (1,000 on OTPM), Scale ~3,700/min. Token-bucket enforcement means bursts can 429 even under the per-minute number; `retry-after` is returned except on the spend-cap 429 (`enforced_spend_limit_reached`). Workspaces can carry lower per-workspace rate and spend limits, which is how to fence a tenant.

### 2.10 BYO key vs server-held key

Anthropic's SDKs disable browser use by default "to avoid exposing your secret API credentials" (https://github.com/anthropics/anthropic-sdk-typescript README), and the key best-practices article says never to put keys in code or configuration files and to rotate every ~90 days and set spend/workspace limits as a safeguard against leaked keys (https://support.claude.com/en/articles/9767949-api-key-best-practices-keeping-your-keys-safe-and-secure). There is no official Swift SDK; community SDKs (e.g. SwiftAnthropic) say production requests must route through your own backend. Implications:
- **Product/service mode**: the app talks only to your proxy (Sign in with Apple → short-lived JWT; App Attest/DeviceCheck; per-user quotas). The proxy holds one workspace-scoped key per environment, sets `inference_geo`, enforces the fixed schema/system prompt (so caching stays warm across all users), logs `usage` for cost attribution, and handles `refusal`, 429 `retry-after`, and `max_tokens`. Files API IDs never reach clients. Workspaces are a per-*tenant* (B2B) boundary at most 100 per org, not a per-consumer boundary.
- **BYOK mode** (the founder's existing Keychain pattern): legitimate for power users who want zero shared infrastructure, but the user then bears rate limits/spend caps, the key is extractable from a jailbroken device, and you cannot guarantee caching, schema version, or `inference_geo`. Keep it as an opt-in "advanced" path, still on-device only, never synced via CloudKit in plaintext.

### 2.11 Embeddings (Voyage AI)

Current lineup (https://docs.voyageai.com/docs/embeddings, https://docs.voyageai.com/docs/pricing, https://blog.voyageai.com/2026/01/15/voyage-4/, https://docs.voyageai.com/docs/multimodal-embeddings, https://docs.voyageai.com/docs/contextualized-chunk-embeddings): the **Voyage 4** series (2026-01-15) supersedes the 3.5 models the brief named; `voyage-3.5`, `voyage-3.5-lite`, `voyage-context-3`, `voyage-multimodal-3` are now listed under "older models" with no free tokens.

| Model | $/MTok | Free tier | Context | Dims | Notes |
|---|---|---|---|---|---|
| `voyage-4-lite` | $0.02 | 200M tokens | 32K | 1024 default; 256/512/2048; float/int8/uint8/binary | cheapest; same embedding space as 4/4-large |
| `voyage-4` | $0.06 | 200M | 32K | same | |
| `voyage-4-large` | $0.12 | 200M | 32K | same | MoE; vendor claims +14% vs OpenAI v3-large, +3.9% vs Gemini 001 on 29 RTEB datasets |
| `voyage-context-4` | $0.12 | 200M | 32K/chunk, 120K/doc | same | contextualized chunk embeddings for multi-page docs |
| `voyage-multimodal-3.5` | $0.12 text + $0.60 per 1B pixels | 200M tokens + 150B px | 32K | 1024 default; 256/512/2048 | images billed between 50K and 2M px → $0.00003–$0.0012 per page image |
| `rerank-3-lite` / `rerank-3` | $0.02 / $0.05 | 200M | — | — | ~$0.001 per 100-doc rerank |
| older: `voyage-3.5` / `-lite` / `context-3` / `multimodal-3` | $0.06 / $0.02 / $0.18 / $0.12 | none | | | |

Batch endpoint: 33% off, 12 h window. Design: embed `title + summary + tags + first ~1,500 tokens of OCR text` with `voyage-4-lite` at 512 or 1024 dims, int8, and store in the app's own index (SQLite-vec/CoreData on device, Postgres+pgvector on the service). The shared embedding space lets you embed queries with `-lite` and documents with `-large` later. Multimodal embeddings of the page image are a cheap option for layout-based "find the one that looked like this" search but are not needed for v1. Costs are negligible (a 1,000-token page ≈ $0.00002).

### 2.12 Per-document cost estimate (whole pipeline)

Assumptions per page: cached system prefix 2,500 tokens; uncached input = image 1,776 + OCR text 800 + instructions 150 ≈ 2,700 tokens; structured output 400 tokens; thinking off (Haiku) / `between_tools` at `low` (Sonnet); embedding 1,200 tokens on `voyage-4-lite`; NL search call amortized at 0.1 per page.

| Item | Haiku 5.5 | Sonnet 5.5 | Opus 5.5 (medium, thinking on, ~800 thinking tokens) |
|---|---|---|---|
| Cache read 2,500 tok | $0.000025 | $0.00025 | $0.0005 |
| Uncached input 2,700 tok | $0.00027 | $0.0054 | $0.0108 |
| Output 400 tok (+thinking) | $0.0002 | $0.004 | $0.024 |
| Embedding | $0.000024 | $0.000024 | $0.000024 |
| Search call share | ~$0.00001 | ~$0.00001 | — |
| **Per page, online** | **≈ $0.0005–0.001** | **≈ $0.010–0.012** | **≈ $0.035** |
| Per page, Batch backfill | ≈ $0.0003 | ≈ $0.005 | ≈ $0.018 |
| Per 1,000 pages online | ≈ $0.5–1 | ≈ $10–12 | ≈ $35 |

A household scanning 200 pages/month costs well under $0.25/month on Haiku; a blended design (Haiku first, ~10% escalated to Sonnet) is ≈ $0.002/page. These are computed from list prices, not measured; real OCR length, image size and output length will move them ±50%.

## 3. Options compared

| Option | Per-page cost | Expected latency to full record | Accuracy on messy mail (vendor positioning) | ZDR | Fit for hot path |
|---|---|---|---|---|---|
| A. Haiku 5.5, thinking off, effort low, image + OCR text, structured output, streamed | ~$0.0007 | ~3–4 s (unmeasured for thinking-off; infer from 167 t/s) | "classification, extraction, routing" model; weakest of the three | Yes | **Best** |
| B. Sonnet 5.5, `between_tools`, effort low | ~$0.011 | ~1.2 s TTFT + ~4 s output | Higher | Yes | Escalation / long packets |
| C. Opus 5.5 (thinking always on) | ~$0.035 | > B, variable thinking | Highest | Yes (not a Covered Model) | No |
| D. Haiku 5.5 text-only (OCR text, no image) | ~$0.0003 | ~2–3 s | Loses logos/handwriting/checkboxes | Yes | Backfill only |
| E. PDF document block of the captured pages | ~2x A per page (text + image tokens) | slower | Same model | Yes inline / No via Files | Backfill of existing PDFs |
| F. Two Haiku calls (60-token classify, then full extract) | ~1.3x A | classify in ~1 s, record later | Same | Yes | Only if streaming doc_type-first proves insufficient |
| G. Batches (any model) | 50% of A/B/C | minutes–24 h | Same | **No** | Backfill / re-index |

## 4. Recommendation for this project

1. **Pipeline shape.** On-device: capture → sharpness/edge detection → perceptual hash (dedupe, "already scanned") → Apple Vision OCR → resize to ≤ 1,100 px short edge (≈ 1,800 visual tokens, 100–130 DPI letter), WebP/JPEG q≈85 → upload original + derived page to the durability queue. Backend/proxy: one Haiku 5.5 request per page: `model: "claude-haiku-5-5"`, `thinking: {"type":"disabled"}`, `output_config: {"effort":"low","format":{"type":"json_schema","schema":…}}`, `max_tokens: 1500`, `stream: true`, `system` with `cache_control`, user turn `[image, OCR text]`. Surface `doc_type` from the stream. If `needs_review`, `confidence < 0.6`, handwriting, non-Latin script, or the packet exceeds 20 pages, re-run on `claude-sonnet-5-5` with `thinking: {"type":"between_tools"}`, `effort: "low"`, identical schema.
2. **Never send more than the model sees**: 200-DPI+ frames are capped to 4,784 tokens and merely add upload time. Verify the tier once with `count_tokens` and `transformations.oversized_image: "error"`.
3. **Freeze the contract**: one system prompt + one schema per app version, pinned `anthropic-version`, constant `effort`/`thinking`. Every change restarts the 24-h grammar cache and the prompt cache; roll changes out between scanning sessions.
4. **Durability is yours, not Claude's**: the "captured" promise must be satisfied by the local write + queued upload, before and independently of the Claude call; Claude output is metadata that can be regenerated by Batch at $0.0003/page.
5. **Keys**: proxy-only for the App Store product; BYOK on-device as an opt-in. Create a dedicated workspace per environment with a spend limit; set `inference_geo` server-side.
6. **Search**: FTS on OCR text + `voyage-4-lite` vectors (512-dim int8) + a Haiku query-parser call producing the filter JSON in §2.3; rerank with `rerank-3-lite` only if the index grows past a few thousand docs.
7. **Privacy posture for launch**: standard 30-day deletion and no-training already hold; request ZDR from sales once the service has an org, and plan for HIPAA readiness (self-serve BAA) if you market to medical users — which forbids the Batch and Files APIs for that org and means a separate org for backfill jobs.
8. **Measure before promising speed**: run 200 real pages through option A and record `usage` + wall-clock TTFT/total; the public benchmarks do not cover Haiku with thinking disabled.

## 5. Risks and unknowns

- **Haiku 5.5 latency with thinking disabled is unmeasured publicly**; the reasoning-on numbers (9–14 s TTFT at 10K input) are far from "sub-second". If thinking-off Haiku is not clearly faster than Sonnet `low` (1.2 s TTFT), the cost argument alone decides, and the UX must hide the latency entirely.
- Structured-output grammar compile latency on first use is unquantified; cache expiry after 24 h idle means the first scan after a day may be slow once.
- Haiku 5.5's safety classifiers can refuse benign documents (`general_harms`) with no server fallback; need a Sonnet retry path and a "stored without metadata" state.
- Prices, tiers and the Evaluation-tier limits change; the Sonnet cache-read price already differs between the local skill ($0.20) and the live page ($0.10). Re-check https://platform.claude.com/docs/en/about-claude/pricing.md at implementation time.
- Haiku 5.5 long-context pricing (>100K tokens per request, 5x) is a trap for big multi-page packets.
- Whether Haiku 5.5 is high-res tier is inferred from "Claude 4.7 and later"; confirm with `count_tokens`.
- Artificial Analysis figures are medians over 72 h from a US GCP region with 10K-token prompts; your prompt is smaller and your users are on mobile networks; both directions of error apply.
- ZDR is a contract arrangement via sales, not a toggle; the Files API and Batches fall outside it; "within 30 days" is the default, not an SLA.
- Apple App Review's current wording on BYOK AI keys was not located; treat as unknown and keep the proxy as the default path.
- Accuracy of document-type classification on handwritten/foreign/poorly lit pages is not benchmarked anywhere I found; the `needs_review` escalation is a guess at the right threshold.

## 6. Open questions for the founder

1. Is sub-second feedback required for the *label* ("tax form") or only for "captured + not a duplicate"? The latter is achievable on-device; the former likely means a two-call design (option F) or accepting ~2–4 s.
2. Will medical documents be in scope at launch (HIPAA org, no Batches/Files for that org) or can v1 ship under standard retention?
3. Do you want ZDR from day one (requires a sales conversation and an org) or is 30-day deletion acceptable for the beta?
4. Languages: English only, or EU languages (affects taxonomy enums, `language` handling, and whether `inference_geo` matters at all, since there is no EU geo)?
5. Is the BYOK path a product feature or a dev convenience? It changes the proxy design and support surface.
6. Expected volume per user per month and number of users at launch, to pick the usage tier to request (Start tier's $500/month cap ≈ 500K Haiku pages, so it is not the bottleneck; the Evaluation tier might be).
7. Should summaries be generated inline (adds ~150 output tokens and ~1 s) or by a nightly Batch?
8. Backfill: how many existing PDFs/scans exist, and where (Drive/NAS), to size the Batch + Files API import?

## 7. Sources

Local skill (authoritative where cited): `<bundled claude-api reference skill>/shared/models.md`, `shared/prompt-caching.md`, `shared/platform-availability.md`, `shared/cost-optimization.md`, `shared/tool-use-concepts.md`, `curl/examples.md`, `shared/live-sources.md`, `shared/model-migration.md`.

Live Anthropic docs (fetched 2026-11-03):
- https://platform.claude.com/docs/en/about-claude/models/overview.md
- https://platform.claude.com/docs/en/about-claude/pricing.md
- https://platform.claude.com/docs/en/models/haiku-5-5/overview
- https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5
- https://platform.claude.com/docs/en/models/sonnet-5-5/overview
- https://platform.claude.com/docs/en/build-with-claude/vision.md
- https://platform.claude.com/docs/en/build-with-claude/vision-coordinates.md
- https://platform.claude.com/docs/en/build-with-claude/pdf-support.md
- https://platform.claude.com/docs/en/build-with-claude/structured-outputs.md
- https://platform.claude.com/docs/en/build-with-claude/prompt-caching.md
- https://platform.claude.com/docs/en/build-with-claude/batch-processing.md
- https://platform.claude.com/docs/en/build-with-claude/files.md
- https://platform.claude.com/docs/en/build-with-claude/effort.md
- https://platform.claude.com/docs/en/build-with-claude/thinking.md
- https://platform.claude.com/docs/en/build-with-claude/token-counting.md
- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5
- https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency.md
- https://platform.claude.com/docs/en/api/rate-limits.md
- https://platform.claude.com/docs/en/api/service-tiers.md
- https://platform.claude.com/docs/en/manage-claude/api-and-data-retention.md
- https://platform.claude.com/docs/en/manage-claude/data-residency.md
- https://platform.claude.com/docs/en/manage-claude/workspaces.md
- https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data
- https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training
- https://support.claude.com/en/articles/9767949-api-key-best-practices-keeping-your-keys-safe-and-secure
- https://github.com/anthropics/anthropic-sdk-typescript/blob/main/README.md

Benchmarks and embeddings:
- https://artificialanalysis.ai/models/claude-haiku-5-5-low
- https://artificialanalysis.ai/models/claude-haiku-5-5-medium/providers
- https://artificialanalysis.ai/models/claude-haiku-5-5
- https://artificialanalysis.ai/models/claude-sonnet-5-5-low
- https://artificialanalysis.ai/models/claude-sonnet-5-5-medium/providers
- https://artificialanalysis.ai/methodology/performance-benchmarking
- https://docs.voyageai.com/docs/pricing
- https://docs.voyageai.com/docs/embeddings
- https://docs.voyageai.com/docs/multimodal-embeddings
- https://docs.voyageai.com/docs/contextualized-chunk-embeddings
- https://blog.voyageai.com/2026/01/15/voyage-4/
