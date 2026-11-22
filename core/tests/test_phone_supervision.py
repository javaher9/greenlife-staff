from contextlib import contextmanager
from io import BytesIO
import json
import os
import socket
import time
from unittest.mock import Mock, patch
from uuid import UUID

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase

from core import phone_supervision as supervision
from core.models import AuditLog


AMI_SETTINGS = {
    "host": "pbx.private",
    "username": "supervision-test",
    "secret": "isolated-test-value",
    "contexts": ["support-agents"],
    "operators": {"201": "رز", "202": "یاسمن"},
    "supervisors": {"supervisor": "901", "second-supervisor": "902"},
}


def operator_channel(extension="201", bridge="bridge-one", **overrides):
    return {
        "channel": f"PJSIP/{extension}-000abcd",
        "channelstatedesc": "Up",
        "context": "support-agents",
        "bridgeid": bridge,
        "uniqueid": "pbx-1735932030.13",
        "duration": "00:02:24",
        "calleridnum": "+989120000000",
        **overrides,
    }


def trunk_channel(bridge="bridge-one"):
    return {"channel": "PJSIP/shatel-000003ad", "bridgeid": bridge, "channelstatedesc": "Up"}


class SupervisionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        users = get_user_model()
        cls.supervisor = users.objects.create_user("supervisor")
        cls.second_supervisor = users.objects.create_user("second-supervisor")
        cls.unenrolled = users.objects.create_user("other-manager")
        cls.inactive = users.objects.create_user("inactive-supervisor", is_active=False)

    def setUp(self):
        self.ami = Mock()
        self.ami.scoped_to_supervision.return_value = True
        self.ami.channels.return_value = [operator_channel(), trunk_channel()]

        @contextmanager
        def fake_ami(config):
            yield self.ami

        self.addCleanup(patch.stopall)
        self.environment = patch.dict(os.environ, {"GREENLIFE_SUPERVISION_AMI": json.dumps(AMI_SETTINGS)})
        self.environment.start()
        self.connector = patch.object(supervision, "_open_ami", side_effect=fake_ami).start()

    def test_absent_settings_and_unauthorized_user_never_contact_pbx(self):
        self.assertFalse(supervision.supervision_snapshot(self.unenrolled)["available"])
        settings = {**AMI_SETTINGS, "supervisors": {**AMI_SETTINGS["supervisors"], "inactive-supervisor": "903"}}
        with patch.dict(os.environ, {"GREENLIFE_SUPERVISION_AMI": json.dumps(settings)}):
            self.assertFalse(supervision.supervision_snapshot(self.inactive)["available"])
        with patch.dict(os.environ, {"GREENLIFE_SUPERVISION_AMI": ""}):
            result = supervision.supervision_snapshot(self.supervisor)
        self.assertEqual(result["calls"], [])
        self.assertFalse(result["available"])
        self.connector.assert_not_called()

    def test_context_bridge_and_group_scope_hide_unapproved_calls_and_numbers(self):
        self.ami.channels.return_value += [
            operator_channel("202", "rejected-context", context="private-context"),
            trunk_channel("rejected-context"),
            operator_channel("202", "ringing", channelstatedesc="Ringing"),
            trunk_channel("ringing"),
            operator_channel("202", "multiparty"),
            trunk_channel("multiparty"),
            trunk_channel("multiparty"),
            operator_channel("999", "unknown"),
            trunk_channel("unknown"),
            operator_channel("202", "no-tag"),
            trunk_channel("no-tag"),
        ]
        self.ami.scoped_to_supervision.side_effect = lambda channel: channel != "PJSIP/202-000abcd"
        result = supervision.supervision_snapshot(self.supervisor)
        self.assertTrue(result["available"])
        self.assertTrue(result["can_start"])
        self.assertEqual(len(result["calls"]), 1)
        call = result["calls"][0]
        self.assertEqual({field for field in call}, {"id", "operator", "extension", "elapsed_seconds"})
        self.assertEqual((call["operator"], call["extension"], call["elapsed_seconds"]), ("رز", "201", 144))
        self.assertNotIn("+989120000000", str(result))
        self.assertNotIn("pbx-1735932030.13", str(result))

    def test_call_tokens_are_bound_to_manager_and_live_bridge(self):
        token = supervision.supervision_snapshot(self.supervisor)["calls"][0]["id"]
        with self.assertRaises(supervision.SupervisionError) as error:
            supervision.start_supervision(self.second_supervisor, token, "whisper")
        self.assertEqual(error.exception.code, "stale")
        self.ami.channels.return_value = [
            operator_channel(bridge="post-transfer"),
            trunk_channel("post-transfer"),
        ]
        with self.assertRaises(supervision.SupervisionError) as error:
            supervision.start_supervision(self.supervisor, token, "listen")
        self.assertEqual(error.exception.code, "stale")
        self.ami.originate.assert_not_called()

    def test_valid_whisper_is_audited_before_ringing_only_enrolled_supervisor(self):
        token = supervision.supervision_snapshot(self.supervisor)["calls"][0]["id"]

        def check_audit(*args):
            entry = AuditLog.objects.get(action=supervision.AUDIT_ACTION)
            self.assertEqual(entry.actor, self.supervisor)
            self.assertEqual(entry.object_id, token)
            self.assertEqual(entry.metadata, {"mode": "whisper", "extension": "201"})

        self.ami.originate.side_effect = check_audit
        result = supervision.start_supervision(self.supervisor, token, "whisper")
        self.assertTrue(result["accepted"])
        self.ami.originate.assert_called_once_with("901", "201", "pbx-1735932030.13", "whisper")
        with self.assertRaises(supervision.SupervisionError) as error:
            supervision.start_supervision(self.supervisor, token, "join")
        self.assertEqual(error.exception.code, "busy")
        self.assertEqual(self.ami.originate.call_count, 1)

    def test_busy_and_unavailable_are_different_from_empty_live_state(self):
        self.ami.channels.return_value = []
        self.assertTrue(supervision.supervision_snapshot(self.supervisor)["available"])
        self.ami.channels.return_value = [operator_channel("901")]
        busy = supervision.supervision_snapshot(self.supervisor)
        self.assertTrue(busy["available"])
        self.assertFalse(busy["can_start"])
        self.assertTrue(busy["reason"])
        self.ami.channels.side_effect = supervision._PBXUnavailable
        unavailable = supervision.supervision_snapshot(self.supervisor)
        self.assertFalse(unavailable["available"])
        self.assertTrue(unavailable["reason"])
        self.assertEqual(unavailable["calls"], [])

    def test_invalid_mode_or_token_never_contacts_pbx(self):
        for token, mode in (("a" * 64, "arbitrary"), ("bad\r\nAction: Hangup", "listen"), ("a" * 64, {})):
            with self.subTest(mode=mode), self.assertRaises(supervision.SupervisionError) as error:
                supervision.start_supervision(self.supervisor, token, mode)
            self.assertEqual(error.exception.status, 400)
        self.connector.assert_not_called()


