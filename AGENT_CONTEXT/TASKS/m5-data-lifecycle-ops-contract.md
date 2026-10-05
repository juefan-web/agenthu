# M5 A 草稿：数据生命周期、导出删除与运行契约

Status: **r2，A 署名修订（2026-10-05）**。r1 是外部 codex 输入材料（协调人
裁定一），不构成共识基线；r2 起 A 认领作者身份——改错、删不认同项、补己见，
修订账见 §9（供 B 互审逐条对照）。基线 bf02eeb；边界/负责人见
[phase-0](m5-phase0-prereq-docs.md)。以下字段、期限与阈值均为拟冻结内容，
不声称现已实现；文中引用的现行码位均在 bf02eeb 对码核验，
核验记录见 [A 对 B-r2 互审报告](../HANDOFF/2026-10-05-a-review-m5-b-r2.md)。

## 1. 导出、删除与验证使用同一图

Backend 定义确定性 resource registry：owner resolver、字段分类、
依赖边、export serializer、delete handler、verify query、存储/Redis清理。
不引入通用工作流平台。owner来自认证；目标ID逐个验证，
没有user_id的子表沿父表解析；UUID不可猜不能代替权限。

| 数据族 | 必须枚举的边与副本 | 处置 |
| --- | --- | --- |
| User | Event、Task、Goal、FocusSession、Plan/PlanItem、CurrentState、Memory、FileObject/MaterialChunk/MaterialAnswer、GroundingConsent/ModelContextConsent、PermissionGrant、NotificationPreferences、ChatSession/ChatMessage、AgentRun/PendingAction/PendingActionMutation、AuditLog | 全账号涵盖全部用户数据，不仅靠ON DELETE CASCADE |
| Event/Task/Focus | task_events、Task.extra/上游标识、Focus结果Event、L1 evidence/source_event_ids、L2 evidence/subject_key、估时样本 | 源删除区分纯派生与独立用户编辑；派生内容清除，独立内容去相关来源后保留，preview告知 |
| Memory | old → replacement 的supersedes_id、三型evidence、embedding、source/subject_key、依赖它的L2/估时/计划/回答/run/action | 忘记记忆默认包含历史全链；源删除先失效再按剩余证据重算，不能继续使用旧内容 |
| FileObject | chunk.text/embedding、blob、回答citations.quote/answer、document evidence、run chunk refs、缓存/临时包 | chunk/embedding/blob清除；含目标资料派生内容的复合回答r1建议整条清除，preview列影响 |
| Chat | session.title可能复制首条消息、content/trgm、history refs、basis/display/summary/result、mutation.response | archive/soft-delete仅代表不可见；永久删除另清复制内容，留下无内容source_deleted标记 |
| Plan/CurrentState/Agent | basis、PlanItem.basis/result、context_snapshot/trigger_ref/tool_calls.result_ref、pending args/display/result、已缓存确认响应 | 重算CurrentState；未执行动作失效禁止重派；摘要/参数/缓存也属于用户内容 |
| 外围/审计 | AuditLog.details/path/resource_id/IP/UA、trace、Redis sets/Arq结果、导出包、客户端队列/草稿/损坏备份/Stronghold | 最小无内容回执按期限保留；不导出credential/JWT/password hash/cookie/signed URL |

A 实现前把本表与全部ORM tables/JSON字段/Redis key/本地储存对照，
补成机器可执行矩阵；“存在但未登记”检查失败。
历史JSON缺血缘时不能宣称精确级联：属于目标用户且可能含来源内容的派生
结果保守清除并列preview；若涉及无法区分的原创内容，则阻塞子集操作、
提供全账号删除，不静默跳过。

