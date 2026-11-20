# ADR-0007 Staff auth: phone OTP + short JWT + rotating refresh tokens
Status: accepted
Access JWT 15 min (HS256, `kid`), refresh opaque token hashed in DB with family id; reuse of a rotated token revokes the family (NFR-10). OTP delivery adapter: WhatsApp template / SMS in prod, console fake in dev (blocked in production). Refresh token held in an HttpOnly Secure SameSite=Strict cookie scoped to `/api/v1/auth`; access token in memory on the client.

**Amendment (2026-11-20):** a rotated refresh token presented again within **30 s** of its rotation is treated as a benign race (page reloaded mid-refresh, two tabs) and yields a new token in the same family; after 30 s, reuse revokes the whole family as before. Found during browser testing: a reload during refresh logged the user out. Tests: `test_refresh_reuse_within_grace_is_a_benign_race`, `test_refresh_rotation_and_reuse_detection`. The web client also single-flights refreshes per tab.
