# Business model, unit economics and roadmap — zero-interaction paper digitizer (iOS first)

Research date: 2026-11-03. Prices in USD unless noted. "Measured" = read directly from a vendor/App Store page on this date; "claim" = vendor marketing statement; "unknown" = could not be verified from a primary source during this run (the shared web-search budget was exhausted, so everything below comes from direct fetches of primary pages; items that returned 403/404 are marked unknown rather than guessed).

## 1) Executive summary

1. AI is not the cost problem. With Claude Haiku 5.5 ($0.10 in / $0.50 out, cache read $0.01 per MTok) a fully understood page costs about **$0.0004**; with Sonnet 5.5 about **$0.0076**. A heavy 1,000-page/month user costs $0.39 (Haiku) to $7.55 (Sonnet) in model fees; embeddings and storage add under $0.25.
2. A Haiku-first pipeline with Sonnet escalation on ~10% of pages (~$0.0011/page) keeps AI + storage under 10% of net revenue even at a $29.99/yr price point; a Sonnet-everything pipeline at 1,000 pages/month would lose money on any consumer price.
3. Consumer scanner apps are already priced: Adobe Scan $9.99/mo or $69.99/yr, CamScanner $9.99/mo or $59.99/yr, Genius Scan Ultra $39.99/yr, Scanner Pro Plus IAPs from $3.99 to $59.99. RevenueCat's 2026 median yearly price across all subscription apps is $34.80. A $39.99-$59.99/yr managed tier is squarely in-market.
4. Apple's Small Business Program takes 15% (not 30%) below $1M proceeds; standard subscriptions drop to 15% after year one anyway; Family Sharing supports up to 5 members.
5. B2B is where price/page is 10-100x higher: Dext charges $25.21/mo for 250 documents and 5 users ($0.10/doc); Shoeboxed $9-$179/mo for 50-5,000 scans ($0.036-$0.18/scan); Dext line-item extraction is $0.50/doc.
6. The market is growing: Sensor Tower measured $167B global in-app spend in 2025 with non-game IAP up 21% and surpassing games; a DMS market estimate is $8.32B (2025) to $29.78B (2034), 15% CAGR. No credible scanner-app-specific TAM figure was reachable; treat that as unknown.
7. Biggest risks: Apple shipping "scan-and-understand" natively (Notes scanning plus the free ~3B-parameter on-device Foundation Models framework already exist), 10x/year model-price deflation that erodes any "we do AI" premium, and AI-app churn (RevenueCat: AI apps earn 41% more per payer but churn 30% faster).
8. Recommended model: free BYO-key tier (founder already ships Keychain-stored keys) + managed subscription at ~$49.99/yr or $5.99/mo with a fair-use page cap + family plan via Apple Family Sharing + a later per-seat B2B tier for bookkeepers/property managers.
9. Roadmap for a solo senior iOS dev with AI assistance: v0 personal tool 4-6 weeks, v1 TestFlight +6-8 weeks, v2 App Store paid +6-10 weeks, v3 backend/service +3-4 months; roughly 9-12 months to a multi-tenant service.
10. Position in the Business category (where Adobe Scan, Scanner Pro and Genius Scan live and where paid scanner apps still chart), keyword around "PDF scanner / scan documents / OCR / receipts", and differentiate on "zero taps, archived forever, searchable by meaning".

## 2) Findings

### 2a. Competitor pricing (measured on App Store / vendor pages, 2026-11-03)

