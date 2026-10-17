# hr_ext

AI-native HR extensions for **Frappe HR v15** (`frappe` + `erpnext` + `hrms`,
all on `version-15`). Ships as a single custom app — the `erpnext`/`hrms` core
is never modified.

## Features at a glance

| # | Feature | Where | Hooks / surface |
|---|---|---|---|
| 1 | Conversational layer | `hr_ext/nlp`, `hr_ext/channels`, `hr_ext/api/chat.py` | whitelisted API `hr_ext.api.chat.handle_message`; WhatsApp/Slack/Teams/Mock adapters; optional LLM classify |
| 2 | Multi-country payroll rules | `hr_ext/payroll` | declarative `country_data/*.json`; `doc_events` on `Salary Slip` `on_submit` |
| 3 | Attrition analytics | `hr_ext/analytics` | logistic scoring model; `Attrition Risk Score`; desk page `/app/attrition_dashboard` |
| 4 | Real-time nudges | `hr_ext/nudges` | `doc_events` (Leave/Expense **after_insert**) + daily scheduler sweep; `Nudge Log`; channels: mock/email/WhatsApp/Slack/Teams |
| 5 | i18n for UI + chatbot | `hr_ext/i18n`, `translations/*.po` | chatbot template translation (hi, fr) |

All computation lives in **plain Python functions with no Frappe import**
(`engine.py`, `model.py`, `rules.py`, `intents.py`, `chatbot.py`,
`channels/*`), unit-tested standalone. Frappe modules are thin glue that only
wire these into hooks/API.

## Interesting files
- `hr_ext/payroll/engine.py` + `payroll/country_data/{india,uae,usa}.json` — add a country by adding one JSON file. Rules cover income-tax slabs, social security, currency, and config-driven **statutory deductions** (India ESI and Maharashtra Professional Tax).
- `hr_ext/fixtures/custom_field.json` — shipped Custom Fields (the `Employee.hr_ext_nationality` field that drives nationality-restricted schemes like UAE GPSSA). Imported on install and every `migrate`.
- `hr_ext/analytics/model.py` — deterministic, explainable attrition model.
- `hr_ext/nudges/rules.py` — pure nudge decisioning.
- `hr_ext/channels/base.py`, `mock.py`, `whatsapp.py`, `slack.py`, `teams.py` — channel transport with env credentials.
- `hr_ext/nlp/intents.py` + `nlp/llm.py` — rule-based parser with optional LLM override (output is allowlist-validated).
- `hr_ext/i18n/chatbot.py` + `i18n/languages/*.json` — template translation layer.

## Install (any host)

```bash
bench init --apps_path ./apps.json frappe-bench   # or add the app to an existing bench
bench get-app hr_ext https://github.com/YOUR_ORG/hr_ext.git
bench --site <site> install-app hr_ext
bench migrate
```

## Verification
- Pure unit tests (no DB): `python -m unittest discover -s hr_ext/tests`
- Frappe tests (needs a site): `bench --site <site> run-tests --app hr_ext`
- Manual:
  - Attrition: `bench --site <site> execute hr_ext.tasks.score_attrition`, then open `/app/attrition_dashboard`.
  - Nudges: `bench --site <site> execute hr_ext.tasks.sweep_nudges` and read the `Nudge Log`.
  - Chat: POST to `/api/method/hr_ext.api.chat.handle_message` with `{"text": "I need leave tomorrow", "employee": "<emp>"}`.
  - Demo data for every nudge rule: `bench --site <site> execute hr_ext.demo_data.run`.
  - FX paths (AED/USD, direct + inverse + fallback): `bench --site <site> execute hr_ext.verify.fx_evidence`.
- **Step-by-step local walkthrough: [`TESTING.md`](TESTING.md)** (URLs, per-intent
  `curl` in English/Hindi/French, job triggers, demo data).

## Conversational layer: classifier behaviour

**Default classifier is rule-based and needs no key or network.** Every message
is classified by the deterministic parser in `hr_ext/nlp/intents.py`
(keyword + date/amount extraction). This is the only classifier active on a
fresh install, and all tests exercise it.

The LLM is an **opt-in override that is OFF by default**:

