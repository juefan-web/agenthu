# 未来阶段整体规划大纲（2026-09-30，基于 main `f4afc09` 的个人理解稿）

定位：这是提案，不是已冻结的规范。它以 `GOALS.md` 的产品构想为方向，以 `AGENTS.md` 的不变量为边界，以 `TECH_STACK_AND_WORKPLAN.md` 的 M0–M4 为起点，并吸收上一份评估报告（`2026-09-30-implementation-evaluation.md`）的结论。与原 workplan 的两处差异会明确标出：**在 Memory 与 alpha 加固之间插入独立的 Agent 阶段**，以及**把"确定性闭环"作为 M2 的硬出口**。采纳前需按 AGENTS §5 走 DECISIONS 记录。

## 0. 总体原则（贯穿所有阶段）

1. **确定性优先，LLM 后置且可替换。** 每个智能能力先有可测试的规则实现（planner、估时、触发器、citation 校验），LLM 只做规则做不好的部分（自然语言理解、解释生成、总结），并且规则版永远是降级路径。
2. **每个新功能必须回答"服务闭环哪一环"**（看到→记住→理解→规划→行动→学习）。不服务闭环的展示型功能延后。
3. **一切建议都带结构化依据。** 任何计划、提醒、回答都携带 `basis`（引用的 Event / Memory / Goal / 资料锚点 / 策略版本），UI 再渲染成人话。
4. **写入分级。** Level 0/1 系统自动；Level 2 必须走 pending-action 确认；Level 3 需显式 `PermissionGrant`。模型产出的记忆默认 `UNREVIEWED`。
5. **契约先行。** 跨 Backend/Client 的变更先冻结契约（Zod 为准，D-009），再并行实现；新数据类别接入前先写清"是否上传、谁能访问、保存多久、如何删除"。
6. **验收工具化。** 每个阶段的出口是一条可自动重放的端到端场景（沿用 e2e 套件），而不只是人工验收轮次。

## 1. 阶段总览

| 阶段 | 主题 | 是否需要 LLM | 出口场景（一句话） |
| --- | --- | --- | --- |
| M2 | 确定性闭环：计划 v2 + Focus 反馈 + 重排建议 | 否 | 采集→避开课程的可解释计划→一次超时 Focus→重排建议→接受→生成一条可修正的 L1 记忆 |
| M3 | Memory 与 Grounding | 部分（embedding） | 用户对某门课资料提问，得到带可验证引用的回答，且回答体现其 Learning Memory |
| M4（新增） | Agent 运行时、Chat、主动 Agent | 是 | Agent 主动提出一个需确认的动作，用户在 Chat 中追问"为什么"，得到基于 basis 的解释 |
| M5（原 M4） | Alpha 加固：隐私、删除、可观测、多用户部署 | 否 | 完整"导出/删除我的数据"，且外部调用全链可追踪 |
| M6 | 多端与 Inbox：Android 感知 + 通知流 | 可选 | 手机通知与 Windows 计划在同一 Current State 上互相影响 |
| M7 | Exercise / Life 领域 | 可选 | 运动与消费事件进入同一 Event/Memory 管线并影响计划 |
| M8 | Review 与个人模型 | 是 | 周/月 Review 由 Event 与 Memory 汇总生成，可被用户修正后写回 L3 |

M2→M3→M4 有强依赖，不可跳序；M6/M7 的 adapter 工作可以在 M3 之后穿插，但其"影响决策"的部分依赖 M4。

## 2. 各阶段目标与核心设计

### M2 — 确定性闭环（当前阶段的剩余部分）

**目标：** 让 AGENTS §8 的验收句子在不依赖 LLM 的情况下完整成立。

**Planner v2。** 以"空闲时段"为基本单位而不是"顺序摆放"。先算当天可用区间（now 至日终，减去课表条目与前后缓冲、休息块、用户占位），总量受 `available_minutes` 约束；再对待办任务做确定性打分（紧迫度取自 slack = 距截止时间 − 剩余估时，再加 goal 权重与 priority）；长任务切块；slack 为负的标记 `at_risk` 而不是静默丢弃。每个计划项写入结构化 basis（截止时间、slack、估时及其来源、goal、所选时段的理由、打分分量），`strategy` 作为版本标签（如 `slots_v2`），便于同一批 fixture 上与旧策略对比。

