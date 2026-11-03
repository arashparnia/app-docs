# Architecture: plan of record

Date: 2026-11-03. This is the synthesis of three independent architecture proposals (`design/proposal-*.md`) as scored by two judges, with the fact-check corrections applied (`research/CORRECTIONS.md`). The speed-first proposal is the backbone; the local-first proposal contributed the phasing and recovery design; the service-scale proposal contributed the capacity planning, the in-track sharper replacement, and the opt-in relay. Every number is tagged **measured**, **vendor** (a vendor claim), **estimate**, or **unknown**. Phase 0 (see `04-roadmap.md`) exists to replace the estimates.

## 1. Governing rules

1. **The only thing the user waits for is the haptic, and the haptic waits only for the local disk.** Dedup confirmation, OCR, the label, the PDF, the upload and the Claude call are progressive refinements of a card that is already visible.
2. **No duplicate signal ever suppresses a capture.** Capture re-arming is gated by geometry (the page left the frame, or a different page replaced it); hashes and text can only make re-arming happen sooner, or announce a likely duplicate. Every capture persists; duplicates are catalog relations.
3. **Page is the unit of capture, dedup and durability. Document is the unit of understanding, naming, PDF and search.** A wrong document boundary can mislabel grouping; it can never lose a page.
4. **Vision owns geometry and text; Claude owns meaning.** Claude never blocks anything the user sees and its output is regenerable metadata.
5. **User-owned storage is the system of record.** "Safe" means a verified copy exists outside the phone. The developer holds nothing in v1.
6. **One sensitive-data policy, one redaction pass.** Full secrets exist only inside the archival PDF in the user's own storage.
7. **Measure before promising.** Apple publishes no latency for any Vision request; all on-device budgets below are derived from one third-party iPhone 16 measurement and must be replaced by Phase 0 numbers on an iPhone 13.

## 2. System shape

```
iPhone (Swift 6 strict concurrency, SwiftUI, iOS 26.0 minimum, iOS 27 features gated)
┌──────────────────────────────────────────────────────────────────────────────┐
│ CAPTURE LOOP: never touches the network, never waits on anything below it   │
│  AVCaptureSession (.photo preset)                                            │
│   ├ VideoDataOutput A: 1280x960 420v → CaptureActor, every frame            │
│   │    DetectDocumentSegmentationRequest ▸ quad stability (IoU/area)         │
│   │    ▸ gyro stillness ▸ Laplacian sharpness vs running max ▸ glare/clip    │
│   │    ▸ framing gate (quad long side ≥ 0.78 of frame) ▸ dHash of quad       │
│   │    ▸ captureReadiness == .ready ──────────────► capturePhoto()           │
│   ├ VideoDataOutput B: full-res 420v, 1-frame ring (A15) / 3-frame (A17+)    │
│   │    best sharp frame kept as the fallback page if the still is late/blurry│
│   └ PhotoOutput: 12 MP .balanced, zero shutter lag + responsive capture ON,  │
│        deferred delivery OFF, HEIC/JPEG                                      │
│        └► S1 WRITE: temp → F_FULLFSYNC → atomic rename → ledger commit       │
│            (SQLite WAL, synchronous=FULL, fullfsync=ON)                      │
│            ══► haptic + solid card: "captured"                              │
├──────────────────────────────────────────────────────────────────────────────┤
│ ON-DEVICE PIPELINE: Swift actors over disk-backed queues, all after the haptic│
│  DedupActor    dHash64 + Vision FeaturePrint vs archive → "Looks like page N"│
│                chip; .fast raw OCR (correction OFF) on 2-3 MP rectified page │
│                → 9-gram Jaccard + parsed anchor fields → confirm/retract ≤1 s│
│  LabelActor    regex rules > sender memory (feature-print kNN) > Create ML   │
│                text classifier → provisional doc_type in <100 ms after OCR  │
│  EnhanceActor  re-detect quad on still → CIPerspectiveCorrection → Lanczos   │
│                to 300 ppi → orientation vote → document enhancer + background│
│                division → unsharp → sRGB JPEG master                         │
│  OCRActor      .accurate + correction ON (text layer, FTS); data detectors   │
│  RedactActor   one mask pass over word boxes → maskedImage, maskedText       │
│  PDFActor      in-house PDF/A-2u writer: JPEG + invisible glyphless layer    │
│  GroupActor    split-biased boundary scorer → open/closed documents          │
│  IndexActor    SQLite FTS5 (porter + trigram) + sqlite-vec + Core Spotlight  │
│  UploadActor   outbox per (page, destination) → background URLSession →      │
│                iCloud Drive container │ Google Drive v3 │ Synology WebDAV    │
│                ══► lock icon when ≥1 destination verified ("safe")           │
├──────────────────────────────────────────────────────────────────────────────┤
│ CLOUD: asynchronous, streamed, one call per page folded into a per-document  │
│ prompt-cached conversation                                                   │
│  v1: device → api.anthropic.com directly, your key in Keychain               │
│  v2+: device → Cloudflare Worker proxy (App Attest, per-user quota, org key) │
│  claude-haiku-5-5: thinking off, effort low, structured output, doc_type     │
│   streamed first, masked 1,100 px JPEG + placeholder OCR lines, cached prompt│
│  claude-sonnet-5-5: refusal / low-confidence / dense-page escalation only   │
└──────────────────────────────────────────────────────────────────────────────┘
Backend: none in v1. v2: one Worker (key custody, quotas). v3: accounts, opt-in
encrypted relay bucket, email ingest, ledger sync.
```

