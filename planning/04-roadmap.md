# Roadmap and Phase 0

Date: 2026-11-03. Assumes one senior iOS developer with AI coding assistance at about 30 productive hours per week. Both judges flagged the timelines as optimistic; each phase ends with a usable app so slips cost time, not the product. The service, email ingestion and Android phases are revenue-gated.

## Phases

| Phase | Weeks | Scope | Exit criteria |
|---|---|---|---|
| **0 Measure** | 1–2 | `OSSignposter` harness on iPhone 13 / 15 Pro / 16 / 17 Pro; 200-page handheld golden run at 20 pages per minute, cold and preheated (Xcode thermal simulation); dedup calibration set (200 pages × 5 recaptures, 50 same-sender sibling pairs, 20 few-field bill pairs, 30 receipts, 20 blank backs); Vision character error rate between captures; FeaturePrint latency and distance ROC; F_FULLFSYNC cost; still shot-to-shot time; iCloud Drive upload latency; `count_tokens` tier check and the Haiku hot-path matrix on your pages (`tools/haiku_hot_path_bench.py`, about $1 of API spend); `kCGPDFContextCreatePDFA` through veraPDF; FTS5 and trigram availability | Every estimate in `02-architecture.md` section 4 and section 8 replaced by p50/p95 per device; dedup thresholds with zero false-skips on the calibration set; stability window (4 vs 6 frames) decided by false-fire rate |
| **1 Capture core (v0, your daily driver)** | 3–8 | Capture state machine; S1 durability with crash-injection tests; two-beat dedup; two-pass Vision OCR; Redactor plus CI canary; rules and sender-memory provisional label; enhancement chain; in-house PDF/A-2u writer with veraPDF in CI; iCloud Drive first hop with `NSMetadataQuery` verification; FTS5, facets and the deterministic query parser; BYO-key Haiku call per page (streamed, structured, incremental document conversation); split-biased grouper; thermal policy; the proxy contract and schema versioning written as documents | You digitize all your own mail daily; settle-to-haptic ≤ 500 ms p95 on 15 Pro and ≤ 700 ms on 13; 20 pages per minute for 10 minutes without reaching the serious thermal state; zero false "already scanned" on the corpus |
| **2 Destinations and understanding (TestFlight)** | 9–14 | Google Drive and Synology connectors with verify, rename and audit; outbox reconciliation and the 24-case device durability matrix; boundary scorer with Claude merge suggestions; envelope, blank-back and duplex handling; in-track sharper replacement; on-device embeddings, RRF, Core Spotlight, `IndexedEntity`; export packs (print, share, ZIP, tax pack); Create ML classifier distilled from Claude labels; Sonnet escalation and refusal path; search eval harness; the 30-minute S1-only notification and amber state; 20 to 50 testers | p50/p95 for "in frame → captured" and "captured → safe" published to testers; boundary accuracy measured on 200 packets; durability matrix green |
| **3 App Store** | 15–22 | LLC and Apple Organization enrolment; StoreKit 2 (managed $49.99/yr with ~500-page fair-use cap, free BYO and on-device tier, Family Sharing, 14-day trial); 5.1.2(i) consent screen, nutrition labels, privacy manifest, medical consent toggle, in-app account deletion; Cloudflare Worker proxy with App Attest, per-user quotas and usage metering; ZDR request to Anthropic and the Build rate tier; ASO in the Business category; 48 MP stand mode; UVDoc Core ML dewarp spike | Public release; AI cost of goods under 10% of net at 200 pages per user per month |
| **4 Service** | months 6–9 | Supabase accounts with native Sign in with Apple; opt-in end-to-end-encrypted relay bucket (R2) with user-held recovery key; CloudKit ledger mirror for multi-device; forwarding-address email ingest (persist-then-process) and share extension; born-digital PDF path; EventKit reminders and passive daily digest; Drive `changes.watch` inbox; B2B seats; Scale rate tier | Multi-tenant service at about 9 months total |
| **5 Android and custom models** | months 10–14 | Kotlin client (CameraX, ML Kit Text v2, OpenCV or a licensed detector) against the same proxy; Google Play Billing into the entitlements table; distilled document embedding for sub-5 ms dedup; BERT text-classifier promotion; dewarp behind a crease detector | Revenue-gated |

Budget half of phases 1 and 2 for the capture loop and durability; they are the product. The PDF/A-2u writer is its own line item (about two weeks including veraPDF conformance).

## Phase 0 in detail

Phase 0 is non-negotiable: every speed claim in this plan is derived from one third-party A18 benchmark and vendor statements. Nothing goes into marketing copy until it is measured on an iPhone 13.

**Devices.** iPhone 13 (A15, floor), 15 Pro (A17 Pro, Apple Intelligence), 16 (A18), 17 Pro (A19 Pro). If you own fewer, the 13 and one Pro are the minimum.

**Corpus.** About 200 real pages of your own mail with typed ground truth (doc type, sender, document date, amounts, identifier last-4s, "page N of M", keep-original): same-sender statements across several months, utility bills, EOBs, receipts (including faded thermal), envelopes, duplex letters, blank backs, a few handwritten and non-English items, a few IDs and cards. Plus 150 natural-language queries you would actually ask. Plus one week's count of marketing versus real mail.

**On-device measurements** (a throwaway Swift harness with `OSSignposter`, run with the Instruments template, histograms only):

