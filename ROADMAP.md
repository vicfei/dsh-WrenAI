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
- [ ] W1.2 PostgreSQL execution backend — pluggable executor behind the same
      single-SELECT guard; zero-dependency pure-stdlib PG wire client
      (SCRAM-SHA-256 auth); `--pg "postgresql://…"` DSN
- [ ] W1.3 `--weknora` preset semantic model — zero-config (reads
      `~/WeKnora/.env`), governed model over `audit_logs` / `knowledge_bases` /
      `knowledges` / `sessions` / `messages`, honest calibers included
      (e.g. "KB queried" = retrieval-cited assistant messages, because
      `audit_logs` records write-side actions only)
- [ ] W1.4 npm 0.1.0 release train + awesome-dsh submission
      (hook: "ask your WeKnora anything")

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
