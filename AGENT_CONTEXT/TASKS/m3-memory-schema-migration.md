# M3 先决文档 1：Memory schema 迁移方案（含删除/依赖图设计）

状态：**A/B 双签**（A：rotcar07 2026-10-01；B：juefan-web 2026-10-01 会签
并裁定 §8 两项——superseded-by 方向勘误确认、correction_status 端点化采纳；
含 2026-10-01 协调人调和增量：遥测两列、FOR UPDATE 串行化、键型登记、
实现易错点三条）。**M2 切片已落地**（PR #18，迁移 `e52a9d3b1c48`：六列 +
遥测 + 版本感知部分唯一索引 + supersedes 反向链索引 + evidence GIN）。
**D-030 修订要求「M3 Memory schema 设计必须同步产出删除/依赖图设计」——
见 §6，这是本文档不可省略的部分。**

## 目标 / 输入 / 输出 / 范围（AGENTS §5.2）

- **目标**：`memories` 表从「可 CRUD 的存储」升级为「可聚合、可版本化、
  可修正、可级联删除的分层记忆底座」，支撑 M2 估时学习/L1 episode 与 M3
  检索/grounding。
- **输入**：D-031 §3（形状冻结）、评估 §3.4（缺口五项与写入者三类）、
  D-030 修订要求（删除/依赖图）、现状代码（`backend/models/memory.py`、
  `backend/schemas/memory.py`、`backend/api/v1/memory.py`，backend-only API，
  不在客户端 Zod 契约内）。
- **输出**：两条 Alembic 迁移（M2 六列切片 + M3 embedding 切片）、模型/
  Read/Create/Update schema 扩展、写入者与检索语义、删除依赖图。
- **负责范围**（A）：迁移、模型、API 语义、聚合写入者框架。
- **不负责范围**：M3 客户端 Memory 页（B）、pgvector 检索实现细节（M3
  任务另立）、实际删除端点实现（M5，本图是其规格）。
- **验收标准**：见 §9。

## 1. 现状与缺口

现有列：`level`(L0-L3)、`domain`、`content`、`source`(JSONB)、
`source_event_ids`(JSONB)、`confidence`、`correction_status`
(UNREVIEWED/CONFIRMED/CORRECTED/REJECTED)。CRUD 完整、D-014 跨用户校验在位，
但**无任何写入者**（event_handlers 不写 Memory）。缺口即评估 §3.4 五项：
无稳定聚合键（聚合只能追加重复行）、无版本链（CORRECTED 只能原地改写，
审计史丢失）、无 kind（episode 与 fact 混在 level 里）、证据只能指事件
（无法指文档锚点）、无向量列。

## 2. 目标形状（D-031 §3 冻结，DDL 草案）

```sql
-- M2 切片迁移
ALTER TABLE memories
  ADD COLUMN subject_key TEXT NULL,
  ADD COLUMN kind VARCHAR(32) NULL
    CONSTRAINT ck_memories_kind CHECK (kind IN
      ('episode','fact','habit','preference','model')),
  ADD COLUMN evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
  ADD COLUMN supersedes_id UUID NULL REFERENCES memories(id)
    ON DELETE SET NULL,
  ADD COLUMN valid_from TIMESTAMPTZ NULL,
  ADD COLUMN valid_to   TIMESTAMPTZ NULL,
  -- 使用遥测（2026-10-01 Hermes 预研补强）：只记「进入决策上下文」
  ADD COLUMN use_count INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN last_used_at TIMESTAMPTZ NULL;
CREATE UNIQUE INDEX uq_memories_user_subject_live
  ON memories(user_id, subject_key)
  WHERE subject_key IS NOT NULL AND supersedes_id IS NULL;
  -- B 评审修订 2026-10-01：版本感知部分唯一索引直接在 M2 建（见 §3）
CREATE INDEX ix_memories_supersedes ON memories(supersedes_id)
  WHERE supersedes_id IS NOT NULL;        -- 反向链遍历（删除/依赖图用）

-- M3 切片迁移（先换 compose 镜像，见 §7）
CREATE EXTENSION IF NOT EXISTS vector;
ALTER TABLE memories ADD COLUMN embedding vector(1536) NULL;
```

`evidence` 元素形状：`{type:"event", id: "<event uuid>"}` 或
`{type:"document", file_id, checksum_sha256, page, span_start, span_end}`。
checksum 把引用钉在被读取的具体版本上（与 M3 引用元组同构）。

