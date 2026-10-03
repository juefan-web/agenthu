# M4 任务：先决文档双草案（phase-0，A/B 各一，互审后冻结）

Status: open（2026-10-03 立项，协调人，M3 收口后开跑）。依据：路线
大纲 M4 节（D-030 accepted）、AGENTS §2.1（显式循环）、§3（权限
数据化）、`HANDOFF/2026-10-01-hermes-memory-prestudy.md` §2 的两条
「记账 M4」（会话 FTS、前缀稳定排序）、现有 M2/M3 phase-0 模式。

进度：**A 草案已交 v2**（2026-10-03，`TASKS/m4-agent-runtime-audit-contract.md`
@ `feature/m4-phase0-runtime-contract`——以重写稿为基并入 A 首稿更优部分，
§1 八项全覆盖 + §11.2 十二条评审点待 B 裁、§11.1 修订清单可 diff）。
B 草案进行中。

## 0. 为什么先文档后动工

M4 是权限层第一次面对真正的对象（agent 而非用户本人），且 Chat、
主动提醒、动作确认共享同一 Agent 与 basis 渲染——不先冻结
agent_runs / pending_actions / 工具注册表三张契约，双侧并行必然
重演 M0 的合并回修。

## 1. A：《Agent 运行时与审计契约》（backend 侧）

必须写清（AGENTS §3 格式：作用/输入/输出/数据/权限等级/失败处理）：

1. **agent_runs schema 草案**：模型、prompt 版本、上下文快照
   （CurrentState 版本 + memory id 列表 + token 预算分配）、调用
   工具序列、token/延迟、结果与失败；快照保证 run 可复现。
2. **工具注册表**：每工具声明 `ACTION_POLICY`（Level 0-3 数据化），
   planner v2 作为工具之一注册（无模型时的兜底路径）。
3. **pending_actions 生命周期**：拟执行参数、原因、过期时间、确认/
   忽略/失败重试的状态机与审计事件；Level 2 不直接执行，Level 3 需
   显式 PermissionGrant。
4. **上下文装配**：CurrentState + top-k Memory + 活跃 Goals 在 token
   预算内的组装规则；**前缀稳定排序**（参考 Hermes 预研 §1.2 的
   设计动机，实现自研）；文档内容进上下文时按 D-033 §3 裁剪 + 分隔
   符隔离标注不可信。
5. **provider 工具调用接口缺口**：现 adapter 只有 embed/generate——
   补工具调用（function calling）的接口形状与降级语义（无工具能力
   的供应商怎么办）。
6. **Agent 循环**：Observe→Understand→Retrieve→Decide→Plan→Act→
   Observe Result→Update→Re-plan 的状态落点（哪些步产生 Event/审计，
   哪些只进 run 记录）；朴素循环优先，引入框架需单列决策。
7. **主动 Agent 复用触发器框架**的接线点与打扰预算字段。
8. **会话 FTS**（Hermes 预研记账项）：PG tsvector 方案与「检索不做
   摘要、返回原文」原则的落点。

## 2. B：《动作确认与 Chat 交互契约》（client 侧）

1. **pending_actions 确认 UI**：拟执行参数、原因、过期的呈现规范；
   确认/忽略操作与 E5 已验证的「断言对齐判据」e2e 口径。
2. **Chat 视图骨架**：与讲解页/计划建议共享 basis 渲染的组件边界
   （不新造第二套解释渲染）；「为什么」直接展开 basis 引用。
3. **主动提醒呈现**：免打扰时段与每日打扰预算的用户侧控制。
4. **离线与降级**：断供时 Chat 入口的失败面（计划/重排建议必须仍
   可用——M4 出口判据之一）。

## 3. 不负责范围（本 phase）

- 任何实现代码；prompt 内容调优；评估 fixture 集（冻结后第一刀，
  在 prompt 调整之前建）。

## 4. 验收标准

1. 两文档互审通过（A/B 各批对方），评审意见闭环。
2. 三张契约（agent_runs / pending_actions / 工具注册表）字段级定稿，
   足以双侧并行开工不再口头对齐。
3. 权限等级、失败处理、审计点在每张契约里显式出现（AGENTS §3 硬
   要求）。
4. 冻结时按惯例记 DECISIONS 条目，拆出实施任务文件（A：运行时+
   审计+工具注册表；B：Chat+确认 UI+提醒呈现）。