| Product | Model | Price (measured) | Notes / source |
|---|---|---|---|
| Adobe Scan | Freemium sub | Premium $9.99/mo; $69.99 (yearly IAP); Plus $4.99/mo, $19.99/yr | Free tier already includes OCR and AI perspective/glare fixes. 1.6M ratings, 4.9 avg, iOS 18+. https://apps.apple.com/us/app/adobe-scan-pdf-scanner-ocr/id1199564834 , https://www.adobe.com/acrobat/mobile/scanner-app.html |
| Scanner Pro (Readdle) | Freemium sub ("Scanner Pro Plus") | IAP price points $3.99, $6.99, $7.99, $19.99, $29.99, $59.99 (periods not labelled on listing) | 338K ratings, 4.9 avg, iOS 18+; OCR text layer, iCloud backup, on-device translation needs iOS 26. https://apps.apple.com/us/app/scanner-pro-ocr-scanning-fax/id333710667 , https://readdle.com/scannerpro |
| Genius Scan | Free + Ultra sub | Basic free (unlimited scans); Ultra $39.99/yr; Plus IAP $11.99 (historically one-time); Teams $40 down to $20/license/yr | 1.4M ratings, 4.9 avg, iOS 17+. https://thegrizzlylabs.com/genius-scan/pricing/ , https://apps.apple.com/us/app/genius-scan-pdf-scanner/id377672876 |
| CamScanner | Freemium sub | $9.99/mo, $59.99/yr, $9.99/week IAP, $49.99/$69.99 variants | ~2M ratings, 4.8 avg, iOS 15+, Productivity category. https://apps.apple.com/us/app/camscanner-pdf-scanner-app/id388627783 |
| SwiftScan | Sub (7-day trial promo) | unknown (pricing page 404; marketing site shows only a trial link) | https://swiftscan.app/ |
| TurboScan Pro, JotNot Pro, Fast Scanner, Genius Scan Enterprise | Paid up-front | prices not shown on chart page | Ranked #4, #15, #18, #12 on the US iPhone Business *paid* chart on 2026-11-03: paid-upfront scanners still sell. https://apps.apple.com/us/iphone/charts/6000?chart=top-paid |
| Paperless-ngx | OSS (GPL-3.0), self-hosted | Free; 47.6k GitHub stars; no official hosted offering | Hosted by third parties: Elestio "from $16/mo"; PikaPods base from $1.80/mo (Paperless availability on PikaPods not confirmed from the page fetched). Mobile client "Paperless Mobile" (Flutter, ~1.5k stars, Android shipped, iOS not on App Store). https://github.com/paperless-ngx/paperless-ngx , https://elest.io/open-source/paperless-ngx , https://www.pikapods.com/ , https://github.com/astubenbord/paperless-mobile |
| Dext (bookkeeping capture) | B2B SaaS | Business: $25.21/mo or $302.50/yr, 250 docs/mo, 5 users; Partner (firms): per-client/month, 10-client minimum, 13% annual discount, base rate not shown; add-ons $7-$7.50/client/mo; line-item extraction from $0.50/doc; bank statement extraction from $0.32/doc | https://dext.com/ , https://dext.com/us/business/pricing , https://dext.com/us/partner/pricing |
| Shoeboxed | B2B/prosumer SaaS | Starter $9/mo (50 digital scans), Pro $29 (250), Plus $79 (1,000), Paper Plus $179 (5,000); annual $97/$297/$797/$1,997 | Includes "Magic Envelope" mail-in scanning. https://www.shoeboxed.com/pricing/ |
| Expensify | Per-seat SaaS | Free for individuals; companies "from $5 per member" (period not stated on page; pricing page itself could not be fetched) | https://www.expensify.com/ |
| ScanSnap iX1600 (hardware) | One-time | unknown (Ricoh/PFU and retailer pages returned 403/404/500) | Treat as the hardware benchmark the founder's app must beat on speed. |

Implied price per document in B2B: Dext $0.10/doc at plan cap, Shoeboxed $0.036-$0.18/scan, Dext extraction add-ons $0.32-$0.50/doc. Consumer apps are flat-rate.

### 2b. Consumer willingness to pay (RevenueCat State of Subscription Apps 2026, measured from the report page)

- Median yearly price rose from $31.60 to $34.80; most common yearly price $30. Monthly median $8-$10 (page is internally inconsistent); weekly median $5.99.
- 17.3% of newly launched apps reach $1K/month within two years; 4.6% reach $10K. Business category: 14.7% reach $1K. Median time to $1K: 58 days.
- Trial-to-paid medians: North America 34.2%; trials of 17-32 days convert at 42.5% vs 25.5% for 4 days or less.
- Productivity: realized LTV per payer ~$24.95/yr; revenue is dominated by monthly plans.
- AI-powered apps generate 41% more revenue per payer but churn 30% faster.
- 2025 edition: annual-plan first-year retention median 44.1%; high-priced apps' year-1 LTV per payer $55.21 vs $8.08 for low-priced.
Sources: https://www.revenuecat.com/state-of-subscription-apps-2026/ , https://www.revenuecat.com/state-of-subscription-apps-2025/

