# ROADMAP — dsh-WrenAI

North star: the family's semantic-layer seat, riding WrenAI's 18.3k★ gravity.
Naming on all surfaces: GitHub = dsh-WrenAI (mirror CamelCase) / npm = dsh-wrenai.
Positioning (research-verified): DSH has raw NL2SQL seats, **nobody ships a
self-hosted semantic layer** — this repo takes that gap, and "calibers ride with
results" is the product soul.

## Milestones

### M0 ✅ (2026-11-17)
Semantic model (dimensions/measures/metrics + calibers in YAML) + SQLite semantic
view (metric windows precomputed) + ask engine (LLM sees the catalog, emits a
single SELECT; guard + self-heal retry; calibers ride with the result).
Live smoke: BTC 365d ask (30d avg close / annualized vol + caliber formulas),
one SQL syntax error self-healed on error feedback.

### M0.5 · Release packaging — partially done
- [x] README polish + npm 0.0.1 placeholder (owner-published)
- [ ] ask screenshots (with the calibers section) + marketplace + channels

### W1 · PostgreSQL backend + WeKnora ops bridge (in flight, 2026-11-18)
WrenAI connects directly to WeKnora's PostgreSQL: ops ask natural-language
questions about WeKnora's own operational data ("how many times was the test KB
queried in the past week?"). WeKnora lacks self-observability; WrenAI lacked a
real data source — each solves the other's pain.
- [x] W1.1 EN-first conversion with `--lang zh` fallback (family rule)
- [x] W1.2 PostgreSQL execution backend — pluggable executor behind the same
      single-SELECT guard; zero-dependency pure-stdlib PG wire client
      (SCRAM-SHA-256 auth, server signature verified); `--pg "postgresql://…"` DSN
- [x] W1.3 `--weknora` preset semantic model — zero-config (reads
      `~/WeKnora/.env`), governed model over `audit_logs` / `knowledge_bases` /
      `knowledges` / `chunks` / `sessions` / `messages`, honest calibers included
      ("KB queried" = retrieval-cited assistant messages via chunk refs, because
      `audit_logs` records write-side actions only; kb_query_events vs
      kb_citations are two calibers). Live smoke hit hand-verified ground truth
      (test KB: 2 events / 30d; hotpot-pool-500: 1287 events / 34948 citations / 90d)
- [x] W1.4 npm 0.1.0 release train — root package (bin `dsh-wrenai`, DSH bundle
      manifest + skill, files whitelist), hermetic test suite + CI, submission
      kit staged in `docs/marketplace-submission/` (fires after owner publishes
      npm 0.1.0 — 2FA). awesome-dsh-plugin PR follows the #16227 precedent.

### W2 · Model lifecycle — deterministic closure (2026-11-20)
A compiler ships its own parser: model construction and drift accounting are
catalog computation, so they live in the engine (zero LLM). Meaning stays human.
- [x] W2.1 `--bootstrap` — catalog → skeleton YAML (#15): public base tables,
      blacklist internals (`schema_migrations`, `task_*`, …); cols with compact
      types; keys from catalog PKs; joins from **declared FKs only** (survey:
      21 FKs all in newer subsystems, core chain declares none — skeleton says
      so); hard disclosure *no calibers ride*; `load_yaml` round-trip. Works
      with any `--pg` DSN, not just WeKnora. Live dev: 86 tables / 1174 cols /
      20 FK joins.
- [x] W2.2 `--check` — column-granular drift (#15): **drift = model claims
      broken** (dropped table/column, type change) → exit 1 (CI-able); new
      catalog columns / unmodeled tables are info, so curated partial models
      stay green while their claims hold. First live run caught the preset's
      `messages.tenant_id` claim gone upstream (tenant scope rides
      `sessions.tenant_id`) — repaired in the same PR.
- [x] W2.3 model-scope guard (#16) — with a tables model, SQL table references
      must be a subset of it: best-effort FROM/JOIN extraction (comma lists,
      aliases, schema-qualified and quoted names; set-returning functions and
      subquery parens skipped), violation raises into the self-heal retry then
      fails honestly. Two defense layers in the live smoke: catalog-discipline
      (LLM refused an unmodeled table and returned an empty honest result) and
      the deterministic guard (hermetic proof it fires on hallucinated names).
      Governs the promise: unmodeled tables cannot ship numbers without calibers.

### M1 · Governance depth (week 2-3)
- [ ] joins / multi-table models + metric versioning + caliber drift alarms
      (same question across versions, side by side)
- [ ] result cache and a query audit log (what was asked, which caliber version)

### M2 · Compatibility & multi-DB (week 4-6)
- [ ] MDL-style model file compatibility layer (WrenAI ecosystem models import directly)
- [ ] DuckDB execution backend + typed tools for the harness plugin surface

## Discipline
- Calibers ride with results — never numbers alone; single-SELECT guard is
  non-negotiable; metric definition changes are version bumps, not edits-in-place.
