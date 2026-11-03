# Proposal: speed-first architecture for the zero-interaction paper digitizer

Angle: SPEED-FIRST. Author: principal engineer, writing independently from the 24 research reports in `../research/` and the fact-check corrections. Date: 2026-11-03.

Governing rule: **the only thing the user waits for is the haptic, and the haptic waits only for the local disk.** Everything else (dedup confirmation, OCR, label, PDF, upload, Claude) is a progressive refinement of an already-visible card. Numbers are tagged measured, vendor, estimate or unknown; estimates are inputs for the week-one harness, not promises.

---

## 1. Architecture

```
iPhone (Swift 6, iOS 26.0 min, iOS 27 features gated)
┌──────────────────────────────────────────────────────────────────────────────┐
│ CAPTURE LOOP (never touches network, never waits on anything below it)       │
│  AVCaptureSession .photo preset                                              │
│   ├ VideoDataOutput #1  1280x960 420v  → CaptureActor (every frame, ≤20 ms) │
│   │    DetectDocumentSegmentation ▸ quad IoU/area stability ▸ gyro ▸ Laplacian│
│   │    sharpness vs running max ▸ glare/clip ▸ framing gate ≥0.78 ▸ dHash    │
│   │    ▸ captureReadiness == .ready  ──► capturePhoto()                      │
│   └ PhotoOutput 12 MP .balanced, ZSL+responsive ON, deferred OFF, HEIC       │
│        └► S1 WRITE: temp → F_FULLFSYNC → rename → ledger commit (WAL,FULL)   │
│             ══► haptic + solid card  ("captured", ≤500 ms after settle)      │
├──────────────────────────────────────────────────────────────────────────────┤
│ ON-DEVICE PIPELINE (actors, disk-backed queues, all after the haptic)        │
│  DedupActor   : dHash64 + FeaturePrint rev2 vs archive → "Looks like page N" │
│                 chip (+5–30 ms); .fast raw OCR (correction OFF) on 2–3 MP     │
│                 rectified page → 128-bit SimHash / 9-gram Jaccard + parsed   │
│                 anchor fields → confirm/retract chip ≤1 s; variant link      │
│  LabelActor   : rules (OMB/1099/EOB/MRZ) > sender memory (header feature     │
│                 print + sender kNN) > Create ML text classifier → provisional│
│  EnhanceActor : re-detect quad on still → CIPerspectiveCorrection → Lanczos  │
│                 to 300 ppi → orientation (2-way .fast OCR vote) → document   │
│                 enhancer + background division → unsharp → sRGB JPEG master │
│  OCRActor     : .accurate + correction ON (text layer, FTS) ; detectedData   │
│  RedactActor  : single mask pass over word boxes → maskedImage/maskedText    │
│  PDFActor     : in-house PDF/A-2u writer, glyphless invisible layer, XMP     │
│  GroupActor   : on-device boundary scorer (split-biased) → open/closed docs  │
│  IndexActor   : SQLite FTS5 (porter+trigram) + sqlite-vec + Core Spotlight   │
│  UploadActor  : outbox → iCloud Drive container (OS daemon) │ Drive v3       │
│                 resumable │ Synology WebDAV PUT+MOVE, all background URLSession│
│                 ══► S2 lock icon when ≥1 destination `verified`              │
├──────────────────────────────────────────────────────────────────────────────┤
│ CLOUD (async, streamed, per page, folded into a per-document conversation)   │
│  v1: device → api.anthropic.com directly, BYO key in Keychain                │
│  v2+: device → Cloudflare Worker proxy (App Attest, per-user quota, org key) │
│   Claude Haiku 5.5: thinking disabled, effort low, structured output,        │
│   1,100 px masked JPEG + placeholder OCR lines, cached system prompt;        │
│   doc_type streamed first; corrections by line index; continues_open_document│
│   Claude Sonnet 5.5: refusal/low-confidence/dense-page escalation only       │
└──────────────────────────────────────────────────────────────────────────────┘
Backend in v1: none. v2: one Worker (key custody, quotas, usage). v3: accounts,
opt-in E2EE relay bucket (R2), email ingest, ledger sync.
```

Why this shape is fastest: the camera-to-Vision path is zero-copy (`CMSampleBuffer` 420v straight into Vision, TN3121), the haptic depends on one fsync'd write, and every slower stage runs on its own actor with a `bufferingNewest(1)` frame stream so analysis always sees the latest frame and never backs up the loop.

## 2. Tech stack (versions / minimums)

