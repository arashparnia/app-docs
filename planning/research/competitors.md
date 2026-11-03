# Competitive Landscape and Gap Analysis: Document Scanning and Personal Document Management (as of 2026-11-03)

Research dimension: competitors. Audience: founder of a zero-interaction, hands-free, AI-understood, multi-destination paper digitizer (iOS first, Claude as primary AI).

Method: ~45 web searches plus direct fetches of vendor pages, App Store listings, GitHub releases/docs, help centers and datasheets. All fetched content was treated as untrusted data. Numbers are labeled **measured** (independent test), **vendor claim**, or **listing** (App Store / pricing page). "Unknown" means I could not find a primary source.

---

## 1. Executive summary

1. Nobody ships the founder's product. Every consumer scanner app still requires per-page or per-document taps; the closest things to "hold phone, flip pages, walk away" are Adobe Scan's Premium "High-speed scan" and a Google Drive **Workspace Labs** experiment (Android only, Sept 2025) that auto-starts and auto-adds pages.
2. The mainstream scanner market is consolidating: Microsoft Lens was killed (scanning disabled 2026-03-09); Evernote Scannable is unmaintained since 2024-12-19 and now paywalled ($49.99/yr); CamScanner is ad/subscription-heavy with a lingering privacy stigma.
3. "Understanding" (classification, entity extraction, semantic search) exists only in silos: receipt/bookkeeping tools (Dext, Veryfi, Expensify) understand receipts only; self-hosted DMS (Paperless-ngx 3.x) understands everything but needs a server and a separate scanning app; DEVONthink is Mac-only.
4. No consumer scanner app writes to Google Drive + iCloud + Synology/WebDAV simultaneously with a durability guarantee; auto-export is a paid tier in Genius Scan and absent in Scanner Pro's free tier.
5. Paperless-ngx 3.0 (July 2026) added native AI (OpenAI-compatible / Ollama only, no Anthropic backend), Azure remote OCR, Tantivy search, versioning and duplicate detection, making it the benchmark for "understanding" and the natural NAS destination to integrate with, not compete with.
6. Hardware (ScanSnap iX1600, Brother ADS-1800W, CZUR ET25 Pro) wins on throughput (30-40 ppm, 1.5 s/page overhead) but requires a desk; on-phone speed benchmarks from an interested vendor put Adobe Scan at 2-4 s and Genius Scan at 1-3 s per page.
7. Mail-scanning services (Stable, PostScan Mail, LegalZoom Virtual Mail ex-Earth Class Mail) charge $10-$299/mo and do have AI summaries/categorization, but at human-mailroom latency (hours to days), and USPS Informed Delivery exposes no public image API.
8. The defensible wedge: on-device detect/dedupe/capture at sub-second cadence, Claude-based understanding, user-owned multi-destination storage with a write-ahead durability model, and natural-language search. Ideas worth stealing: Drive Labs' auto-add-page loop, Adobe's tilt-pause feedback, Paperless' ASN/duplicate hashing, Genius Scan's rules-based auto-export, Stable's AI mail summaries.

---

## 2. Findings

### 2.1 Consumer mobile scanner apps

**Adobe Scan (iOS/Android).** Listing: 4.9 stars / 1.6M ratings, v26.10.19, iOS 18+. Auto capture mode toggled by an "A" icon beside the shutter (Adobe community reply). Premium adds "High-speed scan": a countdown, then "place pages in front of the camera one at a time, and the app detects and captures each one automatically"; it is "AI-powered," prompts you to tilt the device if the angle is wrong and pauses until corrected (Adobe iOS/Android docs). Free OCR is capped at 5 pages/scan, Premium 100 (Jan 2026 Android release notes). IAP listing is messy: Premium Monthly $9.99, Plus Monthly $4.99 / Yearly $19.99, "Scan premium - monthly" $14.99. Complaints: must sign into an Adobe account before scanning one page; cloud-first upsells; 200-300 MB install and battery drain. Vendor-interested test (MiOffice) measured 2-4 s processing per page and 24/25 edge detections.
Sources: https://apps.apple.com/us/app/adobe-scan-pdf-ocr-scanner/id1199564834 ; https://www.adobe.com/devnet-docs/adobescan/android/en/releasenotes.html ; https://unstar.app/blog/adobe-scan-camscanner-microsoft-lens-genius-scan-swiftscan-pdf-scanner-apps-ranked-2026 ; https://mioffice.ai/blog/best-document-scanner-free-2026

**Microsoft Lens.** Retired: "retired from iOS and Android devices starting January 9, 2026," unsupported after Feb 9, removed from stores Feb 9, "continue to scan ... until March 9, 2026." Microsoft recommends the OneDrive app's built-in scanner (scans can't be saved locally). Replacement gaps: no batch reorder, Microsoft-ecosystem export only. Source: https://support.microsoft.com/office/microsoft-lens-for-ios-fbdca5f4-1b1b-4391-a931-dc1c2582397b

