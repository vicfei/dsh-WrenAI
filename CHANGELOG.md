# Changelog

## 0.2.0 (2026-11-26)

Everything since 0.1.1 (launch-window fixes): the model lifecycle, caliber
accountability, and the M2 surface — WrenAI-ecosystem model files, a DuckDB
backend, typed tools.

### Model lifecycle (W2)

- `--bootstrap` — the live PostgreSQL catalog → a skeleton semantic model
  (public base tables, internals blacklisted; compact types; keys from catalog
  PKs; joins from declared FKs only) with the hard disclosure *no calibers
  ride*. Works with any `--pg` DSN.
- `--check` — column-granular drift against the live catalog. Drift = the
  model's claims are broken (dropped table/column, type change) → exit 1,
  CI-able; new columns and unmodeled tables are info, so curated partial
  models stay green. First live run caught the preset's own `messages.tenant_id`
  claim gone upstream.
- Model-scope guard — with a tables model, SQL table references must stay
  inside it: numbers from unmodeled tables would ship without calibers.
  Violations raise into the self-heal retry, then fail honestly.

### Caliber accountability (W3)

- Metric/measures `version:` (missing = 1; every existing model stays valid).
- `--calibers NEW --against OLD` (zero LLM): a caliber text that changed
  without its version moving is **DRIFT, exit 1** — the forbidden
  edit-in-place, caught mechanically; a bump is a recorded supersession.
- `--ledger` — every ask appends one ndjson event beside the model: question,
  final SQL, verdict `ok`/`self_healed`/`failed` (rejections record too), the
  metric versions the answer rode on, result rows (first 50, honest counts).
  `--ledger-print N` reads.
- `--replay <id>` — re-executes a recorded SQL through the same guards on the
  current model/backend and reports moved cells and moved caliber versions:
  the same question across model versions, side by side.

### WrenAI-ecosystem models (M2.1)

- `--mdl file.mdl.json` imports a WrenAI MDL manifest in place: models →
  tables (types dropped — name-only drift), relationships → joins, metric
  formulas as calibers with the no-prose disclosure, calculated columns as
  catalog entries, views skipped. Scope guard, `--check`, `--calibers`,
  `--ledger`, `--replay` all work on an import. JSON only (the UI export
  format).

### DuckDB backend (M2.2)

- `--duckdb [PATH|:memory:]` — module-then-CLI-then-honest-exit; one backend
  per run; DuckDB's exceptions fold into the engine's error class so the
  self-heal retry fires; the ledger records the backend.

### Typed tools (M2.3)

- `lib/index.js` registers `wren_ask`, `wren_check`, `wren_calibers`,
  `wren_ledger` (JSON-schema parameters; backend exclusivity enforced
  tool-side; the engine's non-zero exits are surfaced, not swallowed).
  `dsh plugin add dsh-wrenai` now carries both the bin and the typed tools.

## 0.1.1 (2026-11-20)

Star backflow hook in the footer; intranet LLM endpoints
(`WREN_LLM_BASE_URL` / `WREN_LLM_MODEL` / `WREN_LLM_API_KEY`); guard
rejections self-heal too (CTE/WITH → nested subqueries).

## 0.1.0 (2026-11-19)

The release train: PG backend via the stdlib wire client (SCRAM-SHA-256
verified), `--weknora` zero-config bridge with the honest-caliber preset,
hermetic tests + CI, submission kit.

## 0.0.1 (2026-11-17)

Name reservation.
