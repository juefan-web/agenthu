# M5 P0-5：可观测与多进程（A）

Status: 切片 1、2 已合并（main `931324f` / `c15a6dd`，#78/#81）。**切片 3
开工（2026-10-08 协调人放行令：#81 合并后即开）——§9 边界先行落字
后动手。**
依据：ops 契约 `m5-data-lifecycle-ops-contract.md` §6（冻结）；规划
`m5-planning-guidance.md` §3 切片表（前置 = P0-1 trace 字段冻结，已随
phase-0 契约闭合）；协调人 P0-5 GO 派工（2026-10-06）+ 2026-10-07
放行（B 转 P0-4 切片 2 / P0-6，A 开本片）。

## 0. 边界

- **负责**：Backend/worker/storage 的可观测与多进程——OTel 链
  （HTTP→operation/run→worker attempt→provider/storage）、span/日志
  字段 allowlist 与脱敏加固、Redis 共享限流（替换 `core/rate_limit.py`
  进程内实现的 `hit`/`retry_after` 缝）、Redis 断供策略（503 分面）、
  ≥2 API 进程 + 2 worker 的唯一 claim/租约竞态验证。
- **不负责**：campus/native 侧遥测（B：Tauri 本地、仅用户同意的脱敏
  技术遥测——本片只在其接入点留缝不动手）；E7 执行（本片就绪后解锁
  E7-9 观测面）；发布门/备份恢复演练（P0-6，A 侧可衔接但独立任务书）；
  供应商政策重核（D-033 线）。
- **互审**：B（campus/native 视角核脱敏面与断供策略）；协调人冻结
  待裁定项。

## 1. 冻结形状对照（ops 契约 §6 → 实现面）

| 冻结句 | 实现落点（实现期逐条对号） |
| --- | --- |
| OTel 链 HTTP→operation/run→worker attempt→provider/storage | FastAPI server span → data_operations/agent run span → arq job span → httpx/provider 与 boto3/storage client span；标准 traceparent/links；trace 不是事实层（不参与任何业务判定） |
| allowlist：route template、服务版本、阶段、错误码、retry/timeout、duration/usage 计数、随机关联 ID | span 属性与日志字段双面同清单；route 用 template 不用实例化 path |
| 禁止正文/prompt/response、SQL 参数/query string、email/IP/GPS、认证 URL/signed URL/headers/keys | 脱敏断言测试钉（fixture 注入敏感值 → span/log 导出内容断言不出现）；SDK 自动异常/正文采集关闭项清单化 |
| 原始 UUID 不做 metric label | metric 面只用计数/直方图 + 低基数字段 |
| trace 断供不阻塞普通请求 | exporter 失败注入测试：请求照常、延迟不显著劣化 |
| 删除确认/状态/清理审计必须同事务持久，不依赖 best-effort middleware | 验证面：durable 审计路径不经过 OTel/middleware 的 best-effort 面（现状已同事务——加回归断言，不是重做） |
| Redis 共享限流：受信代理规则识别登录来源，owner 模型/导出额度、并发任务分桶原子结算 | Redis 原子结算（脚本/事务）；代理信任为显式配置（默认不信任直连值）；owner 分桶键 |
| 生产 Redis 失效：新认证/昂贵任务 503；durable 删除继续 DB 扫尾；普通 owner 读取可用；不静默退每进程无限额度 | 断供分面测试：auth/昂贵路径 503、deletion executor 不依赖 Redis 继续、读路径可用、无 per-process 静默配额 |
| 至少 2 API 进程 + 2 worker 验证唯一 claim/租约执行 | compose 多进程栈 + 并发 claim 测试（operation retry/conflict、arq 任务不双执行） |

## 2. 现状盘点（2026-10-06 @ 31e4743）

- `core/rate_limit.py`：进程内 `defaultdict/deque` 滑窗，docstring 自认
  单 worker 假设并标明 `hit`/`retry_after` 为替换缝；仅登录/注册在用。
- `core/logging.py`：KeyValueFormatter 对 extras **无白名单**（全部
  透传打印）——ops 契约"日志字段白名单待加固"即此；异常栈整段进
  `exc=`（栈内变量值不展开，但帧路径在）。
