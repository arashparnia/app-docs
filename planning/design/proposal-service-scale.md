# Architecture proposal: SERVICE-SCALE angle

Author role: principal engineer. Date: 2026-11-03. Angle: design from day one as a multi-tenant App Store product with managed keys, accounts, billing and a path to Android, while keeping v0 shippable by one developer. Evidence base: the 24 research reports in `scratchpad/research/` with the fact-check corrections applied. Every latency figure is a target to be measured in week one unless marked **measured**.

## 0. The three decisions that shape everything

1. **The phone is the product; the backend is a thin trust boundary.** Capture, dedup, OCR, PDF/A, search and durability run on-device. The backend holds the Anthropic key, identity, entitlements and an optional encrypted relay bucket: a few hundred lines of Cloudflare Worker plus Supabase, not a second developer.
2. **One honest durability vocabulary.** `captured` (haptic) = local-durable. `safe` (lock) = one verified off-device copy. Paper goes in the bin when the lock shows. Nothing ever says "already scanned" as a reason not to store a page.
3. **Managed keys from v0, BYO key as a device-direct advanced mode.** Retrofitting accounts, App Attest and a proxy later would change the Team ID, the Keychain group and the consent flow; doing it first costs about two weeks and makes every later phase additive.

## 1. Architecture

```
iPhone (Swift 6, iOS 26.0+, A15 floor)
┌──────────────────────────────────────────────────────────────────────────┐
│ CAPTURE LOOP (never waits on network)                                    │
│  AVCaptureSession .photo, 12 MP .balanced, ZSL+responsive, deferred OFF  │
│   ├─ low-res VideoDataOutput (1920x1440, 420v) ─► CaptureActor           │
│   │    DetectDocumentSegmentation ▸ quad track ▸ stability ▸ sharpness   │
│   │    ▸ exposure/glare ▸ framing gate (≥0.78 of frame)                  │
│   └─ AVCapturePhotoOutput still ─► atomic write + ledger row ══► S1 haptic│
│ ON-DEVICE PIPELINE (actors, disk-backed queues)                          │
│  Rectify ─► dHash / PDQ quality / feature print                          │
│  Vision .fast RAW (anchors, dedup text, orientation, provisional label)  │
│  Vision .accurate+correction / RecognizeDocumentsRequest (layer, FTS)    │
│  Redactor (word-box masking, 3-class policy) ─► masked JPEG + text       │
│  Label: rules ▸ sender memory ▸ Create ML text classifier                │
│  PDF/A-2u page (own writer, Vision layer, deterministic /ID)             │
│  Grouper (page→document manifest, split-biased)                         │
│  SQLite (GRDB): ops DB (WAL, FULL, fullfsync) + content DB (FTS5, vec)   │
│  Core Spotlight donation (summary + tags + Class B only)                 │
│ SYNC ENGINE                                                              │
│  Outbox per (page|doc, destination): pending→staged→uploading→uploaded→  │
│  verified→named→audited; background URLSession started in foreground     │
│   ├─ Relay (managed tier): R2 pre-signed PUT + sha256 check ══► S2 lock  │
│   ├─ iCloud Drive ubiquity container (free-tier first hop)               │
│   ├─ Google Drive (drive.file, generateIds, resumable, sha256Checksum)   │
│   └─ Synology WebDAV/HTTPS (+ File Station MD5), trusted certificate     │
└──────────────────────────────────────────────────────────────────────────┘
          │ HTTPS: Sign in with Apple JWT + App Attest assertion
┌──────────────────────────────────────────────────────────────────────────┐
│ BACKEND (Cloudflare Workers + R2 + Queues; Supabase Postgres + Auth)     │
│  /v1/understand ─► Claude Haiku 5.5 (effort low, thinking off, structured│
│     output, streamed, cached system prompt) ─► Sonnet 5.5 fallback       │
│  /v1/relay/presign ─► R2 object per page (app-level E2EE, 30-day TTL)    │
│  /v1/entitlement ─► StoreKit 2 server notifications → entitlements table │
│  Postgres: tenants, users, entitlements, usage, encrypted ledger mirror  │
│  Phase 4: email ingest, web viewer, cloud index (masked text + Voyage)   │
│  Phase 5: Android client (CameraX + ML Kit) against the same API         │
└──────────────────────────────────────────────────────────────────────────┘
```

The proxy is platform-neutral: every request carries an opaque install id, an entitlement check and the frozen prompt/schema version, so Android is a second consumer of the same endpoints.

## 2. Tech stack

