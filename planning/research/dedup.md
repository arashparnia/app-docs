# Instant duplicate detection and multi-page grouping for a hands-free paper scanner

Research date: 2026-11-03. Dimension: "already scanned" detection, same-template disambiguation, multi-page grouping, content-addressable storage. All latency numbers are labelled **measured** (someone published a measurement), **vendor claim**, or **estimate** (my extrapolation; must be benchmarked on device).

## 1. Executive summary

- No shipping scanner app or SDK (Scanbot, Dynamsoft, Genius Scan, Scanner Pro, retired Microsoft Lens) advertises "already scanned" page detection; the closest prior art is Paperless-ngx (exact SHA-256 at consume time plus an offline fuzzy text matcher) and photo-library "stacks" (Google/Apple), which combine visual similarity with a capture-time window. This is a differentiator we have to build ourselves.
- A single signal is not enough. Perceptual hashes (pHash/dHash/blockhash) are near-perfect on exact duplicates but degrade sharply under geometric change, and on documents they match *templates* rather than *content*: two monthly statements from the same bank will collide. Learned embeddings (Apple feature print, MobileCLIP) are more robust but have the same template problem.
- The decisive signal for "same page vs same form with different values" is text: a 128-bit SimHash over character 9-grams of the OCR output (Hamming ≤ 6, proven on 1M re-scanned book pages) plus an exact comparison of the numeric/ID tokens on the page (account number, date, amount, "Page 2 of 5").
- Recommended on-device cascade, all under ~100 ms after capture: (1) 64-bit dHash on the rectified page for frame-to-frame "same sheet still in view" tracking (<1 ms, estimate); (2) 256-bit blockhash + Apple `VNGenerateImageFeaturePrintRequest` revision 2 (768-d) or MobileCLIP-S0 (1.5 ms measured on iPhone 12 Pro Max) as a candidate filter; (3) SimHash + numeric-token set from Apple fast OCR (30 fps camera-paced on iPhone 16, measured) as the confirming signal.
- Policy: never silently drop a capture. "Already scanned" is announced instantly when all tiers agree; otherwise the new capture is stored and linked to the suspected original as a *variant* and the best-quality image is kept as canonical. This satisfies the durability guarantee while keeping zero-interaction.
- Multi-page grouping: on-device heuristics (capture gap, running header/footer hash, "page N of M" and sentence-continuity cues, blank-back detection) resolve most cases; a batched Claude Haiku 4.5 boundary decision over OCR text (zero-shot boundary F1 0.87-0.97 on public benchmarks, about $0.16-0.45 per 1,000 pages) can be a cloud second pass.
- Content addressing: SHA-256 of the archival PDF and of the normalized page PNG is the cross-device identity; Google Drive exposes `sha256Checksum` so the uploaded copy can be verified byte-for-byte before the "safe to discard the paper" state is shown.
- Biggest unknown: Apple feature-print latency on iPhone (no public measurement found) and the distance threshold on document pages. Both need a one-day benchmark with our own labelled set (same page re-photographed vs sibling statements).

## 2. Findings

### 2a. Perceptual hashing (pHash, dHash, aHash, blockhash, wavelet hash, PDQ)

**What the literature measures.** Zauner's benchmark of the pHash library (DCT hash, Marr-Hildreth, radial variance, block-mean) found: JPEG quality 80 barely moves any hash (DCT mean normalized distance 0.001); resizing is fine for DCT and block-mean (0.076 and 0.012); **rotation by 5 degrees breaks all of them** (DCT 0.335, block-mean 0.220, where 0.5 is "unrelated"), and block-mean stays usable only up to about 3 degrees at a 0.3 threshold; none survives a horizontal flip. Block-mean was ~16x faster than DCT in that implementation. Source: https://phash.org/docs/pubs/thesis_zauner.pdf (2010, old but still the most careful public benchmark).

