# AGENTS.md

## 1. 项目定位

本项目是面向清华学生的 **Personal AI / Student Life OS**。

核心目标：

> 持续获取用户学习与生活中的信息，形成长期可靠的个人记忆与当前状态，由 Agent 主动帮助用户理解、规划、执行和调整。

核心闭环：

```text
现实世界
→ Event
→ Memory
→ Current State
→ Agent
→ Plan / Act
→ 新 Event
```

当前主要业务领域：

* 📅 Time：时间、Todo、Deadline、Focus、自动排程
* 📚 Study：课程、资料、课堂回放、AI 学习、作业辅助
* 🏃 Exercise：运动记录、Performance、Well-being
* 🏠 Life：消费、缴费、预约、校园生活事务
* 📥 Inbox：微信、邮件、通知等信息流处理

`Memory`、`Agent`、`Chat`、`Review` 是贯穿全系统的能力，不应被理解成互相独立的业务模块。

---

# 2. 核心原则

## 2.1 Agent 是核心

Chat 只是入口之一。

Agent 应具备：

```text
Observe
→ Understand
→ Retrieve Context / Memory
→ Decide
→ Plan
→ Act
→ Observe Result
→ Update State / Memory
→ Re-plan
```

不要把系统设计成单纯：

```text
用户提问 → AI 回答 → 结束
```

---

## 2.2 用户不应该反复提供上下文

尽可能自动获得：

* 课程 / 作业 / 日程
* 信息流
* 文件 / 资料
* 运动
* 生活数据
* 历史行为

用户不应为了让 Agent 工作而重复告诉它已经存在的信息。

---

## 2.3 用户拥有最终控制权

操作必须有明确权限等级：

```text
Level 0：只读
Level 1：建议
Level 2：执行前确认
Level 3：用户明确授权后自动执行
```

高风险、不可逆、对外沟通的操作默认需要确认。

新增工具必须明确：

* 作用
* 输入 / 输出
* 使用的数据
* 执行动作
* 权限等级
* 失败处理

---

# 3. 数据架构

## 3.1 Event 是统一事实层

所有来源尽可能统一为 Event，例如：

* 消息收到
* 作业发布
* 作业开始 / 完成
* 课程开始
* Focus 开始 / 结束
* 骑行
* 消费
* 日程变化

Event 至少应有：

```text
id
type
timestamp
source
user
data
context（如适用）
```

业务逻辑尽量基于统一 Event，而不是直接依赖某个具体数据源。

---

## 3.2 Memory 不是 Vector DB 的简单替代品

建议分层：

```text
L0 原始 Event
→ L1 具体经历
→ L2 稳定事实 / 习惯
→ L3 个人模型
```

Memory 必须尽可能可追溯：

* 来源 Event / 文档
* 创建 / 更新时间
* 置信度
* 用户修正状态

错误 Memory 应可修改、降权或删除。

不要让未经验证的 LLM 总结直接成为永久事实。

---

## 3.3 Current State

Memory 描述长期的“我”。

Current State 描述现在的“我”：

* 当前时间
* 当前任务 / Context
* 当前课程
* 剩余工作量
* 可用时间
* 最近状态
* 当前目标

Agent 的即时决策应优先使用：

```text
Current State
+
Relevant Memory
+
Goals
```

而不是把全部历史数据塞进 Context。

---

## 3.4 Goals

系统应支持长期目标，例如：

* 学业
* 科研
* 运动
* 财务
* 其他个人目标

Agent 不应只按 Deadline 排序，也应考虑长期目标。

---

# 4. Agent 设计原则

## 4.1 主动性

Agent 不应只等待用户提问，也应在合适时主动：

* 提醒
* 发现风险
* 建议计划
* 提取任务
* 重新规划

但主动行为必须尊重用户权限和当前状态。

---

## 4.2 动态规划

计划不是一次生成后固定不变。

```text
Plan
→ Execute
→ Reality
→ Detect Deviation
→ Re-plan
```

任务实际耗时、未完成、突发事件都应影响后续计划。

---

## 4.3 重要建议要能解释“为什么”

对重要决策尽可能提供依据：

```text
建议
→ 原因
→ 相关 Event / 数据 / Memory
```

不要让关键决策变成无法解释的黑盒。

---

## 4.4 Context Switching

Agent 应识别用户当前 Context，例如：

```text
I2CS HW2
科研项目
运动
生活事务
```

切换 Context 时优先加载对应资料、任务和 Memory。

Context 是 Agent 内部能力，不要强行做成独立业务模块。

---

# 5. Study 特殊原则

Study 是第一阶段重点场景。

核心闭环：

```text
资料 / 录音
→ 课堂回放
→ AI 讲解
→ 作业辅助
→ 记录过程
→ Learning Memory
→ 下一次更懂用户
```

### 课堂回放

必须考虑：

* Audio
* Slides
* Transcript

三者时间轴同步，并支持互相跳转。

### AI 学习

回答优先基于：

* 当前资料
* 当前课程上下文
* Transcript / Lecture
* Learning Memory
* Personal Memory

目标不是简单“个性化语气”，而是根据用户已有知识和熟悉的表达方式解释新知识。

### Citation / Grounding

引用必须：

* 真实存在
* 可定位
* 能支持对应结论
* 尽量避免无依据引用

可引用：

* PPT / PDF 页码
* 文档区域
* Transcript
* Lecture 时间点

