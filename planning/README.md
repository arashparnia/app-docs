# Planning: the zero-interaction paper digitizer

Status: research complete, plan of record drafted, nothing implemented. Date: 2026-11-03. Product name: to be chosen (see `05-names.md`); the project gets its own GitHub repository once it has a name, and this folder moves there.

## Read in this order

1. `01-executive-summary.md` — the answer in five minutes: what to build, the ten defining decisions, the numbers, what I need from you.
2. `02-architecture.md` — the plan of record: capture state machine, duplicate detection, page grouping, the Claude design, durability states, PDF output, storage connectors, search, the sensitive-data policy, and where it overrules the raw research.
3. `04-roadmap.md` — phases with exit criteria, the Phase 0 measurement harness, risks.
4. `06-decisions-and-needs.md` — ten decisions with recommended defaults, what you need to provide, open questions.
5. `05-names.md` — ten names with domain, App Store and trademark checks and a recommendation.
6. `03-research-findings.md` — condensed findings per research dimension with the fact-check corrections applied.

## Artifacts

- `schemas/document-record.schema.json` — the Claude structured-output schema for one page (draft v0).
- `schemas/search-query.schema.json` — the natural-language-query filter schema.
- `schemas/taxonomy.json` — 33-class US personal-mail taxonomy with key fields, actions, retention and sensitivity flags.
- `tools/haiku_hot_path_bench.py` — Phase 0 harness that measures Claude Haiku 5.5 latency, tokens, cost, refusals and accuracy on your own pages (not yet executed against the API; needs your key).
- `research/` — the 14 dimension reports and 10 gap-round reports, raw agent output. `research/CORRECTIONS.md` lists the ten refuted claims with their corrections and the claims that could not be confirmed.
- `design/` — the three independent architecture proposals (speed-first, local-first-privacy, service-scale) and the naming report, raw.

## How the research was produced

Seventy agents over about four hours on 2026-11-03: 14 research dimensions run in parallel, each fact-checked by an adversarial agent that tried to refute its key claims and critiqued by a second agent for gaps and errors; a completeness critic that produced 10 gap questions, each researched and fact-checked; three independent architecture proposals scored by two judges with different lenses (the founder's; a skeptical systems reviewer's); and a naming round with an adversarial re-check. Both judges picked the speed-first proposal as the backbone and listed the grafts from the other two that `02-architecture.md` applies.

Limits: the shared web-search budget was exhausted after the first five dimensions, so the later reports were built from directly fetched primary sources (Apple documentation and WWDC transcripts, vendor documentation, pricing pages, papers, GitHub). That is stronger evidence than search snippets, but a few sources could not be fetched (Synology's JavaScript-rendered knowledge base, some pricing pages) and are marked unknown. Every latency number is tagged measured, vendor claim, or estimate; Apple publishes no latency for any Vision request, so Phase 0 exists to replace every estimate with measurements on an iPhone 13 before any number is promised.
