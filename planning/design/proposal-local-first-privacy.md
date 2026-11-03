# Proposal: local-first, privacy-first architecture for the zero-interaction paper digitizer

Angle: LOCAL-FIRST-PRIVACY. Date: 2026-11-03. Evidence base: the 24 research reports in `../research/`, with the fact-check corrections applied (Vision timings re-measured by text_sight 1.0.0; Foundation Models image input is iOS 27-only; Synology's official File Station guide is DSM 7.0-updated; Claude first-party request cap is 128 MB; `usage.output_tokens_details.thinking_tokens` exists; UVDoc is 8M parameters; FTC HBNR penalty floor is $53,088; Boros et al. used eight benchmarks).

## Thesis

The phone is the only machine that ever holds a complete, unmasked copy of the user's paper. Everything the user needs in the first second (page found, captured, "looks like page 3", provisional label) is computed on the Neural Engine. The user's own storage is the system of record; there is no backend in v1 or v2 and no service-owned bucket. Claude Haiku 5.5 does the one thing it clearly wins at: turning a masked page into fields, tags, a title and a summary. Every rule below keeps the product working with the network off, Anthropic down, or the developer gone.

## 1. Architecture

```
iPhone (Swift 6.1, SwiftUI, iOS 26.0+, A15 acceptance floor)
┌────────────────────────────────────────────────────────────────────────────┐
│ CAPTURE LOOP (all on-device, never waits on network)                       │
│  AVCaptureSession .photo preset, 12 MP main camera                         │
│   ├─ VideoDataOutput 1920x1440 420v → AsyncStream(bufferingNewest:1)       │
│   │    CaptureActor: DetectDocumentSegmentation ▸ IoU/area stability       │
│   │      ▸ Laplacian sharpness ▸ gyro stillness ▸ glare/clip ▸ framing gate │
│   │      ▸ dHash64 of rectified 32x32 (hint only) ▸ quad-lifecycle trigger │
│   └─ PhotoOutput 12 MP .balanced, ZSL+responsive on, deferred off, HEIC    │
│        ▸ F_FULLFSYNC blob + WAL ledger row  ══▶ S1 "captured" (haptic)     │
├────────────────────────────────────────────────────────────────────────────┤
│ ON-DEVICE PIPELINE (actors, disk-backed queues, Class C staging)           │
│  RectifyActor: re-detect quad on still ▸ CIPerspectiveCorrection ▸ Lanczos │
│    300 ppi ▸ orientation vote ▸ CIDocumentEnhancer+bg division ▸ JPEG      │
│  OCRActor: Vision .fast RAW (anchors, dedup, label) → .accurate+correction │
│    / RecognizeDocumentsRequest (text layer, FTS, paragraphs, detectedData) │
│  Redactor: one pass over word boxes → maskedImage, maskedText, last4 slots │
│  DedupActor: SimHash128 LSH + 9-gram Jaccard + parsed anchors → variant-of │
│  GrouperActor: page→document scorer, tentative split, N-of-M, headers      │
│  LabelActor: rules ▸ sender memory (feature print kNN) ▸ Create ML text    │
│  PDFActor: in-house PDF/A-2u writer, glyphless text layer, deterministic ID│
│  IndexActor: SQLite FTS5 (porter+trigram), sqlite-vec 384-d, Core Spotlight│
├────────────────────────────────────────────────────────────────────────────┤
│ CLOUD PIPELINE (surgical, async, masked input only)                        │
│  EnrichActor ──► api.anthropic.com directly (BYO key, Keychain) or, in v3, │
│    the developer's ZDR proxy. Haiku 5.5 thinking off / effort low,         │
│    structured output, streamed, cached taxonomy prompt, per-document       │
│    incremental cached conversation. Sonnet 5.5 only on refusal/needs_review│
├────────────────────────────────────────────────────────────────────────────┤
│ STORAGE / SYNC ENGINE (outbox per page × destination, background URLSession)│
│  iCloud Drive ubiquity Documents/ (default first hop) │ Google Drive v3    │
│  drive.file + generateIds + sha256Checksum │ Synology WebDAV HTTPS PUT →   │
│  PROPFIND → MOVE, optional File Station MD5 │ CloudKit: encrypted ledger   │
│  mirror only (v2 multi-device) │ nightly BGProcessingTask audit            │
└────────────────────────────────────────────────────────────────────────────┘
Backend: none in v1/v2. v3 (service): Cloudflare Worker key-proxy + ZDR org,
opt-in E2EE relay (R2, 30-day TTL), opt-in email-forwarding ingest. Never a NAS writer.
```

Four rules the diagram encodes: no perceptual hash ever suppresses a capture (the trigger is quad lifecycle); "captured" is S1 local-durable and the lock icon is S2, one verified off-device copy; the first off-device copy is the user's iCloud Drive folder, never CloudKit assets or a service bucket; Class A secrets exist outside the device only inside the archival PDF in the user's own storage.

## 2. Tech stack

| Layer | Choice | Min OS / version | Why (evidence) |
|---|---|---|---|
| Language/UI | Swift 6.1 strict concurrency, SwiftUI, actors + `AsyncStream` back-pressure | Xcode 26/27 | zero-copy `CVPixelBuffer`→Vision path |
| Deployment target | **iOS 26.0**, `#available(iOS 27)` for FM `Attachment`, `OCRTool`, Core AI | same hardware as iOS 27 (A13+); ~80% of iPhones today | unlocks `RecognizeDocumentsRequest`, `DetectLensSmudgeRequest`, `BGContinuedProcessingTask` |
| Camera | AVFoundation `.photo` preset, 12 MP `.balanced`, ZSL + responsive capture on, deferred delivery off, second low-res `AVCaptureVideoDataOutput` | iOS 17 APIs | 24 MP is deferred-only and Photos-bound; 48 MP "several seconds" |
| Document detection | `DetectDocumentSegmentationRequest` | iOS 18 | real-time on Neural Engine (WWDC21) |
| OCR | `RecognizeTextRequest` `.fast` raw + `.accurate` corrected; `RecognizeDocumentsRequest` for paragraphs/tables/detectedData; `minimumTextHeightFraction` lowered from 0.03125 | iOS 18 / 26 | 101 / 404 / 736 ms p50 on iPhone 16 (text_sight 1.0.0) |
| Dedup | dHash64 (hint), PDQ-style 256-bit DCT + quality gate, `GenerateImageFeaturePrintRequest` rev 2, SimHash128 / 9-gram Jaccard, parsed anchors | iOS 18 | gap-2; MobileCLIP rejected (AMLR research-only licence) |
| Instant label | regex rules, sender memory (header feature print + sender kNN), Create ML `MLTextClassifier` | iOS 17 runtime | no Apple-Intelligence gate, no guardrails |
| Local DB | GRDB 7.12 + bundled SQLite with FTS5 (porter, trigram) + sqlite-vec 0.1.9 (USearch fallback) | iOS 13 | confirm FTS5 in system SQLite on device |
| Embeddings | on-device `bge-small-en-v1.5` 384-d via swift-embeddings; same model for documents and queries | iOS 17 | one vector space; no third-party text flow |
| PDF | in-house `ArchivePDFWriter` (PDF/A-2u, glyphless font, XMP + `pap:` schema); veraPDF in CI; `kCGPDFContextCreatePDFA` spiked as fallback | iOS 14 for the CG flag | output.md, gap-9 |
| Cloud AI | `claude-haiku-5-5` (thinking disabled, effort low, json_schema output, streamed); `claude-sonnet-5-5` for escalation; `anthropic-version` pinned | API 2026-10-21 | gap-6 |
| Destinations | iCloud ubiquity container + `NSMetadataQuery`; Google Drive v3 `drive.file`; WebDAV + optional `SYNO.FileStation.*` v2 | — | storage.md, gap-5 |
| Background | background `URLSession` (foreground-enqueued), `BGProcessingTask` nightly audit, `BGContinuedProcessingTask` drain | iOS 26 | gap-4 |
| Telemetry | `OSSignposter` per stage, on-device histograms only; MetricKit `MetricManager` | — | no document bytes leave for telemetry |

Rejected on principle: Scanbot/Genius Scan/Dynamsoft (quote-priced, bundle-ID lock, no latency numbers, and they do not solve grouping, dedup or durability), Voyage (trains by default), Mistral/Azure/Textract OCR (a second third-party flow of full text), CloudKit `CKAsset` for page bytes.

## 3. Latency budget

Targets per page after the page settles in frame; the week-one harness replaces every estimate.

| Stage | Feed | Target A17+ / A15 | Evidence |
|---|---|---|---|
| Quad + overlay | 1920x1440 preview, every frame | <30 ms / <50 ms per frame | Apple: real-time on NE (vendor); unmeasured |
| Stability decision | 6 frames IoU ≥0.95, area Δ ≤5%, gyro still | 200 ms | 33 ms/frame |
| Still delivered + S1 write | 12 MP HEIC, F_FULLFSYNC + atomic rename + fsync'd ledger commit | <300 ms / <500 ms p95 | ZSL ~2 photos/s baseline (WWDC23); F_FULLFSYNC cost unknown |
| Visual dedup hint | dHash64 vs last 50 captures + feature print vs candidates | +5-30 ms / +10-60 ms | Hamming scan 0.39 ms per 200k codes (measured); feature-print latency unknown |
| Rectify + enhance + JPEG | 12 MP still, GPU | 100-250 ms (background) | estimate |
| `.fast` raw OCR (anchors, label, orientation) | rectified 2-3 MP, correction off | 150-300 ms / 300-600 ms | 101 ms p50 on A18 (text_sight); A15 ≈2.2x by NE TOPS |
| Text-tier dedup confirm + provisional label | SimHash/Jaccard/anchors + rules/kNN/classifier | +<10 ms | computed |
| `.accurate` + correction / documents request | full-res rectified page | 1-3 s / 2-6 s (never on feedback path) | 736 ms one-shot at 1080p-class input on A18; full-res unmeasured |
| Provisional PDF/A page + sidecar | Vision boxes | <50 ms | byte copy of JPEG + small text object |
| Claude Haiku record | 1,100 px masked JPEG + masked OCR lines | TTFT 0.5-1.5 s, full record 2.5-4 s on Wi-Fi | decode 165-176 t/s measured; thinking-off TTFT unmeasured |
| S2 lock | 300 KB PDF/A page to first destination | p50 <5 s Wi-Fi; minutes on 1 Mbit/s LTE at 30 ppm | gap-4 computed |

User-visible contract: haptic at S1 (<0.5 s), dedup hint in the same frame, text-confirmed dedup and provisional label within ~1 s on A15, Claude label within ~4 s, lock icon when a remote copy verifies. Sustained 20 pages/min handheld is the acceptance test; on A15 the accurate-OCR queue will lag and is shown as a backlog.

## 4. Zero-interaction capture state machine

```
SEARCHING ──quad found, area ≥25%, no corner on edge──▶ TRACKING
TRACKING ──6 stable frames ∧ sharp(≥90% of page max) ∧ clean(clip<2%) ∧ framed──▶ FIRING
TRACKING ──quad lost──▶ SEARCHING
FIRING ──capturePhoto (readiness .ready)──▶ WRITING ──blob+ledger durable──▶ CAPTURED(S1)
CAPTURED ──(hint) dHash/feature-print match──▶ HOLDING_WITH_HINT ("Looks like page N")
CAPTURED ──no match──▶ HOLDING
HOLDING* ──quad lost ≥ 150 ms──▶ SEARCHING          (next sheet)
HOLDING* ──quad geometry jumps (IoU<0.6) without loss──▶ TRACKING (page swapped in place)
any ──thermal critical / system pressure shutdown──▶ PAUSED (auto-resume at serious/fair)
```

Rules that resolve the dedup conflict:
- The trigger is a lifecycle event (quad acquired or replaced), never a hash comparison. A page hovered over continuously fires once because the quad never leaves; the same page lifted and re-placed fires again, is written again, and later becomes a `variant_of` in the catalog.
- The instant cue is a hint: a soft chip with the matched thumbnail, "Looks like page 3 (2 min ago)", a double-buzz haptic, optional spoken cue, fired from the visual tier (dHash + feature print). Within ~1 s the text tier (9-gram Jaccard on raw `.fast` OCR above a calibrated floor, starting at 0.6, AND two parsed anchor fields equal with none disagreeing) hardens it to "Already scanned, kept the sharper copy" or silently retracts it. Pages under 400 characters and blank backs never auto-merge.
- The hash and anchor index spans the whole archive (12.8 MB at 200k pages, brute-force scan <1 ms); the visual hint compares against the session's last 50 captures plus archive candidates.
- Framing gate: for full-page quads, fire only when the quad's long side ≥0.78 of the frame's long axis (≥286 ppi on Letter at 12 MP); for receipts and cards, when implied ppi ≥300. The overlay ring and a "closer" cue teach without a tap.
- Capture settings: `.near` focus restriction, exposure bias +1 EV tuned by the clip check, `activeMaxExposureDuration` 1/120 s, white balance locked per batch, torch off by default.

Page-boundary scoring runs in `GrouperActor` after S1 and never gates the haptic: N-of-M footer with position and increment check (±5), form-factor change (+3), first-page structure (date, addressee, salutation; +3), last-page structure on the previous page (+2), header feature-print match (−2/+1), anchor-token match (−3), pending envelope (+2); the capture gap is a prior only. ≤−2 appends, ≥2 closes and opens, the uncertain band splits tentatively and lets Claude propose a merge (section 5). Envelopes become `envelope_of` the next document. Merge/split taps exist on the timeline but nothing depends on them; they are labels for the decision log.

Feedback vocabulary: click + `.success` haptic at S1; double-buzz + chip for a dedup hint; a distinct tone plus spoken "keep this paper" when `keep_original` is set; silence otherwise. Lock icon, counts and backlog live on a status strip, never in modals.

Thermal policy: fair = segmentation every 2nd frame, accurate OCR paused while the camera is live, torch ≤0.3; serious = 15 fps, torch off, stills at `.speed`, post-S1 work deferred; critical = PAUSED with a visible reason. Nothing is lost because every page is already at S1.

## 5. Claude usage design

Models and settings (frozen per app version, one combination so the prompt cache and the 24 h grammar cache stay warm):
- Hot path: `claude-haiku-5-5`, `thinking: {"type":"disabled"}`, `output_config: {effort: "low", format: {type: "json_schema"}}`, `max_tokens: 1500`, `stream: true`, `metadata.user_id` = opaque per-install hash. Thinking off is correct here despite Anthropic's general "use effort instead" guidance: the two documented failure modes (skipped tool calls with JSON output; reasoning-like prose) cannot occur in a tool-less, grammar-constrained call. Adaptive-low stays in the harness, scored from `usage.output_tokens_details.thinking_tokens` on the final `message_delta`.
- Escalation: `claude-sonnet-5-5`, `thinking: {"type":"between_tools"}`, `effort: low`, identical schema, on `stop_reason: "refusal"` (Haiku has no server-side fallback), `confidence < 0.6`, `needs_review`, handwriting or non-Latin script. Cache reads are $0.10/MTok. Opus 5.5 is not in the pipeline.
- Forbidden in app and service code, enforced by a CI lint: Message Batches, Files API, code execution, MCP connector, Covered Models (Fable/Mythos 5.x); all are outside ZDR/HIPAA eligibility and ZDR does not block them. Backfill and re-index are inline text-only Haiku calls (≈$0.0003/page; a 20,000-page archive ≈$6-12).

Input per call: the masked analysis JPEG at 1,100 px long edge, q85 (≈1,240 visual tokens; the high-resolution tier is confirmed with one `count_tokens` call on a 1075x1520 image expecting 2,145) as the first content block, then the numbered masked Vision lines (≈800 tokens) and `detectedData` hits, then "page k of open document D". Escalate to 1,568 px (≈2,464 tokens) only for dense or low-confidence pages. Identity documents are never sent; sensitive-class pages (tax, medical, prescription) go text-only.

Prompt layout: `system = [{taxonomy (26 classes, identifiers renamed to *_last4, micr_routing removed) + extraction rules + 3 compact examples, 2,500 tokens, cache_control ephemeral}]`; per-request content only in the user turn.

Unit of inference: the document, called once per page as an incremental prompt-cached conversation (gap-1 structure C): call n carries pages 1..n with 1..n−1 as cache hits, so per-page feedback is as fast as independent calls while the document record stays current and the boundary verdict is free. Chunk or switch to Sonnet above ~40 pages to stay under the 100K-token Haiku price step.

Schema (all properties required, nullable; required-first ordering so `doc_type` streams first; no "reasoning" field):

```
doc_type (enum 26) · doc_subtype · continues_open_document (bool) · boundary_confidence
· suggested_merge_with (string|null) · expected_page_count (int|null) · keep_original (bool)
· language · sender{name,address,email,phone} · recipient{...} · document_date · due_date
· period_start · period_end · tax_year · amounts[{label enum,value,currency}]
· identifiers[{kind enum(tax_id_last4|account_last4|member_id_last4|invoice_number|claim_number
  |policy_number|case_number|reference|order_number|check_number|other), value}]
· people[] · organizations[] · tags[] (3-8) · title (filename-safe ≤80) · summary (2 sentences)
· corrections[{line:int, text:string, reason enum(digit|name|amount|date|other)}]
· page_role enum · confidence · needs_review · review_reason
```

Claude never returns a full transcript on the hot path: it corrects Vision by line index (≈50-150 output tokens), and corrected lines are re-spanned onto Vision boxes with banded character alignment (99.8-100% correct box assignment at 0.5-5% CER in gap-7's simulation). Full-transcript mode (handwriting, CJK/Thai, low Vision confidence) is an inline call accepted only if alignment edit distance <8% and no validated anchor disagrees.

Queue contract: at-least-once with idempotent apply keyed by page hash + schema version; commit only from `end_turn` + schema-valid parse; `retry-after` honored, spend-cap 429 trips a circuit breaker, 5xx/529/timeouts get jittered backoff then park.

Cost (list prices, computed): Haiku arm A at 400 output tokens ≈ $0.00044/page, plus corrections ≈ $0.0005; a 1.7-page document ≈ $0.00085; 5% Sonnet escalation adds ≈ $0.0007 → **≈ $0.0015 per document, ≈ $0.001 per page blended**. A 200-page/month household costs under $0.20/month; nothing here is designed to save Claude cost, everything to keep it off the critical path.

## 6. Durability design and the "safe to shred" guarantee

States per page (and per destination row):

```
S0 framed      memory only                        no promise
S1 captured    local-durable                      haptic; blob F_FULLFSYNC'd + atomic rename; ledger row in SQLite WAL synchronous=FULL fullfsync=ON
S2 safe        off-device-durable                 lock icon; ≥1 destination row `verified`
S3 replicated  all enabled destinations verified  local blob demoted to cache after +7 days, isExcludedFromBackup=true, protection promoted to Class A
```

Outbox row per (page, destination): `pending → staged → uploading → uploaded → verified → named → audited | failed(retry_at) | needs_attention | diverged`. Uploads are enqueued while the capture screen is in the foreground (non-discretionary), one background `URLSession`, `timeoutIntervalForResource` 30 days, `getAllTasks()` reconciled against the outbox on every launch. The first off-device artifact is the ~300 KB per-page PDF/A into a hidden `_pages/` folder, never the HEIC original; the user-visible document PDF follows at `confirmed`.

Honest copy: "Captured means it is safely on this phone. The lock means it is also in your iCloud Drive / Google Drive / NAS. Throw the paper away when the lock shows." The app claims sub-second capture and "safe within seconds on Wi-Fi", never sub-second durability. The residual hole is the S1→S2 window on a dead or deleted phone; it is stated in the durability doc and narrowed by keeping pending blobs inside iCloud Backup until S3.

Default first off-device copy: the iCloud Drive ubiquity container `Documents/PaperVault/<YYYY>/`, because the OS daemon moves the bytes independently of the app process, the data survives app deletion, it is user-owned and Files-visible, and Advanced Data Protection users get end-to-end encryption for free. `verified` requires `IsUploaded == true`, no uploading error, size match, and the archived `ubiquityIdentityToken` hash equal to the current one; the destination freezes on `NSUbiquityIdentityDidChange`. Full iCloud accounts fall through: S2 is satisfied by whichever enabled destination verifies first.

Data Protection classes (resolving privacy.md Class A vs apple.md Class C):

| Store | Class |
|---|---|
| Ops DB (ledger, hashes, outbox, session URIs); staging blobs pending upload | C (read after lock by reconciliation and daemons); staging inside iCloud Backup while pending |
| Vault blobs after S3 | A |
| Content DB (OCR text, FTS, vectors, entities) | A, foreground only; key in Keychain `WhenPasscodeSetThisDeviceOnly` |
| Enrichment results produced while locked | B files, merged at `protectedDataDidBecomeAvailable` |
| OAuth tokens, uploader vault key | Keychain `AfterFirstUnlockThisDeviceOnly` |

Scenarios: app crash keeps S1 and transfers continue; force-quit keeps S1 and cancels URLSession tasks until relaunch (a local notification after 30 minutes of pending pages nudges one); 48 h airplane mode loses nothing; a full device refuses capture visibly; app deletion loses S1-only pages (the documented hole) while iCloud Drive files persist and a reinstall rebuilds the ledger from sidecars; a nightly audit detects user-side deletions and re-uploads. Gap-4's 24-case device test matrix is the pre-ship gate.

## 7. Search design

Entirely on-device in v1 and v2; the same index is exportable so the archive stays searchable without the app.

- Lexical: GRDB external-content FTS5 over `title (10) / tags (5) / summary (3) / sender (3) / ocr_text (1)` with `porter unicode61`, plus a trigram table over masked `ocr_text` and identifier last-4s for OCR-mangled names and partial numbers. All words, including low-confidence ones, are indexed.
- Semantic: 384-d `bge-small-en-v1.5` embeddings of `title + sender + date line + each ~300-token chunk` of masked text, int8 in sqlite-vec with `doc_type`/`tax_year` metadata columns; brute force is single-digit milliseconds at personal scale; the same model embeds queries; `embedding_model` stored per vector.
- Fusion: Reciprocal Rank Fusion k=60; metadata filters as hard SQL constraints; facet chips (type, year, sender) from the current result set for zero-typing refinement.
- Query understanding: a deterministic on-device parser first (<10 ms): `NSDataDetector` dates, relative-period grammar ("last spring"), doc_type synonyms, known `sender_key` dictionary, tax-year patterns, amounts; remaining tokens become FTS terms and the whole string the semantic query. Optional refinement in parallel: Haiku 5.5 (thinking off, low, tiny filter schema) re-runs the query when it lands; Apple Foundation Models `@Generable` on A17 Pro+ is the free offline alternative.
- Aggregates ("how much did I pay Con Edison in 2025") are SQL over extracted `amount_*` cents; Claude phrases the answer and cites rows; RAG with `citations` over the top-20 chunks only for free-form questions.
- Core Spotlight: every document donated to a named index with `.complete` protection; `textContent` = summary + tags + sender + Class B identifiers only. `CSUserQuery` gives system-wide lexical + semantic search; `IndexedEntity` exposes "find my 2024 tax documents" to Siri.
- Eval: 150-300 labelled queries over the founder's own mail, nDCG@10 / Recall@20 via `ranx` in CI against the app-produced SQLite file; duplicates appearing twice, OCR-renamed senders and tax_year vs doc_date confusion are explicit test cases.

## 8. Output / PDF design

- Capture: 12 MP HEIC master kept in `originals/` (≈1.5-3 MB) until the PDF verifies at every destination, optionally forever. 48 MP only in stand mode, set once before `startRunning()`, with `photoProcessingTimeRange` shown as progress.
- Enhancement (one `CIContext` graph, GPU, off the feedback path): quad re-detected on the still → `CIPerspectiveCorrection` → `CILanczosScaleTransform` to 300 ppi (never upscale) → orientation (prior "phone top = page top", quad aspect, two-way `.fast` OCR confidence vote on a 1000 px thumbnail) → `CIDocumentEnhancer` plus a background-division kernel for hand shadows → white point → unsharp → grey/colour decision → sRGB JPEG q50-60. Pixels stored upright, `/Rotate 0`. No dewarp in v1; UVDoc (MIT, 8M parameters) is a v1.5 Core ML spike behind a text-line-curvature detector, and the retained HEIC allows re-rendering later.
- Page geometry: MediaBox from the five-signal rule (quad aspect within 3% of a standard size; locale prior; text line height or receipt column count; LiDAR depth × intrinsics on Pro models; Claude's document class as a late override), recorded as `pap:pageSizeSource`. Marketing claim: "300 ppi when the page is framed, never below 200 ppi", upgraded to FADGI 3-star only after a slanted-edge test.
- PDF/A-2u writer: one JPEG XObject per page (DCT pass-through; lossless JBIG2 or CCITT G4 only for an optional "compact" derivative, never the master), GlyphLessFont invisible layer from Vision word boxes with `3 Tr` and `Tz` fitting, ToUnicode CMap, sRGB OutputIntent, Info dict agreeing with XMP (dc/xmp/pdf/pdfaid + `pap:` extension schema: docType, sender, documentDate, taxYear, originalSHA256, ocrEngine, textLayerVersion, pageSizeSource), trailer `/ID`. Deterministic emission: `/ID[0]` and `xmpMM:DocumentID` derived from the capture-time ULID, `CreationDate` = capture time, image bytes and OCR JSON replayed in fixed object order, so a replay after a crash is byte-identical and every destination sees a duplicate, not a new file. veraPDF and a Preview/Acrobat/Chrome text-extraction diff gate every build.
- Units: the per-page PDF/A is the unit of durability (hidden `_pages/`); the document PDF is assembled by byte-copying page objects at `confirmed` and sealed after 24 h. Bytes are immutable after commit; filename and folder are mutable labels; classification lives in the filename, the sidecar and destination metadata. The text layer is rewritten only when a correction is material (a validated anchor changed, >2% of characters, or an accepted full transcript), as a new version through the verify flow.
- Export: AirPrint, share sheet, mail packs, real `.zip` via ZIPFoundation with `index.csv`, `index.json` and a bookmarked combined PDF; tax-year and expense packs are filters over extracted fields.

## 9. Storage destinations

| Destination | Commit | Verify | Rename | Audit | Notes |
|---|---|---|---|---|---|
| iCloud Drive (default first hop) | coordinated write into `Documents/PaperVault/<YYYY>/` | `IsUploaded` + no error + size + identity-token hash (no server hash; sidecar `.sha256` self-check) | coordinated two-URL move + `item(at:didMoveTo:)` | lifetime `NSMetadataQuery`; gather phase at each launch | Finder tags xattr carries tags; evict local copies only via `evictUbiquitousItem` after re-reading `IsUploaded` |
| Google Drive | `drive.file` only; app-created `PaperVault` by id; `generateIds` pool; one persisted resumable session per file; single-PUT background task started in foreground | `sha256Checksum` + size; 409 on replay → `files.get` and compare | `PATCH` name / `addParents` / `removeParents` | nightly `changes.list` from a stored token | 401 → `refreshTokensIfNeeded` + `bytes */N` probe + new task on the same session URI; `appProperties {sid, h}`; `indexableText` = summary + tags + Class B |
| Synology | WebDAV HTTPS `PUT` into `_inbox/` via background `URLSession` | `PROPFIND Depth: 0` size; `SYNO.FileStation.MD5` start/status (DSM 6.0+, official guide updated for DSM 7.0) when a File Station session exists; sampled read-back otherwise | `MOVE` with `Overwrite: F`, `_01` on 412 | `PROPFIND Depth: 1` per year | Publicly trusted certificate only (DSM Let's Encrypt on `synology.me`, Tailscale `tailscale cert`, or a user-installed CA profile); ATS cannot be loosened per host, so no fingerprint prompt. DSM 7 2FA via `SYNO.API.Auth` v6 `otp_code` + `enable_device_token` once, then `device_id`. No SMB, QuickConnect or NAS-side agent in v1 |

Common to all: path layout `PaperVault/<YYYY>/<YYYY-MM-DD>_<sender>_<doctype>_<id8>.pdf` (provisional `_unsorted_` until classification lands, late-bound when the task is created after Claude returns), a `<name>.json` sidecar uploaded after the PDF verifies, and a per-destination `_vault/index.jsonl` manifest so a fresh install rebuilds the ledger from any one destination. The lock needs one `verified` destination, preferring a server-digest destination over iCloud; "fully replicated" needs all. Deletions never propagate; user renames are adopted; overwrites are flagged `diverged`. Dropbox/OneDrive/Box and Paperless-ngx follow the same connector shape later.

## 10. Privacy and compliance posture

One sensitive-data policy keyed on where bytes go (gap-10), applied identically in BYO, App Store and service modes:

- Class A (secrets: SSN/ITIN, individual EIN, card PANs, bank account and routing numbers and the MICR band, DL/passport numbers, MRN and health-plan member IDs, passwords/PINs) exist outside the device only inside the archival PDF and its text layer in the user's own storage. Everywhere else, including the Claude request, structured output, sidecar, FTS, Spotlight, Drive `indexableText`, embeddings, filenames and logs, carries at most `[SSN ••••1234]` placeholders. Class B (reference IDs, employer EINs, amounts, dates) and Class C (names, addresses, body text, summaries) flow in plaintext.
- One `Redactor` pass after Vision OCR over word boxes (regex + context words, Luhn, ABA mod-10, MICR geometry on check-aspect pages, OCR confusion normalisation, both boxes of a split number) produces the only text any later stage may consume except the PDF writer. A CI canary feeds synthetic secrets and asserts they appear in no outbound request, index row, sidecar, filename or log. Masking recall is measured before it is advertised.
- Claude feature scope: inline Messages with base64 image or `document` block (128 MB / 600 pages on the first-party API, 100 under 1M context), prompt caching, structured outputs, token counting. Managed tier (v3): own org with ZDR on Haiku/Sonnet 5.5; HIPAA readiness only if a provider tier is ever sold. BYO tier: the user's own org, standard 30-day retention, honestly disclosed; the key lives in Keychain only, calls go device→`api.anthropic.com`, API keys only (no claude.ai logins, per the Consumer Terms and the AUP's proxy ban); get Anthropic's written confirmation before marketing it.
- On-device embeddings in v1/v2; Voyage (trains by default, irreversible org-level opt-out) is never used in BYO mode and only after opt-out, on masked text, in v3 if ever.
- App Store: 5.1.2(i) one-time revocable consent naming Anthropic before the first call, with different copy per mode; withdrawal leaves a fully working on-device mode (capture, OCR, archive, FTS), which also satisfies 5.1.1(ii); one superset nutrition label ("Data Linked to You, App Functionality, no tracking": User Content, Financial, Health, Sensitive Info, Name, Address) with a matching `PrivacyInfo.xcprivacy`; `ITSAppUsesNonExemptEncryption=false` by staying on OS Data Protection, CryptoKit and TLS. No account in v1/v2.
- Legal entity: form the LLC and enroll as an Organization before the App Store build (5.1.1(ix); ZDR/DPA are organisational contracts; a later app transfer changes the Team ID and forces a re-login).
- Record-keeping law: the "how your archive works" page maps onto Rev. Proc. 97-22 §4 (hash manifest, immutable PDF/A, periodic integrity scan, index, 300 ppi reproduction); FRE 1003 covers duplicates; the classifier sets `keep_original` for vital records, wills, deeds/titles, notarized documents, bearer instruments, undeposited checks and wet signatures, and the app says "keep this paper" instead of "safe to discard". EU launch is a separate workstream.
- Regulatory exposure stays minimal because the developer holds nothing in v1/v2: HIPAA does not apply; FTC HBNR (individual notice within 60 days, FTC notice for any breach, penalties ≥$53,088 per violation) and Washington MHMDA become live only with a hosted v3, where client-side E2EE with a recovery key is the design.
- Every captured page, including junk mail, is retained forever; junk is tagged `discardable`, hidden from default search, and skips the Claude call once the classifier is confident.

## 11. Phased delivery (solo senior iOS developer with AI assistance, ~30 productive h/week)

| Phase | Weeks | Scope | Exit criterion |
|---|---|---|---|
| 0. Measurement harness | 2 | `OSSignposter` on every stage; 200-page handheld corpus (pages re-shot 5×, 50 sibling pairs, 20 few-field bill pairs, 30 receipts, 20 blank backs, 20 duplex letters) on iPhone 13, 15 Pro, 16, 17 Pro; Vision CER between captures; feature-print latency; F_FULLFSYNC cost; `count_tokens` tier check; `haiku_hot_path_bench.py` matrix; `kCGPDFContextCreatePDFA` veraPDF spike; FTS5 availability | per-stage p50/p95 per device; dedup thresholds; go/no-go on thinking-off |
| 1. Personal v0 | 6-8 | capture state machine, S1 durability, two Vision passes, Redactor, dedup cascade, grouper, rules/sender-memory label, PDF/A-2u writer, Haiku extraction with corrections, iCloud Drive first hop, FTS5 + sqlite-vec, Spotlight donation, timeline | founder digitises his own mail for a month; 20 ppm sustained; zero false "already scanned" on the corpus; veraPDF green |
| 2. Destinations, search, export (TestFlight) | 6-8 | Drive and Synology connectors with verify/rename/audit, outbox UI, query parser + hybrid search + eval harness, print/share/zip/tax packs, share extension + Files inbox, Create ML classifier, Sonnet escalation, 24-case durability matrix | 20-50 testers; measured S2 latency published; search nDCG baseline |
| 3. App Store (BYO tier) | 6-8 | LLC + Organization enrollment, consent/labels/privacy policy, "how your archive works" page, StoreKit 2 (free on-device tier, BYO key, one-time Pro unlock), tap-free onboarding | approved listing; no backend |
| 4. Service (managed tier) | 12-16 | Cloudflare Worker key-proxy with App Attest and Sign in with Apple, ZDR org, metering, opt-in E2EE relay (R2, 30-day TTL), opt-in email-forwarding ingest (the Worker persists synchronously because `setReject` is a permanent bounce, not a retry), CloudKit encrypted ledger mirror, UVDoc dewarp spike | managed subscription live; SOC 2 Type I started |

Total: roughly 9-12 months to a multi-tenant service; half of phases 0-2 is the capture loop and durability pipeline, which is where the product risk is.

## 12. What the founder must provide

- An Anthropic key with a workspace spend limit for the harness (the full matrix on 200 pages costs ≈$1) and, before v3, a sales conversation for ZDR on a dedicated org; the current usage tier matters for TestFlight concurrency.
- Devices: iPhone 13 (A15 floor), 15 Pro (Apple Intelligence), 16, 17 Pro (LiDAR), plus a stand.
- Test corpus: ≈200 real pages of his own mail across the taxonomy with typed ground truth (fields, boundaries), the re-shot and sibling sets above, and a week's count of junk share.
- Accounts: a Google Cloud project with the OAuth consent screen published (homepage and privacy policy on an owned domain), a Synology NAS on DSM 7.x reachable over HTTPS with a public certificate or Tailscale, an iCloud account near its quota for the fallback test, and a Mac with Xcode 27 and Docker for veraPDF and Create ML.
- Decisions: iOS 26 floor confirmed against App Store Connect cohorts; provisional label acceptable in the first second; "keep this paper" classes; whether Legal-size pages matter; LLC timing; whether the service tier may ever hold ciphertext.

## 13. Top risks and mitigations

| Risk | Mitigation |
|---|---|
| Apple segmenter fails on white-on-white mail or folded letters | Week-one harness on the real corpus; `isUtility` gate; decision point at week 3 to license Genius Scan's detector behind the same state machine |
| A false "already scanned" makes a user discard an unscanned page | Capture always persists; the cue is a hint with the matched thumbnail; merge requires text + two agreeing anchors; false-skip rate must be 0 on the calibration set |
| Vision CER between handheld captures breaks SimHash/Jaccard thresholds | Measured in phase 0; graded Jaccard over SimHash; text tiers advisory under 400 characters; sharper copy kept canonical |
| Haiku 5.5 thinking-off TTFT is several seconds | UX never waits on it; provisional label is local; if p95 >5 s, summary moves to a later text-only call |
| iCloud Drive upload timing and force-quit behavior are undocumented | Tests T9/T11 decide the lock-icon copy; non-iCloud destination recommended; service-phase relay as opt-in |
| Full iCloud accounts leave iCloud-only users without S2 | Fall-through quorum; onboarding nudges a second destination; amber "on this phone only" state |
| A15 cannot keep accurate OCR up with 20 ppm | Visible backlog; `BGContinuedProcessingTask`; `.fast` cropped to digit-bearing lines |
| Masking recall misses handwritten or split numbers | Box-level masking, 9-digit-near-keyword rule, measured recall, identity documents never sent, text-only for sensitive classes |
| Same-sender single-page stacks are mis-grouped | Split bias; first/last-page structure cues; Claude pairwise merge at ≥0.8; every decision logged for a future fine-tune |
| Apple ships native scan-and-understand | Differentiate on multi-destination user-owned storage, durability states, cross-year search and export packs |

## 14. Where I deliberately disagree with the research

1. **capture.md and dedup.md**: no dHash "same page, holding" gate suppresses capture. The trigger is quad lifecycle; hashes only produce hints. Their rule would have skipped a sharper re-capture and, worse, last month's statement, since gap-2 measured sibling statements at dHash 0-6 bits, inside the same-page band.
2. **storage.md**: no service-owned R2 escrow as the first commit in any phase; it contradicts "user-owned, no backend" and returns only as an opt-in relay in v3.
3. **apple.md and output.md**: no CloudKit `CKAsset` first hop (double iCloud quota, invisible in Files, tied to iCloud Keychain), no 48 MP default (forfeits ZSL, adds seconds), no 24 MP (deferred-only, Photos-bound).
4. **architecture.md and apple.md**: Foundation Models is not the instant label. It is unavailable on the A15 floor, needs 1.2-1.8 s of prefill for a page transcript at the only published rate, cannot take images before iOS 27, and runs guardrails on guided generation, so it may refuse exactly the medical and legal pages the sensitivity gate exists for.
5. **privacy.md and storage.md**: Class A protection for everything background work touches makes uploads fail silently after lock (Class C for ops DB and staging, Class A at S3, Class B for locked-time results); and there is no "trust this fingerprint" prompt for self-signed NAS certificates because ATS cannot be loosened in the delegate.
6. **dedup.md**: no end-of-session K=5 Claude boundary pass. Boundary F1 falls monotonically with window size (0.969 pairwise vs 0.795 at K=5 on VRDU); boundaries are folded into the per-document incremental call as a pairwise verdict.
7. **mail.md**: junk is never purged; the one-tap merge/split is optional telemetry; and UVDoc is 8M parameters, a Core ML candidate rather than a server-side pass.
8. **search.md and claude.md**: no Voyage in v1/v2. Embedding documents with Voyage and queries with MiniLM is two vector spaces; Voyage trains by default; and it is a second third-party flow of full document text.
9. **ocr.md and output.md**: no Mistral OCR 4 or self-hosted PaddleOCR fallback in v1, and language correction is not on for everything. Correction turns codes into words, so anchors come from a raw pass; Claude corrects by line index rather than re-transcribing, because the post-OCR literature (Boros et al., eight benchmarks) shows LLMs mostly degrade near-clean text and hallucinate.
10. **ingest.md and business.md**: no Cloudflare email ingest, IMAP poller or second backend developer in v1/v2; phone-side paths cover the founder's needs with zero servers.
11. **competitors.md**: the gap is not raw hands-free capture (Genius Scan and Adobe Scan already auto-capture in batch mode); it is grouping, dedup, understanding, honest multi-destination durability, and search.
12. **claude.md and business.md**: the planning number is $0.00044/page at 1,100 px with thinking off, not the $0.0004 that assumed adaptive thinking and the legacy /750 token formula.
