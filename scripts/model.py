#!/usr/bin/env python3
"""Model lifecycle — deterministic, zero LLM: bootstrap a skeleton semantic model
from the live catalog, and drift-check a model against it (#15).

A compiler ships its own parser: catalog -> skeleton and model-vs-catalog drift
are pure computation, so they live in the engine, not in a curation service.
Construction/maintenance here, meaning (calibers) stays human — a skeleton is
emitted with the hard disclosure "no calibers ride".

Catalog reads are engine-side single SELECTs against information_schema
(same channel the ask flow uses via pgwire). Emitted YAML stays inside the
inline-map subset ask.load_yaml parses, so `--bootstrap > m.yaml` output feeds
straight back into `--check` and `--ask`.
"""
import fnmatch
import sys

import pgwire

# Framework/extension internals that never belong in a semantic model. A
# blacklist (not a whitelist) on purpose: new domain tables must flow into the
# skeleton automatically — discovery is the point; skeletons carry no calibers,
# so over-inclusion is low-risk and humans trim.
BLACKLIST = ("schema_migrations", "task_*", "spatial_ref_sys", "*_pre_plan3")

LANG = "en"
STR = {
    "en": {
        "skeleton_note": ("SKELETON from catalog - no calibers ride (no metrics/measures/dimensions "
                          "defined); joins are catalog-declared FKs only, app-level joins need human "
                          "curation; trim tables and add calibers before production use"),
        "summary": ("bootstrap -> skeleton: {n_tables} tables · {n_cols} columns · {n_fks} FK joins "
                    "(internals excluded by blacklist: {n_hidden}) - a skeleton ships no calibers; curate before production"),
        "no_pg": "guard: --bootstrap/--check read the PostgreSQL catalog; pass --pg DSN or --weknora",
        "no_tables_model": "guard: --check compares a tables-model against the catalog; this model has "
                           "no tables section (demo view model) - pass --model <yaml> or --weknora",
        "report_head": "## Drift report - model vs live catalog",
        "report_meta": "model: {path} · dataset: {dataset}\nlive: {db}@{host} · tables compared: {n} · columns compared: {c}",
        "drift_n": "drift: {n} finding(s) - model claims broken",
        "f_dropped_table": "[table dropped] {t} - modeled but absent from the live catalog",
        "f_dropped_col": "[column dropped] {c} - in the model, gone from the catalog",
        "f_type_changed": "[type changed] {c}: model {mt} != live {lt}",
        "unmodeled": "unmodeled live tables (info, not drift): {n}",
        "new_cols": "columns new in the catalog on modeled tables (info, not drift): {n}",
        "result_drift": "RESULT: DRIFT - exit 1",
        "result_clean": "RESULT: clean - model claims hold against the live catalog ({n} tables, {c} columns compared)",
        "result_drift": "RESULT: DRIFT - exit 1",
        "result_clean": "RESULT: clean - model claims hold against the live catalog ({n} tables, {c} columns compared)",
        "cal_report_head": "## Caliber diff - new model vs old model",
        "cal_report_meta": "new: {new_path} (dataset {new_ds})\nold: {old_path} (dataset {old_ds})\ncalibers compared: {n}",
        "cal_drift_n": "drift: {n} caliber(s) edited in place - version did not move",
        "cal_info_n": "info (recorded, not drift): {n}",
        "f_cal_edited": "[EDITED IN PLACE] {kind} {name} - caliber text changed, version still v{version} - bump the version, do not edit",
        "f_cal_bumped": "[superseded] {name}: v{old} -> v{new} - {what}",
        "f_cal_text_changed": "caliber text changed",
        "f_cal_text_same": "caliber text unchanged",
        "f_cal_new": "[new] {kind} {name} - no old version to compare",
        "f_cal_removed": "[removed] {name} - in the old model, gone from the new",
        "cal_no_change": "no caliber differences between the two models",
        "cal_result_clean": "RESULT: clean - no caliber moved without a version bump ({n} compared)",
    },
    "zh": {
        "skeleton_note": ("目录生成的骨架 —— 无口径随行（未定义任何 metrics/measures/dimensions）；"
                          "joins 仅含目录声明的 FK，应用层 join 需人工补充；投产前请裁剪表并补写口径"),
        "summary": ("bootstrap -> 骨架：{n_tables} 表 · {n_cols} 列 · {n_fks} 条 FK join"
                    "（黑名单排除内部表：{n_hidden}）—— 骨架不带口径，投产前须人工策展"),
        "no_pg": "护栏：--bootstrap/--check 读取 PostgreSQL 目录；请传 --pg DSN 或 --weknora",
        "no_tables_model": "护栏：--check 对账的是含 tables 段的模型；当前模型没有 tables 段（演示视图模型）——请传 --model <yaml> 或 --weknora",
        "report_head": "## 漂移报告 —— 模型 vs 活目录",
        "report_meta": "模型：{path} · dataset：{dataset}\n活库：{db}@{host} · 对账表：{n} · 对账列：{c}",
        "drift_n": "漂移：{n} 项 —— 模型声明已失效",
        "f_dropped_table": "[表已删] {t} —— 模型里有，活目录已不存在",
        "f_dropped_col": "[列已删] {c} —— 模型里有，活目录已无",
        "f_type_changed": "[类型变更] {c}：模型 {mt} != 活库 {lt}",
        "unmodeled": "活目录中未建模的表（仅提示，不算漂移）：{n}",
        "new_cols": "已建模表上的目录新增列（仅提示，不算漂移）：{n}",
        "result_drift": "结论：有漂移 —— exit 1",
        "result_clean": "结论：干净 —— 模型声明与活目录一致（{n} 表 / {c} 列对账）",
        "result_drift": "结论：有漂移 —— exit 1",
        "result_clean": "结论：干净 —— 模型声明与活目录一致（{n} 表 / {c} 列对账）",
        "cal_report_head": "## 口径对比 —— 新模型 vs 旧模型",
        "cal_report_meta": "新：{new_path}（dataset {new_ds}）\n旧：{old_path}（dataset {old_ds}）\n对比口径数：{n}",
        "cal_drift_n": "漂移：{n} 条口径原地改动 —— 版本号未动",
        "cal_info_n": "提示（留痕，不算漂移）：{n}",
        "f_cal_edited": "[原地改动] {kind} {name} —— 口径文本变了、版本仍是 v{version} —— 请升版本，不要原地改",
        "f_cal_bumped": "[已接替] {name}：v{old} -> v{new} —— {what}",
        "f_cal_text_changed": "口径文本已变",
        "f_cal_text_same": "口径文本未变",
        "f_cal_new": "[新增] {kind} {name} —— 无旧版可对比",
        "f_cal_removed": "[移除] {name} —— 旧模型有、新模型无",
        "cal_no_change": "两个模型之间没有口径差异",
        "cal_result_clean": "结论：干净 —— 没有口径在版本不动的情况下变化（对比 {n} 条）",
    },
}