统一 live 谓词并落到**全部** live 行读者：
`supersedes_id IS NULL` 且 `valid_to IS NULL 或 valid_to>now` 且
`valid_from IS NULL 或 valid_from<=now`，叠加既有 non-rejected 过滤与
各自 confidence/sample 门槛。bf02eeb 现状以 `supersedes_id IS NULL` 定义
live 的码位共四处：memory_retrieval.py:71（检索）、estimates.py:70
（估时 live_key_row）、**event_handlers.py:279（L1 episode 证据血缘，
r1 漏记）**、api/v1/memory.py:47（_live_key_owner 冲突检查）；四处都必须
换谓词。partial unique index（subject_key WHERE supersedes_id IS NULL）
保留为**写序守卫**，不承担读时 live 定义——索引谓词不能含 now()。
另两点：①MemoryUpdate（schemas/memory.py:78-79）今天允许客户端直写
valid_from/valid_to，即“行被标失效而读者照读”是**现时可触发**的缺口，
不是潜伏风险；r2 提案把两字段移出客户端可写面（§8-6）。②删除替代行触发
FK SET NULL（models/memory.py:114）会让旧行带着已过期的 valid_to 回到
`supersedes_id IS NULL` 位——统一谓词在读路径恰好挡住它，但 _live_key_owner
与写侧判定必须同谓词，否则复活行占住 subject_key 使新建撞 conflict。
整链删除先枚举闭包并同事务处理，不能依赖SET NULL。
L2样本不足时全链清理或保留不可检索无内容占位，需§8裁定。
独立用户修正可保留，但去掉被删来源片段/证据/嵌入并重算有效性；
CONFIRMED不代表免除删除。

## 2. 删除作用、权限与并发

作用：清指定范围及其内容副本。输入：目标/preview摘要/确认/幂等ID。
输出：异步Operation/Receipt。权限：**Level 2**；
不授予Agent自主账号/源删除的Level 3 grant。

1. preview枚举闭包与清除/保留/重算数，列backup/provider/local限制。
   10分钟有效，绑定user、target、graph_version、data_generation、
   影响集及内容版本摘要，不能只hash行数。审计不存正文。
2. confirm事务内复核；目标/版本变化返回409 preview_stale，
   不静默扩大范围。同事务锁owner屏障、登记durable operation/cleanup items、
   提高data_generation；账号删除立即is_active=false，撤grant/consent。
   source/memory屏障覆盖目标与受影响派生，不永久停用整个账号；
   清理完成后放行无关工作，目标抑制仍保留。FAILED不能解除目标屏障。
3. 新写入、context、dispatch、extract/embed/backfill、Focus/投影在入口
   与最终写入/外发前检查屏障/代际；仅enqueue检查不足。外部调用返回
   后再复查，旧结果不得写回。
