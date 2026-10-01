# 预研报告：Hermes agent 记忆系统对照与 M3 先决文档补强（2026-10-01）

Status: 预研结论 + 文档增量已落地（见 §7 变更清单）；DECISIONS 草案待 A/B 签认。

> **协调人归档注记（2026-10-01）**：本报告在陈旧检出（PR #16 之前）上完成，
> §7 所称「已落地」的文档增量当时仅存在于本地未跟踪文件，且隐私文档使用了
> 与仓库不同的文件名（`m3-materials-privacy-decision.md` → 仓库为
> `m3-course-materials-privacy.md`）。协调人已将增量调和移植到 main 现行版
> （含 B 评审修订）：迁移方案补遥测两列/阻断串行化/键型登记/易错点/验收；
> 隐私决策补第 6 条决策 + §5 内容安全扫描 + downloadUrl 排除。两处分歧以
> main 评审版为准：`supersedes_id` 用 SET NULL（预研原案 RESTRICT 不采）；
> `correction_status` 语义端点化作为开放问题路由至迁移方案 §8 待签认。
> 决策编号勘正：本报告「D-031（草案）」编号与已冻结的 M2 契约决策撞号，
> 登记为 **D-032**。
基线：main `ca17169`（D-001~D-030）。研究对象：NousResearch/hermes-agent
（MIT，~250k stars），依据其官方文档 `website/docs/user-guide/features/` 下的
`memory.md`、`skills.md`、`curator.md`（sparse clone 逐行核实，关键条目均已
对到原文行号；本地 clone 在临时目录，不作为持久资料引用）。

关联文档：`TASKS/m3-memory-schema-migration.md`、
`TASKS/m3-course-materials-privacy.md`（2026-09-30 产出，本轮补强；文件名按仓库现行版勘正）。

## 1. Hermes 记忆系统的技术事实

Hermes 的记忆是**给模型用的文件式上下文记忆**，为单机、单用户、上下文窗口
即全部记忆的对话 Agent 优化。四个子系统：

### 1.1 常驻记忆（MEMORY.md / USER.md）

- 两个平面文件：agent 笔记（`memory_char_limit: 2200`，约 800 token）与用户
  画像（`user_char_limit: 1375`，约 500 token）。**无 read 工具**——记忆即
  上下文，不是被查询的资源。
- **冻结快照模式**：会话开始时一次性渲染进 system prompt，会话中不再变化
  （写盘即时，但下次会话才进 prompt）。设计动机是保 LLM prefix cache；为此
  它要求消息平台上在自然边界主动 `/new`，否则"忘→忆→检索"学习环永远不触发。
- **容量治理无自动压缩**：超限写入直接报错并附 `current_entries`，逼 agent
  在同一回合内 consolidate（replace 合并）或 remove 后重试。

### 1.2 写入路径与安全

- `memory` 工具三个动作：add / replace / remove。replace 以唯一子串匹配定位
  后**整条覆盖**（精确全条匹配优先于子串匹配）；重复条目拒绝。
- 写入前扫描：注入/外泄模式（prompt injection、凭据外泄、SSH 后门）hard
  block，不可见 Unicode 阻断——因为内容会被注入 system prompt。
- `memory.write_approval: true` 时所有写入（前台、消息平台、后台自审）进入
  暂存审批：`/memory pending|approve|reject`；**暂存的 replace/remove 钉住
  目标条目全文，落地时若目标已变则拒绝**（乐观锁语义）。
- 写入者两个：对话中的 agent（常主动记偏好/纠正/约定）+ 每 turn 后 fork 的
  **后台自审**（默认同主模型以复用 prompt cache 前缀，可路由便宜 aux 模型；
  `max_input_tokens` 默认取上下文窗口 75%、上限 600k；可 defer 到 GPU 空闲）。

### 1.3 会话检索（与常驻记忆分工）

- SQLite FTS5 全文索引所有会话原文（~20ms、~1ms 滚动、零 LLM 成本），含
  CJK 分词原生组件。
- 分工原则原文：「记忆放永真事实，检索找具体往事」——两种需求两种机制，
  会话检索**不做摘要**，返回存储的消息原文。

### 1.4 过程性记忆（skills）与 curator

- Skills = 按需加载的知识文档，三级渐进披露（list ~3k token → SKILL.md →
  references/ 具体文件）；`skill_manage` 工具 create/patch/delete；三个形状
  linter（incident-log-shape / references-sprawl / oversized-body）只警告不
  阻断。
- Curator（后台维护）：确定性生命周期 14 天 stale → 30 天 archived，**永不
  自动删除**（最坏可恢复归档）；LLM 归并（umbrella 合并）**默认关**，一次
  全量 50–100 次 API 调用。pin 与 cron 引用豁免。
- **审计账本**：JSONL 追加，每 mutation 记 actor（curator/agent/user）、
  action、before/after 按文件 sha256 内容寻址去重存储；支持整树快照回滚与
  **单次 mutation 回滚**；账本 5MB 上限自动压缩；「账本是遥测不是门」——
  写失败 mutation 照常执行。
