import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { json, mockFetch, tokens } from "@/test/utils";

import { ApiError, api, unwrap } from "./client";
import { sessionStore } from "./session";

describe("auth client (ADR-0007)", () => {
  beforeEach(() => sessionStore.set({ accessToken: "old", clinicId: "c1", role: "owner", doctorId: null, isPlatformAdmin: false, expiresAt: 0 }));
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStore.set(null);
  });

  it("refreshes once for concurrent 401s and retries each request with the new token", async () => {
    let refreshes = 0;
    const { calls } = mockFetch({
      "GET /api/v1/clinic": (_u, req) =>
        req.headers.get("Authorization") === "Bearer new" ? json({ name: "Smile" }) : json({ error: { code: "unauthorized", message: "x" } }, 401),
      "GET /api/v1/auth/me": (_u, req) =>
        req.headers.get("Authorization") === "Bearer new" ? json({ phone: "+91" }) : json({ error: { code: "unauthorized", message: "x" } }, 401),
      "POST /api/v1/auth/refresh": () => {
        refreshes += 1;
        return json({ ...tokens(), access_token: "new" });
      },
    });
    const [a, b] = await Promise.all([unwrap(api.GET("/api/v1/clinic")), unwrap(api.GET("/api/v1/auth/me"))]);
    expect(a).toEqual({ name: "Smile" });
    expect(b).toEqual({ phone: "+91" });
    expect(refreshes).toBe(1); // single flight: a second rotation would trip reuse detection
    expect(sessionStore.get()?.accessToken).toBe("new");
    expect(calls.filter((c) => c.key === "GET /api/v1/clinic").map((c) => c.auth)).toEqual(["Bearer old", "Bearer new"]);
  });

  it("signs out when the refresh token is rejected", async () => {
    mockFetch({
      "GET /api/v1/clinic": () => json({ error: { code: "unauthorized", message: "expired" } }, 401),
      "POST /api/v1/auth/refresh": () => json({ error: { code: "refresh_reused", message: "reuse" } }, 401),
    });
    await expect(unwrap(api.GET("/api/v1/clinic"))).rejects.toBeInstanceOf(ApiError);
    expect(sessionStore.get()).toBeNull();
  });

  it("surfaces the server's error code and message", async () => {
    mockFetch({
      "POST /api/v1/appointments": () => json({ error: { code: "slot_taken", message: "that slot was just taken", details: {} } }, 409),
    });
    const err = await unwrap(
      api.POST("/api/v1/appointments", { body: { doctor_id: "d", patient_id: "p", slot_start: "2026-11-24T04:30:00Z", source: "staff" } }),
    ).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect((err as ApiError).code).toBe("slot_taken");
    expect((err as ApiError).status).toBe(409);
  });

  it("maps network failures to a friendly error", async () => {
    vi.stubGlobal("fetch", vi.fn(() => Promise.reject(new TypeError("Failed to fetch"))));
    const err = (await unwrap(api.GET("/api/v1/clinic")).catch((e: unknown) => e)) as ApiError;
    expect(err.code).toBe("network_error");
  });
});