| Layer | Choice | Why (speed) |
|---|---|---|
| Language/UI | Swift 6 strict concurrency, SwiftUI, Xcode 26 | Actors per stage, no bridge between camera and ML |
| Min OS | **iOS 26.0**; `#available(iOS 27)` for Foundation Models image input, `OCRTool`, Core AI | Same hardware as 27 (A13+), ~80% of iPhones today; floor for `RecognizeDocumentsRequest`, `DetectLensSmudgeRequest`, `BGContinuedProcessingTask` |
| Floor device | iPhone 13 (A15, 12 MP only); acceptance on 13 / 15 Pro / 16 / 17 Pro | Budgets are written for A15 |
| Camera | AVFoundation: 12 MP `.balanced`, ZSL + responsive on, deferred off, `.near` focus restriction, smooth AF off, exposure bias ~+1 EV, max exposure 1/120 s, WB locked per batch | Only 12 MP keeps ZSL and a private archive; 24 MP is deferred-only (Photos ingest), 48 MP "several seconds" |
| Detection/OCR | Vision Swift API: `DetectDocumentSegmentationRequest`, `RecognizeTextRequest` (.fast raw / .accurate corrected), `RecognizeDocumentsRequest`, `GenerateImageFeaturePrintRequest` rev2, `DetectLensSmudgeRequest`, barcodes (pdf417) | On-device, Neural Engine, no licence |
| Enhancement | Core Image + one custom Metal kernel (background division) | GPU, tens of ms |
| Label | Regex rules + feature-print kNN + Create ML `MLTextClassifier` | <5–80 ms, no Apple Intelligence gate, no guardrails |
| Store | GRDB 7.x with bundled SQLite (FTS5 + trigram + sqlite-vec); ops DB (Class C, WAL, `synchronous=FULL`, `fullfsync=ON`) and content DB (Class A) | Bundling removes the unverified system-FTS5 question |
| Embeddings | On-device `bge-small-en-v1.5` (384-d, MIT) via swift-embeddings; sqlite-vec brute force | No Voyage in v1/v2 (trains by default) |
| PDF | In-house Swift PDF/A-2u writer, veraPDF in CI; week-one spike of `kCGPDFContextCreatePDFA` as fallback | Write is milliseconds; byte-copy merging |
| Transport | Background `URLSession` (file-backed), `NSFileCoordinator` + `NSMetadataQuery`, Drive v3 resumable, WebDAV over HTTPS | Only paths that survive suspension |
| Cloud AI | `claude-haiku-5-5`, `claude-sonnet-5-5`, `anthropic-version` pinned, structured outputs GA | See §5 |
| Backend (v2) | Cloudflare Workers + Supabase (Sign in with Apple) | ~$30/mo fixed |
| Telemetry | `OSSignposter` per stage, aggregated histograms only | Never content |

## 3. Stage-by-stage latency budget

Targets are for the page-settled → feedback path on A17+ (A15 in parentheses). "Evidence" cites the measured anchor the target is derived from.

| # | Stage | Feed | Target | Evidence / status |
|---|---|---|---|---|
| 1 | Segmentation per frame | 1280x960 420v | ≤15 ms (≤30) | Apple: "realtime" on Neural Engine (vendor, WWDC21); unmeasured |
| 2 | Stability decision | quad IoU ≥0.95, area Δ ≤5%, 4 consecutive frames + gyro still + sharpness within 10% of running max + framing ≥0.78 | ~130 ms after settle | 33 ms/frame (fact); SDK defaults are 1–3 s hold, this is the single biggest speed win |
| 3 | Still delivery | 12 MP ZSL + responsive, `captureReadiness == .ready` | ≤200 ms (≤300) | WWDC23 "~2 photos/s" before responsive capture (vendor demo); ZSL timestamps earlier than call (header) |
| 4 | S1 write + ledger commit | HEIC bytes, F_FULLFSYNC, rename, 2 fsync'd commits | p95 ≤150 ms | F_FULLFSYNC cost on iPhone NAND unknown (plan 5–50 ms) |
| **=** | **Settle → haptic** | | **≤500 ms (≤700)** | Sum of 2–4; measure in week one |
| 5 | Visual dedup cue | dHash64 + FeaturePrint rev2 (360 px) vs in-memory arrays | +5–30 ms (+10–60) | Hamming scan 200k×256-bit 0.39 ms measured (x86); FeaturePrint latency unknown; MobileCLIP 1.5 ms reference only (licence blocks shipping) |
| 6 | Fast raw OCR for text dedup + label | 2–3 MP rectified page, `.fast`, correction off, `minimumTextHeightFraction` lowered | 150–300 ms (300–600) | text_sight iPhone 16: 101 ms p50 one-shot 63-line page (measured, corrected figure); live 19/s at 1080p |
| 7 | Text-confirmed duplicate + provisional label | SimHash/Jaccard + anchor fields; rules/kNN/classifier | ≤1 s total (≤1.2) | Classifier ≤80 ms (DistilBERT@128 3.47 ms on A15 measured, different model) |
| 8 | Warp + Lanczos + enhance + JPEG master | 12 MP still on GPU | 100–250 ms | estimate; Apple publishes nothing |
| 9 | Orientation vote | two `.fast` passes on 1000 px thumb | ~200 ms (~500) | 101 ms per pass measured |
| 10 | Accurate OCR + correction (layer, FTS) | full-res rectified | 1–3 s (2–6 s) | 404 ms / 736 ms one-shot at text_sight size (measured); full-res unknown, scaled by 5.9× pixels and 2.2× TOPS |
| 11 | PDF/A write | stored JPEG + OCR JSON | <20 ms | structural writer, estimate |
| 12 | iCloud Drive upload → S2 lock | 300–900 KB PDF page | p50 <5 s Wi-Fi, LTE may lag minutes | OS-managed, no SLA; test T11 |
| 13 | Claude Haiku record | 2,190 uncached tokens, 250–400 out | TTFT 0.5–1.5 s, full ~3 s (Wi-Fi) | 165–176 tok/s measured (AA); thinking-off TTFT unknown; Sonnet low 1.2 s anchor |
| 14 | Sustained cadence | 20 pages/min handheld, 10 min | no thermal state ≥ serious before page 100 | unknown; thermal policy §4 |

Throughput check: at 20 pages/min the A15 accurate-OCR queue (stage 10) falls behind arrival (3 s/page); that is acceptable because nothing the user sees depends on it, and the backlog drains in `BGProcessingTask`/`BGContinuedProcessingTask`.

