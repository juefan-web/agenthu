# E5 后端半边首跑记录（2026-10-02，A 执行）

**结论：`AGENTHU_E5_FULL=1` 后端半边 1 passed（5.3s，测试体 4.0s）——M3
出口判据的 API 全链首次在自动化验收里走通**：上传 → 真实 worker 抽取/嵌入
→ 同意门 → 提问（记忆参与）→ 引用机械可核 → 删 Learning Memory → 同问
不再体现 → 删回答清空历史。断言编号与 `TASKS/m3-e5-exit-scenario.md`
一一对应，(a)–(g) 全绿。

## 环境（可复现）

- compose `db/redis/s3mock` + 独立库 `agenthu_e5`（alembic 从零 up 到
  `e3a7c59f21b8`），uvicorn `:8010` + arq worker（`WorkerSettings` 9
  functions，启动日志核过），replay `e5-replay.mjs :9099`。
- uvicorn/worker 进程环境：`STORAGE_BACKEND=minio`、
  `S3_ENDPOINT_URL=http://127.0.0.1:9090`、
  `OPENAI_BASE_URL=http://127.0.0.1:9099/v1`、`OPENAI_API_KEY=<占位非空>`。
  （宿主环境里已删除的旧用户级 `OPENAI_API_KEY` 由内联赋值显式覆盖——
  当时的 401 事故不会再混淆口径。）

## replay 侧直接证据

- 每次 `/v1/responses` 调用 `store=false`（D-033 钉死在真实 HTTP 载荷上可见）。
- `memories=true`（ask 1，记忆在上下文）→ `DELETE /v1/memory/{id}` →
  `memories=false`（ask 2）——出口句「删 Learning Memory 后不再体现」在
  供应商边界两侧都有证据。

## 带跑三次修正（各有价值）

1. **ESM 无 `__dirname`**：spec 改 `import.meta.url` + `fileURLToPath`。
2. **consent 是 PUT**：spec helper 默认 POST → 405；§6 冻结形状复习
   （GET/PUT，无 POST）。
3. **断言过度指定（真教训）**：预写 `citations[0].page == 1`，实测 RRF
   常把 page-2 chunk 排首——关键词通道两页都命中，向量通道是确定性哈希
   向量，融合排序不保证语义首选。出口判据只要求「引用真实、可定位、
   支持结论」，已改为「被引页 ∈ fixture 页集合 且 quote 是该页原文的
   逐字子串」。**e2e 断言应对齐判据本身，不锁检索排序这类实现细节。**
   （page-2 文本同样回答该问题，被引并非错引。）

## 旁证（既有纪律再坐实）

Git Bash curl 探 replay 时全角括号 `（）` 被本地码页毁掉 → 正则不匹配 →
空摘录「」；改 node fetch（UTF-8 全链）探针即通过。**CJK 一律走
node/python HTTP 客户端**第三次实测成立。

## 验证面

- 后端全量：294 passed + 6 skipped（深夜墙钟守卫类，预期跳过）。
- `apps/desktop` `tsc --noEmit` 干净；ruff format/check 干净。
- fixture 重新生成 + pypdf 抽取往返校验通过（make_e5_fixture.py 自带）。

## 遗留（如实）

- UI 半边：等 #44 讲解页合入 main 后追加交互断言；B 上传 UI 落地后把
  (a) 换成 UI 上传即完整版。
- 真模型实测：本地已无任何 key；等有效 key 后单独跑一轮（prompt 调参
  批次前置）。
- 多课程提问：M3 末隐私决策项，未动。
