# M4-B 草案：动作确认与 Chat 交互契约

状态：**draft r2，待 A 互审**（2026-10-03；r2 并入 B 对 A 契约 v2 的
delta 复核与协调人裁定：B1/B2/B3/A3/A5、B4①② 入 kind 枚举、
`AgentRunRead` 字段级化、路径对齐 `/v1/agent/runs`、A1 过期语义与
A2 幂等键映射的引用）。本文件是
`m4-phase0-prereq-docs.md` 的 B 侧产出，依赖
[m4-agent-runtime-audit-contract.md](m4-agent-runtime-audit-contract.md) 的
`PendingActionRead`、`DecisionBasis`、权限与降级语义。它冻结 UI 所需的
交互和 API 消费边界，不实现页面或修改现有客户端。

## 1. 目标、输入与边界

**目标。** 让用户在 Chat、计划建议和主动提醒中看到同一份可核的理由；任何
Agent 代表用户执行的 Level 2 动作都必须清楚呈现影响、原因、过期时间和结果，
用户可以确认、忽略或在明确失败后重试。

**输入。** 现有 `BasisPanel`、`ReplanSuggestion`、讲解页引用卡和
`BackendHttpError` 分流模式；M2 的 Level 1 重排建议；M3 的同意门、引用跳转和
E5 的构建包 + CDP 验收模式；A 侧 draft 的 pending action / run 契约。

**输出。** pending-action 确认视图、共享 basis 渲染边界、Chat 视图骨架、
主动提醒控制面、离线和 provider 断供的表现，以及 M4 出口场景草案。

**不负责范围。** 本 phase 不做聊天 UI、推送通道、通知系统设置、prompt 文案
调优或模型评估。它不改变确定性 Plan、Focus 或现有 grounding 闭环。

## 2. 共同数据和 API 形状

客户端不重算权限或工具安全性。服务端是 `PendingActionRead`、状态、是否可重试
和安全 display 摘要的权威来源；客户端只渲染并提出确认意图。

```ts
type DecisionReference = {
  // chat_message / current_state 为冻结裁定新增（B4①②）：聊天引用是
  // 定位不是正文；CurrentState 携 version，派生数字只在 references
  // 出现、不重复进 summary。
  kind: "event" | "memory" | "goal" | "plan" | "task" | "material"
      | "chat_message" | "current_state";
  id: string;
  label: string;
  state?: "available" | "source_deleted" | "version_mismatch";
  locator?: { page?: number; quote?: string; occurred_at?: string;
    file_id?: string; checksum?: string; chunk_id?: string;
    span_start?: number; span_end?: number;
    message_id?: string; state_version?: number };
};

type DecisionBasis = {
  basis_version: string;
  summary: string;
  references: DecisionReference[];
  rule_versions: Record<string, string>;
  // B1（必修）：A 契约 §3.1 的服务端字段，共享 Zod 必须含全字段。
  // UI 不渲染它，drift check 靠它保双源一致。
  selected_tool_call_ids: string[];
};

type PendingActionRead = {
  id: string;
  version: number;
  status: "PENDING" | "CONFIRMED" | "EXECUTING" | "SUCCEEDED" |
    "FAILED_RETRYABLE" | "FAILED" | "IGNORED" | "EXPIRED";
  required_level: 2 | 3;
  tool: { name: string; version: string; title: string };
  display: { summary: string; parameters: Array<{ label: string; value: string }>;
    impact: string; risk_note?: string };
  basis: DecisionBasis;
  expires_at: string | null;
  retryable: boolean;
  safe_error?: { code: string; message: string };
  result?: { summary: string; resource_type?: string; resource_id?: string };
  created_at: string;
  updated_at: string;
};
```

`parameters`、`summary` 和 `impact` 必须由后端的已验证工具参数及
`display_builder` 生成；前端不得直接展示模型给出的 JSON、工具原始参数、
cookie、账号、token 或课件正文。所有字段进共享 Zod schema，随后纳入 D-021
OpenAPI/Zod drift check。

命名分层（B1 裁定）：**动作级**结果统一叫 `result`（上表的
`{summary, resource_type?, resource_id?}` 结构化三元组）；
**工具调用级**保留 A 契约 `tool_calls[].result_ref`——同一事实两个粒度，
不混名。