## 4. Zero-interaction capture state machine

States (per session) and transitions:

```
SEARCHING ──quad found, area ≥25%, no corner on edge──► TRACKING
TRACKING ──4 stable frames ∧ sharp ∧ clean ∧ framed ∧ ready──► FIRING
TRACKING ──quad lost 3 frames──► SEARCHING
FIRING ──capturePhoto() issued──► WRITING (freeze overlay, shutter tick)
WRITING ──bytes fsync'd + ledger row (S1)──► CAPTURED (haptic .success, card)
WRITING ──still fails / blurrier than best cached frame──► write best 1280x960… 
          no: write best full-res VideoDataOutput #2 frame (4032x3024, kept
          in a 3-frame ring) as the page, then CAPTURED; swap still in if it lands
CAPTURED ──always──► COOLDOWN (armed = false)
COOLDOWN ──quad lost ≥3 frames (page swap) ∨ dHash of live quad differs
           from the captured page by >6 bits ∨ gyro impulse──► SEARCHING
```

Rules that resolve the research conflicts:

1. **No perceptual hash ever suppresses a capture.** The COOLDOWN re-arm condition is "quad lost" OR "hash changed" OR "motion impulse", whichever comes first, so a hash can only make re-arming happen *sooner* (a new page slid under a stationary phone), never later. Hovering over the page just captured does not re-fire because the quad never left: a geometric gate on the *trigger*, not a decision about the *page*.
2. **Capture always persists.** S1 precedes any dedup logic; a duplicate is a catalog relation (`variant_of`, sharper copy canonical), never a drop.
3. **Duplicate announcement in two beats.** Beat 1 (≤50 ms after the still): the visual tier (dHash64 ≤6 against the session's last 50 pages, FeaturePrint distance under a calibrated threshold against the archive's candidate set) shows a soft chip "Looks like page N · 2 min ago" with a thumbnail and a double-haptic. Beat 2 (≤1 s): `.fast` raw OCR → 9-gram Jaccard ≥ calibrated floor (~0.6 on synthetic data) AND ≥2 parsed anchor fields (date, amount, account/ref, "Page N of M") agree exactly AND none disagree → chip hardens to "Already scanned" with a spoken cue; otherwise it retracts silently and the page is linked "similar to N". Pages under 400 characters or flagged blank never confirm automatically. The candidate index spans the whole archive (12.8 MB of hashes at 200k pages, brute force); the *merge* always requires the text tier.
4. **Page boundaries without taps.** On-device scorer: N-of-M footer in the same position and incrementing (−5/+5), first-page structure (+3), last-page structure on the previous page (+2), form-factor change (+3), letterhead feature-print match (−2/+1), anchor-ID match (−3), pending envelope (+2); the capture gap is a prior only (>60 s or left screen +3; <4 s same quad = duplex-flip prior). Score ≤ −2 appends, ≥ 2 opens a new document, the uncertain band **splits** and marks the new document tentative; Claude's next call returns `suggested_merge_with` and the device auto-merges at `boundary_confidence ≥ 0.8`. Merge/split taps exist as optional telemetry, never as a dependency.
5. **Envelopes** are attachment pages (on-device OCR only unless certified/IRS/court cues), linked `envelope_of` the next document.
6. **Blank backs**: ink coverage <0.5% + PDQ-style quality gate → stored as a flag on the previous page, excluded from hashing.
7. **Feedback vocabulary**: shutter tick + `.success` haptic = captured (S1); lock icon = safe (S2); double-buzz + chip = looks like a duplicate; spoken "already scanned" = text-confirmed; spoken "keep this paper" = `keep_original_flag` class (titles, wills, notarized, undeposited checks, IDs); one amber banner for destination trouble, never a modal. `UINotificationFeedbackGenerator.prepare()` is called on TRACKING entry.
8. **Stand mode** auto-detects (gyro still >3 s): the motion gate relaxes, re-arm relies on quad-lost/hash-changed, 48 MP becomes available as a setting (set before `startRunning()`, `photoProcessingTimeRange` shown as progress).
9. **Thermal policy** (observe `systemPressureState` and `thermalState`): nominal = 30 fps, segmentation every frame, torch ≤0.5 only when exposure says dark; fair = segmentation every 2nd frame, background OCR/PDF paused while camera live, torch ≤0.3; serious = 15–20 fps preview, torch off, stills `.speed`, all stage ≥10 work deferred; critical = session paused with a message, auto-resume. A drop in `maxAvailableTorchLevel` is treated as the first thermal signal.

## 5. Claude usage design

**Models.** `claude-haiku-5-5` for every page ($0.10/$0.50 per MTok ≤100K prompt, cache read $0.01). `claude-sonnet-5-5` ($2/$10, cache read **$0.10**, the $0.20 in the bundled skill is stale) only for `stop_reason: "refusal"`, `confidence < 0.6`, handwriting/non-Latin, or packets >40 pages. Opus has no role.

**Settings.** `thinking: {"type":"disabled"}`, `output_config.effort: "low"`, `output_config.format` json_schema, `stream: true`, `max_tokens: 1500`, one `cache_control` breakpoint on a ~2,500-token system prompt (taxonomy, rules, two compact examples), `metadata.user_id` = opaque per-install hash. Thinking-off is correct here despite Anthropic's general "use effort instead" guidance: the two documented failure modes (skipped tool call with JSON output; reasoning-like prose) cannot occur in a tool-less, grammar-constrained request. Adaptive-low stays in the harness; thinking tokens are read from `usage.output_tokens_details.thinking_tokens` on the final `message_delta`; adopt adaptive only if median thinking tokens <100 and accuracy wins.

