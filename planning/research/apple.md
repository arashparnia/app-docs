# Apple platform capability matrix for a hands-free document scanner (state as of 2026-11-03)

Scope: iOS/iPadOS APIs that matter for a zero-interaction, speed-first paper digitizer. Note on timing: the brief said "iOS 26 era", but as of today iOS 27 has shipped (iPhone 18 Pro went on sale 2026-09-18 per Wikipedia; Apple's Foundation Models docs now list iOS 27 members). I therefore give min-OS versions for every API and flag the ones that are iOS 27-only. Unless marked "measured", every number below is a vendor statement from Apple's docs or WWDC transcripts. Web search was unavailable for this run (shared per-turn search budget was exhausted), so everything comes from direct fetches of Apple developer documentation JSON, WWDC session pages, Apple product pages, Google developer docs, GitHub and arXiv; third-party benchmarks could not be collected and are marked unknown.

## 1) Executive summary

- Apple ships almost the whole on-device pipeline this app needs: live document detection + mask (`DetectDocumentSegmentationRequest`, iOS 18), structured OCR with tables/lists/data detectors in 26 languages (`RecognizeDocumentsRequest`, iOS 26), blur/smudge gating (`DetectLensSmudgeRequest`, iOS 26, A14+), near-duplicate detection (`GenerateImageFeaturePrintRequest`, iOS 18), and a 3B on-device LLM with constrained JSON output (`Foundation Models`, iOS 26, Apple Intelligence devices only, 4,096-token context).
- The on-device LLM is text-only on iOS 26; image attachments, Vision's `OCRTool`, and the Private Cloud Compute model are iOS 27+. Claude remains the right primary for deep understanding; Apple's model is a good free, offline first-pass classifier.
- Camera: zero shutter lag, responsive capture and deferred photo delivery exist (iOS 17, A12+ / iPhone 11 Pro+), so a continuous "capture-when-sharp" loop at ~2+ photos/s is realistic; 48 MP capture is selectable per format (`supportedMaxPhotoDimensions`, iOS 16).
- Hardware launch surfaces exist (Action button/Control Center/Lock Screen via `LockedCameraCapture` + `CameraCaptureIntent`, iOS 18; Camera Control via `AVCaptureEventInteraction`, iOS 17.2) but the Lock Screen extension is sandboxed with no network.
- Durability: iOS 26's `BGContinuedProcessingTask` lets a user-initiated upload/processing job keep running after backgrounding with system progress UI; pair it with background `URLSession` and CloudKit assets (not subject to the 1 MB record limit).
- Search: Core Spotlight gives on-device lexical + semantic search (`CSUserQuery`, iOS 16/18) and App Intents `IndexedEntity` (iOS 18) exposes items to Siri/Apple Intelligence; for app-internal full text, SwiftData/Core Data have no FTS, so use GRDB + FTS5.
- Recommendation: deployment target iOS 26, custom `AVCaptureSession` (not `VNDocumentCameraViewController`), Vision for everything pre-LLM, Foundation Models for instant on-device classification with Claude for the canonical understanding pass, GRDB/FTS5 + Core Spotlight, CloudKit + user-chosen storage targets, App Attest for backend auth.
- Biggest unknowns: no official latency numbers for Vision document OCR or Foundation Models on A18/A19; adapter training is a per-OS-version commitment; Android parity is feasible but Gemini Nano is foreground-only and device-gated.

## 2) Findings

### 2a) Vision framework

| API | Min OS | What it gives | Notes / source |
|---|---|---|---|
| `RecognizeDocumentsRequest` -> `DocumentObservation` | iOS 26.0 | One observation per image; `document: Container` with `text`, `title?`, `paragraphs`, `lists`, `tables`, `barcodes`; text accessible as transcript, lines, paragraphs, words; tables are 2D cells with row/column ranges; data detectors via DataDetection framework | 26 languages (WWDC25); word-level output not for CJK/Thai; "data detectors" surface as `DataDetectorMatch.match.details` with 10 cases: `calendarEvent`, `emailAddress`, `flightNumber`, `link`, `measurement`, `moneyAmount`, `paymentIdentifier`, `phoneNumber`, `postalAddress`, `shipmentTrackingNumber`. Sources: https://developer.apple.com/documentation/vision/recognizedocumentsrequest , https://developer.apple.com/documentation/vision/documentobservation/container , https://developer.apple.com/documentation/datadetection/datadetector/match/semanticdetails , https://developer.apple.com/videos/play/wwdc2025/272/ |
| `RecognizeTextRequest` | iOS 18.0 (Swift API; `VNRecognizeTextRequest` since iOS 13) | `recognitionLevel` (`.fast`/`.accurate`), `usesLanguageCorrection`, `automaticallyDetectsLanguage`, `recognitionLanguages`, `customWords`, `minimumTextHeightFraction`, revisions | Apple gives no ms numbers; `.fast` is the live-preview path, `.accurate` the archival path. https://developer.apple.com/documentation/vision/recognizetextrequest |
| `DetectDocumentSegmentationRequest` -> `DetectedDocumentObservation` | iOS 18.0 (Swift; VN form since iOS 15) | Four quadrilateral corners + `globalSegmentationMask: PixelBufferObservation` | Use on every preview frame for "page in frame" + perspective crop. https://developer.apple.com/documentation/vision/detectdocumentsegmentationrequest , https://developer.apple.com/documentation/vision/detecteddocumentobservation |
| `DetectLensSmudgeRequest` -> `SmudgeObservation.confidence` (0..1) | iOS 26.0; **A14 Bionic / M1 or later** | Probability the lens is smudged; Apple example threshold 0.9 | Apple warns motion blur/long exposure misclassify; run on stable captures only. https://developer.apple.com/documentation/vision/detectlenssmudgerequest |
| `CalculateImageAestheticsScoresRequest` -> `overallScore`, `isUtility` | iOS 18.0 | `isUtility == true` flags "documents or receipts" style images | Useful as a cheap "this is a document, not a desk" gate. https://developer.apple.com/documentation/vision/calculateimageaestheticsscoresrequest , https://developer.apple.com/documentation/vision/imageaestheticsscoresobservation |
| `GenerateImageFeaturePrintRequest` -> `FeaturePrintObservation.distance(to:)` | iOS 18.0 | Embedding + distance for near-duplicate ("already scanned") checks | Apple publishes no threshold; calibrate on your own pages. https://developer.apple.com/documentation/vision/generateimagefeatureprintrequest , https://developer.apple.com/documentation/vision/featureprintobservation |
| Orientation | n/a | Every `perform(on:orientation:)` takes `CGImagePropertyOrientation`; there is no dedicated "detect text orientation" request. Pair `AVCaptureDevice.RotationCoordinator` (iOS 17) for gravity-level capture with OCR-result geometry (line angles from `RecognizeTextRequest`) to decide page rotation | https://developer.apple.com/documentation/avfoundation/avcapturedevice/rotationcoordinator |

Vision ships 31 request types in iOS 26 (WWDC25 272). All inputs accept `URL`, `Data`, `CGImage`, `CVPixelBuffer`, `CIImage`, `CMSampleBuffer`, so preview frames can be fed directly without copies.

### 2b) VisionKit

| API | Min OS | Control granularity | Verdict for this app |
|---|---|---|---|
| `VNDocumentCameraViewController` | iOS 13.0 | Modal system UI only; returns `VNDocumentCameraScan` (`pageCount`, `imageOfPage(at:)`, `title`); no API for auto-capture tuning, overlays, or embedding | Great quality but kills "zero interaction": it has its own Save/Keep flow. Not recommended as the primary path. https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller |
| `DataScannerViewController` | iOS 16.0; **A12 Bionic+** | `recognizedDataTypes` (`.text(textContentType:languages:)`, `.barcode(symbologies:)`), `qualityLevel` `.fast/.balanced/.accurate`, `recognizesMultipleItems`, `isHighFrameRateTrackingEnabled`, `regionOfInterest`, `recognizedItems` AsyncStream, `capturePhoto() -> UIImage` | Live text/barcode scanning with a system viewfinder; no document-segmentation or page-quality signals, and it owns the camera. Useful as a fallback only. https://developer.apple.com/documentation/visionkit/datascannerviewcontroller , https://developer.apple.com/documentation/visionkit/scanning-data-with-the-camera |
| `ImageAnalyzer` / `ImageAnalysisInteraction` (Live Text) | iOS 16.0 | `analyze(_:configuration:)` on still images; `Configuration` picks text/barcode/visual-lookup; interaction UI is system-provided | Nice for the viewer (select/copy text on archived pages); not a capture tool. https://developer.apple.com/documentation/visionkit/imageanalyzer |

### 2c) Foundation Models framework (on-device LLM)

- Availability: iOS/iPadOS/macOS/visionOS 26.0+; requires an Apple Intelligence-capable device with Apple Intelligence enabled. `SystemLanguageModel.default.availability` reports `.available` or `.unavailable(.deviceNotEligible | .appleIntelligenceNotEnabled | .modelNotReady)`. https://developer.apple.com/documentation/foundationmodels , https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel/availability-swift.enum/unavailablereason
- Eligible devices (Apple's current list): iPhone 15 Pro/Pro Max (A17 Pro) and every iPhone 16/16e/17/17e/Air/18 Pro/Duo; iPad mini (A17 Pro+), iPad Air/Pro (M1+); Macs M1+ plus MacBook Neo (A18 Pro). Storage: up to 14 GB on newer high-end models, up to 8 GB on others. https://www.apple.com/apple-intelligence/ , https://support.apple.com/en-us/121115
- Languages (iOS 27 list): English, Danish, Dutch, French, German, Italian, Norwegian, Portuguese, Spanish, Swedish, Turkish, Vietnamese, Chinese (Simplified/Traditional), Japanese, Korean. Check at runtime with `supportsLocale()` / `supportedLanguages`; unsupported input throws `unsupportedLanguageOrLocale`. All `@Generable` type and property names count as model input and must be in a supported language. https://support.apple.com/en-us/121115 , https://developer.apple.com/documentation/foundationmodels/supporting-languages-and-locales-with-foundation-models
- Context window: **4,096 tokens per session**, covering instructions, prompt, tool schemas/IO, Generable schemas and output; ~3-4 chars/token for Latin scripts, ~1 char/token for CJK. Runtime values: `SystemLanguageModel.contextSize`, `tokenCount(for:)`. Overflow throws `contextSizeExceeded` (iOS 27 naming; `exceededContextWindowSize` on iOS 26). Practical consequence: a full-page OCR transcript (often 2-3k tokens) plus schema fits only if you keep prompts tight; multi-page documents must be chunked. https://developer.apple.com/documentation/foundationmodels/managing-the-context-window
- Guided generation: `@Generable` + `@Guide` produce a compile-time schema and constrained decoding (invalid tokens masked), so an enum of document classes or a struct `{category, issuer, date, amount, tags}` is guaranteed to parse. `DynamicGenerationSchema` for runtime taxonomies. Streaming is property-by-property. `GenerationOptions(sampling: .greedy)` for determinism. https://developer.apple.com/videos/play/wwdc2025/301/
- Tool calling: `Tool` protocol (`name`, `description`, `@Generable Arguments`, `call(arguments:)`); tools can run in parallel; Apple recommends 3-5 tools max because definitions consume context. https://developer.apple.com/documentation/foundationmodels/tool
- Use cases/guardrails: `SystemLanguageModel(useCase: .contentTagging, guardrails:)`; `Guardrails.permissiveContentTransformations` relaxes safety filtering for transformation tasks (relevant for medical/legal mail that default guardrails may refuse). https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel , https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel/guardrails
- Image support: **none on iOS 26**. iOS 27 adds `Attachment` (CGImage, image file URL, `CVPixelBuffer`) with multimodal prompting, Vision's `OCRTool` and `BarcodeReaderTool` (iOS 27, device-only, not Simulator), and `PrivateCloudComputeLanguageModel` (iOS 27, needs the managed entitlement `com.apple.developer.private-cloud-compute`, has `quotaUsage`; Apple's consumer page says server features have daily limits and "expanded access will cost a fee in the future"). https://developer.apple.com/documentation/foundationmodels/attachment , https://developer.apple.com/documentation/vision/ocrtool , https://developer.apple.com/documentation/foundationmodels/privatecloudcomputelanguagemodel , https://developer.apple.com/documentation/foundationmodels/analyzing-images-with-multimodal-prompting
- Model: ~3B parameters, 2-bit QAT weights, 4-bit embeddings, 8-bit KV cache, KV-cache sharing (-37.5% KV memory), 15 languages (2025 report). Only published speed numbers are from the 2024 report on iPhone 15 Pro: ~0.6 ms TTFT per prompt token and ~30 tokens/s generation (stale; the 2025 model and A18/A19 silicon differ). https://machinelearning.apple.com/research/apple-foundation-models-2025-updates , https://machinelearning.apple.com/research/introducing-apple-foundation-models
- Model versions are OS-bound: 26.0-26.3, 26.4, 27.0 are listed as distinct versions; prompts should be re-tested per version. https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel
- Adapter training toolkit: Python 3.11, Apple-silicon Mac with >= 32 GB or Linux GPU; LoRA rank 32; each `.fmadapter` ~160 MB; must be hosted and delivered with Background Assets (not in the bundle); an adapter is compatible with one specific system model version, so you retrain for every OS model update; toolkit 26.0.0 is the last 26-series release and is incompatible with OS 27+; deployment needs the `com.apple.developer.foundation-model-adapter` entitlement requested by the Account Holder; 100-1,000 samples for basic tasks, 5,000+ for complex. Optional draft model for speculative decoding. https://developer.apple.com/apple-intelligence/foundation-models-adapter/

### 2d) Core ML, Create ML, on-device VLMs, silicon

- Create ML (macOS 10.14+, iOS 15+ framework): `MLImageClassifier`, `MLObjectDetector`, `MLTextClassifier`, `MLWordTagger`, `MLGazetteer`; Apple's docs frame training as a Mac activity. A text classifier over OCR output ("tax / medical / insurance / bill / letter") is a sub-millisecond, no-Apple-Intelligence-required alternative to the LLM for the first-pass label. https://developer.apple.com/documentation/createml
- Core ML (iOS 11+): `MLTensor`, `MLState` (stateful models), `MLComputePlan`, `MLComputePolicy`, on-device compile ("Downloading and Compiling a Model on the User's Device"), model encryption. Apple's page now points to "Core AI" for newest inference techniques (unverified beyond the landing page). https://developer.apple.com/documentation/coreml
- FastVLM (Apple, CVPR 2025): 0.5B/1.5B/7B; 85x faster TTFT than LLaVA-OneVision-0.5B at 1152x1152 (paper, hardware unstated); demo runs the 0.5B model on an iPhone 16 Pro GPU; Core ML and MLX checkpoints on Hugging Face (0.5B fp16, 1.5B int8, 7B int4). No published DocVQA/TextVQA per-task numbers or iPhone ms figures. https://machinelearning.apple.com/research/fast-vision-language-models , https://github.com/apple/ml-fastvlm , https://arxiv.org/abs/2412.13303
- MLX Swift examples support VLMs via `mlx-swift-lm`, iOS and macOS; no stated memory requirements or benchmarks. https://github.com/ml-explore/mlx-swift-examples
- Silicon: A19 (iPhone 17/17e) and A19 Pro (Air/17 Pro) are TSMC N3P, 16-core Neural Engine (same NE design as A17/A18, ~35 TOPS per Wikipedia), new "Neural Accelerator" units in each GPU core; 8 GB RAM (A19) / 12 GB (A19 Pro). A20 Pro (iPhone 18 Pro, 2026-09-18; iPhone Duo 2026-10-23) is 2 nm, 7-core GPU with Neural Accelerators, dual 16-core Neural Engine, Apple claims 2x AI performance over A19 Pro; 12 GB RAM reported. These are secondary-source numbers; Apple's spec page confirms "Dual 16-core Neural Engine" and "7-core GPU with Neural Accelerators" for A20 Pro. https://www.apple.com/iphone-18-pro/specs/ , https://en.wikipedia.org/wiki/Apple_A19 , https://en.wikipedia.org/wiki/Apple_A20

### 2e) Camera (AVFoundation / AVKit / LockedCameraCapture)

| Capability | API | Min OS / device | Source |
|---|---|---|---|
| 48 MP stills | `AVCaptureDevice.Format.supportedMaxPhotoDimensions`, `AVCapturePhotoOutput.maxPhotoDimensions`, `AVCapturePhotoSettings.maxPhotoDimensions` | iOS 16.0 | https://developer.apple.com/documentation/avfoundation/avcapturedevice/format/supportedmaxphotodimensions |
| Zero shutter lag | `isZeroShutterLagSupported/Enabled` (ring buffer, on by default when linking iOS 17+ on formats with `isHighestPhotoQualitySupported`; not with flash/manual exposure/bracketing) | iOS 17.0 | https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/iszeroshutterlagsupported , https://developer.apple.com/videos/play/wwdc2023/10105/ |
| Responsive capture (overlapped capture/processing) | `isResponsiveCaptureSupported/Enabled` (requires ZSL on) | iOS 17.0; A12+ | same; WWDC23 demo: ~2 photos/s with ZSL alone, more with responsive capture |
| Fast capture prioritization | `isFastCapturePrioritizationSupported/Enabled` (drops to balanced quality under rapid fire; off by default) | iOS 17.0; A12+ | same |
| Deferred photo delivery | `isAutoDeferredPhotoDeliverySupported/Enabled`; proxy via `didFinishCapturingDeferredPhotoProxy`; final image finalized by Photos later | iOS 17.0; iPhone 11 Pro+ | Proxy must be saved to the Photos library as `.photoProxy`, which conflicts with a private app archive. Not recommended here. |
| Readiness | `captureReadiness`, `AVCapturePhotoOutputReadinessCoordinator` | iOS 17.0 | gate auto-capture on `.ready` |
| Macro / focus | `minimumFocusDistance` (mm, -1 if unknown), `.continuousAutoFocus`, `autoFocusRangeRestriction = .near`, torch via `torchMode` | iOS 15.0 for min focus distance | https://developer.apple.com/documentation/avfoundation/avcapturedevice/minimumfocusdistance |
| Level/rotation | `AVCaptureDevice.RotationCoordinator` (`videoRotationAngleForHorizonLevelCapture/Preview`) | iOS 17.0 | https://developer.apple.com/documentation/avfoundation/avcapturedevice/rotationcoordinator |
| Hardware shutter (Camera Control, volume) | `AVCaptureEventInteraction` (AVKit) / SwiftUI `onCameraCaptureEvent`; events only to foreground apps actively capturing; adopting it replaces default button behavior | iOS 17.2 (Camera Control hardware: iPhone 16 family, 17 Pro, 18 Pro; absent on 16e/17e per spec pages) | https://developer.apple.com/documentation/avkit/avcaptureeventinteraction , https://developer.apple.com/documentation/avfoundation/enhancing-your-app-experience-with-the-camera-control |
| Camera Control overlays | `AVCaptureSystemZoomSlider`, `AVCaptureSlider`, `AVCaptureIndexPicker`, `session.supportsControls/canAddControl/maxControlsCount` | iOS 18.0 | same |
| Launch from Lock Screen / Control Center / Action button | `LockedCameraCapture` extension + `CameraCaptureIntent` (App Intents) in app, widget and extension targets | iOS 18.0 | https://developer.apple.com/documentation/lockedcameracapture , https://developer.apple.com/documentation/appintents/cameracaptureintent , https://developer.apple.com/videos/play/wwdc2024/10204/ |

LockedCameraCapture limits (WWDC24): the extension has **no network access**, can write only to its own container and `sessionContentURL`, cannot read the App Group container, must show a viewfinder immediately or be killed, and its content is moved into the app container on dismissal (`LockedCameraCaptureManager.sessionContentURLs`). So Lock Screen capture can only queue pages; all AI and upload happen after the user unlocks into the app.

### 2f) Storage, sync, indexing, background work

- CloudKit: records max **1 MB**; `CKAsset` excluded from that limit and intended for large files; `CKSyncEngine` (WWDC23, iOS 17) handles scheduling, batching, push-triggered fetches and state serialization but conflicts (`serverRecordChanged`) are yours to merge. https://developer.apple.com/documentation/cloudkit/ckrecord , https://developer.apple.com/videos/play/wwdc2023/10188/
- iCloud Drive: `FileManager.url(forUbiquityContainerIdentifier:)` (iOS 5+, entitlement `com.apple.developer.ubiquity-container-identifiers`, call off main thread); confirm upload with `ubiquitousItemIsUploadedKey` via `NSMetadataQuery`/`NSFilePresenter`, never by polling inside a coordinated read. This is the simplest "user-owned" target because the Documents subfolder appears in Files. https://developer.apple.com/documentation/foundation/filemanager/url(forubiquitycontaineridentifier:) , https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemisuploadedkey
- File Provider: `NSFileProviderReplicatedExtension` is available on iOS 16+/macOS 11+ so the archive can be surfaced as a Files location; Apple's page documents no iOS-specific limits. https://developer.apple.com/documentation/fileprovider/nsfileproviderreplicatedextension
- Core Spotlight: `CSSearchableItem` (iOS 9) with `attributeSet.title`, `textContent`, `contentDescription`, `thumbnailData/URL`, `contentURL`, `keywords`, `contentType`; `isUpdate` for partial updates; batches with client state. `CSUserQuery` (iOS 16) runs lexical **and semantic** queries over a private on-device index; call `CSUserQuery.prepare()` before showing search; `enableRankedResults`, `userEngaged`. Semantic index processes `title` and `textContent` (WWDC24). Apple Intelligence summarization/priority of indexed items exists but only for message/email/voice-audio content types (not documents). https://developer.apple.com/documentation/corespotlight/csuserquery , https://developer.apple.com/videos/play/wwdc2024/10131/ , https://developer.apple.com/documentation/corespotlight/cssearchableitem , https://developer.apple.com/documentation/corespotlight/generating-summary-and-priority-data-for-indexed-items
- App Intents: `IndexedEntity` (iOS 18) adds entities to Spotlight and makes them discoverable by Apple Intelligence; App Shortcuts (iOS 16) give Siri phrases like "find my tax documents in X". https://developer.apple.com/documentation/appintents/indexedentity
- Background: `BGContinuedProcessingTask` (iOS 26) for user-initiated work that must survive backgrounding, shows a Live Activity with cancel, requires progress reporting (no-progress tasks are expired), default `.queue` strategy or `.fail`, optional GPU via `com.apple.developer.background-tasks.continued-processing.gpu`; killed silently if the user swipes the app away; no stated duration cap. `BGProcessingTask` for charger/network-gated maintenance (e.g., nightly OCR re-runs). Background `URLSession` (iOS 7+, out-of-process uploads from file URLs) remains the right primitive for the actual bytes. App Groups (`group.<name>`) share a container between app, Lock Screen extension and File Provider. https://developer.apple.com/documentation/backgroundtasks/bgcontinuedprocessingtaskrequest , https://developer.apple.com/documentation/backgroundtasks/performing-long-running-tasks-on-ios-and-ipados , https://developer.apple.com/videos/play/wwdc2025/227/ , https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.application-groups

### 2g) Local store

| Option | FTS | Sync | Notes |
|---|---|---|---|
| SwiftData (iOS 17+) | None. Apple's docs and the 2024/2025/2026 update pages never mention full-text search; `#Index`/`#Unique` (iOS 18), inheritance (iOS 26), `ResultsObserver`/`HistoryObserver` and `codable` attributes (2026) | CloudKit via container | https://developer.apple.com/documentation/swiftdata , https://developer.apple.com/documentation/updates/swiftdata |
| Core Data | None (NSPredicate `CONTAINS[cd]` only) | `NSPersistentCloudKitContainer` | mature, verbose |
| GRDB + SQLite FTS5 | Yes: `create(virtualTable:using: FTS5())`, `unicode61`/`porter` tokenizers, external-content tables synchronized by triggers (`synchronize(withTable:)`), `ORDER BY rank`, snippets | roll your own (CKSyncEngine) | GRDB's doc says FTS5 needs a build with `SQLITE_ENABLE_FTS5` (use GRDB's bundled SQLite or confirm the system library); normalize Unicode (NFC vs NFD) or matches fail. https://raw.githubusercontent.com/groue/GRDB.swift/master/Documentation/FullTextSearch.md |