API 冻结目标：

| 请求 | 成功 | 客户端必须处理 |
| --- | --- | --- |
| `GET /v1/pending-actions?status=active\|history&cursor=` | 当前待确认或终态/Level 3 自动动作历史的 cursor page | 空列表、cursor 翻页、来源已删和历史状态。 |
| `POST /{id}/confirm` | 更新后的 read | 409（已被确认/忽略/过期）、403、404、网络失败。请求体含 `expected_version`。 |
| `POST /{id}/ignore` | 更新后的 read | 同 confirm；忽略是明确用户选择，不能再显示为待确认。 |
| `POST /{id}/retry` | `CONFIRMED` 或执行中的 read | 只在 `FAILED_RETRYABLE` 且 `retryable=true` 时显示；同参数 retry。 |
| `GET /v1/agent-runs/{id}` | 安全 run 摘要和 basis | 不返回 prompt、聊天原文、资料文本或 chain-of-thought。 |

确认、忽略、重试的响应永远以服务端返回状态为准。客户端不要乐观地把 action
改为成功，也不要从本地时间自行判定过期；可本地提示即将到期，但按钮可用性
由服务端最终裁定。

`history` 必须包含终态 action、Level 3 自动动作和通知投递结果；它是用户可见的
动作账本，不以普通 `/audit` 原始行替代。默认 active 视图只请求未终态 action
（keyset 排序键 `(created_at, id)`，A3 裁定）；历史按
`finished_at/updated_at, id` keyset 分页。客户端对 confirm/ignore/retry
生成稳定 `mutation_id`；网络超时后以同一个 id 重试，由服务端返回前次结算结果。

过期语义（A1 裁定）：`EXPIRED` 仅可自 `PENDING` 进入；**确认后不再过期**
——确认即用户意图结算，不被时间撤回。UI 侧「即将到期」提示只针对
`PENDING`。

## 3. Pending-action 确认视图

### 3.1 组件边界和状态

新增 `PendingActionCard` / `PendingActionList`，位于应用根部可见的“待你决定”
区域，并可从相关 Chat 消息和通知深链回同一 `id`。它是一个受控工具面，不做
卡片内再嵌卡片的装饰布局。

每张卡固定展示：

1. 动作标题、影响摘要和 Level 标签（例如“需要确认”），而不是内部 tool name。
2. 安全参数清单、会影响的对象和不可逆/外发风险说明。
3. “为什么”入口，渲染该 action 的 `DecisionBasis`；过期绝对时间按用户
   timezone 显示，同时给出相对时间。
4. `确认执行`、`忽略` 两个显式命令。`确认执行` 是危险或外发动作时应带
   动词对象，例如“确认删除这份资料”，避免只有模糊的“确定”。
5. 执行中、成功、可重试失败、最终失败、已忽略和已过期的非歧义状态；成功或
   失败必须有可查看的安全结果/下一步，不能停在加载中。

| 服务端状态 | 呈现 | 可用操作 |
| --- | --- | --- |
| `PENDING` | 显示原因、影响、到期时间 | confirm / ignore。 |
| `CONFIRMED`, `EXECUTING` | 显示“已确认，正在执行”，禁用重复点击 | 刷新或轮询；不显示第二次确认。 |
| `SUCCEEDED` | 显示结果摘要及关联资源跳转 | 无重试；刷新相关 Plan / Task / Memory 查询。 |
| `FAILED_RETRYABLE` | 显示服务器安全错误和“使用同一操作重试” | retry / ignore；不让用户暗中改参数。 |
| `FAILED` | 显示失败原因和可行替代入口 | 无 retry，必要时重开新的 Chat 请求。 |
| `FAILED`（用户自致子码：`permission_revoked` / `consent_revoked` / `source_deleted`） | 文案为「你撤销了授权/同意（或来源已删除），动作已失效」——用户自己选择的结果，不显示为系统故障（B3 裁定） | 无 retry；提供对应撤销入口/重开请求。 |
| `IGNORED`, `EXPIRED` | 保留审计可追溯的终态文案 | 无执行按钮。 |

