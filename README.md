QuensultingAI Dental Clinic — AI Receptionist Voice Agent

An inbound voice receptionist for a dental clinic, built on RetellAI Conversation Flow (a real node/branching graph, not a single mega-prompt) and backed by a FastAPI automation service that persists bookings to Google Sheets and sends email + webhook confirmations.

The agent handles inbound calls end-to-end: greets the caller, answers FAQs, books appointments with real-time availability checking, collects an optional email for a confirmation, and transfers to a human for emergencies or anything it can't resolve.

Architecture

                 ┌────────────────────────────────────────────────┐
Caller ──(call)──▶  RetellAI Agent (Conversation Flow)              │
                 │  greeting → FAQ / booking / message              │
                 │  global emergency & human-request detection      │
                 └───────────────┬──────────────────────────────────┘
                                 │ function-call webhooks (HTTPS)
                                 ▼
                 ┌────────────────────────────────────────────────┐
                 │  FastAPI backend (this repo)                    │
                 │  ├─ availability_service   business-hours rules │
                 │  ├─ sheets_service         Google Sheets +      │
                 │  │                         retry + CSV fallback │
                 │  ├─ email_service          SMTP confirmations   │
                 │  └─ webhook_service        outbound webhook     │
                 └────────────────────────────────────────────────┘

Conversation flow (Retell dashboard):

Greeting → FAQ Handling ⇄ (loop)
        → Book Appointment → Extract Booking Data → check_availability
              ├─ available   → book_appointment → Collect Email
              │                                       ├─ declined → Closing
              │                                       └─ given   → Extract Variables
              │                                                     → send_confirmation_email → Closing
              └─ not available → back to Book Appointment (offers alternatives)

        → Take Message → Closing

[Global] Emergency Detection ─┐
[Global] Human Request Detection ─┴─→ Escalate → Transfer to Front Desk (warm transfer)

The two "global" nodes can trigger from any point in the call, not just from the greeting — a caller can interrupt a booking mid-flow to report an emergency and get routed to a human immediately.

Repository layout

retell_agent/
  conversation_flow_agent_import.json   # Full RetellAI Agent JSON — import via dashboard
backend/
  app/
    main.py                      # FastAPI entrypoint, global error handling, /health
    config.py                    # env-driven settings (pydantic-settings)
    models.py                    # Pydantic request/response schemas + validation
    routers/retell_functions.py  # the webhook endpoints Retell's function nodes call
    services/
      availability_service.py   # working-hours / slot logic
      sheets_service.py         # Google Sheets read/write, retries, CSV fallback
      email_service.py          # SMTP confirmation (patient + internal)
      webhook_service.py        # outbound webhook with retry
  requirements.txt
  .env.example
docs/
  architecture.md
  loom_script.md

API endpoints

All four are called directly by Retell's custom-function nodes, except /health.

EndpointCalled by (Retell node)PurposePOST /webhook/check-availabilitycheck_availabilityValidates service + working hours + day, checks for double-booking against the Sheet, suggests alternate slots when unavailablePOST /webhook/book-appointmentbook_appointmentRe-validates availability server-side (closes the race condition), persists the booking to Google Sheets (falls back to a local CSV log if Sheets is unreachable), notifies clinic staff by emailPOST /webhook/send-confirmation-emailsend_confirmation_emailFired only if the caller opted in and gave an email during the post-booking Collect Email step; sends the patient their own confirmation. Kept as a separate call from booking so the booking itself never depends on email succeedingGET /healthuptime checks / load balancersLiveness probe

Interactive schema docs (once running): http://localhost:8000/docs

Environment variables

See backend/.env.example for the full list with defaults. The ones you must set for a working deployment:

VariablePurposeGOOGLE_SHEET_IDTarget spreadsheet ID (from the Sheet's URL)GOOGLE_SERVICE_ACCOUNT_FILEPath to the service account JSON key (must be Editor on the Sheet)SMTP_USERNAME / SMTP_PASSWORDSMTP auth (Gmail App Password or a transactional SMTP provider)CLINIC_NOTIFY_EMAILInternal staff address that gets a copy of every bookingCONFIRMATION_WEBHOOK_URLOptional — Slack/n8n/CRM webhook for appointment_booked eventsRETELL_WEBHOOK_SIGNING_SECRET + VERIFY_RETELL_SIGNATURE=trueEnable in production so only Retell can call these endpoints

Running locally

bashcd backend
python3 -m venv venv && source venv/bin/activate    # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

For local Retell testing, expose it with a tunnel (ngrok http 8000) and point the Retell function-node URLs at the resulting HTTPS address. Free ngrok URLs change on every restart — remember to update both function nodes in Retell if you restart the tunnel.

Deploying

Any standard ASGI host works (Render, Railway, Fly.io, EC2 behind a reverse proxy). Requirements:


HTTPS (Retell requires it)
google_service_account.json present at the path in GOOGLE_SERVICE_ACCOUNT_FILE (mount as a secret file, don't commit it)
All .env values set as real environment variables/secrets on the host
VERIFY_RETELL_SIGNATURE=true with RETELL_WEBHOOK_SIGNING_SECRET set, once you have Retell's signing secret, so the endpoints reject anything that isn't actually from Retell


Design decisions


Conversation Flow, not a mega-prompt. Each node has one job (greet, ask one thing, call a function, branch, close). This is what's debuggable node-by-node in Retell's transcript view, and it's what the assignment explicitly requires over prompt-only agents.
Emergency triage and human-request detection are global nodes, not just edges off the greeting — a caller can trigger them from anywhere in the call, e.g. mid-booking.
Interruption handling and turn-taking are Retell agent-level settings (interruption_sensitivity, responsiveness, enable_backchannel), not conversation logic — that's the correct layer for it in Retell's architecture.
Email confirmation is a separate step and a separate backend call from booking. The caller is asked for an email only after the appointment is already confirmed and saved — so a caller who has no email, or declines, still gets a fully working booking. send-confirmation-email is a no-op (not an error) when no email was given.
Booking data is never lost. Sheets writes retry 3x with backoff, then fall back to a local CSV that can be reconciled manually if Sheets is ever down. Availability reads fail open (assume "not taken") rather than blocking a booking over a transient read error — the write-time check on appointment_id is the actual duplicate-prevention safety net.
Server-side re-validation at booking time, not just at the earlier check-availability step, closes the race condition where two callers could check the same slot seconds apart.
call_id is treated as optional, with a generated fallback, since Retell's function-call envelope doesn't always populate it — the booking should never fail purely over a missing tracking ID.


Known limitations / next steps


Single-location, single-timezone clinic (CLINIC_TIMEZONE in config); no multi-tenant support.
Google Sheets is the source of truth for slot conflicts — sufficient for single-location call volume, not built for high concurrency.
Booking-only; no reschedule/cancel flow yet (the same node pattern — collect, extract, call function, branch — extends directly to it).
No automated test suite yet; endpoints were validated manually against Retell-shaped payloads covering the happy path, out-of-hours/Sunday rejection, invalid service, malformed date/time, invalid phone, and Sheets/SMTP-unreachable fallback paths.