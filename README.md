# QuensultingAI Dental Clinic — AI Receptionist Voice Agent

An inbound voice receptionist built on **RetellAI Conversation Flow** (node-based, not a single prompt), backed by a **FastAPI** automation service that writes bookings to **Google Sheets** and fires **email + webhook** confirmations.

```
Caller ──(phone)──> RetellAI Agent ──(Conversation Flow nodes)──┐
                                                                  │  function-call webhooks
                                                                  ▼
                                              FastAPI backend (this repo)
                                                  ├─ availability_service  (business rules)
                                                  ├─ sheets_service        (Google Sheets, retry + local fallback)
                                                  ├─ email_service         (SMTP confirmation, patient + staff)
                                                  └─ webhook_service       (outbound webhook, retry)
```

## Repository layout

```
retell_agent/
  conversation_flow.json     # RetellAI Conversation Flow — import this into a new Agent
backend/
  app/
    main.py                  # FastAPI entrypoint, global error handling, /health
    config.py                # env-driven settings
    models.py                # Pydantic schemas + validation
    routers/retell_functions.py   # the 3 webhook endpoints Retell calls
    services/
      availability_service.py     # working-hours + slot logic
      sheets_service.py           # Google Sheets read/write, retries, CSV fallback
      email_service.py            # SMTP confirmation (patient + internal)
      webhook_service.py          # outbound webhook with retry
  requirements.txt
  .env.example
docs/
  architecture.md
  loom_script.md
```

## 1. RetellAI setup

1. In the Retell dashboard, create a new Agent → choose **Conversation Flow** (not single-prompt).
2. Use the JSON editor / import feature to load `retell_agent/conversation_flow.json`.
   - Replace `YOUR_BACKEND_DOMAIN` in the two `tools[].url` fields with your deployed backend URL (see §3).
   - Replace the placeholder transfer number in `node_human_transfer.transfer_destination.number` with the clinic's real front-desk line.
3. Apply the `recommended_agent_settings` block values on the **Agent** settings tab (interruption sensitivity, responsiveness, backchannel, silence timeout) — these are agent-level, not flow-node-level, in Retell.
4. Attach a phone number to the agent (Retell → Phone Numbers → Buy/Import → assign to this agent).
5. Test via Retell's web call simulator before going live on a real number.

> Note: RetellAI's Conversation Flow JSON schema is evolving; if a field name has shifted since this was written, the fastest fix is to open this JSON in Retell's visual flow editor — it will surface schema mismatches directly and you can re-save from the UI.

## 2. Backend setup

```bash
cd backend
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt --break-system-packages   # or omit the flag in a venv
cp .env.example .env
```

### Google Sheets
1. Google Cloud Console → create a Service Account → generate a JSON key → save as `backend/credentials/google_service_account.json`.
2. Create a Google Sheet, add a tab named `Appointments` (or set `GOOGLE_SHEET_TAB_NAME`).
3. Share the sheet with the service account's `client_email` (Editor access).
4. Put the Sheet ID (from its URL) into `.env` as `GOOGLE_SHEET_ID`.
   - The service auto-creates the header row on first write if missing.

### Email (SMTP)
- Easiest: Gmail + an [App Password](https://myaccount.google.com/apppasswords) (not your normal password).
- Or point `SMTP_HOST`/`SMTP_PORT` at SendGrid/Mailgun/etc. SMTP relay.
- Both the patient (if you extend the flow to collect email) and `CLINIC_NOTIFY_EMAIL` (staff) get notified.

### Outbound webhook
- Set `CONFIRMATION_WEBHOOK_URL` to a Slack Incoming Webhook, an n8n Webhook node, a CRM endpoint, etc. Used for both `appointment_booked` and `call_escalated` events (distinguish by the `event` field in the payload).

### Run locally
```bash
uvicorn app.main:app --reload --port 8000
```
Expose it to Retell during development with a tunnel (e.g. `ngrok http 8000`), then use the ngrok HTTPS URL in the flow's tool URLs. For production, deploy to Render/Railway/Fly.io/EC2 behind HTTPS and set `VERIFY_RETELL_SIGNATURE=true` with a shared signing secret.

### Endpoints
| Endpoint | Called by | Purpose |
|---|---|---|
| `POST /webhook/check-availability` | `node_check_availability` | Validates service/hours/day, checks for double-booking, suggests alternatives |
| `POST /webhook/book-appointment` | `node_save_booking` | Re-validates, persists to Sheets (with local CSV fallback), sends email + webhook |
| `POST /webhook/escalate` | optional, before/at `node_human_transfer` | Audit-log + notifies staff when a call is escalated |
| `GET /health` | uptime checks | Liveness probe |

Interactive API docs: `http://localhost:8000/docs`.

## 3. Design decisions & why

- **Conversation Flow, not a mega-prompt.** Each node has a single job (greet, triage emergency, collect one field, call a function, confirm, close). This makes behavior debuggable node-by-node in Retell's transcript view and keeps the LLM's job at each turn narrow, which reduces hallucination and makes branching conditions easy to reason about.
- **Interruptions & natural turn-taking** are handled by Retell's agent-level `interruption_sensitivity` / `responsiveness` / `enable_backchannel` settings (documented in `conversation_flow.json`'s `recommended_agent_settings`), not by conversation logic — that's the correct layer for it.
- **Emergency triage runs before general intent routing** at the top of the flow (`node_emergency_check`), because a caller in pain should never get routed into a multi-step booking form.
- **Fallback has a bounded retry.** `node_fallback` explicitly avoids an infinite clarification loop — after one retry it escalates to a human rather than frustrating the caller indefinitely.
- **Booking data is never lost**, even if Google Sheets is down: writes retry 3x with backoff, then fall back to a local CSV that can be reconciled later. Availability reads fail open (assume not taken) rather than blocking a booking on a transient read error — write-time de-dup on `appointment_id` is the real safety net.
- **Email/webhook failures never fail a booking.** The appointment is already durably saved before either is attempted; failures are logged and reported back as flags (`email_sent`, `webhook_sent`) so the agent can optionally mention it to the caller.
- **Server-side re-validation on booking**, not just at the check-availability step, closes the race condition where two callers check the same slot seconds apart.
- **Idempotency via `call_id` + generated `appointment_id`** protects against Retell retrying a function call on network hiccups causing duplicate rows.

## 4. Testing performed

All three webhook endpoints were exercised locally with Retell-shaped payloads: valid booking, Sunday/out-of-hours rejection with alternative-slot suggestions, invalid service name, malformed date/time, invalid phone number, and the no-credentials fallback path (Sheets unreachable → local CSV; SMTP unreachable → logged and reported as `email_sent: false` without failing the booking). See `docs/architecture.md` for sample requests/responses.

## 5. What's out of scope / next steps

- Real Retell import + live phone number test (do this after deploying the backend and swapping in `YOUR_BACKEND_DOMAIN`).
- Rescheduling/cancellation flow (currently booking-only; same node pattern extends cleanly).
- Collecting patient email in-call for direct confirmation (currently phone-only by design, since email is unreliable to capture by voice; the backend already supports it — just add a `node_collect_email` and pass it through).
- Multi-tenant clinic support, persistent slot calendar (currently Sheets acts as the source of truth for double-booking checks, sufficient for single-location volume).
