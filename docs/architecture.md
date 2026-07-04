# Architecture & Flow Detail

## Conversation Flow node map

```
node_greeting
 ├─ emergency-language ───────────────► node_emergency_check ──► node_human_transfer
 ├─ wants to book ────────────────────► node_intent_booking
 ├─ general question ─────────────────► node_faq_router
 ├─ asks for human ───────────────────► node_human_transfer
 └─ unclear ──────────────────────────► node_fallback

node_faq_router
 ├─ another question ─────► (loops to self)
 ├─ now wants to book ────► node_intent_booking
 ├─ out-of-scope/needs human ► node_human_transfer
 └─ done ─────────────────► node_closing

node_intent_booking (asks which service)
 ├─ valid service ─────────► node_collect_name
 └─ invalid/unclear ───────► node_fallback

node_collect_name ─► node_collect_phone ─► node_collect_datetime ─► node_check_availability [FUNCTION]
 ├─ available ─────────────► node_collect_extra_details ─► node_confirm_booking_summary
 │                                                            ├─ confirmed ─► node_save_booking [FUNCTION]
 │                                                            └─ correction ─► node_collect_name
 ├─ not available ─────────► node_offer_alternative
 │                              ├─ picks new time ─► node_check_availability (loop)
 │                              └─ gives up ────────► node_human_transfer
 └─ function error ────────► node_fallback

node_save_booking [FUNCTION]
 ├─ success ─► node_booking_success ─┬─ more questions ─► node_faq_router
 │                                    └─ done ───────────► node_closing
 └─ failure ─► node_booking_failure ─┬─ wants transfer ─► node_human_transfer
                                      └─ ok with callback ► node_closing

node_fallback
 ├─ clarifies → booking ─► node_intent_booking
 ├─ clarifies → question ► node_faq_router
 └─ 2nd failure/frustrated ► node_human_transfer

node_human_transfer [TRANSFER_CALL] ─(if transfer fails)─► node_closing
node_closing ─► node_end [END]
```

18 nodes total: 13 conversation nodes, 2 function nodes, 1 transfer node, 1 end node, plus the implicit branch logic expressed via natural-language edge conditions (Retell evaluates these with the underlying LLM at each turn — this is what "conversation flow branching" means in Retell, as opposed to a single prompt trying to hold the entire state machine in its head).

## Why function nodes wait for results (`wait_for_result: true`)

Both `check_availability` and `book_appointment` block the flow until the backend responds, with a short spoken filler ("Let me check that slot...") so the caller doesn't experience dead air — this directly satisfies "handle interruptions/latency gracefully" without needing custom node logic; it's a first-class Retell function-node feature.

## Sample payloads (as tested against the running backend)

**Request** — `POST /webhook/check-availability`
```json
{
  "call": { "call_id": "call_123" },
  "name": "check_availability",
  "args": {
    "service_requested": "Dental Cleaning",
    "preferred_date": "2026-07-06",
    "preferred_time": "11:00"
  }
}
```
**Response**
```json
{ "available": true, "reason": null, "suggested_slots": [] }
```

**Request** (Sunday, rejected with alternatives)
```json
{ "args": { "service_requested": "Root Canal Treatment", "preferred_date": "2026-07-05", "preferred_time": "11:00" } }
```
**Response**
```json
{
  "available": false,
  "reason": "The clinic is closed on Sundays.",
  "suggested_slots": ["2026-07-06 09:30", "2026-07-06 10:00", "2026-07-06 10:30"]
}
```

**Request** — `POST /webhook/book-appointment`
```json
{
  "call": { "call_id": "call_test_999" },
  "name": "book_appointment",
  "args": {
    "caller_name": "Rahul Sharma",
    "caller_phone": "+91-9876543210",
    "service_requested": "Dental Cleaning",
    "preferred_date": "2026-07-06",
    "preferred_time": "11:00",
    "is_returning_patient": false,
    "insurance_provider": "none",
    "call_id": "call_test_999"
  }
}
```
**Response** (Google Sheets not configured in this sandbox — correctly fell back to local CSV, did not fail the booking)
```json
{
  "success": true,
  "appointment_id": "APT-ECCB55AB",
  "message": "Appointment confirmed.",
  "email_sent": false,
  "webhook_sent": false
}
```

## Failure-mode matrix

| Failure | Behavior |
|---|---|
| Google Sheets unreachable | Retry 3x w/ backoff → write to local CSV (`data/fallback_bookings.csv`) → booking still succeeds |
| SMTP unreachable/misconfigured | Logged, `email_sent: false`, booking still succeeds |
| Outbound webhook unreachable | Retry 3x → logged, `webhook_sent: false`, booking still succeeds |
| Caller gives invalid phone/date/time | Pydantic validation rejects → flow's fallback/re-collect branch triggers, no 500 surfaced mid-call |
| Two callers book same slot near-simultaneously | Server re-checks availability at save time (not just at the earlier check-availability step) |
| Retell retries a function call (network hiccup) | `appointment_id` + row-existence check prevents duplicate Sheets rows |
| Function endpoint times out or errors | Flow edge routes to `node_fallback` rather than the agent going silent or crashing the call |