Why this shape is fastest: the camera-to-Vision path is zero-copy (`CMSampleBuffer` straight into Vision), the haptic depends on one fsync'd write, and every slower stage runs on its own actor with a `bufferingNewest(1)` frame stream so analysis always sees the latest frame and never backs up the capture loop.

## 3. Tech stack

| Layer | Choice | Why |
|---|---|---|
| Language and UI | Swift 6 strict concurrency, SwiftUI, Xcode 26 | Actor per stage, no bridge between camera and ML. Native is the only option for a camera-heavy latency-critical app maintained by one person. |
| Minimum OS | **iOS 26.0**, `#available(iOS 27)` for Foundation Models image input, `OCRTool`, Core AI | Same hardware as iOS 27 (A13 and later); Apple measured ~79% of iPhones on iOS 26 by June 2026; iOS 26 is the floor for `RecognizeDocumentsRequest`, `DetectLensSmudgeRequest`, `BGContinuedProcessingTask`. Revisit an iOS 27 floor mid-2027. |
| Floor device | iPhone 13 (A15); acceptance on 13 / 15 Pro / 16 / 17 Pro | Budgets are written for A15. |
| Camera | AVFoundation: 12 MP `.balanced`, ZSL + responsive capture on, deferred delivery off, `.near` focus range restriction, smooth autofocus off, exposure bias about +1 EV with a clipping check, max exposure duration ~1/120 s, white balance locked per batch, geometric distortion correction on | Only 12 MP keeps zero-shutter-lag and a private archive: 24 MP is served only through deferred delivery into Photos (SDK header), 48 MP processing "can take several seconds" (WWDC26). |
| Detection and OCR | Vision Swift API: `DetectDocumentSegmentationRequest`, `RecognizeTextRequest` (.fast raw / .accurate corrected), `RecognizeDocumentsRequest`, `GenerateImageFeaturePrintRequest`, `DetectLensSmudgeRequest`, barcode detection (pdf417 for IDs) | On-device, Neural Engine, no licence. |
| Enhancement | Core Image plus one custom Metal kernel (background division) | GPU, tens of milliseconds (estimate). |
| Instant label | Regex rules + feature-print sender memory + Create ML `MLTextClassifier` | Under 100 ms after fast OCR on every iOS 26 device; no Apple Intelligence gate, no guardrails. |
| Store | GRDB 7.x with bundled SQLite (FTS5 porter + trigram, sqlite-vec). Two databases: ops (Class C, WAL, `synchronous=FULL`, `fullfsync=ON`) and content (Class A) | Bundling removes the question of whether system SQLite ships FTS5/trigram; SwiftData and Core Data have no FTS. |
| Embeddings | On-device `bge-small-en-v1.5` (384-d, MIT) via swift-embeddings, int8 in sqlite-vec | Voyage AI trains on inputs by default and would be a second third-party flow of full document text; not in v1/v2. |
| PDF | In-house Swift PDF/A-2u writer, veraPDF in CI; one-day spike of `kCGPDFContextCreatePDFA` (iOS 14 header says "conforms to PDF/A-2u", undocumented) as fallback | Writes in milliseconds; byte-copy merging never re-encodes the archival image. |
| Transport | Background `URLSession` (file-backed tasks), `NSFileCoordinator` + `NSMetadataQuery`, Google Drive v3 resumable upload, WebDAV over HTTPS | The only paths that survive app suspension. |
| Cloud AI | `claude-haiku-5-5`, `claude-sonnet-5-5`, pinned `anthropic-version`, structured outputs | Section 7. |
| Backend (v2+) | Cloudflare Workers (+ Queues, R2) and Supabase (Postgres, Auth with native Sign in with Apple) | About $30/month fixed; AI cost dominates at every scale. |
| Telemetry | `OSSignposter` per stage; aggregated histograms only, never content | Phase 0 harness and production. |

## 4. The capture state machine

```
SEARCHING ── quad found, area ≥ 25% of frame, no corner on the frame edge ──► TRACKING
TRACKING  ── N stable frames ∧ sharp ∧ clean ∧ framed ∧ readiness == .ready ──► FIRING
TRACKING  ── quad lost for 3 frames ──► SEARCHING
FIRING    ── capturePhoto() issued; overlay freezes; shutter tick ──► WRITING
WRITING   ── still delivered, bytes fsync'd, ledger row committed (S1) ──► CAPTURED
WRITING   ── still late (> budget) or blurrier than the best ring frame ──►
             write the best full-resolution ring frame as the page, reach CAPTURED,
             then swap the still in as a sharper variant when it lands
CAPTURED  ── haptic .success, solid card ──► COOLDOWN (armed = false)
COOLDOWN  ── quad lost ≥ 3 frames (page lifted)
          ∨ quad IoU < 0.6 jump without loss (page swapped in place under a stand)
          ∨ dHash of the live quad differs from the captured page by > 6 bits
          ∨ gyro impulse ──► SEARCHING
```

Design points:

- **Stability window.** N is a Phase 0 parameter, not a promise: 4 frames (~130 ms at 30 fps) if the false-fire rate on the calibration corpus allows it, 6 frames (~200 ms) otherwise. Commercial SDK defaults hold for 1 to 3 seconds; this window is the single biggest per-page speed win. Stability means quad IoU ≥ 0.95 and area delta ≤ 5% across the window, gyro rotation rate under a threshold, and Laplacian sharpness within 10% of the page's running maximum (judging against the running max, not an absolute, is what lets handheld capture fire quickly).
- **Framing gate.** Fire only when the quad's long side is ≥ 0.78 of the frame's long axis, which puts 12 MP at 286+ ppi on Letter and 269+ on A4 (about 23 to 25 cm working distance). For receipts, cards and envelopes, fire when implied ppi ≥ 300 or the camera hits its minimum focus distance. The preview rectangle and a soft "closer" cue teach the user; nobody taps.
- **Full-resolution ring.** VideoDataOutput B keeps the sharpest recent full-res frame so the haptic never waits on the image signal processor. Memory budget: a 1-frame ring on A15, 3 frames on A17+ (a 3-frame 4032x3024 420v ring is about 55 MB; memory pressure alongside responsive capture is a known risk on A15, so the ring size is a device-class setting).
- **In-track sharper replacement.** If a later frame or still of the same page is more than 25% sharper, it silently replaces the committed page as a variant (the original is kept). Soft handheld captures self-heal without a tap.
- **Stand mode** auto-detects (gyro still for more than 3 s): the motion gate relaxes, re-arming relies on quad-lost, IoU-jump and hash-change, and 48 MP becomes available as a setting (set before `startRunning()`, with `photoProcessingTimeRange` shown as a progress bar).
- **Feedback vocabulary.** Shutter tick + `.success` haptic = captured (S1). Lock icon = safe (S2). Double buzz + chip = looks like a duplicate. Spoken "already scanned" = text-confirmed duplicate. Spoken "keep this paper" = a keep-original class (titles, wills, notarized documents, undeposited checks, IDs). One amber banner for destination trouble, never a modal. The haptic generator is prepared on entry to TRACKING.
- **Thermal policy** (observe `systemPressureState` and `thermalState`): nominal = 30 fps, segmentation every frame, torch ≤ 0.5 only when exposure says dark; fair = segmentation every second frame, background OCR and PDF work paused while the camera is live, torch ≤ 0.3; serious = 15 to 20 fps preview, torch off, stills at `.speed`, all heavy work deferred; critical = session paused with a message, auto-resume. A drop in `maxAvailableTorchLevel` is treated as the first thermal signal. Sustained throughput over 100 to 200 pages is **unknown** and is measured in Phase 0.
- **Lens smudge** (`DetectLensSmudgeRequest`, iOS 26, A14+): checked on the still, not per frame; a smudge shows a one-time "wipe the lens" cue and never blocks capture (motion blur can false-positive).

## 5. "Already scanned": the two-beat duplicate cue

Measured problem: every image hash (dHash, pHash, wavelet, 256-bit DCT, block-mean) places this-month-versus-last-month statements from the same sender inside the same-page distance band, so a hash-gated skip would discard real pages. Text separates most siblings but not bills where only a date and an amount change; only parsed key fields resolve those.

