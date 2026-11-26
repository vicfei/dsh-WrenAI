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
- [x] joins / multi-table models (2026-11-20, W2 #16 + the preset's join paths:
      the scope guard governs any FROM/JOIN over modeled tables, live-smoked on
      the flagship citation join) + **metric versioning + caliber drift alarms**
      (2026-11-26, W3 #19: `version:` on metrics/measures, `--calibers
      --against` exits 1 on an unversioned caliber edit; the live form is
      `--replay`, same question across versions side by side, #20)
- [x] query audit log (2026-11-26, W3 #20: `--ledger` appends every ask —
      verdict, guard rejections, metric versions, result rows; failures record
      too) · result cache: cut without guilt

### M2 · Compatibility & multi-DB (week 4-6) — complete (2026-11-26, #22/#23/#24; 0.2.0)
- [x] MDL-style model file compatibility layer (2026-11-26, #22): `--mdl
      file.mdl.json` imports in place — models->tables (types dropped, name-only
      drift), relationships->joins, metric formulas as calibers with the
      no-prose disclosure, calculated columns as catalog entries, views skipped;
      scope guard / --check / --calibers / --ledger / --replay all work on an
      import. Live-smoked on the dev WeKnora (--check clean, --ask over the
      relationship join, ledger recorded)
- [x] DuckDB execution backend (2026-11-26, #23): `--duckdb [path|:memory:]`,
      module-then-CLI-then-honest-exit; duckdb exceptions fold into the engine's
      error class so self-heal fires; ledger records the backend. Live-smoked
      (30-day table, ask + replay stable).
- [x] typed tools for the harness plugin surface (2026-11-26, #24):
      `lib/index.js` registers wren_ask / wren_check / wren_calibers /
      wren_ledger (JSON-schema parameters, backend exclusivity enforced
      tool-side too, engine spawn with honest exit surfacing); `type: module`
      + ESM bin; files whitelist gains lib; CI gains a hermetic registration
      step. Live-checked: wren_calibers through the tool returns the DRIFT
      verdict with exit 1

## Discipline
- Calibers ride with results — never numbers alone; single-SELECT guard is
  non-negotiable; metric definition changes are version bumps, not edits-in-place.
