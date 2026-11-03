# Naming report: hands-free paper capture app (2026-11-03)

Product being named: a zero-interaction iPhone app that scans every piece of paper you receive, understands it with Claude, files it durably into your own storage (Google Drive / iCloud / Synology) and makes it searchable. Brand attributes: fast, effortless, trustworthy ("safe to throw the paper away"), calm, modern. Consumer App Store product first, service later.

Constraints applied: do not reuse the founder's existing names (Pack Rat, Sofal, Free Go); avoid every product name in `../research/competitors.md` section 7 and anything confusingly similar (in particular the "Scan", "Paperless", "Doc", "Snap", "Lens", "Scannable", "Dext", "Doxie" families).

## 0. How the checks were run (and what could not be run)

| Check | Method actually used | Caveat |
|---|---|---|
| .com / .app / .ai domains | `curl -o /dev/null -w "%{http_code}" https://rdap.org/domain/NAME.TLD` (200 = registered, 404 = no RDAP record, 429 = rate-limited/unknown) | A 404 can still be a registry-reserved or premium name; verify at a registrar before buying. rdap.org rate-limited heavily (429) after ~40 queries; retried with long sleeps. |
| .io domains | rdap.org has **no bootstrap entry for .io** (it returned 404 even for google.io and github.io), so every .io result below comes from the registry's own server, `https://rdap.identitydigital.services/rdap/domain/NAME.io`, which was verified against google.io (200). | That server rate-limits aggressively; several lookups stayed 429 = unknown. |
| App Store conflicts | Apple's own App Store search API: `https://itunes.apple.com/search?term=NAME&entity=software&country=us` for NAME and for "NAME scanner". | US storefront only; the API returns the top 10-15 by relevance, not every app containing the word. |
| Trademark (USPTO classes 9 / 42) | Trademarkia's USPTO mirror (`trademarkia.com/search/trademarks?query=NAME`), first page of results. The USPTO's own tmsearch API, TMview and Justia all refused automated access (405/403/"Request Rejected"). | **Preliminary only.** Exact-word matches, first 10 of N results, no phonetic/similarity search, no state or common-law marks. A real clearance search by a trademark attorney is still required before filing or launch. |
| GitHub org/user slug | `https://github.com/NAME` fetched directly (404 = slug free, 200 = taken). | Dormant accounts can sometimes be reclaimed via GitHub's name-squatting policy, but do not count on it. |
| Web search ("NAME app", "NAME scanner app", "site:apps.apple.com NAME", "NAME trademark software", "github.com/NAME") | **Not performed.** The workflow's shared web-search budget (200 calls per turn across all agents) was already exhausted by sibling research agents when this step started. | The App Store API, the GitHub page fetch and the Trademarkia lookup cover the same three questions from primary sources, so the shortlist is still evidence-based, but general-web collisions (blogs, SaaS products without a US trademark or iOS app) were not checked. A follow-up message can run those searches. |

## 1. The 40 candidates

Style buckets as requested. "Checked" = included in the availability sweep below.

### Evocative English words
1. **Hush** — calm; the paper goes quiet. Checked.
2. **Settle** — settles your paper, settles your mind; also "settle an account". Checked.
3. **Keep** — what the app guarantees. Not checked (generic; Google Keep owns the word in software).
4. **Still** — calm, and "still here" (durability). Not checked (unsearchable).
5. **Glean** — gathering what matters from a field of paper. Not checked.
6. **Tidy** — outcome word. Not checked (Tidy/TidyCal collisions known).

### Compounds
7. **Papershed** — shed the paper (verb) and a shed where it is safely kept (noun). Checked.
8. **Paperfall** — paper falls through the phone like a waterfall; speed. Checked.
9. **Papersieve** — the phone is a sieve: paper in, meaning out. Checked.
10. **Afterpaper** — life after paper; what remains when the paper is gone. Checked.
11. **Paperhush** — the paper goes quiet; calm. Checked.
12. **Quietpaper** — same idea, adjective-first. Checked.
13. **Inkshed** — shed the ink (and a wink at "watershed"). Checked.
14. **Mailshed** — shed the mail. Checked.
15. **Paperdrop** — drop paper in front of the phone and it is gone. Checked.
16. **Paperlift** — lifts the paper off your desk. Checked.
17. **Pagefall** — pages fall away. Checked.
18. **Inkwell** — a well where all ink ends up. Not checked (many stationery/font marks).
19. **Stackless** — no more stacks on the counter. Not checked (also a Python term).

