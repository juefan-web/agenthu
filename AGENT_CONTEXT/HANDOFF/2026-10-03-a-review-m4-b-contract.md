# A 评审记录：M4-B 草案《动作确认与 Chat 交互契约》（2026-10-03）

审阅对象：`AGENT_CONTEXT/TASKS/m4-action-confirmation-chat-contract.md`
**r2 @ `564f68a`**（远端分支 head 文本——版本治理规则：背书落在具体文本
版本上）。审阅人：A（rotcar07）。

## 结论

**Approve，无阻塞项。** 一项互审要求（AgentRunRead 补 `tool_calls[]`）、
两项小修（`expires_at` 非空、字段名统一随 A2 已由 A 侧完成）、两项非阻塞
建议。B 的 r2 已把协调人裁定 B1/B2/B3/A3/A5、B4①②、A1/A2/A4 引用全部
落位，且对 A 契约 v2 的 delta 复核结论（12 项承重语义在位、−64 行为引号
风格）与 A 自查一致。

## B 草案 §9 四个确认点——A 的作答

1. **`display` 是否足以让用户理解每个初始工具？** 足以。逐工具核对：
   plan.confirm（需在 impact 中说明「接受即取代」D-031 §2 语义）、
   task.create / task.update / focus.start（参数清单 + 影响对象）、
   memory.write（UNREVIEWED + 置信度封顶标注）、file.delete / data.delete
   （不可逆 risk_note）、message.send（外发对象与内容预览）。一条补强建议
   （非阻塞）：`task.update` 的 `display.parameters` 需要「旧 → 新」渲染
   约定，否则用户看到新值不知道改了什么——建议 B 落一行 value 格式约定。
2. **`DecisionBasis` 能否不泄露原文地定位证据？** 能。quote 仅沿 M3 已
   验证的机械校验引用模式（用户本人课件、逐字可核）；`chat_message` 只带
   message id + occurred_at（B4①：引用是定位不是正文）；`current_state`
   只带 version（B4②）。label 生成同样不嵌正文（标题/时间即可）。
3. **action 状态机是否覆盖 worker 恢复？** 覆盖。A 侧 lease/watchdog
   （execution_lease 过期 → 先查下游幂等键 → 结算或 `FAILED_RETRYABLE`/
   `execution_lease_expired`）与 B 侧 `EXECUTING` 轮询、`FAILED_RETRYABLE`
   重试、409 refetch 的映射完整；A1 落案后「确认后不过期 + 恢复 worker
   持续 claim」闭合了确认与派发之间 worker 死亡的窗口。
4. **Chat 数据删除能否与 M5 依赖图相容？** 相容。消息软删（`deleted_at`
   置位与 FTS 失效同事务）、会话级联、引用改标 `source_deleted`、
   run 侧只存 message_id 引用（A 契约 §5.3 数据类别表的顺序要求）——
   M5 级联是机械遍历，无隐藏第二存储（A5：投影列不落库）。

## 裁定确认

- **B4①（`chat_message` kind）：确认，无异议。** Agent 检索资格本就含聊天；
  删除 → `source_deleted` 不复活，与 §5.3 删除图一致。
- **B4②（`current_state` kind + version）：已落 A 契约 §3.1**（派生数字只进
  references 不重复进 summary，与 D-027 版本语义一致）。
- **A1–A5 无异议**：A1/A2/B4② 已随 v3 落 A 契约；A3（active 页
  `(created_at, id)`）与 A5（join 投影）B 已落；A4 已按协调人终裁执行
  （pg_trgm + 两条件，A 契约 §8）。

## 互审要求（唯一一项，冻结前落）

**`AgentRunRead` 补 `tool_calls[]`。** B r2 的字段级形状缺工具调用数组。
协调人给评审点 6（L0 审计降噪）的成立条件是「用户可见的审计面必须能 join
出 run 的工具调用序列」——A 侧已把 `tool_calls[]{call_id, tool_name,
tool_version, status, started_at?, ended_at?, error_code?}`（不含参数正文）
写进 A 契约 §3.2 的权威形状，B 侧 Zod 镜像补齐同形数组即可。

## 小修（随 B 下轮或冻结前）

1. `PendingActionRead.expires_at: string | null` → **`string`（必填非空）**：
   服务端该列 NOT NULL 恒有值；A1 落案后「确认后不计时」是 UI 规则，不是
   字段置空。保留「即将到期」本地提示（B 已写，且正确限定于 PENDING）。
2. A2 字段名统一（`client_message_id`）已由 A 侧 v3 完成（§8 请求体 +
   §3.1 公式），无需 B 动作，此处仅记录闭环。

## 非阻塞建议

1. `task.update` display 的「旧 → 新」value 约定（见上问 1）。
2. e2e/集成层补一条 A2 断言：同 `client_message_id` 重发返回同一 user
   message 与 run（消息级幂等），可并入 B §8 的 mutation 幂等集成测试。
3. B §2 的 `retryable: boolean` 与 status 的冗余可接受（客户端不自行推导
   是对的），实施时由服务端从 `FAILED_RETRYABLE && attempt < max` 派生，
   注释写明单一来源。

## 跨契约对齐处置表（本轮双向闭环记录）

| 差异点 | 处置 |
| --- | --- |
| run 读面路径 `/v1/agent-runs`（B 首稿）vs `/v1/agent/runs`（A） | B r2 已对齐 `/v1/agent/runs`——采纳，双稿一致 |
| 检索：sessions 列表挂 `?q=`（A v2）vs 独立 `/v1/chat/search`（B） | 采纳 B；A v3 已撤列表 q |
| 消息级 DELETE 端点（B）vs 仅会话级（A v2） | 采纳 B；A v3 已补（对齐 `deleted_at` 软删设计） |
| POST messages 字段名（A `client_request_id` vs B `client_message_id`） | 采纳 B + A2 公式桥接；A v3 已统一 |
| 会话 title 确定性生成（A）vs 可选标题（B） | 折中：可选显式标题 + 确定性回退；A v3 已改 |
| `AgentRunRead` 含 `tool_calls[]`（A）vs 不含（B r2） | **A 坚持含**（评审点 6 条件）；B 待补 |
| `context_snapshot` 进不进 run 读面 | 采纳 B 的排除（读面 lean，复现走服务端快照域）——A v3 §3.2 已注明 |
| `pending_actions` 结果字段名 `result_ref`（A v2）vs `result` 三元组（B） | 按 B1 命名分层裁定统一为 `result`；A v3 已改 |