| Layer | Choice | Floor | Why |
|---|---|---|---|
| App | Swift 6, SwiftUI, AVFoundation, Vision, Core Image/Metal, Core Motion | Xcode 27, **iOS 26.0**; `#available(iOS 27)` for Foundation Models image input, `OCRTool`, Core AI | iOS 26/27 support identical hardware (A13+); 26 is ~80% of iPhones today; floor for `RecognizeDocumentsRequest`, `DetectLensSmudgeRequest`, `BGContinuedProcessingTask`. 27-only would exclude ~80% of users (gap-8). |
| Floor device | iPhone 13 (A15, 12 MP) | — | One capture path everywhere; 12 MP is the only resolution compatible with ZSL and a private archive (gap-3). |
| Local DB | GRDB 7.12 + bundled SQLite (FTS5 porter/unicode61 + trigram) + sqlite-vec 0.1.9 (USearch fallback) | — | SwiftData/Core Data have no FTS; bundling removes the `ENABLE_FTS5` doubt. |
| Embeddings | On-device `bge-small-en-v1.5` (384-d, MIT) via swift-embeddings; Voyage `voyage-4-lite` only in the phase-4 cloud index after training opt-out | — | No third-party text flow until the service phase (gap-10); one model per index. |
| Classifier | Rules + letterhead feature-print kNN + Create ML `MLTextClassifier` (maxEnt, then BERT transfer) | iOS 17 runtime | Runs on the floor device; no Apple Intelligence gate; no guardrail refusals (gap-8). |
| PDF | Own Swift PDF/A-2u writer, veraPDF in CI; one-day spike of `kCGPDFContextCreatePDFA` as fallback | — | Only path with DCT pass-through, byte-copy merging and deterministic `/ID` (output.md, gap-5, gap-9). |
| Cloud AI | `claude-haiku-5-5`; `claude-sonnet-5-5` for escalation and refusal fallback; pinned `anthropic-version`; raw streaming fetch from the Worker | — | Cheapest, "Fastest"; structured outputs GA; 512-token cache minimum. |
| Backend | Cloudflare Workers Paid ($5/mo), Queues, R2; Supabase Pro ($25/mo) Postgres + Auth + RLS | — | ~$30/month fixed to 1k users; free egress; AI cost dominates at every scale. |
| Auth / billing | Sign in with Apple JWT + `DCAppAttestService`; StoreKit 2 + App Store Server Notifications v2 → entitlements table; Small Business Program (15%) | iOS 14/15 | Keys never ship in the binary; Google Play Billing lands in the same table later. |
| Telemetry | `OSSignposter`; MetricKit `MetricManager` (old API deprecated 27.2); histograms only | — | gap-3 harness. |
| Android (phase 5) | Kotlin, CameraX `ImageAnalysis`, ML Kit Text v2, OpenCV or Genius Scan detector; same proxy | API 26 | ML Kit Document Scanner is a modal Intent (capture.md). |

Licensing: no MobileCLIP weights (AMLR research-only, gap-2); no Chandra/MinerU; Apache-2.0/MIT only.

## 3. Latency budget

The only **measured** on-device numbers are text_sight's iPhone 16 figures: one-shot `.fast` 101 ms, `.accurate` 404 ms, `.accurate`+correction 736 ms p50 on a 63-line page; live 1080p fast 19/s, accurate 5/s. Everything else is derived.

| Stage | Feed | Target A17+ / A15 | Evidence |
|---|---|---|---|
| Quad per preview frame | 1920x1440 420v | 10-30 ms | Apple: segmenter "runs in realtime" on the Neural Engine (WWDC21); unmeasured |
| Stability decision | 6 stable frames (IoU ≥0.95, area Δ ≤5%) + gyro | ~200 ms after settle | 30 fps frame math; same shape as Dynamsoft/Scanbot |
| Still delivered | 12 MP `.balanced`, ZSL+responsive | 100-300 / 150-400 ms | WWDC23 ~2 photos/s before responsive capture; ZSL on by default iOS 17+ |
| **S1 `captured`** | F_FULLFSYNC blob + 2 fsync'd commits | **<300 / <500 ms** after stability | gap-4; F_FULLFSYNC cost unknown (plan 5-50 ms) |
| Visual duplicate hint | dHash + feature print on the still | +5-30 / +10-60 ms | dHash <1 ms (estimate); feature print unmeasured |
| `.fast` RAW OCR on 2-3 MP rectified page | anchors, SimHash, orientation, label | 150-300 / 300-600 ms | text_sight 101 ms at a smaller input; A15 ≈2.2x slower by TOPS |
| Provisional label | rules → sender kNN → Create ML | visible ≈0.3 / 0.7 s | gap-8 |
| Text-tier duplicate confirmation | Jaccard + parsed anchors | within ~1 s | gap-2 synthetic ROC |
| `.accurate`+correction on 12 MP | text layer, FTS | 1-3 / 2-6 s, async | pixel scaling of 736 ms; never on feedback path |
| Warp + enhance + JPEG + PDF/A page | GPU graph + writer | 100-250 ms + <20 ms, async | gap-9 estimates |
| **S2 `safe`** (relay, 300 KB page) | foreground-started PUT | **p50 <2 s Wi-Fi, <5 s LTE**; iCloud path p50 <5 s / p95 <60 s, measure | storage.md option D; iCloud timing unmeasured |
| Claude `doc_type` streamed | 1,100 px masked JPEG + text, thinking off | TTFT ~0.5-1.5 s; full record ~3-4 s p50 | AA 165-176 tok/s decode; Sonnet `low` TTFT 1.2 s is the only sub-2 s anchor; Haiku thinking-off unmeasured (gap-6) |
| Sustained cadence | handheld | 20 pages/min for 10 min without `serious` thermal on A15 | unmeasured anywhere |