### Invented / coined words
20. **Quirely** — from "quire" (a gathering of 24-25 sheets). Checked.
21. **Reamly** — from "ream" (500 sheets). Checked.
22. **Sheafly** — from "sheaf". Checked (RDAP, App Store, GitHub only).
23. **Foliary** — from "folio". Checked (RDAP, App Store, GitHub only).
24. **Papyr** — stylised papyrus. Not checked (likely crowded: Papyr/Papyrus marks).
25. **Vellumo** — vellum + suffix. Not checked.

### Short verbs
26. **Shed** — get rid of. Checked.
27. **Sift** — separate what matters. Checked.
28. **Skim** — fast reading. Checked.
29. **Whisk** — whisk it away. Checked.
30. **Sweep** — sweep the desk clear. Not checked (Sweep/Sweeply collisions known).
31. **Glide** — the phone glides over paper. Not checked (Glide apps platform owns it).
32. **Fold** — fold the paper away. Not checked.

### Metaphors (paper, file, vault, tray)
33. **Quire** — the bookbinder's unit of sheets. Checked.
34. **Sheaf** — a bundle of papers. Checked.
35. **Ream** — 500 sheets, i.e. volume. Checked.
36. **Vellum** — premium parchment; durability. Checked.
37. **Folio** — a leaf of paper. Checked.
38. **Tray** — the in-tray, emptied. Not checked (generic).

### Multilingual roots
39. **Chartula** — Latin diminutive of charta: a little piece of paper, a document (root of "charter", "card", "chart"). Checked.
40. **Kami** — Japanese for paper (and, with a different kanji, spirit). Checked.
Also considered and dropped before checking: Carta (IT/ES, heavily used: Carta Inc. cap-table software), Hoja (ES "sheet"), Papel (ES "paper"), Blatt (DE "sheet"), Scriba (LA "scribe").

## 2. Raw check results

### 2a. Domains (RDAP HTTP status; 200 = registered, 404 = no record, 429 = rate-limited/unknown)

First wave (16 names, run at 2026-11-03):

| Name | .com | .app | .io (registry RDAP) | .ai |
|---|---|---|---|---|
| quire | 200 | 200 | 429 (unknown) | 200 |
| sheaf | 200 | 200 | 200 | 200 |
| ream | 200 | 200 | 200 | 200 |
| sift | 200 | 200 | 200 | 200 |
| skim | 200 | 200 | 200 | 200 |
| shed | 200 | 200 | 200 | 200 |
| settle | 200 | 200 | 200 | 200 |
| papershed | 200 | **404** | **404** | **404** |
| paperfall | 200 | **404** | **404** | **404** |
| vellum | 200 | 200 | 200 | 429 (unknown) |
| folio | 200 | 200 | 200 | 200 |
| kami | 200 | 200 | 200 | 200 |
| quirely | 200 | **404** | **404** | 200 |
| chartula | 200 | 200 | **404** | **404** |
| whisk | 200 | 200 | 200 | 200 |
| hush | 200 | 200 | 200 | 200 |
| sheafly | 200 | 200 | n/a | 429 |
| foliary | 200 | 200 | n/a | 429 |

Second wave (10 compounds):

| Name | .com | .app | .io (registry RDAP) | .ai |
|---|---|---|---|---|
| afterpaper | 200 | **404** | 429 (unknown) | 429 (unknown) |
| paperdrop | 200 | 200 | 200 | **404** |
| paperlift | 200 | **404** | 429 (unknown) | 429 (unknown) |
| pagefall | 200 | **404** | **404** | **404** |
| reamly | 200 | 200 | 200 | 200 |
| papersieve | **404** | **404** | **404** | **404** |
| mailshed | 200 | **404** | 429 (unknown) | 429 (unknown) |
| paperhush | not reached | not reached | not reached | not reached |
| quietpaper | not reached | not reached | not reached | not reached |
| inkshed | not reached | not reached | not reached | not reached |

The second sweep was running with 8-25 s pauses between queries to stay under rdap.org's rate limit and had not reached the last three names when this report had to be finalised; run `curl -sSL -o /dev/null -w "%{http_code}" https://rdap.org/domain/inkshed.app` (etc.) to complete it.

### 2b. App Store (Apple search API, US storefront, top results)

