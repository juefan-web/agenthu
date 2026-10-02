# M3 资料摄取批次（backend，D-033 落地第一刀）

状态：**delivered，待 B review**（A @ `feature/m3-materials-ingestion`，2026-10-02。
前置已满足：D-033 双签 + provider 政策首核双核完成（PR #36），
pgvector 切片已合（PR #35，main `3daf140`）。验收 §6 全项达成：
262 tests passed、ruff/format 干净、迁移 up→down→up + `alembic check`
无漂移、契约 drift 零——实现细节偏差与语义注记见 CURRENT_STATE 当日条目）。

## 目标 / 输入 / 输出 / 范围（AGENTS §5.2）

- **目标**：落地 D-033 的文件→chunk 摄取管线与供应商边界——显式上传的
  课程文件被 worker 按页抽取、过内容安全扫描后入 `material_chunks`；
  文本送模型供应商维持**默认关闭**，按课程 opt-in（带披露文案）后仅对
  clean chunk 计算 embedding。
- **输入**：`TASKS/m3-course-materials-privacy.md`（规范文本，含 §7 实现约束
  `store: false` + 同意文案）、`TASKS/m3-memory-schema-migration.md` §6
  （依赖图位置：material_chunks → embedding → blob）、PR #35 的
  `memories.embedding vector(1536)`、现状 `files.py`/`worker/`/`storage.py`。
- **输出**：一条迁移（`material_chunks` + `grounding_consents` 两表 +
  `file_objects.course_name` 列）、扫描器、抽取器、模型 provider 适配层、
  consent API、worker 任务（抽取 / 课程回填嵌 / 兜底 cron）、删除顺序修正、
  对外 API（chunks 列表 + consent 读写）与 openapi 同步、测试。
- **负责范围**（A）：backend 全部 + 迁移 + openapi + 本文档。
- **不负责范围**：向量召回与混合检索（#37 合并后另批：下限过滤之后应用）、
  grounded 回答生成 / 引用机械校验 / 回答落库（讲解页后端切片另批）、
  客户端上传 UI 与 Tauri 命令、讲解页 / 引用跳转（B）、HNSW 索引（先测
  规模）、M5 删除入口 UI、录音/转写（D-033 明确排除，另行决策）。
- **验收标准**：见 §6。

## 1. 数据形状（本批冻结）

```sql
CREATE TABLE material_chunks (
  id UUID PK,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  file_id UUID NOT NULL REFERENCES file_objects(id) ON DELETE CASCADE,
  page INTEGER NULL,                -- 1-based 页/slide；txt 无页概念为 NULL
  chunk_index INTEGER NOT NULL,     -- 文件内稳定顺序
  content TEXT NOT NULL,            -- 扫描归一化后的文本
  char_count INTEGER NOT NULL,
  scanner_version TEXT NOT NULL,    -- D-033 §5：哪版规则扫的
  scan_status TEXT NOT NULL CHECK (scan_status IN ('clean','flagged')),
  scan_flags JSONB NOT NULL DEFAULT '[]',
  embedding vector(1536) NULL,      -- opt-in 后回填；blocked 不入库、flagged 不嵌
  embedding_model TEXT NULL,        -- 换供应商全量重嵌的依据（同 memories 语义）
  created_at/updated_at,
  UNIQUE (file_id, chunk_index)
);
-- 用户隔离（P0）与按课程过滤（join file_objects.course_name）各建索引。

CREATE TABLE grounding_consents (
  id UUID PK,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  course_name TEXT NOT NULL,        -- 口径对齐 task.extra["course_name"] /
                                    -- estimate:course:<name> 的裸课程名
  enabled BOOLEAN NOT NULL DEFAULT false,
  consent_text_version TEXT NOT NULL,
  consented_at TIMESTAMPTZ NULL,    -- 最近一次开启确认
  revoked_at TIMESTAMPTZ NULL,
  UNIQUE (user_id, course_name)
);

ALTER TABLE file_objects ADD COLUMN course_name TEXT NULL;
```

- `memories.embedding`（#35）服务 L1/L2 记忆；`material_chunks.embedding`
  是文档侧数据类别（D-033 §1 表「随文件派生、同文件级联」）——两处
  vector 列对应两个数据类别，不合并。
- 证据锚点仍按 D-031 元组 `{type:"document", file_id, checksum_sha256,
  page, span_start, span_end}` 引用**文件+页**，不引用 chunk 行（chunk
  是派生物，重扫描会换行；文件+页+span 对用户可见且稳定）。

## 2. 摄取管线

```text
POST /files（显式上传，带 course_name 表单字段）
  └─ FileObject(status='uploaded') + best-effort enqueue extract_material
worker extract_material(file_id)：
  取对象字节 → 按 content_type 分发抽取器 → 每页文本 → 长页再切（≤2000 字符，
  段落边界）→ 逐 chunk 扫描 → blocked 丢弃（file_metadata 计数）→
  clean/flagged 入库 → 若 (user, course) 已 opt-in：对 clean chunks 批量嵌
  → FileObject.status='extracted'（不可抽取类型='unsupported_type'，失败=
  'extraction_failed'，可重试）
cron 兜底（30s）：扫 status='uploaded' 且 updated_at 老于 60s 的文件重试
  （enqueue 失败 / worker 崩溃不静默丢——显式动作路径必须可观察）
opt-in 开启（PUT consent）：enqueue embed_course_backfill(course_name)
  → 该课程所有未嵌 clean chunks 补嵌（幂等：只处理 embedding IS NULL）
```

