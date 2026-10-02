# M3 任务：课程资料检索与带引用的回答（A 负责）

Status: open（2026-10-02 立项，协调人）。前置已合 main（`061c145`）：
#41 摄取切片（chunks/scanner/consent/接口 §8）、#35 embedding 列、
#37 memory 共享检索路径。依据：路线大纲 M3（D-030）、
`TASKS/m3-course-materials-privacy.md` §1/§3（已双签生效）、
`TASKS/m3-materials-ingestion.md` §8（接口冻结）。

## 1. 目标

对一门已开启 grounding 同意的课程资料提问，得到**每条引用都通过机械
校验**的回答；回答体现已确认的 Learning Memory，删除该 Memory 后不再
体现（M3 出口场景的后端半边；客户端半边归 B，见 CURRENT_STATE 队列）。

## 2. 输入

- `material_chunks`（embedding 列、scan_status/scanner_version）与
  consent 端点（契约见 ingestion §8）。
- OpenAI provider adapter（#41：Responses API、`store=False` 硬编码、
  超时/重试上限已具备）。
- `services/memory_retrieval.py`（#37：live + 非 REJECTED + 0.3 下限的
  共享检索路径）。
- 联调环境 = A 的 compose 栈（pgvector 镜像 `pg16`；B 本地无 vector
  二进制，E4/联调以 A 栈为准——裁定见 CURRENT_STATE 2026-10-02 条目）。

## 3. 负责范围

1. **混合检索**：课程范围内关键词 + pgvector 相似度，融合去重；只送
   命中 chunk 文本（文件名/课程名可作上下文，§3 边界）；被扫描
   hard block 的 chunk 不得进入检索（以 #41 实际入库语义为准，在实现
   说明里写明扫描状态与检索资格的对应关系）。
2. **同意门**：回答生成路径**调用时重查** consent——与 embedding 路径
   同一 fail-closed 语义（复用 `consent_enabled`，勿复制第二份判断）；
   未同意课程不触 provider（含嵌入与生成两类调用）。
3. **引用元组**：`(file_id, checksum, page, span)`——checksum 把引用
   钉在被读取的具体版本上；文件重传（新 checksum）后旧引用可检测失效。
4. **机械引用校验**：生成后每段引文必须在被引 chunk 的**归一化文本**
   中找到（与 content_scanner 共用同一归一化函数）；失败 → 删该引用；
   无任何存活引用 → 回答标注「未落地」（grounded=false）。宁可无回答，
   不可假装 grounded（§3 冻结）。
5. **回答落库**：内容 + 引用元组列表 + 命中 chunk id + 所用 memory id +
   模型/prompt 版本——「引用正确率」可从数据度量（§1 表「带引用的回答」
   行的保存/删除承诺同步兑现：回答删除入口，引用不复活已删文件）。
6. **Learning Memory 接入**：回答上下文经 `retrieve_memories` 携带已确认
   L1/L2；记录所用 memory id；删除该 Memory 后同一问题再问不再体现。
7. **HNSW 暂缓**：先走无索引精确路径，记录查询延迟与行数，规模实测后
   单独决策是否建索引（不与本切片捆绑，避免过早优化）。

## 4. 不负责范围

- 客户端讲解页 UI / 引用跳转（B，待 §6 接口冻结后并行）。
- 多课程混问、录音/转写（隐私决策 §6 明确后置）。
- prompt 深度调优（先固定一版 prompt_version 进落库，调优是后续迭代；
  本切片的验收是机械正确性不是回答质量）。

## 5. 易错点（预埋）

- embedding 断言必须 `pytest.approx`（pgvector 文本输出是最短 float32
  往返表示，float64 精确值出库带 ~1e-7 误差——#35 实测，已记
  CURRENT_STATE）。
- 归一化函数与 scanner 必须是同一份实现——否则「扫描过的」与「校验的」
  是两个文本宇宙，对抗 fixture 会在两套归一化间漏过。
- provider 失败路径 = 明确错误（超时/限流透出），绝不降级成「无引用的
  平滑回答」；重试有上限（AGENTS §7.2）。
- 对抗 fixture：诱导模型产出「引用不存在页码/不存在引文」的样本进回归，
  断言被机械校验拦截——没有对抗样本的校验等于没写（与 scanner 同纪律）。
- 回答与 chunk 的读取应在同一事务快照内取 checksum（防止校验期间文件
  被删/重传导致引用锚点漂移）。

## 6. 接口冻结（B 侧并行依据；实现前先冻结本节再动工）

- `POST /v1/material/answers`：`{course_name, question}` →
  `{answer, grounded, citations: [{file_id, checksum, page, span, quote}],
  memory_ids, model_version, prompt_version}`。
- `GET /v1/material/answers?course_name=`：历史列表（offset 分页，
  Page 契约；量级=回答数，无需 keyset）。
- OpenAPI + 客户端 Zod（如进客户端契约）+ drift 双源绿为准；形状调整
  在冻结时一次定稿。

## 7. 验收标准

1. 合成课程文档（fixtures 一律合成，脱敏纪律）+ 已确认 Learning
   Memory：提问 → 回答带引用，每条引用机械校验通过且可定位到 chunk
   的 page/span。
2. 伪造引用样本被拦截（引用被删或 grounded=false）。
3. 删除所用 Memory → 同一问题再问，回答不再体现该 Memory。
4. 未同意课程 → fail-closed 4xx，provider mock 断言零调用。
5. 回答落库可查（模型/prompt 版本在场）；「引用正确率」可从落库数据
   直接算出。
6. ruff / pyright / 全量测试 / drift 双源绿；联调在 A 的 compose 栈
   跑通一次完整问答（真实 provider 或录制回放二选一，报告注明）。