- Toggle: `HR Ext Settings → llm_enabled` (unchecked by default).
- Endpoint: `HR Ext Settings → llm_endpoint` (a full chat-completions URL).
- Model: `HR Ext Settings → llm_model`, or env `HR_EXT_LLM_MODEL`.
- Key: `HR Ext Settings → llm_api_key` (stored encrypted via Frappe
  `get_password`), or env `HR_EXT_LLM_API_KEY`.

Provider: any OpenAI-compatible `/chat/completions` endpoint (the request body
is `{model, temperature, messages}` and the reply is parsed for a JSON
`{"action": ...}`). No SDK is required — it uses `urllib`.

**Exactly what is sent when enabled:** the raw text of the single user message
(`messages: [{system: <fixed 6-line classifier prompt>}, {user: <message text>}]`).
The request does **not** attach any employee record, name, salary, leave balance
or other database field. Note that the user's own message text is sent verbatim,
so it can *contain* personal data if the employee types it — the classifier does
not strip names, amounts or identifiers from the text. Treat the configured
endpoint as a data processor: prefer a **self-hosted model (e.g. Ollama at
`http://localhost:11434/v1/chat/completions`)** so no message leaves your
network, and only enable an external provider for non-sensitive deployments.

**The LLM only performs intent classification — it never calls tools.** The
model returns a single label, which is validated against a fixed allowlist
(`llm.VALID_ACTIONS`: `leave_apply, leave_balance, attendance_status,
expense_claim, salary_information, help`) by `llm.validate_action`. Any other
output — including prompt-injection strings such as `delete_user` or `raw_sql`,
or free text — is rejected and the deterministic parser is used. The validated
label only selects an action; parameters (dates, amounts, employee) are always
re-derived by the rule parser and the server-side dispatcher, so a compromised
model cannot inject parameters. If the call fails, times out, or returns
anything other than a valid action, the code falls back to the rule-based parser
(`_classify` in `hr_ext/api/chat.py`), so the chatbot works with no key
configured.

## Channel credentials (environment variables; also settable in HR Ext Settings)
- Email: uses the site's outgoing account (`frappe.sendmail`); `HR_EXT_EMAIL_NOW=1` sends synchronously.
- WhatsApp: `HR_EXT_WHATSAPP_TOKEN`, `HR_EXT_WHATSAPP_PHONE_ID`
- Slack: `HR_EXT_SLACK_BOT_TOKEN` (optional `HR_EXT_SLACK_DEFAULT_CHANNEL`)
- Teams: `HR_EXT_TEAMS_WEBHOOK_URL`
- LLM: `HR_EXT_LLM_API_KEY`, `HR_EXT_LLM_MODEL` (endpoint configured in Settings)
- Nudge routing/channel: `HR_EXT_NUDGE_HR_USER`, `HR_EXT_NUDGE_CHANNEL`

## Docker

`Dockerfile`, `apps.json` and `docker/` provide a production-shaped port to a
real Docker host (mariadb, redis, gunicorn, websocket, **queue workers**,
**scheduler**, nginx). Bring-up and the four host-only verification checks
(scheduler/workers, real e-mail, PDF, nudge routing) are in
[`docker/README-docker.md`](docker/README-docker.md). Secrets live in
`docker/.env` (git-ignored) and are never baked into the image.

## Sandbox caveats
Built and verified in a Termux proot Debian sandbox where **Docker cannot run**
and the **scheduler/workers** crash (`futex`). Consequences:
- Scheduled/queued delivery (`scheduler_events`, e-mail/attachments) is
  **implemented and unit-tested here, executed only on a real host** — verify
  with `docker/verify-host.sh`.
- PDF print output is untested here (no `wkhtmltopdf`); the Docker image ships
  it and `hr_ext.verify.render_test_pdf` exercises it.
- Real WhatsApp/Slack/Teams calls are untested here; adapters fall back to
  mocks and assert credential validation in unit tests.

## Disclaimer
Payroll and tax figures are *estimates* for planning and communication — not
legal payroll advice. Each `country_data/*.json` records its `tax_year` and
`source` and is marked `illustrative`; validate per-country rules (tax slabs,
social security, statutory deductions such as ESI and state Professional Tax,
currency) with a qualified professional before use.

Note on stock Frappe HR coverage: the India regional setup only *categorises*
Professional Tax (a `component_type` + a report) and provides **no** ESI and no
automatic state-slab computation. `hr_ext` models both as config-driven
`statutory_deductions`; Professional Tax is state-specific and the shipped slab
is Maharashtra's.