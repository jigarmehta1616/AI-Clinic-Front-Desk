# AI Agent Design

> **Status (M3):** steps 1–5 and 7–9 are implemented deterministically (`modules/assistant/text.py`, `flows.py`, `pipeline.py`) — the "button-only" mode from FRD §9 is complete and is what runs today. Step 6 (LLM NLU via LangGraph) is M4 and will only replace `detect_intent` / date parsing when they return nothing.

**Principle: the LLM understands, deterministic code decides and acts.** (ADR-006)

## Pipeline (worker `process_inbound_event`)
1. **Tenant + patient resolution** — by WhatsApp `phone_number_id` (own number) or clinic code (shared number).
2. **Conversation mode** — if `mode=staff` (handed over), store message, notify inbox, stop.
3. **Hard commands (no LLM)** — STOP/બંધ/रोकें → opt-out (FR-2.9); button/list replies carry structured payloads (`slot:<iso>`, `appt:<id>:reschedule`) and go straight to the state machine.
4. **Safety screen (no LLM)** — emergency lexicon (gu/hi/en + transliterations) → emergency template + `handover(emergency)` + staff alert. Medical lexicon → polite deferral + `handover(medical)`.
5. **Consent gate (DP-1)** — new patient: send consent notice (language-detected), buttons Agree / Disagree. Nothing else proceeds until agreed.
6. **NLU (LLM, structured output)** — `{intent, doctor_hint, date_hint, time_of_day, language, is_medical, confidence}`. Input = redacted text + clinic doctor names + today's date. Small model, temperature 0, 2 s timeout.
7. **Intent router / LangGraph state machine** — nodes: `faq`, `booking` (select doctor → date → slots → identity → confirm), `reschedule`, `cancel`, `token`, `queue_status`, `handover`, `dsr`, `fallback_menu`.
8. **Tools** — only these, each a thin wrapper over a module service with Pydantic-validated args and tenant context injected (never model-supplied): `get_clinic_faq, get_available_slots, create_booking, reschedule_booking, cancel_booking, issue_token, get_queue_status, confirm_appointment, request_staff_handover, create_followup, opt_out`.
9. **Reply** — rendered from the template catalogue in the patient's language (gu/hi/en). The LLM does **not** write free-text replies to patients in v1 except FAQ paraphrase, which is restricted to clinic profile facts and post-checked.

## Fallbacks
* LLM timeout/error/low confidence (<0.6) → button menu (Book · Reschedule/Cancel · Token · Queue status · Talk to staff). This is also the full "no-AI" mode (FRD §9).
* Two consecutive misunderstandings → handover(unclear).

## Language
Detection = script heuristics (Gujarati block U+0A80–0AFF, Devanagari U+0900–097F) + LLM label for romanised text. Preference stored on the patient; replies use it.
Date phrases (`kal`, `aavti kale`, `parso`, `savare/sawar`, `bapore`, `saanje/shaam`) are resolved by a deterministic parser first; LLM only if the parser fails.

## Observability
Each turn → Langfuse trace (redacted input, model, tokens, cost, latency, chosen tool). Cost aggregated per clinic for NFR-12.

## Evaluation
`tests/assistant/fixtures/*.yaml`: utterance → expected intent/entities/safety class, in gu/hi/en/mixed. Run against the real model in a nightly job (not in CI unit runs); deterministic layers are unit-tested in CI.
