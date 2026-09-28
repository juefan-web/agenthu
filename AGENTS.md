# AGENTS.md

本文件是仓库级工程规范，适用于开发者和 Agent。它定义产品方向、不可破坏的系统边界、任务协作方式和完成标准。具体技术选型与两人分工见 [`TECH_STACK_AND_WORKPLAN.md`](TECH_STACK_AND_WORKPLAN.md)。

## 1. 产品方向

本项目是面向清华学生的 Personal AI / Student Life OS。目标是持续获取学习与生活信息，形成可追溯的个人记忆和当前状态，由 Agent 主动帮助用户理解、规划、执行和调整。

核心闭环：

```text
现实世界 -> Event -> Memory / Current State -> Agent -> Plan / Act
          -> 结果 Event -> 更新状态与记忆 -> Re-plan
```

主要领域包括 Time、Study、Exercise、Life 和 Inbox。`Event`、`Memory`、`Current State`、`Agent`、`Chat`、`Review` 是跨领域能力，不应被拆成互相孤立的产品。

第一阶段只优先验证一条 Study + Time 垂直闭环：

```text
课程资料 / 作业 / Deadline -> 计划 -> Focus -> 结果 -> Learning Memory
```

新增功能必须说明它如何增强“看到 -> 记住 -> 理解 -> 规划 -> 行动 -> 学习”中的至少一个环节；只有展示效果、无法服务闭环的功能应延后。

## 2. 不可破坏的系统不变量

### 2.1 Agent 与上下文

Agent 的工作流应显式包含：

```text
Observe -> Understand -> Retrieve -> Decide -> Plan -> Act
-> Observe Result -> Update State / Memory -> Re-plan
```

Chat 只是入口之一。Agent 不应只回答问题后结束，也不应要求用户重复提供系统已经拥有的上下文。即时决策优先使用：

```text
Current State + Relevant Memory + Goals
```

计划必须能吸收实际耗时、未完成任务和突发事件，并在偏差后重新规划。重要建议应给出原因以及相关 Event、数据、Memory 或 Goal。

### 2.2 统一事实层

Backend 是跨设备的事实来源，负责身份、权限、Event、Task、Goal、Memory、Current State、Agent State、Knowledge 和同步。Android 与 Windows 不直接互相同步，客户端也不得各自维护一套业务逻辑。

所有外部来源先转换成统一 Event。客户端上报的 Event envelope 至少包含：

```text
client_event_id, type, occurred_at, source, data, context, provenance
```

`provenance` 记录 connector、connector_version、upstream_id、semantic_version 和 fetched_at。Backend 接收时根据认证上下文写入可信 `user_id`，并生成服务端 Event ID；客户端不得自行提交可信用户身份。

业务逻辑依赖 Event 契约和适配层，不直接绑定 OneTHU、微信、邮件或其他具体供应商 API。OneTHU 可以作为数据能力参考，但产品不能要求用户打开它才能工作。

### 2.3 Memory 与 Current State

Memory 不是向量数据库的别名，建议分层：

```text
L0 原始 Event -> L1 具体经历 -> L2 稳定事实 / 习惯 -> L3 个人模型
```

每条 Memory 尽可能记录来源 Event 或文档、创建/更新时间、置信度和用户修正状态。错误 Memory 必须可修改、降权或删除，未经验证的模型总结不能直接成为永久事实。

Memory 描述长期的“我”；Current State 描述现在的“我”，包括当前时间、Context、课程、任务、剩余工作量、可用时间、最近状态和目标。二者都应有版本或更新时间，便于同步、审计和重新计算。

## 3. 权限、隐私与可解释性

每个工具和自动化动作必须写清作用、输入、输出、使用的数据、执行动作、权限等级和失败处理。权限等级固定为：

```text
Level 0：只读
Level 1：建议
Level 2：执行前确认
Level 3：用户明确授权后自动执行
```

高风险、不可逆、删除数据、对外沟通和代表用户做决定的操作，默认至少需要 Level 2 确认。工具调用、确认结果、失败和重试都应可审计。

本项目可能处理通知、GPS、消费、课程、作业、录音、日程和 Personal Memory。每类数据在接入前都要明确：是否上传、谁可以访问、保存多久、如何删除。遵循最小化采集和最小化上传；能在本地处理的敏感原始数据，不无必要上传云端。日志、错误报告和测试 fixtures 必须脱敏。

Study 场景中，AI 回答优先基于当前资料、课程上下文、Transcript、Learning Memory 和 Personal Memory。引用必须真实存在、可定位并支持结论；可以引用 PPT/PDF 页码、文档区域、Transcript 或 Lecture 时间点。作业辅助默认帮助理解和思考，不默认代做，并记录题目、过程、指导轮次和结果版本。

## 4. 客户端与架构边界