Mutation 必须防双击：同 action 共享 mutation key，提交中禁用所有互斥按钮；
收到 409 后 refetch，再按返回态显示，而不是向用户声称服务失败。网络中断时保留
原卡片和“未确认是否送达”的失败说明，重连后 refetch；不得离线排队一条
“确认执行”请求，因为确认的时效和状态必须由当前服务端重新判定。

### 3.2 Level 1 和 Level 3 的区别

现有重排建议继续使用 `ReplanSuggestion`：Level 1 只提议，接受/忽略后才走
既有 Plan API；它不是 pending action，也不能被渲染成“系统已经替你安排”。

Level 3 通知可以自动派发，但 UI 仍必须显示“因已授权而发送”的动作记录、
授权范围和撤销入口。没有有效 Grant、超过每日预算、命中免打扰或服务端拒绝时，
通知不发出，并以应用内建议替代。所有有副作用但不是通知的 Agent 操作默认
Level 2。

## 4. 一份 `DecisionBasis`，多个入口

计划的 `BasisPanel`、M3 讲解页的引用卡、重排建议、pending action 和 Chat
“为什么”必须复用一个 `DecisionBasisView` 及 `DecisionReference` 渲染器。
现有 `BasisPanel` 的 `Record<string, unknown>` 兼容层可继续显示历史 Plan basis，
但 M4 新写入一律使用上节结构化形状；不要为 Chat 再造“解释文本”。

渲染规则：

- `summary` 是服务端按规则/证据产生的人话摘要。模型可润色，但事实值、理由和
  reference id 必须不变；UI 可以标记“模型整理的说明”，不能把润色当证据。
- Event 显示发生时间、来源和已脱敏描述；Memory 显示其状态/置信度和详情入口；
  Goal / Plan / Task 跳当前用户的既有视图；材料复用 M3 的文件、页码、quote 跳转。
- 引用不存在、被用户删除或无权访问时，显示“来源已删除或不可用”，仍保留 action
  的历史解释摘要；绝不改指向别的同名对象。
- UI 不渲染模型的隐藏推理、原始 tool args、provider request/response 或不可信
  文档中的指令。长值换行并限制容器，避免影响确认按钮位置。

这使用户在“重排建议为什么这样排”“Chat 为什么建议创建任务”“动作确认为何
需要我同意”三处看到同一组事实，而不是三套含义不同的文案。

## 5. Chat 视图骨架

Chat 是同一 Agent 的一个入口，不是独立助手或第二套任务系统。

初版 API 采用轮询而不引入第二套 WebSocket / stream 语义；所有列表均用 cursor
而非客户端扫全表：

| 请求 | 返回及关键语义 |
| --- | --- |
| `GET /v1/chat/sessions?cursor=` | 当前用户的 `ChatSessionRead[]` cursor page；字段为 `id,title,created_at,updated_at,archived_at`。 |
| `POST /v1/chat/sessions` | 可选标题和 `client_request_id`；同 key 重发返回同一会话。 |
| `GET /v1/chat/sessions/{id}/messages?cursor=` | `ChatMessageRead[]` cursor page，按稳定时间/id 排序；包含 `id,role,content,created_at,agent_run_id?,decision_basis?,pending_action_id?`。 |
| `POST /v1/chat/sessions/{id}/messages` | `{content,client_message_id}` → **202 `{run_id, user_message_id}`**（异步，A §8 评审点 5 裁定）；同 `(session_id,client_message_id)` 重发返回同一 user message 和关联 queued `agent_run`。幂等键映射（A2 裁定）：`run.client_request_id := "chat:{session_id}:{client_message_id}"`——A 契约 §8 现写的请求字段名 `client_request_id?` 落 A2 时统一为 `client_message_id`。 |
| `DELETE /v1/chat/sessions/{id}` | 204；先失效检索资格/FTS，再级联内容行（对齐 A §8 §5.3 顺序）。 |
| `GET /v1/agent/runs/{id}` | `AgentRunRead`（字段级见下）；客户端在非终态 run 时有限轮询。 |
| `GET /v1/chat/search?q=&cursor=` | 只返回仍可见的原消息、会话和定位；**pg_trgm + ILIKE**（A4 裁定，取代 tsvector 预设；ASCII 词 + CJK bigram 复用 M3 keyword lane 同源函数；<3 字符查询走索引外过滤，冻结文本注明的可接受降级）；不先摘要。 |
| `DELETE /v1/chat/messages/{id}` | 204；同事务从检索资格移除（`deleted_at` 置位同事务），关联引用改为 `source_deleted`。 |

