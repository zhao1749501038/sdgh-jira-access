# SDGH-jira-access

一个供 Codex 使用的简单 Jira Skill。Skill 默认连接 `https://21tb-jira.21tb.com`，通过内置 Python 脚本直接调用 Jira REST API，支持查询、详情、创建、修改、评论、指派和状态流转，不需要安装 MCP 服务。

## 一句话安装并配置

连接公司 VPN 后，将下面整句话发给 Codex：

```text
请使用 $skill-installer 安装并继续配置这个 SDGH-jira-access Skill，不要在 Skill 安装完成后停止：https://github.com/zhao1749501038/sdgh-jira-access/tree/main/skills/sdgh-jira-access
```

Codex 会安装 Skill，并通过 macOS 系统弹窗询问本人 Jira 用户名和密码。密码框为隐藏输入，密码只保存到本人 macOS 钥匙串，不进入聊天、Skill 或 Git 仓库。

## 使用条件

- macOS
- Python 3
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
- 所有写操作都要求显式确认参数，缺少时脚本会在本地拒绝执行。
- 当前不支持删除工单和上传附件。

## 测试

```bash
python3 -m unittest discover -s skills/sdgh-jira-access/tests -v
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/sdgh-jira-access
```
