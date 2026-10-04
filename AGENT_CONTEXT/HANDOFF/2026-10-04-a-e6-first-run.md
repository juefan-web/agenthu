# 2026-10-04 · A：E6 出口 e2e 首跑（21 轮迭代 → 全绿）

## 结果

**六用例全绿（1.9m serial）**，另有紧随其后的一次确认跑。栈：compose
db/redis/s3mock + 独立库 `agenthu_e6`（alembic head `c4f2a8e01d73`）+
uvicorn :8010 + arq worker（12 functions）+ `e6-replay.mjs` :9099（spec
经 `POST /__mode` 自管三模式）+ custom-protocol 构建包经 CDP 9222 驱动。
main = `8d41a0b`（含 #58/#61/#62）+ 本轮修复。

## 产物与审计面（B 核账用）

- `D:\agenthu-wt-a\e6-logs\`：`playwright-run.log`（最终绿跑）、
  `playwright-run-confirm.log`（确认跑）、`uvicorn.log`、`worker.log`、
  `replay.log`、`attempt1/`、`attempt2/`（前两轮失败留档）。
- `agenthu_e6` 库**保留不清**；最终绿跑账号 = `users` 表最新一行
  （`e6-<ts>@e6.test`）。库里另有历史失败轮残留账号（每轮自注册新账号，
  互不干扰），核账以最终账号为准。
- 核账点：审计行（audit_log）、恰一次任务计数（`tasks` 中
  「复习第三章（E6 建议）」= 2 条：s2 UI 确认 + s4 API 并发恰一次各一）、
  预算账本三态（notification_preferences 1/2 → 2/2 → 抑制入
  pending_actions history 的 budget exhausted）、抑制入账
  （`result.summary` 含 budget exhausted 的历史动作）。
- 执行态铁证（2026-10-04T22:14:57+08:00，docs 补丁提交前采集）：两轮
  绿跑的源代码态即 PR #63 原 head `66af4d3`，其后 tracked 树零改动：

  ```text
  $ git -C D:/agenthu-wt-a rev-parse HEAD
  66af4d3c33c96f589d0c3e14dccbea33913a1513
  $ git -C D:/agenthu-wt-a status --short
  ?? e6-logs/
  ?? e6-start-stack.sh
  ```

  两条 `??` 为本地产物（栈日志目录、起栈脚本），非源码改动。
- 核账 SQL 四段输出（B 清单 = PR #63 approve @ `4f60ee8` 正文；A 于
  2026-10-04T23:09:41+08:00 在保留栈执行：`docker exec -i agenthu-db-1
  psql -U agenthu -d agenthu_e6 -X -v ON_ERROR_STOP=1`，十条全部 rc=0。
  原始输出未修数、未筛行；各段「预期」旁注摘自 B 清单，不符处如实贴出、
  不裁决，归核账报告）：

  **段 1 · 任务/计划账**

  1a 「复习第三章」恰一次落点（B 预期：恰 2 条，title 全等——相符）：

  ```text
           title         | status | source | est | actual | completed_at |          created_at
  -----------------------+--------+--------+-----+--------+--------------+-------------------------------
   复习第三章（E6 建议） | TODO   | agent  |  45 |        |              | 2026-10-04 12:55:42.314078+00
   复习第三章（E6 建议） | TODO   | agent  |  45 |        |              | 2026-10-04 12:55:45.222645+00
  (2 rows)
  ```

  1b 该账号任务全量（B 预期 7 = 复习×2 + overrun×4 + 豁免×1；协调人清点
  6 = overrun×3。**实际 7 行**，第 4 条 overrun = 「数字逻辑作业」——差异
  裁决归核账报告）：

  ```text
           title         |  status   | est | actual |         deadline          |         completed_at
  -----------------------+-----------+-----+--------+---------------------------+-------------------------------
   已过期豁免项（E6）    | TODO      |     |        | 2026-10-04 11:55:13.33+00 |
   线性代数作业          | COMPLETED |  75 |    100 |                           | 2026-10-04 12:55:13.620741+00
   复习第三章（E6 建议） | TODO      |  45 |        |                           |
   复习第三章（E6 建议） | TODO      |  45 |        |                           |
   概率论作业            | COMPLETED |  75 |    100 |                           | 2026-10-04 12:56:03.424546+00
   随机过程作业          | COMPLETED |  75 |    100 |                           | 2026-10-04 12:56:33.514442+00
   数字逻辑作业          | COMPLETED |  75 |    100 |                           | 2026-10-04 12:57:02.949985+00
  (7 rows)
  ```

  1c draft 重排建议（B 旁注「S1 出口件：恰 1 条」——**实际 4 条**：s1×1 +
  s6×3，每条 overrun 各产一条，与 4a 的 proactive WAITING×4 对齐；如实贴出）：

  ```text
                    id                  | status |  generated_by  |                                  replan_reason                                   | confirmed_at |          created_at
  --------------------------------------+--------+----------------+----------------------------------------------------------------------------------+--------------+-------------------------------
   32ba24da-e630-427e-a68c-54e3d0fb7a06 | DRAFT  | replan_trigger | 「线性代数作业」Focus 实际 100 分钟，达计划 75 分钟的 133%，今日后续安排需要重排 |              | 2026-10-04 12:55:30.686098+00
   78f28159-c6e1-4b82-a75e-7c657410106a | DRAFT  | replan_trigger | 「概率论作业」Focus 实际 100 分钟，达计划 75 分钟的 133%，今日后续安排需要重排   |              | 2026-10-04 12:56:30.598194+00
   71e28b1c-c519-480d-aa4a-d08f21f21a8b | DRAFT  | replan_trigger | 「随机过程作业」Focus 实际 100 分钟，达计划 75 分钟的 133%，今日后续安排需要重排 |              | 2026-10-04 12:57:00.280249+00
   df8f1a00-e4ae-42a9-815d-81d98e07435f | DRAFT  | replan_trigger | 「数字逻辑作业」Focus 实际 100 分钟，达计划 75 分钟的 133%，今日后续安排需要重排 |              | 2026-10-04 12:57:30.558756+00
  (4 rows)
  ```

  **段 2 · 预算 / 送达 / 抑制账**

  2a 预算账本终点（B 预期：daily_budget=2、sent_count=2、categories 含
  replan——相符）：

  ```text
   daily_budget | sent_count | budget_date |         last_sent_at          | enabled_categories | version
  --------------+------------+-------------+-------------------------------+--------------------+---------
              2 |          2 | 2026-10-04  | 2026-10-04 12:57:00.887621+00 | ["replan"]         |       2
  (1 row)
  ```

  2b 预算耗尽抑制入账（B 预期：恰 1 条，summary 含 budget exhausted——相符）：

  ```text
     action    |  tool_name  |  status   | required_level |                     summary                     |          finished_at
  -------------+-------------+-----------+----------------+-------------------------------------------------+-------------------------------
   notify.push | notify.push | SUCCEEDED |              3 | Notification suppressed: daily budget exhausted | 2026-10-04 12:57:31.118438+00
  (1 row)
  ```

  2c L3 grant 值级 scope（B 预期：恰 1 条 notify.push level-3，scope 含
  categories+channels——相符）：

  ```text
     action    | level |                      scope                      | note |          granted_at
  -------------+-------+-------------------------------------------------+------+-------------------------------
   notify.push |     3 | {"channels": ["web"], "categories": ["replan"]} | e6   | 2026-10-04 12:56:33.068898+00
  (1 row)
  ```

  **段 3 · 审计账**

  3 按 action 分桶（B 预期总数 96——相符，GROUPING SETS 末行 = 总计）：

  ```text
                                  action                                 | n
  -----------------------------------------------------------------------+----
   agent.run.failed                                                      |  1
   agent.run.queued                                                      |  7
   agent.run.started                                                     |  7
   agent.run.waiting_confirmation                                        |  6
   delete /v1/chat/messages/c4001e35-4e6a-426d-bdbe-12be28c6de7a         |  1
   notification.delivered                                                |  2
   notification.suppressed                                               |  2
   patch /v1/focus-sessions/21d4483a-1d30-47cb-8f14-2b6a4ef8d48a         |  1
   patch /v1/focus-sessions/49a5f54a-b0b2-449d-a113-3c59fc5f588a         |  1
   patch /v1/focus-sessions/78dacbe2-31ea-4234-912d-226eb2a55ecb         |  1
   patch /v1/focus-sessions/954cdf03-e377-4df4-8980-7907952953fc         |  1
   patch /v1/notification-preferences                                    |  1
   pending_action.confirmed                                              |  4
   pending_action.created                                                |  6
   pending_action.dispatched                                             |  6
   pending_action.succeeded                                              |  6
   permission.check                                                      | 12
   post /v1/chat/sessions                                                |  3
   post /v1/chat/sessions/266f1849-54ee-4b64-837e-8a91c200d25e/messages  |  1
   post /v1/chat/sessions/308f333c-4b05-4b93-b47e-517fc0d574ee/messages  |  1
   post /v1/chat/sessions/fdcc34cc-e465-4cb2-af3a-3f45a0e8810b/messages  |  1
   post /v1/focus-sessions                                               |  4
   post /v1/pending-actions/2d4d242c-6339-4932-8ec6-2fc406da2419/confirm |  1
   post /v1/pending-actions/4d7cacb4-8f1e-4f88-99f3-c31ef878be95/confirm |  2
   post /v1/pending-actions/b713c412-b1d7-4190-9fd1-a2d7aa162675/confirm |  1
   post /v1/pending-actions/ea81f347-f33e-40b6-b9ee-41f352d3e64e/confirm |  2
   post /v1/permissions/grants                                           |  1
   post /v1/plans                                                        |  4
   post /v1/plans/34596139-6fb0-40bd-9c6b-635a58c53c7f/confirm           |  1
   post /v1/plans/4f234e82-2a70-4f33-a75a-92be7fccc28c/confirm           |  1
   post /v1/plans/ab8c364d-f2bd-4ac4-871f-91d6e2b2cb07/confirm           |  1
   post /v1/plans/c8c8371d-4ff9-45f7-b57d-34ca3e79f524/confirm           |  1
   post /v1/tasks                                                        |  5
   put /v1/model-context-consent                                         |  1
                                                                         | 96
  (35 rows)
  ```

  **段 4 · run / 结算谱**

  4a run 状态谱（B 预期：chat FAILED×1 + WAITING×2、proactive WAITING×4
  ——相符；无 pending_action_resume / retry 桶）：

  ```text
    invocation_kind  |        status        | n
  -------------------+----------------------+---
   chat              | FAILED               | 1
   chat              | WAITING_CONFIRMATION | 2
   proactive_trigger | WAITING_CONFIRMATION | 4
  (3 rows)
  ```

  4b pending_actions 按状态分桶（如实）：

  ```text
    status   | n
  -----------+---
   SUCCEEDED | 6
  (1 row)
  ```

  4c S4 并发恰一次 mutation 缓存（B 预期：恰 2 行，settled 状态一致——相符）：

  ```text
   mutation_id |  kind   | settled_status |          created_at
  -------------+---------+----------------+-------------------------------
   e6-conc-a   | confirm | SUCCEEDED      | 2026-10-04 12:55:45.310105+00
   e6-conc-b   | confirm | SUCCEEDED      | 2026-10-04 12:55:45.22503+00
  (2 rows)
  ```

## 迭代账（21 轮，全部「工件对码 → 栈日志 → 修订」序）

| # | 首绿 | 定性 |
|---|---|---|
| 1 | — | s1 断言越权：agent_decision references 只引被排入任务，而真实 focus 链把超时任务置 COMPLETED（库证据：task=COMPLETED actual 100/planned 75；建议重排豁免 touch 任务）→ spec 修订为引用实际重排输入 |
| 2 | s1 | **环境事件**：失败两分钟后桌面人工交互（confirm/接受建议/ignore/逛偏好）污染该轮账号库态——已披露，run 判定不受影响（失败先于交互）。后续轮次无复现 |
| 3 | s1-s2 | s2 产品缺陷：深链后收件箱吃 staleTime 缓存（登录批拉恰好抢在动作插入前 0.1s）→ 产品修复①（结算失效 pending-actions） |
| 4-5 | — | 无配置运行：`pnpm --filter exec` cwd 在 apps/desktop，`tests/e2e/playwright.config.ts` 不被加载 → 默认 30s 测试超时 vs spec 内 60-130s 等待，相位差即爆（"page closed" 是拆页伴生）→ 运行加 `--config`，命令修正进 spec 注释 |
| 6 | s1-s2 | s3 spec：视图重挂载后会话选择归零（ChatView 条件渲染、sessionId 组件态）→ 三处补会话点击 |
| 7 | s1-s3 | s4 首执行：导航「确认」可访问名含徽标（"确认 1"）→ exact 正则；双击 locator 重解析误点下一卡 → 卡片圈定；「已完成」在历史账本不在活动卡（确认即离场）→ 断 hidden + 历史账本 tab（role=tab 非 button） |
| 8-9 | s1-s3 | 探针谓词 `tool_name` 扁平形不存在（读面嵌套 `tool.name`）→ 修；第二击无界 actionability 悬到 180s（disabled 无默认超时）→ 5s 有界 |
| 10-13 | s1-s4 | s5 精确匹配两处（今天/专注 vs 聊天消息按钮、专注记录 h2） |
| 14 | s1-s5 | s6 收件箱 staleTime 第三咬（偏好面往返 <30s 回确认视图旧缓存）→ 产品修复②（refetchOnMount always） |
| 16/18 | — | 跨账号缓存泄漏：重启后恢复旧会话，登出 invalidate 拿死 token 重取且错误态保留旧 data、boot 默认视图未重挂载端出前一账号建议 → 产品修复④（logout 改 clear）+ s1 等新账号特有任务名（登录后失效重取竞态——app 侧本有 invalidate，纯 spec 竞态） |
| 17 | s1-s5 | s6 提醒面 staleTime（1/2 送达已落账、面板旧 0/2）→ 产品修复③ |
| 19 | s1-s5 | grant scope 缺 `channels`：strict_scope_validator 对 list_keys 双必填（§5.3 fail-closed，A3 测试同款形状 `{"categories":[...],"channels":["web"]}`）→ spec 补全 |
| 20 | s1-s5 | 已激活提醒面重复点击不重取 → 先离再进（今天→提醒） |
| 21 | **全部** | 🟢 6 passed (1.9m) |

## 产品修复清单（客户端五文件，全部单测绿）

1. `ChatView.tsx`：run 结算失效 `["pending-actions"]`（+ 测试断言）。
2. `PendingActions.tsx`：收件箱 `refetchOnMount: "always"`。
3. `NotificationPreferencesView.tsx`：同款（当下账本读数）。
4. `App.tsx`：退出 Backend `queryClient.clear()`（换用户忘却旧缓存）。

## spec 修订要点（见文件内实证注释）

- **必须带 `--config tests/e2e/playwright.config.ts`** 运行，否则默认 30s。
- s1：先导航今天；等新账号任务名（登录重取竞态收口）；references 断言
  与产品语义对齐（结构层引被排入者，人话层由 summary 点名超时任务）。
- s3：删除走 UI（真实路径 + 自带失效）；服务端翻转核验照旧。
- s4：卡片圈定双击；第二击 5s 有界；终态断历史账本。
- s6：grant scope 补 channels；已激活视图先离再进。

## 未尽事项

- B 核账报告 → M4 按 D-030 收口（协调人执行）。
- 桌面在跑测期间曾有一次人工交互（第 2 轮后）——正式验收跑建议桌面空闲
  时执行；本轮最终绿跑与确认跑均无干扰迹象。