### 2h) Security and commerce

- Data Protection: `FileProtectionType.complete`, `.completeUnlessOpen`, `.completeUntilFirstUserAuthentication`, `.none` via the `protectionKey` attribute. Background processing of the archive after lock requires `.completeUntilFirstUserAuthentication` or `.completeUnlessOpen` on files you touch in the background. https://developer.apple.com/documentation/foundation/fileprotectiontype
- Keychain (Security framework) stores the Anthropic/Drive/Synology credentials; access groups via the App Groups/keychain-access-groups entitlement; Secure Enclave keys for signing. https://developer.apple.com/documentation/security/keychain-services
- App Attest: `DCAppAttestService` (iOS 14+): `isSupported`, `generateKey` (Secure Enclave), `attestKey`, `generateAssertion` for proving requests come from the genuine app when the service proxies Claude calls. https://developer.apple.com/documentation/devicecheck/dcappattestservice
- Sign in with Apple (AuthenticationServices, iOS 13+) is standard; StoreKit 2 (`Product`, `Transaction.currentEntitlements`, `Transaction.updates`, JWS-signed, App Store Server Notifications, win-back offers) covers subscriptions. https://developer.apple.com/documentation/storekit/in-app-purchase
- PDF text layer: Core Graphics `CGTextDrawingMode.invisible` ("do not draw the text, but do update the text position") lets you lay OCR words under the page image in a `CGPDFContext`; no higher-level Apple API writes searchable PDFs for you. https://developer.apple.com/documentation/coregraphics/cgtextdrawingmode

