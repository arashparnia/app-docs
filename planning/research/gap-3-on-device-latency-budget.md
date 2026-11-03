# Gap 3: On-device per-stage latency budget (A15 floor through A19), image feeds, and thermal policy

Research date: 2026-11-03. Dimension: measured per-stage latencies for the capture → dedup → OCR pipeline on iPhone 13 (A15) through iPhone 17 Pro (A19 Pro), which image feeds each stage, what "captured + deduped" can be declared at, and how the pipeline must degrade as `ProcessInfo.thermalState` / `AVCaptureDevice.systemPressureState` rise with the torch on.

Method note: the shared web-search budget for this run was exhausted before this dimension started, so every finding comes from direct fetches of primary sources (Apple doc JSON, the iOS 18/26 SDK headers for AVFoundation, WWDC transcripts, the text_sight benchmark repo, Wikipedia chip pages). Every number is labelled **measured** (someone published a measurement on hardware), **vendor statement** (Apple's words, no number), or **estimate** (my derivation; must be verified on device). Where nothing exists the report says "unknown". The budget table in section 4 is a plan for the measurement harness, not a result.

## 1. Executive summary

1. There is still **no Apple-published latency for any Vision request or for shutter-to-delegate time**; the only on-device measurements that exist are from the text_sight Flutter plugin on an **iPhone 16 (A18)**: one-shot `RecognizeTextRequest` p50 on a 63-line page is **101 ms (.fast), 199 ms (.fast + language correction), 404 ms (.accurate), 736 ms (.accurate + correction)**; the one-shot input resolution is *not stated*, and live runs use 1080x1920 frames (fast 19/s, accurate 5/s). The "~400 ms" figure the earlier reports built budgets on is this 404 ms number, not a full-resolution page time.
2. Full-resolution (12 MP) `.accurate` OCR / `RecognizeDocumentsRequest` latency is **unknown** and, by pixel count (5.9x more than 1080x1920) and silicon scaling (A15 Neural Engine 15.8 TOPS vs A18 35 TOPS), is plausibly **1-3 s on A18 and 2-6 s on A15** (estimate). It cannot sit on the feedback path on any device.
3. The only stage with authoritative timing on the capture side is the camera: at 30 fps a frame is 33 ms; before responsive capture the WWDC23 demo managed "about two photos per second" (12 MP); 48 MP "processing can take several seconds" (WWDC26); Lux measured **up to 4 s between 48 MP ProRAW captures on iPhone 14 Pro**.
4. The SDK header settles two gap questions: **24 MP is "only serviced as 24MP via deferred photo delivery"** (so with deferred delivery off, a 24 MP request yields 12 MP), and deferred proxies can only be finalized by ingesting them into the Photos library via `PHAssetResourceTypePhotoProxy`. Zero shutter lag is excluded by the header only for manual exposure and bracketed capture (WWDC23 adds flash and constituent delivery); **whether ZSL serves a 48 MP request is not documented** and is likely "no" because the ring buffer holds binned preview-rate sensor frames (inference).
5. 12 MP already yields ~345-365 dpi on a Letter/A4 page that fills the frame, so the archival-quality requirement does not force 24/48 MP; the acceptance-floor iPhone 13 is 12 MP only anyway.
6. `DetectLensSmudgeRequest` (iOS 26, A14+) is documented to misclassify motion blur as smudge, so it must run on the captured still, not on handheld preview frames; latency unknown.
7. Thermal policy now has an authoritative skeleton: `AVCaptureSystemPressureLevel` serious = "frame rate throttling is advised", critical = "highly advised", shutdown = session interrupted; `ProcessInfo.thermalState` critical = "stop using peripherals such as the camera"; torch max level drops below 1.0 "under thermal duress". Sustained-throughput numbers over 100-200 pages are **unknown anywhere**; Xcode can simulate fair/serious/critical as a floor.
8. Recommendation: declare "captured" when the 12 MP still's bytes are durably on disk (target <300 ms after the stability decision with ZSL + responsive capture; measure), announce "already scanned" from a visual-tier verdict (dHash + feature print / MobileCLIP, tens of ms, estimate) and confirm or retract it from the text tier within ~1-2 s; every OCR stage is asynchronous.

## 2. Findings

### 2a. What is actually measured on an iPhone (and at what input size)

| Stage | Device | Input | Number | Status | Source |
|---|---|---|---|---|---|
| `RecognizeTextRequest .fast` one-shot | iPhone 16 (A18), profile build | 63-line page, resolution not stated | p50 101 ms | measured | https://github.com/LahaLuhem/text_sight/blob/main/doc/performance.md |
| `.fast` + `usesLanguageCorrection` | same | same | p50 199 ms | measured | same |
| `.accurate` one-shot | same | same | p50 404 ms | measured | same |
| `.accurate` + correction | same | same | p50 736 ms | measured | same |
| `.fast` live | same | 1080x1920 camera frames | 19.0 captures/s (9 lines read); earlier run 30/s camera-bound before a small-text bug was fixed | measured | same; https://pub.dev/documentation/text_sight/0.2.2/ |
| `.accurate` live | same | 1080x1920 | 5.0 captures/s (15 lines); earlier run 4.0/s | measured | same |
| Dense page | same | 127-line page at 15.8 pt | neither level reads it at 1080p, "those timings measure a miss" | measured | same |
| Camera frame interval | any | 30 fps | 33 ms | vendor | https://nonstrict.eu/wwdcindex/wwdc2023/10105/ |
| Shot-to-shot, no responsive capture | WWDC23 demo device (unnamed) | 12 MP | "about two photos per second" | vendor demo | same |
| 48 MP ProRAW shot-to-shot | iPhone 14 Pro | 48 MP | "a 4-second delay between captures"; 48 MP direct-to-JPEG "significantly faster" (no number) | measured (journalist) | https://www.lux.camera/iphone-14-pro-camera-review-a-small-step-a-huge-leap/ |
| 24/48 MP processing | iPhone 14 Pro+ | 24/48 MP | "This processing can take several seconds" | vendor | https://nonstrict.eu/wwdcindex/wwdc2026/304/ |
| MobileCLIP-S0 image encoder | iPhone 12 Pro Max | 256x256 | 1.5 ms | measured (paper) | see dedup.md; https://arxiv.org/html/2311.17049v2 |
| `DetectDocumentSegmentationRequest` | any | any | "can run in realtime on a camera or video feed" on devices with a Neural Engine; not realtime on GPU/CPU | vendor | https://nonstrict.eu/wwdcindex/wwdc2021/10041/ |
| `GenerateImageFeaturePrintRequest` | any | any | no number | unknown | https://developer.apple.com/documentation/vision/generateimagefeatureprintrequest |
| `DetectLensSmudgeRequest` | A14+ | any | no number | unknown | https://developer.apple.com/documentation/vision/detectlenssmudgerequest |
| `RecognizeDocumentsRequest` | iOS 26 | any | no number | unknown | https://developer.apple.com/documentation/vision/recognizedocumentsrequest |
| `CIPerspectiveCorrection` on 12 MP | any | 4032x3024 | no number | unknown | https://developer.apple.com/documentation/coreimage/ciperspectivecorrection |

Important caveats from the text_sight authors themselves: "Phones boost when cool, so the settled numbers are a floor. A short scan feels faster", and language correction "roughly doubles the time on iOS". The live `.fast` figure fell from 30/s to 19/s once a Vision setting that skipped small text (<1/32 of image height) was pinned off, which is exactly the setting a document scanner must disable. So the headline "fast keeps up with 30 fps" in earlier reports overstates throughput on real pages.

### 2b. Scaling the one measurement to the A15 floor and to full resolution

Apple Neural Engine ratings (vendor marketing TOPS, precision not consistently stated across generations, so treat ratios as rough): A15 **15.8 TOPS**, A16 **17 TOPS**, A17 Pro **35 TOPS**, A18/A18 Pro **35 TOPS**, A19/A19 Pro **35 TOPS** with new GPU "Neural Accelerators" (Apple claims up to 4x peak GPU compute on A19 Pro vs A18 Pro). Sources: https://en.wikipedia.org/wiki/Apple_A15 , https://en.wikipedia.org/wiki/Apple_A16 , https://en.wikipedia.org/wiki/Apple_A17 , https://en.wikipedia.org/wiki/Apple_A18 , https://en.wikipedia.org/wiki/Apple_A19 . Geekbench AI per-device scores could not be fetched (HTTP 403).

Derived estimates (all **estimate**, to be replaced by harness numbers):

- A15 vs A18 Neural Engine: ~2.2x slower by TOPS. Vision's text recognizer is NE-bound (WWDC19: accurate "needs a deep learning model"), so expect `.accurate` one-shot at the text_sight input size of **~0.9-1.2 s on iPhone 13**.
- Full-resolution input: 4032x3024 = 12.2 MP is 5.9x the pixels of 1080x1920. Vision's detector runs at an internal resolution and the recognizer cost scales with the number of text lines, not pixels, so cost grows sub-linearly with pixels but linearly with page density. A dense full-page letter (40-60 lines, 9-11 pt type) at 12 MP is plausibly **1-3 s `.accurate` on A18, 2-6 s on A15**. `RecognizeDocumentsRequest` adds table/list/data-detector passes on top; assume >= `.accurate`.
- `.fast` on a rectified page downscaled to ~2-3 MP: **150-300 ms on A18, 300-600 ms on A15**. Marginal for a 300-500 ms feedback path on A15; fine for a 1 s path.
- Document segmentation per preview frame: Apple says real-time on the NE; the model is a low-resolution mask network, so **10-30 ms on A15, 5-15 ms on A17+** is the working assumption. Nobody has published this.
- Feature print: unknown; MobileCLIP-S0 at 1.5 ms (measured, iPhone 12 Pro Max, A14) is the lower bound for an embedding; Vision feature print is a larger network, assume 5-20 ms.
- `CIPerspectiveCorrection` + HEIC encode of 12 MP on the GPU/media engine: 50-150 ms.

These should be read as "what order of magnitude to plan the state machine around", not budgets.

### 2c. Camera stage: 12 vs 24 vs 48 MP, ZSL, responsive capture, deferred delivery (authoritative header text)

From `AVCapturePhotoOutput.h` (iOS 26 SDK, mirrored at https://raw.githubusercontent.com/xybp888/iOS-SDKs/master/iPhoneOS26.0.sdk/System/Library/Frameworks/AVFoundation.framework/Headers/AVCapturePhotoOutput.h ; identical wording in the iOS 18 header):

- `zeroShutterLagEnabled`: "For apps linked on or after iOS 17 zero shutter lag is automatically enabled when supported. Enabling zero shutter lag reduces or eliminates shutter lag when using AVCapturePhotoQualityPrioritizationBalanced or Quality at the cost of additional memory usage by the photo output. The timestamp of the AVCapturePhoto may be slightly earlier than when -capturePhotoWithSettings:delegate: was called. ... Zero shutter lag isn't available when using manual exposure or bracketed capture."
- `zeroShutterLagSupported`: "When switching cameras or formats, setting depthDataDeliveryEnabled, or setting virtualDeviceConstituentPhotoDeliveryEnabled this property may change." (Nothing about `maxPhotoDimensions`.)
- `responsiveCaptureSupported`: "Enabling responsive capture increases peak and sustained capture rates, and reduces shutter lag at the cost of additional memory usage ... Responsive capture is only supported when zero shutter lag is enabled."
- `responsiveCaptureEnabled`: "Responsive capture adds buffering between the capture and photo processing stages"; overlap is disabled when requesting uncompressed `kCVPixelBufferPixelFormatTypeKey` output (so request HEIC/JPEG, not raw pixel buffers, for the archival still).
- `fastCapturePrioritizationSupported`: "allows capture quality to be automatically reduced from the selected AVCapturePhotoQualityPrioritization to ensure the photo output can keep up when captures are requested in rapid succession ... only when responsiveCaptureEnabled is YES."
- `maxPhotoDimensions` (output): "Note: When supported, the 24MP setting (5712, 4284) is only serviced as 24MP when opted-in to autoDeferredPhotoDeliveryEnabled." Capture rules: "The maxPhotoDimensions setting for 24MP (5712, 4284), when supported, is only serviced as 24MP via deferred photo delivery."
- `AVCaptureDeferredPhotoProxy`: "This object represents intermediate data that can be rendered into a final image and ingested into the user's photo library via PHAsset APIs. The intermediate data are not accessible by the calling process. Use a PHAssetCreationRequest with a resourceType of PHAssetResourceTypePhotoProxy ... Image processing to finalize the asset will occur either on-demand ... or will execute in the background when the system has determined that it's a good time to process based on thermals, battery level, and other conditions."
- `captureReadiness`: "Capturing only when the output is ready limits the number of requests inflight to minimize shutter lag while maintaining the fastest shot to shot time ... The output continues to accept requests when the captureReadiness property returns a value other than Ready, but the request may not be serviced for a longer period." Cases: `ready`, `notReadyMomentarily`, `notReadyWaitingForCapture`, `notReadyWaitingForProcessing`, `sessionNotRunning` (https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/capturereadiness-swift.enum).
- `photoProcessingTimeRange` (iOS 13+): `.start` is the minimum, `.start + .duration` the maximum expected processing time for this photo; "Consider implementing a UI affordance if the max processing time is uncomfortably long" (https://developer.apple.com/documentation/avfoundation/avcaptureresolvedphotosettings/photoprocessingtimerange). This is the only runtime latency oracle Apple gives; log it per capture.
- `photoQualityPrioritization`: default `.balanced`; quality techniques "can take significant processing time before the system returns a photo" (https://developer.apple.com/documentation/avfoundation/avcapturephotosettings/photoqualityprioritization).

From WWDC26 session 304 (https://nonstrict.eu/wwdcindex/wwdc2026/304/): 12 MP available at speed/balanced/quality; **48 MP is a single-frame capture at balanced or quality**; **24 MP is multi-frame fused, quality only**; only the `.photo` preset supports 24/48 MP; "This processing can take several seconds"; deferred processing shortens the blocking stage so shot-to-shot drops, but "does not reduce the per-photo processing time"; from iOS 27 on iPhone 16/17, balanced fast captures are also deferred. 48 MP exists from iPhone 14 Pro; 24 MP from iPhone 15 (main camera).

From WWDC23 session 10105 (https://nonstrict.eu/wwdcindex/wwdc2023/10105/): ZSL "keeps a rolling ring buffer of frames from the past"; excluded for flash, manual exposure, bracketed captures and constituent photo delivery; responsive capture and fast-capture prioritization need A12+; deferred delivery needs iPhone 11 Pro+; "I can capture about two photos per second" before enabling the features; the transcript gives no post-feature number.

Does ZSL apply to 48 MP? **Unknown, not documented.** Inference: the ring buffer is fed by the sensor's streaming (binned, 12 MP-class) frames, while a 48 MP capture is a separate full-resolution readout, so a 48 MP request most likely cannot be served from the buffer and incurs a full readout plus "several seconds" of processing. The test is trivial: set `maxPhotoDimensions` to the 48 MP entry, read `isZeroShutterLagSupported`, then compare `AVCapturePhoto.timestamp` with the `capturePhoto` call time (ZSL yields an earlier timestamp per the header).

Consequences for this app:
- **12 MP is the only resolution compatible with a sub-second handheld loop** and with a private (non-Photos) archive: 24 MP forces deferred delivery and Photos ingestion; 48 MP forces multi-second processing and probably forfeits ZSL.
- 12 MP is sufficient for archival: a Letter page filling the 4032x3024 frame is 4032/11.0 = **367 dpi** on the long edge and 3024/8.5 = 356 dpi on the short edge; A4 gives 4032/11.69 = **345 dpi**. A 48 MP option can remain as a stand-mounted "archival quality" mode.
- The acceptance-floor iPhone 13 is 12 MP only, so the floor path is the same path shipped everywhere.

### 2d. Which image feeds each stage

Per Apple DTS (Dec 2025, https://developer.apple.com/forums/thread/809719): "you can stream video buffers through the AVCaptureVideoDataOutput at 4032x3024 on most cameras. Whether vision is able to keep up with 30 fps @ 12 MP is a different story ... you could always use a second VideoDataOutput sourcing from the same camera and request a lower resolution and run that through Vision ... Most models internally run at a lower resolution anyway."

| Stage | Feed | Rationale |
|---|---|---|
| `DetectDocumentSegmentationRequest` (every frame or every 2nd) | Low-res `AVCaptureVideoDataOutput`, 420v, ~1280x960 or 1920x1440 | Model uses a low-res mask internally (WWDC21); keeps NE time small on A15 |
| Sharpness (Laplacian variance), glare, gyro | Same low-res luma plane + Core Motion | <5 ms with vDSP (estimate) |
| Frame-to-frame page identity (dHash 64-bit) | Perspective-corrected 32x32 gray from the low-res frame | <1 ms (estimate); drives "same sheet still in view" |
| `AVCapturePhotoOutput` still | `.photo` preset, 12 MP, `.balanced`, ZSL + responsive on, deferred off, HEIC/JPEG (not uncompressed) | Keeps overlap enabled; archival |
| `DetectLensSmudgeRequest` | The captured still (or its 1-2 MP downscale) | Apple: motion blur can be classified as smudge; "use a request on a fixed capture where the device is stable" |
| Feature print / MobileCLIP-S0 | Rectified page downscaled (Vision scales internally; S0 is 256x256) | Candidate dedup filter |
| `CIPerspectiveCorrection` | Full 12 MP still, quad re-detected on the still (not the preview quad) | Preview quad is from a different, lower-res frame |
| `RecognizeTextRequest .fast` (dedup text signal) | Rectified page at ~2-3 MP, `minimumTextHeightFraction` lowered, correction off | Correction doubles time; small-text skip must be off |
| `RecognizeTextRequest .accurate` / `RecognizeDocumentsRequest` (archive text layer) | Full-res rectified page | Only place full resolution pays off (small print) |

### 2e. Thermal, system pressure, and torch (authoritative text)

`AVCaptureSystemPressure.h` (iOS 18 SDK, https://raw.githubusercontent.com/xybp888/iOS-SDKs/master/iPhoneOS18.0.sdk/System/Library/Frameworks/AVFoundation.framework/Headers/AVCaptureSystemPressure.h):
- Nominal: "System pressure level is normal (not pressured)."
- Fair: "System pressure is slightly elevated."
- Serious: "System pressure is highly elevated. Capture performance may be impacted. Frame rate throttling is advised."
- Critical: "System pressure is critically elevated. Capture quality and performance are significantly impacted. Frame rate throttling is highly advised."
- Shutdown: "System pressure is beyond critical. Capture must immediately stop."
- Factors: `SystemTemperature`, `PeakPower` ("peak power requirements exceed the battery's current capacity and may result in a system power off"), `DepthModuleTemperature`, `CameraTemperature` ("the camera module is operating at an elevated temperature").

`AVCaptureDevice.systemPressureState` (iOS 11.1+): "When system pressure reaches AVCaptureSystemPressureLevelShutdown, the capture device cannot continue to provide input, so the AVCaptureSession becomes interrupted until the pressured state abates. System pressure can be effectively mitigated by lowering the device's activeVideoMinFrameDuration ... Clients are encouraged to implement frame rate throttling." The doc page adds: "Under less heavy pressure, the system may automatically reduce capture quality." (https://developer.apple.com/documentation/avfoundation/avcapturedevice/systempressurestate-swift.class)

Torch: `AVCaptureMaxAvailableTorchLevel`: "Under thermal duress, the maximum available torch level may be less than 1.0"; `setTorchModeOn(level:)`: "The specified value may not be available if the iOS device is too hot." (https://developer.apple.com/documentation/avfoundation/avcapturedevice/maxavailabletorchlevel and the header). Depth delivery "may increase the system load, resulting in a reduced video frame rate for thermal sustainability" (header) - do not enable depth.

`ProcessInfo.thermalState` (Apple energy guide, https://developer.apple.com/library/archive/documentation/Performance/Conceptual/power_efficiency_guidelines_osx/RespondToThermalStateChanges.html): serious = "reduce CPU usage; reduce GPU usage; reduce I/O; reduce frame rates; use lower-quality visual effects"; critical = "reduce usage of the CPU, GPU, and I/O to the absolute minimum ... stop using peripherals, such as the camera." WWDC19 session 422 (https://nonstrict.eu/wwdcindex/wwdc2019/422/): at fair iOS pauses discretionary work such as photos analysis; at serious the system lowers the frame rate of ARKit and FaceTime and "system performance will be impacted"; demo frame rate fell to 17 fps at serious without mitigation. Xcode Devices window can simulate fair/serious/critical; the device ramps through states in roughly 10 s steps; the simulated condition is a floor (real heating can push it to critical).

What is **unknown**: how much the Neural Engine, ISP, and GPU are clocked down at each state on A15 vs A19; how many minutes of 30 fps preview + NE segmentation + torch + per-page OCR it takes an iPhone 13 to reach serious; whether OCR throughput at serious is 1.5x or 3x slower. No published measurement exists; the text_sight note that settled numbers are "a floor" because "phones boost when cool" is the only hint that the first pages of a session will be faster than page 100.

### 2f. Smudge detection specifics

`DetectLensSmudgeRequest`: iOS 26.0+, "requires a device with A14 Bionic and later or device with M1 and later"; returns `SmudgeObservation.confidence` 0.0-1.0; Apple's example threshold is 0.9; "Certain types of content may be categorized as a smudge, such as naturally-blurred objects, long exposure, and motion blur while taking a photo. Make sure that you are using a request on a fixed capture where the device is stable." (https://developer.apple.com/documentation/vision/detectlenssmudgerequest). iPhone 13 (A15) qualifies. It is a per-still quality gate, not a per-frame one; run it off the feedback path and use it to trigger a "wipe your lens" hint after N consecutive high-confidence stills.

### 2g. OS floor

iOS 26 (released 2025-09-15) and iOS 27 (2026-09-14) both support iPhone 11 / A13 and later with no devices dropped (https://en.wikipedia.org/wiki/IOS_26 , https://en.wikipedia.org/wiki/IOS_27). So an iOS 26 minimum gives `RecognizeDocumentsRequest` and `DetectLensSmudgeRequest` on the A15 floor; the Swift Vision API (`DetectDocumentSegmentationRequest`, `GenerateImageFeaturePrintRequest`) is iOS 18+.

## 3. Options compared

### 3a. Still resolution and capture mode

| Option | Shot-to-shot / delivery | ZSL | Private archive OK | dpi on Letter | Devices | Verdict |
|---|---|---|---|---|---|---|
| 12 MP, `.balanced`, ZSL + responsive, deferred off | ~2 photos/s baseline (WWDC23 demo); better with responsive capture (no number) | Yes (auto on iOS 17+) | Yes | ~360 | All, incl. iPhone 13 | **Default** |
| 12 MP, `.speed` | Fastest delivery (vendor) | Yes | Yes | ~360 | All | Fallback under thermal pressure |
| 24 MP (`.quality` only) | Multi-frame; "several seconds"; only honored with deferred delivery | n/a | **No** (proxy must go to Photos) | ~510 | iPhone 15+ | Reject |
| 48 MP (`.balanced`/`.quality`) | "several seconds"; up to 4 s measured for ProRAW on 14 Pro | Unknown, likely no | Yes | ~720 | iPhone 14 Pro+ | Optional stand-mounted "archival" mode only |

### 3b. Where to declare "captured" and "already scanned"

| Tier | Signal | Est. time after stability decision (A18 / A15) | Can it be the declaration point? |
|---|---|---|---|
| T0 | Best sharp low-res video frame cached in RAM | 0 ms | No (RAM only; not durable) |
| T1 | 12 MP still delivered + atomic write + SHA-256 row | ~100-300 ms / ~150-400 ms (estimate) | **Yes: "captured"** |
| T2 | dHash + feature print/MobileCLIP vs recent pages | +5-30 ms / +10-60 ms (estimate) | **Yes: provisional "already scanned?"** |
| T3 | `.fast` OCR on ~2-3 MP rectified page + SimHash + numeric tokens | +150-300 ms / +300-600 ms (estimate) | Confirms/retracts T2 within ~0.5-1 s |
| T4 | `.accurate` / `RecognizeDocumentsRequest` on full-res page | +1-3 s / +2-6 s (estimate) | Never on the feedback path; archive text layer |
| T5 | Claude Haiku classification/extraction | +1-4 s cloud | Async |

## 4. Recommendation for this project

1. **Declare "captured" at T1**: the moment `didFinishProcessingPhoto` bytes (HEIC/JPEG, 12 MP) are atomically on disk with a hash row. Target <300 ms from the stability decision on A17+ and <500 ms on A15; if the still is slower than that on A15 (measure), fall back to writing the best cached 4032x3024 video frame first and swapping in the still when it lands, so the haptic never waits on the ISP. Never use 24 MP (it silently becomes 12 MP without deferred delivery, and with it the data goes to Photos) and keep 48 MP behind a stand-mode setting with `photoProcessingTimeRange` shown as a progress affordance.

2. **Announce "already scanned" in two beats**: a visual-tier verdict (T2) within ~50 ms of the still landing, shown as a soft chip plus distinct haptic, then the text-tier confirmation (T3) within ~1 s on A15 that either hardens the chip or retracts it. OCR-based dedup cannot be instant on A15; visual-tier dedup can. The earlier dedup report's "<100 ms including fast OCR" holds only on A17+ with a small input; on A15 plan for 300-600 ms for the text signal.

3. **Everything from T4 onward is asynchronous and queue-based**: `.accurate`/`RecognizeDocumentsRequest` on the full-res page, PDF assembly, upload, Claude. On A15 the OCR queue will fall behind a 20 pages/min operator (2-6 s per page vs 3 s per page arrival); that is acceptable because "captured" does not depend on it, but the UI must show the backlog and the app must finish it in `BGProcessingTask` if the user quits.

4. **Feed sizes**: segmentation and all per-frame gates on a second low-res `AVCaptureVideoDataOutput` (1280x960 to 1920x1440); smudge, feature print and fast OCR on the rectified still downscaled to 1-3 MP; only accurate OCR sees 12 MP. Disable language correction on the dedup pass (2x cost) and lower `minimumTextHeightFraction` so small print is not skipped.

5. **Thermal/torch policy** (observe both `AVCaptureDevice.systemPressureState` and `ProcessInfo.thermalState`):
   - Nominal: preview 30 fps, segmentation every frame, torch on demand at <= 0.5 level (only when ISO/exposure indicates low light), background accurate OCR runs concurrently with capture.
   - Fair: segmentation every 2nd frame (15 Hz), pause background accurate OCR and PDF rendering while the camera is live (resume between pages or after the session), torch capped at 0.3.
   - Serious: preview `activeVideoMinFrameDuration` to 15-20 fps, torch off (prompt for room light), stills at `.speed`, all T4+ work deferred until the session ends or the device is on charge.
   - Critical: stop the session with a clear "device too hot, pausing capture" message; resume automatically at serious/fair.
   - Shutdown: handled as a session interruption; nothing is lost because every page was written at T1.
   - Always read `AVCaptureDevice.maxAvailableTorchLevel` before `setTorchModeOn(level:)` and treat a drop as an early thermal signal.

6. **Measurement harness is the first engineering deliverable**, before any budget is written into the plan: `OSSignposter` intervals for every stage in section 3b, `photoProcessingTimeRange` logged per capture, thermal and pressure states logged every second, torch level, battery. Golden run: 200 real pages, handheld, 20 pages/min, on iPhone 13, iPhone 15 Pro, iPhone 16, iPhone 17 Pro, cold and after 10 minutes of preheating; repeat with Xcode's serious thermal simulation as a floor. Report p50/p95 per stage per device and the page index at which each device first reports fair/serious. This replaces every estimate in this report.

7. **Model tiering later**: if A15 `.fast` OCR for dedup exceeds ~600 ms in the harness, move the text signal off Vision and onto a distilled document embedding (MobileCLIP-S0 image tower fine-tuned on re-photo pairs, 1.5 ms measured on A14), making dedup purely visual and instant on every device.

## 5. Risks and unknowns

- All per-stage numbers for Vision requests on iPhone are estimates derived from one third-party measurement on an iPhone 16 at an unstated one-shot resolution; the A15 numbers could be 2x off in either direction.
- 48 MP + ZSL behaviour is undocumented; the inference that ZSL does not apply must be tested.
- Sustained-session thermal behaviour (pages until serious, NE slowdown factor) is unmeasured anywhere; iPhone 13 with torch on could reach serious in minutes.
- The responsive-capture shot-to-shot improvement has no number from Apple; the "2 photos/s" baseline is a demo on an unnamed device.
- `RecognizeDocumentsRequest` could be materially slower than `.accurate` because of table/list/data-detector passes; if it exceeds ~5 s on A15 the PDF text layer should come from `.accurate` instead.
- Memory: ZSL + responsive capture raise peak memory (header); combined with a 12 MP Core Image pipeline and Vision this may pressure 4 GB devices (iPhone 13) during long sessions.
- Geekbench AI per-device NE scores could not be retrieved (403); the TOPS ratios used are marketing numbers with inconsistent precision bases.

## 6. Open questions for the founder

1. Is an iPhone 13 at 12 MP (~360 dpi on Letter) acceptable as the quality floor, so 48 MP stays an optional stand-mounted mode?
2. Is a two-beat "already scanned" (instant visual guess, text confirmation within ~1 s) acceptable, or must the first announcement already be text-confirmed (which rules out sub-second on A15)?
3. Is a visible OCR backlog during fast sessions acceptable on older devices, given "captured" is already durable?
4. May the app refuse to use the torch (and ask for room light) once the device reports fair, to extend session length?
5. Which four devices can be dedicated to the two-week measurement harness (iPhone 13, 15 Pro, 16, 17 Pro suggested)?
6. Should iOS 26 be the minimum (needed for `RecognizeDocumentsRequest` and smudge detection), accepting that iOS 18/25-era devices are excluded?

## 7. Sources

- text_sight performance doc (iPhone 16 measurements): https://github.com/LahaLuhem/text_sight/blob/main/doc/performance.md
- text_sight README / pub.dev: https://github.com/LahaLuhem/text_sight ; https://pub.dev/documentation/text_sight/0.2.2/ ; https://pub.dev/packages/text_sight/versions/0.2.1
- AVCapturePhotoOutput.h, iOS 26 SDK mirror: https://raw.githubusercontent.com/xybp888/iOS-SDKs/master/iPhoneOS26.0.sdk/System/Library/Frameworks/AVFoundation.framework/Headers/AVCapturePhotoOutput.h
- AVCaptureDevice.h, iOS 18 SDK mirror: https://raw.githubusercontent.com/xybp888/iOS-SDKs/master/iPhoneOS18.0.sdk/System/Library/Frameworks/AVFoundation.framework/Headers/AVCaptureDevice.h
- AVCaptureSystemPressure.h, iOS 18 SDK mirror: https://raw.githubusercontent.com/xybp888/iOS-SDKs/master/iPhoneOS18.0.sdk/System/Library/Frameworks/AVFoundation.framework/Headers/AVCaptureSystemPressure.h
- Apple, systemPressureState: https://developer.apple.com/documentation/avfoundation/avcapturedevice/systempressurestate-swift.class
- Apple, SystemPressureState.Level: https://developer.apple.com/documentation/avfoundation/avcapturedevice/systempressurestate-swift.class/level-swift.struct
- Apple, CaptureReadiness: https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/capturereadiness-swift.enum
- Apple, photoProcessingTimeRange: https://developer.apple.com/documentation/avfoundation/avcaptureresolvedphotosettings/photoprocessingtimerange
- Apple, photoQualityPrioritization: https://developer.apple.com/documentation/avfoundation/avcapturephotosettings/photoqualityprioritization
- Apple, maxPhotoDimensions (settings): https://developer.apple.com/documentation/avfoundation/avcapturephotosettings/maxphotodimensions
- Apple, maxAvailableTorchLevel: https://developer.apple.com/documentation/avfoundation/avcapturedevice/maxavailabletorchlevel
- Apple, DetectLensSmudgeRequest: https://developer.apple.com/documentation/vision/detectlenssmudgerequest
- Apple, DetectDocumentSegmentationRequest: https://developer.apple.com/documentation/vision/detectdocumentsegmentationrequest
- Apple, GenerateImageFeaturePrintRequest: https://developer.apple.com/documentation/vision/generateimagefeatureprintrequest
- Apple, Recognizing text in images: https://developer.apple.com/documentation/vision/recognizing-text-in-images
- Apple, ProcessInfo.ThermalState: https://developer.apple.com/documentation/foundation/processinfo/thermalstate-swift.enum
- Apple energy guide, thermal state table: https://developer.apple.com/library/archive/documentation/Performance/Conceptual/power_efficiency_guidelines_osx/RespondToThermalStateChanges.html
- Apple DTS on 4032x3024 video + Vision: https://developer.apple.com/forums/thread/809719
- WWDC23 10105 transcript (ZSL, responsive capture, deferred): https://nonstrict.eu/wwdcindex/wwdc2023/10105/
- WWDC26 304 transcript (12/24/48 MP): https://nonstrict.eu/wwdcindex/wwdc2026/304/
- WWDC21 10041 transcript (document segmentation): https://nonstrict.eu/wwdcindex/wwdc2021/10041/
- WWDC19 234 transcript (text recognition fast vs accurate): https://nonstrict.eu/wwdcindex/wwdc2019/234/
- WWDC19 422 transcript (thermal states, Xcode simulation): https://nonstrict.eu/wwdcindex/wwdc2019/422/
- Lux, iPhone 14 Pro camera review (48 MP delay): https://www.lux.camera/iphone-14-pro-camera-review-a-small-step-a-huge-leap/
- Wikipedia chip pages: https://en.wikipedia.org/wiki/Apple_A15 ; https://en.wikipedia.org/wiki/Apple_A16 ; https://en.wikipedia.org/wiki/Apple_A17 ; https://en.wikipedia.org/wiki/Apple_A18 ; https://en.wikipedia.org/wiki/Apple_A19
- Wikipedia iOS 26 / iOS 27 device support: https://en.wikipedia.org/wiki/IOS_26 ; https://en.wikipedia.org/wiki/IOS_27
- MobileCLIP paper (1.5 ms S0 on iPhone 12 Pro Max): https://arxiv.org/html/2311.17049v2
