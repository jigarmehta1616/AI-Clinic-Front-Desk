import { ChevronLeft, ChevronRight, Search, UserPlus } from "lucide-react";
import { useEffect, useState } from "react";

import { api, unwrap } from "@/api/client";
import { groups, useAction, useDoctors, usePatients, type Patient } from "@/api/queries";
import { useTz } from "@/components/layout/AppShell";
import { Button, Field, InlineError, Input, Select } from "@/components/ui";
import { addDays, cn, dayIn, formatDate, formatPhone } from "@/lib/format";

export function DayNav({ day, onChange }: { day: string; onChange: (d: string) => void }) {
  const tz = useTz();
  const today = dayIn(tz);
  return (
    <div className="flex items-center gap-1">
      <Button variant="secondary" size="sm" onClick={() => onChange(addDays(day, -1))} aria-label="Previous day">
        <ChevronLeft className="size-4" />
      </Button>
      <label className="sr-only" htmlFor="day-input">Date</label>
      <input
        id="day-input"
        type="date"
        value={day}
        onChange={(e) => e.target.value && onChange(e.target.value)}
        className="h-9 rounded-lg border border-slate-300 bg-white px-2 text-sm shadow-sm"
      />
      <Button variant="secondary" size="sm" onClick={() => onChange(addDays(day, 1))} aria-label="Next day">
        <ChevronRight className="size-4" />
      </Button>
      {day !== today && (
        <Button variant="ghost" size="sm" onClick={() => onChange(today)}>
          Today
        </Button>
      )}
      <span className="ml-1 hidden text-sm text-slate-500 sm:inline">{formatDate(day, tz)}</span>
    </div>
  );
}

export function DoctorSelect({
  value,
  onChange,
  allowAll,
  id,
}: {
  value: string;
  onChange: (id: string) => void;
  allowAll?: boolean;
  id?: string;
}) {
  const doctors = useDoctors();
  const active = (doctors.data ?? []).filter((d) => d.is_active);
  useEffect(() => {
    if (!allowAll && !value && active[0]) onChange(active[0].id);
  }, [allowAll, value, active, onChange]);
  return (
    <Select id={id} aria-label="Doctor" value={value} onChange={(e) => onChange(e.target.value)} className="h-9 w-auto min-w-44">
      {allowAll && <option value="">All doctors</option>}
      {active.map((d) => (
        <option key={d.id} value={d.id}>
          {d.name}
        </option>
      ))}
    </Select>
  );
}

/** Pick an existing patient by name/phone, or create one inline (FR-2.3 at the desk). */
export function PatientPicker({ value, onChange }: { value: Patient | null; onChange: (p: Patient | null) => void }) {
  const [q, setQ] = useState("");
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState({ name: "", phone: "", age: "" });
  const results = usePatients(q.trim().length >= 2 ? q.trim() : "__none__");
  const create = useAction(
    () =>
      unwrap(
        api.POST("/api/v1/patients", {
          body: { name: form.name, phone: form.phone, age: form.age ? Number(form.age) : null },
        }),
      ),
    ["patients"],
  );

  if (value) {
    return (
      <div className="flex items-center justify-between rounded-lg border border-brand-200 bg-brand-50 px-3 py-2">
        <div>
          <p className="font-medium">{value.name}</p>
          <p className="text-sm text-slate-600">{formatPhone(value.phone)}{value.age != null && ` · ${value.age} y`}</p>
        </div>
        <Button variant="ghost" size="sm" onClick={() => onChange(null)}>
          Change
        </Button>
      </div>
    );
  }
  if (creating) {
    return (
      <div className="space-y-3 rounded-lg border border-slate-200 p-3">
        <Field label="Patient name">{(id) => <Input id={id} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} autoFocus />}</Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="WhatsApp number">{(id) => <Input id={id} type="tel" value={form.phone} onChange={(e) => setForm({ ...form, phone: e.target.value })} />}</Field>
          <Field label="Age">{(id) => <Input id={id} inputMode="numeric" value={form.age} onChange={(e) => setForm({ ...form, age: e.target.value.replace(/\D/g, "").slice(0, 3) })} />}</Field>
        </div>
        <InlineError error={create.error} />
        <div className="flex justify-end gap-2">
          <Button variant="ghost" size="sm" onClick={() => setCreating(false)}>Back</Button>
          <Button size="sm" loading={create.isPending} disabled={!form.name || form.phone.replace(/\D/g, "").length < 10} onClick={() => create.mutate(undefined, { onSuccess: (p) => onChange(p) })}>
            Add patient
          </Button>
        </div>
      </div>
    );
  }
  const list = q.trim().length >= 2 ? (results.data ?? []) : [];
  return (
    <div className="space-y-2">
      <div className="relative">
        <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
        <Input aria-label="Search patient by name or phone" placeholder="Search by name or phone" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" autoFocus />
      </div>
      {list.length > 0 && (
        <ul className="max-h-56 divide-y divide-slate-100 overflow-y-auto rounded-lg border border-slate-200">
          {list.map((p) => (
            <li key={p.id}>
              <button className="flex min-h-11 w-full items-center justify-between px-3 py-2 text-left hover:bg-slate-50" onClick={() => onChange(p)}>
                <span className="font-medium">{p.name}</span>
                <span className="text-sm text-slate-500">{formatPhone(p.phone)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {q.trim().length >= 2 && !results.isFetching && list.length === 0 && <p className="text-sm text-slate-500">No patient found.</p>}
      <Button variant="secondary" size="sm" icon={<UserPlus className="size-4" />} onClick={() => setCreating(true)}>
        New patient
      </Button>
    </div>
  );
}

export function SlotGrid({
  slots,
  value,
  onChange,
  tz,
}: {
  slots: Array<{ start: string }>;
  value: string | null;
  onChange: (start: string) => void;
  tz: string;
}) {
  if (slots.length === 0) return <p className="rounded-lg bg-slate-50 px-3 py-4 text-center text-sm text-slate-500">No free slots on this day.</p>;
  const fmt = new Intl.DateTimeFormat("en-IN", { hour: "numeric", minute: "2-digit", hour12: true, timeZone: tz });
  return (
    <div role="radiogroup" aria-label="Free slots" className="grid grid-cols-3 gap-2 sm:grid-cols-4">
      {slots.map((s) => (
        <button
          key={s.start}
          role="radio"
          aria-checked={value === s.start}
          onClick={() => onChange(s.start)}
          className={cn(
            "tabular min-h-11 rounded-lg border text-sm font-medium",
            value === s.start ? "border-brand-700 bg-brand-700 text-white" : "border-slate-200 bg-white hover:border-brand-600",
          )}
        >
          {fmt.format(new Date(s.start)).toUpperCase()}
        </button>
      ))}
    </div>
  );
}

export const invalidateSchedule = groups.schedule;
