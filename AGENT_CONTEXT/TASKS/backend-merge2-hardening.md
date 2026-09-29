# Backend hardening（merge-2 期间的非阻塞项）

负责人：开发者 A。性质：**非合并门槛**——merge-2 报告未发现 Backend 缺陷
（D5/D7 修复已被第二轮验收确认通过），本任务是利用 D8 修复窗口清掉首轮审阅
遗留的次级加固项。

## 1. Docker Compose 服务健康检查（首轮审阅遗留）

- `docker-compose.yml` 的 `api` 与 `worker` 服务自身无 healthcheck（db/redis/
  minio 已有）。补 `api`（`/health` 端点）与 `worker` 的健康探针；`--reload`
  仅保留在显式 dev profile。
- 验收：`docker compose up` 后 `docker compose ps` 显示 healthy。

## 2. CI 依赖与镜像检查（首轮审阅遗留）

- 加 `pip-audit`（Backend 依赖漏洞扫描，允许已知豁免清单并注明原因）。
- 加 Docker build 验证 job（只构建不推送），防止 Dockerfile 漂移无人发现。
- 验收：CI 全绿，两项新 job 在 PR 上可见。

## 3. 联合 review：D8 修复的隐私边界变化

- B 的 D8 修复（见 `client-merge2-d8-info-xsrf.md`）将把 campus 域 Cookie 的
  name/value 对经 IPC 镜像给 TS 适配层。按 AGENTS.md §3「共同 review 涉及隐私
  的代码」，A 需对该变更给出书面 review 意见（镜像范围是否最小化、是否可能
  进入日志/Event、是否影响 Stronghold 快照语义）。
- 验收：review 意见落在该任务文件或 PR 评论；如发现放大面则要求 B 收窄。

## 不负责

- 不动主链路行为与契约（无 schema/OpenAPI 变更预期）。
- 不以本任务阻塞 PR #1 转正；转正门槛仍是 D8 修复 + 第三轮构建包人工验收。