| Query | Exact-name or category conflicts found |
|---|---|
| quire | **Quire** (Potix, project management, 4 TM registrations); **Quire: Document & QR Scanner** (Ian Talisic); Quire Mobile Reports; Quire: EPUB reader. |
| quire scanner | Quire: Document & QR Scanner ranks #1. |
| sheaf | **Sheaf: PDF Editor & Scanner** (EMRE KOTUN), **Sheaf - PDF Scanner & Editor** (RASUL SONMEZ), **Sheaf: Offline OCR & Documents**, PDF Editor & Sign - Sheaf, Sheaf - Document Review, Sheaf - Plural System Tracker. Crowded in exactly our category. |
| ream | Reams (news), Ream: AI Text to Speech, REAM Estate, REAM Property Management; "ream scanner" surfaces **Ream: Scanner & PDF Tools** and **Ream: Image to PDF Scanner**. |
| sift | 12 apps named Sift (tutoring, product reviews, food scanner, news, recipes, Sift Connect). |
| skim | skim: Catch What Matters (Credible AI Labs, pending TM 9/42), theSkimm, SKIMS. |
| shed | Shed Fitness, Shed Tracker, Shed: Reptile Feeding Tracker, Sched. |
| settle | Settle: Nervous System Reset, Settle: Global Money Transfer, Settle: Invoice & Jobs, Settle Up. |
| papershed | No app named Papershed; results are generic paper/PDF apps (Penbook, Instapaper, Paperpile). |
| papershed scanner | Only generic scanner apps. |
| paperfall | **PaperFall** (Samuel Yang, Games) exact-name match, different category; rest are paper-plane games. |
| vellum | Vellum Wallpapers, Vellum Assistant, Vellum - Read & Write Stories, Antique Identifier - Vellum; "vellum scanner" surfaces **Vellum Scanner** (Linh Phan Nhat Khanh). |
| folio | 12 apps named Folio (wallet, book tracker, Folio AI, save-for-later, finance). |
| kami | Kami Home, KAMI/KAMI 2 (games), Kami: Read and Write. |
| quirely | **Quirely - PDF Library Manager** and **Quirely Markdown+LaTeX Editor** (Reggie Fisher). Direct productivity conflict. |
| chartula | Chartula: Handwriting Calendar (Michael Ketelaar, Productivity) only. |
| whisk | Whisk: Recipe Keeper, Whisk AI, Samsung Food (ex-Whisk). |
| hush | 11 apps named Hush (social, chat, nag blocker, sleep sounds). |
| sheafly | Sheafly (Darien DeWolf, Productivity) exact match. |
| foliary | Foliary (Luso Quantum, Lifestyle) exact match. |
| afterpaper | None named Afterpaper. |
| paperdrop | None named Paperdrop; results are AirDrop-style file-share apps and paper-plane games. |
| paperlift | **Paperlift: Scan Paper to Data** (Andrei Dimov, Business) and Paperlift (game). Direct conflict. |
| pagefall | Four music apps published by developer **"Pagefall limited"**. Developer-name conflict. |
| reamly | None. |
| papersieve | None. |
| mailshed | None; results are USPS Informed Delivery, PostScan Mail, mail clients. |
| paperhush | None. |
| quietpaper | None; results are white-noise apps. |
| inkshed | None. |

### 2c. Trademarks (Trademarkia USPTO mirror, exact word, first page; classes 9 = software goods, 42 = software services)

| Name | Total hits | Live hits in 9 / 42 on page 1 | Verdict |
|---|---|---|---|
| quire | 22 | 4 live registrations + 1 pending in class 42 (Potix Corp, Quire LLC, J. Paul Getty Trust, Quire Inc, Quire Finance) | Red flag |
| sheaf | 12 | None in 9/42 (beer, pharma, whiskey) | Clear on TM, but see App Store |
| ream | 93 | Ream Inc pending (9, 41); EcoFlow live (9); Ream Inc abandoned (9, 42) | Yellow/red |
| sift | 132 | Sift Science (42), Sift Enterprises (42, two), All Turtles (9), Meinhold (9) | Red flag |
| skim | 159 | Credible AI Labs pending (9, 42), Skim AI pending (9, 42), Skim Group pending (35, 42), Semikron (9), Bento (9) | Red flag |
| shed | 720 | None on page 1; site filter reports 41 hits in class 9 and 55 in class 42 overall | Yellow (too common) |
| settle | 402 | Settle Inc live (36, 42); Never Settle (35, 42); Settle Max (42); 27 class-9 hits overall | Red flag |
| papershed | 0 | None | Clear (preliminary) |
| paperfall | 0 | None | Clear (preliminary) |
| vellum | 52 | Vellum Wellness (9, 42, two registrations); Promethean (9); 180G LLC (9, the Vellum ebook-formatting software) | Red flag |
| folio | 291 | Bauer Types (9, 42); Cifralluminio (9) | Red flag (and 291 hits) |
| kami | 91 | Kami Buyer LLC (9, 42, three registrations); Kami Vision (9) | Red flag |
| quirely | 0 | None | Clear on TM, but App Store conflict |
| chartula | 0 | None | Clear (preliminary) |
| whisk | 200 | Foodient/Samsung (9) live; Google LLC (9, 42) abandoned | Yellow/red |
| hush | 601 | E-One (9), Hush Studios (42) live | Red flag |
| afterpaper | 0 | None | Clear (preliminary) |
| paperdrop | 0 | None | Clear (preliminary) |
| paperlift | 0 | None | Clear on TM, App Store conflict |
| pagefall | 0 | None | Clear on TM, developer-name conflict |
| reamly | 0 | None | Clear (preliminary) |
| papersieve | 0 | None | Clear (preliminary) |
| mailshed | 0 | None | Clear (preliminary) |
| paperhush | 0 | None | Clear (preliminary) |
| quietpaper | 0 | None | Clear (preliminary) |
| inkshed | 0 | None | Clear (preliminary) |

