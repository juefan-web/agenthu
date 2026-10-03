# E5 — M3 出口场景（grounded 讲解全链）

状态：后端半边已交付并首跑全绿（2026-10-02，spec
`apps/desktop/tests/e2e/e5-m3-exit.spec.ts`，门控 `AGENTHU_E5_FULL=1`，
首跑记录 `HANDOFF/2026-10-02-e5-backend-half-first-run.md`）；UI 半边等
#44 讲解页合入 main 后补交互断言。

## 目标

把 M3 的出口判据自动化：TASKS/m3-grounded-answers.md 的「删除 Learning
Memory 后，回答不再体现该记忆」+ AGENTS §8 的「引用真实存在、可定位、
支持结论」。沿用 E4 模式：真实栈（compose + uvicorn + arq worker）、
环境变量门控、spec 内编号断言、首跑记录入 HANDOFF。

场景一句话：上传课件 → 按课程开启资料问答（同意门）→ 提问 → 回答携带
机械校验通过的引用（文件 / 页码 / 摘录可核）→ 删除一条参与过该回答的
Learning Memory → 同一问题再问，回答不再体现该记忆。

## 断言清单（后端半边 = spec 内 (a)–(g)）

- (a) 上传带 `course_name` 的合成 PDF → 真实 worker 抽取 → chunks
  `scan_status == "clean"`，consent 开启触发 backfill 后
  `embedding_present == true`。
- (b) 同意门：GET 下发 `enabled=false` + 文案（含 ≤30 天监控保留披露）+
  版本；PUT 回显版本后 `enabled=true`。
- (c) 记忆参与：创建 level 1 / confidence 0.9 的 Learning Memory → 提问 →
  `memory_ids` 含该记忆，回答文本含记忆参考句。
- (d) 引用可核：`grounded=true`；citations[0] 的 `page` 落在 fixture 页集合
  内、`quote` 是**其所引页**文本的逐字子串（spec 侧独立复核——「用户手里
  的原文可核」的机器等价物）。不预设哪页被引：检索排序不属于出口判据
  （实测 RRF 常把 page-2 chunk 排首，其文本同样回答该问题）。
- (e) 删除记忆：`DELETE /v1/memory/{id}` → 204。
- (f) 不再体现：同问题再问 → `memory_ids` 不含该 id、回答文本不含记忆
  参考句、仍 grounded（chunk 未变，引用不应受记忆删除影响）。
- (g) 回答删除入口：`DELETE /v1/material/answers/{id}` → 204，历史清空。

## 两阶段口径

- **Phase 1（本文件随附，可在当前 main 跑）**：API 造数 + API 断言的
  后端半边。上传走 `POST /v1/files`（multipart）——B 的上传 UI 落地前，
  造数用 API 是协调人允许的口径。
- **Phase 2（#44/#46 已合入 main，2026-10-03 交付 spec）**：
  `e5-m3-exit-ui.spec.ts`（门控 `AGENTHU_E5_UI=1`，构建包 + CDP）覆盖
  Backend 登录 → 讲解视图 → 同意门 → 提问 → 引用标记/引用卡渲染与跳转
  高亮 → 删 Memory 同问不再体现 → 历史删除。课件仍由 API 造数；campus
  真机上传链（验收 1 的「列表出现真实文件」）是验收轮人工项，不在
  spec 内。

## 环境与复现（Windows / A 栈）

```text
compose(db/redis/s3mock) → 独立库 agenthu_e5（alembic 从零 up）
uvicorn :8010 + arq worker，进程环境：
  STORAGE_BACKEND=minio  S3_ENDPOINT_URL=http://127.0.0.1:9090
  DATABASE_URL=…agenthu_e5  REDIS_URL=…
  OPENAI_BASE_URL=http://127.0.0.1:9099/v1  OPENAI_API_KEY=<replay 占位，非空即可>
replay：node apps/desktop/tests/e2e/e5-replay.mjs（零依赖，默认 :9099）
运行：AGENTHU_TEST_BACKEND_URL=http://127.0.0.1:8010
      AGENTHU_TEST_BACKEND_EMAIL/PASSWORD=<任意值，spec 自注册新账号>
      AGENTHU_E5_FULL=1
      pnpm --filter @agenthu/desktop exec playwright test e5-m3-exit
```

注意：起栈前后清点 python 进程（TaskStop 不杀子进程的教训）；worker 启动
后确认日志 `Starting worker for N functions`（E4 首跑教训）。

## replay 契约（recorded-replay 口径，任务书 §7 允许）

- `POST /v1/embeddings`：内容哈希 → 1536 维确定性向量（无随机、不落盘）。
  检索命中不依赖向量质量：E5 问题词与 chunk 文本在关键词通道（ILIKE）
  命中，RRF 融合后 top 6 稳定。
- `POST /v1/responses`：从请求 `input`（= `build_context` 产物）解析
  `[1]` chunk 块，取其开头 ≤60 字符逐字摘录构造 `「excerpt」[1]`；若
  `input` 含「已确认的个人学习记忆」块则附记忆参考句（含记忆内容前缀），
  否则附「无记忆参与」句——(c)/(f) 的确定性断言靶。
- replay 不转发真实供应商；后端 `store=False` 钉死不受影响。真模型实测
  等有效 key（独立批次，作为 prompt 调参前置）。

## 注意与耦合

- fixture 全合成（`fixtures/make_e5_fixture.py` 可再生成，无真实课程
  资料）。PDF 文本层用英文——CJK 进 PDF 有字体链代价（#41 教训），中文
  断言面已由单元 / 集成测试覆盖。
- 记忆检索门槛（D-031 §5）：confidence ≥ 0.3、非 REJECTED、非
  superseded。E5 seed 用 level=1 / confidence=0.9；UNREVIEWED 可被检索
  （`retrieve_memories` 不过滤该状态；build_context 的「已确认」是文案）。
- CJK 一律走 node fetch（UTF-8 全链）——不要用 Git Bash curl 内联中文
  （本地码页 mojibake 教训）。
- spec 与 replay 的摘录构造耦合：replay 的 excerpt 取自上下文里 chunk
  原文的开头切片，故机械校验必然通过——这是回放口径的确定性行为，
  不是校验弱化（校验的对抗面在单元 / 集成测试）。

## 未做（如实）

- UI 半边（等 #44 合入 main）。
- 真模型实测（本地环境已无 key，等有效 key 后单独跑一轮）。
- 多课程提问（M3 末尾隐私决策项）。