**Input.** User turn = `[image, text]`: masked JPEG q85 at **1,100 px long edge** (850×1100 = 1,240 visual tokens at 28-px patches; high-res tier confirmed with one `count_tokens` call on a 1075×1520 image returning 2,145) plus the numbered Vision lines with Class-A placeholders (~800 tokens) and ~150 tokens of context (date, locale, known senders, open-document summary). Escalate to 1,568 px (2,464 tokens) only for low Vision confidence or dense pages. Never above 2,576 px.

**Call structure (speed + grouping in one).** One call per captured page, appended to the open document's prompt-cached conversation: page n+1 is new, pages 1..n are cache reads. The output is the document-so-far record, so per-page feedback is as fast as an independent call and the boundary verdict costs no extra round trip. Chunk at ~40 pages (100K-token price step) and switch to Sonnet for longer packets.

**Schema (required-first so `doc_type` streams within ~0.1 s of TTFT; all fields required, nullable).** `doc_type` (33-value enum incl. marketing, envelope, blank), `continues_open_document: bool`, `boundary_confidence`, `suggested_merge_with`, `expected_page_count`, `doc_subtype`, `language`, `sender{name,address,email,phone}`, `recipient`, `document_date`, `due_date`, `period_start/end`, `tax_year`, `amounts[{label enum,value,currency}]`, `identifiers[{kind enum: tax_id_last4|account_last4|member_id_last4|invoice_number|claim_number|policy_number|case_number|reference|order_number|check_number, value}]`, `people[]`, `organizations[]`, `tags[]`, `title`, `summary` (≤2 sentences), `keep_original: bool`, `sensitive: bool`, `corrections[{line:int,text,reason enum}]`, `confidence`, `needs_review`, `review_reason` (short; no "reasoning" field, which risks a `reasoning_extraction` refusal). No PHI in enum/const/pattern values. Freeze schema + system prompt + thinking/effort per app version (any change restarts the 24-h grammar cache and the prompt cache); warm the grammar at launch.

**Search-query call.** Same model/settings, tiny filter schema, ~150 in / ~80 out, fired in parallel with the deterministic on-device parse; results re-render only if the set changes.

**Refusals and retries.** Refusal is HTTP 200 with `stop_reason: "refusal"`; Haiku has no server fallback and no fallback credit, so retry once on Sonnet 5.5 client-side; if it also refuses, `metadata_refused`, page stays archived with the on-device label. No idempotency key exists, so apply is an upsert by page hash; commit only from `end_turn` + schema-valid parse; 429 with `retry-after` sleeps that long; spend-cap 429 opens a circuit breaker; 5xx/529/timeouts use jittered backoff, 8 attempts over 10 min, then park for a nightly inline sweep. SDK timeout ~45 s, `max_retries` 0–1.

**Feature scope.** Inline `/v1/messages` only. **No Batches, no Files API** (not ZDR-eligible; ZDR does not block them, so a CI rule must). Backfill = inline text-only Haiku at ~$0.0006/page.

**Cost per document (list prices, computed).** Single-page document arm A (1,100 px + OCR, 400 out): **$0.00044**. Multi-page via cached conversation: ~$0.003 per 5-page packet (~$0.0006/page). 10% Sonnet escalation adds ~$0.0009/page. Embeddings on-device: $0. Planning number: **$0.002 per document blended** (≈$0.0008 Haiku-only), i.e. a 150-page/month user costs well under $0.30/month in AI.

## 6. Durability and the "safe to shred" guarantee

One vocabulary, enforced in code and UI (gap-4):

| State | Meaning | Signal | Time |
|---|---|---|---|
| S0 framed | in memory | none | — |
| **S1 captured** | corrected page bytes F_FULLFSYNC'd + atomically renamed; ledger row committed (WAL, `synchronous=FULL`, `fullfsync=ON`) | haptic, solid card | ≤150 ms p95 after still |
| **S2 safe** | ≥1 destination row `verified` (server hash match, or iCloud `isUploaded && uploadingError == nil` + size + identity-token hash) | lock icon | seconds on Wi-Fi, minutes on LTE, honest counter "17 safe · 3 uploading" |
| S3 replicated | every enabled destination `verified` | nothing on capture screen | background |

S1 survives app crash, force-quit, reboot and 48 h of airplane mode; it does not survive app deletion or device loss. Product copy: *"Captured" means it is safely on this phone; the lock means it is also in your iCloud Drive / Google Drive / NAS; throw the paper away when the lock shows.* A "shred-safe" toggle that withholds the haptic until S2 is offered, never default.

**First off-device hop (v1, no backend): the iCloud Drive ubiquity container `Documents/PaperVault/YYYY/`** via `NSFileCoordinator`: the OS daemon moves the bytes independently of the app process, the files survive app deletion, they are Files-visible and user-owned, and ADP users get E2EE for free. CloudKit `CKAsset` is **not** used for bytes (quota spent twice, invisible in Files, iCloud-Keychain-bound). Any destination that verifies first satisfies S2, so a full 5 GB iCloud account falls through to Drive/NAS; with none reachable, capture continues under a single amber state. The service-phase relay (R2, E2EE, 30-day TTL) is opt-in, not the definition of "captured".

