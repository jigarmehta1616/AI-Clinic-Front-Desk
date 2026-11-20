import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactNode } from "react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { AuthProvider } from "@/auth/AuthProvider";
import { ToastProvider } from "@/components/ui";

type Handler = (url: URL, init: Request) => Response | Promise<Response>;

/** Mock the network boundary only: route by "METHOD /path". Unmatched calls fail loudly. */
export function mockFetch(routes: Record<string, Handler>) {
  const calls: Array<{ key: string; auth: string | null; body: string }> = [];
  const fn = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const req = input instanceof Request ? input : new Request(new URL(String(input), "http://localhost"), init);
    const url = new URL(req.url, "http://localhost");
    const key = `${req.method} ${url.pathname}`;
    calls.push({ key, auth: req.headers.get("Authorization"), body: req.method === "GET" ? "" : await req.clone().text() });
    const h = routes[key];
    if (!h) return json({ error: { code: "not_mocked", message: key } }, 599);
    return h(url, req);
  });
  vi.stubGlobal("fetch", fn);
  return { fn, calls };
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

export function renderApp(ui: ReactNode, { path = "/", route = "*" }: { path?: string; route?: string } = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter initialEntries={[path]}>
        <ToastProvider>
          <AuthProvider>
            <Routes>
              <Route path={route} element={ui} />
              <Route path="/onboarding" element={<p>onboarding page</p>} />
              <Route path="/" element={<p>today page</p>} />
            </Routes>
          </AuthProvider>
        </ToastProvider>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

export const tokens = (over: Partial<{ clinic_id: string | null; role: string | null }> = {}) => ({
  access_token: "header.eyJzdWIiOiJ1In0.sig",
  token_type: "bearer",
  expires_in: 900,
  clinic_id: "c1",
  role: "owner",
  memberships: [],
  ...over,
});
