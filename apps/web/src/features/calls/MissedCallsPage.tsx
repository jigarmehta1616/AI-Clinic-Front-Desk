import { CalendarPlus, Phone, PhoneMissed, Plus } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { api, errorMessage, unwrap } from "@/api/client";
import { useAction, useMissedCalls, type MissedCall, type MissedCallStatus, type Patient } from "@/api/queries";
import { useTz } from "@/components/layout/AppShell";
import { Badge, Button, Card, Dialog, EmptyState, ErrorState, Field, InlineError, Input, PageHeader, Segmented, SkeletonRows, useToast } from "@/components/ui";
import { BookDialog } from "@/features/shared/BookDialog";
import { formatDateTime, formatPhone } from "@/lib/format";

const TABS: Array<{ value: MissedCallStatus | "open"; label: string }> = [
  { value: "call_back_needed", label: "Call back" },
  { value: "pending", label: "Waiting on WhatsApp" },
  { value: "recovered", label: "Recovered" },
  { value: "resolved", label: "Closed" },
];
const STATUS: Record<string, { label: string; tone: "red" | "amber" | "green" | "slate" }> = {
  call_back_needed: { label: "Call back needed", tone: "red" },
  pending: { label: "Offer sent", tone: "amber" },
  recovered: { label: "Recovered — booked", tone: "green" },
  resolved: { label: "Closed", tone: "slate" },
};

/** FR-3.4: missed calls with status recovered / pending / call back needed. */
export default function MissedCallsPage() {
  const [tab, setTab] = useState<MissedCallStatus>("call_back_needed");
  const calls = useMissedCalls(tab);
  const [adding, setAdding] = useState(false);

  return (
    <>
      <PageHeader
        title="Missed calls"
        subtitle="Unanswered calls get a WhatsApp booking offer within a minute. Call back anyone who didn't book."
        actions={<Button variant="secondary" icon={<Plus className="size-4" />} onClick={() => setAdding(true)}>Log a missed call</Button>}
      />
      <Card>
        <div className="overflow-x-auto border-b border-slate-100 p-3">
          <Segmented label="Missed-call status" value={tab} onChange={(v) => setTab(v as MissedCallStatus)} options={TABS} />
        </div>
        {calls.isPending ? (
          <SkeletonRows />
        ) : calls.isError ? (
          <ErrorState error={calls.error} onRetry={() => void calls.refetch()} />
        ) : calls.data.length === 0 ? (
          <EmptyState
            icon={<PhoneMissed className="size-6" aria-hidden />}
            title={tab === "call_back_needed" ? "No one to call back" : "Nothing here"}
            body="Calls appear here when the clinic number forwards an unanswered call to ClinicDesk."
          />
        ) : (
          <ul className="divide-y divide-slate-100">
            {calls.data.map((c) => <CallRow key={c.id} call={c} />)}
          </ul>
        )}
      </Card>
      {adding && <ManualDialog onClose={() => setAdding(false)} />}
    </>
  );
}

function CallRow({ call }: { call: MissedCall }) {
  const tz = useTz();
  const toast = useToast();
  const [book, setBook] = useState(false);
  const resolve = useAction(
    (outcome: "called_back" | "booked_by_phone" | "no_answer" | "not_needed") =>
      unwrap(api.POST("/api/v1/missed-calls/{call_id}/resolve", { params: { path: { call_id: call.id } }, body: { outcome } })),
    ["missed-calls", "today"],
  );
  const s = STATUS[call.status] ?? STATUS.resolved!;
  const done = (outcome: Parameters<typeof resolve.mutate>[0], msg: string) =>
    resolve.mutate(outcome, { onSuccess: () => toast("success", msg), onError: (e) => toast("error", errorMessage(e)) });
  const open = call.status === "pending" || call.status === "call_back_needed";
  return (
    <li className="flex flex-wrap items-center gap-3 px-4 py-3 sm:px-5">
      <div className="min-w-0 flex-1">
        <p className="font-medium">
          {call.patient_id ? <Link to={`/patients/${call.patient_id}`} className="hover:text-brand-700 hover:underline">{call.patient_name}</Link> : formatPhone(call.caller_phone)}
        </p>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
          <Badge tone={s.tone}>{s.label}</Badge>
          {call.patient_id && <span>{formatPhone(call.caller_phone)}</span>}
          <span>{formatDateTime(call.last_called_at, tz)}</span>
          {call.repeat_count > 0 && <Badge tone="amber">called {call.repeat_count + 1}×</Badge>}
          {call.source === "manual" && <Badge>logged by desk</Badge>}
          {call.resolution && <span>· {call.resolution.replace(/_/g, " ")}</span>}
        </div>
      </div>
      {open && (
        <div className="flex flex-wrap gap-1.5">
          <a href={`tel:${call.caller_phone}`} className="inline-flex h-9 items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 text-sm font-medium shadow-sm hover:bg-slate-50">
            <Phone className="size-4" aria-hidden /> Call
          </a>
          <Button size="sm" variant="secondary" icon={<CalendarPlus className="size-4" />} onClick={() => setBook(true)}>Book</Button>
          <Button size="sm" variant="ghost" loading={resolve.isPending} onClick={() => done("called_back", "Marked as called back")}>Called back</Button>
          <Button size="sm" variant="ghost" onClick={() => done("not_needed", "Closed")}>Not needed</Button>
        </div>
      )}
      {book && (
        <BookDialog
          open
          onOpenChange={(o) => {
            setBook(o);
            if (!o) done("booked_by_phone", "Closed as booked by phone");
          }}
          initialPatient={call.patient_id ? ({ id: call.patient_id, name: call.patient_name ?? "", phone: call.caller_phone } as Patient) : null}
        />
      )}
    </li>
  );
}

function ManualDialog({ onClose }: { onClose: () => void }) {
  const toast = useToast();
  const [phone, setPhone] = useState("");
  const add = useAction(() => unwrap(api.POST("/api/v1/missed-calls", { body: { phone } })), ["missed-calls", "today"]);
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Log a missed call"
      description="Use this if call forwarding is not set up or the telephony service is down. No message is sent automatically."
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>Cancel</Button>
          <Button loading={add.isPending} disabled={phone.replace(/\D/g, "").length < 10} onClick={() => add.mutate(undefined, { onSuccess: () => { toast("success", "Added to the call-back list"); onClose(); } })}>
            Add
          </Button>
        </>
      }
    >
      <Field label="Caller's number">{(id) => <Input id={id} type="tel" value={phone} onChange={(e) => setPhone(e.target.value)} autoFocus />}</Field>
      <div className="mt-3"><InlineError error={add.error} /></div>
    </Dialog>
  );
}