- `middleware.py`：request-id + best-effort 审计（写库失败不破请求，
  worker 线程执行）；`X-Process-Time-Ms` 已有。
- `pyproject.toml`：无任何 OTel 依赖——SDK/插桩为净新增（选型待裁定）。
- worker：`backend/worker/`（arq，settings/queue/tasks/enqueue）；外部
  调用面已知：model provider（agent_runner）、对象存储、通知投递；
  实现期逐文件清点纳入 span 面。
- dev 栈单容器单进程（compose 无多进程形态）——多 worker 验证需
  compose 增量或专用 override，随切片 3 落。

## 3. 切片建议（开工前协调人可改）

- **切片 1（OTel 骨架 + 脱敏）**：SDK/插桩引入、五层 span 链、
  allowlist 双面（span+log）与禁止清单断言测试、断供不阻塞、
  logging extras 白名单加固、自动采集关闭项。
- **切片 2（共享限流 + 断供策略）**：Redis limiter 落 `hit`/`retry_after`
  缝、owner 分桶、代理信任配置、Redis 失效 503 分面测试。
- **切片 3（多进程竞态验证）**：compose 双 API + 双 worker 栈、
  唯一 claim/租约、跨进程限流一致性、（顺带）为 E7-9 观测面出
  验证句。
- 切片间无硬依赖，1/2 可并作一片交审；3 依赖 2 的栈形态。

## 4. 验收标准（草案，互审时冻结）

1. 五层 span 链一次请求可关联（traceparent/links 断言）。
2. 脱敏断言测试：注入正文/prompt/SQL 参数/email/IP/签名的 fixture
   → 导出的 span 与日志均不出现；extras 白名单外字段被丢弃有测试。
3. trace exporter 断供：普通请求照常返回（测试注入失败 exporter）。
4. Redis 限流跨进程一致（双进程同键并发计数）；断供时分面行为与
   §1 表逐条一致（503 面/durable 继续/读取可用/无静默配额）。
5. 双 API + 双 worker：同一 operation 并发 claim 恰一执行；arq 任务
   无双执行（租约/去重证据）。
6. 全量测试绿、ruff/pyright 同形、OpenAPI 零漂移；新增配置项有
   dev/test/alpha 缺省与脱敏默认（默认不采正文）。
7. B 侧接入缝（campus 遥测）以接口文档形式留出，不实现。

## 5. 裁定（协调人 2026-10-06 冻结，切片 1 起生效）

原"待裁定"四项已全部冻结；实现面逐条对号：

1. **OTel 选型**：`opentelemetry-sdk` + 官方 instrumentation 库
   （fastapi/httpx/botocore 三件，显式 `instrument(tracer_provider=...)`，
   不用 auto-instrumentation 全家桶/sitecustomize）；**OTLP/HTTP 唯一
   线上格式**（`opentelemetry-exporter-otlp-proto-http`，无 gRPC/console
   导出器）；**alpha compose 加 Collector 容器**
   （`docker-compose.alpha.yml` + `docker/otel-collector/config.yaml`，
   debug exporter 骨架，api/worker 不 depend_on 它——断供不阻塞是设计
   属性不是部署巧合）；**SDK 自动捕获关死**：span events 一律剥除
   （自动异常采集）、status description 一律置空（异常消息可含用户
   内容）、不设 metrics pipeline（meter 面为 no-op，原始 UUID 不做
   label 的禁令在 metrics 落地前天然满足）。**allowlist 唯一通道**在
   exporter 边界机械强制（`AllowlistSpanExporter`：非白名单属性键、
   events、status description 剥除后才序列化）——插桩库内部记什么
   都出不去。默认 `OTEL_ENABLED=false`：dev/test/CI 零发射，未配置
   即无遥测（fail-closed）。
2. **受信代理零信任默认 fail-closed**：`core/proxy.py client_ip()` 是
   登录/恢复限流键与 audit IP 面的唯一取值缝；socket peer 为缺省，
   X-Forwarded-For 仅当 peer 在 `TRUSTED_PROXIES` 显式清单内才被读、
   且只取最右条目（代理实际所见，客户端可控的最左条目与深链构造性
   忽略）；清单为空（默认）时处处忽略该头。auth/data/audit 三处调用
   点已收口。
