# Website consultation: approved Ghazal / Niavaran design

This public acquisition page is LIGHT ivory / plum on all screen sizes, following Ali's explicit approved mobile and desktop mockups. KPI and the equivalent public form were inspected; this is not a Staff operational or executive page. Changes are isolated to `/website/lead/` and do not restyle other public/Instagram forms.

The existing URL, POST field names, CSRF protection, database transaction, duplicate protection, source-page/CTA attribution, website source profile and call-center routing remain intact. Only this view's template and input presentation change. All existing links to this URL continue to work, including `page` and `cta` query strings. Both visible return links use the canonical `https://greenlifeclinics.com/`.

The form is native HTML. Optional details expand with native `details`, including without JavaScript, and reopen when containing a value/error. Phone digits are translated to Latin on input; the existing server normalization remains authoritative. The submit guard resets on pageshow so browser Back does not strand a disabled button. Success and error states use the same visual design.

## Assets

Photo: built-in image editor extracted the photo panel from the user-approved desktop mockup (2026-11-24): same Ghazal identity, emerald suit and purple shawl in the supplied real Niavaran lounge. Prompt: extract the photographic right panel, preserve face/pose/room, remove website UI/text/logo; no creative reinterpretation. Source `exec-5a99a78d-2a03-41d1-aaf3-23a9f9fc34d0.png`. Encoded to WebP quality 92, 1198x1313, 235522 bytes. No crop/face alteration during encoding.

The official original GreenLife logo is bundled unchanged and tinted via its alpha in CSS. Vazirmatn is bundled locally with its OFL license. Photography, logo, font, CSS and JavaScript are served by the existing Staff static-file deployment, with no Vercel/WordPress runtime asset dependency.

## Pre-deployment validation

- 14 Django tests passed: new public consultation tests, existing lead ingestion and Telegram lead tests. These use only Django's isolated test database; no production lead was submitted.
- Coverage includes canonical GET, invalid phone, details retained after errors, local successful creation with Persian country-code input, source/CTA retention, website routing invocation, duplicate blocking, CSRF enforcement and isolation from the other public form.
- JavaScript event smoke checks passed for Persian/Arabic digit conversion, duplicate-submit prevention and pageshow reset.
- Python and JavaScript syntax plus git diff whitespace checks passed.
- Actual rendered Django template visually checked in desktop and 390px browser-width layouts. Input labels, native required validation, optional details and server error state were inspected. Not a physical-phone test.

Live deployment and end-to-end call-center delivery are separate checks; a source commit alone does not verify them. No authorized production test phone was provided, so no real lead should be submitted for this visual change.