## 3. 不变式与索引

- **live 行不变式**：每 `(user_id, subject_key)` 至多一行
  `supersedes_id IS NULL` 的行；非聚合行（L1 episode）`subject_key` 为 NULL，
  不受约束。以版本感知部分唯一索引（`WHERE subject_key IS NOT NULL AND
  supersedes_id IS NULL`）表达，**M2 迁移直接建**（B 评审修订 2026-10-01：
  原案 M2 普通索引 + M3 降级的两步走与 §4 写入者语义矛盾——CORRECTED-
  supersedes 与 L2 聚合 supersede 均为 M2 范围，第一次 keyed supersede
  写入即撞普通唯一索引；部分索引在无写入者时同样成立，M3 也无需索引换装）。
- `supersedes_id ON DELETE SET NULL`：删除被依赖的旧行不炸链，链断由删除
  图（§6）负责显式处理，不为完整性牺牲删除能力。
- upsert 写入者（L2 聚合）以唯一索引为目标做 `INSERT ... ON CONFLICT` /
  SELECT-FOR-UPDATE + supersede，避免并发双写。
- **FK 可延迟**（2026-10-01 落地补记，迁移 `f63b7e2a5c91`）：superseded-by
  方向的写入顺序由部分唯一索引钉死——旧行必须先退（置 `supersedes_id`）
  新行才能插入（部分唯一**索引**在 PostgreSQL 中不可延迟，否则插入时会
  看到两个 live 行）；而旧行的指针指向尚未插入的新行，非延迟 FK 会在
  UPDATE 时即失败。故 FK 定为 `DEFERRABLE INITIALLY DEFERRED`（commit 时
  校验），版本链表的标准做法。
- **REJECTED 阻断与写入串行化**（2026-10-01 预研补强）：部分唯一索引排除了
  REJECTED 行，「阻断再派生」无法由索引表达。`upsert_memory` 必须在同一
  事务内先按 `(user_id, subject_key)` `SELECT ... FOR UPDATE` 锁存续 live
  行，再查阻断、再写——否则 upsert 与 reject 并发时会写出已拒主题的新行。

## 4. 写入者语义（三类）

1. **L1 episode（确定性 handler，M2）**：`focus.completed` handler 直写。
   `level=1, kind=episode, subject_key=NULL, confidence=1.0,
   correction_status=CONFIRMED`（确定性事实，非模型产出）；content 为结构化
   摘要（任务、课程、planned vs actual、时段、`deviation_note`）；evidence
   = focus.completed 事件 + 任务派生事件 id（同时镜像进 `source_event_ids`）。
   追加式，永不更新。
2. **L2 fact（worker 聚合，M2 起逐步加指标）**：按 `subject_key` upsert。
   变化时**新行 supersede 旧行**（旧行补 `valid_to`），不原地改写；
   `confidence = min(0.9, n/10)`（n = 样本量），evidence = 支撑它的 L1
   episode id 列表（血缘向上可追）。首批指标：`estimate:course:<course>`
   （同课程实际分钟中位数）、`estimate_ratio:user`（校准比）。
   **subject_key 键型登记**（2026-10-01 预研补强）：初始键型即上述两种；
   新增键型 = 契约变更，必须先在本文件登记再使用。
3. **LLM 总结（M4+，规则先冻结）**：只能 `UNREVIEWED` + `confidence ≤ 0.5`
   进入；晋升 = 用户确认（CONFIRMED）或 ≥2 次独立确定性证据派生出同键
   live 行。AGENTS §2.3 的「未验证总结不得成为永久事实」由本规则 +
   检索下限（§5）双层落实。

## 5. 修正 / 拒绝 / 检索

- **CORRECTED**：用户修正 = 新行（版本链接向旧行，旧行
  `correction_status=CORRECTED` 不变、补 `valid_to`；**链方向的勘误提案见
  §8——按索引与检索的自洽性，应为旧行被新行指向，非新行指旧行**），
  内容与置信度以用户为准（`confidence` 上调、可附
  `source={user_corrected:true}`）。原地改写禁止——审计史是「可修正」
  验收句的底座。
- **REJECTED**：live 行保留 REJECTED 状态占位 `subject_key`；**聚合器写前
  必查**：live 行为 REJECTED → 跳过本轮并写审计（无 audit 行情的用日志 +
  `source` 标记过渡），否则下一轮聚合悄悄重建用户刚删的事实。用户「解除
  拒绝」= 显式确认或等新确定性证据按晋升规则覆盖（走 supersede，不复活旧行）。