Rule: everything above S1 completes before the user can move to the next page (~1 s); everything below is progressive refinement into an already-visible card.

## 4. Zero-interaction capture state machine

**States:** `SEARCHING → TRACKING(quad) → SETTLING → FIRING → COMMITTED → HOLDING → SEARCHING`, plus session-level `STAND_MODE` and `THERMAL_{fair,serious,critical}`.

- `SEARCHING → TRACKING`: quad ≥25% of frame, no corner on the edge; a *quad track* id starts.
- `TRACKING → SETTLING`: for full-page aspects, quad long side ≥0.78 of the frame long axis (≥286 ppi on Letter at 12 MP); for receipts/cards/envelopes, implied ppi ≥300 or distance at `minimumFocusDistance`. Soft "closer" cue only.
- `SETTLING → FIRING`: 6 consecutive frames IoU ≥0.95, gyro below threshold, Laplacian within 10% of the page's running max and above a floor, clipped pixels in the mask below X%, `isAdjustingFocus == false`, `captureReadiness == .ready`.
- `FIRING → COMMITTED`: still delivered, atomic write, ledger commit, `UINotificationFeedbackGenerator.success` + click, card with the rectified thumbnail. If the still is late or blurrier than the best cached 4032x3024 video frame, commit the frame first and swap the still in later: the haptic never waits on the ISP.
- `COMMITTED → HOLDING`: same track persists. **No re-fire within a track**, except a replacement when sharpness improves >25% (stored as a variant). This is the only suppression rule and it is keyed on track continuity, never on a hash.
- `HOLDING → SEARCHING`: quad lost >150 ms. The next acquisition is a new track and **always captures**.

**Duplicates, one rule.** No hash, embedding or text signal ever prevents a capture or a local write. The cue is two-beat and worded as a hint: within ~50 ms of the still, dHash + feature print against the archive's candidate set shows "Looks like page 3 (2 min ago)" with a thumbnail and a double-buzz; within ~1 s the text tier (RAW `.fast` 9-gram Jaccard ≥ calibrated floor, start 0.6, **and** two parsed anchor fields agreeing exactly, **and** none disagreeing) hardens it to "Already scanned, kept the sharper copy" or retracts it silently. The index spans the whole archive (hashes, SimHash band LSH and anchors in SQLite, flat in memory: 200k pages = 13 MB, 0.4 ms scan). Merging into a variant is an asynchronous catalog edit. Pages under 400 characters, blank backs (ink-coverage gate) and `anchor_uncertain` pages never merge automatically.

**Page boundaries.** Page = unit of capture and durability; document = unit of inference. On-device scorer: N-of-M footer with position and increment check (±5), first-page structure (+3), last-page structure on the previous page (+2), form-factor change (+3), letterhead feature-print match (−2/+1), anchor id match (−3), pending envelope (+2), capture gap as a *prior* only (<4 s same quad = duplex flip; >60 s or left screen = boundary). Score ≤−2 append; ≥2 new document; uncertain band → **split**, mark `tentative`; Claude's next incremental call returns `continues_open_document`, `boundary_confidence`, `suggested_merge_with`; auto-merge at ≥0.8. Envelopes become `envelope_of` the next document; blank backs are flags. No tap is ever required; the optional merge/split affordance is telemetry.

**Feedback vocabulary:** success haptic + click = captured; double-buzz + chip = duplicate hint; warning haptic + optional spoken "keep this paper" for `keep_original` classes (legal, titles, certificates, undeposited checks); lock icon = safe.

**Stand mode:** gyro still >3 s; motion gate relaxed; optional 48 MP with `photoProcessingTimeRange` shown.

**Thermal policy** (observe `systemPressureState` and `thermalState`): nominal = full rate, torch ≤0.5 on demand; fair = segmentation every 2nd frame, accurate OCR paused while the camera is live, torch ≤0.3; serious = 15-20 fps preview, torch off, stills at `.speed`, all later stages deferred; critical = pause with a message; shutdown = session interruption, nothing lost because S1 already happened.

## 5. Claude usage design

