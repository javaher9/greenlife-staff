import json
from django.test import SimpleTestCase, RequestFactory
from unittest.mock import patch
from core.instagram_agent_api import instagram_agent_lead_api


class InstagramAgentApiSecurityTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.url = "/api/integrations/instagram/leads/"

    def request(self, data=None, authorization=None):
        kwargs = {}
        if authorization is not None:
            kwargs["HTTP_AUTHORIZATION"] = authorization
        return self.factory.post(
            self.url, data=json.dumps(data or {}), content_type="application/json", **kwargs
        )

    @patch.dict("os.environ", {}, clear=True)
    def test_disabled_without_secret(self):
        self.assertEqual(instagram_agent_lead_api(self.request()).status_code, 503)

    @patch.dict("os.environ", {"INSTAGRAM_AGENT_API_KEY": "x" * 40})
    def test_requires_bearer_token(self):
        self.assertEqual(instagram_agent_lead_api(self.request()).status_code, 401)

    @patch.dict("os.environ", {"INSTAGRAM_AGENT_API_KEY": "x" * 40})
    def test_requires_consent(self):
        response = instagram_agent_lead_api(self.request(
            {"source_page": "greenlifeclinics", "contact_consent": False},
            "Bearer " + "x" * 40,
        ))
        self.assertEqual(response.status_code, 422)

    @patch.dict("os.environ", {"INSTAGRAM_AGENT_API_KEY": "x" * 40})
    def test_rejects_unknown_source(self):
        response = instagram_agent_lead_api(self.request(
            {"source_page": "unknown", "contact_consent": True},
            "Bearer " + "x" * 40,
        ))
        self.assertEqual(response.status_code, 422)

    @patch.dict("os.environ", {"INSTAGRAM_AGENT_API_KEY": "x" * 40})
    def test_rejects_invalid_json(self):
        request = self.factory.post(
            self.url, data="{broken", content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + "x" * 40,
        )
        self.assertEqual(instagram_agent_lead_api(request).status_code, 400)

    @patch.dict("os.environ", {"INSTAGRAM_AGENT_API_KEY": "x" * 40})
    def test_rejects_wrong_content_type(self):
        request = self.factory.post(
            self.url, data="hello", content_type="text/plain",
            HTTP_AUTHORIZATION="Bearer " + "x" * 40,
        )
        self.assertEqual(instagram_agent_lead_api(request).status_code, 415)

    @patch.dict("os.environ", {"INSTAGRAM_AGENT_API_KEY": "x" * 40})
    def test_rejects_non_object_json(self):
        request = self.factory.post(
            self.url, data="[]", content_type="application/json",
            HTTP_AUTHORIZATION="Bearer " + "x" * 40,
        )
        self.assertEqual(instagram_agent_lead_api(request).status_code, 400)