3. **多进程验证承载**：compose override = E7-9 正式承载（2 API +
   2 worker + 真实 Redis），**CI 保持单进程**（ci-smoke override 不动、
   不合并 alpha 文件）。属切片 3，本片只落 Collector 容器。
4. **限流账单一事实源**：Redis 限流桶账单是唯一事实源，P0-4 切片 2
   UI 额度只从后端 API 读、客户端不自算第二计数。属切片 2（B 的 UI
   与 A 的 limiter 以此对齐）；本片不动 `core/rate_limit.py` 的
   `hit`/`retry_after` 缝。

## 6. 切片 1 实施记录（2026-10-07，随本 PR 落）

**做了什么**：OTel 骨架 + 脱敏加固，五行 span 链就位——
HTTP server（官方 fastapi 插桩，request_hook 播 correlation.id，
scope-header 预置与 RequestContextMiddleware 共享同一 request id）→
operation（`data_executor.run_deletion`/`data_exports.run_export` 包装，
correlation.id=operation 随机 UUID）→ run（`agent_runner.execute_run`）→
worker attempt（`traced_job` 装饰 worker/settings.py 十个任务函数，
functools.wraps 保 arq cron unique 键）→ provider/storage client（官方
httpx/botocore 插桩）。worker 经 arq `on_startup` 配置管线
（service.name=agenthu-worker）。propagator 仅 tracecontext（无
baggage——入站 baggage 无法把字段走私进遥测上下文，fail-closed）。

**脱敏面**：span 属性 allowlist（`SPAN_ATTRIBUTE_ALLOWLIST`，exporter
边界强制）+ logging extras allowlist（`LOG_FIELD_ALLOWLIST`，白名单外
extras 丢弃）同族对齐 ops 契约 §6：路由模板（非实例化 path）、有界
标签/枚举、retry/timeout/duration/usage 计数、随机关联 ID（request/
job/run/operation/file/item/event id——按事件铸造的 uuid4，非 user_id
这类稳定身份 UUID，后者与 course_name、audit action 串一起被有意
移出日志面）。关联 ID 界线注释钉在两处 allowlist 顶部。

**新增配置**：`OTEL_ENABLED`（默认 false）、
`OTEL_EXPORTER_OTLP_ENDPOINT`（默认 http://127.0.0.1:4318/v1/traces）、
`OTEL_SAMPLE_RATIO`、`OTEL_EXPORT_TIMEOUT_SECONDS`、`TRUSTED_PROXIES`
（默认空 = 全零信任）。dev/test/alpha 缺省全脱敏默认。

**测试**（`tests/unit/test_telemetry.py` + `test_proxy_and_logging.py`）：
查询串/头值/非白名单属性不出现在导出面；同请求 server→operation→
provider 三层同 trace 父子关联；`stage_span` 非白名单字段丢弃+告警、
异常记有界 error.code 且消息/事件/status description 不外泄；
exporter 持续抛错 3 请求照常 200；默认禁用=no-op tracer；XFF 五态
（无信任/受信 peer 最右/非受信 peer/畸形/无 client）；extras 白名单
保留关联字段、丢弃身份与内容字段。

**不做**（本片边界）：Redis 共享限流与断供 503 分面（切片 2）、
多进程 compose 栈与唯一 claim 验证（切片 3）、campus/native 遥测
（B，接入缝未动——contract 已冻结字段族即缝）、metrics 面全部。

**验收对照 §4**：#1 部分达成（进程内五层链关联断言已钉；跨进程
traceparent 贯通随切片 3 多进程栈验证）；#2 全量达成；#3 达成；
#4/#5 属切片 2/3；#6 随本 PR 全量跑（测试/ruff/pyright/OpenAPI）；
#7 未动（campus 缝无变化）。

**RC-1 修复（2026-10-08，B 互审必改，变异实验坐实）**：`_sanitize`
原样透传 `links=span.links`——Link 自带 attributes 不经键白名单（B 本地
@2320e49 实跑：`user.email`/`http.request.header.authorization` 带值
随 OTLP 出进程存活；如实记——现行三插桩不发 attribute-bearing links，
属承诺面的缝而非现行泄漏）。修复：links 重建为 context-only
（`tuple(Link(l.context) for l in span.links)`；link 身份=trace/span id，
attributes 整体丢弃——白名单键也不保留，键过滤器本看不到 link
attributes），一次性告警与 events 同款；模块/类 docstring 把 links
计入"重建而非透传"清单。B 的变异探针转常驻测试
`test_link_attributes_never_reach_the_exporter`（注入带属性 Link →
断言导出 link attributes 为空、身份保持 donor span/trace id）。

