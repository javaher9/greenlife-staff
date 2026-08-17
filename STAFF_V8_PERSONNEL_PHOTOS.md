# GreenLife Staff v8 — Personnel Photos

## Added
- Employee avatar upload from personal profile
- Manager upload/change employee photo from personnel list
- Large profile hero background using employee photo with readable overlay
- Small employee avatars in personnel list, attendance team, automatic KPI, KPI records, report list, and app header
- Graceful initials placeholder when no photo exists
- Upload validation: max 5 MB; JPEG/PNG/WebP browser picker
- Existing `EmployeeProfile.avatar` field is reused; no database migration is required for this feature
- Media files remain under `MEDIA_ROOT/avatars/`

## Deployment note
Ensure `/media/` is persisted and served by the production reverse proxy. Existing Docker volume/media settings should remain enabled.