def t(key, **kw):
    return STR[LANG].get(key, key).format(**kw)


def internal(name):
    """True if the table is framework/extension machinery, not a domain table."""
    return any(fnmatch.fnmatch(name, pat) for pat in BLACKLIST)


def type_name(data_type, char_len, udt):
    """Compact catalog type for cols lines and drift comparison.

    numeric precision is dropped on purpose: the emitted cols value is a single
    comma-separated line, so types must stay comma-free to remain splittable.
    """
    if data_type == "ARRAY":
        return udt.lstrip("_") + "[]" if udt else "array"
    char_len = int(char_len) if char_len else None  # wire text format → str
    if data_type == "character varying":
        return "varchar(%d)" % char_len if char_len else "varchar"
    if data_type == "character":
        return "char(%d)" % char_len if char_len else "char"
    return {"timestamp without time zone": "timestamp", "timestamp with time zone": "timestamptz",
            "time without time zone": "time", "time with time zone": "timetz",
            "double precision": "double", "numeric": "numeric"}.get(data_type, data_type)


def build_catalog(tables_rows, cols_rows, pk_rows, fk_rows):
    """Pure catalog assembly from raw information_schema rows (testable without a DB).

    tables_rows: [(name,)] · cols_rows: [(table, column, udt, data_type, char_len)]
    pk_rows: [(table, column)] · fk_rows: [(constraint, table, column, ref_table, ref_column)]
    """
    fks = {}
    for cname, tbl, col, ref_tbl, ref_col in fk_rows:
        f = fks.setdefault(cname, {"table": tbl, "cols": [], "ref_table": ref_tbl, "ref_cols": []})
        if col not in f["cols"]:
            f["cols"].append(col)
        if ref_col not in f["ref_cols"]:
            f["ref_cols"].append(ref_col)
    pks = {}
    for tbl, col in pk_rows:
        pks.setdefault(tbl, col)
    tables = {}
    for (tbl,) in tables_rows:
        if internal(tbl):
            continue
        tables[tbl] = {"key": pks.get(tbl) or "id", "cols": []}
    for tbl, col, udt, data_type, char_len in cols_rows:
        if tbl in tables:
            tables[tbl]["cols"].append((col, type_name(data_type, char_len, udt)))
    hidden = sum(1 for (tbl,) in tables_rows if internal(tbl))
    return {"tables": tables, "fks": list(fks.values()), "hidden": hidden}


