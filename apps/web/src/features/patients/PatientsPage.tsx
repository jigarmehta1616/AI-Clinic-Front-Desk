import { Search, UserPlus } from "lucide-react";
import { useDeferredValue, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { api, unwrap } from "@/api/client";
import { useAction, usePatients } from "@/api/queries";
import { can, useAuth } from "@/auth/AuthProvider";
import { useTz } from "@/components/layout/AppShell";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, InlineError, Input, PageHeader, Select, SkeletonRows } from "@/components/ui";
import { formatDate, formatPhone } from "@/lib/format";

/** FR-7.2 patient list with search. */
export default function PatientsPage() {
  const { session } = useAuth();
  const tz = useTz();
  const [q, setQ] = useState("");
  const deferred = useDeferredValue(q.trim());
  const patients = usePatients(deferred);
  const [adding, setAdding] = useState(false);

  return (
    <>
      <PageHeader
        title="Patients"
        actions={can(session, "desk") && <Button icon={<UserPlus className="size-4" />} onClick={() => setAdding(true)}>New patient</Button>}
      />
      <Card>
        <div className="border-b border-slate-100 p-4">
          <div className="relative max-w-md">
            <Search className="pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2 text-slate-400" aria-hidden />
            <Input aria-label="Search patients" placeholder="Search by name or phone" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" />
          </div>
        </div>
        {patients.isPending ? (
          <SkeletonRows rows={6} />
        ) : patients.isError ? (
          <ErrorState error={patients.error} onRetry={() => void patients.refetch()} />
        ) : patients.data.length === 0 ? (
          <EmptyState title={deferred ? "No matching patients" : "No patients yet"} body="Patients are added automatically when they book on WhatsApp." />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                <tr>
                  <th className="px-4 py-2.5 font-medium sm:px-5">Name</th>
                  <th className="px-4 py-2.5 font-medium">Phone</th>
                  <th className="hidden px-4 py-2.5 font-medium sm:table-cell">Age</th>
                  <th className="hidden px-4 py-2.5 font-medium md:table-cell">Since</th>
                  <th className="px-4 py-2.5 font-medium" />
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {patients.data.map((p) => (
                  <tr key={p.id} className="hover:bg-slate-50">
                    <td className="px-4 py-3 sm:px-5">
                      <Link to={`/patients/${p.id}`} className="font-medium text-slate-900 hover:text-brand-700 hover:underline">{p.name}</Link>
                    </td>
                    <td className="px-4 py-3 whitespace-nowrap text-slate-600">{formatPhone(p.phone)}</td>
                    <td className="hidden px-4 py-3 text-slate-600 sm:table-cell">{p.age ?? "–"}</td>
                    <td className="hidden px-4 py-3 text-slate-600 md:table-cell">{formatDate(p.created_at, tz)}</td>
                    <td className="px-4 py-3 text-right">{p.opted_out_at && <Badge tone="amber">opted out</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
      {adding && <NewPatientDialog open onOpenChange={setAdding} />}
    </>
  );
}

function NewPatientDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const navigate = useNavigate();
  const [f, setF] = useState({ name: "", phone: "", age: "", language: "" });
  const create = useAction(
    () =>
      unwrap(
        api.POST("/api/v1/patients", {
          body: { name: f.name, phone: f.phone, age: f.age ? Number(f.age) : null, language: (f.language || null) as "gu" | "hi" | "en" | null },
        }),
      ),
    ["patients"],
  );
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New patient"
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button loading={create.isPending} disabled={!f.name || f.phone.replace(/\D/g, "").length < 10} onClick={() => create.mutate(undefined, { onSuccess: (p) => navigate(`/patients/${p.id}`) })}>
            Add patient
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Full name">{(id) => <Input id={id} value={f.name} onChange={(e) => setF({ ...f, name: e.target.value })} autoFocus />}</Field>
        <div className="grid grid-cols-2 gap-3">
          <Field label="WhatsApp number">{(id) => <Input id={id} type="tel" value={f.phone} onChange={(e) => setF({ ...f, phone: e.target.value })} />}</Field>
          <Field label="Age">{(id) => <Input id={id} inputMode="numeric" value={f.age} onChange={(e) => setF({ ...f, age: e.target.value.replace(/\D/g, "").slice(0, 3) })} />}</Field>
        </div>
        <Field label="Preferred language">
          {(id) => (
            <Select id={id} value={f.language} onChange={(e) => setF({ ...f, language: e.target.value })}>
              <option value="">Not set</option>
              <option value="gu">Gujarati</option>
              <option value="hi">Hindi</option>
              <option value="en">English</option>
            </Select>
          )}
        </Field>
        <InlineError error={create.error} />
      </div>
    </Dialog>
  );
}
