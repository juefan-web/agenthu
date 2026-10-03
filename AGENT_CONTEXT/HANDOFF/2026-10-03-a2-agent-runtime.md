# A2 任务边界：Agent 运行时与同意门禁（2026-10-03 立项）

依据：`TASKS/m4-implementation-slices.md` A2 + 契约 v3（D-034）§2.5/§3/§4/§5/§6。
分支 `feature/m4-a2-agent-runtime`（自 `523023a` 拉出；#52 合并后改基 main）。

## 目标

后端 Agent 运行时最小闭环：注册表驱动的工具执行、收紧后的权限单点、
确定性 runner（lease/watchdog/幂等结算）、pending_actions 8 态 mutation 面、
上下文装配 manifest、全局模型上下文同意门禁（默认关）、递归审计脱敏、
provider 能力协商与 4 turns/8 calls/token 上限。

## 输入

A1 落库的五表 + ACTION_POLICY 17 行 + 软撤销语义；M3 grounded 管线
（materials.answer 复用）；planner/replan_triggers（确定性兜底）；
memory_retrieval（§5 语义）；B1 在库 Zod（请求形状字段级对齐：
`PendingActionMutation{expected_version, mutation_id}`、
`ChatSessionCreate{title?, client_request_id?}`、
`ChatMessageSend{content, client_message_id?}`）。

## 输出（文件面）

- `models/consent.py`（model_context_consents，镜像 grounding_consents）+
  `models/agent.py` 增 `PendingActionMutation`（响应缓存）+ 迁移 up/down/up。
- `services/permissions.py` 收紧（L3 grant 仅自动执行 L3 声明动作；L2 永远
  逐次确认；通配不再越级）。
- `services/tool_registry.py` + `services/agent_tools.py`（注册表 + 首批工具
  实现 + display_builder + scope 校验）。
- `services/context_assembly.py`（§6.1 顺序/预算/截断/rendered_context_hash/
  consents 记录；同意门禁在此强制）。
- `services/agent_runner.py`（claim/lease/heartbeat、确定性优先执行、
  tool-call 循环上限、终态结算、watchdog 回收、同事务审计）。
- `api/v1/pending_actions.py` 增 confirm/ignore/retry（mutation 响应缓存、
  FOR UPDATE、409 语义）；`api/v1/chat.py` 增 POST sessions/messages（202、
  消息级幂等、run 创建）；`api/v1/model_context_consent.py` GET/PUT。
- `services/audit.py` redact 递归化 + agent 路径白名单。
- `adapters/model_provider`：capabilities + generate_with_tools/
  continue_with_tool_results（OpenAI 实现尽力，测试用注入 fake）。
- `worker/tasks.py`：execute_agent_run + sweep_agent_runtime cron。
- `tests/integration/test_m4_runtime.py`：§9 最低回归集之 A2 面。

## 不负责范围

pg_trgm/FTS/searchChat、触发器接线与打扰预算结算、消息删除（A3）；
UI/B2；e2e E6（B3）；M5 保留期。未实现执行器的已注册 L2 工具
（calendar.write/message.send/file.delete/data.delete）以
`tool_not_implemented`（不可重试）诚实失败，不伪造成功。

## 验收标准

1. 同意关 ⇒ 零 provider 调用（按 fake 计数断言），run 仍可经确定性
   plan.suggest 成功（degraded=model_consent_missing）——M4 出口判据的服务端面。
2. L0–L3 矩阵 + 过期/撤销/通配越级 grant 全 deny-or-confirm；scope 未命中
   的 L3 grant 不自动执行。
3. 并发 confirm 恰一次；同 mutation_id 重发返回缓存响应；retry 同 key 幂等。
4. 同输入 ⇒ 逐字节相同装配与 rendered_context_hash；超预算整段丢弃并计数。
5. PENDING 过期收敛 EXPIRED（CONFIRMED 不）；lease 过期 watchdog 结算 +
   attempt+1；审计（详情键扫描）无秘密/资料正文/聊天正文。
6. chat 202 + 同 client_message_id 重发同 attempt；跨用户隔离 404。
7. CI 12/12 + drift 双源绿 + 迁移 up/down/up + alembic check。

## 交付记录（2026-10-03 深夜）

以上边界全部落地，分支 `feature/m4-a2-agent-runtime`（自 `523023a`）。

**实现面**（新增 `backend/services/{tool_registry,agent_tools,context_assembly,agent_runner,model_consent}.py`、`models/consent.py`、`schemas/consent.py`、`api/v1/model_context_consent.py`、迁移 `a7d1c93f4e20`；改 permissions/audit/chat/pending_actions/config/worker/provider 协议；测试 `tests/integration/test_m4_runtime.py`）。

**验收对照**（§边界验收标准逐条）：

1. 同意关 ⇒ fake provider 调用计数恰为 0；run `SUCCEEDED` +
   `degraded=true, degrade_code=model_consent_missing`；确定性
   plan.suggest/replan.evaluate 照常执行（`test_consent_off_zero_provider_calls_deterministic_plan`）。
2. L0–L3 矩阵：`plan.*` L3 通配 grant 不再放行 `plan.confirm`（granted_level=3 可见但不提升）；notify.push 空 scope/通配 scope/过期/撤销全 deny，仅有效 scoped L3 grant ALLOW（矩阵测试 + `/permissions/check` 集成测试随语义更新——M0 越级断言按 D-034 §2.5 改写）。
3. 并发确认恰一次：confirm 内联派发走原子 claim（FOR UPDATE SKIP LOCKED），双 confirm/重发同 mutation_id 均恰一次副作用；mutation 响应缓存表落库。
4. 逐字节装配：同输入 ⇒ 相同 rendered_context_hash；memory 按 (kind, subject_key NULLS LAST, content_revision, id) 稳定序；超预算整段丢弃并计 dropped（closing 永不丢）。
5. PENDING 过期读路径+worker 收敛 EXPIRED；CONFIRMED 永不过期；EXECUTING 租约回收 → 同 key FAILED_RETRYABLE；RUNNING 租约过期 watchdog 结算 + attempt+1。
6. chat 202 + 同 client_message_id 重发同 run/message；跨用户 404。
7. 全套：329 passed 1 skipped、ruff/format 干净、pyright 0、迁移 up/down/up + alembic check 绿、drift `--require-zod` 双源绿（新增 ChatMessageSendResponse 映射）。

**诚实降级**：无投递通道的 notify.push 只记 audit + 结果标注 "delivery channel lands with A3 wiring"，不伪造外部送达；未实现执行器的四个 L2 工具 FAILED/tool_not_implemented（不可重试）；装配层 chunk 段 A2 留空（grounding 走 materials.answer 工具自带 M3 管线闸），manifest chunk_refs 结构在位。

**已知留待**：A3（pg_trgm/搜索/删除失效/触发器接线/打扰预算结算）、B2（视图族含同意 UI 的 GET/PUT 消费）、B3（E6）。
