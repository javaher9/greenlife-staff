# Schools and family program

The Staff management menu and authorized Niavaran coordinator get a Schools workspace. The coordinator creates schools/cohorts, capacity, dates and terms, and activates admission without owner approval. Organizations are separate from cohorts so company programs can be added later without renaming school data.

## Routes and workflow

- `/schools/`: management and branch-scoped coordinator dashboard.
- `/schools/families/`: filtered drill-down from every metric and follow-up queue, with school, branch, coordinator and registration-date filters.
- `/schools/<id>/report/`: printable aggregate school report, suppressing counts for cohorts with fewer than ten families and excluding identity, health and sales data.
- `/schools/new/`: school/cohort creation and immediate link/QR generation.
- `/schools/<id>/card/`: printable invitation, Save as PDF, downloadable QR image.
- `/customer/schools/<uuid>/`: public school invitation, existing SMS OTP verification, parent consent and registration.
- `/customer/family/`: authenticated family records, separate adult-consultation choice, appointment status and clinical reports.
- `/schools/clinical/`: branch-scoped physician workspace; consultants cannot read/write medical assessments.

Parents register in their ordinary browser after SMS verification. Installing the optional customer PWA is not required for registration, capacity admission or booking. The existing verified phone and CustomerPortalMember identity are retained for the later external GreenLife Me frontend integration.

Capacity counts families in ready/booked/attended states, not children. Verified registration reserves capacity immediately or enters the waiting list. Program-row locks serialize admission, coordinator updates and cancellation. Duplicate submissions reuse the enrollment and its one-to-one school lead. Families can recheck waiting-list admission in the browser; installation remains optional.

Each registration creates a distinct school follow-up lead assigned to the unique active Gandom profile, with school, cohort and branch in its preserved registration description. The existing same-phone commercial lead is neither reassigned nor overwritten. School leads never enter general rotation, including when Gandom is unavailable; they remain visible in Schools until `sync_school_leads` repairs the assignment. This idempotent deployment command also admits legacy pending registrations up to capacity. No child name, birth date or medical result is copied to CRM. Parent cancellation closes the corresponding school follow-up. Ordinary lead routing and the one-day general lead hold remain unchanged.

Booking writes a real `VisitAppointment` for the parent/family using existing clinic slots (15-minute intervals, no Fridays). Children remain in separate protected records and are never identified through the parent's phone in the existing patient table. Changes from reception synchronize the family status after commit. Parent cancellation cancels the linked family appointment.

## Permissions and privacy

`EmployeeProfile.can_manage_schools` grants full operational control within that employee's active branch. Executives retain global visibility. Migration 0121 grants it only if exactly one active Niavaran consultant has the exact normalized surname مرادی or username moradi; ambiguous/no matches grant nobody. Verify on the server with `python manage.py check_school_program`. Do not broaden access to all consultants to work around an identity mismatch.

Parents can see only their own family's reports. No school staff account or student data export is created. Medical records are not copied to general audit payloads, CRM or QR codes. Coordination shows parent contact and child names but no clinical results. Specific consent text/version and program terms are retained, and adult-contact consent is separate and revocable. Dynamic family pages are no-store; the customer service worker does not cache clinical pages.

## Theme and validation

Operational consultant pages use the light palette; executive pages use dark. Shared layout, cards, spacing and action patterns follow the existing KPI/consultant reference. Public family pages use a light purple palette.

Run:

```
python manage.py check --settings=greenlife.test_settings
python manage.py makemigrations --check --dry-run --settings=greenlife.test_settings
python manage.py test schools core.tests.test_customer_portal core.tests.test_appointments --settings=greenlife.test_settings
```

The Schools and family checks workflow renders synthetic data at desktop/mobile widths and uploads screenshots. `schools/qa/seed.py` refuses non-debug or non-SQLite settings; never use it in production. This change includes no real family records.

BMI is a raw calculation, with no adult cutoffs or automated pediatric diagnosis. Physician interpretation and follow-up dates are recorded. Age/sex reference percentile charts, accounting integration and automatic reminder delivery are not included in this first implementation.

Executive-only finance uses manually recorded contract amounts for consenting parents who started treatment and manually recorded cohort costs (tomans). Missing values remain unknown, not zero. The difference is shown only when all relevant values are recorded and no registration-date slice is selected; it is not realized accounting profit. Consultants cannot read or modify these financial fields. Follow-up timestamps drive a real action queue; the contact buttons only prepare calls/messages for the coordinator to initiate. Invitation page views include repeats and are labeled accordingly.

GreenLife Me's account sync and family enrollments both reference `CustomerPortalMember`, identified by the existing verified phone session. The next parent-link phase should extend this shared identity in the external Me frontend, without creating another account. The separate frontend integration is not included in this Staff release.

After deployment, `check_school_program --require-niavaran` verifies a unique active Moradi coordinator and renders both consultant and executive dashboard/list/create routes using their real permission scope. The command does not create sessions, send messages, or change production records. Both public and LAN web containers run this read-only check in the existing deploy workflow.

Deployment uses the existing Afserieh self-hosted production workflow only after required checks pass. Never infer production rollout from a code commit. Verify coordinator activation, actual device installation, SMS OTP and a controlled end-to-end enrollment before inviting real schools.
