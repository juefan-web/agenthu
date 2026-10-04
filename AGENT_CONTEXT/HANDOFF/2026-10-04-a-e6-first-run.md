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
