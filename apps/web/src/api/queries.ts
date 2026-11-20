import { useMutation, useQuery, useQueryClient, type QueryKey } from "@tanstack/react-query";

import { api, unwrap, type Schemas } from "./client";
import type { paths } from "./schema";
import { sessionStore } from "./session";

export type Clinic = Schemas["ClinicOut"];
export type Doctor = Schemas["DoctorOut"];
export type Patient = Schemas["PatientOut"];
export type Appointment = Schemas["AppointmentOut"];
export type QueueSession = Schemas["QueueSessionOut"];
export type QueueEntry = Schemas["EntryOut"];
export type Today = Schemas["TodayOut"];
export type InboxItem = Schemas["InboxItemOut"];
export type ChatMessage = Schemas["MessageOut"];
export type Recall = Schemas["RecallOut"];
export type RecallRule = Schemas["RuleOut"];
export type Revenue = Schemas["RevenueReportOut"];
export type Staff = Schemas["StaffOut"];
export type Slot = Schemas["SlotOut"];
export type ClinicSettings = Schemas["ClinicSettings"];
export type MissedCall = Schemas["MissedCallOut"];
export type Usage = Schemas["UsageOut"];
export type AdminClinic = Schemas["AdminClinicOut"];

/** Every key starts with the clinic id so switching clinics can never show another tenant's cache. */
export const keys = {
  clinic: () => [cid(), "clinic"] as const,
  me: () => [cid(), "me"] as const,
  doctors: () => [cid(), "doctors"] as const,
  today: (day: string) => [cid(), "today", day] as const,
  appointments: (day: string, doctorId?: string) => [cid(), "appointments", day, doctorId ?? "all"] as const,
  slots: (doctorId: string, from: string, to: string) => [cid(), "slots", doctorId, from, to] as const,
  queue: (doctorId: string, day: string) => [cid(), "queue", doctorId, day] as const,
  patients: (q: string) => [cid(), "patients", q] as const,
  patient: (id: string) => [cid(), "patient", id] as const,
  patientAppointments: (id: string) => [cid(), "patient-appointments", id] as const,
  inbox: (status: string) => [cid(), "inbox", status] as const,
  messages: (conversationId: string) => [cid(), "messages", conversationId] as const,
  recalls: (status?: string, patientId?: string) => [cid(), "recalls", status ?? "all", patientId ?? "all"] as const,
  rules: () => [cid(), "recall-rules"] as const,
  revenue: (month: string) => [cid(), "revenue", month] as const,
  staff: () => [cid(), "staff"] as const,
  exceptions: (from: string) => [cid(), "exceptions", from] as const,
  missedCalls: (status: string) => [cid(), "missed-calls", status] as const,
  usage: () => [cid(), "usage"] as const,
  adminClinics: () => ["platform", "admin-clinics"] as const,
};

function cid(): string {
  return sessionStore.get()?.clinicId ?? "none";
}

/** Resource prefixes invalidated together after a mutation or a live signal. */
export const groups = {
  schedule: ["today", "appointments", "slots", "queue", "patient-appointments", "recalls", "missed-calls"],
  queue: ["queue", "today"],
  inbox: ["inbox", "messages", "today"],
} as const;

export function useInvalidate(): (resources: readonly string[]) => Promise<void> {
  const qc = useQueryClient();
  return async (resources) => {
    await qc.invalidateQueries({
      predicate: (q) => resources.includes(String((q.queryKey as QueryKey)[1])),
    });
  };
}

export function useClinic() {
  return useQuery({ queryKey: keys.clinic(), queryFn: () => unwrap(api.GET("/api/v1/clinic")), staleTime: 60_000 });
}

export function useMe() {
  return useQuery({ queryKey: keys.me(), queryFn: () => unwrap(api.GET("/api/v1/auth/me")), staleTime: 60_000 });
}

export function useDoctors() {
  return useQuery({ queryKey: keys.doctors(), queryFn: () => unwrap(api.GET("/api/v1/doctors")), staleTime: 30_000 });
}

export function useToday(day: string) {
  return useQuery({
    queryKey: keys.today(day),
    queryFn: () => unwrap(api.GET("/api/v1/dashboard/today", { params: { query: { day } } })),
    refetchInterval: 60_000,
  });
}

export function useAppointments(day: string, doctorId?: string) {
  return useQuery({
    queryKey: keys.appointments(day, doctorId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/appointments", { params: { query: { day, doctor_id: doctorId || undefined } } })),
  });
}

export function useSlots(doctorId: string | undefined, from: string, to: string, limit?: number) {
  return useQuery({
    queryKey: keys.slots(doctorId ?? "-", from, to),
    enabled: Boolean(doctorId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/doctors/{doctor_id}/slots", {
          params: { path: { doctor_id: doctorId! }, query: { from, to, limit } },
        }),
      ),
  });
}

