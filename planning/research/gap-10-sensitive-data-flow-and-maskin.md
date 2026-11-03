# Gap 10 — One sensitive-data policy for the whole pipeline (masking, Claude feature scope, labels, legal entity, BYO keys)

Research date: 2026-11-03. Method: the shared WebSearch budget for this run was exhausted, so every finding below comes from direct fetches of primary sources (Anthropic platform docs and legal pages, Apple developer docs, Google Drive API reference, Voyage AI docs, Presidio docs). Items I could not fetch are marked **unverified**. This report reads privacy.md, mail.md, claude.md, search.md, ingest.md, storage.md, output.md and gap-5 first and resolves where they contradict each other.

---

## 1. Executive summary

1. The reports contradict each other because they answer different questions. privacy.md masks SSN/account/routing/MRN *before Claude*; mail.md's taxonomy extracts `employee_ssn_last4`, `micr_account_last4`, `micr_routing`, EINs; storage/output/search push "the extracted text" into Drive `indexableText`, sidecar JSON, Core Spotlight and Voyage. The fix is one **three-class policy** keyed on *where the bytes go*, not on *which document type* it is.
2. **Class A (secrets)** — SSN/ITIN, card PANs, bank account numbers, routing/MICR, DL/passport numbers, MRN/health-plan member IDs — exist in exactly one place outside the device: the archival PDF (and its text layer) in the user's own storage. Everywhere else (Claude request, structured output, sidecar, FTS, Spotlight, Drive `indexableText`, embeddings, filenames, logs) carries at most a `last4` placeholder. `micr_routing` is dropped from the taxonomy.
3. **Class B (reference IDs)** — invoice/claim/policy/case/order/check numbers, EINs, amounts, dates — flow in plaintext to Claude, sidecar, FTS, Spotlight and `indexableText`, because they are what people search for. **Class C** (names, addresses, free text, summaries) likewise, but Spotlight and `indexableText` get *summary + tags + Class B*, never the raw OCR dump.
4. One masking pass runs on-device over Vision word boxes and feeds *every* downstream consumer (Claude copy, FTS text, embedding text). A CI "canary" test asserts synthetic Class A values never appear in any outbound request, index, sidecar or filename.
5. Claude feature scope under the recommended posture (managed mode = own org with ZDR on Haiku/Sonnet 5.5): **Message Batches and the Files API are off-limits** — ZDR marks both "No" and *does not block them* (silent step-out), HIPAA readiness returns `400` ([retention doc](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)). Backfill therefore uses inline `/v1/messages` text-only calls (≈2x the Batch price at Haiku 5.5, i.e. ≈$0.0006/page — immaterial). Covered Models (Fable 5.x/Mythos 5.x) are excluded because they require 30-day retention.
6. BYO-key mode cannot promise ZDR or HIPAA (those are per-organization arrangements the end user would have to negotiate), so the consent screen and privacy policy say different things per mode; the App Store nutrition label is one superset label for the binary.
7. End users may paste their own key: the Consumer Terms forbid sharing a key "with anyone else" and the AUP bans "services that route requests through consumer subscriptions", so the key must go device→`api.anthropic.com` only, never through the developer's proxy, and the app must never accept Claude.ai/Pro/Max logins ([consumer terms](https://www.anthropic.com/legal/consumer-terms), [AUP](https://www.anthropic.com/legal/aup)).
8. Guideline 5.1.1(ix) says apps "that require sensitive user information **should** be submitted by a legal entity" ([guidelines](https://developer.apple.com/app-store/review/guidelines/)). It is "should", enforcement is reviewer discretion (no enforcement data could be gathered this run), but an LLC + Organization enrollment before the App Store build is cheap and avoids an app transfer that would change the Team ID and force a Keychain re-login.
9. Voyage AI trains on API inputs **by default**; opt-out needs an org Admin with a payment method and yields "zero-day retention" ([Voyage FAQ](https://docs.voyageai.com/docs/faq)). BYO mode therefore uses on-device embeddings; managed mode may use Voyage only after opt-out and only on masked text.
10. Two launch blockers remain the founder's call: form the entity before submission, and pick ZDR (Haiku/Sonnet 5.5, no Batches/Files) versus standard 30-day retention for the managed tier.

---

## 2. Findings

### 2.1 What the existing reports actually say (the contradictions)

| Report | Position | Conflicts with |
|---|---|---|
| privacy.md §2.1, §4.1 | Mask SSN/account/routing/MRN boxes on-device; send masked JPEG + OCR text with placeholders `[SSN]`, `[ACCT-…1234]`; text-only for tax/medical | mail.md taxonomy |
| mail.md §3 taxonomy | `key_fields` include `employee_ssn_last4`, `employer_ein`, `account_last4`, `micr_routing`, `micr_account_last4`, `payment_last4` | privacy masks the routing/account box, so `micr_routing` cannot be extracted |
| claude.md §2.3 schema | identifiers enum includes `account_number`, `member_id`, `tax_id_last4` | `account_number` (full) contradicts privacy; `member_id` is a HIPAA identifier |
| storage.md rec. 7 / output.md 2g | Drive `contentHints.indexableText` gets "the extracted text (≤128 KB)" | pushes Class A into Drive's search index |
| search.md §2a | Core Spotlight gets `title + textContent` (full OCR) | Spotlight snippets appear in system search; iOS 26 can expose indexed content to Foundation Models |
| claude.md §2.6, §2.11, search.md §5 | Batches for backfill/re-index; Voyage embeddings of `title+summary+tags+first 1,500 tokens of OCR text` | Batches are not ZDR/HIPAA eligible; Voyage trains by default; OCR text contains Class A |
| claude.md §2.7, search.md §3 | claude.md suggests Files API for multi-page docs; search.md says never use Files API as a store | Files API is not ZDR/HIPAA eligible and workspace-scoped |
| privacy.md §2.4 vs business.md | privacy says "over-declare" labels; business assumes BYO tier is "developer never sees content" | one binary needs one label |

### 2.2 Anthropic retention facts that constrain the pipeline (fetched 2026-11-03)

Source: [API and data retention](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention).

| Fact | Exact text / value |
|---|---|
| Default | "Conversation content (your prompts and Claude's outputs) is not retained by default; the exception is Covered Models, which require 30-day retention." Commercial default deletion "within 30 days" ([privacy article, dated 2026-07-01](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)) |
| ZDR | "enabled per organization; each new organization requires ZDR to be enabled separately by your account team" via sales |
| Covered Models | "Claude Fable 5.1, Claude Mythos 5.1, Claude Fable 5, and Claude Mythos 5 … require 30-day data retention and are not available under ZDR unless expressly authorized"; a ZDR org gets `400 invalid_request_error` "your organization or workspace must have data retention enabled"; a workspace can be switched to standard retention individually. Haiku 5.5 / Sonnet 5.5 / Opus 5.5 are **not** listed as Covered Models. |
| Batch processing | `/v1/messages/batches`: ZDR **No**, HIPAA **No**, "29-day retention; async storage required" ([batch doc](https://platform.claude.com/docs/en/build-with-claude/batch-processing)) |
| Files API | `/v1/files`: ZDR **No**, HIPAA **No**, "Files retained until explicitly deleted or they reach their configured expiration" |
| PDF support | inline through Messages: ZDR Yes, HIPAA Yes; "HIPAA eligibility applies to PDFs sent inline through the Messages API, not through the Files API" |
| Prompt caching | ZDR Yes, HIPAA Yes; KV cache in memory for the TTL only |
| Structured outputs | ZDR "Yes (qualified)": "Only the JSON schema is cached, for up to 24 hours since last use"; HIPAA Yes but "**Do not include PHI in JSON schema definitions** … schema property names, `enum` values, `const` values, and `pattern` regular expressions" ([structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs)) |
| Enforcement asymmetry | "Under HIPAA readiness, the API blocks requests that include a 'No' feature and returns a `400` error … Under ZDR, the API does **not** block these features; using one is a choice to step outside your ZDR arrangement for that specific data" |
| HIPAA readiness | self-serve BAA on the Console Data-retention page for eligible orgs; "Once HIPAA readiness is enabled for your organization, the configuration is permanent and cannot be disabled by an administrator"; it is "an alternative to ZDR", not an add-on |
| Trust & safety carve-out | "Even with ZDR or HIPAA arrangements in place … if a chat or session is flagged, Anthropic may retain inputs and outputs for up to 2 years"; classifier scores up to 7 years ([privacy article](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)) |
| ZDR scope article | ZDR applies to "eligible Anthropic APIs" and "products that use your Commercial organization API key"; consumer Free/Pro/Max are never ZDR ([ZDR products](https://privacy.claude.com/en/articles/8956058-i-have-a-zero-retention-agreement-with-anthropic-what-products-does-it-apply-to)) |
| `metadata.user_id` | "should be a uuid, hash value, or other opaque identifier … Do not include any identifying information such as name, email address, or phone number", max 512 ([Messages API](https://platform.claude.com/docs/en/api/messages)) |

Consequences: (a) the only Claude surfaces compatible with *either* strict posture are inline `/v1/messages` with base64 image or `document` blocks, prompt caching, structured outputs and token counting; (b) the schema field names in claude.md (`employee_ssn_last4`, `account_last4`) are fine under the PHI rule because they are *labels*, not patient data — what must never appear are enum/const/pattern values that are themselves PHI; (c) in ZDR the API will happily accept a Batch call, so the "no Batches" rule has to be enforced in code review/CI, not by Anthropic.

### 2.3 Where each store actually puts bytes (verified behaviours)

- **Google Drive `contentHints.indexableText`**: "Text to be indexed for the file to improve fullText queries … limited to 128 KB … may contain HTML". The parent `contentHints` object's fields "are never populated in responses" — write-only ([files resource](https://developers.google.com/workspace/drive/api/reference/rest/v3/files)). `fullText contains` matches "the name, description, indexableText properties, or text in the file's content or metadata" ([search terms](https://developers.google.com/workspace/drive/api/guides/ref-search-terms)). Two implications: Drive already full-text indexes a PDF with a text layer, so `indexableText` is only needed for metadata that is *not* in the PDF (summary, tags, doc_type, sender); and whether `indexableText` becomes searchable by people the file is later shared with is undocumented — assume yes. `appProperties` are "private to the requesting app"; `properties` are "visible to all apps" (same source).
- **Core Spotlight**: "The indexes you create using Core Spotlight remain on device, and are private to the owner of the device. Devices don't share indexed data with Apple, or synchronize that data with the person's other devices" ([framework overview](https://developer.apple.com/documentation/corespotlight)). A named index can be created with `init(name:protectionClass:)` where protectionClass is `none`, `complete`, `completeUnlessOpen` or `completeUntilFirstUserAuthentication` ([doc](https://developer.apple.com/documentation/corespotlight/cssearchableindex/init(name:protectionclass:))). The same overview lists a "Spotlight search tool" article: "Make your app's indexed content available to the system's Foundation models as additional context to use when answering prompts" (article body could not be fetched; opt-in mechanics **unverified**). Spotlight snippets are shown system-wide and to Siri, which is why Class A must not be in `textContent`.
- **Voyage AI**: hosted-API customers are "Opted In" to training by default; opting out requires an organization Admin with a payment method on file, "results in a zero-day retention of the data", and cannot be reversed from the dashboard ([FAQ](https://docs.voyageai.com/docs/faq)). The privacy policy grants Voyage a license to use Customer Content to "train, improve, and otherwise further develop the Service" unless opted out; "If you opt out, your Customer Content will be immediately deleted by Voyage AI after it is processed for you" ([policy](https://www.voyageai.com/privacy)). No SOC 2/HIPAA scope is described beyond trust-page badges; BAA availability unknown.
- **Synology / iCloud / NAS**: Synology Universal Search content-indexes PDFs on the NAS (search.md); iCloud Drive files are indexed by Spotlight on the user's Macs. Both are the user's own property and hold the archival PDF with Class A inside — that is intended; the app cannot and should not control it, but should say so.
- **On-device SQLite FTS5**: a file in the app container; protect with `NSFileProtectionComplete` (privacy.md). It is the one index that *could* hold full numbers safely, but indexing the *masked* text instead costs nothing (the mask pass has already run) and removes the "SSN is in a trigram table" class of bugs entirely.

### 2.4 What on-device masking can and cannot detect

- Presidio's reference recognizers detect `US_SSN`, `US_BANK_NUMBER` ("between 8 to 17 digits"), `US_DRIVER_LICENSE`, `US_PASSPORT`, `US_ITIN` by "regex pattern plus context words" with **no checksum**; only `CREDIT_CARD` (Luhn), `IBAN_CODE` and `MEDICAL_LICENSE` have checksums ([Presidio supported entities](https://presidio.dataprivacystack.org/supported_entities/)). So bank-account detection is inherently context-driven ("Account", "Acct", "A/C", "Account No.") and will over-match; over-masking is cheap here because placeholders keep `last4`.
- ABA routing numbers have a public mod-10 check (weights 3,7,1) — standard algorithm, **not verified against a source this run** — and MICR lines sit at the bottom of check-aspect pages, so "mask the whole MICR band on any document the on-device classifier calls a check" is a geometry rule, not a regex problem.
- Apple's iOS 26 `RecognizeDocumentsRequest`/`DocumentObservation` give words, lines, paragraphs, tables, lists and barcodes ([request](https://developer.apple.com/documentation/vision/recognizedocumentsrequest), [observation](https://developer.apple.com/documentation/vision/documentobservation)); the detected-data types (phone, email, URL, date, address, flight numbers per WWDC25) could not be fetched (**unverified**) and in any case do **not** include SSN or account numbers — the app must own those regexes.
- Known recall gaps (privacy.md §5): OCR confusions (O/0, l/1), handwritten numbers, numbers split across lines, and numbers only visible in the image (e.g. a faint carbon copy). Mitigations: normalize OCR text before matching; mask by *word box* so a split SSN still gets both boxes; treat any 9-digit run adjacent to "SSN", "Social Security", "TIN", "EIN" as Class A even if it fails the pattern; measure recall on a 200-page real-mail set before advertising masking.

### 2.5 Apple rules as fetched today

- **5.1.1(ix)**: "Apps that provide services in highly regulated fields (such as banking and financial services, healthcare, gambling, legal cannabis use, air travel and crypto exchanges) or that require sensitive user information should be submitted by a legal entity that provides the services, and not by an individual developer." ([guidelines](https://developer.apple.com/app-store/review/guidelines/))
- **5.1.1(ii)**: consent for collection, "Paid functionality must not be dependent on or require a user to grant access to this data", easy consent withdrawal, complete purpose strings.
- **5.1.2(i)**: "You must clearly disclose where personal data will be shared with third parties, including with third-party AI, and obtain explicit permission before doing so."
- **Nutrition labels**: "'Collect' refers to transmitting data off the device in a way that allows you and/or your third-party partners to access it for a period longer than what is necessary to service the transmitted request in real time"; "Third-party partners refers to analytics tools, advertising networks, third-party SDKs, or other external vendors whose code you've added to your app"; "Data that is processed only on device is not 'collected'"; Financial Info includes "bank account number", Health includes "any other user provided health or medical data", Sensitive Info is the GDPR Art. 9-style list; "if you have a feature that enables users to upload a particular media type, such as photos … you'll need to disclose the specific type of data" ([App Privacy Details](https://developer.apple.com/app-store/app-privacy-details/)). Apple's pages say nothing about data a user sends to a service under their own account/key (App Store Connect help was also checked: [manage app privacy](https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy)).
- **Privacy manifest**: `NSPrivacyCollectedDataType` values must come from Apple's list; Xcode's privacy report "is organized in a similar way to Privacy Nutrition Labels. Refer to this report when you provide your app's privacy details in App Store Connect" ([manifest doc](https://developer.apple.com/documentation/bundleresources/privacy-manifest-files/describing-data-use-in-privacy-manifests)).
- **Enrollment**: Organization requires "a legal entity that can enter into contracts with Apple. We do not accept DBAs, fictitious business names, trade names, or branches", a D-U-N-S number, a public website on the org's domain and a domain email; Individual covers "an individual or sole proprietor/single person business"; $99/year ([enroll](https://developer.apple.com/programs/enroll/)).
- **App transfer** (individual → organization later): keeps Bundle ID, ratings, reviews; iCloud containers/KVS transfer; but Keychain sharing works "only until the app is updated" — the recipient must rebuild the keychain group with their Team ID and "users must re-login once"; TestFlight must be cleared; subscriptions need an app-specific shared secret ([overview](https://developer.apple.com/help/app-store-connect/transfer-an-app/overview-of-app-transfer), [criteria](https://developer.apple.com/help/app-store-connect/transfer-an-app/app-transfer-criteria)).

### 2.6 Can a consumer lawfully paste their own Anthropic key into a third-party native app?

| Source | Relevant text | Reading |
|---|---|---|
| [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) (effective 2025-10-08) §2 | "You may not share your Account login information, Anthropic API key, or Account credentials with anyone else. You also may not make your Account available to anyone else." §3 bans automated access "Except when you are accessing our Services via an Anthropic API Key." Preamble: Commercial Terms "govern your use of any Anthropic API key, the Anthropic Console". | A key typed into an app on the user's own device, sent only to `api.anthropic.com`, is not shared "with anyone else". A key that transits the developer's server **is**. |
| [Commercial Terms](https://www.anthropic.com/legal/commercial-terms) (effective 2025-06-17) | Agreement "between Anthropic and you or the organization … that you represent"; "Services under these Terms are not for consumer use"; D.4: no reselling "except as expressly approved by Anthropic"; D.3: Customer must notify its Users about limits of Outputs; D.5: Customer responsible for all account activity. | The end user is Anthropic's Customer; the developer is not party to that traffic, gets no DPA/ZDR/BAA for it, and is not "reselling" because no Anthropic traffic touches its servers. The "not for consumer use" sentence is a positioning/warranty statement, not a prohibition on individuals holding keys — individuals self-serve Console accounts — but it is a gray zone worth a one-line confirmation from Anthropic. |
| [Usage Policy](https://www.anthropic.com/legal/aup) (effective 2026-11-12) | "Resell, proxy, or otherwise provide access to Claude through unauthorized means, including services that route requests through consumer subscriptions or misrepresent the product or client being used"; must not provide access in violation of the [Supported Regions](https://www.anthropic.com/supported-countries) policy (US, CA, UK, all 27 EU states supported). | Never offer "Sign in with Claude.ai / use your Pro/Max plan"; API keys only; send an honest `User-Agent`; do not geofence-dodge. |
| Apple guidelines | No clause mentions API keys or BYO; 5.1.1(ii) requires the paid product to work without granting data access. | A free on-device tier plus optional key satisfies this; do not sell or link to Anthropic credits in a way that looks like an IAP bypass (3.1.1 judgment call, **not** addressed by any fetched text). |

Conclusion: lawful, with four design conditions — device-direct calls, Keychain-only storage (no developer-side copy), API keys only (no consumer OAuth), and honest disclosure that BYO mode runs under *the user's* Anthropic agreement with standard 30-day retention.

---

## 3. Options compared

### 3.1 The sensitive-data policy

| Option | What leaves the device to Claude | What is indexed where | Pros | Cons |
|---|---|---|---|---|
| A. No masking (mail.md as written) | full image + full OCR text | everything everywhere | best extraction; simplest | SSNs in Drive index, Spotlight snippets, embeddings vendor, 30-day Anthropic retention in BYO mode; indefensible privacy copy |
| B. Mask only the Claude copy (privacy.md) | masked image + placeholder text | full text in FTS/Spotlight/indexableText/sidecar | protects the processor hop | leaves Class A in five other places; two code paths (masked/unmasked text) |
| C. **Three-class policy, single mask pass** (recommended) | masked image + placeholder text with `last4` | Class A only inside the archival PDF; placeholders elsewhere; Spotlight/`indexableText` get summary+tags+Class B | one pass, one truth, testable; taxonomy keeps `*_last4`; search unaffected for realistic queries | cannot search by full SSN/account (open the PDF instead); ~1% extra masking false positives |
| D. Mask the archive too | as C, and the stored PDF is redacted | nothing holds Class A | maximal | breaks the product: the archive must be a faithful copy the user can file taxes with and throw the paper away |

### 3.2 Retention posture for the managed tier

| Posture | Models | Batches / Files | Backfill path | Cost/page (Haiku 5.5 text-only) | Notes |
|---|---|---|---|---|---|
| Standard 30-day | any incl. Fable 5.x | allowed | Batches, 50% off | ≈$0.0003 | simplest; label/consent must say "retained up to 30 days" |
| **ZDR** (recommended) | Haiku/Sonnet/Opus 5.5 only | "No" but **not blocked** → CI rule | inline Messages, cached prompt | ≈$0.0006 | per-org via sales; T&S carve-out still 2 years |
| HIPAA readiness | same as ZDR for our features | blocked with `400` | inline Messages | ≈$0.0006 | permanent; only worth it if selling to providers; PHI-free schemas |

---

## 4. Recommendation for this project

### 4.1 The policy (one page, applies to v1 BYO, v2 App Store, v3 service)

**Classes**

- **A — secrets** (never leave the archival bytes except as `last4`): SSN, ITIN, EIN *of an individual/sole-prop* (treat 9-digit runs near "TIN/EIN" as A when the document is addressed to a person), card PAN, bank account numbers, routing numbers and the entire MICR band, driver-license and passport numbers, MRN and health-plan member/subscriber IDs, passwords/PINs/one-time codes.
- **B — reference IDs**: employer EINs on W-2/1099/K-1, invoice/claim/policy/case/order/confirmation/check numbers, amounts, dates, tax year.
- **C — everything else**: sender, addressee, addresses, body text, summary, tags.

**Where each class may exist**

| Store | A | B | C |
|---|---|---|---|
| Raw capture + archival PDF/A text layer (device blob store, iCloud Drive, Google Drive, Synology) | full | full | full |
| Claude request (masked JPEG ≤1568 px + placeholder OCR text) | `[SSN ••••1234]`, `[ACCT ••••5678]`, `[MICR]` | plain | plain |
| Claude structured output → sidecar `<name>.json` → CloudKit ledger (encrypted fields) | `*_last4` only | plain | plain |
| SQLite FTS5 (`NSFileProtectionComplete`) | indexes the *masked* text → `1234` searchable, full number not | plain | plain |
| Core Spotlight (named index, `.complete`) `textContent` | none | plain | title + summary + sender + tags only |
| Drive `contentHints.indexableText` | none | plain | summary + tags + doc_type + sender (the PDF text layer already gives Drive full text) |
| Drive `appProperties` | — | — | `{sid, h}` only |
| Embeddings input (on-device in v1/v2; Voyage after training opt-out in v3) | none | not useful | title + summary + tags + first ~1,500 tokens of **masked** text |
| Filenames, notifications, share-sheet titles, `OSLog` | none (`privacy: .private` for everything document-derived) | avoid | sender + doc_type + date |
| `metadata.user_id` to Anthropic | — | — | opaque UUID per install, never email |

**Mechanics**: one `Redactor` runs after Vision OCR on word boxes; its output (`maskedImage`, `maskedText`, `placeholders[] {class, last4, bbox}`) is the *only* text any later stage may consume except the PDF writer. Rules: regex + context words for SSN/ITIN/EIN, Luhn for PANs, ABA mod-10 for routing, context for account/MRN/member IDs, geometry for the MICR band on check-aspect pages, and "full text-only, no image" for identity documents (passport/DL/insurance card) detected by aspect ratio. Default on, forced on in managed mode, a settings toggle in BYO mode only.

**Taxonomy edits** (mail.md / claude.md): rename every identifier to `*_last4`; delete `micr_routing` and the `account_number` enum value; add `identifier_kind: tax_id_last4 | account_last4 | member_id_last4 | …`; keep EIN for `tax.w2/1099/k1` as Class B. No PHI in enum/const/pattern values (already true; add a schema lint).

**Enforcement**: a CI test feeds pages carrying synthetic SSNs/PANs/routing numbers and asserts their full form appears in none of: the serialized Claude request, FTS rows, `CSSearchableItem`s, Drive metadata payloads, sidecar JSON, embedding inputs, filenames, log sinks. This is what makes it *one* policy rather than per-report advice.

### 4.2 Claude feature scope

- Allowed everywhere: inline `/v1/messages` with base64 image or `document` block, prompt caching, structured outputs (`strict`), token counting, `inference_geo`.
- **Forbidden in app and service code**: Message Batches, Files API, code execution, MCP connector, web fetch, Covered Models (Fable 5.x/Mythos 5.x). Backfill and re-index run as inline text-only Haiku 5.5 calls with the cached taxonomy prompt; at ≈$0.0006/page a 20,000-page archive is ≈$12. Multi-page documents go inline as a `document` block (≤32 MB / ≤100 pages per request — ingest.md's 128 MB / 600-page figures are the 1M-context tier; keep per-request size small for the retry/durability story anyway).
- Managed tier: one Anthropic org with ZDR on Haiku 5.5 (hot path) and Sonnet 5.5 (hard cases); a separate HIPAA-ready org only if a provider/B2B tier is ever sold. Consent copy must include the 2-year trust-and-safety carve-out.
- BYO tier: standard retention under the user's own org; the app must not claim ZDR; show a "set a spend limit in the Console" tip at key entry.

### 4.3 Consent and labels per mode

| Item | BYO-key mode | Managed mode |
|---|---|---|
| 5.1.2(i) explicit consent (one-time, revocable, before first Claude call) | "Pages are analyzed by Anthropic Claude using **your** API key under **your** Anthropic account (Commercial Terms; standard 30-day deletion). Sensitive numbers are blacked out before upload." | "Pages are analyzed by Anthropic Claude under our zero-data-retention agreement; Anthropic keeps nothing after responding except content flagged by its safety systems (up to 2 years). Sensitive numbers are blacked out before upload." |
| Withdrawal (5.1.1(ii)) | toggle off → on-device-only mode (capture, OCR, archive, FTS continue) | same; subscription keeps working in on-device mode |
| Nutrition label (one per app) | n/a for a personal build; the App Store binary carries the superset → | **Data Linked to You, App Functionality, no tracking**: Photos or Videos, Other User Content, Other Financial Info, Health, Sensitive Info, Name, Physical Address. Do not claim "Data Not Collected" while the managed proxy exists. |
| `PrivacyInfo.xcprivacy` | same categories as the label; `NSPrivacyTracking=false`; required-reason APIs listed | same |
| Privacy policy | states that in BYO mode the developer receives nothing; names Anthropic, Google, Apple, Synology (user-chosen) and, in v3, Voyage as processors; WA MHMDA section (privacy.md) | same plus proxy transient handling |

### 4.4 Legal entity and enrollment

Form the LLC (or equivalent) **before** the App Store submission and enroll as an Organization (D-U-N-S, domain website, domain email). Reasons, in order: 5.1.1(ix) is "should" and reviewer-discretionary, but the store listing will say "tax documents, medical bills, bank statements", which is exactly the "sensitive user information" language; the ZDR/BAA/DPA with Anthropic are contracts with an organization; the "captured means safe to shred" promise is a liability you want behind an entity; and transferring later changes the Team ID so the Keychain access group — where the BYO key and OAuth refresh tokens live — must be rebuilt and "users must re-login once", which is the one interaction this product promised never to need. v1 personal builds can stay on the individual account via TestFlight/ad-hoc.

---

## 5. Risks and unknowns

- **5.1.1(ix) enforcement rate** for document-scanner apps from individual accounts: no data gathered (search budget exhausted); treated as "likely to be raised once marketing mentions tax/medical". Unverified.
- **Masking recall** on real mail (handwriting, faint copies, split numbers) is unmeasured; a missed SSN goes to Anthropic (30-day retention in BYO mode) and into Spotlight/indexableText only if the miss also escapes placeholder generation — the single-pass design means one miss leaks to all downstream stores at once. Measure before advertising.
- **Classification accuracy with masked images** is unmeasured (gap-6 hot-path tests should include masked pages).
- **"Not for consumer use"** in the Commercial Terms and the Consumer Terms' no-sharing clause have no published Anthropic guidance for BYO-key apps; the reading above is a plain-language one, not legal advice. Ask Anthropic for written confirmation before marketing the BYO tier.
- **Drive sharing** may expose `indexableText` to recipients via `fullText` — undocumented; policy keeps Class A out of it regardless.
- **iOS 26 Spotlight → Foundation Models tool**: article body not fetched; whether exposure is opt-in per index is unknown. Policy keeps Class A out of Spotlight regardless.
- **Voyage** has no documented BAA and trains by default; the opt-out is per organization and irreversible from the dashboard. On-device embeddings avoid the question in v1/v2.
- **ZDR does not block Batches/Files**: a future contributor can silently break the posture; CI rule required.
- **Covered Models** may become the fastest option; choosing one forces 30-day retention for that workspace.
- **Stale-risk**: AUP effective 2026-11-12 (nine days after this report); retention article dated 2026-07-01; guideline text as fetched today.

---

## 6. Open questions for the founder

1. Accept "full SSN/account numbers are searchable only by opening the PDF" (Class A policy), or do you want an encrypted, device-only side index for full numbers?
2. Managed tier: ZDR on Haiku/Sonnet 5.5 (no Batches/Files, inline backfill) or standard 30-day retention with Batches? Will you ever sell to healthcare providers (HIPAA org, permanent)?
3. Will the App Store binary ship both modes (one superset label) or BYO-only first (TestFlight) with the managed tier later?
4. Entity: form the LLC now and enroll as Organization, or ship v1/v2 as an individual and accept a Team-ID-changing transfer later?
5. Should identity documents (passport/DL/insurance cards) be classified on-device only and never sent to Claude, as recommended, or sent masked?
6. Is a BYO Voyage key out (recommended: on-device embeddings until v3)?
7. Marketing copy: will you name "tax", "medical", "bank" documents on the store page (raises 5.1.1(ix) and WA MHMDA exposure) or stay generic ("mail and paperwork")?

---

## 7. Sources

Anthropic
- API and data retention (ZDR/HIPAA table, Covered Models, PHI rule): https://platform.claude.com/docs/en/manage-claude/api-and-data-retention
- Structured outputs (data handling, 24 h schema cache, PHI): https://platform.claude.com/docs/en/build-with-claude/structured-outputs
- Batch processing (29-day retention, ZDR/HIPAA not eligible): https://platform.claude.com/docs/en/build-with-claude/batch-processing
- Messages API `metadata.user_id`: https://platform.claude.com/docs/en/api/messages
- Commercial data retention (dated 2026-07-01): https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data
- ZDR products: https://privacy.claude.com/en/articles/8956058-i-have-a-zero-retention-agreement-with-anthropic-what-products-does-it-apply-to
- BAA article: https://privacy.claude.com/en/articles/8114513-business-associate-agreements-baa-for-commercial-customers
- Covered Models support article: https://support.claude.com/en/articles/15425695
- Consumer Terms (effective 2025-10-08): https://www.anthropic.com/legal/consumer-terms
- Commercial Terms (effective 2025-06-17): https://www.anthropic.com/legal/commercial-terms
- Usage Policy (effective 2026-11-12): https://www.anthropic.com/legal/aup
- Supported countries: https://www.anthropic.com/supported-countries
- DPA page returned 404 (unverified): https://www.anthropic.com/legal/dpa

Apple
- App Store Review Guidelines (5.1.1(ii)/(iii)/(ix), 5.1.2(i)): https://developer.apple.com/app-store/review/guidelines/
- App Privacy Details (definitions, categories): https://developer.apple.com/app-store/app-privacy-details/
- Manage app privacy (App Store Connect help): https://developer.apple.com/help/app-store-connect/manage-app-information/manage-app-privacy
- Privacy manifests: https://developer.apple.com/documentation/bundleresources/privacy-manifest-files/describing-data-use-in-privacy-manifests
- Program enrollment: https://developer.apple.com/programs/enroll/
- App transfer overview: https://developer.apple.com/help/app-store-connect/transfer-an-app/overview-of-app-transfer
- App transfer criteria: https://developer.apple.com/help/app-store-connect/transfer-an-app/app-transfer-criteria
- Core Spotlight overview: https://developer.apple.com/documentation/corespotlight
- CSSearchableIndex init(name:protectionClass:): https://developer.apple.com/documentation/corespotlight/cssearchableindex/init(name:protectionclass:)
- Spotlight search tool (body not fetched): https://developer.apple.com/documentation/corespotlight/spotlight-search-tool
- RecognizeDocumentsRequest (iOS 26): https://developer.apple.com/documentation/vision/recognizedocumentsrequest
- DocumentObservation (iOS 26): https://developer.apple.com/documentation/vision/documentobservation

Google
- Drive files resource (contentHints.indexableText, appProperties): https://developers.google.com/workspace/drive/api/reference/rest/v3/files
- Drive search terms (fullText): https://developers.google.com/workspace/drive/api/guides/ref-search-terms
- Drive sharing guide: https://developers.google.com/workspace/drive/api/guides/manage-sharing

Voyage AI
- FAQ (training opt-out, zero-day retention): https://docs.voyageai.com/docs/faq
- Privacy policy: https://www.voyageai.com/privacy

PII detection
- Presidio supported entities: https://presidio.dataprivacystack.org/supported_entities/

Internal reports read: privacy.md, mail.md, claude.md, search.md, ingest.md, storage.md, output.md, business.md, gap-5-per-destination-verify-rename-.md (same directory).