**估时学习。** Focus 完成后得到实际用时；按课程/任务类型维护中位数先验，加上用户级校准系数（实际÷计划的截尾均值）。结果作为 L2 Memory 行存储（带来源 Event 与样本量置信度），planner 通过与未来 Agent 相同的检索路径读取。样本不足时回退默认值并在 `estimate_source` 中如实标注。

**重排建议引擎。** 触发条件是显式的事件模式：Focus 实际用时显著偏离计划、近 48 小时截止的新任务、已确认计划项的时段已过却未开始、当日课表变更、进入/退出"摆"状态。由 worker 按用户去抖评估。触发后**绝不修改已确认计划**，只生成带 `replaces_plan_id` 与人话 `replan_reason` 的新草稿（Level 1），客户端展示差异并由用户接受（走现有 confirm）或忽略；设频率上限，避免变成噪音。

**CurrentState 补全。** 加入 goals 摘要与"摆/休息"状态（一等公民，而不是缺省）；`recent_state` 进入客户端契约（D-027 附录）；批量入库改为"标记脏、批末重算一次"，投影哈希不变则不递增 version；worker 承担去抖重算。

**其他必做。** 逾期任务策略（独立分桶、可关闭、超过 N 天默认不入计划）；D-029 keyset 分页（含 Rust 代理响应头白名单加 `x-next-cursor`）；离线快速失败（健康探测 ≤2 秒）；e2e 两处 spec 修订；文档头刷新。

**出口：** e2e 新增场景 E4：计划避开课表且每项有人话理由 → 超时 Focus → 出现重排建议并引用超时 → 接受 → Memory 页出现带证据的 L1，可修正/删除。

### M3 — Memory 与 Grounding

**Memory 服务。** 表结构在现有基础上补五个字段：`subject_key`（聚合器 upsert 的稳定键）、`valid_from/valid_to` 与 `supersedes_id`（版本化）、`kind`（episode/fact/habit/preference/model）、通用 `evidence`（既可指向 Event 也可指向文档锚点）、可空 `embedding`。写入者分三类：确定性 handler 写 L1；worker 聚合任务把 L1 汇成 L2（置信度由样本量决定）；模型总结只能以 `UNREVIEWED` + 封顶置信度进入，靠用户确认或重复的确定性证据晋升。`CORRECTED` 生成新版本并 supersede 旧版本；`REJECTED` 必须阻止同一 `subject_key` 被再次派生。检索层默认过滤 REJECTED 并设置置信度下限。客户端提供 Memory 页：展示证据、确认/修正/删除。

**资料摄取。** 元数据先经 CampusAdapter 作为 Event 上报（文件列表、通知、作业详情、考试等，vendor 已具备）；文件本体仅在用户显式操作后由 Tauri 下载并上传对象存储（复用 `FileObject`）。worker 按页/幻灯片抽取文本，写入 `material_chunks(file_id, checksum, page, span, text, embedding)`；PDF 用文本层，扫描件才走 OCR；PPT 以页为单位保留标题层级。

**检索与引用。** 混合检索（关键词 + pgvector），范围默认限定在当前课程。引用是元组 `(file_id, checksum, page, span)`，checksum 把引用钉在被读取的具体版本上。**引用校验是机械步骤**：生成后每段引文必须能在被引 chunk 中（归一化后）找到，否则删除该引用并将回答标为"未落地"。每次回答连同引用、模型与 prompt 版本一起落库，使"引用正确率"可度量。

**Study 体验。** 客户端 AI 讲解页支持点击引用跳转到 PDF/PPT 页码；作业辅助默认引导式，记录题目、过程、指导轮次和结果版本（版本历史）。课堂录音/转写与幻灯片同步属于后续增强，放在本阶段末尾或推迟，取决于隐私决策。

**先决文档：** 课程资料是第三方版权内容，接入前要写一份隐私/合规决策（上传范围、保存期限、删除方式、是否允许送入模型供应商）。

**出口：** 针对一门课的资料提问，回答的每条引用都通过机械校验，回答体现某条已确认的 Learning Memory；用户删除该 Memory 后回答不再体现它。

### M4（新增）— Agent 运行时、Chat 与主动 Agent

