import { AlertTriangle, ArrowLeft, Bot, Send } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api, errorMessage, unwrap } from "@/api/client";
import { groups, useAction, useInbox, useMessages, type InboxItem } from "@/api/queries";
import { useTz } from "@/components/layout/AppShell";
import { Badge, Button, Card, EmptyState, ErrorState, PageHeader, Segmented, SkeletonRows, Textarea, useToast } from "@/components/ui";
import { cn, formatPhone, formatTime } from "@/lib/format";

const REASON: Record<string, { label: string; tone: "red" | "amber" | "slate" | "brand" }> = {
  emergency: { label: "Emergency", tone: "red" },
  medical: { label: "Medical question", tone: "amber" },
  unclear: { label: "Unclear", tone: "slate" },
  requested: { label: "Asked for staff", tone: "brand" },
  no_slots: { label: "No free slots", tone: "amber" },
  complaint: { label: "Complaint", tone: "amber" },
  other: { label: "Other", tone: "slate" },
};

/** FR-8.1/8.2/8.4 shared inbox: chats the assistant handed over, emergencies first. */
export default function InboxPage() {
  const { conversationId } = useParams();
  const [status, setStatus] = useState<"open" | "closed">("open");
  const inbox = useInbox(status);
  const selected = inbox.data?.find((i) => i.conversation_id === conversationId);

  return (
    <>
      <PageHeader title="Inbox" subtitle="Chats the WhatsApp assistant handed to staff." />
      <div className="grid gap-4 lg:grid-cols-[360px_1fr]">
        <Card className={cn(conversationId && "hidden lg:block")}>
          <div className="border-b border-slate-100 p-3">
            <Segmented label="Status" value={status} onChange={setStatus} options={[{ value: "open", label: "Open" }, { value: "closed", label: "Closed" }]} />
          </div>
          {inbox.isPending ? (
            <SkeletonRows />
          ) : inbox.isError ? (
            <ErrorState error={inbox.error} onRetry={() => void inbox.refetch()} />
          ) : inbox.data.length === 0 ? (
            <EmptyState title={status === "open" ? "All caught up" : "No closed chats"} body="Medical questions, emergencies and unclear chats appear here." />
          ) : (
            <ul className="divide-y divide-slate-100">
              {inbox.data.map((i) => (
                <ChatListItem key={i.ticket_id} item={i} active={i.conversation_id === conversationId} />
              ))}
            </ul>
          )}
        </Card>
        <div className={cn(!conversationId && "hidden lg:block")}>
          {conversationId ? (
            <Thread conversationId={conversationId} item={selected} />
          ) : (
            <Card><EmptyState title="Select a chat" body="Pick a conversation to read the full thread and reply." /></Card>
          )}
        </div>
      </div>
    </>
  );
}

function ChatListItem({ item, active }: { item: InboxItem; active: boolean }) {
  const tz = useTz();
  const r = REASON[item.reason] ?? REASON.other!;
  return (
    <li>
      <Link
        to={`/inbox/${item.conversation_id}`}
        className={cn("block px-4 py-3 hover:bg-slate-50", active && "bg-brand-50", item.reason === "emergency" && "border-l-4 border-red-500")}
      >
        <div className="flex items-center justify-between gap-2">
          <p className="truncate font-medium">{item.patient_names[0] ?? formatPhone(item.phone)}</p>
          <span className="shrink-0 text-xs text-slate-500">{item.last_at ? formatTime(item.last_at, tz) : ""}</span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <Badge tone={r.tone}>{item.reason === "emergency" && <AlertTriangle className="size-3" aria-hidden />}{r.label}</Badge>
          <p className="truncate text-sm text-slate-500">{item.last_message}</p>
        </div>
      </Link>
    </li>
  );
}

