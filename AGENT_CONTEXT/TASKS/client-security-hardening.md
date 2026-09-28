# 客户端安全与健壮性修复（审阅跟进）

负责人：开发者 B
目标：落实 2026-09-28 仓库审阅中分配给客户端的 4 项修复，消除已确认的安全与可用性缺陷。

## 输入

- 审阅结论：CSP 过宽（`connect-src https:`、`script-src 'unsafe-eval'`）、Backend 密码登录失败后残留在 React state、Rust `queue_list` 整体 `collect` 到 `Result`、`createCampusRuntime` 返回裸 `CampusSession`。
- 现有 `tauri.conf.json`、`App.tsx`、`src-tauri/src/lib.rs`、`adapters/campus/runtime.ts`。

## 输出

- 生产 CSP 只允许 `self` 与本地 Backend 源，去掉 scheme 通配与 `unsafe-eval`；开发期 `devCsp` 单独保留 Vite dev/HMR 源。
- `scripts/check-csp.mjs` 构建期 guard：拒绝 scheme 通配、`unsafe-*` script-src、未加白的 `VITE_BACKEND_URL` 源，挂入 `pnpm build`。
- Backend 登录在发起请求前立即清除密码 state（对齐校园登录既有模式），失败路径不再残留。
- `queue_list` 逐行容错：坏行跳过并记日志，单行损坏不再卡死整个离线队列与后续同步；跳过不删数据。
- `createCampusRuntime` 只返回 `adapter`，裸 `CampusSession`（cookie/凭据访问面）不再跨模块暴露。

## 不负责

- 不修改 Backend 代码（A 的 P0：`current_plan_for` 过滤、handler savepoint、SECRET_KEY fail-closed）。
- 不处理 2FA 等待期密码驻留：vendored info-lib 在 2FA 验证后的 id roam 需要重放明文密码（`core.ts` login 链 `roam("id")`），登录链存活期间无法丢弃；现有实现已在所有 settle/logout/超时路径清理，彻底消除需上游改造，已记录为约束。

## 验收标准

- `pnpm lint`、`pnpm typecheck`、`pnpm test`、`pnpm build`（含 guard）通过；`cargo test` 通过且 `generate_context!` 编译即证明 `devCsp` 配置合法。
- guard 失败路径实测：未加白 Backend 源、旧版宽松 CSP（`https:` + `'unsafe-eval'`）均以非零退出拦截。
- Rust 新增 `queue_listing_isolates_corrupt_rows` 单测覆盖坏行隔离。