A 2024 study of practical hashes (PDQ, PhotoDNA, NeuralHash) reached the same shape: robust to compression and resizing, not to filtering and rotation (https://arxiv.org/pdf/2406.00918). The 2026 MDPI comparison of aHash/dHash/pHash/wHash (64-bit) vs a VGG-16 embedding on UKBench and Amazon Berkeley Objects reports near-perfect MAP for hashes on exact duplicates at Hamming 0, with sharp drops on near-duplicates and transformed images (flip, rotation, crop); the CNN kept F1 around 0.88-0.92 where hash F1 stayed low, at 4-6x the compute; they used Hamming 0/10/32 as strict/moderate/relaxed thresholds (https://www.mdpi.com/2079-9292/15/7/1493).

**Implication for us.** The hashes are only usable *after* perspective correction and deskew, which Vision gives us for free (`VNDetectDocumentSegmentationRequest`, iOS 15+, returns the document quad: https://developer.apple.com/documentation/vision/vndetectdocumentsegmentationrequest). Residual rotation after rectification is typically well under 3 degrees, so block-mean/dHash on the rectified, grayscale, contrast-normalized page is in the regime where these hashes work.

**Thresholds.** For a random (unrelated) pair of 64-bit hashes, the probability of Hamming ≤ 10 is about 1.0e-8 and of ≤ 16 about 3.9e-5 (binomial tail, my computation). For 256-bit hashes it is negligible at any sane threshold. The real risk is not random collision but **structural collision**: document pages are low-entropy images (white page, black text blocks in the same places), so two pages printed from the same template land close together regardless of threshold. An invoice OCR project reports exactly this: "pHash detects shared vendor template layouts, NOT duplicate document content" (https://github.com/omkarande14/Invoice_OCR_Processing). A photo-search company found pHash false positives on images that merely share composition (https://rentafounder.com/the-problem-with-perceptual-hashes/). No published false-positive rate for "two statements from the same bank" exists; treat it as a hypothesis to measure, and assume hash distance alone cannot separate them.

**PDQ.** Meta's PDQ is a 256-bit DCT hash with a quality score; the reference guidance is match at Hamming ≤ 31 and discard hashes with quality ≤ 49; it can emit eight dihedral (rotation/flip) variants but does not guarantee rotational invariance (https://github.com/facebook/ThreatExchange/blob/main/pdq/README.md). The quality score is a useful "is this frame featureless/blurry" gate.

**Crop-resistant and wavelet hashes.** The `imagehash` library implements aHash, pHash, dHash, wHash (Haar), colorhash and a crop-resistant multi-segment hash (https://github.com/JohannesBuchner/imagehash). Crop resistance matters if the document quad is partly out of frame, but segment hashing is slower and we can simply require a full quad before capturing.

**Speed on iPhone (estimate).** dHash/blockhash on a 32x32 or 16x16 grayscale downsample of the rectified page is a few thousand integer ops; with vImage or Accelerate for the resize this is well under 1 ms. Hamming search over 10,000 stored 256-bit hashes with popcount is also under 1 ms. Nobody has published iPhone timings; the Institutional Books pipeline notes a Hamming compare is "two xors, two popcnts, and an addition" (https://arxiv.org/pdf/2608.19026).

### 2b. Image embeddings on device

**Apple Vision feature print.** `VNGenerateImageFeaturePrintRequest` exists since iOS 13 and returns a `VNFeaturePrintObservation` with `data`, `elementCount`, `elementType` and `computeDistance(_:to:)`; the iOS 18 Swift API is `GenerateImageFeaturePrintRequest` / `FeaturePrintObservation.distance(to:) -> Double` (https://developer.apple.com/documentation/vision/vngenerateimagefeatureprintrequest, https://developer.apple.com/documentation/vision/featureprintobservation). The vector comes from the upper layers of Apple's on-device classification network (WWDC19 session 222, https://nonstrict.eu/wwdcindex/wwdc2019/222/). Apple's Create ML Components docs give the sizes: **revision 1 = 299x299 input, 2048-d; revision 2 (iOS 17+) = 360x360 input, 768-d**, and recommend revision 2 (https://developer.apple.com/documentation/createmlcomponents/imagefeatureprint/revision.md, https://developer.apple.com/documentation/vision/vngenerateimagefeatureprintrequestrevision2.md).

Pitfalls (all from Apple forums, confirmed by an Apple engineer): comparing observations from different revisions throws error code 12 "The revision of the observations do not match", so pin the revision and store it with every vector (https://developer.apple.com/forums/thread/732876); on the Simulator the distance is a constant 19.737993 for any pair, so only benchmark on hardware (https://developer.apple.com/forums/thread/721760). Apple publishes no threshold and no latency. One shipped duplicate-photo app uses distance ≤ 0.3 as "same group" on 160x160 thumbnails and batches 50 images per autorelease pool to control memory (https://dev.to/zoomapps/finding-duplicate-photos-on-iphone-without-uploading-a-single-one-1okg); their revision is not stated, so the number is not transferable. Latency on iPhone: **unknown** (a Medium post claims iPhone 12 mini measurements but was not retrievable; https://medium.com/@MWM.io/apples-vision-framework-exploring-advanced-image-similarity-techniques-f7bb7d008763).

**MobileCLIP (Apple, Core ML).** Measured on iPhone 12 Pro Max, iOS 17.0.3, coremltools 7.0, batch 1: image encoder latency **S0 1.5 ms (256x256, 11.4M params), S1 2.5 ms, S2 3.6 ms, B 10.4 ms (224x224, ViT-B/16)**; text encoders 1.6-3.3 ms (https://arxiv.org/html/2311.17049v2, Core ML exports at https://huggingface.co/apple/coreml-mobileclip). MobileCLIP2 (Aug 2025) claims S4 matches SigLIP-SO400M at 2.5x lower latency on the same phone but gives no absolute ms in the parts I could read (https://arxiv.org/html/2508.20691v1). This is the fastest documented learned embedding on iPhone and ships under Apple's license.

**SigLIP 2 / DINOv2 / DINOv3.** A model card reports SigLIP 2 base (int8) at a median 14 ms per image on iPhone 16 Plus vs 8 ms for TinyCLIP (vendor claim, https://huggingface.co/houssemzaier/iris-scene-encoders). DINOv2 ViT-S/14 Core ML fp16: 41.2 ms median on a Mac at 518x518; no iPhone number (https://huggingface.co/mlboydaisuke/DINOv2-ViT-S14-ExecuTorch). DINOv3 ViT-B/16 Core ML exists at 448x448 with no latency reported (https://huggingface.co/rinpatch/dinov3-coreml). Compute-unit choice matters: several ports found the Neural Engine slower than GPU for ViTs, and first-run compilation can cost seconds, so warm up at launch.

**Fit for documents.** All of these are trained on natural images and photo-text pairs. On a page of 10-pt text they will encode layout and coarse structure, so, like perceptual hashes, they say "same template" more than "same content". They are still worth running as a cheap second opinion because they are robust to the residual geometric and photometric differences that break hashes. A document-tuned small model (distilled on our own page pairs) is the "custom modeling later" path.

### 2c. Text-based near-duplicate detection on OCR output

**Strongest prior art for re-scanned pages.** Harvard's Institutional Books pipeline deduplicates ~1M scanned books and states plainly: "Scanning the same physical page twice usually yields slightly different OCRed text. Thus we search for near-duplicate pages." Their recipe: 128-bit SimHash (MurmurHash3) over character 9-grams, hashing only 9-grams with ≥ 4 distinct characters (so "........" runs do not dominate), pages under 50 characters excluded, **duplicate if Hamming ≤ 6 bits**, union-find to cluster, and 5 bits for paragraph-level dedup with 6-band LSH; 1.98M duplicate pages removed across 983k books (https://arxiv.org/pdf/2608.19026). This is exactly our "re-photographed page" problem at scale.

**Classic thresholds.** Manku et al. validated 64-bit SimHash with k = 3 bits for 8 billion web pages (https://www.www2007.cpsc.ucalgary.ca/papers/paper215.pdf). The 128-bit/≤ 6-bit setting above is more tolerant, which is appropriate for OCR noise.

**MinHash vs SimHash under OCR noise.** On NEWS-COPY (27,210 historical news articles whose duplicates differ by OCR errors), MinHash scored ARI 0.783 vs SimHash 0.695, and the 536k-parameter neural RETSim 0.831; all n-gram methods degrade steeply as edit noise rises and perform poorly on texts under 128 characters (https://arxiv.org/pdf/2311.17264). So: use character-level shingles (not words), prefer MinHash when you need a graded Jaccard score and SimHash when you need a fixed 16-byte key for an index; both are sub-millisecond for a 3,000-character page (estimate).

**Paperless-ngx.** Exact duplicates are caught at consume time by SHA-256 of the file (maintainer statement); a re-scan therefore slips through, and the answer is the offline `document_fuzzy_match --ratio 85` command (rapidfuzz ratio over stored content, metadata ignored), which the maintainer refuses to run at consume time because pairwise matching is O(n²) (https://github.com/paperless-ngx/paperless-ngx/discussions/2716, https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/administration.md). Version 3.2.0 added a "has duplicates" list filter. Lesson: index a hash (SimHash/LSH), do not do pairwise ratio.

**OCR speed budget.** Apple `VNRecognizeTextRequest` fast level ran camera-paced at 30 captures/s on 1080x1920 frames on an iPhone 16 vs 4/s for accurate; fast skips text smaller than 1/32 of image height (measured by a third party, https://pub.dev/packages/text_sight/versions/0.2.1). For the dedup signal we only need the fast pass on the rectified page; the accurate pass (and iOS 26 `RecognizeDocumentsRequest` with paragraphs/tables, WWDC25 session 272: https://developer.apple.com/videos/play/wwdc2025/272/) can run afterwards for the archive.

### 2d. Fusing signals into an under-100 ms decision

Measured budget on a current iPhone: document quad + rectification (Vision, "a few ms" general claim, not measured), dHash/blockhash < 1 ms (estimate), MobileCLIP-S0 1.5 ms (measured, iPhone 12 Pro Max), feature print unknown (estimate 5-20 ms on ANE), fast OCR ≈ 33 ms per frame (derived from 30 fps camera-paced), SimHash + token extraction < 2 ms (estimate), index lookups < 1 ms (estimate). Total ≈ 50-60 ms after the capture frame is chosen, leaving headroom. The decision can be announced before the archival PDF is built.

Confidence policy (recommended):

| Evidence | Decision | UI |
|---|---|---|
| SHA-256 of normalized page PNG equal (only happens for the same file, e.g. sync replay) | exact duplicate, do not store twice | silent |
| Text SimHash Hamming ≤ 3 AND numeric-token set identical AND visual distance under strict threshold | auto-skip | "Already scanned" chime, < 100 ms |
| Text SimHash ≤ 8 OR visual under loose threshold, but numeric tokens differ | keep as new page, flag "similar to X" | none (zero interaction) |
| Text SimHash ≤ 6 and numeric tokens equal but visual far (e.g. heavy glare) | keep as *variant* of X, pick sharper image as canonical | "Already scanned (kept better copy)" |
| Low OCR yield (< 50 characters: photos, blank backs) | fall back to visual tiers only, never auto-skip | none |

"Keep as variant" is the key to durability: the capture is written to the content-addressed store regardless; only the catalog decides whether it becomes a new page or a quality upgrade of an existing one. Thresholds must be calibrated on a labelled set of (a) the same page re-photographed at several angles/lightings and (b) sibling pages from the same sender; the Institutional Books 6-bit figure is the starting point for text, Hamming ≤ 10 of 64 (or ≤ 31 of 256 for PDQ) for image hashes, and the feature-print threshold must be measured because Apple publishes none.

### 2e. Same template, different values

Duplicate-invoice practice in accounts payable converges on progressive matching: exact on (vendor, invoice number, amount), then relaxed (same vendor and amount within a date window, ignoring number formatting), then fuzzy vendor names; normalize identifiers ("INV-1001" vs "INV1001") before comparing (https://www.infrrd.ai/blog/how-to-detect-duplicate-invoices, https://www.spendesk.com/blog/duplicate-invoices/). Applied here: extract an **anchor-token set** from the fast OCR text with regexes (dates, amounts, account/reference/policy numbers, "Page N of M", ZIP codes, phone numbers) and compare it as a set. Two statements from the same bank share layout, header and most boilerplate (hash and embedding say "duplicate") but differ in statement date, closing balance and transaction lines (anchor tokens say "different"). Because SimHash weights every 9-gram equally, a page whose only differences are a handful of numbers can still land within 6 bits, which is why the token-set check is mandatory before auto-skip. Full field extraction (account number + statement date) by Claude is the slow, authoritative version of the same test and should back-fill the catalog so later captures can be matched against structured fields too.

### 2f. Multi-page grouping (page stream segmentation)

What the benchmarks say: on OpenPSS (141k pages, 32k documents, Dutch FOIA releases; about one-third pure image scans), the best page-level boundary F1 is 0.83 (BERT text, or late text+image ensembling), text models are the most robust across datasets, and visual-only models lag (https://irlab.science.uva.nl/wp-content/papercite-data/pdf/heus_open24.pdf). The 2018 CNN study reached 0.93 accuracy on Archive22k and 0.91 on Tobacco800 with combined image + text features (https://ar5iv.labs.arxiv.org/html/1710.03006). On insurance streams, XGBoost on OCR features gets page F1 0.902 / stream F1 0.827 while fine-tuned Mistral-7B gets 0.944 / 0.879; the paper's failure example is a new page header that XGBoost missed (https://aclanthology.org/2025.coling-industry.26.pdf). Zero-shot LLMs do well on text: Claude Haiku 4.5 boundary F1 0.866 on TABME++ and 0.969 on VRDU forms, Gemini 3.1 Flash-Lite 0.883 / 0.971, with multi-split prompting cutting cost to about $0.16-0.45 per 1,000 pages at ~1.2 s per call (https://arxiv.org/html/2609.22620v1). DocSplit (995 documents, 5,231 pages, 13 types) finds clustering pages into documents is the bottleneck (0.56-0.90) and lists the cues models use: content continuity, consistent headers/footers/layout, new title pages, topic shifts, signature pages (https://arxiv.org/html/2602.15958v1). The prompt cue list from the multi-split paper is a ready checklist: header/footer match, page-number sequence, content flow, style/terminology, document identifiers, sentence continuity, letterhead/logo/margins.

Hands-free capture adds signals the batch-scanner literature does not have:

- **Temporal proximity.** Google Photos stacks and the underlying patent group by "captured close together" plus visual similarity (https://support.google.com/photos/answer/14169846, https://patents.google.com/patent/US10127246). A capture gap under ~15-20 s is strong evidence of the same document; a gap over a minute (user opened the next envelope) is a soft boundary.
- **Running header/footer.** dHash of the top 8% and bottom 8% strips of consecutive rectified pages; equal strips = same document. Cheap and language-independent.
- **"Page N of M" / "continued".** Regex over the fast OCR text; when M is known the group has a target size, and N resets to 1 on a new document.
- **Sentence continuity.** Previous page's last line lacking terminal punctuation and the next page starting lowercase is a continuation cue (used by the LLM prompts above).
- **Same sender.** Anchor tokens (account number, reference, sender name from the letterhead) repeating across consecutive pages.
- **Double-sided pages.** The user flips the sheet: expect the back within a few seconds, mirrored left/right margins, and often a blank or "intentionally left blank" back. Blank detection: ink coverage below ~0.5% combined with low pixel standard deviation (pdftl defaults, https://pdftl.readthedocs.io/en/latest/_sources/operations/delete_blank.md.txt); production capture tools expose separate front/back thresholds and dilate the front image to anticipate show-through (https://docshield.tungstenautomation.com/RSXB/en_US/3.9/help/Content/activities/xboundActClassifyEmptyPages.htm). Store blank backs as a flag, not as a page.
- **Stapled packets.** No vision cue is reliable for staples; treat "contiguous captures with consistent header/footer, sequential page numbers and no long gap" as a packet and let the cloud pass (Claude on the OCR text of the whole session, K=5 multi-split) confirm boundaries and reorder.

Recommendation: on-device heuristic grouping decides immediately (zero interaction), and the cloud pass may *regroup* later; since every page is stored individually under its own content hash, regrouping is a catalog edit, not a data move.

### 2g. Content-addressable storage

restic's design addresses every blob by the SHA-256 of its plaintext and skips storing a chunk whose ID already exists, which is the standard pattern for cross-device dedup and integrity (https://forum.restic.net/t/design-question-nonces-and-deduplication/8757). For us: `pageId = SHA-256(normalized rectified PNG)` and `docId = SHA-256(archival PDF bytes)`; every object name in Drive/NAS/iCloud is derived from these, so two devices or a replay after a crash can never create a second copy, and a pending upload can be verified. Google Drive's Files resource exposes output-only `md5Checksum`, `sha1Checksum` and `sha256Checksum` for binary content (https://developers.google.com/workspace/drive/api/reference/rest/v3/files), so "paper can be discarded" should be shown only after the remote `sha256Checksum` equals the local hash (Synology via SMB/WebDAV and iCloud Drive need a read-back or size+hash sidecar instead; no checksum API found). CryptoKit `SHA256` is available since iOS 13 (https://developer.apple.com/documentation/cryptokit/sha256); hardware-accelerated SHA-256 on an A11 runs at about 1.7 GB/s in wolfCrypt's benchmark (not CryptoKit, but same ARMv8 crypto extensions: https://www.wolfssl.com/wolfcryptwolfssl-benchmarks-with-iphone-88-plusx-a11/), so hashing a 5 MB page costs single-digit milliseconds.

Note that SHA-256 never matches two *photographs* of the same page; it is the identity of a capture, not of the paper. The paper's identity is the fused decision in 2d.

### 2h. Other prior art

- **Apple Photos Duplicates (iOS 16).** Runs in the background only when locked and charging and is deliberately conservative; mechanism undocumented (https://www.macworld.com/article/1366211/how-to-use-duplicate-detection-apple-photos.html). Not usable as an API.
- **LLAH (camera-based document retrieval).** Hashes the geometric arrangement of word centroids with perspective-invariant features; the authors report > 98% page retrieval under 150 ms per query on databases up to 50M pages, robust to perspective, occlusion and page curl (https://l3i.univ-larochelle.fr/Camera-Based-Recognition-Retrieval; lab claims, 2000s-2010s). This is the academic answer to "recognize this exact page from a handheld camera" and is a good fallback for pages with little OCR-able text (handwriting, forms with boxes); an implementation would be custom.
- **Local features (ORB/AKAZE + RANSAC homography).** Standard OpenCV pipeline (https://docs.opencv.org/4.x/dc/d16/tutorial_akaze_tracking.html); ORB for ~1000 keypoints was 15 ms on 2011 desktop hardware. Vision's `VNHomographicImageRegistrationRequest` (iOS 11+) does the alignment natively (https://developer.apple.com/documentation/vision/vnhomographicimageregistrationrequest). Useful as a tie-breaker for visually near-identical candidates, not as a first filter.

## 3. Options compared

| Signal | Cost per page (iPhone) | Robust to re-photo (angle/light) after rectification | Separates same-template pages | Cross-device identity | Verdict |
|---|---|---|---|---|---|
| SHA-256 of file | ~3 ms for 5 MB (derived from 1.7 GB/s hw SHA) | No (never matches) | Yes (trivially) | Yes | Mandatory for storage, useless for re-scan |
| dHash/blockhash 64-256 bit | < 1 ms (estimate) | Partial: fine to ~3 deg residual rotation, fails on crop/flip (Zauner) | No (template collision) | Approximate | Frame tracking and candidate filter |
| PDQ 256-bit + quality | ~1-2 ms (estimate) | Same as above, better margin; quality gate | No | Approximate | Alternative to blockhash; quality score useful |
| Apple feature print rev2 (768-d) | unknown (est. 5-20 ms, ANE) | Yes (photometric), moderate (geometric) | No | Revision-pinned vectors only | Good second tier; must benchmark |
| MobileCLIP-S0 (Core ML) | 1.5 ms measured (iPhone 12 Pro Max) | Yes | No | Yes (model version pinned) | Best measured speed; license OK |
| SigLIP 2 base / DINOv2-S | 14 ms (vendor, iPhone 16 Plus) / unknown | Yes | No | Yes | Only if S0 proves insufficient |
| Char-9-gram SimHash 128-bit (≤ 6 bits) | < 1 ms after OCR (estimate); OCR fast ≈ 33 ms | Yes (proven on 1M re-scanned pages) | Mostly, not when only numbers differ | Yes | Core confirming signal |
| MinHash (char shingles, Jaccard) | ~1 ms (estimate) | Yes; better than SimHash under OCR noise (0.783 vs 0.695 ARI) | Same caveat | Yes | Use for graded "similar to" score |
| Anchor numeric/ID token set | < 1 ms | Yes if OCR reads digits correctly | **Yes** | Yes | Mandatory before auto-skip |
| Claude field extraction | 1-3 s, cloud | Yes | Yes (authoritative) | Yes | Back-fill, not in the 100 ms path |
| LLAH / ORB homography | 20-150 ms (claims) | Yes, strongest geometric robustness | No | Yes | Fallback for text-poor pages |

## 4. Recommendation for this project

1. **Two-stage "same sheet" logic.** While the camera runs, compute a 64-bit dHash of the rectified quad every frame; if it is within ~6 bits of the last *captured* page, the user has not moved on, so do not re-trigger capture (this alone removes the most common "duplicate": the phone hovering over the page just captured). Capture triggers on quad-stable + sharp + hash-changed.
2. **Post-capture cascade (target < 100 ms, announce before PDF build):** rectified page → 256-bit blockhash (or PDQ with quality gate) → MobileCLIP-S0 embedding (1.5 ms measured) in parallel with Apple fast OCR (~33 ms) → 128-bit SimHash over character 9-grams with the ≥ 4-distinct-characters filter → anchor-token set. Query a local index: Hamming bucket on blockhash and SimHash (band LSH as in Institutional Books), cosine on a small in-memory vector table (thousands of pages fit trivially). Apply the policy table in 2d. Use `VNGenerateImageFeaturePrintRequest` revision 2 as a second embedding only after measuring its latency; if it is under ~10 ms, prefer it (no model to ship) and pin the revision.
3. **Never discard.** Every capture is written under its SHA-256 before the decision; "duplicate" is a catalog relation (variant-of) and the sharper capture (Laplacian variance) becomes canonical. Show the "safe to throw away" state only when the remote checksum verifies.
4. **Grouping on device, regrouping in cloud.** Heuristic grouper (gap < 20 s, header/footer dHash match, page N of M, sentence continuity, same anchor tokens, flip/blank-back detection) assigns pages to a document immediately. After the session, send the OCR text of the whole session to Claude Haiku 4.5 with a multi-split boundary prompt (K = 5 pages per call) plus the field-extraction prompt already planned for classification; apply its boundaries and extracted fields as a catalog update. Expected cost is well under $0.50 per 1,000 pages for the boundary pass.
5. **Build the calibration set first.** 200 pages: each re-photographed 5 times (angles, lighting, glare, partial shadow), plus 50 sibling pairs (same bank/insurer/utility, different months) and 20 blank/near-blank backs. Report per-tier ROC and the fused policy's false-skip rate; the false-skip rate (announcing "already scanned" for a new page) must be effectively zero because the paper gets thrown away.
6. **Later, custom model.** Distil a document-specific 128-d embedding (student: MobileCLIP-S0 image tower) on our own re-photo pairs with sibling pages as hard negatives; this is the path to a sub-5 ms single-signal decision and to handling text-poor pages without LLAH.

## 5. Risks and unknowns

- Apple feature-print latency and threshold on document pages: no public measurement; Simulator gives constant distances, so testing must be on device.
- Perceptual-hash false positives on same-template pages are documented anecdotally, not quantified; our calibration set is the only way to get a number.
- Fast OCR skips text under 1/32 of frame height; dense small-print pages may yield too few 9-grams for SimHash, pushing the decision to the visual tiers (lower confidence). Mitigation: run fast OCR on the rectified page at full resolution rather than the camera frame, or fall back to accurate OCR (4/s) for the dedup signal when yield is low.
- OCR digit errors can flip the anchor-token test both ways; use fuzzy numeric matching (one-digit edit tolerance) only for the "flag" path, never for auto-skip.
- Revision drift: Apple may change feature-print behaviour between iOS versions; store `requestRevision` and re-embed on upgrade (Apple's own guidance).
- Multi-page benchmarks are batch-scanner datasets; the hands-free temporal signals are untested in the literature (my design, not a measured result).
- Google Drive is the only target with a server-side SHA-256 we can read; Synology and iCloud Drive need our own verification step, otherwise the "paper can go" promise rests on the upload library's word.
- The "6 bits of 128" SimHash threshold was tuned on book pages with consistent OCR; phone OCR of crumpled mail may need a looser threshold, which raises sibling-page collision risk.
- Stale sources: Zauner (2010) and Manku (2007) are old but remain the cited baselines; the MobileCLIP numbers are on an iPhone 12 Pro Max (2020 hardware), so current phones should be faster.

## 6. Open questions for the founder

1. When a re-scan is sharper than the original, should the app silently replace the canonical image (recommended) or keep both and let search return either?
2. Is a false "already scanned" ever acceptable? If the answer is "never", the auto-skip tier must require all three signals and the app should show a thumbnail of the matched page in the chime toast so a wrong skip is noticeable without interaction.
3. Do you want duplicates found across the whole archive (bank statement scanned last year) or only within a session/day? Whole-archive is cheap with hash indexes but raises the sibling-page problem.
4. Double-sided mail: should the app expect a flip after every page (prompt-free "flip now" hint), or only group a back side when it arrives within a few seconds?
5. Which storage target is primary? Only Google Drive gives us a server-side SHA-256 to verify against.
6. Are you willing to ship a ~45 MB MobileCLIP-S0 model in the app, or do you prefer Apple's built-in feature print even if it is slower?
7. Is handwriting or text-poor paper (photos, drawings, forms with boxes) in scope for the duplicate guarantee? If yes, budget for an LLAH-style geometric hash.

## 7. Sources

- Apple, VNGenerateImageFeaturePrintRequest: https://developer.apple.com/documentation/vision/vngenerateimagefeatureprintrequest
- Apple, VNFeaturePrintObservation: https://developer.apple.com/documentation/vision/vnfeatureprintobservation
- Apple, FeaturePrintObservation (iOS 18 API): https://developer.apple.com/documentation/vision/featureprintobservation
- Apple, GenerateImageFeaturePrintRequest (iOS 18 API): https://developer.apple.com/documentation/vision/generateimagefeatureprintrequest
- Apple, ImageFeaturePrint revision sizes (2048 vs 768): https://developer.apple.com/documentation/createmlcomponents/imagefeatureprint/revision.md
- Apple, VNGenerateImageFeaturePrintRequestRevision2: https://developer.apple.com/documentation/vision/vngenerateimagefeatureprintrequestrevision2.md
- Apple forums, revision mismatch error 12: https://developer.apple.com/forums/thread/732876
- Apple forums, Simulator constant distance 19.737993: https://developer.apple.com/forums/thread/721760
- WWDC19 session 222 transcript: https://nonstrict.eu/wwdcindex/wwdc2019/222/
- Apple, VNDetectDocumentSegmentationRequest: https://developer.apple.com/documentation/vision/vndetectdocumentsegmentationrequest
- Apple, VNHomographicImageRegistrationRequest: https://developer.apple.com/documentation/vision/vnhomographicimageregistrationrequest
- Apple, CryptoKit SHA256: https://developer.apple.com/documentation/cryptokit/sha256
- WWDC25 session 272, RecognizeDocumentsRequest: https://developer.apple.com/videos/play/wwdc2025/272/
- text_sight OCR benchmark (iPhone 16): https://pub.dev/packages/text_sight/versions/0.2.1
- Duplicate photo app using feature print (threshold 0.3): https://dev.to/zoomapps/finding-duplicate-photos-on-iphone-without-uploading-a-single-one-1okg
- MobileCLIP paper (iPhone 12 Pro Max latencies): https://arxiv.org/html/2311.17049v2
- MobileCLIP Core ML models: https://huggingface.co/apple/coreml-mobileclip
- MobileCLIP2: https://arxiv.org/html/2508.20691v1
- SigLIP 2 / TinyCLIP iPhone 16 Plus latency (model card): https://huggingface.co/houssemzaier/iris-scene-encoders
- DINOv2 ViT-S/14 Core ML (Mac latency): https://huggingface.co/mlboydaisuke/DINOv2-ViT-S14-ExecuTorch
- DINOv3 Core ML: https://huggingface.co/rinpatch/dinov3-coreml
- Zauner, perceptual hash benchmarking thesis: https://phash.org/docs/pubs/thesis_zauner.pdf
- Robustness of practical perceptual hashes (2024): https://arxiv.org/pdf/2406.00918
- MDPI Electronics 2026, hashing vs deep embeddings: https://www.mdpi.com/2079-9292/15/7/1493
- PDQ README (threshold 31, quality 49): https://github.com/facebook/ThreatExchange/blob/main/pdq/README.md
- imagehash library: https://github.com/JohannesBuchner/imagehash
- pHash template-vs-content observation: https://github.com/omkarande14/Invoice_OCR_Processing
- The problem with perceptual hashes: https://rentafounder.com/the-problem-with-perceptual-hashes/
- Institutional Books pipeline (SimHash page dedup): https://arxiv.org/pdf/2608.19026
- Manku, Jain, Das Sarma, simhash for web crawling: https://www.www2007.cpsc.ucalgary.ca/papers/paper215.pdf
- RETSim / NEWS-COPY (MinHash vs SimHash under OCR noise): https://arxiv.org/pdf/2311.17264
- Paperless-ngx discussion on re-scan duplicates: https://github.com/paperless-ngx/paperless-ngx/discussions/2716
- Paperless-ngx administration docs (document_fuzzy_match): https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/dev/docs/administration.md
- Duplicate invoice detection practice: https://www.infrrd.ai/blog/how-to-detect-duplicate-invoices and https://www.spendesk.com/blog/duplicate-invoices/
- OpenPSS benchmark: https://irlab.science.uva.nl/wp-content/papercite-data/pdf/heus_open24.pdf
- PSS with CNNs (Archive22k, Tobacco800): https://ar5iv.labs.arxiv.org/html/1710.03006
- PSS with LLMs, insurance (COLING 2025): https://aclanthology.org/2025.coling-industry.26.pdf
- LLMs for PSS, TABME++: https://arxiv.org/abs/2408.11981
- Multi-split boundary decisions (Claude Haiku 4.5 numbers): https://arxiv.org/html/2609.22620v1
- DocSplit benchmark: https://arxiv.org/html/2602.15958v1
- Google Photos stacks: https://support.google.com/photos/answer/14169846
- Google patent, grouping similar photos: https://patents.google.com/patent/US10127246
- Apple Photos duplicates (iOS 16): https://www.macworld.com/article/1366211/how-to-use-duplicate-detection-apple-photos.html
- LLAH camera-based retrieval: https://l3i.univ-larochelle.fr/Camera-Based-Recognition-Retrieval
- OpenCV AKAZE/ORB planar tracking: https://docs.opencv.org/4.x/dc/d16/tutorial_akaze_tracking.html
- Blank page detection defaults (pdftl): https://pdftl.readthedocs.io/en/latest/_sources/operations/delete_blank.md.txt
- Blank page detection, front/back and show-through (Tungsten): https://docshield.tungstenautomation.com/RSXB/en_US/3.9/help/Content/activities/xboundActClassifyEmptyPages.htm
- restic content addressing: https://forum.restic.net/t/design-question-nonces-and-deduplication/8757
- Google Drive Files resource checksums: https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- wolfCrypt SHA-256 on A11: https://www.wolfssl.com/wolfcryptwolfssl-benchmarks-with-iphone-88-plusx-a11/
- Scanbot auto-snapping (no duplicate feature): https://docs.scanbot.io/cordova/document-scanner-sdk/features/document-scanner/document-scanner-ui
