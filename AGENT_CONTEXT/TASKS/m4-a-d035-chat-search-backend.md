# M4 · A 侧切片：D-035 Chat 检索后端实施

决策依据：DECISIONS.md **D-035（accepted）** 第 6 点实施分侧中的 A 侧。
分支 `feature/m4-d035-chat-search`，自 `72d42a3`（main）。

## 目标

落地 D-035 冻结的后端检索面：`ChatMessageRead.session_id`（必发）、
全局检索面 `GET /v1/chat/search?q=&session_id?=&limit=&cursor=`
（结果项 `ChatSearchItem` = `ChatMessageRead` + 扁平 `session_title`），
并移除 A3 的会话内子路径（端点收口，唯一非加法项，B 已 ack）。

## 输入

- D-035 冻结文本（q/keyset/可见性/降级语义逐字沿用 A3）。
- A3 现实现：`backend/api/v1/chat.py` 的子路径检索 + pg_trgm 资格模型
  （`deleted_at` / 归档级联，已在 main）。

## 输出

- `backend/schemas/chat.py`：`ChatMessageRead` += `session_id`；新增
  `ChatSearchItem`。
- `backend/api/v1/chat.py`：`GET /chat/search`（限域 `_session_or_404`
  纪律；全局域 = 本人未归档会话的子查询 IN，保持 user_id 无 join 隔离
  不变量；命中行批量补 session title）；子路径路由删除。
- `openapi.json` 重导（A 先行；drift 检查为 Zod→OpenAPI 单向，B 侧
  `ChatMessageSchema` 加必填 `session_id` 前保持绿——D-035 排序规则）。
- `tests/integration/test_m4_retrieval.py`：A3 检索测试迁移到全局面 +
  新增跨会话/title 加富/未知限域 404/跨用户全局隔离/子路径移除断言。

## 负责范围

仅后端 API 形状 + OpenAPI 工件 + 后端测试。零 schema/迁移变更。

## 不负责范围

- B 侧：Zod 镜像（`ChatMessageSchema` += `session_id`、新增
  `ChatSearchItemSchema`）、`ZOD_TO_OPENAPI` 的 `ChatSearchItemSchema`
  映射登记（与 B 的 Zod schema 同批落）、客户端 `searchChatMessages`
  方法与检索 UI。
- 相关性排序 / 服务端分组聚合 / 跨域检索（D-035 非目标）。

## 验收标准

1. `GET /v1/chat/search` 限域与全局双域行为符合 D-035 第 2 点
   （q 规则 422、通配字面化、<3 字符降级、newest-first keyset、
   软删/归档双域不可见、跨用户隔离、未知/他人/归档限域 404、
   命中带 `session_id` + 当前 `session_title`）。
2. 子路径 `GET /v1/chat/sessions/{id}/messages/search` 404（收口坐实）。
3. 消息流面（列表/发送响应路径）消息体带 `session_id`。
4. `check_contract_drift --require-zod` 双源绿；`openapi.json` 与生成
   一致。
5. 全量 pytest / ruff / format / pyright 绿；零迁移文件变更。
