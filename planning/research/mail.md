# Physical-mail specifics, document taxonomy, and boundary detection

Research dimension for the zero-interaction paper digitizer. Date: 2026-11-03. Note on method: the shared WebSearch budget for this run was exhausted before this agent started, so every finding below comes from directly fetched primary sources (Apple developer docs via their JSON endpoints, IRS, USPS, Anthropic, Microsoft, Google, paperless-ngx, arXiv/GitHub) or is explicitly labeled as unverified recollection. Items marked **[unverified]** could not be confirmed against a fetched page.

## 1. Executive summary

1. Treat the envelope as a first-class, low-cost page: it is the only reliable source of postmark date, sender return address and certified/tracking barcodes; capture it, link it to the contents, and never let it be the "document of record".
2. USPS Informed Delivery has no public API; its daily digest email (grayscale images of letter-size mail) is the only ingest signal and is best consumed by the same email-ingest address the app already needs for e-bills.
3. Apple ships the whole on-device capture stack we need: `VNDetectDocumentSegmentationRequest` (iOS 15+) for page quads, `RecognizeDocumentsRequest` (iOS 26+) for structured text + tables + data detectors (dates, addresses, amounts, tracking numbers), `DetectLensSmudgeRequest` (iOS 26, A14+) for capture gating, and `VNGenerateImageFeaturePrintRequest` (iOS 13+) for instant "already scanned" detection.
4. Form factors fall into four capture modes (sheet, long strip, card, booklet/photo); the camera pipeline must switch mode from the detected quad aspect ratio and the first OCR pass, not from user input.
5. Document boundaries in a continuous stream should be decided by a deterministic on-device scorer (time gap, page-number footers, letterhead/sender continuity, physical "page put down" event) with Claude as a tie-breaker, then made trivially reversible with one-tap merge/split; published page-stream-segmentation systems top out around 93% accuracy, so the UX must assume mistakes.
6. A 26-class US personal-mail taxonomy with per-class key fields, implied action and retention is provided in Section 2.4 as JSON; retention rules are anchored on the IRS 3/6/7-year periods.
7. Per-page cloud understanding on Claude Haiku 5.5 costs well under $0.001 per page at full letter resolution (4,784 visual tokens max on 4.7+ models at $0.10/MTok); Sonnet 5.5 is about $0.01/page; so cost does not constrain the design, latency does.
8. Digital inputs (email forward, share sheet, watched NAS folder, camera roll) should all enter the same normalized "page bundle" pipeline so classification, dedupe and boundary logic are written once.
9. Action items (pay-by, respond-by, renew-by) should become EventKit reminders by default; junk mail should be auto-tagged discardable but still archived (cheap, and it feeds the sender knowledge base and opt-out tooling).
10. Biggest unknowns: real-world accuracy of fully automatic boundary detection on handheld streams, duplex handling without any prompt, and faded thermal receipts.

## 2. Findings

### 2.1 Envelope handling