- **检索**（planner 与未来 Agent 共用同一路径）：默认过滤
  `correction_status = REJECTED` 且 `supersedes_id IS NULL`（只要 live 行），
  置信度下限默认 0.3（调用方可提高不可绕过）；M3 增加向量召回（下限过滤
  之后应用）。
- API 面：`MemoryRead` 增列全量透出（backend-only，无客户端契约影响）；
  `MemoryCreate/Update` 增列可选；`MemoryUpdate` 保留原地字段更新的能力
  （手动条目），但服务端写入者一律走版本链。

## 6. 删除 / 依赖图设计（D-030 修订要求）

设计目标：**M5 的级联删除与导出是本图的机械执行，不是考古**。每条记忆的
依赖与被依赖都必须可 SQL 枚举。

```text
Event（事实层，删除入口之一）
  └─ task_events ──> Task（派生投影）
                      └─ L1 episode：evidence 引用其 focus.completed / 派生事件
                            └─ L2 fact：evidence 引用 L1 id 列表（聚合血缘）
                                  └─（M3）文档锚点 evidence 引用 file_id
                                        └─ material_chunks → embedding → 对象存储 blob
```

- **血缘枚举**（删除入口的逆向查询，全部走已建索引）：
  - 删事件 E → 受影响记忆：`evidence @> [{type:'event', id:E}]` 或
    `source_event_ids @> [E]`（JSONB GIN 索引随 M2 迁移补：
    `CREATE INDEX ... USING gin (evidence jsonb_path_ops)`）。
  - 删 L1 → 依赖它的 L2：`evidence @> [{type:'memory', id:<L1>}]`（L2 引用
    L1 时 evidence 元素用 `{type:'memory', id}`——在 §2 元素形状中补入）。
  - 删文档 → 引用锚点的记忆：`evidence @> [{type:'document', file_id:F}]`。
- **处置规则**：证据被删的记忆**不自动删除**——标记失效（`valid_to` 置
  删除时刻）并触发一次该 `subject_key` 的重聚合；重聚合样本不足 → 该 L2
  live 行删除（留下被 supersede 的历史链）。L1 的证据全灭（事件与任务都
  删除）→ L1 一并删除（episode 依附于经历本身）。
- **删除入口**（M5 实现，Level 2 确认 + 审计不含内容）：单条记忆、按
  `subject_key` 全链（含历史版本）、按事件/文档源批量、**导出我的数据**
  沿同一张图正序遍历。
- 本图同时是 M3 回答落库（引用元组）与 E4「删除后回答不再体现该记忆」
  （大纲 M3 出口句）的规格基础。

## 7. 迁移步骤与依赖

1. **M2 切片**（随 D-031 落地）：§2 第一段迁移；模型/schema/API 增列；
   GIN 索引；fixtures 更新；`alembic check` 无漂移。无基础设施变化。
2. **M3 切片**：`docker-compose.yml` 与 CI 镜像 `postgres:16-alpine` →
   `pgvector/pgvector:16`（先验证 CI 可拉取）；§2 第二段迁移（扩展 +
   列；唯一索引已在 M2 为最终形态，无换装）；本地/CI 数据库重建演练一次。
3. 每条迁移 up/down 完整并跑 up→down→up；down 删列/索引/扩展均可逆
   （`DROP EXTENSION` 仅 M3 迁移 down 中执行）。

## 8. 开放问题（M3 开工前裁定）

- embedding 换供应商 = 维度变更迁移 + 全量重嵌（已接受，D-031 §3）；
  pgvector 索引（HNSW/IVFFlat）**暂不建**，规模测量后再决策。
- L0 不入库：Event 表即 L0，`memories` 不复制原始事件（避免双事实源）。
- `domain` 与 `kind` 的关系：domain 保留为粗分类（study/time/...），
  kind 是结构分类，正交使用；不合并。