### 2i) Android parity notes

- ML Kit Document Scanner: minSdk 21, Play services-delivered models/UI (~300 KB app size), device needs >= 1.7 GB RAM, returns JPEG pages and/or PDF, modes BASE / BASE_WITH_FILTER / FULL (ML cleanup of stains/fingers), page limit configurable; UI is not customizable and auto-capture is not exposed, so like `VNDocumentCameraViewController` it breaks zero-interaction. https://developers.google.com/ml-kit/vision/doc-scanner , https://developers.google.com/ml-kit/vision/doc-scanner/android
- ML Kit Text Recognition v2: Latin, Chinese, Devanagari, Japanese, Korean; block/line/element/symbol hierarchy; "real-time on a wide range of devices" (no numbers). https://developers.google.com/ml-kit/vision/text-recognition/v2
- CameraX: API 21+, `ImageAnalysis` for frame-level ML, `ImageCapture`, extensions (HDR/Night). https://developer.android.com/media/camera/camerax
- Gemini Nano via ML Kit GenAI (AICore): Prompt API with image+text input and typed structured output (beta, no SLA), `AgentRunner` tool loops, summarization/proofreading/rewriting/image description, embeddings for semantic search with AppSearch; gated to nano-v2/v3/v4 flagships (Pixel 9-11, Galaxy S25-S26 etc.); per-app inference and battery quotas; **inference only while the app is in the foreground** (`BACKGROUND_USE_BLOCKED`). https://developers.google.com/ml-kit/genai , https://developer.android.com/ai/gemini-nano , https://developers.google.com/ml-kit/genai/prompt/android

