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

## Why (NL2SQL plugins exist — what's missing is the semantic layer)

| | raw NL2SQL plugins | **dsh-WrenAI** |
|---|---|---|
| Model sees | table schemas | **semantic catalog** — metrics with calibers, dimensions with business meaning |
| Trust | hope | **calibers ride with results**: every result cites the metric definitions it used |
| SQL safety | varies | **single-SELECT guard** + self-heal retry, deterministic execution |
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
single SELECT ── deterministic guard (one statement, SELECT-only)
        │           └─ executor error → self-heal retry with the error fed back
        ▼
numbers + calibers together  (a result without its definitions is a bug)
```

Execution is pluggable: SQLite (default, stdlib) or PostgreSQL via
`--pg "postgresql://…"` / `--weknora`. `scripts/pgwire.py` is a
**zero-dependency** PostgreSQL wire-protocol client (SCRAM-SHA-256 with
server-signature verification, MD5, cleartext, optional TLS) — clean-room from
the public protocol docs, so the whole kit stays stdlib-only Python plus a
Node shim.

## Status & roadmap

v0.1 — semantic engine, PG backend, WeKnora bridge; hermetic tests + CI green.
[ROADMAP](ROADMAP.md): M1 metric versioning + caliber drift alarms; M2
MDL-style model compatibility + DuckDB backend.

## License & disclaimer

MIT; concept credit to WrenAI (multi-licensed upstream, core Apache-2.0) —
zero upstream code used. **Not investment advice.**
