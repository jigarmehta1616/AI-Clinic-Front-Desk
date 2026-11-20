---
name: recall-and-revenue
description: Recall rules, follow-ups, treatment plans, no-show rebooking and recovered-revenue attribution. Use for modules recall, reminders (no-show) and reports.
---
# Recall and revenue
**Purpose** Bring patients back and prove it in rupees — honestly.
**When to use** FR-5.x, FR-6.x, FR-7.3; BR-7, BR-8, BR-11, BR-12.
**Required context** `modules/recall`, `modules/reports`, `.claude/skills/whatsapp-integration`.

## Engineering rules
- Recall lifecycle: `scheduled → sent → followup_1 → followup_2 → lapsed | booked | cancelled | opted_out`. Defaults: follow-ups at +3 d and +7 d, max 2 (FR-6.4).
- At send time: skip if opted out; defer to 08:00 inside quiet hours; defer if another recall from this clinic reached the patient < 3 days ago (BR-8).
- Dental and physio specialty templates seed `recall_rules` at onboarding (FR-1.6).
- Bookings from recall / missed-call / no-show messages carry `source` + `source_ref_id`; attribution window 7 days (open question Q6).
- Attribution row only when the appointment becomes arrived/completed or its token completes (BR-11). `UNIQUE(appointment_id)` prevents double counting. Fee snapshot = doctor fee at that moment (BR-12).
- Every revenue figure is labelled "Estimated".

## Validation checklist
- [ ] Booking without arrival is not counted
- [ ] Repeated status changes do not double count
- [ ] Quiet hours, 3-day limit and opt-out tests pass
