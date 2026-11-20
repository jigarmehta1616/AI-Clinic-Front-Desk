import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, refreshSession } from "@/api/client";
import { sessionFromTokens, sessionStore, type Session } from "@/api/session";

type Status = "loading" | "anonymous" | "authenticated";

interface AuthValue {
  status: Status;
  session: Session | null;
  signIn: (tokens: Parameters<typeof sessionFromTokens>[0]) => void;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  const [session, setSession] = useState<Session | null>(sessionStore.get());
  const [restored, setRestored] = useState(false);

  useEffect(() => sessionStore.subscribe(setSession), []);

  useEffect(() => {
    // Restore from the HttpOnly refresh cookie on page load.
    let cancelled = false;
    void refreshSession().finally(() => !cancelled && setRestored(true));
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    // Refresh shortly before the 15-minute access token expires.
    if (!session) return;
    const ms = Math.max(session.expiresAt - Date.now() - 60_000, 5_000);
    const t = setTimeout(() => void refreshSession(), ms);
    return () => clearTimeout(t);
  }, [session]);

  const signIn = useCallback<AuthValue["signIn"]>(
    (tokens) => {
      qc.clear();
      sessionStore.set(sessionFromTokens(tokens));
    },
    [qc],
  );

  const signOut = useCallback(async () => {
    try {
      await api.POST("/api/v1/auth/logout");
    } finally {
      sessionStore.set(null);
      qc.clear();
    }
  }, [qc]);

  const value = useMemo<AuthValue>(
    () => ({
      status: !restored && !session ? "loading" : session ? "authenticated" : "anonymous",
      session,
      signIn,
      signOut,
    }),
    [restored, session, signIn, signOut],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const v = useContext(AuthContext);
  if (!v) throw new Error("useAuth outside AuthProvider");
  return v;
}

export function can(session: Session | null, need: "owner" | "staff" | "desk"): boolean {
  const role = session?.role;
  if (need === "owner") return role === "owner";
  if (need === "desk") return role === "owner" || role === "receptionist";
  return role != null;
}