def catalog(dsn):
    """Fetch the public-schema catalog from a live PostgreSQL (4 single SELECTs)."""
    con = pgwire.connect(dsn)
    try:
        _, tables_rows = con.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name")
        _, cols_rows = con.query(
            "SELECT table_name, column_name, udt_name, data_type, character_maximum_length "
            "FROM information_schema.columns WHERE table_schema = 'public' "
            "ORDER BY table_name, ordinal_position")
        _, pk_rows = con.query(
            "SELECT tc.table_name, kcu.column_name FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema "
            "WHERE tc.constraint_type = 'PRIMARY KEY' AND tc.table_schema = 'public'")
        _, fk_rows = con.query(
            "SELECT tc.constraint_name, tc.table_name, kcu.column_name, ccu.table_name, ccu.column_name "
            "FROM information_schema.table_constraints tc "
            "JOIN information_schema.key_column_usage kcu "
            "ON kcu.constraint_name = tc.constraint_name AND kcu.table_schema = tc.table_schema "
            "JOIN information_schema.constraint_column_usage ccu "
            "ON ccu.constraint_name = tc.constraint_name AND ccu.table_schema = tc.table_schema "
            "WHERE tc.constraint_type = 'FOREIGN KEY' AND tc.table_schema = 'public'")
    finally:
        con.close()
    return build_catalog([tuple(r) for r in tables_rows], [tuple(r) for r in cols_rows],
                         [tuple(r) for r in pk_rows], [tuple(r) for r in fk_rows])


def fk_edges(cat):
    """Declared-FK join statements between surviving tables, named for tracing
    back to the constraint (fk_<table>_<cols>__<ref_table>)."""
    out, seen = [], set()
    for f in cat["fks"]:
        if f["table"] not in cat["tables"] or f["ref_table"] not in cat["tables"]:
            continue
        name = "fk_%s_%s__%s" % (f["table"], "_".join(f["cols"]), f["ref_table"])
        if name in seen:
            continue
        seen.add(name)
        out.append((name, ", ".join("%s.%s = %s.%s" % (f["table"], k, f["ref_table"], v)
                                    for k, v in zip(f["cols"], f["ref_cols"]))))
    return out


def skeleton_yaml(cat, db):
    lines = ["dataset: %s_skeleton" % db, "description: %s" % t("skeleton_note"), "tables:"]
    for name in sorted(cat["tables"]):
        info = cat["tables"][name]
        cols = ", ".join("%s %s" % (c, ty) if ty else c for c, ty in info["cols"])
        lines.append('  %s: {key: %s, cols: "%s"}' % (name, info["key"], cols))
    edges = fk_edges(cat)
    if edges:
        lines.append("joins:")
        for name, edge in edges:
            lines.append('  %s: "%s"' % (name, edge))
    return "\n".join(lines) + "\n"


def bootstrap_report(cat):
    n_cols = sum(len(i["cols"]) for i in cat["tables"].values())
    return t("summary", n_tables=len(cat["tables"]), n_cols=n_cols,
             n_fks=len(fk_edges(cat)), n_hidden=cat["hidden"])


def parse_cols(cols_str):
    """'id varchar(36), name' -> [('id', 'varchar(36)'), ('name', None)] — bare
    names (hand-written models) compare on name only."""
    out = []
    for part in (cols_str or "").split(","):
        part = part.strip()
        if not part:
            continue
        name, _, ty = part.partition(" ")
        out.append((name, ty.strip() or None))
    return out


def drift(model, cat):
    """Model dict vs live catalog -> (drift_findings, new_cols, unmodeled, cols_compared).

    Drift = the model's claims are broken (dropped table/column, type change) —
    the failures that can make a model lie in an answer. New catalog columns and
    unmodeled tables are info, not drift: the model-scope guard keeps them out
    of answers anyway, and treating them as drift would keep every deliberately
    partial (curated) model forever red."""
    findings, new_cols, n_cols = [], {}, 0
    live = cat["tables"]
    for tname, tinfo in model.get("tables", {}).items():
        if tname not in live:
            findings.append(t("f_dropped_table", t=tname))
            continue
        model_cols = parse_cols(tinfo.get("cols", ""))
        live_types = dict(live[tname]["cols"])
        for cname, mty in model_cols:
            n_cols += 1
            if cname not in live_types:
                findings.append(t("f_dropped_col", c="%s.%s" % (tname, cname)))
            elif mty and live_types[cname] and mty != live_types[cname]:
                findings.append(t("f_type_changed", c="%s.%s" % (tname, cname),
                                  mt=mty, lt=live_types[cname]))
        added = [cname for cname, _ in live[tname]["cols"] if cname not in dict(model_cols)]
        if added:
            new_cols[tname] = added
    unmodeled = sorted(set(live) - set(model.get("tables", {})))
    return findings, new_cols, unmodeled, n_cols


