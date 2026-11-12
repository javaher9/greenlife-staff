# Schools and family program

The Staff management menu and authorized Niavaran coordinator get a Schools workspace. The coordinator creates schools/cohorts, capacity, dates and terms, and activates admission without owner approval. Organizations are separate from cohorts so company programs can be added later without renaming school data.

## Routes and workflow

- `/schools/`: management and branch-scoped coordinator dashboard.
- `/schools/new/`: school/cohort creation and immediate link/QR generation.
- `/schools/<id>/card/`: printable invitation, Save as PDF, downloadable QR image.
- `/customer/schools/<uuid>/`: public school invitation, existing SMS OTP verification, parent consent and registration.
- `/customer/family/`: authenticated family records, separate adult-consultation choice, appointment status and clinical reports.
- `/schools/clinical/`: branch-scoped physician workspace; consultants cannot read/write medical assessments.

The customer web portal gains a `گرین‌لایف من` PWA manifest with `/customer/` scope. This is an installable customer web module, not a release to Apple/Google stores or an update to a separately hosted ME frontend. Installation activation uses the browser standalone signal; this is an onboarding condition, never an authentication or security boundary. An existing parent must use the same verified phone after installation. Native installation and external ME frontend integration still require device/production verification.

Capacity counts families in ready/booked/attended states, not children. Registration before activation does not reserve capacity; the landing page discloses this. Program-row locks serialize admission, coordinator updates and cancellation. Duplicate parent registrations reuse the same record; a family can add children. Full cohorts keep activated families on the waiting list. Rechecking capacity or coordinator promotion admits waiting families only when places exist.

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

BMI is a raw calculation, with no adult cutoffs or automated pediatric diagnosis. Physician interpretation and follow-up dates are recorded. Age/sex reference percentile charts, financial ROI attribution and automatic reminder delivery are not included in this first implementation.

Deployment uses the existing Afserieh self-hosted production workflow only after required checks pass. Never infer production rollout from a code commit. Verify coordinator activation, actual device installation, SMS OTP and a controlled end-to-end enrollment before inviting real schools.
