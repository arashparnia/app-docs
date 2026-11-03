# Print-ready, archival, searchable PDF generation on iOS — research report

Dimension: image enhancement → resolution → PDF/A → invisible OCR layer → compression → originals → metadata → rotation/assembly → export. Research date: 2026-11-03. Note: the web-search budget for this run was exhausted before any search ran, so every finding below comes from directly fetched primary sources (Apple JSON doc endpoints, vendor docs, GitHub, readthedocs, Wikipedia for standards overviews). Items I could not fetch are marked **unknown** or **(memory, verify)**.

## 1) Executive summary

1. Apple's own `VNDocumentCameraViewController` is a fixed UI (tap-to-save), so a zero-interaction flow needs a custom `AVCaptureSession` + Vision `DetectDocumentSegmentationRequest` (iOS 18 Swift API; iOS 15 ObjC form) + Core Image warp/enhance pipeline.
2. Resolution is not the bottleneck: a 24 MP capture of a Letter page filling ~80% of the long axis yields ~415 ppi after warp; 12 MP yields ~290 ppi; 48 MP is overkill and slows capture. Target 300 ppi output (Letter = 2550×3300 px), keep 400 ppi when available.
3. No Apple framework writes PDF/A. `CGPDFContext`/`UIGraphicsPDFRenderer` give Info-dict metadata and a PDF/X-style OutputIntent key, but no XMP, no PDF/A identification, no control over image codecs. Verdict: write our own minimal PDF/A-2b writer in Swift (scanned-image PDFs are structurally simple), validated by veraPDF in CI.
4. Invisible text layer: replicate the Tesseract/OCRmyPDF "GlyphLessFont + `3 Tr` + `Tz` horizontal scaling" technique using Vision word/line boxes. Works in Preview, Acrobat, Drive, Spotlight (own index) and Synology (text-layer search).
5. Compression: JPEG (DCTDecode) for color/gray, JBIG2 generic-region (lossless only, never symbol/lossy mode) for bilevel; MRC is a v2 stretch goal. Sub-300 KB text pages are achievable with bilevel JBIG2 or gray JPEG q≈40–50 at 300 ppi (typical values, not vendor-measured).
6. Always keep the camera original (HEIC, ~2–4 MB at 24 MP) next to the PDF until the derived PDF is validated and uploaded; optionally forever as "negatives".
7. Metadata: Info dict + XMP (dc/xmp/pdf/pdfaid) + a custom XMP extension schema (declared via `pdfaExtension`, required by PDF/A) carrying doc_type, sender, document_date, tax_year, sha256; mirror the same fields into Drive `appProperties`/`indexableText`, Core Spotlight, and a sidecar JSON for NAS/iCloud.
8. Commercial SDKs (Scanbot, Genius Scan, Nutrient) are solid but quote-priced (Scanbot "starts at $2,500/yr"), ship their own capture UI assumptions, and none document PDF/A on iOS except Genius Scan's `shouldGeneratePDFA` flag (level undocumented).
9. Per-page budget on a current iPhone: <150 ms to "captured + deduped" (preview-resolution detection + perceptual hash), full OCR/PDF/upload fully asynchronous (OCR accurate-mode is the long pole, est. 0.5–2 s, unmeasured).
10. Biggest unknowns: measured Vision OCR latency at 24 MP, whether Core Graphics' own text output is Unicode-mappable enough for PDF/A-2u, Synology Universal Search behaviour on image-only PDFs, JBIG2 encoder throughput on A-series CPUs.

## 2) Findings

### 2a. Image enhancement pipeline (perspective, deskew, crop, lighting, modes)

**Apple first-party building blocks**

| Capability | API | Availability | Notes / source |
|---|---|---|---|
| Document quad + segmentation mask | `DetectDocumentSegmentationRequest` → `DetectedDocumentObservation` (`globalSegmentationMask: PixelBufferObservation`, corners via `QuadrilateralProviding`) | iOS 18 / macOS 15 (Swift API); ObjC `VNDetectDocumentSegmentationRequest` is older **(memory: iOS 15, verify)** | https://developer.apple.com/documentation/vision/detectdocumentsegmentationrequest ; https://developer.apple.com/documentation/vision/detecteddocumentobservation |
| Perspective warp | `CIPerspectiveCorrection` (Core Image, GPU/Metal) | iOS 8+ | Standard filter; corners from Vision are normalized (origin bottom-left) and must be scaled to pixel extent |
| Shadow/contrast "document look" | `CIFilter.documentEnhancer()` / `CIDocumentEnhancer` (`amount: Float`) — "Adjusts an image's shadows and contrast" | Apple JSON page lists platforms but no versions; **(memory: iOS 13, verify)** | https://developer.apple.com/documentation/coreimage/cidocumentenhancer |
| Lens smudge gate | `DetectLensSmudgeRequest` → confidence 0–1, Apple example threshold 0.9; false positives with motion blur/fog | iOS 26 (WWDC25 session 272) | https://developer.apple.com/videos/play/wwdc2025/272/ |
| Full scanner UI (auto-capture, crop, filters) | `VNDocumentCameraViewController` / `VNDocumentCameraScan` (`pageCount`, `imageOfPage(at:) -> UIImage`, `title`) | iOS 13+ | Apple docs do not document output resolution or which enhancement is applied. The UI requires a user tap to finish, so it fails the zero-interaction requirement. https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller |

Other steps and where they come from:

- **Deskew / rotation**: run the warp first (Vision quad removes most skew), then determine text orientation from OCR line geometry (see 2h). Core Image has no deskew filter; residual deskew (<3°) can be done via `CIAffineTransform` using the dominant text-line angle from `RecognizedTextObservation` boxes.
- **Uneven lighting / shadows**: `CIDocumentEnhancer` handles the common case; for stronger control implement a background-normalization (large-kernel blur or morphological "paper estimate" divided out) as a custom `CIKernel`/Metal shader. Scanbot sells exactly this as a "Color Document Shadow Removal Filter" (https://docs.scanbot.io/ios/document-scanner-sdk/filters-and-image-processing/available-image-filters/), which tells you it is a differentiator but not magic.
- **Color vs gray vs bilevel**: decide per page from the corrected image: saturation histogram (colorful content → color), otherwise gray; bilevel (adaptive threshold, Sauvola-style) only for pure text pages and only when the user picks "compact" mode, because binarization destroys stamps, signatures and halftones. Scanbot's own presets confirm the shadow sensitivity of binarization: "preset1 works well when there are no shadows; preset2–4 work even when shadows are present" (same URL).
- **White balance / contrast**: `CIWhitePointAdjust`, `CIColorControls`, plus `CIUnsharpMask` with small radius for text sharpening; apply after downscale to output ppi to avoid amplifying sensor noise. Moiré (halftone printed photos) is best mitigated by capturing at 24 MP and downsampling with area averaging (`CILanczosScaleTransform`) rather than by filters.
- **OpenCV on iOS**: official `platforms/ios/build_framework.py` builds a universal static `opencv2.framework` (default `IPHONEOS_DEPLOYMENT_TARGET=9.0`, arm64; xcframework via `build_xcframework.py`) (https://raw.githubusercontent.com/opencv/opencv/4.x/platforms/ios/build_framework.py). Useful for `getPerspectiveTransform`, Sauvola threshold, morphology, Hough deskew — but it adds ~20–40 MB and CPU-bound paths; Core Image/Metal keeps everything on GPU. Use OpenCV only if a specific algorithm is missing.
- **Commercial filter sets**: Scanbot lists Color Document, Color Document Shadow Removal, Scanbot Binarization (binary/antialiased), Custom Binarization presets 1–4, Brightness, Contrast, Grayscale (+auto-contrast), White Black Point (https://docs.scanbot.io/ios/document-scanner-sdk/filters-and-image-processing/available-image-filters/). Genius Scan lists Automatic, No Op, Strong/Soft Monochrome/Grayscale/Color, Photo, Dark Background, plus curvature correction (https://geniusscansdk.com/docs/v6/custom-integration/image-processing/). Scanbot's "Document Enhancer" additionally flattens warped/folded pages (https://docs.scanbot.io/ios/document-scanner-sdk/document-enhancer/introduction/).

### 2b. Resolution / DPI and what iPhone cameras deliver

Arithmetic (mine): Letter 8.5×11 in at 300 ppi = **2550×3300 px (8.4 MP)**; at 400 ppi = 3400×4400 (15 MP); A4 at 300 ppi = 2480×3508.

| Capture | Pixels | Page fills 80% of long axis (handheld, margins) → effective ppi on Letter | Verdict |
|---|---|---|---|
| 12 MP (`4032×3024`) | 4032 | ~293 ppi | borderline 300; fine for text, not for "print-ready" claims |
| 24 MP default HEIF on 48 MP sensors (`5712×4284`) | 5712 | ~415 ppi | sweet spot |
| 48 MP (`8064×6048`) | 8064 | ~586 ppi | excess; slower capture, 4× bytes |

Camera facts (Apple tech specs, vendor claims):
- iPhone 17 Pro: Fusion Main 48 MP ƒ/1.78 24 mm, Ultra Wide 48 MP ƒ/2.2 13 mm, Telephoto 48 MP ƒ/2.8 100 mm; "48MP macro photography"; photos at 24 MP and 48 MP; HEIF/JPEG/DNG; A19 Pro (https://support.apple.com/en-us/125090).
- iPhone 17 (non-Pro): Main 48 MP ƒ/1.6 26 mm; Ultra Wide 48 MP ƒ/2.2 with macro; 24/48 MP photos; A19 (https://www.apple.com/iphone-17/specs/).
- iPhone 18 Pro (2026): 48 MP Main with variable aperture ƒ/1.48–ƒ/4.0, 48 MP UW, 48 MP tele; A20 Pro; "48MP macro" (https://support.apple.com/en-us/148590). Variable aperture is relevant: stopping down increases depth of field for tilted pages.
- Minimum focus distance is exposed per device via `AVCaptureDevice.minimumFocusDistance` (millimetres, −1 if unknown; iOS 15+) (https://developer.apple.com/documentation/avfoundation/avcapturedevice/minimumfocusdistance). Apple does not publish the Main camera's number; **unknown** officially. Macro (Ultra Wide) exists but its 13 mm lens distorts edges and is lower sharpness per page — use the Main camera at ~25–35 cm.
- 48 MP requires `AVCapturePhotoOutput.maxPhotoDimensions` set to a value from `activeFormat.supportedMaxPhotoDimensions`; Apple warns changing it "may trigger a lengthy reconfiguration of the capture pipeline" (https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/maxphotodimensions). Measured shutter-to-buffer latency at 24 vs 48 MP: **unknown**, must be benchmarked.
- Archival guidance: FADGI's Technical Guidelines (3rd ed., 2023) are the reference for textual material (https://www.digitizationguidelines.gov/guidelines/digitize-technical.html); the star-level ppi table lives in the PDF I could not fetch (**memory: 300 ppi = 3-star, 400 ppi = 4-star for textual documents, verify**).

### 2c. PDF/A: requirements and what is achievable on iOS

Standard facts (https://en.wikipedia.org/wiki/PDF/A; validator https://github.com/veraPDF/veraPDF-library):
- PDF/A-1 (2005, PDF 1.4; a/b), PDF/A-2 (2011, PDF 1.7; a/b/u), PDF/A-3 (2012; arbitrary attachments), PDF/A-4 (2020, PDF 2.0; f/e).
- Requirements: fonts embedded; device-independent colour (OutputIntent with ICC profile); XMP metadata; no encryption, JavaScript, external references; **LZW forbidden**; **JPEG 2000 allowed only from PDF/A-2**; level **u = b + every text string has a Unicode mapping**.
- veraPDF: open-source validator, GPLv3+/MPLv2+ dual licence, Java 8–25, CLI/GUI/JAR; the project site was offline at fetch time ("critical PHP vulnerability") — build from GitHub or use the Docker image.

Apple APIs:
- `CGPDFContext` auxiliary keys: `kCGPDFContextTitle/Author/Subject/Keywords/Creator`, boxes, encryption, and `kCGPDFContextOutputIntent(s)` which adds an `/OutputIntents` dictionary following PDF 1.4 §9.10.4 / ISO 15930-3 (PDF/X) with `kCGPDFXOutputIntentSubtype`, `kCGPDFXDestinationOutputProfile`, etc. (https://developer.apple.com/documentation/coregraphics/auxiliary-dictionary-keys ; https://developer.apple.com/documentation/coregraphics/kcgpdfcontextoutputintent). There is **no XMP key, no PDF/A identification**, and no control of image filters. `UIGraphicsPDFRenderer` (iOS 10+) is just a wrapper passing `documentInfo` through to the same keys (https://developer.apple.com/documentation/uikit/uigraphicspdfrenderer).
- `PDFDocument.write(to:withOptions:)` (iOS 11+) options: `ownerPasswordOption`, `userPasswordOption`, `saveTextFromOCROption` (iOS 16), `optimizeImagesForScreenOption` and `saveImagesAsJPEGOption` (iOS 16.4), `burnInAnnotationsOption`, `accessPermissionsOption`; Apple provides **no description** for the OCR/image options (https://developer.apple.com/documentation/pdfkit/pdfdocumentwriteoption). PDFKit re-serialises the file on write, so it cannot be trusted to preserve PDF/A structures after a merge.
- Conclusion: PDF/A on iOS is only achievable by (a) writing the PDF ourselves, (b) a commercial SDK, or (c) server-side conversion.

Libraries:

| Library | iOS? | PDF/A | OCR layer | Licence / price |
|---|---|---|---|---|
| Own Swift writer | yes | 2b (2u-ready) by construction | yes (glyphless font) | free; ~1.5–3 k LOC + veraPDF CI |
| Core Graphics / PDFKit | yes | no | partial (`saveTextFromOCROption`, undocumented) | free |
| Nutrient (PSPDFKit) iOS 27.x, iOS 17+ | yes | **not listed** in iOS conversion guides (https://www.nutrient.io/guides/ios/conversion.md); XMP write API exists (`XMPMetadata.setString(_:forXMPKey:namespace:…)`) | yes, on-device, separate licence component (https://www.nutrient.io/guides/ios/ocr/overview.md) | quote-only, 30-day trial, component pricing (https://www.nutrient.io/sdk/pricing/) |
| Scanbot iOS 10.x, iOS 15+ | yes | **unknown** (API reference 403) | yes, OCR module + "searchable PDF" (https://docs.scanbot.io/ios/document-scanner-sdk/scan-result-handling/creating-searchable-pdf-documents-with-ocr/) | "starts at $2,500" fixed annual fee, unlimited scans, 7-day trial (https://scanbot.io/pricing/) |
| Genius Scan SDK v6, iOS 15+ | yes | `shouldGeneratePDFA` flag (level undocumented; incompatible with passwords) (https://geniusscansdk.com/docs/v6/custom-integration/pdf-generation/) | yes, on-device, text layout → searchable PDF | flat annual fee, quote (https://geniusscansdk.com/) |
| PDFium | iOS not in README platform list (https://pdfium.googlesource.com/pdfium/+/refs/heads/main/README.md) | no | no | BSD |
| MuPDF | AGPL or commercial (https://mupdf.readthedocs.io/en/latest/); `mutool draw -t lang` runs Tesseract OCR | not documented | yes (server) | AGPL |
| pdf-lib (JS) | only via JS runtime | no | manual | MIT — irrelevant for native |
| OCRmyPDF (server) | n/a | **default PDF/A-2b**; `--output-type pdfa-1/2/3`; Ghostscript-free path validated with pikepdf, falls back to Ghostscript | yes (fpdf2 renderer aligns text to OCR boxes) | MPL-2 app; Ghostscript AGPL (https://ocrmypdf.readthedocs.io/en/latest/introduction.html ; …/advanced.html) |
| Ghostscript (server) | n/a | PDF/A-1/2/3 **level b only**; needs `PDFA_def.ps` + ICC; `PDFACompatibilityPolicy` 0/1/2 | n/a | AGPL / commercial (https://ghostscript.readthedocs.io/en/latest/VectorDevices.html) |

### 2d. Invisible OCR text layer

The reference technique is Tesseract's `pdfrenderer.cpp` (https://raw.githubusercontent.com/tesseract-ocr/tesseract/main/src/api/pdfrenderer.cpp), also used by OCRmyPDF:
- One embedded Type0/CIDFontType2 font "GlyphLessFont" (Identity-H) whose glyphs are empty; every CID maps to GID 1 ("if I use GID 0 then Acrobat gets upset"); `/DW 500`, `/FontBBox [0 0 500 1000]`, Ascent 1000, Descent −1, Flags 5.
- A ToUnicode CMap mapping `<0000>–<FFFF>` identity, text written as UTF‑16BE hex; this is what makes copy/paste and search work and what satisfies PDF/A-2u's Unicode requirement.
- Each block: `BT 3 Tr` (invisible), `Tm` with rotation for the line baseline, font size from word height, and **`Tz` horizontal scaling = `2 * 100 * word_width_pt / (fontsize * glyph_count)`** so the invisible run exactly spans the word's bounding box; words separated by an explicit U+0020.
- Vision gives what we need: `RecognizedTextObservation` per line with `topCandidates(n)` → `RecognizedText.string`, `.confidence`, and `boundingBox(for: Range<String.Index>) -> RectangleObservation?` for sub-ranges (per word) (https://developer.apple.com/documentation/vision/recognizedtext). iOS 26 `RecognizeDocumentsRequest` → `DocumentObservation` adds paragraphs, tables (cells with row/column ranges and bounding regions), lists, barcodes, detected data (emails, dates, amounts, tracking numbers); words are not provided for CJK/Thai; 26 languages (https://developer.apple.com/documentation/vision/recognizedocumentsrequest ; WWDC25 272).
- Viewer compatibility: Preview, Acrobat, Drive and Chrome all extract text from this construction (it is what OCRmyPDF ships); the "sandwich" renderer caveat in OCRmyPDF ("some viewers may run words together") is avoided by emitting explicit spaces and per-word placement (https://ocrmypdf.readthedocs.io/en/latest/advanced.html).
- Alternative: draw invisible text with Core Graphics `CGTextDrawingMode.invisible` (`kCGTextInvisible = 3`) and a real font; CG embeds the font subset and a ToUnicode map (**memory, verify**) but sizes each word by the real font's advances, so boxes drift; the glyphless approach is deterministic and smaller.
- PDFKit `saveTextFromOCROption` (iOS 16) is worth a 1-day spike as a fallback, but Apple gives no description of positioning or language behaviour.

### 2e. Compression and file-size targets

- **JPEG (DCTDecode)**: universal, PDF/A-1 safe. Ghostscript's defaults illustrate the quality scale: QFactor 0.9 default, 0.4 printer, 0.15 prepress, 0.76 screen/ebook; `PassThroughJPEGImages` avoids recompression (https://ghostscript.readthedocs.io/en/latest/VectorDevices.html). Core Graphics passes JPEG data through unchanged when the `CGImage` originates from JPEG data (**widely observed, verify**); our own writer simply embeds the JPEG bytes.
- **JPEG 2000 (JPXDecode)**: allowed from PDF/A-2; better quality/byte and lossless modes, but ImageIO's JPEG 2000 encoder status on recent iOS is **unknown** (Apple deprecated/removed J2K in recent SDKs per memory, verify); not recommended for v1.
- **CCITT G4**: lossless bilevel, always available (OCRmyPDF converts mono images to G4 as an "always-on" optimisation) (https://ocrmypdf.readthedocs.io/en/latest/optimizer.html).
- **JBIG2**: in PDF since 1.4 (2001); JBIG lossless press release claims **3–5× smaller than G4** (https://en.wikipedia.org/wiki/JBIG2). Encoder: `jbig2enc` (Apache-2.0, https://raw.githubusercontent.com/agl/jbig2enc/master/COPYING) on Leptonica (BSD-ish), C++ and compilable for iOS; patents expired 2017 (OCRmyPDF docs). **Use generic-region (lossless) only**: OCRmyPDF removed `--jbig2-lossy` because of the Xerox 6↔8 substitution problem; NARA rejects lossy JBIG2; BSI restricts it (https://ocrmypdf.readthedocs.io/en/latest/jbig2.html ; Wikipedia). Decoder support in Apple's PDF stack exists (**memory, verify** with a test file on iOS 17+).
- **MRC**: ISO/IEC 16485 three-layer model (bilevel mask + two image layers) achieves high ratios on mixed pages; in PDF it is built from an `/SMask`-ed foreground image over a downsampled background (https://en.wikipedia.org/wiki/Mixed_raster_content). No off-the-shelf iOS encoder; v2 feature.
- OCRmyPDF's practical levels: `-O1` lossless (JBIG2, Deflate, object streams), `-O2` adds lossy JPEG re-encode and quantisation, `-O3` more aggressive; the text layer itself can increase size (https://ocrmypdf.readthedocs.io/en/latest/optimizer.html).

Targets (my typical figures from the above codecs; **not measured** in this run; validate on the corpus):

| Page type | Mode | 300 ppi Letter | Est. size |
|---|---|---|---|
| Black text on white (letters, forms) | Gray JPEG q≈45 | 2550×3300 | 250–450 KB |
| Same | Bilevel JBIG2 generic | 2550×3300 1-bit | 25–70 KB |
| Same | CCITT G4 | 1-bit | 60–150 KB |
| Colour letterhead/receipts | Colour JPEG q≈50, chroma 4:2:0 | 2550×3300 | 400–900 KB |
| Photo-heavy glossy | Colour JPEG q≈65 | 2550×3300 | 0.8–1.5 MB |

"<300 KB text page" is met by gray JPEG at modest quality or trivially by lossless JBIG2; the archival master should remain the gray/colour JPEG and bilevel used only for a "compact copy".

### 2f. Keeping the original full-resolution capture

- The 24 MP HEIF (Apple's default photo format, listed for all current iPhones) is the highest-fidelity artefact and costs ~2–4 MB (**typical, unmeasured**); JPEG at the same resolution is 2–3× larger. Keep it as `originals/<sha256>.heic` with EXIF intact (capture time, device, focal length) because it enables re-processing when enhancement or OCR models improve.
- Durability chain: write HEIC to the app container → compute SHA‑256 → derive PDF → run structural self-check (xref parse, page count, text extract) → upload PDF (and HEIC if enabled) → verify remote size/checksum (Drive returns `md5Checksum`/`sha256Checksum` in the File resource; **memory, verify**) → only then show "secured" and allow local eviction. PDF/A-3 could embed the HEIC inside the PDF, but it doubles size and HEIC is not an archival format; prefer a sidecar.

### 2g. Metadata to embed

- **Info dictionary** (via our writer; CG keys exist too): `/Title` = "2024 Form 1099-INT — Chase", `/Subject` = one-line summary, `/Keywords` = comma list (`tax, 1099, 2024, chase`), `/Creator`/`/Producer`, `/CreationDate` (capture time), `/ModDate`.
- **XMP** (mandatory for PDF/A; must agree with Info dict): `dc:title`, `dc:description`, `dc:subject` (bag of keywords), `dc:creator`, `xmp:CreateDate/ModifyDate/CreatorTool`, `pdf:Producer`, `pdf:Keywords`, `pdfaid:part=2 pdfaid:conformance=B`, `xmpMM:DocumentID/InstanceID` (UUID; pair with the PDF trailer `/ID`).
- **Custom schema**: `xmlns:pap="https://<product>/ns/1.0/"` with `pap:docType`, `pap:sender`, `pap:documentDate`, `pap:taxYear`, `pap:amount`, `pap:currency`, `pap:originalSHA256`, `pap:captureDevice`, `pap:ocrEngine`, `pap:classifierModel`. PDF/A-2 requires custom properties to be described by a `pdfaExtension` schema block (property name, valueType, category, description) — veraPDF fails files that use undeclared namespaces (**standard requirement, ISO 19005-2 §6.6.2.3.2; verify with veraPDF**).
- Mirror outside the PDF so every target can search: Google Drive `contentHints.indexableText` (128 KB limit) and `properties`/`appProperties` (https://developers.google.com/workspace/drive/api/reference/rest/v3/files), queried with `fullText contains '...'` (https://developers.google.com/workspace/drive/api/guides/search-files); `ocrLanguage` hint exists for image uploads (https://developers.google.com/workspace/drive/api/reference/rest/v3/files/create). On-device: Core Spotlight `CSSearchableItem` with `textContent`, keywords and dates (and a `CSImportExtension`, iOS 15+, if we ever expose our own file type) (https://developer.apple.com/documentation/corespotlight/csimportextension). Synology: Universal Search KB pages are JS-rendered and returned no content; behaviour on image-only PDFs **unknown** — ship a text layer regardless and a sidecar `.json` per document.

### 2h. Rotation correction and multi-page assembly

- Orientation: Vision requests take an `orientation` parameter; run `RecognizeTextRequest` in `.fast` mode on a 1000 px thumbnail at 0/90/180/270 (or the two plausible ones from the quad's aspect) and pick the orientation with the highest total confidence × character count; rotate pixels before the accurate pass so the stored image is upright and the `/Rotate` entry stays 0 (viewers and Drive thumbnails are more reliable that way).
- Page-to-document grouping: capture order + timestamp gap, "Page n of m" patterns (DataDetection in `RecognizeDocumentsRequest`), same sender/letterhead, same paper colour/size; keep every page as its own PDF/A file internally and assemble multi-page documents by re-emitting the same image/text objects into one file (our writer makes this a byte copy, no re-encode). Do not merge via PDFKit (re-serialisation risks PDF/A metadata).
- Duplicate detection: perceptual hash (dHash/pHash) of the 256 px gray corrected thumbnail (<5 ms) plus OCR text shingles after the fast pass; near-duplicates with different timestamps = "already scanned", announce via `AVSpeechSynthesizer`/haptics.

### 2i. Export bundles

- Print: `UIPrintInteractionController.shared` with `printingItem = pdfData/URL` or `printingItems`, `UIPrintInfo.outputType = .grayscale/.general/.photo`; AirPrint only; always a system sheet (no silent printing) (https://developer.apple.com/documentation/uikit/uiprintinteractioncontroller).
- Share/AirDrop: `UIActivityViewController` with file URLs; email packs via `MFMailComposeViewController` (mail-provider attachment limits ~25 MB, so pack = merged PDF or zip).
- Zip: Apple Archive framework (iOS 14+, `.aar` — not zip) or ZIPFoundation (MIT) / libarchive for real `.zip`; include `index.json` + CSV manifest.
- Merged PDF: our writer; optionally PDF/A-3 with the manifest attached.

## 3) Options compared

| Option for the PDF/A + OCR layer | Speed on device | PDF/A | Control over text layer/compression | Cost | Risk |
|---|---|---|---|---|---|
| A. Own Swift PDF/A-2b writer + Vision OCR + ImageIO JPEG (+ jbig2enc later) | best (no re-parsing; write is ms) | 2b/2u by construction, veraPDF-gated | total | engineering ~3–4 weeks + CI | spec mistakes early; mitigated by veraPDF |
| B. Core Graphics/PDFKit (`UIGraphicsPDFRenderer`, `saveTextFromOCROption`) | good | none (no XMP/pdfaid) | low (codec choices opaque) | free, fastest MVP | not archival; opaque OCR placement |
| C. Commercial SDK (Scanbot / Genius Scan / Nutrient) | good, all on-device | Genius Scan flag only; others unknown | medium | $2.5k+/yr (Scanbot) to quote-only; OCR add-ons | vendor lock-in, UI assumptions, App Store product margins |
| D. Server-side OCRmyPDF/Ghostscript conversion | adds upload+round trip (seconds) | mature 2b | high | AGPL (Ghostscript) or commercial; infra | breaks offline + "captured means safe" latency |
| E. Hybrid: A on device, D as nightly re-validator/re-optimiser (MRC, JBIG2) | best UX | 2b | highest | A + small worker | two code paths to keep consistent |

## 4) Recommendation for this project

1. **Capture**: custom `AVCaptureSession` with the Main camera at 24 MP HEIF (`maxPhotoDimensions` set once before `startRunning()`), continuous `DetectDocumentSegmentationRequest` on the 1080p preview buffer, auto-trigger when quad is stable for ~300 ms, sharpness (Laplacian variance on the quad region) above threshold and `DetectLensSmudgeRequest` below 0.9. No shutter button. Add the fixed-stand mode later as a mere "burst when quad changes" variant.
2. **Enhance**: Core Image graph entirely on GPU: `CIPerspectiveCorrection` (quad from the full-res frame, re-detected on the still) → `CILanczosScaleTransform` to the output ppi (300, or 400 if the source supports it) → `CIDocumentEnhancer` (amount tuned per page type) → `CIUnsharpMask` → colour/gray decision. Skip OpenCV in v1.
3. **PDF**: build `ArchivePDFWriter` in Swift that emits PDF/A-2b with: one image XObject per page (JPEG pass-through; CCITT G4 or JBIG2-generic for bilevel), GlyphLessFont invisible text from Vision boxes with `Tz` fitting, sRGB OutputIntent (embed the sRGB IEC61966-2.1 ICC, ~3 KB), XMP packet with dc/xmp/pdf/pdfaid + `pap:` extension schema, trailer `/ID`, no encryption. Gate every build and a nightly corpus run with veraPDF (Docker) and a Preview/Acrobat/Chrome text-extraction diff test.
4. **OCR**: iOS 18+ Swift Vision (`RecognizeTextRequest` accurate, language correction on, `automaticallyDetectsLanguage`), and on iOS 26+ `RecognizeDocumentsRequest` to also get paragraphs/tables/detected data for the classifier. Fast-mode thumbnail pass only for orientation + dedupe.
5. **Compression policy**: archival master = gray or colour JPEG at 300 ppi (q 45–60); "compact" derivative on demand with JBIG2 generic for text pages; MRC in v2. Never lossy JBIG2.
6. **Originals**: keep HEIC until the PDF is validated and uploaded; a setting "keep negatives" stores them forever in `originals/`.
7. **Metadata**: Info + XMP as in 2g, mirrored to Drive `appProperties`/`indexableText`, Core Spotlight and a sidecar JSON next to the PDF on NAS/iCloud.
8. **Assembly/export**: page-level PDFs as the unit of durability; documents assembled by the same writer; print via `UIPrintInteractionController`; zip via ZIPFoundation; email packs via `MFMailComposeViewController`.
9. **Per-page budget (iPhone 15 Pro+ class; estimates to be measured)**: preview detection 10–30 ms/frame; still capture 24 MP ~200–400 ms; warp+enhance 100–300 ms (GPU); dedupe hash <5 ms; fast-orientation OCR ~100–200 ms; accurate OCR 0.5–2 s; JPEG encode 50–100 ms; PDF write <20 ms; JBIG2 generic 100–300 ms (CPU). User-visible "captured" feedback at ~150–400 ms after the shutter; everything else runs on a background actor queue and the page shows a spinner-free progress tick.

## 5) Risks and unknowns

- Measured Vision OCR latency at page resolution is unknown; if accurate mode exceeds ~2 s on the oldest supported device, OCR must downscale to ~200 ppi (text ≥10 px high is Google's own minimum for OCR, per Drive help https://support.google.com/drive/answer/176692).
- Core Image `CIDocumentEnhancer` version floor and behaviour on coloured paper are undocumented; need a corpus test.
- JBIG2 encoder on iOS: jbig2enc + Leptonica must be built for arm64 and the generic-region path benchmarked; decoder support in PDFKit must be verified.
- PDF/A extension-schema correctness and Info/XMP agreement are the two most common veraPDF failures; build the validator into CI from day one.
- Apple may change `maxPhotoDimensions` behaviour or HEIC defaults; iPhone 18 Pro's variable aperture is new and untested for document DoF.
- Synology Universal Search behaviour on PDFs with text layers could not be verified (KB is JS-rendered); Google Drive OCR of image-only PDFs is also not stated in the fetched help pages.
- Commercial SDK prices are quote-only (Nutrient) or "from $2,500/yr" (Scanbot); a consumer App Store product with thousands of users may still be fine economically, but OCR add-ons are extra.
- FADGI star-level ppi table and some Apple version floors are cited from memory and flagged.

## 6) Open questions for the founder

1. Minimum supported iPhone/iOS: iOS 18 (Swift Vision API) or iOS 26 (document structure API)? This decides whether `RecognizeDocumentsRequest` is a baseline or an enhancement.
2. Archival master policy: gray/colour JPEG at 300 ppi only, or also keep HEIC negatives forever (roughly 3× storage)?
3. Is bilevel JBIG2 "compact mode" wanted at all, given lossless-only means ~2–4× the size of lossy competitors but no substitution risk?
4. Should documents be stored as one PDF per page (maximum durability, simplest sync) with a logical grouping index, or physically merged multi-page PDFs on the user's storage?
5. Which conformance level to advertise: PDF/A-2b (standard) or 2u (adds Unicode guarantee — our text layer satisfies it)?
6. Do you want PDF/A-3 attachments (original HEIC and/or the AI-extracted JSON inside the PDF) or sidecar files?
7. Is a server-side nightly re-optimiser (OCRmyPDF/MRC) acceptable for a privacy story that otherwise is "all on device"?
8. Budget appetite for a commercial SDK as a stop-gap (Genius Scan has the only documented PDF/A flag) versus building the writer.

## 7) Sources

- Apple Vision RecognizeDocumentsRequest: https://developer.apple.com/documentation/vision/recognizedocumentsrequest
- Apple WWDC25 272 "Read documents using the Vision framework": https://developer.apple.com/videos/play/wwdc2025/272/
- Apple DetectDocumentSegmentationRequest: https://developer.apple.com/documentation/vision/detectdocumentsegmentationrequest
- Apple DetectedDocumentObservation: https://developer.apple.com/documentation/vision/detecteddocumentobservation
- Apple RecognizeTextRequest: https://developer.apple.com/documentation/vision/recognizetextrequest
- Apple RecognizedText: https://developer.apple.com/documentation/vision/recognizedtext
- Apple VNDocumentCameraViewController: https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller
- Apple VNDocumentCameraScan: https://developer.apple.com/documentation/visionkit/vndocumentcamerascan
- Apple CIDocumentEnhancer: https://developer.apple.com/documentation/coreimage/cidocumentenhancer
- Apple CGPDFContext auxiliary keys: https://developer.apple.com/documentation/coregraphics/auxiliary-dictionary-keys
- Apple kCGPDFContextOutputIntent: https://developer.apple.com/documentation/coregraphics/kcgpdfcontextoutputintent
- Apple PDFDocumentWriteOption: https://developer.apple.com/documentation/pdfkit/pdfdocumentwriteoption
- Apple PDFDocument.write(to:withOptions:): https://developer.apple.com/documentation/pdfkit/pdfdocument/write(to:withoptions:)
- Apple UIGraphicsPDFRenderer: https://developer.apple.com/documentation/uikit/uigraphicspdfrenderer
- Apple UIPrintInteractionController: https://developer.apple.com/documentation/uikit/uiprintinteractioncontroller
- Apple AVCaptureDevice.minimumFocusDistance: https://developer.apple.com/documentation/avfoundation/avcapturedevice/minimumfocusdistance
- Apple AVCapturePhotoOutput.maxPhotoDimensions: https://developer.apple.com/documentation/avfoundation/avcapturephotooutput/maxphotodimensions
- Apple CSImportExtension: https://developer.apple.com/documentation/corespotlight/csimportextension
- iPhone 17 Pro tech specs: https://support.apple.com/en-us/125090
- iPhone 17 tech specs: https://www.apple.com/iphone-17/specs/
- iPhone 18 Pro tech specs: https://support.apple.com/en-us/148590
- Tesseract pdfrenderer.cpp: https://raw.githubusercontent.com/tesseract-ocr/tesseract/main/src/api/pdfrenderer.cpp
- OCRmyPDF introduction / advanced / optimizer / jbig2: https://ocrmypdf.readthedocs.io/en/latest/introduction.html ; https://ocrmypdf.readthedocs.io/en/latest/advanced.html ; https://ocrmypdf.readthedocs.io/en/latest/optimizer.html ; https://ocrmypdf.readthedocs.io/en/latest/jbig2.html
- Ghostscript PDF/A: https://ghostscript.readthedocs.io/en/latest/VectorDevices.html
- PDF/A overview: https://en.wikipedia.org/wiki/PDF/A
- JBIG2: https://en.wikipedia.org/wiki/JBIG2 ; jbig2enc: https://github.com/agl/jbig2enc ; licence https://raw.githubusercontent.com/agl/jbig2enc/master/COPYING
- MRC: https://en.wikipedia.org/wiki/Mixed_raster_content
- veraPDF: https://github.com/veraPDF/veraPDF-library ; https://verapdf.org/software/
- MuPDF: https://mupdf.readthedocs.io/en/latest/ ; https://mupdf.readthedocs.io/en/latest/tools/mutool-draw.html
- PDFium README: https://pdfium.googlesource.com/pdfium/+/refs/heads/main/README.md
- OpenCV iOS build script: https://raw.githubusercontent.com/opencv/opencv/4.x/platforms/ios/build_framework.py
- Nutrient iOS: https://www.nutrient.io/guides/ios/ ; https://www.nutrient.io/guides/ios/conversion.md ; https://www.nutrient.io/guides/ios/conversion/scan-to-searchable-pdf.md ; https://www.nutrient.io/guides/ios/ocr/overview.md ; https://www.nutrient.io/guides/ios/customizing-pdf-pages/customizing-document-metadata.md ; https://www.nutrient.io/guides/ios/announcements/version-support.md ; https://www.nutrient.io/sdk/pricing/
- Scanbot iOS: https://docs.scanbot.io/document-scanner-sdk/ios/ ; https://docs.scanbot.io/ios/document-scanner-sdk/filters-and-image-processing/available-image-filters/ ; https://docs.scanbot.io/ios/document-scanner-sdk/document-enhancer/introduction/ ; https://docs.scanbot.io/ios/document-scanner-sdk/scan-result-handling/creating-pdf-documents/ ; https://docs.scanbot.io/ios/document-scanner-sdk/scan-result-handling/creating-searchable-pdf-documents-with-ocr/ ; https://scanbot.io/pricing/
- Genius Scan SDK: https://geniusscansdk.com/ ; https://geniusscansdk.com/docs/ ; https://geniusscansdk.com/docs/v6/custom-integration/pdf-generation/ ; https://geniusscansdk.com/docs/v6/custom-integration/ocr/ ; https://geniusscansdk.com/docs/v6/custom-integration/image-processing/
- Google Drive API: https://developers.google.com/workspace/drive/api/reference/rest/v3/files ; https://developers.google.com/workspace/drive/api/reference/rest/v3/files/create ; https://developers.google.com/workspace/drive/api/guides/search-files ; Drive OCR help https://support.google.com/drive/answer/176692 ; Drive search help https://support.google.com/drive/answer/2375114
- FADGI guidelines: https://www.digitizationguidelines.gov/guidelines/digitize-technical.html
