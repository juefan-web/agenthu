# PlanItem 标题契约与联调合并

负责人：开发者 A（Backend/OpenAPI）与开发者 B（Zod/UI），先冻结接口再分别修改。

## 目标

今日计划显示任务标题，且 OpenAPI、客户端契约与实际响应保持一致；在集成分支完成 Study + Time 主链路验证。

## 输入

- `m0/backend-foundation` 的 `ClientPlanItem.title` 与 OpenAPI/快照。
- `feature/client-tauri-campus-adapter` 的 `PlanItemSchema`、今日计划 UI 和客户端测试。
- D-009 冻结契约与 `CLIENT_INTEGRATION_REVIEW.md`。

## 输出与负责范围

- A 确认 `title` 的非空、默认值和来源语义，更新 Backend 响应模型、OpenAPI 快照、fixture、测试及漂移检查基线；明确 Event `next_cursor` 当前回显行为是占位、废弃还是增量游标。
- B 在冻结结果后更新 Zod、fixture、计划 UI 和相关测试，显示标题而非 `task_id`。
- 集成负责人解决 `.gitignore`、`AGENT_CONTEXT/CURRENT_STATE.md` 的合并冲突，保留双方有效内容。

## 不负责

- 不借此扩展 Agent 规划算法或跨设备同步机制。
- 不在 B 分支单边添加 `title` 为必填字段，避免使旧 Backend 响应无法解析。

## 兼容和回滚

先保证 Backend 已部署 `title` 响应，再发布将 `title` 设为必填的客户端；如需旧 Backend 并存，应先约定可选字段及 UI 回退值，并同步 OpenAPI/Zod。回滚客户端或 Backend 时也按该顺序检查响应兼容性。

## 验收标准

- A/B 对同一份 OpenAPI/Zod 运行 `python -m backend.scripts.check_contract_drift --zod packages/contracts/src/index.ts` 无漂移。
- Backend 与客户端测试、类型检查、构建通过；今日计划列表显示正确标题。
- Windows 构建包在真实 Backend 上完成登录、采集、Event 同步、Task/Plan、确认计划、Focus 完成及断网重试；DevTools 无 CSP violation，拒绝 Event 不重复上传并可见原因。
- 集成分支解决冲突后再提交 PR；未完成实际构建包联调前不声明 main 的闭环验收通过。