def check_report(model, cat, path, dsn):
    p = pgwire.parse_dsn(dsn)
    findings, new_cols, unmodeled, n_cols = drift(model, cat)
    n_tables = len(model.get("tables", {}))
    lines = [t("report_head"), t("report_meta", path=path, dataset=model.get("dataset") or "?",
                                 db=p["database"], host=p["host"], n=n_tables, c=n_cols), ""]
    if findings:
        lines.append(t("drift_n", n=len(findings)))
        lines += ["- " + f for f in findings]
    lines += ["", t("unmodeled", n=len(unmodeled))]
    if unmodeled:
        lines.append(", ".join(unmodeled))
    lines += ["", t("new_cols", n=sum(len(v) for v in new_cols.values()))]
    for tname in sorted(new_cols):
        lines.append("  %s: +%s" % (tname, ", +".join(new_cols[tname])))
    lines += ["", t("result_drift" if findings else "result_clean", n=n_tables, c=n_cols)]
    return "\n".join(lines), bool(findings)


def run(args, model, model_path, pg):
    """Entry from ask.py main(): --bootstrap / --check."""
    global LANG
    LANG = args.lang
    if not pg:
        sys.exit(t("no_pg"))
    cat = catalog(pg)
    if args.bootstrap:
        db = pgwire.parse_dsn(pg)["database"]
        sys.stderr.write(bootstrap_report(cat) + "\n")
        sys.stdout.write(skeleton_yaml(cat, db))
        return
    if not model.get("tables"):
        sys.exit(t("no_tables_model"))
    report, has_drift = check_report(model, cat, model_path, pg)
    print(report)
    sys.exit(1 if has_drift else 0)


# ── W3.1: caliber versioning + deterministic caliber-drift alarm (#19) ──────

def caliber_index(model):
    """Every caliber-bearing entry of a model, keyed by name:
    {name: {"kind": metric|measure, "version": str, "text": caliber-or-desc}}.
    A missing `version` reads as 1 — every pre-W3 model stays valid."""
    out = {}
    for kind in ("metrics", "measures"):
        for name, meta in (model.get(kind) or {}).items():
            out[name] = {"kind": kind.rstrip("s"), "version": str(meta.get("version", "1")),
                         "text": meta.get("caliber") or meta.get("desc") or ""}
    return out


def caliber_diff(new, old):
    """Two model dicts -> (findings, n_compared). Pure; the alarm of #19.

    DRIFT (exit-able) = a caliber text changed while its version did not move —
    an edit-in-place, exactly what the discipline forbids. A text change WITH a
    version bump is a supersession: recorded as info, never drift. New/removed
    entries are info too — arrival is not drift."""
    ni, oi = caliber_index(new), caliber_index(old)
    findings, n = [], 0
    for name in sorted(set(ni) | set(oi)):
        if name not in ni:
            findings.append(("info", t("f_cal_removed", name=name)))
            continue
        if name not in oi:
            findings.append(("info", t("f_cal_new", name=name, kind=ni[name]["kind"])))
            continue
        n += 1
        if ni[name]["text"] != oi[name]["text"] and ni[name]["version"] == oi[name]["version"]:
            findings.append(("drift", t("f_cal_edited", name=name, version=ni[name]["version"], kind=ni[name]["kind"])))
        elif ni[name]["version"] != oi[name]["version"]:
            what = t("f_cal_text_changed", name=name) if ni[name]["text"] != oi[name]["text"] else t("f_cal_text_same", name=name)
            findings.append(("info", t("f_cal_bumped", name=name, old=oi[name]["version"], new=ni[name]["version"], what=what)))
    return findings, n


def calibers_report(new, old, new_path, old_path):
    findings, n = caliber_diff(new, old)
    drifts = [f for kind, f in findings if kind == "drift"]
    lines = [t("cal_report_head"), t("cal_report_meta", new_path=new_path, old_path=old_path,
                                     new_ds=new.get("dataset") or "?", old_ds=old.get("dataset") or "?", n=n), ""]
    if drifts:
        lines.append(t("cal_drift_n", n=len(drifts)))
        lines += ["- " + f for f in drifts]
    infos = [f for kind, f in findings if kind == "info"]
    if infos:
        lines.append(t("cal_info_n", n=len(infos)))
        lines += ["- " + f for f in infos]
    if not findings:
        lines.append(t("cal_no_change"))
    lines += ["", t("result_drift" if drifts else "cal_result_clean", n=n)]
    return "\n".join(lines), bool(drifts)


def run_calibers(args, new_model, new_path):
    """Entry from ask.py main(): --calibers <new> --against <old>."""
    old_path = args.against
    old_model = __import__("ask").load_yaml(old_path)
    report, has_drift = calibers_report(new_model, old_model, new_path, old_path)
    print(report)
    sys.exit(1 if has_drift else 0)
