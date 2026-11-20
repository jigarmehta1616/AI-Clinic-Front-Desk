import { UserPlus } from "lucide-react";
import { useEffect, useState } from "react";

import { api, unwrap } from "@/api/client";
import { useAction, useClinic, useDoctors, useStaff, useUsage, type Clinic, type ClinicSettings } from "@/api/queries";
import { Badge, Button, Card, CardHeader, Dialog, EmptyState, ErrorState, Field, InlineError, Input, PageHeader, Select, SkeletonRows, useToast } from "@/components/ui";
import { formatPhone } from "@/lib/format";

/** Owner settings: clinic profile (FR-1.1), WhatsApp number (FR-1.5), business rules (BR-2..BR-8), staff (FR-1.4). */
export default function SettingsPage() {
  const clinic = useClinic();
  if (clinic.isPending) return <Card><SkeletonRows rows={6} /></Card>;
  if (clinic.isError) return <Card><ErrorState error={clinic.error} onRetry={() => void clinic.refetch()} /></Card>;
  return (
    <>
      <PageHeader title="Settings" subtitle={`Clinic code #${clinic.data.slug} · ${clinic.data.specialty === "dental" ? "Dental" : "Physiotherapy"}`} />
      <div className="grid gap-6 xl:grid-cols-2">
        <ProfileCard clinic={clinic.data} />
        <RulesCard clinic={clinic.data} />
        <StaffCard />
        <UsageCard />
      </div>
    </>
  );
}

function ProfileCard({ clinic }: { clinic: Clinic }) {
  const toast = useToast();
  const [f, setF] = useState(() => init(clinic));
  useEffect(() => {
    setF(init(clinic));
  }, [clinic]);
  const save = useAction(
    () =>
      unwrap(
        api.PATCH("/api/v1/clinic", {
          body: {
            name: f.name,
            address: f.address || null,
            map_url: f.map_url || null,
            phone: f.phone || null,
            default_fee_paise: Math.round(Number(f.fee || 0) * 100),
            wa_phone_number_id: f.wa || null,
            exotel_number: f.exotel || null,
          },
        }),
      ),
    ["clinic"],
  );
  return (
    <Card>
      <CardHeader title="Clinic profile" subtitle="Shown to patients on WhatsApp (address, map, phone, fees)." />
      <div className="grid gap-4 p-4 sm:grid-cols-2 sm:p-5">
        <div className="sm:col-span-2"><Field label="Clinic name">{(id) => <Input id={id} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />}</Field></div>
        <div className="sm:col-span-2"><Field label="Address">{(id) => <Input id={id} value={f.address} onChange={(e) => setF({ ...f, address: e.target.value })} />}</Field></div>
        <Field label="Google Maps link">{(id) => <Input id={id} type="url" value={f.map_url} onChange={(e) => setF({ ...f, map_url: e.target.value })} />}</Field>
        <Field label="Clinic phone" hint="Used in emergency replies and staff alerts.">{(id, d) => <Input id={id} aria-describedby={d} type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />}</Field>
        <Field label="Default consultation fee (₹)">{(id) => <Input id={id} inputMode="numeric" value={f.fee} onChange={(e) => setF({ ...f, fee: e.target.value.replace(/\D/g, "") })} />}</Field>
        <Field label="WhatsApp phone number ID" hint="From Meta WhatsApp Manager. Leave blank to use the shared pilot number.">
          {(id, d) => <Input id={id} aria-describedby={d} inputMode="numeric" value={f.wa} onChange={(e) => setF({ ...f, wa: e.target.value.replace(/\D/g, "") })} />}
        </Field>
        <Field label="Missed-call number (Exotel)" hint="Forward unanswered/busy calls from your clinic phone to this number (FR-3.1).">
          {(id, d) => <Input id={id} aria-describedby={d} type="tel" value={f.exotel} onChange={(e) => setF({ ...f, exotel: e.target.value })} />}
        </Field>
        <div className="flex items-center justify-between gap-3 sm:col-span-2">
          <InlineError error={save.error} />
          <Button className="ml-auto" loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => toast("success", "Profile saved") })}>Save profile</Button>
        </div>
      </div>
    </Card>
  );
}