## 3) Options compared

| Decision | Option A | Option B | Option C | Pick |
|---|---|---|---|---|
| Capture UI | `VNDocumentCameraViewController` (zero code, but modal + taps) | `DataScannerViewController` (live, A12+, no page quality signals) | Custom `AVCaptureSession` + Vision segmentation/smudge/aesthetics gates, ZSL + responsive capture | **C** (only one that is truly hands-free) |
| OCR | `RecognizeTextRequest .fast` on preview frames | `RecognizeDocumentsRequest` on the full capture (tables/lists/data detectors, iOS 26) | Cloud OCR | **A for live feedback + B for archive**; cloud only as Claude vision for hard cases |
| Local understanding | Create ML text classifier (any device, no AI gate) | Foundation Models `@Generable` (A17 Pro+/iOS 26, 4k ctx, free) | Claude (primary, needs network/key) | **B first-pass where available, A as floor, C canonical** |
| Image-to-LLM on device | none (iOS 26) | FM `Attachment` + `OCRTool` (iOS 27) | FastVLM 0.5B via Core ML/MLX (any A-series with RAM, your packaging) | B as progressive enhancement; C only if you need VLM on non-AI devices |
| Local DB | SwiftData | Core Data | GRDB + FTS5 | **GRDB** (FTS5, bm25-style rank, triggers) |
| User-facing search | own FTS UI | Core Spotlight `CSUserQuery` (lexical + semantic, system ranking) | Claude-powered query planner over FTS | **B + C** (index everything in Spotlight; use Claude to turn NL into filters/dates) |
| Durability queue | in-memory | background `URLSession` + `BGProcessingTask` | `BGContinuedProcessingTask` for the session's batch + background `URLSession` for bytes + CloudKit `CKAsset` as always-on first hop | **C** |
| User storage targets | iCloud Drive ubiquity container (native, Files-visible) | Google Drive API / Synology WebDAV via background `URLSession` | File Provider extension exposing the archive | iCloud Drive + REST targets; File Provider later |
| Backend auth | API key in app | App Attest assertions + Sign in with Apple | | **B** |
| Hardware launch | Action button via App Intent (iOS 18 control) | LockedCameraCapture extension (no network, queue only) | Camera Control press via `AVCaptureEventInteraction` | A + C in v1; B later |

