# SDGH-jira-access

一个供 Codex 使用的简单 Jira Skill。Skill 默认连接 `https://21tb-jira.21tb.com`，通过内置 Python 脚本直接调用 Jira REST API，支持查询、详情、创建、修改、评论、指派和状态流转，不需要安装 MCP 服务。

## 一句话安装并配置

连接公司 VPN 后，将下面整句话发给 Codex：

```text
请使用 $skill-installer 安装并继续配置这个 SDGH-jira-access Skill，不要在 Skill 安装完成后停止：https://github.com/zhao1749501038/sdgh-jira-access/tree/main/skills/sdgh-jira-access
```

Codex 会安装 Skill，自动识别电脑上可用的 Python 3 命令，并优先通过 Windows 或 macOS 系统凭据窗口询问本人 Jira 用户名和密码。系统窗口无法启动时会自动切换到终端输入，密码仍然隐藏。用户不需要填写 Python 路径，也不需要把密码发送到聊天。

## 使用条件

- Windows 10/11 或 macOS
- 已安装 Python 3；由 Codex 自动探测可用命令，不要求用户提供安装路径
- 能访问目标 Jira 的公司网络或 VPN
- 本人有效的 Jira 账号

## 支持能力

- 查询本人负责或本人创建的 Jira
- 读取工单详情和评论
- 实时读取项目、问题类型和字段元数据
- 创建前预检必填字段
- 创建和修改工单
- 添加评论、修改负责人、流转状态
- 写操作后回读实际结果

## 安全说明

- 仓库包含公司 Jira 基础地址，不包含账号、密码、Token、项目编号或自定义字段映射。
- Windows 由 Python 直接调用当前用户的 DPAPI 加密密码，不依赖 PowerShell 完成加密；macOS 密码保存在本人钥匙串。配置文件不保存明文密码。
- 所有写操作都要求显式确认参数，缺少时脚本会在本地拒绝执行。
- 当前不支持删除工单和上传附件。

## 测试

维护者测试时同样先自动探测本机可用的 Python 3 命令，再运行单元测试和 Skill 结构校验，不依赖固定解释器路径。
