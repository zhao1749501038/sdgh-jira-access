import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "jira.py"
SPEC = importlib.util.spec_from_file_location("jira_api_script", SCRIPT)
jira = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jira)


class FakeClient:
    base_url = "https://jira.example"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def request(self, method, path, body=None, params=None):
        self.calls.append({"method": method, "path": path, "body": body, "params": params})
        return self.responses.pop(0)


def issue(key="DEMO-1", status="待处理"):
    return {
        "key": key,
        "fields": {
            "summary": "测试需求",
            "status": {"name": status},
            "assignee": {"name": "test-user", "displayName": "测试用户"},
            "priority": {"name": "Medium"},
            "updated": "2026-08-20T09:00:00.000+0800",
        },
    }


class JiraApiTests(unittest.TestCase):
    def test_setup_uses_company_default_url(self):
        parser = jira.parser_definition()
        args = parser.parse_args(["setup", "--gui"])
        self.assertEqual(args.url, "https://21tb-jira.21tb.com")

    def test_windows_config_path_uses_appdata(self):
        path = jira.default_config_path(
            os_name="nt",
            environ={"APPDATA": r"C:\Users\demo\AppData\Roaming"},
        )
        self.assertEqual(
            path,
            Path(r"C:\Users\demo\AppData\Roaming") / "sdgh-jira-access" / "config.json",
        )

    def test_dpapi_secret_is_used_for_windows_config(self):
        client = jira.JiraClient(
            "https://jira.example",
            username="demo",
            password_dpapi="encrypted-value",
        )
        with mock.patch.object(
            jira, "unprotect_windows_secret", return_value="secret"
        ) as decrypt:
            self.assertEqual(client.resolved_password(), "secret")
        decrypt.assert_called_once_with("encrypted-value")

    def test_windows_setup_stores_only_dpapi_ciphertext(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            with (
                mock.patch.object(
                    jira, "ask_windows_credentials", return_value=("demo", "secret")
                ),
                mock.patch.object(
                    jira, "whoami", return_value={"username": "demo", "active": True}
                ),
                mock.patch.object(
                    jira, "protect_windows_secret", return_value="encrypted-value"
                ),
            ):
                result = jira.setup(
                    gui=True,
                    config_path=config_path,
                    system_name="nt",
                    platform_name="win32",
                )
            payload = json.loads(config_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["password_dpapi"], "encrypted-value")
        self.assertNotIn("password", payload)
        self.assertIn("Windows DPAPI", result["password_storage"])

    def test_unavailable_system_prompt_falls_back_to_terminal(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "config.json"
            with (
                mock.patch.object(
                    jira,
                    "ask_windows_credentials",
                    side_effect=jira.CredentialPromptUnavailable("窗口不可用"),
                ),
                mock.patch.object(
                    jira,
                    "ask_terminal_credentials",
                    return_value=("demo", "secret"),
                ) as terminal_prompt,
                mock.patch.object(
                    jira, "whoami", return_value={"username": "demo", "active": True}
                ),
                mock.patch.object(
                    jira, "protect_windows_secret", return_value="encrypted-value"
                ),
            ):
                jira.setup(
                    gui=True,
                    config_path=config_path,
                    system_name="nt",
                    platform_name="win32",
                )
        terminal_prompt.assert_called_once_with(None)

    def test_cancelled_system_prompt_does_not_continue_to_terminal(self):
        with (
            mock.patch.object(
                jira,
                "ask_windows_credentials",
                side_effect=jira.CredentialPromptCancelled("用户取消"),
            ),
            mock.patch.object(jira, "ask_terminal_credentials") as terminal_prompt,
        ):
            with self.assertRaisesRegex(jira.JiraError, "取消"):
                jira.setup(gui=True, system_name="nt", platform_name="win32")
        terminal_prompt.assert_not_called()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI 仅在 Windows CI 运行")
    def test_windows_dpapi_round_trip(self):
        ciphertext = jira.protect_windows_secret("测试-password-123")
        self.assertNotIn("测试-password-123", ciphertext)
        self.assertEqual(
            jira.unprotect_windows_secret(ciphertext), "测试-password-123"
        )

    def test_issue_key_validation(self):
        self.assertEqual(jira.issue_key("demo-12"), "DEMO-12")
        with self.assertRaises(jira.JiraError):
            jira.issue_key("../myself")

    def test_prepare_create_reports_missing_required_fields(self):
        client = FakeClient([
            {"values": [{"id": "100", "name": "业务需求"}]},
            {"values": [
                {"fieldId": "project", "name": "项目", "required": True, "hasDefaultValue": False},
                {"fieldId": "issuetype", "name": "类型", "required": True, "hasDefaultValue": False},
                {"fieldId": "summary", "name": "概要", "required": True, "hasDefaultValue": False},
                {"fieldId": "components", "name": "模块", "required": True, "hasDefaultValue": False},
            ]},
        ])
        result = jira.prepare_create(
            client, project="DEMO", issue_type="业务需求", summary="标题"
        )
        self.assertFalse(result["ready"])
        self.assertEqual(
            result["missing_required_fields"],
            [{"id": "components", "name": "模块"}],
        )

    def test_update_reads_back(self):
        client = FakeClient([{}, issue()])
        result = jira.update_issue(client, "DEMO-1", {"summary": "新标题"})
        self.assertEqual(client.calls[0]["method"], "PUT")
        self.assertEqual(result["verified_issue"]["key"], "DEMO-1")

    def test_transition_matches_target_status_and_reads_back(self):
        client = FakeClient([
            {"transitions": [{"id": "31", "name": "开始设计", "to": {"name": "设计中"}}]},
            {},
            issue(status="设计中"),
        ])
        result = jira.transition_issue(client, "DEMO-1", "设计中")
        self.assertEqual(result["target_status"], "设计中")
        self.assertEqual(result["verified_issue"]["status"], "设计中")

    def test_write_requires_explicit_confirm(self):
        parser = jira.parser_definition()
        args = parser.parse_args([
            "update", "DEMO-1", "--fields-json", json.dumps({"summary": "新标题"})
        ])
        with self.assertRaises(jira.JiraError):
            jira.require_confirm(args)


if __name__ == "__main__":
    unittest.main()
