# OCR and document-understanding model landscape (speed-first) — research report

Dimension: OCR / document-understanding models for mobile-captured paper, optimized for speed first and accuracy second.
Date of research: 2026-11-03. Sources are 2025-2026 unless flagged. "Measured" means a number from a benchmark run or a third-party measurement; "vendor" means a vendor's own claim.

---

## 1. Executive summary

1. There is no single model that is both sub-second on a phone and archival-grade. The right design is tiered: Apple Vision on-device for instant feedback, Claude in the cloud for understanding, and a bounded-box OCR source (Vision itself, or a specialist OCR model) for the searchable PDF text layer.
2. Apple `RecognizeTextRequest` (iOS 18+) is the only option with measured sub-second per-page latency on an iPhone: `.fast` keeps up with a 30 fps camera, `.accurate` runs ~4 frames/s at 1080x1920 on an iPhone 16 (third-party measurement; ~250 ms/page). Apple publishes no numbers.
3. iOS 26 `RecognizeDocumentsRequest` adds paragraphs, tables, lists, barcodes and data detectors (phones, emails, addresses, dates, amounts, tracking numbers) in 26 languages, on-device. No latency figures exist anywhere; must be measured.
4. Apple Foundation Models accepts images only from iOS 27 (`Capability.vision`, iOS 27.0+). On iOS 26 it is text-only. Apple gives no image latency numbers. Treat on-device VLM classification in <500 ms as unproven.
5. Claude Haiku 5.5 is the cheapest frontier vision model for understanding: a 2000x1500 phone photo costs 3,888 visual tokens, roughly $0.0004 input, so about $1 per 1,000 pages all-in at `effort: low`. Claude's weakness is text localization (no OCR word boxes), not transcription (93-95% on Roboflow's OCR transcription sub-score; Opus 5.5 scores 94.5 on text in Datalab's OmniParseBench, above Gemini 3.8 Flash and Mistral OCR).
6. On real camera photos, every model loses accuracy: 7-20 points on Wild-OmniDocBench. End-to-end VLM OCR models lose least; modular pipelines (PaddleOCR-VL 0.9B, MinerU) lose ~20 points.
7. Best open OCR models on clean pages (OmniDocBench v1.6): OXR-1.0 97.03, TeleOCR 96.91, OvisOCR2 96.47, PaddleOCR-VL-1.6 96.34 (Apache 2.0), GLM-OCR 95.22 (MIT). All run ~1-2 pages/s per A100/H100 batched; single-page warm latency is 1-7 s, not sub-second.
8. Cloud OCR APIs: Mistral OCR 4 $4/1k pages (batch $2) with bounding boxes and per-word confidence; Google/AWS/Azure plain OCR $1.50/1k pages; Datalab $4-10/1k pages, median 4.8-6.7 s/page.
9. Recommendation: Vision (fast) per frame -> Vision (accurate / Documents) per capture with duplicate detection and immediate durable local save -> Claude Haiku 5.5 `low` for classification/extraction/tags -> Sonnet 5.5 escalation on hard pages -> Vision word boxes for the PDF text layer, with Mistral OCR 4 or self-hosted PaddleOCR-VL-1.6 as an optional high-fidelity fallback.
10. Biggest unknowns: measured iOS 26/27 on-device latencies, Claude time-to-first-token on a ~4k-token image prompt at `effort: low`, and Claude accuracy on handheld photos specifically (no public benchmark includes Claude 5.5 on camera-captured pages).

---

## 2. Findings

### 2a. Apple on-device (Vision framework, Foundation Models)

**RecognizeTextRequest (Swift API, iOS 18.0+; the ObjC `VNRecognizeTextRequest` goes back to iOS 13).** Returns `RecognizedTextObservation` with bounding boxes. Options: `recognitionLevel` (`.fast` / `.accurate`), `automaticallyDetectsLanguage`, `usesLanguageCorrection`, `customWords`, `minimumTextHeightFraction`, `recognitionLanguages`, revisions. Apple describes the levels only qualitatively. Source: https://developer.apple.com/documentation/vision/recognizetextrequest

