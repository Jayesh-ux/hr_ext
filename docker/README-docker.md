# hr_ext on a real Docker host

The authoring sandbox could not run containers (proot, no Linux capabilities,
`futex` unavailable), so the scheduler, RQ workers, real e-mail and PDF paths
were built and unit-tested but never executed there. Everything below is the
port to a real host or VM, and it targets exactly those gaps.

## What this directory contains

| File | Purpose |
|---|---|
| `../Dockerfile` | Layers `hrms` + `hr_ext` on `frappe/erpnext:v15` (which ships `wkhtmltopdf`). No secrets baked in. |
| `../apps.json` | Bench app manifest: frappe, erpnext, hrms, hr_ext (all `version-15` / `main`). |
| `docker-compose.yml` | mariadb, redis (cache+queue), backend (gunicorn), websocket, **queue-short**, **queue-long**, **scheduler**, nginx frontend. |
| `.env.example` | Copy to `docker/.env`; holds passwords and pins. **Never commit `docker/.env`.** |
| `verify-host.sh` | The four host-only checks (scheduler/workers, e-mail, PDF, routing). |

## Bring-up

```bash
# 1. Point hr_ext at your repo
$EDITOR apps.json           # replace YOUR_ORG/hr_ext.git

# 2. Configure secrets (Administrator password is passed here, not baked in)
cp docker/.env.example docker/.env
$EDITOR docker/.env         # set DB_ROOT_PASSWORD, ADMIN_PASSWORD, SITE_NAME, ...

# 3. Build the image and start the stack
docker compose -f docker/docker-compose.yml build
docker compose -f docker/docker-compose.yml up -d

# 4. The one-shot `create-site` service installs erpnext + hrms + hr_ext,
#    runs `hr_ext.setup.configure`, enables the scheduler and builds assets.
docker compose -f docker/docker-compose.yml logs -f create-site
```

Open `http://<host>:${HTTP_PORT:-8080}`.

## Secrets

- `docker/.env` (git-ignored) holds `DB_ROOT_PASSWORD` and `ADMIN_PASSWORD`.
- The Administrator password is **never** written into the image or `apps.json`;
  it is passed as an environment variable at runtime. On Swarm/K8s use a real
  secret and map it to the same variable.
- Channel/LLM credentials are supplied either as env
  (`HR_EXT_WHATSAPP_TOKEN`, `HR_EXT_SLACK_BOT_TOKEN`, `HR_EXT_TEAMS_WEBHOOK_URL`,
  `HR_EXT_LLM_API_KEY`, ...) or via the `HR Ext Settings` DocType.

## Verify the sandbox-blocked items

```bash
SITE_NAME=hr.localhost ./docker/verify-host.sh
```

Expected results:

1. **Scheduler + workers** — `scheduler_enabled` is `true`; the hook list shows
   `daily: [hr_ext.tasks.daily_maintenance]`; running the job returns
   `{"scoring": N, "nudges": {...}}`; `docker compose ps scheduler` is `Up`.
   The scheduler fires `daily_maintenance` once per day, which scores attrition
   and sweeps nudges.
2. **Real e-mail** — `send_test_email` returns `{"channel": "email", "ok": true}`.
   With `HR_EXT_NUDGE_CHANNEL=email` in `docker/.env`, live nudges go out by
   mail; the worker log shows the queued message.
3. **PDF** — `render_test_pdf` returns `ok: true` with `pdf_bytes` > 1000
   (uses the image's `wkhtmltopdf`).
4. **Nudge routing** — `show_nudge_routing` returns a real `nudge_hr_user`
   (set `HR_EXT_NUDGE_HR_USER` in `docker/.env`, or let `hr_ext.setup.configure`
   pick the first HR Manager/HR User). No more Administrator fallback.

## Notes

- Payroll/tax figures are **estimates** (each `country_data/*.json` records its
  `tax_year` and `source`); validate with a qualified professional. See the
  main `README.md` disclaimer.
- Pin `ERPNEXT_TAG` to a concrete patch (e.g. `v15.57.5`) for reproducible
  builds instead of the moving `version-15` tag.