function Thread({ conversationId, item }: { conversationId: string; item?: InboxItem }) {
  const tz = useTz();
  const toast = useToast();
  const navigate = useNavigate();
  const messages = useMessages(conversationId);
  const [text, setText] = useState("");
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    end.current?.scrollIntoView({ block: "end" });
  }, [messages.data?.length]);

  const reply = useAction(
    () => unwrap(api.POST("/api/v1/inbox/conversations/{conversation_id}/reply", { params: { path: { conversation_id: conversationId } }, body: { text } })),
    groups.inbox,
  );
  const handBack = useAction(
    () => unwrap(api.POST("/api/v1/inbox/conversations/{conversation_id}/hand-back", { params: { path: { conversation_id: conversationId } } })),
    groups.inbox,
  );
  const canReply = item?.can_reply ?? true;

  return (
    <Card className="flex h-[calc(100dvh-12rem)] min-h-[28rem] flex-col">
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-100 px-4 py-3">
        <Link to="/inbox" className="rounded-lg p-1.5 hover:bg-slate-100 lg:hidden" aria-label="Back to chats">
          <ArrowLeft className="size-5" />
        </Link>
        <div className="min-w-0 flex-1">
          <p className="truncate font-semibold">{item?.patient_names[0] ?? (item ? formatPhone(item.phone) : "Conversation")}</p>
          {item && <p className="text-xs text-slate-500">{formatPhone(item.phone)}</p>}
        </div>
        {item?.status === "open" && (
          <Button
            variant="secondary"
            size="sm"
            icon={<Bot className="size-4" />}
            loading={handBack.isPending}
            onClick={() => handBack.mutate(undefined, { onSuccess: () => { toast("success", "Handed back to the assistant"); navigate("/inbox"); } })}
          >
            Hand back to assistant
          </Button>
        )}
      </div>
      {item?.reason === "emergency" && (
        <div role="alert" className="flex items-center gap-2 bg-red-50 px-4 py-2 text-sm text-red-800">
          <AlertTriangle className="size-4 shrink-0" aria-hidden />
          The patient was told to call 108/112 and the clinic. Call them now if you can.
        </div>
      )}
      <div className="flex-1 space-y-2 overflow-y-auto bg-slate-50 px-4 py-4" aria-live="polite">
        {messages.isPending ? (
          <SkeletonRows rows={4} />
        ) : messages.isError ? (
          <ErrorState error={messages.error} onRetry={() => void messages.refetch()} />
        ) : (
          messages.data.map((m) => {
            const body = (m.body as { text?: string | null; payload?: unknown }).text;
            const mine = m.direction === "out";
            return (
              <div key={m.id} className={cn("flex", mine ? "justify-end" : "justify-start")}>
                <div className={cn("max-w-[85%] rounded-2xl px-3 py-2 text-sm shadow-sm", mine ? "bg-brand-700 text-white" : "bg-white text-slate-900")}>
                  <p className="whitespace-pre-wrap break-words">{body || <em className="opacity-70">[{m.kind}]</em>}</p>
                  <p className={cn("mt-1 text-[11px]", mine ? "text-brand-100" : "text-slate-400")}>
                    {formatTime(m.at, tz)}
                    {mine && (m.sent_by_user_id ? " · staff" : " · assistant")}
                  </p>
                </div>
              </div>
            );
          })
        )}
        <div ref={end} />
      </div>
      <form
        className="border-t border-slate-100 p-3"
        onSubmit={(e) => {
          e.preventDefault();
          reply.mutate(undefined, { onSuccess: () => setText(""), onError: (err) => toast("error", errorMessage(err)) });
        }}
      >
        {!canReply ? (
          <p className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-800">
            The patient hasn&apos;t messaged in 24 hours, so WhatsApp only allows approved templates. Please call them instead.
          </p>
        ) : (
          <div className="flex items-end gap-2">
            <Textarea aria-label="Reply" value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a reply — it goes to the patient's WhatsApp" className="min-h-11 flex-1 resize-none" rows={2} maxLength={4000} />
            <Button type="submit" icon={<Send className="size-4" />} loading={reply.isPending} disabled={!text.trim()}>
              Send
            </Button>
          </div>
        )}
      </form>
    </Card>
  );
}
