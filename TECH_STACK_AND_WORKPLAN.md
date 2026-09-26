# 整体技术栈与双人开发计划

本文档是第一阶段的工程基线，服务于 `AGENTS.md` 中的 Personal Agent、Event、Memory、Current State 和 Study + Time 闭环。选型优先考虑两位开发者能够独立推进、共享清晰契约，并在较短时间内交付一条可验证的端到端流程。

## 1. 第一阶段目标

先完成一条可运行的最小闭环：

```text
课程资料 / 作业 / Deadline
    -> Event
    -> Task + Current State
    -> Agent 生成计划
    -> Focus 执行
    -> 记录实际结果
    -> Memory 更新
    -> 偏差触发重新规划
```

第一阶段不追求一次覆盖所有数据源。先让用户能够导入一门课程和一个作业，获得可解释的计划，完成一次 Focus，并看到学习过程被可靠记录。

## 2. 推荐技术栈

### 2.1 Backend 与领域层

| 层次 | 选型 | 约束与原因 |
| --- | --- | --- |
| 语言 | Python 3.12 | AI、数据处理和异步任务生态成熟，便于快速验证 Agent 闭环。 |
| API | FastAPI + Pydantic v2 | 以类型化请求/响应作为跨客户端契约，自动生成 OpenAPI。 |
| ORM / 迁移 | SQLAlchemy 2 + Alembic | 保持领域模型、查询和迁移可测试、可演进。 |
| 主数据库 | PostgreSQL 16 | 统一保存用户、Event、Task、Goal、Memory、Current State 和审计数据。 |
| 向量检索 | pgvector | 第一阶段直接使用 PostgreSQL，避免单独维护向量数据库；后续按规模再拆分。 |
| 异步任务 | Redis + Arq | 用于转写、嵌入、资料解析、提醒和重新规划；任务必须幂等并可重试。 |
| Agent 编排 | LangGraph，外层包一层项目自己的状态接口 | 将 Observe、Retrieve、Decide、Plan、Act、Observe Result 显式化，避免业务代码绑定单次聊天。 |
| 外部模型 | Provider adapter + OpenAI Responses API 作为第一实现 | 模型调用必须经过适配层，保存模型、提示版本、工具调用和引用信息。 |
| 文件存储 | S3 兼容对象存储（本地 MinIO，线上托管 S3） | 原始音频、PPT、PDF 和转写结果不塞进关系库。 |
| 认证 | OIDC/OAuth2 提供商 + Backend JWT 校验 | 客户端不自行实现密码系统；用户身份在 Backend 统一解析。 |

### 2.2 Client

| 平台 | 选型 | 第一阶段范围 |
| --- | --- | --- |
| Android / Windows | React + TypeScript + Vite + Tauri 2 + Rust | 共用 WebView 前端；Windows 优先承载资料、任务和 Focus，Android 复用同一套页面与契约。 |
| 远程状态 | TanStack Query | 统一管理 Backend Current State、Task、Plan 和 Focus 请求，页面不直接拼接请求。 |
| 本地状态 | Zustand | 管理登录、Focus、当前上下文和 UI 草稿；校园数据通过 `CampusAdapter` 暴露。 |
| API / 运行时契约 | OpenAPI 生成类型 + Zod | Backend 响应在客户端边界运行时校验，Event/Task/Plan/Focus 契约位于 `packages/contracts`。 |
| 本地缓存与队列 | SQLite（Tauri host） | 保存待同步 Event、同步游标和 Focus 草稿；Backend 仍是事实来源。 |
| 本地敏感数据 | Tauri Stronghold | Session/Cookie 与密钥进入 Stronghold；默认不保存校园密码，验证码只存在内存。 |
| 校园数据 | vendored `@onethu/core` + Tauri `CampusAdapter` | React 不直接导入 OneTHU；首期只接课程、作业、课表和校历。 |

### 2.3 工程与运行

- 本地环境：Docker Compose，包含 Backend、Worker、PostgreSQL、Redis、MinIO。
- 代码质量：Backend 使用 Ruff、Pyright、pytest；客户端使用 TypeScript、Vitest、Testing Library、Playwright 与 `cargo test`。
- 契约检查：提交时生成并校验 OpenAPI；关键 Event、权限和状态迁移有契约测试。
- CI：GitHub Actions 执行格式化、静态检查、单元测试、API 集成测试和 Tauri 构建检查。
- 观测：结构化日志、OpenTelemetry trace、Sentry 错误上报；日志默认脱敏，不记录原始聊天、音频和敏感位置数据。
- 部署：Backend API 与 Worker 使用容器；PostgreSQL、对象存储和 Redis 优先使用托管服务，先不引入 Kubernetes。

## 3. 系统边界与核心契约

### Backend 必须负责

- 用户身份、权限等级和审计记录。
- Event 的接收、去重、来源和时间戳。
- Task、Deadline、Goal、Current State 和 Memory 的持久化。
- Agent 状态机、工具调用、引用/grounding 和重新规划。
- 文件上传、解析任务、跨设备同步以及通知事件。

### Client 只负责

- 展示和编辑用户可见状态。
- 采集用户明确授权的数据。
- 本地缓存和断网期间的待同步队列。
- 调用 Backend API，不直接访问数据库、模型供应商或校园数据源。

### 第一版必须冻结的接口

