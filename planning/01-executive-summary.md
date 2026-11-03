# Executive summary: the zero-interaction paper digitizer

Date: 2026-11-03. Status: research complete, plan of record drafted, nothing built yet. Working name: to be chosen (see `05-names.md`).

## What you asked for

A phone app you open, hold over a piece of paper, and never touch. It captures each page as soon as it is sharp, tells you instantly if you already scanned it, understands what the document is, files a print-quality searchable PDF into your own storage (Google Drive, Synology, iCloud Drive, or all of them), and makes everything findable by meaning ("all my tax documents for 2024"). Once the app says a page is captured, the paper can go in the bin. Speed first. Claude as the AI. Eventually an App Store product and a service.

## The answer in one paragraph

Build a native Swift app (iOS 26 floor) with a **custom camera loop**, because Apple's built-in document scanner and every commercial scanner SDK require a Save or Done tap and hide the moment of durability. The one thing the user waits for is a haptic, and that haptic depends only on a local, fsync'd write of the page to disk: about half a second after the page settles on current iPhones. Everything else (duplicate confirmation, OCR, the label, the PDF, the upload, the Claude call) is progressive refinement of a card that is already on screen. Apple Vision does all geometry and text on-device for free; **Claude Haiku 5.5** supplies meaning asynchronously at about **$0.0004 per page**. The user's own storage is the system of record, with three honest durability states: *captured* (on this phone), *safe* (verified in at least one destination, shown as a lock, this is when the paper goes), *replicated* (everywhere). Search is entirely on-device and instant. There is no backend at all until the App Store version, and even then only a thin key-holding proxy.

## The ten decisions that define the product