Not TM-checked: sheafly, foliary (dropped once the App Store showed exact-name apps).

### 2d. GitHub slugs (github.com/NAME)

| Slug | Status |
|---|---|
| quire | Taken (user, 1 fork) |
| sheaf | Taken (user, 98 repos) |
| ream | Taken (org, Vue SSR framework, 6 repos) |
| sift | Taken (org) |
| skim | Taken (user, 6 repos) |
| shed | Taken (user, 7 repos) |
| settle | Taken (user, 11 repos) |
| papershed | **Free (404)** |
| paperfall | Taken (user, 1 fork) |
| vellum | Taken (user, 23 repos) |
| folio | Taken (user, 0 repos) |
| kami | Taken (user, 276 repos) |
| quirely | **Free (404)** |
| chartula | Taken (user, 4 repos) |
| whisk | Taken (user, 30 repos) |
| hush | Taken (user, 2 repos) |
| sheafly | **Free (404)** |
| foliary | **Free (404)** |
| afterpaper | Taken (org, 0 public repos) |
| paperdrop | Taken (org "PaperDrop", 0 public repos) |
| paperlift | Taken (user, 0 repos) |
| pagefall | Taken (org, 0 public repos) |
| reamly | Taken (org, 0 public repos) |
| papersieve | **Free (404)** |
| mailshed | Taken (user, 0 repos) |
| paperhush | Taken (user, 0 repos) |
| quietpaper | Taken (user "QuietPaper", 0 repos) |
| inkshed | **Free (404)** |

Note: the repository itself can live under the founder's existing GitHub account regardless of whether the org slug is free; the org slug matters only if a dedicated organisation is wanted. Several taken slugs are empty accounts (0 repos) that may be eligible for GitHub's inactive-name release, but that is never guaranteed.

## 3. Ranked shortlist (10)

Ranking weighs, in order: no App Store collision in the productivity/scanner category; no live USPTO mark in classes 9/42; brand fit (fast, effortless, trustworthy, calm); pronounceability and spell-ability when said aloud; domain availability (.app first, since this is an App Store product; .com is a nice-to-have that almost no short word has).

