// dsh-wrenai host plugin — typed tools over the stdlib Python engine (issue #24).
// The bin shim precedent, proven across the family: every tool spawns
// scripts/ask.py with JSON-schema-typed parameters, so a harness agent calls
// the semantic layer without shelling out blind. Backends are exclusive by
// engine rule (pg XOR weknora XOR duckdb); env passes through untouched.
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const ENGINE = path.join(root, "scripts", "ask.py");

function run(args, timeoutMs) {
  const candidates = process.platform === "win32" ? ["python", "python3"] : ["python3", "python"];
  for (const py of candidates) {
    const r = spawnSync(py, [ENGINE, ...args], { encoding: "utf8", timeout: timeoutMs, maxBuffer: 16 * 1024 * 1024 });
    if (!r.error) {
      const out = (r.stdout || "") + (r.stderr ? `\n[stderr] ${r.stderr}` : "");
      // the engine's own error paths exit non-zero with the reason on stdout/stderr — surface it, don't hide it
      return { summary: out.trim() || `(no output, exit ${r.status})`, exit: r.status ?? 1 };
    }
  }
  throw new Error("dsh-wrenai: python3 not found on PATH (the engine is stdlib-only Python 3)");
}

function backendArgs(args) {
  const a = [];
  if (args.pg) a.push("--pg", String(args.pg));
  if (args.weknora) a.push("--weknora");
  if (args.duckdb !== undefined) a.push("--duckdb", String(args.duckdb ?? ":memory:"));
  const given = [args.pg, args.weknora, args.duckdb !== undefined].filter(Boolean).length;
  if (given > 1) throw new Error("one execution backend per call: pg, weknora or duckdb, not several");
  return a;
}

export const name = "dsh-wrenai";
export const inject = ["tools"];