`AgentRunRead`（字段级，drift check 消费；不含 context_snapshot 原文、
tool args、prompt——与 A §3.2 读面一致）：

```ts
type AgentRunRead = {
  id: string;
  status: "QUEUED" | "RUNNING" | "WAITING_CONFIRMATION" | "SUCCEEDED" | "FAILED" | "CANCELLED";
  invocation_kind: "chat" | "proactive_trigger" | "pending_action_resume" | "retry";
  created_at: string;
  updated_at: string;
  started_at: string | null;
  finished_at: string | null;
  result: { summary: string; degraded: boolean; degrade_code?: string } | null;
  failure: { code: string; retryable: boolean; safe_message: string } | null;
  decision_basis: DecisionBasis | null;
  pending_action_ids: string[];
  usage: { input_tokens: number; output_tokens: number; tool_tokens: number } | null;
};
```

`ChatMessageRead` 的 `decision_basis?` / `pending_action_id?` 是经
`agent_run_id` join 的**投影列**，不落第二份存储（A5 裁定）。

1. 会话列表和消息流来自 Backend `chat_sessions` / `chat_messages`；本地只做
   短期 UI 缓存。发送消息创建或关联 `agent_run`，消息气泡携带 run status、
   `DecisionBasis` 和 pending-action deep link。
2. 用户可问“为什么”。当消息关联 `DecisionBasis` 时，客户端直接展开
   `DecisionBasisView`；不再次调用模型来编造解释。没有 basis 时如实显示
   “这条回复未提出可执行建议”。
3. 可执行建议以 compact action row 呈现，点击后定位到同一个
   `PendingActionCard`。聊天中不提供绕过确认的“立即执行”快捷命令。
4. 课程资料引用继续走 M3 的 `file_id/checksum/chunk_id/page/span/quote` 不可变
   锚点；checksum 不匹配或文件/消息已删时显示 `version_mismatch` /
   `source_deleted`，资料同意、机械引用和课程范围约束不因 Chat 入口而放宽。
5. 聊天搜索结果显示存储的原消息、时间和会话定位，不做自动摘要。删除消息后
   在列表、搜索和下次 Agent 检索中均不再出现。

初版使用列表式会话和单输入区，确保长消息、错误、action card 和引用跳转在
桌面窄窗口中不互相遮挡。输入的发送按钮在请求进行中保持稳定尺寸；重新发送
创建新 run，不覆盖旧 run 或旧动作。

## 6. 主动提醒和用户控制

主动建议由后端规则触发，客户端不自行从本地任务猜测或发送通知。控制面消费
A 侧 user preference：

```ts
type NotificationPreferences = {
  version: number;
  timezone: string;
  enabled_categories: string[];
  quiet_hours_start: string | null; // local HH:mm
  quiet_hours_end: string | null;
  daily_budget: number;
  sent_count: number;               // current local day, read-only
  budget_date: string;              // server-only 只读（B2）：sent_count 的归属日
  last_sent_at: string | null;      // server-only 只读（B2）
};
```

设置页提供：类别开关、免打扰开/结束时间、每日上限的明确数值控件，以及当天
已使用次数。跨午夜的 quiet period 合法；保存后由 Backend 按用户 timezone
校验。`GET /v1/notification-preferences` 返回上述形状；`PATCH` 携带
`expected_version`，冲突返回 409 与最新值，避免两个客户端静默覆盖。UI 不声称
“绝不会提醒”，而是精确显示预算和免打扰规则；deadline 风险若未来获准成为例外，
必须显示政策文字和对应审计记录。

收到的 Level 1 主动建议以应用内可关闭条目呈现，并能打开相同 basis；推送和
应用内消息都不能承载未确认的副作用。关闭一条建议等同于其对应 action 的
ignore 只有在该建议实际创建了 pending action 时成立，普通 Level 1 建议只关闭
展示，不篡改 Plan。

## 7. 离线、未同意和 provider 断供

