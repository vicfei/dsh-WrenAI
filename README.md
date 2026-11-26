# dsh-WrenAI — a self-hosted semantic layer for DeepSeek Harness

**Ask data questions in natural language; get numbers with their metric
calibers attached.** The semantic model (dimensions/measures/metrics +
calibers) rides between the question and the SQL — that is the line between
governed analytics and raw text-to-SQL.

[English](README.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/vicfei/dsh-WrenAI/actions/workflows/ci.yml/badge.svg)](https://github.com/vicfei/dsh-WrenAI/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/dsh-wrenai)](https://www.npmjs.com/package/dsh-wrenai)
[![License: MIT](https://img.shields.io/badge/license-MIT-3da639)](LICENSE)
[![Python](https://img.shields.io/badge/engine-Python%20stdlib%20only%20%2B%20Node%20shim-3776ab)](#install)
[![Concept: WrenAI](https://img.shields.io/badge/concept-WrenAI%20%28core%20Apache--2.0%29-35a7a0)](https://github.com/Canner/WrenAI)

> Implements the differentiated core of [WrenAI](https://github.com/Canner/WrenAI)
> (18.3k★ — GenBI / governed text-to-SQL) natively for
> [DeepSeek Harness](https://github.com/deepseek-ai): the **self-hosted
> semantic layer**. Clean-room, zero upstream code. Not affiliated.
> Family: the 12-repo quant stack — [dsh-TradingAgents](https://github.com/vicfei/dsh-TradingAgents) ·
> [dsh-OpenBB](https://github.com/vicfei/dsh-OpenBB) ·
> [dsh-CCXT](https://github.com/vicfei/dsh-CCXT) ·
> [dsh-quantstats](https://github.com/vicfei/dsh-quantstats) ·
> [dsh-freqtrade](https://github.com/vicfei/dsh-freqtrade) …

## The headline: ask your WeKnora anything

[WeKnora](https://github.com/WeKnora/WeKnora) (self-hosted RAG platform)
ships no self-observability: its audit log records **write-side actions
only**, so "how often is this knowledge base actually used?" is unanswerable
from the UI. dsh-WrenAI connects straight to the deployment's PostgreSQL —
zero config, DSN resolved from `~/WeKnora/.env` — with a preset governed
model and answers with the honest caliber attached:

```bash
dsh-wrenai --weknora --ask "how many times was the test knowledge base queried in the past month?"
```

```text
## Ask: how many times was the test knowledge base queried in the past month?
| kb_query_events |
|-----------------|
| 2               |
## Calibers riding with this result (metric definitions used)
- kb_query_events: DISTINCT COUNT of assistant messages citing at least one
  chunk of the KB in the time window … HONEST LIMIT: WeKnora audit_logs record
  write-side actions only, so retrieval usage is measured by citations
  actually served — this counts questions whose answers cited the KB, not raw
  retrieval calls.
```

(Live dev deployment, 2026-11-19; verified against hand-written SQL.)
`kb_query_events` (distinct questions) and `kb_citations` (citation
occurrences) are two calibers on the same join path — "which KBs were cited
most this quarter?" ranks both side by side (hotpot-pool-500: 1287 events /
34948 citations on the live dev box).

## Model lifecycle: bootstrap a model, then keep it honest

Hand-writing a model over 90 tables is a chore, and models rot silently as the
upstream schema evolves. Both deterministic parts live in the engine — zero
LLM, stdlib only:

```bash
dsh-wrenai --weknora --bootstrap > my-model.yaml      # catalog -> skeleton (stdout)
dsh-wrenai --pg "postgresql://u:p@host:5432/db" --bootstrap > model.yaml   # any PostgreSQL
dsh-wrenai --weknora --model my-model.yaml --check    # model vs live catalog, exit 1 on drift
```

- **`--bootstrap`** reads `information_schema` (public schema, base tables;
  framework internals like `schema_migrations` / `task_*` blacklisted) and
  emits a skeleton: every table's columns with compact types, key from the
  catalog PK, joins from **declared foreign keys only** — no name-convention
  guessing (a wrong join edge is worse than a missing one). The skeleton
  carries the hard disclosure *no calibers ride*: meaning
  (dimensions/measures/metrics) stays human. Output round-trips —
  `--bootstrap > m.yaml` feeds straight back into `--check` and `--ask`.
- **`--check`** drift-accounts a model against the live catalog at column
  granularity. **Drift = the model's claims are broken** — table/column gone,
  column type changed (the `varchar(36)` vs `uuid` class of hazards) — which
  exits 1 and is CI-able. New catalog columns and unmodeled tables are info,
  not drift: a deliberately curated partial model stays green while its claims
  hold. First live run on the dev box caught this repo's own preset claiming
  `messages.tenant_id`, which upstream had removed — the repair rode in the
  same change.

## Bring your WrenAI models: `--mdl` imports MDL files in place

A WrenAI-ecosystem model file is a valid model source — no conversion step:

```bash
dsh-wrenai --pg "postgresql://u:p@host:5432/db" --mdl my-model.mdl.json --ask "..."
dsh-wrenai --pg "postgresql://…" --mdl my-model.mdl.json --check   # and drift-account it
```

`models[]` → tables (key from `primaryKeyName`), `relationships[]` → joins
(`{orders}.x = {customers}.y` conditions with braces stripped), `metrics[]` →
metrics whose caliber is the MDL formula — with the hard disclosure that **no
human caliber prose rides** (an MDL carries formulas, not calibers).
Calculated columns are not physical columns, so they do not land in the cols
line (they would read as drift); they ride as catalog entries carrying their
expression. Column types are dropped on import — MDL types are loose
declarations and the drift check compares catalog types, so keeping them would
paint every import red on day one. Views are skipped with a disclosure. JSON
MDL only: that is the interchange the WrenAI UI exports. Everything downstream
works unchanged — scope guard, `--check`, `--calibers`, `--ledger`, `--replay`.

## Caliber accountability: versioned definitions, recorded asks

The discipline says metric definition changes are version bumps, not
edits-in-place — W3 makes that mechanical, and makes every ask a piece of
append-only evidence:

```bash
dsh-wrenai --model new.yaml --calibers --against old.yaml   # caliber drift alarm (zero LLM)
dsh-wrenai --weknora --ask "..." --ledger                    # record the ask (default: beside the model)
dsh-wrenai --weknora --ledger-print 5                        # the last 5 recorded asks
dsh-wrenai --weknora --replay wl_<id>                        # re-run a recorded SQL now, then vs now
```

- **`--calibers --against`** diffs two models' caliber texts, deterministically.
  A caliber that changed while its `version:` stayed put is **DRIFT — exit 1**
  (an edit-in-place, exactly what the discipline forbids); a change that moved
  the version is a recorded supersession; new/removed metrics are info. A
  missing `version:` reads as 1, so every pre-existing model stays valid.
- **`--ledger`** appends each ask as one ndjson event: the question, the final
  SQL, the verdict (`ok` / `self_healed` / `failed` — rejections record too),
  the metric versions the answer rode on, and the result rows (first 50, count
  always honest). One model, one ledger, beside the model file.
- **`--replay <id>`** re-executes a recorded SQL through the same guards
  against the *current* model and backend, and reports what moved: cells that
  changed, caliber versions that changed. That is the caliber-drift alarm in
  live form — ask once, bump a definition, replay, and see the same question
  answering under a different caliber version.

## Why (NL2SQL plugins exist — what's missing is the semantic layer)

| | raw NL2SQL plugins | **dsh-WrenAI** |
|---|---|---|
| Model sees | table schemas | **semantic catalog** — metrics with calibers, dimensions with business meaning |
| Trust | hope | **calibers ride with results**: every result cites the metric definitions it used |
| SQL safety | varies | **single-SELECT guard + model-scope check** + self-heal retry, deterministic execution |
| Backends | one, usually | **SQLite (stdlib) or PostgreSQL** — via a zero-dependency wire client |
| Self-hosted | — | fully local (YAML models + your DB), no cloud service, no pip installs |

## Install

```bash
npm i -g dsh-wrenai          # or: dsh plugin add dsh-wrenai
dsh-wrenai --weknora --ask "how many times was the test knowledge base queried in the past month?"
```

Requires `python3` on PATH — the engine is **stdlib-only** (no pip installs);
the npm package is a thin launcher plus the DSH plugin manifest and skill.
From source: clone and call `python3 scripts/ask.py` directly.

## Quick start (any dataset)

```bash
git clone https://github.com/vicfei/dsh-WrenAI && cd dsh-wrenai
python3 scripts/ask.py --init <klines.json>          # load data + build semantic views
python3 scripts/ask.py --ask "average close and annualized volatility over the last 30 days?"
```

Real smoke (binance BTC/USDT 365d, 2026-11-17): *avg close 75,870 · vol 36.7%*
— with the vol metric's caliber formula (`sqrt(252×mean(ret²))`, 30d rolling,
non-centered simplification stated) attached to the answer. The first generated
SQL had a syntax error; the engine self-healed on the error feedback.

Output is English-first; `--lang zh` switches the user-facing labels to Chinese.

## How it works

```
semantic model (YAML: dimensions / measures / metrics + calibers)
        │  the LLM sees ONLY this catalog — never raw schemas
        ▼
single SELECT ── deterministic guard (one statement, SELECT-only; with a
        │       tables model, table references must stay inside it — numbers
        │       from unmodeled tables would ship without calibers)
        │           └─ guard/executor error → self-heal retry with the reason fed back
        ▼
numbers + calibers together  (a result without its definitions is a bug)
```

Execution is pluggable: SQLite (default, stdlib) or PostgreSQL via
`--pg "postgresql://…"` / `--weknora`. `scripts/pgwire.py` is a
**zero-dependency** PostgreSQL wire-protocol client (SCRAM-SHA-256 with
server-signature verification, MD5, cleartext, optional TLS) — clean-room from
the public protocol docs, so the whole kit stays stdlib-only Python plus a
Node shim.

## Deploying to an intranet WeKnora (air-gapped friendly)

The kit is stdlib-only Python — copy `scripts/` + `semantic/` to any host
with `python3` (no pip, no npm needed). Point it at your own model service
and your WeKnora database with environment variables:

```bash
export WREN_LLM_BASE_URL="http://<your-deepseek-service>:8000/v1"   # OpenAI-compatible endpoint
export WREN_LLM_MODEL="deepseek-v3"                                 # your served model name
export WREN_LLM_API_KEY="any-placeholder"                           # if the service needs no auth
export WREN_PG_DSN="postgresql://user:pass@<weknora-db-host>:5432/WeKnora"
python3 scripts/ask.py --weknora --ask "how many times was the test KB queried in the past month?"
```

Notes: `--weknora` can also read the deployment's own `.env`
(`WEKNORA_HOME=/path/to/weknora`), mapping the container-internal DB host to
loopback. If your model endpoint is not OpenAI-compatible, adapt the two
`curl` lines in `llm()`. Verify reachability first:
`curl -s <base>/models` and `pg_isready -h <host> -p 5432`.

## Status & roadmap

v0.1 — semantic engine, PG backend, WeKnora bridge, model lifecycle
(`--bootstrap` / `--check`), caliber accountability (versioning + `--calibers`
alarm, `--ledger` / `--replay`); hermetic tests + CI green.
[ROADMAP](ROADMAP.md): M1 result cache; M2 MDL-style model compatibility +
DuckDB backend.

## License & disclaimer

MIT; concept credit to WrenAI (multi-licensed upstream, core Apache-2.0) —
zero upstream code used. **Not investment advice.**