class AMICommandsTests(SimpleTestCase):
    def test_fixed_origination_options_preserve_exact_scope_for_each_mode(self):
        adapter = supervision._AMI(None, None, 0)
        adapter.command = Mock()
        for mode, expected_suffix in (("listen", ""), ("whisper", "w"), ("join", "B")):
            with self.subTest(mode=mode):
                adapter.originate("901", "201", "pbx-01.2", mode)
                adapter.command.assert_called_with(
                    "Originate", Channel="PJSIP/901", Application="ChanSpy",
                    Data=f"pbx-01.2,uEbSx(*)g(greenlife-supervision)e(PJSIP/201){expected_suffix}",
                    Timeout="18000", Async="true", Account="greenlife-supervision",
                )

    def test_channel_framing_ignores_unrelated_events_and_checks_completeness(self):
        request_id = UUID(int=1).hex
        response = (
            f"Event: CoreShowChannelsComplete\r\nActionID: other\r\n\r\n"
            f"Response: Success\r\nActionID: {request_id}\r\n\r\n"
            f"Event: CoreShowChannel\r\nActionID: {request_id}\r\nChannel: PJSIP/201-test\r\n\r\n"
            f"Event: CoreShowChannelsComplete\r\nActionID: {request_id}\r\nListItems: 1\r\n\r\n"
        )
        connection = Mock()
        with patch.object(supervision, "uuid4", return_value=UUID(int=1)):
            adapter = supervision._AMI(connection, BytesIO(response.encode()), time.monotonic() + 2)
            self.assertEqual(adapter.channels()[0]["channel"], "PJSIP/201-test")
            truncated = supervision._AMI(connection, BytesIO(response.split("ListItems:")[0].encode()), time.monotonic() + 2)
            with self.assertRaises(supervision._PBXUnavailable):
                truncated.channels()

    def test_public_dns_resolution_rejected_before_creating_socket(self):
        with patch.dict(os.environ, {"GREENLIFE_SUPERVISION_AMI": json.dumps(AMI_SETTINGS)}):
            config = supervision._configuration()
        resolved = (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("8.8.8.8", 5039))
        with patch.object(socket, "getaddrinfo", return_value=[resolved]), patch.object(socket, "socket") as connector:
            with self.assertRaises(supervision._PBXUnavailable), supervision._open_ami(config):
                self.fail("A public PBX endpoint is outside the allowed scope")
            connector.assert_not_called()