```text
Android ──┐
          ├── Backend ── PostgreSQL / Object Storage / Worker / Model Providers
Windows ──┘
```

- Android 偏通知、信息流、采集、GPS、运动和主动提醒。
- Windows 偏资料、PPT/PDF、作业、Focus 和桌面工作环境。
- 两端共享 Event Schema、API、Memory、Agent 接口和权限模型。
- React 页面不得直接访问数据库、模型供应商或校园 API；校园数据必须经过受控的 Tauri `CampusAdapter`，转换为统一 Event 后交给 Backend。
- Tauri 原生 transport/适配层是本地数据边界，不是跨设备事实源；Backend 仍负责身份、权限、Event、Task、Memory、Current State 和同步。
- 跨客户端的数据一致性由 Backend 保证；客户端只负责展示、明确授权的采集、本地缓存和待同步队列。

第一阶段的详细技术栈、接口字段、里程碑和开发者 A/B 的负责范围以 `TECH_STACK_AND_WORKPLAN.md` 为准；发生冲突时，先记录决策再修改依赖方。GOALS.md 是产品构想参考，不是仓库规范。

## 5. 开发协作

### 5.1 Git 与分支

```text
main
├── feature/<short-name>
├── fix/<short-name>
└── experiment/<short-name>
```

- `main` 应保持可运行；产品代码和大功能使用独立分支并通过 PR 合并。
- 经明确授权的文档维护可以直接提交 `main`；仍需清晰 commit 和验证结果。
- Commit 使用清晰的动词开头，例如 `Add assignment event schema`、`Fix plan rollover`。
- 不在同一任务中混入无关重构；变更数据契约时同步迁移、测试、OpenAPI 和客户端生成代码。

### 5.2 任务边界

每个任务开始前写清：

```text
目标
输入
输出
负责范围
不负责范围
验收标准
```

不要让两个开发者同时随意修改同一功能。跨 Backend、Agent、Client 的改动先冻结接口，再并行实现；接口变更要说明兼容策略和回滚方式。

## 6. Agent 持久化上下文

代码靠 Git，共享知识靠仓库文件，不依赖完整 Chat History。建议维护：

```text
AGENT_CONTEXT/
├── PROJECT.md        # 项目目标、范围、核心原则
├── ARCHITECTURE.md   # 系统结构、数据流、模块边界
├── CURRENT_STATE.md  # 当前进度、进行中任务、阻塞
├── DECISIONS.md      # 重要技术决策及原因
├── TASKS/            # 任务目标、范围、验收标准
└── HANDOFF/          # 跨会话交接记录
```

没有必要为了形式创建空文件；只有在对应信息出现时才更新。文档必须写事实、决策和下一步，不写无法验证的愿望。

## 7. Agent 工作规范

### 开始中大型任务前

1. 读取 `AGENTS.md`、`PROJECT.md`、`CURRENT_STATE.md` 和 `ARCHITECTURE.md`（存在时）。
2. 搜索相关代码、测试、Decision 和 Task，确认现有边界。
3. 写明任务边界、权限影响、数据来源和验收标准。
4. 先复用现有模式；只有能减少真实复杂度时才增加抽象。

### 修改过程中

1. 保持 Event、Memory、Current State、Agent State 的职责清晰。
2. 对外部调用设置超时、重试上限、幂等键和可观测记录。
3. 对用户数据、权限和不可逆操作优先做失败路径和回滚设计。
4. 跨边界变更同步更新 schema、迁移、fixtures、文档和调用方。

### 完成任务前

1. 检查代码和明显回归，运行相关测试、静态检查和构建检查。
2. 更新必要文档、`CURRENT_STATE.md`、Decision 和 Handoff。
3. 检查隐私、权限、来源引用、错误处理、幂等和删除路径。
4. 创建清晰 commit，并在报告中说明：做了什么、改了什么、测试了什么、未完成什么、下一步是什么。

## 8. 第一阶段优先级

- **P0**：Event、Backend、Memory 基础架构、Agent 基础框架、Study + Time 最小闭环。
- **P1**：Inbox、Android/Windows 同步、主动 Agent、动态重新规划、Context Switching。
- **P2**：Exercise、Life、更强的 Memory 能力。
- **P3**：Daily / Weekly / Monthly / Yearly Review。

第一阶段的验收重点是：用户导入课程和作业，系统记录 Event 和 Deadline，生成可解释且需要正确授权的计划，完成一次 Focus，记录实际耗时，发现偏差后重新规划，并将有来源的学习结果写入可修正的 Learning Memory。

## 9. 最终判断

本项目不是“若干功能模块加一个 Chat”，而是一个长期存在的 Personal Agent，通过多个领域的数据和工具了解用户、记住用户、理解当前状态，并在用户控制权范围内帮助用户行动。任何新的代码、架构和产品功能都应优先服务这个目标。