export async function apply(ctx) {
  ctx.tools.register({
    name: "wren_ask",
    description:
      "Ask a natural-language data question through the self-hosted semantic layer: the model sees only the " +
      "semantic catalog (dimensions/measures/metrics with their calibers), emits one guarded SELECT, executes it " +
      "on the chosen backend, and the answer ships WITH the caliber statements of the metrics it used — never " +
      "numbers alone. Backends (pick exactly one): `pg` (PostgreSQL DSN), `weknora` (zero-config, reads " +
      "~/WeKnora/.env), or `duckdb` (a .duckdb file path or ':memory:'). Model source: a semantic YAML " +
      "(`model`), the WeKnora preset (`weknora`), or a WrenAI MDL JSON (`mdl`, imported in place with " +
      "metric formulas as calibers). Pass `ledger: true` to append the ask to the model's ledger as evidence. " +
      "Takes 5-120s (one LLM call, self-heal retry on executor error).",
    parameters: {
      type: "object",
      properties: {
        question: { type: "string", description: "The data question, e.g. 'how many documents per knowledge base, top 5?'" },
        pg: { type: "string", description: 'PostgreSQL DSN, e.g. "postgresql://user:pass@host:5432/db". Exclusive with weknora/duckdb.' },
        weknora: { type: "boolean", description: "Zero-config WeKnora preset (DSN from ~/WeKnora/.env, preset model). Exclusive with pg/duckdb." },
        duckdb: { type: "string", description: "DuckDB backend: a .duckdb file path or ':memory:'. Needs the duckdb module or CLI. Exclusive with pg/weknora." },
        model: { type: "string", description: "Semantic model YAML path (default: the demo model; with weknora: the preset)." },
        mdl: { type: "string", description: "WrenAI MDL JSON path — imported in place as the model source." },
        ledger: { type: "boolean", description: "Append this ask to the model's ledger (append-only evidence with verdict and metric versions)." },
        lang: { type: "string", enum: ["en", "zh"], description: "Output language (default en)." },
      },
      required: ["question"],
    },
    timeoutMs: 300_000,
    execute(args) {
      if (!args.question) throw new Error("wren_ask needs a question");
      const a = [...backendArgs(args)];
      if (args.model) a.push("--model", String(args.model));
      if (args.mdl) a.push("--mdl", String(args.mdl));
      if (args.ledger) a.push("--ledger");
      if (args.lang) a.push("--lang", args.lang);
      return run(["--ask", String(args.question), ...a], 300_000);
    },
  });

  ctx.tools.register({
    name: "wren_check",
    description:
      "Drift-account a semantic model against the live PostgreSQL catalog (deterministic, zero LLM): drift = the " +
      "model's claims are broken (dropped table/column, type changed) and exits non-zero; new catalog columns and " +
      "unmodeled tables are info, so curated partial models stay green. The release gate for model changes.",
    parameters: {
      type: "object",
      properties: {
        model: { type: "string", description: "Semantic model YAML path to check (or an imported MDL — pass mdl instead)." },
        mdl: { type: "string", description: "WrenAI MDL JSON path to import and check." },
        pg: { type: "string", description: "PostgreSQL DSN of the live catalog." },
        weknora: { type: "boolean", description: "Zero-config WeKnora catalog (DSN from ~/WeKnora/.env)." },
      },
      required: [],
    },
    timeoutMs: 60_000,
    execute(args) {
      const a = [...backendArgs(args)];
      if (args.model) a.push("--model", String(args.model));
      if (args.mdl) a.push("--mdl", String(args.mdl));
      return run(["--check", ...a], 60_000);
    },
  });

  ctx.tools.register({
    name: "wren_calibers",
    description:
      "Caliber-drift alarm between two model files (deterministic, zero LLM): a caliber text that changed while its " +
      "`version:` stayed put is DRIFT (exit non-zero) — the forbidden edit-in-place; a change that moved the " +
      "version is a recorded supersession. The gate that makes 'version bumps, not edits' mechanical.",
    parameters: {
      type: "object",
      properties: {
        model: { type: "string", description: "The NEW model YAML path (positional: --model)." },
        against: { type: "string", description: "The OLD model YAML path to diff against." },
        mdl: { type: "string", description: "The NEW model as a WrenAI MDL JSON path instead of YAML." },
      },
      required: ["against"],
    },
    timeoutMs: 60_000,
    execute(args) {
      if (!args.model && !args.mdl) throw new Error("wren_calibers needs the new model (model or mdl)");
      const a = ["--calibers", "--against", String(args.against)];
      if (args.model) a.push("--model", String(args.model));
      if (args.mdl) a.push("--mdl", String(args.mdl));
      return run(a, 60_000);
    },
  });

  ctx.tools.register({
    name: "wren_ledger",
    description:
      "The append-only ask ledger: `print` shows the last N recorded asks (question, verdict ok/self_healed/failed, " +
      "the metric versions each answer rode on); `replay` re-executes a recorded SQL through the same guards on the " +
      "current backend and reports what moved — changed cells, changed caliber versions (the same question across " +
      "model versions, side by side).",
    parameters: {
      type: "object",
      properties: {
        print: { type: "number", description: "Print the last N ledger entries." },
        replay: { type: "string", description: "A ledger entry id (wl_xxxxxxxx) to re-execute now." },
        ledger: { type: "string", description: "Ledger ndjson path (default: beside the model)." },
        model: { type: "string", description: "Model path (replay compares against its caliber versions)." },
        pg: { type: "string", description: "PostgreSQL DSN for replay re-execution." },
        weknora: { type: "boolean", description: "WeKnora preset backend for replay." },
        duckdb: { type: "string", description: "DuckDB backend for replay (path or ':memory:')." },
      },
      required: [],
    },
    timeoutMs: 120_000,
    execute(args) {
      if (args.print === undefined && !args.replay) throw new Error("wren_ledger needs print (a count) or replay (an id)");
      const a = [...backendArgs(args)];
      if (args.model) a.push("--model", String(args.model));
      if (args.ledger) a.push("--ledger", String(args.ledger));
      if (args.print !== undefined) a.push("--ledger-print", String(args.print));
      if (args.replay) a.push("--replay", String(args.replay));
      return run(a, 120_000);
    },
  });
}
