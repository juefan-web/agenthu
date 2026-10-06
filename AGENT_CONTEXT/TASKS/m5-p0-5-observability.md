# M5 P0-5：可观测与多进程（A）

Status: 准备期任务书（2026-10-06 落，开工待 #75/#76 合并后协调人令）。
基线 main `31e4743`。依据：ops 契约 `m5-data-lifecycle-ops-contract.md`
§6（冻结）；规划 `m5-planning-guidance.md` §3 切片表（前置 = P0-1 trace
字段冻结，已随 phase-0 契约闭合）；协调人 P0-5 GO 派工（2026-10-06，
与 E7 fixtures 并行自排；E7 双轮执行以 P0-5/P0-6 齐为门）。

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

## 5. 待裁定（开工前请协调人冻结）

1. **OTel SDK/导出器选型**：`opentelemetry-sdk` + 手动插桩 vs
   auto-instrumentation 全家桶（依赖面与"自动采集关闭项"多少的
   权衡）；Alpha 导出器形态（无 collector 时 console/none 与采样率）。
2. **受信代理信任配置**：默认值（dev 直连 0 信任）与 alpha 的
   代理清单承载方式（env/config），影响登录限流键的取值链。
3. **多进程验证的承载**：compose override（`--scale` 或显式双服务）
   还是 CI 单机多进程脚本；影响 CI 时长与 E7-9 复用。
4. **限流键与 owner 分桶的精确口径**：哪些端点进 owner 分桶
   （模型/导出/并发任务），与 P0-4 切片 2 UI 的额度展示是否同源。
