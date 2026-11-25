#!/usr/bin/env python3
"""Self-hosted semantic layer + calibers-ride-with-results ask-data engine (WrenAI concept seat, M0)

Upstream WrenAI (18.3k★, multi-licensed: core Apache-2.0) = GenBI / governed text-to-SQL
with a semantic layer. This plugin natively implements the differentiated core — the
**self-hosted semantic layer**: metrics carry versioned calibers, generated SQL runs
against semantic views, and every result ships with the caliber statements of the
metrics it used ("calibers ride with results" — the line vs raw NL2SQL, and the
data-asking edition of the factor-authentication caliber discipline). Clean-room,
zero upstream code.

Pipeline: --init loads klines into SQLite and builds the semantic view (metric windows
precomputed) → on ask, the LLM sees only the semantic catalog (dimensions/metrics/
calibers) and emits one SELECT → deterministic guard (single SELECT only) → execute →
numbers + calibers together. Execution is pluggable: SQLite (default, stdlib) or
PostgreSQL via --pg (pgwire, a zero-dependency wire-protocol client) — the semantic
layer above (catalog → guarded SELECT → calibers ride) is identical either way.

Usage:
  python3 scripts/ask.py --init /tmp/btc_365.json
  python3 scripts/ask.py --ask "average close and annualized volatility over the last 30 days?"
  python3 scripts/ask.py --ask "最近30天的平均收盘价和年化波动率是多少？" --lang zh
  python3 scripts/ask.py --ask "..." --pg "postgresql://user:pass@host:5432/db" --model semantic/ops.yaml
  python3 scripts/ask.py --weknora --bootstrap > my-model.yaml   # catalog -> skeleton (no LLM)
  python3 scripts/ask.py --weknora --model semantic/weknora.yaml --check  # drift report
  python3 scripts/ask.py --weknora --model new.yaml --calibers --against semantic/weknora.yaml  # caliber drift alarm (zero LLM)
  python3 scripts/ask.py --weknora --ask "..." --ledger            # append the ask to the ledger (evidence)
  python3 scripts/ask.py --weknora --ledger-print 5                 # the last 5 recorded asks
  python3 scripts/ask.py --weknora --replay wl_ab12cd34             # re-run a recorded SQL now, numbers+calibers side by side
"""
import argparse, datetime as dt, hashlib, json, math, os, re, sqlite3, subprocess, sys

import pgwire
from model import catalog, run as model_run, run_calibers  # --bootstrap / --check (#15); --calibers (#19)

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(KIT, "semantic", "semantic.db")
MODEL = os.path.join(KIT, "semantic", "models.yaml")

