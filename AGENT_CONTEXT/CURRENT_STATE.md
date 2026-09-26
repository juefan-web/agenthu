# 当前进度（2026-09-26）

## 开发者 B：客户端与校园适配

目标：先建立 Windows 上的 Study + Time 客户端路径。输入为 OneTHU 固定版本的课程、作业、课表和校历；输出为带来源的 Event、Backend 任务/计划展示及 Focus 操作。开发者 B 不修改 Backend 数据库或 Agent 决策。

已实现 React/Vite/Tauri 2 工程、共享 Zod 契约、vendored `@onethu/core`、`CampusAdapter`、Event 映射、Tauri 网络 transport、SQLite 待同步 Event/游标及 Focus 草稿命令、Backend API 客户端以及 Today/任务/Focus 工作台。Event 去重键为 `source + upstream_id + semantic_version`，连接器版本独立记录。Focus 草稿经 Zod 校验，客户端重启后可恢复，并可手动清除。本机 `pnpm lint`、`pnpm typecheck`、`pnpm test` 和 `pnpm build` 已通过；新增 Windows CI 执行这些检查和 Rust `cargo test`。

## 尚未满足的验收项

- Rust 侧校园登录和 2FA 命令目前返回“CAS provider 尚未配置”；真实登录、会话恢复和失效后单次重试尚未完成。
- Stronghold 插件已配置，但 Cookie/Session 尚未写入 Stronghold；当前 OneTHU Cookie 仅在 WebView 适配器内存中，不能声称持久恢复安全边界已完成。
- Rust SQLite 命令已实现，但本机无 `cargo` / `rustc`，尚未编译、执行 `cargo test` 或 Tauri Windows/Android 构建；CI 结果需在推送后核对。
- Focus 草稿已落 SQLite，但尚无与 Backend 对账的恢复接口；断网恢复、冲突提示和 Focus 偏差后的重规划依赖 Backend 契约与实现。
- `VITE_BACKEND_URL` 未配置时客户端可展示本地状态，但无法读取 Backend Current State、Task 和 Plan。
- 还需要 Testing Library 和 Playwright 流程测试；现有测试只覆盖契约、映射和批量同步。

## 开发者 A 需要冻结的接口

`POST /v1/events/batch`、`GET /v1/current-state`、`GET /v1/tasks`、`GET /v1/plans/today`、`POST /v1/plans/{plan_id}/confirm`、`POST /v1/focus-sessions`、`PATCH /v1/focus-sessions/{session_id}`。响应以 `packages/contracts` 的 Zod schema 为当前客户端预期，认证由 Backend 处理；如有字段差异，先同步 OpenAPI 和迁移说明。

## 下一步

1. 在有 Rust 工具链的 Windows 环境编译 Tauri host，修复任何 Rust API 兼容问题并补原生命令测试。
2. 完成 CAS/2FA 和 Stronghold 会话持久化，验证会话恢复及失效重试，检查敏感日志。
3. 与开发者 A 对齐 OpenAPI，加入 Backend fixture、端到端登录/同步/Focus 流程和断网测试。