**Uploaded first**: the per-page PDF/A (300–900 KB), not the raw HEIC (local cache, Wi-Fi-only mirror, never gates S2); at 30 pages/min that is ~1.2 Mbit/s.

**Data Protection classes (resolves privacy.md vs apple.md).** Ops DB, outbox staging blobs, ubiquity files: **Class C** (daemons must read after lock; GRDB throws SQLITE_IOERR/AUTH on protected DBs). Vault blobs after S3 and the content/FTS DB: **Class A**. Enrichment results produced while locked: **Class B** per-page files merged at `protectedDataDidBecomeAvailable`. Keychain: `AfterFirstUnlockThisDeviceOnly` for OAuth tokens and anything the uploader needs; `WhenPasscodeSetThisDeviceOnly` only for the content-DB key. Pending blobs stay inside iCloud Backup; `isExcludedFromBackup` only after S3 and re-applied on every rewrite.

**Outbox.** Per (page, destination): `pending → staged(C) → uploading(session_uri,bytes) → uploaded(remote_id) → verified → named → audited | failed(retry_at) | needs_attention`. Uploads are enqueued in the foreground (non-discretionary), batched, and reconciled against `getAllTasks()` on every launch. Idempotent by content hash: Drive pre-generated ids (409 on replay), Synology `_inbox/` PUT then `MOVE Overwrite: F`, deterministic PDF emission (`/ID[0]` and `xmpMM:DocumentID` from the capture-time ULID, `CreationDate` = capture time, replayed JPEG and OCR JSON) so a replay is byte-identical. Nightly `BGProcessingTask` audit (Drive `changes.list`, Synology `PROPFIND`, iCloud gather at launch, 1-in-20 read-back) re-uploads missing files from the local blob (kept until S3 + 7 days) or a sibling destination, adopts user renames, flags overwrites, never propagates deletions. Gap-4's 24-case device test matrix is a release gate.

## 7. Search design

On-device only in v1 and v2; it is what makes search feel instant (<50 ms) and offline.

- **Lexical**: external-content FTS5 over `title(10) / tags(5) / summary(3) / sender(3) / masked_ocr_text(1)` with `porter unicode61`, plus a trigram FTS5 shadow over masked text and identifier variants for OCR-mangled names and partial last-4s.
- **Structured**: `documents` with denormalized facets (doc_type, sender_key, doc_date, tax_year, amounts as cents, people, keep_original), per-page rows, materialized facet counts.
- **Semantic**: bge-small 384-d int8 vectors in sqlite-vec with `doc_type`/`tax_year` metadata columns, embedding each ~300-token chunk of masked text with the document's title/sender/date prepended (free "contextual retrieval"); `embedding_model` stored per vector.
- **Fusion**: RRF k=60 over BM25 and vector lists; filters as hard SQL constraints.
- **Query understanding**: a deterministic parser (NSDataDetector dates, relative-period grammar, doc_type synonyms, known `sender_key` dictionary, tax-year regex, amounts) answers in <10 ms; the Haiku filter-JSON call refines asynchronously; Foundation Models `@Generable` is an offline refiner on A17 Pro+ only.
- **Aggregates** ("how much did I pay X in 2025"): SQL over extracted `amount_*` fields, never summing PDFs through a model; free-form questions go to Claude with `citations` over top-20 chunks.
- **System surface**: every document donated to a named Core Spotlight index (`.complete`) with `title`, `textContent` = summary + tags + sender (never raw OCR, never Class A); `IndexedEntity` for Siri; `CSUserQuery.prepare()` before showing search.
- **Portable**: every destination gets the PDF text layer, a `<name>.json` sidecar and a `_vault/index.jsonl`, so Drive `fullText`, Synology Universal Search and a reinstall work from the files alone. Drive `indexableText` carries summary + tags + doc_type + sender.
- **Eval**: 150 labelled queries over the founder's mail, nDCG@10 / Recall@20 via `ranx`, in CI against the app's own SQLite file.

## 8. Output / PDF design