1. 客户端上报 `Event`：`client_event_id`、`type`、`occurred_at`、`source`、`data`、`context`、`provenance`；Backend 注入 `user_id` 和服务端 ID。
2. `Task`：任务来源、截止时间、估计时长、状态、关联 Goal 和关联 Event。
3. `CurrentState`：当前时间、活动 Context、待办、可用时间、最近状态和版本号。
4. `Memory`：层级、内容、来源 Event/文档、置信度、创建/更新时间、用户修正状态。
5. `Plan`：依据、任务顺序、预计时段、权限等级、确认状态、执行结果和重规划原因。

接口变更必须先更新 schema、测试和迁移说明，再修改客户端或 Agent 行为。

## 4. 两位开发者的分工

### 开发者 A：Backend / Agent / 数据平台负责人

负责服务端事实来源和 Agent 执行边界：

- 建立 FastAPI 工程、PostgreSQL schema、Alembic 迁移、认证和权限中间件。
- 实现 Event、Task、Goal、Current State、Memory 的 CRUD 与版本/审计信息。
- 实现导入适配层接口；第一版只接收手动表单、Markdown/PDF 元数据和本地文件上传。
- 建立 Redis/Arq Worker、对象存储接口和幂等重试机制。
- 实现 Agent 状态机、模型 Provider adapter、工具注册、引用记录和权限拦截。
- 提供 OpenAPI、测试夹具、Docker Compose、CI 和服务端观测。

开发者 A 不负责页面视觉和客户端本地状态；客户端需要的数据必须通过契约交付。

### 开发者 B：Client / Study + Time / Campus Adapter 负责人

负责用户从资料到 Focus 的完整使用路径：

- 建立 React/Tauri Android/Windows 工程、导航、认证流程、Zustand/TanStack Query 状态层和 OpenAPI 客户端。
- vendor 固定版本的 OneTHU core，建立 Tauri transport、CampusAdapter、2FA/会话恢复和 Event 映射；React 页面不得直接调用校园接口。
- 实现课程/资料、作业与 Deadline 导入页面，以及 Task/Current State 展示。
- 实现计划确认、Focus 开始/暂停/完成、实际耗时和偏差反馈。
- 实现 Agent 建议的原因、引用位置、权限确认和失败状态展示。
- 实现本地草稿、SQLite 离线待同步 Event、冲突提示和 Stronghold 敏感数据存储。
- 编写 Vitest/Testing Library/Playwright 测试，并用 OneTHU/API fixtures 验证端到端用户路径。

开发者 B 不直接修改数据库 schema 或 Agent 内部决策；需要新字段时提交契约变更请求给开发者 A。

### 两人共同负责

- 每周一起评审 Event、Memory、Current State 和权限契约。
- 任何跨边界变更先写短 ADR，明确兼容策略和回滚方式。
- 至少共同演练一次端到端闭环和一次故障恢复。
- 共同 review 涉及隐私、不可逆操作、数据删除和外部沟通的代码。

## 5. 里程碑与交付顺序

### M0：工程基线（1 周）

- A：Backend 骨架、数据库迁移、健康检查、CI、Docker Compose。
- B：React/Tauri 骨架、认证壳、导航、Zod 契约和测试框架。
- 共同：冻结核心 schema、权限等级和错误格式。

验收：本地一条命令启动服务；CI 通过；客户端能登录、恢复校园会话并读取空的 Current State。

### M1：Event / Task / Current State（1-2 周）

- A：Event 接收去重、Task/Deadline API、Current State 投影。
- B：课程/作业录入、任务列表、当前状态页和离线草稿。

验收：录入一次作业后，两端都能看到同一 Task 和 Deadline，重复提交不会产生重复 Event。

### M2：Plan / Focus 垂直切片（1-2 周）

- A：计划生成 API、权限确认、Focus 事件、实际时长和重规划接口。
- B：计划确认、Focus 控件、完成/偏差反馈和错误状态。

验收：从 Deadline 生成计划，用户确认后执行一次 Focus，完成结果能触发新的 Current State。

### M3：Memory / Grounding（1-2 周）

- A：资料索引、pgvector 检索、Memory 来源/置信度/修正状态、引用返回。
- B：AI 讲解页、引用跳转、用户纠正 Memory 和删除入口。

验收：回答只使用已上传资料和可追溯 Memory；用户能看到引用并修正错误记忆。

### M4：Alpha Hardening（1 周）

- 两人共同：权限回归、数据删除、断网恢复、重试/幂等、性能和隐私检查。

验收：完成一套代表性课程 -> 作业 -> 计划 -> Focus -> Memory 测试夹具，并有可回滚发布说明。

## 6. 协作规则与 Definition of Done

- 每个任务必须写明目标、输入、输出、负责范围、不负责范围和可测试验收标准。
- 代码放在 `feature/*`、`fix/*` 或 `experiment/*` 分支；`main` 只通过 PR 更新。
- PR 至少需要另一位开发者 review；跨领域 PR 必须附 schema/API 变更说明。
- 完成前运行对应测试、静态检查和安全/隐私检查；失败时记录原因，不得只写“已完成”。
- 变更数据结构时同步迁移、fixtures、OpenAPI 和客户端生成代码。
- 每个里程碑结束更新 `CURRENT_STATE.md`、相关 ADR 和 `HANDOFF/`，让下一次工作不依赖聊天记录。

## 7. 当前明确不做的事情

- 不在第一阶段引入 Kafka、Kubernetes 或独立向量数据库。
- 不让 Android 与 Windows 直接互相同步。
- 不让 React 页面直接调用模型、校园 API 或数据库；校园请求只能经 Tauri `CampusAdapter`。
- 不把未经验证的模型总结直接写成永久 Memory。
- 不在没有权限确认的情况下执行对外沟通、删除或其他不可逆动作。