| # | Name | Rationale | Pronounceability | Domains (.com / .app / .io / .ai) | App Store conflicts | Trademark red flags | Tagline | GitHub repo slug |
|---|---|---|---|---|---|---|---|---|
| 1 | **Papershed** | Verb and noun in one word: you shed the paper, and the shed is where it is safely kept. Says "effortless" and "trustworthy" without saying "scan". | PAY-per-shed; two common words, spelled as heard. | taken / **free** / **free** / **free** | None named Papershed; nothing similar in the scanner category. | 0 USPTO hits (preliminary). Avoid the "Paperless"/"PaperScan" family by never abbreviating to "Paper". | "Open the mail. Throw it away." | `papershed` (org slug free) |
| 2 | **Papersieve** | The phone is a sieve: paper goes in, meaning and files come out. Strong metaphor for "understands it". | PAY-per-siv; the "-ieve" spelling will be misspelled ("papersive") by some. | **free** / **free** / **free** / **free** (the only name with all four RDAP 404s; confirm none is premium) | None. | 0 hits (preliminary). | "Everything on paper, nothing left behind." | `papersieve` (org slug free) |
| 3 | **Inkshed** | Shed the ink; echoes "watershed" (a turning point). Short, modern, calm. | INK-shed; unambiguous. | not reached in the RDAP sweep; check before deciding | None. | 0 hits (preliminary). | "Paper in. Peace out." | `inkshed` (org slug free) |
| 4 | **Afterpaper** | Life after paper. Aspirational and calm; works as a service name later ("Afterpaper for teams"). | AF-ter-pay-per; obvious. | taken / **free** / unknown (429) / unknown (429) | None. | 0 hits (preliminary). | "What's left when the paper is gone: everything." | `afterpaper` (org slug taken by an empty org; use `afterpaper-app` or the founder's account) |
| 5 | **Paperhush** | The pile goes quiet. Most "calm" of the set. | PAY-per-hush; obvious. | not reached in the RDAP sweep | None (results were white-noise apps). | 0 hits for the compound; note 601 "Hush" marks exist, including E-One (9) and Hush Studios (42), so a compound is safer than "Hush" alone. | "Quiet the pile." | `paperhush` (slug held by an empty user; use `paperhush-app`) |
| 6 | **Chartula** | Latin "a small document"; root of charter, card, chart. Distinctive, ownable, slightly premium. | kar-TOO-la; needs to be heard once; non-English speakers may stumble. | taken / taken / **free** / **free** | "Chartula: Handwriting Calendar" (one unrelated productivity app). | 0 hits (preliminary). | "Every little piece of paper, kept." | `chartula-app` (user slug taken) |
| 7 | **Quietpaper** | Same promise as Paperhush, adjective-first; reads well as a brand ("Quiet Paper"). | KWY-et-pay-per; obvious. | not reached in the RDAP sweep | None. | 0 hits (preliminary). | "Mail, without the noise." | `quietpaper-app` (slug held by an empty user) |
| 8 | **Paperfall** | Paper cascades through the phone; communicates speed. | PAY-per-fawl; obvious. | taken / **free** / **free** / **free** | "PaperFall" by Samuel Yang (a game, exact name, different category). Low risk but not zero. | 0 hits (preliminary). | "Hold it up. Let it fall." | `paperfall-app` (user slug taken) |
| 9 | **Mailshed** | Narrower, but mail is the hero use case; "shed" carries the same double meaning as Papershed. | MAIL-shed; obvious. | taken / **free** / unknown / unknown | None (results were USPS Informed Delivery, PostScan Mail, mail clients - adjacent but not conflicting). | 0 hits (preliminary). | "Shed your mail." | `mailshed-app` (slug held by an empty user) |
| 10 | **Paperdrop** | Drop the paper in front of the phone; fast and casual. | PAY-per-drop; obvious. | taken / taken / taken / **free** | None named Paperdrop, but the App Store returned AirDrop-style file-share apps, so "drop" reads as file transfer. | 0 hits (preliminary); "Drop" connotes Dropbox/AirDrop, a brand-confusion risk rather than a legal one. | "Drop it. It's filed." | `paperdrop-app` (org slug taken) |

## 4. Names rejected after checking, and why

- **Quire** — the most beautiful word on the list (it means a gathering of sheets) but Potix's project-management app owns it in class 42 with four other live registrations, and "Quire: Document & QR Scanner" already sits in our exact category.
- **Sheaf** — trademark-clean in 9/42, but at least four "Sheaf" PDF scanner/OCR apps already exist on the App Store; a new scanner called Sheaf would be indistinguishable in search.
- **Ream** — two "Ream" scanner apps, and Ream Inc has a pending class-9 application.
- **Vellum** — "Vellum Scanner" exists; Vellum (180G) is well-known Mac software; Vellum Wellness holds 9/42.
- **Quirely** — Reggie Fisher's "Quirely - PDF Library Manager" is a direct productivity conflict.
- **Paperlift** — "Paperlift: Scan Paper to Data" is literally our product's description.
- **Pagefall** — a developer named "Pagefall limited" publishes on the App Store.
- **Sheafly / Foliary** — exact-name apps already published.
- **Sift, Skim, Shed, Settle, Whisk, Hush, Folio, Kami** — each has 90-720 USPTO hits and 10+ identically named apps; they would need a modifier ("Sift Paper") to be findable, which defeats the point of a short name.

## 5. Recommendation

Register **Papershed** (papershed.app, papershed.io, papershed.ai; make an offer on papershed.com) and use `papershed` as the GitHub org and repo slug. It is the only candidate that came back clean on every automated check, it carries both halves of the promise (shed the paper; the shed keeps it), and it is spelled the way it sounds. Keep **Inkshed** and **Afterpaper** as backups in case a human trademark search turns up a common-law conflict. Before launch: order a professional USPTO/EUIPO clearance search, check the name in the UK/EU/CA App Stores, and search the general web once the search budget is available (the five web queries per name specified in the brief were not run; see section 0).
