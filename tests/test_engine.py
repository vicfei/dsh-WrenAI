#!/usr/bin/env python3
"""Hermetic engine tests — no LLM, no network, no database server.
Run: python3 tests/test_engine.py   (exits non-zero on any FAIL)"""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ask, pgwire

FAILS = []


def check(name, cond):
    print(("PASS" if cond else "FAIL"), name)
    if not cond:
        FAILS.append(name)


# 1. quote-aware inline splitter
parts = ask._split_inline('a: 1, b: "x, y", c: 3')
check("split_inline respects quotes", len(parts) == 3 and parts[1] == 'b: "x, y"')

# 2. demo model parses; commas survive inside quoted calibers
m = ask.load_yaml(ask.MODEL)
check("demo caliber intact (comma survival)", "no mean-centering" in m["metrics"]["vol_30d_ann"]["caliber"])
check("demo dimensions", set(m["dimensions"]) == {"date", "symbol"})
check("demo view target", m.get("view") == "v_metrics")

# 3. weknora preset parses fully
w = ask.load_yaml(os.path.join(os.path.dirname(ask.MODEL), "weknora.yaml"))
check("weknora tables", set(w["tables"]) == {"knowledge_bases", "knowledges", "chunks", "sessions", "messages", "audit_logs"})
check("weknora join paths", {"kb_documents", "document_chunks", "session_messages", "kb_retrieval_usage"} <= set(w.get("joins", {})))
check("weknora id-type fact rides along", "varchar(36)" in w["joins"]["id_types"])
check("weknora honest caliber", "write-side" in w["metrics"]["kb_query_events"]["caliber"])
check("weknora metric count", len(w["metrics"]) == 6)

# 4. single-SELECT guard (strict: WITH is rejected too — data-modifying CTEs exist in PG)
check("guard accepts SELECT", ask.guarded("  SELECT 1 ; ") == "SELECT 1")
for bad in ("DELETE FROM x", "UPDATE x SET a=1", "INSERT INTO x VALUES (1)",
            "SELECT 1; DROP TABLE x", "WITH t AS (SELECT 1) SELECT * FROM t"):
    try:
        ask.guarded(bad)
        check("guard rejects %r" % bad[:24], False)
    except ValueError:
        check("guard rejects %r" % bad[:24], True)

# 5. pgwire DSN parsing (no server touched)
p = pgwire.parse_dsn("postgresql://u:p%40ss@db.example.com:5433/mydb?sslmode=require")
check("dsn decodes + defaults", p["user"] == "u" and p["password"] == "p@ss" and p["host"] == "db.example.com"
      and p["port"] == 5433 and p["database"] == "mydb" and p["sslmode"] == "require")
for bad_dsn in ("postgresql://u:p@h/db?sslmode=verify-full", "mysql://x"):
    try:
        pgwire.parse_dsn(bad_dsn)
        check("dsn rejects %s" % bad_dsn[:40], False)
    except pgwire.PGError:
        check("dsn rejects %s" % bad_dsn[:40], True)
check("dsn defaults sslmode=disable", pgwire.parse_dsn("postgresql://u:p@h/db")["sslmode"] == "disable")

# 6. display formatting
check("fmt compresses numeric strings", ask.fmt("75870.2341") == "75870.2")
check("fmt None → empty", ask.fmt(None) == "")
check("fmt date passthrough", ask.fmt("2026-11-19") == "2026-11-19")
check("fmt int", ask.fmt(42) == "42")

# 7. --weknora DSN resolution: container-internal host → loopback, password percent-encoded
with tempfile.TemporaryDirectory() as wk:
    open(os.path.join(wk, ".env"), "w").write(
        "DB_HOST=postgres\nDB_PORT=5432\nDB_USER=postgres\nDB_PASSWORD=p@ss!word\nDB_NAME=WeKnora\n")
    os.environ["WEKNORA_HOME"] = wk
    dsn = ask.weknora_dsn()
    check("weknora_dsn maps host + encodes password",
          dsn == "postgresql://postgres:p%40ss%21word@127.0.0.1:5432/WeKnora")
    del os.environ["WEKNORA_HOME"]

# 8. intranet LLM config: env overrides with sane defaults
for k in ("WREN_LLM_BASE_URL", "WREN_LLM_MODEL", "WREN_LLM_API_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(k, None)
check("default llm url", ask._llm_url() == "https://api.deepseek.com/chat/completions")
check("default llm model", ask._llm_model() == "deepseek-chat")
os.environ["WREN_LLM_BASE_URL"] = "http://10.0.0.5:8000/v1/"
check("intranet base url joins path", ask._llm_url() == "http://10.0.0.5:8000/v1/chat/completions")
os.environ["WREN_LLM_MODEL"] = "deepseek-v3-intranet"
check("intranet model override", ask._llm_model() == "deepseek-v3-intranet")
os.environ["WREN_LLM_API_KEY"] = "dummy"
check("key env precedence", ask._llm_key() == "dummy")
os.environ["DEEPSEEK_API_KEY"] = "real"
check("WREN key beats DEEPSEEK env", ask._llm_key() == "dummy")
for k in ("WREN_LLM_BASE_URL", "WREN_LLM_MODEL", "WREN_LLM_API_KEY", "DEEPSEEK_API_KEY"):
    os.environ.pop(k, None)

print("result:", "GREEN" if not FAILS else "RED (%d)" % len(FAILS))
sys.exit(1 if FAILS else 0)
