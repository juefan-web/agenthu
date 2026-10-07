# M5 P0-5：可观测与多进程（A）

Status: 切片 1 实施中（2026-10-07 协调人放行令开工；四裁定已冻结入
§5）。基线 main `8efd84b`（#76 合并后）。依据：ops 契约
`m5-data-lifecycle-ops-contract.md` §6（冻结）；规划
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
