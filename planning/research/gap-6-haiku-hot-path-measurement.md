# Gap 6: Haiku 5.5 hot-path measurement — what is known, what is not, and the harness to close it

Research date: 2026-11-03. Scope: the one Claude call per captured page (classify + extract, structured output, streamed). Method: live fetches of Anthropic platform docs, the Haiku 5.5 system card (PDF, 13 MB, text-extracted locally), Artificial Analysis pages, plus the bundled `claude-api` skill on disk; cross-checked against `claude.md`, `architecture.md`, `business.md` in this folder. Web search was unavailable for this round (shared budget exhausted), so every fact below comes from a primary page I fetched; numbers I computed from published formulas are marked **computed**, and numbers nobody has published are marked **unknown** or **estimate**.

**Honest status of the headline question.** No Anthropic API key is available in this sandbox (`ANTHROPIC_API_KEY` unset, no `ant` profile), and no public benchmark measures Haiku 5.5 with thinking disabled, on image prompts, from a phone. So the p50/p95 TTFT/latency/thinking-token/refusal numbers for 200 handheld pages **cannot be reported as measured here**. What this report delivers instead: (a) every fixed input to those numbers, verified against primary sources, (b) a tokens-and-dollars table for the full arm matrix, computed exactly, (c) the best public latency anchors and why they mislead, (d) a ready-to-run harness at `../tools/haiku_hot_path_bench.py` that runs the exact matrix (image / text / both × 1,100 / 1,568 / 2,576 px × thinking disabled / adaptive-low × `inference_geo`) and prints p50/p95 per arm, and (e) the retry/idempotency and capacity answers, which do not need measurement.

## 1. Executive summary

1. **Measured p50/p95 for Haiku 5.5 thinking-off image prompts do not exist publicly**; Artificial Analysis has no "non-reasoning" Haiku 5.5 variant (page 404s), and its reasoning-on numbers (8.95 s TTFT at `low`, 10K-token prompt) include thinking time and must not be used for the hot path. Run the harness with the founder's key before promising any latency.
2. The cost spread in earlier reports ($0.0004–$0.001/page) is entirely image size + output length: **computed** list-price cost per page on Haiku 5.5 is $0.00029 (1,100 px, image only, 250 output tokens) to $0.00080 (2,576 px + OCR, 400 tokens). Sonnet 5.5 is 19–20x that.
3. **Sonnet 5.5 cache reads are $0.10/MTok** (live pricing page, 0.05x base; the announcement says "now cost 50% less: $0.10 ... rather than $0.20"). The $0.20 in the bundled skill is stale.
4. **Haiku 5.5 is on the 28-px-patch high-resolution tier by documentation inference** ("Claude 4.7 and later models"; Haiku 5.5 shares the 4.7+ tokenizer and is listed under vision), but no per-model row exists; one `count_tokens` call with a 1075x1520 image settles it: **2,145** visual tokens = high-res, **1,551** = standard (harness `--count-tokens-only`).
5. Use `thinking: {"type":"disabled"}` + `effort: "low"` for this call despite Anthropic's general "lower effort instead" guidance: the two documented failure modes of thinking-off (skipped tool calls with JSON output; reasoning-like prose) cannot occur in a tool-less, grammar-constrained call. Keep adaptive-low as the measured alternative; switch only if thinking tokens are small and accuracy is better.
6. Refusals: `stop_reason: "refusal"` is HTTP 200; `cyber`/`general_harms` pre-output refusals are not billed, `bio`/`frontier_llm`/`reasoning_extraction` are; all count against rate limits; Haiku 5.5 has **no server-side fallback and no fallback credit**, so the retry to Sonnet 5.5 is client-side (SDK `BetaRefusalFallbackMiddleware` or your own). Classifier refusal rate on ID/medical/financial pages: **unknown**; the system card's model-level over-refusal on benign sensitive prompts is 0.17% ± 0.03% (API).
7. The Messages API documents **no idempotency key**; the queue must be at-least-once with idempotent apply keyed by page hash, committing metadata only from a complete `end_turn` + schema-valid parse. Spend-cap 429s carry no `retry-after` and must trip a circuit breaker, not a retry loop.
8. Capacity: **ITPM, not the 4,000 RPM, binds first** (913 pages/min on Start at 1,100 px + OCR ≈ 46 simultaneous scanners); the $500/$1,000 caps bind at roughly 4,000–9,000 (Start) and 8,000–18,000 (Build) users at 150 pages/user/month. Haiku 5.5 has its own rate-limit row, not shared with Sonnet 5.5, but shared across all your users and both `inference_geo` values.
9. `inference_geo: "us"` costs 1.1x on every token category, shares the same rate pool, and gives up "global" routing that the docs describe as being for "optimal performance and availability"; use it only for a compliance reason, and measure both arms.
10. Priority Tier is no longer sold and excludes Haiku 5.5 / Sonnet 5.5; fast mode is Opus-only. There is no paid latency lever for this call; speed comes from fewer input tokens, thinking off, short output, `doc_type` first in the schema, and warm caches.

