# dsh-WrenAI — DeepSeek Harness 的自托管语义层

**自然语言问数，数字带着指标口径一起回来。** 语义模型（维度/度量/指标+口径）
站在问题与 SQL 之间——这就是受治理的数据问数与裸 text-to-SQL 的分界线。

[English](README.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/vicfei/dsh-WrenAI/actions/workflows/ci.yml/badge.svg)](https://github.com/vicfei/dsh-WrenAI/actions/workflows/ci.yml)
[![npm](https://img.shields.io/npm/v/dsh-wrenai)](https://www.npmjs.com/package/dsh-wrenai)
[![License: MIT](https://img.shields.io/badge/license-MIT-3da639)](LICENSE)
[![Python](https://img.shields.io/badge/engine-Python%20stdlib%20only%20%2B%20Node%20shim-3776ab)](README.zh-CN.md#安装)
[![Concept: WrenAI](https://img.shields.io/badge/concept-WrenAI%20%28core%20Apache--2.0%29-35a7a0)](https://github.com/Canner/WrenAI)

> 原生实现 [WrenAI](https://github.com/Canner/WrenAI)（18.3k★ —— GenBI / 受治理
> text-to-SQL）的差异核心，面向 [DeepSeek Harness](https://github.com/deepseek-ai)：
> **自托管语义层**。净室实现，零上游代码关系，无隶属。
> 家族：12 仓量化栈 —— [dsh-TradingAgents](https://github.com/vicfei/dsh-TradingAgents) ·
> [dsh-OpenBB](https://github.com/vicfei/dsh-OpenBB) ·
> [dsh-CCXT](https://github.com/vicfei/dsh-CCXT) ·
> [dsh-quantstats](https://github.com/vicfei/dsh-quantstats) ·
> [dsh-freqtrade](https://github.com/vicfei/dsh-freqtrade) …

## 头条特性：问你的 WeKnora 任何事

[WeKnora](https://github.com/WeKnora/WeKnora)（自托管 RAG 平台）没有自我可观测性：
审计日志**只记写侧动作**，"这个知识库到底被用了多少次？"在 UI 里无法回答。
dsh-WrenAI 直连部署的 PostgreSQL——零配置，DSN 从 `~/WeKnora/.env` 解析——
用预置的受治理模型作答，并附上诚实口径：

```bash
dsh-wrenai --weknora --ask "how many times was the test knowledge base queried in the past month?"
```

```text
## Ask: how many times was the test knowledge base queried in the past month?
| kb_query_events |
|-----------------|
| 2               |
## Calibers riding with this result (metric definitions used)
- kb_query_events: DISTINCT COUNT of assistant messages citing at least one
  chunk of the KB in the time window … HONEST LIMIT: WeKnora audit_logs record
  write-side actions only, so retrieval usage is measured by citations
  actually served — this counts questions whose answers cited the KB, not raw
  retrieval calls.
```

（真实 dev 部署，2026-11-19；已与手写 SQL 对账。）`kb_query_events`（去重问题数）
与 `kb_citations`（引用出现次数）是同一 join 路径上的两个口径——"本季度哪些库被引用
最多？"会把两者并排列出（live dev 机上 hotpot-pool-500：1287 事件 / 34948 引用）。

## 模型生命周期：bootstrap 起骨架，--check 守诚实

对着 90 张表手写模型是苦役，而模型会随上游 schema 演进无声腐烂。两件确定性的事
现在都在引擎里——零 LLM，纯 stdlib：

```bash
dsh-wrenai --weknora --bootstrap > my-model.yaml      # 目录 -> 骨架（stdout）
dsh-wrenai --pg "postgresql://u:p@host:5432/db" --bootstrap > model.yaml   # 任意 PostgreSQL
dsh-wrenai --weknora --model my-model.yaml --check    # 模型 vs 活目录，漂移 exit 1
```

- **`--bootstrap`** 读 `information_schema`（public schema、基表；黑名单排除
  `schema_migrations` / `task_*` 等框架内部表），产出骨架：每表的列清单带紧凑类型、
  key 取目录 PK、joins **只收显式声明的外键**——不做命名约定猜测（错误的 join 边比
  缺失更糟）。骨架带硬披露：**无口径随行**——含义（维度/度量/指标）留给人类。产物
  可回灌：`--bootstrap > m.yaml` 直接进 `--check` 与 `--ask`。
- **`--check`** 列粒度对账模型 vs 活目录。**漂移 = 模型的声明失效**——表/列被删、
  列类型变更（`varchar(36)` vs `uuid` 这类血泪坑）——exit 1，可进 CI。活目录新增列与
  未建模表只算提示：刻意裁剪的部分模型只要声明仍成立就保持绿。dev 机首跑就抓到本仓
  自带 preset 声明的 `messages.tenant_id` 已被上游删除——修复随同一变更合入。

## DuckDB 后端：`--duckdb`

第三个执行后端，同样的护栏、同样的口径随行输出：

```bash
dsh-wrenai --duckdb mydata.duckdb --model my-model.yaml --ask "…"
dsh-wrenai --duckdb --model my-model.yaml --ask "…"        # :memory:，在 SQL 里读 parquet/csv
```

一次运行一个后端（`--pg` 与 `--duckdb` 二选一）。解析顺序每步都诚实：可 import 的
`duckdb` **Python 模块** → PATH 上的 `duckdb` **CLI** → 都没有就退出并点名两条路——
DuckDB 是调用方自带的可选后端，引擎本体保持零依赖（与 LLM key 同一姿态）。
DuckDB 自身异常折进引擎的统一错误类，自愈重试与诚实失败路径照常；`--ledger` 记
`backend: "duckdb"`，`--replay` 对当前后端重跑。

## 直接吃 WrenAI 生态模型：`--mdl` 原地导入

WrenAI 生态的模型文件本身就是合法模型源——不需要转换步骤：

```bash
dsh-wrenai --pg "postgresql://u:p@host:5432/db" --mdl my-model.mdl.json --ask "…"
dsh-wrenai --pg "postgresql://…" --mdl my-model.mdl.json --check   # 还能对活目录做漂移对账
```

`models[]` → 表（key 取 `primaryKeyName`）、`relationships[]` → join
（`{orders}.x = {customers}.y` 条件去掉花括号）、`metrics[]` → 指标，口径即 MDL
公式——并硬性披露**不带人工口径叙述**（MDL 载的是公式，不是口径）。计算列不是
物理列，不进 cols 行（否则会被当成漂移），改以携表达式的目录条目随行；导入时
列类型剥掉——MDL 类型是宽松声明，漂移对账比的是目录类型，留着会让每次导入
开箱即红；views 跳过并披露。仅支持 JSON MDL：那是 WrenAI UI 的导出交换格式。
下游全部照常——作用域守卫、`--check`、`--calibers`、`--ledger`、`--replay`。

## 口径可问责：定义带版本，问数留台账

纪律写着"指标定义的改动是升版本，不是原地改"——W3 把它变成机制，并让每次问数成为
一条只增不改的证据：

```bash
dsh-wrenai --model new.yaml --calibers --against old.yaml   # 口径漂移告警（零 LLM）
dsh-wrenai --weknora --ask "……" --ledger                    # 把这次问数记入台账（默认在模型旁）
dsh-wrenai --weknora --ledger-print 5                        # 最近 5 条记录
dsh-wrenai --weknora --replay wl_<id>                        # 现在重跑记录的 SQL，当时 vs 现在
```

- **`--calibers --against`** 确定性地对比两个模型的口径文本：口径变了而 `version:`
  没动 = **漂移，exit 1**（正是纪律禁止的原地改）；随文本一起升了版本 = 留痕的接替；
  新增/移除只提示。缺 `version:` 按 1 读，旧模型全部兼容。
- **`--ledger`** 把每次问数追加为一条 ndjson 事件：问题、最终 SQL、判定
  （ok / self_healed / failed——被拒也照记）、答案实际骑乘的指标版本、结果行
  （前 50 行，总数永远诚实）。一个模型一条台账，就在模型文件旁边。
- **`--replay <id>`** 用同样的护栏对着**当前**模型与后端重跑记录的 SQL，报告什么
  变了：变了的单元格、变了的口径版本。这就是活体形态的口径漂移告警——问一次，
  改一次定义，重放，看见同一问题在新口径版本下作答。

## 为什么（NL2SQL 插件已有——缺的是语义层）

| | 裸 NL2SQL 插件 | **dsh-WrenAI** |
|---|---|---|
| 模型看到什么 | 表结构 | **语义目录**——带口径的指标、带业务含义的维度 |
| 信任 | 靠信念 | **口径随行**：每个结果引用它实际使用的指标定义 |
| SQL 安全 | 参差 | **单条 SELECT 护栏+模型表域校验**+自愈重试，确定性执行 |
| 后端 | 通常一个 | **SQLite（stdlib）或 PostgreSQL**——零依赖 wire 客户端 |
| 自托管 | — | 完全本地（YAML 模型+你的库），无云服务，无 pip 安装 |

## 安装

```bash
npm i -g dsh-wrenai          # 或：dsh plugin add dsh-wrenai
dsh-wrenai --weknora --ask "how many times was the test knowledge base queried in the past month?"
```

需要 PATH 上有 `python3`——引擎**纯 stdlib**（无需 pip 安装）；npm 包是一个薄启动器
加 DSH 插件清单与技能。源码方式：clone 后直接 `python3 scripts/ask.py`。

## 快速开始（任意数据集）

```bash
git clone https://github.com/vicfei/dsh-WrenAI && cd dsh-wrenai
python3 scripts/ask.py --init <klines.json>          # 装载数据 + 建语义视图
python3 scripts/ask.py --ask "average close and annualized volatility over the last 30 days?"
```

真实冒烟（binance BTC/USDT 365d，2026-11-17）：*30 天均价 75,870 · 年化波动 36.7%*
——答案附带波动率指标的口径公式（`sqrt(252×mean(ret²))`，30 日滚动，声明了无均值
中心化的简化）。首次生成的 SQL 有语法错误，引擎靠错误反馈自愈重试通过。

输出英文优先；`--lang zh` 把用户可见标签切为中文。

## 工作原理

```
语义模型（YAML：维度/度量/指标 + 口径）
        │  LLM 只看这个目录——绝不看裸表结构
        ▼
单条 SELECT ── 确定性护栏（仅一条语句、仅 SELECT；带 tables 的模型还要求
        │      表引用不越出模型——未建模的表出数没有口径随行）
        │           └─ 护栏/执行错误 → 原因回带自愈重试一次
        ▼
数字 + 口径一起出（没有定义的数字即为 bug）
```

执行层可插拔：SQLite（默认，stdlib）或 PostgreSQL（`--pg "postgresql://…"` /
`--weknora`）。`scripts/pgwire.py` 是**零依赖**的 PostgreSQL wire 协议客户端
（SCRAM-SHA-256 含服务端签名校验、MD5、cleartext、可选 TLS）——依公开协议文档
净室实现，整套工具保持纯 stdlib Python 加一个 Node 启动器。

## 状态与路线图

v0.1——语义引擎、PG 后端、WeKnora 桥；hermetic 测试 + CI 绿。
[ROADMAP](ROADMAP.md)：M1 结果缓存；M2 MDL 风格模型兼容+DuckDB 后端。

## 许可与免责

MIT；概念致谢 WrenAI（上游多许可，core Apache-2.0）——零上游代码。
**非投资建议。**
