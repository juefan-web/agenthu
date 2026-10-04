# 2026-10-04 A 侧交付：结构化 basis 产出面缺口切片（协调人裁定 1）

## 任务边界

- **目标**：补齐冻结契约承诺但 A2/A3 未落地的三个产出者（B3 缺口矩阵 #1/#2/#3，协调人 2026-10-04 裁定并成一个 A 侧切片，M4 收口前落地）。
- **输入**：main `e537068`（#56 已合）；A 契约 §7、B 契约 §5、B4① 冻结文本。
- **输出**：①确定性 planner/replan 写 `Plan.basis.agent_decision`；②删除消息/归档会话时存储引用翻转 `source_deleted`；③chat run 的 basis 引用触发消息（`chat_message` kind）。
- **不负责**：B 侧 S1/S3 spec 活链断言升级（本切片合并后 B 摘注释锚）；E6 首跑；grant 面文案。

## 交付内容

### ① agent_decision 写入者（A 契约 §7 欠账）

`planner.generate_plan` 在排项完成后写 `plan.basis["agent_decision"]`（新行 flush
前写入，无需变更追踪）：

- 形状 = 冻结 DecisionBasis 外层（`basis_version: "v1"` + summary + references +
  `rule_versions: {planner: slots_v2}` + 空 `selected_tool_call_ids`）；
- references 引用排入的任务（kind task，id+label）、goal（如有）、当日课表事件
  （kind event——镜像投影的 upstream 去重规则，改期的课按最新行只引一次）、
  估时采用的 Memory 行、CurrentState（`locator.state_version`）；
- summary = replan_reason（重排建议的人话理由就是决策摘要）或
  「已排入 N 个任务块 / 本轮无可排入的任务块」；
- legacy 键（strategy/task_ids/trigger_signature 等）原位不动，BasisPanel
  历史兼容层不受影响。

所有 generate_plan 调用方（/generate、/replan、触发引擎、plan.suggest、
replan.evaluate 工具）一次覆盖。

### ② source_deleted 发射点（B 契约 §5 欠账）

新服务 `backend/services/reference_invalidation.py`：
`invalidate_chat_message_references(session, user_id, message_ids)` 扫描
`agent_runs.decision_basis` 与 `pending_actions.basis` 中的 `chat_message`
引用（id 或 locator.message_id 命中），置 `state="source_deleted"`，
JSONB 原位变更用 `flag_modified` 标记。接线在 `chat.py` 两个 DELETE 的
首删分支内、同事务：消息删除翻转单条；会话归档先收集存活消息 id 再
随级联一起翻转。幂等（已翻转不再重复写）。扫描范围 = 用户全部 run/action
行——当前语料量够用，规模问题挂 HNSW/检索重做同桶。

### ③ chat_message kind 产出者（B4①）

`agent_runner.execute_run` 在上下文装配后引用触发消息：
`{kind: chat_message, id, label: "对话消息", locator: {message_id,
occurred_at}}`——只带定位不带正文（冻结文本）。模型环创建的 L2 pending
action 继承同一 references（create_pending_action 已有语义），②的翻转因此
能到达确认卡。顺带把 current_state 引用的 version 从顶层挪进
`locator.state_version`（B4② 冻结形状；旧顶层键是 A2 实现欠账）。

### 附带修复：`_chat_context` 查键错误（A2 真缝隙）

公式 `chat:{session_id}:{client_message_id}` 第三段是**客户端幂等键**，
原实现却按消息主键查 ChatMessage——永远查空，`user_message` 恒为 None，
消息正文从未经该路径进入上下文装配（此前只靠会话近史段兜住）。修复为按
`(session_id, client_message_id)` 查（唯一索引在位）。与 A3 修过的 dispatch
缝隙同类：A2 冻结公式与实现的键语义错位。全量回归零破坏（346 passed）。

## 验证

- `tests/integration/test_m4_basis_gaps.py` 7 用例：生成计划带 agent_decision
  （任务/current_state 引用 + legacy 键共存）；触发引擎建议带
  agent_decision（summary == replan_reason，trigger_signature 保留）；课表
  事件入引用；chat run 引用触发消息（id/locator/不带正文；pending action
  继承）；删消息翻转 run+action 引用（API 读面断言）；归档级联翻转；
  幂等重删。
- 全量 346 passed / 1 skipped（S3 环境缺省）；ruff/format 0 错；
  pyright 0 错（改动五文件）；drift 双源绿；无 schema/迁移/OpenAPI 变更
  （纯行为补齐，DecisionBasis 形状早已冻结在库）。

## B 侧可升级的断言（S1/S3 注释锚）

- S1：重排建议的 `Plan.basis.agent_decision.references` 现在含真实任务引用
  （`GET /v1/plans?status=draft` → items[].basis.agent_decision）。
- S3：删一条被 chat run 引用的消息 → run/卡片 basis 中该引用
  `state="source_deleted"`，UI 失效标注活链可断言。