**CamScanner (INTSIG).** Listing: 4.8 / ~2M ratings, iOS 15+, v7.28.5. IAP: Premium 1 year $59.99, 1 month $9.99, 1 week $9.99. Batch scanning exists but "Batch scanning a 20-page document means watching 20 ads" on free tier; all processing cloud-side (3-6 s/page in MiOffice test); App Privacy lists Identifiers and Usage Data "used to track you"; billing complaints (weekly plan silently converting to annual). Sources: https://apps.apple.com/us/app/camscanner-pdf-scanner-app/id388627783 ; https://www.sikayetvar.com/en/camscanner-us

**Genius Scan (Grizzly Labs).** Pricing page: Basic free ("fully functional"), Ultra $39.99/yr (OCR, export to all clouds, cloud backup, web access), Teams $20-40/license/yr. "Hand free scanning: Your documents are auto-detected and snapped for you handsfree!" and "Batch mode: Quickly scan dozens of pages in a row." Export: Google Drive, Dropbox, OneDrive, Box, Evernote, WebDAV (Synology/Nextcloud via WebDAV), FTP/SFTP/FTPS; iCloud Drive not listed; auto-export ("as soon as they're created") is only on Enterprise/Lifetime Plus/Ultra. OCR is on-device. Complaints: edge detection misses dark/low-contrast docs; crashes on 30-50 page docs; Plus purchase doesn't carry across platforms. Listed by the Paperless-ngx wiki as a recommended uploader. Sources: https://thegrizzlylabs.com/genius-scan/pricing ; https://help.geniusscan.com/exporting-and-sharing/comparison-of-export-methods-by-plan ; https://help.geniusscan.com/exporting-and-sharing/service-specific-guides/export-via-webdav

**Scanner Pro (Readdle).** Listing: 4.9 / 338K, v9.0.3 (Liquid Glass redesign), iOS 18+; Scanner Pro Plus IAPs $3.99-$59.99 (reported $19.99/yr). Auto-capture "fires when the document is steady and edges are detected"; v8.34 (March 2026) moved color enhancement to a neural-net pipeline, "All three stages run on-device, using Apple's Neural Engine"; Auto Color Detection is Plus-only. Export: Dropbox, Evernote, Google Drive, Box, iCloud Drive, OneDrive, OneNote, WebDAV. Smart Categories (receipts/invoices/forms) date from ~2021; "Auto Name" from content. No timing numbers published. Sources: https://apps.apple.com/us/app/scanner-pro-ocr-scanning-fax/id333710667 ; https://readdle.com/blog/why-scanner-pro-scans-look-better-than-ever

**SwiftScan (ex-Scanbot).** Listing: 4.8 / 19K, iOS 15+, v9.6.82. IAP: Plus Annual $59.99, VIP Annual $34.99, Plus Monthly $7.99-9.99; lifetime deals $41.99-$59.99 via StackSocial. Auto edge detection and capture; AI summarize/translate; exports to iCloud Drive, Dropbox, Google Drive, Box, Evernote, WebDAV, FTP/SFTP/FTPS. Complaints: free tier "feels like a demo"; sync conflicts; one reviewer says auto-capture is "a little too quick" and misfires. Source: https://apps.apple.com/us/app/swiftscan-ai-document-scanner/id834854351 ; https://justuseapp.com/en/app/834854351/swiftscan-ai-scanner/reviews

**Evernote Scannable.** Still listed, free + IAP (Weekly $2.99, Yearly $49.99), last update v3.2.4 on 2024-12-19, iOS 16+. "Point your camera... Scannable immediately captures them." Reviews complain it now demands a paid plan and an Evernote account. Effectively abandoned. Source: https://apps.apple.com/us/app/evernote-scannable/id883338188

**Apple Notes / Files / Preview (iOS 26).** Notes and Files scan via VisionKit: "If your device is in Auto mode, your document will automatically scan"; multi-page; iOS 26 adds flash/filter options; a new Preview app offers "Scan Documents" and saves PDFs under Files > Preview. `VNDocumentCameraViewController` cannot have auto-capture customized ("no way to customize ... please file an enhancement request" - Apple DTS, early 2025). No classification, no destinations beyond iCloud/Files. Sources: https://support.apple.com/en-us/108963 ; https://developer.apple.com/forums/thread/772703 ; https://www.tomsguide.com/phones/iphones/ios-26-preview-7-features-to-explore-in-your-iphones-newest-app

**Google Drive scanner.** Nov 2023: Android got auto capture + viewfinder; iOS got scanner + ML "title suggestions" (US only). Sept 29, 2025 (9to5Google): a Workspace Labs test where "the Google Drive scanner begins scanning automatically," the manual/auto slider is removed, and "If the scanner sees a new page, it will scan it and add it to the file"; a multi-page legal doc "shrunk ... to a few seconds." Android-only so far; iOS availability unknown. Saves "searchable PDFs" to Drive. Sources: https://workspaceupdates.googleblog.com/2023/11/updates-to-google-drive-scanner-on-android-and-ios.html ; https://9to5google.com/2025/09/29/google-drive-testing-ai-scanner/ ; https://support.google.com/drive/answer/3145835