# English is the first language (family rule); Chinese is the --lang zh fallback.
LANG = "en"
STR = {
    "en": {
        "ask": "## Ask: {q}",
        "calibers": "## Calibers riding with this result (metric definitions used)",
        "guard": "guard: single SELECT only (rewrite CTE/WITH as nested subqueries; no writes, no multi-statement) — rejected: {sql}",
        "scope": "guard: unmodeled table(s) {bad} — query only the modeled tables ({tables}); rewrite against the catalog — rejected: {sql}",
        "init": "init → {db} · {symbol} · {n} bars · view v_metrics (calibers in semantic/models.yaml)",
        "retry_hint": "\n\nThe previously generated SQL failed to execute with error: {err}\nFix it and output again.",
        "footer": "---\n*engine: semantic-ask v0 · single-SELECT guard · self-heal retry · backend: {backend} · calibers versioned in semantic/models.yaml · {ts}*\n★ github.com/vicfei/dsh-WrenAI",
        "ledger_line": "ledger: {id} -> {path} ({n} row(s) recorded{trunc}, verdict {verdict})",
        "ledger_print_head": "## Ledger - last {n} of {total} recorded ask(s) ({path})",
        "ledger_row": "{id} · {at} · {verdict} · Q: {q}",
        "ledger_row_cals": "        calibers: {cals}",
        "ledger_empty": "ledger is empty ({path})",
        "replay_head": "## Replay {id} - recorded {at}, model {ds} - re-executed now",
        "replay_shape": "shape: then {ra} rows x {ca} cols · now {rb} rows x {cb} cols",
        "replay_cell": "row {r} · {col}: then {a} -> now {b}",
        "replay_cal": "caliber {name}: then v{old} -> now v{new}",
        "replay_verdict_moved": "RESULT: numbers moved ({cells} cell(s) changed{shape})",
        "replay_verdict_cal": "RESULT: calibers changed ({cals} version(s) moved) - the same question now answers under different definitions",
        "replay_verdict_stable": "RESULT: stable - same numbers, same caliber versions",
    },
    "zh": {
        "ask": "## 问数：{q}",
        "calibers": "## 口径随行（本次引用的指标定义）",
        "guard": "护栏：仅允许单条 SELECT（CTE/WITH 请改写为嵌套子查询；禁止写语句与多语句），拒绝：{sql}",
        "scope": "护栏：未建模的表 {bad} —— 只能查询模型内的表（{tables}）；请按目录改写 —— 拒绝：{sql}",
        "init": "init → {db} · {symbol} · {n} bars · 视图 v_metrics（口径见 semantic/models.yaml）",
        "retry_hint": "\n\n上次生成的 SQL 执行报错：{err}\n请修正后重新输出。",
        "footer": "---\n*engine: semantic-ask v0 · 单条 SELECT 护栏 · 自愈重试 · 后端：{backend} · 口径版本随 semantic/models.yaml · {ts}*\n★ github.com/vicfei/dsh-WrenAI",
        "ledger_line": "台账：{id} -> {path}（记录 {n} 行{trunc}，判定 {verdict}）",
        "ledger_print_head": "## 台账 —— 最近 {n} / 共 {total} 条记录（{path}）",
        "ledger_row": "{id} · {at} · {verdict} · 问：{q}",
        "ledger_row_cals": "        口径：{cals}",
        "ledger_empty": "台账为空（{path}）",
        "replay_head": "## 重放 {id} —— 记录于 {at}，模型 {ds} —— 现在重新执行",
        "replay_shape": "形态：当时 {ra} 行 x {ca} 列 · 现在 {rb} 行 x {cb} 列",
        "replay_cell": "第 {r} 行 · {col}：当时 {a} -> 现在 {b}",
        "replay_cal": "口径 {name}：当时 v{old} -> 现在 v{new}",
        "replay_verdict_moved": "结论：数字变了（{cells} 个单元格变化{shape}）",
        "replay_verdict_cal": "结论：口径变了（{cals} 个版本变动）—— 同一问题现在在不同定义下作答",
        "replay_verdict_stable": "结论：稳定 —— 数字与口径版本都未变",
    },
}


def t(key, **kw):
    return STR[LANG].get(key, key).format(**kw)


def _split_inline(body):
    # split an inline {k: v, ...} body on commas, but never inside double quotes
    parts, buf, inq = [], [], False
    for ch in body:
        if ch == '"':
            inq = not inq
        elif ch == "," and not inq:
            parts.append("".join(buf)); buf = []; continue
        buf.append(ch)
    parts.append("".join(buf))
    return [p.strip() for p in parts if p.strip()]


def load_yaml(path):
    out, cur, section = {}, None, None
    for line in open(path):
        line = line.rstrip()
        if not line or line.lstrip().startswith("#"):
            continue
        m = re.match(r"^(\w+):\s*(.*)$", line)
        if m and not line.startswith(" "):
            cur, section = m.group(1), m.group(2) or None
            out[cur] = section if section else {}
            if section is None:
                out[cur] = {}
        else:
            m2 = re.match(r"^\s+(\w+):\s*\{(.+)\}\s*$", line)
            if m2 and cur in ("dimensions", "measures", "metrics", "tables"):
                name, body = m2.group(1), m2.group(2)
                d = {}
                for part in _split_inline(body):
                    k, _, v = part.partition(":")
                    d[k.strip()] = v.strip().strip('"')
                out[cur][name] = d
            else:
                m3 = re.match(r"^\s+(\w+):\s*(.+)$", line)
                if m3 and cur == "joins":
                    out.setdefault(cur, {})[m3.group(1)] = m3.group(2).strip().strip('"')
    return out


