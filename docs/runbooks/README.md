# Runbooks (skeletons — filled in as features land)

| Runbook | Trigger | First actions |
|---|---|---|
| WhatsApp down / number restricted | outbox failures spike, Meta status page | Switch clinics to dashboard booking; enable SMS reminders (P1); pause recall sends; check quality rating |
| Worker stalled | `scheduled_jobs` overdue > 5 min (NFR-5 alarm) | Check worker container + Redis; jobs are durable in Postgres — restart worker, sweeper re-claims |
| DB restore | data loss/corruption | RDS PITR to new instance → verify → swap endpoint; record drill result monthly |
| Personal-data breach (DP-8) | suspected unauthorised access | Contain; preserve logs; notify affected clinics (Data Fiduciaries) immediately; support them with Board notification within 72 h per DPDP Rules — **confirm current legal timeline with counsel**; record in breach register |
| LLM provider outage | NLU timeouts | Automatic button-mode fallback; verify via metrics; no action needed unless > 1 h |
| Exotel outage | no missed-call webhooks | Receptionist logs missed calls manually in dashboard |