| 情况 | Chat / action 表现 | 必须继续可用的路径 |
| --- | --- | --- |
| Backend 不可达或无 Backend 会话 | Chat 显示明确离线状态，禁用发送、confirm、ignore 和 retry；不伪造本地确认成功。 | 本地 Focus 草稿、已缓存的 Today / Task 只读信息与现有校园采集队列。 |
| Provider 未配置、模型数据同意缺失或 provider 503 | 关联 run 显示“模型暂不可用”；不生成无依据的平滑回答。 | `GET /plans/today`、确定性 planner、`ReplanSuggestion`、Focus 和已有 basis。 |
| 课程资料同意未开启 | 延续 M3 的 403 同意门，不把课程内容带入 Chat 模型上下文。 | 非资料型确定性计划和本地任务工作流。 |
| pending action 到期、冲突或权限被撤销 | 显示服务器终态并移除执行按钮。 | 用户可重新发起新的、基于当前状态的请求。 |

已有 `BackendHttpError` 的状态码分流模式继续使用。错误文本应说明“没有执行”
还是“执行结果未知”；后者只能通过刷新 action 状态结算，不能建议用户重复
发送可能有副作用的请求。

## 8. M4 出口场景草案

以 E5 的“编号断言 + 构建包/CDP + 真实 Backend 或录制回放”模式建立 M4 e2e。
场景使用合成任务、事件、Memory 和资料，不能使用真实课程内容。

1. seed 一个实际用时超标的 Focus Event 和已确认 Plan，触发规则产生 Level 1
   重排建议；客户端显示与 `Plan.basis` 相同的 Event / Task 依据。
2. 从 Chat 请求“把这项作业加入日程”。Agent 创建 Level 2 `task.create` pending
   action；卡片显示安全参数、原因、绝对到期时间和 `DecisionBasis`。
3. 在 Chat 点击“为什么”，断言展示相同 basis 引用；删除或失效的来源显示失效
   标识而不跳错对象。
4. 确认 action，断言只产生一个 Task / Event / audit 结果；并发或双击只得到
   一个成功执行。失败模拟时 action 显示可重试或最终失败，retry 使用原 key。
5. 将模型 provider 置为 unavailable，断言 Chat 明确失败，而 today plan、重排
   建议、Focus 和其已有 basis 仍可操作。
6. 配置 quiet hours 和 daily budget；相同 trigger 在免打扰或预算耗尽时不发送，
   仅保留应用内建议和审计。配置有效 Level 3 grant 后才允许一次自动通知。

单元测试覆盖每个 action state、409 刷新、显示脱敏、引用跳转和错误分流；
集成测试覆盖跨用户隔离、过期、撤销授权和 mutation 幂等；构建包 E2E 覆盖以上
用户路径。任何 API 形状变更同步更新 Zod、OpenAPI、fixtures 和 drift check。

## 9. 互审问题与实施拆分

A 互审应确认：`display` 是否足以让用户理解每个初始工具、`DecisionBasis` 是否
能不泄露原文地定位证据、action 状态机是否覆盖 worker 恢复，以及 Chat 数据删除
能否与 M5 依赖图相容。B 互审完成后才把本文件和 A 文件的共同部分记入
DECISIONS。

r2 状态（2026-10-03）：B 对 A 契约 v2 的 delta 复核已完成——fca521c 基线的
承重语义 12 项在 v2 全部在位（−64 行均为引号风格/重排），v2 新增面
（degrade_code、manifest 冻结形状、pg_trgm、异步 202、默认值集）经 B 裁定
采纳，§11.2 十二条 B 侧逐条裁定见 PR #50 评审留痕。**待 A 侧补落三项裁定**：
A1（CONFIRMED 起不过期）、A2（`chat:{session_id}:{client_message_id}` 映射，
并统一 A §8 的请求字段名）、B4②（`current_state` kind + version）；B4①
（`chat_message` kind）B 已按裁定并入本文件，A 如无异议确认即可。

冻结后的 B 实施建议顺序：共享 Zod + BackendClient action 方法和 mocks；
`DecisionBasisView` 兼容现有 `BasisPanel`；PendingAction 视图；Chat 骨架；
notification preference；最后按上述场景补 build-package E2E。每一步保持
确定性 Plan / Replan / Focus 不依赖 provider 的回归测试。
