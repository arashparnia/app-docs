# Gap 9: Print-ready page geometry, effective DPI, enhancement pipeline and the PDF/A writer

Dimension: what capture resolution and enhancement chain actually yields a print-ready archival PDF from a handheld photo; how physical page size (MediaBox) is inferred with no scale reference; orientation when the phone points straight down; which capture/enhancement steps are needed and what they cost; in-house PDF/A writer vs Core Graphics plus a post-pass. Research date: 2026-11-03. Note: the shared web-search budget was exhausted before this run, so every finding comes from directly fetched primary sources (Apple JSON doc endpoints, the iOS 16.5 SDK header mirror, FADGI 2023 PDF, vendor docs, GitHub, arXiv) or from the earlier reports in this folder. Items I could not source are marked **unknown** or **(memory, verify)**.

## 1. Executive summary

1. "Print-ready" has a number: FADGI 2023 "Modern Textual Records" requires **>= 294 ppi (300 ppi minus 2 %)**, 8- or 16-bit, grey or colour, sRGB acceptable, PDF/A acceptable as a master. 12 MP (4032 px long axis) hits 294 ppi on Letter **only if the page fills >= 82 % of the frame's long axis** (87 % for A4; Legal cannot reach it at all). At the realistic 55-70 % handheld framing, 12 MP gives **200-260 ppi** on Letter (FADGI 2-star territory), 24 MP gives 290-360 ppi and 48 MP 400-510 ppi. The three earlier reports disagreed because each assumed a different framing, not because any of them was wrong about the sensor.
2. 24 MP is not a usable middle ground: Apple's header says 24 MP is only serviced via deferred photo delivery, whose proxies can only be finalised by ingesting into Photos (gap-3). 48 MP is a single-frame capture but "can take several seconds" of processing (WWDC26). So the practical choice is **12 MP + a framing gate** for handheld, and **48 MP only in stand mode**.
3. The framing gate is the real lever: the auto-capture state machine should simply not fire until the detected quad's long side is >= ~0.78 of the frame's long axis (for Letter/A4-class pages). The user still does nothing except move the phone; the preview rectangle does the teaching. At 24-26 mm equivalent focal length that is a 23-25 cm working distance, comfortably above the main camera's close-focus limit (Apple does not publish the number; `minimumFocusDistance` returns it in mm at runtime).
4. Page size cannot be read from a photo; it must be inferred. The ranked signals are: rectified-quad aspect ratio (Letter 1.294 vs A4 1.414 vs Legal 1.647 vs #10 envelope 2.30 vs DL 2.00 are all separable; the A-series are self-similar so A4/A5/C5 are not), locale prior (US/Canada = Letter, everywhere else = A4), text line height from Vision boxes (resolves the 2x A4/A5 ambiguity and receipts: 80 mm thermal paper prints 42/48/56 columns at 180 dpi), LiDAR depth plus camera intrinsics on Pro models (metric), and the document class Claude returns (IRS forms are Letter). MediaBox is just two numbers written at PDF time, so a late signal can still be used.
5. Orientation when the phone points straight down: `AVCaptureDevice.RotationCoordinator` is defined "relative to gravity"; Apple's docs say nothing about the flat case, and the gravity vector then carries no in-plane information. Use the prior "phone top = page top" (true for a reader holding the phone naturally), the quad aspect for portrait/landscape, and a two-way (or four-way) `.fast` OCR confidence vote on a ~1000 px thumbnail (measured 101 ms per pass on A18) to settle it before the archival encode. Store pixels upright, `/Rotate 0`.
6. Capture settings that are cheap and matter: `setExposureTargetBias` (+0.7 to +1.3 EV for white paper, rule of thumb), `activeMaxExposureDuration` capped around 1/120-1/200 s to stop handheld blur, `autoFocusRangeRestriction = .near` (Apple: "faster, more power efficient, and less error prone"), `isSmoothAutoFocusEnabled = false`, gate on `isAdjustingFocus == false`, keep `isGeometricDistortionCorrectionEnabled` (default true), lock white balance per batch with `setWhiteBalanceModeLocked`.
7. Enhancement: perspective warp -> Lanczos downsample to the target ppi -> orientation -> `CIDocumentEnhancer` (Apple: "Adjusts an image's shadows and contrast", `amount` undocumented range) or a custom background-division kernel -> unsharp -> mode decision. All GPU; tens of ms per step on A15+ (estimates). Dewarping tri-fold creases is a v1.5 item: UVDoc is MIT, 8 M parameters, 488x712 input, 45x31 grid, no published runtime; v1 should keep the original photo so pages can be re-processed later.
8. Colour: Core Image's default output space is sRGB; render to sRGB and declare an sRGB OutputIntent. FADGI accepts sRGB for textual records. P3 adds nothing for paper.
9. The PDF/A writer question has a new fact: the iOS 16.5 SDK header for `CGPDFContext.h` documents `kCGPDFContextCreatePDFA` (iOS 14 / macOS 11) as "Output a PDF that conforms to PDF/A-2u (ISO 19005-2)", default false, alongside `CGPDFContextAddDocumentMetadata` for XMP. The earlier output.md statement "no Apple framework writes PDF/A" is wrong on paper; whether the output passes veraPDF is **unknown** (410 GitHub code hits are all bindings and doc mirrors; zero issues or validation reports). Recommendation: spike it in week one against veraPDF; keep the in-house Swift writer as the plan of record because only it gives DCT pass-through, JBIG2, the pdfaExtension schema and byte-copy merging. qpdf (Apache-2.0, C++17, zlib + libjpeg) is a structural tool, not a PDF/A converter; libharu lists PDF/A 1-4 enums and XMP/OutputIntent helpers but cannot produce an invisible glyphless text layer; Skia's SkPDF has a real PDF/A-2b flag but is a very heavy dependency.
10. Net effect on the rest of the plan: 12 MP stills (HEIC 1.5-3 MB, JPEG master at ~2550x3300 ~0.3-0.9 MB), no change to the latency budget in gap-3, and the "print-ready" claim in marketing should read "300 ppi when framed, never below 200 ppi" until measured.

## 2. Findings

### 2a. What "print-ready archival" means in numbers (FADGI 2023, Third Edition)

Source: FADGI Technical Guidelines for Digitizing Cultural Heritage Materials, Third Edition, May 2023, https://www.digitizationguidelines.gov/guidelines/FADGITechnicalGuidelinesforDigitizingCulturalHeritageMaterials_ThirdEdition_05092023.pdf (text extracted locally with pdftotext).

| Category | 1-star | 2-star | 3-star | 4-star |
|---|---|---|---|---|
| Documents (Unbound): General Collections, resolution | >= 190 ppi (200 - 5 %) | >= 242.5 ppi (250 - 3 %) | >= 294 ppi (300 - 2 %) | >= 396 ppi (400 - 1 %) |
| Bit depth | 8 | 8 | 8 or 16 | 16 |
| Colour space | Gray Gamma 2.2, sRGB | Adobe RGB, sRGB, ProPhoto, ECIRGB_v2 | same | same |
| Colour mode | grey or colour | colour | colour | colour |
| SFR10 sampling efficiency | > 60 % | > 70 % | > 80 % | > 90 % |
| Lightness uniformity (std/mean L*) | < 8 % | < 5 % | < 3 % | < 1 % |
| White balance (dE a*b*) | < 8 | < 6 | < 4 | < 2 |

The new "Documents (Unbound): Modern Textual Records" category (added in this edition, the closest match to mail and office paper) has a single level: **>= 294 ppi, 8 or 16 bit, colour or greyscale, Gray Gamma 2.2 / sRGB / Adobe RGB / ProPhoto / ECIRGB_v2, tone response dL < 3, white balance dE < 4, lightness uniformity < 3 %, mean colour error dE2000 < 3.5**; master formats TIFF 6.0, JPEG 2000 part 1, PNG 1.2 or **PDF/A**, with lossless codecs or, for federal agencies, "up to 20:1 visually lossless compression". FADGI also says it is "critically important ... to maintain the relationship to the original size of the object", i.e. the ppi written into the file must be the true reproduction scale. That is exactly the MediaBox problem in 2c.

Two consequences: (1) FADGI's 3-star bar is 294 ppi *measured* with a slanted-edge target, not nominal pixels per inch; handheld motion blur and lens MTF reduce sampling efficiency, so nominal 300 ppi from a phone is not automatically 3-star. (2) A bilevel image is not an archival master under FADGI (8-bit minimum), which settles the binarisation question: bilevel/MRC is a derivative, never the master.

### 2b. Effective ppi at realistic framing (arithmetic, mine)

Sensor long-axis pixels: 12 MP = 4032, 24 MP = 5712, 48 MP = 8064 (dimensions from output.md and Apple's `maxPhotoDimensions` entries). Effective ppi = pixels covering the page's long side / long side in inches. Frame fraction = page long side / frame long side after rectification (not counting perspective loss).

| Capture | Page | 55 % | 60 % | 70 % | 80 % | 90 % |
|---|---|---|---|---|---|---|
| 12 MP | Letter (11 in) | 202 | 220 | 257 | 293 | 330 |
| 12 MP | A4 (11.69 in) | 190 | 207 | 241 | 276 | 310 |
| 12 MP | Legal (14 in) | 158 | 173 | 202 | 230 | 259 |
| 12 MP | #10 envelope (9.5 in) | 233 | 255 | 297 | 340 | 382 |
| 24 MP | Letter | 286 | 312 | 363 | 415 | 467 |
| 24 MP | A4 | 269 | 293 | 342 | 391 | 440 |
| 48 MP | Letter | 403 | 440 | 513 | 586 | 660 |
| 48 MP | Legal | 317 | 346 | 403 | 461 | 518 |

Frame fraction needed for FADGI 3-star (294 ppi) / 4-star (396 ppi): 12 MP Letter **82 % / 109 %**, A4 **87 % / 116 %**, Legal **104 % / 139 %**; 24 MP Letter 58 % / 77 %; 48 MP Letter 41 % / 55 %, Legal 52 % / 69 %.

Pixel targets for the output: Letter 300 ppi = 2550x3300 (8.4 MP); A4 300 ppi = 2481x3507 (8.7 MP); Legal 300 ppi = 2550x4200 (10.7 MP); 80 mm receipt 8 in long at 300 ppi = 945x2400 (2.3 MP); #10 envelope 300 ppi = 1238x2850 (3.5 MP).

Working distance (mine, pinhole model, 36 mm frame width at the stated equivalent focal length; iPhone 17 Main is 24 mm equiv on Pro, 26 mm on non-Pro per output.md): Letter at 60 % of the long axis is ~31-34 cm from the paper; at 80 % it is ~23-25 cm. Both are normal handheld distances. A receipt filling 40 % of the frame sits at ~15 cm; a card at ~10 cm. Whether the Main camera focuses at 10-15 cm is device-specific and **not published**; `AVCaptureDevice.minimumFocusDistance` (iOS 15+) reports it in millimetres, -1 if unknown, and for virtual devices reports the smallest among the constituent cameras (https://developer.apple.com/documentation/avfoundation/avcapturedevice/minimumfocusdistance). The ultra-wide macro mode is marketed from 2 cm on iPhone 13 Pro and later **(memory, verify)**; it is lower resolution per page width and distorts edges, so prefer the Main camera and let small items fill less of the frame: a 58-80 mm receipt only needs ~700-950 px across to reach 300 ppi, which 12 MP delivers at 19-24 % of the long axis.

Why 24 MP is not the answer: gap-3 quotes the AVFoundation header: "The maxPhotoDimensions setting for 24MP (5712, 4284), when supported, is only serviced as 24MP via deferred photo delivery", and deferred proxies "can be rendered into a final image and ingested into the user's photo library via PHAsset APIs. The intermediate data are not accessible by the calling process" (gap-3-on-device-latency-budget.md, 2c). WWDC26 session 304: 24 MP is multi-frame fused and `.quality` only; 48 MP is a single-frame capture at `.balanced` or `.quality`; "this processing can take several seconds" (https://nonstrict.eu/wwdcindex/wwdc2026/304/). Apple's `maxPhotoDimensions` page adds that changing the value "may trigger a lengthy reconfiguration of the capture pipeline, so set this value before calling `startRunning()`" (https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/maxphotodimensions), i.e. you cannot flip between 12 and 48 MP per page.

Resolved detail vs nominal pixels: 48 MP on iPhone is a quad-Bayer sensor and 24 MP is a fused output; the true resolving power of either is **unknown** from primary sources and must be measured with a slanted-edge target (FADGI's SFR10 metric) on the devices in the test fleet. Treat 48 MP as "> 300 ppi with margin", not as 586 ppi.

### 2c. Inferring the physical page size (MediaBox) with no scale reference

A photo has no absolute scale. The PDF needs one: MediaBox in points (Letter 612x792, A4 595.3x841.9, Legal 612x1008, #10 envelope 297x684, 80 mm receipt 226.8 pt wide). Signals, ranked by reliability:

1. **Aspect ratio of the rectified quad.** Standard sizes (https://en.wikipedia.org/wiki/Paper_size, https://en.wikipedia.org/wiki/Envelope): Letter 216x279 mm (1.294), Legal 216x356 (1.647), Half Letter/Statement 140x216 (1.545), Executive 184x267 (1.45), Tabloid 279x432 (1.55), A4 210x297 (1.414), A5 148x210 (1.414), A3 297x420 (1.414); envelopes #10 105x241 mm (2.30), #9 98x225 (2.30), #6 3/4 92x165 (1.79), DL 110x220 (2.00), C5 162x229 (1.414), C6 114x162 (1.42), C4 229x324 (1.414), A2 announcement 111x146 (1.32), A7 133x184 (1.38). Letter vs A4 differ by 9 %, which a quad from `DetectDocumentSegmentationRequest` resolves easily (corner error of 1-2 % of a side gives ~2 % ratio error). Failure classes: everything in the ISO A/C series shares sqrt(2), so A4 vs A5 vs C5 is invisible to aspect; Letter (1.294) vs A2 announcement envelope (1.32) and Executive (1.45) vs A4 (1.414) are close; receipts have arbitrary length.
2. **Locale prior.** Wikipedia: Letter dominates in the US and Canada; A4 everywhere else, with Letter still common in Mexico, Costa Rica, Colombia, Venezuela, Chile and the Philippines. Use `Locale.current.region` plus a per-user learned prior (after 20 pages the user's own distribution is a better prior than the country's).
3. **Text metrics.** Vision line boxes give line height in pixels; body text in correspondence is 10-12 pt (line pitch ~4-5 mm). A +-25 % estimate is enough to split 2x ambiguities (A4 vs A5, Letter vs Half Letter, C5 vs A4). For thermal receipts use printer geometry instead: an Epson TM-T88VI prints 180 dpi on 79.5 +-0.5 mm paper at 42, 48 or 56 columns, and on 57.5 mm paper at 30, 36 or 40 columns (https://epson.com/For-Work/Printers/POS/TM-T88VI-Thermal-Receipt-Printer/p/C31CE94061); counting characters per line in the OCR therefore yields the paper width to within a few percent. (Printer widths vary by vendor; treat as a prior, not a constant.)
4. **Metric depth on LiDAR devices.** `builtInLiDARDepthCamera` (iOS 15.4+) "provides high-quality, high-accuracy depth information ... synchronizes and perspective-corrects this data to frames that the YUV camera produces" (https://developer.apple.com/documentation/avfoundation/avcapturedevice/devicetype-swift.struct/builtinlidardepthcamera); ARKit's `ARDepthData.depthMap` is "distance from the plane of the camera in meters" (https://developer.apple.com/documentation/arkit/ardepthdata). Combine depth Z with the intrinsics (`AVCameraCalibrationData.intrinsicMatrix`, "The values fx and fy are the pixel focal length", https://developer.apple.com/documentation/avfoundation/avcameracalibrationdata/intrinsicmatrix; delivered per frame when `AVCaptureConnection.isCameraIntrinsicMatrixDeliveryEnabled` is set before `startRunning()`, https://developer.apple.com/documentation/avfoundation/avcaptureconnection/iscameraintrinsicmatrixdeliveryenabled): physical width = pixel width x Z / fx. `AVDepthData.Accuracy` distinguishes `.relative` ("usable for foreground/background separation but are not absolutely accurate") from `.absolute` (https://developer.apple.com/documentation/avfoundation/avdepthdata/accuracy); dual-camera disparity is typically relative and LiDAR absolute **(inference; check `depthDataAccuracy` at runtime)**. Depth map resolution is **unknown** from the pages fetched (the LiDAR sample uses `kCVPixelFormatType_DepthFloat16`, https://developer.apple.com/documentation/avfoundation/capturing-depth-using-the-lidar-camera). Apple's MakerNote also carries `FocusDistanceRange` (0x000c, rational64s[2]) and `AFMeasuredDepth` (0x0038, "time-of-flight-assisted auto-focus estimator") per ExifTool (https://exiftool.org/TagNames/Apple.html), both undocumented by Apple; `lensPosition` is explicitly "not an exact physical distance" and 0..1 (https://developer.apple.com/documentation/avfoundation/avcapturedevice/lensposition), so it is useless for scale.
5. **Document class.** Claude's classification arrives late (gap-6/7) but an IRS form, a W-2 or a Swiss QR-bill has a known size; because MediaBox is only written when the PDF is assembled, this signal can still override the geometric guess.

Decision rule I recommend: pick the standard size whose aspect is within 3 % of the quad's, breaking ties with the locale prior and text metrics; if nothing matches within 3 % (receipts, odd envelopes, cut sheets), set MediaBox from the text/receipt-width estimate, else from an assumed 300 ppi; always record `pap:pageSizeSource` (aspect, locale, text, lidar, class, assumed) in the XMP extension schema so the number can be corrected later without touching pixels. Scanbot's straightening API takes an explicit `aspectRatios` list (e.g. A4 portrait and landscape) for the same reason (https://docs.scanbot.io/ios/document-scanner-sdk/document-enhancer/document-straightening/).

### 2d. Capture settings and what Apple documents

| Setting | Apple text (quoted or paraphrased) | Why it matters here | Source |
|---|---|---|---|
| `setExposureTargetBias(_:)` (iOS 8) | bias in EV between `minExposureTargetBias` and `maxExposureTargetBias` | Auto-exposure aims at mid-grey, so white paper renders grey and small type loses contrast; +0.7 to +1.3 EV is the photographic rule of thumb (not an Apple number); verify with the clipped-pixel check already in capture.md | https://developer.apple.com/documentation/avfoundation/avcapturedevice/setexposuretargetbias(_:completionhandler:) |
| `activeMaxExposureDuration` (iOS 12) | "the autoexposure algorithm picks a default maximum exposure duration ... balancing low light image quality with motion preservation. You may also override the default value" | Caps shutter time so handheld motion blur cannot eat the 300 ppi; 1/120-1/200 s is a starting point, ISO rises instead | https://developer.apple.com/documentation/avfoundation/avcapturedevice/activemaxexposureduration |
| `setWhiteBalanceModeLocked(with:)` (iOS 8) | gains between 1.0 and `maxWhiteBalanceGain`, normalised to the minimum channel | Lock once per batch from the paper region so consecutive pages match; FADGI white-balance tolerance is dE < 4 | https://developer.apple.com/documentation/avfoundation/avcapturedevice/setwhitebalancemodelocked(with:completionhandler:) |
| `autoFocusRangeRestriction = .near` (iOS 7) | "This approach makes autofocus faster, more power efficient, and less error prone" | Documents are always near | https://developer.apple.com/documentation/avfoundation/avcapturedevice/autofocusrangerestriction-swift.enum |
| `isSmoothAutoFocusEnabled = false` (iOS 7) | "the camera makes lens movements more slowly ... a behavior that you may want for video capture" | Leave off; we want the fastest lens move | https://developer.apple.com/documentation/avfoundation/avcapturedevice/issmoothautofocusenabled |
| `isAdjustingFocus` (iOS 4) | KVO boolean | Gate the still on `false`; autofocus settle time is **not published by Apple**; measure per device | https://developer.apple.com/documentation/avfoundation/avcapturedevice/isadjustingfocus |
| `minimumFocusDistance` (iOS 15) | millimetres, -1 if unknown | Refuse to fire when the quad implies a distance below it; feed the "move back" hint | https://developer.apple.com/documentation/avfoundation/avcapturedevice/minimumfocusdistance |
| `isGeometricDistortionCorrectionEnabled` (iOS 13) | "When the device supports geometric distortion correction (GDC), the default value is true" | Keep on; straight page edges make the quad and the warp accurate | https://developer.apple.com/documentation/avfoundation/avcapturedevice/isgeometricdistortioncorrectionenabled |
| `photoQualityPrioritization` (iOS 13) | `.balanced` default; `.speed` "even at the expense of quality"; `.quality` "at the expense of shot-to-shot time" | `.balanced` for 12 MP; `.speed` under thermal pressure (gap-3); `.quality` is the 24 MP path and is rejected | https://developer.apple.com/documentation/avfoundation/avcapturephotosettings/photoqualityprioritization |
| Colour space | "By default, a capture session automatically enables wide-gamut capture for supported devices"; cases `sRGB`, `P3_D65`, `HLG_BT2020`, `appleLog` | Paper does not need P3; either set the device to `.sRGB` or let Core Image convert | https://developer.apple.com/documentation/avfoundation/avcapturecolorspace |
| `CIContextOption.outputColorSpace` | "If this option is not specified, then the default output space is sRGB" | The rendered JPEG is already sRGB; embed the sRGB ICC as the PDF/A OutputIntent | https://developer.apple.com/documentation/coreimage/cicontextoption/outputcolorspace |

### 2e. Enhancement pipeline and per-step cost

Order: quad from `DetectDocumentSegmentationRequest` ("four corner points of a document's quadrilateral and saliency masks", result `DetectedDocumentObservation` with `globalSegmentationMask`, iOS 18+, https://developer.apple.com/documentation/vision/detectdocumentsegmentationrequest) re-detected on the still -> `CIPerspectiveCorrection` (a `CIFourCoordinateGeometryFilter`, corners as `CGPoint`, https://developer.apple.com/documentation/coreimage/ciperspectivecorrection) -> `CILanczosScaleTransform` down to the target ppi (never up) -> orientation (2f) -> `CIFilter.documentEnhancer()` ("Adjusts an image's shadows and contrast", `amount: Float`, range and version undocumented on the current page; iOS 13 **(memory, verify)**, https://developer.apple.com/documentation/coreimage/cidocumentenhancer) or a custom background-normalisation kernel (large-radius blur of the luma as the paper estimate, divide, clamp) when the enhancer leaves gradients -> `CIWhitePointAdjust` from the paper estimate -> small-radius `CIUnsharpMask` -> colour/grey decision from the saturation histogram -> JPEG encode via ImageIO (sRGB, q 45-60 for the master).

Costs: Apple publishes none. Working estimates for a 12 MP input on A15+ with the whole graph in one `CIContext` render: warp + Lanczos 30-80 ms, document enhancer 10-40 ms, white point + unsharp < 10 ms, 8 MP JPEG encode 50-100 ms; total 100-250 ms on the GPU, off the feedback path. These are estimates to be measured in the week-one harness, not vendor numbers.

Deskew: the quad warp removes gross rotation; residual skew (< 2 degrees) is corrected with a `CIAffineTransform` using the dominant text-line angle from `RecognizedTextObservation` boxes. OCRmyPDF makes the same split: `--rotate-pages` "is for when the cardinal angle is wrong", `--deskew` for a page "just a little off horizontal" (https://ocrmypdf.readthedocs.io/en/latest/cookbook.html).

Shadow/gradient removal is the step with the most visible quality impact on handheld captures (the phone and hand shade the page). FADGI 3-star lightness uniformity is < 3 % std/mean, which the enhancer alone will not reach on a shaded page; background division will. Both are single-pass GPU kernels.

Dewarping (tri-fold creases, curled receipts): three tiers.
- Do nothing beyond shading removal: creases mostly show as shading and a 1-3 mm local displacement; text stays OCR-able. Acceptable for v1 given the original photo is retained.
- Text-line model (Leptonica `dewarp`): needs "text lines covering a sufficient part of the page" and by default 15 nearly full-length lines (`DefaultMinLines = 15`, sampling 30) to build the vertical disparity; horizontal disparity only when margins are aligned; multi-column pages are skipped by default (https://raw.githubusercontent.com/DanBloomberg/leptonica/master/src/dewarp1.c). Fails on forms, tables, receipts, envelopes, i.e. much of mail. BSD-style licence, CPU.
- Learned mesh model: UVDoc (SIGGRAPH Asia 2023) predicts a 45x31 unwarping grid from a 488x712 input with an **8 M-parameter** network, corrected UVDoc-benchmark MS-SSIM 0.785 / AD 0.119 vs DocTr 0.697 / 0.160, MIT licence, no published inference time (https://github.com/tanguymagne/UVDoc, https://ar5iv.labs.arxiv.org/html/2302.02887). An 8 M-parameter CNN at 488x712 is in the range that converts to Core ML and runs in tens of milliseconds on the Neural Engine **(estimate, unmeasured)**. DocTr++ handles partially visible documents but its licence requires contacting the author for commercial use (https://github.com/fh2019ustc/DocTr-Plus). Scanbot's `DocumentStraighteningMode.STRAIGHTEN` ("creases, curl, folds, and crinkles") is the commercial equivalent, with no numbers published (https://docs.scanbot.io/ios/document-scanner-sdk/document-enhancer/document-straightening/); Genius Scan exposes `GSKCurvatureCorrectionConfiguration(curvatureCorrection: true)` for "books, magazines, or curved sheets" (https://geniusscansdk.com/docs/v6/custom-integration/image-processing/).

Binarisation/MRC: covered in output.md; the only addition from FADGI is that 1-bit output is not a master. Keep the 8-bit grey or colour JPEG at 300 ppi as the archival page; produce bilevel/JBIG2 or MRC only as the "compact" derivative.

### 2f. Orientation when the phone points straight down

`AVCaptureDevice.RotationCoordinator` (iOS 17) "monitors the physical orientation of a capture device and provides adjustment angles to keep images level, relative to gravity"; `videoRotationAngleForHorizonLevelCapture` is "an angle ... so that they're level relative to gravity" and is KVO-observable (https://developer.apple.com/documentation/avfoundation/avcapturedevice/rotationcoordinator, https://developer.apple.com/documentation/avfoundation/avcapturedevice/rotationcoordinator/videorotationangleforhorizonlevelcapture). Neither page says what happens when the camera axis is parallel to gravity; by construction the in-plane angle is then undefined, so the value should be expected to hold whatever was last seen **(inference)**. Core Motion yaw is relative to magnetic north, not to the paper. Vision's quad gives `topLeft/topRight/bottomLeft/bottomRight` as `NormalizedPoint`s via `QuadrilateralProviding` (https://developer.apple.com/documentation/vision/quadrilateralproviding); nothing documents whether that naming is semantic (text-up) or geometric, so assume geometric.

Practical scheme, zero user interaction:
1. Prior: the phone's top edge is the page's top. A person reading mail holds the phone with its top away from the body and the page the same way; expect this to be right most of the time (unmeasured; log it).
2. Portrait vs landscape from the quad aspect (ratio < 1 means the page's long side runs across the frame, so the candidates are 90/270 instead of 0/180).
3. Decide between the two candidates with `RecognizeTextRequest` `.fast` on a ~1000 px thumbnail at each candidate `orientation` and pick the one with the larger sum of confidence x recognised characters; this is OCRmyPDF's rotate-pages logic ("the ratio of how confidence the OCR engine is that the document image should be changed", default "quite conservative", https://ocrmypdf.readthedocs.io/en/latest/cookbook.html). Measured `.fast` cost: 101 ms p50 on an iPhone 16 for a 63-line page (gap-3, https://github.com/LahaLuhem/text_sight/blob/main/doc/performance.md); two passes ~200 ms on A18, estimated 400-600 ms on A15. It runs after the "captured" haptic and before the archival encode, so it does not touch the feedback path.
4. For pages with almost no text (photos, blank backs), keep the prior and let Claude's later pass override; rotation metadata is a number in the manifest, pixels are re-rendered only if the decision changes.
5. Store pixels upright and write `/Rotate 0` (viewers and Drive thumbnails are more reliable that way, output.md 2h).

### 2g. PDF/A-2b writer: in-house Swift vs Core Graphics plus a post-pass

New primary-source fact. The iOS 16.5 SDK `CGPDFContext.h` (mirror: https://raw.githubusercontent.com/theos/sdks/master/iPhoneOS16.5.sdk/System/Library/Frameworks/CoreGraphics.framework/Headers/CGPDFContext.h) declares:

- `kCGPDFContextCreatePDFA` (macOS 11.0, iOS 14.0): "Output a PDF that conforms to PDF/A-2u (ISO 19005-2). The value of this key must be a CFBooleanRef. The default value of this key is kCFBooleanFalse."
- `kCGPDFContextCreateLinearizedPDF` (same availability): "Output a linearized PDF".
- `CGPDFContextAddDocumentMetadata` (iOS 4.0): adds an XMP metadata stream to the catalog.
- `kCGPDFContextOutputIntent(s)`: PDF/X-style; "the value of this key must be a CFString equal to "GTS_PDFX"; otherwise, the dictionary is ignored" (so an app cannot supply a `GTS_PDFA1` intent through this key; if the PDFA flag works, Apple must synthesise the intent itself).

Apple's web page for the key confirms availability (iOS 14.0+, macOS 11.0+) but has an empty abstract and no discussion (https://developer.apple.com/documentation/coregraphics/kcgpdfcontextcreatepdfa). Microsoft's .NET bindings surface it as `CGPDFInfo.CreatePdfA2u` (https://raw.githubusercontent.com/dotnet/macios/main/src/CoreGraphics/CGContextPDF.cs). A GitHub code search returns 410 hits, all language bindings and documentation mirrors; a GitHub issue search returns zero, so there is **no public evidence either way** that the output passes veraPDF. The output.md verdict "no Apple framework writes PDF/A" was therefore wrong on paper and unverified in practice.

What the flag cannot give us even if it validates: control of the image filter (DCT pass-through is widely observed but undocumented, output.md 2e), JBIG2/CCITT for bilevel derivatives, a glyphless invisible font (Core Graphics embeds whatever real font you draw with; invisible text via text render mode 3 with a real embedded font is legal PDF/A), the `pdfaExtension` schema block for our custom XMP fields (we can write the whole XMP ourselves via `CGPDFContextAddDocumentMetadata`, but Info-dict/XMP agreement and the ID pairing are then our problem), and byte-copy merging of pages into multi-page documents (CG re-renders).

Alternatives examined:
- **qpdf**: "structural, content-preserving transformations on PDF files"; "not a PDF content creation library"; Apache-2.0 (Artistic 2.0 for pre-7 at your option); C++17 to link; dependencies zlib and libjpeg plus optional GnuTLS/OpenSSL; builds with CMake on Unix/Windows/macOS, no iOS statement (https://qpdf.readthedocs.io/en/stable/overview.html, https://raw.githubusercontent.com/qpdf/qpdf/main/README.md). It can inject `/Metadata` and `/OutputIntents` objects into a CG-made file through its C++ API, but it does not know PDF/A rules; it is a fixer, not a converter.
- **libharu**: `HPDF_PDFAType` enumerates `HPDF_PDFA_1A/1B/2A/2B/2U/3A/3B/3U/4/4E/4F` (https://raw.githubusercontent.com/libharu/libharu/master/include/hpdf_types.h) and `hpdf_pdfa.h` exposes `HPDF_PDFA_SetPDFAConformance`, `HPDF_PDFA_AppendOutputIntents`, `HPDF_PDFA_AddXmpMetadata`, `HPDF_PDFA_AddXmpExtension`, `HPDF_PDFA_GenerateID` (https://raw.githubusercontent.com/libharu/libharu/master/include/hpdf_pdfa.h). Whether the 2/3/4 enum values are fully implemented is **unknown**; libharu has no glyphless-font or text-render-mode-3 text-layer helper and its JPEG path is file based. Little gain over writing it ourselves.
- **Skia SkPDF**: `SkPDF::Metadata::fPDFA` "If true, include XMP metadata, a document UUID, and sRGB output intent ... necessary features for PDF/A-2b conformance"; `fEncodingQuality` <= 100 encodes opaque images as JPEG (https://raw.githubusercontent.com/google/skia/main/include/docs/SkPDFDocument.h). Real, BSD, but Skia is a multi-megabyte C++ dependency with its own build system; disproportionate for an image-plus-text-layer PDF.
- **In-house Swift writer** (output.md option A): scanned-image PDF/A is structurally small (one XObject per page, one glyphless CID font, XMP, OutputIntent, trailer ID); weeks, not months; veraPDF in CI.

### 2h. Size and transfer consequences of the resolution choice

12 MP HEIC originals 1.5-3 MB **(typical, unmeasured)**; rendered 300 ppi Letter JPEG master 0.3-0.9 MB (output.md 2f typical values); 48 MP HEIC 6-10 MB (apple.md) and 4x the warp/encode work. With three destinations (Drive, Synology, iCloud) the per-page upload is ~1-4 MB at 12 MP vs ~8-14 MB at 48 MP if originals are mirrored. Keeping originals local-only until the PDF verifies, then mirroring only on Wi-Fi, keeps the multi-destination cost at the PDF size.

## 3. Options compared

Capture resolution for the handheld loop:

| Option | ppi on Letter at 60 % / 80 % framing | Still latency | Private archive | Upload per page | Verdict |
|---|---|---|---|---|---|
| 12 MP, `.balanced`, ZSL | 220 / 293 | ~100-300 ms (gap-3 estimate) | yes | ~1-4 MB | **Default**, with a >= 78 % framing gate for full pages |
| 24 MP, `.quality`, deferred | 312 / 415 | multi-frame, "several seconds" | **no** (Photos ingestion) | n/a | Reject |
| 48 MP, `.balanced` | 440 / 586 nominal | "several seconds", ZSL unknown | yes | ~8-14 MB | Stand mode / archival toggle only |
| 12 MP + two-shot stitch | ~2x | 2 captures + registration | yes | 2x | Not for zero-interaction v1 |

Page-size inference:

| Signal | Resolves | Fails on | Cost | Devices |
|---|---|---|---|---|
| Quad aspect ratio | Letter/A4/Legal/Half/#10/DL/#6 3/4 | A4 vs A5 vs C5; receipts | free | all |
| Locale prior | Letter vs A4 default | mixed-use countries | free | all |
| Text line height / receipt columns | 2x ambiguities, receipt width | sparse pages | free (reuses OCR) | all |
| LiDAR depth + intrinsics | absolute size | non-Pro iPhones, glossy paper | depth output on, ~free | Pro models |
| Document class from Claude | form sizes | late | free | all |

Writer:

| Option | PDF/A | Control (DCT pass-through, JBIG2, ext. schema, merge) | Dependency | Risk |
|---|---|---|---|---|
| Core Graphics + `kCGPDFContextCreatePDFA` + own XMP | claimed 2u by header; unvalidated | low | none | undocumented behaviour; may silently not validate |
| CG + qpdf post-pass | still CG's content; qpdf fixes catalog only | low-medium | qpdf (Apache-2.0, C++17, zlib, libjpeg) | two toolchains, still not a PDF/A converter |
| libharu | enum 1-4, implementation depth unknown | medium | C, permissive | no invisible-text helper |
| Skia SkPDF | 2b (documented) | medium | very large | build and size |
| In-house Swift writer | 2b/2u by construction, veraPDF-gated | total | none | spec mistakes early |

## 4. Recommendation for this project

1. **Ship 12 MP stills and gate on framing, not on megapixels.** Add one condition to the capture state machine in capture.md: for a quad whose aspect matches a full-page size, fire only when the quad's long side is >= 0.78 of the frame's long axis (gives 286+ ppi on Letter, 269+ on A4); for receipts, cards and envelopes, fire when the implied ppi (quad pixels / inferred inches) is >= 300 or the implied distance is at `minimumFocusDistance`. The user never taps; the preview frame plus a soft "closer" cue does the work. Measure the natural framing distribution in the first week; if users sit at 60 %, the gate is what moves them to 80 %.
2. **Declare the output honestly**: "300 ppi master when the page is framed; never below 200 ppi". Run a slanted-edge SFR test on an iPhone 13, 15 and 17 at 25 cm handheld to learn the real sampling efficiency before claiming FADGI 3-star.
3. **48 MP only in stand mode**, set once before `startRunning()`, with `photoProcessingTimeRange` surfaced as progress, per gap-3.
4. **Page size**: implement the five-signal rule from 2c with the 3 % aspect tolerance; write `pap:pageSizeSource` and `pap:pageSizeConfidence` into the XMP extension schema; when LiDAR is present, enable depth delivery on the photo output and use the metric estimate as the tie-breaker.
5. **Capture settings**: `.near` focus restriction, smooth AF off, exposure bias +1 EV (tuned by the clipping check), `activeMaxExposureDuration` 1/120 s, white balance locked per batch from the paper region, GDC on, `.balanced`, sRGB output from Core Image.
6. **Orientation**: prior + quad aspect + two-way `.fast` OCR vote, after the haptic, before the encode. Instrument how often the prior is wrong.
7. **Enhancement v1**: warp, Lanczos to 300 ppi, orientation, document enhancer plus background division, white point, unsharp, grey/colour decision, JPEG q 50 sRGB. No dewarp in v1; keep the HEIC original so creased pages can be re-rendered when UVDoc-in-Core-ML (v1.5 spike: convert, measure on A15, ship behind a "creased" detector) lands.
8. **Writer**: keep the in-house Swift PDF/A-2b writer as the plan of record (output.md). In week one, run a one-day spike: `CGPDFContext` with `kCGPDFContextCreatePDFA = true`, our XMP via `CGPDFContextAddDocumentMetadata`, invisible text with a real embedded font, one JPEG page, through veraPDF. If it passes 2b, use it for the v0 prototype and as a fallback; if it fails or re-encodes images, the spike cost a day and the question is closed. Do not add qpdf or libharu; neither solves PDF/A.
9. **Colour**: sRGB everywhere (capture conversion by Core Image, sRGB IEC61966-2.1 ICC as OutputIntent). P3 is irrelevant for paper and complicates PDF/A.

## 5. Risks and unknowns

- Real resolving power of iPhone 12 MP binned output vs 48 MP quad-Bayer at 25 cm handheld is unmeasured; nominal ppi may overstate FADGI sampling efficiency by 10-30 %.
- Main-camera minimum focus distance is unpublished; if it is > 15 cm on some models, receipts and cards cannot reach 300 ppi without the ultra-wide macro path (lower quality, edge distortion). Runtime `minimumFocusDistance` tells us per device.
- Autofocus settle time is unpublished; it sits inside the sub-second feedback budget.
- `kCGPDFContextCreatePDFA` is undocumented beyond one header comment; it may produce files that fail veraPDF, re-encode images, or change between OS versions.
- `CIDocumentEnhancer` has no documented range, version floor or behaviour on coloured paper.
- RotationCoordinator behaviour in the face-down case is undocumented; the prior-plus-OCR vote is the mitigation.
- Depth map resolution and accuracy at 25 cm on LiDAR devices are unknown from the pages fetched; the metric size estimate may be noisy on glossy or dark paper.
- Dewarp model runtime on A15-class Neural Engines is unmeasured; UVDoc's benchmark gains may not transfer to tri-fold business mail.
- Receipt column counts vary by printer vendor; the 42/48/56-column rule is an Epson figure.
- WWDC26 / iOS 27 capture behaviour (balanced captures deferred on iPhone 16/17) could change whether 12 MP `.balanced` stays non-deferred; re-verify on the shipping SDK.

## 6. Open questions for the founder

1. Is "print-ready" a marketing claim ("prints like the original") or a compliance claim (FADGI 3-star / 294 ppi measured)? The second needs the framing gate and a stand-mode 48 MP option; the first is satisfied by 12 MP at natural framing.
2. Acceptable to nudge framing with a visual cue and a delayed trigger (still zero taps), or must capture fire at whatever distance the user holds?
3. Target device floor: if iPhone 13 (A15, no 48 MP) is in scope, 300 ppi on Legal is impossible handheld; is Legal a case that matters (US leases, some tax forms)?
4. Should MediaBox follow the inferred physical size (correct 100 % printing, FADGI) or should every page be normalised to Letter/A4 (simpler printing of packs, loses scale)? I recommend physical size plus "fit to page" on export packs.
5. Should the app ask for the user's paper-size region once (one tap at onboarding) or learn it silently from the first pages?
6. Budget a one-day veraPDF spike of Core Graphics' PDF/A flag, or go straight to the in-house writer?
7. Keep HEIC originals forever (enables future dewarp/OCR re-runs; ~2 MB/page) or only until the PDF verifies at every destination?

## 7. Sources

- FADGI Technical Guidelines, Third Edition (2023): https://www.digitizationguidelines.gov/guidelines/FADGITechnicalGuidelinesforDigitizingCulturalHeritageMaterials_ThirdEdition_05092023.pdf (index page: https://www.digitizationguidelines.gov/guidelines/digitize-technical.html)
- Apple kCGPDFContextCreatePDFA: https://developer.apple.com/documentation/coregraphics/kcgpdfcontextcreatepdfa
- iOS 16.5 SDK CGPDFContext.h (theos mirror): https://raw.githubusercontent.com/theos/sdks/master/iPhoneOS16.5.sdk/System/Library/Frameworks/CoreGraphics.framework/Headers/CGPDFContext.h
- Apple auxiliary dictionary keys: https://developer.apple.com/documentation/coregraphics/auxiliary-dictionary-keys
- .NET macios CGContextPDF.cs (CreatePdfA2u binding): https://raw.githubusercontent.com/dotnet/macios/main/src/CoreGraphics/CGContextPDF.cs
- Apple RotationCoordinator: https://developer.apple.com/documentation/avfoundation/avcapturedevice/rotationcoordinator and https://developer.apple.com/documentation/avfoundation/avcapturedevice/rotationcoordinator/videorotationangleforhorizonlevelcapture
- Apple CIDocumentEnhancer: https://developer.apple.com/documentation/coreimage/cidocumentenhancer
- Apple CIPerspectiveCorrection: https://developer.apple.com/documentation/coreimage/ciperspectivecorrection
- Apple CIContextOption.outputColorSpace: https://developer.apple.com/documentation/coreimage/cicontextoption/outputcolorspace
- Apple minimumFocusDistance: https://developer.apple.com/documentation/avfoundation/avcapturedevice/minimumfocusdistance
- Apple lensPosition: https://developer.apple.com/documentation/avfoundation/avcapturedevice/lensposition
- Apple activeMaxExposureDuration: https://developer.apple.com/documentation/avfoundation/avcapturedevice/activemaxexposureduration
- Apple setExposureTargetBias: https://developer.apple.com/documentation/avfoundation/avcapturedevice/setexposuretargetbias(_:completionhandler:)
- Apple setWhiteBalanceModeLocked: https://developer.apple.com/documentation/avfoundation/avcapturedevice/setwhitebalancemodelocked(with:completionhandler:)
- Apple autoFocusRangeRestriction: https://developer.apple.com/documentation/avfoundation/avcapturedevice/autofocusrangerestriction-swift.enum
- Apple isSmoothAutoFocusEnabled: https://developer.apple.com/documentation/avfoundation/avcapturedevice/issmoothautofocusenabled
- Apple isAdjustingFocus: https://developer.apple.com/documentation/avfoundation/avcapturedevice/isadjustingfocus
- Apple isGeometricDistortionCorrectionEnabled: https://developer.apple.com/documentation/avfoundation/avcapturedevice/isgeometricdistortioncorrectionenabled
- Apple photoQualityPrioritization: https://developer.apple.com/documentation/avfoundation/avcapturephotosettings/photoqualityprioritization
- Apple maxPhotoDimensions: https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/maxphotodimensions
- Apple AVCaptureColorSpace: https://developer.apple.com/documentation/avfoundation/avcapturecolorspace
- Apple intrinsicMatrix: https://developer.apple.com/documentation/avfoundation/avcameracalibrationdata/intrinsicmatrix
- Apple isCameraIntrinsicMatrixDeliveryEnabled: https://developer.apple.com/documentation/avfoundation/avcaptureconnection/iscameraintrinsicmatrixdeliveryenabled
- Apple AVDepthData.Accuracy: https://developer.apple.com/documentation/avfoundation/avdepthdata/accuracy
- Apple builtInLiDARDepthCamera: https://developer.apple.com/documentation/avfoundation/avcapturedevice/devicetype-swift.struct/builtinlidardepthcamera
- Apple LiDAR depth sample: https://developer.apple.com/documentation/avfoundation/capturing-depth-using-the-lidar-camera
- Apple ARDepthData: https://developer.apple.com/documentation/arkit/ardepthdata
- Apple isDepthDataDeliverySupported / embedsDepthDataInPhoto: https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/isdepthdatadeliverysupported , https://developer.apple.com/documentation/avfoundation/avcapturephotosettings/embedsdepthdatainphoto
- Apple DetectDocumentSegmentationRequest / DetectedDocumentObservation / QuadrilateralProviding: https://developer.apple.com/documentation/vision/detectdocumentsegmentationrequest , https://developer.apple.com/documentation/vision/detecteddocumentobservation , https://developer.apple.com/documentation/vision/quadrilateralproviding
- ExifTool Apple MakerNote tags: https://exiftool.org/TagNames/Apple.html
- WWDC26 session 304 (capture): https://nonstrict.eu/wwdcindex/wwdc2026/304/ (via gap-3)
- text_sight Vision timings: https://github.com/LahaLuhem/text_sight/blob/main/doc/performance.md (via gap-3)
- Paper sizes: https://en.wikipedia.org/wiki/Paper_size ; envelopes: https://en.wikipedia.org/wiki/Envelope
- Epson TM-T88VI specs: https://epson.com/For-Work/Printers/POS/TM-T88VI-Thermal-Receipt-Printer/p/C31CE94061
- OCRmyPDF cookbook (rotate-pages, deskew, image-dpi): https://ocrmypdf.readthedocs.io/en/latest/cookbook.html
- Leptonica dewarp1.c: https://raw.githubusercontent.com/DanBloomberg/leptonica/master/src/dewarp1.c
- UVDoc: https://github.com/tanguymagne/UVDoc ; paper: https://ar5iv.labs.arxiv.org/html/2302.02887
- DocTr++: https://github.com/fh2019ustc/DocTr-Plus
- Scanbot document straightening: https://docs.scanbot.io/ios/document-scanner-sdk/document-enhancer/document-straightening/
- Genius Scan image processing: https://geniusscansdk.com/docs/v6/custom-integration/image-processing/
- qpdf overview and README: https://qpdf.readthedocs.io/en/stable/overview.html , https://raw.githubusercontent.com/qpdf/qpdf/main/README.md
- libharu PDF/A headers: https://raw.githubusercontent.com/libharu/libharu/master/include/hpdf_pdfa.h , https://raw.githubusercontent.com/libharu/libharu/master/include/hpdf_types.h
- Skia SkPDFDocument.h: https://raw.githubusercontent.com/google/skia/main/include/docs/SkPDFDocument.h
- Earlier reports in this folder: capture.md, output.md, apple.md, gap-3-on-device-latency-budget.md, gap-7-text-layer-source-and-claude-h.md