function init(c: Clinic) {
  return {
    name: c.name,
    address: c.address ?? "",
    map_url: c.map_url ?? "",
    phone: c.phone ?? "",
    fee: String(c.default_fee_paise / 100),
    wa: c.wa_phone_number_id ?? "",
    exotel: c.exotel_number ?? "",
  };
}

const RULES: Array<{ key: keyof ClinicSettings; label: string; hint: string; kind: "number" | "time" | "bool" }> = [
  { key: "booking_horizon_days", label: "Booking horizon (days)", hint: "BR-2 · 1–60", kind: "number" },
  { key: "change_cutoff_minutes", label: "Change / cancel cut-off (minutes)", hint: "BR-3", kind: "number" },
  { key: "max_upcoming_per_doctor", label: "Max upcoming bookings per number per doctor", hint: "BR-4", kind: "number" },
  { key: "token_window_minutes", label: "Tokens open before session (minutes)", hint: "BR-5", kind: "number" },
  { key: "alert_ahead", label: "Queue alert when this many are ahead", hint: "FR-4.3", kind: "number" },
  { key: "noshow_grace_minutes", label: "No-show grace after session end (minutes)", hint: "FR-5.2", kind: "number" },
  { key: "quiet_start", label: "Quiet hours start", hint: "BR-7 · no reminders/recalls", kind: "time" },
  { key: "quiet_end", label: "Quiet hours end", hint: "BR-7", kind: "time" },
  { key: "staff_can_override_cutoff", label: "Staff may cancel inside the cut-off", hint: "Audited", kind: "bool" },
];

function RulesCard({ clinic }: { clinic: Clinic }) {
  const toast = useToast();
  const [s, setS] = useState<ClinicSettings>(clinic.settings);
  useEffect(() => {
    setS(clinic.settings);
  }, [clinic.settings]);
  const save = useAction(() => unwrap(api.PATCH("/api/v1/clinic", { body: { settings: s } })), ["clinic"]);
  return (
    <Card>
      <CardHeader title="Booking & messaging rules" subtitle="Defaults follow the FRD; adjust per clinic." />
      <div className="grid gap-4 p-4 sm:grid-cols-2 sm:p-5">
        {RULES.map((r) => (
          <Field key={r.key} label={r.label} hint={r.hint}>
            {(id, d) =>
              r.kind === "bool" ? (
                <Select id={id} aria-describedby={d} value={String(s[r.key])} onChange={(e) => setS({ ...s, [r.key]: e.target.value === "true" })}>
                  <option value="false">No</option>
                  <option value="true">Yes</option>
                </Select>
              ) : r.kind === "time" ? (
                <Input id={id} aria-describedby={d} type="time" value={String(s[r.key] ?? "").slice(0, 5)} onChange={(e) => setS({ ...s, [r.key]: `${e.target.value}:00` })} />
              ) : (
                <Input id={id} aria-describedby={d} inputMode="numeric" value={String(s[r.key] ?? "")} onChange={(e) => setS({ ...s, [r.key]: Number(e.target.value.replace(/\D/g, "") || 0) })} />
              )
            }
          </Field>
        ))}
        <div className="flex items-center justify-between gap-3 sm:col-span-2">
          <InlineError error={save.error} />
          <Button className="ml-auto" loading={save.isPending} onClick={() => save.mutate(undefined, { onSuccess: () => toast("success", "Rules saved") })}>Save rules</Button>
        </div>
      </div>
    </Card>
  );
}

function StaffCard() {
  const staff = useStaff();
  const [invite, setInvite] = useState(false);
  return (
    <Card>
      <CardHeader title="Staff" subtitle="Each person signs in with their own mobile number." actions={<Button size="sm" icon={<UserPlus className="size-4" />} onClick={() => setInvite(true)}>Invite</Button>} />
      {staff.isPending ? <SkeletonRows rows={3} /> : staff.isError ? <ErrorState error={staff.error} /> : staff.data.length === 0 ? <EmptyState title="No staff yet" /> : (
        <ul className="divide-y divide-slate-100">
          {staff.data.map((m) => (
            <li key={m.id} className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
              <div className="flex-1">
                <p className="font-medium">{m.name || formatPhone(m.phone)}</p>
                <p className="text-sm text-slate-500">{formatPhone(m.phone)}</p>
              </div>
              <Badge tone={m.role === "owner" ? "brand" : "slate"}>{m.role}</Badge>
              {m.status !== "active" && <Badge tone="amber">{m.status}</Badge>}
            </li>
          ))}
        </ul>
      )}
      {invite && <InviteDialog onClose={() => setInvite(false)} />}
    </Card>
  );
}

