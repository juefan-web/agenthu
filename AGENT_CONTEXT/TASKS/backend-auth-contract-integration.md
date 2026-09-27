# 后端认证与契约联调

负责人：开发者 A  
目标：让 Backend 的 Bearer JWT 契约可被客户端稳定消费，并完成首轮 A/B 联调。

## 输入

- D-018 Bearer JWT 决策
- `packages/contracts` 当前 Zod 契约
- Backend 分支 `origin/m0/backend-foundation`

## 输出

- 修正 OAuth2/OpenAPI `tokenUrl` 为 `/v1/auth/token`。
- 提供 `/register`、`/login`、`/token`、`/me`、过期 Token 的稳定 fixture。
- 对 `events/batch`、`current-state`、`tasks`、`plans/today`、计划确认和 Focus 接口提供联调测试。
- 将 OpenAPI 与共享客户端契约的漂移检查纳入 CI。

## 不负责

- 不实现 React/Tauri 登录界面或本地 Token 存储。
- 不改变校园账号、OneTHU 认证或客户端 SQLite 队列职责。

## 验收标准

- OpenAPI Authorize 使用 `/v1/auth/token`，相关测试通过。
- 缺失、非法、过期 Bearer Token 均返回约定的 `401` 错误 envelope。
- 一组可重复运行的 API fixture 覆盖 Event -> Task/Current State -> Plan -> Focus 主链路。
- CI 能在契约变化时报告 OpenAPI/Zod 漂移。

