import {
  CalendarDays,
  HeartPulse,
  IndianRupee,
  LayoutDashboard,
  ListOrdered,
  LogOut,
  Menu,
  MessageSquare,
  PhoneMissed,
  Settings,
  Stethoscope,
  Users,
  X,
} from "lucide-react";
import { Suspense, useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { useClinic, useInbox, useMe, useUsage } from "@/api/queries";
import { can, useAuth } from "@/auth/AuthProvider";
import { Spinner } from "@/components/ui";
import { cn } from "@/lib/format";
import { useLiveEvents, type LiveState } from "@/live/useLiveEvents";

import { ErrorBoundary } from "./ErrorBoundary";

const NAV = [
  { to: "/", label: "Today", icon: LayoutDashboard, need: "staff" },
  { to: "/calendar", label: "Appointments", icon: CalendarDays, need: "staff" },
  { to: "/queue", label: "Queue", icon: ListOrdered, need: "staff" },
  { to: "/patients", label: "Patients", icon: Users, need: "staff" },
  { to: "/inbox", label: "Inbox", icon: MessageSquare, need: "desk" },
  { to: "/missed-calls", label: "Missed calls", icon: PhoneMissed, need: "desk" },
  { to: "/recall", label: "Recall", icon: HeartPulse, need: "staff" },
  { to: "/revenue", label: "Revenue", icon: IndianRupee, need: "owner" },
  { to: "/doctors", label: "Doctors", icon: Stethoscope, need: "owner" },
  { to: "/settings", label: "Settings", icon: Settings, need: "owner" },
] as const;

function LiveDot({ state }: { state: LiveState }) {
  const label = { live: "Live", connecting: "Connecting", offline: "Offline — retrying" }[state];
  return (
    <span className="inline-flex items-center gap-1.5 text-xs text-slate-500" title="Real-time updates">
      <span
        className={cn(
          "size-2 rounded-full",
          state === "live" && "bg-emerald-500",
          state === "connecting" && "bg-amber-400",
          state === "offline" && "bg-red-500",
        )}
        aria-hidden
      />
      {label}
    </span>
  );
}

function Nav({ onNavigate }: { onNavigate?: () => void }) {
  const { session } = useAuth();
  const inbox = useInbox("open", can(session, "desk"));
  const openChats = inbox.data?.length ?? 0;
  const emergency = inbox.data?.some((i) => i.reason === "emergency");
  return (
    <nav aria-label="Main" className="space-y-1 px-3">
      {NAV.filter((n) => can(session, n.need)).map((n) => (
        <NavLink
          key={n.to}
          to={n.to}
          end={n.to === "/"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn(
              "flex min-h-11 items-center gap-3 rounded-lg px-3 text-sm font-medium transition-colors",
              isActive ? "bg-brand-50 text-brand-800" : "text-slate-600 hover:bg-slate-100 hover:text-slate-900",
            )
          }
        >
          <n.icon className="size-5 shrink-0" aria-hidden />
          <span className="flex-1">{n.label}</span>
          {n.to === "/inbox" && openChats > 0 && (
            <span
              className={cn(
                "rounded-full px-2 py-0.5 text-xs font-semibold text-white",
                emergency ? "bg-red-600" : "bg-brand-700",
              )}
              aria-label={`${openChats} open chats`}
            >
              {openChats}
            </span>
          )}
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell() {
  const { session, signOut } = useAuth();
  const clinic = useClinic();
  const me = useMe();
  const live = useLiveEvents(Boolean(session?.clinicId));
  const [open, setOpen] = useState(false);
  const location = useLocation();
  useEffect(() => {
    setOpen(false);
  }, [location.pathname]);

  const brand = (
    <div className="flex items-center gap-2.5 px-5 py-5">
      <div className="flex size-9 items-center justify-center rounded-lg bg-brand-700 text-white">
        <span className="text-lg font-bold" aria-hidden>+</span>
      </div>
      <div className="min-w-0">
        <p className="truncate text-sm font-semibold text-slate-900">{clinic.data?.name ?? "ClinicDesk"}</p>
        <p className="text-xs text-slate-500">ClinicDesk AI</p>
      </div>
    </div>
  );
  const footer = (
    <div className="mt-auto space-y-3 border-t border-slate-100 px-5 py-4">
      <div className="text-xs text-slate-500">
        <p className="truncate font-medium text-slate-700">{me.data?.name || me.data?.phone}</p>
        <p className="capitalize">{session?.role}</p>
      </div>
      <button
        onClick={() => void signOut()}
        className="flex min-h-9 items-center gap-2 text-sm font-medium text-slate-600 hover:text-slate-900"
      >
        <LogOut className="size-4" aria-hidden /> Sign out
      </button>
    </div>
  );

  return (
    <div className="min-h-dvh lg:flex">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to content
      </a>
      <aside className="hidden w-64 shrink-0 flex-col border-r border-slate-200 bg-white lg:sticky lg:top-0 lg:flex lg:h-dvh">
        {brand}
        <Nav />
        {footer}
      </aside>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden" role="dialog" aria-modal="true" aria-label="Menu">
          <div className="absolute inset-0 bg-slate-900/40" onClick={() => setOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 flex-col bg-white shadow-xl">
            <div className="flex items-center justify-between pr-3">
              {brand}
              <button className="rounded-lg p-2 hover:bg-slate-100" onClick={() => setOpen(false)} aria-label="Close menu">
                <X className="size-5" />
              </button>
            </div>
            <Nav onNavigate={() => setOpen(false)} />
            {footer}
          </aside>
        </div>
      )}

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-slate-200 bg-white/90 px-4 backdrop-blur lg:px-8">
          <button className="-ml-2 rounded-lg p-2 hover:bg-slate-100 lg:hidden" onClick={() => setOpen(true)} aria-label="Open menu">
            <Menu className="size-5" />
          </button>
          <p className="truncate font-semibold text-slate-900 lg:hidden">{clinic.data?.name}</p>
          <div className="ml-auto">
            <LiveDot state={live} />
          </div>
        </header>
        <AccountBanner />
        <main id="main" className="mx-auto w-full max-w-7xl px-4 py-6 lg:px-8">
          <ErrorBoundary resetKey={location.pathname}>
            <Suspense fallback={<Spinner />}>
              <Outlet />
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
    </div>
  );
}

/** FR-9.1 / FR-9.4: trial ending soon or account suspended — visible on every screen. */
function AccountBanner() {
  const { session } = useAuth();
  const usage = useUsage(can(session, "staff"));
  const u = usage.data;
  if (!u) return null;
  if (u.status === "suspended")
    return (
      <div role="alert" className="bg-red-600 px-4 py-2 text-center text-sm font-medium text-white">
        This clinic&apos;s account is suspended. Bookings and messages are paused — please contact ClinicDesk support.
      </div>
    );
  if (u.status === "trial" && u.days_left != null && u.days_left <= 14)
    return (
      <div className="bg-amber-50 px-4 py-2 text-center text-sm text-amber-900">
        Pilot plan: {u.days_left} day{u.days_left === 1 ? "" : "s"} left.{" "}
        {can(session, "owner") && <NavLink to="/settings" className="font-medium underline">See plan & usage</NavLink>}
      </div>
    );
  return null;
}

export function useTz(): string {
  return useClinic().data?.timezone ?? "Asia/Kolkata";
}