1. **Custom AVFoundation + Vision capture loop, not VisionKit.** Apple Developer Technical Support confirmed twice (Jan 2025, May 2026) that `VNDocumentCameraViewController` cannot be customized: it returns pages only after a Save tap and gives no processing callback. Zero interaction is a capture-architecture decision made on day one.
2. **The haptic waits only for the disk.** "Captured" (S1) means the page bytes are F_FULLFSYNC'd, atomically renamed, and the ledger row is committed. Target: at most 500 ms after the page settles on A17-class phones, 700 ms on the iPhone 13 floor device. These are estimates; Apple publishes no Vision latency numbers, so Phase 0 is a two-week measurement harness that replaces every estimate with measured p50/p95 before any number is promised.
3. **No duplicate signal ever suppresses a capture.** A synthetic calibration run showed every image hash puts this month's and last month's statement from the same bank inside the same-page distance band. So "already scanned" is announced in two beats: a visual hint within ~50 ms, confirmed or retracted within ~1 s by fast on-device OCR text plus two agreeing parsed fields (date, amount, account last-4, "Page N of M"). Duplicates become catalog relations, never drops, and a text-confirmed duplicate skips its own Claude call.
4. **Page is the unit of capture and durability; document is the unit of understanding.** Consecutive pages are grouped by an on-device scorer biased toward splitting (a wrong split never hides a page), and Claude's per-page call returns the boundary verdict for free because each open document is one prompt-cached Haiku conversation.
5. **Vision for geometry and text, Claude for meaning.** Two on-device OCR passes per page: a raw fast pass (language correction off, so "C001" is not corrected to "cool") for dedup anchors and the instant label, and an accurate pass for the PDF text layer and the search index. Claude 5.5 models transcribe as well as specialist OCR but return no word boxes, so they are the field extractor and a line-indexed corrector, not the transcriber.
6. **Claude Haiku 5.5, thinking off, effort low, structured output, streamed, doc_type first.** One call per page with a masked 1,100 px JPEG plus the OCR lines, appended to the document's cached conversation. Sonnet 5.5 only on refusal or low confidence; Opus has no role. Inline Messages API only (Batches and Files are not zero-data-retention eligible). Cost per fully understood page: $0.0003 to $0.0008 list; a 1,000-page-per-month user costs well under $1 in AI.
7. **12 MP stills with a framing gate, not 24 or 48 MP.** 24 MP on iPhone is only delivered via deferred processing into the Photos library; 48 MP "can take several seconds". 12 MP reaches the FADGI print-ready bar (294 ppi) on Letter when the page fills at least 78% of the frame's long axis, so the auto-capture state machine simply waits for that framing. 48 MP is a stand-mode option.
8. **An in-house PDF/A-2u writer** (one JPEG per page plus an invisible glyphless text layer from Vision's word boxes, XMP metadata, deterministic IDs so re-emission is byte-identical), validated by veraPDF in CI. Apple's frameworks do not reliably write PDF/A; a one-day spike of the undocumented `kCGPDFContextCreatePDFA` flag is the fallback. Bytes are immutable; the filename is renamed after Claude lands.
9. **User-owned storage is the system of record; iCloud Drive is the default first off-device hop** (OS-managed upload that survives app deletion, visible in Files, end-to-end encrypted under Advanced Data Protection). Google Drive via the non-sensitive `drive.file` scope with SHA-256 verification; Synology via WebDAV over HTTPS with a publicly trusted certificate. A service-side encrypted relay bucket is an opt-in later, for users whose iCloud is full or who want the lock within seconds on LTE.
10. **One three-class sensitive-data policy.** Full SSNs, account, routing, card and ID numbers exist only inside the archival PDF in the user's storage; everywhere else (the Claude request, the index, Spotlight, sidecars, filenames, logs) carries last-4 placeholders produced by one on-device mask pass over Vision's word boxes. A CI canary test asserts synthetic secrets never appear in any outbound payload.

## What nobody ships today

Sixty products were surveyed. Adobe Scan (premium "High-speed scan"), Genius Scan (batch auto-capture) and a Google Drive Labs experiment on Android already auto-capture pages. **No app chains documents without a Done tap, detects re-scans, understands and routes the document, or delivers verified copies to several user-owned destinations.** The market is consolidating (Microsoft Lens scanning disabled March 2026; Evernote Scannable unmaintained and paywalled). Paperless-ngx 3.0 has opt-in LLM features but is a self-hosted server; it should be a destination for this app, not a competitor.

## Numbers you should plan with

| Item | Figure | Status |
|---|---|---|
| Page settled to haptic | 500 ms (A17+), 700 ms (A15) | target, unmeasured |
| Visual "looks like a duplicate" hint | +5 to 30 ms after the still | target |
| Text-confirmed duplicate and provisional label | under 1 s | target |
| Accurate OCR + text layer (asynchronous) | 1 to 3 s (A18), 2 to 6 s (A15) | estimate from one third-party iPhone 16 measurement |
| Claude record (asynchronous) | first token 0.5 to 1.5 s, full record ~3 s on Wi-Fi | estimate; thinking-off Haiku latency is unpublished |
| Lock (first verified remote copy) | seconds on Wi-Fi, minutes on LTE | OS-managed, no SLA |
| AI cost per page, Haiku 5.5 | $0.0003 to $0.0008 | computed from list prices |
| Blended cost per document with 10% Sonnet escalation | about $0.002 | computed |
| Managed subscription price | $49.99/yr or $5.99/mo | recommendation; COGS under 10% of net |
| Solo-developer timeline | v0 personal ~8 weeks, TestFlight ~14, App Store ~22 weeks, service ~9 months | estimate, after a 2-week measurement phase |

## What I need from you

Details in `06-decisions-and-needs.md`. The short list: an Anthropic Console key with a spend limit (the Phase 0 harness needs it), the four test iPhones (13, 15 Pro, 16, 17 Pro) or whatever subset you own, about 200 pages of your real mail with typed ground truth, your Synology DSM version and whether it can get a public certificate, and seven decisions where I have a recommended default.

## Name

Full shortlist with domain, App Store and trademark checks in `05-names.md`. My recommendation: **Papersieve** (all four domains free, no App Store or trademark hits) if you want a clean start, or **Papershed** (the best name, .app/.io/.ai free, .com held since 1999 by an unrelated business) if you are willing to live without the .com. Backups: Quietpaper, Afterpaper, Mailshed. The GitHub repository gets created once you pick.

## How this research was done, and its limits

Seventy agents ran over about four hours: 14 research dimensions, each fact-checked by an adversarial agent and critiqued by a second one; a completeness pass that produced 10 gap questions, each researched and fact-checked; three independent architecture proposals (speed-first, local-first/privacy, service-scale) scored by two judges; and a naming round with an adversarial re-check. Both judges chose the speed-first proposal as the backbone and named specific grafts from the other two; `02-architecture.md` is that synthesis. Ten claims were refuted and corrected (`research/CORRECTIONS.md`). One limit to know about: the shared web-search budget ran out about a third of the way through, so most later agents worked from directly fetched primary sources (Apple documentation, vendor docs, papers, pricing pages) rather than search. That is better evidence, but a few items could not be fetched (notably Synology's JavaScript-rendered knowledge base) and are marked unknown. Every latency figure is tagged measured, vendor claim, or estimate; nothing in this plan should be quoted externally until Phase 0 measures it on your devices.

## Next steps

1. You read `02-architecture.md` and `06-decisions-and-needs.md`, pick a name, and answer the seven decisions (or accept the defaults).
2. I create the GitHub repository under the chosen name and move this planning folder there.
3. Phase 0 starts: the measurement harness on your phones and `tools/haiku_hot_path_bench.py` on your 200 pages with your key.