def weknora_dsn():
    """Zero-config DSN: read the WeKnora deployment's own .env and map the
    container-internal DB host to the host's loopback (published port)."""
    from urllib.parse import quote
    wk = os.environ.get("WEKNORA_HOME") or os.path.expanduser("~/WeKnora")
    envf = os.path.join(wk, ".env")
    if not os.path.exists(envf):
        sys.exit("--weknora: %s not found (set WREN_PG_DSN or WEKNORA_HOME)" % envf)
    env = {}
    for line in open(envf):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            env[k.strip()] = v.strip()
    host = env.get("DB_HOST", "postgres")
    if host in ("postgres", "db", "app"):  # container-internal name → host loopback
        host = "127.0.0.1"
    return "postgresql://%s:%s@%s:%s/%s" % (
        quote(env.get("DB_USER") or "postgres", safe=""),
        quote(env.get("DB_PASSWORD") or "", safe=""),
        host, env.get("DB_PORT") or "5432", env.get("DB_NAME") or "WeKnora")


def init_db(klines_json):
    data = json.load(open(klines_json))
    symbol, bars = next(iter(data.items()))
    con = sqlite3.connect(DB)
    con.execute("DROP TABLE IF EXISTS bars")
    con.execute("CREATE TABLE bars (symbol TEXT, date TEXT, open REAL, close REAL, high REAL, low REAL, volume REAL)")
    con.executemany("INSERT INTO bars VALUES (?,?,?,?,?,?,?)",
                    [(symbol, b[0], b[1], b[2], b[3], b[4], b[5]) for b in bars])
    con.execute("""
        CREATE VIEW v_metrics AS
        WITH r AS (
          SELECT symbol, date, close,
                 close / LAG(close, 1) OVER w - 1 AS ret_1d,
                 close / LAG(close, 30) OVER w - 1 AS ret_30d,
                 close / MAX(close) OVER w2 - 1 AS dd_120
          FROM bars
          WINDOW w AS (PARTITION BY symbol ORDER BY date),
                 w2 AS (PARTITION BY symbol ORDER BY date ROWS BETWEEN 119 PRECEDING AND CURRENT ROW)
        )
        SELECT symbol, date, close, ret_1d, ret_30d, dd_120,
               SQRT(252 * AVG(ret_1d * ret_1d) OVER (PARTITION BY symbol ORDER BY date ROWS BETWEEN 29 PRECEDING AND CURRENT ROW)) AS vol_30d_ann
        FROM r
    """)
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM bars").fetchone()[0]
    print(t("init", db=DB, symbol=symbol, n=n))
    con.close()


def _llm_key():
    """API key precedence: WREN_LLM_API_KEY / DEEPSEEK_API_KEY env, then the
    ~/.bashrc export line (single-box default). An intranet endpoint without
    auth may set WREN_LLM_API_KEY to any non-empty placeholder."""
    for var in ("WREN_LLM_API_KEY", "DEEPSEEK_API_KEY"):
        if os.environ.get(var):
            return os.environ[var]
    return subprocess.run(["bash", "-c", 'grep -m1 "^export DEEPSEEK_API_KEY=" ~/.bashrc | cut -d= -f2'],
                          capture_output=True, text=True).stdout.strip().strip('"')


def _llm_url():
    """OpenAI-compatible chat endpoint; override for intranet model services
    (vLLM / Ollama / company DeepSeek deployments) via WREN_LLM_BASE_URL."""
    base = (os.environ.get("WREN_LLM_BASE_URL") or "https://api.deepseek.com").rstrip("/")
    return base + "/chat/completions"


