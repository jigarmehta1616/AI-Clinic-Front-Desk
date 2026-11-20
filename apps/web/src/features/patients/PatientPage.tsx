import { ArrowLeft, CalendarPlus } from "lucide-react";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, unwrap } from "@/api/client";
import { useAction, useDoctors, usePatient, usePatientAppointments, useRecalls } from "@/api/queries";
import { can, useAuth } from "@/auth/AuthProvider";
import { useTz } from "@/components/layout/AppShell";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, SkeletonRows, StatusBadge, useToast } from "@/components/ui";
import { AppointmentActions } from "@/features/shared/AppointmentActions";
import { BookDialog } from "@/features/shared/BookDialog";
import { formatDate, formatDateTime, formatPhone } from "@/lib/format";

const LANG = { gu: "Gujarati", hi: "Hindi", en: "English" } as const;

/** FR-7.2 patient profile: details, consent (DP-2), visits, recalls. */
export default function PatientPage() {
  const { patientId = "" } = useParams();
  const { session } = useAuth();
  const tz = useTz();
  const toast = useToast();
  const patient = usePatient(patientId);
  const appts = usePatientAppointments(patientId);
  const recalls = useRecalls(undefined, patientId);
  const doctors = useDoctors();
  const [book, setBook] = useState(false);
  const consent = useAction(
    (v: { purpose: "reminders" | "recalls"; granted: boolean }) =>
      unwrap(api.POST("/api/v1/patients/{patient_id}/consents", { params: { path: { patient_id: patientId } }, body: v })),
    ["patient"],
  );
  const desk = can(session, "desk");
  const doctorName = (id: string) => doctors.data?.find((d) => d.id === id)?.name ?? "";

  if (patient.isPending) return <Card><SkeletonRows /></Card>;
  if (patient.isError) return <Card><ErrorState error={patient.error} onRetry={() => void patient.refetch()} /></Card>;
  const p = patient.data;
  const now = new Date().toISOString();
  const list = (appts.data ?? []).filter((a) => a.status !== "rescheduled");
  const upcoming = list.filter((a) => a.slot_start >= now && (a.status === "booked" || a.status === "confirmed")).reverse();
  const past = list.filter((a) => !upcoming.includes(a));

  return (
    <>
      <Link to="/patients" className="mb-3 inline-flex items-center gap-1 text-sm text-slate-600 hover:text-slate-900">
        <ArrowLeft className="size-4" aria-hidden /> Patients
      </Link>
      <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold">{p.name}</h1>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-slate-600">
            <span>{formatPhone(p.phone)}</span>
            {p.age != null && <span>· {p.age} years</span>}
            {p.language && <span>· {LANG[p.language as keyof typeof LANG]}</span>}
            {p.opted_out_at && <Badge tone="amber">Opted out of reminders & recalls</Badge>}
          </p>
        </div>
        {desk && <Button icon={<CalendarPlus className="size-4" />} onClick={() => setBook(true)}>Book appointment</Button>}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card>
            <CardHeader title="Upcoming" />
            {appts.isPending ? <SkeletonRows rows={2} /> : upcoming.length === 0 ? (
              <EmptyState title="No upcoming appointments" />
            ) : (
              <ul className="divide-y divide-slate-100">
                {upcoming.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
                    <div className="flex-1">
                      <p className="font-medium">{formatDateTime(a.slot_start, tz)}</p>
                      <p className="text-sm text-slate-500">{doctorName(a.doctor_id)}</p>
                    </div>
                    <StatusBadge status={a.status} />
                    <AppointmentActions appt={{ ...a, patient_name: p.name }} compact />
                  </li>
                ))}
              </ul>
            )}
          </Card>
          <Card>
            <CardHeader title="Visit history" />
            {appts.isError ? <ErrorState error={appts.error} /> : past.length === 0 ? (
              <EmptyState title="No past visits" />
            ) : (
              <ul className="divide-y divide-slate-100">
                {past.map((a) => (
                  <li key={a.id} className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
                    <div className="flex-1">
                      <p className="font-medium">{formatDateTime(a.slot_start, tz)}</p>
                      <p className="text-sm text-slate-500">
                        {doctorName(a.doctor_id)}
                        {a.visit_type && ` · ${a.visit_type.replace("_", " ")}`}
                      </p>
                    </div>
                    <StatusBadge status={a.status} />
                    {(a.status === "arrived" || a.status === "completed") && <AppointmentActions appt={{ ...a, patient_name: p.name }} compact />}
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
        <div className="space-y-6">
          <Card>
            <CardHeader title="Messages consent" subtitle="Separate from booking consent (DP-2)." />
            <div className="space-y-3 p-4 sm:p-5">
              {(["reminders", "recalls"] as const).map((purpose) => {
                const state = purpose === "reminders" ? p.reminders_consent : p.recalls_consent;
                return (
                <div key={purpose} className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <p className="text-sm font-medium">{purpose === "recalls" ? "Check-up recalls" : "Appointment reminders"}</p>
                    <p className="text-xs">
                      {state === true ? <span className="text-emerald-700">Agreed</span> : state === false ? <span className="text-amber-700">Withdrawn — no messages</span> : <span className="text-slate-500">Not asked yet — no messages</span>}
                    </p>
                  </div>
                  {desk && (
                    <div className="flex gap-1.5">
                      <Button size="sm" variant="secondary" disabled={state === true} onClick={() => consent.mutate({ purpose, granted: true }, { onSuccess: () => toast("success", "Consent recorded") })}>
                        Patient agreed
                      </Button>
                      <Button size="sm" variant="ghost" disabled={state === false} onClick={() => consent.mutate({ purpose, granted: false }, { onSuccess: () => toast("success", "Withdrawal recorded") })}>
                        Withdrew
                      </Button>
                    </div>
                  )}
                </div>
                );
              })}
              <p className="text-xs text-slate-500">Record only what the patient told you. Patients can also reply STOP or START on WhatsApp.</p>
            </div>
          </Card>
          <Card>
            <CardHeader title="Recalls" />
            {recalls.isPending ? <SkeletonRows rows={2} /> : (recalls.data ?? []).length === 0 ? (
              <EmptyState title="No recalls" body="Set a follow-up after a visit to schedule one." />
            ) : (
              <ul className="divide-y divide-slate-100">
                {recalls.data!.map((r) => (
                  <li key={r.id} className="flex items-center justify-between gap-3 px-4 py-3 sm:px-5">
                    <div>
                      <p className="text-sm font-medium">{r.label}</p>
                      <p className="text-xs text-slate-500">Due {formatDate(r.due_date, tz)}</p>
                    </div>
                    <StatusBadge status={r.status} />
                  </li>
                ))}
              </ul>
            )}
          </Card>
        </div>
      </div>
      {book && <BookDialog open onOpenChange={setBook} initialPatient={p} />}
    </>
  );
}
