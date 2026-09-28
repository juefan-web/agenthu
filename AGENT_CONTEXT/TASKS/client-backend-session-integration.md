# 客户端 Backend 会话与闭环联调

负责人：开发者 B  
目标：将 React/Tauri 客户端接入 Backend Bearer JWT，并完成 Windows 首轮真实联调。

## 输入

- D-018 Bearer JWT 决策
- 开发者 A 的认证与 API fixture
- 现有 `BackendClient`、Tauri Stronghold 和校园 `CampusAdapter`

## 输出

- 独立的 Backend 登录/注册/Token/Me 会话状态，不与校园会话混用。
- 使用 Stronghold 保存 Token，请求统一附加 `Authorization: Bearer`，登出和 401/过期时清除会话。
- 完成 Event 上传、Current State、Task、Today Plan、确认计划、Focus 的客户端联调。
- 增加登录、401、重启恢复、断网重试、重复同步和 Focus 完成测试。

## 不负责

- 不修改 Backend 数据库、JWT 签发规则或 Agent 决策。
- 不把校园账号密码或 Cookie 上传到 Backend。

## 验收标准

- 配置 `VITE_BACKEND_URL` 后客户端不再因缺少 Bearer Token 收到预期外的 401。
- 校园会话和 Backend 会话在 UI 中分别显示状态。
- Windows 构建包完成一次：校园登录/2FA -> 采集 -> Event 同步 -> Task/Plan -> Focus -> 结果同步。
- 失败路径可恢复，敏感凭据不进入日志、Event 或 Backend 请求体。