**Models.** Haiku 5.5 for every page (`effort: "low"`, `thinking: {"type":"disabled"}`); Sonnet 5.5 (`between_tools`, low) for `needs_review`, `confidence < 0.6`, handwriting, non-Latin script, >40 pages, and as the client-side refusal fallback (Haiku has no server fallback or credit). Opus never. Thinking-off is chosen against the general "lower effort instead" guidance because its two documented failure modes (skipped tool calls, reasoning prose) cannot occur in a tool-less, grammar-constrained call; adaptive-low stays in the harness and wins only if `usage.output_tokens_details.thinking_tokens` (read from the final `message_delta`; the reports' "no usage field" claim was wrong) is <100 median and accuracy is better.

**Input per page.** Masked JPEG at 1,100 px long edge, q85 (≈1,240 visual tokens; confirm the high-res tier once with `count_tokens` on a 1075x1520 image: 2,145 = high-res), plus numbered Vision lines with placeholders (~800 tokens), plus ~150 tokens of instructions. 1,568 px (2,464 tokens) only for low-confidence or dense pages. Never above 2,576 px. OCR text is mandatory: Vision supplies exact digits, Claude supplies layout, logos, stamps and handwriting.

**Call shape: incremental cached document conversation** (gap-1 structure C). Call n sends pages 1..n with 1..n−1 as cache hits and returns the document-so-far record, so per-page feedback latency equals an independent call and the boundary verdict costs no extra round trip; a 5-page packet is ~$0.003. Chunk or switch to Sonnet above ~40 pages (100K-token price step).

**System prompt** (≥512 tokens, one `cache_control` breakpoint, 5-minute TTL because service traffic is continuous): taxonomy (33-value `doc_type` enum, mail.md's classes as `doc_subtype`), extraction rules, 2-3 worked examples. Known senders go in the user turn. Frozen per app version together with `thinking`, `effort`, `output_config.format`.

**Schema** (`json_schema`, all properties required and nullable, required-first streaming): `doc_type` first, then `continues_open_document`, `boundary_confidence`, `suggested_merge_with`, `expected_page_count`, `doc_subtype`, `language`, `sender`/`recipient`, dates (`document_date`, `due_date`, `period_start/end`, `tax_year`), `amounts[]`, `identifiers[] {kind ∈ tax_id_last4 | account_last4 | member_id_last4 | invoice_number | claim_number | policy_number | case_number | order_number | reference, value}`, `people[]`, `organizations[]`, `tags[]`, `title`, `summary`, `page_roles[]`, `keep_original`, `sensitive_class`, `corrections[] {line, text, reason}` (diff-style, 50-150 tokens, never a transcript), `confidence`, `needs_review`, `review_reason`. No `reasoning` field; no PHI in enum/const/pattern values.

**Query parsing:** tiny schema (`filters`, `keywords`, `semantic_query`, `aggregate`), thinking off, ~150 in / 80 out tokens, in parallel with the on-device parse. **Backfill:** inline text-only Haiku calls (≈$0.0006/page). Message Batches and the Files API are **forbidden by CI lint** because ZDR silently steps out for them.

**Proxy contract:** at-least-once with idempotent apply keyed by page hash + schema version; commit only on `end_turn` + schema-valid parse; 429 `retry-after` honoured; spend-cap 429 opens a circuit breaker; 5xx/529/mid-stream error → full-jitter backoff capped 60 s, 8 attempts, then `metadata_parked`; refusal → one Sonnet retry → `metadata_refused` with the on-device label kept. `metadata.user_id` = opaque install hash; timeout 45 s; SDK retries 0.

**Cost per document (list prices).** Arm A: 2,190 uncached × $0.10/M + 2,500 cached × $0.01/M + 400 out × $0.50/M = **$0.00044/page**; 10% Sonnet escalation adds $0.00086; multi-page cache writes ~$0.00016; query calls ~$0.00001. Blended ≈ **$0.0015/page, ≈$0.003 per document** (mean 1.8 pages). Relay storage and Worker requests are below $0.00001. A 150-page/month user costs ~$0.25/month against $3.54/month net on a $49.99/yr plan (7% COGS). `inference_geo: "us"` (×1.1) only on customer demand.

**Capacity.** ITPM binds before RPM: Start tier ≈913 pages/min ≈46 simultaneous scanners; Build ≈114; Scale ≈228. Request Build at launch and Scale before ~5,000 users; keep uncached tokens per page under ~2,500.

## 6. Durability design and the "safe to shred" guarantee

**Vocabulary (per page, per destination):** `S0 framed` (RAM) → `S1 captured` (haptic) → `S2 safe` (lock) → `S3 replicated` (status screen).

- **S1** = corrected page blob written with `F_FULLFSYNC` then `rename`; ledger row committed in the ops DB (`WAL`, `synchronous=FULL`, `fullfsync=ON`). Durable across crash, force-quit, reboot and 48 h airplane mode; not across app deletion or device loss. The content DB stays `NORMAL`.
- **S2** = at least one `verified` outbox row: relay (R2 `x-amz-checksum-sha256`), Google Drive (`sha256Checksum` + size), Synology (`SYNO.FileStation.MD5` or HEAD size + sampled read-back), iCloud Drive (`ubiquitousItemIsUploadedKey`, no uploading error, size, identity-token hash current). Prefer server-digest destinations when several finish together.
- **S3** = every enabled destination `verified`; local blob demoted to cache, `isExcludedFromBackup = true`, protection promoted to Class A, kept 7 days.

**First off-device hop.** Managed tier: the **relay** (R2, per-document random key wrapped by a user key in iCloud Keychain, 30-day TTL, deleted once the user's destinations verify). It is independent of the user's iCloud quota and NAS uptime and lands in seconds from the foreground. Free/BYO tier: the **iCloud Drive ubiquity container** (OS-managed daemon, survives app deletion, Files-visible, E2EE under ADP), falling through to Drive/Synology on `ubiquitousFileNotUploadedDueToQuota` or a nil identity token. CloudKit `CKAsset` never carries page bytes (double quota, invisible, keychain-reset loss); CloudKit carries only the encrypted ledger mirror.

**What uploads when.** The per-page PDF/A page (150-400 KB) uploads at S1 to the relay or a hidden `_pages/` folder; 30 pages/min is 1.2 Mbit/s. The user-visible document PDF uploads at `confirmed` (closed + Claude verdict or 60 s) under a provisional name, then is renamed by a metadata operation. Raw stills never gate S2.

**Data Protection classes:** ops DB, outbox staging, ubiquity files = Class C (daemons read them after lock; a protected SQLite returns `SQLITE_IOERR`); content DB and S3 vault blobs = Class A, foreground-only; enrichment results produced while locked = Class B files merged at `applicationProtectedDataDidBecomeAvailable`; Keychain `AfterFirstUnlockThisDeviceOnly` for upload tokens and the relay key, `WhenPasscodeSetThisDeviceOnly` only for the content DB key.

**Failure outcomes.** Force-quit cancels `URLSession` tasks and blocks relaunch: reconcile `getAllTasks()` against the outbox on every launch, enqueue from the foreground, notify if pages stay S1-only >30 min. App deletion loses S1-only pages; relay/iCloud copies and sidecars rebuild the ledger on reinstall. Low storage: refuse capture visibly. Nightly `BGProcessingTask` audit (Drive `changes.list`, Synology `PROPFIND`, iCloud gather phase, 1-in-20 hash read-back); user renames adopted, overwrites flagged, deletions never propagated. gap-4's 24-case device matrix is the acceptance suite.

**Paper-disposal copy:** "Captured means it is safely on this phone. The lock means it is also in your [iCloud Drive / Google Drive / NAS / vault]. Documents marked *keep this paper* should not be discarded." Never "sub-second durable".

## 7. Search design

- **Index per page, search per document.** `documents` (denormalised Claude fields, integer cents, `sender_key`), `pages` (masked OCR text, hashes), `document_fts` (external-content FTS5; weights title 10 / tags 5 / summary 3 / sender 3 / text 1), `document_trgm` (trigram over masked text and identifier variants), `document_vec` (sqlite-vec 384-d int8 with `doc_type`/`tax_year` columns), facets table.
- **Text sources** (gap-7): FTS body and PDF layer from Vision `.accurate`+correction in paragraph order; anchors from Vision `.fast` RAW; fields from Claude; three-witness validation (two agree exactly, or one passes a structural check) with alternates indexed in the trigram table. Low-confidence words stay in the layer and trigram table, never in anchors.
- **Query path:** deterministic parser (<10 ms: `NSDataDetector`, relative periods, type synonyms, known senders, amounts) → FTS ∪ trigram → on-device query embedding when ≥3 content words → RRF (k=60) → SQL filters as hard constraints; the Haiku parse refines in parallel; facet chips give zero-typing refinement.
- **Aggregates** are SQL over extracted amounts; Claude only phrases and cites. Free-form QA: top-150 chunks → top-20 → Claude with `citations.enabled` on `content` documents.
- **Core Spotlight:** named index, `.complete` protection, `textContent` = summary + tags + sender + Class B only; `IndexedEntity` for Siri; `CSUserQuery.prepare()` before search.
- **Phase 4:** Postgres FTS per page + pgvector `halfvec` HNSW with `tenant_id` RLS (ParadeDB if BM25 quality matters); Voyage `voyage-4-lite` on masked text after the training opt-out; the on-device index stays primary.
- **Eval:** 150-300 labelled queries, nDCG@10 / Recall@20 via `ranx`, in CI against the app's own SQLite file.

## 8. Output / PDF design

- **Geometry:** 12 MP still, quad re-detected on the still, `CIPerspectiveCorrection` → Lanczos to 300 ppi (never upscale) → orientation (prior "phone top = page top", quad aspect, two-way `.fast` OCR confidence vote on a 1000 px thumbnail) → `CIDocumentEnhancer` + background-division kernel → white point → unsharp → grey/colour decision → sRGB JPEG q50 master, upright pixels, `/Rotate 0`. Claim "300 ppi master when framed, never below 200 ppi" until a slanted-edge test is run (FADGI 3-star is ≥294 ppi measured).
- **MediaBox** from the five-signal rule: quad aspect within 3%, locale prior, text line height or receipt column count, LiDAR depth × intrinsics on Pro models, document class late; `pap:pageSizeSource` in XMP.
- **PDF/A-2u, own writer:** one DCT XObject per page (JPEG bytes unchanged), GlyphLessFont invisible layer from Vision word boxes (`3 Tr`, `Tz` fitting, explicit spaces, ToUnicode), sRGB OutputIntent, XMP with `pdfaExtension` schema, Info/XMP agreement, `/ID[0]` from docId, `/ID[1]` body digest, `CreationDate` = capture time; byte-identical re-emission; veraPDF plus a Preview/Acrobat/Chrome extraction diff in CI. Multi-page documents are byte-copies of page objects, never PDFKit merges.
- **Immutable bytes, mutable label.** The PDF is built once with the Vision layer before any upload. Classification lives in the filename (`YYYY/YYYY-MM-DD_<sender>_<doctype>_<id8>.pdf`, renamed from `_unsorted_unsorted_`), the `<name>.json` sidecar, Drive `appProperties {sid,h}` and `indexableText` (summary + tags + Class B), Finder tags and `_vault/index.jsonl`. Rewrite only on a material correction (validated anchor changed or >2% of characters), through the full verify path.
- **Compression:** 8-bit grey/colour JPEG master (FADGI forbids bilevel masters); JBIG2 generic-region or CCITT G4 only as a "compact copy"; MRC v2. **Originals:** 12 MP HEIC kept until S3, then an opt-in "keep negatives" (enables a later Core ML UVDoc dewarp, 8M params, MIT).
- **Export:** `UIPrintInteractionController`, `UIActivityViewController`, tax-year and expense packs as ZIP with per-document PDF/A, `index.csv`, `index.json` and a bookmarked combined PDF; expiring share links from R2 in phase 4.

## 9. Storage destinations

| Destination | Transport | Verify | Rename | Notes |
|---|---|---|---|---|
| Relay (managed) | Pre-signed R2 PUT, foreground-started background task | `x-amz-checksum-sha256` server reject | n/a | App-level E2EE; 30-day TTL; deleted once user destinations verify; default-on for subscribers, opt-out |
| iCloud Drive | `setUbiquitous` into `Documents/PaperVault/YYYY/`; one lifetime `NSMetadataQuery` | `IsUploaded` + no error + size + identity hash | coordinated move + `item(at:didMoveTo:)` | Freeze on `NSUbiquityIdentityDidChange`; evict only after a fresh `IsUploaded` read |
| Google Drive | REST v3, `drive.file` only (no CASA), `generateIds` pool, persisted resumable session, single file-backed PUT | `sha256Checksum` + size | `PATCH` name/parents | Refresh token before task creation; 401 → refresh + `*/N` probe + new task; consent screen out of Testing before TestFlight |
| Synology | WebDAV/HTTPS with a **publicly trusted certificate** (DSM Let's Encrypt on `synology.me`, Tailscale + `tailscale cert`, or a user-installed CA profile); optional File Station session (`otp_code` + `enable_device_token` once, `device_id` after) | `SYNO.FileStation.MD5` or size + sampled read-back | `MOVE Overwrite: F` → `_01` on 412 | No fingerprint prompt (ATS cannot be loosened); static private-range `NSExceptionDomains`; no SMB, no QuickConnect |
| Dropbox/OneDrive/Box | later | content hashes | — | Dropbox production approval at 50 users |

Quorum: S2 = 1 verified; "fully replicated" = all. The service never reaches a NAS. Server-side Drive mirroring is a phase-4 option for "phone was off for a week".

## 10. Privacy and compliance posture

- **Three-class data policy** (gap-10), one `Redactor` pass over Vision word boxes feeding every consumer except the PDF writer. Class A secrets (SSN/ITIN, PANs by Luhn, account and routing numbers by context + ABA mod-10, whole MICR band on check-aspect pages, DL/passport numbers, MRN/member ids) exist in full only inside the archival PDF in the user's own storage; everywhere else as `[SSN ••••1234]`. Identity documents go text-only. Class B reference ids and amounts flow plain; Class C summary/tags only to Spotlight and `indexableText`. Every identifier field becomes `*_last4`; `micr_routing` and full `account_number` are removed. A CI canary feeds synthetic secrets and asserts they appear in no request, index, sidecar, filename or log.
- **Anthropic posture:** managed tier = own org, ZDR on Haiku/Sonnet 5.5 (not Covered Models), inline Messages only, Batches/Files forbidden by lint, consent copy includes the 2-year trust-and-safety carve-out; a HIPAA-ready second org only if a provider tier is sold. BYO tier = device-direct to `api.anthropic.com` under the user's own Commercial Terms, API keys only, Keychain `WhenPasscodeSet`, honest "30-day retention" copy.
- **App Store:** 5.1.2(i) consent screen before the first Claude call, revocable to on-device-only mode; nutrition label = Data Linked to You, App Functionality, no tracking (Photos/Videos, User Content, Financial, Health, Sensitive, Name, Address); `PrivacyInfo.xcprivacy`; `ITSAppUsesNonExemptEncryption = false` by staying on CryptoKit/TLS/Data Protection; in-app account deletion from day one; Google OAuth only as a storage connector (4.8 does not bite); Business category; generic "mail and paperwork" copy.
- **Legal entity:** form the LLC and enrol as an Organization before the App Store build (5.1.1(ix) "should"; avoids a Team-ID-changing transfer and a forced Keychain re-login).
- **Regulatory:** HIPAA not triggered by consumers; FTC HBNR applies once the service hosts data (60-day consumer notice, FTC notice for any breach, penalty floor $53,088/violation, re-check the Sept 2026 adjustment); WA MHMDA has no threshold and a private right of action, so "medical" gets its own consent toggle and the relay is E2EE; EU is a separate workstream. IRS Rev. Proc. 97-22 maps onto the hash manifest, immutable PDF/A, integrity scan and ≥300 ppi; `keep_original` is the legal-risk control.
- **Service hygiene (phase 3+):** DPA with Anthropic, incident runbook, security@ and abuse@, §2258A procedure for share links, external pen test, SOC 2 Type I when B2B asks.

## 11. Phased delivery (solo developer, ~30 productive h/week, AI-assisted)

| Phase | Weeks | Scope | Exit criterion |
|---|---|---|---|
| **0 Measure** | 1-2 | Signposted harness on iPhone 13/15 Pro/16/17 Pro: Vision two-pass latencies, feature-print latency and document-page ROC, F_FULLFSYNC cost, still shot-to-shot, iCloud S2 latency, thermal ramp at 20 ppm; Haiku harness on 200 pages incl. masked pages; `count_tokens` tier check; `kCGPDFContextCreatePDFA` veraPDF spike; `PRAGMA compile_options` | Every row of §3 has p50/p95 per device; §4 thresholds chosen from data |
| **1 Daily driver** | 3-10 | Capture state machine; S1 durability; rectify/enhance; two Vision passes; Redactor; rules + sender-memory label; PDF/A writer + veraPDF CI; split-biased grouper; FTS + on-device vectors; iCloud Drive connector; Worker proxy + Sign in with Apple + App Attest + Haiku incremental conversation; search UI; print/share/zip | Founder scans all household mail for two weeks with zero taps; dedup false-skip = 0 on the calibration set |
| **2 TestFlight** | 11-18 | Google Drive and Synology connectors with verify/rename/audit; relay; outbox reconciliation + nightly audit; dedup and boundary calibration on the 200-page corpus; CI canary; Sonnet escalation + refusal fallback; Create ML classifier; 20-50 testers; published p50/p95 | gap-4 test matrix green; stream-level boundary accuracy reported |
| **3 App Store** | 19-26 | LLC + Organization; StoreKit 2 ($49.99/yr or $5.99/mo, 14-day trial, Family Sharing, 500-page fair-use cap) → entitlements; BYO-key mode; consent, labels, privacy policy, account deletion; ZDR request; Build tier; ASO; support inbox | Approved in Business; "faster than X" backed by side-by-side video |
| **4 Service** | months 7-10 | Email ingest (Postmark inbound with retries, or a Cloudflare Email Worker that persists to R2 synchronously and `forward()`s to a fallback mailbox on failure, never relying on `setReject`); share links and tax/expense packs from R2; cloud index (masked text, Voyage after opt-out); web viewer; server-side Drive mirroring; EventKit reminders + passive daily digest; B2B seats with per-tenant RLS; Scale tier | 5 design-partner firms; AI COGS <10% of net revenue |
| **5 Android + models** | months 10-14 | Kotlin client against the same proxy; Play Billing into the entitlements table; distilled document embedding for sub-5 ms dedup; BERT classifier promotion; UVDoc Core ML dewarp behind a crease detector | Capture/dedup/search parity on one backend |

Half of phases 1-2 goes to the capture loop and durability; AI integration is the smaller risk.

## 12. What the founder must provide

- **Keys and accounts:** Anthropic Console org (Build tier; ZDR ticket), Cloudflare account with the product domain on Cloudflare DNS, Supabase project, Google Cloud project with OAuth consent screen (brand verification needs a homepage and privacy policy on an owned, Search-Console-verified domain), Apple Organization enrolment (LLC, D-U-N-S, domain email), App Store Connect analytics from the existing apps (iOS 18/26/27 and chip mix validate the 26 floor), optional Postmark Pro and Voyage org for phase 4.
- **Devices:** iPhone 13, iPhone 15 Pro, iPhone 16, iPhone 17 Pro; a Synology NAS on DSM 7.2+ with a `synology.me` or Tailscale-certified hostname; a Mac for Create ML and veraPDF CI; a phone stand.
- **Test corpus:** 200 real pages with typed ground truth, each re-photographed 5× handheld and on the stand; 50 same-template sibling pairs across ≥10 senders; 20 few-field-difference pairs; 30 receipts/postcards; 20 blank and show-through backs; 20 duplex letters; 200 multi-page packets with envelopes; 150-300 labelled search queries; mail-stream stats.
- **Decisions:** "Looks like page N" as the instant cue; S1 haptic with the S2 lock following; one PDF per document with hidden per-page copies; relay default-on for subscribers; junk archived forever; full secrets searchable only by opening the PDF; US-only launch.

## 13. Top risks and mitigations

| Risk | Mitigation |
|---|---|
| Every on-device latency is unmeasured on the floor device; A15 may need 600 ms for `.fast` and 6 s for `.accurate` | Phase 0 harness before any budget is promised; the haptic never depends on OCR; OCR backlog shown and drained in `BGProcessingTask`; if the A15 text tier is too slow, dedup is visual-only there with a distilled embedding later |
| A false "already scanned" loses a page | Structural: no signal suppresses capture; merge only on text + two anchors; zero false-skips required on the calibration set; the cue shows a thumbnail |
| Haiku thinking-off TTFT and accuracy on masked handheld pages unknown | Harness arms A-G reading `thinking_tokens`; optimistic UI hides the call; escalation thresholds from data |
| iCloud Drive S2 timing and force-quit behaviour undocumented; full iCloud accounts common | Relay is the managed first hop; fall-through to Drive/NAS; gap-4 tests T9/T11/T12; honest amber "on this phone only" state |
| Boundary errors (literature: ~1 in 8 packets) | Split bias; Claude merge proposals ≥0.8; every page stays findable; corrections are manifest edits with idempotent update-in-place |
| Masking recall on OCR confusions, handwriting, split numbers | Mask by word box, normalise first, treat any 9-digit run near TIN/EIN/SSN as Class A, measure on 200 real pages before advertising |
| Thermal throttling in long sessions with torch | §4 policy; torch capped; measure pages-until-`serious` on A15 |
| Apple ships native auto-advance "scan and understand" | Differentiation is grouping, dedup, verified multi-destination durability, cross-year search and export packs, which Apple does not ship |
| Model price and behaviour drift (Haiku 10× cheaper in a year; Sonnet cache-read halved) | Price on outcome; frozen contract per app version; schema/prompt versions in every sidecar for re-index |
| Solo-developer scope; 14 months is optimistic | Phases 1-3 are the product; 4-5 are revenue-gated; every phase ends with a usable app |

## 14. Where I deliberately disagree with the research

1. **No backend in v1 (privacy.md, business.md, architecture.md).** A 300-line proxy plus Sign in with Apple and App Attest in phase 1 keeps the key out of the binary, keeps caching warm across users, makes the schema version a server fact and avoids the Team-ID and account-deletion retrofit. BYO key survives as device-direct advanced mode.
2. **Auto-skip when all tiers agree (dedup.md), hash-gated capture (capture.md), "warn only" pHash (architecture.md).** Replaced by one rule: track continuity gates re-firing; nothing suppresses a capture; merge is asynchronous and text+anchor based. gap-2 shows sibling statements inside the same-page band for every image hash.
3. **CloudKit `CKAsset` first hop and 48 MP default (apple.md).** Double quota, invisible to Files, keychain-reset loss; 48 MP forfeits ZSL and takes seconds. 12 MP plus a framing gate; 48 MP only in stand mode.
4. **Junk purge after 30 days (mail.md).** Every page is archived forever; junk is tagged `discardable`, hidden from default results, and skips the Claude call once the classifier is confident.
5. **One-tap merge/split as a dependency (mail.md).** The automatic path never needs a tap; taps are telemetry; re-understanding after a merge is one cached call (~$0.001-0.002).
6. **Upload original then re-upload an enriched version (storage.md rec. 1).** Bytes are immutable at first commit; labels are metadata operations; classification travels in sidecar, filename and destination metadata.
7. **Synology fingerprint prompt (storage.md) and SMB over URLSession (apple.md).** ATS cannot be loosened per host; SMB is foreground-only. Trusted certificates or a user-installed CA profile.
8. **Voyage as the default embedding (search.md, claude.md).** On-device embeddings through phase 3; Voyage only in the phase-4 cloud index on masked text after the training opt-out, with the service holding the key.
9. **Mistral OCR 4 / PaddleOCR-VL fallback in v1 (ocr.md).** Out of scope until a measured Vision CER justifies it; Sonnet escalation plus diff-style corrections cover hard pages, and Boros et al. (8 benchmarks, not 7) warns against blanket LLM re-transcription of near-clean text.
10. **End-of-session K=5 boundary pass (dedup.md).** Boundary F1 falls monotonically with K; pairwise verdicts are folded into the incremental call.
11. **Foundation Models as the instant label (apple.md, architecture.md).** Unavailable on the floor device, text-only on iOS 26, guardrails always on for guided generation; rules + sender memory + Create ML are primary.
12. **Second backend developer and `setReject`-driven retries (ingest.md).** `setReject` is a permanent bounce; use Postmark retries or persist-then-forward; one developer, phase 4.
13. **competitors.md's gap framing and claude.md's API details.** Genius Scan and Adobe Scan already auto-capture in batch; the defensible gap is grouping, dedup, understanding and verified routing. Thinking tokens are reported in `usage.output_tokens_details.thinking_tokens`, and Sonnet 5.5 cache reads cost $0.10/MTok; the harness and cost model use both.
