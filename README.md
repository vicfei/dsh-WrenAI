# dsh-WrenAI — a self-hosted semantic layer for DeepSeek Harness

**Ask data questions in natural language; get numbers with their metric
calibers attached. The semantic model (dimensions/measures/metrics + 口径)
rides between the question and the SQL — that's the line between governed
analytics and raw text-to-SQL.**
**自然语言问数，数字带着指标口径一起回来。语义模型（维度/度量/指标+口径）
站在问题与 SQL 之间——这就是受治理的数据问数与裸 text-to-SQL 的分界线。**

[![DeepSeek Harness](https://img.shields.io/badge/DSH-plugin-4E6DD4)](https://github.com/deepseek-ai) [![License: MIT](https://img.shields.io/badge/license-MIT-3da639)](LICENSE) [![WrenAI multi](https://img.shields.io/badge/concept-WrenAI%20%28core%20Apache--2.0%29-35a7a0)](https://github.com/Canner/WrenAI)

> Implements the differentiated core of [WrenAI](https://github.com/Canner/WrenAI)
> (18.3k★ — GenBI / governed text-to-SQL) natively for DSH: the **self-hosted
> semantic layer**. Clean-room, zero upstream code. Not affiliated.
> Family: the 12-repo quant stack — [dsh-TradingAgents](https://github.com/vicfei/dsh-TradingAgents) ·
> [dsh-OpenBB](https://github.com/vicfei/dsh-OpenBB) · [dsh-CCXT](https://github.com/vicfei/dsh-CCXT) ·
> [dsh-quantstats](https://github.com/vicfei/dsh-quantstats) · [dsh-freqtrade](https://github.com/vicfei/dsh-freqtrade) …

## Why (NL2SQL plugins exist — what's missing is the semantic layer)

| | raw NL2SQL plugins | **dsh-WrenAI** |
|---|---|---|
| Model sees | table schemas | **semantic catalog** — metrics with calibers, dimensions with business meaning |
| Trust | hope | **口径随行**: every result cites the metric definitions it used |
| SQL safety | varies | **single-SELECT guard** + self-heal retry, deterministic execution (SQLite stdlib) |
| Self-hosted | — | fully local (semantic/models.yaml + SQLite), no cloud service |

## Quick start

```bash
git clone https://github.com/vicfei/dsh-WrenAI && cd dsh-wrenai
python3 scripts/ask.py --init <klines.json>          # load data + build semantic views
python3 scripts/ask.py --ask "average close and annualized volatility over the last 30 days?"
python3 scripts/ask.py --ask "最近30天的平均收盘价和年化波动率是多少？" --lang zh   # zh fallback
```

Output is English-first (engine, calibers, docs); `--lang zh` switches the
user-facing labels to Chinese.

## Ask your WeKnora anything (`--weknora`)

WeKnora (the self-hosted RAG platform) ships no self-observability: its audit
log records **write-side actions only**, so "how often is this knowledge base
actually used?" is unanswerable from the UI. dsh-WrenAI connects straight to
the deployment's PostgreSQL — zero config, DSN resolved from `~/WeKnora/.env`
(`WREN_PG_DSN` / `WEKNORA_HOME` overrides) — with a preset governed model
over `audit_logs` / `knowledge_bases` / `knowledges` / `chunks` / `sessions` /
`messages`:

```bash
python3 scripts/ask.py --weknora --ask "how many times was the test knowledge base queried in the past month?"
# → kb_query_events = 2   (live dev deployment, 2026-11-19)
```

The caliber that rides with that number states the honest measurement:
retrieval usage = assistant messages whose citations (messages → chunk refs →
`chunks.knowledge_base_id`) include the KB — **not** raw retrieval calls,
because WeKnora doesn't audit those. `kb_query_events` (distinct questions)
and `kb_citations` (citation occurrences, repeats counted) are two different
calibers on the same join path — the semantic layer keeps them distinct.
"Which KBs were cited the most this quarter?" ranks both side by side
(hotpot-pool-500: 1287 events / 34948 citations on the live dev box).

Execution backends: SQLite (stdlib, default) or PostgreSQL via
`--pg "postgresql://…"` / `--weknora` — `scripts/pgwire.py` is a
**zero-dependency** PostgreSQL wire-protocol client (SCRAM-SHA-256 verified,
MD5, cleartext, optional TLS), so the whole kit stays stdlib-only Python.

Real smoke (binance BTC/USDT 365d, 2026-11-17): *avg close 75,870 · vol 36.7%*
— with the vol metric's caliber formula (`sqrt(252×mean(ret²))`, 30d rolling,
non-centered simplification stated) attached to the answer. The first generated
SQL had a syntax error; the engine self-healed on the error feedback.

## Status & roadmap

v0 semantic engine smoke-tested on live data. [ROADMAP](ROADMAP.md): M1 joins +
metric versioning + caliber drift alarms; M2 MDL-style model files + multi-DB.

## License & disclaimer

MIT; concept credit to WrenAI (multi-licensed upstream, core Apache-2.0) —
zero upstream code used. **Not investment advice.**
