# 开发者 B 工作总结：React/Tauri 客户端与校园数据适配

日期：2026-09-26

分支：`feature/client-tauri-campus-adapter`

提交：`6198e72`、`6abc73b`

## 1. 工作目标

围绕 Study + Time 首期闭环，将客户端调整为 React + TypeScript + Vite + Tauri 2 + Rust，并把 OneTHU 封装为受控的校园数据适配层。React 页面只依赖 `CampusAdapter`，校园数据先转换为统一 Event，再交给 Backend；客户端不修改 Backend 数据库或自行生成可信 `user_id`。

## 2. 已完成内容

### 工程与依赖

- 建立 pnpm workspace 下的 React/Vite/Tauri 桌面客户端和共享 `packages/contracts` 契约包。
- 按固定 commit `2e3455fc235719b7f91fffaf5fe35e09220dda73` vendor OneTHU 必要源码，包含 `@onethu/core` 和认证所需的 `info-lib` 子集。
- 增加 `THIRD_PARTY_NOTICES.md`，记录 OneTHU 来源、版本、复制范围、MIT/BSL 1.1/LearnX 与依赖许可注意事项。

### 校园认证与原生边界

- 实现 `CampusAdapter` 和 `TauriCampusAuthGateway`，支持登录、2FA 方式选择、验证码校验、信任设备选择、取消、登出和会话恢复。
- Tauri Rust transport 负责清华 HTTPS 请求、受限重定向、Cookie 隔离、请求超时和响应大小限制；React 不直接访问校园 API。
- Session/Cookie 快照通过 Stronghold 加密保存，Windows 密钥由系统 credential store 保存；默认不保存校园密码，密码和 2FA 验证码只在内存中使用并在流程结束后清理。
- 会话恢复会探测身份；会话失效时只自动恢复/重试一次，失败后返回明确的重新登录状态。

### OneTHU 数据与 Event

- 首期接入 `getCourseList`、`getAllHomework`、`getSchedule`、`getCalendarData`。
- 课程、作业、课表和校历统一映射为带 `source`、`upstream_id`、`semantic_version`、`fetched_at` 的 Event。
- 去重依据为 `source + upstream_id + semantic_version`，敏感凭据、Cookie 和验证码不进入 Event 或日志。

### 离线与 Focus

- Tauri SQLite 保存待同步 Event、同步游标和 Focus 草稿；网络恢复后可以按客户端幂等键批量上传。
- Focus 草稿使用 Zod 校验，支持重启后恢复和手动清除；Web 环境保留 localStorage fallback。
- 完成 Tauri command 注册修复，解决公开根模块命令产生的 `__cmd__*` 宏重复定义问题。

## 3. 验证结果

本地已通过：

- `pnpm lint`
- `pnpm typecheck`
- `pnpm test`
- `pnpm build`

Windows GitHub Actions 已通过：

- 前端 lint、typecheck、test、build
- Rust `cargo test --manifest-path apps/desktop/src-tauri/Cargo.toml`

CI Run：<https://github.com/juefan-web/agenthu/actions/runs/36223546458>

本机未安装 Rust 工具链，因此 Rust 验证以 Windows CI 为准。CI 同时出现了 GitHub Actions 将 Node.js 20 action 强制运行于 Node.js 24 的非阻塞提示。

## 4. 尚未完成与风险

- 真实校园账号登录、2FA 和会话恢复仍需在构建后的 Windows 客户端中进行人工验收；fixture 不能替代校园服务验收。
- Backend 的 OpenAPI、Event 去重、Task/Deadline 投影、计划生成和 Focus 重规划由开发者 A 维护，客户端仍需与最终字段冻结结果联调。
- SQLite 待同步 Event 与 Backend 对账、冲突提示和 Focus 偏差重规划尚未形成完整端到端流程。
- Android 的 Tauri 构建、平台凭据存储、通知和同步恢复尚未完成。
- Testing Library/Playwright 用户流程覆盖仍需补齐；当前测试重点是契约、映射、认证状态和离线队列。
- 发布前必须完成 OneTHU BSL 1.1、LearnX 及依赖许可的逐文件分发审查。

## 5. 下一步建议

1. 开发者 A 冻结并提供客户端依赖的 OpenAPI 响应 fixture，优先联调 `/v1/events/batch`、`/v1/current-state`、`/v1/tasks`、`/v1/plans/today` 和 Focus 接口。
2. 在 Windows 构建包中使用测试账号完成登录、2FA、重启恢复、失效重试、登出和敏感日志检查。
3. 增加课程/作业导入到 Event、Task、Plan、Focus、结果 Event 的端到端测试，以及断网重试和冲突处理测试。
4. 冻结 Windows 版本后复用 React 前端推进 Android 凭据存储、通知和同步恢复。

## 6. 交付状态

本次开发范围已提交并推送到 `feature/client-tauri-campus-adapter`，工作区干净。客户端原生校园适配和离线基础能力可进入 A/B 联调阶段；真实校园服务验收、Backend 联调和 Android 稳定性属于后续工作。
