# 当前进度（2026-09-28）

## 开发者 B：客户端与校园适配

目标：先建立 Windows 上的 Study + Time 客户端路径。输入为 OneTHU 固定版本的课程、作业、课表和校历；输出为带来源的 Event、Backend 任务/计划展示及 Focus 操作。开发者 B 不修改 Backend 数据库或 Agent 决策。

已实现 React/Vite/Tauri 2 工程、共享 Zod 契约、vendored `@onethu/core`、`CampusAdapter`、Event 映射、Tauri 网络 transport、SQLite 待同步 Event/游标及 Focus 草稿命令、Backend API 客户端以及 Today/任务/Focus 工作台。Event 去重键为 `source + upstream_id + semantic_version`，连接器版本独立记录。Focus 草稿经 Zod 校验，客户端重启后可恢复，并可手动清除。本机 `pnpm lint`、`pnpm typecheck`、`pnpm test` 和 `pnpm build` 已通过；新增 Windows CI 执行这些检查和 Rust `cargo test`。

客户端耗时排查已确认 Tauri transport 原先每请求新建 HTTP Client，且每个响应都把会话快照重新写入 Stronghold；后者会阻塞请求热路径。现按会话复用重定向策略对应的 Client，登录成功时由显式 `campus_save_session` 保存快照，普通校园请求只在内存更新 Cookie，不再同步写 Stronghold。采集流程用校历学期 ID 取课程，省去重复学期请求，并让课表与课程/作业链并行；UI 分开显示采集、保存和同步阶段及完成耗时。登录后的身份探测仍保留。测试覆盖快照未变/变化与采集并行顺序。真实校园网络和账号下的登录、2FA、采集耗时尚未重新测量；OneTHU 仍会为每门课请求三类作业，上游延迟可能占主导。

本轮风险修复：校园请求完成后会按快照内容变化持久化刷新 Cookie；LocalEventQueue 分别恢复 events/cursor，损坏内容写入隔离备份；Event 去重键对反斜杠和分隔符转义，避免字段碰撞。对应回归测试已加入；Rust 与 TypeScript 编译验证通过。

本轮完成 Backend JWT 客户端会话：`createBackendSession` 独立管理 Backend Token，与校园会话隔离；请求通过 `BackendClient` 统一注入 Bearer Token。登录先用 `/v1/auth/me` 验证候选 Token，再写入 TokenStore；验证失败或持久化失败时恢复旧 Token 和 UI 状态。重启恢复会跳过过期 Token、处理 `/me` 401，并对 TokenStore 读写/清理失败给出可见错误且不产生未处理拒绝。401 清理与 `restore/login/logout` 操作串行化，旧请求迟到时不会清除新会话；普通请求的 401 清理失败也有回归测试。新增 LocalTokenStore 与会话回归测试；本机桌面端 8 个测试文件、37 个测试、lint、typecheck 和 build 已通过。

本轮落实 2026-09-28 审阅分配的客户端安全修复（见 `TASKS/client-security-hardening.md`）：生产 CSP 收紧为 `self` + 本地 Backend 源，移除 `connect-src https:` 通配与 `script-src 'unsafe-eval'`，开发期源移入独立 `devCsp`；新增 `scripts/check-csp.mjs` 挂入 `pnpm build`，拒绝 scheme 通配、`unsafe-*` 与未加白的 `VITE_BACKEND_URL` 源（失败路径已实测拦截）。Backend 登录改为发起请求前立即清除密码 state；Rust `queue_list` 逐行容错，坏行跳过并记日志、不删数据，新增单测；`createCampusRuntime` 只返回 `adapter`，裸 `CampusSession` 不再跨模块暴露。桌面端 lint/typecheck/test/build 与 `cargo test`（6 测试）均通过。审阅中的 2FA 等待期密码驻留一项不修：vendored info-lib 在 2FA 验证后的 id roam 需重放明文密码，登录链存活期间无法丢弃；所有 settle/logout/超时路径均已清理，彻底消除需上游改造。

## 尚未满足的验收项

- 真实校园账号登录、2FA、会话恢复和失效重试仍需在构建后的 Windows 客户端中人工验收；当前已有 OneTHU 认证适配、Stronghold 加密快照和脱敏状态测试。
- Rust SQLite 待同步 Event 与 Backend 对账、冲突提示和 Focus 偏差重规划依赖开发者 A 的最终契约与实现。
- `VITE_BACKEND_URL` 的示例和构建包 CSP 已补齐，非本地 Backend 源现在必须在 `tauri.conf.json` 显式加白（构建期 guard 强制）；未配置时客户端仍可展示本地状态，但无法读取 Backend Current State、Task 和 Plan。
- Event 同步现已将 Backend rejected 事件移出待同步队列，并将拒绝原因返回给 UI；仍需在真实 Backend 上验证敏感字段、大小和深度限制的提示。
- Focus PATCH 现只发送 Backend 支持的 `status`、`actual_minutes`、`deviation_note` 字段；实际时长仍由 Backend 完成接口根据时间计算。
- 还需要 Testing Library 和 Playwright 用户流程测试，以及 Android 凭据存储、通知和同步恢复。
- 发布前仍需完成 OneTHU BSL 1.1、LearnX 及依赖许可的逐文件分发审查。

## 开发者 A 需要冻结的接口

`POST /v1/events/batch`、`GET /v1/current-state`、`GET /v1/tasks`、`GET /v1/plans/today`、`POST /v1/plans/{plan_id}/confirm`、`POST /v1/focus-sessions`、`PATCH /v1/focus-sessions/{session_id}`。响应以 `packages/contracts` 的 Zod schema 为当前客户端预期，认证由 Backend 处理；如有字段差异，先同步 OpenAPI 和迁移说明。

## 下一步

1. A/B 共同冻结 `PlanItem.title` 契约：A 更新 Backend OpenAPI/快照和 fixture，B 更新 Zod/UI，并共同跑漂移检查；当前不能把 A 分支直接合并到 main。
2. 解决两个分支合并时的 `.gitignore`、`AGENT_CONTEXT/CURRENT_STATE.md` add/add 冲突，再在集成分支跑完整 Backend 与客户端检查。
3. 开发者 B 将当前 Backend JWT 会话接入 Windows 构建包，验证 Stronghold 凭据存储、重启恢复和真实 API 联调；当前代码仍未替代构建包人工验收。
4. 两位开发者共同在 Windows 构建包验收校园登录/2FA、Event 同步、计划确认、Focus 完成、断网重试和冲突处理。
5. 主链路稳定后再推进 Android 凭据存储/通知、Agent 动态重规划、Memory/Grounding 和 OneTHU 分发许可审查。
