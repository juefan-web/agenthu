# Round-5 人工验收计划（M1-1 全链 + 加固项实测）

制定：协调人，2026-09-29。对象：main @ `aa9773e`（M1-1 全链 + B-4 代理 +
徽标 + e2e 脚手架 + 解析器加固全部在库，在途 PR 清零）。本文件是验收执行的
唯一清单；执行人按序执行并逐项记录结果与计时。

## 0. 环境准备

1. Backend：`aa9773e` 起 uvicorn（127.0.0.1:8000，`ENVIRONMENT=test
   STORAGE_BACKEND=memory`）+ PostgreSQL（便携版或 compose），迁移已应用；
   另起**第二实例 127.0.0.1:8001**（同库或独立库均可，供 C-12 换源测试）。
2. 构建包：从 `aa9773e` 构建 Windows 包（生产 CSP；构建期
   `VITE_BACKEND_URL=http://127.0.0.1:8000`）。启动命令带
   `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222`。
3. 账号：真实校园账号（2FA 走企业微信）；Backend 新建 **qa-round5** 全新用户
   （保证派生任务无旧数据干扰——任务列表里出现的每个任务都应可溯源到本轮采集）。
4. 开 `localStorage["agenthu.campus-debug"]="1"`（诊断通道，含 cookie 名不含值）。
5. 计时与 console 记录照旧写入 `tools/`（`timings.jsonl` / `console.jsonl`）。

## A. 登录与受信链（回归）

| # | 步骤 | 通过标准 |
| --- | --- | --- |
| A1 | Backend 登录（qa-round5） | 成功；密码提交即清空 |
| A2 | 校园登录（清 `campus.hold` 全新指纹，勾选信任设备） | **单轮 2FA** 完成登录；登录链内完成 learn 漫游（无采集期补登录） |
| A3 | 登出后重新登录（受信） | 免 2FA 直接就绪 |

## B. M1-1 主链（本轮核心）

| # | 步骤 | 通过标准 |
| --- | --- | --- |
| B1 | 点击采集 | 课表+校历+课程+作业**四域全部成功**（zhjw http 窄口继续工作）；记录事件总数 |
| B2 | 同步 | `accepted=N, rejected=0, 待同步=0`——**rejected 必须为 0**：客户端已发 `+08:00`，出现 naive 拒收即 D-028 时区修复失效（P0 级失败） |
| B3 | 派生任务呈现 | 任务列表出现作业任务：标题为作业名、**「校园采集」徽标**、无 UUID 裸露 |
| B4 | **截止时间无偏移**（关键判据） | 任选 2 门作业：客户端显示的截止时间与 learn.tsinghua.edu.cn 网页端显示**精确到分钟一致**；`GET /v1/tasks` 原始 JSON 的 `due_at` 偏移量正确（`+08:00`） |
| B5 | 重复采集幂等 | 立即二次采集+同步：任务数不变（不翻倍）；`重复=N` 结算正确 |
| B6 | CurrentState 投影（D-027 首次实测） | 今日计划标题右侧 `available_minutes` 徽标**非空且数值合理**（对照当日课表估算）；`context` 文案与当时情境相符（在课/即将上课/空闲）；`recent_state.available_minutes_breakdown` 各分量合理 |
| B7 | 计划→Focus 闭环 | 从**真实派生任务**生成今日计划（显示标题非 task_id）→ 确认 → Focus 开始 → 完成：actual_minutes 由后端计算、任务转 done、`focus.completed` 联动 |

## C. B-4 换源免重构建（新验收）

| # | 步骤 | 通过标准 |
| --- | --- | --- |
| C1 | 运行时在登录面板「Backend 地址」填入 `http://127.0.0.1:8001` | Rust 校验通过、持久化并重载；任务/计划数据来自 8001 实例 |
| C2 | 清空该设置 | 回落构建期默认（8000），数据随之切换 |
| C3 | 全程 DevTools console | **0 条 CSP violation**（生产 CSP 现为 `'self'+ipc:`，Backend 流量全走 IPC）；无未处理拒绝 |

## D. 断网与队列（回归，带派生链路）

| # | 步骤 | 通过标准 |
| --- | --- | --- |
| D1 | 杀 Backend → 采集 | 事件全量落本地队列，徽标显示待同步数，无异常 |
| D2 | 恢复 Backend → 「重试同步」 | 重复结算正确、徽标归零；派生任务不因重放翻倍（幂等约束实测） |

## E. e2e 首跑（工具化，B 到场）

| # | 步骤 | 通过标准 |
| --- | --- | --- |
| E1 | 运行 `tests/e2e` 外壳用例（无凭据） | 通过 |
| E2 | 运行真实账号主链用例（TOTP 人工输入） | 通过；记录总时长 |
| E3 | 现场**新增 spec**「派生任务出现且截止时间无偏移」（A 在 #8 review 的建议） | 断言 B3/B4 要素；作为本轮交付物之一提交 |

## F. 观察项（不阻塞，记录即可）

- 21ms 瞬态失败（round-3 后未复现）。
- 课表最新修订解析失败回退旧修订的边缘场景（PR #3 备注①，哨兵未加）。
- `available_minutes_breakdown` 在长课表日的合理性。

## 通过标准与产出

- **B 组全部通过 + A/C/D/E 无 P0/P1 缺陷** → M1-1 验收通过。
- 产出：`HANDOFF/<日期>-round5-acceptance-report.md`（计时表、通过项、缺陷
  清单、E3 新 spec）；timings/console 归档。
- 通过后动作：A/B 共同更新 CURRENT_STATE/DECISIONS 收口 M1-1；A-3 backlog
  排期（keyset 分页、Redis 限流、M3 预研）；M3 Memory/Grounding 进入规划。
- 新缺陷按既定协议：D 编号报告 → 协调人验证真伪 → 立项分配。

## 分工

- 执行：测试人（真实凭据）；B 到场支持 E 组与客户端复现；A 待命后端问题。
- 协调人：缺陷核验与任务分配（不变）。
