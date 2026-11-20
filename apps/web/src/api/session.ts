/** Access token lives in memory only (ADR-0007); the refresh token is an HttpOnly cookie the JS never sees. */

export type Role = "owner" | "doctor" | "receptionist";

export interface Session {
  accessToken: string;
  clinicId: string | null;
  role: Role | null;
  doctorId: string | null; // UX only (pre-selects own schedule); the server enforces doctor scope
  isPlatformAdmin: boolean; // UX only (shows the admin console); the server enforces it
  expiresAt: number;
}

type Listener = (s: Session | null) => void;

let current: Session | null = null;
const listeners = new Set<Listener>();

export const sessionStore = {
  get: (): Session | null => current,
  set(next: Session | null): void {
    current = next;
    listeners.forEach((l) => l(current));
  },
  subscribe(listener: Listener): () => void {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
};

export function sessionFromTokens(t: {
  access_token: string;
  expires_in: number;
  clinic_id?: string | null;
  role?: string | null;
}): Session {
  return {
    accessToken: t.access_token,
    clinicId: t.clinic_id ?? null,
    role: (t.role as Role | null | undefined) ?? null,
    doctorId: (claim(t.access_token, "did") as string | null) ?? null,
    isPlatformAdmin: claim(t.access_token, "pa") === true,
    expiresAt: Date.now() + t.expires_in * 1000,
  };
}

function claim(jwt: string, name: string): string | boolean | null {
  try {
    const part = jwt.split(".")[1] ?? "";
    const json = JSON.parse(atob(part.replace(/-/g, "+").replace(/_/g, "/"))) as Record<string, unknown>;
    const v = json[name];
    return typeof v === "string" || typeof v === "boolean" ? v : null;
  } catch {
    return null;
  }
}