**测试计数修正**（B 互审核实；此前"453+10"分解有误，实测值本身无误）：
`8efd84b` 后端基线 = **447+6**（与 #77 CI 回填同数，#77 零后端改动）；
本片新增 = telemetry 8 + proxy/logging 8 + RC-1 探针 1 = **17**，
447+16=463 与既有 CI 实测严丝合缝。白天窗本地全量 469 passed + 1
skipped（6 个晚窗守卫白天实跑通过，skip=S3_ENDPOINT_URL 未设）；
修复头 CI 数字以实跑日志为准回填。

## 7. 切片 2 边界（2026-10-08 开工前冻结；落字在先，实现在后）

**负责**：

- `core/rate_limit.py` 的 `hit`/`retry_after` 缝换 **Redis 滑动窗实现**
  （ZSET + Lua 单脚本原子：trim 过期 → count → 未满则 ZADD 唯一成员
  → PEXPIRE；`retry_after` 读 oldest score。语义与进程内版一致：同
  窗口、同上限、同 Retry-After 口径；时间取 Redis 服务器钟
  （脚本内 TIME），免客户端钟偏）。
- **断供 fail-closed 503 分面**：Redis 不可达/超时（bounded socket
  timeout，显式配置项）⇒ `RateLimitUnavailableError(
  ServiceUnavailableError)`、code=`rate_limit_unavailable`——与 429
  `rate_limited` 区分；不静默放行（fail-open = 跨进程/重启后暴力面
  失守），不伪装 429。
- **键名与分桶**：`rl:` 前缀命名空间（与 arq 键隔离）；分桶保持现状
  ——auth=`auth:{client_ip}`、recover=`recover:id:{identity}` +
  `recover:ip:{client_ip}`（owner 分桶即 recover:id）。裁定④对齐：
  Redis 账单唯一事实源；B 的 UI 维持只读服务端响应，**本片不加新
  额度 API**。
- **测试**：现有 auth/register/recover 限流测试改注入 Redis 版
  limiter（namespace 按 test 唯一隔离）；断供分面单测（不可达 Redis
  URL → 503 + code 断言 + Retry-After 缺席）；滑动窗语义测试（短窗
  实跑）；一条"限流键取 client_ip"回归（XFF 受信链下键值正确，
  TRUSTED_PROXIES 应用面随切片 1 已收口，此处只钉回归）。
- **Redis 客户端**：复用 `redis_url` 配置（与 health 检查同源），
  sync 客户端（调用点均为 sync def 端点），连接池进程内懒建单例。

**不负责**：多进程 compose 栈、唯一 claim/租约、跨进程 traceparent
（切片 3）；数值额度展示 API（B 的 UI 契约不变；若需数值面另开
裁定）；limiter 遥测 span（遥测面切片 1 已定型，本片不加新 span
面）；worker 侧限流（worker 无此缝）。

**兼容与回滚**：`RateLimiter` 类名与 `hit`/`retry_after` 方法签名
保持；构造签名扩可选参数（redis client 注入口 + namespace，测试
隔离用）；**进程内实现删除**（保留 = 第二账本 = 违反裁定④；回滚 =
revert 本片提交）。旧进程内账本无迁移（窗口 ≤600s，滚动即清）。

**验收**：①滑动窗语义 + 跨键隔离测试钉（CI 起 redis 服务、本地
agenthu-redis-1，单代码路径无 fallback）；②断供分面 503+code 测试
钉；③contract drift 无漂移（错误 code 不入 OpenAPI 枚举则无漂移，
以实测为准）；④全量测试 + ruff + pyright 绿。

## 8. 切片 2 实施记录（2026-10-08，随本 PR 落）