**Provider 适配层。** 统一接口覆盖补全、结构化输出、工具调用，强制超时与重试上限；首选一个供应商，接口不泄漏供应商类型。

**Agent 循环。** 显式实现 Observe→Understand→Retrieve→Decide→Plan→Act→Observe Result→Update→Re-plan。先用朴素循环实现，只有框架能消除真实复杂度时才引入 LangGraph，两种选择都要记录决策。确定性 planner 保留为 Agent 的一个**工具**，也是无模型时的兜底。

**上下文装配。** "CurrentState + top-k 相关 Memory + 活跃 Goals"，在 token 预算内组装；快照（CurrentState 版本 + memory id 列表）随每次 run 落库，保证可复现。

**可审计。** `agent_runs`（模型、prompt 版本、上下文快照、调用的工具、token、延迟、结果）；工具注册表中每个工具声明其 `ACTION_POLICY` 动作，权限等级成为数据而非约定。

**动作确认。** Level 2 工具不直接执行，而是创建 `pending_actions`（拟执行参数、原因、过期时间），用户在客户端确认后才执行；Level 3 需要显式 `PermissionGrant`；失败与重试同样入审计。这也是权限层第一次面对它真正的对象（agent 而非用户本人）。

**Chat。** 只是入口之一：Chat 与主动提醒共用同一 Agent 与同一 basis 渲染；"为什么"直接展开 basis 中的 Event/Memory/Goal 引用。

**主动 Agent。** 复用 M2 的触发器框架，由规则决定"何时值得打扰"，LLM 只负责措辞与补充解释；有免打扰时段与每日打扰预算。

**评估。** 在调 prompt 之前先建 fixture 评估集：计划解释、引用校验、遵守 Memory 的回答、拒绝越权动作。

**出口：** 见总览表；另要求断开模型供应商后，计划与重排建议仍能工作（降级路径可用）。

### M5（原 M4）— Alpha 加固

**数据生命周期。** 删除必须沿依赖图级联：Event → 派生 Task 的 `source_event_ids` → Memory 证据（依赖它的 L2 重算或失效）→ chunk 与 embedding → 对象存储实体。导出走同一张图。删除操作本身是 Level 2 并留下可审计但不含内容的记录。

**可观测。** 外部调用（校园、模型、存储）与 agent run 的 OpenTelemetry 追踪；错误上报脱敏；日志与测试 fixture 不含个人内容。

**部署形态。** Redis 限流替换进程内限流；多 worker；备份与迁移演练；密钥与配置分环境。

**合规。** OneTHU BSL 1.1、LearnX 及依赖的许可逐文件审查（已是分发的阻塞项）；小范围内测用户的知情同意与数据说明。

**出口：** 一次完整的"导出我的数据"与"删除我的数据"演练，随后检索、Memory、对象存储中都查不到残留。

### M6 — 多端与 Inbox

**Android。** 定位于感知：通知采集、（授权后）位置与运动、主动提醒。它与 Windows 共享 Event Schema、API、权限模型，**不直接互相同步**，一切经 Backend。本地处理优先：通知原文先在本机分类/脱敏，只上传必要字段与分类结果。

**Inbox。** 通知/邮件/消息统一为 Event 后进入分类管线：先规则（来源、关键词、发件人、课程关联），再由 Agent 判定"是否影响当前计划"。分类结果可被用户纠正，纠正进入 Memory。Inbox 不做"另一个信息流"，只做"哪些内容需要改变我的计划"。

**Context Switching。** 多端状态汇入同一个 CurrentState（手机上报"在路上/在教室"等），由 CurrentState 的 `context` 派生链统一裁决，而不是各端各自维护。

### M7 — Exercise 与 Life

每个领域遵循同一模板：**一个 adapter 方法 → 一种 Event 类型 → 可选 handler → 影响 CurrentState/计划的明确规则**。Exercise 区分 Performance（训练、体测）与 Well-being（休息、恢复），并与"摆"状态联动；Life 覆盖消费、校园卡、水电、场馆预约等，其中金额与位置类数据默认本地处理、仅上传聚合结果。新领域只有在能改变某个决策时才接入，否则不做。

### M8 — Review 与个人模型

Daily/Weekly/Monthly Review 由确定性汇总（完成率、估时偏差、时段分布、逾期原因）加 LLM 叙述组成，所有数字可追溯到 Event。L3 个人模型（作息倾向、拖延模式、学习风格）只能由多次 L2 证据加用户确认产生，并允许用户整体查看与重置。

