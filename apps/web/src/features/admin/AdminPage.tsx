import { LogOut, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Navigate } from "react-router-dom";

import { api, errorMessage, unwrap } from "@/api/client";
import { useAction, useAdminClinics, type AdminClinic } from "@/api/queries";
import { useAuth } from "@/auth/AuthProvider";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, InlineError, Input, PageHeader, Select, SkeletonRows, useToast } from "@/components/ui";
import { formatDate } from "@/lib/format";

/** FR-9.4 platform admin console: trials, plans, suspension. Clinic-level counts only — no patient data (DP-10). */
export default function AdminPage() {
  const { session, signOut } = useAuth();
  const clinics = useAdminClinics(Boolean(session?.isPlatformAdmin));
  const [editing, setEditing] = useState<AdminClinic | null>(null);
  if (!session?.isPlatformAdmin) return <Navigate to="/" replace />;

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <div className="mb-2 flex items-center justify-between">
        <span className="inline-flex items-center gap-2 text-sm font-medium text-brand-800"><ShieldCheck className="size-4" aria-hidden /> Platform admin</span>
        <button className="inline-flex items-center gap-1.5 text-sm text-slate-600 hover:text-slate-900" onClick={() => void signOut()}>
          <LogOut className="size-4" aria-hidden /> Sign out
        </button>
      </div>
      <PageHeader title="Clinics" subtitle="Trials, plans and usage. Conversations and patient records are not visible here (DP-10)." />
      <Card>
        {clinics.isPending ? <SkeletonRows rows={5} /> : clinics.isError ? <ErrorState error={clinics.error} onRetry={() => void clinics.refetch()} /> : clinics.data.length === 0 ? (
          <EmptyState title="No clinics yet" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Clinic</th>
                  <th className="px-4 py-2.5 font-medium">Plan</th>
                  <th className="px-4 py-2.5 font-medium">Status</th>
                  <th className="px-4 py-2.5 text-right font-medium">Messages (month)</th>
                  <th className="px-4 py-2.5 text-right font-medium">Doctors</th>
                  <th className="px-4 py-2.5 text-right font-medium">Patients</th>
                  <th className="px-4 py-2.5" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {clinics.data.map((c) => (
                  <tr key={c.id}>
                    <td className="px-4 py-3">
                      <p className="font-medium">{c.name}</p>
                      <p className="text-xs text-slate-500">#{c.slug} · {c.specialty} · since {c.created_at ? formatDate(c.created_at, "Asia/Kolkata") : "–"}</p>
                    </td>
                    <td className="px-4 py-3 capitalize">{c.plan}</td>
                    <td className="px-4 py-3">
                      <Badge tone={c.status === "suspended" ? "red" : c.status === "trial" ? "amber" : "green"}>{c.status}</Badge>
                      {c.status === "trial" && c.days_left != null && <span className="ml-1 text-xs text-slate-500">{c.days_left} days left</span>}
                    </td>
                    <td className="tabular px-4 py-3 text-right">
                      {c.messages_this_month}{c.messages_limit ? ` / ${c.messages_limit}` : ""}
                      {c.messages_level !== "ok" && <Badge tone={c.messages_level === "exceeded" ? "red" : "amber"} className="ml-1">{c.messages_level}</Badge>}
                    </td>
                    <td className="tabular px-4 py-3 text-right">{c.doctors}</td>
                    <td className="tabular px-4 py-3 text-right">{c.patients}</td>
                    <td className="px-4 py-3 text-right"><Button size="sm" variant="secondary" onClick={() => setEditing(c)}>Manage</Button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {editing && <ManageDialog clinic={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}

function ManageDialog({ clinic, onClose }: { clinic: AdminClinic; onClose: () => void }) {
  const toast = useToast();
  const [days, setDays] = useState("30");
  const [plan, setPlan] = useState(clinic.plan as "pilot" | "basic" | "pro");
  const [reason, setReason] = useState("");
  const path = { params: { path: { clinic_id: clinic.id } } };
  const act = useAction(
    (a: "extend" | "plan" | "suspend" | "reactivate") => {
      if (a === "extend") return unwrap(api.POST("/api/v1/admin/clinics/{clinic_id}/extend-trial", { ...path, body: { days: Number(days) } }));
      if (a === "plan") return unwrap(api.POST("/api/v1/admin/clinics/{clinic_id}/plan", { ...path, body: { plan } }));
      if (a === "suspend") return unwrap(api.POST("/api/v1/admin/clinics/{clinic_id}/suspend", { ...path, body: { reason } }));
      return unwrap(api.POST("/api/v1/admin/clinics/{clinic_id}/reactivate", path));
    },
    ["admin-clinics"],
  );
  const run = (a: Parameters<typeof act.mutate>[0], msg: string) =>
    act.mutate(a, { onSuccess: () => { toast("success", msg); onClose(); }, onError: (e) => toast("error", errorMessage(e)) });
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()} title={clinic.name} description="Every change is written to the clinic's audit log.">
      <div className="space-y-5">
        <div className="flex items-end gap-2">
          <Field label="Extend trial by (days)">{(id) => <Input id={id} inputMode="numeric" value={days} onChange={(e) => setDays(e.target.value.replace(/\D/g, ""))} />}</Field>
          <Button variant="secondary" disabled={!Number(days)} onClick={() => run("extend", "Trial extended")}>Extend</Button>
        </div>
        <div className="flex items-end gap-2">
          <Field label="Plan">
            {(id) => (
              <Select id={id} value={plan} onChange={(e) => setPlan(e.target.value as typeof plan)}>
                <option value="pilot">Pilot</option>
                <option value="basic">Basic</option>
                <option value="pro">Pro</option>
              </Select>
            )}
          </Field>
          <Button variant="secondary" disabled={plan === clinic.plan} onClick={() => run("plan", "Plan changed")}>Change</Button>
        </div>
        {clinic.status === "suspended" ? (
          <Button variant="success" onClick={() => run("reactivate", "Clinic reactivated")}>Reactivate clinic</Button>
        ) : (
          <div className="space-y-2 rounded-lg border border-red-200 p-3">
            <Field label="Suspend — reason" hint="Staff lose access within 30 seconds; WhatsApp messages are ignored.">
              {(id, d) => <Input id={id} aria-describedby={d} value={reason} onChange={(e) => setReason(e.target.value)} maxLength={200} />}
            </Field>
            <Button variant="danger" disabled={reason.trim().length < 3} onClick={() => run("suspend", "Clinic suspended")}>Suspend clinic</Button>
          </div>
        )}
        <InlineError error={act.error} />
      </div>
    </Dialog>
  );
}
