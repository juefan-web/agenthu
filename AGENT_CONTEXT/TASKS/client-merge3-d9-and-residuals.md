# Merge-3 修复任务（负责人：开发者 B；A 临时不在，本轮全部任务归 B）

输入：`HANDOFF/2026-09-28-merge1-acceptance-round3-report.md`（D9 新增 + D3 残留）。
根因已经代码复核确认。round-2 的诊断 worktree `C:\agenthu-dbg` 已过时，本轮工作
基于 `bad00c7`；官方包环境与 `agenthu.campus-debug` 开关可用。

## 1. D9（P0）：教务课表直连 http:80 被 Rust 白名单拒绝

- 根因（已核实）：vendor `info/urls.ts:7` `ZHJW_PREFIX = "http://zhjw.cic.tsinghua.edu.cn"`
  （课表 JSONP `jxmh_out.do`、成绩、二级课表都基于它）；`http.ts:72`
  `PUBLIC_DIRECT_HOSTS` 对该 host 跳过 webvpn 包装；而 `campus.rs:69`
  `allowed_campus_url` 仅放行 `https + 443 + *.tsinghua.edu.cn`，入口（:181）与
  重定向策略（:38）双处拒绝 → 采集确定性失败（时序与报告吻合：webvpn 域
  dance/csrf 成功后课表请求被拒）。
- **方案定向：a 案（窄开口），b 案不采用**。决定性证据是 vendor 自己的加白注释
  （`http.ts:75-77`）："portal3rd.do **原走包装撞引导壳**（教务 host 的 wengine
  票从未建立——教务访问统一直连 JSONP）"——上游已实测过 webvpn 包装 zhjw 并失败，
  2026-09-19 才改为直连。b 案（改走 webvpn /http/）是已被上游证伪的路径，且会
  多烧一轮人工验收。审阅者倾向 b 的理由（不放松安全边界）记录在案，但与 vendor
  实测历史冲突。
- **实施要求**：
  - `allowed_campus_url` 增加窄例外：`scheme == "http" && port 80 &&
    host == "zhjw.cic.tsinghua.edu.cn"`（精确 host，不做子域通配，不放开其他
    http host；重定向策略复用同函数自然继承）。
  - 更新/新增 Rust 单测：接受 zhjw http:80；拒绝其他 host 的 http、zhjw 的其他
    端口、http 的子域伪造（如 `evil-zhjw.cic.tsinghua.edu.cn` 不在例外内属正常
    放行域判断——注意例外是精确匹配，`x.zhjw.cic.tsinghua.edu.cn` 的 http 应
    拒绝）。
  - 隐私/安全边界变化写入 `CURRENT_STATE.md`（该 host 的会话 cookie 以明文
    http 传输，与上游实测路径一致、范围限单 host），如 A 回归后补 DECISIONS
    编号。
- 验收：真实账号构建包采集全链成功（课表+校历+课程+作业），Event 入队。

## 2. D3 残留：错误态缺原地重试入口

- 根因（已核实）：`restartChain`（`tauriAuthGateway.ts:248`）用内存凭据复活整链
  （指纹/受信保留、受信设备可免 2FA 直接就绪），但只在 `send2fa`/`verify2fa`
  （:270/:286）内可达；链 settle 为错误后 UI 落回完整登录表单，入口消失，用户
  被迫重输密码。而 `this.credentials` 到 logout 才清空——原地复活不需要密码。
- 实施：错误态（凭据仍在内存时）提供「重试验证」再入口，经 `restartChain`
  回到 2FA 表单或直接就绪；凭据已清（logout 后）则维持完整表单。注意
  `restartChain` 当前为 private，需在 gateway 暴露受控入口并保持链纪元语义。
  附回归测试。
- 验收：真实环境错误码 → 错误透出 → 原地点重试 → 重发验证码 → 通过。

## 3. 错误码透出时延复核（观察项）

- 报告测得透出时延上限 ~30s，不确定是上游响应慢还是客户端状态传播路径有
  可避免的延迟。复核 `Promise.race([completion, signal])` 与 hook 的 signal
  触发路径；有可收紧处则收紧，属上游延迟则在 CURRENT_STATE 记录结论。

## 4. 继承 A 的移交项（A 不在，归 B）

1. **compose healthy 终验转为 CI 步骤**：本机无 Docker Hub 连接，但 GitHub
   Actions runner 有。加 compose smoke job（`docker compose up -d --wait` 或
   等待 api/worker healthy 后 teardown），一次性终结这项人工移交。注意控制
   job 时长（healthcheck start_period）。
2. **debug 输出不含 cookie value 的回归断言**（A 的非阻塞建议）：为镜像/debug
   通道补一条断言测试（debug 行只含 cookie 名与截断 URL）。

## 完成标准与下一轮验收

- D9/D3 残留修复后双侧 CI 全绿；第三轮被阻塞的验收项在 round-4 执行：
  采集 → 入队 → 待同步计数 → **断网重试与队列恢复** → 真实数据驱动的
  Task/Plan/Focus 全链 → DevTools 无 CSP violation。
- 完成报告附可 fetch 的 commit hash；A 回归后对 D9 的安全边界变化补联合
  review。

---

## 开发者 A 补录联合 review：D9 窄口实现（2026-09-29，AGENTS.md §3）

Review 依据：`6a72dfd` 中 `campus.rs` 的 `allowed_campus_url` 实现、重定向
Policy 与入口双处调用、Rust 单测断言；DECISIONS 裁定见 **D-026**。**结论：
通过，无收窄要求**，附三项核对与一条非阻塞提醒。

### 1. 范围最小性 ✅

- 精确 host 等值（`host == "zhjw.cic.tsinghua.edu.cn"`，非后缀匹配）：
  `x.zhjw.cic.tsinghua.edu.cn`（子域伪造）与
  `zhjw.cic.tsinghua.edu.cn.evil.test`（后缀伪造）均不落入窄口；
- 仅 `http` + `port_or_known_default() == Some(80)`：缺省端口与显式 `:80`
  均合法（同一端口语义），`:8080` 等其他端口拒绝；
- `username().is_empty() && password().is_none()` 在两个分支之外层——窄口
  同样不允许 `http://user:pass@zhjw…` 凭据注入；
- 未引入子域通配、未放开任何其他 http host。

### 2. 重定向继承 ✅

重定向链每跳经 `Policy::custom` 调用同一 `allowed_campus_url`
（`campus.rs:37-39`），入口（`:197`）与 manual redirect 路径复用同一谓词——
窄口语义（包括对伪造 host 的拒绝）自然继承到所有跳；重定向上限 10 跳不变。

### 3. 伪造测试覆盖 ✅

Rust 单测断言：接受 `http://zhjw.cic.tsinghua.edu.cn/jxmh_out.do?m=bks_jxrl`
（真实业务路径）；拒绝其他 http host（`id.`）、zhjw 其他端口（`:8080`）、
http 子域伪造（`x.zhjw.…`）、后缀伪造（`zhjw….evil.test`）；原有 https 系列
回归（`evil.test` 后缀、`evil-tsinghua` 前缀、凭据注入、`:8443` 端口）全部
保留。`request_headers` 的 Cookie/Authorization 剥离断言仍在。

### 4. 非阻塞提醒

上游 `ZHJW_PREFIX` 若改为 https，需同步删除窄口例外（已写入 D-026 的
revisit 条件）；建议 B 在 vendor 升级流程里带上这条检查。
