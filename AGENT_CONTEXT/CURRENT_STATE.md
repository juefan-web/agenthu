# 当前进度（2026-09-27）

## 开发者 B：客户端与校园适配

目标：先建立 Windows 上的 Study + Time 客户端路径。输入为 OneTHU 固定版本的课程、作业、课表和校历；输出为带来源的 Event、Backend 任务/计划展示及 Focus 操作。开发者 B 不修改 Backend 数据库或 Agent 决策。

已实现 React/Vite/Tauri 2 工程、共享 Zod 契约、vendored `@onethu/core`、`CampusAdapter`、Event 映射、Tauri 网络 transport、SQLite 待同步 Event/游标及 Focus 草稿命令、Backend API 客户端以及 Today/任务/Focus 工作台。Event 去重键为 `source + upstream_id + semantic_version`，连接器版本独立记录。Focus 草稿经 Zod 校验，客户端重启后可恢复，并可手动清除。本机 `pnpm lint`、`pnpm typecheck`、`pnpm test` 和 `pnpm build` 已通过；新增 Windows CI 执行这些检查和 Rust `cargo test`。

客户端耗时排查已确认 Tauri transport 原先每请求新建 HTTP Client，且每个响应都把会话快照重新写入 Stronghold；后者会阻塞请求热路径。现按会话复用重定向策略对应的 Client，登录成功时由显式 `campus_save_session` 保存快照，普通校园请求只在内存更新 Cookie，不再同步写 Stronghold。采集流程用校历学期 ID 取课程，省去重复学期请求，并让课表与课程/作业链并行；UI 分开显示采集、保存和同步阶段及完成耗时。登录后的身份探测仍保留。测试覆盖快照未变/变化与采集并行顺序。真实校园网络和账号下的登录、2FA、采集耗时尚未重新测量；OneTHU 仍会为每门课请求三类作业，上游延迟可能占主导。

本轮风险修复：校园请求完成后会按快照内容变化持久化刷新 Cookie；LocalEventQueue 分别恢复 events/cursor，损坏内容写入隔离备份；Event 去重键对反斜杠和分隔符转义，避免字段碰撞。对应回归测试已加入；Rust 与 TypeScript 编译验证通过。

本轮完成 Backend JWT 客户端会话：`createBackendSession` 独立管理 Backend Token，与校园会话隔离；请求通过 `BackendClient` 统一注入 Bearer Token。登录先用 `/v1/auth/me` 验证候选 Token，再写入 TokenStore；验证失败或持久化失败时恢复旧 Token 和 UI 状态。重启恢复会跳过过期 Token、处理 `/me` 401，并对 TokenStore 读写/清理失败给出可见错误且不产生未处理拒绝。401 清理与 `restore/login/logout` 操作串行化，旧请求迟到时不会清除新会话；普通请求的 401 清理失败也有回归测试。新增 LocalTokenStore 与会话回归测试；本机桌面端 8 个测试文件、37 个测试、lint、typecheck 和 build 已通过。

## 尚未满足的验收项

- 真实校园账号登录、2FA、会话恢复和失效重试仍需在构建后的 Windows 客户端中人工验收；当前已有 OneTHU 认证适配、Stronghold 加密快照和脱敏状态测试。
- Rust SQLite 待同步 Event 与 Backend 对账、冲突提示和 Focus 偏差重规划依赖开发者 A 的最终契约与实现。
- `VITE_BACKEND_URL` 未配置时客户端可展示本地状态，但无法读取 Backend Current State、Task 和 Plan。
- 还需要 Testing Library 和 Playwright 用户流程测试，以及 Android 凭据存储、通知和同步恢复。
- 发布前仍需完成 OneTHU BSL 1.1、LearnX 及依赖许可的逐文件分发审查。

## 开发者 A 需要冻结的接口

`POST /v1/events/batch`、`GET /v1/current-state`、`GET /v1/tasks`、`GET /v1/plans/today`、`POST /v1/plans/{plan_id}/confirm`、`POST /v1/focus-sessions`、`PATCH /v1/focus-sessions/{session_id}`。响应以 `packages/contracts` 的 Zod schema 为当前客户端预期，认证由 Backend 处理；如有字段差异，先同步 OpenAPI 和迁移说明。

## 下一步

1. 开发者 A 先修正 OAuth2/OpenAPI `tokenUrl`，补齐 Bearer JWT fixture、主链路 API 联调测试，并把 OpenAPI/Zod 漂移检查纳入 CI。详见 `TASKS/backend-auth-contract-integration.md`。
2. 开发者 B 将 Backend JWT 会话接入 Windows 构建包，验证 Stronghold 凭据存储、重启恢复和真实 API 联调；当前代码仍未替代构建包人工验收。
3. 两位开发者共同在 Windows 构建包验收校园登录/2FA、Event 同步、计划确认、Focus 完成、断网重试和冲突处理。
4. 主链路稳定后再推进 Android 凭据存储/通知、Agent 动态重规划、Memory/Grounding 和 OneTHU 分发许可审查。
