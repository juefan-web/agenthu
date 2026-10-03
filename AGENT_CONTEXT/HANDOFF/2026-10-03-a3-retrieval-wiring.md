# A3 检索与主动接线（任务边界与交付记录）

- 分支：`feature/m4-a3-retrieval-wiring`（自 main `8d47781` = #54 合并点拉出）
- 切片：`TASKS/m4-implementation-slices.md` A3 + 协调人裁定附件（202 字面量抽取归 A3；服务端细分码可选）
- 上游依据：D-034（pg_trgm 取代 tsvector、<3 字符过滤降级、conftest 预装）、契约 §6（预算/免打扰/分流）、§2（history = 含 L3 自动动作与通知投递结果的用户账本）

## 目标

1. chat DELETE 双端点（会话/消息，对齐 B1 冻结的 client 调用形状：会话嵌套路径、消息扁平路径）+ 删除即失检索资格（同事务）。
2. pg_trgm 扩展 + chat_messages GIN trgm 索引 + 站内会话消息搜索端点（形状冻结进 OpenAPI；<3 字符走无索引子串过滤，结果仍正确）。
3. replan_triggers 接线主动 run：触发器命中 → QUEUED `proactive_trigger` run（`trigger_ref.trigger_signature` 去重，双保险 = `uq_agent_runs_active_trigger` 活跃态部分唯一 + `uq_agent_runs_op_attempt` 操作键唯一）。
4. 打扰预算结算：notify.push 执行时刻按用户本地日原子结算（类别开关 → 免打扰 → 每日预算三重门），L1 建议免费呈现（既有 ReplanSuggestion 面）、L3 通知消耗预算——即「分流」。
5. 顺带：chat.py 的 202 公式字面量抽公共函数（B 评审备注）。

## 输入

既有触发引擎（`replan_triggers.py`，4 类触发 + 签名幂等 + 30 分钟限频）、`drain_trigger_evaluation` cron、A2 runner（chat 解耦已就位：非 chat 运行 `_chat_context` 返回 None）、`NotificationPreference` 冻结表（结算字段 server-owned）、notify.push 工具注册（L3、执行器现为诚实占位）、B1 在库 client 的 DELETE 调用形状。

## 负责范围

backend：迁移（扩展+索引）、chat API 三个新端点、搜索、通知预算结算服务、notify.push 执行器真实化、主动 run 排队与确定性结算、worker 接线、conftest 预装、回归测试、OpenAPI 导出与 drift。

## 不负责范围

- 客户端视图/契约镜像（B 域；搜索端点的 Zod 镜像由 B 后续批次冻结，本次不动 `packages/contracts`——避免与 #55 rebase 撞文件）。
- 通知的外部推送基建（无 FCM/WebSocket；契约 §2 裁定 pending-actions `history` 即用户可见投递账本，prefs 计数器为 E6 可观测面）。
- 服务端细分失败码（裁定为可选；客户端超集方案已覆盖今天的诚实呈现，本次不做，零现时消费者不改词汇表）。
- 跨会话搜索（需要 ChatMessageRead 增 session_id 或新 schema——契约演进应与 B 同批冻结，本次只做会话内搜索）。

## 关键实现裁定（写码时生效）

- 会话删除 = 软删级联：session.archived_at + 全部未删消息 deleted_at 同事务置位；归档会话不入列表、其消息不可读不可搜。
- 搜索 = `content ILIKE '%q%'` 过滤 + gin_trgm_ops 索引加速（trgm 对 CJK 子串匹配的标准用法）；≥3 字符可走索引，<3 字符无 trigram 退化为顺序过滤（结果仍正确）——即 D-034 的「过滤降级」；排序沿用 (created_at, id) keyset，不做相似度排名（分页稳定性优先）。
- 主动 run 的 operation_key = `trigger:{trigger_signature}`；确定性结算（无同意/无 provider）也要产出 notify.push pending action（无 grant → PENDING 待确认；有有效 grant → CONFIRMED 自动执行），预算在**执行时刻**结算而非创建时刻（创建免费、投递付费）。
- 抑制（suppressed）不是工具失败：pending action 结算 SUCCEEDED，result.summary 如实写「已抑制（原因）」，审计记 notification.suppressed。

## 验收标准

- 全量回归绿（pytest/ruff/pyright/迁移 up-down-up/alembic check/drift --require-zod）。
- 新增回归钉死：DELETE 语义（含级联/幂等/跨用户 404/检索资格同事务丧失）、搜索（CJK 匹配/<3 降级/删除排除/跨用户 404/keyset）、触发→run 去重（同签名不双跑）、预算三重门与本地日翻转、L3 grant 自动执行 vs 无 grant PENDING、免打扰跨午夜窗口。

## 交付记录（2026-10-03 深夜）

- 分支 `feature/m4-a3-retrieval-wiring`（自 `8d47781`），单批次交付。
- 验证：全量 pytest **331 passed / 8 skipped**（7 = conftest 深夜时间窗守卫、1 = 既有 S3 环境跳过；新 A3 回归 9 项全绿）；ruff + format 干净；pyright 0 错；迁移 `c4f2a8e01d73` scratch 库 up/down/up + `alembic check` 零漂移；OpenAPI 重导（61 路径，+290 行）+ drift `--require-zod` 双源绿。
- **验收映射**：DELETE 语义（级联软删/幂等 204/跨用户 404/检索资格同事务丧失）→ `test_delete_*`；搜索（CJK 子串/<3 降级/通配字面化/keyset/越权 404/畸形 422）→ `test_search_*`；去抖（同签名永不二跑，终态后也不）→ `test_queue_proactive_run_dedup_per_signature` + `test_engine_trigger_queues_run_and_refire_dedups`；主动结算与分流（无 grant→PENDING→确认→抑制如实；有 grant→自动执行→预算真实记账→耗尽拒绝不记账）→ `test_proactive_*`；预算三重门/跨午夜/本地日翻转/无行=全关 → `test_settlement_*`。
- **超出边界文档的一处必要修复**：`dispatch_confirmed_action` 的 L3 grant 复验原对所有 L3 生效，把「用户逐次确认的无 grant 动作」也拒成 `permission_denied`——与 `evaluate_permission` 的 `requires_confirmation` 语义矛盾（A2 缝隙，A3 的 no-grant→confirm→deliver 路径首次踩中）。修复：复验仅当 `grant_snapshot` 非空（grant 确认路径，§5.1 原意）；用户确认路径的授权就是确认本身。A2 既有 fail-closed 测试（grant 创建后撤销→denied）不受影响，29/29 绿。
- 遗留观察（非阻塞，待裁定）：L3 grant scope 的 `strict_scope_validator` 只做形状校验——`categories: ["deadline"]` 的 grant 会自动执行 `category: "replan"` 的推送（A2 冻结语义 + 现有 scope matrix 测试钉死该行为）。预算/偏好门仍兜底。若收紧为「args.category ∈ grant scope.categories」，属 A2 语义变更，需协调人裁定后单独落。
- 未做（按裁定/边界）：服务端细分失败码（可选项；客户端超集已覆盖）；跨会话搜索与 `ChatMessageRead.session_id`（契约演进应与 B 同批冻结）；外部推送基建（契约 §2：pending-actions history 即投递账本）。
