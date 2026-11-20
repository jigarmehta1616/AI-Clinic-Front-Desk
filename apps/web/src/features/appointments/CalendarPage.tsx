import { CalendarPlus } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { useAppointments, useDoctors, useSlots } from "@/api/queries";
import { can, useAuth } from "@/auth/AuthProvider";
import { useTz } from "@/components/layout/AppShell";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, SkeletonRows, StatusBadge } from "@/components/ui";
import { AppointmentActions } from "@/features/shared/AppointmentActions";
import { BookDialog } from "@/features/shared/BookDialog";
import { DayNav, DoctorSelect } from "@/features/shared/pickers";
import { cn, dayIn, formatPhone, formatTime } from "@/lib/format";

/** Day view per doctor: booked appointments interleaved with free slots (one tap to book a free slot). */
export default function CalendarPage() {
  const tz = useTz();
  const { session } = useAuth();
  const [params, setParams] = useSearchParams();
  const day = params.get("day") ?? dayIn(tz);
  const [doctorId, setDoctorId] = useState(params.get("doctor") ?? session?.doctorId ?? "");
  const doctors = useDoctors();
  const appts = useAppointments(day, doctorId || undefined);
  const slots = useSlots(doctorId || undefined, day, day);
  const [booking, setBooking] = useState<{ open: boolean; day?: string }>({ open: false });
  const desk = can(session, "desk");

  const setDay = (d: string) => setParams((p) => { p.set("day", d); return p; }, { replace: true });
  const visible = (appts.data ?? []).filter((a) => a.status !== "rescheduled");
  type Row = { kind: "appt"; at: string; appt: (typeof visible)[number] } | { kind: "free"; at: string };
  const rows: Row[] = [
    ...visible.map((a) => ({ kind: "appt" as const, at: a.slot_start, appt: a })),
    ...(doctorId && desk ? (slots.data ?? []).map((s) => ({ kind: "free" as const, at: s.start })) : []),
  ].sort((x, y) => x.at.localeCompare(y.at));
  const doctorName = (id: string) => doctors.data?.find((d) => d.id === id)?.name;

  return (
    <>
      <PageHeader
        title="Appointments"
        actions={desk && <Button icon={<CalendarPlus className="size-4" />} onClick={() => setBooking({ open: true, day })}>Book appointment</Button>}
      />
      <Card>
        <CardHeader
          title={<DayNav day={day} onChange={setDay} />}
          actions={session?.role !== "doctor" && <DoctorSelect allowAll value={doctorId} onChange={setDoctorId} />}
        />
        {appts.isPending ? (
          <SkeletonRows rows={6} />
        ) : appts.isError ? (
          <ErrorState error={appts.error} onRetry={() => void appts.refetch()} />
        ) : rows.length === 0 ? (
          <EmptyState
            title="Nothing scheduled"
            body={doctorId ? "No appointments or free slots — the doctor may have no session this day." : "Pick a doctor to see free slots, or book from the button above."}
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {rows.map((r) =>
              r.kind === "free" ? (
                <li key={`free-${r.at}`} className="flex items-center gap-3 px-4 py-2 sm:px-5">
                  <div className="tabular w-20 shrink-0 text-sm text-slate-400">{formatTime(r.at, tz)}</div>
                  <button
                    onClick={() => setBooking({ open: true, day })}
                    className="flex-1 rounded-lg border border-dashed border-slate-200 px-3 py-2 text-left text-sm text-slate-500 hover:border-brand-600 hover:text-brand-700"
                  >
                    Free — book this slot
                  </button>
                </li>
              ) : (
                <li key={r.appt.id} className={cn("flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5", r.appt.status === "cancelled" && "opacity-60")}>
                  <div className="tabular w-20 shrink-0 font-semibold">{formatTime(r.at, tz)}</div>
                  <div className="min-w-0 flex-1">
                    <p className="truncate font-medium">{r.appt.patient_name ?? "Patient"}</p>
                    <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
                      <StatusBadge status={r.appt.status} />
                      {!doctorId && <span>{doctorName(r.appt.doctor_id)}</span>}
                      {r.appt.patient_phone && <span>{formatPhone(r.appt.patient_phone)}</span>}
                      {r.appt.visit_type && <Badge>{r.appt.visit_type.replace("_", " ")}</Badge>}
                      {!["staff", "assistant"].includes(r.appt.source) && <Badge tone="violet">{r.appt.source.replace("_", " ")}</Badge>}
                      {r.appt.source === "assistant" && <Badge tone="brand">WhatsApp</Badge>}
                      {r.appt.needs_reschedule && <Badge tone="amber">needs reschedule</Badge>}
                    </div>
                  </div>
                  <AppointmentActions appt={r.appt} />
                </li>
              ),
            )}
          </ul>
        )}
      </Card>
      {booking.open && <BookDialog open onOpenChange={(o) => setBooking({ open: o })} initialDay={booking.day} initialDoctorId={doctorId || undefined} />}
    </>
  );
}
