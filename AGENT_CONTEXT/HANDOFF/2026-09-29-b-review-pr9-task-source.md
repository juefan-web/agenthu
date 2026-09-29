# B 对 PR #9 的审查记录（ClientTask.source + D-028 §3a 勘误）

- 日期：2026-09-29
- 审查人：开发者 B（juefan-web，GitHub 首次正式 approve——作者 rotcar07，
  此前 gh CLI 未认证时以 HANDOFF 文件代替，本轮起恢复正式流程）
- 结论：**Approve，已合并 `efc4c8c`**
- 分支：`feature/client-task-source-field` @ `944b2e5`（基于 #4 合并点，对新
  main MERGEABLE，CI 双轮全绿）

## 审查范围与核验

PR 内容（5 文件 ~60 行）：DECISIONS D-028 §3a 勘误、`ClientTask.source`
（`str = "manual"`）、`client_view.py` 接线、OpenAPI 刷新、主链两断言。

1. **代码路径独立核验**（不止看 diff）：
   - 持久层 `Task.source` 列（`String(50)`, default `"manual"`, unique
     `(user_id, source, source_upstream_id)`）来自已合并 #4，本 PR 无重复改动。
   - 派生链路成立：`event_handlers.py` 以 `source=event.source` upsert →
     校园事件 envelope `source="onethu"` → 派生 Task 继承 → 断言
     `derived[0]["source"] == "onethu"` 的前提核实无误。
   - `source` 为自由字符串与 B 侧 Zod `z.string().optional()` 约定一致
     （client_contract.py 注释已写明衔接方式与过渡语义）。
2. **勘误内容核对**：§3a 勘误准确反映 B 在 PR #4 审查备注 #1 的事实——
   协调器对 rejected 的既有语义（有回归测试）是移出队列并把 reason 透出
   UI；恢复路径是重新采集（被拒事件未入库、服务端 dedupe 无记录，新
   semantic_version 正常派生，无锁死）；勘误明文禁止按原文实现「保留重发」
   特殊分支，原文保留于勘误标记下可追溯。
3. **本地独立重跑**：ruff 全过；unit 83 passed；
   `check_contract_drift --require-zod` 双 Zod 源无漂移；集成测试本地无
   PostgreSQL 优雅跳过，以分支 CI 为准（6 checks 全 success：backend/
   compose-smoke/pip-audit/docker-build/frontend/tauri-rust）。

## B 侧闭环（同日，`feature/task-source-badge`）

PR #9 只解决服务端透出；客户端侧随后落地：

- `packages/contracts` 与冻结快照 `tests/fixtures/client_contract.ts` 的
  `TaskSchema` 同步加 `source: z.string().optional()`（旧 Backend 载荷缺失
  该字段仍解析为 undefined，按 manual 对待）。
- TaskList 抽为 `components/TaskList.tsx`（沿 CampusConnection 先例），
  加来源徽标：`onethu` → 「校园采集」；未知来源显示原始字符串（为未来
  connector 留扩展）；manual/缺省不标。
- 测试：6 个 RTL 用例（徽标三分支 + 空态/加载/错误回归）+ 2 个 contracts
  契约用例（source 保留、backend-only 字段剥离、旧载荷兼容）。
- 全部验证绿：drift 双源、desktop 85、contracts 5、lint/typecheck/build。
- 实现注记：drift 检查器按逗号分割 Zod 对象体，`z.object({...})` 内的
  注释行会被误解析为字段名（实测报 `ClientTask.// Task origin: missing
  from OpenAPI`）——注释必须写在 schema 定义上方。

## 遗留 / 下一步

- round-5 真实数据全链验收（双方，全部前置已在 main）：采集 → 派生任务
  两端呈现（截止无偏移、重复采集不翻倍、来源徽标）→ 计划/Focus → 完成。
- e2e 冒烟可在验收时顺手补 A 建议的「派生任务出现且截止时间无偏移」spec。
