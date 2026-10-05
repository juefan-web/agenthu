# M5 P0-1 切片 1：统一 live 谓词与 validity 移出可写面

Status: **已实现，待 B head-bound 互审与协调人核验合并（2026-10-05）**。
依据：[D-036](../DECISIONS.md) §8-1/§8-6 与实施令；本切片是 P0-1 的首个
契约变更。后续 P0-1 切片（持久操作/清理账本、owner 屏障与代际、依赖
清单矩阵）另行开任务。

## 0. 任务边界

| 项目 | 本次切片 |
| --- | --- |
| 目标 | 把 live 行定义收敛为单一共享谓词并接入全部读者/写侧判定；validity 移出客户端可写面；唯一索引窄化为不可变子集 |
| 输入 | D-036 §1/§6、bf02eeb 现状（四处 `supersedes_id IS NULL` 读者 + keyed upsert 写侧）、M4 迁移惯例 |
| 输出 | `live_memory_conditions` 共享谓词、五处接入、schema/OpenAPI 收窄、索引迁移、集成测试、本文档 |
| 负责范围 | backend 读者/写侧/schema/迁移/OpenAPI/测试 |
| 不负责范围 | 删除图/导出（P0-3）、B 侧客户端（P0-2）、E7 预期账面重写（随实现切片同步） |
| 验收 | 全部读者不回流失效行；复活行不占 subject_key；PATCH/POST 忽略 validity；迁移升降级往返 + autogenerate 零漂移；全量测试/静态检查绿 |

## 1. 实现记录

- **共享谓词**：`backend/services/memory_lifecycle.py::live_memory_conditions(now)`
  = `supersedes_id IS NULL AND (valid_from IS NULL OR <=now) AND
  (valid_to IS NULL OR >now)`。窗口语义 `valid_from <= now < valid_to`，
  NULL 界无界。
- **接入点（5 处，比裁定书多一处，见 §2）**：
  `memory_retrieval.py`（检索）、`estimates.py::live_key_row`（估时梯子）、
  `event_handlers.py::_recent_episode_ids`（L1 证据血缘）、
  `api/v1/memory.py::_live_key_owner`（创建/改键冲突预检）、
  `memory_lifecycle.py::upsert_keyed_memory`（L2 keyed upsert 的写侧
  live 行解析）。
- **可写面收窄**：`MemoryUpdate` 移除 `valid_from/valid_to`（D-036 §6
  原文）；`MemoryCreate` 同步移除（§2 解释步）。旧客户端发送两字段被
  pydantic 默认静默忽略（同 correction_status/embedding 既有模式），
  `MemoryRead` 保留两字段只读输出，客户端镜像（读侧）无需变更。
- **索引**：`uq_memories_user_subject_live` 谓词加 `AND valid_to IS NULL`
  （迁移 `45b7db4cb2cb`，down_revision `c4f2a8e01d73`）。索引仍是
  **写序守卫**（不可含 now()），不是读侧 live 定义；窄化只把行移出
  索引，不可能引入唯一冲突，无回填需求（现无 writer 产生未来 valid_to
  行；退休恒盖 `valid_to=now`）。

## 2. 两处实现期判断（供 B 互审与协调人核验）

1. **Create 侧同步移除（超出裁定书字面、未出原则）**：D-036 §6 命名
   MemoryUpdate，但同节原则是"有效期仅服务端管理"；POST 侧保留
   可写 valid_to 会原样保留"建成即失效仍被读"的缺口（本切片前
   客户端可 POST valid_to=past 直接造出读不到的 live 行）。若 B/
   协调人不同意，恢复 Create 字段是单行回退。
2. **第五接入点 upsert_keyed_memory**：裁定书"四处读者 + 写侧
   live-key"；keyed upsert 的 live 行解析（FOR UPDATE 查找）正是
   写侧 live-key，不接则复活行会被 L2 writer 当 live 行去 supersede。

## 3. 验证证据（本地，2026-10-05）

- 新增 `tests/integration/test_memory_liveness.py`（5 例）：谓词边界
  （from==now 含、to==now 排除、未来 from 排除）、复活行四读者全排除、
  复活行不占 subject_key（POST 201 而非 409）、PATCH/POST 忽略 validity
  且行仍可检索、keyed upsert 跳过复活行插新行。
- 更新 `test_memory.py::test_memory_extension_fields_round_trip`：旧
  断言钉死"客户端 validity 往返"，按 D-036 §6 改为"发送即忽略、读侧
  恒 null"（对齐 embedding 测试的 not-client-writable 模式）。
- 迁移：scratch 库 `alembic upgrade head` → 索引谓词含 `valid_to IS
  NULL`；`downgrade -1` 恢复旧谓词；再 upgrade 往返干净；
  `revision --autogenerate` 产出 `pass`（模型与库零漂移）。
- `agenthu-openapi` 重生：openapi.json −48 行（两请求 schema 的
  validity 字段），61 路径数不变；`check_contract_drift` 无漂移
  （客户端只镜像 MemoryRead，读侧未动）。
- ruff / pyright 0 错误；全量后端测试结果见 PR 描述（本地基线
  352 passed + 1 fixed → 全绿）。
- **流程注记（协调人 2026-10-05 记录在案）**：首头 165060d 远端 CI 红，
  根因是纯格式——`ruff format --check` 在新测试文件 :88/:138 换行排版
  上失败（46 秒即死、测试未跑）。本地交付前只跑了 `ruff check`（lint），
  与 CI 步骤不同形（ci.yml 另有 `ruff format --check .`）。修复 =
  `24d62f1`（纯格式，8 行）。教训：**交付前本地必须跑 CI 同形命令**
  （`ruff check .` 与 `ruff format --check .` 两条都要），远端非绿必须
  在交付报告中披露。

## 4. 对 E7 账面的影响

E7-4 断言"全部 live 行读者不读 valid_to 失效行、PATCH 不可写
valid_to"自本切片起对码成立（[E7](m5-e7-acceptance.md) §2 已在
D-036 轮同步修订，无需再改）；E7-3/E7-7 的删除-复活类断言仍待
P0-1 后续切片的删除图实现。
