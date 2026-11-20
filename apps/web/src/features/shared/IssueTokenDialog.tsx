import { useEffect, useState } from "react";

import { api, unwrap } from "@/api/client";
import { groups, useAction, type Patient } from "@/api/queries";
import { Button, Dialog, Field, InlineError, Input, Segmented, useToast } from "@/components/ui";

import { DoctorSelect, PatientPicker } from "./pickers";

/** FR-4.1: receptionist issues a walk-in token (BR-5 window and limit enforced server-side). */
export function IssueTokenDialog({
  open,
  onOpenChange,
  initialDoctorId,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  initialDoctorId?: string;
}) {
  const toast = useToast();
  const [doctorId, setDoctorId] = useState(initialDoctorId ?? "");
  const [mode, setMode] = useState<"patient" | "phone" | "anonymous">("patient");
  const [patient, setPatient] = useState<Patient | null>(null);
  const [phone, setPhone] = useState("");
  useEffect(() => {
    if (open) {
      setDoctorId(initialDoctorId ?? "");
      setPatient(null);
      setPhone("");
    }
  }, [open, initialDoctorId]);

  const issue = useAction(
    () =>
      unwrap(
        api.POST("/api/v1/queue/tokens", {
          body: {
            doctor_id: doctorId,
            patient_id: mode === "patient" ? (patient?.id ?? null) : null,
            phone: mode === "phone" && phone ? phone : null,
          },
        }),
      ),
    groups.queue,
  );
  const ready = doctorId && (mode === "anonymous" || (mode === "patient" && patient) || (mode === "phone" && phone.replace(/\D/g, "").length >= 10));
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Issue walk-in token"
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button
            loading={issue.isPending}
            disabled={!ready}
            onClick={() =>
              issue.mutate(undefined, {
                onSuccess: (e) => {
                  toast("success", `Token ${e.token_no} issued`);
                  onOpenChange(false);
                },
              })
            }
          >
            Issue token
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Doctor">{(id) => <DoctorSelect id={id} value={doctorId} onChange={setDoctorId} />}</Field>
        <Segmented
          label="Who is the token for"
          value={mode}
          onChange={setMode}
          options={[
            { value: "patient", label: "Patient" },
            { value: "phone", label: "Phone only" },
            { value: "anonymous", label: "No details" },
          ]}
        />
        {mode === "patient" && <PatientPicker value={patient} onChange={setPatient} />}
        {mode === "phone" && (
          <Field label="WhatsApp number" hint="They'll get an alert when 3 patients are ahead (FR-4.3).">
            {(id, d) => <Input id={id} aria-describedby={d} type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} autoFocus />}
          </Field>
        )}
        <InlineError error={issue.error} />
      </div>
    </Dialog>
  );
}
