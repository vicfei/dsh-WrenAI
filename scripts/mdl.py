#!/usr/bin/env python3
"""MDL compatibility — a WrenAI-ecosystem model file IS a model source (#22).

WrenAI's MDL (Model Definition Language) is the ecosystem's interchange: models
with columns and primary keys, relationships with join conditions, metrics with
formulas. This module imports one into the engine's model shape so every
downstream surface works unchanged: the model-scope guard, --check (MDL models
are physical tables), --calibers, --ledger/--replay, and of course --ask.

Honesty rules that shape the mapping:
- calculated columns (an `expression`) are NOT physical columns — putting them
  in `cols` would make --check flag them as dropped drift. They ride as catalog
  entries carrying the expression, so the generator can inline them.
- column TYPES are dropped (bare names): an MDL's types are loose declarations
  (`varchar`), and the drift check compares compact catalog types — keeping
  them would paint every imported model red on day one. Bare names are the
  hand-written-model convention: --check compares them on name only.
- an MDL metric carries a formula, not a caliber: the imported caliber says so.
- views are skipped with a disclosure (this engine asks tables, not views).

JSON MDL only — the format the WrenAI UI exports. A .yaml MDL is refused with
an honest error (the repo is stdlib-only; a list-based YAML dialect would need
a real parser).
"""
import json
import os
import sys

STR = {
    "en": {
        "not_json": "guard: --mdl takes a WrenAI MDL JSON file (the UI export format); {path} is not JSON: {err}",
        "no_models": "guard: --mdl found no models[] in {path} — not a WrenAI MDL manifest?",
        "disclosure": ("Imported from WrenAI MDL ({path}): metrics carry their MDL formulas as calibers - "
                       "no human caliber prose rides; calculated columns ride as catalog entries with their "
                       "expressions; column types dropped (MDL types are loose, --check compares names); "
                       "MDL views are skipped (this engine asks tables)"),
        "calc_note": "MDL calculated column on {model}: {expr}",
        "metric_note": "MDL metric (type {t}, base {base}): {formula}",
    },
    "zh": {
        "not_json": "护栏：--mdl 接 WrenAI MDL JSON 文件（UI 导出格式）；{path} 不是 JSON：{err}",
        "no_models": "护栏：--mdl 在 {path} 里没找到 models[] —— 这不是 WrenAI MDL 清单？",
        "disclosure": ("自 WrenAI MDL 导入（{path}）：指标以 MDL 公式作口径——不带人工口径叙述；"
                       "计算列以目录条目携表达式随行；MDL views 跳过（本引擎问的是表）"),
        "calc_note": "{model} 上的 MDL 计算列：{expr}",
        "metric_note": "MDL 指标（类型 {t}，基表 {base}）：{formula}",
    },
}

LANG = "en"


def t(key, **kw):
    return STR[LANG].get(key, key).format(**kw)


def _join_condition(rel):
    """'{orders}.customer_id = {customers}.id' -> 'orders.customer_id = customers.id'."""
    return str(rel.get("condition") or "").replace("{", "").replace("}", "")


def load_mdl(path, lang="en"):
    """An MDL JSON file -> the engine's model dict. Raises SystemExit on a file
    that is not an MDL manifest (honest refusal, not a half-model)."""
    global LANG
    LANG = lang
    try:
        mdl = json.load(open(path, encoding="utf-8"))
    except ValueError as e:
        sys.exit(t("not_json", path=path, err=e))
    if not isinstance(mdl.get("models"), list) or not mdl["models"]:
        sys.exit(t("no_models", path=path))
    model = {"dataset": os.path.splitext(os.path.basename(path))[0] + "_mdl",
             "description": t("disclosure", path=os.path.basename(path)),
             "tables": {}, "joins": {}, "dimensions": {}, "measures": {}, "metrics": {}}
    for m in mdl["models"]:
        name = m.get("name")
        if not name:
            continue
        cols = [c["name"] for c in m.get("columns") or [] if c.get("name") and not c.get("expression")]
        model["tables"][name] = {"key": m.get("primaryKeyName") or "id", "cols": ", ".join(cols)}
        for c in m.get("columns") or []:
            if c.get("name") and c.get("expression"):
                model["dimensions"][c["name"]] = {"desc": t("calc_note", model=name, expr=c["expression"])}
    for r in mdl.get("relationships") or []:
        if r.get("name") and r.get("condition"):
            model["joins"][r["name"]] = _join_condition(r)
    for m in mdl.get("metrics") or []:
        if not m.get("name"):
            continue
        model["metrics"][m["name"]] = {
            "caliber": t("metric_note", t=m.get("type") or "?", base=m.get("baseObject") or "?",
                         formula=m.get("formula") or "?")}
    skipped_views = len(mdl.get("views") or [])
    model["_mdl"] = {"path": path, "models": len(model["tables"]), "relationships": len(model["joins"]),
                     "metrics": len(model["metrics"]),
                     "calculated_columns": len(model["dimensions"]), "views_skipped": skipped_views}
    return model


def summary(model):
    i = model.get("_mdl", {})
    return ("mdl -> model: %s model(s) · %s relationship join(s) · %s metric(s) (formulas as calibers, "
            "no prose) · %s calculated column(s) as catalog entries · %s view(s) skipped — dataset %s"
            % (i.get("models", 0), i.get("relationships", 0), i.get("metrics", 0),
               i.get("calculated_columns", 0), i.get("views_skipped", 0), model.get("dataset")))