## 4) Recommendation for this project

1. Deployment target iOS 26.0, with `#available(iOS 27)` paths for `Attachment`/`OCRTool`/`PrivateCloudComputeLanguageModel`. Device floor for the "fast path" is A14/iOS 26 (for `DetectLensSmudgeRequest`); Foundation Models features light up only on A17 Pro+ and must be feature-detected, never assumed.
2. Capture loop: custom `AVCaptureSession` with `.photo` preset, format chosen for 48 MP via `supportedMaxPhotoDimensions`, ZSL + responsive capture on, fast-capture prioritization off (quality matters for archival), deferred delivery off (it forces Photos-library proxies). Run per preview frame at ~10-15 Hz: `DetectDocumentSegmentationRequest` (page present, corners stable across N frames, fills >= X% of frame), a Laplacian/variance sharpness score (your code), and gate the still on `captureReadiness == .ready`. Immediately after capture: `DetectLensSmudgeRequest` (reject > 0.9) and `GenerateImageFeaturePrintRequest` distance against the last ~50 pages for the instant "already scanned" announcement (use `AVSpeechSynthesizer`/haptics). Apple publishes no latency for these; budget the measurement into week one on an A16, A18 and A19 device.
3. Understanding: `RecognizeTextRequest(.fast)` on preview for the live "I see a W-2 from X" label, `RecognizeDocumentsRequest` on the final still for the archival transcript, tables, and data detectors (amounts, dates, addresses, tracking numbers come for free). Feed that transcript to `SystemLanguageModel(useCase: .contentTagging)` with a `@Generable` `{kind: DocKind, issuer, docDate, taxYear?, amount?, tags: [String]}` for an instant, offline, free first pass (keep total under ~3.5k tokens; chunk long pages). Send the image + transcript to Claude for the canonical, higher-quality extraction and summary asynchronously; reconcile. A Create ML `MLTextClassifier` over the transcript is the fallback on non-Apple-Intelligence devices.
4. Durability: write page JPEG/HEIC + JSON sidecar to the app container with `.completeUntilFirstUserAuthentication`, enqueue a `CKAsset` upload (private DB, `CKSyncEngine`) as the always-on first hop, then fan out to the user's chosen iCloud Drive folder, Google Drive, Synology (WebDAV/SMB over background `URLSession`). Wrap each scanning session's post-processing in a `BGContinuedProcessingTask` so the Live Activity shows "Saving 12 pages" and the user may pocket the phone; only mark "captured" in UI once the local write plus CloudKit upload have succeeded.
5. Search: GRDB with an external-content FTS5 table over transcript + Claude summary + tags (`unicode61` tokenizer, NFC-normalized), ranked by `rank`; mirror every document into Core Spotlight (`title`, `textContent`, `thumbnailData`, `contentType = PDF`, `keywords`) and adopt `IndexedEntity` so Spotlight/Siri find "2024 tax documents" without opening the app. Use Claude to compile natural-language queries into structured filters (year, kind, issuer) plus an FTS string.
6. Output: build the archival PDF yourself with `CGPDFContext`: image page + invisible text layer (`setTextDrawingMode(.invisible)`) positioned from `RecognizeDocumentsRequest` line geometry; attach PDF/A-style metadata; zip bundles via Compression framework.
7. Launch surfaces: ship an App Intent for the Action button and Control Center in v1; add Camera Control press handling with `AVCaptureEventInteraction`; defer the LockedCameraCapture extension (queue-only, no network) to v2.
8. Service: App Attest + Sign in with Apple in front of a Claude-proxying backend; StoreKit 2 subscriptions; keep BYO Anthropic key in Keychain as the founder's own mode.

