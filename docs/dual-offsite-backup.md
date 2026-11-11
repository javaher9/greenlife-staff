# GreenLife Staff — External Backup Runbook (staged, NOT deployed)

## Verified by repository inspection
- `scripts/deploy_runner.sh` invokes `./scripts/backup.sh` before migrations.
- DB: `pg_dump -Fc` -> `backups/db_YYYYMMDD_HHMMSS.dump`.
- Media: Docker `media_data` volume -> `backups/media_YYYYMMDD_HHMMSS.tar.gz`.
- Local retention: 14 days AND newest three generations per family by default.
- The media step can skip with a warning, while backup overall still reports success.
- No independent schedule or successful external transfer is established by these files.
- GitHub inspection DOES NOT establish that real backups exist or are restorable.

## Stage A — audit only (read-only)
On production host, in `/home/ubuntu/greenlife-staff-runtime`:
```bash
bash scripts/audit_local_backups.sh
```
Record latest DB/media timestamp and sizes, exit code, and available disk. The audit checks `pg_restore --list` (if installed) and media archive readability. It is NOT a live database restore. Separately verify that all user-uploaded paths live in the `media_data` volume; other bind mounts need explicit coverage. Do not include private patient records in tickets/logs.

## Stage B — provision two destinations
1. Home computer: dedicated always-on restricted storage account, reachable by outbound-only VPN (e.g. WireGuard/Tailscale), with SFTP/REST destination. Do not expose SSH publicly. Protect home PC OS credentials from staff.
2. Independent object storage: S3-compatible private bucket with versioning/object-lock (where supported), dedicated write-only/limited-access user, server-side controls that prevent the production host from deleting historical snapshots.
3. Install `restic` on production. Create a 32+ byte random encryption passphrase in a root-only file under `/etc/greenlife`, BACK IT UP OFFLINE. Without it archives cannot be recovered. Never put keys in GitHub, `.env`, screenshots, or logs.
4. Initialize each empty destination once using `RESTIC_PASSWORD_FILE=/etc/greenlife/restic-password restic -r <repository> init`. Use provider-specific configuration with minimal privilege; keep cloud credentials in a root-only environment file. Do not initialize if an existing repository is expected.

Example `/etc/greenlife/offsite-backup.env` (chmod 600; customize without committing):
```bash
BACKUP_DIR=/home/ubuntu/greenlife-staff-runtime/backups
RESTIC_PASSWORD_FILE=/etc/greenlife/restic-password
RESTIC_REPOSITORY_HOME=sftp:backup-only@home-vpn:/srv/backup/greenlife-staff
RESTIC_REPOSITORY_CLOUD=s3:https://example-object-store.invalid/greenlife-staff
# AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY belong here only on the production host.
```
Ensure `/etc/greenlife/offsite-backup.env` is shell-parseable, root-owned, not readable by others. `RESTIC_REPOSITORY_HOME` and `RESTIC_REPOSITORY_CLOUD` must point to separate storage domains.

## Stage C — scheduled operations
- Make a consistent daily local DB+media backup, independently of deployments. The existing `scripts/backup.sh` prunes to three copies and may skip media; harden it before using as an unattended scheduled job. Run scheduled backup and offsite upload sequentially, not concurrently with deploy.
- Run `bash scripts/offsite_backup.sh` only **after** successful local backup and explicit configuration. It requires BOTH targets to succeed. It never deletes remote snapshots. It refuses incomplete or older-than-24-hour local backup sets.
- Keep remote retention controlled by separate privileged offsite policy (e.g. 30 daily + 12 monthly) in a protected environment; NEVER give production-side credentials permission to delete historical backups. Do not run `restic forget --prune` with the production uploader.
- Separate weekly integrity check (`restic check`) and monthly isolated restoration drill for both destinations. Verify actual table counts, representative media files and app startup with zero access to production write paths. A snapshot listing is not proof of restorability.
- Target RPO 6h for database needs 6h DB backup cadence; a daily schedule does NOT meet that target. With current local backup mechanism, set initial RPO conservatively to 24h and refine after a verified schedule.
- Alert on missing fresh DB/media archive, either failed destination, or absent valid snapshots; monitor free disk and egress.
- Prevent production backup credentials from access to old snapshots' deletion. Protect encryption key and home machine with independent access controls.

## Activation gate
Do not enable cron/systemd timers or merge into production auto-deploy before: (1) read-only audit results, (2) verified home VPN & storage, (3) actual cloud account/bucket and IAM/object lock, (4) secret management, (5) isolated restore drill. No production access, remote endpoint, or credentials are yet available in this chat.