## 2. Findings

### 2.1 Public latency data and why it does not answer the question

| Source | Setting | Output speed | TTFT / first answer token | E2E (500 out) | Caveat |
|---|---|---|---|---|---|
| Artificial Analysis, Haiku 5.5 `low` (https://artificialanalysis.ai/models/claude-haiku-5-5-low/providers) | reasoning on, 10,000-token text prompt, median of 72 h, from GCP `us-central1-a` | 167 t/s (165 median) | 8.95 s (first chunk 8.96 s) | 11.99 s | AA's TTFT "will be the first reasoning token" and first-answer-token "is measured after any 'thinking' time" (https://artificialanalysis.ai/methodology/performance-benchmarking); ~8 s of the 8.95 s is therefore thinking on AA's reasoning-heavy prompts |
| AA, Haiku 5.5 `medium` (from `claude.md`) | same | 176 t/s | 13.81 s first answer token | 16.77 s | same |
| AA, Haiku 5.5 `max` (https://artificialanalysis.ai/models/claude-haiku-5-5/providers) | same | 235 t/s | 333.7 s | 359.9 s | thinking-dominated; irrelevant |
| AA, Haiku 5.5 non-reasoning | — | — | — | — | **page does not exist (HTTP 404)**: https://artificialanalysis.ai/models/claude-haiku-5-5-non-reasoning |
| AA, Sonnet 5.5 `low` (from `claude.md`) | reasoning on | 105.7 t/s | 1.20 s | — | the only sub-2 s TTFT anchor in the family |
| Anthropic | — | none published | none published | — | "Fastest" comparative label only (https://platform.claude.com/docs/en/models/haiku-5-5/overview); Box quote "about half the latency" of Haiku 4.5, Asana "up to 2.5x faster inference per agent turn" (https://www.anthropic.com/claude-haiku-5-5) — customer claims |

What the AA numbers do tell us, with caveats: Haiku 5.5's **decode speed is measured at ~165–176 t/s**, so a 250-token record takes ~1.5 s and a 400-token record ~2.4 s to stream after the first token, regardless of thinking setting. AA also runs a vision workload ("a single 1 megapixel image and approximately 1,000 input tokens") but I could not retrieve a Haiku 5.5 figure for it.

The inference that matters for the thinking question: on AA's prompts, `low` effort still produced on the order of 8 s × ~165 t/s ≈ **1,300 thinking tokens** before the first answer token (**estimate**, derived from AA's two numbers). If a document page triggers even a quarter of that, adaptive-low adds ~2 s and ~$0.00016/page (thinking "tokens ... are billed as output tokens, even when the thinking text isn't returned", https://platform.claude.com/docs/en/build-with-claude/thinking). The docs also say adaptive mode "can skip thinking entirely for simpler problems" (https://platform.claude.com/docs/en/build-with-claude/effort), so the real number for a classify-and-extract page could be near zero. Only the harness answers this.

### 2.2 A latency decomposition for the phone (estimates, to be replaced by harness output)

End-to-end per page = upload + prefill (+ grammar compile on first use) (+ thinking) + decode. From a phone the first term is the one no server-side benchmark includes.

| Stage | Driver | Estimate | Basis |
|---|---|---|---|
| Upload | JPEG bytes (base64 +33%) over uplink | 1,100 px q85 letter page ≈ 150–300 KB (**estimate**; harness logs actual bytes); at 5–10 Mbps LTE uplink 0.2–0.6 s, on 50 Mbps Wi-Fi <0.1 s | US LTE median upload speed was already flagged **unknown** in `gap-4`; the vision guide says lossy compression "can reduce latency by reducing the size of requests" but "heavy JPEG compression can make text difficult to read" (https://platform.claude.com/docs/en/build-with-claude/vision) |
| Prefill | ~1,400–5,900 uncached tokens + cached system prompt | **unknown**; Sonnet 5.5 shows 1.20 s TTFT at 10K tokens including some thinking, so Haiku thinking-off on ≤6K tokens should be ≤1 s (**inference**) | AA Sonnet 5.5 low |
| Grammar | first use of the schema | "additional latency while the grammar compiles"; cached "24 hours from last use" | https://platform.claude.com/docs/en/build-with-claude/structured-outputs |
| Thinking | adaptive-low only | 0 to several seconds (§2.1) | thinking page, AA |
| Decode | output tokens / 165 t/s | 250 tok ≈ 1.5 s; 400 tok ≈ 2.4 s; `doc_type` as first required property lands ~0.1 s after TTFT | AA output speed; structured outputs stream "like normal responses" as `text_delta` and properties are emitted required-first in schema order (structured outputs page; `claude.md` §2.3) |

So the realistic thinking-off target is **TTFT ≈ 0.5–1.5 s and full record ≈ 2.5–4 s on Wi-Fi**, plus the LTE upload term; the "instant" feedback (captured, duplicate, provisional type) must remain on-device, as the earlier reports concluded.

### 2.3 Image size matrix: tokens and dollars (computed from the published rule)

Visual tokens = ⌈w/28⌉ × ⌈h/28⌉; high-res tier caps long edge at 2,576 px and tokens at 4,784, resizing aspect-preserving to the largest size that fits both (https://platform.claude.com/docs/en/build-with-claude/vision, https://platform.claude.com/docs/en/build-with-claude/vision-coordinates). US-letter aspect; A4 is ~10% fewer tokens.

| Long edge sent | Sent size (letter) | Visual tokens (high-res) | Visual tokens (if standard tier) | Note |
|---|---|---|---|---|
| 800 px | 618x800 | 667 | 667 | ~73 DPI; small print marginal |
| 1,100 px | 850x1100 | 1,240 | 1,240 | ~100 DPI |
| 1,300 px | 1005x1300 | 1,692 | 1,496 (resized) | first size where the tier matters |
| 1,568 px | 1212x1568 | 2,464 | 1,496 | ~143 DPI |
| 2,576 px | 1991x2576 → resized 1688x2184 | 4,758 (token cap binds, not the edge) | 1,496 | ~200 DPI effective; nothing above this is ever seen by the model |
| 12 MP native (3024x4032) | → 1688x2184 | 4,758 | 1,496 | upload cost only |

Per-page list price (Haiku 5.5 ≤100K-token prompt: $0.10 in, $0.50 out, cache read $0.01; Sonnet 5.5: $2 / $10 / $0.10; https://platform.claude.com/docs/en/about-claude/pricing). Assumptions: 2,500-token cached system prompt; OCR transcript 800 tokens (**assumption**; Haiku 5.5 counts ~30% more tokens than 4.5 for the same text); 150 tokens of instructions; no thinking.

| Arm | Uncached input tokens | Output 250 | Output 400 | Sonnet 5.5 (400) |
|---|---|---|---|---|
| Text only (OCR, no image) | 950 | $0.000245 | $0.000320 | $0.0062 |
| 1,100 px image only | 1,390 | $0.000289 | $0.000364 | $0.0070 |
| 1,100 px + OCR | 2,190 | $0.000369 | $0.000444 | $0.0086 |
| 1,568 px + OCR | 3,414 | $0.000491 | $0.000566 | $0.0111 |
| 2,576 px + OCR | 5,708 | $0.000721 | $0.000796 | $0.0157 |

Add 1.1x for `inference_geo: "us"`; add thinking tokens at $0.50/MTok for adaptive-low; subtract 50% for Batch backfill. Refusals in the billed categories and mid-stream refusals add the cost of the refused attempt (§2.5). Which arm is *accurate enough* is **unknown** publicly: Anthropic says high-res fidelity matters for "dense documents" and advises downsampling otherwise; with the Vision transcript supplying exact strings, the image's job is layout, logos, stamps, checkboxes and handwriting, so 1,100 px is the right default hypothesis and 1,568 px the escalation for small print. The harness scores `doc_type` and `document_date` against ground truth per arm.

### 2.4 Tier confirmation and the exact `count_tokens` check

The vision page lists `claude-haiku-5-5` as a supported model and defines the tiers as "High-resolution: Claude 4.7 and later models — 2,576 px — 4,784 tokens; Standard: All other models — 1,568 px — 1,568 tokens", with "High-resolution support is automatic on the listed models" (https://platform.claude.com/docs/en/build-with-claude/vision). Haiku 5.5 "uses the same newer tokenizer as Claude 4.7 and later models" (https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5). That is a strong inference, not a per-model row. The discriminating call: `POST /v1/messages/count_tokens` with `model: claude-haiku-5-5` and a 1075x1520 JPEG; the docs' own example gives **2,145** visual tokens on high-res and a resize to 924x1307 = **1,551** on standard (https://platform.claude.com/docs/en/build-with-claude/vision-coordinates). Adding `"transformations": {"oversized_image": "error"}` makes the same call reject if the image would be resized, and "the Token counting endpoint honors `transformations` too" — so the check is unambiguous. Count tokens is free of model inference, accepts images only as base64, and "estimates an image's token cost from its dimensions without fully processing it" (https://platform.claude.com/docs/en/build-with-claude/token-counting, vision-coordinates page).

### 2.5 Refusals on Haiku 5.5: mechanics, billing, rates

- Shape: HTTP 200, `stop_reason: "refusal"`, `stop_details: {type, category, explanation}`; `category` ∈ `cyber`, `bio`, `frontier_llm`, `reasoning_extraction`, `general_harms`, or `null`; "A refusal can arrive before any output, or mid-stream after partial output. In either case, treat any partial output as incomplete and discard it." (https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback)
- Billing: pre-output refusals are billed only for `bio`, `frontier_llm`, `reasoning_extraction` ("categories where Anthropic measures low volumes of false positives, as of September 2026"); `cyber`, `general_harms` and `null` are not billed; "A mid-stream refusal bills the input tokens and the output already streamed"; "The request still counts against your rate limits." (same page)
- With structured outputs "The output might not match your schema because the refusal message takes precedence over schema constraints" and asking for reasoning in a property "might lead to a `reasoning_extraction` refusal" (structured outputs page) — keep `review_reason` short and never add a "reasoning" field.
- No fallback: "Claude Haiku 5.5 has no server-side fallback: with `fallbacks: "default"`, a declined request stays declined, and a list of fallback models returns a 400 error"; "A Claude Haiku 5.5 refusal carries no fallback credit"; "Sending the same request to Claude Haiku 5.5 again usually returns another refusal" (refusals page; https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5). The SDK `BetaRefusalFallbackMiddleware` (Python/TS/Go/C#/Java/PHP) retries client-side on any platform and splices the fallback model's events into the stream (refusals page §client-side fallback).
- Rates: **classifier refusal rate on ID/medical/financial pages is unknown**; nobody publishes it. The system card gives model-level over-refusal on benign-but-sensitive prompts: **0.17% (± 0.03%) on the API without a system prompt, 0.82% on claude.ai**, versus 0.44% / 3.05% for Haiku 4.5 (Table 4.1.2.A), and notes that "our cyber safeguards for Claude Haiku 5.5 trigger on significantly less activity than other recent releases" and that in the automated behavioral audit it "over-refused more than any other model we tested" (https://www.anthropic.com/document/claude-haiku-5-5-system-card, PDF). Those are not `stop_reason: "refusal"` measurements, so the harness counts both (`stop_reason` and schema-valid-but-`needs_review` with refusal-like summary) per page class.

### 2.6 Thinking disabled vs adaptive-low: what the docs actually say

- Haiku 5.5 accepts `{"type":"disabled"}` at `low`/`medium`/`high`; 400 at `xhigh`/`max`; a per-message effort change is a 400 while disabled; `between_tools` is Sonnet-5.5-only (https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting).
- "Although you can still turn thinking off ... the better way to trade response quality against speed and cost is to use the effort parameter" (what's-new page). The two concrete reasons given: "With thinking off, Claude Haiku 5.5 might skip a tool call it needs when you also request JSON output" and "sometimes writes reasoning-like text in the reply that users see. This occurs more often with thinking off or at `low` effort" (prompting page). The extraction call has **no tools** and its output is **grammar-constrained JSON**, so neither applies; `summary` is the one free-text field, and a two-sentence instruction plus the grammar bounds it.
- Cost/latency mechanics: thinking is billed as output tokens and counts toward `max_tokens` with **no separate usage field** (thinking page) — so the harness measures thinking tokens as `output_tokens` minus the token count of the JSON text. `display: "omitted"` (default) "reduces latency, not cost" and with adaptive "when the model skips thinking for a simple request, no thinking block is produced".
- Cache: "changing any of them [thinking config, effort] starts a new cache prefix" — freeze one combination per app version (thinking page §prompt caching).
- Verdict: thinking off + `low` is the correct default for *this* call and is consistent with Anthropic's own reduce-latency example, which is Haiku 5.5 at `low` (https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency). Keep adaptive-low in the eval; adopt it only if its median thinking tokens are < ~100 and it wins on accuracy.

### 2.7 Retry and idempotency facts the queue design rests on

- **No idempotency key**: the API overview's request/response header tables (`request-id`, `anthropic-organization-id`, `anthropic-workspace-id`, rate-limit headers) and the errors page document no `Idempotency-Key`; `metadata.user_id` is an opaque abuse-detection id (https://platform.claude.com/docs/en/api/overview, https://platform.claude.com/docs/en/api/errors, https://platform.claude.com/docs/en/api/messages). Treat every Messages call as non-idempotent at the server.
- **429**: token-bucket enforcement ("a rate of 60 requests per minute might be enforced as 1 request per second"), acceleration limits on sharp ramps, `retry-after` in seconds ("Not every 429 carries it"); the spend-cap 429 has `error.details.error_code: "enforced_spend_limit_reached"`, **no `retry-after`**, and "Retrying, including the SDK's automatic retries, fails until access resumes" at 00:00 UTC on the 1st; a self-set spend limit returns **HTTP 400** `invalid_request_error` "You have reached your specified API usage limits" (https://platform.claude.com/docs/en/api/rate-limits).
- **5xx**: 500 `api_error` ("Retry ... with exponential backoff"), 504 `timeout_error` ("Consider using the streaming Messages API"), 529 `overloaded_error`; "The official SDK automatically retries transient failures (connection errors, rate limits, and 5xx) with exponential backoff, twice by default, honoring `retry-after`"; Python also retries 408 and 409; default timeout 10 min, per-request override, `APITimeoutError` on expiry, "requests that time out are retried twice by default" (errors page; https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python).
- **Mid-stream**: after HTTP 200 the stream can carry `event: error` with `overloaded_error`; `stop_reason` arrives only in `message_delta`; "Tool use and thinking blocks cannot be partially recovered. You can resume streaming from the most recent text block" — but resumption means an assistant prefill, which Haiku 5.5 rejects with 400, so for this call a broken stream is a full resend (https://platform.claude.com/docs/en/build-with-claude/streaming, https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons).
- **`max_tokens`**: "The output might be incomplete and not match your schema. Retry with a higher `max_tokens` value" (structured outputs page); thinking consumes the same budget.

### 2.8 Capacity: where the caps and limits bind (computed)

Haiku 5.5 limits per tier, own row, not shared with other models (https://platform.claude.com/docs/en/api/rate-limits): Start 4,000 RPM / 2M ITPM / 400K OTPM; Build 10,000 / 5M / 1M; Scale 13,000 / 10M / 2M. Only uncached input counts toward ITPM; cache reads do not. Spend caps: Start $500, Build $1,000, Scale $200,000; Custom uncapped. New orgs may sit in an Evaluation tier below these. "Rate limits are currently shared across all `inference_geo` values."

| Tier | Binding limit at 1,100 px + OCR (2,190 uncached tok, 300 out) | Pages/min | Simultaneous scanners at 20 pages/min | Spend cap → pages/month at $0.00037–0.00080 | Users at 150 pages/user/month |
|---|---|---|---|---|---|
| Start | ITPM | 913 | ~46 | 625K–1.35M | ~4,200–9,000 |
| Build | ITPM | 2,283 | ~114 | 1.25M–2.7M | ~8,300–18,000 |
| Scale | ITPM | 4,566 | ~228 | 250M–540M | ~1.7M–3.6M |

RPM would bind only below ~500 uncached tokens per request. Image-only at 1,100 px raises Start throughput to 1,333 pages/min (then OTPM binds); 2,576 px + OCR cuts it to 350. Peak-concurrency translation (**assumption-driven**: 2 sessions/user/week, ~10 min each, concentrated in a 4-hour evening window with a 2x peak factor): 1,000 users ≈ 24 concurrent scanners, 5,000 ≈ 120, 10,000 ≈ 240. So on Start both the ITPM wall (~2,000–4,000 users) and the $500 cap (~4,000–9,000 users) arrive in the same band; Build carries ~5,000 users of peak and ~8,000–18,000 of spend; Scale carries ~10,000 users of peak before Custom-tier limits or token reduction is needed. Spillover levers that do not need a tier change: Sonnet 5.5 has a separate bucket (20x price), Batches have separate limits (Start 1,000 RPM, 200,000 queued) for the offline backlog, and per-workspace limits fence a tenant.

### 2.9 `inference_geo` pinning

`"us"` is 1.1x on input, output, cache writes and cache reads (and on Haiku 5.5's >100K tier); `"global"` is the default and "may run in any available geography for optimal performance and availability"; `usage.inference_geo` reports where inference ran; only `us` and `global` exist, workspace geo is `us` only, and rate limits are shared across geos (https://platform.claude.com/docs/en/manage-claude/data-residency). No latency figure is published for either; the harness `--geo` flag runs both arms.

## 3. Options compared

| Option (Haiku 5.5, structured output, streamed, cached system prompt) | Uncached tokens | $/page (400 out) | Expected TTFT / E2E on Wi-Fi (estimate) | Accuracy risk | Throughput on Start | Verdict |
|---|---|---|---|---|---|---|
| A. 1,100 px image + OCR text, thinking **disabled**, effort low | 2,190 | $0.00044 | ~0.5–1.5 s / ~3 s | OCR gives exact strings; image gives layout | 913 pages/min | **Default** |
| B. Same as A, adaptive thinking, effort low | 2,190 + thinking | $0.00044 + $0.50/MTok × thinking | +0 to several s | possibly higher | lower (OTPM) | Measure; adopt only if thinking < ~100 tokens median |
| C. 1,568 px + OCR, disabled, low | 3,414 | $0.00057 | +0.2–0.5 s upload/prefill | best for small print | 586 | Escalation for dense pages |
| D. 2,576 px + OCR, disabled, low | 5,708 | $0.00080 | slowest; 2x A's prefill | marginal over C | 350 | Not for the hot path |
| E. 1,100 px image only | 1,390 | $0.00036 | fastest upload+prefill | loses exact digits unless the model OCRs well | 1,333 (OTPM) | Only if OCR text proves unnecessary |
| F. OCR text only (no image) | 950 | $0.00032 | fastest | loses logos/stamps/handwriting/checkboxes | 2,105 (ITPM) | Backfill of existing PDFs |
| G. Sonnet 5.5 `between_tools` low, same input as A | 2,190 | $0.0086 | 1.2 s TTFT anchor measured; ~4 s decode at 105 t/s | higher | separate bucket | Refusal/needs-review fallback |

## 4. Recommendation for this project

1. **Run the harness before any speed claim.** `pip install anthropic pillow`, export the founder's key, then: `--count-tokens-only` (confirms the tier in one call), then the full matrix on the 200-page handheld set with OCR transcripts and truth files, Wi-Fi and LTE, `--geo us` and `--geo ""`. The script writes JSONL and `--summarize` prints per-arm p50/p95 TTFT, time-to-`doc_type`, E2E, output tokens (thinking included), uncached input, refusal %, JSON-valid %, error %, and median $/page. Use `max_retries=0` as the script does, so 429/529 are visible rather than absorbed.
2. **Ship arm A** (1,100 px long edge, JPEG q85 inspected for legibility, OCR text, thinking disabled, effort low, `max_tokens` 1,500, `doc_type` first in `required`, 2,500-token system prompt behind one `cache_control` breakpoint). Escalate to C (1,568 px) only when the on-device OCR confidence is low or the page is dense; never send above 2,576 px.
3. **Durability queue contract** (per page, SQLite outbox row keyed by the sha256 of the archival image + schema version):
   - States: `captured` → `metadata_pending` → `metadata_done` | `metadata_refused` | `metadata_parked`. "Captured" never waits on Claude.
   - Each attempt stores `request-id`, `message.id`, `stop_reason`, `stop_details.category`, `usage`, wall-clock TTFT/E2E. Commit metadata only from a stream that ended with `message_delta.stop_reason == "end_turn"` and a schema-valid parse; streamed `doc_type` is a UI hint only; partial JSON is discarded.
   - Retry classes: (i) 429 with `retry-after` → sleep that many seconds (+ jitter), no other backoff; (ii) 429 `enforced_spend_limit_reached` or 400 "reached your specified API usage limits" → open a global circuit breaker until the stated time, alert, park all rows (durability unaffected); (iii) 500/504/529, mid-stream `error`, connection reset, `APITimeoutError` → full jitter backoff 1 s × 2^n capped at 60 s, 8 attempts over ~10 min, then `metadata_parked` and hand to a nightly Batch job (50% price, separate limits); (iv) `max_tokens` → one retry with `max_tokens` doubled, then park; (v) `refusal` → one retry on Sonnet 5.5 (`between_tools`, low, identical schema) via the SDK middleware or your own call, no `fallbacks` field on the Haiku request; if Sonnet also refuses, `metadata_refused` with the on-device label kept and the page still archived.
   - Idempotency is client-side: apply is an upsert by page hash, so a duplicate call after an ambiguous timeout costs one extra ~$0.0005 request, never a duplicate record. Set `metadata.user_id` to an opaque per-install hash.
   - Set the SDK per-request timeout to ~45 s (not the 10-minute default) and `max_retries` to 0–1 so the queue owns the schedule; ramp traffic gradually to stay under acceleration limits.
4. **Capacity plan**: request Build at launch and Scale before ~5,000 users; watch the Console's "hourly maximum uncached input tokens per minute" chart; keep the uncached-token budget per page under ~2,500 (ITPM is the wall); use workspace limits per environment; keep `inference_geo` global unless a customer contract requires `us`.
5. **Pricing inputs for the business model**: Haiku 5.5 $0.10/$0.50 (≤100K prompt), cache read $0.01; Sonnet 5.5 $2/$10, cache read **$0.10**; ×1.1 for `us`; ×0.5 for Batch. Use $0.00044/page (arm A, 400 output tokens) as the planning number and $0.00057 for the escalation mix.

## 5. Risks and unknowns

- **All latency numbers are estimates or third-party text-prompt medians**; TTFT from a phone over LTE has never been measured for this model. If arm A's measured p95 E2E exceeds ~5 s, the UX must hide the call entirely (it already should).
- **Thinking tokens at adaptive-low are unknown** for document prompts; the AA-derived ~1,300-token figure is for reasoning-heavy prompts and may be wildly off in either direction.
- **Accuracy by image size is unmeasured**; small print on 1,100 px pages may degrade entity extraction even with OCR text present.
- **Classifier refusal rate on medical/ID/financial pages is unknown**; the 0.17% over-refusal figure is model-level, API-without-system-prompt, and on sensitive-topic prompts, not documents. Refusals still consume rate limit and, in billed categories, money.
- **Grammar compile latency** on first use and the 24-hour idle expiry are unquantified; a user's first scan of the day may pay it.
- **Evaluation tier** limits below the published Start numbers could throttle a beta before the math above applies.
- **Tier inference**: high-res tier for Haiku 5.5 is documented by generation, not by model ID; resolve with the one-call check.
- **Price drift**: Sonnet 5.5 cache-read already changed once ($0.20 → $0.10); Haiku's >100K-token rate card (5x) is a trap for multi-page requests.
- **No server-side idempotency**: a proxy or SDK retry after an ambiguous timeout can double-bill a page; acceptable at $0.0005, but the apply path must be idempotent.
- **AA methodology**: medians over 72 h from a single US GCP zone with `temperature: 0`-style defaults; Anthropic rejects non-default sampling on Haiku 5.5, so AA's exact request shape for Claude is unknown to me.

## 6. Open questions for the founder

1. Can you run the harness now (key, 200 handheld pages, Vision transcripts, ~$1 at list prices for the full matrix including repeats) and share the JSONL? Every number in §2.2 should be replaced by it.
2. What is the acceptable p95 for the *full record* (not the label) before the design changes — 3 s, 5 s, 10 s?
3. Is `summary` needed in the hot path at all (≈150 output tokens ≈ 0.9 s of decode), or can it be a Batch job?
4. Do any target customers require `inference_geo: "us"` (1.1x, possibly slower)? If not, keep global.
5. What is the expected mix of dense pages (statements, tax forms) vs letters? It sets how often arm C runs and therefore the ITPM budget.
6. For refused pages: is "archived without AI metadata, on-device label only" acceptable, or must every page get a Sonnet pass (20x cost on that slice)?
7. Which tier is the org on today (Evaluation vs Start)? It decides whether the first TestFlight can even sustain 50 simultaneous scanners.

## 7. Sources

Primary (fetched 2026-11-03):
- https://platform.claude.com/docs/en/about-claude/pricing.md — Haiku 5.5 / Sonnet 5.5 rows, footnote 2 (0.05x cache reads), long-context pricing, `inference_geo` 1.1x, tool-use system-prompt token table
- https://platform.claude.com/docs/en/build-with-claude/vision.md — 28-px patches, tier table, request limits, resize and compression guidance
- https://platform.claude.com/docs/en/build-with-claude/vision-coordinates.md — exact resize rule, 1075x1520 example, `transformations.oversized_image`, count_tokens behaviour
- https://platform.claude.com/docs/en/build-with-claude/token-counting.md
- https://platform.claude.com/docs/en/api/rate-limits.md — tiers, spend caps, token bucket, acceleration limits, headers, spend-cap 429 shape
- https://platform.claude.com/docs/en/api/errors.md — status codes, SDK retry policy, mid-stream errors, validation errors
- https://platform.claude.com/docs/en/api/overview.md — request/response headers (no idempotency key)
- https://platform.claude.com/docs/en/api/messages.md — `metadata.user_id`
- https://platform.claude.com/docs/en/build-with-claude/streaming.md — event types, `error` events, `message_delta`, recovery notes
- https://platform.claude.com/docs/en/build-with-claude/handling-stop-reasons.md
- https://platform.claude.com/docs/en/build-with-claude/structured-outputs.md — `max_tokens` and refusal behaviour, grammar cache, extra system prompt, streaming
- https://platform.claude.com/docs/en/build-with-claude/refusals-and-fallback.md — categories, billing table, mid-stream refusals, Haiku 5.5 exclusions, SDK middleware
- https://platform.claude.com/docs/en/build-with-claude/fallback-credit.md — "A Claude Haiku 5.5 refusal carries no fallback credit"
- https://platform.claude.com/docs/en/build-with-claude/thinking.md — thinking billed as output tokens, display omitted, skip-thinking, cache invalidation
- https://platform.claude.com/docs/en/build-with-claude/thinking-troubleshooting.md — per-model `disabled` support table
- https://platform.claude.com/docs/en/build-with-claude/effort.md — levels, Haiku 5.5 default `medium`, per-message effort
- https://platform.claude.com/docs/en/build-with-claude/prompt-engineering/prompting-claude-haiku-5-5 — thinking-off failure modes, refusal handling
- https://platform.claude.com/docs/en/models/haiku-5-5/overview and https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5
- https://platform.claude.com/docs/en/manage-claude/data-residency.md
- https://platform.claude.com/docs/en/api/service-tiers.md — Priority Tier no longer sold; excludes Haiku 5.5 / Sonnet 5.5
- https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency.md
- https://platform.claude.com/docs/en/cli-sdks-libraries/sdks/python.md — retries, timeouts, error classes
- https://www.anthropic.com/claude-haiku-5-5 and https://www.anthropic.com/news/claude-haiku-5-5 — customer latency claims, Chartography, cache-read price change
- https://www.anthropic.com/document/claude-haiku-5-5-system-card (PDF via https://assets.claude.com/e1080d6bf5ae2018ea3c2f414064be03232f5be5.pdf) — Table 4.1.2.A over-refusal rates; cyber safeguard scope
- https://artificialanalysis.ai/models/claude-haiku-5-5-low/providers, https://artificialanalysis.ai/models/claude-haiku-5-5/providers, https://artificialanalysis.ai/models/claude-haiku-5-5-non-reasoning (404), https://artificialanalysis.ai/methodology/performance-benchmarking

Local: bundled skill `<bundled claude-api reference skill>` (`shared/models.md` — stale $0.20 Sonnet 5.5 cache read; `shared/model-migration.md` §Migrating to Claude Haiku 5.5); sibling reports `claude.md`, `architecture.md`, `business.md`, `gap-3-on-device-latency-budget.md`, `gap-4-captured-state-machine-and-fir.md`; harness `../tools/haiku_hot_path_bench.py`.
