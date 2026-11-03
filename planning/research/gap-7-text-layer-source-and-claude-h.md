# Gap 7: Which text becomes the PDF text layer, the FTS index and the embedding input, and when the per-page handoff is emitted

Dimension: text-source selection (raw Vision word boxes vs `RecognizeDocumentsRequest` paragraphs vs a Claude-corrected transcript), the cost/time of a Claude transcript, re-alignment of corrected text to Vision boxes, the Vision-vs-Claude conflict policy for anchor tokens, and whether the per-page handoff (raw still, corrected HEIC, analysis JPEG, transcript + boxes, provisional PDF) is emitted before or after the Claude return.

Research date: 2026-11-03. Method note: the shared web-search budget for this run was exhausted before this dimension started, so every finding comes from direct fetches of primary sources (Apple doc JSON endpoints, WWDC transcripts, Anthropic docs, arXiv/ACL papers, tool docs) plus one simulation I ran myself (section 2f). Labels: **measured** (a published measurement or my own run), **vendor** (vendor statement, no number), **estimate** (my derivation). "Unknown" means no primary source was found. Reports this builds on: `ocr.md`, `claude.md`, `output.md`, `search.md`, `gap-2`, `gap-3`, `gap-4`.

---

## 1. Executive summary

1. **Vision is the text layer, the FTS body and the dedup anchor source; Claude is the field source and an optional corrector.** No public evidence says a Claude transcript beats Apple Vision on clean printed mail, and the post-OCR literature shows LLM correction helps noisy text (54-60 % CER reduction on historical newspapers) but tends to *degrade* near-clean text and to hallucinate plausible words.
2. Run Vision twice per still: `.fast` with `usesLanguageCorrection = false` (raw digits for dedup anchors; ~100 ms measured on A18) and `.accurate` with correction on (text layer and FTS; ~740 ms measured). Correction is what turns "C001" into "cool" (Apple, WWDC19), so anchors must never come from the corrected pass.
3. A full Claude Haiku 5.5 transcript of a dense page costs ~$0.0005 (1,000 output tokens at $0.50/MTok, $0.00025 on Batch) and **4.3-6.0 s of generation** at the measured 167-235 tok/s, plus TTFT. Money is negligible; time is not. It must never sit on the "captured" path.
4. Re-aligning a Claude transcript to Vision boxes is a solved, cheap problem: character-level edit-distance alignment (Myers/Needleman-Wunsch, banded) mapped 99.8-100 % of corrected words to the correct Vision box at 0.5-5 % simulated CER, in ~250 ms of pure Python for a 600-word page; a Swift implementation is an estimated 2-10 ms. Claude *can* return pixel boxes (Anthropic coordinates guide), but they are "approximate", lose precision on small text, and would cost ~6-9k output tokens per page; not viable for a word layer.
5. Default shape: **diff-style correction, not transcription.** Send Claude the numbered Vision lines plus the image (already planned); add a small `corrections: [{line, text}]` array to the extraction schema (~50-150 output tokens) and apply it by line index. Full-transcript mode is a Batch job reserved for low-confidence pages, handwriting and non-Latin scripts.
6. Conflict policy for amounts/account numbers/dates: three witnesses (Vision raw, Vision corrected, Claude-from-image); a value is *validated* when two agree or it passes a structural check (date parses, amount has two decimals, Luhn/mod-97/ABA where applicable). Search indexes every variant; dedup merges only on Vision-raw vs Vision-raw anchor agreement; the record shows the validated value with the rest as alternates.
7. Low-confidence Vision words: **keep** them in the invisible layer and the trigram table (recall, phrase integrity), **exclude** them from anchor fields and from the porter FTS column weighting. OHRBench measured ~50 % retrieval/generation loss only at *severe* semantic noise; mild noise is tolerable, dropped words are not.
8. Handoff contract: everything (raw still cache, corrected archival image, analysis JPEG, Vision transcript + boxes JSON for both passes, provisional PDF/A-2u with Vision layer, sidecar v1) is emitted at S1, **before** Claude. The Claude return updates the sidecar, the local index, and destination metadata (Drive `indexableText`, 128 KB) without touching the PDF. The PDF is rewritten and re-uploaded only when a correction is material (threshold proposed in 4.5), which should be rare.
9. Never hold the upload for Claude: S2 is the durability promise and the Claude round trip is 3-7 s plus network variance.
10. Biggest unknowns: Apple Vision CER on handheld mail (decides whether any correction is worth it), Haiku 5.5 thinking-off TTFT, whether `topCandidates` ever contains the uncorrected string, and how often a Claude diff is material enough to trigger a PDF rewrite.

---

## 2. Findings

### 2a. What Apple Vision actually gives you (and what language correction does)