- **Beat 1, visual, ≤ 50 ms after the still lands.** dHash64 of the rectified quad against the session's last 50 pages, and Vision FeaturePrint distance against the archive's candidate set (flat in-memory arrays backed by SQLite; 200k 256-bit codes brute-force in under 1 ms on a desktop core, **measured**; FeaturePrint latency on iPhone **unknown**). A match shows a soft chip "Looks like page N · 2 min ago" with a thumbnail and a double haptic.
- **Beat 2, text, ≤ 1 s.** `.fast` raw OCR (language correction off, `minimumTextHeight` lowered) on the 2 to 3 MP rectified page → 9-gram Jaccard over the transcript ≥ a calibrated floor AND at least two parsed anchor fields (date, amount, account or reference last-4, "Page N of M") agree exactly AND none disagree → the chip hardens to "Already scanned" with a spoken cue. Otherwise it retracts silently and the page is linked "similar to N".
- **Never auto-confirm** pages under 400 characters, under 50 characters, or flagged blank (ink coverage under 0.5%).
- **Store first, decide later.** The still, its SHA-256, OCR and hashes are persisted before any dedup logic runs. A confirmed duplicate is a `variant_of` relation; the sharper copy becomes canonical. A text-confirmed duplicate skips its own Claude call and inherits the canonical page's record.
- **Calibration before thresholds.** Phase 0 builds the set: 200 pages × 5 recaptures, 50 same-sender sibling pairs, 20 few-field bill pairs, 30 receipts, 20 blank backs; the release gate is a measured false-skip rate of zero.
- **Do not ship MobileCLIP** weights (re-licensed to Apple's research-only AMLR in Feb 2025); use Apple's FeaturePrint or an Apache-2.0 model (DINOv2-S, SigLIP 2) with the model revision stored per vector.

## 6. Page boundaries without taps

Page-stream segmentation in the literature tops out at 0.93 to 0.95 page accuracy and 0.83 to 0.88 whole-stream accuracy on enterprise data, so mistakes are assumed and the design makes them harmless.

- **On-device scorer** (split-biased): "N of M" footer in the same position and incrementing (−5 continue / +5 new), first-page structure such as letterhead and date block (+3), last-page structure on the previous page such as a signature or "total" (+2), form-factor change (+3), letterhead feature-print match (−2) or mismatch (+1), anchor-ID match (−3), pending envelope (+2). The capture gap is only a prior (more than 60 s or the app left the screen: +3; under 4 s with the same quad: duplex-flip prior). Score ≤ −2 appends, ≥ 2 opens a new document, the uncertain band **splits** and marks the new document tentative.
- **Claude as tie-breaker at no extra cost.** Each open document is one prompt-cached Haiku conversation; the per-page structured output includes `continues_open_document`, `boundary_confidence`, `suggested_merge_with` and `expected_page_count`. The device auto-merges at confidence ≥ 0.8. Pairwise decisions only; multi-split prompts over five pages were measurably worse in the research (F1 0.80 vs 0.97).
- **Envelopes** are attachment pages (on-device OCR only unless certified, IRS, court or government cues promote them to a cloud call), linked `envelope_of` the next document; `mailed_date` is stored separately from `document_date`.
- **Blank backs** are a flag on the previous page, excluded from hashing. Duplex is handled by the flip prior plus "continued" structure.
- **Corrections** (optional one-tap merge/split) are telemetry and training labels, never a dependency. Every boundary decision is logged for a later custom pairwise model.
- **Per-page PDFs** go to a hidden `_pages/` folder in each destination immediately; the document PDF is assembled by byte-copying page objects at the confirmed state (closed plus Claude verdict, or 60 s) and sealed after 24 h. A wrong boundary is fixed by update-in-place on stable remote IDs, two-phase removal (archive, verify the survivor's checksum, then trash), and local tombstones with aliases; every operation is idempotent by (document id, destination, revision).

## 7. Understanding with Claude

**Models and prices (list, first-party API).** `claude-haiku-5-5` for every page: $0.10 input / $0.50 output per million tokens for prompts up to 100K tokens, cache reads $0.01, cache writes $0.125 (5-minute) or $0.20 (1-hour). `claude-sonnet-5-5` ($2 / $10, cache reads about $0.10 per the live docs) only for `stop_reason: "refusal"`, `confidence < 0.6`, handwriting, non-Latin script, or packets over 40 pages. Opus has no role. The Fable and Mythos models are excluded: they require 30-day retention and are unavailable under zero data retention.

**Request settings.** `thinking: {"type": "disabled"}` (accepted on Haiku 5.5 at effort high or below), `output_config: {"effort": "low", "format": {"type": "json_schema", "schema": …}}`, `stream: true`, `max_tokens: 1500`, one `cache_control` breakpoint on a ~2,500-token system prompt (taxonomy, rules, two compact examples; the 512-token cache minimum is cleared), `metadata.user_id` = opaque per-install hash. Thinking-off is justified here despite Anthropic's general "use effort as the lever" guidance: the two documented failure modes (a skipped tool call; reasoning-like prose in the output) cannot occur in a tool-less, grammar-constrained request. Phase 0 also runs adaptive thinking at effort low and reads `usage.output_tokens_details.thinking_tokens` from the final `message_delta`; adopt adaptive only if median thinking tokens are under 100 and accuracy improves. No `fallbacks` field: Haiku 5.5 has no server-side refusal fallback; the client retries once on Sonnet 5.5.

**Input.** User turn = `[image, text]`: the masked JPEG (quality 85) at **1,100 px long edge** (850×1100 ≈ 1,240 visual tokens at 28-px patches; Haiku 5.5 is on the high-resolution vision tier, confirmed by a single `count_tokens` call returning 2,145 for a 1075×1520 image) plus the numbered Vision lines with Class A placeholders (~800 tokens) and ~150 tokens of context (date, locale, known senders, open-document summary). Escalate to 1,568 px (≈ 2,464 tokens) only for low Vision confidence or dense pages; never above 2,576 px (the resize cap). A request with more than 20 image blocks (resent earlier turns count) applies a 3,000 px per-image limit; the 1,100 to 1,568 px images here always comply, so long document conversations are safe, and the 40-page chunk below exists only for the price step.

**Call structure (speed and grouping in one).** One call per captured page, appended to the open document's prompt-cached conversation: page n+1 is new input, pages 1..n are cache reads. The output is the document-so-far record, so per-page feedback is as fast as an independent call and the boundary verdict costs no extra round trip. Chunk at about 40 pages (the 100K-token price step on Haiku) and switch to Sonnet for longer packets.

**Schema.** `schemas/document-record.schema.json`. Required-first ordering streams `doc_type` within ~0.1 s of the first token; all properties required and nullable (optional properties count against the strict-schema complexity limit); no "reasoning" field (risks a `reasoning_extraction` refusal); identifiers are last-4 kinds only; `corrections[]` carries line-indexed OCR fixes rather than a full transcript (a full Haiku transcript costs ~$0.0005 but 4 to 7 s of generation, and LLM post-correction of near-clean OCR degrades it in the literature). Freeze schema, system prompt, thinking and effort per app version: any change restarts the 24-hour grammar cache and the prompt cache; warm the grammar at launch. Compare enum values case-insensitively; clamp `confidence` client-side.

**Search-query call.** Same model and settings, `schemas/search-query.schema.json`, ~150 tokens in and ~80 out, fired in parallel with the deterministic on-device parser; results re-render only if the set changes.

**Refusals and retries.** A refusal is HTTP 200 with `stop_reason: "refusal"` and may not match the schema. Retry once on Sonnet 5.5 client-side; if it also refuses, mark `metadata_refused` and keep the page archived with its on-device label. There is no server-side idempotency key, so apply is an upsert by page hash and metadata is committed only from a complete `end_turn` plus a schema-valid parse; a streamed `doc_type` is a UI hint. 429 with `retry-after` sleeps exactly that long; a spend-cap 429 opens a circuit breaker; 5xx, 529 and timeouts use jittered exponential backoff (1 s × 2ⁿ, cap 60 s, 8 attempts) and then park the page for a nightly inline sweep; one doubled-`max_tokens` retry on truncation. SDK timeout about 45 s, retries 0 to 1.

**Feature scope.** Inline `/v1/messages` only. **No Batches, no Files API** (both are marked not ZDR-eligible; ZDR does not block them, so a CI rule must). Backfill and re-indexing are inline text-only Haiku calls at about $0.0003 to $0.0006 per page.

**Rate limits and capacity.** Input-tokens-per-minute binds before requests-per-minute (about 913 pages per minute on the Start tier at ~2,200 uncached tokens per page, roughly 46 simultaneous scanners at 20 pages per minute). Request the Build tier at launch and Scale before ~5,000 users; keep uncached tokens per page under ~2,500; `inference_geo` stays global unless a contract requires `us` (1.1× price).

**Cost (list prices, computed).** Single-page document, 1,100 px image + OCR text, 400 output tokens: **$0.00044**. Multi-page via the cached conversation: about $0.003 per 5-page packet. 10% Sonnet escalation adds about $0.0009 per page. Planning figure: **$0.002 per document blended**, so a 150-page-per-month user costs under $0.30 per month in AI. Phase 0 measures real token counts and thinking tokens on your pages.

**Privacy posture per tier.** v1 (BYO key): calls go device-direct to `api.anthropic.com` under your own Anthropic agreement (standard 30-day retention, no training on API data); the key lives in Keychain; API keys only, never a Claude.ai login (consumer credentials may not be shared or proxied). Managed tier (v2+): one Anthropic org with **zero data retention** requested for Haiku/Sonnet 5.5, a data processing agreement, and a CI lint that forbids Batches, Files, code execution and Covered Models.

## 8. Durability: what "captured" promises

| State | Meaning | Signal | Timing |
|---|---|---|---|
| S0 framed | in memory | none | — |
| **S1 captured** | page bytes F_FULLFSYNC'd and atomically renamed; ledger row committed (WAL, `synchronous=FULL`, `fullfsync=ON`) | haptic, solid card | ≤ 150 ms p95 after the still lands (F_FULLFSYNC cost on iPhone NAND **unknown**; plan 5 to 50 ms) |
| **S2 safe** | ≥ 1 destination row `verified` (server hash match, or iCloud `isUploaded && uploadingError == nil` plus size and identity-token check) | lock icon; counter "17 safe · 3 uploading" | seconds on Wi-Fi, minutes on LTE; never promised sub-second |
| S3 replicated | every enabled destination verified; blob demoted to cache, excluded from backup, promoted to Class A | nothing on the capture screen | background |

S1 survives app crash, force-quit, reboot and 48 h of airplane mode. It does not survive app deletion or device loss. Product copy: *"Captured" means it is safely on this phone; the lock means it is also in your iCloud Drive, Google Drive or NAS; throw the paper away when the lock shows.* A "shred-safe" toggle that withholds the haptic until S2 exists for users who want it, never as the default. If pages sit at S1-only for 30 minutes, a local notification and a persistent amber "on this phone only · N pages" state make sure nobody discards paper during a silent upload stall.

**First off-device hop in v1 (no backend): the iCloud Drive ubiquity container, `Documents/<AppName>/YYYY/`**, written through `NSFileCoordinator`. The OS daemon moves the bytes independently of the app process, the files survive app deletion, they are visible in Files and user-owned, and Advanced Data Protection users get end-to-end encryption for free. CloudKit `CKAsset` is **not** used for page bytes (quota spent twice, invisible in Files, bound to iCloud Keychain); CloudKit is reserved for a small ledger mirror for multi-device later. Any destination that verifies first satisfies S2, so a full 5 GB iCloud account falls through to Drive or the NAS; with nothing reachable, capture continues under the amber state. The service-phase relay (R2, end-to-end encrypted with a user-held recovery key, SHA-256 checked, 30-day TTL, deleted once user destinations verify) is **opt-in** for users whose iCloud is full or who want the lock within seconds on LTE; it is never the definition of "captured".

**What is uploaded first**: the per-page PDF/A (300 to 900 KB), not the raw HEIC. At 30 pages per minute that is about 1.2 Mbit/s. The HEIC original stays local until S3 plus 7 days (a "keep negatives" setting keeps it forever) and mirrors on Wi-Fi only.

**Data Protection classes** (resolving the conflict between the privacy and Apple-platform reports): ops database, outbox staging blobs and ubiquity files are **Class C** (`completeUntilFirstUserAuthentication`) because daemons and background tasks must read them after lock and GRDB throws on protected databases; vault blobs after S3 and the content/FTS database are **Class A** (`complete`); enrichment results produced while locked are **Class B** per-page files merged at `protectedDataDidBecomeAvailable`. Keychain: `afterFirstUnlockThisDeviceOnly` for OAuth tokens and anything the uploader needs; `whenPasscodeSetThisDeviceOnly` only for the content-database key. Pending blobs and the ledger stay inside iCloud Backup; `isExcludedFromBackup` is applied only after S3 and re-applied on every rewrite.

**Outbox.** Per (page, destination): `pending → staged → uploading(session, bytes) → uploaded(remote id) → verified → named → audited | failed(retry at) | needs attention`. Uploads are enqueued in the foreground (so iOS does not downgrade them to discretionary), batched, and reconciled against `getAllTasks()` on every launch with a 30-day resource timeout. Idempotent by content hash: Google Drive pre-generated IDs (409 on replay), Synology `_inbox/` PUT then `MOVE` with `Overwrite: F`, and deterministic PDF emission (`/ID[0]` and `xmpMM:DocumentID` from the capture-time ULID, `CreationDate` = capture time, replayed JPEG and OCR JSON) so a replay is byte-identical. A nightly `BGProcessingTask` audit (Drive `changes.list`, Synology `PROPFIND`, iCloud query reconciliation, 1-in-20 read-back) re-uploads missing files from the local blob or a sibling destination, adopts user renames, flags overwrites and never propagates deletions. Reinstall rebuilds the ledger from any one destination's `_vault/index.jsonl` plus the per-document sidecars. The 24-case device test matrix in `research/gap-4-captured-state-machine-and-fir.md` (lock within 5 s, force-quit reconciliation, iCloud quota full, 48 h airplane, delete and reinstall, backup restore) is a release gate.

## 9. Output: the archival PDF

- **Resolution.** "Print-ready" has a number: FADGI 2023 Modern Textual Records, ≥ 294 ppi. 12 MP meets it on Letter only when the page fills ≥ 82% of the frame's long axis; the framing gate at 0.78 gives 286+ ppi on Letter and 269+ on A4. Marketing copy: "300 ppi when framed, never below 200 ppi" until a slanted-edge resolution test on iPhone 13/15/17 measures true sampling efficiency. Legal-size paper never reaches 294 ppi at 12 MP; decide whether it matters (see `06-decisions-and-needs.md`).
- **Master image.** Perspective-corrected, Lanczos-downsampled to 300 ppi (never upsampled), upright pixels with `/Rotate 0` (orientation from a phone-top-is-page-top prior, quad aspect, and a two-way `.fast` OCR confidence vote after the haptic), document-enhanced with background division, white-point corrected, unsharp-masked, 8-bit grey or colour chosen by saturation histogram, sRGB JPEG quality ≈ 50 (0.3 to 0.9 MB). Bilevel JBIG2 (lossless generic only) and MRC are optional "compact" derivatives, never the master. Dewarping creased or curled pages (UVDoc: MIT, 8M parameters, runtime unpublished) is a v1.5 Core ML spike; keeping HEIC originals makes re-rendering possible later.
- **Page size (MediaBox).** Inferred from quad aspect within 3% of a standard size (Letter 1.294, A4 1.414, Legal 1.647, #10 envelope 2.30), tie-broken by locale prior, Vision text-line height or receipt column count, LiDAR depth plus intrinsics on Pro models, and Claude's document class; `pageSizeSource` and confidence are recorded in XMP so the size can be corrected without touching pixels.
- **Writer.** In-house PDF/A-2u: one JPEG XObject per page (DCT pass-through), invisible glyphless text layer from Vision `.accurate` word boxes (render mode 3, horizontal scaling fitted per word, explicit spaces, identity ToUnicode), sRGB OutputIntent, Info dictionary plus XMP with a declared extension schema (id, sha256, sender, doc type, dates, amounts, OCR engine, text-layer version, page-size source), deterministic trailer `/ID`. veraPDF gates every CI build. Multi-page documents are assembled by byte-copying page objects so no re-encode ever degrades the archive.
- **Immutable bytes, mutable label.** The PDF is built once at S1 and uploaded under a provisional name `YYYY-MM-DD_unsorted_unsorted_<id8>.pdf`; when Claude lands it becomes `YYYY-MM-DD_<sender>_<doctype>_<id8>.pdf` by a metadata-only rename (Drive `files.update`, WebDAV `MOVE`, coordinated move), late-bound at task creation when the record arrives first. The PDF is rewritten and re-verified only when Claude's corrections are material (a validated anchor changed or more than 2% of characters).
- **Portability.** Every destination gets the PDF text layer, a `<name>.json` sidecar (masked text, fields, tags, schema and prompt versions) and a `_vault/index.jsonl`, so Google Drive's own full-text search, Synology Universal Search and macOS Spotlight work on the files without this app, and a reinstall can rebuild from any one destination.
- **Export.** `UIPrintInteractionController`, the share sheet, ZIP bundles with `index.csv` and `index.json` plus a bookmarked combined PDF for tax-year and expense packs, mail compose for packs under ~25 MB.

## 10. Storage destinations

| Destination | Transport | Commit | Verify | Rename | Notes |
|---|---|---|---|---|---|
| iCloud Drive | ubiquity container `Documents/<AppName>/`, coordinated write off the main thread | OS daemon | one app-lifetime `NSMetadataQuery`: `IsUploaded && UploadingError == nil` + size + archived `ubiquityIdentityToken` hash; frozen on `NSUbiquityIdentityDidChange` | coordinated move | default first hop; falls through on quota |
| Google Drive | REST v3, **`drive.file` only** (non-sensitive scope, no CASA assessment), `generateIds` pool, persisted resumable session, single file-backed PUT from a background task | 200/201 or 409 → `files.get` | `sha256Checksum` + `size` (the strongest check of the three) | `PATCH name/addParents/removeParents` | 401 → refresh token, probe with `Content-Range: bytes */N`, new task on the same session URI; `appProperties {id, hash}` (124-byte cap); `indexableText` = summary + tags + doc type + sender |
| Synology NAS | **WebDAV over HTTPS (port 5006) with a publicly trusted certificate** (DSM Let's Encrypt on `synology.me`, or Tailscale with `tailscale cert`, or a user-installed CA profile); File Station API optional (`SYNO.API.Auth` v6 with `otp_code` + device token once) | `PUT /_inbox/<id>.pdf` | `PROPFIND Depth: 0` size, `SYNO.FileStation.MD5` job when linked (official guide updated for DSM 7.0), sampled read-back otherwise | `MOVE Overwrite: F` into `/YYYY/` | No SMB (foreground-only, cannot run on a background session), no QuickConnect (carries only Synology's own apps), **no fingerprint-trust prompt** (App Transport Security forbids loosening trust at runtime); static exception domains only for private CIDR ranges |
| Later | Dropbox (`content_hash`), OneDrive (Graph upload session), S3-compatible (`x-amz-checksum-sha256`), Paperless-ngx consume folder or API | | | | same outbox, same naming |

Quorum for S2 is one verified destination; when several are enabled, Drive or Synology-with-MD5 are preferred over iCloud because they carry a server-side digest.

## 11. Search

On-device only in v1 and v2; that is what makes search instant (target under 50 ms) and offline.

- **Lexical.** External-content FTS5 over `title (weight 10) / tags (5) / summary (3) / sender (3) / masked OCR text (1)` with `porter unicode61`, plus a trigram FTS5 shadow over masked text and identifier variants for OCR-mangled names and partial last-4s.
- **Structured.** `documents` with denormalized facets (doc type, sender key, document date, tax year, amounts in cents, people, keep-original), per-page rows, materialized facet counts. "All my tax documents for 2024" is a SQL filter; "how much did I pay Con Edison in 2025" is a SQL SUM over extracted amount fields, never a model adding numbers from 40 PDFs.
- **Semantic.** bge-small 384-d int8 vectors in sqlite-vec, embedding each ~300-token chunk of masked text with the document's title, sender and date prepended (free contextual retrieval); `embedding_model` stored per vector.
- **Fusion.** Reciprocal rank fusion (k = 60) over BM25 and vector lists; filters are hard SQL constraints; facet chips on result sets for zero-typing refinement.
- **Query understanding.** A deterministic parser (NSDataDetector dates, a relative-period grammar, doc-type synonyms, a known-sender dictionary, tax-year regex, amounts) answers in under 10 ms; the Haiku filter-JSON call refines asynchronously; Apple Foundation Models is an offline refiner on A17 Pro+ only.
- **Questions.** Free-form questions go to Claude with `citations` over the top-20 chunks.
- **System surfaces.** Every document is donated to a named Core Spotlight index with `title` and `textContent` = summary + tags + sender (never raw OCR, never Class A), `IndexedEntity` for Siri and Shortcuts, `CSUserQuery.prepare()` before the search screen shows.
- **Evaluation.** 150 labelled queries over the founder's own mail, nDCG@10 and Recall@20 via `ranx`, in CI against the app's own SQLite file. Most search failures will be extraction failures, so the harness grades extraction first.
- **v2 service** (only when a cloud index is needed for web access or sharing): Postgres with `tenant_id` row-level security, per-page `tsvector` plus pgvector over masked text, RRF in SQL; Turbopuffer namespaces if vectors outgrow RAM. User PDFs are never persisted in the Anthropic Files API.

## 12. Sensitive data: one policy

- **Class A secrets** (SSN/ITIN, card numbers, bank account and routing numbers including the MICR band, driver licence and passport numbers, medical record and member IDs) exist in full only inside the archival PDF in the user's own storage. Everywhere else carries `last4` placeholders: the Claude request (masked JPEG and `[SSN ••••1234]` lines), the structured output, sidecars, FTS (indexes masked text), Spotlight, Drive `indexableText`, embeddings, filenames, logs.
- **Class B reference IDs** (invoice, claim, policy, case and check numbers, employer EINs, amounts, dates) flow in plaintext because they are what people search for.
- **Class C** text is everything else.
- **One Redactor pass** over Vision word boxes produces the only text any downstream stage may read, except the PDF writer. Masking recall on OCR-mangled, split or handwritten numbers is **unknown** and is measured on real mail before it is advertised; the rules include O/0 and l/1 normalization, a conservative nine-digit rule near SSN/TIN/EIN context, and MICR-band geometry.
- **Sensitivity gate** (tax, medical, prescription, ID, insurance claim, court) = a regex rule hit (OMB 1545-, 1099/W-2/1098/1095, EOB/CPT/NPI/Rx, MRZ, pdf417, SSN pattern) OR classifier posterior > 0.3, computed before the Claude call and never by Foundation Models (its guardrails fire on exactly these pages). Identity documents go text-only to Claude, always. Other sensitive classes text-only is a user toggle, not the default, because tax forms are exactly where layout cues help.
- **CI canary.** A test corpus with synthetic SSNs, card numbers and routing numbers asserts none of them appears in any outbound request, index row, sidecar, filename or log.
- **App Store.** Form an LLC and enrol as an Apple Organization before submission (guideline 5.1.1(ix); transferring an individual app later changes the Team ID and forces a Keychain re-login). One-time revocable consent naming Anthropic as a third-party AI provider (5.1.2(i)) with a fully functional on-device mode when consent is withdrawn, a superset privacy nutrition label (User Content, Financial, Health, Sensitive, Name, Address: linked to you, app functionality, no tracking), `ITSAppUsesNonExemptEncryption = false` by staying on OS Data Protection, CryptoKit and TLS, in-app account deletion from the first build that has accounts, a separate consent toggle for medical pages (Washington My Health My Data Act), a per-document "keep the original" label, and a Shred action that is honest about provider trash folders and NAS snapshots.
- **Law on discarding originals.** IRS Rev. Proc. 97-22 accepts electronic records once the system is tested and documented; the "how your archive works" page doubles as that system description. Vital records, wills, titles, notarized and bearer instruments, undeposited checks and IDs announce "keep this paper".

## 13. Digital inputs (v3+)

The non-camera half of "everything I get", deferred until the capture product is shipping:

- **Email.** A per-user unguessable forwarding address on a Cloudflare-hosted domain, processed by an Email Worker that persists the raw message and attachments to R2 before anything else (the `setReject` call is a permanent bounce, not a retry, so persist-then-process is the durability mechanism; Postmark inbound with documented retries is the alternative). Gmail users get a walkthrough for a user-side "forward it" filter; iCloud Mail is polled over IMAP with unread-only rules. **Gmail OAuth is deferred**: every Gmail read scope is Restricted (6-week review, annual CASA assessment, 100-user cap while unverified, and a Limited Use clause that forbids training custom models on Gmail-sourced data).
- **On the phone.** A Share and Action extension that hands files off through the App Group and a background URLSession; an iCloud Drive inbox folder watched with `NSMetadataQuery`; optional user-picked folders rescanned on launch; camera-roll triage via document segmentation and the iOS 18 image-aesthetics "utility" flag; Synology watched folders for a desktop sheet-fed scanner.
- **Born-digital PDFs** are archived byte-for-byte with text extracted per page by PDFKit (OCR only for scanned pages, form fields via widget annotations).
- **Action layer.** Due dates to Reminders (full access) and Calendar (write-only) through EventKit with an app-side ledger of created items; a single passive daily digest; tax-year and expense packs; expiry alerts for passports and registrations. All email and PDF text is treated as untrusted input.

## 14. Backend evolution

| Version | Backend | Why |
|---|---|---|
| v1 personal / TestFlight | none; BYO Anthropic key, device-direct | zero servers, "we collect nothing" is literally true |
| v2 App Store | one Cloudflare Worker: key custody for the managed tier, App Attest, per-user quotas, usage metering; StoreKit 2 entitlements | the proxy contract (opaque install id, entitlement check, frozen prompt and schema version, idempotent apply by page hash) is written as a document in Phase 1 so BYO and managed modes share one client path |
| v3 service | Supabase accounts with native Sign in with Apple and row-level security, opt-in encrypted relay bucket (R2), CloudKit ledger mirror for multi-device, email ingest, share links and packs served from R2, B2B seats | revenue-gated |
| v4 | Android client (Kotlin, CameraX, ML Kit Text v2, OpenCV or a licensed detector; the ML Kit Document Scanner is a Play-services Intent flow with no camera control) against the same proxy; distilled models | revenue-gated |

Rough hosting cost: about $30/month fixed; AI cost dominates at every scale (about $55/month at 1k users, $550 at 10k, $5.5k at 100k at 150 pages per user per month).

## 15. Where this plan deliberately disagrees with the raw research reports

1. The capture and dedup reports let a hash suppress re-capture and auto-skip duplicates; the plan lets a hash only accelerate re-arming and never skips.
2. The Apple-platform report declares "captured" only after local write and CloudKit upload, with `CKAsset` as the first hop; that fails offline, adds seconds, spends iCloud quota twice and ties durability to iCloud Keychain. Haptic at S1; iCloud Drive container is the hop.
3. The storage report wants a service escrow bucket as the v1 first commit; v1 has no backend. The relay is an opt-in later.
4. The output report wants 24 MP for every capture and the Apple report wants 48 MP with zero shutter lag; 24 MP is deferred-only and 48 MP forfeits ZSL and takes seconds. 12 MP plus the framing gate handheld, 48 MP in stand mode.
5. The architecture and Apple reports use Foundation Models as the instant label; it is unavailable on the floor device, text-only on iOS 26 (image input is iOS 27), takes 1 to 3 s on a full transcript, and its guardrails fire on the sensitive classes. Rules plus sender memory plus Create ML instead.
6. The OCR report adds Mistral OCR 4 or self-hosted PaddleOCR as a fallback; not in v1/v2 (a third-party flow of full page images with no measured gain over Vision plus Claude line corrections). Revisit if Vision's character error rate on your mail exceeds ~5%.
7. The output report turns language correction on for everything; Apple documents that correction corrupts codes. Raw `.fast` for anchors, corrected `.accurate` for the layer.
8. The search, Claude and business reports use Voyage embeddings; Voyage trains on inputs by default and the free tier is per account, not per end user. On-device bge-small.
9. The mail report purges junk after 30 days and relies on one-tap merge/split; junk is archived forever and hidden; taps are optional telemetry; the dedup report's five-page multi-split boundary pass is replaced by pairwise decisions inside the per-page call.
10. The Claude report makes the proxy the primary path with BYO as a power-user option; reversed for v1 and the free tier.
11. The storage report proposes a NAS certificate-fingerprint prompt and the Apple report proposes SMB over background URLSession; neither works under App Transport Security or background sessions.
12. The business report computes image tokens with the legacy pixels/750 formula; at 28-px patches a 1,568 px page is about 2,464 tokens, and the planning arm is 1,100 px at ~1,240 tokens.
13. The competitors report frames the gap as raw hands-free capture; Genius Scan and Adobe Scan already auto-capture in batch mode. The gap is sub-second feedback plus dedup, grouping, understanding, verified multi-destination delivery and search; the capture loop is custom, but the moat is everything after S1.