## 3. 模块核心设计速查

| 模块 | 核心设计要点 | 首次落地 |
| --- | --- | --- |
| Event / Adapter | 统一 envelope + provenance；服务端算 dedupe 键；新数据源只写 adapter 与类型，不改业务代码；敏感字段入口拒绝 | 已有；随各域扩展 |
| Task / Goal | Task 有稳定上游身份与来源；估时来自 Memory；Goal 参与打分而非仅展示；逾期独立分桶 | M2 |
| CurrentState | 可重算的投影而非 Event 副本；批末重算 + 哈希去重；含 goals、摆状态、可用分钟及其分解 | M2 |
| Planner | 空闲时段 + 确定性打分；结构化 basis；策略版本标签；永不改写已确认计划 | M2 |
| Focus | 会话持久化、幂等完成；偏差说明结构化后进入 L1；估时学习的数据来源 | M2 |
| Trigger / Worker | 事件模式触发 + 按用户去抖 + 频率上限；同一框架服务重排建议与主动 Agent | M2 |
| Memory | 分层 L0–L3；subject_key 聚合、版本化、可修正/拒绝且拒绝阻止再派生；模型产出默认未确认 | M3 |
| Knowledge / Grounding | 版本钉死的引用元组；机械引用校验；课程范围检索；回答落库可度量 | M3 |
| Agent Runtime | 显式循环；上下文快照；run 审计；规则 planner 作为工具和兜底 | M4 |
| Permission / Action | ACTION_POLICY 绑定工具；pending_actions 确认；Level 3 需 Grant；失败/重试可审计 | M4 |
| Chat / Proactive | 同一 Agent、同一 basis；打扰预算与免打扰；LLM 只管措辞 | M4 |
| Privacy / Lifecycle | 数据类别接入前先写四问；级联删除与导出同图；本地优先处理敏感原文 | M5 |
| Observability | OTel 追踪外部调用与 run；脱敏日志 | M5 |
| Client (Windows) | Zod 契约权威；适配层受控；视图按功能拆分并注入单例；UI 渲染 basis | 持续，M2 起拆分 |
| Client (Android) | 感知与提醒；本地脱敏；经 Backend 同步 | M6 |
| Inbox | 规则分类 + Agent 判定影响；用户纠正入 Memory | M6 |
| Exercise / Life | adapter→Event→规则影响决策；敏感数据本地聚合 | M7 |
| Review | 确定性汇总 + 叙述；L3 需用户确认 | M8 |

## 4. 关键风险与应对

1. **再次陷入通道工程。** 已用五轮验收换来登录/同步的稳定。M2 起把每阶段出口定义为产品场景，并给"通道类"工作设定时间盒。
2. **记忆污染。** 模型总结被当作事实是最难回滚的错误。靠 UNREVIEWED 默认、拒绝阻断再派生、版本化三层防护。
3. **引用看似可信实则错误。** 靠机械校验和 checksum 钉版本；校验失败一律降级为"未落地"，不给"看起来对"的答案。
4. **版权与隐私。** 资料与转写进入云端前必须有书面决策；默认本地处理、最小上传。
5. **客户端与 Backend 契约漂移。** 沿用 D-021 的 CI 漂移检查，并把 `basis`、`recent_state`、pending-action 等新结构纳入。
6. **双人分工下的接口冲突。** 每个阶段开工前先冻结该阶段的契约与 DECISIONS 条目，再并行；否则重演 M0 的多次合并回修。

## 5. 建议的下一步（按顺序）

1. 把本大纲中的"M4 插入 Agent 阶段"和"M2 出口 = 确定性闭环"提交为一条 DECISIONS，确认或修改。
2. 为 M2 建任务文件（目标/范围/验收，遵循 AGENTS §5.2），拆成 A：planner v2 + 触发器 + CurrentState 批末重算 + 分页；B：重排建议 UI（差异 + 接受/忽略）+ basis 渲染 + Memory 页原型 + 视图拆分。
3. 并行起草 M3 的两份先决文档：Memory schema 迁移方案，以及课程资料的隐私/合规决策。
4. 刷新 `CURRENT_STATE.md` 头部与已失效的合并门槛。