**`usesLanguageCorrection` (iOS 18+, `RecognizeTextRequest`).** Apple's whole discussion is one sentence: "When this value is `true`, Vision applies language correction during the recognition process. Disabling this property returns the raw recognition results, which provides performance benefits but less accurate results." No default is stated on the Swift or ObjC page (vendor). Source: https://developer.apple.com/documentation/vision/recognizetextrequest/useslanguagecorrection and https://developer.apple.com/documentation/vision/vnrecognizetextrequest/useslanguagecorrection

**What correction does to codes.** WWDC19 session 234 (Apple engineers, transcript): "think of the serial number like C001 that can very easily be misconstructed as cool"; "I disabled the language correction because I know I'm looking for codes"; "this language correction does not come for free". The phone-number demo replaces correction with domain rules ("if it reads something like an S, which would be a 5, or if I get an L, this should be a 1"). Source: https://nonstrict.eu/wwdcindex/wwdc2019/234/ (vendor statements, no numbers).

**`customWords`** "take precedence over the standard lexicon. The request ignores this value if `usesLanguageCorrection` is `false`." Vision "doesn't support language correction, or its related `customWords` array, for Chinese." Sources: https://developer.apple.com/documentation/vision/recognizetextrequest/customwords , https://developer.apple.com/documentation/vision/recognizing-text-in-images

