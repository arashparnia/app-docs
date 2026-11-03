# End-to-end architecture and latency engineering for a zero-interaction document scanner

Research date: 2026-11-03. Method note: the shared web-search budget for this run was exhausted before this dimension started, so every finding below comes from direct fetches of primary sources (Apple developer docs/JSON, Anthropic platform docs, vendor pricing pages, papers, GitHub READMEs). Where a primary source gave no number, the report says "unknown" rather than estimating. All latency *targets* in section 2b are engineering budgets to be validated by measurement, not measured results, unless a source is cited.

---

## 1. Executive summary

1. Go native Swift/SwiftUI on iOS 18+ (iOS 26 for the best on-device stack). Nothing cross-platform gives a solo developer a faster camera-to-ML path than AVFoundation + Vision + Core ML, and the founder already ships this stack.
2. The product's speed comes from a strict rule: the capture loop (camera, document detection, stability, dedup, local durable write) runs 100% on-device and never waits on the network. Cloud understanding is an asynchronous enrichment stage.
3. Apple's Vision framework provides every on-device primitive needed: `DetectDocumentSegmentationRequest` (iOS 18), `RecognizeTextRequest` fast/accurate (iOS 18), `RecognizeDocumentsRequest` with tables/lists/paragraphs in 26 languages (iOS 26), `DetectLensSmudgeRequest` (iOS 26, A14+).
4. Apple Foundation Models (iOS 26, ~3B params, 4,096-token context, image attachments, `@Generable` guided generation) is the right on-device "instant guess" classifier; Claude Haiku 5.5 ($0.10/$0.50 per MTok, "Fastest" in Anthropic's lineup, structured outputs, 512-token cache minimum) is the cloud "refined truth".
5. Per-page cloud understanding costs roughly $0.0003-0.0006 at Haiku 5.5 prices; at 100k users AI cost (~$7-8k/month) dwarfs backend hosting (<$1k/month). A BYO-key mode removes the AI cost entirely for the founder's own use.
6. Durability is a local-first contract: "captured" is announced only after an atomic local write plus a hash record; uploads use background `URLSession` in a separate system process; no page is deleted locally until every chosen destination confirms.
7. Dedup is an on-device 64-bit perceptual hash (Hamming distance ≤5 = same page) refined later by OCR-text similarity, so "already scanned" fires inside the capture loop in milliseconds.
8. Recommended service backend: Cloudflare Workers + Queues + R2 (free egress) as the key-holding proxy and staging layer, Supabase (Postgres + Auth with native Sign in with Apple) for accounts and search index; total fixed cost ~$30/month at 1k users.
9. Independent third-party latency data for Haiku 5.5 is currently unusable (Artificial Analysis shows a 333 s TTFT that is clearly a data error), so the first engineering task is a measurement harness that records per-stage timings with `OSSignposter`.
10. Competitor pages (Scanner Pro, Adobe Scan, Genius Scan) make no quantitative speed claims; the bar to beat is therefore defined by our own targets: document lock <150 ms, capture decision <300 ms after stability, on-device label <1 s, cloud-refined metadata <4 s, all without the user stopping.

---

## 2. Findings

### 2a. Native iOS vs cross-platform for a camera-heavy, latency-critical app

| Stack | Camera/ML path | Evidence | Verdict for this project |
|---|---|---|---|
| Native Swift (AVFoundation + Vision + Core ML + Metal) | Direct `CVPixelBuffer` from `AVCaptureVideoDataOutput`; Vision requests accept `CVPixelBuffer`/`CMSampleBuffer` with zero copies. Apple TN3121 warns BGRA buffers cost ~2.6x the memory of native `420v` and require conversion; Vision accepts native YUV directly ([TN3121](https://developer.apple.com/documentation/technotes/tn3121-selecting-a-pixel-format-for-an-avcapturevideodataoutput), [AVCaptureVideoDataOutput](https://developer.apple.com/documentation/avfoundation/avcapturevideodataoutput)). | Only path to Foundation Models, `RecognizeDocumentsRequest`, `DetectLensSmudgeRequest` and background `URLSession` without bridging. Founder already ships this. **Recommended.** |
| React Native (VisionCamera) | Frames delivered to a JS worklet runtime ("Frame Output" in the current docs); docs state frames are GPU buffers at full rate and that if the small buffer pool fills "the pipeline stalls and subsequent frames will be dropped"; you must `frame.dispose()`. ML still needs native plugins (OpenCV/LiteRT examples). No latency numbers published ([VisionCamera frame processors](https://visioncamera.margelo.com/docs/guides/frame-processors)). | Adds a JS runtime, a worklet bridge and a native plugin layer between camera and Vision; every Apple API above still has to be wrapped natively. Net maintenance burden is higher for one person. |
| Flutter (`camera` plugin) | Supports "streaming image buffers to Dart" (iOS 13+); page documents no latency figures and lists CameraX device-specific limitations on Android ([pub.dev camera](https://pub.dev/packages/camera)). | Image stream copies to Dart; no access to Vision/Foundation Models without platform channels. Not recommended for this app. |
| Kotlin Multiplatform | Shares business logic only; camera UI is still per-platform (no primary-source performance data fetched). | Could share the pipeline *model* later for Android; irrelevant for the iOS-first MVP. |

Android equivalents exist when the time comes: ML Kit Document Scanner (on-device, auto-capture, edge detection, Play-services-delivered models) ([ML Kit doc scanner](https://developers.google.com/ml-kit/vision/doc-scanner)) and the Gemini Nano Prompt API (multimodal image+text, typed structured output, beta, no SLA) ([Gemini Nano](https://developer.android.com/ai/gemini-nano), [Prompt API](https://developers.google.com/ml-kit/genai/prompt/android)).

### 2b. Stage-by-stage latency budget

Measured facts first, then the budget.

**Measured / vendor-stated numbers**
- Apple on-device foundation model (2024 generation): TTFT "about 0.6 millisecond per prompt token" and 30 tokens/s on iPhone 15 Pro, before token speculation ([Apple ML, 2024](https://machinelearning.apple.com/research/introducing-apple-foundation-models)). The 2025 model is ~3B params, 2-bit decoder weights, with KV-cache sharing "significantly improving the time-to-first-token"; no absolute numbers published ([Apple ML, 2025](https://machinelearning.apple.com/research/apple-foundation-models-2025-updates)). Flag: the 0.6 ms/token figure is from 2024 hardware/model and may be stale.
- Claude Haiku 5.5: "Fastest" comparative latency in Anthropic's lineup; released 2026-10-07; `effort: low` is "the cheapest and fastest level"; streaming recommended ([models overview](https://platform.claude.com/docs/en/about-claude/models/overview), [reduce latency](https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency)). Anthropic's announcement cites customer-reported "about half the latency of Haiku 4.5" (Box) but publishes no tokens/s ([announcement](https://www.anthropic.com/claude-haiku-5-5)).
- Artificial Analysis reports Haiku 5.5 output speed 235 tok/s but a TTFT of 333.74 s, and Sonnet 5.5 at 138.7 tok/s with TTFT 456 s; both TTFT values are obviously corrupted and must not be used ([AA Haiku 5.5](https://artificialanalysis.ai/models/claude-haiku-5-5), [AA Sonnet 5.5](https://artificialanalysis.ai/models/claude-sonnet-5-5)). **Haiku 5.5 TTFT with an image: unknown; measure it.**
- Image token cost: `⌈w/28⌉ × ⌈h/28⌉` visual tokens; Claude 4.7+ models (incl. Haiku 5.5) use the high-resolution tier (max long edge 2,576 px, max 4,784 visual tokens). A 1092x1092 page is 1,521 tokens; 2000x1500 is 3,888 tokens ([vision docs](https://platform.claude.com/docs/en/build-with-claude/vision)). Anthropic explicitly advises: "To minimize latency ... prefer resizing images before uploading them."
- Structured outputs: first use of a schema adds grammar-compilation latency; compiled grammars are cached 24 h from last use ([structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)). Warm the schema at app launch.
- Apple Vision OCR latency on current iPhones: no primary source publishes numbers (unknown; measure both `.fast` and `.accurate`).

**Budget (targets, to validate on iPhone 15 Pro and newer)**

| Stage | Where | Target | What the user sees |
|---|---|---|---|
| Frame -> document quad | `DetectDocumentSegmentationRequest` on every 2nd-3rd preview frame (YUV `420v`, downscaled) | <40 ms/frame; quad overlay <150 ms after page enters view | Green quad snaps to page |
| Stable -> capture decision | Quad corners stable (<1% drift) for N frames + sharpness (Laplacian variance on luma plane) + `DetectLensSmudgeRequest` on the candidate (iOS 26, A14+) | 250-300 ms of stability, then `AVCapturePhotoOutput` full-res capture | Shutter tick + haptic; page card appears instantly |
| Capture -> corrected preview | Perspective warp (Core Image/Metal) + dedup pHash | <120 ms | Card flips to corrected thumbnail |
| Dedup verdict | 64-bit pHash vs local index (Hamming ≤5) | <5 ms | "Already scanned" toast within the same frame budget |
| Durable local write | Atomic write of corrected JPEG/HEIC + sidecar JSON + hash row (SQLite/SwiftData) | <50 ms | Card shows the "captured" lock icon; paper can be discarded |
| On-device OCR | `RecognizeTextRequest .fast` immediately; `RecognizeDocumentsRequest` (accurate, tables/lists) in background | fast: target <300 ms; accurate: target <1.5 s (unknown; measure) | Searchable text appears; nothing blocks |
| On-device classification | Foundation Models `@Generable` enum over OCR snippet + image attachment (iOS 26) or Create ML classifier (iOS 17+) | <800 ms (3B model; ~2k prompt tokens at 0.6 ms/token was ~1.2 s on 2024 hardware, so keep prompt <1k tokens) | Provisional label ("Invoice?", "Tax form?") in italics |
| Cloud understanding | Haiku 5.5, `effort: low`, structured output, streaming, image resized to ~1,100 px long edge + OCR text | TTFT unknown; total target <4 s p50 | Label turns solid, entities/tags fill in; summary streams |
| PDF render | Image + invisible text layer (from `RecognizeDocumentsRequest` lines) via Core Graphics/PDFKit | <200 ms/page, background | Nothing; done before upload |
| Upload | Background `URLSession` to each destination (and R2 staging if cloud search is on) | Network-bound; never on UI path | Per-document sync checkmarks |

The perceived-instant rule: every row above the "Durable local write" line must complete before the user can plausibly move to the next page (~1 s). Everything below is progressive refinement rendered into an already-visible card (optimistic UI), so the user is never gated.

### 2c. Concurrency design

- Swift 6 actors give one serial executor per actor instance, reentrant at `await` points, with a runtime queue that "uses a lighter-weight queue than Dispatch" and considers priority ([SE-0306](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0306-actors.md)). Use one actor per pipeline stage (`CaptureActor`, `OCRActor`, `EnrichActor`, `UploadActor`) and keep invariants inside synchronous sections.
- Back-pressure: `AsyncStream` buffering policies `bufferingNewest(n)` / `bufferingOldest(n)` / `unbounded`; a 0-size buffer drops unless a consumer is waiting ([SE-0314](https://github.com/swiftlang/swift-evolution/blob/main/proposals/0314-async-stream.md)). The preview-frame stream must be `bufferingNewest(1)` so detection always sees the latest frame; the enrichment stream must be `unbounded` backed by the on-disk queue, not memory.
- Camera: set `alwaysDiscardsLateVideoFrames = true` on `AVCaptureVideoDataOutput` and use a dedicated serial queue for the delegate ([AVCaptureVideoDataOutput](https://developer.apple.com/documentation/avfoundation/avcapturevideodataoutput)); choose a native YUV format per TN3121 and run Vision on the luma plane where possible.
- Batching vs per-page Claude calls: per-page calls win for latency (first result in TTFT, not TTFT × pages). Batch when (a) a multi-page document is detected (same pHash lineage/sequence within seconds) so one call sees all pages (API allows up to 600 images/request, but >20 images triggers a stricter 3,000 px per-image limit), or (b) the user is offline and a backlog forms; then the Message Batches API at 50% discount with "most batches finishing in less than 1 hour" is appropriate ([batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing)).
- Streaming: use SSE streaming with structured output so the label/entities arrive as soon as they are generated; keep `max_tokens` small (~400) for the classification call and run the summary as a second, lower-priority call.
- Prompt caching: put the static system prompt (schema description, taxonomy) under a 1-hour `cache_control`; Haiku 5.5's minimum cacheable prefix is 512 tokens; cache reads are $0.01/MTok and do not count toward ITPM rate limits ([prompt caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching), [rate limits](https://platform.claude.com/docs/en/api/rate-limits)).
- Rate headroom: Haiku 5.5 Start tier is 4,000 RPM / 2M ITPM / 400k OTPM; Scale tier 13,000 RPM / 10M ITPM ([rate limits](https://platform.claude.com/docs/en/api/rate-limits)). At ~2.5k input tokens/page, 2M ITPM is ~800 pages/minute on the smallest paid tier; fine for launch, and a known ceiling for the service phase.

### 2d. Backend options for the service phase

Pricing fetched 2026-11-03 from vendor pages:

| Component | Option | Price facts |
|---|---|---|
| Key-holding proxy / API | Cloudflare Workers Paid | $5/mo min, 10M requests incl., then $0.30/M; 30M CPU-ms incl., $0.02/M after; no egress charge ([Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)) |
| | Vercel Pro | $20/mo, function invocations from $0.60/M, 1 TB transfer incl. then $0.15/GB ([Vercel](https://vercel.com/pricing)) |
| | AWS Lambda | $0.20/M requests (event fns), $0.0000166667/GB-s x86, 1M req + 400k GB-s free ([Lambda](https://aws.amazon.com/lambda/pricing/)) |
| | Fly.io | shared-cpu-1x 256 MB $2.19/mo; egress $0.02/GB NA/EU; no free tier ([Fly](https://docs.fly.io/about/pricing)) |
| | Supabase Edge Functions | 2M invocations incl. on Pro, $2/M after ([Supabase](https://supabase.com/pricing)) |
| Queue | Cloudflare Queues | 1M ops/mo incl., $0.40/M after; ~3 ops per message ([Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/)) |
| Object staging | Cloudflare R2 | $0.015/GB-mo, Class A $4.50/M, Class B $0.36/M, **egress free**, 10 GB free ([R2](https://developers.cloudflare.com/r2/pricing/)) |
| DB + Auth | Supabase Pro | $25/mo: 8 GB DB, 100 GB storage, 100k MAU, 250 GB egress; Team $599 ([Supabase](https://supabase.com/pricing)); native Sign in with Apple via `signInWithIdToken` ([Supabase Apple](https://supabase.com/docs/guides/auth/social-login/auth-apple)) |
| DB alt | Turso | Developer $4.99/mo (9 GB, 2.5B row reads) ([Turso](https://turso.tech/pricing)) |
| Auth alt | Clerk | 50k MRU free; Pro $25/mo ([Clerk](https://clerk.com/pricing)) |
| Auth rule | App Store 4.8 | If any third-party/social login is offered, an equivalent privacy-preserving option (Sign in with Apple qualifies) is required; not required if only your own account system is used ([App Store guidelines](https://developer.apple.com/app-store/review/guidelines/)) |

**Rough monthly cost model** (assumption: 150 pages/user/month, each page ~2.5k input tokens of which ~600 cached, ~300 output tokens; Haiku 5.5 at $0.10/$0.50; staging objects ~1 MB kept 7 days):

| Users | Claude (AI) | Proxy + queue | Staging (R2) | DB/Auth | Total (approx.) |
|---|---|---|---|---|---|
| 1k (150k pages) | ~$55 | $5 | ~$0 (free tier) | $25 | **~$85** |
| 10k (1.5M pages) | ~$550 | ~$6 | ~$5 | $25-75 | **~$650** |
| 100k (15M pages) | ~$5,500 | ~$15 | ~$55 | $599 (Team) + compute | **~$6.5-7k** |

AI cost dominates at every scale; hosting is noise. The Batch API halves AI cost for anything the user is not waiting on (re-indexing, summaries, backfills). A BYO-key tier (founder's existing Keychain pattern) shifts AI cost to the user entirely.

### 2e. On-device model strategy

| Option | Availability | Facts | Role |
|---|---|---|---|
| Apple Foundation Models | iOS 26+, Apple Intelligence devices (iPhone 15 Pro/16/Air and later; iPad A17 Pro/M1+; Mac M1+) ([Apple support](https://support.apple.com/en-us/121115)) | ~3B params; 4,096-token context per session (`SystemLanguageModel.contextSize`); `@Generable` guided generation with constrained decoding; image `Attachment` from `CVPixelBuffer`/`CGImage`, framework handles scaling; built-in `OCRTool`/`BarcodeReaderTool`; `.contentTagging` use case; `prewarm()` ([Foundation Models](https://developer.apple.com/documentation/foundationmodels), [context window](https://developer.apple.com/documentation/foundationmodels/managing-the-context-window), [multimodal](https://developer.apple.com/documentation/foundationmodels/analyzing-images-with-multimodal-prompting)) | Instant provisional label + a few entities (date, sender, amount). Keep prompts under ~1k tokens; use `greedy` sampling for classification. |
| Create ML image/text classifier | iOS 17+ (Image Feature Print V2) ([Create ML](https://developer.apple.com/documentation/createml/creating-an-image-classifier-model)) | Transfer learning; min 10 images/class, ≥299 px recommended; trainable from Claude-labeled scans (distillation) | Fallback classifier for non-Apple-Intelligence devices (iPhone 12-15 non-Pro); a text classifier over OCR output is likely more robust than an image classifier for document types. |
| FastVLM (Apple) via MLX | Research release; 0.5B/1.5B/7B; iOS demo on iPhone 16 Pro ([ml-fastvlm](https://github.com/apple/ml-fastvlm), [paper](https://arxiv.org/abs/2412.13303)) | 85x faster TTFT than LLaVA-OneVision-0.5B, 5.2x faster than SmolVLM; absolute ms not published in text; model license separate | Phase 3 experiment for devices without Apple Intelligence; app size and thermal cost unknown. |
| SmolVLM2 (HF) via MLX Swift | 256M/500M/2.2B; iPhone demo app with 500M model; SmolVLM 2B DocVQA 81.6 ([SmolVLM](https://huggingface.co/blog/smolvlm), [SmolVLM2](https://huggingface.co/blog/smolvlm2)) | No latency/memory numbers for phone | Same as above; benchmark against FastVLM. |
| Gemini Nano (Android) | AICore devices; Prompt API multimodal + structured output, beta ([Gemini Nano](https://developer.android.com/ai/gemini-nano)) | No SLA; device list not on page | Android analogue of Foundation Models when that phase comes. |

Expected accuracy vs cloud: no primary source gives document-classification accuracy for the Apple on-device model; Anthropic reports Haiku 5.5 at 46.4% on Chartography vs Sonnet 5.5 61.6% and a customer-reported 0.84 "Ask in Document" score vs 0.76 for Haiku 4.5 ([announcement](https://www.anthropic.com/claude-haiku-5-5)). Treat the on-device label as a guess (show it as provisional) and the Claude label as truth; log disagreements to build the distillation set.

### 2f. What competitors achieve, and targets that beat them

Fetched competitor pages publish no per-page timing: Scanner Pro describes OCR and multi-page but no auto-capture or speed metric ([Readdle](https://readdle.com/scannerpro)); Adobe Scan claims "automatic boundary detection" and OCR "instantly" with no numbers ([Adobe](https://www.adobe.com/acrobat/mobile/scanner-app.html)); Genius Scan claims "batch scanning" and automatic detection with no numbers ([Grizzly Labs](https://thegrizzlylabs.com/genius-scan/)); Microsoft Lens page was unavailable (HTTP 503) and geniusscan.com is outside this session's allowed domains. Apple's own `VNDocumentCameraViewController` (iOS 13) captures page-by-page but exposes only `delegate`/`isSupported`, no customization ([VisionKit](https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller)). All of them require a tap, a "save", or a review step per document; none announce duplicates or classify.

Targets that beat them are therefore behavioral, not just numeric: (1) no tap, no save, no review; (2) capture decision within 300 ms of the page being still; (3) a visible, locked "captured" state within 1 s; (4) duplicate warning within the same second; (5) a confident type label within 1 s on-device and refined metadata within ~4 s; (6) sustained 20+ pages/minute handheld without thermal throttling (measure with `MetricKit`/Instruments).

### 2g. Offline and degraded modes

- Everything through the durable local write, fast OCR and on-device label works with no network. The enrichment queue persists on disk and drains when connectivity returns.
- Uploads use `URLSessionConfiguration.background(withIdentifier:)`: the system performs transfers "in a separate process" and they "can continue even when the app is suspended or terminated"; a force-quit from the app switcher cancels them and the app must be relaunched ([URLSession background](https://developer.apple.com/documentation/foundation/urlsessionconfiguration/background(withidentifier:))). Surface this to the user ("keep the app installed; uploads resume on next launch").
- Long backlogs (hundreds of pages after a trip) go through `BGProcessingTaskRequest` with `requiresNetworkConnectivity = true` ([BGProcessingTaskRequest](https://developer.apple.com/documentation/backgroundtasks/bgprocessingtaskrequest)) and, when latency does not matter, through the Message Batches API (50% off; results within 24 h, 29-day retention) ([batch processing](https://platform.claude.com/docs/en/build-with-claude/batch-processing)).
- Claude refusals: Haiku 5.5 can return `stop_reason: "refusal"` with no server-side fallback ([what's new](https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5)); keep the on-device label and mark the document "needs review" rather than dropping it.

### 2h. Privacy-safe per-stage timing telemetry

- Instrument each stage with `OSSignposter.beginInterval/endInterval` (iOS 15+) so Instruments shows the pipeline on a timeline ([OSSignposter](https://developer.apple.com/documentation/os/ossignposter)).
- Aggregate on-device into histograms (p50/p95 per stage, device model, OS, thermal state) and send only those; never send image bytes, OCR text or hashes. MetricKit delivers daily aggregated payloads; note that `MXMetricManager`/`MXSignpostMetric` are deprecated from iOS 27.2 in favor of `MetricManager`/`SignpostIntervalMetric` ([MXSignpostMetric](https://developer.apple.com/documentation/metrickit/mxsignpostmetric), [MXMetricManager](https://developer.apple.com/documentation/metrickit/mxmetricmanager)). Plan the telemetry layer on the new API.
- Cloud side: record Anthropic `usage` fields and TTFT per request in the proxy keyed by an anonymous install ID; store no document content.

### 2i. Testing: datasets and golden sets

| Dataset | Content | Use |
|---|---|---|
| RVL-CDIP | 400k grayscale document images, 16 classes (letter, memo, invoice, form, budget, ...), ≤1,000 px; license inherits from the Legacy Tobacco library ([RVL-CDIP](https://adamharley.com/rvl-cdip/)) | Classifier pre-training/eval (old scans, US-centric). |
| DocLayNet | 80,863 pages, 11 layout classes, COCO boxes at 1025x1025, six document categories ([DocLayNet](https://github.com/DS4SD/DocLayNet)) | Layout/table extraction regression for `RecognizeDocumentsRequest`. |
| CORD | Indonesian receipts, 1,000 released images, 42 field labels, CC BY 4.0 ([CORD](https://github.com/clovaai/cord)) | Receipt field-extraction golden set. |
| FUNSD | 199 forms, 31,485 words, 9,707 entities ([FUNSD](https://guillaumejaume.github.io/FUNSD/)) | Form key/value extraction. |

Synthetic set: generate HTML/PDF documents per target type (US/EU tax forms, utility bills, insurance EOBs, medical letters) with known ground truth, print, photograph under 5 lighting/angle conditions on 3 iPhone models, and keep a 300-page handheld "golden run" that is replayed through the pipeline on every build. Score: classification accuracy, entity F1, dedup false-positive rate (must be ~0: a false "already scanned" loses a document), and per-stage p95 latency.

---

## 3. Options compared

| Decision | Option A | Option B | Option C | Pick |
|---|---|---|---|---|
| App stack | Native Swift/SwiftUI | React Native + VisionCamera | Flutter | **A** (direct Vision/FM access, lowest latency, founder's expertise) |
| Capture UI | Custom AVFoundation + Vision | `VNDocumentCameraViewController` | `DataScannerViewController` | **A** (B/C are uncustomizable, per-page tap, no dedup/classification) |
| Instant label | Foundation Models `@Generable` | Create ML classifier | FastVLM/SmolVLM via MLX | **A on iOS 26 AI devices, B as fallback, C as experiment** |
| Cloud model | Haiku 5.5 `effort: low` | Sonnet 5.5 | Opus 5.5 | **A** for every page; **B** only for low-confidence/complex pages (routing) |
| Call shape | Per page, streamed, structured output | Per document batched | Message Batches API | **A** live; **B** for detected multi-page docs; **C** for backlog/backfill |
| Proxy | Cloudflare Workers + Queues | Lambda | Fly.io | **A** (lowest fixed cost, free egress, queue built in) |
| Staging store | R2 | S3 | None (device uploads directly to Drive/NAS/iCloud) | **C by default, A only when cloud search/sharing is enabled** |
| DB/Auth | Supabase | Turso + Clerk | CloudKit only | **A** for service; CloudKit stays for per-user private sync |
| Dedup | pHash in capture loop + OCR similarity later | OCR-only | Cloud embedding | **A** |

---

## 4. Recommendation for this project

**Architecture (text diagram)**

```
 iPhone (Swift 6, iOS 18+, best on iOS 26 + Apple Intelligence)
 ┌──────────────────────────────────────────────────────────────────────┐
 │ AVCaptureSession (420v) ─► AsyncStream(bufferingNewest:1)            │
 │   └► CaptureActor: DetectDocumentSegmentation ▸ stability ▸ sharpness│
 │        ▸ LensSmudge ▸ AVCapturePhotoOutput ▸ warp ▸ pHash dedup      │
 │        ▸ ATOMIC LOCAL WRITE (image + sidecar + SQLite row)  ══► "captured" (haptic)
 │   └► OCRActor: RecognizeText(.fast) ─► RecognizeDocuments(accurate)  │
 │   └► LocalLabelActor: FoundationModels @Generable (or Create ML)     │
 │   └► PDFActor: image + text layer ─► PDF/A-ish file                  │
 │   └► EnrichActor: disk-backed queue ─► proxy (stream, structured)    │
 │   └► UploadActor: background URLSession ─► Drive / Synology / iCloud │
 │   └► Search: SQLite FTS5 + on-device embeddings; CloudKit sync       │
 └──────────────────────────────────────────────────────────────────────┘
                     │ HTTPS (Sign in with Apple JWT)
 Cloudflare Worker (proxy: auth, per-user quota, Anthropic key, prompt cache)
   ├─ Claude Haiku 5.5: effort low, structured output, streaming  (per page)
   ├─ Claude Sonnet 5.5: only when Haiku confidence < threshold   (routing)
   ├─ Cloudflare Queues ─► Message Batches API (backlog, backfill, 50% off)
   ├─ R2 (optional staging, free egress) ─► user destinations / share packs
   └─ Supabase Postgres: accounts, usage, cloud search index (text only)
```

**Stack with justification**
- Swift 6 strict concurrency, SwiftUI, AVFoundation, Vision, Core Image/Metal for warp, SQLite (FTS5) or SwiftData for the local catalog, CloudKit for private cross-device sync. Reason: zero-copy camera-to-Vision path and the only access to Apple's on-device models.
- Claude Haiku 5.5 as primary AI (price, "Fastest", structured outputs, 512-token caching, 1M context) with Sonnet 5.5 as the escalation model. Keep images at ~1,100 px long edge (~1,500 visual tokens) and pass OCR text alongside; this keeps cost ~$0.0004/page and minimizes TTFT. Do not send 4K photos (4,784 tokens, ~3x cost, slower).
- Cloudflare Workers/Queues/R2 + Supabase for the service. Reason: ~$30/month fixed, free egress for share packs and zips, native Sign in with Apple in Supabase.
- Phase plan: (1) single-user app with BYO key via Keychain (founder's existing pattern), full capture/dedup/OCR/PDF/upload; (2) proxy + accounts + cloud search; (3) distillation (Claude-labeled pages -> Create ML / adapter) and FastVLM experiments for sub-second cloud-free labels on all devices.

---

## 5. Risks and unknowns

- **Haiku 5.5 TTFT with an image is unknown.** Third-party data is corrupted; Anthropic gives relative claims only. If measured p50 exceeds ~3 s, the UX still works (optimistic UI) but the "refined within 4 s" target moves.
- **Apple Vision OCR and `RecognizeDocumentsRequest` latency unknown** on current hardware; accurate-mode OCR on a full page may exceed 1.5 s on older devices.
- **Foundation Models availability** is limited to Apple Intelligence devices and iOS 26+; the 4,096-token context forces short prompts; the 0.6 ms/token figure is from the 2024 model and may be stale; image-attachment support's exact minimum OS version is not stated on the fetched page.
- **Dedup false positives** are catastrophic for the durability promise (a real page dismissed as a duplicate). Mitigate: pHash only *warns*; the page is still stored; OCR-text similarity confirms before any merge.
- **Force-quit cancels background uploads** (Apple docs); the app must reconcile on relaunch and never mark a destination "synced" without a server-side confirmation.
- **Rate limits and refusals**: Start tier 2M ITPM caps ~800 pages/min; Haiku 5.5 has no server-side refusal fallback.
- **MetricKit API deprecation** (iOS 27.2) means telemetry code written today against `MXMetricManager` will need migration.
- **Tokenizer change**: Haiku 5.5 counts ~30% more tokens than Haiku 4.5 for the same text; budgets must be re-measured with `count_tokens`.
- **Competitor speed is unmeasured** by any public source fetched; "faster than anything" must be substantiated by our own side-by-side video benchmarks.

---

## 6. Open questions for the founder

1. Minimum iOS version: iOS 18 (Vision document segmentation, no Foundation Models) or iOS 26 (full stack)? What share of your current users are on Apple Intelligence devices?
2. Is a 1,100 px long-edge JPEG acceptable for the cloud call, with the full-resolution image kept only for the archival PDF? (Cost/latency vs. fidelity for dense small print.)
3. Should the service phase ever store document images server-side (enables share packs, cloud search, cross-device) or stay strictly device-to-destination with text-only indexes?
4. Target pages per user per month for pricing (the cost model assumed 150)?
5. Is routing low-confidence pages to Sonnet 5.5 acceptable, or must every page use one model for predictable cost?
6. Android timeline: does it affect choosing SQLite over SwiftData now so the catalog schema can be shared later?
7. Do you want BYO-key to remain a first-class mode in the App Store product (affects proxy design and App Review)?

---

## 7. Sources

- Anthropic pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Anthropic models overview: https://platform.claude.com/docs/en/about-claude/models/overview
- Claude Haiku 5.5 overview: https://platform.claude.com/docs/en/models/haiku-5-5/overview
- What's new in Haiku 5.5: https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5
- Haiku 5.5 announcement: https://www.anthropic.com/claude-haiku-5-5
- Claude vision (image limits, token formula): https://platform.claude.com/docs/en/build-with-claude/vision
- Structured outputs: https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Prompt caching: https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- Rate limits: https://platform.claude.com/docs/en/api/rate-limits
- Batch processing: https://platform.claude.com/docs/en/build-with-claude/batch-processing
- PDF support: https://platform.claude.com/docs/en/build-with-claude/pdf-support
- Reducing latency: https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency
- Artificial Analysis Haiku 5.5 (TTFT data flagged as erroneous): https://artificialanalysis.ai/models/claude-haiku-5-5 and https://artificialanalysis.ai/models/claude-haiku-5-5/providers
- Artificial Analysis Sonnet 5.5: https://artificialanalysis.ai/models/claude-sonnet-5-5
- Apple Foundation Models: https://developer.apple.com/documentation/foundationmodels
- Managing the context window: https://developer.apple.com/documentation/foundationmodels/managing-the-context-window
- Analyzing images with multimodal prompting: https://developer.apple.com/documentation/foundationmodels/analyzing-images-with-multimodal-prompting
- SystemLanguageModel: https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel
- Apple on-device model 2024 (0.6 ms/token, 30 tok/s): https://machinelearning.apple.com/research/introducing-apple-foundation-models
- Apple on-device model 2025 updates: https://machinelearning.apple.com/research/apple-foundation-models-2025-updates
- Apple Intelligence device requirements: https://support.apple.com/en-us/121115
- RecognizeDocumentsRequest: https://developer.apple.com/documentation/vision/recognizedocumentsrequest
- WWDC25 "Read documents using the Vision framework": https://developer.apple.com/videos/play/wwdc2025/272/
- DetectDocumentSegmentationRequest: https://developer.apple.com/documentation/vision/detectdocumentsegmentationrequest
- DetectedDocumentObservation: https://developer.apple.com/documentation/vision/detecteddocumentobservation
- RecognizeTextRequest: https://developer.apple.com/documentation/vision/recognizetextrequest
- WWDC21 "Extract document data using Vision": https://developer.apple.com/videos/play/wwdc2021/10041/
- DetectLensSmudgeRequest: https://developer.apple.com/documentation/vision/detectlenssmudgerequest
- ImageAestheticsScoresObservation: https://developer.apple.com/documentation/vision/imageaestheticsscoresobservation
- VNDocumentCameraViewController: https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller
- VNDocumentCameraScan: https://developer.apple.com/documentation/visionkit/vndocumentcamerascan
- DataScannerViewController: https://developer.apple.com/documentation/visionkit/datascannerviewcontroller
- AVCaptureVideoDataOutput: https://developer.apple.com/documentation/avfoundation/avcapturevideodataoutput
- TN3121 pixel formats: https://developer.apple.com/documentation/technotes/tn3121-selecting-a-pixel-format-for-an-avcapturevideodataoutput
- Create ML image classifier: https://developer.apple.com/documentation/createml/creating-an-image-classifier-model
- FastVLM repo: https://github.com/apple/ml-fastvlm
- FastVLM paper: https://arxiv.org/abs/2412.13303
- FastVLM Apple ML article: https://machinelearning.apple.com/research/fast-vision-language-models
- SmolVLM: https://huggingface.co/blog/smolvlm
- SmolVLM2: https://huggingface.co/blog/smolvlm2
- MLX Swift examples: https://github.com/ml-explore/mlx-swift-examples
- SE-0306 Actors: https://github.com/swiftlang/swift-evolution/blob/main/proposals/0306-actors.md
- SE-0314 AsyncStream: https://github.com/swiftlang/swift-evolution/blob/main/proposals/0314-async-stream.md
- URLSessionConfiguration.background: https://developer.apple.com/documentation/foundation/urlsessionconfiguration/background(withidentifier:)
- BGProcessingTaskRequest: https://developer.apple.com/documentation/backgroundtasks/bgprocessingtaskrequest
- OSSignposter: https://developer.apple.com/documentation/os/ossignposter
- MXSignpostMetric (deprecated iOS 27.2): https://developer.apple.com/documentation/metrickit/mxsignpostmetric
- MXMetricManager: https://developer.apple.com/documentation/metrickit/mxmetricmanager
- pHash/aHash: http://www.hackerfactor.com/blog/index.php?/archives/432-Looks-Like-It.html
- VisionCamera frame processors: https://visioncamera.margelo.com/docs/guides/frame-processors
- Flutter camera plugin: https://pub.dev/packages/camera
- ML Kit document scanner: https://developers.google.com/ml-kit/vision/doc-scanner
- Gemini Nano: https://developer.android.com/ai/gemini-nano
- ML Kit Prompt API: https://developers.google.com/ml-kit/genai/prompt/android
- Cloudflare Workers pricing: https://developers.cloudflare.com/workers/platform/pricing/
- Cloudflare R2 pricing: https://developers.cloudflare.com/r2/pricing/
- Supabase pricing: https://supabase.com/pricing
- Supabase Sign in with Apple: https://supabase.com/docs/guides/auth/social-login/auth-apple
- Fly.io pricing: https://docs.fly.io/about/pricing
- Vercel pricing: https://vercel.com/pricing
- AWS Lambda pricing: https://aws.amazon.com/lambda/pricing/
- Clerk pricing: https://clerk.com/pricing
- Turso pricing: https://turso.tech/pricing
- App Store Review Guidelines 4.8: https://developer.apple.com/app-store/review/guidelines/
- Scanner Pro: https://readdle.com/scannerpro
- Adobe Scan: https://www.adobe.com/acrobat/mobile/scanner-app.html
- Genius Scan (Grizzly Labs): https://thegrizzlylabs.com/genius-scan/
- RVL-CDIP: https://adamharley.com/rvl-cdip/
- DocLayNet: https://github.com/DS4SD/DocLayNet
- CORD: https://github.com/clovaai/cord
- FUNSD: https://guillaumejaume.github.io/FUNSD/
