# Client fixes from 2026-09-28 merge-1 manual test

负责人：开发者 B。上游输入：`HANDOFF/2026-09-28-merge1-manual-test-report.md`
（D1、D2、D3、D4、D6）。用户补充要求：登录链不应当登录两次；修复可参照上游
OneTHU（https://github.com/smartThise/OneTHU ，dev3 分支）的桌面端实现
（`apps/desktop/src/lib/infoLib.ts`、`clients.ts`、`transport.ts`）。
以下根因已经过代码复核，附证据位置，不必重新诊断。

## D1（P0）采集确定性失败：learn 会话无法建立

复现链（与报告 4 次复现完全吻合）：collect → `requireLearnSession`
（`onethuAdapter.ts:34-39`）→ `learn.resume()` 失败 → read 层自动
restore+probe 成功（info/webvpn 域正常）→ 重试仍失败 → `session.reset()` →
「校园会话已失效」。

三个结构性缺口（对照上游实装均已确认）：

1. **登录后没有显式 learn 漫游**。`tauriAuthGateway.ts` `run` 只调
   `login(helper,...)`，注释写明刻意跳过二次 CAS roam（"A second direct CAS
   roam here would prompt for 2FA again"）。上游在登录后显式调用
   `libRoamLearn()`（`roam(helper,"id","bb5df85216504820be7bba2b0ae1535b/0")`，
   即 learn 的 id 表单链：表单→check→锚点→包装跟随）。
2. **`learn.credentialProvider` 从未接线**（`runtime.ts` 创建 LearnClient 后未
   设置）。`silentRelogin()` 路径二（账密全链）永远 `return false`，唯一活路是
   路径一 `/f/login` 302 SSO——真实环境实测失败。上游在登录链内存有凭据期间
   供给 `credentialProvider`（配合 finger3 受信免 2FA）。
3. 路径一失败的具体原因需现场日志定位：vendored learn client 已有完备诊断
   （`LEARN-SILENT` debug 行、`lastDebug`），先在构建包里打开 debug 采集一轮，
   确认是 WebVPN 包装链、id Cookie 域，还是重定向链中断。

修复方向：按上游模式，登录成功后（finger3/受信就绪时）显式 roam learn；
`runtime.ts` 接线 `credentialProvider`（仅内存凭据期间）；保留 resume 兜底。
验收：真实账号一次登录后采集成功，跨重启后恢复 + 采集成功。

## D2（P1）一次登录被要求两轮 2FA 且无提示

- 根因（结构性，非我方 bug 但我方未消化）：vendored info-lib `login()` 成功后
  调 `roam(helper,"id",...)`，该分支用账密**重新完整登录 id**
  （`i_user`/`i_pass` 重放），响应含「二次认证」就再次触发
  `twoFactorAuth` → 第二轮 2FA；外层还有 `for(i<2)` 整链重试。上游通过
  **finger3 受信链**让第二次登录免 2FA：首轮 2FA 时 SAVE_FINGER 返回
  fingerGenPrint，roam 重放时携带。我方 gateway 有 trustFingerprintHook，但
  测试账号为全新设备未受信 → 两轮 2FA 必现。
- 修复方向：a) 确保「信任设备」勾选后 finger3 保存/复灌（登录前
  `helper.fingerGenPrint = 存量 finger3`，restore 路径已有类似逻辑）；b) 第二轮
  2FA 触发时 UI 必须显式提示（如「安全策略要求再次验证」），参照上游
  「链已死 → 自动重启链并应答」的自愈处理，不得静默回方式选择页。
- 验收：真实账号勾选信任设备后，后续登录只出现一轮 2FA；未受信设备出现第二轮
  时 UI 有明确提示且可正常完成。

## D3（P1）2FA 失败/超时后恢复路径断裂

- 根因：`tauriAuthGateway.ts` 状态机只支持一轮 2FA。`send2fa` 的守卫
  `!this.methodGate || !this.completion || ...` 在首轮结束后 methodGate 已死 →
  「请选择当前可用的验证方式，或取消后重新登录」（与报告原文一致）；上游
  `LoginError(m3)` 等错误原因被 `catch` 折叠成统一文案从未透出；`login()` 起置的
  180s 总超时（vendored core 同样 3 分钟）覆盖两轮 2FA + 用户输码，超时即
  `logout()` 静默销毁全链。
- 修复方向：methodGate/codeGate 支持多轮生命周期；失败后同轮重发验证码可用；
  上游错误 message 透出到 UI；超时改为每轮独立计时或给出可见倒计时。
- 验收：验证码错误/过期后可原地重发并重试；取消/超时路径文案准确；新增会话
  测试覆盖第二轮 hook 触发与失败重试。

## D4（P1）计划列表显示 task_id 而非 title

- 根因：`packages/contracts/src/index.ts` `PlanItemSchema`（59-64 行）无
  `title`；`App.tsx:298` 渲染 `item.task_id`。Backend 已下发 `title`（curl 实证）
  且漂移检查因「backend-only additions 容忍」而通过——契约检查无法发现该缺口。
- 修复方向：`PlanItemSchema` 增加 `title: z.string()`（Backend 恒定下发，可必填；
  与 A 确认 drift 基线与冻结快照同步），今日计划 UI 显示 title，task_id 仅作 key。
- 验收：真实联调中今日计划显示课程/任务标题；联合 drift check 无漂移。

## D6（P1）生产 CSP 拦截 Tauri IPC（上一轮收紧 CSP 的回归）

- 根因：`tauri.conf.json` 生产 `connect-src` 缺 `http://ipc.localhost`
  （Windows WebView2 的 Tauri v2 IPC 源；页面源为 `http://tauri.localhost`，
  `'self'` 不覆盖）与 `ipc:`（macOS/Linux）。`scripts/check-csp.mjs` 对 IPC 源
  零校验，未能拦截回归。当前靠 postMessage 降级工作（性能差 + console 6 条
  violation，违反「DevTools 无 CSP violation」验收项）。
- 修复方向：`csp` 与 `devCsp` 的 `connect-src` 增加 `ipc: http://ipc.localhost`；
  guard 增加「必须包含 IPC 源」的正向校验。
- 验收：构建包 DevTools 无 CSP violation；guard 对缺失 IPC 源的配置构建失败
  （实弹验证失败路径）；lint/typecheck/test/build、cargo test、CI 全绿。

## 不负责

- D5、D7 属 Backend（见 `backend-merge1-review-fixes.md`）；不改 Backend schema
  与 Agent 决策；vendored OneTHU 升级如涉及许可文件变化，同步
  `THIRD_PARTY_NOTICES.md`。

## 完成标准

- D1 修复后在 Windows 构建包用真实账号走通：登录（单轮或带提示的双轮 2FA）→
  采集 → 同步 → 计划（显示 title）→ 确认 → Focus → 断网重试；DevTools 无
  CSP violation。完成报告附可 fetch 的 commit hash 与实测记录。