**Cost of correction (measured, third party).** text_sight on an iPhone 16 (A18), one-shot `RecognizeTextRequest`, 63-line page: `.fast` 101 ms, `.fast` + correction 199 ms, `.accurate` 404 ms, `.accurate` + correction 736 ms (p50); the authors say correction "roughly doubles the time on iOS" (from `gap-3`, source https://pub.dev/documentation/text_sight/0.2.2/). So a raw pass is cheap enough to run *in addition to* a corrected pass.

**Candidates and confidence.** `RecognizedTextObservation.topCandidates(_ maxCandidateCount:) -> [RecognizedText]`; `RecognizedText.string`, `RecognizedText.confidence: Float` ("a normalized confidence score"), and `boundingBox(for: Range<String.Index>) -> RectangleObservation?` ("Calculates the bounding box around the characters in the range of a string"). Apple gives no scale guidance, no threshold, and does not say whether the candidate list ever contains the uncorrected reading when correction is on (unknown). WWDC19: "if you want to increase the recall, you can index more candidates for each of the results. Of course, at the cost of precision." Sources: https://developer.apple.com/documentation/vision/recognizedtext , https://developer.apple.com/documentation/vision/recognizedtextobservation

**Bounding-box semantics differ by path.** "The fast path calculates the recognized text's bounding rectangle based on its individual characters. The accurate path tokenizes on whitespace, which means when working with Chinese text, the resulting bounding boxes will likely contain lines or line fragments instead of complete text." Source: https://developer.apple.com/documentation/vision/recognizing-text-in-images

**`RecognizeDocumentsRequest` (iOS 26+).** `DocumentObservation.document: Container` with `text: Container.Text` (all text), `paragraphs: [Container.Text]`, `title: Container.Text?`, `tables`, `lists`, `barcodes`. `Container.Text` exposes `transcript: String` ("The complete text as a string"), `lines: [RecognizedTextObservation]`, `words: [RecognizedTextObservation]?` (optional; WWDC25: "not supported for certain languages, such as Chinese, Japanese, Korean, and Thai"), `detectedData: [DataDetectorMatch]` (each wraps a DataDetection `DataDetector.Match` and conforms to `BoundingRegionProviding`), `boundingRegion`, `textAlignment`, and `boundingRegion(for: Range<String.Index>) -> NormalizedRegion?`. WWDC25: "Lines can be grouped into paragraphs, giving a more natural view of how the text would be read"; "If a line is not part of a paragraph grouping, it's considered to be its own paragraph." Whether `RecognizeDocumentsRequest` exposes a language-correction switch is not documented on the pages fetched (unknown). Sources: https://developer.apple.com/documentation/vision/documentobservation , https://developer.apple.com/documentation/vision/documentobservation/container , https://developer.apple.com/documentation/vision/documentobservation/container/text-swift.struct , https://nonstrict.eu/wwdcindex/wwdc2025/272/

Implication: paragraphs give *reading order* for a transcript string (what FTS, embeddings and the Claude prompt want); words/lines plus `boundingRegion(for:)` give *geometry* for the invisible layer. They are two views of the same recognition, not competing text sources. The real choice is correction on vs off, and Vision vs Claude.

### 2b. What Claude costs and how long a transcript takes

**Prices (vendor, verified 2026-11-03).** Haiku 5.5: $0.10/MTok input, $0.50/MTok output for prompts <= 100k tokens; 5-min cache write $0.125, 1-h $0.20, cache read $0.01; Batch 50 % off ($0.05/$0.25). Sonnet 5.5 $2/$10; Opus 5.5 $4/$20. Claude 4.7+ models (incl. Haiku 5.5) use a tokenizer that "produces approximately 30 % more tokens for the same text". Haiku 5.5: 1M context, 128k max output, "Fastest" comparative latency, adaptive thinking on by default (`effort` default `medium`). Sources: https://platform.claude.com/docs/en/about-claude/pricing , https://platform.claude.com/docs/en/models/haiku-5-5/overview

**Output speed (measured, Artificial Analysis, first-party API).** Haiku 5.5 `max` 235.4 tok/s; `low` 167 tok/s; `medium` 176 tok/s (from `claude.md`; https://artificialanalysis.ai/models/claude-haiku-5-5). The page gives no figure for a thinking-disabled variant and its 333.7 s TTFT for `max` is unexplained (treat as an artefact). Sonnet 5.5 `low` 105.7 tok/s, TTFT 1.20 s.

**Derived per-page transcript cost and time (estimate from the numbers above):**

| Dense page transcript | Output tokens | Output cost (standard / batch) | Generation time at 167-235 tok/s | Plus TTFT |
|---|---|---|---|---|
| ~600-word letter | ~800 | $0.00040 / $0.00020 | 3.4-4.8 s | >= ~1.2 s (Sonnet `low` read-across; Haiku thinking-off unmeasured) |
| ~900-word dense page | ~1,200 | $0.00060 / $0.00030 | 5.1-7.2 s | same |
| Diff-style corrections only (proposed, 4.3) | ~50-150 | $0.00003-0.00008 | 0.2-0.9 s | same |
| Word boxes from Claude (`[x1,y1,x2,y2]` + word, ~600 words) | ~6,000-9,000 | $0.003-0.0045 | 26-54 s | same |

Input side is already paid by the extraction call in `claude.md` (image ~1,776 tokens + ~800-1,200 tokens of Vision text + cached system prompt). A transcript therefore roughly **doubles** the per-page Claude spend (from ~$0.0007 to ~$0.0012) and **doubles to triples** the wall-clock of the cloud pass. For 1,000 pages/month that is $0.50/month extra; cost is not the constraint, latency and re-emission are.

**Can Claude return coordinates?** Yes, and Anthropic now documents it: "Claude can locate and label regions of an image (for example, returning bounding boxes for tables, form fields, chart elements, or UI components)... You'll need this for OCR pipelines, form extraction..."; "Claude works best with absolute pixel coordinates... Claude does not work well when you ask for normalized coordinates"; but "Claude's spatial reasoning has limits... Coordinate accuracy is best when you... spot-check results visually... Small elements lose precision when an image is downscaled: for fine targets, crop the region of interest." The resize rule is published (largest aspect-preserving size within the 2,576 px / 4,784-token high-res tier; padding to a multiple of 28 on bottom/right; a 130-DPI A4 page at 1075x1520 is *not* resized on high-res models), and `"transformations": {"oversized_image": "error"}` rejects any image that would be resized. The vision page's limitations: "Claude might hallucinate or make mistakes when interpreting low-quality, rotated, or very small images under 200 pixels"; "Claude's coordinate and localization outputs are approximate." Sources: https://platform.claude.com/docs/en/build-with-claude/vision-coordinates , https://platform.claude.com/docs/en/build-with-claude/vision

Implication: Claude boxes are fine for *regions* (a table, a remittance stub, a signature block) but not for a 600-word invisible layer: too many output tokens, "approximate" precision on 9-11 pt type, and no PDF/A benefit. Vision boxes stay; Claude text is aligned to them (2e).

### 2c. Does LLM correction help on this kind of text? (literature, measured)

- **Thomas, Gaizauskas, Lu (LT4HALA 2024), BLN600 19th-century newspapers, test-set mean CER 8.4 %.** CER reduction: BART-140M 14.60 %, BART-400M 23.30 %, Llama 2 7B 43.26 %, Llama 2 13B 54.51 % (fine-tuned, 5-run mean). Their Table 2 includes a *hallucination* row: OCR "A BAD , .0- ? aff-a. . t , -", ground truth "A SAD CASE.", model "A BAD AFFRAY." and a misnamed-entity row where "MR. JOHN TROUTBECK" became "MATTHEW RUTHVEN": fluent, confident, wrong. Source: https://aclanthology.org/2024.lt4hala-1.14/
- **CLOCR-C (arXiv 2408.17428, 2024).** Best of seven LMs cut CER by over 60 % on NCSE; "misleading socio-cultural context in the prompts lowers performance". Source: https://arxiv.org/abs/2408.17428
- **Boros et al. (LaTeCH-CLfL 2024), 14 models (GPT-2/3/3.5/4, LLaMA/-2, BLOOM/Z, OPT), 7 benchmarks.** "Overall, the performance of LLM-based post-correction is very poor, with a considerable degradation in the quality of original transcriptions across all models, prompts and datasets"; "LLMs mostly degrade the input text, occasionally leave it unchanged, and rarely improve it"; "the noisiest input texts are those that show the least degradation, and sometimes even improvement. This underlines the ability of LLMs to make corrections where necessary, but not to leave almost error-free texts intact"; manual inspection of ~2,500 pairs found "most cases correspond to strong deviations from the GT (C3), with a majority of pure hallucination", GPT-4 "embellishing the text as it sees fit". Source: https://aclanthology.org/2024.latechclfl-1.14/ **Stale flag:** 2023-era models; Claude 5.5 is far stronger, but the failure *modes* (paraphrase, embellishment, invented entities) are exactly the ones a legal/tax archive cannot tolerate.
- **Claude's own transcription accuracy** (from `ocr.md`, measured by third parties on clean documents): Opus 5.5 text sub-score 94.5, Sonnet 5.5 93.3 on Datalab OmniParseBench; Roboflow transcription 93-95 %. No benchmark covers Claude 5.5 on handheld phone photos, and no CER for Apple Vision on such photos exists either (both unknown).

Net: the literature supports correction when the OCR is bad (historical, >5 % CER) and warns against it when the OCR is nearly clean. Modern printed mail photographed under decent light is the second case most of the time; the first case (faxed forms, dot-matrix receipts, handwriting, carbon copies) is the minority. That argues for *conditional* correction, gated on Vision confidence and a cheap disagreement signal, not blanket transcription.

### 2d. How much OCR noise hurts search (measured)

**OHRBench (arXiv 2412.02592, 8,561 pages, 8,498 Q&A).** Ground truth gives retrieval 70.0 / generation 43.9 / overall 36.1; the best OCR solutions lose "a 14 % (5 F1-score) drop" overall; "increasing Semantic Noise from mild (r=0) to severe (r>0.6) results in nearly a 50 % performance decline" for most retrievers and LLMs; formatting noise cost at most 12.7 % (BGE-M3 retrieval) and 9.1 % (Llama3.1-8B generation), mostly on table/formula questions; OCR errors were present in 66 % of failed semantic-noise cases. Source: https://arxiv.org/abs/2412.02592

Read-across: mild character noise barely moves retrieval; what collapses it is severe noise. On a personal archive the practical risks are (i) a misread *digit* in an account number or amount (exact-match search and anchors), and (ii) a misread *sender/entity name* (facet search). Both are better fixed as *fields* (which Claude already extracts from the image) than by re-transcribing 600 words.

### 2e. Re-aligning corrected text to Vision boxes

Claude does not need to return coordinates if its text is aligned back to Vision's geometry. The standard technique is character-level edit-distance alignment between the OCR string (each character tagged with its source word/box) and the corrected string, then giving each corrected word the box(es) of the OCR characters it aligns to. This is the same alignment OCR evaluation tools perform to compute CER (e.g. dinglehopper, Apache-2.0, aligns GT and OCR at character and word level from PAGE/ALTO/text; https://github.com/qurator-spk/dinglehopper) and the same machinery OCRmyPDF's fpdf2 renderer relies on to achieve "Accurate text positioning aligned with OCR bounding boxes" (https://ocrmypdf.readthedocs.io/en/latest/advanced.html).

Fast implementations exist: edlib (C/C++, Myers bit-vector + Ukkonen banding + Hirschberg linear-space traceback; global/prefix/infix modes; returns the full alignment path or a CIGAR string; O(T*Q) time, O(T+Q) space; official Python bindings; https://github.com/Martinsos/edlib). A Swift port of banded Needleman-Wunsch is ~100 lines; a dense page is ~4-8k characters.

**Measured, my simulation (section 2f):** on a synthetic 600-word bill (12 % amounts, 6 % dates, 6 % long digit strings) with OCR noise of 0.5 / 2 / 5 % character substitutions plus 1 % word splits, 1 % merges and 0.5 % dropped short words, full Needleman-Wunsch assigned a box to 99.8-100 % of corrected words and the *correct* box in 99.8-100 % of cases; 4-7 words per page map to two boxes (OCR splits). A 96-character band gave the same coverage (99.8-100 %) in 254 ms for 4,214 characters and 516 ms for 8,499 characters in pure Python with dict-backed rows; the un-banded version took 2.5-3.3 s and 11.6-12.8 s. A Swift/edlib implementation on an A15 is an **estimated 2-10 ms** per page (not measured). With an LLM that drops a whole line and rewrites 2 % of words, coverage stayed 99.8 %, i.e. hallucinated words silently inherit the box of whatever they displaced: alignment cannot detect hallucination, only a disagreement threshold can.

Two layer-construction details follow from `output.md`: the glyphless-font + `3 Tr` + `Tz` technique spans each word across its box regardless of character count, so a corrected word of different length still fits; and veraPDF's PDF/A rules exempt rendering mode 3 from glyph-presence/width checks but *not* from the ToUnicode requirement (6.2.11.7.2-1, levels A/U: "The Font dictionary of all fonts shall define the map of all used character codes to Unicode values"; 6.1.3-3: "No data can follow the last end-of-file marker except a single optional end-of-line marker"). Sources: https://github.com/veraPDF/veraPDF-validation-profiles/wiki/PDFA-Parts-2-and-3-rules , https://en.wikipedia.org/wiki/PDF/A

### 2f. Simulation details (measured, my run)

Script: `../tools/align_sim.py` and `align_banded.py` (stdlib only, seed 7). Noise model uses a confusion table (o/0, l/1, 5/S, 8/B, e/c, m/rn, a/o, i/l) plus random substitutions. Results:

| Case | Corrected words | OCR tokens | Edit distance | Words with a box | Correct box | Time (pure Python) |
|---|---|---|---|---|---|---|
| 600 w, CER 0.5 % | 600 | 602 | 29 | 100 % | 100 % | 3.3 s full / n.a. |
| 600 w, CER 2 % | 600 | 598 | 90 | 99.8 % | 99.8 % | 2.7 s full / 0.25 s banded |
| 600 w, CER 5 % | 600 | 599 | 188 | 99.8 % | 99.8 % | 2.5 s full / 0.25 s banded |
| 1,200 w, CER 2 % | 1,200 | 1,196 | 162 | 100 % | 100 % | 12.8 s full / 0.52 s banded |
| 600 w, CER 2 % + LLM drops a line and rewrites 2 % | 589 | 603 | 224 | 99.8 % | n.a. | 2.4 s full |

Caveats: synthetic text, Latin script, no column reflow, no table cells; real Vision line segmentation and Claude paragraph reflow will add insertions/deletions of whitespace and hyphenation that the alignment handles but which I did not model.

### 2g. Where corrected text can go without rewriting the PDF

- **Google Drive**: `contentHints.indexableText` "is limited to 128 KB in length and may contain HTML elements" and exists "to improve fullText queries"; `appProperties` are "private to the requesting app"; `sha256Checksum` is exposed. A metadata-only `files.update` sets these without re-sending content (standard API behaviour; verify the specific client call). Source: https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- **Synology Universal Search** indexes PDF text layers; whether a modified file is re-indexed promptly and whether semantic indexing applies outside Team Folders is per `search.md` (DSM 7.4 spec); re-index latency after overwrite is unknown.
- **iCloud Drive**: no content index of its own that the app controls; Spotlight on device uses the app's Core Spotlight items (`search.md`), which the app can update at any time.
- **PDF/A rewrite**: the own-writer design in `output.md` re-emits the image object as a byte copy and only regenerates the text object, so a rewrite is cheap locally (ms, 150-400 KB file). Whether PDF/A tolerates an *incremental* update is not settled by the sources fetched (veraPDF 6.1.3-3 constrains post-`%%EOF` data; pdfa.org returned 403); a full rewrite avoids the question. The cost of a rewrite is therefore entirely in re-upload, destination revision churn and re-verification (gap-5), not in generation.

---

## 3. Options compared

| Option | Text layer source | FTS body | Embedding input | Dedup anchors | Per-page cloud cost / extra time | PDF rewrite after cloud pass | Risk |
|---|---|---|---|---|---|---|---|
| A. Vision corrected (`.accurate`, correction on) only | Vision words/lines | Vision transcript (paragraph order) | Vision transcript + Claude fields | Vision corrected tokens | $0 / 0 s (extraction call unchanged) | never | Digits mutated by correction ("C001 -> cool"); no fix for misread names |
| B. Vision raw (`usesLanguageCorrection = false`) only | Vision raw words | raw transcript | raw transcript | raw tokens | $0 / 0 s, OCR ~2x faster | never | "Less accurate results" (Apple); worse FTS on words; `customWords` disabled |
| C. Two Vision passes (`.fast` raw + `.accurate` corrected) | corrected words/lines | corrected transcript | corrected transcript + Claude fields | **raw** tokens, cross-checked | $0 / +~100-200 ms on A18 (est. 2x on A15) | never | Two sets of boxes to reconcile (same engine, same geometry) |
| D. C + Claude diff-style corrections (line index + text) | corrected words, lines patched by index | patched transcript | patched transcript + fields | raw tokens validated 2-of-3 | +$0.00003-0.00008 / +0.2-0.9 s generation | only when material (rare) | Untested schema; Claude must respect line indices |
| E. C + full Claude transcript on every page (sync) | Claude text aligned to Vision boxes | Claude transcript | Claude transcript | raw tokens validated | +$0.0005 / +4.3-7.2 s + TTFT | **every page** (second upload + verify) | Hallucination inherits boxes silently; doubles cloud time; degrades near-clean text (Boros) |
| F. C + full Claude transcript via Batch for flagged pages | as E, async | as E | as E | as D | +$0.00025 on flagged pages, 12-h window | flagged pages only | Index/PDF temporarily out of sync (acceptable; sidecar versioned) |
| G. Claude returns word boxes itself | Claude boxes | Claude text | Claude text | Claude digits | +$0.003-0.0045 / +26-54 s | every page | "Approximate" coordinates, small-text precision loss (Anthropic); unusable for a word layer |

---

## 4. Recommendation for this project

### 4.1 Text sources, by consumer

| Consumer | Source | Why |
|---|---|---|
| Invisible PDF text layer (PDF/A-2u) | Vision `.accurate` + correction on: `Container.Text.lines` with per-word sub-range boxes (`boundingRegion(for:)`), falling back to line boxes where `words == nil` (CJK/Thai) | Deterministic geometry, Unicode-mappable strings, no cloud dependency; written at S1 |
| Transcript string (FTS `ocr_text`, Claude prompt, embeddings) | Same pass, concatenated in `paragraphs` order, line breaks preserved inside paragraphs | Reading order for multi-column mail; what Claude should see |
| Dedup anchors (dates, amounts, account/reference numbers, "Page N of M") | Vision `.fast` with `usesLanguageCorrection = false` on the rectified still, plus `detectedData` from the documents request | Raw digits are what anchors need; correction is the documented way to corrupt them |
| Facets / fields (`sender`, `document_date`, `amount_total`, `account_refs`, `tax_year`) | Claude Haiku 5.5 extraction from image + numbered Vision lines (already in `claude.md`) | Claude reads the pixels, so it is an independent witness for digits and names |
| Embedding input | `title + summary + tags + first ~1,500 tokens` of the *patched* transcript (4.3) | Per `claude.md`; corrections matter more for names than for body text |
| Trigram FTS table | Vision transcript (all words, any confidence) + every variant of validated fields | Partial account-number and fuzzy search need the noisy strings too |

### 4.2 Two Vision passes, not one

The `.fast` raw pass already exists in the latency plan (`gap-3` T3, 101 ms p50 on A18, estimated 300-600 ms on A15); make it the anchor source by setting `usesLanguageCorrection = false`. The `.accurate` + correction pass (736 ms A18 p50, est. 1.5-2 s A15) runs off the feedback path and produces the layer and transcript. If `RecognizeDocumentsRequest` turns out not to expose a correction switch (unknown), keep `RecognizeTextRequest` for the raw pass and use the documents request for the corrected one. Feed `customWords` with the user's known senders and account labels (it is ignored on the raw pass by design). Measure both passes on A15 in the week-one harness; if the two passes exceed the ~2 s/page cadence on A15, demote the raw pass to digit-bearing lines only (crop by line box, `regionOfInterest`).

### 4.3 Claude corrects by line index; it does not transcribe by default

Extend the extraction schema with `corrections: [{line: int, text: string, reason: enum[digit, name, amount, date, other]}]` and the instruction "only lines you can read from the image with confidence and that change a name, number, date or amount". The Vision lines are already in the prompt; number them. Expected output ~50-150 tokens, so the cloud pass stays at the ~3-4 s `claude.md` budget. Apply corrections by replacing the line's text and re-spanning its existing word boxes with the character alignment from 2e (needed only when the word count changes). Because `output_config.format` constrains the JSON (claude.md), `line` can be bounded to the valid range by `enum` if you include the line count in the schema per request, or validated client-side.

Full-transcript mode (option F) is triggered when any of: mean `RecognizedText.confidence` on the page below a calibrated floor; Claude's `corrections` touch more than N % of lines; `detectedData` finds no date/amount on a document whose `doc_type` implies one; script is CJK/Thai or handwriting is flagged. It runs on the Batch API ($0.00025/page output, 50 % off input too, 12-h window) with the page image at full high-res-tier size and the Vision transcript as context, and the result is aligned with the 2e algorithm. Reject the transcript (keep Vision) if alignment edit distance exceeds a threshold (start at 8 % of characters) or if any validated anchor field disagrees; Boros's hallucination categories are precisely the cases that fail this check.

### 4.4 Conflict policy for anchors and searchable fields

Three witnesses per field: Vision raw, Vision corrected, Claude-from-image.
- **Validated** when two agree exactly after normalisation, or when one passes a structural check (ISO date parses and is within a plausible window; amount matches `^\d{1,3}(,\d{3})*\.\d{2}$`; account/reference passes Luhn, IBAN mod-97, ABA checksum, or the sender's known format) and no other witness passes.
- **Record and search**: store the validated value as the field; store all witnesses as `alternates`; index all of them in the trigram table so "4471" finds the page even if the field was validated differently.
- **Dedup merge** (gap-2 rule): only Vision-raw anchors from both captures, never Claude anchors, because the merge test must compare like with like and Claude is not run on every capture before the dedup decision. Field disagreement between Vision raw and Claude on the *same* capture marks the page `anchor_uncertain`, which blocks automatic merge and surfaces in the review list.
- **Low-confidence Vision words**: keep in the PDF layer and trigram table (zero visual cost; preserves phrase search and the "find any page containing X" guarantee); exclude from anchors; do not drop them from `ocr_text` either, since FTS5 has no per-token weight and a gap breaks phrase queries. Record per-line confidence in the sidecar so a future reindex can change the policy without re-OCR.

### 4.5 Handoff contract: emit at S1, patch after Claude, rewrite rarely

Emitted at S1, before any network call (all local, fsync'd per `gap-4`):
1. raw still (cache tier, never gates S2),
2. corrected archival image (HEIC/JPEG, print-ready),
3. analysis JPEG, pre-resized with Anthropic's `resized_size` helper so coordinates and tokens are deterministic (<= 1,100 px short edge per `claude.md`, or the full high-res-tier size for flagged pages),
4. `ocr.json` v1: both Vision passes (strings, confidence, boxes, paragraphs, detectedData, `recognitionLanguages`, Vision revision),
5. provisional PDF/A-2u with the Vision layer, XMP `pap:ocrEngine=vision-accurate-lc`, `pap:textLayerVersion=1`,
6. sidecar `meta.json` v1 (no Claude fields; `schema_version`, hashes).

After the Claude return (3-7 s, or hours on Batch):
7. `meta.json` v2 with fields, tags, summary, title, corrections, validation results; local FTS/vector/facet rows updated; Core Spotlight item updated,
8. destination metadata patch where supported: Drive `indexableText` (title + summary + tags + patched transcript, truncated to 128 KB) and `appProperties`; Synology/iCloud rely on the sidecar and the eventual PDF,
9. PDF rewrite **only if** the patched transcript differs from the layer by more than a material threshold (proposal: any validated anchor field changed, or > 2 % of characters changed, or full-transcript mode accepted). Rewrite = regenerate text object, byte-copy image object, bump `pap:textLayerVersion`, new SHA-256, re-run the gap-5 verify/rename flow. Expected frequency on clean mail: low (unmeasured; instrument it).

Do not hold the upload for Claude. S2 ("Safe") must depend only on the S1 artifacts; a 3-7 s cloud pass with retries would push the lock icon into the 10-30 s range that `gap-4` option E rejected. The one-time cost of the rare rewrite (second upload of a 150-400 KB file) is far cheaper than making every page wait.

### 4.6 What to measure in week one

1. Vision CER between two handheld captures *and* against a typed ground truth for 200 pages (letters, bills, EOBs, receipts, forms), both passes, A15 and A18: this decides whether 4.3's thresholds ever fire.
2. Does `topCandidates(3)` with correction on contain the raw reading? If yes, the raw pass may be unnecessary.
3. Haiku 5.5 `thinking: disabled`, `effort: low` TTFT and tok/s on the real prompt (`count_tokens` + wall clock).
4. Frequency of material corrections (4.5 step 9) on the same 200 pages.
5. Swift banded alignment time on A15 for 8k characters.

---

## 5. Risks and unknowns

- **Apple Vision CER on handheld mail is unmeasured** (every earlier report says so). If it is > 3-5 % on common mail, conditional correction becomes routine and option F's batch delay (12 h) means the archive's text is "provisional" for hours on many pages; the sidecar version field makes this honest but the search quality promise weakens.
- **Hallucination inherits geometry.** Alignment maps whatever Claude writes onto Vision boxes; only disagreement thresholds and anchor validation catch invented text. A tax archive with an invented account number is worse than one with a misread one.
- **Haiku thinking-off latency unmeasured**; if TTFT is several seconds the diff-style corrections still fit, but full-transcript sync mode (E) is dead on arrival, which is consistent with the recommendation.
- **`RecognizeDocumentsRequest` correction switch and latency unknown**; the two-pass plan assumes a raw pass is available on iOS 26 via `RecognizeTextRequest` at least.
- **PDF rewrite churn** on destinations: Drive keeps revisions (quota), Synology re-index latency unknown, iCloud Drive replace semantics interact with gap-4's `isUploaded` verification; a rewrite must go through the same verify path or S3 state regresses silently.
- **Drive `indexableText` 128 KB cap** truncates long multi-page documents; the PDF layer remains the full-text fallback there.
- **Literature staleness**: the post-OCR studies use 2023-2024 models on historical text; no study measures Claude 5.5 correcting Apple Vision output on modern print. Treat the "degrades near-clean text" finding as a design prior to be tested, not a fact about Claude 5.5.
- **Simulation limits**: Latin script, no multi-column reflow, no tables; real alignment inputs will have more whitespace/hyphenation edits, which raise edit distance but should not change box assignment.

---

## 6. Open questions for the founder

1. Is a 12-hour window acceptable for the *final* text of hard pages (handwriting, faded receipts) if the provisional Vision text is searchable immediately, or must every page be final within minutes (which forces sync full transcripts and the ~5-7 s cloud pass)?
2. Should the PDF text layer ever be rewritten after upload, or should corrections live only in the sidecar/index and the archive file be immutable once verified (simplest durability story, slightly worse text layer on flagged pages)?
3. May the app keep low-confidence words in the invisible layer (better recall, occasional nonsense in copy/paste) or do you want a "clean copy/paste" guarantee?
4. For disputed digits (Vision raw vs Claude), do you want a review queue at all, given the zero-interaction goal, or should the app silently keep both and show the validated one?
5. Is iOS 26 the floor (documents request, paragraphs, detectedData), or must the text pipeline also work on iOS 18 with `RecognizeTextRequest` only?
6. Are non-Latin scripts (CJK/Thai, where `words` is nil and correction is unsupported) in scope for v1?

---

## 7. Sources

- Apple, `usesLanguageCorrection` (Swift): https://developer.apple.com/documentation/vision/recognizetextrequest/useslanguagecorrection
- Apple, `usesLanguageCorrection` (ObjC): https://developer.apple.com/documentation/vision/vnrecognizetextrequest/useslanguagecorrection
- Apple, `customWords`: https://developer.apple.com/documentation/vision/recognizetextrequest/customwords
- Apple, `RecognizedText`: https://developer.apple.com/documentation/vision/recognizedtext
- Apple, `RecognizedTextObservation`: https://developer.apple.com/documentation/vision/recognizedtextobservation
- Apple, `DocumentObservation`: https://developer.apple.com/documentation/vision/documentobservation
- Apple, `DocumentObservation.Container`: https://developer.apple.com/documentation/vision/documentobservation/container
- Apple, `DocumentObservation.Container.Text`: https://developer.apple.com/documentation/vision/documentobservation/container/text-swift.struct
- Apple, `DataDetectorMatch`: https://developer.apple.com/documentation/vision/documentobservation/container/datadetectormatch
- Apple, Recognizing text in images: https://developer.apple.com/documentation/vision/recognizing-text-in-images
- WWDC19 session 234 transcript: https://nonstrict.eu/wwdcindex/wwdc2019/234/
- WWDC25 session 272 transcript: https://nonstrict.eu/wwdcindex/wwdc2025/272/
- text_sight measurements (via gap-3): https://pub.dev/documentation/text_sight/0.2.2/
- Anthropic, Pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Anthropic, Claude Haiku 5.5 overview: https://platform.claude.com/docs/en/models/haiku-5-5/overview
- Anthropic, Vision: https://platform.claude.com/docs/en/build-with-claude/vision
- Anthropic, Coordinates and bounding boxes: https://platform.claude.com/docs/en/build-with-claude/vision-coordinates
- Artificial Analysis, Claude Haiku 5.5: https://artificialanalysis.ai/models/claude-haiku-5-5
- OHRBench (Zhang et al.): https://arxiv.org/abs/2412.02592
- CLOCR-C: https://arxiv.org/abs/2408.17428
- Boros et al., LaTeCH-CLfL 2024: https://aclanthology.org/2024.latechclfl-1.14/
- Thomas, Gaizauskas, Lu, LT4HALA 2024: https://aclanthology.org/2024.lt4hala-1.14/
- dinglehopper: https://github.com/qurator-spk/dinglehopper
- edlib: https://github.com/Martinsos/edlib
- OCRmyPDF advanced features (renderers, redo-ocr): https://ocrmypdf.readthedocs.io/en/latest/advanced.html
- veraPDF PDF/A-2/3 rules: https://github.com/veraPDF/veraPDF-validation-profiles/wiki/PDFA-Parts-2-and-3-rules
- Wikipedia, PDF/A: https://en.wikipedia.org/wiki/PDF/A
- Google Drive Files resource: https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- Simulation scripts (this run): `../tools/align_sim.py`, `.../align_banded.py`
