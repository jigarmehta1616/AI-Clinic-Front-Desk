import { useMutation } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";

import { api, unwrap } from "@/api/client";
import { useAuth } from "@/auth/AuthProvider";
import { Button, Card, Field, InlineError, Input, Select } from "@/components/ui";

/** FR-1.1 clinic profile + FR-1.6 specialty template; next steps (doctors, WhatsApp) follow in Doctors/Settings. */
export default function OnboardingPage() {
  const { signIn, signOut } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({
    name: "",
    slug: "",
    specialty: "dental" as "dental" | "physio",
    address: "",
    map_url: "",
    phone: "",
    fee: "500",
  });
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });

  const create = useMutation({
    mutationFn: () =>
      unwrap(
        api.POST("/api/v1/clinics", {
          body: {
            name: form.name,
            slug: form.slug.toUpperCase(),
            specialty: form.specialty,
            address: form.address || null,
            map_url: form.map_url || null,
            phone: form.phone || null,
            default_fee_paise: Math.round(Number(form.fee || 0) * 100),
            languages: ["gu", "hi", "en"],
          },
        }),
      ),
    onSuccess: (r) => {
      signIn(r.tokens);
      navigate("/doctors?welcome=1", { replace: true });
    },
  });

  const submit = (e: FormEvent) => {
    e.preventDefault();
    create.mutate();
  };

  return (
    <div className="min-h-dvh bg-gradient-to-b from-brand-50 to-slate-50 px-4 py-10">
      <div className="mx-auto max-w-xl">
        <p className="text-sm font-medium text-brand-700">Step 1 of 3 · Clinic profile</p>
        <h1 className="mt-1 text-2xl font-semibold">Set up your clinic</h1>
        <p className="mt-1 text-sm text-slate-500">
          Next you&apos;ll add doctors and their weekly sessions, then connect WhatsApp. Most clinics are live in under 30 minutes.
        </p>
        <Card className="mt-6 p-6">
          <form onSubmit={submit} className="grid gap-4 sm:grid-cols-2" noValidate>
            <div className="sm:col-span-2">
              <Field label="Clinic name">
                {(id) => <Input id={id} value={form.name} onChange={set("name")} required autoFocus placeholder="Smile Dental Studio" />}
              </Field>
            </div>
            <Field label="Clinic code" hint="3–12 letters/numbers. Patients type it on a shared WhatsApp number, e.g. #SMILE.">
              {(id, d) => (
                <Input id={id} aria-describedby={d} value={form.slug} onChange={(e) => setForm({ ...form, slug: e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, "") })} maxLength={12} required />
              )}
            </Field>
            <Field label="Specialty" hint="Pre-fills recall rules (FR-1.6). You can edit them later.">
              {(id, d) => (
                <Select id={id} aria-describedby={d} value={form.specialty} onChange={set("specialty")}>
                  <option value="dental">Dental</option>
                  <option value="physio">Physiotherapy</option>
                </Select>
              )}
            </Field>
            <div className="sm:col-span-2">
              <Field label="Address">{(id) => <Input id={id} value={form.address} onChange={set("address")} placeholder="CG Road, Ahmedabad" />}</Field>
            </div>
            <Field label="Google Maps link">{(id) => <Input id={id} type="url" value={form.map_url} onChange={set("map_url")} placeholder="https://maps.app.goo.gl/…" />}</Field>
            <Field label="Clinic phone">{(id) => <Input id={id} type="tel" value={form.phone} onChange={set("phone")} placeholder="98765 43210" />}</Field>
            <Field label="Consultation fee (₹)" hint="Used for the estimated recovered-revenue report.">
              {(id, d) => <Input id={id} aria-describedby={d} inputMode="numeric" value={form.fee} onChange={(e) => setForm({ ...form, fee: e.target.value.replace(/\D/g, "") })} />}
            </Field>
            <div className="sm:col-span-2 space-y-3">
              <InlineError error={create.error} />
              <div className="flex items-center justify-between">
                <button type="button" className="text-sm text-slate-500 hover:text-slate-800" onClick={() => void signOut()}>
                  Sign out
                </button>
                <Button type="submit" loading={create.isPending} disabled={form.name.length < 2 || form.slug.length < 3}>
                  Create clinic
                </Button>
              </div>
            </div>
          </form>
        </Card>
      </div>
    </div>
  );
}
