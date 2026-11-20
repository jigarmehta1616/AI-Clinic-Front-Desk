import { AlertTriangle, CalendarPlus, MessageSquare, Ticket } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage, unwrap } from "@/api/client";
import { groups, useAction, useAppointments, useToday, type Today } from "@/api/queries";
import { can, useAuth } from "@/auth/AuthProvider";
import { useTz } from "@/components/layout/AppShell";
import {
  Badge,
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorState,
  PageHeader,
  SkeletonRows,
  StatTile,
  StatusBadge,
  useToast,
} from "@/components/ui";
import { AppointmentActions } from "@/features/shared/AppointmentActions";
import { BookDialog } from "@/features/shared/BookDialog";
import { IssueTokenDialog } from "@/features/shared/IssueTokenDialog";
import { dayIn, formatDate, formatTime } from "@/lib/format";

/** FR-7.1 Today view, built around the receptionist's top actions (NFR-7). */
export function TodayPage() {
  const tz = useTz();
  const { session } = useAuth();
  const day = dayIn(tz);
  const today = useToday(day);
  const appts = useAppointments(day);
  const [book, setBook] = useState(false);
  const [token, setToken] = useState<string | null>(null);
  const desk = can(session, "desk");

  const totals = sum(today.data);
  return (
    <>
      <PageHeader
        title="Today"
        subtitle={formatDate(day, tz)}
        actions={
          desk && (
            <>
              <Button variant="secondary" icon={<Ticket className="size-4" />} onClick={() => setToken("")}>Issue token</Button>
              <Button icon={<CalendarPlus className="size-4" />} onClick={() => setBook(true)}>Book appointment</Button>
            </>
          )
        }
      />

      {today.data && today.data.emergencies > 0 && (
        <Link to="/inbox" className="mb-4 flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-red-800 hover:bg-red-100" role="alert">
          <AlertTriangle className="size-5 shrink-0" aria-hidden />
          <span className="font-medium">
            {today.data.emergencies} emergency message{today.data.emergencies > 1 ? "s" : ""} waiting — open the inbox now.
          </span>
        </Link>
      )}

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5">
        <StatTile label="Appointments" value={today.isPending ? "–" : totals.appointments} hint={`${totals.remaining} still to come`} />
        <StatTile label="Arrived" value={today.isPending ? "–" : totals.arrived} tone="brand" />
        <StatTile label="No-shows" value={today.isPending ? "–" : totals.noShow} tone={totals.noShow ? "amber" : "slate"} />
        <StatTile label="Tokens waiting" value={today.isPending ? "–" : totals.waiting} />
        <StatTile
          label="Open chats"
          value={today.isPending ? "–" : (today.data?.open_chats ?? 0)}
          tone={today.data?.emergencies ? "red" : "slate"}
          icon={<MessageSquare className="size-4" aria-hidden />}
        />
      </div>
      {today.data && (today.data.needs_reschedule > 0 || today.data.recalls_due > 0 || today.data.call_backs_needed > 0) && (
        <div className="mt-3 flex flex-wrap gap-2 text-sm">
          {today.data.needs_reschedule > 0 && (
            <Badge tone="amber">{today.data.needs_reschedule} booking(s) need rescheduling (doctor leave/holiday)</Badge>
          )}
          {today.data.recalls_due > 0 && <Badge tone="brand">{today.data.recalls_due} recall(s) going out today</Badge>}
          {today.data.call_backs_needed > 0 && (
            <Link to="/missed-calls"><Badge tone="red">{today.data.call_backs_needed} missed call(s) to call back</Badge></Link>
          )}
        </div>
      )}

      <div className="mt-6 grid gap-6 xl:grid-cols-3">
        <Card className="xl:col-span-2">
          <CardHeader title="Appointments" subtitle="Mark arrivals as patients walk in" actions={<Link to="/calendar" className="text-sm font-medium text-brand-700 hover:underline">Full day view</Link>} />
          {appts.isPending ? (
            <SkeletonRows />
          ) : appts.isError ? (
            <ErrorState error={appts.error} onRetry={() => void appts.refetch()} />
          ) : appts.data.filter((a) => a.status !== "rescheduled").length === 0 ? (
            <EmptyState title="No appointments today" body="Bookings from WhatsApp and the desk show up here instantly." action={desk && <Button size="sm" onClick={() => setBook(true)}>Book appointment</Button>} />
          ) : (
            <ul className="divide-y divide-slate-100">
              {appts.data
                .filter((a) => a.status !== "rescheduled")
                .map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
                    <div className="tabular w-20 shrink-0 font-semibold text-slate-900">{formatTime(a.slot_start, tz)}</div>
                    <div className="min-w-0 flex-1">
                      <p className="truncate font-medium">{a.patient_name ?? "Patient"}</p>
                      <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                        <StatusBadge status={a.status} />
                        {doctorName(today.data, a.doctor_id)}
                        {a.source !== "staff" && a.source !== "assistant" && <Badge tone="violet">{a.source.replace("_", " ")}</Badge>}
                        {a.needs_reschedule && <Badge tone="amber">needs reschedule</Badge>}
                      </div>
                    </div>
                    <AppointmentActions appt={a} compact />
                  </li>
                ))}
            </ul>
          )}
        </Card>

        <div className="space-y-4">
          {today.isPending ? (
            <Card><SkeletonRows rows={3} /></Card>
          ) : today.isError ? (
            <Card><ErrorState error={today.error} onRetry={() => void today.refetch()} /></Card>
          ) : today.data.doctors.length === 0 ? (
            <Card>
              <EmptyState title="No doctors yet" body="Add doctors and their weekly sessions to start booking." action={<Link to="/doctors" className="font-medium text-brand-700 hover:underline">Add a doctor</Link>} />
            </Card>
          ) : (
            today.data.doctors.map((d) => <DoctorQueueCard key={d.doctor_id} doctor={d} day={day} onIssue={() => setToken(d.doctor_id)} desk={desk} />)
          )}
        </div>
      </div>

      {book && <BookDialog open={book} onOpenChange={setBook} />}
      {token !== null && <IssueTokenDialog open onOpenChange={(o) => !o && setToken(null)} initialDoctorId={token || undefined} />}
    </>
  );
}