**交付面**：`core/rate_limit.py` 整体替换为 Redis 滑动窗——ZSET + 两个
Lua 脚本（`register_script` SHA 缓存；服务器钟 TIME 免客户端钟偏；
`rl:` 键前缀与 arq 键隔离；**进程内实现删除**，保留即第二账本=违反
裁定④，回滚=revert 本片）。`RateLimiter` 类名与 `hit`/`retry_after`
缝保持；构造签名扩 keyword-only `client`（测试注入口）与 `namespace`
（默认 "rl"）。**断供 fail-closed 503 分面**：Redis 不可达
（connect/socket 双超时 = `RATE_LIMIT_REDIS_TIMEOUT_SECONDS`，默认
0.5s）⇒ `RateLimitUnavailableError(ServiceUnavailableError)`，code=
`rate_limit_unavailable`——全局 AppError 处理链直接落 503 信封，
auth/recover 调用点零 try/except（缝内收口）。**调用面零改动**：
auth `_auth_limiter` 与 data `_RECOVER_LIMITS` 构造不变（分桶/上限/
窗口保持：auth=IP 单桶；recover=id+IP 双桶 3/10 每 600s）；仅 auth
限流器注释更新（"per process"→账本跨进程语义）。Redis 客户端：
`redis_url` 同源、进程内懒建单例（一线程安全连接池）。

**测试**：新增 `tests/unit/test_rate_limit_redis.py`（真 Redis，不可达
自动 skip）：窗内放行/超限、窗口滑动（1s 实窗）、键隔离、**双实例共
账本**（跨进程单事实源的钉子）、namespace 隔离、max=0 禁用不触后端、
断供双方法抛 503 分面；`test_security.py` 三条进程内旧测试移除（语义
由新文件覆盖）。集成面：auth 两条限流测试改注入隔离 namespace
limiter；**新增 503 分面集成测试**（死端口 client → login 503 +
`rate_limit_unavailable` + 无 Retry-After）；**新增 client_ip 键回归**
（TRUSTED_PROXIES 受信链下不同转发客户端各获独立预算、同客户端独耗
己桶）；recover autouse fixture 由清 `_hits` 改为按测试换隔离
namespace limiter 对。conftest 的 `AUTH_RATE_LIMIT_MAX=0` 使默认测试
路径短路（不触 Redis），仅显式注入的 limiter 连 Redis——CI redis
服务/本地 agenthu-redis-1 承载；测试键自带 PEXPIRE，无清理负担。

**验证**：全量 **475 passed + 1 skipped**（白天窗；469 基线 +9 新
[8 单测+503 集成+client_ip 回归−3 移除] 之实跑数）、ruff/format/
pyright 0、contract drift --require-zod 无漂移（新错误码走统一错误
信封，不入 OpenAPI 枚举）。

**不做**：多进程栈/唯一 claim/跨进程 traceparent（切片 3）、数值额度
API（B 的 UI 维持读服务端响应）、limiter 遥测 span。

## 9. 切片 3 边界（多进程竞态验证；2026-10-08 开工前冻结，落字在先）

**负责**：

- **跨进程 traceparent 缝**（切片 1 §6 留待本片的贯通面）：
  `worker/queue.py` 新增 enqueue helper——把当前 span 的 traceparent
  （`TraceContextTextMapPropagator.inject`）作为 `_traceparent` kwarg
  随任务入队；`telemetry.traced_job` pop 该 kwarg 并 extract 为父
  上下文（任务函数签名零变化，`_job_id` 透传保持）；六个 enqueue
  调用点（chat / tasks×2 / jobs / material / files）换 helper。无
  活动 span → 无 kwarg → worker span 为根（现状语义）；cron 任务
  无 kwarg → 根 span。隐私面：traceparent 是随机关联 ID 载体，不入
  span 属性/日志字段、不触 allowlist；"trace 不是事实层"不变。滚动
  混布不在兼容面（compose 全栈重建、api/worker 同版升级，旧 worker
  收到 `_traceparent` 会当多余 kwarg 报错——同版约束写头注）；
  回滚 = revert 本片。