- **Capture resolution**: 12 MP. "Print-ready" means FADGI Modern Textual Records (≥294 ppi). 12 MP reaches it on Letter only when the page fills ≥82% of the long axis, so the **framing gate (quad long side ≥0.78 of frame)** is the real lever: 286+ ppi on Letter, 269+ on A4, at a 23–25 cm working distance; receipts/cards fire when implied ppi ≥300. Marketing copy: "300 ppi when framed, never below 200 ppi" until slanted-edge SFR is measured. 48 MP is stand-mode only; 24 MP is rejected.
- **Master**: perspective-corrected, Lanczos-downsampled to 300 ppi (never upsampled), upright pixels with `/Rotate 0`, document-enhanced + background-divided, white-point corrected, unsharp, 8-bit grey or colour by saturation histogram, sRGB JPEG q≈50 (0.3–0.9 MB). Bilevel/JBIG2 (lossless generic only) and MRC are "compact" derivatives, never the master. The HEIC original is kept locally until S3 + 7 days ("keep negatives" setting for forever) so creases can be re-rendered when UVDoc (MIT, 8 M params, runtime unknown) is ported to Core ML in v1.5.
- **Page size (MediaBox)**: quad aspect within 3% of a standard size, tie-broken by locale prior, text line height / receipt column count, LiDAR depth + intrinsics on Pro models, and Claude's class; `pap:pageSizeSource` in XMP so it can be corrected without touching pixels.
- **PDF/A-2u writer (in-house)**: one JPEG XObject per page (DCT pass-through), GlyphLessFont invisible layer from Vision `.accurate` word boxes (`3 Tr`, `Tz` fitting, explicit spaces, ToUnicode identity), sRGB OutputIntent, Info + XMP with a `pap:` extension schema (id, sha256, sender, doctype, dates, amounts, ocrEngine, textLayerVersion, pageSizeSource), deterministic trailer `/ID`. veraPDF gates every CI build. A week-one spike runs `kCGPDFContextCreatePDFA` (header: "conforms to PDF/A-2u") through veraPDF; pass = v0 fallback, fail = question closed in a day.
- **Immutable bytes, mutable label**: the PDF is built once at S1 and uploaded under a provisional name `YYYY-MM-DD_unsorted_unsorted_<id8>.pdf`; when Claude lands it becomes `YYYY-MM-DD_<sender>_<doctype>_<id8>.pdf` by a metadata-only rename (Drive `files.update`, WebDAV `MOVE`, coordinated move), late-bound at task creation when the record arrives first. The PDF is rewritten and re-verified only when Claude's `corrections` are material (a validated anchor changed or >2% of characters), expected to be rare.
- **Unit**: page = capture, dedup and durability; document = PDF, naming and search. Per-page PDFs go to a hidden `_pages/` folder immediately; the document PDF is assembled by byte-copying page objects at `confirmed` (closed + Claude verdict or 60 s) and sealed after 24 h.
- **Export**: `UIPrintInteractionController`, `UIActivityViewController`, ZIPFoundation bundles with `index.csv`/`index.json` and a bookmarked combined PDF for tax-year/expense packs, mail compose for packs under ~25 MB.

## 9. Storage destinations