### 2c. Unit economics

**Model prices (measured, Anthropic pricing page, 2026-11-03)** — https://platform.claude.com/docs/en/about-claude/pricing

| Model | Input | Cache write (5m) | Cache read | Output | Batch (50% off) |
|---|---|---|---|---|---|
| Haiku 5.5 (prompt ≤100K) | $0.10 | $0.125 | $0.01 | $0.50 | $0.05 / $0.25 |
| Sonnet 5.5 | $2.00 | $2.50 | $0.10 | $10.00 | $1.00 / $5.00 |
| Opus 5.5 | $4.00 | $5.00 | $0.20 | $20.00 | $2.00 / $10.00 |

Haiku 5.5 released 2026-10-07; Anthropic claims ~75% lower cost to run than Haiku 4.5 and "fastest model to date"; customer claims include Box at ~half the latency of Haiku 4.5 (claims, not measured). https://www.anthropic.com/news/claude-haiku-5-5 . Sonnet 5.5 released 2026-09-28 at the same $2/$10 as Sonnet 5 with cache reads halved to $0.10. https://www.anthropic.com/news/claude-sonnet-5-5

**Image tokens (measured)**: Claude bills ⌈w/28⌉×⌈h/28⌉ visual tokens. Claude 4.7+ models are "high-resolution tier": max long edge 2,576 px and up to 4,784 tokens per image; a 1,920×1,080 image costs 2,691 tokens, 2,000×1,500 costs 3,888. If the app pre-resizes to ≤1,568 px long edge the cost is ~1,560 tokens (matches the founder's 1,600 assumption). Max 10 MB per image, 600 images per request on the API. https://platform.claude.com/docs/en/build-with-claude/vision

**Per-page assumptions**: 1,600 image tokens (pre-resized) + 100 uncached text tokens + 1,500-token system prompt served from cache + 400 output tokens. Cache writes (1,500 tokens once per 5-minute burst: $0.0002 Haiku, $0.0038 Sonnet) are omitted as negligible per page.

| Pipeline | $/page (std-res 1,600 tok) | $/page if sent at full hi-res (4,784 tok) | $/page via Batch API |
|---|---|---|---|
| Haiku 5.5 | $0.000385 | $0.000703 | $0.000193 |
| Sonnet 5.5 | $0.00755 | $0.0139 | $0.00378 |
| Opus 5.5 | $0.0151 | $0.0278 | $0.00755 |
| Hybrid: Haiku on all pages, Sonnet re-run on 10% (low-confidence / complex) | $0.00110 | — | — |

Per-page comparables: AWS Textract DetectDocumentText $0.0015/page, Forms $0.05/page (measured, us-west-2) — Haiku 5.5 vision is ~4x cheaper than plain cloud OCR and returns structure, classification and summary in the same call. https://aws.amazon.com/textract/pricing/ . Apple on-device Vision OCR is $0 (founder already uses it).

**Embeddings (measured)**: Voyage voyage-3.5 $0.06/MTok, voyage-3.5-lite $0.02/MTok, voyage-3-large $0.18/MTok, voyage-multimodal-3.5 $0.12/MTok text + $0.60 per billion pixels. At ~800 text tokens per page: $0.00005/page (3.5) or $0.00002 (lite); multimodal on a 1,568×1,200 page ≈ $0.0012/page. https://docs.voyageai.com/docs/pricing

**Storage/bandwidth (measured)**: Cloudflare R2 $0.015/GB-month, Class A $4.50/M, Class B $0.36/M, egress free, 10 GB free. Backblaze B2 $6.95/TB-month, egress free up to 3x stored. https://developers.cloudflare.com/r2/pricing/ , https://www.backblaze.com/cloud-storage/pricing . Assumption: 1 MB stored per page (archival PDF with text layer plus thumbnails). If the user's own Drive/iCloud/Synology is the system of record, this line is ~$0 for the service.

**Monthly cost per user (AI + embeddings + storage; storage shown at year-1 average cumulative volume on R2)**

| Pages/mo | Haiku-only | Hybrid 90/10 | Sonnet-only | Embeddings (voyage-3.5) | Storage R2 (yr-1 avg / end of yr-1) | Total Haiku | Total hybrid | Total Sonnet |
|---|---|---|---|---|---|---|---|---|
| 50 | $0.019 | $0.055 | $0.38 | $0.002 | $0.005 / $0.009 | ~$0.03 | ~$0.06 | ~$0.39 |
| 200 | $0.077 | $0.22 | $1.51 | $0.010 | $0.019 / $0.035 | ~$0.11 | ~$0.25 | ~$1.54 |
| 1,000 | $0.385 | $1.10 | $7.55 | $0.048 | $0.095 / $0.176 | ~$0.53 | ~$1.25 | ~$7.70 |

Add a fixed platform overhead (auth, database, monitoring, support tooling) of roughly $0.05-$0.20/user/month at a few thousand users (estimate, not measured). Bandwidth is negligible: a resized page JPEG is ~300 KB; R2/B2 egress is free.

**Margin check at Small Business Program rates (15%)**:
- $49.99/yr managed tier → $42.49 net → $3.54/mo. Hybrid pipeline at 200 pages = $0.25 (7% COGS). Sonnet-only at 1,000 pages = $7.70 (loss).
- $5.99/mo → $5.09 net. Hybrid at 1,000 pages = $1.25 (25% COGS); Haiku-only $0.53 (10%).
- Conclusion: a fair-use cap (e.g. 500 pages/mo on the base tier, overage or "Pro" tier above) plus Haiku-first routing keeps gross margin above 85%.

**Price deflation evidence (measured, same pricing page)**: Haiku 4.5 (Oct 2025) $1/$5 → Haiku 5.5 (Oct 2026) $0.10/$0.50 = 10x in 12 months; Sonnet 4.5 $3/$15 → Sonnet 5.5 $2/$10; Opus 4.1 $15/$75 → Opus 5.5 $4/$20. Plan pricing on value, not on model cost.

### 2d. Monetization mechanics on Apple (measured)

- Small Business Program: 15% commission on paid apps and IAP for developers with ≤$1M proceeds in the prior and current calendar year; requires enrolment and listing of associated accounts; the page also mentions a further reduced 10% for subscriptions after their first year (wording ties it to EU alternative terms; verify in App Store Connect). https://developer.apple.com/app-store/small-business-program/
- Standard auto-renewable subscriptions: developer keeps 70% in year one, 85% after one year of paid service; SBP members get 85% from day one. Family Sharing: up to 5 family members, enabled per subscription and cannot be undone. 800 price points (+100 on request). Intro offers: free trial, pay-as-you-go, pay-up-front; one intro offer per subscription group. https://developer.apple.com/app-store/subscriptions/
- StoreKit 2: signed JWS transactions, SubscriptionStoreView, App Store Server API parity, in-app refund/manage flows; Apple's 2026-09-16 notice "Get your subscriptions ready for iOS 27" says to use StoreKit 2 and introduces Bundles, Suites and multiseat purchasing (relevant for family and team SKUs). StoreKit 2 minimum iOS 15 is from memory, not verified. https://developer.apple.com/storekit/ , https://developer.apple.com/news/?id=likeohx4
- US anti-steering: App Review Guidelines updated 2025-05-01 to comply with the US court decision on buttons and external links (3.1.1, 3.1.3) — a web-checkout path for the managed tier is legally possible in the US. https://developer.apple.com/news/?id=9txfddzf
- EU: single business terms with a 5% Core Technology Commission effective 2026-10-01. https://developer.apple.com/news/?id=gmws0jgp
- Mini Apps Partner Program (2025-11-13): 15% commission for apps adopting Declared Age Range and Advanced Commerce APIs — not applicable at launch but shows Apple's direction toward more 15% paths. https://developer.apple.com/news/?id=xcz1s7cz

### 2e. App Store positioning and ASO (measured, US iPhone charts 2026-11-03)

- Category: Adobe Scan, Scanner Pro and Genius Scan are in **Business**; CamScanner is in **Productivity**. The Business paid chart has five scanner-type apps in its top 25 (TurboScan Pro #4, ScanBizCards #8, Genius Scan Enterprise #12, JotNot Pro #15, Fast Scanner #18); the Business free chart has "Scanner App - Scan PDF & Docs" at #24. The Productivity free chart is dominated by AI assistants (Muse, ChatGPT, Claude, Gemini, Copilot, Grok in the top 9) and Google/Microsoft office apps; Google Drive's subtitle literally says "Store, access and scan files". The Utilities chart has no scanner apps in its top 25. Sources: https://apps.apple.com/us/charts/iphone/business-apps/6000 , https://apps.apple.com/us/iphone/charts/6000?chart=top-paid , https://apps.apple.com/us/charts/iphone/productivity-apps/6007 , https://apps.apple.com/us/charts/iphone/utilities-apps/6002
- Title/subtitle keywords used by incumbents (from their listings): "PDF scanner", "Scan documents", "OCR", "receipts", "fax", "document scanner". Expect to compete on "scanner" long-tail; the new angle to own is "auto scan", "mail", "paperless", "archive", "searchable", "AI document".
- Ratings scale of incumbents: Adobe Scan 1.6M, CamScanner ~2M, Genius Scan 1.4M, Scanner Pro 338K ratings. A new entrant cannot win on generic "scanner" keywords in year one; the wedge is a different job-to-be-done ("digitize my mail with zero taps and never lose it").
- Minimum iOS: incumbents are at iOS 15-18; shipping iOS 26+ (for Foundation Models, Vision RecognizeDocumentsRequest and Readdle-style on-device translation) is in line with where the category is moving.

### 2f. Market size and trends

- Sensor Tower State of Mobile 2026 (measured): $167B global IAP revenue in 2025 (+10.6% YoY); US ~$60B; non-game IAP +21% YoY and surpassed games for the first time; generative-AI app IAP revenue nearly tripled to >$5B; GenAI downloads doubled to 3.8B. https://sensortower.com/blog/state-of-mobile-2026
- Document management systems: $8.32B (2025) → $9.74B (2026) → $29.78B (2034), 15.0% CAGR (Fortune Business Insights estimate; analyst figure, not measured market data). https://www.fortunebusinessinsights.com/document-management-system-market-106615
- Scanner-app-specific TAM: unknown (Grand View, Mordor, Statista, MarketsandMarkets pages were blocked or empty during this run).
- Adjacent opportunities, each a natural upsell for the same corpus: email/PDF ingestion (bills and statements already arrive as PDFs; Gmail/IMAP connectors), bill-pay reminders (due dates extracted at capture time), tax-prep export (a "2025 tax pack" zip/PDF bundle with an index page to send to an accountant — directly requested by the founder), expense reports (Scanner Pro sells an "Expense Report" IAP at $4.99; Expensify/Dext show per-seat demand), and a bookkeeper portal (Dext's partner model: per-client/month with a 10-client minimum).

### 2g. Risks

- **Platform risk**: iPhone Notes/Files already scan documents with auto-capture; Apple's on-device Foundation Models framework (~3B parameters, free, iOS 26+) is explicitly aimed at summarization and entity extraction; iOS 27 adds server-side "AFM 3 Cloud" models in Shortcuts. Apple could ship "scan, summarize, file to iCloud" natively at any WWDC. Mitigations: multi-destination storage (Google Drive, Synology, iCloud at once), archival guarantees, cross-year semantic search, export packs, and speed — none of which Apple tends to ship. Sources: https://machinelearning.apple.com/research/apple-foundation-models-2025-updates , https://www.apple.com/ios/ , https://support.apple.com/guide/iphone/scan-text-and-documents-iph653f28965/ios
- **Model-cost deflation**: 10x drop in Haiku pricing in one year (above). Good for margins, bad for any "AI premium" pricing; competitors get the same drop. Price on outcome (never lose a document, find anything) rather than on AI.
- **Privacy expectations**: mail includes tax, medical and legal documents. Expect to need: on-device OCR first, clear data-flow disclosure (App Privacy labels), a BYO-key mode where the developer never sees content, and, for the managed tier, Anthropic's zero-data-retention terms where available (note: the pricing page states Claude Fable 5.1 requires 30-day retention; Haiku/Sonnet terms should be checked in the Console). Paperless-ngx's own README warns data is stored unencrypted — a self-hosted crowd that cares.
- **Churn**: AI apps churn 30% faster (RevenueCat). Mail arrives weekly, which is a natural retention hook; the archive is the lock-in.
- **Commission drift**: rates are moving (China 15%→12%, EU 5% CTC, US external links allowed); model the business at 15% and treat anything lower as upside.

### 2h. Phased roadmap (solo senior iOS developer with AI coding assistance; estimates, not measured)

| Phase | Scope | Effort | Monetization |
|---|---|---|---|
| v0 personal tool | Continuous camera with sharpness/stability gate and auto-capture; on-device Vision OCR; perceptual-hash + text-hash dedup ("already scanned"); Haiku 5.5 call for class/entities/tags/summary; PDF with text layer; write to iCloud Drive/Files; SQLite FTS5 search; local durable queue (write-ahead, never delete source until upload confirmed) | 4-6 weeks | None (founder's own key) |
| v1 TestFlight | Google Drive and Synology (WebDAV/SMB) destinations with multi-target fan-out; retry/outbox UI; search UI; export (print, share, zip bundles); crash/metrics; 20-50 testers; measure p50/p95 capture-to-"captured" latency | +6-8 weeks | None; collect willingness-to-pay via survey |
| v2 App Store paid | StoreKit 2 subscriptions (SBP enrolment), free BYO-key tier, managed tier with page cap, Family Sharing, onboarding, paywall with 14-30 day trial, App Privacy labels, ASO assets, support inbox | +6-10 weeks | $49.99/yr or $5.99/mo managed; BYO-key free |
| v3 service/backend | API proxy with per-user metering and key custody, accounts, server-side embeddings (Voyage) and semantic search, web viewer, email ingestion, tax-pack export, B2B seats (bookkeepers, property managers, immigration lawyers), Android or web capture later | +3-4 months | B2B per-seat/per-client; family plan; overage packs |

Rough total: 9-12 months to a multi-tenant service, assuming ~30 productive hours/week. The dominant engineering risk is not AI but the capture loop (sub-second auto-capture plus dedup) and the durability pipeline; budget half of v0/v1 time there.

## 3) Options compared

| Monetization option | Pros | Cons | Fit for this project |
|---|---|---|---|
| One-time purchase ($9.99-$29.99) | Simple; paid scanner apps still chart in Business; no churn | No recurring revenue to cover managed AI/storage; cannot fund backend | Only for a BYO-key "Pro unlock" of local features |
| Subscription via StoreKit 2 (SBP 15%) | Matches category norms ($39.99-$69.99/yr); funds managed AI; Family Sharing | Churn; need trial funnel; App Store review | Primary model for the managed tier |
| BYO-key free tier + managed tier | Zero COGS on free users; privacy story; founder already has the Keychain pattern | Most consumers will not get an API key; support burden for key errors | Keep as free tier; it is also the "prosumer/privacy" wedge |
| Family plan | 5 members via Apple Family Sharing at no extra integration | Lower ARPU per person | Enable on the yearly SKU; price the yearly tier assuming sharing |
| B2B niche seats (bookkeepers, property managers, immigration lawyers) | 10-100x higher $/doc (Dext $0.10/doc plan, $0.50/doc add-ons); low churn | Needs backend, SSO, audit trail, retention policies | v3; start with 3-5 design-partner firms |
| Usage-based (per page) | Tracks cost exactly | Consumers dislike meters; unnecessary at $0.001/page | Use only as overage packs above fair-use cap |

| AI pipeline option | $/page | Latency | Notes |
|---|---|---|---|
| On-device Vision OCR only | $0 | fastest | No classification/summary; keep as first pass and offline fallback |
| Haiku 5.5 vision on every page | $0.0004 | low (vendor: fastest model) | Default |
| Haiku + Sonnet escalation (10%) | $0.0011 | low; escalation async | Recommended |
| Sonnet 5.5 on every page | $0.0076 | medium | Loses money for 1,000-page users at consumer prices |
| Batch API nightly re-index | 50% off | hours | Use for re-processing the archive when models improve |
| Cloud OCR (Textract) | $0.0015-$0.05 | medium | Dominated by Haiku on cost and output richness |

## 4) Recommendation for this project

1. Price the managed tier at **$49.99/yr (or $5.99/mo)** with a 14-day trial, Family Sharing on, and a fair-use cap around 500 pages/month; add a **$99/yr "Pro"** tier (unlimited pages, email ingestion, tax packs) once v3 exists. These sit between Genius Scan Ultra ($39.99) and Adobe Scan ($69.99) and above RevenueCat's $34.80 median, justified by the archive and search, not by "AI".
2. Keep the **BYO Anthropic key tier free** and local-first (on-device OCR, user-owned storage). It is the privacy story, it costs nothing, and it is the natural v0/v1.
3. Build the pipeline **Haiku 5.5 first, Sonnet 5.5 on escalation**, with images pre-resized to ≤1,568 px long edge (keeps ~1,560 tokens/page; sending native high-res triples cost to 4,784 tokens). Use prompt caching for the system prompt and Batch API for archive re-indexing.
4. Make **user-owned storage the system of record** (Drive/iCloud/Synology) so service storage cost stays near zero and the durability promise is backed by the user's own accounts; the managed backend holds only index/embeddings.
5. Enrol in the **Small Business Program** before the first sale; model everything at 15%.
6. Ship in the **Business** category with a subtitle built from "auto scanner, mail, archive, searchable PDF"; do not try to out-rank incumbents on "PDF scanner" in year one.
7. Treat **bookkeeping firms and property managers** as the v3 revenue engine (Dext's per-client/month with a 10-client minimum is the template), using the same capture app with a shared workspace.

## 5) Risks and unknowns

- SwiftScan pricing, ScanSnap list price, Google Document AI pricing and a scanner-app-specific market size could not be verified (403/404/empty pages; search budget exhausted). None changes the recommendation.
- Scanner Pro IAP durations are not labelled on the App Store page; the $59.99 point may be lifetime or yearly.
- The Small Business Program page's 10% sentence is ambiguous (EU alternative terms vs all subscriptions after year one); confirm in App Store Connect.
- StoreKit 2 minimum iOS (15) and VNDocumentCameraViewController auto-capture behaviour are from memory; Apple doc pages fetched empty.
- Dext partner base price per client is not rendered on the page; only the 10-client minimum, 13% annual discount and $7-$7.50 add-ons are visible.
- Latency numbers for Haiku 5.5 are vendor/customer claims, not measured; the "sub-second" target must be measured in v0 on real hardware.
- Haiku 5.5 pricing doubles above 100K-token prompts; per-page requests stay far below that, but batched multi-page requests must not cross it.
- Fable 5.1 requires 30-day data retention; check retention/ZDR terms for Haiku/Sonnet if the privacy marketing promises zero retention.
- Apple WWDC 2027 could add native "scan and understand"; the market-size figures quoted are analyst estimates.

## 6) Open questions for the founder

1. Is the managed tier allowed to see document content (proxying through the developer's key), or must the product remain BYO-key/on-device for anything sensitive? This decides whether v3 is a metering proxy or a full backend.
2. Which storage is the system of record when several are selected, and what happens if one destination is unreachable for days (how long does the phone hold the outbox)?
3. Target page volume for the founder personally and for the first 100 users (sets the fair-use cap)?
4. Appetite for B2B (bookkeepers/property managers/immigration lawyers) in year one, or consumer-only until v3?
5. Launch geography: US-only (external payment links allowed) or EU too (5% CTC, GDPR data-flow documentation)?
6. Is Android/web capture ever in scope, or is iOS-only acceptable for the service phase?
7. Family plan: should one subscription cover a household's shared archive (shared Drive folder) or separate archives?

## 7) Sources

- Anthropic pricing: https://platform.claude.com/docs/en/about-claude/pricing
- Anthropic vision tokens/limits: https://platform.claude.com/docs/en/build-with-claude/vision
- Claude Haiku 5.5 announcement: https://www.anthropic.com/news/claude-haiku-5-5
- Claude Sonnet 5.5 announcement: https://www.anthropic.com/news/claude-sonnet-5-5
- Voyage AI embeddings pricing: https://docs.voyageai.com/docs/pricing
- Cloudflare R2 pricing: https://developers.cloudflare.com/r2/pricing/
- Backblaze B2 pricing: https://www.backblaze.com/cloud-storage/pricing
- AWS Textract pricing: https://aws.amazon.com/textract/pricing/
- Apple Small Business Program: https://developer.apple.com/app-store/small-business-program/
- Apple auto-renewable subscriptions: https://developer.apple.com/app-store/subscriptions/
- Apple StoreKit overview: https://developer.apple.com/storekit/
- Apple developer news (US guidelines 2025-05-01, EU CTC 2026-08-18, iOS 27 subscriptions 2026-09-16, Mini Apps 2025-11-13): https://developer.apple.com/news/ , https://developer.apple.com/news/?id=9txfddzf , https://developer.apple.com/news/?id=gmws0jgp , https://developer.apple.com/news/?id=likeohx4 , https://developer.apple.com/news/?id=xcz1s7cz
- Apple Foundation Models 2025 updates: https://machinelearning.apple.com/research/apple-foundation-models-2025-updates
- Apple iOS 26 newsroom: https://www.apple.com/newsroom/2025/06/apple-elevates-the-iphone-experience-with-ios-26/
- Apple iOS (iOS 27 page): https://www.apple.com/ios/
- iPhone User Guide, Notes scanning: https://support.apple.com/guide/iphone/scan-text-and-documents-iph653f28965/ios
- Adobe Scan (App Store): https://apps.apple.com/us/app/adobe-scan-pdf-scanner-ocr/id1199564834 ; product page: https://www.adobe.com/acrobat/mobile/scanner-app.html
- Scanner Pro (App Store): https://apps.apple.com/us/app/scanner-pro-ocr-scanning-fax/id333710667 ; product page: https://readdle.com/scannerpro
- Genius Scan pricing: https://thegrizzlylabs.com/genius-scan/pricing/ ; App Store: https://apps.apple.com/us/app/genius-scan-pdf-scanner/id377672876
- CamScanner (App Store): https://apps.apple.com/us/app/camscanner-pdf-scanner-app/id388627783
- SwiftScan site: https://swiftscan.app/
- Paperless-ngx: https://github.com/paperless-ngx/paperless-ngx ; Paperless Mobile: https://github.com/astubenbord/paperless-mobile ; Elestio hosting: https://elest.io/open-source/paperless-ngx ; PikaPods: https://www.pikapods.com/
- Dext: https://dext.com/ , https://dext.com/us/business/pricing , https://dext.com/us/partner/pricing
- Shoeboxed pricing: https://www.shoeboxed.com/pricing/
- Expensify: https://www.expensify.com/ , https://help.expensify.com/articles/new-expensify/billing-and-subscriptions/Plan-types-and-pricing
- App Store charts: https://apps.apple.com/us/charts/iphone/business-apps/6000 , https://apps.apple.com/us/iphone/charts/6000?chart=top-paid , https://apps.apple.com/us/charts/iphone/productivity-apps/6007 , https://apps.apple.com/us/charts/iphone/utilities-apps/6002
- RevenueCat State of Subscription Apps 2026 and 2025: https://www.revenuecat.com/state-of-subscription-apps-2026/ , https://www.revenuecat.com/state-of-subscription-apps-2025/
- Sensor Tower State of Mobile 2026: https://sensortower.com/blog/state-of-mobile-2026
- Fortune Business Insights DMS market: https://www.fortunebusinessinsights.com/document-management-system-market-106615