- **provenance 是政策标志不是作者声明**：`created_by` 实际语义是「允许自治
  维护吗」，手工写的 skill 永不进入 curator 管辖，adopt 是显式声明而非推断
  （「上千次 patch 证明 agent 维护它，不证明 agent 写了它」）。

### 1.5 单机假设（对 §5 的可行性结论最关键）

memory.md 原文：两个 agent 进程**绝不共享一个 Hermes home**，并发写会产出
"无主状态"；共享记忆要走外部 provider。多 profile = 同机多目录。无多用户、
无服务端身份、无跨设备同步。

## 2. 与 agenthu 记忆设计的对照判定

| Hermes 机制 | agenthu 对应 | 判定 |
| --- | --- | --- |
| 注入/外泄扫描写入内容 | 无 | **真欠缺 → 已补进隐私决策 §3.5** |
| 使用遥测（use/view/patch 计数） | 无（M4 context snapshot 隐含一半） | **真欠缺 → 已补进迁移方案第一刀** |
| 会话原文 FTS 检索 | 无（Chat 未建） | 记账 M4：PG tsvector 即可，无需新基础设施；其"检索不做摘要"原则采纳 |
| 过期/衰变生命周期 | `valid_to` 只覆盖"被修正"，不覆盖"过时" | 记账 M5/M8（worker 确定性衰变 pass） |
| 过程性记忆（skills 自改进） | L2 habit/preference 占一角 | 推迟 M8+ |
| 写入审批 staging | UNREVIEWED + 检索过滤 | 等价且更适合事实型记忆，不引入；其"暂存钉住目标条目"的乐观锁细节可借鉴 |
| 硬字符上限逼合并 | subject_key upsert 结构性防重 + M4 token 预算 | 已覆盖 |
| 冻结快照进 prompt | M4 context snapshot（CurrentState 版本 + memory ids） | 设计同构，互相印证；M4 实现参考其对**前缀稳定排序**的处理 |
| 记忆条目本身 | L0 事实层、provenance、置信度、版本链、REJECTED 阻断、checksum 证据锚点 | **我们独有**，且是 AGENTS §2.3 的硬要求——Hermes 无来源无置信度的文本条目正是其禁止形态 |
| 多用户/跨设备/审计 | Backend 事实源 + 权限 0–3 + audit | 我们独有，Hermes 架构无此概念 |

一句话：Hermes 验证可靠的是 **LLM 管线**（provider 路由/工具调用/压缩/子
agent）——恰是我们 M4 里最薄的一层；它没有的是我们的承重结构（事件管线、
多用户、结构化记忆、确定性 planner、校园适配链）。

## 3. 欠缺一：内容安全扫描（已落地隐私决策 §3.5）

威胁模型：M3 把课程 PDF/PPT 抽取的 chunk 送进检索与 LLM 上下文，恶意构造的
课件（或被投毒的转写）是现成 prompt injection 载体。现有 D-012 只在 Event
摄取拒绝 credential 形态的**键**，不扫描将进 prompt 的**内容**。

三层防线（详细口径见隐私决策文档）：

1. 入库扫描：指令形态 hard block；不可见 Unicode 只 flag + 归一化重扫
   （**误报是主要风险**：正常 PDF 文本层抽取常见零宽/连字产物）；规则数据
   文件化 + `scanner_version` 落 chunk 元数据。
2. 上下文装配隔离（M4）：检索片段分隔符包裹 + 标注不可信。
3. 机械引用校验：引文必须能在被引 chunk 归一化后找到，失败降级"未落地"。

## 4. 欠缺二：记忆使用遥测（已落地迁移方案第一刀）

- DDL：`use_count INTEGER NOT NULL DEFAULT 0`、`last_used_at timestamptz NULL`。
- 语义：只记「**进入决策上下文**」（M2 planner 检索 L2 估时行、M4 上下文
  装配两个写入点），不记「被候选检索」；M2 批末去抖重算不得重复计数。
- 权威账本是 M4 `agent_runs` 的 context snapshot（memory id 列表），两列只是
  可展示缓存——比 Hermes 的「被看过」更强，我们记的是「参与决策」。
- 用户可见性：Memory 页展示"这条事实参与过 N 次计划决策"；为 M5/M8 的
  效用计算与衰变提供数据。

## 5. 「基于 Hermes 构建」可行性结论

**不建议作为底座；采纳其设计而非其内核。** 技术依据（详细对照见会话记录，
此处存档结论）：

1. **单机单用户是硬边界**（§1.5 原文），与 AGENTS §2.2「Backend 是跨设备
   事实源」根本冲突；多用户内测（M5）无落点。
2. 权限是进程级配置开关，无法落成「数据化的 Level 0–3 + pending_actions +
   服务端审计」。
3. 记忆模型冲突（无溯源文本 vs 结构化可修正），并存即双脑：两套记忆/触发/
   权限，basis 的解释权分裂。
4. 交互面（CLI/TUI/消息平台）映射不了 Focus 工作台、离线队列、课表视图；
   Android 无 Hermes 形态。
5. 校园凭据 custody 会从 Rust + Stronghold 边界退化为进程 env/文件——
   五轮验收换来的隐私边界回归。