| Destination | Transport | Commit | Verify | Rename | Notes |
|---|---|---|---|---|---|
| iCloud Drive | ubiquity container `Documents/PaperVault/`, `setUbiquitous`/coordinated write off main thread | OS daemon | one app-lifetime `NSMetadataQuery`: `IsUploaded && UploadingError == nil` + size + archived `ubiquityIdentityToken` hash; freeze on `NSUbiquityIdentityDidChange` | coordinated move | default first hop; falls through on quota |
| Google Drive | REST v3, **`drive.file` only** (non-sensitive, no CASA), `generateIds` pool, persisted resumable session, single file-backed `PUT` from a background task | 200/201 or 409 → `files.get` | `sha256Checksum` + `size` (strongest of the three) | `PATCH name/addParents/removeParents` | 401 → refresh token, `Content-Range: bytes */N` probe, new task on the same session URI; `appProperties {sid,h}` (124-byte cap) |
| Synology | **WebDAV over HTTPS (5006) with a publicly trusted certificate** (DSM Let's Encrypt on `synology.me`, Tailscale + `tailscale cert`, or a user-installed CA profile); File Station API optional (`SYNO.API.Auth` v6 `otp_code` + `enable_device_token` once, `device_id` thereafter) | `PUT /_inbox/<id>.pdf` | `PROPFIND Depth:0` size, `SYNO.FileStation.MD5` job when linked (guide updated for DSM 7.0), sampled read-back otherwise | `MOVE Overwrite: F` to `/YYYY/` | No SMB (foreground-only), no QuickConnect, **no fingerprint prompt** (ATS forbids loosening trust in the delegate); static `NSExceptionDomains` CIDR entries for private ranges |
| Later | Dropbox (`content_hash`), OneDrive (Graph upload session), S3-compatible (`x-amz-checksum-sha256`), Paperless-ngx consume/API | | | | same outbox, same naming |

Same path layout and naming in every destination; quorum for S2 = 1 verified (Drive or Synology-with-MD5 preferred over iCloud when several are enabled because they carry a server digest).

## 10. Privacy / compliance posture

- **Three-class data policy, one on-device mask pass** (gap-10). Class A secrets (SSN/ITIN, PAN, bank/routing + MICR band, DL/passport numbers, MRN/member IDs) exist only inside the archival PDF in the user's own storage; everywhere else carries `last4` placeholders: Claude request (masked JPEG + `[SSN ••••1234]` lines), structured output, sidecar, FTS (indexes masked text), Spotlight, Drive `indexableText`, embeddings, filenames, logs. Class B reference IDs and Class C text flow in plaintext. The `Redactor` output is the only text later stages may read except the PDF writer. Identity documents (aspect 1.586, MRZ, pdf417) go text-only to Claude. A CI canary asserts synthetic Class A values appear in no outbound request, index, sidecar or filename. Taxonomy edits: every identifier becomes `*_last4`; `micr_routing` and full `account_number` are deleted.
- **Sensitivity gate** = regex rule hit (OMB 1545-, 1099/W-2/1098/1095, EOB/CPT/NPI/Rx, MRZ/pdf417, SSN pattern) OR classifier posterior >0.3 on tax/medical/ID/insurance-claim/court classes; computed before the Claude call, never by Foundation Models (its guardrails fire on exactly those pages).
- **v1 (personal, BYO key, no backend, no account)**: key in Keychain, calls device → `api.anthropic.com` only (never through a developer server; consumer keys may not be shared, AUP forbids proxying through consumer subscriptions; API keys only, no Claude.ai login), standard 30-day retention under the user's own Anthropic agreement; no analytics SDKs; privacy policy can truthfully say "we collect nothing".
- **v2 (App Store)**: LLC and Organization enrolment before submission (5.1.1(ix) "should" for sensitive information; a later transfer changes the Team ID and forces a Keychain re-login); one-time revocable consent naming Anthropic (5.1.2(i)); one superset nutrition label "Data Linked to You, App Functionality, no tracking"; `ITSAppUsesNonExemptEncryption=false` by staying on OS Data Protection + CryptoKit + TLS; free on-device tier so the key is optional; per-document "keep the original" label; WA MHMDA section; a "Shred" action honest about provider trash and NAS snapshots.
- **v3 (service)**: own Anthropic org with **ZDR** on Haiku/Sonnet 5.5 (not Covered Models; Batches/Files excluded by CI), DPA, consent copy including the 2-year trust-and-safety carve-out; `inference_geo` global unless a contract needs `us` (1.1×); App Attest + Sign in with Apple + in-app deletion; client-side E2EE relay with recovery key; FTC HBNR runbook (60-day consumer notice, FTC notice for any breach, penalty floor $53,088 per violation as of Jan 2025); SOC 2 Type I at launch; a separate HIPAA-ready org only if selling to providers.
- **Retention law**: Rev. Proc. 97-22 permits destroying paper once the system is tested; the "how your archive works" page doubles as its system description. "Safe to discard" is per class; vital records, wills, titles, notarized and bearer instruments announce "keep this paper".

## 11. Phased delivery (solo senior iOS developer, ~30 productive h/week, AI-assisted)

| Phase | Weeks | Scope | Exit milestone |
|---|---|---|---|
| 0 Measure | 1–2 | `OSSignposter` harness on the four devices; 200-page handheld golden run (20 ppm, cold and preheated, Xcode thermal simulation); calibration set (200 pages ×5 recaptures, 50 sibling pairs, 20 few-field pairs, 30 receipts, 20 blank backs); Vision CER between captures; FeaturePrint latency and distance ROC; `count_tokens` tier check and the Haiku hot-path matrix (~$1); `kCGPDFContextCreatePDFA` veraPDF spike | Every estimate in §3 replaced by a p50/p95; dedup thresholds with zero false-skips on the set |
| 1 Capture core (v0 personal) | 3–8 | State machine, S1 durability (fsync, WAL, crash injection), two-beat dedup, two-pass Vision OCR, rules + sender-memory label, enhancement chain, PDF/A-2u writer + veraPDF CI, iCloud Drive hop with `NSMetadataQuery` verification, FTS5 + facets + deterministic parser, BYO-key Haiku call per page (streamed, structured, incremental conversation), Redactor + canary test, thermal policy | Founder digitizes his own mail daily; settle→haptic ≤500 ms p95 on 15 Pro, ≤700 ms on 13; 20 ppm for 10 min without `serious` |
| 2 Destinations + understanding (TestFlight) | 9–14 | Google Drive and Synology connectors with verify/rename/audit, outbox reconciliation and the 24-case device matrix, boundary scorer + Claude merge suggestions, envelope/blank/duplex handling, on-device embeddings + RRF + Spotlight + `IndexedEntity`, export packs, Create ML classifier from Claude labels, Sonnet escalation + refusal path, search eval harness, 20–50 testers | p50/p95 "in frame → captured" and "captured → safe" published; boundary accuracy measured on 200 packets |
| 3 App Store | 15–22 | LLC + Org enrolment, StoreKit 2 (managed $49.99/yr, ~500-page fair-use cap, BYO free tier, Family Sharing, 14-day trial), consent + labels + privacy manifest, Cloudflare Worker proxy with App Attest and quotas, ZDR request, ASO in Business, 48 MP stand mode, UVDoc Core ML spike | Public release; AI COGS <10% of net at 200 pages/user/month |
| 4 Service | months 6–9 | Supabase accounts + Sign in with Apple, opt-in E2EE relay (R2), CloudKit ledger mirror, Email Worker forwarding-address ingest + share extension, born-digital PDF path, EventKit reminders + passive digest, Drive `changes.watch` inbox, B2B seats, Android scoping | Multi-tenant service; ~9 months total |

Budget half of phases 1–2 for the capture loop and durability; they are the product.

## 12. What the founder must provide

- **Keys/accounts**: Anthropic Console org + key (confirm tier; Evaluation-tier limits can throttle a beta) with a spend limit; later a sales conversation for ZDR. Google Cloud project (`drive.file`, brand verification on an owned domain with privacy policy, consent screen published). Apple Developer Organization (LLC, D-U-N-S, domain email) and App Store Connect analytics for iOS 18/26/27 and chip cohorts. Cloudflare account + domain (v2/v3). Synology DSM version, 2FA status, and whether the NAS can get a public certificate.
- **Devices**: iPhone 13, 15 Pro, 16, 17 Pro; a stand.
- **Test corpus**: ~200 real pages of his own mail with typed ground truth (doc_type, sender, date, amounts, last4), including same-sender statements across months, utility bills, EOBs, receipts, envelopes, duplex letters, blank backs, handwritten and faded items; 150 natural-language queries; a week's count of marketing vs real mail.
- **Decisions**: haptic at S1 with lock at S2 (default) vs shred-safe mode; iOS 26 floor; 12 MP + framing gate; junk archived but hidden; split-biased boundaries; "Looks like page N" wording; LLC before App Store; no Voyage; whether Legal-size paper matters.

## 13. Top risks and mitigations

1. **No Apple latency for any Vision request; A15 numbers could be 2× off.** Phase-0 harness before budgets are committed; if `.fast` raw OCR exceeds ~600 ms on A15, dedup stays visual-first and the text tier leaves the feedback path.
2. **Hashes cannot separate this month's statement from last month's (synthetic sibling dHash 0–6 vs same-page 0–5).** Hashes only hint; merges need Jaccard + two agreeing parsed fields; false-skip must be 0 on the calibration set; capture always persists.
3. **Haiku thinking-off TTFT from a phone and refusal rate on medical/ID pages are unmeasured.** The UX never waits on Claude; harness measures both; Sonnet client-side fallback; archived-without-metadata state.
4. **The S1→S2 window is a real hole for app deletion/device loss.** Stated in the durability doc; pending blobs stay in iCloud Backup; opt-in relay in the service phase; notification after N hours pending.
5. **Full 5 GB iCloud accounts are common.** Fall-through to any verified destination; onboarding nudges a second one.
6. **Segmenter quality on white-on-white, folded, windowed mail is unknown.** Week-two corpus test; Genius Scan SDK (custom-camera components) as plan-B detector behind the same state machine.
7. **Thermal throttling on long sessions is unmeasured.** Tiered policy in §4; S1 precedes all heavy work so nothing is lost.
8. **Handheld boundary accuracy has no literature; enterprise stream numbers top out at 0.83–0.88.** Split bias keeps every page findable; Claude merge suggestions; every decision logged.
9. **Masking recall on OCR-mangled or handwritten numbers.** Word-box masking, O/0 l/1 normalization, context rules, MICR geometry; measured before it is advertised.
10. **Google's Labs auto-scanner on iOS or Apple adding auto-advance to VisionKit.** The moat is dedup, grouping, understanding, multi-destination durability and search.
11. **`kCGPDFContextCreatePDFA` and `CIDocumentEnhancer` are undocumented.** Both are spikes; the in-house writer and custom kernel are the plan of record.
12. **Haiku's >100K-token price step and the >20-image 3,000 px rule.** Chunk at 40 pages; never send >20 images per request.

## 14. Where this proposal deliberately disagrees with the research

1. **capture.md / dedup.md: dHash suppresses re-capture; dedup.md auto-skips.** A hash may only accelerate re-arming; the trigger gate is geometric. Nothing is ever skipped: "already scanned" is a two-beat chip plus a catalog relation.
2. **capture.md: 6-frame stability window.** Four frames plus gyro (~130 ms) once sharpness is judged against the page's running max; this window is the biggest per-page lever and SDK defaults sit at 1–3 s.
3. **apple.md: "captured" only after local write AND CloudKit upload; CKAsset as first hop.** Fails offline, adds seconds, spends iCloud quota twice, ties durability to iCloud Keychain. Haptic at S1; the iCloud Drive container is the hop.
4. **storage.md: R2 escrow as the v1 first commit; output.md: "<150 ms to captured + deduped".** v1 has no backend; captured is ≤500 ms, the visual cue follows, text confirmation lands within a second.
5. **output.md: 24 MP for all captures; apple.md: 48 MP with ZSL.** 24 MP is deferred-only and goes to Photos; 48 MP forfeits ZSL and takes seconds. 12 MP plus a framing gate handheld; 48 MP in stand mode.
6. **architecture.md / apple.md: Foundation Models as the instant label.** Unavailable on the floor device, text-only on iOS 26, 1–3 s on a full transcript, and its guardrails fire on exactly the sensitive classes. Rules + sender memory + Create ML instead.
7. **ocr.md: Mistral OCR 4 / PaddleOCR fallback.** Not in v1–v2: a third-party flow of full page images, warm-GPU economics, no measured gain on photographed mail over Vision + Claude line corrections. Revisit if Vision CER exceeds ~5%.
8. **output.md: language correction ON for everything.** Correction corrupts codes ("C001 → cool", Apple). Raw `.fast` for anchors, corrected `.accurate` for the layer.
9. **search.md / claude.md / business.md: Voyage embeddings.** Voyage trains by default and the free tier is per account. On-device bge-small suffices and keeps the "nothing leaves but masked Claude requests" story true.
10. **mail.md: junk purged after 30 days, one-tap merge/split as the mechanism; dedup.md: K=5 session pass.** Junk is archived forever and hidden by default (and its Claude call is skipped once the classifier is confident). Taps are optional telemetry. K=5 is measurably worse (F1 0.795 vs 0.969 on forms); boundaries are pairwise inside the per-page call.
11. **claude.md: proxy-only with BYO as a power-user path.** Reversed for v1 and the free tier: device-direct BYO is the privacy story and needs no backend; the proxy arrives with the managed tier.
12. **claude.md / gap-6: "no separate thinking-token usage field".** `usage.output_tokens_details.thinking_tokens` exists; the harness reads it.
13. **storage.md: NAS fingerprint prompt; apple.md: SMB over background URLSession.** Neither works under ATS / background sessions; certificate recipes replace the prompt, SMB is dropped.
14. **privacy.md Class A everywhere vs apple.md Class C everywhere.** Both right about different files; §6's per-store table is the one answer.
15. **business.md: 1,568 px at ~1,560 tokens (legacy /750 formula).** At 28-px patches that is 2,464; the planning arm is 1,100 px / 1,240 tokens at $0.00044 per page.
16. **competitors.md: the gap is raw hands-free capture.** Genius Scan and Adobe already auto-capture in batch mode; the gap is sub-second feedback plus dedup, grouping, understanding, durable multi-destination delivery and search. The capture loop is custom, but the moat is everything after S1.
