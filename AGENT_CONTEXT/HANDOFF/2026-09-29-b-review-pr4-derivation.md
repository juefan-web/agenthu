# 开发者 B：PR #4（D-028 派生实现 + B-4 拍板）审查记录

审查人：开发者 B（Client / Study + Time）· 2026-09-29 · 审查对象
`feature/assignment-event-derivation` @ `6e8872a`（PR #4，D-028 阶段 0 的实现侧）。

## 结论：**Approve**（无阻塞意见；三条备注见下，其中 #1 建议 D-028 文本勘误）

## 逐项核对（按指定审查重点）

1. **naive 拒收与客户端队列的交互（重点①）**：边界拒收作用于两处——单发
   `POST /v1/events`（422）与批量 `ingest_event_batch`（envelope 进 `rejected`、
   不入库、reason 注明 D-028）。客户端侧交互核对：
   - 批量路径的 `rejected` 会被既有协调器移出队列并把 reason 透出 UI（merge-1
     语义，有回归测试）——**注意**：这与 D-028 §3a 的措辞「留在客户端队列等
     B 修复后重发」不一致，见备注 #1。
   - **无锁死**：被拒事件从未入库，服务端 dedupe 无记录；B 修复后重新采集会以
     同一 upstream 身份重新生成（新的 semantic_version → 新 client_event_id），
     正常派生。旧 naive 事件的恢复路径 = 再采集，而非队列续传。
2. **`TaskRead` 新字段（重点②）**：`source_upstream_id` 为 backend-only
   addition，`TaskCreate` 不收（上游身份只属服务端派生）✓；客户端 Zod 默认
   strip 未知键，契约无破坏 ✓。**缺口**：`ClientTask`（`/v1/tasks` 的客户端
   形状）没有 `source` 字段——「派生任务来源可辨识」的 UI 呈现（如「校园」
   徽标）拿不到数据，见备注 #2。
3. **派生 handler**：upsert 键 `(user_id, source, source_upstream_id)` 与 D-028
   §2 一致；COMPLETED 粘性（C2 语义）；handler 在 savepoint 内（C1 语义，
   失败审计 `event.handler_failed`）；`extra` 保留 `deadline_raw`/
   `late_deadline_raw`/`publish_time` 溯源 ✓。标题缺省回退 upstream id ✓。
4. **迁移**：`b1d4a7c90e12` up/down 对称，唯一约束多 NULL 放行手动任务 ✓。
5. **测试**：6 个派生用例覆盖冻结全分支（tz-aware 落库、updated 不重复建、
   submitted 粘性、双边界 naive 拒收、并发同键恰好一个 Task、真实载荷回放）
   + 主链测试更新（派生任务与手动任务并存断言）✓。
6. **B-4 拍板**：已读（`client-m1-hardening.md` 末节）。同意原生受控转发形态
   与边界条件（Rust allowlist 唯一事实源、头白名单、无 Set-Cookie 透传、本地
   http 例外、CSP guard 维持）。B 按此开工，无需再等拍板。

## 备注（不阻塞合并）

1. **D-028 §3a 文本勘误建议**：决策写「留在客户端队列等 B 修复后重发」，但
   客户端对 `rejected` 的既有（且经测试的）行为是**移出队列并透出原因**——
   实际恢复依赖再采集。行为本身是对的（naive 事件留着只会反复被拒），建议
   把决策文本改为「留在客户端可再采集的范围内，恢复依赖重新采集（同
   upstream 重新生成，无服务端锁死）」，避免后人按字面实现「保留重发」的
   特殊分支。
2. **`ClientTask` 补 `source`**：一行 backend-only addition 即可解锁「来源作业
   可辨识」的 UI（B 侧同步在 Zod 加 `source: z.string().optional()`，等 A 的
   OpenAPI 更新后 drift 自然对齐）。可入本 PR 或后续小 PR。
3. **双层一致性确认**：边界对 deadline 类字段的不可解析串与非字符串值同样
   拒收（"not a valid ISO-8601 datetime"），handler `_parse_tzaware` 的 None
   回退实际只覆盖「字段缺省/显式 null」——两层语义闭合，无不对称漏洞
   （handler 侧的防御保留为纵深，正确）。

## B 侧随附（本分支 `feature/m1-1-client-tz-events`）

- `events.ts`：deadline/late_deadline/publish_time 三字段转 `+08:00` tz-aware
  ISO，原串保留 `*_raw`（D-028 §3 客户端侧）；`asIso` 的 `new Date()` 本地
  时区依赖一并修复（date-only 按北京零点、naive 日期时间按 +08:00 解释，
  OS 非北京时区不再偏移）。