## 5) Risks and unknowns

- No vendor latency numbers for `RecognizeDocumentsRequest`, `DetectLensSmudgeRequest`, or Foundation Models on A18/A19; the only Apple speed figures are 2024 iPhone 15 Pro numbers (0.6 ms/prompt token, 30 tok/s). Sub-second per-page UX is plausible but unmeasured.
- Foundation Models is text-only on iOS 26 and gated to Apple Intelligence devices, 16 languages, 4k context; guardrails may refuse medical/legal content unless `permissiveContentTransformations` is used; model versions change with OS point releases, so prompts and any adapters need re-validation (adapters are ~160 MB each, one per model version, entitlement-gated).
- iOS 27 multimodal/PCC are brand new; PCC needs a managed entitlement and Apple signals future fees and daily quotas.
- Feature-print distance thresholds for "same page" are uncalibrated; two different pages of the same form may look alike.
- `VNDocumentCameraViewController`-grade cleanup (shadow removal, dewarp) is not exposed as an API; you must implement perspective correction and enhancement yourself (Core Image + the segmentation mask).
- `BGContinuedProcessingTask` is killed without callback if the user force-quits; CloudKit conflicts are manual; iCloud Drive upload is best-effort and depends on the user's iCloud quota.
- Core Spotlight semantic models are downloaded lazily and may be unloaded; no documented index size limits.
- GRDB FTS5 requires confirming `SQLITE_ENABLE_FTS5` in the SQLite you link.
- Android: Gemini Nano is beta, foreground-only, flagship-only; ML Kit doc scanner is not customizable.
- A19/A20 TOPS and RAM figures come from Wikipedia, not Apple.

