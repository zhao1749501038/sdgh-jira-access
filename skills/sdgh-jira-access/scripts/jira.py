#!/usr/bin/env python3
"""Direct Jira Server/Data Center REST API CLI for the sdgh-jira-access Skill."""

import argparse
import base64
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request


DEFAULT_CONFIG = Path.home() / ".config" / "sdgh-jira-access" / "config.json"
ISSUE_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*-\d+$", re.IGNORECASE)


class JiraError(Exception):
    pass


def dump(value):
    return json.dumps(value, ensure_ascii=False, indent=2)


def issue_key(value):
    key = str(value or "").strip().upper()
    if not ISSUE_KEY_RE.fullmatch(key):
        raise JiraError(f"Jira 编号格式不正确：{value}")
    return key


def simple_value(value):
    if isinstance(value, list):
        return [simple_value(item) for item in value]
    if not isinstance(value, dict):
        return value
    if "displayName" in value:
        return {
            "username": value.get("name") or value.get("key"),
            "display_name": value.get("displayName"),
        }
    for key in ("value", "name", "key", "id"):
        if value.get(key) is not None:
            return value.get(key)
    return {
        key: simple_value(item)
        for key, item in value.items()
        if key not in ("self", "avatarUrls", "iconUrl")
    }


def user_name(user):
    return (user or {}).get("displayName") or (user or {}).get("name")


def simplify_issue(issue, base_url, detail=False):
    fields = (issue or {}).get("fields", {})
    result = {
        "key": (issue or {}).get("key"),
        "summary": fields.get("summary"),
        "type": (fields.get("issuetype") or {}).get("name"),
        "status": (fields.get("status") or {}).get("name"),
        "priority": (fields.get("priority") or {}).get("name"),
        "assignee": user_name(fields.get("assignee")),
        "reporter": user_name(fields.get("reporter")),
        "updated": fields.get("updated"),
    }
    if detail:
        result.update({
            "description": fields.get("description"),
            "created": fields.get("created"),
            "due_date": fields.get("duedate"),
            "labels": fields.get("labels"),
            "components": [item.get("name") for item in fields.get("components") or []],
            "fix_versions": [item.get("name") for item in fields.get("fixVersions") or []],
        })
        comments = ((fields.get("comment") or {}).get("comments") or [])
        result["comments"] = [
            {
                "id": item.get("id"),
                "author": user_name(item.get("author")),
                "created": item.get("created"),
                "updated": item.get("updated"),
                "body": item.get("body"),
            }
            for item in comments
        ]
        names = (issue or {}).get("names") or {}
        result["custom_fields"] = {
            field_id: {"name": names.get(field_id, field_id), "value": simple_value(value)}
            for field_id, value in fields.items()
            if field_id.startswith("customfield_") and value not in (None, "", [])
        }
    result["url"] = f"{base_url}/browse/{result['key']}"
    return result


def read_config(path=None):
    config_path = Path(path or os.environ.get("JIRA_API_CONFIG") or DEFAULT_CONFIG)
    data = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise JiraError(f"无法读取配置文件 {config_path}：{exc}") from exc
    mapping = {
        "base_url": "JIRA_BASE_URL",
        "username": "JIRA_USERNAME",
        "password": "JIRA_PASSWORD",
        "token": "JIRA_TOKEN",
        "keychain_service": "JIRA_KEYCHAIN_SERVICE",
        "ca_bundle": "JIRA_CA_BUNDLE",
    }
    for key, env_name in mapping.items():
        if os.environ.get(env_name):
            data[key] = os.environ[env_name]
    if os.environ.get("JIRA_SSL_VERIFY"):
        data["ssl_verify"] = os.environ["JIRA_SSL_VERIFY"].lower() != "false"
    return data, config_path