def _llm_model():
    return os.environ.get("WREN_LLM_MODEL") or "deepseek-chat"


def llm(catalog, question, dialect, target):
    key = _llm_key()
    sysmsg = (f"You are a semantic-layer SQL generator. Write a SINGLE SELECT against {target} "
              f"({dialect}; aggregate/window functions allowed). "
              "INSERT/UPDATE/DELETE/DDL/multiple statements are forbidden. "
              "Metric calibers are binding definitions — follow the join paths they prescribe, "
              "and prefer metric/dimension names from the catalog. "
              "Output JSON {\"sql\":\"...\",\"metrics_used\":[metric names]}. "
              "Metric caliber catalog (the semantic source of any result):\n" + catalog)
    body = {"model": _llm_model(), "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": question}]}
    r = subprocess.run(["curl", "-s", "-m", "120", _llm_url(),
                        "-H", f"Authorization: Bearer {key}", "-H", "Content-Type: application/json",
                        "-d", json.dumps(body)], capture_output=True, text=True)
    return json.loads(json.loads(r.stdout)["choices"][0]["message"]["content"])


def guarded(sql):
    """Normalize + enforce the single-SELECT guard. Raises GuardRejection so the
    caller can self-heal (retry with the reason fed back) before giving up."""
    sql = sql.strip().rstrip(";").strip()
    if not re.match(r"(?is)^SELECT\s.+$", sql) or ";" in sql:
        raise ValueError(t("guard", sql=sql[:120]))
    return sql


# keywords / set-returning functions that can follow FROM/JOIN without being tables
_SCOPE_SKIP = {"lateral", "unnest", "generate_series", "generate_subscripts",
               "jsonb_array_elements", "jsonb_array_elements_text", "jsonb_to_record",
               "jsonb_to_recordset", "regexp_split_to_table", "string_to_table",
               "crosstab", "values", "select"}


def table_refs(sql):
    """Best-effort table references in a single SELECT: identifiers after
    FROM/JOIN (comma lists included), schema-qualified names reduced to the
    table, quoted identifiers unquoted; set-returning function calls (identifier
    followed by '('), keywords and subquery parens skipped. A governor, not a
    parser — same posture as the single-SELECT guard."""
    refs = set()
    s = re.sub(r"--[^\n]*", " ", sql)
    s = re.sub(r"/\*.*?\*/", " ", s, flags=re.S)
    ident = r'"[^"]+"|[A-Za-z_][A-Za-z0-9_$]*'
    for m in re.finditer(r"(?i)\b(from|join)\s*", s):
        pos = m.end()
        while True:
            idm = re.match(r"\s*((?:%s)(?:\.(?:%s))*)" % (ident, ident), s[pos:])
            if not idm:
                break
            name = idm.group(1).split(".")[-1].strip('"').lower()
            pos += idm.end()
            if name in _SCOPE_SKIP or re.match(r"\s*\(", s[pos:]):
                break  # keyword or function call, not a table
            refs.add(name)
            comma = re.match(r"\s*,\s*", s[pos:])
            if not comma:
                # optional alias (AS x / x) may sit between table and comma
                am = re.match(r"\s+(?:as\s+)?(?:%s)" % ident, s[pos:], re.I)
                if am:
                    pos += am.end()
                    comma = re.match(r"\s*,\s*", s[pos:])
            if comma:
                pos += comma.end()
                continue
            break
    return refs


def scoped(sql, tables):
    """Single-SELECT guard + model-scope guard: with a tables model, SQL may
    only reference modeled tables — numbers from unmodeled tables would ship
    without calibers. Raises ValueError (self-healable) on either violation."""
    sql = guarded(sql)
    if tables:
        bad = sorted(r for r in table_refs(sql) if r not in tables)
        if bad:
            raise ValueError(t("scope", bad=", ".join(bad),
                               tables=", ".join(sorted(tables)), sql=sql[:120]))
    return sql


