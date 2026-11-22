# Optional Asterisk integrations for GreenLife Staff

## After-call keypad rating

Install [greenlife_survey.py](greenlife_survey.py) as an executable in the pilot PBX's configured AGI directory and install a short local Persian prompt named `greenlife-call-rating` in its sounds directory. Give the PBX service account read access to a private `/etc/asterisk/greenlife-survey.json` on that node.

```json
{
  "url": "https://staff.example.org/api/private/phone-center/ratings/",
  "token": "REPLACE_WITH_THE_SHARED_STAFF_PHONE_RATINGS_TOKEN",
  "node_id": "pilot-pbx",
  "operators": {
    "trusted-operator-key": 123
  }
}
```

Use the same generated secret in the private file and in Staff's `STAFF_PHONE_RATINGS_TOKEN` environment setting. Operator mappings point to active call-center **EmployeeProfile** IDs in Staff. Give each PBX node a stable, unique ID. The HTTPS request carries an opaque derived call ID, the mapped operator ID and the selected score. Sending the same score twice for the same call is safe. A conflicting score or operator for that call is rejected by Staff.

On an approved pilot route, call this subroutine on the visitor's original channel after a verified operator answered and finished the call, while the visitor is still connected. Pass the key for the actual connected operator and the caller channel's `${CHANNEL(linkedid)}`. The correct operator must come from the route's trusted answered-operator metadata. Verify the route's transfer behavior before associating a score with a transferred call.

```asterisk
[greenlife-post-call-rating]
exten => s,1,Read(GL_RATING,greenlife-call-rating,1,,1,6)
 same => n,GotoIf($["${READSTATUS}" != "OK"]?done)
 same => n,AGI(greenlife_survey.py,${ARG1},${ARG2},${GL_RATING})
 same => n(done),Return()
```

With `Queue()`, option `c` can keep the caller channel running when the agent hangs up. Verify the answered operator and call outcome before invoking this subroutine. Validate a completed call with a valid score, a caller hangup, an unanswered queue call, an invalid keypress and a repeat delivery on the pilot before integrating with a production route. See [Queue](https://docs.asterisk.org/Asterisk_22_Documentation/API_Documentation/Dialplan_Applications/Queue/), [Read](https://docs.asterisk.org/Asterisk_22_Documentation/API_Documentation/Dialplan_Applications/Read/) and [AGI](https://docs.asterisk.org/Asterisk_22_Documentation/API_Documentation/Dialplan_Applications/AGI/).

## Completed-call statistics

A trusted CDR or call-event collector can send one finalized event per external call to `/api/private/phone-center/metrics/` using the separate `STAFF_PHONE_METRICS_TOKEN` Bearer secret. Consolidate transferred and retried legs under the same opaque call ID before sending. Use the trunk direction, actual answer outcome, call start time with offset, and answered-call duration in whole seconds. Send zero seconds for an unanswered call. The endpoint accepts the following fields.

```json
{
  "call_id": "7d04f781-9ff2-4bd7-a24c-dda970baefbc",
  "direction": "inbound",
  "outcome": "answered",
  "occurred_at": "2026-01-01T10:20:00+03:30",
  "duration_seconds": 90
}
```

Reuse the same event and UUID on delivery retry. Staff accepts identical repeats and rejects conflicting events for that UUID. The normalized event excludes caller numbers, raw channel identifiers and recordings. Validate the collector against real trunk calls in the pilot before putting the totals into operational use. See [Asterisk CDR variables](https://docs.asterisk.org/Configuration/Reporting/Call-Detail-Records-CDR/CDR-Variables/).

## Supervisor audio

Staff's optional `GREENLIFE_SUPERVISION_AMI` environment value is a JSON object. Use the real private AMI TLS endpoint and restrict its network access to Staff. Install a certificate trusted by Staff for the configured hostname. The optional `ca_file` points to the private CA certificate in the Staff runtime when needed.

```json
{
  "host": "pilot-pbx.internal",
  "port": 5039,
  "username": "greenlife-supervision",
  "secret": "REPLACE_WITH_A_DEDICATED_AMI_SECRET",
  "contexts": ["approved-pilot-context"],
  "supervisors": {"staff-supervisor-username": "7099"},
  "operators": {"7101": "اپراتور آزمایشی"}
}
```

Map each permitted Staff username to its own dedicated enrolled numeric PJSIP extension. Use different extensions for operators and supervisors. Verify the permissions for `CoreShowChannels`, `Getvar` and `Originate` on the installed Asterisk version and restrict the service account and interface to the required access. Apply `SPYGROUP=greenlife-supervision` only to eligible operator legs in the configured contexts. Remove the group when a leg leaves that scope. Test each mode with two approved pilot endpoints and the caller notification configured for the pilot, including verifying that whisper is audible only on the operator leg.
