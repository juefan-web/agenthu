# E7 验收栈（M5 P0-7 准备期 runbook）

独立验收栈与门控套件（m5-e7-acceptance §1：独立 DB / bucket / Redis）。
准备期冒烟由 A 执行；双轮执行等 P0-5/P0-6 齐（协调人派工 2026-10-06）。

## 1. 一次性准备

```bash
# 独立库（compose db 容器，pgvector/pg16 镜像；E6 先例 agenthu_e6）
docker exec agenthu-db-1 psql -U agenthu -d agenthu -c "CREATE DATABASE agenthu_e7 OWNER agenthu;"

# 迁移从零 up（注意 DATABASE_URL 指向 E7 库）
DATABASE_URL=postgresql+psycopg://agenthu:agenthu@127.0.0.1:5432/agenthu_e7 \
  ./.venv/Scripts/python.exe -m alembic upgrade head

# s3mock 上建独立 bucket
curl -s -X PUT http://127.0.0.1:9090/agenthu-e7 -o /dev/null -w "%{http_code}\n"  # 200/201

# 执行期 Redis：独立容器（准备期冒烟可用既有容器的 DB 15，见任务书裁定④）
docker run -d --name agenthu-e7-redis -p 6380:6379 redis:7-alpine
```

## 2. 栈环境（uvicorn :8011 + arq worker 同 env）

```bash
export DATABASE_URL=postgresql+psycopg://agenthu:agenthu@127.0.0.1:5432/agenthu_e7
export REDIS_URL=redis://127.0.0.1:6380/0          # 冒烟可 redis://127.0.0.1:6379/15
export STORAGE_BACKEND=minio
export S3_ENDPOINT_URL=http://127.0.0.1:9090
export S3_ACCESS_KEY=agenthu S3_SECRET_KEY=agenthu123 S3_BUCKET=agenthu-e7 S3_REGION=us-east-1
export SECRET_KEY=e7-stack-secret-not-for-production
export ENVIRONMENT=local                            # 假件/本地面
export AUDIT_ENABLED=false                          # 确定性：API 调用不写审计行（seed 行仍证 §5 脱敏）
export OPENAI_BASE_URL=http://127.0.0.1:9099/v1 OPENAI_API_KEY=e7-replay  # 执行期接 E6 e6-replay.mjs

./.venv/Scripts/python.exe -m uvicorn backend.main:app --host 127.0.0.1 --port 8011 &
./.venv/Scripts/python.exe -m arq backend.worker.settings.WorkerSettings &
```

## 3. Seed / verify / 门控套件

```bash
export E7_DATABASE_URL=$DATABASE_URL E7_REDIS_URL=$REDIS_URL
export AGENTHU_E7_STACK=1 AGENTHU_E7_BACKEND_URL=http://127.0.0.1:8011

# seed（每用例重建 = truncate + 直插 + blob；不碰 Redis——dirty 成员会唤醒
# trigger cron 造行破坏确定性，任务书裁定⑨/seed.py 模块注记）
./.venv/Scripts/python.exe -m tests.e7.seed

# baseline（未操作世界必须全绿：before counts + marker 隔离 + 向量/对象/Redis）
./.venv/Scripts/python.exe -m tests.e7.verify --baseline

# 门控套件（每用例自带 fresh world；证据落 output/e7/<round>/<case>/）
./.venv/Scripts/python.exe -m pytest tests/e7/cases -v

# 单案独立复核 = 重跑该 pytest 案本身：自带 fresh world + 动作 + 案内
# verify，证据照常落 output/e7/<round>/<案>/。CLI verify 仅保留
# --baseline——旧「--case 对当前库核账」形态已撤（D1 裁定）：case 期望
# 是动作后终态账，只对该案自己驱动的世界成立；对套件终末世界或任何
# 其他案的世界结构性必红（r1 假红的根因，示例恰是必红的 E7-3a）。
./.venv/Scripts/python.exe -m pytest "tests/e7/cases/test_e7_3_source_deletion.py::test_e7_3a_delete_anchored_event_whole_deletes_derived_task" -v
```

## 4. 纪律

- **预登记**：expected 只读 `tests/e7/manifest.json`（由 seed_spec 派生、
  提交在库、B 先核）；`tests/unit/test_e7_manifest.py` 在普通 CI 钉漂移。
- **证据**：`output/e7/` 已 gitignore——原始证据本地受控留存，脱敏汇总
  入 `AGENT_CONTEXT/TASKS/m5-e7-fixtures.md`；真实个人内容、真实 key
  永不进入 fixtures/日志/证据（E6 纪律沿用）。
- **两轮协议**：同一 spec/构建/执行 head，第二轮从新 seed 开始
  （`AGENTHU_E7_ROUND=<r1|r2>` 区分证据目录）。
- **冒烟不需要模型调用**：seed 直插 AgentRun/PendingAction 行；
  provider 假件仅在执行期 E7-5 竞态场景接入。

## 5. 冒烟栈的拆除与 B 侧核账

冒烟结束保留 `agenthu_e7` 库与 bucket 供 B 核账（E6 先例：证据库保留）；
确认收口后再拆。勿动 `agenthu` 主库与 E6 证据库。

B 侧库面抽查（修复轮起）：容器 `agenthu-db-1`/`agenthu-s3mock-1` 保持
运行，`docker exec agenthu-db-1 psql -U agenthu -d agenthu_e7` 直连在档；
API/worker 按 §2 环境块两条命令即起（A 会话进程存活期间
`http://127.0.0.1:8011` 可直连）。

