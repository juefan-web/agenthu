# M4-B3 任务：E6 出口 e2e（契约 §8 六场景，构建包/CDP）

Status: **工件交付（2026-10-04）；首跑待栈机**——B 机无 docker/PostgreSQL/
Redis（多路径核实），E6 栈无法本地拉起；运行手册见 §4，首跑按协调人分派
（A 的 E5 栈先例或本地安装决策后 B 自跑）。

## 1. 目标 / 输入 / 输出

- **目标**：按 `m4-action-confirmation-chat-contract.md` §8 六场景验证 M4
  出口判据（D-030 口径：Agent 主动提出需确认的动作、Chat「为什么」得到
  basis 解释、断供后计划/重排仍工作）。
- **输入**：main 上的 B2 视图族 + A2/A3 全部端点；E5 的构建包/CDP 口径。
- **输出**：`apps/desktop/tests/e2e/e6-m4-exit-ui.spec.ts`（门控
  `AGENTHU_E6_UI=1`，serial 六用例）+ `e6-replay.mjs`（三模式 provider
  假件）+ README「E6 栈」手册。
- **不负责**：跨会话搜索（等 A 契约演进冻结稿与 B 同批）；grant 管理 UI。

## 2. 场景 → 断言映射（已实现判据）

| # | 契约 §8 场景 | spec 断言 |
| --- | --- | --- |
| 1 | 超时 Focus → L1 重排建议 | API：DRAFT `replaces_plan_id` 落库（worker 30s cron）；UI：重排建议卡 + 超时理由；依据同源以 **run 级结构化 basis references** 核验 |
| 2 | Chat 请求 → `task.create` L2 卡片 | 同意门（读文案→开启）→ 202 → 助手回复 + 动作行 → 深链卡片：安全参数（标题值）/Level 2/**动作确认截止的绝对时间 + 倒计时**（`PendingActionRead.expires_at`；replay 提案不带任务 due date，契约 §8 的「绝对到期时间」即此字段）/basis |
| 3 | 「为什么」同一份 basis | 卡片与消息展开的是同一 run basis；kind 标签渲染、定位不是正文 |
| 4 | 确认恰一次 | UI 防双击（连点两次）+ API 并发双 `mutation_id` confirm → 双 200、任务数恰 +1 |
| 5 | 断供明确失败 | replay `unavailable`（/v1/responses 503）→ Chat 明确失败面；今天计划/重排建议/专注仍可操作 |
| 6 | 预算/免打扰 + L3 grant | 偏好面设 replan + 上限 2 → 触发①无 grant PENDING→确认送达 1/2 → grant（值级 scope）→ 触发②自动送达 2/2 → 触发③预算耗尽如实抑制入历史账本 |

## 3. 缺口矩阵（B3 准备期确诊，报协调人裁定）

| # | 契约条款 | 现状 | 影响 |
| --- | --- | --- | --- |
| 1 | A 契约 §7：确定性 planner/replan 写 Plan 时产生 references，落 `basis.agent_decision` | **无写入者**——建议 basis 仍是 legacy 弱类型（`trigger_signature`/`replaced_plan_id` 等） | 场景 1「与 Plan.basis 相同依据」只能以 run 级 basis 核验；`BasisPanel` 的 agent_decision 兼容层（#55）无活数据 |
| 2 | B 契约 §5：删消息「关联引用改为 source_deleted」；引用失效态 | **无发射点**——`source_deleted`/`version_mismatch` 仅存在于 schema/枚举/单测 | 场景 3「失效来源显示失效标识」的活链断言无法落（UI 渲染路径已由 `DecisionBasisView.test` 单测钉住） |
| 3 | B4① `chat_message` kind | schema 级在库，运行时无产出者 | 同上，待 A 侧 context 装配/runner 补 |

**建议处置**：三缺口同属「结构化 basis 的产出面覆盖」，宜并成一个 A 侧
小切片（planner/replan 写 agent_decision + 引用失效态发射点）随 M4 收口
前落；E6 先按已实现判据出首跑报告，缺口闭合后补两处断言（spec 内已留
注释锚点）。

## 4. E6 栈与首跑手册（栈机执行）

1. compose `db redis s3mock` + 独立库 `agenthu_e6`（alembic 从零 up）+
   uvicorn（:8010）+ arq worker，进程环境同 E5 栈
   （`OPENAI_BASE_URL=http://127.0.0.1:9099/v1`、`OPENAI_API_KEY=e6-replay`
   非空占位、`STORAGE_BACKEND=minio`、S3 指向 s3mock）。
2. provider 假件：`node apps/desktop/tests/e2e/e6-replay.mjs`（:9099；默认
   grounding 兼容 E5，`POST /__mode` 切 chat-tools / unavailable——spec 自管
   切换，勿手工干预）。
3. 构建包：`VITE_BACKEND_URL=http://127.0.0.1:8010 pnpm build` + 同 env
   `cargo build --features tauri/custom-protocol`（E5-UI 手册 §3.1）；
   `WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=--remote-debugging-port=9222` 起包。
4. 运行：
   `AGENTHU_TEST_BACKEND_URL=http://127.0.0.1:8010 AGENTHU_E6_UI=1 pnpm --filter @agenthu/desktop exec playwright test e6-m4-exit-ui`
   （EMAIL/PASSWORD 非空占位；serial 六用例，场景间共享构建包内登录态）。

## 5. 验收标准

1. 六用例全绿（或附缺口矩阵 #1/#2 的已实现判据口径说明）。
2. 断言对齐判据本身、不锁检索排序；重复渲染一律 `.first()`（E5 教训）。
3. 首跑报告含：运行环境坐标、逐场景结论、缺口处置建议。