**Other scanner apps encountered.** PaperScan (DocuWare, free, "Automatically recognizes documents and triggers image capture," last update 2025-03-14); QuickScan (iSolid, free/donation, on-device OCR, "Export Favorites" with auto-delete after export, WebDAV + paperless-ngx destinations, 4.9 / 4.1K); Scan.Plus; MakeACopy (open-source Android, Show HN Oct 2025); "Scan & Convert to PDF" (Show HN Nov 2025). Sources: https://apps.apple.com/app/paperscan/id670210933 ; https://apps.apple.com/us/app/ocr-scanner-quickscan/id1513790291 ; https://hn.algolia.com/api/v1/search?query=document%20scanner%20app&tags=show_hn

### 2.2 Self-hosted document management

**Paperless-ngx.** v3.0.0 released 22 Jul 2026 (latest v3.4.1, 31 Oct 2026). Headline features: "Feature: Paperless AI" (opt-in; backends `openai-like` and `ollama` only; embeddings via openai-like/huggingface/ollama; sqlite-vec vector store; AI suggestions for title/date/tags/correspondent/type and RAG document chat), "Feature: Remote OCR (Azure AI)" (`PAPERLESS_REMOTE_OCR_ENGINE=azureai`, only engine), Tantivy replaces Whoosh, document file versions, parser plugin framework, duplicates allowed with warnings plus a Duplicates tab (`PAPERLESS_CONSUMER_DELETE_DUPLICATES` hash-based rejection). Docs warn "Paperless-ngx will send document content to the AI provider you have configured." No Anthropic backend; Claude would need an OpenAI-compatible proxy. Ingest paths: consume dir, email, REST API. No official mobile app. Sources: https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.0.0 ; https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/usage.md ; https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/configuration.md

**Paperless mobile/companion ecosystem.** Wiki lists Genius Scan, Less Paper (iOS, Show HN Aug 2026), OpenScan, Paperless Document Scanner, Paperparrot, QuickScan, Scanly, Swift Paperless (4.9 / 57), ScanToPaperless; plus Paperless Ingest (iOS 17+), Scannerless (queues failed uploads), Paperless Mobile (Flutter, Android, 1.5k stars, iOS "Publish to AppStore" unchecked), Paperless Go (Android). All are tap-to-scan, upload-one-document flows. paperless-ai (clusterzx) README: "This repo is currently not maintained"; paperless-gpt (icereed) uses LLM + LLM-vision OCR, last push May 2026, 147 open issues. receipthero-ng (Show HN Feb 2026) is a receipt processor for Paperless. Sources: https://github.com/paperless-ngx/paperless-ngx/wiki/Scanner-&-Software-Recommendations ; https://github.com/astubenbord/paperless-mobile ; https://cdn.jsdelivr.net/gh/clusterzx/paperless-ai@main/README.md ; https://gittrend.io/repo/icereed/paperless-gpt

**Papra.** AGPL-3, Docker image <200 MB (x86/ARM64/ARMv7), full-text search, rule-based auto-tagging, folder/email ingestion, API/SDK/webhooks/CLI. No AI classification, no mobile app. Source: https://github.com/papra-hq/papra ; https://docs.papra.app/

**Docspell / Teedy / Mayan EDMS.** Docspell (AGPL, personal organizer, needs a scanner feeding it); Teedy (Java/Elasticsearch, ~2.5k stars, hosted plan ~EUR 19/user/mo); Mayan EDMS (enterprise workflows/ACLs, ~800 stars, GPL/Apache reported inconsistently). None have a capture app or LLM understanding out of the box. Source: https://www.pistack.xyz/posts/2026-04-27-mayan-edms-vs-teedy-vs-docspell-self-hosted-document-management-2026/

### 2.3 Mac/iOS knowledge managers

**DEVONthink 4 / To Go 4.** Standard $99, Pro $199, Server $499, "two seats and one year of updates" (updates-subscription model). AI: connects to ChatGPT, Claude, Mistral, or local Ollama/LM Studio; summarization, tagging, NL search, built-in MCP server (May 2026 4.3 "Herschel"). To Go 4 (Dec 2025) scans from lock screen/Control Center into the database, with searchable output. Mac-centric; sync via its own encrypted stores; no Google Drive/Synology "destination" concept (databases, not files). Sources: https://devontechnologies.com/apps/devonthink/new ; https://www.devontechnologies.com/apps/devonthink ; https://www.macsparky.com/blog/2025/12/devonthink-to-go-4/

### 2.4 Receipt / bookkeeping capture

