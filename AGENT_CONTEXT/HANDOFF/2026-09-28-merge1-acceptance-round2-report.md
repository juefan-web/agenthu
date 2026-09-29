# 2026-09-28 第二次合并验收报告（draft PR #1 / `integration/study-time-m0` @ `bcd53c8`）

结论：**仍不建议转正合并**。D1 的 learn 域修复已确认生效，但采集在下一层（info 域 XSRF）被新的结构性缺陷卡死，记为 **D8**。D2/D4/D5/D6/D7 验证通过，断网重试仍被阻塞。

## 本轮通过项

- **D6 CSP**：官方构建包全程 console **0 条 CSP violation**（第一轮 6 条），IPC 源加白 + guard 正向校验生效。
- **D5**：新用户 8 并发 `GET /v1/current-state` 全部 200（修复前 2/5 为 500）。
- **D7**：创建任务后 `GET /v1/plans/today` 自动重排出新 items（修复前复用当日空草稿）。
- **D4**：计划列表显示任务标题（「大学物理实验报告」「数据结构作业：二叉树」），无 UUID。
- **D2**：真实账号勾选「信任此设备」后单轮 2FA 即完成（1459ms）；再次登录完全免 2FA（815ms）——受信 finger3 链成立。
- 计划确认 1070ms；Focus 开始 774ms / 完成 1316ms（Backend actual_minutes=1、任务转 done）。
- 整包重启后校园会话（快照含 Cookie）与 Backend Token 均自动恢复。

## D8（P0，新增）：Info 域 XSRF 依赖惰性 jar，采集必然失败

- **现象**：登录/恢复成功后点击采集，报「校园数据未保存：校园会话已失效，请重新登录」。官方包 2 次（1096ms / 21ms），诊断包 3 次，确定性复现。
- **定位过程**：构建包无 `http.debug` 接线（任务文件要求的 LEARN-SILENT 现场定位无法执行，本次在临时 worktree `C:\agenthu-dbg` 接线后抓到）。日志显示 **learn 域完全正常**：校历 → 课程列表 → 全部课程的作业查询（new/submitted/graded）逐个 success，其中一门课 67 条作业——D1 的 learn 修复本身是成功的。
- **根因**（堆栈 + 源码双确认）：`COLLECT-FAIL` 堆栈指向 `InfoClient.#csrfToken` 抛 `AuthRequiredError`：

  ```ts
  // vendor/onethu/core/src/info/client.ts #csrfToken
  const read = () => this.#http.jar.getCookies(new URL(`${urls.INFO_PREFIX}/`))
    .find((c) => c.name === "XSRF-TOKEN")?.value;
  ```

  而桌面运行时 `apps/desktop/src/adapters/campus/runtime.ts:16` 将 jar 置为惰性
  （`getCookies: () => []`，注释「Cookies stay in Rust」）→ `read()` 恒为空 →
  dance 后重读仍为空 → 必然抛错 → `#roamInfoService` → `#ensureZhjw` →
  `getSchedule` 失败 → `Promise.all` 否决整个采集（learnPromise 后台跑完被丢弃）。
- **影响面**：所有走 `#roamInfoService` 的 info 域业务（课表、个人信息、yyfw 服务等）在此架构下**永远无法成功**，与账号/网络无关。
- **修复方向**（供参考）：Rust 侧暴露按 host 查询 Cookie 的命令并把 `jar.getCookies` 接到该命令；或 `#csrfToken` 改由传输层返回的响应头/Set-Cookie 链路获取 token。另建议：适配层把 collect 路径的 `AuthRequiredError` 原文透传（本轮需注入 `[COLLECT-FAIL]` 日志才可见真实错误）；构建包接线 `http.debug` 使 LEARN-SILENT 可用。

## 未关闭 / 未覆盖

- **断网重试与队列恢复**：仍被 D8 阻塞（采集在入队前失败，队列恒为空，`重试同步`按钮持续禁用）。
- **D3 错误透传与原地重发**：本轮受信设备单轮 2FA，未出现失败场景可复测；采集路径错误被吞为通用文案的问题仍在（见 D8 修复建议）。
- **双轮 2FA 的显式提示**（D2 未受信分支）：本轮未触发（受信设备），仅单测覆盖。
- 一次 21ms 瞬败疑似与采集失败后 `session.reset()` 与重新登录 `applyStatus` 的状态同步竞态相关，待 D8 修复后观察是否复现。

## 计时（第二轮，关键步骤）

| 步骤 | 耗时 | 结果 |
| --- | --- | --- |
| Backend 登录（qa-merge2） | 719ms | ✅ |
| 校园密码登录 → 出 2FA | 848ms | ✅ |
| 发送验证码 | 741ms | ✅ |
| 验证码提交（含信任设备） | 1459ms | ✅ 单轮通过 |
| 再次登录（受信，免 2FA） | 815ms | ✅ |
| 采集并同步（官方包 ×2 / 诊断包 ×3） | 1096 / 21ms；诊断包 learn 阶段 ~12s | ❌ D8 |
| 确认计划 | 1070ms | ✅ |
| Focus 开始 / 完成 | 774ms / 1316ms | ✅ |

超过 10 秒的系统等待：诊断包中 learn 域「校历+课程列表」阶段约 11-12 秒（上游延迟，采集未成功故未计入同步耗时）；其余系统步骤均 ≤1.5 秒。

## 环境遗留

- 官方构建包 exe 已恢复运行（9222 调试端口）；Backend uvicorn 与便携 PostgreSQL 运行中。
- 诊断 worktree：`C:\agenthu-dbg`（`bcd53c8` + 未提交的调试补丁：`http.debug` 接线、`[COLLECT-FAIL]`、`AUTH-STACK`、JSON-FAIL 日志），可直接用于 D8 定位复现；不需要时 `git worktree remove /c/agenthu-dbg`。
- 计时/console 记录：`C:\agenthu-pg\tools\`（`timings.jsonl`、`console.jsonl`；第一轮已归档至 `round1/`）。
