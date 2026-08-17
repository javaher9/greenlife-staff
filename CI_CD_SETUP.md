# GreenLife Staff — GitHub Self-hosted Deployment

This repository is designed for the current network layout:

Internet → Router → IIS entry point → Ubuntu VM → Docker Compose → Nginx :8085 → Django

The published Docker/Nginx port remains **8085**. PostgreSQL remains external at the address defined in the server `.env` (currently planned as `192.168.40.96:5432`).

## One-time work on the Ubuntu VM

1. Install Docker Engine + Docker Compose plugin, Git, rsync and curl.
2. Create the fixed production directory:

```bash
sudo mkdir -p /opt/greenlife-staff
sudo chown -R <runner-user>:<runner-user> /opt/greenlife-staff
```

3. Create `/opt/greenlife-staff/.env` from `.env.example` and put real secrets **only on the server**. Never commit `.env`.
4. Rotate any password/API key that has previously been shared in chat or screenshots.
5. In GitHub repository settings, open **Actions → Runners → New self-hosted runner** and register the Ubuntu runner.
6. Add the custom runner label:

`greenlife-prod`

The workflow requires these labels:

`self-hosted`, `linux`, `greenlife-prod`

7. Make sure the runner user can run Docker without an interactive password (normally by membership in the `docker` group).
8. Start the runner as a system service using GitHub's generated `svc.sh` commands.

## Deployment behavior

Every push to `main` triggers:

1. Python and shell syntax validation on a GitHub-hosted runner
2. Production Docker image build validation
3. Checkout on the GreenLife production runner
4. Source snapshot for rollback
5. Rsync to `/opt/greenlife-staff` while preserving `.env`, backups and runtime data
6. PostgreSQL + media backup
7. Docker build on the production server
8. Django migrations
9. Container replacement
10. Healthcheck against `http://127.0.0.1:8085/api/health/`
11. Source rollback if healthcheck/deployment fails

Database migrations are not automatically reversed. A database dump is created before migrations so a manual DB restore remains possible.

## Security

- Keep the repository private once connector access is verified.
- Never commit `.env`, database passwords, OpenAI keys, CRM tokens, or reporting API keys.
- Production should use `DISABLE_CSRF=0`, `CSRF_COOKIE_SECURE=1`, and `SESSION_COOKIE_SECURE=1` when IIS serves HTTPS.
- IIS can continue routing/reverse-proxying to the Ubuntu VM as configured by the network administrator; CI/CD does not require inbound SSH from GitHub.
