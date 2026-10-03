# M3 验收轮记录（2026-10-03，A 执行，栈 + 打包客户端）

**结论：验收轮主体完成。** E5 后端半边在合并后 main（`900c0b`）复跑绿；
**验收轮首个产物 = 发现并修复 keyword AND 缺陷（PR #47）**；检索延迟口径
拆分并采到首组 HNSW 数据；**E5 UI 半边在打包客户端全链绿**（新 spec
`e5-m3-exit-ui.spec.ts`，1 passed 5.2s）。唯一未闭环项 = campus 真机上传
链（验收 1 的「列表出现真实文件」），需用户在构建包内登录校园账号，
见文末移交。

## 1. 发现并修复：关键词通道 AND 笔误（PR #47）

- **信号**：E5 复跑绿，但 uvicorn 日志 `keyword_candidates=0`——问题里的
  内容 token 明明在 chunk 原文。
- **根因**：`and_(*like_clauses)` 应为 `or_`——chunk 被要求同时含问题里
  所有 token，真实问题必带功能词（what/does）→ 通道恒零。与设计意图、
  #43 交付报告（"ILIKE OR tokens"）和原注释均不符，属交付转录笔误。
- **为何此前未现形**：向量通道在小语料下 top-8 全返回，集成测试的
  grounded 断言被单通道满足——**通道级候选数日志第一次把它摆上台面**
  （延迟日志的意外红利）。
- **修复面**：or_ 语义 + 回归测试（无 embedding chunk + 混合 token 问题
  须经关键词通道召回）+ 两个把 RRF 排序写死的既有测试改为顺序无关
  （provider 增 `scripted_fn`，引文从上下文原位提取——E5「断言对齐判据、
  不锁排序」教训的测试面复用）。全量 301 passed；修复后实测
  `keyword_candidates` 0 → 2。

## 2. 检索延迟口径拆分 + 首组 HNSW 数据

原 `latency_ms` 混计 provider embed 往返与 DB 扫描（实测混计 1490ms 里 DB
只占小头）——对 HNSW 决策不可用。拆为 `scan_ms` / `embed_ms`（PR #47 内）。

首组数据（2-chunk 语料、A compose 栈、replay embed）：
`scan_ms=33.0/15.0`，`embed_ms=186.1/72.8`。**当前语料量级下 DB 扫描远非
瓶颈**——HNSW 结论：继续等语料规模数据，方向不变。

## 3. E5 UI 半边（打包客户端 + CDP）

新 spec `apps/desktop/tests/e2e/e5-m3-exit-ui.spec.ts`（门控
`AGENTHU_E5_UI=1`）：构建包内 Backend 登录 → 讲解视图 → 同意门（读文案 →
开启）→ 提问（记忆参与）→ 引用标记/引用卡渲染 + 双向跳转高亮 → 删
Learning Memory 同问不再体现 → 历史删除。**1 passed 5.2s**。

带跑修正（各有价值，均已固化进 spec/注释）：

1. **裸 `cargo build` 产出 dev 模式二进制**（WebView 走 devUrl :5173 死链）
   ——打包口径必须 `--features tauri/custom-protocol`（或 tauri CLI）。
   构建命令：`VITE_BACKEND_URL=http://127.0.0.1:8010 pnpm build` +
   同 env `cargo build --features tauri/custom-protocol`（Vite 烤前端 +
   build.rs 注入 Rust 源 allowlist）。
2. fixture 声明须先于 `test.skip`（`const test` 遮蔽导入名的 TDZ）。
3. **strict mode**：ask 成功会 invalidate 历史 →「最新回答卡」与「历史
   列表同一条」同时渲染、同文案两处——断言一律 `.first()`。**顺带 UI
   观察（转告 B，非阻塞）**：两卡用同一 `answer.id` 拼 DOM id，重复 id
   时跳转/高亮命中第一处。
4. 跳转高亮的方向语义：**卡→标记**方向置高亮（onHighlight 在卡按钮），
   标记→卡只滚动。
5. Backend token 在 Stronghold 跨重启存活——spec 开头处理残留登录态
   （「退出 Backend」按钮仅在已登录时渲染）。

## 4. campus 真机上传链（唯一阻塞，移交）

- 现状：构建包校园未连接，MaterialsPanel 如实报「课件列表需要校园账号」
  （fail-visible 正确）。
- 需要用户操作：在构建包内登录校园账号（学号 + 密码 + 2FA——凭据操作，
  Agent 不代办）→ 讲解页选真实课程 → 真实文件列表 → 单文件上传。
- **顺序建议**：B 的 `read_timeout(30s)` 跟进 PR 先行落地（尚未开出）——
  否则真机链撞上 learn 端僵死连接会无限挂起「转送中…」。
- 上传成功后按 E5-UI 流程复验提问/引用即闭环验收 1。

## 5. 环境与复现（A 栈手册）

- compose `db/redis/s3mock` + 独立库 `agenthu_e5`（alembic 从零）+
  uvicorn `:8010` + arq worker + `e5-replay.mjs :9099`（env 同 E5 栈）。
- 构建：见 §3.1；运行：`WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS=
  --remote-debugging-port=9222` 起包。
- E5 backend：`AGENTHU_E5_FULL=1`；E5 UI：`AGENTHU_E5_UI=1` +
  `AGENTHU_TEST_BACKEND_URL`（与构建期 VITE_BACKEND_URL 同源）。
