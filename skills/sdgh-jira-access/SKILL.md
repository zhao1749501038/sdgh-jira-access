---
name: sdgh-jira-access
description: >-
  通过 Skill 内置脚本直接调用自托管 Jira Server 或 Data Center REST API，使用当前用户身份查询、读取、创建、修改、评论、指派和流转工单。用户提到 Jira 单号、我负责的 Jira、创建 Jira、修改字段或状态时使用。不依赖 MCP、Web Access、浏览器自动化或 Computer Use。
---

# SDGH-jira-access

通过 `scripts/jira.py` 直接调用 Jira REST API，默认连接 `https://21tb-jira.21tb.com`。这个 Skill 自带运行代码，不安装 MCP 服务。

## Python 命令

运行脚本前由 AI 自动探测本机可用的 Python 3 命令。Windows 依次尝试 `py -3`、`python`，macOS 依次尝试 `python3`、`python`，并确认版本为 Python 3。后续命令中的 `<Python命令>` 代表探测成功的命令。不要让用户填写 Python 路径，也不要写死绝对路径。

## 身份和配置

首次使用或身份存疑时运行：

```bash
<Python命令> scripts/jira.py whoami
```

尚未配置时，读取 [references/安装与分享.md](references/安装与分享.md)。用户明确要求安装并配置本 Skill 时，可连续完成安装和身份配置；优先由本人在 Windows 或 macOS 系统凭据窗口输入。系统窗口不可用时自动切换到终端输入，密码保持隐藏，不能要求用户把密码发送到聊天。

`whoami` 返回的用户不是当前使用者时停止写入。Windows 密码由当前用户的 DPAPI 加密后保存，macOS 密码保存在本人钥匙串；明文密码不写入 Skill、Git、配置文件、命令行或聊天。

## 查询

- 本人负责：`<Python命令> scripts/jira.py search --jql 'assignee = currentUser() ORDER BY updated DESC'`
- 本人创建：`<Python命令> scripts/jira.py search --jql 'reporter = currentUser() ORDER BY updated DESC'`
- 工单详情：`<Python命令> scripts/jira.py get DEMO-1234`
- 可见项目：`<Python命令> scripts/jira.py projects`

保留脚本返回的真实 Jira URL。用 Jira 内容生成其他产物时，以实时返回为准。

## 创建

1. 查询字段：`create-fields --project <项目> --issue-type <类型>`。
2. 使用 `prepare-create` 组装字段并检查必填项。
3. `ready=false` 时补齐字段；用户只要草稿时停在预检结果。
4. 向用户展示准确创建内容并取得确认后，使用相同参数执行 `create`，末尾增加 `--confirm`。
5. 核对返回的 `verified_issue` 和真实 URL。

不要猜测项目类型、自定义字段 ID、枚举值或必填项。实时字段元数据优先。

## 修改、评论和状态

- 修改前运行 `edit-fields <单号>`，确认准确变化后执行 `update <单号> --fields-json '<JSON>' --confirm`。
- 评论确认后执行 `comment <单号> --body '<内容>' --confirm`。
- 指派确认后执行 `assign <单号> --username <Jira登录名> --confirm`。
- 状态变化先运行 `transitions <单号>`，只能选择实时返回的流转；确认后执行 `transition <单号> --target <状态或流转名> --confirm`。

所有写操作都由脚本再次读取 Jira 并返回实际结果。批量写入时逐张执行；单张失败不能推断其他工单成功。

## 能力边界

- 不使用任何 MCP 工具。
- 不因 API 报错而改用 Web Access、浏览器或 Computer Use。
- 当前不提供删除和附件上传。需要时先讨论扩展，不从网页绕过。