| Product | Capture | AI | Price (listing/claims) | Notes |
|---|---|---|---|---|
| Dext | mobile app, email, WhatsApp, upload; multi-page | "over 99% data accuracy" (vendor) | Business $31.50/mo monthly or ~$25.21/mo annual, 250 docs/mo, 5 users (third-party) | Receipts/invoices only; 250-doc cap and overages |
| Shoeboxed | app + mailed "Magic Envelope" (9x12 Tyvek) | human-verified data entry (claimed elsewhere) | Starter $9/mo (50 digital scans, 20 paper/yr), Pro $29, Plus $79, Paper Plus $179 | Mail-in is days-latency; receipts focus |
| Expensify SmartScan | tap photo | ~98-99% accuracy claims (unverified) | Collect $5/member/mo; free SmartScan quota reported as 25/mo or unlimited (conflicting) | Expense reports only |
| Hubdoc | app/email/scanner | key-field extraction | included with Xero plans | Xero adding native AI capture (UK, Feb 2026) |
| Veryfi API | API | receipts/invoices/W-2/checks | Free 100 docs/mo; Starter $500+/mo; $0.08/receipt, $0.16/invoice, $0.25/statement; "Blazing Fast" but no latency figure | Developer backend, not consumer |
| Klippa DocHorizon | API | IDP | ~EUR 0.04/doc (unverified); quote-based | Acquired by SER (Mar 2025); renamed **Doxis AI.dp** 2026-03-30 |
| SparkReceipt | app, email, IMAP pull | "ChatGPT AI model" extraction | Free 15 docs/mo; Pro $6.58/mo annual ($9 monthly); Elite $12/mo | Small-business receipts |

Sources: https://dext.com/en/business/product/capture-receipts-and-invoices ; https://costbench.com/software/accounting/dext/ ; https://www.shoeboxed.com/pricing ; https://leadchangegroup.com/software/expensify/pricing/ ; https://community.expensify.com/discussion/comment/16489 ; https://www.xero.com/uk/accounting-software/capture-data-with-hubdoc/ ; https://www.veryfi.com/pricing/ ; https://www.klippa.com/en/newsroom/klippa-is-now-doxis/ ; https://sparkreceipt.com/comparison

**FileThis** (auto-fetch of statements) shut down 2023-10-01 per AlternativeTo/MyMoneyBlog; no 2025-26 revival found. Source: https://alternativeto.net/software/filethis/about

### 2.5 Hardware scanners

| Device | Speed (vendor) | Price (listing) | Auto classification / destinations |
|---|---|---|---|
| Ricoh/PFU ScanSnap iX1600 | 40 ppm / 80 ipm, 50-sheet ADF | ~$473-$554 US list (2026 snapshots) | ScanSnap Home groups into documents/receipts/business cards/photos, learned file naming; ScanSnap Cloud routes by type to 10+ cloud services; proprietary, no TWAIN |
| Brother ADS-1800W | 30 ppm / 60 ipm (PCMag measured 34.0 ppm / 67.2 ipm), 20-sheet ADF | $324.99 (brother-usa) | Scan-to OneDrive/Google Drive/Dropbox via iPrint&Scan; OCR "scan to" |
| Epson ES-C320W | 30 ppm / 60 ipm, 20-sheet ADF | $249.99-$329.99 | basic |
| Doxie Pro | "22 pages per minute," 20-page ADF, wired | not listed | OCR, searchable PDF; Doxie Go SE battery portable; Doxie Flip discontinued 2020 |
| CZUR ET25 Pro (overhead) | "1.5 sec. per scan for single or dual facing pages," 25 MP, 330 dpi | unknown (datasheet) | "Auto-Scan with page-turn detection," ABBYY OCR, finger removal with finger cots, hand button/foot pedal |

Sources: https://www.pfu.ricoh.com/global/scanners/scansnap/sshome/ ; https://scansnapofficial.com/ ; https://www.brother-usa.com/products/ads1800w ; https://epson.com.au/products/scanner/WorkForceES-C320W_Specs.asp ; https://www.getdoxie.com/product/doxie-pro ; https://www.scannx.com/hubfs/docs/data_sheets/CZUR_ET25_Pro_Scanner.pdf

Relevance: CZUR proves "turn the page, it scans" with a fixed overhead camera is a solved UX at 1.5 s cadence; the founder's app is a handheld software version of that.

### 2.6 Mail-scanning services and USPS

| Service | Price | What you get | AI |
|---|---|---|---|
| Stable | Grow $49/mo (yearly; 360 pieces/yr), Scale $83/mo (600/yr); $3/piece overage | auto open-and-scan rules, 30-day storage, API/webhooks, Dropbox/Slack/Zapier | "AI summaries" on all plans; AI routing/extraction/categorization on Custom; blog: transcription "often in seconds," human-in-the-loop when low confidence |
| PostScan Mail | Starter $10/mo (30 items), Standard $20, Premium $30; Business $100-$600 | exterior scan on arrival; open-and-scan $2/envelope up to 10 pages then $0.25/page | "AI Mail Summary: 10 free summaries per month, then $0.25" |
| LegalZoom Virtual Mail (Earth Class Mail "is now part of LegalZoom") | Starter $39/mo (5 items digitized), Essentials $59 (25), Premium $119 (50), MailRoom $179-$299 | 20 pages/item free then $0.15/page; API | none stated |
| Anytime Mailbox | ~$9.99/mo entry; per-location pricing; open-and-scan $0.25-$1.00/page | franchised locations | none |
| USPS Informed Delivery | free | grayscale exterior images of letter mail, 7-day retention | no public developer API found |

