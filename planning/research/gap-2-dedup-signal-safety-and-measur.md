# Gap 2: Which duplicate signal is safe to drive "already scanned", and what the error rates actually look like on mail

Research date: 2026-11-03. Gap-filling round on top of `dedup.md` (read first; not repeated here). Every number is labelled **measured** (someone published a measurement, or I ran it here), **vendor claim**, **computed** (arithmetic from a published fact), or **estimate**. Numbers I measured here come from a *synthetic* calibration set rendered and perturbed in software; they show the *shape* of each tier's behaviour, not phone-camera truth. Note: the web-search budget for this run was exhausted before my first query, so everything below comes from primary sources fetched directly by URL plus local measurement; I say "not found" where a search would normally have been made.

## 1. Executive summary

1. No tier is safe to *suppress* a capture. Every image hash I measured (dHash64, pHash64, wHash64, pHash256 as a PDQ proxy, 256-bit block-mean) places "this month's vs last month's statement" *inside* the same-page band: on a stand-mounted recapture the sibling statement scores dHash 1-5 while the same page scores 0-4. There is no threshold.
2. Text tiers separate most siblings but not all: 9-gram Jaccard cleanly splits same-page (0.81-0.97 at 0.3% OCR noise) from sibling statements (0.17-0.21), but a utility bill whose only differences are date and amount is indistinguishable from a re-OCR'd copy of itself (Jaccard 0.58-0.82 vs 0.56-0.94). Only field-level comparison (date, amount, account) resolves that case, and OCR digit errors flip that test too (same bill re-OCR'd at 2% CER: 6 of ~15 anchor tokens differ; sibling bills: 2 differ).
3. The Institutional Books "6 of 128 bits" SimHash threshold assumes near-identical OCR output; at 0.3% character error it already yields 4-19 bits for the same page, at 1% 6-26, at 2% 16-35. On a phone this threshold must be measured, not copied.
4. Short items (receipts, ~140 characters) are noisier at every tier: same-receipt SimHash 0-32 bits at 0.3% CER; dHash on a cropped receipt 7-26 bits. Under ~400 characters treat text tiers as advisory only, as the RETSim authors already found for n-gram methods under 128 characters.
5. Blank backs are hash noise (dHash 0-47 between two blank backs); they need an ink-coverage gate (and PDQ's quality score), never a hash match.
6. Index scale is not a problem: brute-force Hamming over 200,000 256-bit codes measured 0.39 ms per query on one x86 core here (0.11 ms for 64-bit); 200k pages of hashes is 12.8 MB. Embeddings are the only thing that needs quantization (768-d FeaturePrint rev2 in float32 is 627 MB at 200k; int8 166 MB; binarized 32 MB).
7. MobileCLIP weights are **not** safe for an App Store product as of today: Apple re-licensed them to the Apple Machine Learning Research Model license (research only, "does not include ... use in any commercial product or service") in Feb 2025; the 2024 Core ML repo still carries an `apple-ascl` tag pointing at a file that no longer exists. Use Apple's built-in `VNGenerateImageFeaturePrintRequest` (no model to license) or Apache-2.0/MIT alternatives (DINOv2, SigLIP 2, TinyCLIP).
8. Recommendation: the instant cue is driven by a *frame-level* signal (dHash on the preview quad against the last few captures) and is worded as "looks like page N", never "skipped"; the capture is always written; the catalog merges only when the text tier plus field-level anchors agree; everything else is a flagged variant.

## 2. Findings

### 2a. What the published numbers say about each image-hash tier

**dHash (64-bit).** The only published large-scale evaluation remains the 2013 Hacker Factor post: 150,000 photos, "match" at Hamming <= 10; dHash had "very few false positives" (example: 2 true matches, 4 false positives at distances 8-10), aHash about 10x more, pHash none; a 16-bit dHash has about 15 collisions per hash at 1M images ([hackerfactor](http://www.hackerfactor.com/blog/index.php?/archives/529-Kind-of-Like-That.html), measured on photos, 2013, stale). Nothing about documents.

**PDQ (256-bit).** Meta's design document is the best-characterised hash: random pairs average distance 128 "supported on the range of 90 to 160 or so"; thresholds of "30, 20, or less has been found to produce good results"; the empirical upper bound on any threshold is 90 (no pair of the 157 distinct CopyDays originals is closer); the provisional lower bound from JPEG-quality variants is "somewhere between 20-60"; at threshold 32, all 157 originals plus JPEG q75/q50 form perfect clusters, with 1 split at q30, 2 at q20, 5 at q15 (measured, photos; [hashing.pdf](https://github.com/facebook/ThreatExchange/blob/main/hashing/hashing.pdf)). PDQ hashes always have exactly 128 one-bits, so distances are almost always even; the quality metric is a gradient sum on the 64x64 luma downsample, capped at 100, and solid-colour images score 0. The 2024 robustness paper confirms PDQ is "not robust to: filtering, rotating, mirroring, bordering, cropping" with 1000 ImageNet images at normalized-distance 0.3 (=77 of 256 bits) ([arXiv 2406.00918](https://arxiv.org/pdf/2406.00918), measured, photos).

**Block-mean 256-bit.** The commonsmachinery `blockhash` implementation (MIT) follows Yang/Gu/Niu 2006 and publishes no accuracy numbers ([GitHub](https://github.com/commonsmachinery/blockhash)). Zauner's thesis (2010) is still the only ROC-style benchmark and only on photos ([phash.org](https://phash.org/docs/pubs/thesis_zauner.pdf)).

**Nothing on mail.** I found no published false-skip or false-alarm rate for any perceptual hash on same-template documents, page-1-vs-page-2, blank backs or receipts (search was unavailable this run; the prior report found only the anecdotal "pHash detects shared vendor template layouts, NOT duplicate document content"). That is why I measured it.

### 2b. Measured here: synthetic calibration of the image-hash tiers

Setup (all code in `../bench/synth.py` and `synth2.py`): A4 pages rendered at 150 dpi with a fixed "bank statement" template (logo block, address, summary, 26 transaction lines, footer), a "clinic letter" letterhead with two pages, a cropped receipt, blank backs with and without 6% show-through. "Recapture" simulates a second handheld photo after rectification: residual rotation +/-1.5 deg, scale 0.98-1.02, 1% translation, brightness/contrast 0.85-1.15, illumination gradient up to 25 grey levels, Gaussian blur 0.3-1.2 px, sensor noise sigma 3, JPEG q70-90. "Stand" is the same at 30% strength. 12 trials per row; cells are min / median / max Hamming distance. `pHash256` is imagehash's 16x16 DCT hash of a 64x64 downsample, structurally the same as PDQ and used as its proxy; `block256` is a 16x16 block-mean hash.

| Pair type | dHash64 | pHash64 | wHash64 | pHash256 (PDQ proxy) | block256 |
|---|---|---|---|---|---|
| Same page, two handheld recaptures | 1 / 3 / 4 | 0 / 5 / 12 | 0 / 3 / 8 | 8 / 36 / 64 | 12 / 40 / 48 |
| Same page, original vs recapture | 0 / 3 / 5 | 0 / 5 / 8 | 4 / 8 / 14 | 6 / 25 / 42 | 14 / 30 / 60 |
| **Sibling statement (next month), handheld** | **0 / 1.5 / 6** | **4 / 8 / 12** | **2 / 2 / 6** | **30 / 51 / 80** | **18 / 37 / 58** |
| Same statement, stand-mounted | 0 / 1 / 4 | 2 / 6 / 10 | 0 / 3 / 6 | 18 / 29 / 54 | 6 / 19 / 24 |
| **Sibling statement, stand-mounted** | **1 / 3 / 5** | **4 / 6 / 10** | **2 / 3 / 6** | **20 / 42 / 58** | **10 / 19 / 38** |
| Page 1 vs page 2, same statement | 7 / 9 / 13 | 12 / 17 / 24 | 6 / 10 / 14 | 58 / 67 / 82 | 42 / 60 / 86 |
| Letter page 1 vs page 2, same letterhead | 5 / 12.5 / 22 | 4 / 10 / 12 | 0 / 6 / 12 | 40 / 63 / 76 | 12 / 22 / 42 |
| Two different letters, same letterhead | 6 / 8.5 / 18 | 6 / 11 / 16 | 2 / 4 / 8 | 42 / 66 / 98 | 14 / 25 / 44 |
| Receipt (cropped to quad) same, recaptured | 7 / 12 / 26 | 2 / 8 / 16 | 6 / 7 / 14 | 28 / 51 / 102 | 14 / 26 / 52 |
| Receipt (cropped) vs sibling receipt | 2 / 11 / 21 | 6 / 10 / 18 | 4 / 9 / 16 | 50 / 69 / 102 | 16 / 33 / 58 |
| Blank back vs blank back | 0 / 24.5 / 47 | 22 / 27 / 34 | 0 / 0 / 26 | 108 / 123 / 140 | 0 / 0 / 120 |
| Blank back vs show-through back | 0 / 20 / 51 | 26 / 29 / 36 | 0 / 0 / 26 | 110 / 126 / 134 | 0 / 7 / 108 |
| Statement vs unrelated letter | 24 / 30 / 41 | 8 / 16 / 20 | 12 / 14 / 16 | 64 / 77 / 84 | 70 / 85 / 102 |

Readings (synthetic, measured):

- **Same-template siblings are inside the same-page band for every hash.** Stand-mounted: same page dHash 0-4, sibling 1-5. Handheld: same 1-4, sibling 0-6. Any dHash/pHash/wHash threshold that catches a re-scan also catches last month's statement. This is the false-skip that the durability guarantee cannot tolerate, and it is not a tail event: the *median* sibling distance (1.5) is below the median same-page distance (3).
- **pHash64 is nearly useless on documents**: unrelated statement vs letter scores 8-20, overlapping same-page 0-12. Low-entropy white pages with text blocks compress to almost the same low-frequency DCT.
- **256-bit DCT (PDQ-like) and block hashes have more dynamic range but worse recall**: same page handheld lands at 8-64 (median 36), above PDQ's recommended 31; the sibling band (30-80) overlaps it. PDQ at 31 would miss about half of genuine re-scans and still admit the nearest siblings. Its value here is the quality score, not the distance.
- **Page 1 vs page 2 of the same statement** separates on dHash (7-13 vs 0-5) only if the threshold is <= 6; the letterhead letter (5-22) does not separate reliably. Different letters on the same letterhead (6-18) overlap page-2 cases.
- **Receipts** (cropped to their own quad, as segmentation would do) are unstable at dHash (same 7-26) and not separable from a sibling receipt (2-21).
- **Blank backs are noise**: every hash of a blank page is dominated by illumination gradient and sensor noise; two blank backs score anywhere from 0 to 47 at dHash and 108-140 at the 256-bit DCT. A blank page must be detected by ink coverage (pdftl/Tungsten-style thresholds, see `dedup.md`) and by PDQ quality, then excluded from hash matching entirely.
- The recapture model is optimistic in one way (rectification residual <= 1.5 deg, which Zauner shows is the hash-friendly regime) and pessimistic in another (gradients and blur are applied uniformly). Phone data will be wider, not narrower.

### 2c. Measured here: the text tiers under OCR noise and on short text

Setup (`simhash.py`, `simhash2.py`): 128-bit and 64-bit SimHash over character 9-grams with the Institutional Books filter (>= 4 distinct characters), 40 trials; OCR noise is random substitution/deletion/insertion at a given character error rate (CER) applied independently to the two "captures". Texts: statement 1,568 chars; utility bill 504 chars where siblings differ only in billing period and amount; receipt 141 chars. Jaccard is over the same 9-gram sets (what MinHash estimates).

| Pair | 128-bit SimHash min/med/max | 9-gram Jaccard min/med/max |
|---|---|---|
| Same statement, CER 0% | 0 / 0 / 0 | 1.00 |
| Same statement, CER 0.3% | 4 / 9.5 / 19 | 0.81 / 0.90 / 0.97 |
| Same statement, CER 1% | 6 / 18 / 26 | 0.64 / 0.72 / 0.80 |
| Same statement, CER 2% | 16 / 26 / 35 | n/a |
| Same statement, CER 5% / 10% | 33 / 41.5 / 52 ; 42 / 54 / 67 | n/a |
| **Sibling statements (next month), CER 0.3%** | 32 / 41 / 50 | 0.17 / 0.19 / 0.21 |
| Same bill, CER 0.3% / 1% | 4 / 14 / 24 ; 13 / 23.5 / 37 | 0.79-0.98 ; 0.56-0.94 |
| **Sibling bills (only date and amount differ), CER 0.3%** | **21 / 27 / 37** | **0.58 / 0.75 / 0.82** |
| Same receipt (141 ch), CER 0.3% / 1% / 2% | 0 / 14 / 32 ; 11 / 27 / 36 ; 8 / 34 / 48 | 0.66-1.00 ; 0.57-0.90 ; n/a |
| Sibling receipts, CER 0.3% | 47 / 60.5 / 71 | 0.00 / 0.03 / 0.06 |
| Statement vs bill (unrelated), CER 2% | 53 / 63.5 / 75 | n/a |

Readings (synthetic, measured):

- **The 6-bit threshold does not survive phone OCR noise.** Institutional Books set "at most 6 bits" on 128-bit SimHash for 1M books and call it "conservative"; it worked because their two scans go through the same scanner OCR ([arXiv 2608.19026 §4.3, C.3](https://arxiv.org/pdf/2608.19026)). At 0.3% CER the same page already lands at a median of 9.5 bits, at 1% at 18. Apple Vision's CER on handheld document photos is unmeasured (per `ocr.md`), so the real distribution is unknown; a 1-2% difference between two handheld captures is plausible for small print, glare and shadow.
- **Jaccard (MinHash) has far more headroom than SimHash** for full pages: same statement 0.81-0.97 vs sibling 0.17-0.21 at 0.3% CER, and still 0.64-0.80 vs 0.17-0.21 at 1%. Prefer a graded Jaccard score for the merge decision; keep SimHash only as an index key (band LSH).
- **Same-template, few-field-difference items are the hard negative that text tiers cannot solve.** A bill where only date and amount change scores Jaccard 0.58-0.82 against its sibling, overlapping a re-OCR'd copy of itself (0.56-0.94 at 1% CER). This is the structural limit of any n-gram method: 2 changed tokens out of 500 characters move about 18 of ~450 9-grams.
- **Anchor tokens cut both ways.** With a regex token set (dates, amounts, account numbers), sibling bills differ in 2 tokens; the *same* bill re-OCR'd at 2% CER differs in 6 (Jaccard 0.67) and at 5% in 9. An exact-set test therefore says "different" more often for a genuine re-scan than for a sibling. The test must be field-level (parsed date, parsed amount, account id) with digit-edit tolerance for the *flag* path, and exact agreement on at least two parsed key fields for the *merge* path.
- **Short text**: receipts at 141 characters give 0-32 bits for the same item at 0.3% CER (Jaccard down to 0.66) and are only separable from sibling receipts because receipts share almost no 9-grams (Jaccard 0.03). The RETSim authors state MinHash and SimHash "perform poorly on short text lengths" and that their neural model wins "on short texts with fewer than 128 characters" ([arXiv 2311.17264](https://arxiv.org/html/2311.17264), measured on W4NT3D/NEWS-COPY). Below ~400 characters, treat text tiers as advisory and rely on fields (merchant, date, total).

### 2d. Random-collision mathematics vs structural collision (computed)

For uniformly random bits the per-capture probability that a new page lands within the threshold of *any* of N stored pages is: 64-bit <= 10: 2.0e-3 at N = 200k (5e-4 at 50k); 64-bit <= 6: 9e-7; 128-bit <= 6: 3e-24; 256-bit <= 31: 2e-32 (binomial tail, my computation). Over a whole 200k archive, 64-bit <= 10 expects about 200 random collisions. These numbers only bound the *random* component; the synthetic tables show the real risk is structural (templates), which the mathematics does not cover.

### 2e. Which image is each feature computed on

- **Preview frame** (1080p or 1440p `AVCaptureVideoDataOutput`): 10-pt body text on an A4 page has a cap height of ~2.5 mm = 0.84% of page height = **9 px at 1080p, 12 px at 1440p** (computed). Vision's `minimumTextHeight` default is "1/32" of image height = 34 px at 1080p ("Increasing the size reduces memory consumption and expedites recognition with the tradeoff of ignoring text smaller than the minimum height", [Apple](https://developer.apple.com/documentation/vision/vnrecognizetextrequest/minimumtextheight)). So the 30 fps "fast" benchmark in `ocr.md` reads only headings of a full page; body text needs `minimumTextHeight` <= 0.006 and more pixels, with unmeasured cost. Conclusion: **the text tier cannot run on the preview frame of a full page**; it runs on the rectified still. Only the geometric hashes (dHash on the rectified quad, 9x8 downsample) and the embedding (256-360 px input) are preview-safe.
- **Full-res still** (12 MP: ~25 px body text; 48 MP: ~51 px, computed): source for OCR, PDQ/block hash (64x64 downsample of the rectified page, so the still and the preview give near-identical hashes; compute on the still so the stored hash matches the stored page), the archival SHA-256, and the sharpness score used to pick the canonical copy.
- **Embedding**: `VNGenerateImageFeaturePrintRequest` revision 2 takes 360x360 input (768-d) and MobileCLIP-S0 256x256 (see `dedup.md`); both can be fed the rectified preview quad before the shutter and recomputed on the still afterwards. The pre-shutter run is what makes a sub-100 ms "looks like page N" cue possible; the post-shutter run is what gets indexed.
- **Lens smudge / sharpness gate**: `DetectLensSmudgeRequest` (iOS 26, A14+) returns a 0-1 probability; Apple warns that motion blur and long exposure may be classified as smudge and recommends "a fixed capture where the device is stable" ([Apple](https://developer.apple.com/documentation/vision/detectlenssmudgerequest)). Run it on the still, not per frame.

### 2f. Index size, lookup latency, persistence, sync

**Lookup.** Brute-force Hamming scan measured here (C, `-O3 -march=native`, one core, Xeon 2.3 GHz, 200 random queries): 50k codes: 0.026 ms (64-bit), 0.037 (128), 0.065 (256); **200k codes: 0.113 / 0.190 / 0.387 ms**; 1M codes: 0.74 / 1.27 / 1.91 ms. An iPhone core with NEON `cnt` should be the same order (estimate). Norouzi et al. measured linear scan of 1 B 64-bit codes at 12.23 s and 256-bit at 38.89 s on a 2013 Opteron, i.e. ~2.4 ms / 7.8 ms per 200k, with multi-index hashing 115-670x faster at 1 B ([arXiv 1307.2982](https://arxiv.org/abs/1307.2982), measured). Meta's own advice: "If you have a small collection, don't underestimate the efficiency of linear search" ([hashing.pdf](https://github.com/facebook/ThreatExchange/blob/main/hashing/hashing.pdf)). **At 200k pages no index structure is needed for hashes**; the 100 ms budget is dominated by OCR, not lookup.

**Embeddings.** 200k x 768-d float32 (FeaturePrint rev2) = 627 MB, which is unacceptable; int8 = 166 MB; binarized 96 B = 32 MB; MobileCLIP-S0-class 512-d int8 = 115 MB (computed). A flat int8 dot-product scan over 200k x 512 is ~100M MACs, a few ms with Accelerate (estimate). If an ANN index is wanted, USearch (Apache-2.0) ships Swift bindings with add/search/remove, save/load and filter predicates but no batch ops or user metrics in Swift, supports f16/i8 and binary (Hamming) quantization, and publishes no iOS latency ([GitHub](https://github.com/unum-cloud/usearch)); ObjectBox Swift offers HNSW with cosine/euclidean/dot-product, no quantization yet and no published latency ([docs](https://docs.objectbox.io/on-device-vector-search)).

**Persistence.** On device: one SQLite table (`page_id, dhash64, pdq256, pdq_quality, simhash128, anchor_fields_json, embedding_int8, embedding_rev`) plus the whole table memory-mapped into contiguous arrays at launch (12.8 MB of hashes for 200k pages, computed). The same rows should be written as a sidecar next to the archive in the user's own storage (Drive/NAS/iCloud Drive) so a reinstall or second device rebuilds the index from the archive without re-hashing 200k PDFs; the SHA-256 of the archival PDF is the join key (see `dedup.md` 2g).

**Sync.** CloudKit guidelines: "400 items (records or shares) per operation, 2 MB per request (not counting asset sizes)"; on `limitExceeded` "split the operation in half" ([Apple](https://developer.apple.com/documentation/cloudkit/ckerror/code/limitexceeded)); fields over "a few kilobytes" belong in `CKAsset` ([Apple](https://developer.apple.com/documentation/cloudkit/ckasset)). A ~600-byte per-page record (hashes + fields + int8 embedding) syncs 200k pages in ~500 operations; embeddings should be a `CKAsset` chunk per 1,000 pages rather than per-record fields. Store the FeaturePrint revision with every vector: observations from different revisions cannot be compared (error 12, see `dedup.md`).

### 2g. MobileCLIP licensing (decision-relevant)

- The PyTorch weights at `apple/MobileCLIP-S0` show `License: apple-amlr` ([HF](https://huggingface.co/apple/MobileCLIP-S0)); the repo's LICENSE file is the "Apple Machine Learning Research Model License Agreement", which grants use "exclusively for Research Purposes", defines Research Purposes as "non-commercial scientific research and academic development activities" that "does not include any commercial exploitation, product development or use in any commercial product or service", and extends the restriction to fine-tuned derivatives ([LICENSE](https://huggingface.co/apple/MobileCLIP-S0/resolve/main/LICENSE)). The HF commit log shows "Update LICENSE" on 2025-02-24 and "AMLR license (#2)" on 2025-02-28 ([commits](https://huggingface.co/apple/MobileCLIP-S0/commits/main)).
- Before that, the GitHub repo's `LICENSE_weights_data` (commit 341ef05, 2024-07-22) was titled "ML-MobileCLIP Model Weights and Data" and granted "a personal, non-exclusive license" to "use, reproduce, modify and redistribute" with no research-only limitation ([raw at 341ef05](https://raw.githubusercontent.com/apple/ml-mobileclip/341ef05/LICENSE_weights_data)). That file is gone from `main`; today the repo has `LICENSE_MODELS` = AMLR and the README says "ML models: Apple ML Research Model TOU" ([README](https://github.com/apple/ml-mobileclip), [LICENSE_MODELS](https://raw.githubusercontent.com/apple/ml-mobileclip/main/LICENSE_MODELS)).
- The Core ML repo `apple/coreml-mobileclip` (uploaded 2024-10-21, no later license commits) still declares `license_name: apple-ascl` with `license_link` to the removed `LICENSE_weights_data` file, and contains no LICENSE file ([README raw](https://huggingface.co/apple/coreml-mobileclip/raw/main/README.md), [tree](https://huggingface.co/apple/coreml-mobileclip/tree/main)). HF's identifier table defines `apple-ascl` as "Apple Sample Code license" and `apple-amlr` as "Apple Model License for Research" ([HF docs](https://huggingface.co/docs/hub/repositories-licenses)).
- MobileCLIP2 (Aug-Oct 2025) is AMLR from the start ([HF](https://huggingface.co/apple/MobileCLIP2-S0)).
- Reading: Apple's current position on all MobileCLIP weights is research-only. Whether copies obtained under the 2024 grant remain usable commercially is a legal question I cannot settle; the conservative engineering answer is to not ship them. The 1.5 ms figure in `dedup.md` is therefore a benchmark reference, not a product option, unless Apple legal confirms otherwise.
- Clean alternatives: `VNGenerateImageFeaturePrintRequest` (system model, no weights to ship, latency unmeasured); DINOv2 ViT-S/14 (21 M params, "code and model weights are released under the Apache License 2.0", [GitHub](https://github.com/facebookresearch/dinov2)); SigLIP 2 base (Apache-2.0, [HF](https://huggingface.co/google/siglip2-base-patch16-224)); TinyCLIP ViT-8M (MIT, [LICENSE](https://raw.githubusercontent.com/wkcn/TinyCLIP/main/LICENSE)). None has a published iPhone latency except the vendor claim for SigLIP 2 base int8 (14 ms, iPhone 16 Plus) in `dedup.md`. A custom distilled model trained on our own page pairs avoids the question entirely.

## 3. Options compared

| Tier | Computed on | Cost (est. unless noted) | Same-page recall (synthetic) | Sibling separation (synthetic) | Page1/page2 | Blank backs | Short text | Safe role |
|---|---|---|---|---|---|---|---|---|
| dHash64 | rectified preview quad, every frame | < 1 ms | 0-5 bits | **none** (0-6) | partial (7-13) | noise | unstable (7-26) | frame tracking, "looks like page N" hint |
| pHash64 | rectified still | ~1 ms | 0-12 | none; unrelated pages 8-20 | weak | noise | weak | do not use |
| PDQ / pHash256 | rectified still, 64x64 | 1-2 ms | poor at 31 (median 36) | none | yes (58-82) | quality score useful | poor | quality gate; loose candidate filter |
| block256 | rectified still | < 1 ms | 12-60 | none | partial | noise | poor | candidate filter only |
| FeaturePrint rev2 | 360x360 rectified | unknown | unmeasured | expected none (natural-image model) | ? | ? | ? | candidate filter; needs on-device calibration |
| MobileCLIP-S0 | 256x256 | 1.5 ms (measured, iPhone 12 Pro Max, Apple) | unmeasured on docs | expected none | ? | ? | ? | **blocked by AMLR license** |
| SimHash128 (9-gram) | OCR of rectified still | OCR-bound | 4-19 bits at 0.3% CER, 6-26 at 1% | statements yes (32-50); bills with 2 fields changed **no** (21-37) | yes | n/a (< 50 chars excluded) | weak | LSH index key; flag path |
| 9-gram Jaccard (MinHash) | same | OCR-bound | 0.81-0.97 at 0.3%; 0.64-0.80 at 1% | statements yes (0.17-0.21); bills **no** (0.58-0.82) | yes | n/a | 0.66-1.00 same / 0.03 sibling | graded merge score |
| Parsed key fields (date, amount, account) | OCR of still | < 1 ms after OCR | exact only if digits read correctly (6/15 tokens flip at 2% CER) | **yes**, the only tier that does | yes ("Page N of M") | n/a | yes (merchant/date/total) | required for merge |
| Claude field extraction | still, cloud | 1-3 s | authoritative | authoritative | yes | n/a | yes | back-fill, re-check merges asynchronously |

## 4. Recommendation for this project

1. **Separate the cue from the decision.** The sub-100 ms cue is a hint, not a verdict: "Looks like page 3 (scanned 2 min ago)" with a thumbnail, driven by dHash64 of the rectified preview quad against the last ~50 captures of the session plus the embedding of the preview quad against the archive's candidate set. It never prevents a capture and never says "skipped".
2. **Always write the capture.** The still, its SHA-256, OCR transcript and hashes are persisted before any dedup logic runs (as `dedup.md` already says). Durability is then independent of every threshold in this report.
3. **Merge only on text plus fields, and only asynchronously.** A capture becomes a *variant* of an existing page (sharper copy kept canonical) when: 9-gram Jaccard over the accurate-OCR transcript >= a calibrated value (synthetic data suggests a floor around 0.6 for full pages; must be measured) **and** at least two parsed key fields agree exactly (date, amount, account/reference, "Page N of M") **and** no parsed key field disagrees. Anything else with Jaccard above ~0.3 is linked as "similar to", never merged. Pages under 400 characters, pages with fewer than 50 characters, and pages flagged blank by ink coverage never merge automatically.
4. **Gate blanks and junk before hashing.** Ink coverage plus PDQ quality score; store the blank-back flag on the previous page.
5. **Do not ship MobileCLIP weights.** Use `VNGenerateImageFeaturePrintRequest` rev 2 as the embedding tier if its on-device latency is acceptable (measure it in week one; it is unknown), otherwise DINOv2-S or SigLIP 2 base under Apache-2.0, or distil your own. Pin and store the revision/model id with every vector.
6. **Index design.** Flat arrays in memory, SQLite on disk, sidecar copy in the user's archive, CloudKit for cross-device with embeddings chunked into `CKAsset`s. Brute-force Hamming and int8 dot products are sufficient to 200k pages; add USearch only if the archive grows past ~1M pages.
7. **Calibration set before any threshold is committed.** 200 physical pages re-photographed 5 times each (handheld and stand), 50 same-template sibling pairs across at least 10 senders, 20 few-field-difference pairs (utility bills, insurance EOBs), 30 receipts and postcards, 20 blank backs and show-through backs, 20 two-page letters. Record per-tier distances and Apple Vision CER between captures; publish the ROC per tier and the fused false-skip rate, which must be 0 on this set before a merge is ever automatic. Repeat on an A15, A17 and A19 device because FeaturePrint distances are hardware-only (the Simulator returns a constant).

## 5. Risks and unknowns

- All error rates in §2b-2c are synthetic. Real handheld captures will have wider same-page distributions (curl, shadow, partial glare), which makes the overlap with siblings worse, not better.
- Apple Vision's CER between two handheld captures of the same page is unmeasured; it decides whether SimHash/Jaccard thresholds are workable at all.
- `VNGenerateImageFeaturePrintRequest` latency and document-page distance distribution remain unknown (no public measurement found; search unavailable this run).
- The MobileCLIP license history is reconstructed from public commit pages; the `apple-ascl` tag on the Core ML repo may be an oversight or may be intentional; only Apple can say. Treat as research-only.
- Hamming-scan timings were measured on an x86 server core, not an iPhone.
- Sources older than 2025: Hacker Factor (2013), Zauner (2010), Norouzi (2013), Meta PDQ design doc (undated, ~2019). Their numbers are about photos and should be read as upper bounds on hash quality for documents.
- Anchor-field parsing depends on OCR reading digits; at 2-5% CER the same page disagrees with itself on 6-9 tokens. Field-level parsing with checksum-style validation (dates that parse, amounts with two decimals) narrows but does not remove this.

## 6. Open questions for the founder

1. Is "Looks like page N" with a thumbnail an acceptable form of the instant cue, given that a definitive "already scanned" cannot be made safe at capture time?
2. For few-field siblings (monthly bills), is a wrong *merge* of two different months acceptable if both captures are retained as variants and searchable, or must merges be reversible from the UI without interaction?
3. What fraction of your mail is under ~400 characters (receipts, postcards, envelopes)? That fraction will get weaker duplicate hints.
4. Are you willing to budget a one-week on-device benchmark (FeaturePrint latency, Vision CER between captures, hash ROC) before the capture state machine is designed?
5. Should the index sidecar live inside the user's archive folder (visible files) or only in the app container plus CloudKit?
6. If Apple legal confirms the 2024 MobileCLIP grant still applies to the Core ML package, do you want to revisit it, or stay with Apple's built-in feature print and a custom distilled model?

## 7. Sources

- Apple Machine Learning Research Model License (MobileCLIP-S0 LICENSE): https://huggingface.co/apple/MobileCLIP-S0/resolve/main/LICENSE
- MobileCLIP-S0 commit history (license commits Feb 2025): https://huggingface.co/apple/MobileCLIP-S0/commits/main
- ml-mobileclip README (licenses section) and commit log: https://github.com/apple/ml-mobileclip , https://github.com/apple/ml-mobileclip/commits/main
- ml-mobileclip LICENSE (MIT, code): https://raw.githubusercontent.com/apple/ml-mobileclip/main/LICENSE
- ml-mobileclip LICENSE_MODELS (AMLR): https://raw.githubusercontent.com/apple/ml-mobileclip/main/LICENSE_MODELS
- ml-mobileclip LICENSE_weights_data at 341ef05 (2024 grant): https://raw.githubusercontent.com/apple/ml-mobileclip/341ef05/LICENSE_weights_data
- coreml-mobileclip model card metadata and file tree: https://huggingface.co/apple/coreml-mobileclip/raw/main/README.md , https://huggingface.co/apple/coreml-mobileclip/tree/main
- MobileCLIP2-S0 (apple-amlr): https://huggingface.co/apple/MobileCLIP2-S0
- HF license identifiers: https://huggingface.co/docs/hub/repositories-licenses
- ml-mobileclip iOS demo app README (latencies, iOS 17.2): https://github.com/apple/ml-mobileclip/blob/main/ios_app/README.md
- DINOv2 (Apache-2.0): https://github.com/facebookresearch/dinov2
- SigLIP 2 base (Apache-2.0): https://huggingface.co/google/siglip2-base-patch16-224
- TinyCLIP LICENSE (MIT): https://raw.githubusercontent.com/wkcn/TinyCLIP/main/LICENSE
- Meta PDQ/TMK design document: https://github.com/facebook/ThreatExchange/blob/main/hashing/hashing.pdf
- Robustness of PhotoDNA/PDQ/NeuralHash (2024): https://arxiv.org/pdf/2406.00918
- Hacker Factor, dHash evaluation (2013): http://www.hackerfactor.com/blog/index.php?/archives/529-Kind-of-Like-That.html
- blockhash (Yang/Gu/Niu block mean): https://github.com/commonsmachinery/blockhash
- Zauner, perceptual hash benchmarking (2010): https://phash.org/docs/pubs/thesis_zauner.pdf
- Institutional Books pipeline, §4.3 and C.3: https://arxiv.org/pdf/2608.19026
- RETSim / NEWS-COPY, short-text behaviour: https://arxiv.org/html/2311.17264
- Norouzi et al., multi-index hashing: https://arxiv.org/abs/1307.2982
- USearch: https://github.com/unum-cloud/usearch
- ObjectBox on-device vector search: https://docs.objectbox.io/on-device-vector-search
- Apple, minimumTextHeight: https://developer.apple.com/documentation/vision/vnrecognizetextrequest/minimumtextheight
- Apple, RecognizeTextRequest.recognitionLevel: https://developer.apple.com/documentation/vision/recognizetextrequest/recognitionlevel-swift.property
- Apple, GenerateImageFeaturePrintRequest (iOS 18+): https://developer.apple.com/documentation/vision/generateimagefeatureprintrequest
- Apple, DetectLensSmudgeRequest (iOS 26): https://developer.apple.com/documentation/vision/detectlenssmudgerequest
- Apple, CKError.Code.limitExceeded (400 items, 2 MB): https://developer.apple.com/documentation/cloudkit/ckerror/code/limitexceeded
- Apple, CKAsset: https://developer.apple.com/documentation/cloudkit/ckasset
- Local measurement scripts and outputs: ../bench/ (synth.py, synth2.py, simhash.py, simhash2.py, scan.c)
