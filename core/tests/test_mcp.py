import hashlib
import json
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings


@override_settings(ROOT_URLCONF="greenlife.urls")
class MCPServerTests(SimpleTestCase):
    key = "test-key-that-is-not-used-in-production"

    def post(self, payload, *, key=None, bearer=True):
        headers = {}
        if key:
            if bearer:
                headers["HTTP_AUTHORIZATION"] = f"Bearer {key}"
            else:
                headers["HTTP_X_STAFF_API_KEY"] = key
        return self.client.post(
            "/mcp/",
            data=json.dumps(payload),
            content_type="application/json",
            **headers,
        )

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    def test_rejects_missing_key(self):
        response = self.post({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
        self.assertEqual(response.status_code, 401)
        self.assertIn("Bearer", response["WWW-Authenticate"])

    def test_accepts_hashed_work_token(self):
        token = "test-work-token"
        digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        with patch.dict(
            "os.environ",
            {
                "MCP_API_KEY": "",
                "STAFF_REPORT_API_KEY": "",
                "MCP_WORK_TOKEN_SHA256": digest,
            },
            clear=False,
        ):
            response = self.post(
                {"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": {}},
                key=token,
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["result"]["serverInfo"]["version"], "1.1.0")

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    def test_initialize(self):
        response = self.post(
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            key=self.key,
        )
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["result"]["protocolVersion"], "2025-06-18")
        self.assertIn("tools", body["result"]["capabilities"])
        self.assertIn("no-cache", response["Cache-Control"])

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    def test_lists_only_read_only_tools(self):
        response = self.post(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            key=self.key,
            bearer=False,
        )
        tools = response.json()["result"]["tools"]
        self.assertEqual(
            [tool["name"] for tool in tools],
            ["get_attendance_summary", "ask_management"],
        )
        self.assertTrue(all(tool["annotations"]["readOnlyHint"] for tool in tools))

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    @patch("core.mcp._attendance_summary")
    def test_calls_attendance_tool(self, summary):
        summary.return_value = {
            "date": "1405/06/03",
            "late": 2,
            "late_people": [{"name": "Test User", "check_in": "09:15"}],
        }
        response = self.post(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "get_attendance_summary",
                    "arguments": {"date": "1405/06/03"},
                },
            },
            key=self.key,
        )
        self.assertEqual(response.status_code, 200)
        result = response.json()["result"]
        self.assertEqual(result["structuredContent"]["late"], 2)
        self.assertFalse(result["isError"])
        summary.assert_called_once_with("1405/06/03")

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    @patch("core.mcp._management_answer")
    def test_calls_management_question_tool(self, answer):
        answer.return_value = {"answer": "دو نفر دیر آمدند.", "data": []}
        response = self.post(
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "ask_management",
                    "arguments": {"question": "دیروز چند نفر دیر آمدند؟"},
                },
            },
            key=self.key,
        )
        self.assertEqual(response.json()["result"]["structuredContent"]["answer"], "دو نفر دیر آمدند.")
        answer.assert_called_once_with("دیروز چند نفر دیر آمدند؟")

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    def test_notification_has_no_body(self):
        response = self.post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            key=self.key,
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, b"")
