# Hands-free continuous document capture on iPhone — research report

Dimension: zero-tap, continuous, multi-page capture (iOS first, Android noted). Date: 2026-11-03. Sources are mostly 2025-2026 Apple docs and WWDC transcripts; older items are flagged.

---

## 1. Executive summary

1. Apple's built-in scanner (`VNDocumentCameraViewController`, iOS 13+) does auto-capture page after page, but it is a modal UI with exactly two API surfaces (`delegate`, `isSupported`), returns images only after the user taps Save, has no "processing done" callback, and Apple DTS confirmed in Jan 2025 and again in May 2026 that none of this can be customized. It cannot meet "zero interaction + durability + speed".
2. The right architecture is a custom `AVCaptureSession` loop: `AVCaptureVideoDataOutput` frames into Vision's ML document segmenter (`VNDetectDocumentSegmentationRequest`, iOS 15+; Swift `DetectDocumentSegmentationRequest`, iOS 18+), which Apple says runs in real time on the Neural Engine and is the same engine VisionKit uses.
3. The capture decision is a state machine over per-frame signals: quad stability (IoU + area delta over N frames), gyro stillness (Core Motion), sharpness (variance of Laplacian on a downscaled luma plane, per Apple's own sample), exposure/glare checks, and a "page changed" detector (quad identity + perceptual hash).
4. The archival still should come from `AVCapturePhotoOutput` with iOS 17 responsive-capture features (`isResponsiveCaptureEnabled`, `isZeroShutterLagEnabled`, `captureReadiness`), 12 MP by default; 48 MP only on demand because Apple says high-res processing "can take several seconds".
5. iOS 26 adds `RecognizeDocumentsRequest` (layout-aware OCR with tables, lists, data detectors) and `DetectLensSmudgeRequest` (0–1 confidence, A14+); iOS 18 adds `CalculateImageAestheticsScoresRequest.isUtility`, which flags documents/receipts.
6. No vendor or Apple publishes per-frame latency for document detection on iPhone; all numbers must be measured. Only an academic CPU baseline exists (65–102 ms/frame on an iPhone 6 for a non-Apple Hough method).
7. Commercial SDKs (Scanbot, Genius Scan, Dynamsoft) all auto-capture and support multi-page, but are quote-priced flat annual licenses (Dynamsoft from USD 1,249/yr is the only public number) and still rely on their own UI/stability heuristics; none advertises a measured capture latency.
8. Android's ML Kit Document Scanner is a Play-services-owned Intent flow (minSdk 21) with auto-capture but no camera control; a true hands-free loop on Android means CameraX plus a custom or SDK detector.
9. Durability rule: write the raw still (or the full-res video frame) to disk with a content hash before any haptic "captured" signal fires; never hold pages in memory like VisionKit does.
10. Recommendation: build the custom loop, free of third-party capture SDKs, with a measurement harness from day one; keep Scanbot/Genius Scan as a fallback license if Apple's segmenter proves weak on crumpled/white-on-white mail.

---

## 2. Findings

### 2a. Apple VisionKit `VNDocumentCameraViewController`

| Fact | Detail | Source |
|---|---|---|
| Availability | iOS 13.0+, iPadOS 13+, macCatalyst 13.1+, visionOS 1.0+ | https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller.md |
| Public API | Only `delegate` and `class var isSupported`. Apple's own overview: "scan a physical document, page by page, by tapping a camera interface". | same |
| Delegate | `documentCameraViewController(_:didFinishWith: VNDocumentCameraScan)`, `documentCameraViewControllerDidCancel(_:)`, `documentCameraViewController(_:didFailWithError:)` | https://developer.apple.com/forums/thread/826935 |
| Result | `VNDocumentCameraScan` with `pageCount`, `title`, `imageOfPage(at:) -> UIImage`; delivered only when the user taps Save | https://developer.apple.com/documentation/visionkit/vndocumentcamerascan.md |
| Auto-capture control | Apple DTS (Jan 2025): "There is no way to customize VNDocumentCameraViewController in that way, please file an enhancement request… you could use the Vision framework and CoreImage to implement similar functionality." | https://developer.apple.com/forums/thread/772703 |
| Processing-state callback | Apple DTS (May 2026) confirmed there is no API signalling that per-page processing is done; the Done button is dead until the thumbnail appears and "Ready for next Scan" shows; classified as framework-level. | https://developer.apple.com/forums/thread/826935 |
| Manual button bugs | Forum reports of the manual shutter not working while auto mode still captures. | https://developer.apple.com/forums/thread/723143 |
| Detection engine | WWDC21: VisionKit's document camera switched to `VNDetectDocumentSegmentationRequest` on Neural Engine devices. | https://nonstrict.eu/wwdcindex/wwdc2021/10041/ |
| Per-page processing time | Unknown; no published figure. The May 2026 thread shows there is a non-trivial internal pipeline per page. | — |

Verdict: it does auto-capture across many pages without taps, but it is modal, holds every page in memory until Save (a crash loses the batch), offers no duplicate detection, no custom overlay, no haptic hook, no torch policy, and no way to read the page before Save. It fails zero-interaction (Save tap, mode toggles) and durability.

### 2b. Custom capture loop: AVFoundation + Vision

**Document detection**

- `VNDetectDocumentSegmentationRequest`: iOS 15+. ML-based, trained on "paper, signs, notes, receipts, and labels"; documents "don't all have to be rectangles"; returns four corner points plus a low-resolution per-pixel confidence mask; finds a single document. Apple: runs "in realtime on a camera or video feed" on Neural Engine devices; "on the GPU or CPU, it is not fast enough for realtime use". https://nonstrict.eu/wwdcindex/wwdc2021/10041/ ; https://developer.apple.com/documentation/vision/vndetectdocumentsegmentationrequest.md
- Swift-native `DetectDocumentSegmentationRequest`: iOS 18+, `perform(on: CMSampleBuffer | CVPixelBuffer | CIImage …)` returns `DetectedDocumentObservation` (conforms to `QuadrilateralProviding`, `BoundingBoxProviding`, has `globalSegmentationMask: PixelBufferObservation`). https://developer.apple.com/documentation/vision/detectdocumentsegmentationrequest.md ; https://developer.apple.com/documentation/vision/detecteddocumentobservation.md
- `VNDetectRectanglesRequest`: classical CPU algorithm, can return multiple nested rectangles, fails with obscured corners/folds; keeps up in real time "as long as the CPU isn't saturated". Useful only as a fallback for pre-Neural-Engine devices. https://nonstrict.eu/wwdcindex/wwdc2021/10041/

**iOS 26 Vision additions relevant to documents (WWDC25 session 272)**

- `RecognizeDocumentsRequest` (iOS 26+): returns `DocumentObservation` with hierarchical containers: paragraphs, lines, words (not for CJK/Thai), tables (cells with row/column ranges), lists, barcodes; built-in DataDetection for phone numbers, emails, postal addresses, URLs, dates, measurements, currency amounts, tracking numbers, payment IDs, flight numbers; 26 languages; `transcript` gives full text. https://developer.apple.com/documentation/vision/recognizedocumentsrequest.md ; https://nonstrict.eu/wwdcindex/wwdc2025/272/
- `DetectLensSmudgeRequest` (iOS 26+, A14/M1+): `SmudgeObservation.confidence` 0.0–1.0; Apple's sample threshold is 0.9; Apple warns motion blur and long exposure can score as smudge, so run it "on a fixed capture where the device is stable". https://developer.apple.com/documentation/vision/detectlenssmudgerequest.md
- `CalculateImageAestheticsScoresRequest` (iOS 18+): `ImageAestheticsScoresObservation.isUtility` flags "utility images such as documents or receipts"; `overallScore`. Cheap page-vs-not-a-page sanity check. https://developer.apple.com/documentation/vision/calculateimageaestheticsscoresrequest.md ; https://developer.apple.com/documentation/vision/imageaestheticsscoresobservation.md
- Nothing new in VisionKit itself for iOS 26 was found (search returned only iOS 16 `DataScannerViewController` tutorials). Flag: verify against Xcode 26 release notes.

**Quad to perspective correction**

- `CIPerspectiveCorrection` with `inputTopLeft/TopRight/BottomLeft/BottomRight`. Vision returns normalized, bottom-left-origin coordinates that must be scaled to pixels; the `crop` key is poorly documented and must be passed as `inputCrop`. https://developer.apple.com/documentation/coreimage/ciperspectivecorrection.md ; https://developer.apple.com/forums/thread/705621
- Apple's ARKit sample applies a `VNRectangleObservation` straight into `CIPerspectiveCorrection`. https://developer.apple.com/documentation/arkit/tracking-and-altering-images.md

**Stability, sharpness, glare**

- Sharpness: Apple's Accelerate sample (Xcode 14 / iOS 16) computes variance of the Laplacian with `vDSP.convolve(... with3x3Kernel: [-1,-1,-1,-1,8,-1,-1,-1,-1])` then `vDSP_normalize` on the luma plane only, and deliberately uses `sessionPreset = .hd1280x720` because the 3×3 kernel "reports a lot of noise if applied to a full-resolution image". https://developer.apple.com/documentation/accelerate/finding-the-sharpest-image-in-a-sequence-of-captured-images.md
- A Metal variant (MPS Laplacian on a 3×3 tile grid, score = sharpest tile) exists in an open-source package; useful idea, not a live-camera benchmark. https://pub.dev/documentation/kirz_blurry_image_detector/latest/
- Motion: `CMMotionManager.deviceMotionUpdateInterval` gives attitude and unbiased rotation rate; Apple says create one manager per app; third-party sources say the cap is 100 Hz (verify). No Apple-documented "stationary" threshold; tune a rotation-rate magnitude over a window. https://developer.apple.com/documentation/coremotion/cmmotionmanager.md
- Coarse scene-change: `AVCaptureDevice.isSubjectAreaChangeMonitoringEnabled` posts `subjectAreaDidChangeNotification` on "lighting changes, substantial movement" (iOS 5+). https://developer.apple.com/documentation/avfoundation/avcapturedevice/issubjectareachangemonitoringenabled.md
- Glare: no published open algorithm with thresholds. Patents describe (a) torch-off/torch-on frame differencing to mask specular pixels (US10630905) and (b) tracking a glare parameter inside the document region across preview frames and auto-capturing only when under threshold (US11297248). Scanbot exposes `glareDetectionThreshold` default 0.5 ("glare may cover up to 50% of text size"). https://patents.google.com/patent/US10630905 ; https://api-docs.scanbot.io/document-scanner-sdk/android/v9.0.0/-android%20-scanbot%20-s-d-k/io.scanbot.sdk.documentdata/-glare-detection-configuration/index.html
- Torch: `AVCaptureDevice.setTorchModeOn(level:)` 0.0–1.0, `maxAvailableTorchLevel` may be < 1.0 under thermal duress, requires `lockForConfiguration()`. https://developer.apple.com/documentation/avfoundation/avcapturedevice/settorchmodeon(level:).md

**Frame pipeline and when to fire a still**

- Video formats: an iPhone 12 Pro Max dump lists a 4032×3024 video format at 1–30 fps (420v/420f) as well as 1920×1440@30, 3264×2448@30, 1280×720@240. https://zenn.dev/yorifuji/scraps/bc52d2e4601de0
- Apple DTS (Dec 2025): you can stream 4032×3024 through `AVCaptureVideoDataOutput` "on most cameras"; whether Vision keeps up at 30 fps "would depend on the model"; recommended pattern is a second `AVCaptureVideoDataOutput` at lower resolution for Vision because "most models internally run at a lower resolution anyway". https://developer.apple.com/forums/thread/809719
- `AVCapturePhotoOutput` (iOS 17 responsive capture family): `isResponsiveCaptureSupported/Enabled`, `isFastCapturePrioritizationSupported/Enabled`, `isZeroShutterLagSupported/Enabled`, `isAutoDeferredPhotoDeliverySupported/Enabled`, `captureReadiness` (`sessionNotRunning`, `notReadyMomentarily`, `notReadyWaitingForCapture`, `notReadyWaitingForProcessing`, `ready`; iOS 17+), `maxPhotoDimensions`, `maxPhotoQualityPrioritization` (`.speed/.balanced/.quality`), `isShutterSoundSuppressionSupported`. https://developer.apple.com/documentation/avfoundation/avcapturephotooutput.md ; https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/capturereadiness-swift.enum.md
- WWDC23 session 10105 specifics: zero shutter lag is automatic for apps linked on iOS 17+ on formats where `isHighestPhotoQualitySupported` is true; excluded for flash, manual exposure, bracketed captures; responsive capture and fast-capture prioritization need A12+; deferred processing needs iPhone 11 Pro+; responsive capture raises peak memory; demo showed roughly 2 photos/s before responsive capture, no numeric after-figure; a 30 fps frame is 33 ms. https://nonstrict.eu/wwdcindex/wwdc2023/10105/
- WWDC26 session 304 (iOS 27 era; flag as newest): 48 MP is a single full-res sensor frame available with `.balanced` or `.quality`; 24 MP is multi-frame and `.quality` only; only the `.photo` preset supports 24/48 MP; "high-resolution processing can take several seconds"; `photoProcessingTimeRange` on `AVCaptureResolvedPhotoSettings` reports expected delivery time; starting iOS 27 on iPhone 16/17, balanced fast captures are also deferred. https://nonstrict.eu/wwdcindex/wwdc2026/304/ ; https://developer.apple.com/documentation/avfoundation/avcaptureresolvedphotosettings/photoprocessingtimerange.md
- Deferred delivery caveat: the proxy must be persisted quickly; edits at capture time don't apply to the final; code must handle both proxies and full photos (`photoOutput(_:didFinishCapturingDeferredPhotoProxy:error:)`). https://developer.apple.com/documentation/avfoundation/avcapturephotocapturedelegate/photooutput(_:didfinishcapturingdeferredphotoproxy:error:).md

**"Page changed" detector**

- No Apple API. Building blocks: (1) quad identity (IoU of successive quads; Dynamsoft's iOS tutorial exposes IoU threshold 0.50–0.98, area-delta 0.02–0.30, stable-frame count 1–8); (2) a "quad lost then re-acquired" transition; (3) perceptual hash (dHash/pHash, 64-bit, Hamming distance ≤ 4–5 as "same") on the corrected thumbnail; (4) after OCR, a normalized text hash for robust "already scanned". https://www.dynamsoft.com/codepool/build-mobile-document-scanner-ios-app.html ; https://ssojet.com/dev-guides/phash-in-swift ; https://pub.dev/documentation/kirz_blurry_image_detector/latest/
- Academic precedent for video-based multi-page capture (page-turn detection from video, frame selection) dates to CVPR-W 2013; old but the problem framing is unchanged. https://openaccess.thecvf.com/content_cvpr_workshops_2013/W03/html/Kumar_Mobile_Video_Capture_2013_CVPR_paper.html

### 2c. Commercial SDKs

| SDK | Auto-capture | Continuous multi-page, no taps | Custom camera hook | Min iOS | Price (public) | Latency published | Source |
|---|---|---|---|---|---|---|---|
| Apple VisionKit | Yes | Yes until Save | No | 13 | Free | No | Apple docs |
| Scanbot (Apryse since 2025-07-10) | Yes; `autoSnappingSensitivity` 0–1 (1.0 immediate, 0.0 = 3 s, default 0.66 ≈ 2 s), `autoSnappingDelay` default 200 ms between pages, glare threshold 0.5 | Yes (`multiPageEnabled`, `maxNumberOfPages`) | Yes (Custom UI view-controller components) | 15, Xcode 16 | Flat annual, unlimited scans, quote only; 1 min/session without key; 7-day trial; bound to bundle ID | No | https://docs.scanbot.io/ios/document-scanner-sdk/introduction/ ; https://pub.dev/documentation/scanbot_sdk/latest/scanbot_sdk_ui/FinderDocumentScannerConfiguration-class.html ; https://apryse.com/blog/apryse-acquires-scanbot-and-accusoft |
| Genius Scan SDK | Yes ("auto-trigger to capture document upon detection"; `GSKTriggerDecider` in v4 API) | Yes (`multiPage: true` in ScanFlow) | Yes (`GSKCameraViewController`, `GSKDocumentDetector` real-time) | unknown | Flat annual, unlimited installs/scans, one license covers iOS+Android, quote only; 1 min/session trial; 30-day key | No | https://geniusscansdk.com/docs/v6/document-scanning/quick-start/ ; https://geniusscansdk.com/docs/v4/ios/api ; https://geniusscansdk.com/license/licensing/ |
| Dynamsoft Capture Vision / Document Normalizer | Yes; QuadStabilizer IoU + area delta over N frames; 1080p; 0.5 s manual fallback | Per session (`expectedDocumentsCount`), continuous loop possible in custom code | Yes (`CameraEnhancer`, `CaptureVisionRouter`) | 16, Xcode 16, SPM 3.6.4000+ | From USD 1,249/yr (Document Normalizer); Mobile Web Capture 1,299/yr ≤50 clients, 2,999/yr ≤200; 30-day trial, 30-day refund | No | https://www.dynamsoft.com/document-normalizer/ask-for-quote/ ; https://www.dynamsoft.com/codepool/build-mobile-document-scanner-ios-app.html |
| Microblink Capture (capture-ios v1.5.0, Nov 2025) | Yes (ID-document focused) | Not documented | Yes (`CaptureCore` no-UI) | Xcode 16.4 | Not public; volume/session based | No | https://github.com/BlinkID/capture-ios/releases |
| Anyline | ID/meter/barcode focus | Not documented | unknown | unknown | Not public (third-party listing €457/mo) | No | https://www.capterra.com/p/178754/Anyline/ |
| Nutrient (PSPDFKit) | None. Nutrient's own page: "no live camera viewfinder with auto-capture, edge detection, and perspective correction" | No | No | — | Not public (third-party $8k–25k/yr) | — | https://www.nutrient.io/sdk/vs/scanbot/ |

Observation: every SDK's auto-capture is the same shape (detect quad, require N stable frames, fire), none publishes measured detect-to-capture latency, and all consumer-grade defaults are 1–3 s hold times, which is far slower than the founder's target.

### 2d. Android

- ML Kit Document Scanner: `com.google.android.gms:play-services-mlkit-document-scanner:16.0.0`, minSdk 21, needs 1.7 GB RAM, UI and models delivered by Play services, no camera permission required, launched via `getStartScanIntent` + `ActivityResultLauncher`; options `setPageLimit`, `setGalleryImportAllowed`, `setResultFormats(JPEG|PDF)`, `setScannerMode(BASE|BASE_WITH_FILTER|FULL)`; on-device. Modal, app has zero camera control. `pageLimit` broke after the 2025-09-29 Play services update and was confirmed fixed on 25.45.34 (Nov 2025). https://developers.google.com/ml-kit/vision/doc-scanner/android ; https://github.com/googlesamples/mlkit/issues/980
- CameraX custom loop: open-source DocScanner uses CameraX 1.3.1 ImageAnalysis at up to 30 fps, Sobel-based quad detection, ~0.4 s steady hold before auto-capture, API 24+. No ML Kit-equivalent to Apple's segmenter without the modal UI; OpenCV or Scanbot/Genius/Dynamsoft fill that gap. https://github.com/vvkdhkl/DocScanner ; https://scanbot.io/blog/ml-kit-vs-opencv-document-scanning-software/

### 2e. UX patterns for hands-free scanning

- Adobe Scan "High-Speed Scan" (subscription): multi-page without pressing Keep Scanning; corner dots; status strings "Looking for document", "Capturing… hold steady", "No document found. Capture manually". https://www.adobe.com/devnet-docs/adobescan/ios/en/scan.html
- VisionKit: thumbnail in bottom-left + "Ready for next Scan" text after each page. https://developer.apple.com/forums/thread/826935
- Overhead scanners: CZUR advertises 1.2–2 s per capture with page-turn detection; reviewers find real-world slower. ScanSnap iX1600 = 40 ppm / 80 ipm, iX2500 = 45 ppm / 90 ipm (sheet-fed baseline to beat for "faster than anything"). https://store.scannx.com/products/czur-m3000-pro-v2 ; https://www.pfu-us.ricoh.com/blog/ix2500-vs-ix1600
- Haptics: `UINotificationFeedbackGenerator` (iOS 10+) `.success/.warning/.error`; call `prepare()` ahead to cut latency. https://developer.apple.com/documentation/uikit/uinotificationfeedbackgenerator.md
- Shutter sound can be suppressed only where `isShutterSoundSuppressionSupported` (region-dependent). https://developer.apple.com/documentation/avfoundation/avcapturephotooutput.md

### 2f. Realistic latency numbers per stage

Measured public numbers do not exist for Apple's segmenter. What exists:

| Stage | Published number | Type | Source |
|---|---|---|---|
| Frame interval at 30 fps | 33 ms | fact | WWDC23 10105 |
| Classical Hough document localization, iPhone 6 CPU | 65 ms (SmartDoc) / 102 ms (MIDV-500) per frame | measured, academic, 2021 | https://arxiv.org/pdf/2106.09987 |
| Apple segmenter on Neural Engine | "realtime"; "not fast enough" on GPU/CPU | vendor claim | WWDC21 10041 |
| Shot-to-shot before responsive capture | ~2 photos/s | demo | WWDC23 10105 |
| 48 MP / 24 MP processing | "several seconds"; read `photoProcessingTimeRange` | vendor claim | WWDC26 304 |
| SDK default hold-to-capture | Scanbot ≈ 2 s default (0.66), 3 s at 0.0; Dynamsoft N stable frames (1–8) at 1080p; DocScanner 0.4 s | vendor config | see 2c, 2d |
| CZUR overhead capture | 1.2–2 s/page | vendor claim | see 2e |

Working budget (my estimate, to be verified on an iPhone 15/16/17 with a harness): segmentation 10–30 ms/frame on A15+ Neural Engine at 1440×1080 or lower; Laplacian variance on 1280×720 luma < 5 ms with vDSP; pHash < 2 ms; decision at 5–8 consecutive stable frames ≈ 170–270 ms after the page settles; full-res 12 MP still with responsive capture + zero shutter lag ≈ 100–300 ms to `didFinishProcessingPhoto`; `CIPerspectiveCorrection` + JPEG/HEIC encode of 12 MP on GPU ≈ 50–150 ms. End-to-end "page settled → haptic" target: < 500 ms; "page settled → corrected file on disk": < 1 s. These are targets, not measurements.

---

## 3. Options compared

| Option | Zero interaction | Speed ceiling | Durability control | Dedup / "already scanned" | Cost | Custom UI/haptics | Risk |
|---|---|---|---|---|---|---|---|
| A. VisionKit `VNDocumentCameraViewController` | No (Save tap, mode toggles) | Unknown; internal pipeline per page | Poor (pages in memory until Save) | None | Free | None | Apple-locked; DTS says no customization |
| B. Custom AVFoundation + Vision (recommended) | Yes | Highest; you own every stage | Full | Yes (quad + pHash + text hash) | Free (engineering time) | Full | Detector quality on hard mail; must build stability/glare logic |
| C. Custom camera with Scanbot/Genius Scan detector | Yes (Custom-UI components) | High, bounded by SDK heuristics | Full | Partial (hash yourself) | Quote-only flat annual, likely 4–5 figures/yr | Mostly | Vendor lock, bundle-ID licenses, Apryse roadmap |
| D. Dynamsoft Capture Vision | Yes with custom code | High (1080p, tunable stabilizer) | Full | Hash yourself | From USD 1,249/yr | Mostly | Per-platform SKUs; Document Normalizer vs Mobile Web Capture split |
| E. Android ML Kit Doc Scanner | No (Play UI) | Unknown | Poor (Intent result) | None | Free | None | Play-services regressions (pageLimit bug) |
| F. Android CameraX custom loop | Yes | High | Full | Yes | Free + detector | Full | Needs OpenCV or licensed detector |

---

## 4. Recommendation for this project

Build option B. The founder already ships native Swift with Vision OCR, so the marginal cost is the capture state machine, not the platform.

**Capture session**
- `AVCaptureSession` with `sessionPreset = .photo`; one `AVCaptureDeviceInput` (`.builtInWideAngleCamera`, back). Lock focus to a near-range continuous mode and disable auto-macro switching so quads do not jump between lenses.
- Two outputs, per Apple DTS: `AVCaptureVideoDataOutput` for analysis (request 420f, `alwaysDiscardsLateVideoFrames = true`, dedicated serial queue), and `AVCapturePhotoOutput` for the archival still. Enable `isResponsiveCaptureEnabled`, `isFastCapturePrioritizationEnabled`, `isZeroShutterLagEnabled` where supported; set `maxPhotoDimensions` to the format's 12 MP by default, `.balanced` prioritization; keep 24/48 MP as a user setting because of the multi-second processing cost. Observe `captureReadiness` through `AVCapturePhotoOutputReadinessCoordinator` so the state machine never fires into `notReadyWaitingForProcessing`.
- iOS floor: 17 (responsive capture) for the fast path; 18 if you want the Swift-native `DetectDocumentSegmentationRequest`; use `VNDetectDocumentSegmentationRequest` on 15–17 if you need a wider floor. Realistically ship iOS 18+ and light up iOS 26 features (`RecognizeDocumentsRequest`, `DetectLensSmudgeRequest`) conditionally.

**Per-frame analysis (target ≤ 20 ms/frame, every frame at 30 fps, skip when behind)**
1. Downscale/ROI: run the segmenter on a ≤ 1440×1080 buffer (Vision scales internally; `regionOfInterest` can cut cost).
2. `DetectDocumentSegmentationRequest` → quad + mask confidence. Reject quads with < ~25% frame area or any corner on the frame edge.
3. Stability: IoU with previous quad ≥ 0.95 and area delta ≤ 5% for N = 6 frames (≈ 200 ms), plus `CMMotionManager` rotation-rate magnitude below a tuned threshold over the same window. Reset counter on failure.
4. Sharpness: variance of Laplacian on the luma plane of the quad's bounding box (vDSP, Apple's recipe), compared against a running max for this page, not a global constant; fire only when the score is within ~10% of the best seen for this page and above a floor.
5. Exposure/glare: histogram of the quad region; reject if > X% of pixels are clipped at 255 inside the mask, or if mean luma is below a floor; torch policy = off by default, step up `setTorchModeOn(level:)` to 0.2–0.4 only when mean luma stays low for > 1 s, and re-check clipping after torch changes (glare is torch's main failure mode on glossy mail).
6. Page identity: dHash of the perspective-corrected 32×32 grayscale of the live frame. If Hamming ≤ 5 vs the last captured page → state "same page, holding" (no capture, show "already scanned" chip after 1 s). If the quad was lost and re-acquired and the hash differs → "new page" → begin stability window.

**Capture and durability**
- Fire `capturePhoto(with:delegate:)` the frame the state machine goes `stable && sharp && clean && new`. Write the delivered `AVCapturePhoto.fileDataRepresentation()` to disk immediately (atomic write, SHA-256 in the filename), then play `UINotificationFeedbackGenerator.success` and flash the overlay. Only then run `CIPerspectiveCorrection` with the full-res quad (re-run the segmenter on the still, since the video quad is lower-res), encode HEIC/JPEG, and enqueue OCR/upload. If the still fails or arrives blurrier than the best video frame (compare Laplacian scores), fall back to the best cached 4032×3024 video frame so the user never gets a silent miss.
- After the still, run `DetectLensSmudgeRequest` on iOS 26 (confidence ≥ 0.9 → one-time "clean your lens" toast; do not block capture) and `CalculateImageAestheticsScoresRequest.isUtility` as a cheap "is this a document" guard.
- Post-OCR dedup: normalized text SimHash with the stored library; mark duplicates as linked, never silently drop.

**UX**
- Overlay: live quad outline, a progress ring that fills over the stability window, a captured-page thumbnail strip, a counter, and a non-blocking "Already scanned (page 3)" chip. Audio click plus haptic on capture; distinct double-buzz for duplicate. No buttons on the main path; everything else lives behind a single menu.
- Stand mode: auto-detected when the gyro is still for > 3 s; relax the motion gate and rely on quad-identity transitions, so the user just swaps pages (CZUR-style page-change detection).

**Measurement harness first**
- Instrument every stage with `os_signpost` and log per-page: frames to decision, decision-to-still, still-to-disk, disk-to-corrected. Ship no heuristic without a number on iPhone 13 (A15) as the floor device.

**Why not a commercial SDK now**
- They do not publish latency, default to 1–3 s hold times, are quote-priced, and still require the same stability/dedup layer on top. Keep Scanbot or Genius Scan as a plan B if Apple's segmenter under-performs on white envelopes on white desks; both expose custom-camera components so the state machine is reusable.

**Android later**
- Reuse the state machine over CameraX `ImageAnalysis`; choose the detector then (OpenCV for free, Genius Scan one-license-covers-both, or Dynamsoft from USD 1,249/yr). Avoid the ML Kit Intent flow for the core product.

---

## 5. Risks and unknowns

- No published per-frame latency for Apple's document segmenter; the 10–30 ms estimate is unverified. Thermal throttling during long sessions is unmeasured.
- Detection quality on low-contrast cases (white paper on white desk, folded letters, windowed envelopes, receipts with curl) is unknown; Apple trained on receipts/labels but gives no accuracy numbers.
- Zero shutter lag is excluded when the torch/flash is used; torch-on captures will have normal shutter lag.
- Responsive capture raises peak memory; combined with a 4032×3024 analysis stream this may pressure older devices. Use the second lower-res output.
- WWDC26 session content (iOS 27, 48 MP via balanced, deferred balanced captures on iPhone 16/17) is the newest material; verify shipping behavior in the current SDK.
- Shutter-sound suppression is region-locked; Japan/Korea builds will click.
- Duplicate detection via dHash is layout-sensitive; two different pages of the same form template can collide, and the same page rotated 180° can miss. Text-hash after OCR is the reliable layer.
- Commercial SDK prices beyond Dynamsoft are unknown; Scanbot is now owned by Apryse (July 2025) and licensing may change.
- Android ML Kit showed a production regression from a Play-services update (Sept–Nov 2025), a reminder that Play-delivered flows can break without an app release.
- Deferred photo delivery is all-or-nothing once enabled and proxies must be persisted fast; for documents it may be simpler to disable it and keep `.balanced` 12 MP.

---

## 6. Open questions for the founder

1. Minimum iOS version: 17 (fast capture path) or 18 (Swift Vision API) acceptable? Is an iOS 26-only launch acceptable for layout OCR?
2. Floor device for performance acceptance (iPhone 13 / A15 suggested)?
3. Is 12 MP (≈ 300 dpi over a Letter page at typical handheld distance) sufficient for "print-ready", or is 24/48 MP a requirement despite the multi-second processing cost?
4. Torch policy: never, auto, or user-set? (Glare on glossy mail vs. low-light kitchens.)
5. Should duplicates be dropped silently, linked as versions, or always kept and only flagged?
6. Should the app also accept a stand/overhead mode with a different cadence (page-swap detection) at launch, or handheld only?
7. Budget appetite for a fallback detector license (4–5 figures/yr) if Apple's segmenter proves weak?
8. Android timing: is a CameraX port in scope for v1 of the service, or iOS-only until the capture state machine is proven?
9. Is a camera-shutter click acceptable in regions where suppression is unavailable?

---

## 7. Sources

- Apple, VNDocumentCameraViewController: https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller.md
- Apple, VNDocumentCameraScan: https://developer.apple.com/documentation/visionkit/vndocumentcamerascan.md
- Apple Developer Forums, DTS: no customization of VisionKit scanner (Jan 2025): https://developer.apple.com/forums/thread/772703
- Apple Developer Forums, DTS: Done button race, no processing callback (May 2026): https://developer.apple.com/forums/thread/826935
- Apple Developer Forums, manual button not working: https://developer.apple.com/forums/thread/723143
- Apple, DetectDocumentSegmentationRequest (iOS 18): https://developer.apple.com/documentation/vision/detectdocumentsegmentationrequest.md
- Apple, DetectedDocumentObservation: https://developer.apple.com/documentation/vision/detecteddocumentobservation.md
- Apple, VNDetectDocumentSegmentationRequest (iOS 15): https://developer.apple.com/documentation/vision/vndetectdocumentsegmentationrequest.md
- WWDC21 10041 transcript, Extract document data using Vision: https://nonstrict.eu/wwdcindex/wwdc2021/10041/
- WWDC25 272 transcript, Read documents using the Vision framework: https://nonstrict.eu/wwdcindex/wwdc2025/272/
- Apple, RecognizeDocumentsRequest (iOS 26): https://developer.apple.com/documentation/vision/recognizedocumentsrequest.md
- Apple, DetectLensSmudgeRequest (iOS 26): https://developer.apple.com/documentation/vision/detectlenssmudgerequest.md
- Apple, CalculateImageAestheticsScoresRequest / ImageAestheticsScoresObservation (iOS 18): https://developer.apple.com/documentation/vision/calculateimageaestheticsscoresrequest.md ; https://developer.apple.com/documentation/vision/imageaestheticsscoresobservation.md
- Apple, AVCapturePhotoOutput: https://developer.apple.com/documentation/avfoundation/avcapturephotooutput.md
- Apple, AVCapturePhotoOutput.CaptureReadiness (iOS 17): https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/capturereadiness-swift.enum.md
- Apple, photoProcessingTimeRange: https://developer.apple.com/documentation/avfoundation/avcaptureresolvedphotosettings/photoprocessingtimerange.md
- Apple, deferred photo proxy delegate: https://developer.apple.com/documentation/avfoundation/avcapturephotocapturedelegate/photooutput(_:didfinishcapturingdeferredphotoproxy:error:).md
- WWDC23 10105 transcript, Create a more responsive camera experience: https://nonstrict.eu/wwdcindex/wwdc2023/10105/
- WWDC26 304 transcript, Implement high resolution photo capture: https://nonstrict.eu/wwdcindex/wwdc2026/304/
- Apple Developer Forums, DTS on 4032×3024 video + Vision (Dec 2025): https://developer.apple.com/forums/thread/809719
- iPhone 12 Pro Max AVCaptureDevice format dump: https://zenn.dev/yorifuji/scraps/bc52d2e4601de0
- Apple, Finding the sharpest image (variance of Laplacian sample): https://developer.apple.com/documentation/accelerate/finding-the-sharpest-image-in-a-sequence-of-captured-images.md
- Apple, CMMotionManager: https://developer.apple.com/documentation/coremotion/cmmotionmanager.md
- Apple, isSubjectAreaChangeMonitoringEnabled: https://developer.apple.com/documentation/avfoundation/avcapturedevice/issubjectareachangemonitoringenabled.md
- Apple, setTorchModeOn(level:): https://developer.apple.com/documentation/avfoundation/avcapturedevice/settorchmodeon(level:).md
- Apple, CIPerspectiveCorrection: https://developer.apple.com/documentation/coreimage/ciperspectivecorrection.md ; forum on inputCrop quirk: https://developer.apple.com/forums/thread/705621
- Apple, UINotificationFeedbackGenerator: https://developer.apple.com/documentation/uikit/uinotificationfeedbackgenerator.md
- Metal tile-based Laplacian package: https://pub.dev/documentation/kirz_blurry_image_detector/latest/
- pHash/dHash in Swift guide: https://ssojet.com/dev-guides/phash-in-swift
- Hough-based on-device document localization (iPhone 6 timings): https://arxiv.org/pdf/2106.09987
- Kumar et al., Mobile Video Capture of Multi-page Documents (CVPR-W 2013): https://openaccess.thecvf.com/content_cvpr_workshops_2013/W03/html/Kumar_Mobile_Video_Capture_2013_CVPR_paper.html
- Glare patents: https://patents.google.com/patent/US10630905 ; https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11297248
- Scanbot iOS introduction: https://docs.scanbot.io/ios/document-scanner-sdk/introduction/
- Scanbot autoSnappingSensitivity / delay (Flutter docs mirror native): https://pub.dev/documentation/scanbot_sdk/latest/scanbot_sdk_ui/FinderDocumentScannerConfiguration-class.html ; https://pub.dev/documentation/scanbot_sdk/latest/scanbot.rtu.document/DocumentScannerCameraConfiguration-class.html
- Scanbot glare threshold: https://api-docs.scanbot.io/document-scanner-sdk/android/v9.0.0/-android%20-scanbot%20-s-d-k/io.scanbot.sdk.documentdata/-glare-detection-configuration/index.html
- Scanbot licensing: https://docs.scanbot.io/ios/document-scanner-sdk/detailed-setup-guide/license-handling/
- Apryse acquires Scanbot (2025-07-10): https://apryse.com/blog/apryse-acquires-scanbot-and-accusoft
- Genius Scan SDK v6 quick start: https://geniusscansdk.com/docs/v6/document-scanning/quick-start/ ; v4 iOS API: https://geniusscansdk.com/docs/v4/ios/api ; licensing: https://geniusscansdk.com/license/licensing/ ; demo features: https://github.com/payhawk/geniusscan-sdk-demo
- Dynamsoft pricing: https://www.dynamsoft.com/document-normalizer/ask-for-quote/ ; https://www.dynamsoft.com/mobile-web-capture/ask-for-quote/
- Dynamsoft iOS auto-capture tutorial: https://www.dynamsoft.com/codepool/build-mobile-document-scanner-ios-app.html
- Microblink capture-ios releases: https://github.com/BlinkID/capture-ios/releases
- Anyline pricing listing (third-party): https://www.capterra.com/p/178754/Anyline/
- Nutrient vs Scanbot (no live capture): https://www.nutrient.io/sdk/vs/scanbot/
- ML Kit Document Scanner Android: https://developers.google.com/ml-kit/vision/doc-scanner/android ; pageLimit regression: https://github.com/googlesamples/mlkit/issues/980
- CameraX DocScanner sample: https://github.com/vvkdhkl/DocScanner
- Scanbot, ML Kit vs OpenCV: https://scanbot.io/blog/ml-kit-vs-opencv-document-scanning-software/
- Adobe Scan iOS help (High-Speed Scan): https://www.adobe.com/devnet-docs/adobescan/ios/en/scan.html
- CZUR M3000 Pro V2 listing: https://store.scannx.com/products/czur-m3000-pro-v2
- Ricoh ScanSnap iX2500 vs iX1600: https://www.pfu-us.ricoh.com/blog/ix2500-vs-ix1600
