---
name: dsh-wrenai
description: Self-hosted semantic layer — natural-language data questions with metric calibers riding on every result; single-SELECT guard, self-heal SQL, SQLite/PostgreSQL backends, and a zero-config --weknora bridge (ask your WeKnora deployment anything).
---

Use this skill for governed "ask the data" over any dataset with a semantic
model. Calibers are the contract: numbers never travel without their
definitions. The `dsh-wrenai` CLI must be on PATH (installed with the package;
requires python3, stdlib only).

## Run

```bash
dsh-wrenai --init <klines.json>                        # SQLite demo: load data + views
dsh-wrenai --ask "average close and volatility over the last 30 days?"
dsh-wrenai --ask "<问题>" --lang zh                     # Chinese fallback
# WeKnora ops: zero-config bridge to a WeKnora deployment's own PostgreSQL
dsh-wrenai --weknora --ask "how many times was the test knowledge base queried in the past month?"
# any PostgreSQL: --pg "postgresql://user:pass@host:5432/db" --model <yaml>
# caliber accountability: versioned definitions, recorded asks
dsh-wrenai --model new.yaml --calibers --against old.yaml   # exit 1 on an unversioned caliber edit
dsh-wrenai --weknora --ask "<question>" --ledger            # record the ask beside the model
dsh-wrenai --weknora --replay wl_<id>                       # re-run a recorded SQL, then vs now
```

Semantic models live in the kit's `semantic/` directory (`models.yaml` demo,
`weknora.yaml` preset); copy and edit for your dataset. LLM key: the engine
reads `DEEPSEEK_API_KEY` from ~/.bashrc export lines.

## Discipline

- Always quote the calibers section with results — never numbers alone.
- Single-SELECT guard is non-negotiable; report self-heal events honestly.
- Metric definition changes are version bumps, not edits-in-place — gate model
  changes with `--calibers --against old.yaml`; record production asks with
  `--ledger` and `--replay` them after any caliber bump.
