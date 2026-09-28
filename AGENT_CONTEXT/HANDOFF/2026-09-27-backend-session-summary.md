# Backend JWT 客户端会话交接

日期：2026-09-27

分支：`feature/client-tauri-campus-adapter`

## 已完成

- `apps/desktop/src/backend/session.ts` 增加可注入 `fetcher`，便于不依赖真实 Backend 的会话测试。
- 登录拿到候选 JWT 后先调用 `/v1/auth/me`，验证成功后才写入 TokenStore。
- 替换登录失败或 TokenStore 写入失败时，恢复原内存 Token、持久化 Token 和 Zustand UI 会话状态。
- `restore()` 处理 TokenStore 读取失败、过期 Token、Backend 401 和 TokenStore 清理失败；失败时清理内存 Token 并显示明确错误。
- `logout()` 清除内存 Token、持久化 Token 和 UI 状态；普通 Backend 请求由 `BackendClient` 统一注入 Bearer Token。
- 401 清理和 `restore/login/register/logout` 通过操作队列串行化；旧请求迟到时不会清除新登录写入的 Token。
- 新增 `session.test.ts` 与 `tokenStore.test.ts`，覆盖登录、重启恢复、过期 Token、普通请求 401、401 清理失败、登出、替换登录回滚、持久化失败和本地 Token 校验。

## 验证

- `pnpm test`：8 个桌面端测试文件、37 个桌面端测试通过；contracts 和 OneTHU smoke tests 也通过。
- `pnpm lint`：通过。
- `pnpm typecheck`：通过。
- `pnpm build`：通过。
- `git diff --check`：通过。

Build 仍有既有警告：OneTHU `http.ts` 动态/静态导入混用，以及最终 JS bundle 超过 500 KB。

## 未完成

- 尚未在构建后的 Windows 客户端上使用真实 Backend 和校园账号完成登录、重启恢复、2FA、Event 同步、计划确认、Focus 和断网重试人工验收。
- 仍需开发者 A 冻结 OpenAPI/共享契约并完成 Backend fixture 与主链路联调。
- 会话操作竞态已通过内部队列处理；仍未在真实 Backend 和构建后的 Windows 客户端上完成人工验收。
