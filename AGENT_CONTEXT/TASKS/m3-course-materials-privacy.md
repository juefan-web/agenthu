# M3 先决文档 2：课程资料的隐私 / 合规决策（A/B 双签，已生效）

状态：**accepted**（A：rotcar07 2026-10-01；B：juefan-web 2026-10-01，
六条决策清单含内容安全扫描补强全部确认，无 modify。转录条目 = DECISIONS
**D-033**；修订走 DECISIONS 变更（同 D-027 口径）。课程资料是第三方版权内容，
按 AGENTS §3「每类数据接入前明确四问」与大纲 M3「先决文档」，本决策是
M3 grounding 的**硬前置**——未冻结前不写任何资料摄取代码。涉隐私决策须
A/B 共同 review（TECH_STACK §4）。

## 0. 决策清单（可逐条 accept/modify，签署即全部生效）

1. 元数据随采集自动入库（现状延伸），文件本体**默认不上传**，仅用户对
   单个文件的显式动作触发（经 Tauri 下载 → 流式上传对象存储）。
2. 一切资料数据（元数据行、blob、chunks、embedding、回答）**仅本人**可
   访问；用户隔离是硬要求，违反即 P0。
3. 保存期：alpha 无自动过期；用户可随时删除（Level 2 确认，因不可逆）；
   删除沿 `m3-memory-schema-migration.md` §6 的依赖图级联。
4. 文本内容送模型供应商：**默认关闭**；用户按课程（或按问题）显式开启后，
   只送命中 chunk 的文本（非整文件），且范围限定当前课程；每次回答落库
   记录送出的 chunk、模型与 prompt 版本；断供/未开启时回答降级标注
   「未落地」（不伪造 grounded）。
5. alpha 不保留资料本地持久副本（Tauri 临时文件上传即清理）；日志与
   fixtures 不含真实页文本（测试用合成文档）。
6. **内容安全扫描**（2026-10-01 Hermes 预研补强）：抽取的 chunk 文本是
   不可信输入（恶意构造的课件是 prompt injection 载体），入库前过分层
   扫描（详见 §5）；扫描规则版本化，`scanner_version` 记入 chunk 元数据；
   对抗 fixture（含注入指令的自造文档）进回归。

## 1. 数据类别与四问（AGENTS §3）

| 类别 | 是否上传 | 谁可访问 | 保存多久 | 如何删除 |
| --- | --- | --- | --- | --- |
| 文件元数据（`study.material.discovered` 等事件：文件名/课程/大小/时间，无内容；**`downloadUrl` 不进 Event**——会话态 URL 携带认证参数，撞 D-012 且是最小化采集违例，2026-10-01 补强） | 随采集自动（与 D-028 家族作业事件同管线） | 本人（Event API 鉴权） | 与账号同生命周期 | 事件级删除入口（M5）+ 账号删除级联 |
| 文件本体（PDF/PPT 字节） | **仅显式动作**，单文件，经 Tauri 中转 | 本人；FileObject 行级 user_id 鉴权 | 无自动过期；用户随时删 | blob + FileObject 行 + 下游 chunks/embedding 级联 |
| 抽取文本 `material_chunks`（按页/片） | 随文件派生（worker） | 本人 | 同文件 | 同文件级联 |
| embedding | 同上 | 本人 | 同文件 | 同文件级联 |
| 带引用的回答（内容+引用+模型/prompt 版本） | 生成即落库（可度量引用正确率） | 本人 | 与账号同生命周期 | 回答删除入口；引用不复活已删文件 |

## 2. 版权与合规边界

- 课程文件是**第三方版权材料**：本项目用途 = 用户个人学习（本人已合法
  访问的资料的个人化处理），**不分发、不跨用户共享、不对外展示**。用户
  隔离因此不仅是隐私要求，也是版权合规要求——任何把 A 用户资料暴露给
  B 用户（或匿名）的路径都是 P0 缺陷。
- 对外材料（截图、演示、README、验收报告）不得含真实课程资料内容；
  e2e 与单测 fixtures 一律合成文档（继续遵守现有脱敏纪律）。
- **OneTHU BSL 1.1 / LearnX 许可审查**是**代码分发**阻塞项（见
  CURRENT_STATE），与本数据决策互不替代、互不解锁；两者都在 M5 合规节
  收口。
- 校园信息系统使用条款：不绕过访问控制（沿用登录态采集）、采集频率
  最小化（元数据随现有采集节奏，不因资料功能加密采集）。

## 3. 模型供应商边界（决策清单第 4 条展开）

- 只送**命中 chunk 的文本**；文件名/课程名作为上下文可送；整文件字节、
  其他课程内容、与问题无关的 chunk 不送。
- Provider 政策需可追溯：默认 OpenAI Responses API（API 输入不用于训练，
  记录政策链接与核对日期于本文件修订）；更换供应商必须重核并修订本条。
