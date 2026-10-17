# syntax=docker/dockerfile:1
#
# hr_ext — runtime image for a real Docker host.
#
# Layered on the official Frappe ERPNEXT v15 image (which already contains
# frappe + erpnext, plus wkhtmltopdf for PDF print formats). We add the HRMS v15
# app and the hr_ext app on top, then build frontend assets. No secrets are
# baked into the image: the admin password, DB password and API keys are passed
# at runtime (docker compose secrets / environment).
#
# Build (from the hr_ext repo root):
#   docker build -t hr_ext:v15 --build-arg ERPNEXT_TAG=<pin> .
#
# The image is consumed by docker/docker-compose.yml, whose services cover the
# worker/scheduler processes the sandbox could not run (queue-short, queue-long,
# scheduler) plus the websocket and frontend.

ARG ERPNEXT_TAG=version-15
FROM frappe/erpnext:${ERPNEXT_TAG}

USER frappe
ENV NODE_ENV=production

# HRMS v15 is required by hr_ext (attendance, leave, payroll doctypes).
ARG HRMS_BRANCH=version-15
RUN bench get-app --branch ${HRMS_BRANCH} https://github.com/frappe/hrms.git

# The app itself. .dockerignore keeps dev/test/log files out.
COPY --chown=frappe:frappe . /home/frappe/frappe-bench/apps/hr_ext
RUN bench get-app /home/frappe/frappe-bench/apps/hr_ext

# Compile frontend assets for the added apps.
RUN bench build --app hrms && bench build --app hr_ext

# One-time site bootstrap + host verification checklist (run as a job).
COPY --chown=frappe:frappe docker/ /home/frappe/docker/