export function useQueue(doctorId: string | undefined, day: string) {
  return useQuery({
    queryKey: keys.queue(doctorId ?? "-", day),
    enabled: Boolean(doctorId),
    queryFn: () => unwrap(api.GET("/api/v1/queue", { params: { query: { doctor_id: doctorId!, day } } })),
    refetchInterval: 30_000, // safety net; live signals refresh sooner (NFR-2)
  });
}

export function usePatients(q: string) {
  return useQuery({
    queryKey: keys.patients(q),
    queryFn: () => unwrap(api.GET("/api/v1/patients", { params: { query: { q: q || undefined, limit: 50 } } })),
    placeholderData: (prev) => prev,
  });
}

export function usePatient(id: string) {
  return useQuery({
    queryKey: keys.patient(id),
    queryFn: () => unwrap(api.GET("/api/v1/patients/{patient_id}", { params: { path: { patient_id: id } } })),
  });
}

export function usePatientAppointments(id: string) {
  return useQuery({
    queryKey: keys.patientAppointments(id),
    queryFn: () =>
      unwrap(api.GET("/api/v1/patients/{patient_id}/appointments", { params: { path: { patient_id: id } } })),
  });
}

export function useInbox(status: "open" | "closed", enabled = true) {
  return useQuery({
    queryKey: keys.inbox(status),
    enabled,
    queryFn: () => unwrap(api.GET("/api/v1/inbox", { params: { query: { status } } })),
    refetchInterval: 60_000,
  });
}

export function useMessages(conversationId: string | undefined) {
  return useQuery({
    queryKey: keys.messages(conversationId ?? "-"),
    enabled: Boolean(conversationId),
    queryFn: () =>
      unwrap(
        api.GET("/api/v1/inbox/conversations/{conversation_id}/messages", {
          params: { path: { conversation_id: conversationId! } },
        }),
      ),
  });
}

export type RecallStatus = NonNullable<
  NonNullable<paths["/api/v1/recalls"]["get"]["parameters"]["query"]>["status"]
>;

export function useRecalls(status?: RecallStatus, patientId?: string) {
  return useQuery({
    queryKey: keys.recalls(status, patientId),
    queryFn: () =>
      unwrap(api.GET("/api/v1/recalls", { params: { query: { status, patient_id: patientId } } })),
  });
}

export function useRecallRules() {
  return useQuery({ queryKey: keys.rules(), queryFn: () => unwrap(api.GET("/api/v1/recall/rules")) });
}

export function useRevenue(month: string, enabled = true) {
  return useQuery({
    queryKey: keys.revenue(month),
    enabled,
    queryFn: () => unwrap(api.GET("/api/v1/reports/revenue", { params: { query: { month } } })),
  });
}

export function useStaff(enabled = true) {
  return useQuery({ queryKey: keys.staff(), enabled, queryFn: () => unwrap(api.GET("/api/v1/clinic/staff")) });
}

export function useExceptions(from: string) {
  return useQuery({
    queryKey: keys.exceptions(from),
    queryFn: () => unwrap(api.GET("/api/v1/schedule-exceptions", { params: { query: { from } } })),
  });
}

/** Mutation that invalidates resource groups on success. */
export function useAction<TVars, TData>(
  fn: (vars: TVars) => Promise<TData>,
  invalidate: readonly string[],
) {
  const inv = useInvalidate();
  return useMutation({ mutationFn: fn, onSuccess: () => inv(invalidate) });
}


export type MissedCallStatus = "pending" | "recovered" | "call_back_needed" | "resolved";

export function useMissedCalls(status?: MissedCallStatus, enabled = true) {
  return useQuery({
    queryKey: keys.missedCalls(status ?? "all"),
    enabled,
    queryFn: () => unwrap(api.GET("/api/v1/missed-calls", { params: { query: { status } } })),
    refetchInterval: 60_000,
  });
}

export function useUsage(enabled = true) {
  return useQuery({ queryKey: keys.usage(), enabled, queryFn: () => unwrap(api.GET("/api/v1/clinic/usage")), staleTime: 60_000 });
}

export function useAdminClinics(enabled = true) {
  return useQuery({ queryKey: keys.adminClinics(), enabled, queryFn: () => unwrap(api.GET("/api/v1/admin/clinics")) });
}