- 抽取器：PDF（pypdf 文本层）、PPTX（python-pptx 每 slide）、txt/md
  （单块）。扫描后的 PDF 文本层连字/零宽产物由 flag+归一化路径吸收
  （D-033 §5：误报是本层主要风险，不可见字符不硬拒）。

## 3. 内容安全扫描（D-033 §5 第一层）

- 规则版本化于 `backend/core/scanner_rules.py`（模式表 + `SCANNER_VERSION`）；
  规则变更必须 bump 版本——存量 chunk 的 `scanner_version` 回答「这批
  chunk 是哪版规则扫的」。
- 分层：① 指令形态（中英文注入模板、凭据外泄模式）→ **hard block，不入库**，
  文件 `file_metadata.blocked_chunk_count` 计数；② 不可见 Unicode（零宽、
  RTL 覆盖）→ flag + 归一化（去零宽/NFC）后重扫——归一化后命中 ① 才 block。
- flagged chunk 入库但**不嵌不送**（检索批沿用此口径过滤）。
- 对抗 fixture（回归必有）：合成 PDF 含「忽略之前的指令…」+ 零宽包裹的
  注入变体，断言前者 block、后者 flag 后重扫 block；正常连字页 clean。

## 4. 供应商边界（D-033 §3/§7 实现约束）

- 适配层 `backend/adapters/model_provider/`：`base.py` 协议 +
  `openai_provider.py`（httpx）。模型调用必须经适配层（TECH_STACK）。
- **fail-closed**：无 API key / 网络失败 → 异常上抛，绝不静默降级为
  「已嵌入」；**未 opt-in 的课程绝不发起任何 provider 调用**（含
  embeddings）——worker 嵌入前置检查 consent，单测用 spy provider 锁死。
- **`store: false`**：适配层的 Responses 请求构造显式
  `store=False` 常量（本批落 request-builder + 断言测试；generate 完整
  实现随回答批，复用同一构造函数——约束先钉死，不留给未来调用点）。
  embeddings 端点无 store 参数（ZDR-eligible 是端点属性，无需请求级
  关闭），已在 D-033 §7 核对记录。
- 超时、重试上限（≤3）、批量（≤64 input/请求）；嵌入结果只落本地列。
- 关闭 opt-in：停止新增调用，**不删**已有 embedding（本地数据；删除是
  Level 2 独立动作）——PR 描述注明此语义。

## 5. 同意文案（版本化，v1）

- 后端常量 `CONSENT_TEXT_V1`（版本号入 `consent_text_version`）：
  披露「送出的 chunk 文本在供应商侧有 ≤30 天滥用监控保留，默认不用于
  训练」+ 只送命中 chunk、限当前课程、可随时关闭 / 删除数据。
- GET 返回全文 + 当前状态；PUT 开启必须回传**当前**服务端版本
  （旧文案上的同意 422 拒绝——文案更新后必须重新阅读确认）。

## 6. 验收标准

1. 迁移 up→down→up + `alembic check` 通过。
2. 集成：上传合成 PDF（带 course_name）→ worker 跑完 → chunks 落库
   （页号 / chunk_index / scanner_version）；txt / pptx 同径。
3. 对抗 fixture：注入 chunk 不入库且文件元数据计数；零宽变体 flag；
   正常页 clean。
4. fail-closed：未 opt-in → spy provider 零调用；opt-in 后 clean chunks
   被嵌（embedding 非 NULL + model 记录），flagged 不嵌；关闭后新文件
   不再调用。
5. consent：PUT 开启带过期版本 → 422；GET 文案含 ≤30 天披露句。
6. 删除文件：行（含 chunks CASCADE）事务内先删，对象 best-effort，
   失败进 orphan 集由 cron 重试（D-033 §5 删除顺序要求）。
7. 跨用户访问 chunks / consent → 404（用户隔离 P0）。
8. `FileRead.status` 透出摄取状态；chunks / consent 端点进 openapi 且
   客户端契约 drift 检查通过（客户端 Zod 零改动）。
9. ruff / 全量测试绿。

## 7. 删除顺序修正（D-033 §5 实现要求）

现状 `files.py` 先删对象后删行 → 改为：事务内先删关系行（chunks 随
CASCADE）+ 删 FileObject 行，commit 后对象 best-effort 删除；失败键进
Redis orphan 集，cron `drain_storage_orphans` 重试（删前确认行已不存在，
防删到并发重上传的同 key——key 含 uuid 实际不会重用，检查是防御性的）。

## 8. 接口冻结（B 侧并行依据）

- `POST /v1/files`：新增可选表单字段 `course_name`（不传 = 非课程文件，
  不进 grounding 管线）。`FileRead` 增 `course_name`；`status` 取值
  `active`(存量) / `uploaded` / `extracted` / `unsupported_type` /
  `extraction_failed` / `deleting`。
- `GET /v1/files/{file_id}/chunks`：offset 分页 `Page[MaterialChunkRead]`，
  字段 id/file_id/page/chunk_index/content/char_count/scan_status/
  scanner_version/scan_flags/embedding_present/created_at。
- `GET /v1/grounding-consent?course_name=` → `{course_name, enabled,
  consent_text, consent_text_version, consented_at}`（无记录时 enabled=
  false + 当前文案）。
- `PUT /v1/grounding-consent` `{course_name, enabled, consent_text_version}`
  → 开启回填嵌、关闭停新；响应同 GET。
