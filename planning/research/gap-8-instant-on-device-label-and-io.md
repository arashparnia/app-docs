# Gap 8: Instant on-device label, sensitive-class routing, distillation pipeline, and the iOS floor

Research date: 2026-11-03. Dimension: can any on-device path produce a provisional `doc_type` (and the tax/medical/ID "high-sensitivity" routing decision) in ~300-500 ms on the floor device; what accuracy and labelled-data volume each path needs; how Claude labels are collected for the founder's distillation path and when a distilled model beats Haiku; and, given iOS 27 shipped on 2026-09-14, what v1 floor (17/18/26/27) cuts off whom.

Method note: the shared web-search budget was exhausted before this round started, so every finding comes from direct fetches of primary sources (Apple doc JSON endpoints, WWDC transcripts via nonstrict.eu, Apple ML research posts, arXiv PDFs extracted locally, StatCounter, Apple's App Store measurement page). Each number is tagged **measured** (published measurement on hardware), **vendor** (Apple/author statement), **computed** (derived here from vendor numbers; verify on device), or **unknown**. I read `gap-3`, `apple.md`, `claude.md`, `gap-6`, `privacy.md`, `ocr.md` and `architecture.md` first and do not repeat them.

## 1. Executive summary

1. **Yes, a provisional label in <300 ms is achievable on the floor device, but not with Foundation Models.** The right hot-path stack is (a) regex/keyword rules over the `.fast` OCR transcript (<5 ms, **computed**) plus (b) a per-user "sender memory" (letterhead feature print + sender string kNN over Claude-labelled pages, tens of ms, **estimate**) plus (c) a Create ML `MLTextClassifier` trained from Claude labels (maxEnt: ~1 ms; BERT transfer learning: ~10-80 ms, **estimate** from Apple's 3.47 ms DistilBERT-on-A15 figure). All three run on every iOS 17+ device with no Apple Intelligence gate.
2. **Foundation Models is the wrong primary.** It needs A17 Pro+ with Apple Intelligence enabled, its only published speed is **0.6 ms per prompt token and 30 tok/s on iPhone 15 Pro** (Apple, 2024 model), so a full-page transcript (2-3k tokens) costs 1.2-1.8 s of prefill before any output: that is where the "2-3 s per page" figure comes from. A 300-token header prompt with an enum-only `@Generable` output is **~0.25-0.5 s computed**, so it is usable only as a trimmed-prompt second opinion. Worse for this dimension: guided generation always runs the default guardrails (Apple: `permissiveContentTransformations` "only works for generating a string value"), so medical/legal pages are exactly where it may throw `guardrailViolation`.
3. **Accuracy ceiling for text-only classification is high**: on RVL-CDIP (16 classes) BERT-base on clean OCR text reaches **89.81%** vs 90.97% for VGG-16 images and 94.42% for LayoutLM with images (**measured**, LayoutLM paper). With noisy Tesseract OCR and a FastText model text-only drops to **74.6%** (**measured**, Audebert 2019). Vision's `.fast` output on a rectified page sits between those regimes; expect 80-90% on the 26-33-class taxonomy once ~100 labels/class exist (**estimate**).
4. **Sensitive-class routing should be rule-first, recall-biased**: IRS forms carry a visible "OMB No. 1545-xxxx" (verified on the 2026 W-2: "OMB No. 1545-0029"), medical pages carry EOB/CPT/NPI/patient vocabulary, US driver licences carry a PDF417 barcode that Vision decodes (`BarcodeSymbology.pdf417`, iOS 18). A rule hit or a classifier posterior above a low threshold routes the page to text-only Claude (per `privacy.md`); the cost of a false positive is only extraction quality.
5. **Labelled-data needs**: Apple's adapter guidance is 100-1,000 samples for basic tasks and 5,000+ for complex ones; Create ML transfer learning with BERT embeddings is explicitly for "without requiring huge amounts of task-specific training data" (WWDC23); SetFit-style few-shot methods are competitive at N=8 per class (**measured**, SetFit paper). Plan on **50-100 Claude-labelled pages per class (~2-3k pages total)** before the classifier replaces rules as the primary label, and 5k+ before any adapter.
6. **Distillation economics**: the on-device label wins on latency immediately (tens of ms vs ~3-4 s streamed Haiku per `claude.md`). It wins on cost only for pages where the Claude call is skipped entirely (marketing/junk, exact re-scans); at $0.0003-0.0008 per Haiku page (`gap-6`) and 150 pages/user/month, the whole Claude bill is ~$0.05-0.12/user/month, so cost is not the reason to distill. Apple adapters cost 160 MB each, one per OS model version, need an entitlement, and the current toolkit (26.0.0) "is not compatible with iOS 27" (**vendor**); do not build the product on them.
7. **iOS floor**: iOS 26 and iOS 27 support identical hardware (A13 / iPhone 11 and later); iOS 17/18 add only A12 (XS/XR, 2018). Apple measured **79% of all iPhones on iOS 26 (86% of those introduced in the last four years) on 2026-06-07** (**measured**, Apple); StatCounter US October 2026 shows iOS 27.x at ~15%, iOS 26.x at ~62%. A 27-only floor today excludes ~80% of users; a 26 floor excludes ~15-20% of users today (mostly 18.x holdouts and misreported 26.x) and the 2018 XS/XR hardware.
8. **Recommendation**: deployment target **iOS 26.0**, `#available(iOS 27)` for Foundation Models image attachments, `OCRTool`, Core AI and the Foundation Models `LanguageModel` protocol (Anthropic is publishing a Swift package for it); plan to raise to 27 around mid-2027 when 27 crosses ~80%. Do not pick 17/18 unless the founder's App Store Connect data shows a large iOS-18 cohort.
9. **The sub-second feedback can include a label on every device**, but it should be shown as provisional (rules/kNN/classifier), then replaced by Claude's `doc_type` streamed first, with every disagreement logged as training data.
10. Biggest unknowns: nobody has published Foundation Models latency on A17 Pro-A19 for the 2025/2026 models; Create ML BERT-embedding inference latency on iPhone is unpublished; the founder's own iOS-version and chip mix is unknown until App Store Connect is checked.

## 2. Findings

### 2a. What "instant" costs on each on-device path (floor = iPhone 13 / A15, iOS 26)

| Path | Min OS / hardware | Input it needs | Latency on floor | Status | Source |
|---|---|---|---|---|---|
| Regex/keyword rules over `.fast` OCR text | iOS 18 Swift API (VN form iOS 13); any chip | `RecognizeTextRequest .fast` transcript (101 ms p50 on A18 at text_sight's page size; 300-600 ms on A15 at 2-3 MP, per `gap-3`) | <5 ms after OCR | computed | OCR: https://github.com/LahaLuhem/text_sight/blob/main/doc/performance.md |
| Letterhead / sender memory (feature print kNN + sender string) | iOS 18 (`GenerateImageFeaturePrintRequest`), any chip | Header crop of the rectified page + the first OCR lines | feature print: unknown (assume 5-20 ms); kNN over a few hundred vectors: <1 ms | estimate | https://developer.apple.com/documentation/vision/generateimagefeatureprintrequest |
| Create ML `MLTextClassifier`, `maxEnt` | Train: macOS 10.14 / iOS 15 (on-device Create ML); run: `NLModel` iOS 12 | OCR transcript (any length) | ~1 ms (bag-of-words logistic regression) | estimate | https://developer.apple.com/documentation/createml/mltextclassifier ; https://developer.apple.com/documentation/naturallanguage/nlmodel |
| Create ML `MLTextClassifier`, `.transferLearning(.bertEmbedding)` | `NLContextualEmbedding` assets iOS 17; any chip | OCR transcript, truncated to the embedding's `maximumSequenceLength` | unpublished; Apple's ANE-optimised DistilBERT runs 128 tokens in **3.47 ms on iPhone 13** (measured), so a few hundred tokens through Apple's BERT model is plausibly 10-80 ms | estimate from measured | https://machinelearning.apple.com/research/neural-engine-transformers ; https://developer.apple.com/documentation/naturallanguage/nlcontextualembedding |
| Foundation Models, text-only `@Generable` enum | iOS 26; A17 Pro+ with Apple Intelligence enabled | Trimmed OCR text | **not available on the floor device at all**; on A17 Pro: 0.6 ms/prompt token + 30 tok/s (2024 model, measured by Apple) -> 300-token prompt + 1-3 output tokens ~0.25-0.5 s; 2,500-token page ~1.5 s prefill + ~1.3 s for a 40-token struct ~2-3 s | computed | https://machinelearning.apple.com/research/introducing-apple-foundation-models |
| Foundation Models, image `Attachment` | iOS 27; A17 Pro+ | Page image (any size; "larger images will consume more tokens and incur more latency") | unknown; the 2025 tech report's on-device vision backbone is 300M params, 144 image tokens at 672x672 or 9 tokens in "rapid mode" at 224x224 | unknown | https://nonstrict.eu/wwdcindex/wwdc2026/241/ ; https://arxiv.org/html/2507.13575 |

Why the earlier reports' Foundation Models numbers disagree: `architecture.md` budgeted "<800 ms" by assuming a <1k-token prompt, `apple.md` called it "instant", and the refutation's "2-3 s" assumes the whole page transcript plus a multi-field struct. All three are consistent with the single Apple measurement (0.6 ms/token, 30 tok/s on iPhone 15 Pro); they differ only in prompt and output size. The 2025 model claims TTFT reduced "by ~37.5%" through KV-cache sharing and uses speculative decoding (**vendor**, https://machinelearning.apple.com/research/apple-foundation-models-2025-updates), and iOS 27 ships a model "rebuilt from the ground up" with no published numbers. `prewarm(promptPrefix:)` can pre-process the instructions+taxonomy prefix but Apple says to call it only with "a window of at least 1 second before the call" (https://developer.apple.com/documentation/foundationmodels/languagemodelsession/prewarm(promptprefix:)), which the capture loop has. The WWDC26 Instruments session confirms the three metrics to log (TTFT, tokens/s, total latency) but shows no values (https://nonstrict.eu/wwdcindex/wwdc2026/243/).

Availability gates that apply to Foundation Models and to nothing else in the table: `SystemLanguageModel.Availability.UnavailableReason` has `deviceNotEligible`, `appleIntelligenceNotEnabled`, and `modelNotReady` (https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel/availability-swift.enum/unavailablereason); 16 supported languages, and "all inputs need to be in supported language for the model to understand, including all `Generable` types" (https://developer.apple.com/documentation/foundationmodels/supporting-languages-and-locales-with-foundation-models); Apple Intelligence hardware is iPhone 15 Pro/Pro Max, iPhone 16 or later, iPhone Air (https://support.apple.com/en-us/121115).

### 2b. The guardrail problem for sensitive classes

Apple's safety article: "the input prompt and the model output are both checked by a guardrail. If either fails the safety check, the model session throws a `guardrailViolation` error"; guardrails "aim to block harmful or sensitive content"; the default guardrails "may throw a `guardrailViolation` error for sensitive source material". The escape hatch, `permissiveContentTransformations`, "only works for generating a string value. When you use guided generation, the framework runs the default guardrails against model input and output as usual, and generates `guardrailViolation` and `refusal` errors as usual", and even then "the model may still produce a refusal message" (https://developer.apple.com/documentation/foundationmodels/improving-the-safety-of-generative-model-output). The WWDC26 transcript notes guardrail false-positive reductions in iOS 26.4 and more in 27 (https://nonstrict.eu/wwdcindex/wwdc2026/241/), rates unpublished.

Consequence: a `@Generable` enum classifier cannot be the gate that decides whether a medical, legal or ID page may be sent as an image to Claude, because the pages most likely to be refused are the ones the gate exists for. The gate must be rules + a Create ML classifier (no guardrails), with Foundation Models at most a string-mode second opinion.

### 2c. Rule cues that identify the high-sensitivity classes

| Class (from `claude.md` enum) | Cues visible in the OCR text | Evidence |
|---|---|---|
| `tax_form` | "OMB No. 1545-" (IRS Paperwork Reduction Act number printed on IRS forms); "Form W-2", "1099-", "1098", "1095-", "Wage and Tax Statement", "Department of the Treasury - Internal Revenue Service"; a tax year in the header | Verified on the current W-2 PDF: "OMB No. 1545-0029", "W-2 Wage and Tax Statement 2026" (https://www.irs.gov/pub/irs-pdf/fw2.pdf, text extracted locally) |
| `tax_notice` | "Notice CP", "Notice number", "Tax period", IRS/state DOR letterhead | general knowledge; validate on real notices |
| `medical_record`, `medical_bill`, `prescription` | "Explanation of Benefits"/"EOB", "This is not a bill", "patient", "date of service", "CPT", "ICD", "NPI", "DEA", "Rx", "refills", "provider", "diagnosis", "copay/deductible" | general knowledge; validate |
| `id_document` | MRZ lines (`P<`, `<<<` runs), "Driver License"/"DL", "DOB", "Class", "Endorsements"; a **PDF417 barcode** on the back of US licences | Vision decodes `pdf417` (and `microPDF417`, `qr`, `aztec`, `dataMatrix`...) via `BarcodeSymbology`, iOS 18 Swift API (https://developer.apple.com/documentation/vision/barcodesymbology) |
| Any class | SSN pattern `\b\d{3}-\d{2}-\d{4}\b`, Medicare MBI pattern, account-number runs | regex; treat as sensitivity signal independent of class |

`RecognizeDocumentsRequest` (iOS 26) also surfaces data detectors (`moneyAmount`, `postalAddress`, `paymentIdentifier`, `phoneNumber`, `calendarEvent`...) per `apple.md`, which are useful features for the classifier but not for sensitivity.

Routing rule to implement: `sensitive = ruleHit || P(classifier in {tax_*, medical_*, prescription, id_document, insurance_claim}) > 0.3`. Bias for recall: a false positive sends text-only to Claude (lower extraction quality, per `privacy.md`); a false negative uploads an image of an SSN.

### 2d. Accuracy ceilings for text-only classification

| Setup | Dataset / classes | Accuracy | Status | Source |
|---|---|---|---|---|
| BERT-base, text only (clean OCR) | RVL-CDIP, 16 classes, 400k images | 89.81% | measured | LayoutLM paper Table 5, https://arxiv.org/pdf/1912.13318 (extracted locally) |
| RoBERTa-large, text only | same | 90.11% | measured | same |
| VGG-16, image only | same | 90.97% | measured | same |
| LayoutLM-base, text + layout | same | 91.78% | measured | same |
| LayoutLM-base, text + layout + image | same | 94.42% | measured | same |
| FastText-based CNN on **Tesseract** OCR text | RVL-CDIP | 74.6% | measured | Audebert et al. 2019 Table 2, https://arxiv.org/pdf/1907.06370 |
| MobileNetV2 image only / fusion | RVL-CDIP | 89.1% / 90.6% | measured | same |

Reading for this project: text alone gets within ~1 point of images and ~4-5 points of the multimodal ceiling on a 16-way task when OCR is clean; with noisy OCR text-only collapses by 15 points. Vision `.accurate`/`RecognizeDocumentsRequest` on a rectified 12 MP still is close to the clean regime; `.fast` on a 2-3 MP preview frame is in between, and the text_sight authors note `.fast` misses dense pages at 1080p (`gap-3`). The taxonomy in `claude.md` has 33 enum values (the brief says 26); several pairs (`bill` vs `utility`, `legal_notice` vs `government_letter`, `insurance_policy` vs `insurance_claim`) are text-separable only by vocabulary that OCR captures well, so expect the on-device classifier to be weakest exactly on those pairs. A per-user prior (most mail comes from a few dozen recurring senders) raises accuracy well above any public benchmark for repeat senders; this is the letterhead/sender-memory path.

RVL-CDIP class list for mapping (letter, memo, email, file folder, form, handwritten, invoice, advertisement, budget, news article, presentation, scientific publication, questionnaire, resume, scientific report, specification; 1000-px grayscale, 320k/40k/40k splits, https://adamharley.com/rvl-cdip/) overlaps the consumer-mail taxonomy only for `invoice`, `form`, `letter`, `advertisement`; it is a pre-training/sanity set, not an eval set for this app.

### 2e. How much labelled data each path needs

| Path | Data needed | Evidence |
|---|---|---|
| Rules | 0 labelled pages; ~1 day of writing and a 50-page spot check per sensitive class | this report |
| Sender memory (kNN) | 1 Claude-labelled page per sender; label repeats instantly thereafter | design; precision depends on the feature-print distance threshold, which `dedup.md` says Apple does not publish |
| Create ML `maxEnt` | tens of pages per class to beat rules; Apple: "trains quickly and performs well for a wide variety of data... a good starting point" | https://developer.apple.com/documentation/createml/creating-a-text-classifier-model |
| Create ML `.transferLearning(.bertEmbedding)` | Apple: lets you train "without requiring huge amounts of task-specific training data"; "trains fairly quickly to a high degree of accuracy"; no numbers | WWDC23 session 10042, https://nonstrict.eu/wwdcindex/wwdc2023/10042/ |
| Few-shot sentence-transformer methods (SetFit) | competitive at **N = 8 labelled samples per class**; the paper's headline is 8 examples on Customer Reviews vs RoBERTa-Large fine-tuned on 3k | measured, https://arxiv.org/pdf/2209.11055 (extracted locally) |
| Foundation Models adapter (rank 32) | "100 to 1,000 samples to teach the model basic tasks", "5,000+ samples to teach the model complex tasks"; ~160 MB per adapter; one adapter per system-model version; entitlement `com.apple.developer.foundation-model-adapter`; toolkit 26.0.0 "is not compatible with macOS, iOS, iPadOS, or visionOS 27 and later" | vendor, https://developer.apple.com/apple-intelligence/foundation-models-adapter/ |

Planning number: 50-100 Claude-labelled pages per class, i.e. 1,500-3,300 pages for the full taxonomy, with rare classes (court_document, certificate, id_document) back-filled synthetically or from public forms. A single heavy user at ~150 pages/month produces that in about a year; a 20-person beta produces it in a month.

### 2f. The data pipeline for distillation (the founder's custom-model path)

1. Every captured page already yields: rectified image, Vision transcript with word boxes, data-detector matches, feature print of the header crop, the on-device provisional label with its source (rule / kNN / classifier) and confidence, and later Claude's `doc_type`, `doc_subtype`, `sender`, `confidence`, `needs_review` (schema in `claude.md`).
2. Store `(transcript, header_featureprint, sender, provisional_label, provisional_source, claude_label, claude_confidence, user_correction)` as a local training row; user corrections (rare, since zero interaction is the goal) outrank Claude.
3. Train off-device: export rows (text-only, with sensitive tokens replaced by typed placeholders as `privacy.md` prescribes) to a Mac; `MLTextClassifier(trainingData:, parameters: .init(validation: .split(strategy: .automatic), algorithm: .transferLearning(.bertEmbedding, revision: 1), language: .english))`; evaluate on a held-out, per-user stratified split; ship the `.mlmodel` via Background Assets or in the bundle (Create ML text models are small; size unpublished but far below the 160 MB adapter).
4. Train on-device (optional, v2): Create ML on iOS 15+ can train text classifiers on the phone (WWDC21 10037: image, sound and text classifiers "now available on iOS"), so a personal classifier can be refreshed nightly under `BGProcessingTask` without any data leaving the device. This is the privacy-cleanest form of distillation and needs no entitlement.
5. Promotion rule: the classifier becomes the primary provisional label for a class only when its held-out accuracy on that class beats the rules; sensitive-class routing keeps the rules in OR.
6. iOS 27 adds a second deployment target for a custom encoder: Core AI (`.aimodel`, converted from PyTorch, runs on CPU/GPU/Neural Engine, "no server and no cost per token", https://developer.apple.com/documentation/coreai ; https://nonstrict.eu/wwdcindex/wwdc2026/324/) and the Foundation Models `LanguageModel` protocol with open-source `CoreAILanguageModel`/`MLXLanguageModel` backends, plus Anthropic's own Swift package for Claude behind the same `LanguageModelSession` API (https://nonstrict.eu/wwdcindex/wwdc2026/241/). That lets a future distilled small model (MiniLM/ModernBERT-class) slot into the same session abstraction as Claude. Not for v1.

### 2g. When a distilled model beats Haiku

- Latency: immediately, at any volume. On-device rules/kNN/classifier: ~5-100 ms after OCR. Haiku 5.5 with thinking off: TTFT unpublished, decode ~165-176 t/s, full record ~3-4 s streamed, `doc_type` first (per `claude.md`/`gap-6`). No network path can match tens of milliseconds.
- Cost: Claude remains necessary for extraction/summary/tags, so distillation does not remove the per-page call. Computed: $0.00029-0.00080 per Haiku page (`gap-6`) x 150 pages/user/month = **$0.04-0.12 per user per month**. Savings come only from skipping Claude on classes that need no extraction (marketing/junk, exact re-scans already caught by dedup) and from routing sensitive pages text-only (fewer image tokens, ~1,500-2,100 of the ~2,500 input tokens). If 40% of mail is marketing (**unknown**; measure on the founder's own mail), the saving is ~$0.02-0.05/user/month: real at 100k users (~$2-5k/month), irrelevant at 1k.
- The proper question is therefore not "at what volume" but "at what label count": once ~50-100 labels per class exist, the classifier beats rules; nothing about Haiku changes. Apple adapters never pay back for this product: 160 MB per adapter per OS model version, entitlement, retraining each OS release, A17 Pro+ only, guardrails still applied to guided generation.

### 2h. iOS floor: what each cut-off costs

Hardware support (Wikipedia, cross-checked with Apple support page for Apple Intelligence):

| Floor | Oldest iPhone | Drops vs previous | Apple Intelligence (A17 Pro+) | Source |
|---|---|---|---|---|
| iOS 17 | iPhone XS/XR (A12, 2018) | X/8 | iOS 18.1+ only | https://en.wikipedia.org/wiki/IOS_18 ("all iPhones that support iOS 17 are also compatible with iOS 18") |
| iOS 18 | XS/XR (A12) | none | yes, 15 Pro+ | same |
| iOS 26 | iPhone 11 (A13, 3 GB RAM) | XS/XS Max/XR | yes | https://en.wikipedia.org/wiki/IOS_26 |
| iOS 27 | iPhone 11 (A13) | **none** ("keeps support for all iPhones that support iOS 26") | yes | https://en.wikipedia.org/wiki/IOS_27 (released 2026-09-14) |

Adoption:

| Source | Date | Numbers | Status |
|---|---|---|---|
| Apple App Store measurement | 2026-06-07 (before iOS 27) | iOS 26: **86%** of iPhones introduced in the last four years, **79%** of all iPhones; "As measured by devices that transacted on the App Store" | measured, https://developer.apple.com/support/app-store/ |
| StatCounter, United States | October 2026 | iOS 26.6 54.33%, 18.7 10.48%, iOS 27 10.04%, 26.5 6.05%, 27.0 5.05%, 26.7 1.6% (listed versions sum to 87.55%; no 17.x/16.x rows shown); note: "Apple's Safari anti-fingerprinting changes misreported iOS 26.2 as 18.7 and iOS 26.1 as 18.6" | measured (web traffic, biased), https://gs.statcounter.com/ios-version-market-share/mobile-tablet/united-states-of-america |
| StatCounter, worldwide | October 2026 | 26.6 45.75%, 18.7 9.69%, 27 9.29%, 26.5 7.58%, 27.0 6.71%, 26.7 1.81% | measured (biased), https://gs.statcounter.com/ios-version-market-share/mobile-tablet/worldwide |

Derived (**computed**): a 27-only floor today reaches ~15-16% of US iPhone web traffic; a 26 floor reaches ~77-80% today and will approach Apple's ~86% four-year figure for 27 by mid-2027 if the iOS 26 curve repeats; an 18 floor adds at most the ~10% "18.7" bucket, part of which is misreported iOS 26, plus the 2018 A12 phones. The founder's own cohorts are **unknown** here: App Store Connect > Analytics > Metrics (filter by iOS version and device) answers it in minutes, and his existing apps already use Vision OCR so the cohort is probably recent-iPhone-skewed.

API consequences of each floor (from `apple.md` and the fetches above):

| Capability | 17 | 18 | 26 | 27 |
|---|---|---|---|---|
| Vision Swift API (`RecognizeTextRequest`, `DetectDocumentSegmentationRequest`, `GenerateImageFeaturePrintRequest`, `BarcodeSymbology`) | VN* classes only | yes | yes | yes |
| `RecognizeDocumentsRequest` (tables, lists, data detectors) | no | no | yes | yes |
| `DetectLensSmudgeRequest` | no | no | yes (A14+) | yes |
| `NLContextualEmbedding` / Create ML BERT transfer learning | yes | yes | yes | yes |
| Foundation Models text, `@Generable`, `contentTagging`, `prewarm` | no | no | yes (A17 Pro+) | yes |
| Foundation Models image `Attachment`, `OCRTool`, `BarcodeReaderTool`, `LanguageModelError`, PCC model | no | no | no | yes |
| Core AI, `LanguageModel` protocol (Anthropic Swift package) | no | no | no | yes |
| `BGContinuedProcessingTask` | no | no | yes | yes |
| ZSL / responsive capture | yes | yes | yes | yes |

## 3. Options compared

| Option | Floor device OK? | Latency after OCR | Accuracy on 26-33 classes | Labels needed | Sensitive-class gate? | Verdict |
|---|---|---|---|---|---|---|
| A. Rules/regex over `.fast` text | yes (any) | <5 ms (computed) | high precision on tax/ID/medical cues, low coverage elsewhere | 0 | yes, recall-biased | ship in v1 as the floor and as the OR-gate |
| B. Sender memory (header feature print + sender kNN over Claude labels) | yes (iOS 18+) | ~5-25 ms (estimate) | very high for repeat senders, none for first contact | 1 per sender | partial (inherits the sender's class) | ship in v1; biggest practical win for real mail |
| C. Create ML `maxEnt` text classifier | yes (iOS 12 runtime) | ~1 ms (estimate) | ~80% once ~50/class (estimate) | 1-3k pages | yes (posterior threshold) | ship as soon as labels exist; trivially cheap |
| D. Create ML BERT transfer learning | yes (iOS 17+) | 10-80 ms (estimate; 3.47 ms DistilBERT@128 on A15 measured) | ~85-90% at ~100/class (estimate; BERT 89.8% on 16-class RVL-CDIP measured) | 2-3k pages | yes | replace C when it measurably beats it |
| E. Foundation Models text `@Generable` enum, trimmed prompt | **no** (A17 Pro+, AI enabled, 16 languages) | ~0.25-0.5 s on A17 Pro (computed from 0.6 ms/token, 30 tok/s) | unknown; zero-shot | 0 | **no** (guardrails always on for guided generation) | optional second opinion on eligible devices only |
| F. Foundation Models image attachment (iOS 27) | no | unknown | unknown | 0 | no | measure in 2027; not v1 |
| G. Foundation Models adapter | no | as E | unknown | 5k+ | no | reject: 160 MB x OS versions, entitlement, toolkit not yet 27-compatible |
| H. Custom distilled encoder via Core ML (26) / Core AI (27) | yes | ~10-50 ms (estimate) | best achievable text-only | 3k+ plus engineering | yes | v2/v3 once D plateaus |

## 4. Recommendation for this project

1. **Deployment target iOS 26.0.** Same hardware as 27, ~80% of iPhones today, and it is the floor for `RecognizeDocumentsRequest`, `DetectLensSmudgeRequest`, `BGContinuedProcessingTask` and Foundation Models text. Gate iOS 27 features behind `#available(iOS 27)`. Re-evaluate raising the floor to 27 when Apple's measurement page shows 27 above ~80%, likely mid-2027.
2. **Provisional label on every device in <100 ms after `.fast` OCR**, with this precedence: rule hit > sender-memory match (feature-print distance below a calibrated threshold AND sender string match) > Create ML classifier posterior > "Document" (no label). Show it in the provisional style the UI already plans; replace it with Claude's `doc_type` (first property in the streamed schema per `claude.md`) and log every disagreement.
3. **Sensitivity gate = rules OR classifier posterior > 0.3 on the sensitive classes**, computed before the Claude call, never from Foundation Models. Pages flagged sensitive go text-only to Claude per `privacy.md`; the rest go masked-image + placeholder text.
4. **Foundation Models only as an opt-in experiment on A17 Pro+**: `SystemLanguageModel(useCase: .contentTagging)`, `prewarm(promptPrefix:)` with the fixed instructions+taxonomy at camera start, a 250-300-token prompt (title lines, first paragraph, data-detector hits), `@Generable` enum output, `GenerationOptions(sampling: .greedy)`. Instrument TTFT/tokens-per-second with the Foundation Models instrument before deciding whether it ever ships. Expect `guardrailViolation` on some medical/legal pages and treat it as "no opinion".
5. **Distillation pipeline from day one**: persist the training row described in 2f for every page; start with the founder's own mail; train the Create ML classifier on a Mac once any class has ~50 labels; promote per class. Keep on-device Create ML retraining (iOS 15+) as the v2 privacy-preserving personalisation path. Skip Apple adapters entirely; keep Core AI/`LanguageModel` protocol in view for a v3 custom encoder.
6. **Do not expect cost savings from distillation**; expect latency and offline capability. The lever that does cut Claude cost is skipping the call for marketing/junk once the classifier is confident, which is also what the user wants (junk should not be "understood" at length, only archived and tagged).

## 5. Risks and unknowns

- No published latency for Foundation Models on the 2025/2026 models on any chip; the 0.6 ms/token and 30 tok/s figures are 2024, iPhone 15 Pro, pre-speculative-decoding. Everything in 2a's Foundation Models rows is computed from them.
- Create ML BERT-embedding inference latency on iPhone is unpublished; the DistilBERT-on-ANE figure is a different model. `NLContextualEmbedding.maximumSequenceLength` is a runtime property, value not documented, so truncation strategy is unverified.
- Feature-print distance thresholds for "same letterhead" are not published by Apple (already flagged in `dedup.md`); a bad threshold mislabels a new sender as a known one.
- `.fast` OCR quality on dense pages is poor at 1080p (text_sight); the provisional label may need the 2-3 MP rectified crop, which pushes floor-device OCR to 300-600 ms (`gap-3`), so the label lands around 0.5-0.7 s on iPhone 13 rather than 0.3 s.
- StatCounter is web-traffic share, not installed base, and its 18.7 bucket is contaminated by Safari anti-fingerprinting misreporting; Apple's June 2026 number predates iOS 27.
- Foundation Models guardrail false-positive rates on medical/legal documents are unpublished; iOS 27 adds `LanguageModelError` with distinct `refusal` and `guardrailViolation` cases, iOS 26 uses the deprecated `GenerationError` names.
- The adapter toolkit 26.0.0 is explicitly not 27-compatible; whether a 27 toolkit exists is unknown from the fetched page.
- Taxonomy size mismatch: brief says 26 classes, `claude.md` enum has 33 values; class count directly changes the labels-needed arithmetic.
- The marketing/junk share of the founder's mail (which drives the only real cost saving) is unmeasured.

## 6. Open questions for the founder

1. What do App Store Connect analytics for your shipped apps show for iOS 18 vs 26 vs 27 and for A12/A13-A16/A17 Pro+ devices? This decides 26 vs 27 and whether Foundation Models reaches a meaningful share of your users.
2. Is a provisional label from rules/sender-memory (sometimes just "Document") acceptable in the sub-second feedback, with the Claude label arriving ~3-4 s later?
3. Confirm the taxonomy size (26 vs the 33-value enum in `claude.md`) and which classes are "sensitive" for text-only routing: tax_form, tax_notice, medical_record, medical_bill, prescription, id_document; also insurance_claim and court_document?
4. May pages be exported (text-only, placeholders for identifiers) to your Mac for Create ML training, or must all training stay on device?
5. Should marketing/junk skip the Claude call entirely once the on-device classifier is confident, and what is the share of such mail in your own inbox (measure over a week)?
6. English only for v1? Create ML BERT embeddings cover 27 languages via three script models; Foundation Models 16; rules are per language.
7. Do you want to spend effort on the Foundation Models experiment at all in v1, given it is unavailable on the floor device and cannot be the sensitivity gate?

## 7. Sources

- Apple App Store measurement (iOS 26 adoption, 2026-06-07): https://developer.apple.com/support/app-store/
- StatCounter iOS version share, US and worldwide, October 2026: https://gs.statcounter.com/ios-version-market-share/mobile-tablet/united-states-of-america ; https://gs.statcounter.com/ios-version-market-share/mobile-tablet/worldwide
- iOS 27 / 26 / 18 device support: https://en.wikipedia.org/wiki/IOS_27 ; https://en.wikipedia.org/wiki/IOS_26 ; https://en.wikipedia.org/wiki/IOS_18
- Apple Intelligence devices and languages: https://support.apple.com/en-us/121115
- Apple on-device foundation model 2024 (0.6 ms/token, 30 tok/s, iPhone 15 Pro): https://machinelearning.apple.com/research/introducing-apple-foundation-models
- Apple foundation models 2025 update (2-bit QAT, KV-cache sharing, rank-32 adapters): https://machinelearning.apple.com/research/apple-foundation-models-2025-updates ; tech report https://arxiv.org/html/2507.13575
- Foundation Models adapter training (100-1,000 / 5,000+ samples, 160 MB, entitlement, toolkit 26.0.0 not 27-compatible): https://developer.apple.com/apple-intelligence/foundation-models-adapter/
- `prewarm(promptPrefix:)`: https://developer.apple.com/documentation/foundationmodels/languagemodelsession/prewarm(promptprefix:) ; KV caching article: https://developer.apple.com/documentation/foundationmodels/optimizing-key-value-caching-in-language-model-sessions
- Guardrails and `permissiveContentTransformations`: https://developer.apple.com/documentation/foundationmodels/improving-the-safety-of-generative-model-output ; https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel/guardrails
- `LanguageModelError` (iOS 27): https://developer.apple.com/documentation/foundationmodels/languagemodelerror ; `UnavailableReason`: https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel/availability-swift.enum/unavailablereason ; `UseCase`: https://developer.apple.com/documentation/foundationmodels/systemlanguagemodel/usecase ; languages: https://developer.apple.com/documentation/foundationmodels/supporting-languages-and-locales-with-foundation-models
- `Attachment` (iOS 27): https://developer.apple.com/documentation/foundationmodels/attachment ; multimodal article: https://developer.apple.com/documentation/foundationmodels/analyzing-images-with-multimodal-prompting ; `OCRTool` (iOS 27, no Simulator): https://developer.apple.com/documentation/vision/ocrtool
- WWDC26 241 What's new in Foundation Models: https://nonstrict.eu/wwdcindex/wwdc2026/241/ ; 243 Instruments: https://nonstrict.eu/wwdcindex/wwdc2026/243/ ; 237 image understanding: https://nonstrict.eu/wwdcindex/wwdc2026/237/ ; 324 Meet Core AI: https://nonstrict.eu/wwdcindex/wwdc2026/324/ ; Core AI docs: https://developer.apple.com/documentation/coreai
- WWDC25 286 Meet Foundation Models: https://nonstrict.eu/wwdcindex/wwdc2025/286/ ; 301 deep dive: https://nonstrict.eu/wwdcindex/wwdc2025/301/
- Create ML text classifier: https://developer.apple.com/documentation/createml/mltextclassifier ; algorithms: https://developer.apple.com/documentation/createml/mltextclassifier/modelalgorithmtype ; feature extractors: https://developer.apple.com/documentation/createml/mltextclassifier/featureextractortype ; article: https://developer.apple.com/documentation/createml/creating-a-text-classifier-model ; `NLModel`: https://developer.apple.com/documentation/naturallanguage/nlmodel ; `NLContextualEmbedding` (iOS 17): https://developer.apple.com/documentation/naturallanguage/nlcontextualembedding
- WWDC23 10042 Natural Language multilingual (BERT embeddings, 27 languages): https://nonstrict.eu/wwdcindex/wwdc2023/10042/ ; WWDC21 10037 Create ML on iOS: https://nonstrict.eu/wwdcindex/wwdc2021/10037/
- DistilBERT on Apple Neural Engine (3.47 ms, iPhone 13): https://machinelearning.apple.com/research/neural-engine-transformers
- LayoutLM RVL-CDIP table: https://arxiv.org/pdf/1912.13318 ; Audebert et al. 2019 (Tesseract text-only 74.6%): https://arxiv.org/pdf/1907.06370 ; RVL-CDIP: https://adamharley.com/rvl-cdip/ ; SetFit: https://arxiv.org/pdf/2209.11055
- Vision `BarcodeSymbology` (pdf417, iOS 18): https://developer.apple.com/documentation/vision/barcodesymbology ; feature print: https://developer.apple.com/documentation/vision/generateimagefeatureprintrequest
- IRS Form W-2 (OMB No. 1545-0029): https://www.irs.gov/pub/irs-pdf/fw2.pdf
- text_sight Vision OCR measurements: https://github.com/LahaLuhem/text_sight/blob/main/doc/performance.md