- **`correction_status` 语义端点化**（2026-10-01 预研提案，待 A/B 签认）：
  预研建议 `MemoryCreate/Update` 移除 `correction_status` 直填，改为语义
  端点 `POST /memory/{id}/confirm|correct|reject`——理由是直填可绕过版本
  链（与 §5「服务端写入者一律走版本链」存在旁路面）。属破坏性契约变更，
  签认时连同 D-032 一并裁定；在此之前按 §5 现行语义实现。
  **A 立场（2026-10-01 签认时提交）**：倾向采纳。直填旁路与
  版本链语义并存是真实的绕过面；Memory API 是 backend-only（客户端契约
  零影响），破坏性只触及服务端 API 消费者；B 的 M2 Memory 页是引入
  `confirm/correct/reject` 端点的自然时机（页面按钮本就需要语义动作而非
  直填状态）。落地排 M2 Memory 页批次，correct/reject 端点内部走版本链。
  **B 裁定（2026-10-01 会签）：采纳**。作为 Memory 页实现者补充落地口径：
  `correct` 端点收 content/confidence 覆盖值并内部走版本链（superseded-by，
  见下条）；`reject` 保持 §5 的 REJECTED live 行占位语义（阻断再派生）；
  页面按钮 ↔ 端点一一对应，`MemoryUpdate` 直填 correction_status 在端点
  落地批次移除。
- **`supersedes_id` 链方向勘误提案（A，2026-10-01，待 B 会签后补 D-031
  勘误注记）**：冻结文本内部存在矛盾。「live 行 = `supersedes_id IS NULL`」
  （D-031 §3 表、本文 §3 不变式、§5 检索）、部分唯一索引谓词与 §3 的
  FOR UPDATE 串行化说明，三者只有在 **supersedes_id 语义 = 「取代本行的
  行」（superseded-by 方向：新行落库时同事务把旧行 `supersedes_id` 置为
  新行 id）** 时自洽；而 D-031 §3 与本文 §5 原括注「新行 `supersedes_id`
  指旧行」（supersedes 方向）与之冲突——supersedes 方向下部分唯一索引
  无法表达 live 唯一（同一旧行可被多个新行指向，出现多个「当前行」且
  索引不拦），且「只要 live 行」的检索会取到**最旧**版本。裁定提案：
  **superseded-by 方向**，两处括注措辞勘误为「旧行 `supersedes_id` 同事务
  被置为新行 id」，其余冻结文本零改动。已落地的列与索引对两种方向不偏
  不倚（PR #18 只约束 NULL 行，方向由写入者批次实现）。
  **B 裁定（2026-10-01 会签）：确认 superseded-by 方向**。B 独立复核坐实
  矛盾机制：supersedes 方向下新行带非空指针——同时逃出部分唯一索引谓词
  又被检索的 `IS NULL` 过滤排除，旧行保持 NULL 反成唯一「live」，每次
  替换产出无约束新行且用户恒取最旧版本；superseded-by 下三者（不变式/
  索引/检索）天然一致，`ix_memories_supersedes` 恰好服务旧行→新行的
  历史遍历。D-031 勘误注记随本裁定补入 DECISIONS。

## 8a. 实现易错点（第一刀必防，2026-10-01 预研补强）

1. **kind 列三步顺序**：加列(NULL) → 按 level 回填（L1→episode、L2→fact、
   L3→model，无推导歧义）→ 需要收紧时再补 CHECK 内含 NULL 的过渡后置
   NOT NULL；颠倒顺序在存量行上失败。`alembic check` + up→down→up 必跑。
2. **use_count 计数点**：只在「进入决策上下文」递增——写入点两个（M2
   planner 检索 L2 估时行、M4 上下文装配）；不记「被候选检索」；批内去抖
   重算不重复计数。权威账本是 M4 `agent_runs` 的 context snapshot（memory
   id 列表），两列只是可展示缓存，别在检索预览路径上递增。
3. **版本链删除**：`supersedes_id` 维持 §2 的 `ON DELETE SET NULL`（评审
   已定，链断由删除图显式处理）；服务层规则「版本化行只删最新版或整链
   保留」，防链中硬删断链丢审计史。（预研原案 RESTRICT 与评审版冲突，
   以评审版为准，见 §3。）

## 9. 验收标准

- 迁移 up→down→up + `alembic check` 通过；compose 镜像替换后 CI 全绿。
- 回归测试：upsert-supersede 链（旧行不被改写、live 唯一）；REJECTED 阻断
  再派生；CORRECTED 版本链；检索过滤 + 置信度下限；evidence（event/
  memory/document 三型）round-trip；血缘枚举三类查询各一条用例。
- E4 依赖项（M2 切片）：L1 直写带证据、L2 估时两键可 upsert。
- 遥测断言（2026-10-01 补强）：`use_count` 只在决策装配递增（批内多次重算
  不重复计数）；Memory 页可展示「这条事实参与过 N 次计划决策」。