### 作业辅助

目标是辅助思考，而不是默认代做。

记录：

* 题目
* 开始 / 完成时间
* 答案多个版本
* AI Guidance 多轮过程
* 最终结果

学习过程数据可进入 Learning Memory。

---

# 6. 数据源与客户端

## 6.1 OneTHU

OneTHU 可以作为校园数据能力的参考来源，但：

> **本产品不应依赖用户打开 OneTHU。**

应通过独立的数据适配层接入校园数据。

Agent / 业务逻辑不得直接绑定具体校园 API。

---

## 6.2 Android / Windows

使用：

```text
Android ──┐
          ├── Backend
Windows ──┘
```

不要让两个客户端直接互相同步。

### Android

偏：

* 通知 / 信息流
* GPS
* 运动
* 手表
* 主动提醒

### Windows

偏：

* 学习
* 文件
* PPT / PDF
* 作业
* 桌面工作环境
* 悬浮辅助

两端共享：

* Event Schema
* API
* Memory
* Agent 接口
* 权限模型

---

## 6.3 Backend

Backend 是跨设备的统一事实来源，负责：

* 用户身份
* Event
* Memory
* Current State
* Tasks
* Knowledge
* Goals
* Agent State
* 同步

客户端不应各自维护一套独立业务逻辑。

---

# 7. 隐私

本项目可能处理：

* 微信 / 通知
* GPS
* 消费
* 课程
* 作业
* 录音
* 日程
* 生活轨迹
* Personal Memory

因此遵循：

> **最小化采集、最小化上传、明确授权。**

每类数据都应明确：

* 是否上传
* Agent 是否可访问
* 保存多久
* 如何删除

能本地处理的敏感原始数据，不应无必要上传云端。

---

# 8. 开发协作

## 8.1 Git

代码共享使用 Git。

```text
main
├── feature/xxx
├── fix/xxx
└── experiment/xxx
```

原则：

* 不长期直接开发 main
* 大功能使用独立分支
* PR 合并
* 合并前测试
* Commit 要清晰

---

## 8.2 任务边界

不要让两个 Agent 同时随意修改同一功能。

每个任务应明确：

```text
目标
输入
输出
负责范围
不负责范围
验收标准
```

Agent 不得无理由扩大任务范围。

---

# 9. Agent 持久化上下文

不要依赖共享完整 Chat History。

**代码靠 Git，共享知识靠仓库文件。**

建议：

```text
AGENT_CONTEXT/
├── PROJECT.md
├── ARCHITECTURE.md
├── CURRENT_STATE.md
├── DECISIONS.md
├── TASKS/
└── HANDOFF/
```

### PROJECT.md

回答：

> 我们在做什么？核心原则是什么？

### ARCHITECTURE.md

记录：

> 系统结构、数据流、模块边界。

### CURRENT_STATE.md

记录：

> 当前做到哪里、进行中什么、有什么阻塞。

### DECISIONS.md

记录：

> 为什么做出某个重要设计决定。

### TASKS/

记录：

> 单个任务的目标、范围和验收标准。

### HANDOFF/

记录：

> 上一个 Agent 做了什么、为什么、还剩什么、下一步是什么。

---

# 10. Agent 工作规范

开始中大型任务前：

```text
1. 读取 AGENTS.md
2. 读取 PROJECT.md
3. 读取 CURRENT_STATE.md
4. 读取 ARCHITECTURE.md
5. 搜索相关代码
6. 查看相关 DECISIONS / TASK
7. 明确任务边界
8. 再开始修改
```

完成任务后：

```text
1. 检查代码
2. 运行相关测试
3. 检查明显回归
4. 更新必要文档
5. 更新 CURRENT_STATE.md
6. 记录重要 DECISION
7. 写 HANDOFF
8. 创建清晰 commit
```

完成报告至少说明：

* 做了什么
* 改了什么
* 测试了什么
* 未完成什么
* 下一步是什么

不要只输出：

> Done.

---

# 11. 新增功能的判断标准

新增功能前先回答：

> 它是否增强了以下闭环？

```text
看到
→ 记住
→ 理解
→ 规划
→ 行动
→ 学习
```

如果只是“看起来很酷”，但与核心闭环关系弱，应谨慎加入。

---

# 12. 第一阶段优先级

优先建立一条完整闭环，而不是同时做完所有模块。

推荐：

### P0

* Event
* Backend
* Memory 基础架构
* Agent 基础框架
* Study + Time 最小闭环

### P1

* Inbox
* Android / Windows 同步
* 主动 Agent
* 动态重新规划
* Context Switching

### P2

* Exercise
* Life
* 更强 Memory

### P3

* Daily / Weekly / Monthly / Yearly Review

第一阶段最值得验证的闭环：

```text
上课
→ 录音 + PPT
→ 同步回放
→ AI 讲解
→ 做 HW
→ AI 辅助
→ 记录过程
→ Learning Memory
→ 下一次更懂用户
```

再连接 Time：

```text
HW
→ Deadline
→ Planning
→ Focus
→ 完成
→ 实际耗时
→ Memory
```

---

# 13. 最终原则

本项目不是：

> 五个功能模块 + 一个 Chat。

而是：

> **一个长期存在的 Personal Agent，通过多个领域的数据和工具了解用户、记住用户、理解当前状态，并主动帮助用户行动。**

任何新的代码、架构和产品功能，都应优先服务这一目标。