function InviteDialog({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const doctors = useDoctors();
  const [f, setF] = useState({ phone: "", name: "", role: "receptionist" as "receptionist" | "doctor" | "owner", doctor: "" });
  const save = useAction(
    () => unwrap(api.POST("/api/v1/clinic/staff", { body: { phone: f.phone, name: f.name || null, role: f.role, doctor_id: f.role === "doctor" ? f.doctor || null : null } })),
    ["staff"],
  );
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Invite staff"
      description="They sign in with an OTP on this number; access starts on first sign-in."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button loading={save.isPending} disabled={f.phone.replace(/\D/g, "").length < 10 || (f.role === "doctor" && !f.doctor)} onClick={() => save.mutate(undefined, { onSuccess: () => { toast("success", "Invited"); onClose(); } })}>Invite</Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid grid-cols-2 gap-3">
          <Field label="Mobile number">{(id) => <Input id={id} type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} autoFocus />}</Field>
          <Field label="Name">{(id) => <Input id={id} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} />}</Field>
        </div>
        <Field label="Role">
          {(id) => (
            <Select id={id} value={f.role} onChange={(e) => setF({ ...f, role: e.target.value as typeof f.role })}>
              <option value="receptionist">Receptionist — book, tokens, inbox</option>
              <option value="doctor">Doctor — own schedule & queue</option>
              <option value="owner">Owner — everything</option>
            </Select>
          )}
        </Field>
        {f.role === "doctor" && (
          <Field label="Which doctor profile">
            {(id) => (
              <Select id={id} value={f.doctor} onChange={(e) => setF({ ...f, doctor: e.target.value })}>
                <option value="">Select…</option>
                {doctors.data?.map((d) => <option key={d.id} value={d.id}>{d.name}</option>)}
              </Select>
            )}
          </Field>
        )}
        <InlineError error={save.error} />
      </div>
    </Dialog>
  );
}

/** FR-9.1 / FR-9.3: plan, trial days left, usage with 80 % / 100 % warnings. */
function UsageCard() {
  const usage = useUsage();
  const u = usage.data;
  const meter = (label: string, used: number, limit: number | null, level: string) => (
    <div>
      <div className="flex justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="tabular text-slate-600">{used}{limit ? ` / ${limit}` : ""}</span>
      </div>
      {limit ? (
        <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-slate-100" role="progressbar" aria-label={label} aria-valuenow={used} aria-valuemax={limit}>
          <div
            className={level === "exceeded" ? "h-full bg-red-600" : level === "warning" ? "h-full bg-amber-500" : "h-full bg-brand-600"}
            style={{ width: `${Math.min(100, Math.round((used / limit) * 100))}%` }}
          />
        </div>
      ) : null}
      {level !== "ok" && (
        <p className={level === "exceeded" ? "mt-1 text-xs text-red-700" : "mt-1 text-xs text-amber-700"}>
          {level === "exceeded" ? "Limit reached for this plan." : "Over 80 % of this plan's limit."}
        </p>
      )}
    </div>
  );
  return (
    <Card>
      <CardHeader title="Plan & usage" subtitle="Usage resets on the 1st of each month." />
      {usage.isPending ? <SkeletonRows rows={3} /> : usage.isError || !u ? <ErrorState error={usage.error} /> : (
        <div className="space-y-4 p-4 sm:p-5">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone="brand">{u.plan} plan</Badge>
            <Badge tone={u.status === "suspended" ? "red" : u.status === "trial" ? "amber" : "green"}>{u.status}</Badge>
            {u.days_left != null && <span className="text-sm text-slate-600">{u.days_left} days left in the pilot</span>}
          </div>
          {meter("WhatsApp messages this month", u.messages_this_month, u.messages_limit, u.messages_level)}
          {meter("Active doctors", u.doctors, u.doctors_limit, u.doctors_level)}
          <p className="text-xs text-slate-500">{u.patients} patients · paid plans and GST invoices come with billing (FR-9.2).</p>
        </div>
      )}
    </Card>
  );
}
