import { ChevronLeft, ChevronRight, Info } from "lucide-react";
import { useState } from "react";

import { useRevenue } from "@/api/queries";
import { useTz } from "@/components/layout/AppShell";
import { Badge, Button, Card, CardHeader, EmptyState, ErrorState, PageHeader, SkeletonRows, StatTile } from "@/components/ui";
import { addMonths, dayIn, formatDateTime, formatMoney, formatMonth, monthOf } from "@/lib/format";

const SOURCES = [
  { key: "missed_call", label: "Missed calls", help: "Unanswered calls that turned into a visit" },
  { key: "recall", label: "Recalls", help: "Patients who came back after a recall message" },
  { key: "noshow_rebook", label: "No-show rebooks", help: "No-shows who rebooked and came" },
] as const;

/** FR-7.3 / AC-11: recovered visits by source × consultation fee — always an estimate (BR-12). */
export default function RevenuePage() {
  const tz = useTz();
  const current = monthOf(dayIn(tz));
  const [month, setMonth] = useState(current);
  const report = useRevenue(month);

  return (
    <>
      <PageHeader
        title="Revenue recovered"
        subtitle="Visits that would likely have been lost, counted only when the patient actually arrived."
        actions={
          <div className="flex items-center gap-1">
            <Button variant="secondary" size="sm" aria-label="Previous month" onClick={() => setMonth(addMonths(month, -1))}><ChevronLeft className="size-4" /></Button>
            <span className="min-w-36 text-center text-sm font-medium">{formatMonth(month)}</span>
            <Button variant="secondary" size="sm" aria-label="Next month" disabled={month >= current} onClick={() => setMonth(addMonths(month, 1))}><ChevronRight className="size-4" /></Button>
          </div>
        }
      />
      {report.isPending ? (
        <Card><SkeletonRows rows={5} /></Card>
      ) : report.isError ? (
        <Card><ErrorState error={report.error} onRetry={() => void report.refetch()} /></Card>
      ) : (
        <>
          <div className="mb-4 flex items-start gap-2 rounded-xl border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-900">
            <Info className="mt-0.5 size-4 shrink-0" aria-hidden />
            <p><strong>These figures are estimates.</strong> Recovered visits × each doctor&apos;s consultation fee at the time of the visit (BR-12) — not actual payments collected.</p>
          </div>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <StatTile label="Estimated revenue" value={formatMoney(report.data.total_estimated_revenue_paise)} tone="brand" hint={`${report.data.total_visits} recovered visit(s)`} />
            {SOURCES.map((s) => {
              const v = report.data.by_source[s.key];
              return <StatTile key={s.key} label={s.label} value={formatMoney(v?.estimated_revenue_paise ?? 0)} hint={`${v?.visits ?? 0} visit(s) · ${s.help}`} />;
            })}
          </div>
          <Card className="mt-6">
            <CardHeader title="Recovered visits" />
            {report.data.items.length === 0 ? (
              <EmptyState title="No recovered visits this month yet" body="They appear here when a recalled, rebooked or missed-call patient arrives." />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
                    <tr>
                      <th className="px-4 py-2.5 font-medium sm:px-5">Arrived</th>
                      <th className="px-4 py-2.5 font-medium">Source</th>
                      <th className="px-4 py-2.5 font-medium">Doctor</th>
                      <th className="px-4 py-2.5 text-right font-medium">Est. fee</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {report.data.items.map((i) => (
                      <tr key={i.appointment_id}>
                        <td className="px-4 py-3 whitespace-nowrap sm:px-5">{formatDateTime(i.recovered_at, tz)}</td>
                        <td className="px-4 py-3"><Badge tone="violet">{SOURCES.find((s) => s.key === i.source)?.label ?? i.source}</Badge></td>
                        <td className="px-4 py-3">{i.doctor}</td>
                        <td className="tabular px-4 py-3 text-right">{formatMoney(i.fee_paise)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </>
      )}
    </>
  );
}
