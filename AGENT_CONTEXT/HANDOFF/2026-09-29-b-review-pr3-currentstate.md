# 开发者 B：PR #3（D-026 + D-027）审查记录

审查人：开发者 B（Client / Study + Time）· 2026-09-29 · 审查对象
`feature/m1-currentstate-projection` @ `274cac1`（PR #3）。

## 结论：**Approve**（无阻塞意见；两条非阻塞备注见末节）

## 逐项核对

1. **客户端契约零影响（B 最关注项）**：`current_state_to_client` 改为消费
   `CurrentStateRead.context_label`（recompute 内 override 优先的最终值），
   `ClientCurrentState.context` 字段形状不变；`context_label` 不进 OpenAPI。
   客户端 Zod（`CurrentStateSchema`）无需改动，drift 面干净。
2. **D-026（D9 边界还债）**：A 的联合 review 把范围最小性（单 host 单端口）、
   重定向继承（同谓词）、伪造测试覆盖（子域/后缀/端口）逐项核对并记录在
   `client-merge3-d9-and-residuals.md` 末节，与 B 侧实现与测试一致；revisit
   条件（上游转 https 当天移除窄口）明确。无异议。
3. **D-027 口径 vs UI 直觉**：
   - 优先级链 override > 在课 > 专注中 > 进行中 > 即将上课（≤30min）> 空闲 >
     None 与用户心智一致——课中不会被"任务"盖住，专注优先于普通进行中。
   - 「在课：课程@地点」「即将上课：课程（n 分钟后）」文案可直接落入今日计划
     标题右侧的 meta 槽位，无需客户端改写。
   - `available_minutes` 口径（override 优先，否则 剩余日 − 课表重叠 − 当前任务
     估时，休息显式 0）可解释、可审计（breakdown 入 recent_state）——徽标旁
     无需额外解释文案。
   - derived 不落列、Event 流为事实源：与客户端"每次 GET 拿投影"的消费方式
     兼容；投影时效 = recompute 触发粒度（见备注 2）。
4. **测试**：8 个用例覆盖决策文档全部分支（无数据/在课扣减/即将上课/双
   override/最新版本胜出/专注压任务/空闲/client_view 端到端），含
   `latest_revision_wins_per_upstream` 的移课不双计。覆盖充分。

## B 侧对齐确认（round-5 清单，D-027 文件「与 B 的对齐清单」三条）

1. **available_minutes 徽标**：采纳。今日计划标题右侧显示「剩余可用 3h20m」
   格式徽标（≥60 分钟 `XhYm`、不足 1 小时 `Ym`）；`null`（无 override 且无
   待办推导）不显示。实现见本分支 `formatAvailableMinutes` + App 今日计划
   标题（`feature/current-state-presentation`）。
2. **「空闲」派生默认与 None 占位**：「空闲」（有待办、无更高优先级状态）
   合意，优于空白；`None` 维持客户端现状占位「当前上下文未设置」。
3. **口径变更纪律**：知悉——口径调整一律走 DECISIONS 变更，客户端只消费
   不推导。

## 非阻塞备注（供 A 参考，不挡合并）

1. `_today_schedule_entries`：某 `upstream_id` 的**最新修订**解析失败时
   `continue` 未登记该 upstream，循环会采用**更旧的修订**（陈旧课表条目
   复活，可能与移课后的新版双计或错计）。建议解析失败也登记哨兵（视为
   "该条目当前无效"），阻断旧版本回退。边缘场景，M1 内顺手修即可。
2. 派生 label 与 available_minutes 的时效 = recompute 触发粒度（事件驱动），
   无事件的时段内"在课/即将上课"可能陈旧。round-5 验收措辞已按"课中采集后
   显示"对齐；定时重算触发器已另立决策，客户端徽标同样消费投影值，预期
   一致，无需本侧动作。