Sources: https://www.usestable.com/pricing ; https://www.usestable.com/blog/how-stable-uses-ai-for-faster-mail-processing ; https://www.postscanmail.com/pricing ; https://www.legalzoom.com/business/business-operations/lz-virtual-mail-overview.html ; https://venturesmarter.com/anytime-mailbox-review/ ; https://www.usps.com/manage/informed-delivery.htm

### 2.7 New AI-native personal document apps (2025-2026)

- **MyAttic** (EU): capture by forwarding to WhatsApp/Telegram/Email/Messenger ("No new apps"); optional AI categorization + OCR; storage in MyAttic EU vault, Google Drive or Dropbox; Pro EUR 5/mo, Family EUR 14, Team EUR 29. No camera capture. https://myattic.ai/
- **Filex AI**: web/iOS/Android; OCR, files by person/property/project, extracts amounts/dates/deadlines, plain-English search; 10 files free then $7.99/mo or $44.99/yr. Built-in scanner but no hands-free capture. https://filexai.com/blog/best-ai-document-management-apps
- **Zush** (Mac/Windows desktop): watches a scanner/Downloads folder, AI renames with templates, sorts into local folders; local models via Ollama/LM Studio or own API key; $10/mo or $48 one-time. https://zushapp.com/blog/best-ai-document-organizers
- **Nominate** (open-source macOS, Feb 2025): local-model PDF renaming. https://github.com/NSHipster/Nominate
- **NameQuick, Wisfile, Sortio, Sorto, Clocr, Sortifyd, Trustworthy**: file-renamers or vaults; none does hands-free capture.
- **Scan2Sheet** (Show HN Jun 2026): receipt photo to Google Sheets row. https://www.scan2sheet.com
- **ScanBox** (archived Apr 2026): "turns a network scanner into a hands-free document digitization station," splits mixed stacks into documents. https://github.com/jflammia/scanbox

### 2.8 Speed: what is actually known

- Only independent-ish per-page numbers: MiOffice (vendor of a competing tool) lists Adobe Scan 2-4 s, Lens 1-3 s, CamScanner 3-6 s, Genius Scan 1-3 s processing per page; sample 25 documents. https://mioffice.ai/blog/best-document-scanner-free-2026
- CZUR: 1.5 s per capture (vendor datasheet). ScanSnap: 40 ppm = 1.5 s/page (vendor).
- Google Drive Labs: multi-page doc "to a few seconds" (journalist anecdote).
- Readdle: on-device Neural Engine pipeline but publishes no ms figures.
- No app publishes "already scanned" duplicate-detection latency; Paperless-ngx dedupes by file hash after upload (seconds to minutes server-side), not perceptually at capture time.

---

## 3. Options compared

