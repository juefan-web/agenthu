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

# 逐 case 核账（驱动内已跑；独立复核用）
./.venv/Scripts/python.exe -m tests.e7.verify --case E7-3a --report output/e7/smoke/E7-3a/verify-standalone.json
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

## 5. 冒烟栈的拆除

冒烟结束保留 `agenthu_e7` 库与 bucket 供 B 核账（E6 先例：证据库保留）；
确认收口后再拆。勿动 `agenthu` 主库与 E6 证据库。
