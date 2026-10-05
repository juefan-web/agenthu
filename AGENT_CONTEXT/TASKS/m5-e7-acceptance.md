# M5 E7 验收草案：导出、删除与恢复双证

Status: **r1 方案，2026-10-05；未执行。双草已冻结（D-036），
E7-7已按P0-2切片1（main `d7d8717`）实现基础预登记，其余用例
随对应切片落地时同步对齐**。
依据D-030 M5出口；[总指导](m5-planning-guidance.md)、
[A稿](m5-data-lifecycle-ops-contract.md)、[B稿](m5-data-controls-grants-client-contract.md)。
目标是证明系统能长期尊重用户控制权，删除后不再“记住并行动”。

## 1. 输入/输出与环境

输入：冻结契约、migrations、OpenAPI/Zod、Windows新构建、
registry/verify SQL、脱敏seed manifest、provider replay、对象存储。
输出：两轮结果、逐用例截图/HTTP/SQL/对象列表、trace脱敏报告、
restore/key/license证据、B独立核账、执行SHA/树状态/包checksum。
范围：真实栈与故障演练；不使用真实个人内容作fixtures，
不删除M4 E6证据库、不在共享栈乱杀进程。

独立E7数据库/bucket/Redis前缀；每用例重建seed，user U和对照V，
同名内容不同owner；固定UTC锚点/本地时区Asia/Shanghai。
seed含：Event/派生Task/Focus、L1、L2修正历史链、用户原创Memory、
Plan/PlanItem、CurrentState、两个资料及chunks/embedding/回答quotes、
两个Chat会话、软删消息、AgentRun/PendingAction/Mutation、grant/consent、
审计PII、对象版本、export、Redis及本地正常/损坏队列。
用synthetic unique marker查内容泄漏，不用真实secret。

自动schema inventory与seed预登记全部族的before counts、依赖/历史链、
expected delete/redact/recompute/retain counts及原因；B先核manifest。
不得在跑完后改预期凑绿，也不沿用E6的96条审计/7任务数字。

## 2. 用例与硬断言

| 编号 | 场景 | 必须通过 |
| --- | --- | --- |
| E7-1 | U完整导出，V尝试列/下载/receipt；并发source删除；包TTL | U manifest计数、checksum/快照与seed一致；无V或凭据；include_files=false有明确遗漏；并发删除使旧包作废；过期/已删签名能力不能读 |
| E7-2 | 预览变化、过期、重复确认、202丢响应、失败重试 | stale→409，无扩大删除；同ID同operation，不同输入409；durable账本不丢；账号停用后只有窄receipt恢复路径可用，不能借旧JWT业务访问 |
| E7-3 | 分别删Event、file、Chat message/session | 每种source的图闭包与preview匹配；派生Task/Memory/quotes/标题/摘要/缓存清；独立用户内容按冻结规则保留；失效basis不再有原文。**派生Task=锚定判据**（task.(source,source_upstream_id) 匹配被删 event 锚→整删含 focus_sessions 级联计数；仅 task_events 边关联→去相关存活，边清 task 留）；preview reason_code 区分 anchored_derivation/decorrelated；audit 脱敏按真实行 id 定位（P0-3 切片 2 裁定①②，2026-10-06） |
| E7-4 | Memory最新版整链忘记、source导致L2样本不足 | SET NULL不复活旧版；全部live行读者（检索、估时、L1证据血缘、live-key判定）不读valid_to失效行，PATCH不可写valid_to；向量/检索/重算不回写已忘事实；独立用户修正按预期处置 |
| E7-5 | 账号删除与两个worker在context/dispatch/embed/结果写回各处竞态 | 新业务拒绝，run/action诚实结算；已发外部请求不伪造撤回；无新Task/Memory/回答；一份有效claim，旧结果不落库，V不受影响 |
| E7-6 | DB已接受后Redis断供、S3超时/403、进程崩溃 | DB清理账本仍有key；状态非COMPLETED，403不当404；恢复继续同operation，最多自动5次，耗尽可核查；对象版本/导出包一起清 |
| E7-7 | 换账号、离线旧队列、坏备份、Focus草稿、旧客户端/在途闭包 | 无跨账号重传/显示；同上游事件双owner各自保留；换号守卫中止且批N+1不以新token推旧owner队列；无主队列隔离+仅显式adopt/discard；被删来源重采不复活；本机verified需真实清SQLite/WAL、localStorage备份、凭据与临时文件；离线设备标pending（实现基础与逐条预登记见下） |
| E7-8 | grant管理/窄scope、撤销竞态、模型/资料两类consent | 只有实现目录可授权；错category/channel/window拒绝；到期/撤销阻发；L2不被通知L3绕过；quiet hours/daily budget与grant分别生效 |
| E7-9 | 2API+2worker共享限流/恢复、trace链、敏感marker扫描 | 限额不翻倍；Redis断供按冻结策略；HTTP/worker/run/外部调用可关联；logs/trace/errors/审计无marker、credential、URL参数/正文 |
| E7-10 | 从bf02eeb迁移、含删除前数据备份的隔离恢复、配置/key/许可门 | restore先重放抑制再放流量，无已删内容/旧队列复活；RPO/RTO有实测；旧key拒绝/新key可用；许可逐文件有分发结论，未澄清不能发布 |