**What the envelope uniquely carries.** Return address block (sender identity when the letter inside has no letterhead), postmark/meter date (the only evidence of *when* something was mailed, which matters for IRS notices and legal deadlines), Intelligent Mail barcode (IMb), and extra-service labels (Certified Mail, Return Receipt). USPS states the IMb is a 65-bar barcode required on letters and flats prepared for automation prices, including Certified Mail and other extra-service mail, and that it is used to sort and track letters, cards and flats (https://postalpro.usps.com/mailing/intelligent-mail-barcode). The page does not list the field layout or provide a public mailer-ID-to-company lookup; the commonly cited layout (barcode ID, service type, mailer ID, serial, routing ZIP) is **[unverified]** here and there is no public lookup from mailer ID to company name per the fetched page.

**Sender from envelope vs letterhead.** Recommendation: extract both, store both, and prefer letterhead for `sender` and envelope for `sender_mailing_address` and `mailed_date`. When the letter has no letterhead (common for IRS/state notices in windowed envelopes, collections, legal), the envelope return address is the only sender signal. Envelope-to-contents linking is a boundary-detection problem (Section 2.3): an envelope image followed within a short time gap by pages is attached as `envelope_of` the next document, never as a standalone document unless nothing follows.

**Should envelopes be captured at all?** Yes, but as a cheap "attachment page": on-device OCR only (no cloud call) unless the heuristics flag Certified/Registered/IRS/court, in which case the envelope is included in the Claude request so the postmark date is extracted. Capture cost is one extra frame; storage cost is negligible; the value is high for the 2-5% of mail where dates matter.

**USPS Informed Delivery as an ingest signal.** USPS describes it as a free service that emails a morning Daily Digest with grayscale images of the address side of letter-sized mail that passes through automated sorting equipment; items that are not letter-sized or do not pass through automation get no image; previews appear only on days mail is delivered (https://www.usps.com/manage/informed-delivery.htm). The page mentions no API or export. The FAQ page could not be fetched (JS-rendered). A cap of roughly 10 images per digest email, with more on the dashboard, is **[unverified]** recollection. Practical use: forward the digest to the app's ingest address; parse the images; create "expected mail" stubs (sender guess from the envelope image) that are reconciled when the physical piece is scanned the same or next day. This gives the app a provenance record ("USPS imaged this on 2026-11-02; you scanned contents on 2026-11-03") and a nudge when expected mail was never scanned.

### 2.2 Form factors and how capture must adapt

Apple on-device building blocks (all fetched from Apple's documentation JSON):

| API | Min OS | What it gives us | Source |
|---|---|---|---|
| `VNDocumentCameraViewController` / `VNDocumentCameraScan` | iOS 13 | Apple's own scanner UI, page images by index; no documented customization, no documented auto-capture control | https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller |
| `VNDetectDocumentSegmentationRequest` | iOS 15 | Four corner points of the document quad plus a saliency mask, as `VNRectangleObservation` | https://developer.apple.com/documentation/vision/vndetectdocumentsegmentationrequest |
| `DataScannerViewController` | iOS 16 | Live text/barcode scanning with `capturePhoto()`; no document-boundary capture | https://developer.apple.com/documentation/visionkit/datascannerviewcontroller |
| `RecognizeDocumentsRequest` / `DocumentObservation` | iOS 26 | Structured text (words, lines, paragraphs, title), tables (merged cells), lists, barcodes, and DataDetection matches | https://developer.apple.com/documentation/vision/recognizedocumentsrequest |
| `DetectLensSmudgeRequest` | iOS 26, A14/M1+ | 0..1 smudge confidence for capture gating | https://developer.apple.com/documentation/vision/detectlenssmudgerequest |
| `VNGenerateImageFeaturePrintRequest` | iOS 13 | Image embedding for near-duplicate detection | https://developer.apple.com/documentation/vision/vngenerateimagefeatureprintrequest |
| `EKReminder` | iOS 6 | Due-date reminders | https://developer.apple.com/documentation/eventkit/ekreminder |

WWDC25 session 272 states `RecognizeDocumentsRequest` data detectors find phone numbers, email and postal addresses, URLs, times and dates (as calendar events), measurements with units, dollar amounts with currency, and tracking numbers, payment identifiers and flight numbers; text recognition covers 26 languages; everything runs on-device (https://developer.apple.com/videos/play/wwdc2025/272/). The same session notes `CalculateImageAestheticScoresRequest` can flag "utility" images such as documents or receipts, which is useful for camera-roll triage (Section 2.5).

Because `VNDocumentCameraViewController` exposes no capture control, the custom pipeline must be AVFoundation + `VNDetectDocumentSegmentationRequest` on every Nth frame, which is what the speed requirement needs anyway. Capture modes derived from the quad and first OCR pass:

| Form factor | Detection cue | Capture/processing adaptation |
|---|---|---|
| Letter/A4/legal sheet | Quad aspect ~1.29 (letter), ~1.41 (A4), ~1.65 (legal) | Default mode; single frame; perspective-correct to the quad; target >= 300 DPI equivalent (letter at 300 DPI = 2550x3300 px; 12 MP sensor suffices when the page fills the frame) |
| Long thermal receipt | Quad aspect > 2.5 or bottom edge off-frame | Strip mode: capture overlapping frames as the user pans, stitch on-device (feature matching), or accept 2-3 segments; grayscale-contrast enhancement and adaptive thresholding. Thermal paper's dye reverts under heat, humidity, UV, oils and plasticizers (https://en.wikipedia.org/wiki/Thermal_paper), so faded receipts are common: run OCR on a contrast-stretched copy, store the original, and flag `low_confidence_ocr` for Claude to re-read the full-resolution image |
| Index/business card | Quad aspect ~1.6-1.75, short edge small | Card mode: higher digital zoom crop; business cards route to contacts extraction |
| Plastic ID / insurance / credit card | Rounded corners, specular glare, aspect 1.586 (ID-1) | Glare handling: capture 2-3 frames at slightly different angles and composite the non-saturated regions; Azure and Google both ship ID/health-insurance-card models, which confirms this is a distinct class with distinct fields (https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/overview?view=doc-intel-4.0.0) |
| Check | Aspect ~2.3, MICR line at bottom | Check mode: both sides; MICR routing/account via OCR; Azure has a prebuilt Check model (same source) |
| Photo / postcard | No text on first OCR pass, or aspect ~1.4 with a picture | Photo mode: keep color, no binarization, lower priority for cloud understanding |
| Booklet / stapled packet | Two-page spread (aspect ~0.65) or staple detected at corner | Spread splitting at the gutter; packet pages are forced into the same document (Section 2.3) |
| Carbonless (NCR) copy | Low-contrast colored sheet (yellow/pink) with weak impression text | Per-channel contrast normalization before OCR; carbonless sets use colored copies (white original, yellow/other copies) (https://en.wikipedia.org/wiki/Carbonless_copy_paper) |
| Tri-folded letter that will not lie flat | Quad detection succeeds but text lines are curved | Dewarp: perspective correction alone is insufficient; see below |
| Double-sided page | Second side text or bleed-through seen when the page is flipped | See "prompt-free flip handling" below |

**Curl/warp correction.** Apple's segmentation returns a quad and a saliency mask, not a mesh, so folded letters need a dewarping model. UVDoc (SIGGRAPH Asia 2023) predicts a 3D grid mesh and a 2D unwarping grid with a "relatively small" fully convolutional network, MIT-licensed, pretrained weights at `model/best_model.pkl`, MS-SSIM 0.785 / AD 0.119 on the UVDoc benchmark vs DocTr 0.697 / 0.160 (https://github.com/tanguymagne/UVDoc, https://arxiv.org/abs/2302.02887). DocTr (ACM MM 2021) reports MS-SSIM 0.5105 and LD 7.76 on DocUNet (https://github.com/fh2019ustc/DocTr). Neither project states parameter counts or mobile inference time, so the Core ML conversion cost and on-device latency are **unknown** and must be measured. Recommendation: ship v1 with perspective-only correction plus a text-line-curvature detector that flags `needs_dewarp`; run UVDoc server-side on flagged pages for the archival PDF while the on-device OCR proceeds on the uncorrected image (OCR tolerates mild curl better than the archival PDF does).

**Prompt-free flip handling.** With zero interaction the app cannot ask "is there a back side?". Signals that a back side exists: bleed-through (mirrored faint text visible through the sheet in the capture), a "continued on reverse"/"see reverse" string, printed page footers like "Page 1 of 2" with only one page seen, and the physical gesture of the same sheet reappearing flipped (feature print of the new frame is dissimilar but the quad size and paper color/texture match within a short gap). Treat a flipped page captured within ~8 s of its front as side B of the same sheet. Blank backs are detected by low ink coverage after thresholding (paperless-ngx relies on the scanner's blank-page removal; for a camera we do it ourselves) and are dropped but logged.

**Text size floor.** Azure's documented floor for extraction is 12 px text height on a 1024x768 image, roughly 8-point text at 150 DPI (https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/tax-document?view=doc-intel-4.0.0). Claude 4.7+ models downscale to a 2,576 px long edge / 4,784 visual tokens (https://platform.claude.com/docs/en/build-with-claude/vision), i.e. about 235 DPI on a letter page, comfortably above that floor; fine print on insurance EOBs and 1099-B pages should nevertheless be sent as 2-3 crops when on-device OCR confidence is low.

### 2.3 Deciding document boundaries in a continuous stream

**State of the art.** Page stream segmentation (PSS) is the task of splitting a sequence of page images into multi-page documents; a CNN combining text and visual features reached about 93% accuracy on a German federal archive stream (Wiedemann & Heyer, https://arxiv.org/abs/1710.03006). Van Landeghem et al. (WACV 2024) formalize multi-page document classification, page stream classification and document bundle classification and argue existing benchmarks are not representative of real multi-page, multi-channel streams (https://arxiv.org/abs/2308.12896). Google's Custom Splitter predicts page groupings and a class per group, has zero-shot Gemini-based versions, recommends at least 10 (ideally 50) labeled documents per class for a trained version, and explicitly recommends human review because a bad split breaks two documents (https://docs.cloud.google.com/document-ai/docs/custom-splitter). paperless-ngx only splits on separator barcodes (PATCH-T sheets, ASN barcodes, or tag barcodes) and otherwise treats the whole upload as one document (https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/advanced_usage.md).

Conclusion: nobody has a prompt-free, handheld, >99% boundary detector; the design must combine strong physical-world signals (which desktop scanners and PDF streams do not have) with cheap correction.

**Signals available to a handheld camera pipeline, ranked by reliability:**

1. *Physical page events.* The quad disappearing then reappearing is a page swap; the time between is the gap. A page swap under ~4 s, with the same paper color and quad size, is "next page of same thing" with high prior. A gap over ~20 s, or the user leaving the capture screen, is a strong boundary prior.
2. *Printed page numbers.* Footers like "Page 2 of 5", "2/5", "continued" parsed on-device from `RecognizeDocumentsRequest` text. "N of M" with M > 1 is near-deterministic: pages 1..M are one document, and page 1 of a new sequence is a boundary.
3. *Envelope sandwich.* Envelope image -> pages -> envelope image: the second envelope opens a new document.
4. *Layout/sender continuity.* Same letterhead region hash (feature print of the top 15% of the page), same account/claim/policy number string, same statement date, same font family, same paper color. A match keeps the document open; a mismatch is a boundary candidate, not a decision (multi-page packets often mix stock).
5. *Form-factor change.* Sheet -> receipt -> card transitions are boundaries.
6. *Semantic check (cloud).* When the on-device score is in the uncertain band, send the last page of the open document and the new page to Claude with a one-question prompt ("same document? answer with JSON") using Haiku 5.5 for latency.

**Recommended algorithm (two-tier):**

```
on new_page(p):
  if is_envelope(p): start_pending_envelope(p); return
  if dup := nearest_feature_print(p, threshold) and ocr_jaccard(p, dup) > 0.9:
      announce("already scanned"); attach_as_duplicate(p, dup); return   # < 100 ms, all on-device
  s = 0
  s += gap_score(t_now - t_prev)                 # <4s: -2, 4-20s: 0, >20s: +2, left screen: +3
  s += page_number_score(p, open_doc)            # "N of M" continuation: -5; "1 of M" or restart: +5
  s += formfactor_change(p, open_doc) ? +3 : 0
  s += letterhead_match(p, open_doc) ? -2 : +1
  s += id_number_match(p, open_doc) ? -3 : 0     # account/claim/policy/case number
  s += pending_envelope ? +2 : 0
  if s <= -2: append(p, open_doc)
  elif s >= 2: close(open_doc); open_doc = new_doc(p, envelope=pending_envelope)
  else: decision = claude_same_document(open_doc.last, p); apply(decision)
  record(boundary_decision, score, signals)      # for one-tap undo and for training
```

Every document's "captured" state is reached per page (durability is per page, not per document), so a wrong boundary never loses data; it only mislabels grouping. The timeline UI exposes **merge-with-previous** and **split-here** as single taps on the page strip, and both are logged as labels to retrain the scorer. Classification and extraction run again automatically after a merge/split.

**Duplicates.** Feature prints (`VNGenerateImageFeaturePrintRequest`, iOS 13+) give an embedding with a distance function; the page does not document the metric or a threshold, so the threshold must be tuned on labeled pairs. Pair it with an OCR-text shingling (Jaccard over 5-grams) check so the same form with different values (two months of the same utility bill) is not called a duplicate. paperless-ngx dedupes on file checksum only and merely warns by default (https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/usage.md), which is inadequate for camera captures where no two images are byte-identical.

### 2.4 US personal-mail taxonomy

Evidence that these classes have stable, machine-extractable fields: Azure Document Intelligence v4.0 ships prebuilt models for W-2, 1098/1098-E/1098-T, 1099 and 30+ variations (A, B, C, CAP, Combo, DIV, G, H, INT, K, LS, LTC, MISC, NEC, OID, PATR, Q, QA, R, S, SA, SB, SSA), 1040 and schedules, 1095-A/C, W-4, bank statement, check, contract, credit card, invoice, pay stub, receipt, mortgage 1003/1004/1005/1008/closing disclosure, health insurance card, identity, marriage certificate (https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/tax-document?view=doc-intel-4.0.0 and the overview page). Google Document AI has GA parsers for W-2, pay slip, bank statement, US driver license, ID proofing, expense/receipt and invoice, plus Custom Extractor, Custom Classifier and Custom Splitter (https://docs.cloud.google.com/document-ai/docs/processors-list). Recipient deadlines come from the IRS General Instructions for Certain Information Returns (https://www.irs.gov/instructions/i1099gi): most 1098/1099/W-2G to recipients by January 31; 1099-B, 1099-DA, 1099-S, 1099-LS, 1099-SB by February 15; 5498 by May 31 (FMV portion January 31); 5498-SA May 31; 5498-ESA April 30. Retention anchors come from the IRS (https://www.irs.gov/businesses/small-businesses-self-employed/how-long-should-i-keep-records): 3 years normally; 6 years if income under-reported by more than 25%; 7 years for worthless securities/bad debt claims; indefinitely if no return or fraudulent return; property records until the limitations period expires for the year the property is disposed of; employment tax records at least 4 years. Non-tax retention values below are practitioner convention and are marked `retention_basis: "convention"`.

```json
[
  {"class":"tax.w2","examples":["W-2","W-2c"],"key_fields":["employer","employer_ein","employee_ssn_last4","tax_year","box1_wages","box2_fed_withheld","state_wages"],"action":"keep_for_tax_year","due":"recipient by Jan 31 (IRS i1099gi)","retention":"tax_year+7y","retention_basis":"IRS 3/6/7y rules, use max","junk":false},
  {"class":"tax.1099","examples":["1099-NEC","1099-MISC","1099-INT","1099-DIV","1099-B","1099-R","1099-G","1099-K","1099-S","1099-SA","1099-Q","1099-C","1099-OID","1099-DA","1099-SSA"],"key_fields":["payer","payer_tin","tax_year","variant","box_amounts","recipient_name"],"action":"keep_for_tax_year","due":"Jan 31; B/DA/S/LS/SB Feb 15","retention":"tax_year+7y","retention_basis":"IRS","junk":false},
  {"class":"tax.1098","examples":["1098 mortgage interest","1098-E","1098-T","1098-C"],"key_fields":["lender_or_school","tax_year","interest_or_tuition_amount","account_number"],"action":"keep_for_tax_year","due":"Jan 31","retention":"tax_year+7y; 1098 for property: until disposal+limitations","retention_basis":"IRS","junk":false},
  {"class":"tax.1095","examples":["1095-A","1095-B","1095-C"],"key_fields":["issuer","tax_year","covered_individuals","months_covered","marketplace_id"],"action":"keep_for_tax_year","retention":"tax_year+7y","retention_basis":"IRS","junk":false},
  {"class":"tax.k1","examples":["Schedule K-1 (1065/1120-S/1041)"],"key_fields":["entity","ein","tax_year","partner_share_amounts"],"action":"keep_for_tax_year","retention":"tax_year+7y; indefinitely while holding the interest","retention_basis":"IRS","junk":false},
  {"class":"tax.notice","examples":["IRS CP notices","state DOR notices"],"key_fields":["agency","notice_number","tax_year","amount_due","respond_by_date","letter_date","postmark_date"],"action":"respond_by_date (hard)","retention":"indefinitely","retention_basis":"convention","junk":false,"envelope_required":true},
  {"class":"tax.property","examples":["property tax bill","assessment notice"],"key_fields":["assessor","parcel_id","tax_year","amount_due","due_dates[]"],"action":"pay_by_date","retention":"until property disposal + limitations period","retention_basis":"IRS property rule","junk":false},
  {"class":"banking.statement","examples":["checking/savings statement","credit card statement"],"key_fields":["institution","account_last4","period_start","period_end","closing_balance","minimum_due","payment_due_date"],"action":"pay_by_date if balance due; else file","retention":"1y, 7y if supports tax item","retention_basis":"convention","junk":false},
  {"class":"banking.notice","examples":["rate change","overdraft","fraud alert","new card"],"key_fields":["institution","account_last4","effective_date","summary"],"action":"review","retention":"1y","retention_basis":"convention","junk":false},
  {"class":"investment.statement","examples":["brokerage statement","401k/IRA statement","trade confirmation","5498"],"key_fields":["institution","account_last4","period","ending_value","contributions","cost_basis_items"],"action":"file; keep_for_tax_year if 5498 or year-end","retention":"year-end: until account closed + 7y; monthly: 1y","retention_basis":"convention","junk":false},
  {"class":"insurance.policy","examples":["auto/home/life/umbrella policy","declarations page","renewal"],"key_fields":["carrier","policy_number","insured","effective_date","expiration_date","premium","coverage_summary"],"action":"renew_by_date; pay_by_date","retention":"life of policy + 3y; life insurance: indefinitely","retention_basis":"convention","junk":false},
  {"class":"insurance.eob","examples":["Explanation of Benefits","Medicare Summary Notice"],"key_fields":["insurer","member_id","claim_number","provider","service_date","billed","allowed","patient_responsibility","this_is_not_a_bill"],"action":"reconcile_with_medical_bill; no payment","retention":"1y after claim resolved; 7y if HSA/medical deduction","retention_basis":"convention","junk":false},
  {"class":"medical.bill","examples":["provider invoice","hospital bill"],"key_fields":["provider","patient","account_number","service_date","amount_due","due_date","claim_number"],"action":"pay_by_date after EOB match","retention":"7y if HSA/deduction else 1y","retention_basis":"convention","junk":false},
  {"class":"medical.record","examples":["lab results","imaging report","visit summary","vaccination record","prescription label/info"],"key_fields":["provider","patient","date","test_names","results","medication","dosage"],"action":"file","retention":"indefinitely","retention_basis":"convention","junk":false},
  {"class":"utility.bill","examples":["electric","gas","water","internet","mobile phone","trash"],"key_fields":["provider","account_number","service_address","period","amount_due","due_date","usage"],"action":"pay_by_date","retention":"1y; 7y if home-office deduction","retention_basis":"convention","junk":false},
  {"class":"government.id_and_notices","examples":["DMV registration/renewal","jury summons","Social Security statement/benefit letter","immigration (USCIS) notices","voter registration","passport correspondence"],"key_fields":["agency","case_or_id_number","person","respond_by_date","appear_date","expiration_date","postmark_date"],"action":"respond_by_date / renew_by_date (hard)","retention":"SSA and USCIS: indefinitely; DMV: until superseded; jury: 1y","retention_basis":"convention","junk":false,"envelope_required":true},
  {"class":"housing.mortgage_lease_hoa","examples":["mortgage statement","escrow analysis","lease","HOA dues/notices","rent increase"],"key_fields":["servicer_or_landlord","account_or_unit","period","principal","interest","escrow","amount_due","due_date","lease_start","lease_end"],"action":"pay_by_date; lease: keep_until_moveout+","retention":"mortgage: until payoff + 7y; lease: term + 3y","retention_basis":"convention","junk":false},
  {"class":"legal","examples":["court notices","attorney letters","contracts","wills/trust docs","settlement"],"key_fields":["parties","case_number","court","date","deadline","signature_required"],"action":"respond_by_date (hard); keep_original_flag=true","retention":"indefinitely","retention_basis":"convention","junk":false,"envelope_required":true},
  {"class":"employment","examples":["pay stub","benefits enrollment","offer letter","performance/HR letters","COBRA notices"],"key_fields":["employer","pay_period","gross","net","ytd","benefit_plan","enrollment_deadline"],"action":"pay stubs: file until W-2 reconciles; enrollment: respond_by_date","retention":"pay stubs 1y; employment agreements: indefinitely","retention_basis":"convention","junk":false},
  {"class":"education","examples":["tuition bill","transcript","financial aid","student loan statement","school notices"],"key_fields":["institution","student","term","amount_due","due_date","loan_servicer","interest_paid"],"action":"pay_by_date; keep_for_tax_year if 1098-T/E related","retention":"transcripts indefinitely; bills 7y","retention_basis":"convention","junk":false},
  {"class":"auto","examples":["registration","title","service/repair invoice","recall notice","toll bill","parking ticket"],"key_fields":["vehicle","vin","plate","date","amount_due","due_date","odometer"],"action":"pay_by_date; recall: respond","retention":"title/registration: ownership + 1y; repairs: ownership","retention_basis":"convention","junk":false},
  {"class":"subscription_membership","examples":["renewal notice","membership card","magazine renewal","gym"],"key_fields":["organization","member_id","renewal_date","amount"],"action":"renew_by_date (soft)","retention":"until superseded","retention_basis":"convention","junk":false},
  {"class":"receipt_warranty_manual","examples":["store receipt","online order packing slip","warranty card","product manual"],"key_fields":["merchant","date","total","items[]","payment_last4","return_by_date","warranty_expiry","serial_number"],"action":"return_by_date (soft); file","retention":"receipt: return window or warranty term; big-ticket: ownership; tax-deductible: 7y","retention_basis":"convention","junk":false},
  {"class":"personal_correspondence","examples":["letters","greeting cards","invitations","postcards","photos"],"key_fields":["from","to","date","event_date","rsvp_by"],"action":"rsvp_by_date if present; else file","retention":"indefinitely (user)","retention_basis":"user preference","junk":false},
  {"class":"marketing_junk","examples":["catalogs","prescreened credit offers","insurance solicitations","political mail","coupons","charity appeals","local flyers"],"key_fields":["sender","offer_expiry","opt_out_contact"],"action":"discard; auto-tag discardable; feed opt-out","retention":"30d then purge (user-configurable)","retention_basis":"convention","junk":true},
  {"class":"payment_instrument","examples":["paper check received","refund check","rebate card","gift card","convenience checks"],"key_fields":["payer","amount","check_number","date","payee","micr_routing","micr_account_last4","expiry"],"action":"deposit_by_date; keep_original_flag=true until deposited","retention":"7y if income; else 1y","retention_basis":"convention","junk":false},
  {"class":"shipping","examples":["package label","delivery notice","customs form","return label"],"key_fields":["carrier","tracking_number","sender","ship_date","delivery_date"],"action":"track; discard after delivery","retention":"90d","retention_basis":"convention","junk":false}
]
```

Two cross-cutting fields apply to every class: `envelope_required` (keep postmark evidence) and `keep_original_flag` (Section 2.6).

### 2.5 Digital inputs

| Input | Mechanism | Numbers and constraints | Source |
|---|---|---|---|
| Forward email to an ingest address | Inbound-parse webhook: SendGrid posts each attachment as a form part, recommends total message + attachments <= 30 MB; Cloudflare Email Workers expose `message.raw` to a Worker with an example 25 MiB inbound-size check and recommend `postal-mime` for MIME parsing; paperless-ngx polls IMAP every 10 min by default and tracks processed messages by UID | 30 MB (SendGrid), 25 MiB example (Cloudflare), 10 min poll (paperless) | https://www.twilio.com/docs/sendgrid/for-developers/parsing-email/setting-up-the-inbound-parse-webhook, https://developers.cloudflare.com/email-routing/email-workers/, https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/usage.md |
| PDFs/e-bills | Same path; born-digital PDFs skip OCR and use the embedded text layer; Claude accepts PDFs directly, with each page typically costing 1,500-3,000 tokens and no extra PDF fee (request-size and page caps per Anthropic docs: 32 MB / 600 pages per the claude-api skill cache, which should be re-checked on the PDF page) | 1,500-3,000 tokens/page | https://platform.claude.com/docs/en/build-with-claude/pdf-support |
| Share sheet | iOS Share/Action extension receiving PDF/image/URL from Mail, Files, Safari; must write to the shared App Group container and enqueue, because extensions are memory- and time-limited | n/a (founder-known) | Apple App Extensions (not re-fetched) |
| Desktop scanner watched folder | ScanSnap/NAS writes PDFs to a folder; the app's sync agent (or a small service on the Synology) watches it. paperless-ngx's consumption directory is the reference pattern ("think of this folder as a temporary location"; files are removed after consumption) | **[unverified]** ScanSnap Home cloud/folder destinations (vendor pages returned 403/404) | https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/usage.md |
| Camera roll | `PHPhotoLibraryChangeObserver` on new assets; triage with `CalculateImageAestheticScoresRequest` "utility image" flag and `VNDetectDocumentSegmentationRequest` presence; only document-like photos are offered for ingestion | iOS 26 for aesthetics scores | https://developer.apple.com/videos/play/wwdc2025/272/ |
| USPS Informed Delivery digest | Email path, see 2.1 | n/a | https://www.usps.com/manage/informed-delivery.htm |

All inputs normalize to the same `PageBundle {pages[], source, received_at, hints}` so boundary detection (Section 2.3) and classification run once. Multi-page PDFs from a flatbed or NAS carry no physical-gap signal; there the scorer relies on page numbers, letterhead continuity and the Claude tie-breaker, exactly as PSS systems do.

### 2.6 Action items

- **Due dates to reminders/calendar.** Every class with `pay_by_date`, `respond_by_date`, `renew_by_date`, `appear_date`, `rsvp_by_date` or `return_by_date` creates an `EKReminder` (`dueDateComponents`, `priority`) in a dedicated "Mail" list; hard deadlines (tax notice, legal, government) also create a calendar event the day before. Dates come first from `RecognizeDocumentsRequest` data detectors (dates as calendar events, dollar amounts with currency) and are confirmed by the Claude extraction so a misread "Pay by" never silently sets a reminder; conflicting dates produce a reminder with both candidates in the note.
- **Junk-mail detection.** Signals: presorted standard/marketing mail indicia, "or current resident", prescreened-offer language, no account number, sender in the user's junk-sender list, Informed Delivery image showing a catalog. Policy: still capture and OCR (cheap), tag `discardable`, exclude from search by default, purge after 30 days. Reduce the stream at the source: DMAchoice registration is $8 online ($9 by mail) for 10 years (https://www.dmachoice.org/register.php); PaperKarma is a subscription app that photographs mailers and files opt-outs, claiming >100,000 mailers in its database and results in 2-3 months (self-reported, https://paperkarma.com/); OptOutPrescreen for credit/insurance prescreened offers could not be fetched (403) so its 5-year/permanent terms are **[unverified]**. A "stop this sender" one-tap can prefill a DMAchoice/PaperKarma flow or generate the opt-out letter.
- **"Keep original" flag.** paperless-ngx's workflow is instructive: decide per document whether the paper must be kept (contracts, certificates), write an Archive Serial Number (ASN) on it, store physically by ASN, discard the rest (https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/usage.md). For zero interaction, the classifier sets `keep_original_flag` automatically for legal, titles, certificates, undeposited checks, signed originals and anything with a wet signature or raised seal, and the app announces "keep this paper" at capture time with a spoken/haptic cue and assigns an ASN the user can write on the page; everything else gets "safe to discard" once durable storage is confirmed.

### 2.7 Cost sanity check for Claude understanding

Claude 4.7+ models process images in 28x28 patches with a 2,576 px long-edge / 4,784 visual-token cap; a 1000x1000 image costs 1,296 tokens (https://platform.claude.com/docs/en/build-with-claude/vision). Pricing: Haiku 5.5 $0.10 input / $0.50 output per MTok (prompts <= 100K), Sonnet 5.5 $2 / $10, Opus 5.5 $4 / $20; Batch API is 50% off; cache hits are 0.05x base on Opus 5.5/Sonnet 5.5 (https://platform.claude.com/docs/en/about-claude/pricing). A full-resolution letter page (~4,784 tokens) plus ~1,000 prompt tokens and ~600 output tokens is therefore about $0.0009 on Haiku 5.5, about $0.018 on Sonnet 5.5, and about $0.035 on Opus 5.5 per page; at 30 pages/day that is under $1/month on Haiku and about $16/month on Sonnet. Multi-image requests over 20 images require each image <= 3,000 px on any side (same vision page), which matters for batch re-processing of packets.

## 3. Options compared

| Decision | Option A | Option B | Option C | Pick |
|---|---|---|---|---|
| Capture UI | `VNDocumentCameraViewController` (iOS 13; Apple UI, no capture control) | Custom AVFoundation + `VNDetectDocumentSegmentationRequest` (iOS 15) + smudge gating (iOS 26) | `DataScannerViewController` + `capturePhoto()` (iOS 16; no document quads) | B |
| On-device text structure | `VNRecognizeTextRequest` lines only | `RecognizeDocumentsRequest` (iOS 26; paragraphs, tables, lists, data detectors) | Third-party OCR SDK | B, with A as the iOS 15-18 fallback |
| Boundary detection | Separator sheets/barcodes (paperless) | Deterministic on-device scorer + Claude tie-break + one-tap merge/split | Cloud splitter only (Google Custom Splitter style) | B |
| Duplicate detection | File checksum (paperless default) | Feature print + OCR shingles | Cloud embedding | B |
| Dewarp | Perspective only | UVDoc server-side on flagged pages | UVDoc/DocTr converted to Core ML on-device | B now, C if latency allows |
| Envelope policy | Never capture | Capture, on-device OCR, attach to next document; cloud only when certified/government/legal | Always send to Claude | B |
| Junk mail | Discard at capture | Capture, tag discardable, purge in 30 d, feed opt-out | Always archive forever | B |
| Email ingest | IMAP polling (paperless style, 10 min) | Inbound-parse webhook (SendGrid/Cloudflare, seconds) | Gmail API push | B for the service; C optional for Gmail users |

## 4. Recommendation for this project

1. Build the capture loop on AVFoundation with `VNDetectDocumentSegmentationRequest` on every 3rd frame, sharpness (Laplacian variance) and `DetectLensSmudgeRequest` gating, and auto-shutter when the quad is stable for ~300 ms. Do not use `VNDocumentCameraViewController`; it offers no control over auto-capture and would cap the speed story.
2. Run `VNGenerateImageFeaturePrintRequest` on the cropped page immediately and compare against the last ~200 pages; announce "already scanned" by voice and haptic within 100 ms when distance is below the tuned threshold and OCR shingles agree. Tune the threshold on a labeled set of 500 pairs (same page re-shot vs. different months of the same form).
3. Run `RecognizeDocumentsRequest` (iOS 26) on-device for the text layer, page-number parsing, data-detector dates/amounts/tracking numbers and letterhead hashing; fall back to `VNRecognizeTextRequest` on iOS 15-18.
4. Implement the two-tier boundary scorer from Section 2.3 with Haiku 5.5 as tie-breaker, log every decision with its signals, and ship merge/split as one-tap actions on the capture timeline. Measure boundary F1 on a 200-document handheld corpus before launch; expect to iterate.
5. Treat envelopes as attachment pages with on-device OCR only, promoted to a cloud call when the heuristics say certified/government/legal/IRS; store `mailed_date` separately from `document_date`.
6. Ship the 26-class taxonomy as the classifier's closed label set with the JSON key fields as the extraction schema (use Claude structured outputs), and derive reminders and retention from `action`/`retention` fields rather than from free text.
7. Ingest everything digital through one inbound-parse address plus share sheet and a NAS watched folder, normalized to the same page bundle; parse the Informed Delivery digest into "expected mail" stubs.
8. Handle faded receipts and carbonless copies with on-device contrast normalization before OCR and always send the original crop, not the enhanced one, to Claude for the archival extraction.
9. Defer dewarping to a server-side UVDoc pass on pages flagged by text-line curvature; benchmark a Core ML port later.
10. Set `keep_original_flag` automatically for legal/title/certificate/check classes and give the user an ASN at capture time; everything else gets an explicit "safe to discard" only after storage confirmation.

## 5. Risks and unknowns

- Boundary detection accuracy on real handheld streams is unknown; literature says ~93% on archive streams with text+vision models, and Google recommends human review after splitting. The one-tap merge/split UX is the mitigation, not a nice-to-have.
- Prompt-free duplex handling rests on heuristics (bleed-through, "see reverse", footers, flip gesture) with no published benchmark; expect misses on blank-backed forms that are actually double-sided.
- `RecognizeDocumentsRequest`, `DetectLensSmudgeRequest` and the data detectors are iOS 26-only; `DetectLensSmudgeRequest` needs A14/M1 or later. Supporting iOS 15-18 means a second, weaker on-device path.
- Apple does not document the feature print distance metric, the capture resolution of its scanner, or any latency numbers; all on-device timings must be measured.
- UVDoc and DocTr publish no parameter counts or mobile inference times; Core ML conversion effort is unknown.
- Informed Delivery has no API and the digest's image count cap is unverified; email format changes could silently break the parser.
- Google Document AI pricing and ScanSnap folder/cloud destinations could not be fetched (JS-rendered or 403) and are unknown here; Azure's pricing page showed placeholders. None of these block the Claude-first design.
- Thermal-receipt fading is documented but recovery techniques are not; some receipts will be unrecoverable regardless of model.
- Retention values outside the IRS rules are convention, not law; the app should present them as defaults the user can edit, never as advice.

## 6. Open questions for the founder

1. Minimum iOS version: is iOS 26-only acceptable for v1 (unlocks structured OCR, data detectors, smudge detection), or must iOS 15-18 be supported?
2. Should envelopes be shown in the archive as pages of the document, as a collapsed attachment, or hidden unless certified/government?
3. How aggressive should auto-discard of junk be: purge after 30 days, or keep forever as a searchable sender history?
4. Do you want the app to write Archive Serial Numbers (ASN) for keep-original documents, and if so printed labels or handwritten?
5. For the Claude tie-breaker on boundaries, is a ~300-800 ms cloud round-trip acceptable in the uncertain band, or must boundaries be decided entirely on-device with later cloud correction?
6. Do you receive mail for multiple people/households (spouse, kids, a business)? That changes the `recipient` field from a nicety to a primary partition key.
7. Should reminders go to Apple Reminders, Calendar, both, or an in-app list with notifications?
8. Is server-side dewarping (page image leaves the device for UVDoc) acceptable under your privacy posture, given the user's own API key model?

## 7. Sources

- IRS, How long should I keep records: https://www.irs.gov/businesses/small-businesses-self-employed/how-long-should-i-keep-records
- IRS, General Instructions for Certain Information Returns (2026 chart): https://www.irs.gov/instructions/i1099gi
- USPS, Informed Delivery: https://www.usps.com/manage/informed-delivery.htm
- USPS PostalPro, Intelligent Mail barcode: https://postalpro.usps.com/mailing/intelligent-mail-barcode
- Apple, VNDocumentCameraViewController: https://developer.apple.com/documentation/visionkit/vndocumentcameraviewcontroller
- Apple, VNDocumentCameraScan: https://developer.apple.com/documentation/visionkit/vndocumentcamerascan
- Apple, DataScannerViewController: https://developer.apple.com/documentation/visionkit/datascannerviewcontroller
- Apple, VNDetectDocumentSegmentationRequest: https://developer.apple.com/documentation/vision/vndetectdocumentsegmentationrequest
- Apple, RecognizeDocumentsRequest: https://developer.apple.com/documentation/vision/recognizedocumentsrequest
- Apple, DocumentObservation and Container: https://developer.apple.com/documentation/vision/documentobservation
- Apple, DetectLensSmudgeRequest: https://developer.apple.com/documentation/vision/detectlenssmudgerequest
- Apple, VNGenerateImageFeaturePrintRequest: https://developer.apple.com/documentation/vision/vngenerateimagefeatureprintrequest
- Apple, EKReminder: https://developer.apple.com/documentation/eventkit/ekreminder
- Apple, WWDC25 session 272, Read documents using the Vision framework: https://developer.apple.com/videos/play/wwdc2025/272/
- Anthropic, Vision: https://platform.claude.com/docs/en/build-with-claude/vision
- Anthropic, PDF support: https://platform.claude.com/docs/en/build-with-claude/pdf-support
- Anthropic, Pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Microsoft, Document Intelligence overview (prebuilt models): https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/overview?view=doc-intel-4.0.0
- Microsoft, Document Intelligence US tax documents: https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/prebuilt/tax-document?view=doc-intel-4.0.0
- Microsoft, Document Intelligence pricing (placeholders only): https://azure.microsoft.com/en-us/pricing/details/ai-document-intelligence/
- Google, Document AI processor list: https://docs.cloud.google.com/document-ai/docs/processors-list
- Google, Document AI Custom Splitter: https://docs.cloud.google.com/document-ai/docs/custom-splitter
- paperless-ngx, Usage: https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/usage.md
- paperless-ngx, Advanced usage (barcode separators, ASN): https://raw.githubusercontent.com/paperless-ngx/paperless-ngx/main/docs/advanced_usage.md
- Wiedemann & Heyer, Page Stream Segmentation with CNNs: https://arxiv.org/abs/1710.03006
- Van Landeghem et al., Beyond Document Page Classification (WACV 2024): https://arxiv.org/abs/2308.12896
- Verhoeven, Magne, Sorkine-Hornung, UVDoc (SIGGRAPH Asia 2023): https://arxiv.org/abs/2302.02887 and https://github.com/tanguymagne/UVDoc
- DocTr: https://github.com/fh2019ustc/DocTr
- SendGrid Inbound Parse: https://www.twilio.com/docs/sendgrid/for-developers/parsing-email/setting-up-the-inbound-parse-webhook
- Cloudflare Email Workers: https://developers.cloudflare.com/email-routing/email-workers/
- DMAchoice registration: https://www.dmachoice.org/register.php
- PaperKarma: https://paperkarma.com/
- Wikipedia, Thermal paper: https://en.wikipedia.org/wiki/Thermal_paper
- Wikipedia, Carbonless copy paper: https://en.wikipedia.org/wiki/Carbonless_copy_paper
