# Loom Walkthrough Script (target: 3–5 minutes)

Record your screen with the Retell dashboard, this repo, and (optionally) the Google Sheet open in tabs. Suggested pacing below — adjust to your voice.

## 0:00–0:30 — Intro
"This is my AI receptionist for QuensultingAI Dental Clinic, built on RetellAI's Conversation Flow, with a FastAPI backend handling bookings, Google Sheets, and confirmations."

## 0:30–2:00 — Conversation flow design (screen: Retell flow canvas)
- Point at the greeting node → explain it routes on intent, not a single prompt handling everything.
- Walk the emergency path: "Emergency detection happens *before* general routing — a caller in pain gets triaged and transferred immediately, they never get stuck in a booking form."
- Walk the booking path: name → phone → date/time → **check_availability function call** → confirm summary → **book_appointment function call** → success.
- Show the offer-alternative branch: "If the slot's taken, the backend suggests real alternatives from the Sheet, and the caller can pick one without starting over."
- Show the fallback node: "This is bounded — one retry, then it escalates to a human, so we never trap a caller in a loop."
- Mention agent-level settings: interruption sensitivity, responsiveness, backchannel — "this is what makes interruption-handling feel natural; it's an agent setting, not something I had to script node by node."

## 2:00–3:00 — Automation & integrations (screen: this repo / terminal / Sheet)
- Show `retell_functions.py`: "These three endpoints are what the function nodes call."
- Show a live curl test or the Sheet updating after a booking.
- Mention resilience: "If Sheets is down, it retries then falls back to a local log instead of losing the booking. Email and webhook failures never fail the booking itself — they're independent, logged, and reported back as flags."
- Show the email template / Slack or webhook payload landing.

## 3:00–4:00 — Design decisions
- Why Conversation Flow over prompt-only: debuggability, narrow per-turn scope, testable branches.
- Why server-side re-validation at booking time, not just at check-availability: race condition close.
- Why idempotency (`call_id` + `appointment_id`): Retell can retry function calls on network hiccups.
- Why local CSV fallback instead of failing loud: booking data must never be lost even if a downstream service is flaky.

## 4:00–4:30 — Wrap-up
- Quick mention of what's next: reschedule/cancel flow, in-call email capture, multi-location support.
- Thank you / sign-off.

---
**Reminder before recording:** replace the placeholder transfer phone number and `YOUR_BACKEND_DOMAIN` in `conversation_flow.json` with real values, and do at least one live test call through Retell's web simulator so the walkthrough shows a real call, not just the editor.
