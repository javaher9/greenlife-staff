import hashlib
import json
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase, override_settings

from core.models import AuditLog, EmployeeProfile
from core.reporting import answer_query


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
        self.assertEqual(response.json()["result"]["serverInfo"]["version"], "1.3.1")

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
    def test_lists_reporting_and_role_tools(self):
        response = self.post(
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            key=self.key,
            bearer=False,
        )
        tools = response.json()["result"]["tools"]
        self.assertEqual(
            [tool["name"] for tool in tools],
            [
                "get_attendance_summary",
                "get_daily_reports",
                "ask_management",
                "find_staff",
                "set_operational_role",
            ],
        )
        self.assertTrue(tools[3]["annotations"]["readOnlyHint"])
        self.assertFalse(tools[4]["annotations"]["readOnlyHint"])

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
    @patch("core.mcp._daily_reports")
    def test_calls_daily_reports_tool(self, reports):
        reports.return_value = {
            "date": "1405/06/05",
            "report_count": 1,
            "reports": [{"name": "Test User", "content": "کارهای امروز انجام شد."}],
        }
        response = self.post(
            {
                "jsonrpc": "2.0",
                "id": 5,
                "method": "tools/call",
                "params": {
                    "name": "get_daily_reports",
                    "arguments": {
                        "date": "1405/06/05",
                        "branch": "نیاوران",
                        "include_raw": True,
                    },
                },
            },
            key=self.key,
        )
        result = response.json()["result"]["structuredContent"]
        self.assertEqual(result["report_count"], 1)
        reports.assert_called_once_with("1405/06/05", "نیاوران", True)

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    def test_notification_has_no_body(self):
        response = self.post(
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            key=self.key,
        )
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, b"")


@override_settings(ROOT_URLCONF="greenlife.urls")
class MCPRoleManagementTests(TestCase):
    key = "test-private-mcp-key"

    def setUp(self):
        self.admin = User.objects.create_user(
            "admin-user", first_name="مدیر", last_name="سیستم", is_active=True
        )
        self.admin.profile.role = "admin"
        self.admin.profile.is_active = True
        self.admin.profile.save(update_fields=["role", "is_active"])
        self.employee = User.objects.create_user(
            "narges", first_name="نرگس", last_name="نمونه", is_active=True
        )
        self.profile = self.employee.profile
        self.profile.role = "employee"
        self.profile.job_title = "کارمند"
        self.profile.phone = "09120000000"
        self.profile.is_active = True
        self.profile.save(update_fields=["role", "job_title", "phone", "is_active"])

    def post_tool(self, name, arguments):
        return self.client.post(
            "/mcp/",
            data=json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 20,
                    "method": "tools/call",
                    "params": {"name": name, "arguments": arguments},
                }
            ),
            content_type="application/json",
            HTTP_AUTHORIZATION=f"Bearer {self.key}",
        )

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    def test_finds_exact_staff_candidates_before_change(self):
        response = self.post_tool("find_staff", {"query": "نرگس"})
        result = response.json()["result"]["structuredContent"]
        self.assertEqual(result["match_count"], 1)
        self.assertEqual(result["matches"][0]["profile_id"], self.profile.id)
        self.assertEqual(result["matches"][0]["role"], "employee")

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    def test_role_change_requires_explicit_confirmation(self):
        response = self.post_tool(
            "set_operational_role",
            {"profile_ids": [self.profile.id], "role": "call_center", "confirm": False},
        )
        self.assertEqual(response.json()["error"]["code"], -32602)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, "employee")

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    def test_changes_operational_role_and_writes_audit_log(self):
        response = self.post_tool(
            "set_operational_role",
            {
                "profile_ids": [self.profile.id],
                "role": "call_center",
                "job_title": "کارشناس کال‌سنتر",
                "confirm": True,
            },
        )
        result = response.json()["result"]["structuredContent"]
        self.assertEqual(result["updated_count"], 1)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, "call_center")
        self.assertEqual(self.profile.job_title, "کارشناس کال‌سنتر")
        audit = AuditLog.objects.get(action="mcp_operational_role")
        self.assertEqual(audit.actor, self.admin)
        self.assertEqual(audit.metadata["role"], "call_center")

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    def test_cannot_grant_admin_role(self):
        response = self.post_tool(
            "set_operational_role",
            {"profile_ids": [self.profile.id], "role": "admin", "confirm": True},
        )
        self.assertEqual(response.json()["error"]["code"], -32602)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, "employee")

    @patch.dict("os.environ", {"STAFF_REPORT_API_KEY": key}, clear=False)
    def test_cannot_grant_internal_manager_role(self):
        response = self.post_tool(
            "set_operational_role",
            {
                "profile_ids": [self.profile.id],
                "role": "internal_manager",
                "confirm": True,
            },
        )
        self.assertEqual(response.json()["error"]["code"], -32602)
        self.profile.refresh_from_db()
        self.assertEqual(self.profile.role, "employee")


class ManagementReportRoutingTests(SimpleTestCase):
    class EmptyScopedUsers(list):
        def values_list(self, *args, **kwargs):
            return []

    @patch("core.reporting.daily_reports_summary")
    @patch("core.reporting.scope_users")
    @patch("core.reporting.day_summary")
    def test_today_reports_question_returns_report_content_not_attendance(
        self, attendance, scoped_users, reports
    ):
        attendance.return_value = {"date": "۱۴۰۵/۰۶/۰۵", "rows": []}
        scoped_users.return_value = self.EmptyScopedUsers()
        reports.return_value = {
            "date": "۱۴۰۵/۰۶/۰۵",
            "report_count": 2,
            "reporter_count": 2,
            "reporters": ["کارمند اول", "کارمند دوم"],
            "reports": [
                {"name": "کارمند اول", "content": "خلاصه اول"},
                {"name": "کارمند دوم", "content": "خلاصه دوم"},
            ],
        }

        result = answer_query(object(), "خلاصه گزارش‌های امروز را بده")

        self.assertEqual(result["data"]["report_count"], 2)
        self.assertIn("۲ گزارش", result["answer"])
        reports.assert_called_once()
