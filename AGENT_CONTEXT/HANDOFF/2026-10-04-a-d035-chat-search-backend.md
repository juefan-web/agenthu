# Handoff · 2026-10-04 · A：D-035 Chat 检索后端切片

分支 `feature/m4-d035-chat-search`（自 main `72d42a3`）。D-035（accepted）
第 6 点 A 侧范围，全部完成。

## 交付

1. **`ChatMessageRead` += `session_id`（必发）**——消息自带会话定位；
   唯一构造点 `_message_read` 已带上；消息流/检索一切出现处生效。
2. **全局检索面 `GET /v1/chat/search`**（`backend/api/v1/chat.py`）：
   - `q` 1–200，strip 后空 → 422；ILIKE 字面子串 + autoescape 通配
     字面化；pg_trgm ≥3 字符加速、<3 降级过滤（A3 逐字沿用）。
   - `session_id` 限域：`_session_or_404`（未知/他人/归档一律 404，
     与消息流同纪律）；省略 = 全局（本人全部未归档会话，子查询 IN，
     保持「消息过滤自带 user_id 不依赖 join」的 P0 隔离不变量）。
   - newest-first `(created_at, id)` keyset + `Page{items, total,
     next_cursor}`；软删消息与归档会话双域不可见。
   - `ChatSearchItem` = `ChatMessageRead` + 扁平 `session_title`（命中
     行批量一次 IN 取当前 title；构造复用 `_message_read`，basis/
     pending 投影不重复实现）。
3. **子路径移除**：`GET /v1/chat/sessions/{id}/messages/search` 路由
   删除（端点收口，D-035 唯一非加法项，B 在 #57 评审已 ack）。
4. **`openapi.json` 重导**：61 paths；`ChatSearchItem` 组件在场。
   drift 检查为 Zod→OpenAPI 单向（check_contract_drift 只遍历 Zod
   字段对 OpenAPI），A 先行加必填字段保绿——D-035 排序规则的机制
   前提，`check_contract_drift --require-zod` 实测绿。

## 测试（`tests/integration/test_m4_retrieval.py`，12 passed）

- A3 三测试迁移到全局面（限域语义不变），并各加双域断言：删消息后
  全局也不可复现；归档会话限域 404 + 全局 0 命中。
- 新增：跨会话 newest-first + 每行 `session_id`/`session_title` 加富
  + 跨会话 keyset；未知 `session_id` 404；跨用户限域 404 + 全局 0
  命中（存在性不泄露）；子路径 404（收口回归钉死）；`session_id`
  字段在命中行与消息流面均在场。
- 全量 342 passed / 1 skip 之外零失败；ruff·format·pyright 0；零
  schema/迁移变更（diff 四文件：chat API、schema、openapi.json、测试）。

## B 侧接力（同批配对，按 D-035 排序规则）

- `ChatMessageSchema` += 必填 `session_id`（本切片合入后落，drift 保持
  绿的窗口即打开）；新增 `ChatSearchItemSchema`（复用 CursorPage）；
  **`ZOD_TO_OPENAPI` 的 `ChatSearchItemSchema` 映射登记随 B 的 Zod
  schema 同批**（登记时 Zod 侧必须已在场，否则 drift 硬红——本切片
  有意不碰映射表）。
- 客户端 `searchChatMessages({q, sessionId?})` + 检索 UI 接线（命名归
  B 约定）。

## 同轮其他动向（非本切片）

- **#58 复核（绑 `c6dfac2`）**：三必改全部对码核实修对；新必改 4 =
  seeding 终点不打脏标的 cron SPOP 竞态（全链证据：`mark_user_dirty`
  仅 `api/v1/tasks.py:66` 与 `services/events.py:152` 两处；plan
  confirm/PATCH item 只走 `recompute_current_state` 不 SADD；cron 每
  30s SPOP 消费不回补），修法 A/B 二选一已给，CHANGES_REQUESTED。
- #59 已获 B approve（延续协议注记在评审里），待协调人合。
