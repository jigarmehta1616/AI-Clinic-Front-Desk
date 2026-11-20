import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { sessionStore } from "@/api/session";
import { ErrorBoundary } from "@/components/layout/ErrorBoundary";
import { LoginPage } from "@/features/auth/LoginPage";
import { TokenStatusPage } from "@/features/public/TokenStatusPage";
import { json, mockFetch, renderApp, tokens } from "@/test/utils";

afterEach(() => {
  vi.unstubAllGlobals();
  sessionStore.set(null);
});

const noSession = { "POST /api/v1/auth/refresh": () => json({ error: { code: "refresh_missing", message: "x" } }, 401) };

describe("LoginPage", () => {
  it("signs in with OTP and goes to onboarding when the user has no clinic", async () => {
    const { calls } = mockFetch({
      ...noSession,
      "POST /api/v1/auth/otp/request": () => json({ status: "sent" }, 202),
      "POST /api/v1/auth/otp/verify": () => json(tokens({ clinic_id: null, role: null })),
    });
    renderApp(<LoginPage />, { path: "/login", route: "/login" });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Mobile number"), "98765 43210");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    await user.type(await screen.findByLabelText("One-time code"), "123456");
    await user.click(screen.getByRole("button", { name: "Verify and sign in" }));
    expect(await screen.findByText("onboarding page")).toBeInTheDocument();
    expect(calls.find((c) => c.key === "POST /api/v1/auth/otp/verify")?.body).toContain('"code":"123456"');
  });

  it("shows the server's message for a wrong code and keeps the user on the form", async () => {
    mockFetch({
      ...noSession,
      "POST /api/v1/auth/otp/request": () => json({ status: "sent" }, 202),
      "POST /api/v1/auth/otp/verify": () => json({ error: { code: "otp_invalid", message: "invalid or expired code" } }, 401),
    });
    renderApp(<LoginPage />, { path: "/login", route: "/login" });
    const user = userEvent.setup();
    await user.type(await screen.findByLabelText("Mobile number"), "9876543210");
    await user.click(screen.getByRole("button", { name: "Send code" }));
    await user.type(await screen.findByLabelText("One-time code"), "000000");
    await user.click(screen.getByRole("button", { name: "Verify and sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid or expired code");
  });

  it("disables Send until a 10-digit number is entered", async () => {
    mockFetch(noSession);
    renderApp(<LoginPage />, { path: "/login", route: "/login" });
    const user = userEvent.setup();
    const button = await screen.findByRole("button", { name: "Send code" });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText("Mobile number"), "98765");
    expect(button).toBeDisabled();
  });
});

describe("TokenStatusPage (FR-4.2)", () => {
  it("shows token, now serving, people ahead — and no personal data", async () => {
    mockFetch({
      ...noSession,
      "GET /api/v1/public/queue/abcdefghijklmnopqrstuv": () =>
        json({ token_no: 7, status: "waiting", current_token_no: 4, ahead: 2, eta: new Date(Date.now() + 20 * 60000).toISOString(), doctor_name: "Dr. Shah" }),
    });
    renderApp(<TokenStatusPage />, { path: "/t/abcdefghijklmnopqrstuv", route: "/t/:code" });
    expect(await screen.findByText("7")).toBeInTheDocument();
    expect(screen.getByText("Now serving").nextSibling).toHaveTextContent("4");
    expect(screen.getByText("Ahead of you").nextSibling).toHaveTextContent("2");
    expect(document.body.textContent).not.toMatch(/\+91|\d{10}/);
  });

  it("tells the patient when the link is not valid", async () => {
    mockFetch({ ...noSession, "GET /api/v1/public/queue/badbadbadbadbadbad": () => json({ error: { code: "not_found", message: "unknown" } }, 404) });
    renderApp(<TokenStatusPage />, { path: "/t/badbadbadbadbadbad", route: "/t/:code" });
    expect(await screen.findByText(/not valid/)).toBeInTheDocument();
  });

  it("announces the patient's turn", async () => {
    mockFetch({
      ...noSession,
      "GET /api/v1/public/queue/abcdefghijklmnopqrstuv": () =>
        json({ token_no: 7, status: "called", current_token_no: 7, ahead: null, eta: null, doctor_name: "Dr. Shah" }),
    });
    renderApp(<TokenStatusPage />, { path: "/t/abcdefghijklmnopqrstuv", route: "/t/:code" });
    expect(await screen.findByText(/your turn/i)).toBeInTheDocument();
  });
});

describe("ErrorBoundary", () => {
  it("contains a crashing screen", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    function Boom(): never {
      throw new Error("boom");
    }
    render(
      <ErrorBoundary>
        <Boom />
      </ErrorBoundary>,
    );
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("This screen hit a problem"));
    spy.mockRestore();
  });
});
