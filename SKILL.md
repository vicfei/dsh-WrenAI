---
name: dsh-wrenai
description: Self-hosted semantic layer for DeepSeek Harness — natural-language data questions over a governed model (dimensions/measures/metrics with calibers); single-SELECT guard, self-heal SQL, calibers ride with every result.
---

Use this skill for "问数" over any dataset with a semantic model. Calibers are
the contract: numbers never travel without their definitions.

## Run

```bash
KIT=<this-directory>
python3 $KIT/scripts/ask.py --init <klines.json>
python3 $KIT/scripts/ask.py --ask "<question>"            # English-first output
python3 $KIT/scripts/ask.py --ask "<question>" --lang zh  # Chinese fallback
```

Semantic model lives in `semantic/models.yaml` (edit for your dataset; the view
SQL builds from it). Data: family klines JSON or any tabular load you wire in.

## Discipline

- Always quote the 口径 section with results — never numbers alone.
- Single-SELECT guard is non-negotiable; report self-heal events honestly.
- Metric definition changes are version bumps, not edits-in-place.