## 6. E7-9 多进程栈（multi compose，项目 `agenthu-multi`）

E7-9 的证据载体是 `docker-compose.yml` + `docker-compose.multi.yml` 合并
形态：2 API（宿主 `127.0.0.1:8100/8101`，**非 8000-8001**——WSL 内
llm_gateway 占 8000 是红线，端口覆写即为此冲突的冻结解法）+ 2 arq
worker + OTel Collector（`127.0.0.1:4318`，debug exporter detailed，
span 名/trace id 可直读 `docker logs`）。multi 文件把 `name:` 钉为
`agenthu-multi`，栈与 dev 栈（项目 `agenthu`）隔离共存：multi 侧
db/redis/s3mock 不发布宿主端口，dev 栈照常持有 5432/6379/9090。

```bash
# 起栈（E7-9 驱动会自己做；手工形态同此，compose >= 2.24，!override 需要）
AUTH_RATE_LIMIT_MAX=6 docker compose -p agenthu-multi \
  -f docker-compose.yml -f docker-compose.multi.yml --profile s3mock \
  up -d --wait --scale api=2 --scale worker=2 \
  migrate db redis s3mock otel-collector api worker

# seed（镜像烤了 tests/；容器内走内网地址；bucket 需先建一次）
docker compose -p agenthu-multi -f docker-compose.yml -f docker-compose.multi.yml \
  exec -T api python -c "<boto3 head/create_bucket agenthu-e7 @ s3mock:9090>"
docker compose -p agenthu-multi -f docker-compose.yml -f docker-compose.multi.yml \
  exec -T -e E7_DATABASE_URL=postgresql+psycopg://agenthu:agenthu@db:5432/agenthu \
  -e E7_REDIS_URL=redis://redis:6379/0 -e S3_ENDPOINT_URL=http://s3mock:9090 \
  -e S3_ACCESS_KEY=agenthu -e S3_SECRET_KEY=agenthu123 -e S3_BUCKET=agenthu-e7 \
  api python -m tests.e7.seed

# 限流账本清零（滑窗确定性）；provider 面接宿主 e6-replay（:9099，须先起）
docker compose -p agenthu-multi -f docker-compose.yml -f docker-compose.multi.yml \
  exec -T redis sh -c "redis-cli --scan --pattern 'rl:*' | xargs -r redis-cli DEL"
node apps/desktop/tests/e2e/e6-replay.mjs &   # 容器内经 host.docker.internal 访问

# 证据面：collector/api/worker 的 docker logs --since <起栈时刻> + 审计表
# 拆栈（确认收口后）：docker compose -p agenthu-multi ... down -v
```

注意：worker 的 dev bind mount 在 multi 形态被 `!override []` 撤除——证据
栈跑镜像里烤进的已提交代码，不跑宿主工作树；api/worker 的
OPENAI_BASE_URL 默认指 `host.docker.internal:9099/v1`（e6-replay 假件，
沿用「证据期不接活 provider」纪律）。

## 7. E7-10 恢复演练 / key 轮换 / 许可门（驱动自管栈）

E7-10 机制面由驱动自管三个短命栈（`tests/e7/cases/test_e7_10_recovery_gates.py`），
宿主前置：`agenthu-db-1`（pg_dump/psql 演练面）、`agenthu-e7-redis`（:6380）
与 s3mock 运行中，源栈（§2，:8011）照常；**端口 8013 / 8112 / 8113 须空闲**。

- **key 轮换（假件语义）**：scratch 库 `agenthu_e7_10_rotate` + redis db 6；
  K_old 进程 :8112 铸旧 JWT → 切 K_new 进程 :8113 → 旧 JWT 全业务面 401、
  新登录读通。库随案 DROP。
- **恢复演练**：源栈 seed 后 `pg_dump`（删除前备份）→ 删 e1 →（源栈面即
  断言 p1/pi1/r1 失效 basis 仍供悬空 id 但不再供 e1/t1 原文，E7-3a 同面）→
  抑制账本 + data_generation 独立导出（`ledger.json`，值键行无 users FK
  ——表设计本就支持单表重放）→ 备份恢复进隔离库 `agenthu_e7_10_restore` →
  **先重放抑制再起栈**（:8013 api + worker，redis db 5 全新——Redis 永不
  恢复）→ 维护性重删走真实闭包执行器 → 放行业务流量 → 同锚新 envelope
  409。备份件 `backup.sql`/`ledger.json` 落
  `output/e7/<round>/E7-10/`（gitignored）。
- **恢复栈必须沿用源栈 SECRET_KEY**：抑制锚 `upstream_hmac` 与 receipt 能力
  密封都以 server secret 为键（write_guards.py / data_recovery.py）——key
  轮换需配套 digest 迁移方案，驱动级发现已录任务书 §7。
- **许可门 = 引用对账**（分项 2）：驱动只断言库内终态文档在案
  （license-inventory 零红旗/封印/阻断规则、README 临时公开封印段、
  THIRD_PARTY_NOTICES 逐文件结论），不重新普查；真实 key 轮换证据位
  如实登记「未提供」（分项 3）。
- RPO/RTO 为演练实测墙钟（备份→故障→恢复→重放→放行），Alpha 目标
  （RPO≤24h/RTO≤4h）是契约拟目标，不作 SLO 声明。
