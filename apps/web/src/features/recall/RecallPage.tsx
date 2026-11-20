import { useState } from "react";
import { Link } from "react-router-dom";

import { api, unwrap } from "@/api/client";
import { useAction, useDoctors, useRecallRules, useRecalls, type RecallRule, type RecallStatus } from "@/api/queries";
import { can, useAuth } from "@/auth/AuthProvider";
import { useTz } from "@/components/layout/AppShell";
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Field, InlineError, Input, PageHeader, Segmented, SkeletonRows, StatusBadge, useToast } from "@/components/ui";
import { formatDate, formatPhone } from "@/lib/format";

const TABS: Array<{ value: RecallStatus; label: string }> = [
  { value: "scheduled", label: "Scheduled" },
  { value: "sent", label: "Waiting reply" },
  { value: "booked", label: "Booked" },
  { value: "lapsed", label: "Lapsed" },
  { value: "declined", label: "Declined" },
  { value: "skipped", label: "Skipped" },
];

/** FR-6.x recall pipeline + rules (owner). */
export default function RecallPage() {
  const tz = useTz();
  const { session } = useAuth();
  const [tab, setTab] = useState<RecallStatus>("scheduled");
  const recalls = useRecalls(tab);
  const doctors = useDoctors();
  const doctorName = (id: string) => doctors.data?.find((d) => d.id === id)?.name ?? "";

  return (
    <>
      <PageHeader title="Recall" subtitle="Patients due to come back. Messages respect quiet hours, consent and the 3-day limit." />
      <Card>
        <div className="overflow-x-auto border-b border-slate-100 p-3">
          <Segmented label="Recall status" value={tab} onChange={setTab} options={TABS} />
        </div>
        {recalls.isPending ? (
          <SkeletonRows />
        ) : recalls.isError ? (
          <ErrorState error={recalls.error} onRetry={() => void recalls.refetch()} />
        ) : recalls.data.length === 0 ? (
          <EmptyState title="Nothing here" body="Recalls are created when a visit is completed or a follow-up is set." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium sm:px-5">Patient</th>
                  <th className="px-4 py-2.5 font-medium">Recall</th>
                  <th className="px-4 py-2.5 font-medium">Due</th>
                  <th className="hidden px-4 py-2.5 font-medium md:table-cell">Doctor</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {recalls.data.map((r) => (
                  <tr key={r.id}>
                    <td className="px-4 py-3 sm:px-5">
                      <Link to={`/patients/${r.patient_id}`} className="font-medium hover:text-brand-700 hover:underline">{r.patient_name ?? "Patient"}</Link>
                      {r.patient_phone && <p className="text-xs text-slate-500">{formatPhone(r.patient_phone)}</p>}
                    </td>
                    <td className="px-4 py-3">{r.label}</td>
                    <td className="px-4 py-3 whitespace-nowrap">{formatDate(r.due_date, tz)}</td>
                    <td className="hidden px-4 py-3 md:table-cell">{doctorName(r.doctor_id)}</td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap items-center gap-1.5">
                        <StatusBadge status={r.status} />
                        {r.sends > 1 && <Badge>{r.sends - 1} follow-up{r.sends > 2 ? "s" : ""}</Badge>}
                        {r.closed_reason && <span className="text-xs text-slate-500">{r.closed_reason.replace(/_/g, " ")}</span>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {can(session, "owner") && <RulesCard />}
    </>
  );
}

function RulesCard() {
  const rules = useRecallRules();
  const [editing, setEditing] = useState<RecallRule | null>(null);
  return (
    <Card className="mt-6">
      <CardHeader title="Recall rules" subtitle="Per visit type (FR-6.1). Starting points come from your specialty template." />
      {rules.isPending ? <SkeletonRows rows={3} /> : rules.isError ? <ErrorState error={rules.error} /> : (
        <ul className="divide-y divide-slate-100">
          {rules.data.map((r) => (
            <li key={r.id} className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
              <div className="min-w-0 flex-1">
                <p className="font-medium">{r.label} {!r.is_active && <Badge>off</Badge>}</p>
                <p className="text-sm text-slate-500">
                  {r.plan_based ? `Next session every ${r.delay_days} day(s) until the plan is done` : `Recall ${r.delay_days} days after the visit`}
                  {r.followup_days.length > 0 && ` · follow-ups after ${r.followup_days.join(" & ")} days`}
                </p>
              </div>
              <code className="text-xs text-slate-400">{r.visit_type}</code>
              <Button size="sm" variant="secondary" onClick={() => setEditing(r)}>Edit</Button>
            </li>
          ))}
        </ul>
      )}
      {editing && <RuleDialog rule={editing} onClose={() => setEditing(null)} />}
    </Card>
  );
}

function RuleDialog({ rule, onClose }: { rule: RecallRule; onClose: () => void }) {
  const toast = useToast();
  const [f, setF] = useState({ label: rule.label, delay: String(rule.delay_days), followups: rule.followup_days.join(", "), active: rule.is_active });
  const followups = f.followups.split(/[,\s]+/).filter(Boolean).map(Number);
  const save = useAction(
    () =>
      unwrap(
        api.PUT("/api/v1/recall/rules/{visit_type}", {
          params: { path: { visit_type: rule.visit_type } },
          body: { label: f.label, delay_days: Number(f.delay), followup_days: followups, plan_based: rule.plan_based, is_active: f.active },
        }),
      ),
    ["recall-rules"],
  );
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Edit rule · ${rule.visit_type}`}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => { toast("success", "Rule saved"); onClose(); } })}>Save</Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Label shown to patients">{(id) => <Input id={id} value={f.label} onChange={(e) => setF({ ...f, label: e.target.value })} maxLength={80} />}</Field>
        <Field label={rule.plan_based ? "Days between sessions" : "Days after the visit"}>
          {(id) => <Input id={id} inputMode="numeric" value={f.delay} onChange={(e) => setF({ ...f, delay: e.target.value.replace(/\D/g, "") })} />}
        </Field>
        <Field label="Follow-up days (max 2)" hint="Sent if there is no reply, counted from the first message. Default 3, 7.">
          {(id, d) => <Input id={id} aria-describedby={d} value={f.followups} onChange={(e) => setF({ ...f, followups: e.target.value })} />}
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" className="size-4" checked={f.active} onChange={(e) => setF({ ...f, active: e.target.checked })} /> Rule is active
        </label>
        <InlineError error={save.error} />
      </div>
    </Dialog>
  );
}
