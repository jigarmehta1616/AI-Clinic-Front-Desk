import { Megaphone, Ticket } from "lucide-react";
import { useState } from "react";

import { api, errorMessage, unwrap } from "@/api/client";
import { groups, useAction, useQueue, type QueueEntry, type QueueSession } from "@/api/queries";
import { can, useAuth } from "@/auth/AuthProvider";
import { useTz } from "@/components/layout/AppShell";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, SkeletonRows, StatusBadge, useToast } from "@/components/ui";
import { IssueTokenDialog } from "@/features/shared/IssueTokenDialog";
import { DayNav, DoctorSelect } from "@/features/shared/pickers";
import { cn, dayIn, formatPhone, formatTime, minutesUntil } from "@/lib/format";

/** FR-4.4 / FR-4.6: merged queue per doctor session — call next, skip, recall. Live via WebSocket (NFR-2). */
export default function QueuePage() {
  const tz = useTz();
  const { session } = useAuth();
  const [doctorId, setDoctorId] = useState(session?.doctorId ?? "");
  const [day, setDay] = useState(dayIn(tz));
  const [issue, setIssue] = useState(false);
  const queue = useQueue(doctorId || undefined, day);
  const isToday = day === dayIn(tz);

  return (
    <>
      <PageHeader
        title="Queue"
        actions={
          can(session, "desk") && isToday && (
            <Button icon={<Ticket className="size-4" />} onClick={() => setIssue(true)} disabled={!doctorId}>
              Issue token
            </Button>
          )
        }
      />
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <DoctorSelect value={doctorId} onChange={setDoctorId} />
        <DayNav day={day} onChange={setDay} />
      </div>
      {!doctorId || queue.isPending ? (
        <Card><SkeletonRows /></Card>
      ) : queue.isError ? (
        <Card><ErrorState error={queue.error} onRetry={() => void queue.refetch()} /></Card>
      ) : queue.data.length === 0 ? (
        <Card>
          <EmptyState title="No queue yet" body="The queue starts when the first token is issued or a booked patient is marked arrived." />
        </Card>
      ) : (
        <div className="space-y-6">
          {queue.data.map((s) => (
            <SessionCard key={s.id} session={s} tz={tz} live={isToday} />
          ))}
        </div>
      )}
      {issue && <IssueTokenDialog open onOpenChange={setIssue} initialDoctorId={doctorId} />}
    </>
  );
}

