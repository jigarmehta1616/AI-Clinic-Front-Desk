import { useEffect, useState } from "react";

import { ApiError, api, unwrap } from "@/api/client";
import { groups, useAction, useSlots, type Appointment, type Patient } from "@/api/queries";
import { useTz } from "@/components/layout/AppShell";
import { Button, Dialog, Field, InlineError, Input, Spinner, useToast } from "@/components/ui";
import { dayIn, formatDateTime } from "@/lib/format";

import { DoctorSelect, PatientPicker, SlotGrid } from "./pickers";

/** Book a new appointment, or reschedule `reschedule` (FR-2.4, BR-1..BR-4 enforced server-side). */
export function BookDialog({
  open,
  onOpenChange,
  initialDoctorId,
  initialDay,
  initialPatient,
  reschedule,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  initialDoctorId?: string;
  initialDay?: string;
  initialPatient?: Patient | null;
  reschedule?: Appointment | null;
}) {
  const tz = useTz();
  const toast = useToast();
  const [doctorId, setDoctorId] = useState(reschedule?.doctor_id ?? initialDoctorId ?? "");
  const [day, setDay] = useState(initialDay ?? dayIn(tz));
  const [slot, setSlot] = useState<string | null>(null);
  const [patient, setPatient] = useState<Patient | null>(initialPatient ?? null);
  const [visitType, setVisitType] = useState("");

  useEffect(() => {
    if (open) {
      setDoctorId(reschedule?.doctor_id ?? initialDoctorId ?? "");
      setDay(initialDay ?? dayIn(tz));
      setSlot(null);
      setPatient(initialPatient ?? null);
      setVisitType("");
    }
  }, [open, reschedule, initialDoctorId, initialDay, initialPatient, tz]);
  useEffect(() => {
    setSlot(null);
  }, [doctorId, day]);

  const slots = useSlots(doctorId || undefined, day, day);
  const save = useAction(async () => {
    if (!slot) throw new Error("no slot");
    if (reschedule) {
      return unwrap(
        api.POST("/api/v1/appointments/{appointment_id}/reschedule", {
          params: { path: { appointment_id: reschedule.id } },
          body: { slot_start: slot, doctor_id: doctorId },
        }),
      );
    }
    return unwrap(
      api.POST("/api/v1/appointments", {
        body: { doctor_id: doctorId, patient_id: patient!.id, slot_start: slot, source: "staff", visit_type: visitType || null },
      }),
    );
  }, groups.schedule);

  const submit = () =>
    save.mutate(undefined, {
      onSuccess: (a) => {
        toast("success", `${reschedule ? "Rescheduled" : "Booked"} for ${formatDateTime(a.slot_start, tz)}`);
        onOpenChange(false);
      },
      onError: (e) => {
        if (e instanceof ApiError && e.code === "slot_taken") void slots.refetch(); // AC-2: show what's left
      },
    });

  const canSave = Boolean(doctorId && slot && (reschedule || patient));
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      wide
      title={reschedule ? "Reschedule appointment" : "Book appointment"}
      description={reschedule ? `Currently ${formatDateTime(reschedule.slot_start, tz)} · ${reschedule.patient_name ?? ""}` : undefined}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button onClick={submit} loading={save.isPending} disabled={!canSave}>
            {reschedule ? "Move appointment" : "Book"}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        {!reschedule && (
          <div>
            <p className="mb-1.5 text-sm font-medium text-slate-700">Patient</p>
            <PatientPicker value={patient} onChange={setPatient} />
          </div>
        )}
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Doctor">{(id) => <DoctorSelect id={id} value={doctorId} onChange={setDoctorId} />}</Field>
          <Field label="Date">{(id) => <Input id={id} type="date" value={day} min={dayIn(tz)} onChange={(e) => e.target.value && setDay(e.target.value)} />}</Field>
        </div>
        <div>
          <p className="mb-1.5 text-sm font-medium text-slate-700">Time</p>
          {slots.isPending && doctorId ? <Spinner /> : <SlotGrid slots={slots.data ?? []} value={slot} onChange={setSlot} tz={tz} />}
        </div>
        {!reschedule && (
          <Field label="Visit type (optional)" hint="e.g. cleaning, checkup, physio_session — drives automatic recalls">
            {(id, d) => <Input id={id} aria-describedby={d} value={visitType} onChange={(e) => setVisitType(e.target.value.toLowerCase().replace(/[^a-z_]/g, ""))} />}
          </Field>
        )}
        <InlineError error={save.error} />
      </div>
    </Dialog>
  );
}