## 6) Open questions for the founder

1. Minimum supported device: is A14/iOS 26 acceptable, or must iPhone 12-era and older (no `DetectLensSmudgeRequest`) work?
2. Is on-device-only operation (no Claude) a required mode, or may understanding always go to the cloud when online?
3. Which storage target is the source of truth for durability: CloudKit (ours) or the user's own drive? Who pays for CloudKit storage at scale?
4. Must "already scanned" detect the same physical page only, or also identical copies (duplicate statements)?
5. Priority between archival fidelity (48 MP, ~6-10 MB per page) and upload speed/storage cost; is 12 MP acceptable for most mail?
6. Are you willing to maintain a Foundation Models adapter per OS release, or should custom modeling start with Create ML text classifiers and distilled cloud labels?
7. Languages beyond English for v1? (Vision: 26; Foundation Models: 16.)
8. Android timeline, given the Gemini Nano foreground-only and device constraints.

## 7) Sources

- https://developer.apple.com/documentation/vision/recognizedocumentsrequest
- https://developer.apple.com/documentation/vision/documentobservation
- https://developer.apple.com/documentation/vision/documentobservation/container
- https://developer.apple.com/documentation/datadetection/datadetector/match/semanticdetails
- https://developer.apple.com/videos/play/wwdc2025/272/
- https://developer.apple.com/documentation/vision/recognizetextrequest
- https://developer.apple.com/documentation/vision/detectdocumentsegmentationrequest
- https://developer.apple.com/documentation/vision/detecteddocumentobservation
- https://developer.apple.com/documentation/vision/detectlenssmudgerequest
- https://developer.apple.com/documentation/vision/calculateimageaestheticsscoresrequest
- https://developer.apple.com/documentation/vision/imageaestheticsscoresobservation
- https://developer.apple.com/documentation/vision/generateimagefeatureprintrequest
- https://developer.apple.com/documentation/vision/featureprintobservation
- https://developer.apple.com/documentation/vision/ocrtool
- https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller
- https://developer.apple.com/documentation/visionkit/vndocumentcamerascan
- https://developer.apple.com/documentation/visionkit/datascannerviewcontroller
- https://developer.apple.com/documentation/visionkit/scanning-data-with-the-camera
- https://developer.apple.com/documentation/visionkit/imageanalyzer
- https://developer.apple.com/documentation/foundationmodels
- https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel
- https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel/availability-swift.enum/unavailablereason
- https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel/guardrails
- https://developer.apple.com/documentation/foundationmodels/managing-the-context-window
- https://developer.apple.com/documentation/foundationmodels/supporting-languages-and-locales-with-foundation-models
- https://developer.apple.com/documentation/foundationmodels/tool
- https://developer.apple.com/documentation/foundationmodels/languagemodelsession/generationerror
- https://developer.apple.com/documentation/foundationmodels/attachment
- https://developer.apple.com/documentation/foundationmodels/analyzing-images-with-multimodal-prompting
- https://developer.apple.com/documentation/foundationmodels/privatecloudcomputelanguagemodel
- https://developer.apple.com/apple-intelligence/foundation-models-adapter/
- https://developer.apple.com/videos/play/wwdc2025/301/
- https://machinelearning.apple.com/research/apple-foundation-models-2025-updates
- https://machinelearning.apple.com/research/introducing-apple-foundation-models
- https://www.apple.com/apple-intelligence/
- https://support.apple.com/en-us/121115
- https://developer.apple.com/documentation/createml
- https://developer.apple.com/documentation/coreml
- https://machinelearning.apple.com/research/fast-vision-language-models
- https://github.com/apple/ml-fastvlm
- https://arxiv.org/abs/2412.13303
- https://github.com/ml-explore/mlx-swift-examples
- https://www.apple.com/iphone-18-pro/specs/
- https://en.wikipedia.org/wiki/Apple_A19
- https://en.wikipedia.org/wiki/Apple_A20
- https://developer.apple.com/documentation/avfoundation/avcapturephotooutput
- https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/iszeroshutterlagsupported
- https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/isresponsivecapturesupported
- https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/isautodeferredphotodeliverysupported
- https://developer.apple.com/videos/play/wwdc2023/10105/
- https://developer.apple.com/documentation/avfoundation/avcapturedevice/format/supportedmaxphotodimensions
- https://developer.apple.com/documentation/avfoundation/avcapturedevice/minimumfocusdistance
- https://developer.apple.com/documentation/avfoundation/avcapturedevice/rotationcoordinator
- https://developer.apple.com/documentation/avkit/avcaptureeventinteraction
- https://developer.apple.com/documentation/avfoundation/enhancing-your-app-experience-with-the-camera-control
- https://developer.apple.com/documentation/lockedcameracapture
- https://developer.apple.com/documentation/appintents/cameracaptureintent
- https://developer.apple.com/videos/play/wwdc2024/10204/
- https://developer.apple.com/documentation/backgroundtasks/bgcontinuedprocessingtask
- https://developer.apple.com/documentation/backgroundtasks/bgcontinuedprocessingtaskrequest
- https://developer.apple.com/documentation/backgroundtasks/performing-long-running-tasks-on-ios-and-ipados
- https://developer.apple.com/videos/play/wwdc2025/227/
- https://developer.apple.com/documentation/cloudkit/ckrecord
- https://developer.apple.com/videos/play/wwdc2023/10188/
- https://developer.apple.com/documentation/foundation/filemanager/url(forubiquitycontaineridentifier:)
- https://developer.apple.com/documentation/foundation/urlresourcekey/ubiquitousitemisuploadedkey
- https://developer.apple.com/documentation/fileprovider/nsfileproviderreplicatedextension
- https://developer.apple.com/documentation/corespotlight/csuserquery
- https://developer.apple.com/documentation/corespotlight/cssearchableitem
- https://developer.apple.com/documentation/corespotlight/cssearchableitemattributeset
- https://developer.apple.com/documentation/corespotlight/generating-summary-and-priority-data-for-indexed-items
- https://developer.apple.com/videos/play/wwdc2024/10131/
- https://developer.apple.com/documentation/appintents/indexedentity
- https://developer.apple.com/documentation/bundleresources/entitlements/com.apple.security.application-groups
- https://developer.apple.com/documentation/swiftdata
- https://developer.apple.com/documentation/updates/swiftdata
- https://raw.githubusercontent.com/groue/GRDB.swift/master/Documentation/FullTextSearch.md
- https://developer.apple.com/documentation/foundation/fileprotectiontype
- https://developer.apple.com/documentation/security/keychain-services
- https://developer.apple.com/documentation/devicecheck/dcappattestservice
- https://developer.apple.com/documentation/storekit/in-app-purchase
- https://developer.apple.com/documentation/coregraphics/cgtextdrawingmode
- https://developers.google.com/ml-kit/vision/doc-scanner
- https://developers.google.com/ml-kit/vision/doc-scanner/android
- https://developers.google.com/ml-kit/vision/text-recognition/v2
- https://developer.android.com/media/camera/camerax
- https://developers.google.com/ml-kit/genai
- https://developers.google.com/ml-kit/genai/prompt/android
- https://developer.android.com/ai/gemini-nano
