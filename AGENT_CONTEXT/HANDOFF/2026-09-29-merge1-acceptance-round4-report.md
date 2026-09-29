# 2026-09-29 第四次验收报告（draft PR #1 / `integration/study-time-m0` @ `6a72dfd`）

结论：**D1–D9 全部在真实环境验证通过；唯一悬而未决的是新发现 D10（真实事件不产生任务），其定性（缺陷 vs M1 范围决策）由审阅人裁定——这直接决定 PR #1 能否转正。**

## 主线全链（D9 真实判据）——通过

- **登录**：受信指纹整链免 2FA 直接就绪（1665ms；`roamLearn` 显式漫游在登录链内完成）。
- **采集全链**：**「采集 100 条（1.8 秒），同步 0.6 秒；上传 100 条，重复 0 条，待同步 0 条」**。课表（zhjw 直连 JSONP，经 D9 单 host 窄口）+ 校历 + 课程 + 作业四个域全部成功——并行结构下任何一支失败都会整体失败，本次全过即 D9 真实判据满足。全程 3163ms。
- **Event 入队/待同步计数**：同步后徽标归零；采集同步阶段正常展示。
- **断网重试与队列恢复（首次实测）**：杀掉 Backend 后再采集，事件全部落本地队列，UI 徽标「**100 条待同步**」，无未处理异常；Backend 恢复后点「重试同步」**939ms** 完成：「上传 0 条，重复 100 条，待同步 0 条」——100 条全部按去重键正确结算（重复），徽标消失、重试按钮回灰。
- **CSP**：整轮（含断网/重试）console **0 条 violation**；21ms 瞬态失败未复现。
- **D3 残留（错误码原地重试，真实环境）**：清除受信状态后全新登录，注入错误验证码 **998ms** 透出上游原文（本轮为「校验码已失效，请重新发送。」），错误态出现**「重试验证（免重输密码）」**按钮，点击后 **977ms** 链复活回到方式选择表单（内存凭据 + 同指纹，无需重输密码）→ 重发验证码 787ms → 新码勾选信任设备提交 **968ms** 登录完成。D3 残留闭环。
- 重新登录（受信）1024ms；第二轮报告的受信免 2FA（815ms）与未受信双轮显式提示（round-3）维持有效。

## D10（待定性）：真实事件与 Backend 领域 handler 零交集，真实数据无法驱动 Task/Plan/Focus

- **现象**：100 条真实事件全部被 Backend 接受（`accepted 100 / rejected 0`），但 `/v1/tasks` 为空、`current_state.tasks` 为空、`/v1/plans/today` 无 items——真实数据驱动的 Task/Plan/Focus 全链无米下锅。
- **根因**（两侧代码确认）：客户端发出 `study.course.discovered`、`study.assignment.discovered|updated`、`time.schedule.entry`、`time.academic_calendar.updated`（`apps/desktop/src/adapters/campus/events.ts`）；Backend handler 注册表仅有 `focus.started`、`focus.completed`、`task.*` 三个 pattern（`backend/services/event_handlers.py:92,100,141`）。**没有任何 pattern 匹配 campus 事件类型**，事件入库后无领域效果。
- **定性建议**：若 M0 契约本就不含「campus 事件→任务派生」（round-1 交接曾把「真实导入适配层」列为 M1），则 D10 是范围决策而非缺陷——本轮主线（Event 入队/同步/断网重试/队列恢复）已全部通过，PR #1 可转正，D10 作为 M1 首项立项；若审阅人认定转正门槛包含「真实数据驱动 Task/Plan/Focus」，则需先立项实现 assignment→task handler 再合并。**本验收人倾向前者**：M0 的冻结契约与全部既有验收口径均未承诺事件派生任务，且 Task/Plan/Focus 链已在 API 造数路径下完整验证（round-2/3：title 显示、确认、Focus 实际时长、任务 done 联动）。
- 附带证据：D10 修复时可顺带核查 `current_state` 的 `available_minutes`/`context` 当前为 null/空（projection 版本在 bump，字段待真实任务/目标接入）。

## 计时（第四轮，关键步骤）

| 步骤 | 耗时 | 结果 |
| --- | --- | --- |
| 受信登录（免 2FA） | 1665ms | ✅ |
| **采集全链（四域）+ 同步** | 3163ms（采集 1.8s + 同步 0.6s） | ✅ 100/100 |
| 断网采集（入队） | 数秒内完成，徽标 100 条待同步 | ✅ |
| Backend 恢复 + 重试同步 | 939ms（重复 100，待同步 0） | ✅ |
| D3：错误码透出 | 998ms | ✅ |
| D3：重试验证按钮 → 链复活 | 977ms | ✅ |
| D3：复活后重发 / 最终验证 | 787ms / 968ms | ✅ 登录完成 |

超过 10 秒的系统等待：**无**。断网采集步骤的 180.6s 是验收脚本的观察窗口（正则未匹配新提示文案），入队本身在数秒内完成。

## 遗留

- A 侧：D9 明文 cookie 边界变化的联合 review 与 DECISIONS 编号（开发方已声明回归后补）。
- A 移交项：`docker compose up` healthy 终验（本机无 Docker，连续第三轮移交）。
- D10 定性 → 决定 PR #1 转正或立项。

## 环境

官方构建包（`6a72dfd`）、Backend、便携 PostgreSQL 均在运行，`agenthu.campus-debug` 开启，可直接复测；`C:\agenthu-dbg` 诊断 worktree 已无用可删；计时/console 记录 `C:\agenthu-pg\tools\`（round1–3 已归档）。