1. `DetectDocumentSegmentationRequest` per frame at 1280x960 and 1920x1440.
2. Settle-to-still with ZSL plus responsive capture on, 12 MP `.balanced`; shot-to-shot time; whether 24 MP really is deferred-only on the test devices.
3. F_FULLFSYNC plus atomic rename plus two fsync'd SQLite commits.
4. `.fast` raw OCR on a 2 to 3 MP rectified page; `.accurate` with correction at full resolution; `RecognizeDocumentsRequest` at full resolution.
5. `GenerateImageFeaturePrintRequest` latency and the distance distribution on the calibration set (same page vs sibling vs different).
6. dHash, PDQ-style hash, 9-gram Jaccard and parsed-anchor agreement on the calibration set: per-tier ROC and the fused false-skip rate (must be zero).
7. Thermal ramp: pages until the fair and serious states at 20 pages per minute with and without torch.
8. iCloud Drive container upload latency for a 300 KB file on Wi-Fi and LTE; behaviour after force-quit; behaviour with a full iCloud account.
9. Vision character error rate between two captures of the same page (drives the dedup text thresholds).
10. `kCGPDFContextCreatePDFA` output through veraPDF.

**Claude measurements** (`tools/haiku_hot_path_bench.py`, needs your key and a spend limit):

```
pip install "anthropic>=1.0" pillow
export ANTHROPIC_API_KEY=sk-ant-...
# 1. confirm the vision tier for free
python3 tools/haiku_hot_path_bench.py --pages ./pages --sizes 1100,1568,2576 --count-tokens-only
# 2. run the matrix: image / both / text × 1100 / 1568 / 2576 px × thinking disabled / adaptive-low
python3 tools/haiku_hot_path_bench.py --pages ./pages --ocr ./ocr --truth ./truth --out results.jsonl \
    --arms image,both,text --sizes 1100,1568,2576 --thinking disabled,adaptive-low --geo ""
# 3. summarize p50/p95 per arm
python3 tools/haiku_hot_path_bench.py --summarize results.jsonl
```

It records, per request: time to first token, time until `doc_type` is closed in the stream, end-to-end time, input/cache/output tokens (thinking tokens are included in output tokens), stop reason and refusal category, JSON validity, and doc type and date accuracy against the truth files. Run it on Wi-Fi and on LTE from the phone's hotspot. The `ocr/` folder needs the on-device Vision transcripts, so run step 2 after the harness app exists; step 1 can run on day one. The script was written in a sandbox with no API key and has not been executed against the API; expect to fix small things on first run.

**Decisions Phase 0 settles.** Stability window length; whether the text tier stays on the sub-second path on A15 (if `.fast` raw OCR exceeds ~600 ms there, dedup stays visual-first); the exact dedup thresholds; whether thinking-off or adaptive-low wins on Haiku; the image size arm (1,100 vs 1,568 px); whether the Core Graphics PDF/A flag is usable; the full-res ring size per device class.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Apple publishes no Vision latency; A15 numbers could be 2× off either way | Phase 0 before any budget is committed; the S1 haptic is designed never to depend on OCR |
| Image hashes cannot separate same-template siblings; a false "already scanned" would lose a page | No signal ever suppresses capture; merges need text Jaccard plus two agreeing parsed anchors; zero false-skips required on the calibration set |
| Haiku 5.5 thinking-off latency, extraction accuracy on masked handheld pages and refusal rate on medical, ID and financial pages are unmeasured | The UX never waits on Claude; the harness measures all three; client-side Sonnet fallback; an archived-without-metadata state |
| The S1-to-S2 window is a real hole for app deletion or device loss | Honest two-state UI; pending blobs stay in iCloud Backup; fall-through to any verified destination; the 30-minute amber notification; opt-in relay in the service phase |
| Full 5 GB iCloud accounts are common | Quorum fall-through to Drive or NAS; onboarding nudges a second destination |
| Apple's segmenter may underperform on white-on-white, folded or windowed mail | Week-two corpus test; Genius Scan SDK custom-camera components as a plan-B detector behind the same state machine |
| Thermal throttling in long handheld sessions with the torch on | Tiered thermal policy; S1 precedes all heavy work so nothing is lost; pages-until-serious measured on A15 |
| Handheld page-boundary accuracy has no literature; enterprise stream numbers top out at 0.83 to 0.88 | Split bias keeps every page findable; Claude merge suggestions; every decision logged as training data |
| Masking recall on OCR-mangled or handwritten numbers | Word-box masking, normalization, context rules, MICR geometry, CI canary; measured on real mail before it is advertised |
| Undocumented Apple behaviour the plan spikes rather than depends on (`kCGPDFContextCreatePDFA`, `CIDocumentEnhancer` range, rotation coordinator face-down, FeaturePrint thresholds) | In-house writer and custom kernel are the plan of record; thresholds calibrated on device |
| Platform risk: Google's Labs auto-scanner on iOS, or Apple adding auto-advance to VisionKit | The moat is dedup, grouping, understanding, verified multi-destination durability and search, none of which either ships |
| Claude pricing and limit traps: the >100K-token price step on Haiku, the 3,000 px per-image limit on requests with more than 20 images, Evaluation-tier limits, no server-side idempotency | Chunk at 40 pages; keep images at or below 1,568 px; upsert-by-hash apply; request the Build tier at launch; circuit breaker on spend-cap 429 |
| Model price and behaviour drift (Haiku 10× cheaper in a year; Covered Models incompatible with ZDR) | Price on outcome; freeze prompt and schema per app version; store schema versions in sidecars so re-indexing is cheap |
| Solo-developer scope | Phases 1 to 3 are the product; 4 and 5 are revenue-gated; each phase ends with a usable app |
