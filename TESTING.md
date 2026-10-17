# TESTING.md — local manual testing

Everything below runs against the sandbox site **`hr.localhost`** on port **8000**.

## 1. URLs to open

| What | URL |
|---|---|
| Desk (login) | http://hr.localhost:8000/app |
| Attrition dashboard | http://hr.localhost:8000/app/attrition_dashboard |
| Nudge Log (list) | http://hr.localhost:8000/app/nudge-log |
| Leave Application (list) | http://hr.localhost:8000/app/leave-application |
| Expense Claim (list) | http://hr.localhost:8000/app/expense-claim |
| HR Ext Settings (single) | http://hr.localhost:8000/app/hr-ext-settings |

Login is the Administrator user. The rotated password is **not** in this repo;
it lives at `/home/frappe/.admin_password` (mode 0600) on the host that set it.

## 2. Bring the services up

```bash
sudo bash /home/frappe/start-all.sh
```

Starts MariaDB (127.0.0.1:3306), Redis (127.0.0.1:6379) and the web server
(hr.localhost:8000), skips any that are already running, and prints a health
line. The web server is a single process; it does **not** run background
workers or the scheduler (see the caveats at the end).

## 3. Chat endpoint — one curl per intent, in English / Hindi / French

All requests use an Administrator API token. Generate one for your own site
(Desk -> User -> API Access -> Generate Keys) and export it; never commit it.

```bash
BASE=http://hr.localhost:8000/api/method/hr_ext.api.chat.handle_message
# AUTH="Authorization: token <api_key>:<api_secret>"   # set from your own user
EMP=HR-EMP-00001
```

### Leave apply

```bash
for L in en hi fr; do
curl -s -X POST $BASE -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"text\":\"I need leave tomorrow\",\"language\":\"$L\",\"employee\":\"$EMP\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['message']['response'])"
done
```

### Attendance status

```bash
for L in en hi fr; do
curl -s -X POST $BASE -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"text\":\"check my attendance today\",\"language\":\"$L\",\"employee\":\"$EMP\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['message']['response'])"
done
```

### Expense claim (dry-run — shows the company currency)

```bash
for L in en hi fr; do
curl -s -X POST $BASE -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"text\":\"reimburse me 2500\",\"language\":\"$L\",\"employee\":\"$EMP\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['message']['response'])"
done
```

Add `"execute":true` to actually create the draft Expense Claim.

### Salary estimate

```bash
for L in en hi fr; do
curl -s -X POST $BASE -H "$AUTH" -H "Content-Type: application/json" \
  -d "{\"text\":\"what is my take home salary\",\"language\":\"$L\",\"employee\":\"$EMP\"}" \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['message']['response'])"
done
```

Expected (recorded) replies:

| Intent | English |
|---|---|
| leave_apply | `Sure Arjun Mehta, I've applied for your leave from <date> to <date>.` |
| attendance_status | `Your attendance for today is: Not marked.` |
| expense_claim | `Expense claim request received for 2500.0 (INR). Draft created as (dry-run).` |
| salary_information | `Your estimated take-home for a monthly gross of 50000.0 (INR) is 48000.0 (INR) in India, assuming standard deductions.` |

## 4. Trigger the background jobs manually

The scheduler cannot run in the sandbox, so run its entry points by hand:

```bash
runuser -u frappe -- bash /home/frappe/run-bench.sh --site hr.localhost \
  execute hr_ext.tasks.daily_maintenance      # score attrition + sweep nudges (what the scheduler calls)

runuser -u frappe -- bash /home/frappe/run-bench.sh --site hr.localhost \
  execute hr_ext.tasks.score_attrition        # attrition scoring only

runuser -u frappe -- bash /home/frappe/run-bench.sh --site hr.localhost \
  execute hr_ext.tasks.sweep_nudges           # nudge sweep only
```

Check the scheduler wiring and routing:

```bash
runuser -u frappe -- bash /home/frappe/run-bench.sh --site hr.localhost \
  execute hr_ext.verify.check_scheduler
runuser -u frappe -- bash /home/frappe/run-bench.sh --site hr.localhost \
  execute hr_ext.verify.show_nudge_routing
```

## 4b. Foreign-exchange paths (AED, USD)

`base_exchange_rate` resolves a currency three ways: an ERPNext
`Currency Exchange` record, its inverse, or the rule's sample
`exchange_rate` as a fallback. Show every path for AED and USD:

```bash
runuser -u frappe -- bash /home/frappe/run-bench.sh --site hr.localhost \
  execute hr_ext.verify.fx_evidence
```

It temporarily creates `Currency Exchange` records, prints the resolved
`(rate, source)` for the direct, inverse and fallback paths, then removes them.
Expected sources: `Currency Exchange`, `Currency Exchange (inverse)`,
`fallback:rule.exchange_rate` (plus `base (1:1)` for INR).

## 5. Demo data — make every nudge rule fire

```bash
runuser -u frappe -- bash /home/frappe/run-bench.sh --site hr.localhost \
  execute hr_ext.demo_data.run
```

`run` creates the conditions and returns the resulting `Nudge Log`:

- `pending_leave_approval` — inserts a Leave Application draft (after_insert trigger)
- `pending_expense_approval` — inserts an Expense Claim draft (after_insert trigger)
- `probation_ending` — sets a confirmation date 15 days out
- `high_attrition_risk` — emits a nudge with a forced score of 0.82 (the sweep
  would otherwise recompute the score first, so this is forced for the demo)
- `missing_attendance` — any active employee with no attendance marks

Then open **http://hr.localhost:8000/app/nudge-log** and watch it fill. Remove
the demo artifacts with:

```bash
runuser -u frappe -- bash /home/frappe/run-bench.sh --site hr.localhost \
  execute hr_ext.demo_data.cleanup
```

## 5b. Nationality (UAE/GCC social security)

Stock `Employee` has no nationality column, so `hr_ext` ships the
`hr_ext_nationality` **Custom Field** (Link to Country) via `fixtures`; it is
imported on install and every `migrate`. Set it on an Employee to make
nationality-restricted schemes apply:

```bash
# a GCC national: UAE GPSSA is withheld
runuser -u frappe -- bash /home/frappe/run-bench.sh --site hr.localhost \
  set-value "Employee" "HR-EMP-00001" "hr_ext_nationality" "United Arab Emirates"
```

`test_nationality_slip` submits a real Salary Slip for a GCC national and
asserts the `on_submit` handler annotated it; `test_nationality_missing`
asserts that a missing/blank nationality (or a non-GCC one) leaves the scheme
unapplied. The missing-field warning is emitted at most once per process.

## 6. Test suites

```bash
# Pure unit tests (no DB, no site):
runuser -u frappe -- bash -lc "cd /home/frappe/frappe-bench/apps/hr_ext && \
  /home/frappe/frappe-bench/env/bin/python -m unittest discover -s hr_ext/tests"

# Full app suite (needs the site):
runuser -u frappe -- bash /home/frappe/run-bench.sh --site hr.localhost \
  run-tests --app hr_ext
```

## 7. What does NOT work in this sandbox

The scheduler, queue workers, real e-mail delivery and PDF/print output need a
real host (see `docker/README-docker.md`). On a Docker host run
`docker/verify-host.sh` and the same `run-tests` command inside the backend
container to exercise them.