| Product | Capture | Hands-free multi-page | AI understanding | Destinations | Search | Export | Price | Platform | Top complaint |
|---|---|---|---|---|---|---|---|---|---|
| Adobe Scan | auto/manual | Premium High-speed scan | OCR, straighten, eraser; no classification | Adobe Cloud; share out | text in Adobe cloud | PDF, Word/Excel/PPT | free; $4.99-$14.99/mo | iOS/Android | forced login, upsells |
| Microsoft Lens | - | - | - | - | - | - | retired Mar 2026 | - | gone |
| CamScanner | auto/manual, batch | no | OCR, "AI search" | Drive/Dropbox/Evernote/OneDrive (paid) | cloud | PDF/JPG | $9.99/mo, $59.99/yr | iOS/Android/Mac | ads, tracking, billing |
| Genius Scan | auto ("handsfree") + batch | batch mode (still per-doc) | on-device OCR, smart rename | Drive, Dropbox, OneDrive, Box, WebDAV/Synology, FTP/SFTP; auto-export paid | tags + text | PDF/JPG | free; Ultra $39.99/yr | iOS/Android | edge detect on dark docs, crashes >30 pp |
| Scanner Pro | auto when steady | no | on-device OCR, Smart Categories, Auto Name | iCloud, Drive, Dropbox, Box, OneDrive, Evernote, WebDAV | full-text | PDF/JPG, fax | free; Plus ~$19.99/yr | iOS | Plus-gated features |
| SwiftScan | auto edge | no | OCR, AI summarize/translate | iCloud, Drive, Dropbox, Box, WebDAV, (S)FTP | text | PDF/JPG | $34.99-$59.99/yr | iOS/Android/Mac | demo-like free tier, sync conflicts |
| Apple Notes/Files/Preview | auto/manual | no | Live Text search in Notes | iCloud/Files | Notes search | PDF | free | iOS | no classification, no routing |
| Google Drive (Labs) | fully automatic | yes, auto-add pages (Android Labs) | title suggestions (US) | Google Drive only | Drive OCR | PDF/JPG | free | Android (iOS unknown) | single destination |
| Evernote Scannable | auto | no | none | Evernote | - | PDF/JPG | $49.99/yr | iOS | abandoned, paywalled |
| Paperless-ngx 3.x | n/a (server) | n/a | OCR + ML + opt-in LLM suggestions/chat, Azure OCR | self-hosted store | Tantivy FT + semantic | PDF/archive, sharelink bundles | free | server + 3rd-party apps | needs server + separate scanner app |
| DEVONthink 4 | To Go scan | no | AI chat/tagging incl. Claude, MCP | its databases | strong | many | $99-$499 | Mac/iOS | Mac-centric, not file-destination based |
| Dext / Expensify / Shoeboxed | tap | no | receipts only | accounting systems | by field | CSV/exports | $5-$179/mo | iOS/Android/web | not for general mail |
| ScanSnap iX1600 | sheet-fed | yes (ADF) | type detection, learned naming | ScanSnap Cloud -> 10+ clouds | ScanSnap Home | PDF/JPG | ~$500 | desk | proprietary software |
| CZUR ET25 Pro | overhead, page-turn detect | yes | ABBYY OCR | PC/Mac | - | PDF/Word | unknown | desk | fixed station |
| Stable / PostScan Mail | mailroom scans | n/a | AI summaries; categorization at Custom tier | app, Dropbox, API | basic | PDF | $10-$299/mo | web | days latency, business pricing |
| MyAttic / Filex AI | forward or upload | no | LLM categorization/extraction | own vault, Drive/Dropbox | NL search | download | EUR 5 / $7.99 per mo | web/mobile | no camera workflow |

---

## 4. Recommendation for this project