4. QUEUED/RUNNING/**WAITING_CONFIRMATION** run使用已有CANCELLED
   （枚举见 models/agent.py:41）；PENDING/CONFIRMED/
   FAILED_RETRYABLE action用已有FAILED，code=account_deleted/source_deleted。
   不把CONFIRMED伪称时间过期。EXECUTING待执行边界/租约核验；
   已发外部请求不能声称撤回，结果不明记录outstanding side effect，
   不自动重发。
5. 屏障下先使关系/检索不可用，再批量清内容/对象，最后验证。
   清理账本与关系删除同事务，Redis仅唤醒，spop后崩溃不能丢对象。
   对象版本/副本/导出一起清，权限不足不算完成。
6. source删除保留owner-scoped上游抑制标识（尽量HMAC，不含标题正文）
   和代际；换client_event_id不能重新导入。同来源仅在用户明确重新授权
   后解除。账号恢复抑制凭据独立于旧备份，见§5。

复用M4租约模式，增加durable phase/checkpoint/attempt。
单步timeout提案30s，最多5次自动重试，退避5/30/120/300/900s
（每次重试各配一档），自动重试总窗口提案24h；RETRY_WAIT含next_retry_at
与恢复phase；耗尽为FAILED，列剩余项与safe error。
人工重试仍是原operation，不能解除屏障；**手动重试仅适用于owner仍可
业务认证的范围（source/memory）**——账号删除后owner无法业务认证，
其FAILED清理只走自动重试与运维处置，receipt能力保持只读（§4）。
存储超时/403不等于不存在；现exists()把ClientError/BotoCoreError全归
False（storage.py:134-139），不可当擦除证据。验证必须区分确证404、
403与网络故障。

## 3. 导出一致性与包

作用：本人可携带副本。输入：client_request_id、include_files（默认true）。
输出：异步包与manifest。本人主动读取为Level 0；
临时复制需审计。Agent仅提示入口，不能代用户下载外传。

按同图输出用户正文、历史Memory/有效性/修正状态、来源关系、
计划/Focus实际结果、Chat、同意/授权历史、允许的审计副本。
排除auth/storage/provider secrets与内部租约；embedding默认不输出，
manifest记录排除和重建版本。永久删除内容不能再导出。
仅隐藏而尚未硬清理的Chat按政策注明hidden，不误称已彻底删除。

DB一致性快照；大包采用不可变staging+快照版本，不能跨事务混装。
blob校验checksum；若并发删除，作废导出，不漏文件仍报READY。
ZIP含分族JSONL、manifest.json、用户可读README，路径为archive-relative。
manifest字段：schema_version、graph_version、snapshot_at、generation、
family_counts、entries（path/sha256/size_bytes）、关系/重建说明、
excluded_categories。include_files=false明确列遗漏。
导出是携带功能，M5不增加用户导入恢复入口。

临时包24h到期，owner鉴权下载；若用signed URL，最多5min；
账号删除立即作废下载能力和全部包。URL不进日志/manifest。
用户已下载副本无法由Backend远程擦除，UI明确说明。

## 4. 拟冻结HTTP与字段矩阵

统一前缀/v1/data。请求不接收可信user_id；UTC RFC3339/UUID/非负counts，
strict enum、拒绝未知字段。下表 ? 表示**字段必有但允许null**，
可省略另写，不能与optional混淆。

| 路由（相对此前缀） | 输入 | 输出/权限 |
| --- | --- | --- |
| GET /capabilities | 无 | DataCapabilities，Level 0 |
| POST /previews | DeleteTarget | DataPreview，Level 0，不执行 |
| POST /deletions | preview_id, preview_digest, client_request_id, confirmed=true | 202 DataOperation，Level 2，独立用户确认 |
| POST /exports | client_request_id, include_files（可省略，默认true） | 202 DataOperation，本人读取 |
| GET /operations/{id} | owner auth | DataOperation，Level 0 |
| GET /operations/{id}/download | owner auth，仅export READY | 包流，Cache-Control:no-store |
| POST /operations/{id}/retry | expected_version | DataOperation，本人明确重试，不改范围；版本冲突即天然幂等（409 version_conflict），不引入第二个幂等键 |
| GET /receipts/{id} | 专用receipt capability，Authorization头，不在URL | DataReceipt，仅读该回执，可用于账号停用后 |

DeleteTarget判别联合：account {kind}；
source {kind, source_kind:event|file|chat_session|chat_message, ids:UUID[1..100]}；
memory {kind, ids:UUID[1..100], include_history:true}。
所有权错误404，不支持scope422，不接自由JSON删除条件。

| DTO | 字段（提案） |
| --- | --- |
| DataCapabilities | schema_version:string, graph_version:string, export_enabled:bool, deletion_enabled:bool, supported_source_kinds:string[], minimum_client_version:string |
| DataPreview | id:UUID, target:DeleteTarget, graph_version:string, data_generation:int, preview_digest:string, expires_at:datetime, effects:DataEffect[], limitations:string[] |
| DataEffect | resource_type:string, delete_count:int, redact_count:int, recompute_count:int, retain_count:int, reason_code:string；不含标题正文 |
| DataOperation | id:UUID, kind:export或deletion, target:DeleteTarget?, status:QUEUED/RUNNING/RETRY_WAIT/READY/COMPLETED/EXPIRED/FAILED, phase:OperationPhase?, version:int, data_generation:int, created_at/updated_at:datetime, next_retry_at:datetime?, expires_at:datetime?, progress:OperationProgress, error:SafeError?, receipt_id:UUID?, receipt_capability:string? |
| OperationProgress | processed:int, total:int?, outstanding_count:int；不展示未经计算百分比 |
| SafeError | code:string, message:string, retryable:bool；无原文/对象key/凭据 |
| DataReceipt | id:UUID, operation_id:UUID, completed_at:datetime?, completion_scope:controlled_live, effects:DataEffect[], outstanding_count:int, backup_expires_at:datetime?, provider_limitations:string[], local_cleanup_required:bool, audit_receipt_version:string |

OperationPhase枚举：export_collect/export_package/export_verify、
delete_fence/delete_relational/delete_objects/delete_verify。
export：QUEUED→RUNNING→READY→EXPIRED，包验证才可READY。
deletion：QUEUED→RUNNING（四phase）→COMPLETED；
步骤可到RETRY_WAIT/FAILED。READY不能用于删除，EXPIRED不能撤销删除。
deletion的expires_at为null；next_retry_at仅RETRY_WAIT非null；
error仅失败/等待重试非null；target仅export为null。

幂等唯一(user,kind,client_request_id)；同输入返回同operation，
不同输入409 idempotency_conflict。删除重传先查幂等，再验preview到期。
owner、幂等记录与data_generation都必须保存在独立最小操作账本
（以opaque owner handle键控），不能因删除users行CASCADE丢掉；
业务查询不得拿它恢复用户身份。缓存脱敏operation，
不能沿用含被删正文的mutation.response。202代表已持久接受，
不代表清除完成。

账号删除创建时发随机高熵receipt capability（≥128-bit随机），
持久账本仅存摘要。为丢失首次202保留独立加密短期交付缓存（提案10分钟）；
特殊恢复接口 POST /deletions/recover 仅凭原JWT身份、原client_request_id
和同请求摘要返回原operation与能力，停用身份仅可走此路径，
不重新开放业务JWT。过期后不能新发能力；UI说明回执可能无法找回，
清理继续。该路径与 GET /receipts/{id} 的防枚举硬化（r2 补）：
不区分“无此请求/已过期/身份不符”（统一404）、按原身份与按IP双限流
（429带Retry-After）、digest作为高熵第二因子参与匹配、
响应时延不构成存在性oracle、能力值不进日志。密钥与业务库隔离。
能力90天到期，仅读脱敏回执，不能导出/恢复/列数据；B安全保存，
GET operation不能重复吐secret，receipt_capability在普通读取为null。

沿用error envelope/request-id：401 auth_required、404 not_found、
409 preview_stale/version_conflict/idempotency_conflict/deletion_in_progress、
410 export_expired、422 unsupported_scope/invalid_confirmation、
429 rate_limited（Retry-After）、503 dependency_unavailable。
关闭账号业务入口401；无效receipt能力404；持久接受失败不能202。

## 5. 每类数据四问与保留期（待裁定）

| 数据 | 上传/谁访问 | 保存多久 | 如何删除 |
| --- | --- | --- | --- |
| Event/Task/Goal/Focus/Plan/CurrentState/Memory/Chat/资料/回答 | 最小化事件或用户明确上传；本人经Backend、服务最小权限 | 活跃账号按D-033无自动过期，直到用户删除；明确隐藏Chat提案7天硬清 | 同图处理正文/副本/摘要/向量 |
| consent/grant/通知偏好/agent内容结果 | Backend；本人及执行服务 | 跟随账号，撤销历史到账号删除 | 撤销≠删除；账号删除清内容/标识 |
| 生命周期操作、无内容审计回执 | owner/receipt能力、受控运维 | 完成后90天；未完成不能过期丢清理项 | 到期清；账号删除先脱敏IP/UA/标题/源URL/业务路径/JSON正文 |
| 日志/trace/错误报告 | allowlist；受控运维 | 提案14天，无原文 | 定期到期，用户删除清可关联PII；SET NULL不等于匿名 |
| export staging/ZIP | 受控对象存储；本人 | 24h，失败包同样TTL | 到期或账号删除清对象所有版本 |
| 加密DB/对象备份 | 不公开；最小访问恢复操作者 | 滚动最多30天 | 到期销毁；恢复放流量前重放删除抑制 |
| 删除抑制记录 | opaque ID/HMAC，无内容；仍按个人数据管理 | source到重新授权/账号删除；账号记录覆盖最后含其备份失效+7天 | 独立加密，不随旧备份回滚；到期清 |
| 校园密码/验证码/cookie、JWT、本地草稿/队列/临时文件 | 凭据本地处理；必要内存/Stronghold，不能云导出 | 密码/验证码随流程清；本地按B稿隔离/清理 | 本机清损坏备份、SQLite WAL、临时文件和内存 |
| 供应商已收内容 | D-033与model_context_consent分别控制，现store=False | 发布前重核实际供应商政策；store=False不等于零保留 | 停后续发送、可行时请求供应商删除；不可直接擦除的期限回执说明 |

GPS/录音/消费/通知原文等新类别不借M5扩大接入。
加密/散列标识可能关联用户，不能自行标匿名。
新永久删除尽快清理，7天隐藏保留不得作为新操作延迟清除的借口。

## 6. 运维契约

- OTel链：HTTP→operation/run→worker attempt→provider/storage；
  campus在Tauri本地，仅上传用户同意的脱敏技术遥测。标准traceparent/links，
  trace不是事实层。allowlist：route template、服务版本、阶段、错误码、
  retry/timeout、duration/usage计数、随机关联ID。禁止正文/prompt/response、
  SQL参数/query string/email/IP/GPS、认证URL/signed URL/headers/keys。
  SDK自动异常/正文采集也关闭或过滤；原始UUID不做metric label。
- 外部调用有限timeout/retry/idempotence。校园认证不重复验证码/2FA提交。
  trace断供不阻塞普通请求；删除确认/状态/清理审计必须同事务持久，
  不依赖best-effort middleware。
- Redis共享限流：受信代理规则识别登录来源，owner模型/导出额度、并发任务
  分桶原子结算。生产Redis失效时新认证/昂贵任务503；
  durable删除继续DB扫尾、普通owner读取可用，不静默退每进程无限额度。
  至少2API进程+2worker验证唯一claim/租约执行。现rate_limit.py为进程内
  defaultdict/deque（core/rate_limit.py:14-23，docstring自认单worker假设），
  `hit`/`retry_after` 即替换缝。
- 备份恢复：提案每日加密DB+对象清单，Alpha RPO<=24h/RTO<=4h，
  是拟目标不是实测。删除抑制账本独立保存；恢复时抑制与data_generation
  从独立账本重放（§4），不依赖users行、不从旧Redis dump恢复任务；
  隔离恢复→重放抑制/清理→checksum/schema校验→放流量。
  演练从bf02eeb升级；降级不能恢复已删内容。
- dev/test/alpha secrets隔离，保留现强密钥校验。
  有权限操作者新key验证→切配置→撤旧key→旧拒绝/新最低额度验证；
  证据仅key标识与结果。备份/E6敏感证据本地受控，不提交公共仓库。

## 7. 兼容与回滚提案

新API先禁用上线，A/B升级后开启。旧DELETE逐个冻结迁移方式：
204仅能表示其原有语义，不能让旧UI误称全擦除；
建议新永久删除统一202 operation，旧入口设废弃窗口后明确升级错误，
不可悄悄改响应破坏Zod。兼容窗口截止由协调人裁定。
同步代际用独立元数据（例如X-Data-Generation），不改可信身份规则。
旧无主/无代际队列禁止自动补当前值重放；账号停用永远不能兼容写入。
同owner的无关待同步工作可在用户明确确认后重基，Backend逐项校验来源
抑制/删除目标/当前代际，禁止将被删项混入新批次；具体sync错误和恢复
DTO随phase-0冻结，不得仅在客户端改代际头绕过。

关新入口不停止已接受清理；回滚版本仍须识别屏障/抑制，
不支持的旧版禁止重部署。先增表字段→迁移消费者→启用；
承诺变化同步OpenAPI/Pydantic/Zod/fixture/UI/手册。

## 8. 必须显式裁定

1. D-032删除图的有效期过滤（统一live谓词与四处读者改造）、整链忘记、
   L2不足样本与独立修正保留。
2. 90d/14d/24h/30d、隐藏Chat7d、备份抑制、receipt恢复协议与
   RPO<=24h/RTO<=4h目标。
3. API字段/状态、确认摘要、旧DELETE窗口/同步代际兼容。
4. grant新建/扩scope确认与并发版本，notify实际channel、
   local_time_window执行或禁止；现matcher只比category
   （agent_tools.py:173-174），strict_scope_validator对channels仅要求
   存在（:706-711），不值级比较。不支持渠道不能存有效grant，
   旧grant如何迁移/撤销一起裁定。
5. E7受控在线擦除与离线/备份/供应商限制分开报告，
   不承诺所有磁盘历史扇区即时物理擦除。
6. valid_from/valid_to移出MemoryUpdate的兼容窗口与迁移
   （现schemas/memory.py:78-79可直写）；SET NULL复活行的写侧判定
   与partial unique index写序守卫的定位。

当前无A/B签认或协调人采纳记录；验收见 [E7](m5-e7-acceptance.md)。

## 9. r2 修订账（供 B 互审逐条对照）

**改错（4）**：
1. §1 r1 只列检索/估时两条读路径；对码 bf02eeb 实为**四处**
   `supersedes_id IS NULL` 读者（加 event_handlers.py:279 的 L1 证据
   血缘与 api/v1/memory.py:47 的 _live_key_owner）。且 MemoryUpdate
   今可直写 valid_from/valid_to——缺口现时可触发，非潜伏。
2. §2.4 run 终态漏 WAITING_CONFIRMATION（枚举已有该值，
   models/agent.py:41）。
3. §2 重试退避 5/30/120/300s 四值配“最多5次尝试”对不齐；
   补 900s 档并加自动重试总窗口 24h。
4. §4 retry 输入的 client_request_id 冗余——expected_version 的
   409 version_conflict 已是幂等；字段级 delta 供 B 重镜像 §1。

**删除/不认同（1）**：
1. r1 手动重试未限定范围。收紧：manual retry 仅适用 source/memory
   （owner 仍可业务认证）；账号删除后 FAILED 只走自动重试与运维处置，
   receipt 能力保持只读——与 §4 “仅读脱敏回执”自洽。

**补己见（6）**：
1. 统一 live 谓词（读四处+写侧同源）+ partial unique index 定位为
   写序守卫 + SET NULL 复活行带 stale valid_to 的读写两侧对齐（§1）。
2. valid_from/valid_to 移出 MemoryUpdate，冻结为生命周期内部字段（§8-6）。
3. recover/receipts 防枚举硬化五条：高熵能力、统一404、双限流、
   digest 第二因子、无时延oracle（§4）。
4. 幂等记录与 data_generation 落独立操作账本，restore 重放不依赖
   users 行（§4/§6）。
5. 孤儿集现行凭据码位入档：files.py:194-211（行先提交、对象best-effort、
   mark_storage_orphan返回值被忽略）、enqueue.py:58-89（SADD/SPOP破坏性
   弹出，pop后崩溃丢key）、worker/tasks.py:251-275（drain cron）——
   §2.5 durable账本方案即覆盖此三处。
6. storage exists() 把 ClientError/BotoCoreError 全归 False
   （storage.py:134-139）——§2.5 “验证三分”的现行依据。
