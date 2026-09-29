# Round-5 后续任务（M1-1 收口后的跟进清单）

来源：`HANDOFF/2026-09-29-round5-acceptance-report.md`（A-D 组全过、M1-1 验收
通过）+ 计划审核修订。按责任分派；E 组与 L2 优先，其余为 M2 议题排期。

## 开发者 B

1. **E 组 spec 修订与首跑（优先）**：
   - `smoke.spec.ts` L49 `selectOption("totp")` 改为**动态选择账号实际可用方式**
     （combobox 现有 option，如 wechat）；L36 前置态改为「清 `campus.hold` →
     重启包」（保证登录表单存在；删除前先退出包进程，文件占用）。
   - 新增 E3 spec：「派生任务出现且截止时间无偏移」（B3/B4 断言要素：徽标、
     标题、`due_at` 偏移）。
   - 与测试人约时间首跑（E1 无凭据 + E2 真实链，TOTP 改为实际方式后预计
     验证码 1 个）。**M2 起的验收以 e2e 为常规工具**——本项是解锁条件。
2. **D1 断网快速失败（M2 议题，排期）**：对不可达 Backend 的 flush 失败处理
   ~13s，压缩到 ≤5s（连接超时/快速失败区分「不可达」与「慢」）。

## 开发者 A

1. **L2 任务列表截断（优先，小改动）**：`/v1/tasks` 默认 `limit=50`（上限
   200）且客户端无分页——79 条任务 UI 只见 50 条。短期：客户端请求
   `limit=200`；正确解：keyset 分页（本就是 A-3 backlog 的 events 同族问题，
   可一并设计）。契约变更走冻结流程。
2. **L1 breakdown 出口（M2 议题）**：`available_minutes_breakdown` 目前仅
   `recent_state` 内部字段，客户端契约不可见。决策：入 `ClientCurrentState`
   契约（可解释性）或出独立诊断端点（不膨胀主契约）。定了再动。
3. **L3 派生标题语义确认（小）**：50 个派生任务抽样 3 中 1 个标题能直接对上
   事件原文（`Homework 2` 型）。确认 assignment→task 的标题合成规则是否如
   预期（course 前缀？ trimming？），如是则补文档，否则修。
4. **L4 当日含项草稿不吸收新任务（决策）**：D7 修复只覆盖空草稿；已确认的
   当日计划不自动吸收新派生任务（需 cancel/重排）。确认这是 D-019/D-023 的
   预期行为并记录，或定义吸收语义（M2 planner 范畴）。
5. **L5 2099 哨兵作业（决策，小）**：上游存在 year-2099 占位作业，是否应在
   派生时排除（deadline 距今 >N 年视为哨兵）。定了规则加回归测试。

## 共同

- M1-1 正式收口（本文件随报告归档即完成）；M2 规划时把上述 M2 议题
  （D1 快速失败、L1、L4、events/tasks keyset 分页、多 worker Redis 限流）
  一并排期；M3 Memory/Grounding 预研启动。