def run_sql(dsn, sql):
    """Execute a guarded SELECT on the selected backend → (cols, rows).
    Raises sqlite3.OperationalError / pgwire.PGError with the executor's message."""
    if dsn:
        con = pgwire.connect(dsn)
        try:
            return con.query(sql)
        finally:
            con.close()
    con = sqlite3.connect(DB)
    try:
        cur = con.execute(sql)
        rows = cur.fetchall()
        return [d[0] for d in cur.description], rows
    finally:
        con.close()


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.6g}"
    if not isinstance(v, int):  # PG text format → compress numerics for display
        try:
            return f"{float(v):.6g}"
        except ValueError:
            return str(v)
    return str(v)


LEDGER_ROWS_CAP = 50   # a recorded ask keeps its first 50 rows; the count stays honest via n_rows/truncated


def ledger_default_path(model_path):
    """The ledger sits beside its model — one model, one append-only trail."""
    return os.path.join(os.path.dirname(os.path.abspath(model_path or MODEL)), "ledger.ndjson")


def ledger_append(path, entry):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def ledger_read(path):
    if not os.path.exists(path):
        return []
    out = []
    for line in open(path, encoding="utf-8"):
        if line.strip():
            out.append(json.loads(line))
    return out


def metrics_with_versions(model, names):
    """The caliber versions an answer rode on — the ask-time view of #19's versioning."""
    out = []
    for m in names or []:
        meta = (model.get("metrics") or {}).get(m) or (model.get("measures") or {}).get(m)
        if meta:
            out.append({"name": m, "version": str(meta.get("version", "1"))})
    return out


def replay(entry, model, pg):
    """Re-execute a recorded SQL through the same guards and diff it against its
    recording: cells that moved, caliber versions that moved. The M1 caliber-drift
    alarm in live form — same question, then vs now, side by side."""
    sql = scoped(entry["sql"], (model.get("tables") or None))
    cols, rows = run_sql(pg, sql)
    now_rows = [[fmt(v) for v in r] for r in rows[:LEDGER_ROWS_CAP]]
    then_rows = entry.get("rows") or []
    cell_diffs, shape_note = [], ""
    if len(then_rows) != len(now_rows) or (then_rows and len(then_rows[0]) != len(now_rows[0])):
        shape_note = " + " + t("replay_shape", ra=len(then_rows), ca=len(then_rows[0]) if then_rows else 0,
                               rb=len(now_rows), cb=len(now_rows[0]) if now_rows else 0)
    for ri, (a, b) in enumerate(zip(then_rows, now_rows)):
        for ci, (va, vb) in enumerate(zip(a, b)):
            if va != vb:
                cell_diffs.append(t("replay_cell", r=ri + 1, col=(cols[ci] if ci < len(cols) else ci), a=va, b=vb))
    then_v = {m["name"]: m["version"] for m in entry.get("metrics_used") or []}
    now_v = {m["name"]: m["version"] for m in metrics_with_versions(model, then_v)}
    cal_diffs = [t("replay_cal", name=n, old=then_v[n], new=now_v.get(n, "?")) for n in then_v if now_v.get(n) != then_v[n]]
    lines = [t("replay_head", id=entry["id"], at=entry.get("at"), ds=entry.get("model", {}).get("dataset") or "?"), "",
             "```sql\n" + sql + "\n```\n"]
    for d in cell_diffs[:20]:
        lines.append("- " + d)
    if len(cell_diffs) > 20:
        lines.append("- … " + str(len(cell_diffs) - 20))
    for d in cal_diffs:
        lines.append("- " + d)
    if cal_diffs:
        lines.append("\n" + t("replay_verdict_cal", cals=len(cal_diffs)))
    elif cell_diffs or shape_note:
        lines.append("\n" + t("replay_verdict_moved", cells=len(cell_diffs), shape=shape_note))
    else:
        lines.append("\n" + t("replay_verdict_stable"))
    return "\n".join(lines)