function DoctorQueueCard({ doctor, day, onIssue, desk }: { doctor: Today["doctors"][number]; day: string; onIssue: () => void; desk: boolean }) {
  const toast = useToast();
  const callNext = useAction(async () => {
    const sessions = await unwrap(api.GET("/api/v1/queue", { params: { query: { doctor_id: doctor.doctor_id, day } } }));
    const now = Date.now();
    const current = sessions.find((s) => new Date(s.starts_at).getTime() <= now + 3600_000 && new Date(s.ends_at).getTime() > now) ?? sessions[0];
    if (!current) throw new Error("No queue for this doctor right now");
    return unwrap(api.POST("/api/v1/queue/sessions/{queue_session_id}/next", { params: { path: { queue_session_id: current.id } } }));
  }, groups.queue);
  const a = doctor.appointments;
  return (
    <Card>
      <CardHeader title={doctor.name} subtitle={`${a.booked + a.confirmed} to come · ${a.arrived} arrived · ${a.completed} done`} />
      <div className="flex items-center justify-between gap-3 px-4 py-4 sm:px-5">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">Now serving</p>
          <p className="tabular text-4xl font-bold text-brand-700">{doctor.current_token ?? "–"}</p>
          <p className="mt-1 text-sm text-slate-500">{doctor.tokens.waiting} waiting</p>
        </div>
        <div className="flex flex-col gap-2">
          <Button
            size="lg"
            loading={callNext.isPending}
            onClick={() =>
              callNext.mutate(undefined, {
                onSuccess: (e) => toast(e ? "success" : "info", e ? `Calling token ${e.token_no}` : "No one is waiting"),
                onError: (e) => toast("error", errorMessage(e)),
              })
            }
          >
            Call next
          </Button>
          {desk && <Button variant="secondary" size="sm" onClick={onIssue}>Issue token</Button>}
        </div>
      </div>
    </Card>
  );
}

function sum(t: Today | undefined) {
  const out = { appointments: 0, remaining: 0, arrived: 0, noShow: 0, waiting: 0 };
  for (const d of t?.doctors ?? []) {
    const a = d.appointments;
    out.appointments += a.booked + a.confirmed + a.arrived + a.completed + a.no_show;
    out.remaining += a.booked + a.confirmed;
    out.arrived += a.arrived + a.completed;
    out.noShow += a.no_show;
    out.waiting += d.tokens.waiting;
  }
  return out;
}

function doctorName(t: Today | undefined, id: string) {
  const n = t?.doctors.find((d) => d.doctor_id === id)?.name;
  return n ? <span>{n}</span> : null;
}
