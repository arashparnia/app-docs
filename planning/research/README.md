# Raw research reports

These are the unedited outputs of the research agents (2026-11-03). They are the evidence base for `../02-architecture.md` and `../03-research-findings.md`, which supersede them wherever they disagree. Each report was fact-checked by an adversarial agent and critiqued by a second agent; `CORRECTIONS.md` lists the ten claims that were refuted, with corrections and evidence URLs, plus the claims that could not be confirmed from a primary source. Read the raw reports for depth and sources; read the synthesized documents for the decisions.

| File | Dimension |
|---|---|
| `capture.md` | Hands-free continuous capture on iPhone |
| `ocr.md` | OCR and document-understanding model landscape |
| `claude.md` | Claude API pipeline design |
| `dedup.md` | Duplicate detection and multi-page grouping |
| `competitors.md` | Competitive landscape and gap analysis |
| `storage.md` | Durable delivery to iCloud Drive, Google Drive, Synology |
| `output.md` | Print-ready archival searchable PDF on iOS |
| `search.md` | Search architecture |
| `architecture.md` | End-to-end architecture and latency engineering |
| `privacy.md` | Privacy, security, legal, compliance |
| `business.md` | Business model, unit economics, roadmap |
| `mail.md` | Physical-mail specifics, taxonomy, boundary detection |
| `apple.md` | Apple platform capability matrix |
| `ingest.md` | Digital ingestion and the action layer |
| `gap-1` … `gap-10` | Second-round reports on the questions the completeness critic found unanswered: document boundaries, dedup signal safety, on-device latency budget, the "captured" state machine, per-destination verify and rename protocols, the Haiku hot-path measurement plan, the text-layer source, the instant on-device label and iOS floor, print-ready page geometry, and the sensitive-data policy |

Known weaknesses of the raw reports, already corrected in the synthesized documents: several use a 64-bit hash to suppress capture (unsafe); several treat Apple Foundation Models as accepting images on iOS 26 (iOS 27 only); the OCR latency figures quoted from the `text_sight` plugin's old docs are superseded by its 1.0.0 measurements; the business report uses the legacy pixels/750 image-token formula; the storage report's escrow bucket and the Apple report's CloudKit first hop are not in the plan; the ingest report's reliance on Cloudflare `setReject` for retries is wrong (it is a permanent bounce).