1. **Build the capture loop nobody has shipped on iOS.** Target the Google Drive Labs/CZUR interaction model, handheld: continuous `AVCaptureSession` + on-device rectangle/sharpness detection, auto-capture when stable, auto-advance on page change, no shutter, no "Add page" button. Do not use `VNDocumentCameraViewController` (auto-capture not configurable, modal UI, per-document flow). Make "already scanned" a perceptual-hash check on the capture thread (<100 ms), announced by haptic + voice, a feature no competitor exposes at capture time.
2. **Ship speed numbers.** Every competitor hides latency. Publish a measured p50/p95 "page in frame -> confirmed captured" and "captured -> durable" on the website; this alone differentiates against Adobe (2-4 s) and CamScanner (3-6 s, cloud).
3. **Position as a front-end to the user's storage, not another cloud.** Lock-in and forced accounts are the #1 complaint for Adobe and CamScanner; Genius Scan charges for auto-export. Make multi-destination auto-export (Google Drive, iCloud Drive, Synology via WebDAV/SMB, plus optional Paperless-ngx consume/API) free and default, with a local write-ahead journal so "captured" means "durably persisted locally, with cloud fan-out retried until acknowledged."
4. **Use Claude for understanding, Vision for OCR.** Apple on-device Vision OCR (already proven by the founder) gives the searchable text layer in ~sub-second; send text (plus a downscaled page image only when needed) to Claude for classification, entities, tags, summary and a canonical file name. Structured JSON output with a document taxonomy modeled on Paperless (correspondent, type, tags, date, ASN). Emit sidecar JSON + the PDF so NAS/Drive users can grep it, and offer a Paperless-ngx post-consume integration rather than competing with it.
5. **Search as a product surface.** Local full-text (SQLite FTS5) + embeddings for "all my tax documents for 2024"; this is DEVONthink/Paperless-grade search that no scanner app has. Keep the index on-device and in the user's storage (export the index), never only on your server.
6. **Pricing posture.** Free unlimited capture/OCR/export; charge for AI understanding and search (BYO Anthropic key as a tier, like DEVONthink/Paperless, plus a managed tier). Avoid weekly plans and trial-to-annual conversions (CamScanner's reputational damage).
7. **Do not chase**: mail-service integration (no USPS API; mailroom vendors are B2B), receipt accounting integrations (Dext/Expensify own it), Android first (iOS Neural Engine + VisionKit maturity; Drive Labs already covers Android casual users).

---

## 5. Risks and unknowns

- **Google may ship the Labs auto-scanner broadly, including iOS** (status unknown as of Nov 2026). It would own the "free, automatic, Drive-only" quadrant; the defense is multi-destination, understanding and search.
- **Apple could add auto-advance to VisionKit/Preview** in iOS 27; Sherlocking risk for the capture loop alone, not for the understanding/search layer.
- **Per-page latency figures are vendor-interested** (MiOffice) or anecdotal; the founder should benchmark Adobe, Genius Scan, Scanner Pro and Notes on the same device before claiming "faster than anything."
- **Claude cost/latency per page** is not in this report's scope; it determines whether understanding runs synchronously or as a background queue (recommend background with local-first durability).
- **Paperless-ngx AI uses only openai-like/ollama backends**; a Claude integration there requires a proxy or a contributed backend.
- **Pricing data** for Adobe, Dext, Expensify and Anytime Mailbox conflicts across sources and regions; treat as ranges.
- **Hash-based dedupe** (Paperless) will not catch a re-scan from a different angle; a perceptual/text-similarity dedupe is required and is untested at phone frame rates.
- **Trademark-dense namespace** (see list below): "Scan", "Paperless", "Doc", "Snap" are heavily used.

---

## 6. Open questions for the founder

1. Is iOS 18 the floor (Adobe/Readdle) or iOS 17 (Paperless Ingest)? This decides which Vision/VisionKit APIs are available.
2. Should the app integrate with Paperless-ngx (upload via API/consume dir) as a first-class destination? It is the most active "understanding" ecosystem and its users are vocal early adopters.
3. Is a BYO-Anthropic-key tier acceptable for the App Store product, or must every user go through a managed key?
4. What is the acceptable cloud fan-out delay for "guaranteed captured": local persistence only (ms) or at least one remote acknowledgment (seconds)?
5. Which NAS protocol: WebDAV (Genius Scan's Synology path), SMB (Files app network shares), or Synology Drive API?
6. Is on-device dedupe limited to the current session, or across the whole archive (requires a local index of every page's hash/embedding)?
7. Should receipts route to accounting tools (Dext/Expensify) or stay generic?

---

## 7. Product names encountered (for trademark avoidance)

Adobe Scan, Adobe Acrobat, Adobe Document Cloud, Microsoft Lens (Office Lens), Microsoft 365 Copilot, OneDrive, CamScanner, CamScan, Genius Scan, Genius Cloud, Grizzly Labs, Scanner Pro, Readdle, SwiftScan, Scanbot, Evernote, Scannable, Apple Notes, Files, Preview, VisionKit, Live Text, Google Drive, Gemini, Workspace Labs, Paperless-ngx, Paperless-ng, Paperless AI, paperless-ai, paperless-gpt, Paperless Mobile, Paperless Go, Paperless NGX Uploader, Paperless Ingest, Paperless Document Scanner, Paperless 24, Paperparrot, Less Paper, Swift Paperless, Scanly, Scannerless, ScanToPaperless, OpenScan, QuickScan, PaperScan, DocuWare, Scan.Plus, Scan & Convert to PDF, MakeACopy, Online Document Scanner, DocScan AI, Ai Scanner, Document Scanner Fast, Papra, Docspell, Teedy (Sismics Docs), Mayan EDMS, Papermerge, OpenKM, ecoDMS, Tabbles, TagSpaces, DEVONthink, DEVONthink To Go, DEVONagent, Dext (Receipt Bank), Dext Solo, Shoeboxed, Magic Envelope, Expensify, SmartScan, Hubdoc, Xero, Veryfi, Klippa, DocHorizon, Doxis, Doxis AI.dp, SER Group, SparkReceipt, FileThis, ScanSnap, ScanSnap Home, ScanSnap Cloud, iX1600, iX1400, iX1300, Brother ADS, iPrint&Scan, Epson WorkForce, Doxie, Doxie Go, Doxie Pro, Doxie Flip, Doxie Q, CZUR, ET25 Pro, ET24 Pro, ET Max, Shine Ultra, ScannX, Earth Class Mail, LegalZoom Virtual Mail, PostScan Mail, Stable, Anytime Mailbox, iPostal1, US Global Mail, Informed Delivery, MyAttic, Filex AI, Zush, Nominate, NameQuick, Wisfile, File Juggler, Sortio, Sorto, Sorted AI, Sortifyd, Clocr, Trustworthy, Scan2Sheet, Parsie, ScanBox, receipthero-ng, Nanonets, MiOffice AI, Unstar, Kintsugi Mail, Mail Unmerge, Notion, Dropbox, Box, Evernote, OneNote, Nextcloud, Synology.

---

## 8. Sources

- https://apps.apple.com/us/app/adobe-scan-pdf-ocr-scanner/id1199564834
- https://www.adobe.com/devnet-docs/adobescan/android/en/releasenotes.html
- https://community.adobe.com/questions-6/charged-for-2-subscriptions-on-a-7-day-free-trial-1554478
- https://support.microsoft.com/office/microsoft-lens-for-ios-fbdca5f4-1b1b-4391-a931-dc1c2582397b
- https://apps.apple.com/us/app/camscanner-pdf-scanner-app/id388627783
- https://www.sikayetvar.com/en/camscanner-us
- https://thegrizzlylabs.com/genius-scan/pricing
- https://help.geniusscan.com/exporting-and-sharing/comparison-of-export-methods-by-plan
- https://help.geniusscan.com/exporting-and-sharing/service-specific-guides/export-via-webdav
- https://apps.apple.com/us/app/scanner-pro-ocr-scanning-fax/id333710667
- https://readdle.com/blog/why-scanner-pro-scans-look-better-than-ever
- https://readdle.com/blog/scanner-pro-smart-categories
- https://apps.apple.com/us/app/swiftscan-ai-document-scanner/id834854351
- https://justuseapp.com/en/app/834854351/swiftscan-ai-scanner/reviews
- https://apps.apple.com/us/app/evernote-scannable/id883338188
- https://support.apple.com/en-us/108963
- https://developer.apple.com/forums/thread/772703
- https://www.tomsguide.com/phones/iphones/ios-26-preview-7-features-to-explore-in-your-iphones-newest-app
- https://workspaceupdates.googleblog.com/2023/11/updates-to-google-drive-scanner-on-android-and-ios.html
- https://9to5google.com/2025/09/29/google-drive-testing-ai-scanner/
- https://support.google.com/drive/answer/3145835
- https://apps.apple.com/app/paperscan/id670210933
- https://apps.apple.com/us/app/ocr-scanner-quickscan/id1513790291
- https://hn.algolia.com/api/v1/search?query=document%20scanner%20app&tags=show_hn
- https://hn.algolia.com/api/v1/search?query=paperless&tags=show_hn
- https://github.com/paperless-ngx/paperless-ngx/releases
- https://github.com/paperless-ngx/paperless-ngx/releases/tag/v3.0.0
- https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/usage.md
- https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/configuration.md
- https://github.com/paperless-ngx/paperless-ngx/wiki/Scanner-&-Software-Recommendations
- https://github.com/astubenbord/paperless-mobile
- https://cdn.jsdelivr.net/gh/clusterzx/paperless-ai@main/README.md
- https://gittrend.io/repo/icereed/paperless-gpt
- https://apps.apple.com/app/swift-paperless/id6448698521
- https://apps.apple.com/us/app/-/id6758277408 (Paperless Ingest)
- https://github.com/papra-hq/papra
- https://docs.papra.app/
- https://www.pistack.xyz/posts/2026-04-27-mayan-edms-vs-teedy-vs-docspell-self-hosted-document-management-2026/
- https://devontechnologies.com/apps/devonthink/new
- https://www.devontechnologies.com/apps/devonthink
- https://www.macsparky.com/blog/2025/12/devonthink-to-go-4/
- https://dext.com/en/business/product/capture-receipts-and-invoices
- https://costbench.com/software/accounting/dext/
- https://www.shoeboxed.com/pricing
- https://leadchangegroup.com/software/expensify/pricing/
- https://community.expensify.com/discussion/comment/16489
- https://help.expensify.com/new-expensify/hubs/getting-started/Free-Features-in-Expensify
- https://www.xero.com/uk/accounting-software/capture-data-with-hubdoc/
- https://www.veryfi.com/pricing/
- https://www.klippa.com/en/newsroom/klippa-is-now-doxis/
- https://businesswire.com/news/home/20250318748542/en/SER-Group-Acquires-Intelligent-Document-Processing-Innovator-Klippa-to-Enhance-Next-Generation-Smart-Content-Platform
- https://sparkreceipt.com/comparison
- https://alternativeto.net/software/filethis/about
- https://www.pfu.ricoh.com/global/scanners/scansnap/sshome/
- https://scansnapofficial.com/
- https://frontdeskreview.com/product/document-scanners/ricoh-scansnap-ix1600/
- https://www.brother-usa.com/products/ads1800w
- https://tech.yahoo.com/computing/articles/brother-ads-1800w-225120623.html
- https://epson.com.au/products/scanner/WorkForceES-C320W_Specs.asp
- https://www.getdoxie.com/product/doxie-pro
- https://help.getdoxie.com/doxieflip/faq
- https://www.scannx.com/hubfs/docs/data_sheets/CZUR_ET25_Pro_Scanner.pdf
- https://www.usestable.com/pricing
- https://www.usestable.com/blog/how-stable-uses-ai-for-faster-mail-processing
- https://startupowl.com/reviews/stable
- https://www.postscanmail.com/pricing
- https://www.legalzoom.com/business/business-operations/lz-virtual-mail-overview.html
- https://venturesmarter.com/anytime-mailbox-review/
- https://www.usps.com/manage/informed-delivery.htm
- https://myattic.ai/
- https://myattic.ai/blog/best-personal-document-management-apps
- https://filexai.com/blog/best-ai-document-management-apps
- https://zushapp.com/blog/best-ai-document-organizers
- https://github.com/NSHipster/Nominate
- https://github.com/jflammia/scanbox
- https://mioffice.ai/blog/best-document-scanner-free-2026
- https://unstar.app/blog/adobe-scan-camscanner-microsoft-lens-genius-scan-swiftscan-pdf-scanner-apps-ranked-2026
- https://www.nicheloom.com/launches/45522/ (DocScan AI, Product Hunt Oct 2026)
