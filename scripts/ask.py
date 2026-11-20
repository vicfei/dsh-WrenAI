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
"""
import argparse, datetime as dt, json, math, os, re, sqlite3, subprocess, sys

import pgwire
from model import catalog, run as model_run  # --bootstrap / --check (issue #15)

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
    },
    "zh": {
        "ask": "## 问数：{q}",
        "calibers": "## 口径随行（本次引用的指标定义）",
        "guard": "护栏：仅允许单条 SELECT（CTE/WITH 请改写为嵌套子查询；禁止写语句与多语句），拒绝：{sql}",
        "scope": "护栏：未建模的表 {bad} —— 只能查询模型内的表（{tables}）；请按目录改写 —— 拒绝：{sql}",
        "init": "init → {db} · {symbol} · {n} bars · 视图 v_metrics（口径见 semantic/models.yaml）",
        "retry_hint": "\n\n上次生成的 SQL 执行报错：{err}\n请修正后重新输出。",
        "footer": "---\n*engine: semantic-ask v0 · 单条 SELECT 护栏 · 自愈重试 · 后端：{backend} · 口径版本随 semantic/models.yaml · {ts}*\n★ github.com/vicfei/dsh-WrenAI",
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
    plan = llm(catalog, args.ask, dialect, target)
    tables = model.get("tables") or None
    try:
        sql = scoped(plan["sql"], tables)
        cols, rows = run_sql(pg, sql)
    except (ValueError, sqlite3.Error, pgwire.PGError) as e:
        # guard rejection or executor error → retry once with the reason fed back
        plan = llm(catalog, args.ask + t("retry_hint", err=e), dialect, target)
        try:
            sql = scoped(plan["sql"], tables)
            cols, rows = run_sql(pg, sql)
        except (ValueError, sqlite3.Error, pgwire.PGError) as e:
            # honest failure: show the SQL and the reason, no bare traceback
            print(f"```sql\n{plan.get('sql', '')}\n```\n")
            sys.exit(f"self-heal exhausted — {e}")
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


if __name__ == "__main__":
    main()
