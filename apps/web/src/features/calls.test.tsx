import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { sessionStore } from "@/api/session";
import AdminPage from "@/features/admin/AdminPage";
import MissedCallsPage from "@/features/calls/MissedCallsPage";
import { json, mockFetch, renderApp, tokens } from "@/test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStore.set(null);
});

const call = {
  id: "mc1",
  caller_phone: "+919825012345",
  called_at: "2026-11-23T04:30:00Z",
  last_called_at: "2026-11-23T04:40:00Z",
  repeat_count: 1,
  status: "call_back_needed",
  source: "exotel",
  offer_sent_at: "2026-11-23T04:30:00Z",
  appointment_id: null,
  resolution: null,
  patient_name: null,
  patient_id: null,
};

describe("MissedCallsPage (FR-3.4)", () => {
  it("lists calls to call back and closes one as called back", async () => {
    const { calls } = mockFetch({
      "POST /api/v1/auth/refresh": () => json(tokens()),
      "GET /api/v1/clinic": () => json({ timezone: "Asia/Kolkata" }),
      "GET /api/v1/missed-calls": () => json([call]),
      "POST /api/v1/missed-calls/mc1/resolve": () => json({ ...call, status: "resolved", resolution: "called_back" }),
    });
    renderApp(<MissedCallsPage />, { path: "/missed-calls", route: "/missed-calls" });
    const row = (await screen.findByText("+91 98250 12345")).closest("li")!;
    expect(within(row).getByText("called 2×")).toBeInTheDocument();
    expect(within(row).getByRole("link", { name: /call/i })).toHaveAttribute("href", "tel:+919825012345");
    await userEvent.setup().click(within(row).getByRole("button", { name: "Called back" }));
    expect(await screen.findByText("Marked as called back")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/v1/missed-calls/mc1/resolve")?.body).toContain("called_back");
  });
});

describe("AdminPage (FR-9.4)", () => {
  it("is only reachable by platform admins", async () => {
    mockFetch({ "POST /api/v1/auth/refresh": () => json(tokens()) }); // token without the admin claim
    renderApp(<AdminPage />, { path: "/admin", route: "/admin" });
    expect(await screen.findByText("today page")).toBeInTheDocument();
  });
});
