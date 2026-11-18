# PR body（提交 awesome-dsh-plugin 用——owner 发布 npm 0.1.0 后执行）

**Adds vicfei/dsh-WrenAI — self-hosted semantic layer with calibers-riding results (tools)**

One file added: `data/plugins/vicfei__dsh-WrenAI--npm.yml`.

- Install: `dsh plugin add dsh-wrenai` (npm 0.1.0; declares `dsh.bundle` +
  `cordis.patch.yml`; skill `skills/dsh-wrenai/SKILL.md` + `dsh-wrenai` CLI
  that spawns the bundled stdlib-only Python engine)
- What it does: natural-language data questions where **every number carries
  its metric caliber** — the LLM sees only the semantic catalog (dimensions/
  measures/metrics with versioned definitions), emits one SELECT behind a
  deterministic single-statement guard with self-heal retry, and the caliber
  statements ride with the result. That is the line between governed analytics
  and raw text-to-SQL.
- The headline feature: `--weknora` — zero-config bridge to a WeKnora
  deployment's own PostgreSQL (DSN from `~/WeKnora/.env`). "How many times was
  the test KB queried this month?" answers from live data, with the caliber
  honestly stating it counts retrieval-cited answers (WeKnora's audit log
  records write-side actions only). Verified against hand-written SQL on a
  live dev deployment.
- Zero-dependency PostgreSQL support: `scripts/pgwire.py` is a clean-room
  frontend wire-protocol v3 client (SCRAM-SHA-256 with server-signature
  verification, MD5, cleartext, optional TLS) — the whole kit stays
  stdlib-only Python + a Node shim.
- Real working code: hermetic test suite + CI green; MIT; concept credit to
  WrenAI (Canner, multi-licensed, core Apache-2.0) with explicit clean-room
  non-affiliation.

PR 执行命令（owner 在 npm 0.1.0 发布后跑）：

```bash
cd /tmp && git clone --depth 1 git@ssh.github.com:vicfei/awesome-dsh-plugin.git && cd awesome-dsh-plugin
git checkout -b add-dsh-wrenai
cp ~/dsh-wrenai/docs/marketplace-submission/vicfei__dsh-WrenAI--npm.yml data/plugins/
git add data/plugins/vicfei__dsh-WrenAI--npm.yml
git commit -m "Add vicfei/dsh-WrenAI (self-hosted semantic layer, calibers ride with results)"
git push -f origin add-dsh-wrenai
# 开 PR：base awesome-dsh-plugin/awesome-dsh-plugin ← vicfei:add-dsh-wrenai，body 用上文
```

> 备选渠道（同一投稿件可复用）：0xsline/awesome-deepseek-harness（1.4k★）、
> polang233/dsh-plugin-index（256★）——主渠道过审后再补。