- Measured (third-party, text_sight Flutter plugin, iPhone 16, live camera at 1080x1920): `.fast` 30 captures/s (camera-bound), `.accurate` 4.0 captures/s (~250 ms per frame). Author states `.fast` is roughly 4x quicker than `.accurate` one-shot, but that run had a Vision setting skipping small text (<1/32 of image height), so `.fast` numbers overstate throughput on dense pages; charts flagged for recapture. Source: https://pub.dev/documentation/text_sight/0.2.2/ and https://pub.dev/packages/text_sight/versions/0.2.1
- Accuracy: no rigorous published CER/WER for Apple Vision on document photos. Anecdotal reports consistently rank it above Tesseract on Mac/iOS (e.g. https://news.ycombinator.com/item?id=43044474, https://bitbucket.org/galad87/subler/issues/676). Treat as unmeasured.

**RecognizeDocumentsRequest (iOS 26.0+, macOS 26.0+, visionOS 26.0+).** One `DocumentObservation` per image. Document is a container of text, tables, lists, barcodes. Text exposes transcript, lines, paragraphs, words (no word splitting for Chinese/Japanese/Korean/Thai) and `detectedData` via the new DataDetection framework: phone numbers, emails, postal addresses, URLs, dates/times, measurements, currency amounts, tracking numbers, payment identifiers, flight numbers. Tables are 2D cell arrays with row/column ranges (spanning cells). 26 languages. Sources: https://developer.apple.com/documentation/vision/recognizedocumentsrequest.md and WWDC25 session 272 transcript https://developer.apple.com/videos/play/wwdc2025/272/

- Latency: unknown. No Apple figure, no developer forum measurement found. One forum post notes PDFKit on iPadOS 26 runs `VNRecognizeDocumentsRequest` on rendered pages with noticeable thread/memory cost (secondary, not a per-page time). Source: https://developer.apple.com/forums/tags/vision
- Implication: it replaces the "RecognizeTextRequest + geometric row reconstruction" code path and gives free entity extraction for the instant-feedback tier.

**Live Text / DataScannerViewController**: same recognizer under the hood; useful for interactive UIs but not for headless capture. Not benchmarked separately.

**Foundation Models framework.**
- iOS 26: text-only on-device ~3B model (Apple 2025 tech report, https://arxiv.org/pdf/2507.13575). No image input; confirmed by Apple forum threads from Sept 2025. Useful for text classification of OCR output, not for image understanding.
- iOS 27: `LanguageModelCapabilities.Capability.vision` ("The capability to accept image inputs in prompts"), availability iOS 27.0+, macOS 27.0+, visionOS 27.0+, watchOS 27.0+. Source: https://developer.apple.com/documentation/foundationmodels/languagemodelcapabilities/capability/vision.md
- WWDC26 session 241: `Attachment(UIImage(...))` in the prompt builder; accepts UIImage, NSImage, CGImage, Core Image, CVPixelBuffer, file URLs; any size and aspect ratio, "larger images will consume more tokens and incur more latency"; on-device `contextSize` printed as 8192 in the example; Private Cloud Compute model has 32k context and `reasoningLevel`. Two system tools backed by Vision: `OCRTool` and `BarcodeReaderTool`. Source: https://developer.apple.com/videos/play/wwdc2026/241/ (also Apple iOS "What's new": https://developer.apple.com/ios/whats-new/)
- Latency / tokens per image: not published. A secondary blog claims ~30 tokens/s text generation on iPhone 15 Pro (unverified, text-only). Whether a document can be classified from pixels in <500 ms on-device is unknown.

### 2b. Other on-device OCR engines

| Engine | Platform | Scripts | Measured speed | Notes / source |
|---|---|---|---|---|
| ML Kit Text Recognition v2 | Android, iOS | Latin, Chinese, Devanagari, Japanese, Korean | Galaxy S24, 480x640: 5.9-6.6 fps (text_sight) | Blocks/lines/elements/symbols with boxes + confidence; no fast/accurate setting; Latin model ~260 KB downloaded from Play Services. https://developers.google.com/ml-kit/vision/text-recognition/v2 |
| Tesseract 5 | any | 100+ | no phone numbers | Needs binarization/preprocessing; anecdotal ~70% on ideal photo, ~30% with poor lighting; consistently behind ML Kit/Vision in 959-image Fritz test. https://heartbeat.comet.ml/comparing-on-device-text-recognition-ocr-sdks-24f8a0423461 |
| PaddleOCR PP-OCRv5 mobile | server/edge via Paddle Lite | multi | CPU 4-core desktop: 0.45-1.75 s/image; no phone numbers | ~5M params. https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html |
| PP-OCRv6 (June 2026) | same | multi | tiny tier 3.9x faster than v5 mobile on Xeon CPU | 1.5M-34.5M params; medium tier 83.2% recognition accuracy on in-house set, claimed above Qwen3-VL-235B/GPT-5.5/Gemini-3.1-Pro (vendor). https://arxiv.org/abs/2606.13108 |

Conclusion: on iOS, Apple Vision is the only engine with a zero-integration-cost, Neural-Engine-accelerated path and measured sub-second latency. PaddleOCR mobile is the credible choice if an Android port needs parity with Vision quality; ML Kit is the quick Android option.

### 2c. VLM OCR via API (Claude, Gemini, OpenAI, Mistral)

**Pricing (per 1M tokens, standard tier, verified on vendor pages 2026-11-03):**

| Model | Input | Output | Batch | Source |
|---|---|---|---|---|
| Claude Haiku 5.5 (prompt <=100k tok) | $0.10 | $0.50 | 50% off | https://platform.claude.com/docs/en/about-claude/pricing |
| Claude Sonnet 5.5 | $2.00 | $10.00 | 50% off | same |
| Claude Opus 5.5 | $4.00 | $20.00 | 50% off | same |
| Gemini 2.5 Flash-Lite | $0.10 | $0.40 | $0.05/$0.20 | https://aistudio.google.com/docs/pricing |
| Gemini 3.1 Flash-Lite | $0.25 | $1.50 | $0.125/$0.75 | same |
| Gemini 3.5 Flash-Lite | $0.30 | $2.50 | $0.15/$1.25 | same |
| Gemini 3.8 Flash | $0.75 (doubles to $1.50 on 2027-01-01) | $3.75 (to $7.50) | half | same |
| GPT-6 Luna | $0.10 | $0.50 | $0.05/$0.25 | https://developers.openai.com/api/docs/pricing |
| GPT-5.4 nano / GPT-5 nano | $0.20 / $0.05 | $1.25 / $0.40 | half | same |
| GPT-5.4 mini | $0.75 | $4.50 | half | same |
| Mistral OCR 4 (per 1k pages) | $4 ($2 batch); Document AI $5 | - | 50% | https://mistral.ai/news/ocr-4 |
| Mistral OCR 3 (per 1k pages, Dec 2025) | $2 ($1 batch); annotations $3 | - | 50% | https://mistral.ai/news/mistral-ocr-3 |

**Claude image token cost (vendor docs):** `ceil(w/28) x ceil(h/28)` visual tokens. Claude 4.7 and later (incl. Haiku/Sonnet/Opus 5.5) use the high-resolution tier: max long edge 2,576 px, max 4,784 visual tokens. A 2000x1500 photo is not resized and costs 3,888 tokens; a 3840x2160 photo is downscaled to 2576x1449 and costs 4,784. Max 10 MB per image; 600 images per request. Source: https://platform.claude.com/docs/en/build-with-claude/vision

Derived per-page cost (3,888 input + ~800 output tokens): Haiku 5.5 ~$0.0008/page (~$0.80 per 1k pages); Sonnet 5.5 ~$0.016/page; Opus 5.5 ~$0.032/page. Batch halves these. Images should be sent before text; pre-resizing reduces latency (vendor guidance, same page).

**Accuracy on documents (measured by third parties):**
- Datalab OmniParseBench (2,937 pages, 92 languages, run 2026-10-27, vendor-run): Datalab accurate 94.1, Gemini 3.8 Flash 92.7, Datalab balanced 92.6, GPT-6.1 Sol 91.4, Reducto 90.8, **Claude Opus 5.5 90.7 (text 94.5, tables 97.2, layout 84.3)**, LlamaParse 90.4, Mistral OCR 89.5, **Claude Sonnet 5.5 88.7 (text 93.3, tables 96.1, layout 77.5)**, GPT-5.6 Sol 87.7. Claude's text and table sub-scores are the highest in the table; its layout score drags the overall. Source: https://www.datalab.to/blog/chandra-2-6
- Roboflow Vision Evals, Claude Haiku 5.5: OCR composite 61.2% (low effort) / 65.3% (high), rank #28/49; sub-scores transcription 93.0/94.7%, structured JSON 82.2/85.3%, text localization 32.0/45.8%; overall vision 69.6%, avg 11.0 s per sample on their harness; OCR result flagged as a single preliminary run. Source: https://playground.roboflow.com/models/anthropic/claude-haiku-5-5
- OmniDocBench v1.6 (official leaderboard, general VLMs): Gemini 3 Pro 92.91, Gemini 3 Flash 92.62, Qwen3-VL-235B 89.78, GPT-5.2 86.59. Claude not listed. Source: https://github.com/opendatalab/OmniDocBench
- olmOCR-bench (Ai2 harness, older entries): Mistral OCR API 72.0, GPT-4o 69.9, Gemini Flash 2 63.8, Qwen3-VL-8B 64.6. Mistral OCR 4 self-reports 85.20. Sources: https://github.com/allenai/olmocr, https://mistral.ai/news/ocr-4

**Latency (measured, Artificial Analysis, 10k-token text prompts; these include thinking time and are not representative of a 4k-token image prompt):**
- Claude Haiku 5.5 (low): TTFT 8.95 s, 167 tok/s, 12.0 s for 500 output tokens. https://artificialanalysis.ai/models/claude-haiku-5-5-low/providers
- Gemini 3.5 Flash-Lite: TTFT 6.4 s, 441 tok/s, 7.95 s e2e. https://artificialanalysis.ai/models/gemini-3-5-flash-lite/providers
- Gemini 3.8 Flash (high): TTFT 25.3 s. https://artificialanalysis.ai/models/gemini-3-8-flash/providers
- GPT-6 Luna (non-reasoning): TTFT 0.81 s; 117-129 tok/s. https://artificialanalysis.ai/models/releases/gpt-6-luna
- Anthropic's latency guidance: Haiku 5.5 at `output_config.effort: "low"` is the fastest configuration; stream; trim output. https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency. Haiku 5.5 supports `thinking: {type: "disabled"}` at effort high or below (https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5). Haiku 5.5 has no server-side refusal fallback; clients must handle `stop_reason: "refusal"`.

**Mistral OCR 4** (released 2026-06-23, `mistral-ocr-latest`; OCR 4.1 preview 2026-07-16): $4/1k pages, $2 batch, Document AI $5; olmOCR-bench 85.20 and OmniDocBench 93.07 (vendor); 72% average human-preference win rate (vendor, competitors unnamed); 170 languages; returns bounding boxes, typed blocks and per-page/per-word confidence; single-container self-hosting for enterprise. No absolute latency published; customer quotes "17x lower latency" vs unnamed incumbent. Source: https://mistral.ai/news/ocr-4. OCR 3 (`mistral-ocr-2512`) was $2/1k and claimed robustness to skew, distortion, low DPI; measured 72.0 on olmOCR-bench by Ai2 and 85.66 on OmniDocBench v1.6. Sources: https://mistral.ai/news/mistral-ocr-3, https://github.com/opendatalab/OmniDocBench

**Handwriting**: no independent handwriting benchmark exists for any of these. Mistral's 88.9% handwriting figure circulating in reviews is from internal data and not on Mistral's page (flagged unverified). Chandra claims "excellent handwriting support" without numbers.

### 2d. Specialized open OCR / document models (2025-2026)

**OmniDocBench v1.6 (official leaderboard, github.com/opendatalab/OmniDocBench, last updated 2026-09-11; many rows self-reported by model authors):**

| Model | Params | Overall | License (where known) |
|---|---|---|---|
| OXR-1.0 | - | 97.03 | unknown |
| TeleOCR | 1.2B | 96.91 | unknown (paper Aug 2026) |
| OvisOCR2 | 0.8B | 96.47 | unknown |
| PaddleOCR-VL-1.6 (2026-05-28) | 0.9B | 96.34 (card says 96.33) | Apache 2.0 |
| MinerU2.5-Pro | 1.2B | 95.75 | MinerU license (contested) |
| GLM-OCR | 0.9B | 95.22 | MIT (layout Apache 2.0) |
| PaddleOCR-VL-1.5 | 0.9B | 94.93 | Apache 2.0 |
| Ovis2.6-30B-A3B (general) | 30B | 93.70 | - |
| Gemini 3 Pro / 3 Flash | - | 92.91 / 92.62 | API |
| dots.ocr | 3B | 90.77 | MIT |
| DeepSeek-OCR 2 | 3B | 90.25 | Apache 2.0 |
| Qwen3-VL-235B | 235B | 89.78 | Apache 2.0 |
| GPT-5.2 | - | 86.59 | API |
| MinerU-Pipeline | - | 86.47 | - |
| olmOCR | 7B | 85.74 | Apache 2.0 |
| Mistral OCR (3-era) | - | 85.66 | API |
| Nanonets-OCR-s | 3B | 83.61 | - |
| Marker (pipeline) | - | 78.44 | - |

**olmOCR-bench (Ai2 harness; PDF-centric, 7 hard categories):** Datalab API 86.7, Chandra 2 85.8 (5B, OpenRAIL-M: free under $2M revenue/funding, commercial license otherwise), Mistral OCR 4 85.20 (vendor), dots.ocr 1.5 83.9, Chandra 1 83.1, Infinity-Parser 7B 82.5, olmOCR 2 82.4, PaddleOCR-VL 80.0, dots.ocr 79.1, Marker 1.10 76.1-76.5, DeepSeek-OCR 2 76.3, LightOnOCR-1B 76.1, DeepSeek-OCR 75.4-75.7, MinerU 2.5.4 75.2, Nanonets-OCR2-3B 69.5. Sources: https://github.com/allenai/olmocr, https://github.com/datalab-to/chandra, https://huggingface.co/deepseek-ai/DeepSeek-OCR-2, https://huggingface.co/blog/lightonai/lightonocr

**Speed on GPU (measured):**

| Model | Hardware / setup | Throughput | Single-page latency | Source |
|---|---|---|---|---|
| PaddleOCR-VL-1.5 | A100, batch 512, FastDeploy / vLLM | 1.43 / 1.14 pages/s | not reported | https://arxiv.org/html/2601.21957 |
| MinerU2.5 | A100, vLLM | 1.00 pages/s | - | same |
| DeepSeek-OCR | A100, vLLM | 0.64 pages/s | - | same (vendor claims 200k pages/day/A100; https://www.notebookcheck.net/DeepSeek-OCR-AI-model-can-process-200-000-document-pages-a-day-on-a-single-Nvidia-A100-GPU.1144400.0.html) |
| dots.ocr | A100, vLLM | 0.28 pages/s | - | same |
| LightOnOCR-1B | H100, vLLM | 5.71 pages/s (vendor) | - | https://huggingface.co/blog/lightonai/lightonocr |
| GLM-OCR | single replica, concurrency 1 | 1.86 pages/s (PDF), 0.67 images/s | ~1.5 s/image | https://huggingface.co/unsloth/GLM-OCR/blob/main/README.md |
| Chandra 2 | H100, vLLM, 96 concurrent | 1.44 pages/s | 60 s avg, 156 s p95 at that concurrency | https://huggingface.co/datalab-to/chandra-ocr-2 |
| Datalab API (Chandra 2.6) | hosted | - | median 4.8 s balanced / 4.9 s accurate (production); 6.7 s on fixed hard set | https://www.datalab.to/blog/chandra-2-6 |
| Marker 2 / MinerU pipeline / Docling | B200 | 2.9 / 0.54 / 2.1 pages/s at 76.0 / 72.7 / 50.3 olmOCR-bench (vendor-run) | - | https://www.marktechpost.com/2026/07/24/datalab-marker-v2-vs-mineru-docling-and-liteparse-benchmark-breakdown/ |

Other models in the brief: Florence-2 and GOT-OCR 2 (~580M) are 2024-era and are not on current leaderboards (stale). Qwen3-VL-8B scores 64.6 on olmOCR-bench (Datalab run); Qwen3-VL-235B 89.78 on OmniDocBench. Surya is Datalab's older OCR engine ($4-6/1k pages on Replicate). MinerU has a competent VLM backend (MinerU2.5-Pro 95.75) but a contested license.

**Serverless hosting cost (vendor pricing pages):** Modal H100 $0.001097/s (~$3.95/h), A100-80GB $0.000694/s, L40S $0.000542/s, L4 $0.000222/s, T4 $0.000164/s, $30/month free (https://modal.com/pricing). RunPod serverless H100 $5.39/h, A100 $2.72/h, L40S $1.75/h, L4 $0.75/h; on-demand pods H100 SXM $2.69-3.99/h, L4 $0.59/h (https://www.runpod.io/pricing). Derived compute cost at batched throughput: PaddleOCR-VL-1.5 on A100 ~ $0.61 per 1k pages; LightOnOCR on H100 ~ $0.19 per 1k pages. Cold starts: Modal ~5 s with memory snapshots, Replicate 60 s+ (secondary sources: https://blog.premai.io/serverless-llm-deployment-runpod-vs-modal-vs-lambda-2026). A warm, always-on L4/L40S replica is required for sub-5-second user-facing latency; that is $0.59-1.95/h regardless of volume.

### 2e. Cloud document AI (Google, AWS, Azure)

| Service | Plain OCR | Layout / structure | Forms / custom | Free tier | Source |
|---|---|---|---|---|---|
| Google Document AI | Enterprise Document OCR $1.50/1k pages (first 5M/month), $0.60 after | Layout Parser $10/1k | Form Parser / Custom Extractor $30/1k (1-1M), $20 after | not confirmed | https://cloud.google.com/document-ai/pricing (page content not machine-readable; figures via search summary and https://erpresearch.com/erp-add-ons/ocr/google-document-ai/pricing) |
| AWS Textract (US West) | Detect Document Text $1.50/1k (first 1M), $0.60 after | Tables $15/1k; Layout free with Tables | Forms $50/1k; Forms+Tables+Queries $70/1k; Expense $10/1k | 1,000 pages/month for 3 months | https://aws.amazon.com/textract/pricing/ |
| Azure Document Intelligence | Read $1.50/1k (<=1M), $0.60 after | Layout $10/1k | Prebuilt $10/1k; custom extraction $30/1k | 500 pages/month (F0) | https://azure.microsoft.com/en-us/pricing/details/ai-document-intelligence/ (prices rendered as placeholders; numbers from https://superdupr.com/blog/azure-document-intelligence-pricing checked 2026-10-24) |

Latency: none of the three publishes per-page latency. Accuracy: none appears on OmniDocBench/olmOCR-bench; Azure's 78.2% handwriting figure quoted in Mistral reviews is unverified. These services return word-level bounding boxes and confidence, which matters for PDF text layers, but they offer no semantic understanding; Claude would still be needed.

### 2f. On-device small VLMs

| Model | Size | Runs on iPhone? | Measured latency | Source |
|---|---|---|---|---|
| Apple FastVLM | 0.5B / 1.5B / 7B | yes, demo app iOS 18.2+, MLX export, shown on iPhone 16 Pro | relative only: 85x faster TTFT than LLaVA-OneVision-0.5B, 5.2x faster than SmolVLM (~0.5B); no absolute ms published (the "31.7 ms" blog figure is unverified) | https://github.com/apple/ml-fastvlm, https://machinelearning.apple.com/research/fast-vision-language-models |
| Apple Foundation Models (iOS 27) | ~3B | yes, system model | unknown; "larger images -> more tokens -> more latency" | https://developer.apple.com/videos/play/wwdc2026/241/ |
| SmolVLM2-500M | 0.5B | MLX/Swift examples exist | no primary iPhone number (unverified 54 tok/s on A18 Pro) | https://arxiv.org/pdf/2504.05299 |
| Moondream 3 Preview | 9B MoE, 2B active | cloud listing; 0.5B edge distillation exists | no mobile numbers | https://openrouter.ai/moondream/moondream3-preview |
| Gemini Nano via ML Kit GenAI | - | Android only (AICore); no iOS path | - | https://android-developers.googleblog.com/2025/10/ml-kit-genai-prompt-api-alpha-release.html |

Verdict: no public measurement shows a VLM classifying a document image in under 500 ms on a phone. FastVLM-0.5B is the most plausible candidate (vision encoder designed for low TTFT at high resolution), but the useful signal for classification (letterhead, form codes, totals) is in the text, which Vision already extracts in ~250 ms. An on-device text classifier over Vision output (Foundation Models text on iOS 26, or a Core ML text classifier) is the lower-risk path for sub-second classification; iOS 27 image prompting should be measured, not assumed.

### 2g. Benchmarks and camera-photo robustness

- **Wild-OmniDocBench** (1,350 JPGs derived from OmniDocBench v1.5 with perspective shifts, bends, wrinkles, uneven/low light, moire, reflections, shadows). Clean -> Wild: DocHumming-1B 93.75 -> 87.03 (-6.7), Qwen3-VL-235B 89.15 -> 79.69 (-9.5), dots.ocr 88.41 -> 78.01 (-10.4), PaddleOCR-VL 0.9B 91.93 -> 72.19 (-19.7), MinerU2.5 90.67 -> 70.91 (-19.8). "End-to-end models exhibit significantly less degradation than modular cascaded pipelines." TeleOCR 88.53, OvisOCR2 87.91, PaddleOCR-VL-1.6 87.36 on Wild (paper-reported). Sources: https://github.com/VirtualLUOUCAS/Wild_OmniDocBench, https://arxiv.org/abs/2608.12898
- **Real5-OmniDocBench** (PaddleOCR-VL-1.5 paper; scanning, warping, screen-photo, illumination, skew): PaddleOCR-VL-1.5 92.05 (clean 94.50), Gemini-3 Pro 89.24, Qwen3-VL-235B 88.90, Gemini-2.5 Pro 88.21, dots.ocr 86.38, MinerU2.5 85.61, Nanonets-OCR-s 84.19, GPT-5.2 78.66, DeepSeek-OCR 73.99, Marker 60.10. Skew is the hardest axis for pipelines (Marker 41.3, PP-StructureV3 38.0). Source: https://arxiv.org/html/2601.21957
- **olmOCR-bench** is PDF-rendered, so it under-represents handheld capture; **OmniDocBench** is scans/digital; **DocVQA** is saturated (Qwen3-VL-235B 97.1 ANLS, unverified) and not discriminative for this use. Claude 5.5 models appear on none of the camera-photo benchmarks; Datalab's OmniParseBench includes "degraded scans" and "rotated" slices (Gemini 3.8 Flash 85.4 and 92.5 respectively) but not handheld photos.
- Practical implication: dewarping and perspective correction on-device (Vision rectangle detection + Core Image perspective correction) before any cloud call is worth 10-20 accuracy points for pipeline-style models and still helps VLMs.

---

## 3. Options compared

| Option | Where | Latency per page | Cost per 1k pages | Doc accuracy (benchmark) | Word boxes | Handwriting | Fit for this project |
|---|---|---|---|---|---|---|---|
| Apple Vision RecognizeTextRequest `.fast` | on-device | <33 ms/frame (camera-bound, iPhone 16) | $0 | unmeasured; skips small text | yes | weak | Frame gating, stability, dedupe |
| Apple Vision `.accurate` / RecognizeDocumentsRequest | on-device | ~250 ms (text); Documents: unknown | $0 | unmeasured; 26 languages; tables/lists/data detectors | yes | some | Instant text, entities, PDF text layer |
| ML Kit Text v2 | on-device Android/iOS | ~150-170 ms at 480x640 (S24) | $0 | unmeasured | yes | weak | Android parity |
| Claude Haiku 5.5 `low` | cloud | TTFT unknown for images; ~9 s measured on 10k-token text w/ thinking | ~$0.80 (image+JSON) | transcription 93% (Roboflow); localization 32% | no | moderate | Primary understanding tier |
| Claude Sonnet 5.5 / Opus 5.5 | cloud | seconds | ~$16 / ~$32 | 88.7 / 90.7 OmniParseBench; text 93.3 / 94.5 | no | good | Escalation for hard pages |
| Gemini 3.5 Flash-Lite / 3.8 Flash | cloud | TTFT 6.4 s / 25 s measured (with thinking) | ~$1.2-3 / ~$3-6 (est.) | 3.8 Flash 92.7 OmniParseBench; 3 Flash 92.62 OmniDocBench | no | good | Alternative to Claude only if Claude measured worse on photos |
| GPT-6 Luna | cloud | TTFT 0.81 s (non-reasoning) | ~$0.8-1 (est.) | vision overall 69.7% Roboflow; no doc benchmark | no | unknown | Fast but unproven on documents |
| Mistral OCR 4 | cloud | unknown | $4 ($2 batch) | 85.20 olmOCR / 93.07 OmniDocBench (vendor); 89.5 OmniParseBench | yes, with confidence | claimed | High-fidelity text layer fallback |
| Google / AWS / Azure OCR | cloud | unknown | $1.50 | no public leaderboard | yes | moderate | Cheap boxes, no understanding |
| Self-hosted PaddleOCR-VL-1.6 / GLM-OCR / TeleOCR | serverless GPU | 1-3 s warm; batched ~1-1.5 pages/s per A100 | ~$0.6-2 compute + idle GPU $0.59-1.95/h | 95-97 OmniDocBench; 87-92 on camera benchmarks | yes (layout blocks) | moderate | Best accuracy per dollar at scale; ops burden |
| Datalab API (Chandra 2.6) | cloud | median 4.8-6.7 s | $4 (balanced) / $10 (accurate) / $0.50 (lite) | 94.1 OmniParseBench (vendor) | yes | claimed strong | Turnkey high-fidelity, slower |
| On-device VLM (FastVLM 0.5B, iOS 27 FM) | on-device | unknown (<500 ms unproven) | $0 | unmeasured on documents | no | - | Research track, not v1 |

---

## 4. Recommendation for this project

Design around the fact that the user only needs three things fast: "page is in frame and sharp", "captured and safe", and "already scanned". Everything else can take seconds in the background as long as it is guaranteed to finish.

**Tier 0 - per camera frame, on-device, budget <40 ms.** Vision `DetectRectanglesRequest`/document segmentation plus a Laplacian sharpness score, and `RecognizeTextRequest` at `.fast` on the preview buffer. Capture when the quad is stable for ~300 ms and sharp. Use the `.fast` text to compute a rolling text fingerprint so the "already scanned" announcement can fire before the shutter.

**Tier 1 - per capture, on-device, budget <600 ms, this is where "captured" is declared.** Perspective-correct the frame, then run `RecognizeDocumentsRequest` on iOS 26+ (fallback `RecognizeTextRequest` `.accurate`, measured ~250 ms on iPhone 16). Persist immediately: JPEG at full resolution + Vision transcript + word boxes + detected data, written to an append-only local store and queued for upload. Duplicate detection: SimHash/MinHash over the Vision transcript plus a perceptual hash of the dewarped image; threshold tuned so a re-scan of the same page matches in <50 ms. Preliminary classification: a small on-device text classifier (Core ML, or Foundation Models text on iOS 26) over the transcript and detected data (sender, amounts, dates). Confidence-weight it; it exists so the UI can say "tax form" before the cloud answers.

**Tier 2 - cloud understanding, async, target 2-5 s, Claude Haiku 5.5.** Send the dewarped JPEG resized to 2,576 px long edge (3,888-4,784 visual tokens) plus the Vision transcript as a text hint, `effort: "low"`, structured output (`output_config.format`) for: document type, sender/issuer, date(s), amounts, account/reference numbers, tax year, people named, language, 5-10 tags, one-line title, 2-sentence summary, confidence, and a "needs_escalation" flag. Cost ~$0.001/page; batch mode is not useful here because the user wants results now. Use prompt caching for the system prompt (min cacheable 512 tokens on Haiku 5.5). Handle `stop_reason: "refusal"` client-side (no server-side fallback on Haiku 5.5).

**Tier 2b - escalation, Claude Sonnet 5.5.** When Haiku reports low confidence, handwriting, multi-column tables, or a document type the user marked as high-value (tax, legal, medical), re-run with Sonnet 5.5 (text 93.3 / tables 96.1 on OmniParseBench) at ~$0.016/page. Opus 5.5 (text 94.5) only for explicit "fix this page" requests.

**Tier 3 - archival text layer for the searchable PDF.** Build the PDF text layer from Vision's word boxes (free, instant, on-device, correct geometry). Store Claude's transcription and extracted fields in the search index, not in the PDF. For pages where Vision confidence is low (handwriting, faint thermal receipts, non-Latin scripts outside the 26 languages), call Mistral OCR 4 ($4/1k pages, boxes + per-word confidence) or a self-hosted PaddleOCR-VL-1.6 / GLM-OCR replica and replace the text layer. At indie scale (<50k pages/month) Mistral is cheaper than keeping a GPU warm; above ~100k pages/month a warm L40S running PaddleOCR-VL-1.6 (~$1.95/h, ~1 page/s) becomes cheaper and is Apache 2.0.

**Why Claude as the understanding model and not the OCR model.** Measured data says Claude 5.5 transcribes text as well as or better than Gemini 3.8 Flash and Mistral OCR (Opus 5.5 text 94.5 vs 91.9 vs 82.8 on OmniParseBench) but is weak at localization (Haiku 5.5 text localization 32-46% on Roboflow) and returns no word boxes. Vision supplies the boxes; Claude supplies meaning. This split also keeps the per-page cost near $0.001 and keeps the zero-interaction promise because nothing in the cloud path blocks the next page.

**Numbers to target in the prototype (to be measured, not assumed):** Tier 1 end-to-end <600 ms p95 on iPhone 15 Pro and later; duplicate verdict <100 ms; Claude Haiku `low` image round-trip <3 s p50 / <6 s p95 from a phone network; Sonnet escalation rate <10% of pages; per-page cloud cost <$0.003 blended.

**Later speed work:** (1) measure iOS 27 Foundation Models image prompting for classification; (2) distill a Core ML text classifier from Claude labels collected in production; (3) if Android ships, PaddleOCR mobile (PP-OCRv6 tiny) for parity with Vision.

---

## 5. Risks and unknowns

- **No published latency for RecognizeDocumentsRequest or iOS 27 image prompting.** The whole instant-feedback tier rests on a ~250 ms third-party measurement of `RecognizeTextRequest` that the author flagged for recapture. Must benchmark on real devices (iPhone 13-17) before committing UX budgets.
- **Claude accuracy on handheld photos is unmeasured.** Every camera-photo benchmark (Wild-OmniDocBench, Real5) omits Claude. Gemini 3 Pro and Qwen3-VL-235B lose 1-10 points on photos; Claude may behave similarly, but prove it on 200 of the founder's own pages.
- **Claude time-to-first-token for image prompts is unknown.** Artificial Analysis numbers (9 s at low effort) are for 10k-token text prompts with adaptive thinking; small image prompts with `thinking` disabled should be far lower, but nothing public confirms it.
- **Benchmarks are partly vendor-run.** Datalab's OmniParseBench ranks its own model first; Mistral's 85.20/93.07 are self-reported; OmniDocBench rows are often author-submitted. Rankings within ~2 points are not meaningful.
- **Pricing volatility.** Gemini 3.x Flash prices double on 2027-01-01; Mistral doubled OCR pricing from OCR 3 ($2) to OCR 4 ($4) in six months; Haiku 5.5 jumps 5x for prompts over 100k tokens (irrelevant per page but relevant for batched multi-page requests).
- **Licensing traps.** Chandra weights are OpenRAIL-M, non-commercial above $2M revenue/funding; MinerU's license is disputed; PaddleOCR-VL-1.6 (Apache 2.0), GLM-OCR (MIT), DeepSeek-OCR 2 (Apache 2.0) are safe.
- **Warm-GPU economics.** Self-hosted OCR needs an always-on replica for user-facing latency; cold starts of 5-60 s break the experience. At low volume the hourly idle cost exceeds Mistral/Claude per-page pricing.
- **Handwriting and non-Latin scripts** are unquantified across the board; Vision supports 26 languages for documents, and word segmentation is absent for CJK/Thai.
- **Haiku 5.5 refusals** have no server-side fallback; medical/legal pages could trigger safety classifiers, so the client must retry with Sonnet 5.5 and its `fallbacks: "default"` option.
- **Stale-source flags:** Florence-2 and GOT-OCR 2 (2024) are superseded; olmOCR-bench figures for Mistral/GPT-4o/Gemini Flash 2 are from 2025 runs on older model versions; Gemini 3 Flash is "preview" on Google's page while 3.6/3.8 Flash are current.

---

## 6. Open questions for the founder

1. Which languages and scripts must v1 handle? Vision's document API covers 26; CJK word boxes are unavailable.
2. How much handwriting is in the mail stream (signed letters, filled forms)? This decides whether Sonnet escalation or Mistral OCR 4 is on the default path.
3. Is an offline mode required (no cloud at all for some documents, e.g. medical)? If yes, the on-device tier must carry classification alone.
4. Is a stand-mounted continuous feed a real target? If so, Tier 0 can run at 30 fps and auto-capture multiple pages per second, which changes dedupe and upload design.
5. Minimum supported iPhone and iOS? iOS 26 unlocks RecognizeDocumentsRequest; iOS 27 unlocks on-device image prompting.
6. Acceptable blended cloud cost per page for the consumer tier ($0.001 vs $0.02 changes whether Sonnet escalation is automatic or opt-in)?
7. Does the archival PDF need PDF/A conformance and word-accurate highlight positions, or is page-level search sufficient? This sets how much effort goes into the Vision-box text layer.
8. Will Android ship within 12 months? That decides whether to invest in PaddleOCR mobile now or keep the pipeline Vision-specific.
9. Can you provide a Mistral key for a 500-page bake-off alongside Claude, and ~200 real pages (with ground truth typed by you) to run the measurements this report could not find?

---

## 7. Sources

Apple
- https://developer.apple.com/documentation/vision/recognizetextrequest
- https://developer.apple.com/documentation/vision/recognizedocumentsrequest.md
- https://developer.apple.com/videos/play/wwdc2025/272/
- https://developer.apple.com/documentation/foundationmodels/languagemodelcapabilities/capability/vision.md
- https://developer.apple.com/videos/play/wwdc2026/241/
- https://developer.apple.com/ios/whats-new/
- https://arxiv.org/pdf/2507.13575
- https://github.com/apple/ml-fastvlm
- https://machinelearning.apple.com/research/fast-vision-language-models

On-device engines and measurements
- https://pub.dev/documentation/text_sight/0.2.2/
- https://pub.dev/packages/text_sight/versions/0.2.1
- https://developers.google.com/ml-kit/vision/text-recognition/v2
- https://android-developers.googleblog.com/2025/10/ml-kit-genai-prompt-api-alpha-release.html
- https://www.paddleocr.ai/latest/version3.x/algorithm/PP-OCRv5/PP-OCRv5.html
- https://arxiv.org/abs/2606.13108
- https://heartbeat.comet.ml/comparing-on-device-text-recognition-ocr-sdks-24f8a0423461
- https://arxiv.org/pdf/2504.05299
- https://openrouter.ai/moondream/moondream3-preview

Claude
- https://platform.claude.com/docs/en/about-claude/pricing
- https://platform.claude.com/docs/en/build-with-claude/vision
- https://platform.claude.com/docs/en/models/haiku-5-5/overview
- https://platform.claude.com/docs/en/models/haiku-5-5/whats-new-haiku-5-5
- https://platform.claude.com/docs/en/test-and-evaluate/strengthen-guardrails/reduce-latency
- https://www.anthropic.com/claude-haiku-5-5
- https://artificialanalysis.ai/models/claude-haiku-5-5-low/providers
- https://playground.roboflow.com/models/anthropic/claude-haiku-5-5

Other API providers
- https://aistudio.google.com/docs/pricing
- https://developers.openai.com/api/docs/pricing
- https://artificialanalysis.ai/models/gemini-3-5-flash-lite/providers
- https://artificialanalysis.ai/models/gemini-3-8-flash/providers
- https://artificialanalysis.ai/models/releases/gpt-6-luna
- https://mistral.ai/news/ocr-4
- https://mistral.ai/news/mistral-ocr-3
- https://www.datalab.to/blog/chandra-2-6
- https://www.datalab.to/pricing
- https://cloud.google.com/document-ai/pricing
- https://erpresearch.com/erp-add-ons/ocr/google-document-ai/pricing
- https://aws.amazon.com/textract/pricing/
- https://azure.microsoft.com/en-us/pricing/details/ai-document-intelligence/
- https://superdupr.com/blog/azure-document-intelligence-pricing

Open models and benchmarks
- https://github.com/opendatalab/OmniDocBench
- https://github.com/allenai/olmocr
- https://github.com/datalab-to/chandra
- https://huggingface.co/datalab-to/chandra-ocr-2
- https://huggingface.co/deepseek-ai/DeepSeek-OCR-2
- https://huggingface.co/blog/lightonai/lightonocr
- https://huggingface.co/unsloth/GLM-OCR/blob/main/README.md
- https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6/blob/main/README.md
- https://arxiv.org/html/2601.21957 (PaddleOCR-VL-1.5, Real5-OmniDocBench, GPU speed table)
- https://github.com/VirtualLUOUCAS/Wild_OmniDocBench
- https://arxiv.org/abs/2608.12898 (TeleOCR)
- https://arxiv.org/pdf/2510.19817 (olmOCR 2)
- https://www.marktechpost.com/2026/07/24/datalab-marker-v2-vs-mineru-docling-and-liteparse-benchmark-breakdown/
- https://www.notebookcheck.net/DeepSeek-OCR-AI-model-can-process-200-000-document-pages-a-day-on-a-single-Nvidia-A100-GPU.1144400.0.html

Hosting
- https://modal.com/pricing
- https://www.runpod.io/pricing
- https://blog.premai.io/serverless-llm-deployment-runpod-vs-modal-vs-lambda-2026
