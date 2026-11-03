# Gap 1: Grouping consecutive captures into documents with zero interaction

Research date: 2026-11-03. Dimension: page-to-document boundary detection in a handheld, prompt-free capture stream; the measured reliability of each boundary signal; the unit of Claude inference; the cost of a 5-page packet including re-understanding after a wrong boundary; and the reconciliation protocol for per-document PDFs already uploaded to Google Drive, iCloud Drive and Synology.

Labels used throughout: **measured** (a published measurement), **vendor claim**, **estimate** (my extrapolation; must be measured on device), **unknown**.

Note on method: this round's web-search budget was exhausted before my first query, so every fact below comes from fetched primary pages, two papers extracted locally from their PDFs, the Synology File Station API PDF, and the existing reports `mail.md`, `dedup.md`, `claude.md`, `output.md`, `storage.md` in this directory. Things I could not fetch are marked unknown rather than guessed.

## 1. Executive summary

1. No published system reaches >99% automatic page-stream segmentation. Best measured numbers: 0.929 page accuracy on a German archive (image+text CNN), document-level F1 0.80 / segmentation quality 0.93 on OpenPSS, page F1 0.944 / whole-stream F1 0.879 for a fine-tuned Mistral-7B on real insurance streams. Expect roughly 1 in 8 multi-page packets to contain at least one wrong cut if we only use the signals those systems had.
2. No paper isolates the precision of "Page N of M", letterhead continuity, sentence continuity, form-factor change or capture-gap signals. Those per-signal error rates are **unknown** and must come from our own labeled handheld corpus. The literature gives direction only: new headers are the strongest cue, page-number sequences can mislead (fax headers), and visual-only models lag text models.
3. Claude Haiku 4.5 zero-shot pairwise boundary F1 is 0.866 (TABME++) and 0.969 (VRDU forms) on OCR text at 2.4-2.5 s per call; vision input is not more accurate and costs more; multi-page "K=5" prompts are *worse* (0.817 / 0.795) and collapse by K=20. dedup.md's proposed K=5 session pass should be replaced by pairwise (K=2) or at most K=3 decisions.
4. The correct unit is: the **page** for capture and durability, the **document** for Claude inference. Fold the boundary verdict into the understanding call by running each open document as a growing, prompt-cached Claude conversation: page n+1 is appended, pages 1..n are cache hits (Haiku 5.5 cache read is $0.01/MTok), and the structured output includes `continues_open_document`.
5. A 5-page packet costs about 5 calls and $0.003 in that design (estimate at Haiku 5.5 prices, 1568-px pages); a later merge or split costs one more call of about $0.001-0.002. Token cost is negligible; the real cost of a wrong boundary is storage churn.
6. Make the user-facing multi-page PDF a derived, rebuildable artifact over immutable per-page blobs, upload per-page originals immediately (durability), and upload the document PDF only once the document is "settled" (closed and cloud-confirmed). Reconcile with update-in-place on a stable remote ID (Drive `files.update`, Synology `Upload overwrite=true`, iCloud coordinated `.forReplacing`), two-phase delete (upload new, verify checksum, then trash old), and local tombstones with aliases.
7. In the uncertain band, prefer **split** on device and let Claude propose **merges**: a wrong split keeps every page findable and merging later is a manifest edit; a wrong merge contaminates two documents' classification and extraction.
8. A stack of single-page letters from the same sender remains the hardest case for every signal; the cheap on-device cue the literature supports is "first-page structure" (date + addressee block + salutation) and "last-page structure" (closing, signature, totals), which no existing report uses.
9. Vendor splitters (Google Custom Splitter, Azure custom classification `splitMode=auto`) exist but are batch-file APIs (15 online pages, human-review recommended) and cannot see our physical signals; they are not a fit for the hot path.
10. Zero interaction stays intact: nothing requires a tap; the timeline's merge/split controls become optional telemetry, not a dependency.

## 2. Findings

### 2.1 How good is automatic page-stream segmentation, measured

