import { useMutation } from "@tanstack/react-query";
import { ArrowLeft, Building2 } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router-dom";

import { api, unwrap, type Schemas } from "@/api/client";
import { sessionFromTokens } from "@/api/session";
import { useAuth } from "@/auth/AuthProvider";
import { Button, Card, Field, InlineError, Input } from "@/components/ui";

type Step = "phone" | "code" | "pick";

export function LoginPage() {
  const { status, session, signIn } = useAuth();
  const navigate = useNavigate();
  const from = (useLocation().state as { from?: string } | null)?.from ?? "/";
  const [step, setStep] = useState<Step>("phone");
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [memberships, setMemberships] = useState<Schemas["MembershipSummary"][]>([]);

  const request = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/otp/request", { body: { phone } })),
    onSuccess: () => setStep("code"),
  });
  const verify = useMutation({
    mutationFn: () => unwrap(api.POST("/api/v1/auth/otp/verify", { body: { phone, code } })),
    onSuccess: (t) => {
      signIn(t);
      if (t.clinic_id) navigate(from, { replace: true });
      else if (t.memberships.length > 1) {
        setMemberships(t.memberships);
        setStep("pick");
      } else navigate(sessionFromTokens(t).isPlatformAdmin ? "/admin" : "/onboarding", { replace: true });
    },
  });
  const pick = useMutation({
    mutationFn: (clinicId: string) =>
      unwrap(api.POST("/api/v1/auth/select-clinic", { body: { clinic_id: clinicId } })),
    onSuccess: (t) => {
      signIn(t);
      navigate(from, { replace: true });
    },
  });

  if (status === "authenticated" && session?.clinicId && step !== "pick") return <Navigate to={from} replace />;

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (step === "phone") request.mutate();
    else if (step === "code") verify.mutate();
  };

  return (
    <div className="flex min-h-dvh items-center justify-center bg-gradient-to-b from-brand-50 to-slate-50 px-4 py-10">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <div className="flex size-10 items-center justify-center rounded-xl bg-brand-700 text-xl font-bold text-white" aria-hidden>
            +
          </div>
          <span className="text-xl font-semibold text-slate-900">ClinicDesk AI</span>
        </div>
        <Card className="p-6">
          {step === "pick" ? (
            <div className="space-y-3">
              <h1 className="text-lg font-semibold">Choose a clinic</h1>
              {memberships.map((m) => (
                <button
                  key={m.clinic_id}
                  onClick={() => pick.mutate(m.clinic_id)}
                  className="flex min-h-12 w-full items-center gap-3 rounded-lg border border-slate-200 px-4 text-left hover:border-brand-600 hover:bg-brand-50"
                >
                  <Building2 className="size-5 text-slate-500" aria-hidden />
                  <span className="flex-1 font-medium">{m.clinic_name}</span>
                  <span className="text-xs capitalize text-slate-500">{m.role}</span>
                </button>
              ))}
              <InlineError error={pick.error} />
            </div>
          ) : (
            <form onSubmit={submit} className="space-y-4" noValidate>
              <div>
                <h1 className="text-lg font-semibold">{step === "phone" ? "Sign in" : "Enter the code"}</h1>
                <p className="mt-1 text-sm text-slate-500">
                  {step === "phone"
                    ? "We'll send a one-time code to your mobile number."
                    : `We sent a 6-digit code to ${phone}.`}
                </p>
              </div>
              {step === "phone" ? (
                <Field label="Mobile number">
                  {(id) => (
                    <Input
                      id={id}
                      type="tel"
                      inputMode="tel"
                      autoComplete="tel"
                      placeholder="98765 43210"
                      value={phone}
                      onChange={(e) => setPhone(e.target.value)}
                      required
                      autoFocus
                    />
                  )}
                </Field>
              ) : (
                <Field label="One-time code">
                  {(id) => (
                    <Input
                      id={id}
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      pattern="\d{6}"
                      maxLength={6}
                      value={code}
                      onChange={(e) => setCode(e.target.value.replace(/\D/g, ""))}
                      className="tabular text-center text-lg tracking-[0.4em]"
                      required
                      autoFocus
                    />
                  )}
                </Field>
              )}
              <InlineError error={step === "phone" ? request.error : verify.error} />
              <Button
                type="submit"
                className="w-full"
                loading={request.isPending || verify.isPending}
                disabled={step === "phone" ? phone.replace(/\D/g, "").length < 10 : code.length !== 6}
              >
                {step === "phone" ? "Send code" : "Verify and sign in"}
              </Button>
              {step === "code" && (
                <div className="flex items-center justify-between text-sm">
                  <button type="button" className="inline-flex items-center gap-1 text-slate-600 hover:text-slate-900" onClick={() => setStep("phone")}>
                    <ArrowLeft className="size-4" aria-hidden /> Change number
                  </button>
                  <button type="button" className="font-medium text-brand-700 hover:underline" onClick={() => request.mutate()} disabled={request.isPending}>
                    Resend code
                  </button>
                </div>
              )}
            </form>
          )}
        </Card>
        <p className="mt-6 text-center text-xs text-slate-500">For clinic staff. Patients use WhatsApp — no app needed.</p>
      </div>
    </div>
  );
}
