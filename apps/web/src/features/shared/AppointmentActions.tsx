import { CalendarClock, Check, MoreHorizontal, UserCheck, UserX, X } from "lucide-react";
import { useState } from "react";

import { api, errorMessage, unwrap } from "@/api/client";
import { groups, useAction, useRecallRules, type Appointment } from "@/api/queries";
import { can, useAuth } from "@/auth/AuthProvider";
import { useTz } from "@/components/layout/AppShell";
import { Button, Dialog, Field, InlineError, Input, useToast } from "@/components/ui";
import { formatDate } from "@/lib/format";

import { BookDialog } from "./BookDialog";

type Status = "confirmed" | "arrived" | "completed" | "no_show";

/** One-tap actions for an appointment row (receptionist's top actions, NFR-7). */
export function AppointmentActions({ appt, compact }: { appt: Appointment; compact?: boolean }) {
  const { session } = useAuth();
  const toast = useToast();
  const [more, setMore] = useState(false);
  const [resched, setResched] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [followup, setFollowup] = useState(false);
  const desk = can(session, "desk");

  const setStatus = useAction(
    (status: Status) =>
      unwrap(api.POST("/api/v1/appointments/{appointment_id}/status", { params: { path: { appointment_id: appt.id } }, body: { status } })),
    groups.schedule,
  );
  const run = (status: Status, msg: string) =>
    setStatus.mutate(status, { onSuccess: () => toast("success", msg), onError: (e) => toast("error", errorMessage(e)) });

  const upcoming = appt.status === "booked" || appt.status === "confirmed";
  return (
    <div className="flex flex-wrap items-center justify-end gap-1.5">
      {upcoming && (
        <Button size="sm" variant="success" icon={<UserCheck className="size-4" />} loading={setStatus.isPending && setStatus.variables === "arrived"} onClick={() => run("arrived", `${appt.patient_name ?? "Patient"} marked arrived`)}>
          Arrived
        </Button>
      )}
      {appt.status === "arrived" && (
        <Button size="sm" icon={<Check className="size-4" />} onClick={() => run("completed", "Visit completed")}>
          Done
        </Button>
      )}
      {(appt.status === "arrived" || appt.status === "completed") && !compact && (
        <Button size="sm" variant="secondary" onClick={() => setFollowup(true)}>
          Follow-up
        </Button>
      )}
      {(upcoming || appt.status === "arrived" || appt.status === "completed") && (
        <Button size="sm" variant="ghost" aria-label="More actions" aria-expanded={more} onClick={() => setMore((m) => !m)}>
          <MoreHorizontal className="size-4" />
        </Button>
      )}
      {more && (
        <div className="flex w-full flex-wrap justify-end gap-1.5">
          {upcoming && appt.status === "booked" && (
            <Button size="sm" variant="secondary" onClick={() => run("confirmed", "Confirmed")}>Confirm</Button>
          )}
          {upcoming && desk && (
            <Button size="sm" variant="secondary" icon={<CalendarClock className="size-4" />} onClick={() => setResched(true)}>Reschedule</Button>
          )}
          {upcoming && desk && (
            <Button size="sm" variant="secondary" icon={<X className="size-4" />} onClick={() => setCancelOpen(true)}>Cancel</Button>
          )}
          {upcoming && new Date(appt.slot_start) <= new Date() && (
            <Button size="sm" variant="secondary" icon={<UserX className="size-4" />} onClick={() => run("no_show", "Marked no-show")}>No-show</Button>
          )}
          {(appt.status === "arrived" || appt.status === "completed") && compact && (
            <Button size="sm" variant="secondary" onClick={() => setFollowup(true)}>Follow-up</Button>
          )}
        </div>
      )}
      {resched && <BookDialog open={resched} onOpenChange={setResched} reschedule={appt} />}
      {cancelOpen && <CancelDialog appt={appt} open={cancelOpen} onOpenChange={setCancelOpen} />}
      {followup && <FollowupDialog appt={appt} open={followup} onOpenChange={setFollowup} />}
    </div>
  );
}

function CancelDialog({ appt, open, onOpenChange }: { appt: Appointment; open: boolean; onOpenChange: (o: boolean) => void }) {
  const toast = useToast();
  const [reason, setReason] = useState("");
  const cancel = useAction(
    () =>
      unwrap(api.POST("/api/v1/appointments/{appointment_id}/cancel", { params: { path: { appointment_id: appt.id } }, body: { reason: reason || null, staff_override: false } })),
    groups.schedule,
  );
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Cancel appointment?"
      description={`${appt.patient_name ?? "Patient"} — the slot becomes free immediately.`}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Keep</Button>
          <Button variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate(undefined, { onSuccess: () => { toast("success", "Appointment cancelled"); onOpenChange(false); } })}>
            Cancel appointment
          </Button>
        </>
      }
    >
      <Field label="Reason (optional)">{(id) => <Input id={id} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} />}</Field>
      <div className="mt-3"><InlineError error={cancel.error} /></div>
    </Dialog>
  );
}

/** FR-6.2: one-tap follow-ups after a visit. */
function FollowupDialog({ appt, open, onOpenChange }: { appt: Appointment; open: boolean; onOpenChange: (o: boolean) => void }) {
  const tz = useTz();
  const toast = useToast();
  const rules = useRecallRules();
  const [sessions, setSessions] = useState("10");
  type Body = { kind: "days"; days: number } | { kind: "rule"; visit_type: string } | { kind: "plan"; sessions: number };
  const save = useAction(
    (body: Body) =>
      unwrap(api.POST("/api/v1/appointments/{appointment_id}/followup", { params: { path: { appointment_id: appt.id } }, body })),
    groups.schedule,
  );
  const go = (body: Body) =>
    save.mutate(body, {
      onSuccess: (r) => {
        toast("success", `${r.label} — recall on ${formatDate(r.due_date, tz)}`);
        onOpenChange(false);
      },
    });
  const ruleButtons = (rules.data ?? []).filter((r) => r.is_active && !r.plan_based);
  const planRule = (rules.data ?? []).find((r) => r.plan_based && r.is_active);
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Set follow-up" description={appt.patient_name ?? undefined}>
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-2">
          {[7, 14, 30].map((d) => (
            <Button key={d} variant="secondary" onClick={() => go({ kind: "days", days: d })} disabled={save.isPending}>
              Review in {d} days
            </Button>
          ))}
          {ruleButtons.map((r) => (
            <Button key={r.id} variant="secondary" onClick={() => go({ kind: "rule", visit_type: r.visit_type })} disabled={save.isPending}>
              {r.label} · {r.delay_days >= 150 ? `${Math.round(r.delay_days / 30)} months` : `${r.delay_days} days`}
            </Button>
          ))}
        </div>
        {planRule && (
          <div className="flex items-end gap-2 rounded-lg border border-slate-200 p-3">
            <Field label="Treatment plan — total sessions">
              {(id) => <Input id={id} inputMode="numeric" value={sessions} onChange={(e) => setSessions(e.target.value.replace(/\D/g, "").slice(0, 3))} />}
            </Field>
            <Button onClick={() => go({ kind: "plan", sessions: Number(sessions) })} disabled={Number(sessions) < 2 || save.isPending}>
              Start plan
            </Button>
          </div>
        )}
        <InlineError error={save.error} />
      </div>
    </Dialog>
  );
}