E7-8必须验证“实际渠道”而非scope里有channels列表就算覆盖；
现在notification.delivered仅预算结算，不能当远程设备已收消息。
E7-10的key真实验证由有权限操作者做；replay用于可重复行为测试，
不能替代真实key轮换证据。

E7-7存储层基础已由P0-2切片1落地（main `d7d8717`，PR #69）：
TS localStorage键与Rust offline.sqlite3复合主键
(owner,client_event_id)/(owner,key)/(owner)两层命名空间——同上游
事件（同client_event_id）双owner各自保留（旧全局键静默丢行已修）；
历史行迁移全归unowned、禁自动归户；ownerKey=SHA-256(origin+"\n"+
userId)前16hex（自包含同步实现，FIPS向量钉住）；换号守卫三道检查
（循环顶push前/push后/setCursor前），批间换号push计数不增、
结算不落新命名空间；未登录不推无主队列，处置仅显式
adopt/discard且目标cursor优先。逐条预登记：①双owner同id两侧
各自可见、互不可见；②换号中止后旧队列重发由服务端幂等兜底为
duplicate；③unowned adopt/discard在真实SQLite执行并断言迁移后
行为；④无主Focus草稿在P0-4处置面落地前仅断言"存在且对各owner
不可见"（处置缺口已在#69评审记档），P0-4落地后追加处置断言；
⑤Stronghold分槽随receipt（P0-4/P0-5）落地后追加凭据槽隔离
断言，此前仅清单记档。

## 3. 删除后零残留核账

registry生成/维护参数化SQL与存储检查，owner限制先于内容查找：

- 每族主/子表删除后计数；JSONB evidence/source_event_ids/basis/
  context_snapshot/args/display/result/mutation.response的ID和marker扫描。
- Chat原文ILIKE/trgm搜索、MaterialChunk vector查询、Memory检索、
  估时ladder、重新生成计划/context/回答；返回零目标内容，不只查DELETE行。
- Memory整条superseded-by闭包、valid_to/rejected/live条件；
  老版本不能靠FK清空指针重新进入live唯一索引/决策。
- 对象head/list/version/导出staging/包：确证不存在；权限/超时独立失败。
- Redis dirty/orphan sets、Arq job/result与worker未完成账本；
  不以Redis空就推断全部清理成功。
- SQLite正常/坏payload与WAL、fallback/corrupt backup、Focus/查询内存、
  Stronghold/临时文件；本机证据独立于服务端receipt。
- 对照V计数/可访问性不变；允许保留的U无内容回执/抑制凭据逐项列明，
  不将仍可关联身份的记录称匿名。

COMPLETED要求受控在线outstanding_count=0且验证通过。
备份30天/供应商政策/其他离线设备是单独限制，不拿“未来会过期”
抵销在线残留，也不承诺第三方不可证的即时擦除。
用户已下载副本不在远程删除保证内，必须有明确提示。

## 4. 执行、审计与收口协议

冻结后先落fixtures/故障注入/verify queries，再写功能，最后联合验收；
不是prompt调优后补一套只证成功路径的样例。
两轮使用同一spec/构建/执行head，第二轮从新seed开始。
E6作为M4受影响路径回归，M5新增断言由E7负责，不覆盖历史spec/证据。
墙钟相关测试注明锚定/免疫/守卫；守卫跳过涉及删除硬门则必须另有固定
锚点的有效通过证据，不能以skip充证。

A留原始失败与恢复账，不修数、不筛行；每个不符预期显式对账。
B独立核验执行SHA/clean tracked tree、manifest、SQL/对象与幂等指纹，
仅声称自己可证范围；报告不虚构收到的中继原文。
脱敏报告入Git，原始本地证据受控留存并备份；E6证据先dump再拆旧栈。
最终协调人核：所有P0 PR准确head批准并合并、E7双轮绿、B无未解释残差、
许可/真实key/恢复门有证据、收口main CI与Client checks双绿，
再登记M5收口。评估门未触发的HNSW/SSE可结转，不作为强行改架构的出口。
