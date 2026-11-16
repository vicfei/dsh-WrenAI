#!/usr/bin/env python3
"""自托管语义层 + 口径随行的问数引擎（WrenAI 概念位 M0）

上游 WrenAI（18.3k★，多许可：core Apache-2.0）= GenBI/text-to-SQL + 语义层。
本插件原生实现其差异核心——**自托管语义层**：指标带版本化口径（caliber），
生成的 SQL 走语义视图，结果逐指标附口径声明（口径随行 = 与裸 NL2SQL 的
分界线，也是因子鉴真口径治理思想的数据问数版）。净室实现，零上游代码关系。

管线：--init 把 K 线装进 SQLite 并按语义模型建视图（指标窗口预计算）→
问数时 LLM 只见语义目录（维度/指标/口径）产出 SELECT → 确定性校验
（仅允许单条 SELECT）→ 执行 → 数字+口径一起出。

用法：
  python3 scripts/ask.py --init /tmp/btc_365.json
  python3 scripts/ask.py --ask "最近30天的平均收盘价和年化波动率是多少？"
"""
import argparse, datetime as dt, json, math, os, re, sqlite3, subprocess, sys

KIT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB = os.path.join(KIT, "semantic", "semantic.db")
MODEL = os.path.join(KIT, "semantic", "models.yaml")


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
                for part in body.split(","):
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
    print(f"init → {DB} · {symbol} · {n} bars · 视图 v_metrics（口径见 semantic/models.yaml）")
    con.close()


def llm(catalog, question):
    key = subprocess.run(["bash", "-c", 'grep -m1 "^export DEEPSEEK_API_KEY=" ~/.bashrc | cut -d= -f2'],
                         capture_output=True, text=True).stdout.strip().strip('"')
    sysmsg = ("你是语义层 SQL 生成器。只能对视图 v_metrics 写【单条 SELECT】（可用 SQLite 聚合函数），"
              "禁止 INSERT/UPDATE/DELETE/DDL/多语句。输出 JSON {\"sql\":\"...\",\"metrics_used\":[指标名]}。"
              "指标口径目录（结果的语义来源）：\n" + catalog)
    body = {"model": "deepseek-chat", "temperature": 0, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": sysmsg}, {"role": "user", "content": question}]}
    r = subprocess.run(["curl", "-s", "-m", "120", "https://api.deepseek.com/chat/completions",
                        "-H", f"Authorization: Bearer {key}", "-H", "Content-Type: application/json",
                        "-d", json.dumps(body)], capture_output=True, text=True)
    return json.loads(json.loads(r.stdout)["choices"][0]["message"]["content"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--init")
    ap.add_argument("--ask")
    args = ap.parse_args()
    model = load_yaml(MODEL)
    if args.init:
        init_db(args.init)
        return
    if not args.ask:
        print(__doc__); sys.exit(2)
    catalog = json.dumps({k: {n: v.get("caliber", v.get("desc")) for n, v in model.get(k, {}).items()}
                          for k in ("dimensions", "measures", "metrics")}, ensure_ascii=False, indent=1)
    plan = llm(catalog, args.ask)
    sql = plan["sql"].strip().rstrip(";")
    if not re.match(r"(?is)^SELECT\s.+$", sql) or ";" in sql:
        sys.exit(f"护栏：仅允许单条 SELECT，拒绝：{sql[:120]}")
    con = sqlite3.connect(DB)
    try:
        try:
            rows = con.execute(sql).fetchall()
        except sqlite3.OperationalError as e:
            # 语法错回带错误重试一次（语义层自愈）
            plan = llm(catalog, f"{args.ask}\n\n上次生成的 SQL 执行报错：{e}\n请修正后重新输出。")
            sql = plan["sql"].strip().rstrip(";")
            if not re.match(r"(?is)^SELECT\s.+$", sql) or ";" in sql:
                sys.exit(f"护栏：仅允许单条 SELECT，拒绝：{sql[:120]}")
            rows = con.execute(sql).fetchall()
        cols = [d[0] for d in con.execute(sql).description]
    finally:
        con.close()
    print(f"## 问数：{args.ask}\n")
    print(f"```sql\n{sql}\n```\n")
    print("| " + " | ".join(cols) + " |")
    print("|" + "---|" * len(cols))
    for r in rows[:12]:
        print("| " + " | ".join(f"{v:.6g}" if isinstance(v, float) else str(v) for v in r) + " |")
    print("\n## 口径随行（本次引用的指标定义）")
    for m in plan.get("metrics_used", []):
        meta = model.get("metrics", {}).get(m) or model.get("measures", {}).get(m)
        if meta:
            print(f"- **{m}**: {meta.get('caliber') or meta.get('desc')}")
    print(f"\n---\n*engine: semantic-ask v0 · SQLite 单条 SELECT 护栏 · 口径版本随 semantic/models.yaml · {dt.datetime.now().isoformat(timespec='seconds')}*")


if __name__ == "__main__":
    main()
