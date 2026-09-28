# 客户端 ↔ Backend 联调问题清单（给开发者 B）

审查人：开发者 A（Backend）  
Backend 基线：`m0/backend-foundation` @ `c130400`（含去重转义对齐 + 快照刷新）  
客户端基线：`feature/client-tauri-campus-adapter` @ `c581226ca702ba66a484576547bc37bc893a2e0f`

## 0. 已验证契约对齐（先看结论）

用 Backend 的漂移检查器直接跑客户端**真实**契约文件：

```bash
python -m backend.scripts.check_contract_drift \
  --zod packages/contracts/src/index.ts
# => No contract drift detected
```

已确认对齐、无需改动：

- 端点与 `/v1` 前缀：`/v1/auth/{register,login,me}`、`/v1/events/batch`、`/v1/tasks`、
  `/v1/current-state`、`/v1/plans/today`、`/v1/plans/{id}/confirm`、
  `/v1/focus-sessions`、`/v1/focus-sessions/{id}`。
- Auth 形状：`Token{access_token,token_type,expires_in}`、`UserRead{id,email,display_name,is_active}`
  与 `TokenSchema`/`UserSchema` 一致；`Authorization: Bearer` + `credentials:"omit"` 符合 D-018。
- Event/Task/CurrentState/Plan/Focus 的字段、枚举、nullability 与 `packages/contracts` 一致。
- Focus 完成不传 `actual_minutes` 是**允许**的：Backend `_complete` 会用 `started_at → now`
  计算（`backend/services/focus.py`）。客户端多传的 `ended_at` 会被忽略，不影响。
- CORS 默认源（`localhost:5173`、`127.0.0.1:5173`、`tauri://localhost`、`http://tauri.localhost`）
  与 `tauri.conf.json` 一致。

> Backend 已修复：OAuth2 `tokenUrl`、OpenAPI/Zod CI 漂移检查、Event 去重键 `\`/`:` 转义。
> 客户端 `AGENT_CONTEXT/CURRENT_STATE.md`（09-27）里把这几项列为 A 的“下一步”，现已过时，请更新。

---

## P1-1（B）Tauri CSP 会拦截对 Backend 的请求

- 位置：`apps/desktop/src-tauri/tauri.conf.json:23`
- 现状：`connect-src 'self' https: http://localhost:5173`
- 证据/影响：若配置 `VITE_BACKEND_URL=http://localhost:8000`（或 `http://127.0.0.1:8000`），
  打包后的 Tauri WebView 在生产构建中注入该 CSP，`fetch` 会被 `connect-src` 拒绝；验收项恰好是
  “Windows 构建包完成一次闭环”。`https:` 只覆盖 https 后端。
- 建议：
  - 把本地后端源加进 `connect-src`（例如 `http://localhost:8000 http://127.0.0.1:8000`），
    或让联调后端走 https。
  - 在仓库提供 `.env.example`，写明 `VITE_BACKEND_URL`（当前无任何文档，空值时后端功能整体禁用，
    见 `apps/desktop/src/App.tsx:16-17`）。
- 验收：`pnpm build` 后用 `VITE_BACKEND_URL=http://127.0.0.1:8000` 启动构建包，Backend 登录/取数
  成功且 DevTools 无 CSP violation。

## P1-2（B）被拒绝的 Event 永久堵在本地队列

- 位置：`apps/desktop/src/sync/coordinator.ts:23-45`
- 现状：`flush()` 只 `queue.remove([...accepted, ...duplicate])`，**`rejected` 不移除**。
- 证据/影响：
  - 被拒事件每次 flush 都重传、再被拒，`pending` 永不归零，UI 一直显示“N 条待同步”。
  - Backend 的敏感字段规则比客户端更严：`backend/core/sensitive.py` 额外拦截 `pwd`、`secret`、
    `api_key`、`client_secret`、`id_token`；客户端 `assertSafeEvent` 放行的事件仍可能被后端拒绝。
    再叠加大小（256 KiB）/深度（20）上限，命中即毒化队列。
- 建议：收到 `rejected` 后把对应 `client_event_id` 移出队列（或写入隔离区并展示 `reason`），
  不要让它们无限重试。
- 验收：构造一个必被拒的事件（如 `data` 含 `secret` 键），`flush()` 后队列不再包含它，
  UI 能提示原因；`pending` 可归零。

## P2（A 已处理，B 仅需确认）Event 去重键转义

- Backend `compute_dedupe_key` 现在与 `eventDedupeKey` 逐字节一致：`\` → `\\`、`:` → `\:`
  （`backend/services/events.py`，D-010）。
- 请确认客户端不依赖旧的无转义格式（客户端从不发送自己的 key，理论上无影响）。

---

## P3-1（A+B，契约变更）计划项在 UI 显示 UUID

- 位置：`apps/desktop/src/App.tsx:280`（`<strong>{item.task_id}</strong>`）
- 原因：冻结契约 `PlanItemSchema` 只有 `task_id/start_at/end_at/reason`（`packages/contracts/src/index.ts:59-64`），
  没有标题。Backend 实际会额外返回 `title`（`ClientPlanItem.title`），但被 Zod strip 掉。
- 建议：给 `PlanItemSchema` 增加 `title: z.string()`（可再加 `planned_minutes`）。这是 D-009 冻结契约
  变更，需 A/B 同步：B 改 `index.ts`，A 更新 OpenAPI/快照，然后双方各跑一次漂移检查。
- 验收：今日计划列表显示任务标题而非 UUID。

## P3-2（A+B）`next_cursor` 是假游标

- 位置：`backend/api/v1/events.py:84`（`next_cursor=payload.client_cursor` 原样回显）
- 影响：客户端存下游标再传回，游标永不前进；无功能故障，但“增量同步游标”语义为空。
- 建议：要么实现真正的 `next_cursor`（例如基于事件时间/序号），要么从契约与 UI 中移除，避免误导。
- 验收：文档明确游标语义；若保留，服务端返回值在多次同步间会前进。

## P3-3（B）`updateFocus` 的字段语义

- 位置：`apps/desktop/src/backend/client.ts:107-113`、`App.tsx:315`
- 现状：PATCH 只发 `{status, deviation_note, ended_at}`；`ended_at` 被 Backend 忽略
  （`FocusSessionUpdate` 只接受 `status/actual_minutes/deviation_note`，Pydantic 默认忽略额外字段）。
- 影响：当前无故障（后端自己算 `actual_minutes`）。若产品需要“手动填写实际时长”，应显式发送
  `actual_minutes`；否则可在 PATCH 里去掉无效的 `ended_at` 以免误读。
- 建议：明确产品语义后二选一，并在 `client.test.ts` 覆盖。

---

## 建议处理顺序

1. P1-1 CSP + `VITE_BACKEND_URL` 文档（否则打包验收无法进行）。
2. P1-2 队列 rejected 处理（否则真实采集会产生“幽灵待同步”）。
3. P3-1 `PlanItem.title` 契约变更（先双方确认再改，一起跑漂移检查）。
4. P3-2 / P3-3 语义收敛。

完成后建议做一次联合验收：启动真实 Backend（`docker compose up -d db redis` + `uvicorn`），
配置 `VITE_BACKEND_URL`，走一遍
`登录 → 采集 Event → 同步 → Task/Plan → 确认计划 → Focus 完成 → 结果回写`，
并确认 `pnpm --filter @agenthu/contracts test`、`pnpm typecheck`、Backend `pytest` 全绿。
