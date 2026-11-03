# Privacy, Security, Legal and Compliance — Research Report

Dimension: privacy / security / legal / compliance for a zero-interaction paper-digitizing iOS app (v1 personal, v2 App Store, v3 hosted service) that sends document images to the Claude API and writes archives to user-owned storage (iCloud Drive, Google Drive, Synology).

Research date: 2026-11-03. Method note: the shared WebSearch budget for this workflow run was exhausted before this agent started, so every finding below comes from direct fetches of primary sources (Anthropic/Apple/IRS/FTC/HHS/Cornell LII/Google docs). Items I could not fetch are marked **unverified** and come from training knowledge; treat them as leads, not facts.

---

## 1. Executive summary

1. The legal exposure of this product is driven by *what leaves the phone*, not by scanning itself. Keep the archival PDF, the search index and the raw photos on-device / in the user's own storage; send Claude only what it needs.
2. Anthropic API defaults are workable today: inputs/outputs are deleted within 30 days, never used for training, with SOC 2 Type II / ISO 27001 / ISO 42001 attestations ([retention](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-data), [training](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training), [certs](https://privacy.claude.com/en/articles/10015870-what-certifications-has-anthropic-obtained)).
3. Zero-data-retention (ZDR) and a self-serve HIPAA BAA exist for the Messages API, but the newest "Covered Models" (Fable 5.x / Mythos 5.x) *require* 30-day retention, and Files API / Batch / code execution are never ZDR- or HIPAA-eligible ([data retention doc](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)). Design the pipeline around inline Messages API calls only.
4. HIPAA does not apply to a consumer storing their own medical bills, but the FTC Health Breach Notification Rule (amended 2024) *does* reach non-HIPAA health apps once you host the data (v3) — up to $51,744 per violation ([FTC](https://www.ftc.gov/business-guidance/resources/health-breach-notification-rule-basics-business)).
5. App Store: privacy policy + nutrition labels, explicit consent before sharing personal data with "third-party AI" (Guideline 5.1.2(i), text updated 2025), in-app account deletion if you offer accounts, and the export-compliance declaration. BYO API key is not addressed by any guideline; it is widely used in shipping apps and is fine so long as the app is usable without it or it is clearly the core service.
6. IRS Rev. Proc. 97-22 explicitly permits destroying paper originals once an electronic storage system meets its integrity/indexing/legibility tests; Federal Rule of Evidence 1003 makes duplicates admissible unless authenticity is genuinely disputed. Keep vital records, wills, titles, notarized and bearer instruments as physical originals (practice-based, see §2.6).
7. Washington's My Health My Data Act has no revenue threshold and a private right of action; it is the single most dangerous state law for v2/v3 if you touch health data without consent flows.
8. For v3 hosted storage, a client-side-encrypted (user-held key) design removes most breach, CSAM-scanning and subpoena burdens, at the cost of server-side search and recovery. Recommended: E2E by default with an optional recovery key, server-side search only over client-encrypted index blobs.
9. Secure "shred" is trivially cheap on iOS (per-file AES keys; delete = crypto-erase), hard on Google Drive/Synology (trash, versioning, snapshots) — so the honest promise is "deleted from the app and requested from storage providers."
10. Priority checklist for v1 is small (Keychain, Data Protection, no analytics on document content). v2 adds the App Store paperwork and consent UX. v3 is where SOC 2, breach-notification plumbing and the 18 U.S.C. §2258A duties arrive.

---

## 2. Findings

### 2.1 Threat model and data minimization

**What is at stake.** Scanned mail contains SSNs, account numbers, medical codes, legal letters. The three realistic adversaries are (a) device theft while unlocked/locked, (b) compromise of any cloud hop (Claude, Google, Synology over WAN, your own server in v3), and (c) the developer's own telemetry/crash reporting leaking document text.

**On-device OCR before any cloud call.** Apple Vision OCR is on-device. `VNRecognizeTextRequest` has shipped since iOS 13; the newer `RecognizeDocumentsRequest` (document structure, tables, lists, detected data such as phone numbers/emails/dates) is iOS 26+ (**unverified**: Apple's doc page is JS-rendered and could not be read; this is from the WWDC25 session "Read documents using the Vision framework"). Both give word-level bounding boxes, which is what makes masking feasible: detect SSN (`\d{3}-\d{2}-\d{4}`), account-number, routing-number and MRN patterns on-device, black out those boxes in the *copy* sent to Claude, and keep the unmasked archival image local. This is the single biggest privacy lever in the design and costs ~0 latency because Vision OCR must run anyway for the duplicate check and text layer.

Trade-off: masking reduces Claude's extraction accuracy for exactly the fields that matter for search (last-4 of account). Compromise: send last-4 only, or send the masked image plus the on-device OCR text with sensitive tokens replaced by typed placeholders (`[SSN]`, `[ACCT-…1234]`).

**Encryption at rest (iOS).** Apple Data Protection assigns every file a 256-bit per-file key (AES-XTS on A14+/M1+) ([Apple Platform Security: Data Protection overview](https://support.apple.com/guide/security/data-protection-overview-secf6276da8a/web)). Classes ([Apple: Data Protection classes](https://support.apple.com/guide/security/data-protection-classes-secb010e978a/web)):

| Class | Constant | Key available | Use in this app |
|---|---|---|---|
| A Complete | `NSFileProtectionComplete` | only while unlocked; wiped ~10 s after lock | archival PDFs, OCR text, search DB |
| B Unless Open | `NSFileProtectionCompleteUnlessOpen` | can write while locked if opened before | upload queue files written in background |
| C Until First Auth | `NSFileProtectionCompleteUntilFirstUserAuthentication` | from first unlock after boot (default for 3rd-party apps) | nothing sensitive — this is the default, so set the class explicitly |
| D None | `NSFileProtectionNone` | always | never |

Caveat for "zero interaction + background upload": Class A files are unreadable when the phone locks, so a background `URLSession` upload must read from Class B/C staging files; keep staging files short-lived.

**Keychain.** `kSecAttrAccessibleWhenPasscodeSetThisDeviceOnly` items exist only in the system keybag, never sync to iCloud Keychain, are never backed up, and become unusable if the passcode is removed; "ThisDeviceOnly" variants are UID-wrapped during backup so a restore to another device cannot read them ([Apple: Keychain data protection](https://support.apple.com/guide/security/keychain-data-protection-secb0694df1a/web)). Store the Anthropic key, Google OAuth refresh token, Synology credentials and any database master key here. Secret keys require a Secure Enclave round trip and ACLs (biometric/passcode) are evaluated inside the Secure Enclave.

**SQLCipher.** AES-256-CBC per page, PBKDF2-HMAC-SHA512 with 256,000 default iterations, 4096-byte pages, HMAC-SHA512 per page ([SQLCipher design](https://www.zetetic.net/sqlcipher/design/)). Given Data Protection Class A already encrypts the database file, SQLCipher is mainly useful (a) for the search index you might ship to a NAS or Drive, and (b) as defense in depth against forensic extraction of Class C files. It also matters for export compliance (see §2.4).

**In transit.** TLS via `URLSession`; pin nothing (Apple discourages pinning for App Store apps and Anthropic rotates certs); do set `NSAppTransportSecurity` defaults and never disable ATS.

**End-to-end encryption for a hosted service (v3).** Options:

| Design | Search | Recovery | Breach/CSAM/subpoena exposure | Complexity |
|---|---|---|---|---|
| Server holds plaintext (encrypted at rest with provider KMS) | full server-side FTS + embeddings | password reset works | you are a PHR vendor/controller with everything that implies | low |
| Client-side encryption, user passphrase-derived key, no escrow | client-only; or encrypted index blobs synced | lose passphrase = lose archive (violates the "guaranteed digital copy" promise) | minimal | medium |
| Client-side encryption + recovery key (24-word / iCloud Keychain-stored) | as above | recovery via key, like Apple ADP | minimal | medium-high |
| Hybrid: E2E documents, server-side search over *client-generated* encrypted metadata + embeddings | server can rank over opaque vectors (leaks similarity structure) | as above | low | high |

Apple's own precedent: under standard iCloud protection Apple holds the keys for iCloud Drive and Photos; only with Advanced Data Protection do iCloud Drive, Photos and *CloudKit encrypted fields and assets* become end-to-end encrypted ([Apple: iCloud data security overview](https://support.apple.com/en-us/102651)). Practical consequence: if the founder's v1 uses CloudKit, use `CKAsset` + encrypted fields so that users who turn on ADP get E2E for free, and for non-ADP users your data is at least not readable by you.

### 2.2 Anthropic API data handling (and alternatives)

All figures from Anthropic's own pages, fetched 2026-11-03.

| Item | Anthropic Claude API | Source |
|---|---|---|
| Default retention | inputs/outputs deleted within 30 days | [privacy.claude.com 7996866](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-data) |
| Training use | "By default, we will not use your inputs or outputs" (commercial/API); exceptions: feedback/bug reports, explicit opt-in; feedback kept 5 years | [7996868](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training); Commercial Terms §B "Anthropic may not train models on Customer Content" ([commercial-terms](https://www.anthropic.com/legal/commercial-terms)) |
| Trust & safety carve-out | flagged inputs/outputs up to 2 years, classifier scores up to 7 years — applies even under ZDR/HIPAA | [7996866](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-data); [api-and-data-retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) |
| Ad-hoc deletion | "For paid API customers, we do not support ad hoc deletion" | [7996875](https://privacy.claude.com/en/articles/7996875-can-you-delete-data-that-i-sent-via-api) |
| ZDR | per-organization, via sales, subject to approval; covers Messages + Token Counting for eligible features; does not cover Console, Managed Agents, consumer plans | [api-and-data-retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention) |
| ZDR exclusions relevant here | Files API (**No**), Batch (**No**, 29-day retention), code execution / programmatic tool calling (**No**, 30 days), Agent Skills (**No**), MCP connector (**No**); PDF support inline (**Yes**), prompt caching (**Yes** — KV cache in memory for TTL only), structured outputs (**Yes, qualified**), thinking (**Yes**), citations (**Yes**), data residency (**Yes**) | same |
| Covered Models | Claude Fable 5.1 / Mythos 5.1 / Fable 5 / Mythos 5 *require* 30-day retention; ZDR orgs get a 400 error unless a workspace is switched to standard retention | same |
| HIPAA / BAA | self-serve standard BAA in Console (Settings > Data retention > "HIPAA compliance" card) for eligible orgs; permanent once enabled; enforced at org level; non-eligible features return 400; PHI must not appear in JSON schema definitions for structured outputs; HIPAA readiness is an alternative to ZDR, not an add-on | same; [BAA article](https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers) |
| HIPAA exclusions | Files, Batch, Skills, Code Execution, Web Fetch; Claude Platform on AWS; Console usage; Bedrock/Vertex/Foundry deployments unless separately configured | same |
| Data residency | storage is in the US; `inference_geo: "us"` (Claude 4.6+) at 1.1x price; `"global"` default; workspace geo only `"us"`; no EU option | [7996890](https://privacy.claude.com/en/articles/7996890-where-are-your-servers-located-do-you-host-your-models-on-eu-servers); [data-residency](https://platform.claude.com/docs/en/manage-claude/data-residency) |
| Certifications | SOC 2 Type I & II, ISO 27001:2022, ISO/IEC 42001:2023, HIPAA-ready configuration; reports via trust.anthropic.com | [10015870](https://privacy.claude.com/en/articles/10015870-what-certifications-has-anthropic-obtained) |
| Usage Policy (effective 2026-11-12) | no facial recognition / biometric identification; health data counts as "private information" not to be accessed without permission; consumer-facing chatbots must disclose AI (not applicable to a silent classifier) | [AUP](https://www.anthropic.com/legal/aup) |
| Files API | 500 MB/file, 1 TB/org, free, **workspace-scoped** (any key in the workspace can read any file — never expose file_ids to end users; one workspace per tenant, 100 workspaces/org) | [files](https://platform.claude.com/docs/en/build-with-claude/files) |

Design consequence: use the inline Messages API (base64 image or PDF `document` block) — never the Files API or Batch — for document understanding; that path is ZDR-eligible and HIPAA-eligible. Prompt caching for the long system prompt/taxonomy is fine under both.

**Comparison providers (if a sub-task needs them):**

| | OpenAI API | Google Gemini API |
|---|---|---|
| Retention | abuse-monitoring logs up to 30 days | paid tier: "limited period" (unspecified on the terms page); grounding data 30 days |
| Training | not used since 2023-03-01 unless opt-in | **unpaid tier: used for product improvement and human-reviewed**; paid tier: not used |
| ZDR | approved customers; `/v1/files`, `/v1/batches`, vector stores, assistants **not** eligible | not documented on terms page |
| BAA | available; `/v1/chat/completions`, `/v1/responses` eligible with Private/Safety Retention; web search not covered | none on terms page; terms bar clinical-practice use |
| Residency | storage in 10 regions; inference only US/EU/UAE; 10% uplift on newer models | "any country where Google has facilities" |
| Sources | [OpenAI your-data](https://developers.openai.com/api/docs/guides/your-data) | [Gemini API terms](https://aistudio.google.com/docs/terms) |

Bottom line: Anthropic's posture is at parity with OpenAI and better than Gemini's free tier; OpenAI has an EU inference option Anthropic lacks today.

### 2.3 Regulations

**HIPAA.** HHS defines covered entities as health plans, health care clearinghouses and health care providers that transmit standard transactions, plus their business associates ([HHS covered entities](https://www.hhs.gov/hipaa/for-professionals/covered-entities/index.html) — page returned 403 on fetch; definition is well-settled, **cite from training**). An individual photographing their own EOBs is neither; the app developer is not a business associate of the individual. HIPAA is therefore not triggered by v1/v2 and only by v3 if you sell to providers. The Anthropic BAA is nevertheless cheap insurance and would let you say "HIPAA-ready pipeline" in marketing — but it is permanent and blocks Files/Batch/code-execution for the whole org.

**FTC Health Breach Notification Rule (16 CFR 318).** The 2024 final rule (announced 2024-04-26, published 2024-05-30, effective 60 days after publication, i.e. 2024-07-29) "more clearly applies to health apps and similar technologies not covered by HIPAA"; a breach includes *unauthorized disclosure*, not only hacking; individuals must be notified within 60 calendar days of discovery; breaches of 500+ require FTC notice at the same time; media notice "in some cases"; penalties up to $51,744 per violation (that figure is the 2024 inflation-adjusted number and will be stale) ([FTC press release](https://www.ftc.gov/news-events/news/press-releases/2024/04/ftc-finalizes-changes-health-breach-notification-rule); [FTC basics](https://www.ftc.gov/business-guidance/resources/health-breach-notification-rule-basics-business)). GoodRx and Premom were the enforcement precedents. Whether a general document archive is a "personal health record" (it "draws information from multiple sources" and contains health information) is a genuine open question; a hosted v3 that stores medical bills and bills itself as a health-records keeper should assume yes. A v1/v2 app that keeps documents only on-device or in the user's own Drive/NAS has no "breach" surface and is realistically out of scope.

**GLBA / Safeguards Rule.** Applies only to "financial institutions" (activities financial in nature under BHCA §4(k): lenders, tax-prep firms, financial advisors, etc.). Storing a user's own bank statements does not make you one. Note the Safeguards Rule's 30-day FTC breach notice for 500+ consumers (effective May 2024) as a benchmark ([FTC Safeguards Rule](https://www.ftc.gov/business-guidance/resources/ftc-safeguards-rule-what-your-business-needs-know)).

**CCPA/CPRA.** Thresholds: >$25M revenue, or buying/selling/sharing PI of 100,000+ California residents/households, or 50%+ revenue from selling PI ([CA AG](https://oag.ca.gov/privacy/ccpa)). The AG page does not show the inflation-adjusted figures (the revenue threshold was adjusted to ~$26.6M in 2025, **unverified**). An indie app will not cross these for a long time; however, the privacy policy must still be accurate, and "sensitive personal information" (SSN, financial account, health) carries the right-to-limit.

**Washington My Health My Data Act (RCW 19.373).** Applies to any entity doing business in Washington that determines purposes for "consumer health data" — no revenue threshold; small businesses covered since 2024-06-30; requires a separate consumer-health-data privacy policy linked from the homepage, consent for collection/sharing, deletion including from backups, and a private right of action via the Consumer Protection Act ([WA AG](https://www.atg.wa.gov/protecting-washingtonians-personal-health-data-and-privacy)). Nevada SB 370 and Connecticut have similar (weaker) laws (**unverified**). For v2, a document app that classifies "medical" documents is arguably collecting consumer health data; the mitigation is that the data stays on the user's device/storage and the developer never has it.

**GDPR (if sold in EU/UK).** Health data is a special category under Art. 9(1); explicit consent (9(2)(a)) is the usable basis for a consumer app ([Art. 9](https://gdpr-info.eu/art-9-gdpr/)). Breach notification to the supervisory authority within 72 hours unless unlikely to result in risk ([Art. 33](https://gdpr-info.eu/art-33-gdpr/)). Anthropic acts as processor under its DPA; data is stored in the US and the DPA/subprocessor pages could not be fetched (the /legal/dpa URL returned 404), so the transfer mechanism (SCCs / EU-US DPF) is **unverified**. Because the app itself decides to send documents to Anthropic, the developer is the controller for that transfer and needs a DPA with Anthropic (available per the privacy center index) plus a lawful transfer basis. With user-owned storage and on-device processing, the developer processes almost nothing as controller — a strong "privacy by design" story for Art. 25.

**State breach laws.** All 50 US states have breach-notification statutes with 30-60 day clocks (**unverified**, general knowledge); most exempt encrypted data where the key was not compromised, which is another argument for client-side encryption in v3.

### 2.4 App Store requirements

From the current [App Store Review Guidelines](https://developer.apple.com/app-store/review/guidelines/) (fetched 2026-11-03):

- **5.1.1(i)** privacy policy link in App Store Connect and in-app; must explain retention/deletion and how to revoke consent.
- **5.1.1(ii)** consent for any data collection; "paid functionality must not be dependent on or require a user to grant access to this data"; purpose strings must be complete. You need `NSCameraUsageDescription` (and `NSPhotoLibraryAddUsageDescription` only if you save to Photos — avoid; use the app container).
- **5.1.1(v)** "If your app supports account creation, you must also offer account deletion within the app." Deletion must remove the account and all data not legally required; may take reasonable time; may link to a web page; must handle auto-renewable subscriptions by pointing to `showManageSubscriptions`; Sign in with Apple token revocation via REST API is "should" ([Apple account deletion](https://developer.apple.com/support/offering-account-deletion-in-your-app/)). v1/v2 with no account sidestep this entirely.
- **5.1.2(i)** "You must clearly disclose where personal data will be shared with third parties, including with third-party AI, and obtain explicit permission before doing so." This is the clause App Review will apply to Claude. A one-time onboarding consent screen ("Documents are analyzed by Anthropic Claude; sensitive numbers are masked before upload") satisfies it; do not bury it in the privacy policy only.
- **4.8** if you add Google Sign-In for Drive, you must also offer a login option that limits data to name/email and lets users hide email (Sign in with Apple qualifies) — *but only if that login sets up the user's primary account*. Using Google OAuth purely as a storage connector (not for the app's primary account) does not trigger 4.8. Keep it that way.
- **3.1.1 / 3.1.2** paid features must use IAP; subscriptions must deliver ongoing value, ≥7 days, work across the user's devices; 3.1.3(b) lets web-purchased subscriptions be honored in-app if also sold via IAP.
- **Privacy nutrition labels** ([App Privacy Details](https://developer.apple.com/app-store/app-privacy-details/)): "collected" means transmitted off device and retained longer than needed to service the request in real time; "data that is processed only on device is not 'collected'". Sending an image to Claude, which deletes it in 30 days, arguably *is* collection by a third party (30 days > real-time). Declare: Photos or Videos / Other User Content (the scans), Financial Info, Health, Sensitive Info, Contact Info — "linked to user", purpose "App Functionality", not used for tracking. Declaring honestly and broadly is safer than claiming "Data Not Collected". Data collected by Apple frameworks (CloudKit) need not be disclosed by you; third-party SDKs you embed must be.
- **Export compliance.** Apple's reference table: encryption limited to the OS -> no documentation; industry-standard algorithm *not* provided by the OS (SQLCipher's OpenSSL/CommonCrypto-backed AES counts) -> French encryption declaration if distributed in France; proprietary algorithms -> CCATS + French declaration ([Apple export compliance reference](https://developer.apple.com/help/app-store-connect/reference/export-compliance-documentation-for-encryption); [overview](https://developer.apple.com/help/app-store-connect/manage-app-information/overview-of-export-compliance)). Apple clears submissions in ~2 business days. Set `ITSAppUsesNonExemptEncryption` to `false` only if you stick to CryptoKit/CommonCrypto/TLS; if you ship SQLCipher or a custom E2E layer, answer "yes, standard algorithms", file the annual BIS self-classification report (due Feb 1 each year for mass-market 5D992 items, **unverified** — BIS page not readable) and the ANSSI declaration for France. Practical shortcut: build E2E on CryptoKit (AES-GCM, HKDF, Secure Enclave P-256) and skip SQLCipher; then the OS-only exemption applies.
- **Sign in with Apple** is not required if you use only your own account system or no account at all.

### 2.5 SOC 2 / ISO 27001, pen testing, incident response (v3)

SOC 2 reports cover Security, Availability, Processing Integrity, Confidentiality and Privacy Trust Services Criteria ([AICPA](https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2)); Type I is point-in-time, Type II covers an observation window typically 3-12 months (**unverified** from AICPA page; standard practice). Nobody will demand this of a consumer app; B2B/prosumer buyers (accountants, small firms) and Google will. Concretely:

- **Google Drive OAuth.** Use only `drive.file` (non-sensitive: per-file access to files the app created or the user picked) and `drive.appdata`. Full `drive` and `drive.readonly` are *restricted* scopes requiring OAuth verification, limitation to backup/sync or productivity categories, and if your servers touch Drive data an annual CASA security assessment (AL1/AL2, OWASP ASVS-based, Letter of Validation) ([Drive scopes](https://developers.google.com/workspace/drive/api/guides/api-specific-auth); [Google restricted-scope verification](https://support.google.com/cloud/answer/13465431)). With `drive.file` and an on-device-only client you avoid CASA entirely. Cost of CASA is not stated on Google's page (third-party labs quote roughly $0-$4,500 depending on tier, **unverified**).
- **Pen test**: one external test before v3 launch and annually; cheap mobile+API tests exist. Also Google's CASA AL2 effectively is one.
- **Incident response plan**: a written one-page runbook, a security@ address, and the notification clocks: FTC HBNR 60 days/consumer, GDPR 72 h/authority, Safeguards-style 30 days as a self-imposed ceiling, state laws 30-60 days.
- **Vulnerability disclosure policy** and dependency scanning are table stakes for v3.

### 2.6 Document retention law: can scans replace paper?

**US federal tax.** Rev. Proc. 97-22 (1997-13 IRB) defines an "electronic storage system" that "electronically imag[es] hardcopy documents" and says records maintained in a compliant system "will constitute records within the meaning of § 6001". Section 7: the procedure "permits the destruction of the original hardcopy books and records" after the taxpayer (1) completed its own testing establishing the records are reproduced in compliance and (2) instituted procedures ensuring continued compliance ([IRS IRB 1997-13 PDF](https://www.irs.gov/pub/irs-irbs/irb97-13.pdf)). Section 4 requirements map cleanly onto product features:

| Rev. Proc. 97-22 §4 requirement | Product feature |
|---|---|
| accurate and complete transfer; index, store, preserve, retrieve, reproduce | capture pipeline + durable write-ahead log + verified upload |
| controls to prevent/detect unauthorized creation, alteration, deletion, deterioration | SHA-256 of each page stored in manifest; immutable PDF/A; audit log |
| inspection/QA program with periodic checks | periodic integrity scan of the archive (hash recheck) |
| indexing system "functionally comparable to a reasonable hardcopy filing system" | metadata DB + per-document unique ID |
| legible, readable hardcopies on demand | ≥300 DPI, print-ready PDF |
| retain as long as material; descriptions of the system available to IRS | user-facing "how your archive works" page; export |

IRS Publication 583 restates this for small businesses: "The original hard copy books and records may be destroyed provided that the electronic storage system has been tested…" ([Pub 583](https://www.irs.gov/pub/irs-pdf/p583.pdf), p. 12). Retention periods: 3 years default; 6 years if >25% income omitted; 7 years for worthless securities/bad debt; employment tax 4 years; indefinitely if no return/fraud; property records until the limitations period for the year of disposal ([IRS how long to keep records](https://www.irs.gov/businesses/small-businesses-self-employed/how-long-should-i-keep-records)). Rev. Proc. 97-22 is from 1997 but remains the cited authority in 2025-2026 IRS publications — not stale.

**Court admissibility.** FRE 1003: "A duplicate is admissible to the same extent as the original" unless a genuine question is raised about the original's authenticity or it would be unfair ([Cornell LII](https://www.law.cornell.edu/rules/fre/rule_1003)). Partial reproductions can trigger a demand for the original — scan every page including blank backs and envelopes.

**Keep as physical originals** (practice-based, no single authoritative source fetched; Nolo returned 403): birth/death/marriage/divorce certificates (agencies issue *certified copies*, which is what counts — [USA.gov](https://www.usa.gov/replace-vital-documents)), Social Security cards, passports, original signed wills and trusts (many states require the original to probate), deeds and vehicle titles, notarized/apostilled documents, paper savings bonds and stock certificates, military discharge (DD-214), court orders with raised seals, and anything with a wet signature that a counterparty may contest. The app should *detect* these classes and tell the user "scanned — keep the paper" instead of "safe to discard". That single classifier label is a legal-risk control.

**EU notes (brief, mostly unverified because Légifrance and EUR-Lex pages did not render).** France: Code civil art. 1379 and Décret 2016-1673 give a "copie fiable" the same evidential weight as the original if integrity is guaranteed (qualified e-signature/timestamp or equivalent) — otherwise the original can be demanded. Germany: GoBD requires "ersetzendes Scannen" per a documented procedure (Verfahrensdokumentation) before paper can be destroyed; 8-10 year retention. eIDAS 2.0 (Reg. 2024/1183) introduces "qualified electronic archiving services" with a presumption of integrity and origin, applicable from 2026 for most provisions. For an EU launch, a qualified timestamp (RFC 3161, from a QTSP) applied to each document hash is the cheap way to meet the French/German/eIDAS integrity bar. Avoid a blanket "you may discard the paper" claim in the EU; say "scanned and timestamped".

### 2.7 BYO API key model

No App Store guideline addresses user-supplied API keys (confirmed by reading 2.5.2, 3.1.1, 5.1.x). Risks and mitigations:

- **3.1.1 circumvention risk**: if the *only* way to use the app is pasting a key you sell elsewhere, reviewers can view it as unlocking functionality outside IAP. Mitigation: ship a usable free tier (on-device OCR + local archive), make the key optional ("advanced analysis"), and never link to where to buy credits.
- **Anthropic terms**: an end user pasting their own key is a Commercial customer of Anthropic; the developer is not Anthropic's customer for that traffic and gets no DPA/BAA/ZDR coverage — fine for v1, and for v2 "power user" mode, but a hosted v3 should run its own org key with ZDR/HIPAA and bill via IAP.
- **Security**: key in Keychain (`WhenPasscodeSetThisDeviceOnly`), never in CloudKit; calls go directly from device to `api.anthropic.com` (no proxy, so the developer never sees content). Privacy label: the developer collects nothing; Anthropic is a third party the *user* chose.
- **Prompt-injection surface**: mail contains text; the classifier prompt must treat document text as data. Structured outputs with `strict: true` constrain the response shape (ZDR-eligible "qualified").

### 2.8 Secure deletion and shred workflows

- **iOS**: per-file AES keys mean deleting a file and its key is a cryptographic erase; "Erase All Content and Settings" wipes the class keys in Effaceable Storage (Apple Data Protection overview; the specific deletion paragraph was not in the fetched excerpt, **partially unverified**). No overwrite passes are needed or possible on flash.
- **Keychain**: deleting the item is sufficient; `ThisDeviceOnly` items never left the device.
- **Anthropic**: nothing to do — 30-day auto-delete, no ad-hoc deletion offered; with ZDR nothing is stored.
- **Google Drive / iCloud / Synology**: deletion moves to trash (Drive 30 days, iCloud 30 days, Synology Recycle Bin / Btrfs snapshots with user-configured retention, **unverified** figures). A "Shred" action should: delete the file, empty it from trash where the API allows (Drive `files.delete` bypasses trash when called directly; iCloud via `FileManager` goes to "Recently Deleted" **unverified**), delete all local derivatives (thumbnails, OCR text, embeddings, search-index rows), log a tombstone so sync does not resurrect it, and tell the user what you could not purge (NAS snapshots, provider backups).
- **Washington MHMDA** explicitly requires deletion from archives/backups within its timelines — only achievable if you never held the data or if it was client-encrypted and you destroy the key.

### 2.9 Obligations for hosted storage (v3)

- **18 U.S.C. § 2258A**: a "provider" must report apparent CSAM to NCMEC's CyberTipline "as soon as reasonably possible after obtaining actual knowledge"; must preserve reported content for 1 year (raised from 90 days by the 2024 REPORT Act); must store preserved material under NIST CSF controls; no duty to proactively scan ("nothing in this section requires a provider to monitor… or affirmatively search, screen, or scan"); knowing/willful failure to report: fines up to $600,000 first offense for providers under 100M MAU ([Cornell LII §2258A](https://www.law.cornell.edu/uscode/text/18/2258A)). With client-side E2E you cannot gain "actual knowledge" except through user reports; keep an abuse@ channel and a takedown procedure. EU DSA/CSAM interim regulation imposes similar duties for EU hosting (**unverified**).
- **Section 230 / DMCA** are irrelevant for private, unshared archives but become relevant the moment "send a pack to someone" creates share links; add a report-abuse link on shared pages.
- **Government requests**: a published transparency/law-enforcement policy; with E2E, respond with ciphertext and metadata only.

---

## 3. Options compared

| Decision | Option A | Option B | Option C | Recommendation |
|---|---|---|---|---|
| Where document understanding runs | On-device only (Vision OCR + small local model) | Device OCR + Claude inline Messages API | Claude Files API / Batch | **B**. A alone cannot classify/extract well enough; C is not ZDR/HIPAA eligible and leaks file_ids across the workspace. |
| What is sent to Claude | full image | masked image + typed OCR text with placeholders | OCR text only | **masked image + placeholder text**; fall back to text-only for documents the on-device classifier marks as high-sensitivity (tax forms, medical). |
| Anthropic retention arrangement | default 30-day | ZDR (sales, per-org) | HIPAA readiness (self-serve BAA, permanent) | v1/v2 BYO key: default. v3 hosted: **ZDR** on a Sonnet/Haiku-class model; add a second org with HIPAA readiness only if selling to providers. Note Covered Models are incompatible with ZDR. |
| Local encryption | Data Protection Class A only | A + SQLCipher | A + CryptoKit envelope encryption | **C** (keeps OS-only export exemption, no French declaration). |
| v3 storage model | server plaintext + KMS | client-side E2E, user key + recovery key | hybrid E2E + encrypted search blobs | **B now, C later**; avoids PHR-vendor exposure, CSAM-scanning expectations, most state breach clocks. |
| Google Drive scope | `drive` (restricted, CASA) | `drive.file` + `drive.appdata` | WebDAV/SMB only | **B**; no verification/CASA cost. |
| Accounts | none (v1/v2) | Sign in with Apple only | Google/Apple/email | **none until v3**; then Sign in with Apple + email; account deletion in-app from day one. |
| "Discard the paper" claim | always | never | per-document class | **per-document**: "Safe to discard" vs "Scanned — keep the original" (vital records, wills, titles, notarized, bonds). |

---

## 4. Recommendation for this project

1. **Architecture for privacy = architecture for speed.** Run Vision OCR on-device first (needed anyway for the sharpness/duplicate check and the PDF text layer); mask SSN/account/routing/MRN boxes; send Claude a masked JPEG (≤1568 px long edge) plus the placeholder OCR text in a single inline `/v1/messages` call with a cached system prompt and `strict` structured output. This path is ZDR- and HIPAA-eligible, free of Files-API workspace leakage, and leaves the developer with zero document data.
2. **v1 (personal, BYO key, no account):** Keychain `WhenPasscodeSetThisDeviceOnly` for the key and storage tokens; `NSFileProtectionComplete` for archive/DB, Class B for the upload staging queue; CloudKit private DB with encrypted fields so ADP users get E2E; `drive.file` scope for Google; no analytics SDKs. Write the two-page "how your archive works" doc that Rev. Proc. 97-22 §4.01(5) envisions — it doubles as your privacy policy.
3. **v2 (App Store):** onboarding consent screen naming Anthropic as third-party AI (5.1.2(i)); nutrition labels declaring User Content/Financial/Health/Sensitive "linked, app functionality, no tracking"; `ITSAppUsesNonExemptEncryption=false` by staying on CryptoKit/TLS; a free on-device tier so the key is optional; per-document "keep the original" label; a "Shred" action with honest provider caveats; a WA-compliant consumer-health-data section in the privacy policy with a consent toggle for the "medical" category. No account, so 5.1.1(v) and 4.8 do not bite.
4. **v3 (hosted service):** your own Anthropic org with ZDR (model choice constrained by Covered-Models rule); client-side E2E with a recovery key; server stores ciphertext + client-generated encrypted index; Sign in with Apple + in-app deletion; DPA with Anthropic; FTC HBNR/GDPR/state breach runbook; SOC 2 Type I at launch, Type II after 6-12 months; external pen test; 2258A reporting process; abuse and law-enforcement policies. Treat EU launch as a separate workstream (US-only storage at Anthropic, qualified timestamps for copie fiable/GoBD).
5. **Marketing language that is defensible:** "Your documents never leave your devices and your own cloud unencrypted"; "IRS-recognized electronic record keeping (Rev. Proc. 97-22)"; never "legally equivalent to the original" without the per-class caveat.

---

## 5. Risks and unknowns

- **Covered Models vs ZDR**: the fastest/best vision models may be "Covered Models" that require 30-day retention. If the speed goal pushes you to Fable/Mythos 5.x, ZDR is unavailable; HIPAA readiness remains possible. Confirm with Anthropic sales which Haiku/Sonnet generation is both fast enough and ZDR-eligible.
- **Trust-and-safety carve-out**: even under ZDR, flagged content can be kept 2 years. Legal letters about, say, abuse cases or medical documents with graphic content could trip classifiers. Disclose this in the privacy policy.
- **Nutrition-label interpretation**: whether a 30-day-retained inference request is "collection" by a third party is a judgment call; over-declare.
- **PHR-vendor status under FTC HBNR** for a hosted archive is untested; the FTC has been aggressive (GoodRx, Premom).
- **WA MHMDA private right of action** applies even to small developers; a "medical" tag + any server-side processing is enough to argue coverage.
- **Masking accuracy**: regex-based SSN masking on OCR text misses OCR errors (O vs 0) and handwritten numbers; measure recall on real mail before advertising it.
- **Background upload vs Class A**: zero-interaction capture while the phone locks requires careful staging-file class choices or uploads will fail silently — a durability risk disguised as a privacy setting.
- **Unverified items**: RecognizeDocumentsRequest minimum OS; Anthropic DPA transfer mechanism (DPA URL 404); BIS annual report deadline; CASA cost; iCloud/Drive trash retention; EU copie fiable/GoBD/eIDAS details; CCPA inflation-adjusted threshold; HHS page (403).
- **Stale-risk**: FTC penalty figure ($51,744) is 2024's; Apple guideline text is current as of fetch; Anthropic retention article is dated 2026-07-01, AUP effective 2026-11-12 (nine days after this report).

---

## 6. Open questions for the founder

1. Is v1 strictly single-user BYO key with no backend? If yes, most of §2.3/§2.5 is deferred and the privacy policy can truthfully say "we collect nothing".
2. Which Claude model generation is the speed target? If it is a Covered Model, accept 30-day retention or plan for HIPAA readiness instead of ZDR.
3. Will the app ever be marketed for medical or tax use specifically (triggering HBNR/MHMDA framing), or as a general mail digitizer?
4. EU/UK launch in scope for v2? If so, budget for a DPA, Art. 9 explicit-consent UX, and qualified timestamps.
5. Is server-side semantic search a must-have for v3, or is on-device/encrypted-index search acceptable? This decides E2E vs plaintext hosting.
6. Are you willing to accept "lose your recovery key = lose your archive" for E2E, or must the service be able to recover accounts (which forces key escrow and PHR-vendor exposure)?
7. Should "Shred" promise purge from Drive/iCloud/NAS trash and snapshots, or only "deleted from the app and deletion requested"?
8. Do you want CloudKit encrypted fields (E2E only when the user enables Advanced Data Protection) or your own CryptoKit envelope (E2E for everyone, but you own key management)?
9. Will you embed any third-party SDK (crash reporting, analytics)? Each one changes the nutrition label and may ingest document text via breadcrumbs.

---

## 7. Sources

Anthropic
- Commercial data retention: https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-data (article dated 2026-07-01)
- ZDR products: https://privacy.claude.com/en/articles/8956058-i-have-a-zero-retention-agreement-with-anthropic-what-products-does-it-apply-to
- Training use: https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training
- API deletion: https://privacy.claude.com/en/articles/7996875-can-you-delete-data-that-i-sent-via-api
- BAA: https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers
- Server locations: https://privacy.claude.com/en/articles/7996890-where-are-your-servers-located-do-you-host-your-models-on-eu-servers
- Certifications: https://privacy.claude.com/en/articles/10015870-what-certifications-has-anthropic-obtained
- API and data retention (ZDR/HIPAA feature table): https://platform.claude.com/docs/en/manage-claude/api-and-data-retention
- Data residency: https://platform.claude.com/docs/en/manage-claude/data-residency
- Files API: https://platform.claude.com/docs/en/build-with-claude/files
- Batch processing: https://platform.claude.com/docs/en/build-with-claude/batch-processing
- Commercial Terms: https://www.anthropic.com/legal/commercial-terms
- Usage Policy (effective 2026-11-12): https://www.anthropic.com/legal/aup

Other AI providers
- OpenAI data controls: https://developers.openai.com/api/docs/guides/your-data
- Gemini API terms: https://aistudio.google.com/docs/terms

Apple
- App Store Review Guidelines: https://developer.apple.com/app-store/review/guidelines/
- Account deletion: https://developer.apple.com/support/offering-account-deletion-in-your-app/
- App Privacy Details: https://developer.apple.com/app-store/app-privacy-details/
- Export compliance overview: https://developer.apple.com/help/app-store-connect/manage-app-information/overview-of-export-compliance
- Export compliance documentation table: https://developer.apple.com/help/app-store-connect/reference/export-compliance-documentation-for-encryption
- Data Protection classes: https://support.apple.com/guide/security/data-protection-classes-secb010e978a/web
- Data Protection overview: https://support.apple.com/guide/security/data-protection-overview-secf6276da8a/web
- Keychain data protection: https://support.apple.com/guide/security/keychain-data-protection-secb0694df1a/web
- iCloud data security overview: https://support.apple.com/en-us/102651

Google
- Drive scopes: https://developers.google.com/workspace/drive/api/guides/api-specific-auth
- Restricted-scope verification / CASA: https://support.google.com/cloud/answer/13465431

US law and regulators
- Rev. Proc. 97-22 (IRB 1997-13): https://www.irs.gov/pub/irs-irbs/irb97-13.pdf
- IRS Publication 583: https://www.irs.gov/pub/irs-pdf/p583.pdf
- IRS record-retention periods: https://www.irs.gov/businesses/small-businesses-self-employed/how-long-should-i-keep-records
- FRE 1003: https://www.law.cornell.edu/rules/fre/rule_1003
- 18 U.S.C. § 2258A: https://www.law.cornell.edu/uscode/text/18/2258A
- FTC HBNR final rule press release: https://www.ftc.gov/news-events/news/press-releases/2024/04/ftc-finalizes-changes-health-breach-notification-rule
- FTC HBNR basics: https://www.ftc.gov/business-guidance/resources/health-breach-notification-rule-basics-business
- FTC Safeguards Rule: https://www.ftc.gov/business-guidance/resources/ftc-safeguards-rule-what-your-business-needs-know
- CCPA: https://oag.ca.gov/privacy/ccpa
- Washington My Health My Data Act: https://www.atg.wa.gov/protecting-washingtonians-personal-health-data-and-privacy
- USA.gov vital documents: https://www.usa.gov/replace-vital-documents

EU
- GDPR Art. 9: https://gdpr-info.eu/art-9-gdpr/
- GDPR Art. 33: https://gdpr-info.eu/art-33-gdpr/

Other
- SQLCipher design: https://www.zetetic.net/sqlcipher/design/
- AICPA SOC 2: https://www.aicpa-cima.com/topic/audit-assurance/audit-and-assurance-greater-than-soc-2

Not retrievable (cited from training, flagged unverified in text): HHS covered-entity page (403), Anthropic DPA (404), Apple RecognizeDocumentsRequest doc (JS), Légifrance art. 1379 / Décret 2016-1673, EUR-Lex Reg. 2024/1183, BIS encryption page, Nolo originals guide (403).