- 「未落地不伪造」：引用校验失败（机械步骤）→ 删除该引用并标注回答
  未落地（大纲 M3 已冻结，此处作为隐私侧的同义约束：宁可无回答，不可
  假装 grounded）。
- M4 Agent 复用同一边界：上下文装配遇到文档内容时按本条范围裁剪。

## 4. 数据流与本地/云边界

```text
learn.tsinghua.edu.cn ──(OneTHU@Tauri transport)──> 元数据 Event ──> Backend
用户点击「讲解此文件」─> Tauri 下载到临时目录 ──流式──> Backend /files
  └─ 上传完成即删本地临时文件（不留持久副本，决策清单第 5 条）
Backend worker：按页抽取文本 → material_chunks →（开启检索时）embedding
回答生成：课程范围内混合检索 → 只送命中 chunk → 引用机械校验 → 落库
```

- React 页面不直接下载/上传文件（经 Tauri 命令，与 campus 采集同边界）；
  React 不接触文件字节。
- `storage_key` 建议**强制 user 前缀**（`{user_id}/...`）——对象层再多一层
  隔离（当前仅行级鉴权 + 全局唯一 key）；实现于 M3 摄取任务，非本决策
  阻塞项但同批落地。

## 5. 内容安全扫描（chunk 是不可信输入，2026-10-01 Hermes 预研补强）

三层防线：

1. **入库扫描**：chunk 写入 `material_chunks` 前过注入模式扫描——指令形态
   （"ignore previous instructions" 类、凭据外泄模式）hard block；不可见
   Unicode（零宽字符、RTL 覆盖）**只 flag + 归一化后重扫**——PDF 文本层
   抽取的连字/零宽产物在正常课件中常见，一刀切硬拒会把合法资料全挡掉
   （误报是本层主要风险）。扫描规则作为数据文件维护并版本化，
   `scanner_version` 记入 chunk 元数据（否则无法回答"这批 chunk 是哪版
   规则扫的"）。
2. **上下文装配隔离**（M4）：检索片段送入 prompt 时用明确分隔符包裹并
   标注不可信；机械引用校验（引文必须能在被引 chunk 归一化后找到）作为
   第三道防线。
3. **对抗 fixture 必须有**：一篇内容含注入指令的自造文档进 e2e/回归，
   断言被 flag——没有对抗样本的扫描等于没写。

**文件删除顺序**（实现要求）：现状 `files.py` 先删对象后删行；加 chunk 后
必须改为**事务内先删关系行 + 状态标记，对象 best-effort 删除 + 孤儿清理**——
否则失败中间态留下"对象已删但 chunk 仍可检索"，直接破坏 §1 表的删除承诺。

## 6. 明确排除 / 后置

- **课堂录音与转写**：单独数据类别（生物特征/他人声音风险更高），
  **另行决策**，本文件不覆盖、不隐含授权（大纲 M3 也已后置）。
- 多课程混问（跨课程上下文）、Android 端资料访问（M6）：M3 末 / M6 再议。

## 7. 签署与修订

- A：**rotcar07（2026-10-01，`feature/a-signoffs-d032-m3docs`）**
  B：**juefan-web（2026-10-01，同分支随 PR #19 会签）**——双签完成，本文件
  转 accepted，转录为 DECISIONS D-033；修订走 DECISIONS 变更（同 D-027 口径）。
- Provider 政策核对记录（**首核完成 2026-10-02，A 执行**；首次核对
  日期 + 链接；M3 摄取开工前完成首核，未核前决策清单第 4 条保持默认
  关闭）。核对对象 = 第一实现供应商 **OpenAI**（TECH_STACK「Provider
  adapter + OpenAI Responses API」；embedding = text-embedding-3-small，
  D-031 维度 1536）。核对当日有效版本：
  ① `https://openai.com/enterprise-privacy/`（页首 Updated January 8,
  2026）——「By default, we do not use your business data for training
  our models」；API Platform（2023-03-01 起）输入输出默认不用于训练，
  需显式 opt-in 才参与改进；「you retain all rights to the inputs you
  provide … you own any output」。
  ② `https://platform.openai.com/docs/guides/your-data`（Data controls）
  ——`/v1/responses` 与 `/v1/embeddings` 端点级表格均为 not used for
  training；embedding 端点 eligible for zero data retention。
  **残留事实（须向用户如实披露）**：API 输入/输出在供应商侧有**至多
  30 天**的滥用监控日志保留（含客户内容；ZDR 需资格审批，alpha 个人
  账号不适用）；Responses API 默认 `store: true` 亦产生至多 30 天的
  application state。**实现约束（随摄取批次落地）**：适配层对
  Responses 调用显式 `store: false`；按课程开启的同意文案披露「送出
  的 chunk 文本在供应商侧有 ≤30 天滥用监控保留，默认不用于训练」。
  **结论：与决策清单第 4 条兼容**——第 4 条「默认关闭」继续成立，
  资料摄取批次可开工。复核节奏：供应商政策页变更或每里程碑一次
  （下一复核 = M3 摄取合入前，B 会签本记录即完成双核）。