6. fork 维护成本：46k commits 高速上游；vendor 固定版错过修复、跟踪则持续
   rebase 改过内核的 fork（OneTHU vendor 之苦的平方）。

**采纳的形式**：M4 实现 provider adapter、工具注册表、冻结快照时以其源码为
参考实现对照（届时重新 sparse clone 并钉 commit）；M4 之后可 timebox 一个
**可选 chat surface 实验**（Hermes 经 MCP 调 `/v1` API，不承重、不进主线）。

### D-032（草案，原报告误编 D-031）— 不基于 Hermes agent 构建，采设计不采底座

Status: draft（待 A/B 签认后正式登记）。Context：Hermes（MIT）作为成熟对话
Agent harness 被评估为潜在底座；其单机单 home、文件记忆、进程级权限与本项目
冻结边界（AGENTS §2.2/§2.3/§4）冲突，见上 6 条。Decision：维持现架构；
采纳其可迁移机制（冻结快照、写入前注入扫描、使用遥测、provenance 即政策）；
Hermes 仅可作为 M4 后的可选 chat surface 实验。Revisit 条件：产品转向单机
优先（放弃多用户与多端同步），或 M4 provider/agent 工作连续两个里程碑停滞。

## 6. 容易出错的加强点（汇总）

**Memory schema 第一刀**（细节已写入迁移方案文档）：

1. **阻断语义不在唯一索引里**：部分唯一索引排除了 REJECTED 行，阻断只能由
   服务层表达。`upsert_memory` 必须同事务 `SELECT ... FOR UPDATE` 锁
   `(user_id, subject_key)` 存续行再查阻断——否则 upsert/reject 并发会写出
   已拒主题的新行。
2. **kind 列三步顺序**：加列(NULL) → 按 level 回填 → 加 CHECK + NOT NULL；
   颠倒在存量行上失败；`alembic check` + up→down→up 必跑。
3. **版本链删除语义**：`supersedes_id` FK 用 RESTRICT；服务层规则「版本化行
   只删最新版或闭链保留」；否则链中硬删断链丢审计史。
4. **correction_status 移出 MemoryCreate 是破坏性契约变更**：tests、fixtures、
   OpenAPI、冻结快照、e2e 中直接 PATCH status 的用例必须同批改为语义端点
   （confirm/correct/reject）。
5. **use_count 计数点**：只记决策装配；批内重算不重复计数；M4 前列只是
   缓存，别在检索预览路径上递增。

**Grounding / 隐私**（细节已写入隐私决策文档）：

6. **不可见 Unicode 误报**是入库扫描的主要风险：分层处理（指令 hard block /
   不可见字符 flag+归一化重扫），别一刀切。
7. **文件删除顺序必须改**：现状先删对象后删行；加 chunk 后先事务内删关系行
   + 状态标记，对象 best-effort + 孤儿清理，否则失败中间态留下"对象已删但
   chunk 仍可检索"，直接破坏隐私决策表的删除承诺。
8. **扫描规则要版本化**：`scanner_version` 落 chunk 元数据，否则无法追溯
   "这批 chunk 是哪版规则扫的"。
9. **对抗 fixture 必须有**：含注入指令的自造 PDF 进回归，断言被 flag——
   没有对抗样本的扫描等于没写。
10. **`downloadUrl` 不进 Event**（已在隐私决策 §2）：会话态 URL 携带认证
    参数，撞 D-012 且是最小化采集违例。

**工程协作**：

11. **multi-head**：Memory 第一刀与 M2 planner/估时迁移并行线，开工前冻结
    顺序，后开工方 rebase。
12. **本地 Hermes clone 在临时目录**：会被系统清理，本报告已固化技术结论；
    M4 需要对照源码时重新 sparse clone 并钉 commit，勿引用临时路径。

## 7. 本轮文档变更清单

- `TASKS/m3-memory-schema-migration.md`：第一刀 DDL 增使用遥测两列（含计数
  点语义）、验收项、新增「易错点」三条（竞态/迁移顺序/版本链删除）。
  （协调人注：增量已调和移植进 main 现行版；RESTRICT 原案与评审版 SET NULL
  冲突，以评审版为准。）
- `TASKS/m3-course-materials-privacy.md`（文件名勘正）：决策清单第 6 条 +
  §5 内容安全扫描（三层防线 + 版本化 + 对抗 fixture）；删除顺序改序要求
  已并入 §5（现状先删对象后删行，代码已核实 `files.py:146-147`）。
- 本报告：Hermes 技术事实存档（§1）、对照判定（§2）、D-031 草案（§5）、
  加强点汇总（§6）。

## 8. 下一步

1. A/B 签认两份 M3 先决文档 + D-031 草案（连同 2026-09-30 的四项拍板：
   迁移两刀、pgvector 两刀、模型外发默认关显式开启、长期保留+手动删除）。
2. M2 任务文件立项时，Memory 第一刀迁移排最前（估时学习与 Memory 页原型
   都依赖它）。
3. M4 立项时，从本报告 §2 的"记账 M4"两条（会话 FTS、前缀稳定排序）与
   Hermes 参考实现对照清单开工。