- **多进程 compose 承载 = E7-9 正式承载**（裁定③）：新
  `docker-compose.multi.yml`——Collector 服务同 alpha 定义；api/worker
  OTEL env 打开指向 collector；api 端口改区间
  `127.0.0.1:8100-8101:8000`（compose `!override`，需 compose
  ≥ 2.24，头注写明；**2026-10-08 实测修正**：原冻结 8000-8001，实测
  宿主 8000 被 WSL 内开发者常驻 llm_gateway 长期占用、dev api 缺省
  亦为 8000——证据区间挪 8100-8101 与两者共存）；一次性 `migrate`
  服务（alembic upgrade head）+ api command 去迁移化 + depends_on
  migrate（双 api 不赛跑 DDL）；起栈 `--scale api=2 --scale worker=2`；
  真实 Redis = 既有 redis 服务；auth 限流上限/窗口透传
  `${AUTH_RATE_LIMIT_MAX:-10}` /
  `${AUTH_RATE_LIMIT_WINDOW_SECONDS:-60}`（证据跑可压小上限）；
  ci-smoke 保持单进程、零合并。
- **唯一 claim 验证（CI 单进程可跑，双会话/双线程模拟跨进程）**：
  ①并发 claim——两会话两线程对同一批 due cleanup items 并发
  `claim_cleanup_items`：各自所得互斥、并集 = 全部 due、attempts
  恰一（SKIP LOCKED 语义钉；断言对任意交错成立，不赌时序）；
  ②双派发恰一执行——同一 deletion operation 双 `run_data_operation`
  并发驱动：终态一致、存储删除恰一次（operation/items 状态守卫面）；
  ③arq 面机制句——cron unique 键 + `max_tries`/`job_timeout` +
  claim 幂等 = 至少一次投递、恰一次生效（任务书记录，不加代码）。
- **跨进程限流一致性**：语义已由切片 2"双实例共账本"单测钉；本片补
  栈级验证程序（E7-9 证据句，落 §10）：multi 栈下对 :8000/:8001 交替
  打 login，同一预算耗尽处 429（计数跨进程一致）。
- **B 两条非阻塞注记顺手补**（随 #81 合并议定）：within-window 断言
  改窗长推导区间 `1 ≤ retry_after ≤ window`；新增空键归零态专测
  （fresh key → `retry_after() == 0`）。

**不负责**：E7-9 执行本身（等 P0-5/P0-6 收口后的执行轮）；负载均衡/
反代（双端口直连即证据面）；metrics 面；campus/native 遥测；多进程
CI 化（裁定③不变）；limiter/claim 语义改动（本片只验证不重写）。

**验收**：①traceparent 缝三态单测（有父贯通/无父根 span/畸形头不崩）
钉死；②并发 claim 与双派发恰一执行测试绿；③multi 栈本地可起、E7-9
验证句组落 §10（跨进程同 trace id 证据 = collector 面实测，非推演）；
④B 两条注记测试落；⑤全量测试 + ruff + pyright 绿、OpenAPI 零漂移
（无 API 变更）；⑥新增配置零项（OTEL_* 既有，compose 透传不动
config 缺省）。

## 10. 切片 3 实施记录（2026-10-08，随本 PR 落）

**交付面**：

- **跨进程 traceparent 缝**：`worker/queue.py` 新增 `enqueue`
  （producer 的 traceparent 经 `TraceContextTextMapPropagator.inject`
  作为 `_traceparent` job kwarg 入队；无活动 span 则 kwarg 缺席，
  worker span 保持根——切片前语义）；`telemetry.traced_job` pop 该
  kwarg 并 extract 为父（任务函数签名零变化；畸形头降级根 span 不
  崩）。**`stage_span` 有意不加 `context` 参数**：现有调用方全部经
  dict-splat 传字段，带类型的非 str keyword 参会让 splat 调用在
  pyright 下全数报错（实测 16 错）；traced_job 改为自行开 span，
  属性面（stage + correlation.id/job.try + 有界 error.code）与
  stage_span 完全同构。六个 enqueue 调用点换缝（chat / tasks×2 /
  jobs / material / files，`_job_id` 透传保持）。
- **`docker-compose.multi.yml` = E7-9 正式承载**：Collector 服务 +
  一次性 `migrate`（双 api 不赛跑 DDL）+ api 端口区间 8100-8101
  （`!override`，需 compose ≥ 2.24）+ OTEL env + auth 限流上限/窗口
  透传 + S3 缺省 s3mock；db/redis/s3mock **丢弃宿主端口**与 dev 栈
  共存；ci-smoke 单进程零合并。配套
  `docker/otel-collector/config.evidence.yaml`（verbosity detailed
  ——E7-9 从 `docker logs` 直读 span 名/trace id；alpha 骨架的
  basic 不动）。
