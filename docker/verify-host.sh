#!/usr/bin/env bash
# Host verification for the four items the sandbox could not run.
#
# Usage (from the repo root, with the compose stack up):
#   SITE_NAME=hr.localhost ./docker/verify-host.sh
#
# It shells every check through the `backend` container so it uses the same
# bench, workers and DB as the running site.
set -euo pipefail

SITE="${SITE_NAME:-hr.localhost}"
COMPOSE="${COMPOSE:-docker compose -f docker/docker-compose.yml}"

exec_site() { $COMPOSE exec -T backend bench --site "$SITE" "$@"; }
run()      { exec_site execute "$@"; }

echo "==================================================================="
echo "1) SCHEDULER + WORKERS"
echo "   a) hook wiring + scheduler switch:"
run hr_ext.verify.check_scheduler
echo "   b) run the scheduled daily job once (attrition scoring + nudge sweep):"
run hr_ext.verify.run_daily_job
echo "   c) confirm the scheduler process is alive:"
$COMPOSE ps scheduler

echo "==================================================================="
echo "2) REAL E-MAIL DELIVERY THROUGH THE NUDGE CHANNEL"
run hr_ext.verify.send_test_email
echo "   tail of the worker log (look for the queued/sent mail):"
$COMPOSE logs --tail=20 queue-long queue-short || true

echo "==================================================================="
echo "3) PDF PRINT FORMAT"
run hr_ext.verify.render_test_pdf

echo "==================================================================="
echo "4) NUDGE ROUTING AWAY FROM ADMINISTRATOR"
run hr_ext.verify.show_nudge_routing

echo "==================================================================="
echo "Done. Expected: scheduler_enabled true; daily job returns scored/decisions;"
echo "email ok=true; pdf_bytes > 1000; nudge_hr_user is a real HR user."
