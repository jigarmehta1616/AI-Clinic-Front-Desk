import { CalendarOff, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useSearchParams } from "react-router-dom";

import { api, unwrap } from "@/api/client";
import { groups, useAction, useClinic, useDoctors, useExceptions, type Doctor } from "@/api/queries";
import { useTz } from "@/components/layout/AppShell";
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Field, InlineError, Input, PageHeader, Select, SkeletonRows, useToast } from "@/components/ui";
import { dayIn, formatDate, formatMoney } from "@/lib/format";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
type SessionRow = { weekday: number; start_time: string; end_time: string; max_tokens: number };

/** FR-1.2 doctors + weekly sessions, FR-1.3 holidays/leave. */
export default function DoctorsPage() {
  const tz = useTz();
  const [params] = useSearchParams();
  const doctors = useDoctors();
  const clinic = useClinic();
  const exceptions = useExceptions(dayIn(tz));
  const [editing, setEditing] = useState<Doctor | "new" | null>(null);
  const [leave, setLeave] = useState(false);

  return (
    <>
      <PageHeader
        title="Doctors & schedules"
        actions={
          <>
            <Button variant="secondary" icon={<CalendarOff className="size-4" />} onClick={() => setLeave(true)}>Add holiday / leave</Button>
            <Button icon={<Plus className="size-4" />} onClick={() => setEditing("new")}>Add doctor</Button>
          </>
        }
      />
      {params.get("welcome") && (doctors.data?.length ?? 0) === 0 && (
        <div className="mb-4 rounded-xl border border-brand-200 bg-brand-50 px-4 py-3 text-sm text-brand-900">
          <strong>Step 2 of 3 · Doctors.</strong> Add each doctor with their weekly sessions. Then connect WhatsApp in Settings.
        </div>
      )}
      <Card>
        {doctors.isPending ? <SkeletonRows /> : doctors.isError ? <ErrorState error={doctors.error} onRetry={() => void doctors.refetch()} /> : doctors.data.length === 0 ? (
          <EmptyState title="No doctors yet" body="Patients can book once a doctor has weekly sessions." action={<Button onClick={() => setEditing("new")}>Add doctor</Button>} />
        ) : (
          <ul className="divide-y divide-slate-100">
            {doctors.data.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-3 px-4 py-4 sm:px-5">
                <div className="min-w-0 flex-1">
                  <p className="font-medium">{d.name} {!d.is_active && <Badge>inactive</Badge>}</p>
                  <p className="text-sm text-slate-500">
                    {d.slot_minutes}-min slots · fee {formatMoney(d.fee_paise ?? clinic.data?.default_fee_paise ?? 0)}
                    {d.fee_paise == null && " (clinic default)"}
                  </p>
                  <p className="mt-1 text-sm text-slate-600">{summarise(d.sessions)}</p>
                </div>
                <Button size="sm" variant="secondary" onClick={() => setEditing(d)}>Edit</Button>
              </li>
            ))}
          </ul>
        )}
      </Card>
      <Card className="mt-6">
        <CardHeader title="Upcoming holidays & leave" subtitle="Bookings in these days are flagged for rescheduling, never cancelled silently." />
        {exceptions.isPending ? <SkeletonRows rows={2} /> : (exceptions.data ?? []).length === 0 ? <EmptyState title="None planned" /> : (
          <ul className="divide-y divide-slate-100">
            {exceptions.data!.map((x) => (
              <li key={x.id} className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
                <Badge tone={x.kind === "holiday" ? "amber" : "blue"}>{x.kind}</Badge>
                <span className="font-medium">{formatDate(x.start_date, tz)}{x.end_date !== x.start_date && ` – ${formatDate(x.end_date, tz)}`}</span>
                <span className="text-sm text-slate-500">{x.doctor_id ? doctors.data?.find((d) => d.id === x.doctor_id)?.name : "Whole clinic"}{x.reason && ` · ${x.reason}`}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>
      {editing && <DoctorDialog doctor={editing === "new" ? null : editing} onClose={() => setEditing(null)} />}
      {leave && <LeaveDialog onClose={() => setLeave(false)} />}
    </>
  );
}

function summarise(sessions: Doctor["sessions"]): string {
  if (!sessions?.length) return "No weekly sessions yet";
  const byTime = new Map<string, number[]>();
  for (const s of sessions) {
    const k = `${s.start_time.slice(0, 5)}–${s.end_time.slice(0, 5)}`;
    byTime.set(k, [...(byTime.get(k) ?? []), s.weekday]);
  }
  return [...byTime.entries()].map(([t, days]) => `${days.map((d) => DAYS[d]).join(", ")} ${t}`).join(" · ");
}

function DoctorDialog({ doctor, onClose }: { doctor: Doctor | null; onClose: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({
    name: doctor?.name ?? "",
    fee: doctor?.fee_paise != null ? String(doctor.fee_paise / 100) : "",
    slot: String(doctor?.slot_minutes ?? 15),
    active: doctor?.is_active ?? true,
  });
  const [sessions, setSessions] = useState<SessionRow[]>(
    doctor?.sessions?.map((s) => ({ weekday: s.weekday, start_time: s.start_time.slice(0, 5), end_time: s.end_time.slice(0, 5), max_tokens: s.max_tokens })) ??
      [0, 1, 2, 3, 4, 5].map((d) => ({ weekday: d, start_time: "10:00", end_time: "13:00", max_tokens: 30 })),
  );
  const save = useAction(async () => {
    const body = { name: f.name, fee_paise: f.fee ? Math.round(Number(f.fee) * 100) : null, slot_minutes: Number(f.slot) };
    const d = doctor
      ? await unwrap(api.PATCH("/api/v1/doctors/{doctor_id}", { params: { path: { doctor_id: doctor.id } }, body: { ...body, is_active: f.active } }))
      : await unwrap(api.POST("/api/v1/doctors", { body }));
    await unwrap(api.PUT("/api/v1/doctors/{doctor_id}/sessions", { params: { path: { doctor_id: d.id } }, body: { sessions } }));
    return d;
  }, ["doctors", ...groups.schedule]);
  const update = (i: number, patch: Partial<SessionRow>) => setSessions(sessions.map((s, j) => (j === i ? { ...s, ...patch } : s)));

  return (
    <Dialog
      open
      wide
      onOpenChange={(o) => !o && onClose()}
      title={doctor ? `Edit ${doctor.name}` : "Add doctor"}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} disabled={f.name.length < 2} onClick={() => save.mutate(undefined, { onSuccess: () => { toast("success", "Doctor saved"); onClose(); } })}>Save</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="sm:col-span-3"><Field label="Name">{(id) => <Input id={id} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} placeholder="Dr. Mehul Shah" />}</Field></div>
          <Field label="Fee (₹)" hint="Blank = clinic default">{(id, d) => <Input id={id} aria-describedby={d} inputMode="numeric" value={f.fee} onChange={(e) => setF({ ...f, fee: e.target.value.replace(/\D/g, "") })} />}</Field>
          <Field label="Slot length">
            {(id) => (
              <Select id={id} value={f.slot} onChange={(e) => setF({ ...f, slot: e.target.value })}>
                {[10, 15, 20, 30, 45, 60].map((m) => <option key={m} value={m}>{m} minutes</option>)}
              </Select>
            )}
          </Field>
          {doctor && (
            <label className="flex items-center gap-2 self-end pb-3 text-sm">
              <input type="checkbox" className="size-4" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} /> Taking bookings
            </label>
          )}
        </div>
        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium text-slate-700">Weekly sessions</p>
            <Button size="sm" variant="secondary" icon={<Plus className="size-4" />} onClick={() => setSessions([...sessions, { weekday: 0, start_time: "17:00", end_time: "20:00", max_tokens: 30 }])}>Add session</Button>
          </div>
          <div className="space-y-2">
            {sessions.map((s, i) => (
              <div key={i} className="grid grid-cols-[1fr_1fr_1fr_auto] items-center gap-2 sm:grid-cols-[1fr_1fr_1fr_100px_auto]">
                <Select aria-label="Day" value={s.weekday} onChange={(e) => update(i, { weekday: Number(e.target.value) })}>
                  {DAYS.map((d, n) => <option key={d} value={n}>{d}</option>)}
                </Select>
                <Input aria-label="Start" type="time" value={s.start_time} onChange={(e) => update(i, { start_time: e.target.value })} />
                <Input aria-label="End" type="time" value={s.end_time} onChange={(e) => update(i, { end_time: e.target.value })} />
                <Input aria-label="Max walk-in tokens" className="hidden sm:block" inputMode="numeric" value={s.max_tokens} onChange={(e) => update(i, { max_tokens: Number(e.target.value.replace(/\D/g, "") || 0) })} />
                <Button size="sm" variant="ghost" aria-label="Remove session" onClick={() => setSessions(sessions.filter((_, j) => j !== i))}><Trash2 className="size-4" /></Button>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-slate-500">Last column = maximum walk-in tokens per session (BR-5).</p>
        </div>
        <InlineError error={save.error} />
      </div>
    </Dialog>
  );
}

function LeaveDialog({ onClose }: { onClose: () => void }) {
  const tz = useTz();
  const toast = useToast();
  const doctors = useDoctors();
  const [f, setF] = useState({ doctor: "", start: dayIn(tz), end: dayIn(tz), reason: "" });
  const save = useAction(
    () =>
      unwrap(
        api.POST("/api/v1/schedule-exceptions", {
          body: { doctor_id: f.doctor || null, start_date: f.start, end_date: f.end, kind: f.doctor ? "leave" : "holiday", reason: f.reason || null },
        }),
      ),
    ["exceptions", ...groups.schedule],
  );
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Add holiday or leave"
      description="Existing bookings in this period are flagged so the desk can reschedule them."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: (x) => { toast("success", x.flagged_appointments ? `${x.flagged_appointments} booking(s) flagged for rescheduling` : "Saved"); onClose(); } })}>Save</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Who">
          {(id) => (
            <Select id={id} value={f.doctor} onChange={(e) => setF({ ...f, doctor: e.target.value })}>
              <option value="">Whole clinic (holiday)</option>
              {doctors.data?.map((d) => <option key={d.id} value={d.id}>{d.name} (leave)</option>)}
            </Select>
          )}
        </Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="From">{(id) => <Input id={id} type="date" value={f.start} onChange={(e) => setF({ ...f, start: e.target.value })} />}</Field>
          <Field label="To">{(id) => <Input id={id} type="date" value={f.end} min={f.start} onChange={(e) => setF({ ...f, end: e.target.value })} />}</Field>
        </div>
        <Field label="Reason (optional)">{(id) => <Input id={id} value={f.reason} onChange={(e) => setF({ ...f, reason: e.target.value })} maxLength={200} />}</Field>
        <InlineError error={save.error} />
      </div>
    </Dialog>
  );
}
