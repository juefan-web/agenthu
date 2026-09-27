# 当前进度（2026-09-27）

## 开发者 B：客户端与校园适配

目标：先建立 Windows 上的 Study + Time 客户端路径。输入为 OneTHU 固定版本的课程、作业、课表和校历；输出为带来源的 Event、Backend 任务/计划展示及 Focus 操作。开发者 B 不修改 Backend 数据库或 Agent 决策。

已实现 React/Vite/Tauri 2 工程、共享 Zod 契约、vendored `@onethu/core`、`CampusAdapter`、Event 映射、Tauri 网络 transport、SQLite 待同步 Event/游标及 Focus 草稿命令、Backend API 客户端以及 Today/任务/Focus 工作台。Event 去重键为 `source + upstream_id + semantic_version`，连接器版本独立记录。Focus 草稿经 Zod 校验，客户端重启后可恢复，并可手动清除。本机 `pnpm lint`、`pnpm typecheck`、`pnpm test` 和 `pnpm build` 已通过；新增 Windows CI 执行这些检查和 Rust `cargo test`。

客户端耗时排查已确认 Tauri transport 原先每请求新建 HTTP Client，且每个响应都把会话快照重新写入 Stronghold；后者会阻塞请求热路径。现按会话复用重定向策略对应的 Client，登录成功时由显式 `campus_save_session` 保存快照，普通校园请求只在内存更新 Cookie，不再同步写 Stronghold。采集流程用校历学期 ID 取课程，省去重复学期请求，并让课表与课程/作业链并行；UI 分开显示采集、保存和同步阶段及完成耗时。登录后的身份探测仍保留。测试覆盖快照未变/变化与采集并行顺序。真实校园网络和账号下的登录、2FA、采集耗时尚未重新测量；OneTHU 仍会为每门课请求三类作业，上游延迟可能占主导。

本轮风险修复：校园请求完成后会按快照内容变化持久化刷新 Cookie；LocalEventQueue 分别恢复 events/cursor，损坏内容写入隔离备份；Event 去重键对反斜杠和分隔符转义，避免字段碰撞。对应回归测试已加入；客户端 Vitest 仍受当前 Windows 环境 pnpm store 权限和 `spawn EPERM` 限制，Rust 与 TypeScript 编译验证通过。

## 尚未满足的验收项

- 真实校园账号登录、2FA、会话恢复和失效重试仍需在构建后的 Windows 客户端中人工验收；当前已有 OneTHU 认证适配、Stronghold 加密快照和脱敏状态测试。
- Rust SQLite 待同步 Event 与 Backend 对账、冲突提示和 Focus 偏差重规划依赖开发者 A 的最终契约与实现。
- `VITE_BACKEND_URL` 未配置时客户端可展示本地状态，但无法读取 Backend Current State、Task 和 Plan。
- 还需要 Testing Library 和 Playwright 用户流程测试，以及 Android 凭据存储、通知和同步恢复。
- 发布前仍需完成 OneTHU BSL 1.1、LearnX 及依赖许可的逐文件分发审查。

## 开发者 A 需要冻结的接口

`POST /v1/events/batch`、`GET /v1/current-state`、`GET /v1/tasks`、`GET /v1/plans/today`、`POST /v1/plans/{plan_id}/confirm`、`POST /v1/focus-sessions`、`PATCH /v1/focus-sessions/{session_id}`。响应以 `packages/contracts` 的 Zod schema 为当前客户端预期，认证由 Backend 处理；如有字段差异，先同步 OpenAPI 和迁移说明。

## 下一步

1. 使用构建后的 Windows 客户端复测登录、2FA、采集和同步各阶段耗时，并完成重启恢复、失效重试和敏感日志验收。
2. 与开发者 A 对齐 OpenAPI，加入 Backend fixture、端到端登录/同步/Focus 流程、断网重试和冲突测试。
3. 推进 Android 凭据存储、通知、同步恢复和 OneTHU 分发许可审查。
