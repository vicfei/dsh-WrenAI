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
"""
import argparse, datetime as dt, json, math, os, re, sqlite3, subprocess, sys

import pgwire

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(KIT, "semantic", "semantic.db")
MODEL = os.path.join(KIT, "semantic", "models.yaml")

# English is the first language (family rule); Chinese is the --lang zh fallback.
STR = {
    "en": {
        "ask": "## Ask: {q}",
        "calibers": "## Calibers riding with this result (metric definitions used)",
        "guard": "guard: single SELECT only — rejected: {sql}",
        "init": "init → {db} · {symbol} · {n} bars · view v_metrics (calibers in semantic/models.yaml)",
        "retry_hint": "\n\nThe previously generated SQL failed to execute with error: {err}\nFix it and output again.",
        "footer": "---\n*engine: semantic-ask v0 · single-SELECT guard · self-heal retry · backend: {backend} · calibers versioned in semantic/models.yaml · {ts}*",
    },
    "zh": {
        "ask": "## 问数：{q}",
        "calibers": "## 口径随行（本次引用的指标定义）",
        "guard": "护栏：仅允许单条 SELECT，拒绝：{sql}",
        "init": "init → {db} · {symbol} · {n} bars · 视图 v_metrics（口径见 semantic/models.yaml）",
        "retry_hint": "\n\n上次生成的 SQL 执行报错：{err}\n请修正后重新输出。",
        "footer": "---\n*engine: semantic-ask v0 · 单条 SELECT 护栏 · 自愈重试 · 后端：{backend} · 口径版本随 semantic/models.yaml · {ts}*",
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
            if m2 and cur in ("dimensions", "measures", "metrics"):
                name, body = m2.group(1), m2.group(2)
                d = {}
                for part in _split_inline(body):
                    k, _, v = part.partition(":")
                    d[k.strip()] = v.strip().strip('"')
                out[cur][name] = d
    return out


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


def llm(catalog, question, dialect, target):
    key = subprocess.run(["bash", "-c", 'grep -m1 "^export DEEPSEEK_API_KEY=" ~/.bashrc | cut -d= -f2'],
                         capture_output=True, text=True).stdout.strip().strip('"')
    sysmsg = (f"You are a semantic-layer SQL generator. Write a SINGLE SELECT against the {dialect} "
              f"view/table {target} ({dialect} aggregate functions allowed). "
              "INSERT/UPDATE/DELETE/DDL/multiple statements are forbidden. "
              "Output JSON {\"sql\":\"...\",\"metrics_used\":[metric names]}. "
              "Metric caliber catalog (the semantic source of any result):\n" + catalog)
    body = {"model": "deepseek-chat", "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": question}]}
    r = subprocess.run(["curl", "-s", "-m", "120", "https://api.deepseek.com/chat/completions",
                        "-H", f"Authorization: Bearer {key}", "-H", "Content-Type: application/json",
                        "-d", json.dumps(body)], capture_output=True, text=True)
    return json.loads(json.loads(r.stdout)["choices"][0]["message"]["content"])


def guarded(sql):
    sql = sql.strip().rstrip(";")
    if not re.match(r"(?is)^SELECT\s.+$", sql) or ";" in sql:
        sys.exit(t("guard", sql=sql[:120]))
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
    ap.add_argument("--pg", metavar="DSN", help='PostgreSQL backend, e.g. "postgresql://user:pass@host:5432/db"')
    ap.add_argument("--model", metavar="PATH", help="semantic model YAML (default semantic/models.yaml)")
    ap.add_argument("--lang", choices=("en", "zh"), default="en",
                    help="output language (default en; zh is the fallback)")
    args = ap.parse_args()
    LANG = args.lang
    model_path = args.model or MODEL
    model = load_yaml(model_path)
    if args.init:
        if args.pg:
            sys.exit("guard: --init is the SQLite demo loader; --pg backends attach to existing data")
        init_db(args.init)
        return
    if not args.ask:
        print(__doc__); sys.exit(2)
    dialect = "PostgreSQL" if args.pg else "SQLite"
    target = model.get("view") or model.get("table") or "v_metrics"
    catalog = json.dumps({k: {n: v.get("caliber", v.get("desc")) for n, v in model.get(k, {}).items()}
                          for k in ("dimensions", "measures", "metrics")}, ensure_ascii=False, indent=1)
    plan = llm(catalog, args.ask, dialect, target)
    sql = guarded(plan["sql"])
    try:
        cols, rows = run_sql(args.pg, sql)
    except (sqlite3.Error, pgwire.PGError) as e:
        # executor error → retry once with the error fed back (semantic self-heal)
        plan = llm(catalog, args.ask + t("retry_hint", err=e), dialect, target)
        sql = guarded(plan["sql"])
        cols, rows = run_sql(args.pg, sql)
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
    backend = "PostgreSQL via pgwire (stdlib wire client)" if args.pg else "SQLite (stdlib)"
    print("\n" + t("footer", ts=dt.datetime.now().isoformat(timespec='seconds'), backend=backend))


if __name__ == "__main__":
    main()