class JiraClient:
    def __init__(self, base_url, username="", password="", token="",
                 keychain_service="", ca_bundle="", ssl_verify=True, timeout=30):
        self.base_url = str(base_url or "").rstrip("/")
        self.username = username or ""
        self.password = password or ""
        self.token = token or ""
        self.keychain_service = keychain_service or ""
        self.timeout = max(1, min(int(timeout), 300))
        self.ssl_context = (
            ssl.create_default_context(cafile=ca_bundle or None)
            if ssl_verify else ssl._create_unverified_context()
        )
        if not self.base_url:
            raise JiraError("尚未配置 Jira 地址，请先运行 setup")

    @classmethod
    def from_config(cls, path=None):
        data, _ = read_config(path)
        return cls(
            data.get("base_url"),
            username=data.get("username", ""),
            password=data.get("password", ""),
            token=data.get("token", ""),
            keychain_service=data.get("keychain_service", ""),
            ca_bundle=data.get("ca_bundle", ""),
            ssl_verify=data.get("ssl_verify", True),
            timeout=data.get("timeout", 30),
        )

    def resolved_password(self):
        if self.password:
            return self.password
        if not self.keychain_service or not self.username:
            return ""
        try:
            result = subprocess.run(
                [
                    "/usr/bin/security", "find-generic-password",
                    "-s", self.keychain_service, "-a", self.username, "-w",
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise JiraError("无法从 macOS 钥匙串读取 Jira 密码") from exc
        return result.stdout.rstrip("\r\n")

    def auth_header(self):
        if self.token:
            return f"Bearer {self.token}"
        password = self.resolved_password()
        if not self.username or not password:
            raise JiraError("尚未配置 Jira 身份，请先运行 setup")
        encoded = base64.b64encode(f"{self.username}:{password}".encode()).decode()
        return f"Basic {encoded}"

    def request(self, method, path, body=None, params=None):
        url = f"{self.base_url}/rest/api/2{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(url, data=data, method=method)
        request.add_header("Authorization", self.auth_header())
        request.add_header("Content-Type", "application/json")
        request.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(
                request, timeout=self.timeout, context=self.ssl_context
            ) as response:
                text = response.read().decode("utf-8")
                return json.loads(text) if text.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = payload.get("errorMessages") or payload.get("errors") or payload
            except (ValueError, UnicodeDecodeError):
                detail = exc.reason
            raise JiraError(f"Jira API 返回 {exc.code}：{detail}") from exc
        except urllib.error.URLError as exc:
            raise JiraError(
                f"无法连接 Jira {self.base_url}，请检查公司网络或 VPN：{exc.reason}"
            ) from exc


def whoami(client):
    user = client.request("GET", "/myself")
    return {
        "username": user.get("name") or user.get("key"),
        "display_name": user.get("displayName"),
        "email": user.get("emailAddress"),
        "active": user.get("active"),
    }


def projects(client):
    return [
        {"id": item.get("id"), "key": item.get("key"), "name": item.get("name")}
        for item in client.request("GET", "/project")
    ]


def search(client, jql, max_results=20):
    if not str(jql or "").strip():
        raise JiraError("JQL 不能为空")
    data = client.request("GET", "/search", params={
        "jql": jql,
        "maxResults": max(1, min(int(max_results), 50)),
        "fields": "summary,status,assignee,reporter,priority,issuetype,updated",
    })
    return {
        "total": data.get("total"),
        "issues": [simplify_issue(item, client.base_url) for item in data.get("issues", [])],
    }


def get_issue(client, key, comment_limit=10):
    key = issue_key(key)
    issue = client.request(
        "GET", f"/issue/{urllib.parse.quote(key, safe='')}",
        params={"expand": "names", "fields": "*all"},
    )
    result = simplify_issue(issue, client.base_url, detail=True)
    limit = max(0, min(int(comment_limit), 50))
    result["comments"] = result.get("comments", [])[-limit:] if limit else []
    return result


def issue_snapshot(client, key, detail=False):
    key = issue_key(key)
    params = {"fields": "*all" if detail else "summary,status,assignee,priority,updated"}
    if detail:
        params["expand"] = "names"
    data = client.request(
        "GET", f"/issue/{urllib.parse.quote(key, safe='')}", params=params
    )
    return simplify_issue(data, client.base_url, detail=detail)


def find_issue_type(client, project, issue_type):
    project_value = urllib.parse.quote(str(project).strip(), safe="")
    data = client.request("GET", f"/issue/createmeta/{project_value}/issuetypes")
    values = data.get("values", data if isinstance(data, list) else [])
    wanted = str(issue_type).strip().casefold()
    for item in values:
        if str(item.get("id")) == str(issue_type) or str(item.get("name", "")).casefold() == wanted:
            return item
    raise JiraError(f"项目 {project} 中找不到类型 {issue_type}")


def create_metadata(client, project, issue_type):
    info = find_issue_type(client, project, issue_type)
    project_value = urllib.parse.quote(str(project).strip(), safe="")
    type_value = urllib.parse.quote(str(info.get("id")), safe="")
    data = client.request(
        "GET", f"/issue/createmeta/{project_value}/issuetypes/{type_value}"
    )
    values = data.get("values", data if isinstance(data, list) else [])
    return info, values


def field_summary(field_id, info):
    return {
        "id": field_id,
        "name": info.get("name"),
        "required": bool(info.get("required")),
        "has_default": bool(info.get("hasDefaultValue")),
        "type": (info.get("schema") or {}).get("type"),
        "items": (info.get("schema") or {}).get("items"),
        "allowed_values": [simple_value(value) for value in (info.get("allowedValues") or [])[:100]],
    }


def create_fields(client, project, issue_type):
    info, fields = create_metadata(client, project, issue_type)
    return {
        "project": project,
        "issue_type": {"id": info.get("id"), "name": info.get("name")},
        "fields": [field_summary(item.get("fieldId"), item) for item in fields],
    }


def edit_fields(client, key):
    key = issue_key(key)
    data = client.request("GET", f"/issue/{urllib.parse.quote(key, safe='')}/editmeta")
    return {
        "key": key,
        "fields": [
            field_summary(field_id, info)
            for field_id, info in (data.get("fields") or {}).items()
        ],
    }


def build_create_fields(client, project, issue_type, summary, description="",
                        assignee=None, priority=None, labels=None, components=None,
                        extra_fields=None):
    info, metadata = create_metadata(client, project, issue_type)
    fields = {
        "project": {"key": project},
        "issuetype": {"id": info.get("id")},
        "summary": summary,
    }
    if description:
        fields["description"] = description
    if assignee:
        fields["assignee"] = {"name": assignee}
    if priority:
        fields["priority"] = {"name": priority}
    if labels:
        fields["labels"] = labels
    if components:
        fields["components"] = [{"name": name} for name in components]
    if extra_fields:
        fields.update(extra_fields)
    metadata_by_id = {item.get("fieldId"): item for item in metadata}
    reporter = metadata_by_id.get("reporter") or {}
    if reporter.get("required") and not reporter.get("hasDefaultValue") and "reporter" not in fields:
        current = client.request("GET", "/myself")
        fields["reporter"] = {"name": current.get("name") or current.get("key")}
    missing = [
        {"id": field_id, "name": item.get("name")}
        for field_id, item in metadata_by_id.items()
        if item.get("required") and not item.get("hasDefaultValue") and field_id not in fields
    ]
    return fields, missing


def prepare_create(client, **kwargs):
    fields, missing = build_create_fields(client, **kwargs)
    return {
        "ready": not missing,
        "missing_required_fields": missing,
        "fields": fields,
        "message": "字段完整，可以在用户确认后创建" if not missing else "请先补充必填字段",
    }


def create_issue(client, **kwargs):
    fields, missing = build_create_fields(client, **kwargs)
    if missing:
        names = ", ".join(f"{item['name']}({item['id']})" for item in missing)
        raise JiraError(f"创建字段不完整：{names}")
    result = client.request("POST", "/issue", body={"fields": fields})
    key = result.get("key")
    return {
        "key": key,
        "url": f"{client.base_url}/browse/{key}",
        "message": "创建成功",
        "verified_issue": issue_snapshot(client, key, detail=True),
    }


def update_issue(client, key, fields):
    key = issue_key(key)
    if not isinstance(fields, dict) or not fields:
        raise JiraError("fields-json 必须是非空 JSON 对象")
    client.request(
        "PUT", f"/issue/{urllib.parse.quote(key, safe='')}", body={"fields": fields}
    )
    return {
        "key": key,
        "message": "更新成功",
        "updated_fields": list(fields.keys()),
        "verified_issue": issue_snapshot(client, key, detail=True),
    }


def add_comment(client, key, body):
    key = issue_key(key)
    result = client.request(
        "POST", f"/issue/{urllib.parse.quote(key, safe='')}/comment", body={"body": body}
    )
    return {
        "key": key,
        "comment_id": result.get("id"),
        "message": "评论已添加",
        "verified_issue": issue_snapshot(client, key, detail=True),
    }


def transitions(client, key):
    key = issue_key(key)
    data = client.request("GET", f"/issue/{urllib.parse.quote(key, safe='')}/transitions")
    return [
        {
            "id": item.get("id"),
            "name": item.get("name"),
            "to_status": (item.get("to") or {}).get("name"),
        }
        for item in data.get("transitions", [])
    ]


def transition_issue(client, key, target, comment=None):
    key = issue_key(key)
    options = client.request("GET", f"/issue/{urllib.parse.quote(key, safe='')}/transitions")
    wanted = str(target).strip().casefold()
    matched = None
    for item in options.get("transitions", []):
        candidates = {
            str(item.get("id", "")).casefold(),
            str(item.get("name", "")).casefold(),
            str((item.get("to") or {}).get("name", "")).casefold(),
        }
        if wanted in candidates:
            matched = item
            break
    if not matched:
        available = [item.get("name") for item in options.get("transitions", [])]
        raise JiraError(f"找不到流转 {target}，当前可用：{available}")
    payload = {"transition": {"id": matched.get("id")}}
    if comment:
        payload["update"] = {"comment": [{"add": {"body": comment}}]}
    client.request(
        "POST", f"/issue/{urllib.parse.quote(key, safe='')}/transitions", body=payload
    )
    return {
        "key": key,
        "transition": matched.get("name"),
        "target_status": (matched.get("to") or {}).get("name"),
        "message": "状态已流转",
        "verified_issue": issue_snapshot(client, key),
    }


def assign_issue(client, key, username):
    key = issue_key(key)
    client.request(
        "PUT", f"/issue/{urllib.parse.quote(key, safe='')}/assignee",
        body={"name": username},
    )
    return {
        "key": key,
        "assignee": username,
        "message": "负责人已修改",
        "verified_issue": issue_snapshot(client, key),
    }


def ask_macos_dialog(prompt, hidden=False):
    hidden_clause = " with hidden answer" if hidden else ""
    script = (
        f'text returned of (display dialog "{prompt}" default answer ""'
        f'{hidden_clause} buttons {{"取消", "继续"}} default button "继续"'
        ' with title "SDGH Jira Access 配置")'
    )
    try:
        result = subprocess.run(
            ["/usr/bin/osascript", "-e", script],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise JiraError("用户取消了 Jira 配置") from exc
    return result.stdout.rstrip("\r\n")


def setup(url, username=None, gui=False, config_path=None):
    if sys.platform != "darwin" or not Path("/usr/bin/security").exists():
        raise JiraError("当前一键配置仅支持 macOS")
    if not username:
        username = (
            ask_macos_dialog("请输入本人 Jira 用户名")
            if gui else input("请输入本人 Jira 用户名：").strip()
        )
    password = (
        ask_macos_dialog("请输入本人 Jira 密码", hidden=True)
        if gui else __import__("getpass").getpass("请输入本人 Jira 密码：")
    )
    if not username or not password:
        raise JiraError("Jira 用户名和密码不能为空")
    client = JiraClient(url, username=username, password=password)
    identity = whoami(client)
    if not identity.get("active"):
        raise JiraError("Jira 账号未处于启用状态")
    host = urllib.parse.urlparse(url).hostname or "jira"
    service = f"sdgh-jira-access:{host}"
    subprocess.run(
        [
            "/usr/bin/security", "add-generic-password", "-U",
            "-s", service, "-a", username, "-w", password,
        ],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    target = Path(config_path or DEFAULT_CONFIG).expanduser()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "base_url": str(url).rstrip("/"),
        "username": username,
        "keychain_service": service,
        "ssl_verify": True,
    }
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=target.parent, delete=False
    ) as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    os.replace(temporary, target)
    return {
        "configured": True,
        "identity": identity,
        "config_path": str(target),
        "password_storage": "macOS Keychain",
        "capabilities": ["查询", "详情", "创建", "修改", "评论", "指派", "状态流转"],
    }


def json_object(text, label):
    try:
        value = json.loads(text or "{}")
    except json.JSONDecodeError as exc:
        raise JiraError(f"{label} 不是有效 JSON：{exc}") from exc
    if not isinstance(value, dict):
        raise JiraError(f"{label} 必须是 JSON 对象")
    return value


def add_create_arguments(parser):
    parser.add_argument("--project", required=True)
    parser.add_argument("--issue-type", required=True)
    parser.add_argument("--summary", required=True)
    parser.add_argument("--description", default="")
    parser.add_argument("--assignee")
    parser.add_argument("--priority")
    parser.add_argument("--labels-json", default="[]")
    parser.add_argument("--components-json", default="[]")
    parser.add_argument("--extra-fields-json", default="{}")


def parser_definition():
    parser = argparse.ArgumentParser(description="直接调用 Jira REST API")
    parser.add_argument("--config", help="配置文件路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    setup_parser = subparsers.add_parser("setup", help="配置本人 Jira 身份")
    setup_parser.add_argument("--url", required=True)
    setup_parser.add_argument("--username")
    setup_parser.add_argument("--gui", action="store_true")

    subparsers.add_parser("whoami")
    subparsers.add_parser("projects")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("--jql", required=True)
    search_parser.add_argument("--max-results", type=int, default=20)

    get_parser = subparsers.add_parser("get")
    get_parser.add_argument("issue_key")
    get_parser.add_argument("--comment-limit", type=int, default=10)

    create_fields_parser = subparsers.add_parser("create-fields")
    create_fields_parser.add_argument("--project", required=True)
    create_fields_parser.add_argument("--issue-type", required=True)

    prepare_parser = subparsers.add_parser("prepare-create")
    add_create_arguments(prepare_parser)

    create_parser = subparsers.add_parser("create")
    add_create_arguments(create_parser)
    create_parser.add_argument("--confirm", action="store_true")

    edit_parser = subparsers.add_parser("edit-fields")
    edit_parser.add_argument("issue_key")

    update_parser = subparsers.add_parser("update")
    update_parser.add_argument("issue_key")
    update_parser.add_argument("--fields-json", required=True)
    update_parser.add_argument("--confirm", action="store_true")

    comment_parser = subparsers.add_parser("comment")
    comment_parser.add_argument("issue_key")
    comment_parser.add_argument("--body", required=True)
    comment_parser.add_argument("--confirm", action="store_true")

    transitions_parser = subparsers.add_parser("transitions")
    transitions_parser.add_argument("issue_key")

    transition_parser = subparsers.add_parser("transition")
    transition_parser.add_argument("issue_key")
    transition_parser.add_argument("--target", required=True)
    transition_parser.add_argument("--comment")
    transition_parser.add_argument("--confirm", action="store_true")

    assign_parser = subparsers.add_parser("assign")
    assign_parser.add_argument("issue_key")
    assign_parser.add_argument("--username", required=True)
    assign_parser.add_argument("--confirm", action="store_true")
    return parser


def require_confirm(args):
    if not getattr(args, "confirm", False):
        raise JiraError("写操作尚未确认。先向用户展示准确变化，确认后增加 --confirm")


def create_kwargs(args):
    try:
        labels = json.loads(args.labels_json)
        components = json.loads(args.components_json)
    except json.JSONDecodeError as exc:
        raise JiraError(f"labels-json 或 components-json 无效：{exc}") from exc
    if not isinstance(labels, list) or not isinstance(components, list):
        raise JiraError("labels-json 和 components-json 必须是 JSON 数组")
    return {
        "project": args.project,
        "issue_type": args.issue_type,
        "summary": args.summary,
        "description": args.description,
        "assignee": args.assignee,
        "priority": args.priority,
        "labels": labels,
        "components": components,
        "extra_fields": json_object(args.extra_fields_json, "extra-fields-json"),
    }


def execute(args):
    if args.command == "setup":
        return setup(args.url, username=args.username, gui=args.gui, config_path=args.config)
    client = JiraClient.from_config(args.config)
    if args.command == "whoami":
        return whoami(client)
    if args.command == "projects":
        return projects(client)
    if args.command == "search":
        return search(client, args.jql, args.max_results)
    if args.command == "get":
        return get_issue(client, args.issue_key, args.comment_limit)
    if args.command == "create-fields":
        return create_fields(client, args.project, args.issue_type)
    if args.command == "prepare-create":
        return prepare_create(client, **create_kwargs(args))
    if args.command == "create":
        require_confirm(args)
        return create_issue(client, **create_kwargs(args))
    if args.command == "edit-fields":
        return edit_fields(client, args.issue_key)
    if args.command == "update":
        require_confirm(args)
        return update_issue(client, args.issue_key, json_object(args.fields_json, "fields-json"))
    if args.command == "comment":
        require_confirm(args)
        return add_comment(client, args.issue_key, args.body)
    if args.command == "transitions":
        return transitions(client, args.issue_key)
    if args.command == "transition":
        require_confirm(args)
        return transition_issue(client, args.issue_key, args.target, comment=args.comment)
    if args.command == "assign":
        require_confirm(args)
        return assign_issue(client, args.issue_key, args.username)
    raise JiraError(f"未知命令：{args.command}")


def main():
    parser = parser_definition()
    args = parser.parse_args()
    try:
        print(dump(execute(args)))
    except (JiraError, OSError, subprocess.SubprocessError) as exc:
        print(dump({"error": str(exc)}), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