def main():
    global LANG
    ap = argparse.ArgumentParser()
    ap.add_argument("--init")
    ap.add_argument("--ask")
    ap.add_argument("--bootstrap", action="store_true",
                    help="emit a skeleton semantic model from the PostgreSQL catalog to stdout (zero LLM, no calibers ride); combine with --pg DSN or --weknora")
    ap.add_argument("--check", action="store_true",
                    help="drift-check the semantic model against the live catalog (table/column/type diff; exit 1 on drift)")
    ap.add_argument("--pg", metavar="DSN", help='PostgreSQL backend, e.g. "postgresql://user:pass@host:5432/db"')
    ap.add_argument("--weknora", action="store_true",
                    help="zero-config WeKnora preset: PG DSN from ~/WeKnora/.env (WREN_PG_DSN/WEKNORA_HOME override) + semantic/weknora.yaml")
    ap.add_argument("--model", metavar="PATH", help="semantic model YAML (default semantic/models.yaml; --weknora defaults to semantic/weknora.yaml)")
    ap.add_argument("--calibers", action="store_true",
                    help="deterministic caliber-drift alarm: diff this --model against --against OLD.yaml (zero LLM; exit 1 when a caliber changed without a version bump)")
    ap.add_argument("--against", metavar="OLD.yaml", help="the old model for --calibers")
    ap.add_argument("--ledger", nargs="?", const="", metavar="PATH",
                    help="with --ask: append the ask as one ndjson event (default PATH sits beside the model)")
    ap.add_argument("--ledger-print", nargs="?", const=10, metavar="N", type=int,
                    help="print the last N recorded asks and exit")
    ap.add_argument("--replay", metavar="ID", help="re-execute a recorded ask's SQL now, numbers and caliber versions side by side")
    ap.add_argument("--lang", choices=("en", "zh"), default="en",
                    help="output language (default en; zh is the fallback)")
    args = ap.parse_args()
    LANG = args.lang
    pg = args.pg
    if args.weknora:
        pg = pg or os.environ.get("WREN_PG_DSN") or weknora_dsn()
    model_path = args.model or (os.path.join(KIT, "semantic", "weknora.yaml") if args.weknora else MODEL)
    model = load_yaml(model_path)
    if args.init:
        if pg:
            sys.exit("guard: --init is the SQLite demo loader; --pg backends attach to existing data")
        init_db(args.init)
        return
    if args.bootstrap or args.check:
        model_run(args, model, model_path, pg)
        return
    if args.calibers:
        if not args.against:
            sys.exit("--calibers needs --against OLD.yaml (the model to diff against)")
        run_calibers(args, model, model_path)
        return
    if args.ledger_print is not None:
        path = args.ledger or ledger_default_path(model_path)
        entries = ledger_read(path)
        if not entries:
            print(t("ledger_empty", path=path)); return
        n = min(args.ledger_print, len(entries))
        print(t("ledger_print_head", n=n, total=len(entries), path=path))
        for e in entries[-n:]:
            cals = ", ".join("%s@v%s" % (m["name"], m["version"]) for m in e.get("metrics_used") or []) or "-"
            print(t("ledger_row", id=e["id"], at=e.get("at"), verdict=e.get("verdict"), q=(e.get("question") or "")[:70]))
            print(t("ledger_row_cals", cals=cals))
        return
    if args.replay:
        path = args.ledger or ledger_default_path(model_path)
        hit = [e for e in ledger_read(path) if e["id"] == args.replay]
        if not hit:
            sys.exit("replay: no ledger entry %s in %s" % (args.replay, path))
        if not pg:
            sys.exit("replay: re-execution needs the backend the SQL ran on (--pg DSN or --weknora)")
        print(replay(hit[0], model, pg))
        return
    if not args.ask:
        print(__doc__); sys.exit(2)
    dialect = "PostgreSQL" if pg else "SQLite"
    if model.get("tables"):
        target = "the PostgreSQL tables and join paths listed in the catalog"
        catalog = json.dumps({k: model[k] for k in ("tables", "joins", "dimensions", "measures", "metrics") if model.get(k)},
                              ensure_ascii=False, indent=1)
    else:
        target = "the %s view %s" % (dialect, model.get("view") or model.get("table") or "v_metrics")
        catalog = json.dumps({k: {n: v.get("caliber", v.get("desc")) for n, v in model.get(k, {}).items()}
                              for k in ("dimensions", "measures", "metrics")}, ensure_ascii=False, indent=1)
    t0 = dt.datetime.now()
    plan = llm(catalog, args.ask, dialect, target)
    tables = model.get("tables") or None
    trail = {"verdict": "ok", "guard_rejection": None, "sql": None, "cols": [], "rows": []}

    def _record(verdict):
        """One append-only ledger event — the ask as evidence (#20). Failures
        record too: the honest trail includes the rejections."""
        path = args.ledger or ledger_default_path(model_path)
        entry = {"id": "wl_" + hashlib.sha1((args.ask + dt.datetime.now().isoformat()).encode()).hexdigest()[:8],
                 "at": dt.datetime.now().isoformat(timespec="seconds"), "question": args.ask,
                 "model": {"path": model_path, "dataset": model.get("dataset"),
                           "sha": hashlib.sha256(open(model_path, "rb").read()).hexdigest()[:16]},
                 "backend": "pg" if pg else "sqlite", "sql": trail["sql"] or plan.get("sql", ""),
                 "verdict": verdict, "guard_rejection": trail["guard_rejection"],
                 "metrics_used": metrics_with_versions(model, plan.get("metrics_used", [])),
                 "cols": trail["cols"], "n_rows": len(trail["rows"]),
                 "rows": [[fmt(v) for v in r] for r in trail["rows"][:LEDGER_ROWS_CAP]],
                 "truncated": len(trail["rows"]) > LEDGER_ROWS_CAP,
                 "elapsed_s": round((dt.datetime.now() - t0).total_seconds(), 1)}
        ledger_append(path, entry)
        return entry, path

    try:
        try:
            sql = scoped(plan["sql"], tables)
            cols, rows = run_sql(pg, sql)
        except (ValueError, sqlite3.Error, pgwire.PGError) as e:
            # guard rejection or executor error → retry once with the reason fed back
            trail["verdict"], trail["guard_rejection"] = "self_healed", str(e)[:300]
            plan = llm(catalog, args.ask + t("retry_hint", err=e), dialect, target)
            sql = scoped(plan["sql"], tables)
            cols, rows = run_sql(pg, sql)
    except (ValueError, sqlite3.Error, pgwire.PGError) as e:
        # honest failure: record it, show the SQL and the reason, no bare traceback
        _record("failed")
        print(f"```sql\n{plan.get('sql', '')}\n```\n")
        sys.exit(f"self-heal exhausted — {e}")
    trail["sql"], trail["cols"], trail["rows"] = sql, cols, rows
    print(t("ask", q=args.ask) + "\n")
    print(f"```sql\n{sql}\n```\n")
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for r in rows[:12]:
        print("| " + " | ".join(fmt(v) for v in r) + " |")
    print("\n" + t("calibers"))
    for m in plan.get("metrics_used", []):
        meta = model.get("metrics", {}).get(m) or model.get("measures", {}).get(m)
        if meta:
            print(f"- **{m}**: {meta.get('caliber') or meta.get('desc')}")
    backend = "SQLite (stdlib)"
    if pg:
        backend = "WeKnora PostgreSQL via pgwire" if args.weknora else "PostgreSQL via pgwire (stdlib wire client)"
    print("\n" + t("footer", ts=dt.datetime.now().isoformat(timespec='seconds'), backend=backend))
    if args.ledger is not None:
        entry, path = _record(trail["verdict"])
        print(t("ledger_line", id=entry["id"], path=path, n=entry["n_rows"],
                trunc="…" if entry["truncated"] else "", verdict=entry["verdict"]))


if __name__ == "__main__":
    main()
