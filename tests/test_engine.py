#!/usr/bin/env python3
"""Hermetic engine tests — no LLM, no network, no database server.
Run: python3 tests/test_engine.py   (exits non-zero on any FAIL)"""
import os, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import ask, pgwire
import model as modelkit

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

# 9. model lifecycle (issue #15): blacklist + type normalization
check("blacklist drops internals", modelkit.internal("schema_migrations") and modelkit.internal("task_pending_ops")
      and modelkit.internal("task_dead_letters") and modelkit.internal("organization_members_pre_plan3")
      and modelkit.internal("spatial_ref_sys"))
check("blacklist keeps domain tables", not (modelkit.internal("automations") or modelkit.internal("automation_runs")
      or modelkit.internal("messages")))
check("types normalize compact",
      modelkit.type_name("character varying", 36, "varchar") == "varchar(36)"
      and modelkit.type_name("character varying", None, "varchar") == "varchar"
      and modelkit.type_name("timestamp without time zone", None, "timestamp") == "timestamp"
      and modelkit.type_name("ARRAY", None, "_int4") == "int4[]"
      and modelkit.type_name("numeric", None, "numeric") == "numeric")

CAT = modelkit.build_catalog(
    [("messages",), ("sessions",), ("chunks",), ("schema_migrations",), ("task_pending_ops",)],
    [("messages", "id", "varchar", "character varying", 36),
     ("messages", "session_id", "varchar", "character varying", 36),
     ("messages", "role", "varchar", "character varying", 16),
     ("messages", "knowledge_references", "jsonb", "jsonb", None),
     ("sessions", "id", "varchar", "character varying", 36),
     ("sessions", "kind", "varchar", "character varying", 16),
     ("chunks", "id", "varchar", "character varying", 36),
     ("schema_migrations", "id", "int4", "integer", None)],
    [("messages", "id"), ("sessions", "id"), ("chunks", "id"), ("schema_migrations", "id")],
    [("msgs_session_fk", "messages", "session_id", "sessions", "id"),
     ("orphan_fk", "messages", "kb_id", "schema_migrations", "id")],
)
check("build_catalog blacklists internals", set(CAT["tables"]) == {"messages", "sessions", "chunks"} and CAT["hidden"] == 2)
check("build_catalog keys from PK", all(CAT["tables"][x]["key"] == "id" for x in CAT["tables"]))
check("fk_edges keeps only surviving endpoints",
      modelkit.fk_edges(CAT) == [("fk_messages_session_id__sessions", "messages.session_id = sessions.id")])

skel = modelkit.skeleton_yaml(CAT, "WeKnora")
check("skeleton discloses no-calibers", any("no calibers ride" in l for l in skel.splitlines()))
with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as f:
    f.write(skel)
    skelpath = f.name
parsed = ask.load_yaml(skelpath)
os.unlink(skelpath)
check("skeleton round-trips through load_yaml",
      set(parsed["tables"]) == {"messages", "sessions", "chunks"}
      and parsed["tables"]["messages"]["key"] == "id"
      and parsed["joins"]["fk_messages_session_id__sessions"] == "messages.session_id = sessions.id")
check("skeleton cols re-parse to typed pairs",
      modelkit.parse_cols(parsed["tables"]["messages"]["cols"]) ==
      [("id", "varchar(36)"), ("session_id", "varchar(36)"), ("role", "varchar(16)"), ("knowledge_references", "jsonb")])
check("parse_cols bare names (hand-written)", modelkit.parse_cols("id, session_id, role") == [("id", None), ("session_id", None), ("role", None)])

# 10. drift accounting (issue #15): drift = broken model claims only
hand = {"dataset": "weknora_ops", "tables": {
    "messages": {"key": "id", "cols": "id, session_id, gone_col"},
    "sessions": {"key": "id", "cols": "id, kind"},
    "ghost": {"key": "id", "cols": "id"},
}}
findings, new_cols, unmodeled, n_cols = modelkit.drift(hand, CAT)
ftext = " | ".join(findings)
check("drift: dropped table", "ghost" in ftext)
check("drift: dropped column", "messages.gone_col" in ftext)
check("new columns are info, not drift", new_cols.get("messages") == ["role", "knowledge_references"]
      and not any("knowledge_references" in f for f in findings))
check("drift: unmodeled is info, not drift", unmodeled == ["chunks"] and not any("chunks" in f for f in findings))
check("drift: bare names compare name-only (no type diff)", "type changed" not in ftext)
typed = {"tables": {"messages": {"key": "id", "cols": "id uuid, session_id varchar(36)"}}}
f2, _, _, _ = modelkit.drift(typed, CAT)
f2text = " ".join(f2)
check("drift: type change caught (varchar vs uuid hazard)", "type changed" in f2text and "uuid" in f2text)
report, has_drift = modelkit.check_report(hand, CAT, "test.yaml", "postgresql://u:p@127.0.0.1:5432/WeKnora")
check("check_report flags drift + exit code", has_drift and "RESULT: DRIFT" in report and "chunks" in report
      and "messages: +role, +knowledge_references" in report)
clean = {"tables": dict((k, {"key": v["key"],
                             "cols": ", ".join("%s %s" % (c, ty) if ty else c for c, ty in v["cols"])})
                        for k, v in CAT["tables"].items())}
r2, d2 = modelkit.check_report(clean, CAT, "skel.yaml", "postgresql://u:p@127.0.0.1:5432/WeKnora")
check("check_report clean on self-generated model", not d2 and "RESULT: clean" in r2)

# 11. model-scope guard (issue #16): unmodeled tables must not execute
W6 = set(w["tables"])
flagship = ("SELECT count(*) FROM messages m "
            "JOIN LATERAL jsonb_array_elements(messages.knowledge_references) ref ON TRUE "
            "JOIN chunks ON chunks.id = ref->>'id' WHERE m.deleted_at IS NULL")
check("table_refs extracts flagship citation path", ask.table_refs(flagship) == {"messages", "chunks"})
check("table_refs handles comma lists + schema + quotes + subqueries",
      ask.table_refs('SELECT * FROM public.knowledge_bases kb, "chunks" c '
                     'WHERE x IN (SELECT id FROM audit_logs)') == {"knowledge_bases", "chunks", "audit_logs"})
check("table_refs skips set-returning funcs and comments",
      ask.table_refs("SELECT * FROM sessions, generate_series(1,10) g -- FROM task_pending_ops"
                     " /* FROM automations */") == {"sessions"})
try:
    ask.scoped("SELECT count(*) FROM automations", W6)
    check("scope rejects unmodeled table", False)
except ValueError as e:
    check("scope rejects unmodeled table", "automations" in str(e) and "modeled" in str(e))
check("scope accepts all-modeled flagship SQL", ask.scoped(flagship, W6).startswith("SELECT"))
check("scope skipped without a tables model", ask.scoped("SELECT 1", None) == "SELECT 1")
try:
    ask.scoped("SELECT 1; DROP TABLE x", W6)
    check("scope still rejects multi-statement first", False)
except ValueError as e:
    check("scope still rejects multi-statement first", "single SELECT" in str(e))

print("result:", "GREEN" if not FAILS else "RED (%d)" % len(FAILS))
sys.exit(1 if FAILS else 0)
