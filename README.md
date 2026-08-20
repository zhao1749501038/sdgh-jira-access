# SDGH Jira Access

一个供 Codex 使用的简单 Jira Skill。Skill 内置 Python 脚本，直接调用自托管 Jira Server 或 Data Center REST API，支持查询、详情、创建、修改、评论、指派和状态流转，不需要安装 MCP 服务。

## 一句话安装并配置

将下面整句话发给 Codex，并把 Jira 地址替换成公司实际地址：

```text
请使用 $skill-installer 安装并继续配置这个 SDGH Jira Access Skill，不要在 Skill 安装完成后停止；Jira 地址为 <公司 Jira 地址>：https://github.com/zhao1749501038/sdgh-jira-access/tree/main/skills/sdgh-jira-access
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

- 仓库不包含 Jira 地址、项目编号、自定义字段映射或个人凭据。
- 所有写操作都要求显式确认参数，缺少时脚本会在本地拒绝执行。
- 当前不支持删除工单和上传附件。

## 测试

```bash
python3 -m unittest discover -s skills/sdgh-jira-access/tests -v
python3 ~/.codex/skills/.system/skill-creator/scripts/quick_validate.py skills/sdgh-jira-access
```