- **同版部署耦合**（写入 queue.py docstring 与 compose 头注）：
  `_traceparent` kwarg 只有同版 traced_job 会 pop，api/worker 随
  compose 全栈同版升级，滚动混布不在兼容面；回滚 = revert 本片。

**测试（+6）**：telemetry 3（有父贯通按 trace/span id 断言/无父
根 span/畸形头降级 + 严格签名任务充当 pop 证明）；lifecycle 1（两
连接两线程并发 `claim_cleanup_items`：所得互斥、并集 = 全部 due、
attempts 恰一——对任意交错成立，不赌时序）；executor 1（同一
operation 双 `run_data_operation` 并发：每对象存储删除恰一次、
operation 收敛 COMPLETED、items DONE attempts=1）；rate-limit 2
（B 的 #81 两注记：窗长推导区间断言 + 空键归零态专测）。两并发
测试在真提交连接上各自开会话（finally 自清行）——单进程 CI 可跑，
claim 层面等价两个 worker。

**本地验证**（独占窗口，无并发 pytest 干扰）：全量 **473 passed +
9 skipped**（总量 = 476 基线 + 6 新测试；9 skip = S3 1 + 晚窗守卫
8）、ruff/format/pyright 0、OpenAPI 零漂移（再生成内容一致，仅
CRLF 假改）。**CI 实测（修复头 `4e2545c`，run 37869406909）：
`482 passed, 2 warnings in 159.64s`，0 skipped**——恰为 476 基线 +
6 新测试。首头 `14b9fba` CI 两败已修：①双派发测试在生产
`session_scope`（绑 `DATABASE_URL`）与测试 engine（绑
`TEST_DATABASE_URL`）在 CI 指向**不同库**时静默 not_found（本地两
URL 同库故未暴露）——测试改为把 `backend.worker.tasks.session_scope`
monkeypatch 到绑定测试 engine 的 scope（密封，本地以 CI 同款分离
库环境复跑实证）；②retry_after 上界：同毫秒命中时
`floor(window−0)+1 = window+1`（CI 实测 31/窗 30）——+1 进位是语义
一部分，断言区间改为 `window−2 ≤ ra ≤ window+1` 并注明。

**multi 栈实测**（本机 compose v5.3.1，项目名 `agenthu-multi`，
证据跑完已拆栈、dev 栈未动）：

- **起栈**：migrate 一次性 + db + redis + s3mock + otel-collector +
  api×2 + worker×2 共 8 容器全 healthy（`--scale api=2
  --scale worker=2`，端口 8100/8101）。
- **跨进程限流一致**（AUTH_RATE_LIMIT_MAX=10）：1 次真登录（200）
  + 8 次错密码（401）交替打 :8100/:8101 后，第 10 次命中
  **429@8101**，续打 :8100 仍 **429**——预算跨两 API 进程单一账本。
- **跨进程 traceparent**：ping@8100 202 → collector detailed 面
  `POST /v1/jobs/ping`（Server，Trace ID `8143a4e5…55e`，ID
  `5fe0e088…`）与 `worker.ping`（**Trace ID 相同、Parent ID =
  server span 的 ID**）——一条 trace 贯穿 api→redis→worker 三个
  进程边界。§4 验收 #1 的跨进程半面就此闭合。
- **环境事实**（留存）：① 本地 `otel-collector:0.116.0` 镜像层
  损坏（裸跑 `--version` 即 exec 失败；0.117.0 重拉实测可用——起栈
  时以 `OTEL_COLLECTOR_IMAGE=otel/opentelemetry-collector:0.117.0`
  覆盖，文件缺省不动）；② 宿主 8000 被 WSL 内开发者常驻
  llm_gateway 长期占用（保持不动）→ 证据区间 8100-8101（§9 修正
  已注）。

**不做**：E7-9 执行本身（执行轮）；metrics 面；campus/native 遥测；
CI 多进程化（裁定③不变）。
