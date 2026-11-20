# ADR-0005 Queue ordering algorithm (BR-6)
Status: accepted (pending pilot validation, Q8)
Pure function over a session's entries at time `now`:
1. **Due booked**: arrived booked entries with `slot_start <= now` → earliest `slot_start`.
2. else **walk-ins** in token order (issue order = arrival order).
3. else **early booked**: arrived booked with future slots → earliest `slot_start`.
The FRD's patient-journey diagram (Booking → Reminders → Arrived? yes → Token queue) confirms that booked patients join the token queue when they arrive. Skipped entries leave the order; "recall" re-queues a skipped entry to be called next. Token numbers are one per-session sequence; booked patients receive theirs on arrival. Projection for wait time simulates the rule forward using avg consult time (default slot length until FR-4.7 data exists), treating not-yet-arrived bookings as arriving at `slot_start`.
