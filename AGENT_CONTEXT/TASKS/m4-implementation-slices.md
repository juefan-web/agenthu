# M4 任务：实施切片分派（phase-0 冻结后，依据 D-034）

Status: open（2026-10-03 立项，协调人）。契约依据 = 两份冻结文本
（`m4-agent-runtime-audit-contract.md` v3 + `m4-action-confirmation-
chat-contract.md` r3，D-034）。**顺序门禁：切片 B1/A1（契约代码化）
同批先行合入，之后 A/B 并行；A2 内含全局同意门禁。**

进度：**A1 已交付**（2026-10-03 深夜，`feature/m4-a1-contract-codification`
——迁移 `b8d3e57a21c4` 五表 + grant 部分唯一 + content_revision 回填、
ACTION_POLICY 四新行 + focus.start L2、软撤销语义、8 读面端点、drift
注册与快照预置；309 passed / pyright 0 / 迁移可逆。**staged drift：**
快照侧零漂移，packages/contracts 侧 6 条待 B1 镜像——B1 合入即双源绿）。
B1 进行中。

## A（backend）

### A1 迁移与契约代码化（与 B1 同批）

- 迁移（up→down→up 必跑）：`agent_runs`、`pending_actions`、
  `chat_sessions`、`chat_messages`、notification preferences；
  PermissionGrant 软撤销（`revoked_at` 回填，DELETE 语义改造）；
  Memory `content_revision`（前缀排序键——若现有版本链无对应列则补）。
- ACTION_POLICY 新行（`materials.answer`、`task.update` 等）+
  `focus.start` 校正 L2；Pydantic schema + OpenAPI 导出。
- 验收：drift 双源绿、`alembic check` 无漂移、迁移可逆、用户隔离
  P0 测试在场。

### A2 运行时与同意门禁（核心切片）

- 工具注册表 + 权限拦截单点（收紧语义：L3 grant 仅自动执行 L3
  声明动作）；确定性 runner（lease/heartbeat/watchdog、先查下游
  幂等键再结算）；pending_actions 状态机（8 态、CONFIRMED 不过期、
  mutation 响应缓存）。
- 上下文装配 manifest（token 预算、content_revision 排序、untrusted
  边界、会话近史段、逐字节 fixture 断言）。
- **全局「Agent 模型上下文」同意门禁**（形状冻结、默认关）——未落地
  前任何 provider 调用不得携带 CurrentState/Memory/chat。
- audit 递归白名单脱敏（`redact()` 升级）；provider tool-call
  capability（4 turns/8 calls/token 上限、`result.degraded`）。
- 验收：A 契约 §9 最低回归集（跨用户隔离、L0-L3 矩阵与过期/撤销
  Grant、并发确认恰一次、retry 同参幂等、快照排序稳定与截断、资料
  隔离与断供降级、审计无秘密/原文、FTS 只返原消息、同 trigger 去重）。

### A3 检索与主动接线

- pg_trgm 扩展 + conftest 预装（#35 先例）+ chat search（<3 字符
  过滤降级）+ 消息删除同步移除检索资格。
- replan_triggers 接线主动 run（`trigger_signature` 去抖、打扰预算
  按用户本地日原子结算、Level 1 建议与 L3 通知分流）。

## B（client）

### B1 共享 Zod + 客户端方法（与 A1 同批，冻结进库）

- Zod：`DecisionBasis`（含 `selected_tool_call_ids`）、
  `PendingActionRead`（`expires_at` 非空）、`AgentRunRead`（含
  `tool_calls[]` 逐字段镜像）、`NotificationPreferences`（含
  `budget_date`/`last_sent_at`）、chat session/message 形状。
- BackendClient 方法 + mocks；与 A1 OpenAPI 对齐，drift 双源绿。

### B2 视图族

- `DecisionBasisView`（兼容 `BasisPanel` 历史形状；references 含
  `chat_message`/`current_state` kind 的定位渲染）→
  `PendingActionCard/List`（8 态呈现、409 refetch、mutation 防双击、
  仅 PENDING 显示倒计时、用户自致失败子码单列文案、`task.update`
  旧→新渲染）→ Chat 骨架（202+轮询、搜索、消息删除、断供明确失败
  面）→ 通知偏好面（预算/免打扰数值控件）。
- 离线纪律：确认请求不排队、不伪造本地成功（契约 §7 表）。

### B3 E6 出口 e2e

- 按契约 §8 六场景（构建包/CDP + 录制回放或真实 Backend）：重排
  建议依据 → Chat 建议任务 → Level 2 卡片 → 「为什么」basis →
  并发确认恰一次 → 断供降级 → 预算/免打扰 + L3 grant。

## 门禁与验收

1. B1/A1 先合（契约代码化对齐），A2 门禁未解除前不接任何真实
   provider 工具调用。
2. 每切片独立 PR、交叉审、CI 12/12 + 相关测试绿。
3. M4 出口（D-030 口径）：E6 全绿 + 断开模型供应商后计划与重排
   建议仍工作。
