# 2026-09-30 E 组首跑报告（e2e 套件 @ main `65942ee`）

结论：**E 组首跑全绿——3 passed (2.2m)**。「M2 起验收工具化」正式解锁。

## 运行口径

- 构建包：main `65942ee`（client + Rust 重建）；Backend 8000 独立运行（主库迁移至 head `b1d4a7c90e12`）。
- 命令：`AGENTHU_APP_EXE / AGENTHU_TEST_USERNAME / AGENTHU_TEST_PASSWORD / AGENTHU_TEST_BACKEND_URL / AGENTHU_TEST_BACKEND_EMAIL / AGENTHU_TEST_BACKEND_PASSWORD` + `pnpm --filter @agenthu/desktop test:e2e`（README 口径）。
- 人工介入：1 个验证码（企业微信，勾选信任设备后单轮完成，提交 3955ms）——与计划「动态方式后预计 1 个」一致。

## 结果

| 用例 | 耗时 | 结果 |
| --- | --- | --- |
| E1 应用启动并渲染外壳与校园登录表单 | 377ms | ✅ |
| E2 登录进入 2FA 并按凭据完成主链（重启→登录→2FA→采集→同步归零→专注入口） | 2.1m（含人工验证码等待） | ✅ |
| E3 派生任务出现且截止时间无偏移（徽标行/非 UUID/绝对时刻配对/limit=200） | 2.0s | ✅ |

E3 亮点确认：断言按 A review 修订为**绝对时刻配对**（任务 `due_at` 时刻命中作业事件 `data.deadline`，时区无关），历史 ±8h naive bug 在此判据下必不命中；limit=200 已吸收 round-5 L2 短期口径。

## 首遍跑出的两个 spec 问题（已复跑验证，供 B 修订）

1. **E1 视图假设**：E1 断言「今天」标题可见，但套件启动时旧实例可能停在任务视图（round-5 人工组遗留视图态），首遍 E1 超时失败。建议：E1 先导航回「今天」或对标题断言放宽为「任一主视图标题」。
2. **E2 选择器歧义**：重启后的新实例若 Backend Token 恢复失败（本次根因：套件启动与我的 Backend 重启时序竞态；Backend 稳定后复跑未再出现），Backend 登录表单与校园表单同屏，`getByLabel('密码')` 触发 strict-mode 双匹配。建议：校园字段用 `getByLabel('密码', { exact: true })`（或 role+name 精确匹配），Backend 字段用全名。

两处均为 spec 健壮性修订，不阻塞首跑结论（复跑已全绿）；建议 B 以小 PR 落地，随 M2 常规工具化使用。

## 运行备注

- E2 重启后的实例由套件拉起并保持运行（README 口径），campus-debug 开关在新实例 localStorage 生效。
- 本轮 console 监听未跨重启重挂，E 组运行期 CSP 未单独采样——同构建同配置，CSP 结论沿用 round-5 人工组（0 violation）。
- E2 自动重启 + E3 直连 API 的组合把 round-5 人工 B3/B4 判据完整沉淀为可重复断言。

## 收束状态

main `65942ee`：M0 集成 + M1-1 全链（round-5 验收通过）+ 全部跟进项 + **E 组首跑通过**。在途 PR：0。**M2 起验收工具化正式解锁**；下一轮验收建议口径：e2e 套件先跑（E1–E3），人工组聚焦故障注入与新增功能。