function SessionCard({ session, tz, live }: { session: QueueSession; tz: string; live: boolean }) {
  const toast = useToast();
  const next = useAction(
    () => unwrap(api.POST("/api/v1/queue/sessions/{queue_session_id}/next", { params: { path: { queue_session_id: session.id } } })),
    groups.queue,
  );
  const complete = useAction(
    () => unwrap(api.POST("/api/v1/queue/sessions/{queue_session_id}/complete-current", { params: { path: { queue_session_id: session.id } } })),
    groups.queue,
  );
  const waiting = session.entries.filter((e) => e.status === "waiting").sort((a, b) => (a.ahead ?? 999) - (b.ahead ?? 999));
  const current = session.entries.find((e) => e.status === "called");
  const others = session.entries.filter((e) => e.status !== "waiting" && e.status !== "called");
  const walkIns = session.entries.filter((e) => e.kind === "walk_in" && e.status !== "cancelled").length;

  return (
    <Card>
      <CardHeader
        title={`${formatTime(session.starts_at, tz)} – ${formatTime(session.ends_at, tz)}`}
        subtitle={`${walkIns}/${session.max_tokens} walk-in tokens · avg ${session.avg_consult_minutes} min per patient`}
      />
      <div className="grid gap-4 p-4 sm:p-5 md:grid-cols-[minmax(0,240px)_1fr]">
        <div className="rounded-xl bg-brand-50 p-5 text-center">
          <p className="text-xs font-medium uppercase tracking-wide text-brand-800">Now serving</p>
          <p className="tabular text-6xl font-bold text-brand-700" aria-live="polite">{current?.token_no ?? "–"}</p>
          <p className="mt-1 truncate text-sm text-brand-900">{current ? (current.patient_name ?? (current.kind === "booked" ? "Booked patient" : "Walk-in")) : "No one with the doctor"}</p>
          {live && (
            <div className="mt-4 flex flex-col gap-2">
              <Button
                size="lg"
                icon={<Megaphone className="size-5" />}
                loading={next.isPending}
                onClick={() =>
                  next.mutate(undefined, {
                    onSuccess: (e) => toast(e ? "success" : "info", e ? `Calling token ${e.token_no}` : "No one is waiting"),
                    onError: (e) => toast("error", errorMessage(e)),
                  })
                }
              >
                Call next
              </Button>
              {current && (
                <Button variant="secondary" size="sm" loading={complete.isPending} onClick={() => complete.mutate(undefined, { onError: (e) => toast("error", errorMessage(e)) })}>
                  Visit done
                </Button>
              )}
            </div>
          )}
        </div>
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-700">Waiting ({waiting.length})</h3>
          {waiting.length === 0 ? (
            <p className="rounded-lg bg-slate-50 px-3 py-4 text-sm text-slate-500">No one waiting.</p>
          ) : (
            <ol className="divide-y divide-slate-100 rounded-lg border border-slate-200">
              {waiting.map((e) => (
                <EntryRow key={e.id} entry={e} tz={tz} live={live} />
              ))}
            </ol>
          )}
          {others.length > 0 && (
            <details className="mt-4">
              <summary className="cursor-pointer text-sm font-medium text-slate-600">Skipped, done and cancelled ({others.length})</summary>
              <ol className="mt-2 divide-y divide-slate-100 rounded-lg border border-slate-200">
                {others.map((e) => (
                  <EntryRow key={e.id} entry={e} tz={tz} live={live} />
                ))}
              </ol>
            </details>
          )}
        </div>
      </div>
    </Card>
  );
}

function EntryRow({ entry, tz, live }: { entry: QueueEntry; tz: string; live: boolean }) {
  const toast = useToast();
  const act = useAction(
    (action: "skip" | "recall" | "cancel") =>
      unwrap(api.POST("/api/v1/queue/entries/{entry_id}/{action}", { params: { path: { entry_id: entry.id, action } } })),
    groups.queue,
  );
  const run = (a: "skip" | "recall" | "cancel") => act.mutate(a, { onError: (e) => toast("error", errorMessage(e)) });
  return (
    <li className={cn("flex flex-wrap items-center gap-3 px-3 py-2.5", entry.status === "skipped" && "bg-amber-50/50")}>
      <span className="tabular w-10 text-center text-xl font-semibold">{entry.token_no}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">
          {entry.patient_name ?? (entry.phone ? formatPhone(entry.phone) : "Walk-in")}
        </p>
        <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-slate-500">
          <Badge tone={entry.kind === "booked" ? "brand" : "slate"}>{entry.kind === "booked" ? `Booked ${entry.slot_start ? formatTime(entry.slot_start, tz) : ""}` : "Walk-in"}</Badge>
          {entry.status !== "waiting" && <StatusBadge status={entry.status} />}
          {entry.status === "waiting" && entry.ahead != null && <span>{entry.ahead === 0 ? "Next" : `${entry.ahead} ahead`}</span>}
          {entry.status === "waiting" && entry.eta && <span>· ~{minutesUntil(entry.eta)} min</span>}
        </div>
      </div>
      {live && (
        <div className="flex gap-1">
          {entry.status === "waiting" && <Button size="sm" variant="ghost" onClick={() => run("skip")} loading={act.isPending}>Skip</Button>}
          {entry.status === "skipped" && <Button size="sm" variant="secondary" onClick={() => run("recall")} loading={act.isPending}>Recall</Button>}
          {entry.kind === "walk_in" && (entry.status === "waiting" || entry.status === "skipped") && (
            <Button size="sm" variant="ghost" onClick={() => run("cancel")}>Remove</Button>
          )}
        </div>
      )}
    </li>
  );
}