| Dataset / system | Input | Result | Source |
|---|---|---|---|
| Archive22k (22,741 pages, 100 binders), MLP image+text | scans | page accuracy 0.929, kappa 0.691; text-only CNN 0.904; image-only 0.884 | https://ar5iv.labs.arxiv.org/html/1710.03006 |
| Tobacco800 (1,290 pages), same model | scans | accuracy 0.911, kappa 0.816 | same |
| OpenPSS-LONG (89,491 pages, 24,181 docs, median 217 pages/stream), BERT+EfficientNet late ensemble | Dutch FOIA scans | document precision 0.82, recall 0.82, document F1 0.80, segmentation quality (mean IoU of matched docs) 0.93; best page-level boundary F1 about 0.83 | OpenPSS paper (local extract of https://irlab.science.uva.nl/wp-content/papercite-data/pdf/heus_open24.pdf) |
| Insurance streams (7.5k streams, 20.3k docs, 44.7k pages), XGBoost on OCR features | real, private | page F1 0.902, stream F1 0.827 | COLING 2025 industry paper (local extract of https://aclanthology.org/2025.coling-industry.26.pdf) |
| Same, fine-tuned Mistral-7B (LoRA, 4-bit) | real, private | page F1 0.944-0.947, stream F1 0.879-0.882; Phi-3-mini 0.933 / 0.861 | same |
| TABME++ (~6.2k pages, synthetic streams of business docs), Claude Haiku 4.5 zero-shot pairwise (BD) | OCR text | boundary F1 0.866 at 2.42 s/call; vision 0.837 at 2.91 s | https://arxiv.org/html/2609.22620v1 Table 3 |
| VRDU (~1.1k pages, forms), Claude Haiku 4.5 BD | OCR text | boundary F1 0.969 at 2.50 s/call; vision 0.969 at 3.15 s | same |
| Same paper, multi-split windows (MSBD) with Claude | text | K=3: 0.844 / 0.900; K=5: 0.817 / 0.795; K=7: 0.782 / 0.722; K=20: 0.620 / 0.527 (TABME++ / VRDU) | same, Tables 3-4 |
| Same paper, other models BD text | text | Gemini 3.1 Flash-Lite 0.883 / 0.971; GPT-5.4-mini 0.873 / 0.783; fine-tuned Phi-3-mini 0.973 and Mistral-7B 0.987 (reference rows, not directly comparable) | same |
| DocSplit (RVL-CDIP-MP, 995 docs, 5,231 pages, 13 types), Claude Haiku 4.5 | page images | clustering score 0.81-0.88 across the five benchmarks; Claude Sonnet 4.5 0.83-0.88; Qwen 3 VL 235B best at 0.86-0.90; ordering >0.98 for all | https://arxiv.org/html/2602.15958v1 Table 2 |

Takeaways that matter for us:

- "Stream-level" numbers (every cut in a packet correct) sit at 0.83-0.88 on real enterprise data. The founder's streams are shorter and carry physical signals the datasets lack, so we should beat this, but nobody has measured handheld streams (dedup.md says the same).
- Haiku and Sonnet 4.5 tie on DocSplit; there is no accuracy reason to escalate boundary decisions to Sonnet.
- Vision input did not beat OCR text in any pairwise setting and was always slower and pricier (multi-split paper, Section 6). For boundary decisions, send text; send images only when the understanding call needs them anyway.
- Window size is a trap: Claude's boundary F1 falls monotonically with K and the paper reports Claude "over-segments" and produces malformed outputs at large K. dedup.md's K=5 end-of-session pass would be measurably worse than pairwise decisions on form-heavy mail (0.795 vs 0.969 on VRDU).

### 2.2 What is known about each signal (the gap the brief asks about)

| Signal | Published evidence | Measured error rate | What it cannot do |
|---|---|---|---|
| Printed "Page N of M" / "N/M" / "continued" | XGBoost on OCR features "struggles with documents containing multiple stamps or misleading page sequences (e.g., original and fax page numbers)" while LLMs "consistently succeed" (COLING 2025, Section 5.1). Google's and the multi-split paper's prompts list "page numbers" as a cue. | **Unknown** as an isolated feature; no paper reports its precision. Prevalence of N-of-M footers in US household mail: unknown. | Fax/transmittal headers, "Page 1 of 1" repeated on every statement page, attachments with their own numbering, cover letters without numbers. Treat as strong only when N increments from the open document's last N in the same footer position; "1 of M" and "1 of 1" are boundary openers. |
| Letterhead / running header continuity | Figure 1 of the COLING paper is exactly "a new page header" that XGBoost missed and the LLM caught; OpenPSS reports visual-only models lag text models; Wiedemann notes humans "struggle to find clear layout patterns" for first pages in archives. | **Unknown** as a standalone feature. | Multi-page packets that mix stock (mail.md 2.3); single-page letters from the same sender in a stack (identical headers, different documents). |
| Sentence / content continuity | Used in every LLM prompt (multi-split paper cue list; DocSplit "content continuity"); the only text cue Wiedemann names is a closing phrase such as a salutation on the predecessor page raising the chance of a new document. | **Unknown**. Expect high precision when it fires (hyphenated or lower-case continuation) and low recall (most pages end at a paragraph boundary). | Forms, tables, statements (no running prose). |
| First-page / last-page structure (date line + addressee block + "Dear" at top; "Sincerely", signature, "Total due", "Page N of N" at bottom) | Implicit in Wiedemann's salutation cue and DocSplit's "new title or cover sheets", "signature pages", "logical completion"; the Azure and Google splitters classify "first page" implicitly. | **Unknown**; no existing report in this directory uses it. | Pre-printed notices with no salutation; multi-letter packets where each page is a letter. |
| Form-factor change (sheet -> receipt -> card) | No literature; handheld-only signal from the detected quad's size and aspect (`VNDetectDocumentSegmentationRequest`). | **Unknown**; estimate: near-deterministic for class changes, useless within one class. | Everything that is letter-size. |
| Physical page-swap gap | No literature on handheld capture intervals. Google Photos stacks use time plus similarity (dedup.md). Scanner SDK docs fetched this round state only that the SDK "automatically captures the document when the device is optimally positioned" with no timing published (https://docs.scanbot.io/document-scanner-sdk/ios/features/document-scanner/). | **Unknown**. | Cannot separate a stack of single-page letters from one multi-page letter (dedup.md and its critic agree; nothing found this round contradicts them). Useful only as "left the capture screen / >60 s" (boundary prior) and "<4 s, same quad" (duplex flip prior). |
| Claude pairwise tie-break | Haiku 4.5 BD text F1 0.866 / 0.969, 2.4-2.5 s per call (measured in the paper's harness, not a latency benchmark); Haiku 5.5 numbers **unknown**. | See Section 2.1. | Nothing forces it to be a separate call; see Section 2.4. |
| Fine-tuned small model (future custom model) | Mistral-7B 0.944 / 0.879 on real insurance streams; Phi-3-mini 0.973 reference. Training data: thousands of labeled streams. | Measured, but on enterprise data. | Needs our labeled handheld corpus first; the on-device scorer's logged decisions are that corpus. |

Honest conclusion: the per-signal error rates the brief asks for do not exist in the literature. The one hard number we can plan around is that text-based models with header, page-number and continuity cues reach 0.93-0.95 page accuracy on real streams, and that the two systematic failure families are new headers that look like continuations (missed cuts) and attachments or sub-documents that look like first pages (false cuts; three quarters of SVM errors on Archive22k and 77% of OpenPSS false-positive documents lie inside a larger document).

### 2.3 The handheld cases, one by one

| Case | Signals that fire | Hard part | Recommended default |
|---|---|---|---|
| 3-page statement | N of M footer, same header hash, same account number, gap <20 s | None if footers exist; statements without footers rely on header + account-number match | Append |
| Front/back of one sheet | Same quad size and paper color, flip within ~4-8 s (mail.md 2.2), bleed-through, "continued on reverse" | Blank backs (drop, log) and the case where the user flips a single-sided letter (blank page) | Append as side B; blank backs stored as flag only |
| Envelope + contents | Envelope form factor (aspect, no body text, postmark/indicia) then letter-size pages | Envelope arriving after the letter; two envelopes in a row | Envelope becomes `envelope_of` the next document (mail.md 2.1); a second envelope with no pages in between closes the first as envelope-only |
| Interleaved packet (letter + remittance stub + return envelope + insert) | Form-factor changes, header changes, "detach here" text | Which pieces belong: all of them, but advertising inserts should be split off and classified separately | One document with `attachments[]`; Claude's document-level call decides which pages are inserts |
| Page re-shot later (better capture of a page already in a closed document) | Feature-print near-duplicate plus OCR Jaccard (dedup.md) | Distinguishing "replace page 2" from "new copy of the same letter" | Treat as page-level replacement when text Jaccard >0.9; rebuild the PDF, never create a new document |
| Page 3 arrives two minutes after pages 1-2 closed | N of M says "3 of 3" and the open document ended at "2 of 3" | Only works with footers; otherwise Claude must recognise continuation | Auto-append to the last closed document whose expected M is unmet, else new document and let the document-level call propose a merge |
| Stack of single-page letters from the same sender | Header matches, gap is short, no footers | The genuinely ambiguous case | Split when first-page structure is present on each page; otherwise Claude pairwise decision on text |
| Same template, different instance (two months of a bill) | Header match, text Jaccard 0.5-0.8, different dates/amounts | Must not be called a duplicate and must not be merged | Split; dedup.md's Jaccard guard prevents "already scanned" |

### 2.4 Unit of inference: page or document

Facts from the Claude docs (https://platform.claude.com/docs/en/build-with-claude/vision.md, https://platform.claude.com/docs/en/about-claude/pricing.md, https://platform.claude.com/docs/en/build-with-claude/prompt-caching.md):

- Up to 600 images per request (100 for 200k-context models); above 20 image blocks every image must be at most 3,000 px per side; 10 MB per image; 128 MB per request.
- Images cost `ceil(w/28) x ceil(h/28)` visual tokens. "Claude 4.7 and later models" are high-resolution tier (long edge 2,576 px, cap 4,784 tokens); earlier models cap at 1,568 px / 1,568 tokens. Haiku 5.5 is a later model, so I assume high-resolution tier; **flag: not stated by name**. A 1140x1568 portrait page = 41 x 56 = 2,296 tokens; a 1600x2200 page = 58 x 79 = 4,582 tokens.
- Haiku 5.5: $0.10 input / $0.50 output per MTok for prompts up to 100K tokens; $0.50 / $2.50 above 100K, and the threshold counts cache reads and writes. Cache write 1.25x (5-min) or 2x (1-hour); cache read $0.01/MTok. Minimum cacheable prefix on Haiku 5.5 is 512 tokens. Images are cacheable; adding an image invalidates only the `messages` level, so a growing prefix of pages keeps earlier pages cached.
- At 2,296 tokens per page the 100K threshold is reached at about 43 pages in one request; at 4,582 tokens, about 21 pages. Long packets must be chunked or sent to Sonnet 5.5 ($2 / $10, no long-context surcharge).

Three call structures for a 5-page packet (estimates; per page 2,296 image tokens, ~1,500 cached system/schema tokens, ~500 output tokens; Haiku 5.5 prices):

| Structure | Calls | Approx. cost | Latency to first per-page result | Boundary tie-break | Cost of a later merge/split |
|---|---|---|---|---|---|
| A. Independent per-page calls, then one document-level call with all 5 images at close | 6 (7 after a correction) | 5 x $0.0005 + $0.0016 = **$0.004**; +$0.002 per re-understanding | one call | separate pairwise call or on-device only | re-send whole document |
| B. Document-level only, called when the document closes | 1 | **$0.0016** | waits for closure (seconds to a minute) | none in the loop | re-send whole document |
| C. Incremental cached conversation: call n sends pages 1..n with pages 1..n-1 as cache hits; output = document-so-far JSON including `continues_open_document` for page n | 5 | writes 5 x 2,296 x 1.25 = 14.4K tokens ($0.0014) + reads 23K tokens ($0.0002) + output 2.5K ($0.0013) = **$0.003** | one call, same as A | free, inside the call we make anyway | append or re-send only the changed pages: ~$0.001-0.002 |

Structure C is the recommendation. The unit of inference is the document, but every page triggers a call, so per-page feedback is as fast as structure A while the document-level fields (type, sender, period, total, summary) are always current and the boundary verdict costs no extra round-trip. The structured-output schema already proposed in claude.md (`page_role` and friends) extends with three fields: `continues_open_document: bool`, `boundary_confidence: number`, `suggested_merge_with: doc_id | null`. The 5-minute cache TTL comfortably covers page swaps; use the 1-hour TTL (2x write) only for documents the user is likely to come back to within the hour (e.g., a page 3 found later).

Where this interacts with other reports: claude.md's advice to send groups of at most 20 images per request and to keep Haiku requests under 100K tokens still holds; architecture.md's "batch when a multi-page document is detected" becomes "append to the document's cached conversation".

### 2.5 What the vendor splitters offer (and why they are not the hot path)

- Google Document AI Custom Splitter: pretrained `pretrained-splitter-v1.5-2025-07-14` (GA, Gemini 2.5 Flash) and `v1.6` / `v1.6-pro` release candidates (Gemini 3.1 Flash / Pro, March 2026, no data residency); output is one entity per document with `pageAnchor.pageRefs` (zero-based, page 0 omitted from JSON), `type` and `confidence`; the service does not split the file, the Toolbox SDK's `split_pdf` does; online limit 15 pages (30 with `imageless_mode`), batch 1,000 pages; trained versions want at least 10 and ideally 50 documents per class; the doc says "a best practice is to always have a human review step after the splitting prediction but before the actual file split" because "a bad split makes two documents wrong". Pricing page is JavaScript-rendered and returned no numbers: **unknown**. (https://docs.cloud.google.com/document-ai/docs/custom-splitter, https://docs.cloud.google.com/document-ai/docs/handle-response, https://docs.cloud.google.com/document-ai/docs/processors-list)
- Azure Document Intelligence v4.0 (2024-11-30 GA) custom classification: `splitMode` is `none` by default (changed from earlier releases), `perPage` or `auto`; at least two classes and five samples per class; response lists `documents[]` with `docType`, `boundingRegions[].pageNumber` and `confidence`; up to 2,000 pages per PDF. Pricing page shows "$-" placeholders: **unknown**. (https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/train/custom-classifier?view=doc-intel-4.0.0, https://azure.microsoft.com/en-us/pricing/details/ai-document-intelligence/)
- paperless-ngx: merge is a bulk-edit action on selected documents; split, rotate, delete-pages and re-order live only in the PDF Editor; the docs warn that rotation and page deletion "alter the Paperless-ngx original file"; duplicates are detected by checksum and only warned about unless `PAPERLESS_CONSUMER_DELETE_DUPLICATES` is set. (https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/usage.md)

None of these sees quad size, flip timing or capture gaps, all are file-in/file-out, and both cloud vendors recommend a human review step. They remain an option for backfilling existing multi-document PDFs from a NAS or flatbed.

### 2.6 What happens downstream when a boundary is wrong

**Storage model that makes corrections cheap.** Every page is an immutable, content-addressed blob plus its OCR layer and per-page PDF/A (output.md, dedup.md 2g). A document is a manifest: ordered page IDs, envelope ID, attachment roles, Claude's document record, and per-destination remote IDs. The multi-page PDF is derived by byte-copying page objects into one file (output.md 2h), so rebuilding it is milliseconds, not a re-encode.

**Settlement states.** `captured` (page blob durable locally and queued to every destination) -> `open` (document accepting pages) -> `closed` (boundary decided on device) -> `confirmed` (Claude's document-level verdict received, or 60 s timeout) -> `filed` (document PDF and sidecar uploaded and verified at every destination) -> `sealed` (no automatic regrouping after 24 h; later changes require a confirmed duplicate, an N-of-M completion, or the user). The durability promise is given at `captured`; `filed` is when the user-facing PDF exists.

**Reconciliation operations.** Per destination, each correction becomes at most three idempotent operations: update-in-place of the surviving document, optional rename, and two-phase removal of the absorbed document.

| Destination | Update in place | Rename / move | Remove absorbed document | Verify | Source |
|---|---|---|---|---|---|
| Google Drive | `PATCH https://www.googleapis.com/upload/drive/v3/files/{fileId}` with media; same `fileId`, new head revision; old blob revisions are purgeable after about 30 days or when 100 purgeable revisions exist; `keepRevisionForever` pins up to 200 | same PATCH with `name`; `addParents`/`removeParents` for folders | `files.update` with `trashed: true` (restorable) rather than `files.delete`; write the surviving `fileId` into `appProperties` of the trashed file as a forward pointer | `md5Checksum` on the file resource (storage.md) | https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update, https://developers.google.com/workspace/drive/api/guides/manage-revisions, https://developers.google.com/workspace/drive/api/reference/rest/v3/files |
| iCloud Drive | coordinated write with `.forReplacing` to the same URL; other devices see a changed item, not a new one | `coordinate(writingItemAt:options:.forMoving ...)` and `item(at:didMoveTo:)`; the archived guide: "Call the itemAtURL:didMoveToURL: method to move a file or directory to a new location" | coordinated `.forDeleting`; Apple's design guide: "deleting a document from iCloud removes it from the user's iCloud account and from all of their iCloud-enabled devices", so move the absorbed PDF to an app-managed `Archive/.merged/` folder first and delete only after the surviving file is verified | re-read bytes and compare SHA-256 after download state is current | https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/FileCoordinators/FileCoordinators.html, https://developer.apple.com/library/archive/documentation/General/Conceptual/iCloudDesignGuide/Chapters/iCloudFundametals.html; conflict handling via `NSFileVersion` as in storage.md |
| Synology (File Station API) | `SYNO.FileStation.Upload` v2 with `overwrite=true`, `create_parents=true` | `SYNO.FileStation.Rename` v2 (`path[]`, `name[]`); `SYNO.FileStation.CopyMove` v3 `start/status/stop` with `remove_src=true` for moves | `SYNO.FileStation.Delete` v2: blocking `delete` or non-blocking `start/status/stop`; `recursive` flag | `SYNO.FileStation.MD5` v2 (non-blocking start/status) | Synology File Station Official API PDF (local extract; "Availability: Since DSM 6.0") |
| Any WebDAV (Synology WebDAV Server, Nextcloud) | `PUT` to same path | `MOVE` with `Destination` | `DELETE` after verification | `HEAD` size plus re-read sample (storage.md) | storage.md |

**Per-case protocol.**

- *Merge B into A* (pages of B belong to A): keep A's document ID and remote IDs; append B's pages to A's manifest; re-run the document-level Claude call (one call, B's pages written to cache, A's read); rebuild A's PDF and sidecar; update-in-place at every destination; rename if the derived name changed (date, sender, type; the 8-character ID suffix from storage.md stays, so renames are detectable); move B's remote file to the destination's archive folder, verify A, then trash/delete B; write a local tombstone `B -> A` and keep B's ID in A's `aliases` so old search hits, share links and export bundles resolve. Re-emit search artifacts (Core Spotlight item, Drive `contentHints.indexableText`, embeddings) for A and delete B's.
- *Split AB into A and B*: A keeps the ID and remote files with pages 1..k (update in place); B is a brand-new document with a fresh upload; no tombstone needed; both get fresh Claude records (two calls, A's prefix cached).
- *Page replaced by a better re-shot*: page-level swap in the manifest, PDF rebuilt, update-in-place; no renames, no deletes, one Claude call only if the OCR text changed materially.
- *Late page completes a closed document* (N of M satisfied): same as merge with a one-page B.
- *Failure handling*: if any destination is offline the outbox state machine from storage.md carries the pending operations; the local catalog is the source of truth and every remote operation is idempotent by `(document_id, destination, revision)`.

**Operation count.** A merge across three destinations is up to 3 updates + 3 renames + 3 moves + 3 deletes = 12 remote calls, all background. A split is 3 updates + 3 uploads. With the vendors' measured 0.83-0.88 stream accuracy as a pessimistic prior, roughly one correction per eight multi-page packets; at a household volume of a few packets a day this is a handful of background operations a week.

**Why not delay all uploads until the document is sealed?** Because the durability promise is per page and given at capture time. storage.md already resolves this: upload the per-page original first, the enriched document PDF/A second. Keep the per-page files in a hidden `_pages/` folder (or the service escrow bucket in storage.md option D) so the user-visible tree only ever contains settled document PDFs and corrections rarely touch what the user sees.

### 2.7 Zero interaction preserved: how corrections happen without taps

mail.md's design "exposes merge-with-previous and split-here as single taps". That is fine as an optional affordance, but the automatic path must not depend on it:

1. On-device scorer decides instantly (mail.md 2.3 pseudocode) with the additions from Section 2.2: `first_page_structure` (+3), `last_page_structure_on_previous` (+2), N-of-M handling that requires footer position and increment, and the rule that the gap signal is a prior only.
2. In the uncertain band, the device **splits** and marks the new document `tentative`.
3. The next incremental Claude call for the tentative document carries the previous document's last page text as context and returns `suggested_merge_with`. Haiku pairwise text decisions measured 0.866-0.969 F1; the device merges automatically when `boundary_confidence >= 0.8` and otherwise leaves both documents as they are.
4. Every decision and the signals behind it are logged; the user's optional merge/split taps and the "already scanned" announcements become labels. That log is the corpus for measuring the per-signal error rates this report could not find, and later for the founder's custom model (fine-tuned Phi-3-mini / Mistral-class models reach 0.97-0.99 on labeled streams).
5. The end-of-session pass, if kept, runs pairwise or K=3 over the session's boundaries, not K=5.

## 3. Options compared

| Option | Zero interaction | Accuracy evidence | Per-page latency | 5-page packet cost (Haiku 5.5, estimate) | Downstream churn | Verdict |
|---|---|---|---|---|---|---|
| 1. On-device scorer only, taps for correction (mail.md) | Violates the requirement when a tap is needed | none measured for handheld | <100 ms | $0 for boundaries | corrections are user-triggered | Keep the scorer, drop the dependency on taps |
| 2. Scorer + separate Claude pairwise tie-break in the uncertain band | Yes | Haiku 4.5 BD text F1 0.866 / 0.969 | +2.4 s round trip per uncertain pair (Haiku 4.5 measured; 5.5 unknown) | +$0.0002 per tie-break | same as 1 | Good, but redundant once option 5 exists |
| 3. End-of-session K=5 multi-split pass (dedup.md) | Yes | F1 0.817 / 0.795, degrading with K | not in the loop | about $0.16-0.45 per 1,000 pages (Gemini numbers in the paper) | regroups after documents are already filed: maximum churn | Replace with pairwise or K<=3 |
| 4. Cloud splitter (Google / Azure) | Yes | unmeasured publicly; vendors recommend human review | file-level, 15 online pages | unknown pricing | file-in/file-out, no physical signals | Backfill of legacy PDFs only |
| 5. Scorer + incremental cached document conversation with boundary verdict folded into understanding (this report) | Yes | same as 2 plus document-level context | one Haiku call per page, which we make anyway | about $0.003 per packet, $0.001-0.002 per correction | corrections are manifest edits plus idempotent update-in-place | **Recommended** |

PDF unit options:

| PDF unit | Durability | Search / export | Correction cost | Verdict |
|---|---|---|---|---|
| Per-page PDFs only, plus a logical grouping index | best | user sees loose pages in Drive; "send me the statement" needs assembly at export time | none | Not acceptable as the user-facing tree |
| Per-document PDF only, assembled at close | depends on close timing | best | rebuild + re-upload + delete on every correction | Acceptable only with the settlement delay |
| Both: hidden per-page files uploaded immediately, document PDFs uploaded at `confirmed` | best | best | rebuild is a byte copy; user-visible files change rarely | **Recommended** (storage.md's two-phase upload already implies this) |

## 4. Recommendation for this project

1. **Units.** Page = unit of capture, dedup and durability. Document = unit of Claude inference, PDF, naming and search. Envelope = attachment page of a document. Never make the PDF the primary record.
2. **Call structure.** One Haiku 5.5 call per captured page, appended to the open document's prompt-cached conversation (pages at 1,568 px long edge, about 2,300 tokens each; system prompt plus schema over 512 tokens so it caches; `effort: low`). Structured output returns the document-so-far record plus `continues_open_document`, `boundary_confidence`, `suggested_merge_with`, `expected_page_count`. Chunk or switch to Sonnet 5.5 above about 40 pages. Send OCR text, not a second image, when a pairwise comparison with the previous document is needed.
3. **Boundary policy.** On-device scorer decides in under 100 ms; uncertain band splits (tentative); Claude proposes merges; auto-merge at confidence >= 0.8; nothing requires a tap. Add first-page and last-page structure detectors to the scorer; demote the capture gap to a prior; require footer-position and increment checks for N of M.
4. **Settlement and uploads.** Per-page originals upload at capture to a hidden `_pages/` folder (or escrow); the document PDF/A uploads at `confirmed` (closed + Claude verdict or 60 s); documents seal after 24 h.
5. **Reconciliation.** Update-in-place on stable remote IDs (Drive `fileId`, iCloud URL under coordination, Synology path with `overwrite=true`), rename only when the derived name changes, two-phase removal (archive, verify survivor by checksum, then trash), tombstones with aliases in the local catalog, and re-emission of every search artifact. All operations idempotent by `(document_id, destination, revision)` and carried by the existing outbox.
6. **Measure before launch.** Build a 200-packet handheld corpus (statements, duplex letters, envelopes, interleaved packets, same-sender stacks) and report per-signal precision/recall and stream-level accuracy; this is the number nobody has published.
7. **Custom model later.** The decision log is the training set; the COLING numbers show a 7B fine-tune beats zero-shot by 5-8 F1 points on real streams, and the founder's "custom modeling later" has a concrete target: on-device or edge pairwise boundary model trained on logged decisions.

## 5. Risks and unknowns

- Per-signal error rates are unmeasured anywhere; the scorer weights in mail.md and the additions here are design guesses until the corpus exists.
- Haiku 5.5 boundary accuracy and latency are unknown; all LLM numbers are Haiku 4.5 or other vendors. Whether Haiku 5.5 is on the high-resolution image tier is inferred from "Claude 4.7 and later", not stated.
- The stack-of-single-page-letters case has no reliable on-device signal; the first-page-structure cue is plausible but unmeasured.
- Over-segmentation is the dominant error family in two studies; a split-biased policy will produce some two-part documents that only a later Claude call can heal, and only if its confidence clears the threshold.
- iCloud deletes propagate to every device and `trashItem` behaviour on ubiquitous URLs is unverified; the archive-folder step is the mitigation.
- Google Drive revision retention (about 30 days, 100 purgeable revisions) means frequent in-place updates could pile up revisions on a busy file; corrections are rare enough that this should not matter, but the behaviour on shared drives was not checked.
- Vendor splitter pricing (Google, Azure) could not be fetched; both pages are JavaScript-rendered.
- Haiku 5.5's 100K-token price step and the >20-image 3,000-px rule are easy to trip with long packets at full resolution.
- Several numbers come from datasets of scanned enterprise files, not photographed mail; transfer is assumed, not shown.

## 6. Open questions for the founder

1. When Claude disagrees with the device after a document is already filed, is a silent regroup acceptable, or should the app announce it ("merged two pages into the Chase statement") the way it announces "already scanned"?
2. Is a 60-second settlement delay before the document PDF appears in Drive/iCloud/NAS acceptable, given that per-page originals are already safe?
3. Should the hidden per-page folder exist in the user's own storage, or only in the service escrow bucket (storage.md option D)?
4. For same-sender stacks (several EOBs from one insurer), is the preferred failure a few two-letter PDFs (merge bias) or a few split statements (split bias)? This report assumes split bias.
5. May the app collect the anonymised boundary-decision log (signals only, no page content) from beta users to measure per-signal error rates, or must the corpus be the founder's own mail?
6. Is a 24-hour seal acceptable, after which only duplicates, N-of-M completion or the user can regroup?

## 7. Sources

- Multi-split LLM page stream segmentation (Claude Haiku 4.5 numbers, K sweep, latency, cost): https://arxiv.org/html/2609.22620v1
- DocSplit benchmark (Claude Haiku/Sonnet 4.5 clustering scores): https://arxiv.org/html/2602.15958v1
- Page Stream Segmentation with LLMs in insurance (XGBoost vs Mistral/Phi, stream-level F1, failure examples): https://aclanthology.org/2025.coling-industry.26.pdf
- OpenPSS dataset and document-level metrics: https://irlab.science.uva.nl/wp-content/papercite-data/pdf/heus_open24.pdf
- Wiedemann and Heyer, image+text PSS on Archive22k / Tobacco800: https://ar5iv.labs.arxiv.org/html/1710.03006
- Van Landeghem et al., multi-page document classification formalisation: https://arxiv.org/abs/2308.12896
- Google Document AI Custom Splitter: https://docs.cloud.google.com/document-ai/docs/custom-splitter
- Google Document AI splitter response handling: https://docs.cloud.google.com/document-ai/docs/handle-response
- Google Document AI processor list and page limits: https://docs.cloud.google.com/document-ai/docs/processors-list
- Azure Document Intelligence custom classification and `splitMode`: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/train/custom-classifier?view=doc-intel-4.0.0
- Azure Document Intelligence pricing (placeholders only): https://azure.microsoft.com/en-us/pricing/details/ai-document-intelligence/
- paperless-ngx usage (merge, split, duplicates): https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/usage.md
- Claude vision limits and image token tiers: https://platform.claude.com/docs/en/build-with-claude/vision.md
- Claude pricing (Haiku 5.5 tiers, cache, batch): https://platform.claude.com/docs/en/about-claude/pricing.md
- Claude prompt caching (minimum prefix, image caching, invalidation): https://platform.claude.com/docs/en/build-with-claude/prompt-caching.md
- Google Drive files.update: https://developers.google.com/workspace/drive/api/reference/rest/v3/files/update
- Google Drive revisions retention: https://developers.google.com/workspace/drive/api/guides/manage-revisions
- Google Drive File resource (appProperties, indexableText 128 KB): https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- Apple File System Programming Guide, file coordinators: https://developer.apple.com/library/archive/documentation/FileManagement/Conceptual/FileSystemProgrammingGuide/FileCoordinators/FileCoordinators.html
- Apple iCloud Design Guide fundamentals (deletion propagation): https://developer.apple.com/library/archive/documentation/General/Conceptual/iCloudDesignGuide/Chapters/iCloudFundametals.html
- Synology File Station Official API (Rename, CopyMove, Delete, Upload, MD5): https://global.download.synology.com/download/Document/Software/DeveloperGuide/Package/FileStation/All/enu/Synology_File_Station_API_Guide.pdf
- Scanbot document scanner SDK (auto-capture statement, no timing): https://docs.scanbot.io/document-scanner-sdk/ios/features/document-scanner/
- Prior reports in this directory: mail.md (Section 2.3 scorer), dedup.md (Section 2f grouping), claude.md (Sections 2.6-2.7), output.md (Section 2h), storage.md (outbox and naming).
