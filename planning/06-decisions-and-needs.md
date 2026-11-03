# Decisions, what I need from you, and open questions

Date: 2026-11-03.

## Decisions (each has a recommended default; say "defaults" and we proceed)

| # | Decision | Recommended default | Why | Alternative |
|---|---|---|---|---|
| 1 | What "captured" promises | Haptic at S1 (on this phone), lock icon at S2 (verified in one destination), paper goes when the lock shows | The only honest sub-second promise; S2 depends on the network | A "shred-safe" toggle that withholds the haptic until S2 (slower, offered as an option) |
| 2 | Minimum iOS version | iOS 26.0, with iOS 27 features gated | Same hardware as iOS 27, ~80% of iPhones, floor for the document-OCR and smudge APIs | iOS 18 (loses `RecognizeDocumentsRequest`, lens smudge, continued processing) or iOS 27 (about 15% of US iPhones today) |
| 3 | Capture resolution | 12 MP with the 0.78 framing gate; 48 MP only in stand mode | 24 MP is deferred-only, 48 MP takes seconds; 12 MP framed is 286+ ppi on Letter | Accept Legal paper never reaching 294 ppi at 12 MP, or require stand mode for Legal |
| 4 | Junk mail | Archived forever, hidden by default, Claude call skipped once the classifier is confident | Your requirement is that nothing captured disappears | Purge after 30 days (the mail report's suggestion) |
| 5 | First off-device copy in v1 | iCloud Drive ubiquity container, with fall-through to Google Drive or Synology | OS-managed, survives app deletion, Files-visible, E2EE under Advanced Data Protection, no backend | A service relay bucket from day one (requires a backend and a privacy posture in v1) |
| 6 | Embeddings | On-device bge-small in sqlite-vec; no Voyage in v1/v2 | Voyage trains on inputs by default; the "nothing leaves but masked Claude requests" story stays true | Voyage after a training opt-out, masked text only, in the service phase |
| 7 | Sensitive classes to Claude | Identity documents text-only always; tax, medical and legal pages send the masked image by default, with a user toggle for text-only | Tax forms are where layout cues help most; the mask already removes Class A secrets | Text-only for all sensitive classes (the local-first proposal) |
| 8 | Company structure before the App Store | Form an LLC and enrol as an Apple Organization before submission | Guideline 5.1.1(ix); a later individual-to-organization transfer changes the Team ID and forces a Keychain re-login | Ship as an individual and transfer later (costs every user a re-login) |
| 9 | Pricing | Free on-device and BYO-key tier; managed $49.99/yr or $5.99/mo with a ~500-page fair-use cap, 14-day trial, Family Sharing | COGS under 10% of net; incumbents anchor at $40 to $70 per year | One-time purchase; or managed-only |
| 10 | Name | Papersieve (clean) or Papershed (better brand, no .com) | See `05-names.md` | Quietpaper, Afterpaper, another round |

## What I need from you

**Now (for Phase 0):**

- An Anthropic Console organization and API key with a spend limit set (a few dollars covers the whole harness). Tell me the usage tier; Evaluation-tier limits can throttle a beta.
- The test iPhones you have (ideal: 13, 15 Pro, 16, 17 Pro; minimum: a 13 and one Pro). Note the iOS version on each.
- About 200 pages of your real mail with typed ground truth, as described in `04-roadmap.md`, plus 150 natural-language queries you would actually ask. This corpus never leaves your devices except for the Claude harness, which sends masked images.
- Your Synology DSM version, whether 2FA is on, whether the NAS is reachable from outside your network, and whether it can get a publicly trusted certificate (DSM Let's Encrypt on a `synology.me` name or Tailscale).
- Whether you use iCloud Advanced Data Protection and how full your iCloud is.
- Whether Legal-size paper matters to you.

**Before TestFlight:**

- A Google Cloud project for the Drive integration (`drive.file` scope, OAuth consent screen, brand verification on a domain you own with a published privacy policy).
- A domain for the product (also needed for the Google consent screen and later for email ingestion).

**Before the App Store:**

- The LLC, a D-U-N-S number, and Apple Organization enrolment.
- A Cloudflare account (Worker proxy) and, for the service phase, Supabase.
- A sales conversation with Anthropic for zero data retention on the managed tier.

## Open questions I could not settle from research

1. Does Apple's document segmenter hold up on white-on-white, folded and windowed mail? Week-two corpus test; Genius Scan's detector is the plan B.
2. What is the real `.fast` OCR latency on A15 at 2 to 3 MP? If it exceeds ~600 ms, the text-confirmed duplicate leaves the sub-second path and the visual hint stands alone.
3. Haiku 5.5 with thinking off: time to first token from a phone, extraction accuracy on masked handheld pages, refusal rate on medical, ID and financial pages. The harness answers all three.
4. Does `kCGPDFContextCreatePDFA` produce veraPDF-valid PDF/A-2u? One-day spike.
5. iCloud Drive container upload timing after force-quit and with a full account. Tests T9 and T11 in the gap-4 matrix.
6. Masking recall for SSNs and account numbers on OCR-mangled or handwritten text. Measured on your corpus before the feature is described anywhere.
7. Thermal: how many pages at 20 per minute before the serious state on an iPhone 13, with and without the torch.
8. Whether `RotationCoordinator` behaves usefully when the phone points straight down (undocumented); the plan uses a prior plus an OCR vote regardless.
9. Synology port and QuickConnect facts could not be fetched from Synology's own site (JavaScript-rendered); they are from secondary sources and get confirmed on your NAS.
10. FTC civil-penalty figure after the September 2026 inflation adjustment (the January 2025 figure of $53,088 is the floor).

## Not in scope of this plan (deliberately)

- Mail-scanning services, accounting-software integrations and Android before the iOS product works.
- Custom OCR models or self-hosted OCR; revisit only if Vision's character error rate on your mail exceeds about 5%.
- EU launch requirements (copie fiable, GoBD, qualified timestamps) until a US version ships.
- Gmail OAuth (Restricted scopes, CASA assessment, 100-user cap) until the product has revenue.
