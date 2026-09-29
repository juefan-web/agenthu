# 2026-09-28 第三次验收报告（draft PR #1 / `integration/study-time-m0` @ `bad00c7`）

结论：**仍不建议转正合并**。D8 修复本身验证通过（镜像 jar 打通 info 域 XSRF，采集链已越过 dance/csrf/roam 到达教务课表请求），但在传输层撞上新的结构性矛盾，记为 **D9**，采集再次确定性失败。D2/D3 的真实环境复测大部分通过。

## 本轮通过项

- **D2 未受信分支（真实环境）**：清除 `campus.hold` 后全新指纹登录，第一轮 2FA 通过（5080ms）后出现第二轮，界面显式提示**「安全策略要求对本机再次验证，本轮通过后即可完成登录」**——不再静默；第二轮勾选信任设备提交 888ms 完成。
- **D2 受信分支**（第二轮报告已验）：受信后再次登录免 2FA。
- **D3 错误透出（真实环境）**：故意输入错误验证码，上游原文**「校验码错误，请重试。」**直达 UI（第一轮为静默）；本轮采集失败也透出了真实原因「Campus URL is not allowed」（第一轮是笼统的「校园会话已失效」）。
- **D8 镜像 jar 本身**：info 分支不再卡 `#csrfToken`（round-2 的失败点已消失），learn 域全链 success（校历/课程/全部作业，含 67 条作业的课），证据同 round-2 诊断。
- **D6 CSP 维持**：全程 console **0 条 violation**（62 条日志无一 CSP）。
- 21ms 瞬态失败：本轮未复现（两次采集失败均为 ~1.1s，见 D9）。
- 整包重启恢复、Backend Token 恢复：正常（沿用前两轮结论）。

## D9（P0，新增）：Rust 白名单只放行 https:443，vendor 教务课表直连 http:80 被拒

- **现象**：登录成功后采集 ~1.1s 失败，UI 透出「校园数据未保存：Campus URL is not allowed」；复现 1 次（官方包，本轮唯一一次点击；确定性由代码路径保证）。
- **根因**（代码级确认）：
  - vendor `http.ts:72` `PUBLIC_DIRECT_HOSTS` 含 `zhjw.cic.tsinghua.edu.cn`（注释：教务访问统一直连 JSONP，"课表 JSONP 同域直连一直是活的"）→ `resolveUrl` 对该 host 不做 webvpn 包装。
  - vendor `info/urls.ts` `ZHJW_PREFIX = "http://zhjw.cic.tsinghua.edu.cn"`（http **80 端口**），`ZHJW_SCHEDULE_JSONP` 即基于它。
  - 桌面 Rust `campus.rs:69` `allowed_campus_url`：仅 `https` + `port 443` + `*.tsinghua.edu.cn` → `http://zhjw.cic…:80` 在 `campus_request` 入口（`campus.rs:181`）与重定向策略（`campus.rs:38`）两处均被拒。
  - 时序吻合：采集并行分支中 info 域 dance/csrf（webvpn 域，允许）成功后，课表 JSONP 直连请求被拒 → `Promise.all` 否决，learn 后台结果丢弃。
- **修复方向**（二选一，需安全权衡）：a) `allowed_campus_url` 为 `http://*.tsinghua.edu.cn:80` 开窄口（放松安全边界，建议限定 zhjw.cic 单 host 并在报告注明）；b) vendor 侧把教务请求改走 webvpn `/http/` 段（`INFO_PREFIX` 的 `/https/` 同款模式，`urls.ts` 注释已提及"webvpn 走 /http/ 段"但 `PUBLIC_DIRECT_HOSTS` 与之矛盾）。倾向 b（不放松安全边界），但需实测 webvpn /http/ 段的教务会话行为。

## 部分达成 / 观察

- **D3 原地重发**：错误文案透出已达成；但错误码提交后 UI 落在完整登录表单，`restartChain` 复活路径（`tauriAuthGateway.ts:248`）仅在 2FA 表单内经 `send2fa` 可达——错误态用户需重输密码完整重登（密码已被安全策略清除）。与任务验收「验证码错误后可原地重发并重试」存在差距，建议作为 D3 残留项跟进（UI 层在错误态保留重进入口）。
- **错误码透出时延**：故意错误码提交后，检测窗口 30s 内未捕捉到状态变化，+33s 检查时错误已在——透出时延未精确测得（上限 ~30s），不排除上游对错误码响应偏慢，建议开发端复核。

## 仍被阻塞

- Event 入队 → 同步、待同步计数、**断网重试与队列恢复**（第三轮清单第 1 条的后半段）——采集在入队前失败，队列恒空。
- 真实 Event → 任务/计划/Focus 的数据链（用 API 造数可测 UI，但验收口径是真实采集数据）。
- A 移交项：`docker compose up` healthy 终验——本机无 Docker，继续移交。

## 计时（第三轮）

| 步骤 | 耗时 | 结果 |
| --- | --- | --- |
| Backend 切换 qa-merge3 | 653ms | ✅ |
| 校园登录（全新指纹）→ 2FA | 819ms + 发码 755ms | ✅ |
| 错误验证码注入（D3） | ≤30s 透出「校验码错误，请重试。」 | ✅ 透出 |
| 重新登录 + 发码 | 782ms | ✅ |
| 第一轮验证（不信任设备） | 5080ms → 第二轮出现**带显式提示** | ✅ D2 |
| 第二轮发码 / 验证（信任设备） | 745ms / 888ms | ✅ 登录完成 |
| **采集并同步** | 1091ms | ❌ D9 |

超过 10 秒的系统等待：本轮无（learn 后台阶段 ~12s 不面向用户；错误码透出时延上限 30s 已单列）。

## 环境遗留

- 官方构建包（bad00c7）、Backend（uvicorn + 便携 PostgreSQL）、便携库 `C:\agenthu-pg` 均在运行。
- localStorage `agenthu.campus-debug=1` 已开启（新 debug 接线验证可用，日志含 `[campus]` 前缀的 learn 链路，不含 cookie 值）。
- round-2 的诊断 worktree `C:\agenthu-dbg` 已过时（基于上一版代码），D9 定位建议基于 bad00c7 重做或在官方包开 debug（本轮已证明够用）。
- 计时/console 记录：`C:\agenthu-pg\tools\`（round1/、round2/ 已归档）。
