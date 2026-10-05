# M4 状态复核与 M5 规划交接（2026-10-05）

Status: **本轮只完成独立状态核验与规划初稿，未实施M5、未代签互审**。
成果入口：[规划指导](../TASKS/m5-planning-guidance.md)、
[双草任务](../TASKS/m5-phase0-prereq-docs.md)、
[A稿](../TASKS/m5-data-lifecycle-ops-contract.md)、
[B稿](../TASKS/m5-data-controls-grants-client-contract.md)、
[E7方案](../TASKS/m5-e7-acceptance.md)。

## 1. 独立核验与可证范围

git fetch origin --prune 后origin/main为
bf02eeb5906aa2732708ced8fe792ae41be96dd4。
[PR #66](https://github.com/juefan-web/agenthu/pull/66)状态MERGED，
head bd6668fc57f510a03e1cb00b208473c7db05ed2b，
mergeCommit为上述bf02eeb，mergedAt=2026-10-05T02:43:31Z
（北京时间10:43:31）。
收口SHA [CI](https://github.com/juefan-web/agenthu/actions/runs/37256514192)
与 [Client checks](https://github.com/juefan-web/agenthu/actions/runs/37256514201)
均success，非仅引用合并前PR绿。

已读取E6首跑归档、B核账与DECISIONS收口条目：
spec/执行态66af4d3、两轮六用例绿（1.9m/2.4m），
A十查rc=0、B账实相符；96审计、7任务、4条draft重排、
confirm请求6/结算4等差异有对账闭合。
**这些执行/SQL事实由归档佐证；本轮没有重跑E6或连接验收数据库。**
main的058c512是#65产品/墙钟修复复绿点；bf02eeb是#66正式收口提交，
二者不能混作“最终收口head”。
#50–#65排除未合#53共15merge；若只数#51起则14，不改历史报告原文。

## 2. 工作区与运营尾项

原工作区仍在feature/backend-request-proxy（f162569），有已有未跟踪文件；
本轮未切换/覆盖它。新托管worktree位于
C:/Users/惠普/.codex/worktrees/m5-planning/agenthu，
分支codex/m5-planning，从bf02eeb建立。
旧M4辅助草稿不能作为已冻结D-034/D-035替代品。

两项尾巴**仍未在本轮执行/验证**：

- A保留e6-logs原始目录，agenthu_e6 pg_dump到受控本地文件，
  验证dump可读/恢复后再停其uvicorn/arq/replay、撤compose。
  不把dump/未脱敏日志推到public仓库，不盲目删volume。
- B的agenthu-b-cursor占用已合docs/m4-closure-d030，
  下次由B自行检查本地改动后切回main/拉齐；本轮未动其工作区或强删分支。

这两项不否定M4已收口；也不能因协调报告已发指令就写成已执行。

## 3. 规划结论与下一步

优先级：删除/导出持久账本与并发屏障、Memory全链/源传播、
客户端owner隔离、grant真实作用域、trace/限流/恢复、许可与真实key发布门。
HNSW与SSE只做测量驱动评估，默认daily_budget=3暂保留。
新接口、期限、旧DELETE兼容、grant增量与E7出口全部是提案；
不预占Decision编号。

下一步A/B各修自己的初稿，逐字段互审（包括nullable/strip缺口），
对准确head批准，协调人裁定并登记，再按P0小切片开工。
本轮未通知/向A或B发送消息，没有人为批准或发布授权的推定。

## 4. 本轮开源对照（固定提交、只读研究）

2026-10-05用GitHub API取各仓库main SHA并读取如下原文件；
仅参考机制，**本轮没有复制源码或新增依赖**。

| 对象/来源 | 可借鉴实现 | 不可直接继承的保证 |
| --- | --- | --- |
| LangGraph 9a0394d88b2211f299dcd69df92db3480c69ee61，[PostgresSaver源码](https://github.com/langchain-ai/langgraph/blob/9a0394d88b2211f299dcd69df92db3480c69ee61/libs/checkpoint-postgres/langgraph/checkpoint/postgres/__init__.py)、[MIT许可](https://github.com/langchain-ai/langgraph/blob/9a0394d88b2211f299dcd69df92db3480c69ee61/LICENSE) | delete_thread显式删checkpoints、checkpoint_blobs、checkpoint_writes三表；提醒删除不能只删主记录 | thread_id不是Agenthu可信owner；不包含Event/Memory/对象/客户端副本。M4已有朴素runner，不为此引入LangGraph |
| Mem0 abb81c88e1f738a8117d8293530fbc31a5ef8fd9，[Memory源码](https://github.com/mem0ai/mem0/blob/abb81c88e1f738a8117d8293530fbc31a5ef8fd9/mem0/memory/main.py)、[Apache-2.0许可](https://github.com/mem0ai/mem0/blob/abb81c88e1f738a8117d8293530fbc31a5ef8fd9/LICENSE) | delete_all拒绝无user/agent/run作用域，反复list top_k=1000直到空，避免vector store默认分页漏删 | caller传user_id不是认证；repeated batch保护会break后返回成功，不能照搬成零残留证明；也不能视为Agenthu整个历史/审计/派生图已删除 |
| Hermes [仓库已有预研](2026-10-01-hermes-memory-prestudy.md) | 写入审批绑定目标内容、原文检索与稳定上下文前缀已有设计输入 | 本轮未重新验证其上游；本地文件/单用户假设、before/after内容审计与保留快照不适合直接作为多用户永久删除机制 |

取舍：复用现SQLAlchemy/Arq/ObjectStorage/租约/幂等，沿同图枚举所有存储；
OTel用标准SDK/instrumentation而非自写协议。后续如复制源码或接新包，
固定版本、保留license/NOTICE、核依赖许可并补隔离/失败测试。

## 5. 本轮验证

验证范围是文档链接、字段/状态/边界一致性、git diff --check、
已合M4远端状态/收口SHA CI。没有声称M5实现、E7或真机通过；
代码未变，不以重复运行全套产品测试代替尚不存在的E7证据。
