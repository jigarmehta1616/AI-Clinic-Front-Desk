import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { ApiError, api, unwrap } from "@/api/client";
import { Spinner } from "@/components/ui";
import { minutesUntil } from "@/lib/format";

/** FR-4.2: patient's live token status from the WhatsApp link. No login, no personal data. */
export function TokenStatusPage() {
  const { code = "" } = useParams();
  const q = useQuery({
    queryKey: ["public-token", code],
    queryFn: () => unwrap(api.GET("/api/v1/public/queue/{code}", { params: { path: { code } } })),
    refetchInterval: 15_000,
    retry: (n, e) => !(e instanceof ApiError && e.status === 404) && n < 3,
  });
  const d = q.data;
  const done = d && (d.status === "completed" || d.status === "cancelled");
  const yourTurn = d?.status === "called";

  return (
    <div className="flex min-h-dvh flex-col items-center bg-gradient-to-b from-brand-700 to-brand-900 px-4 py-10 text-white">
      <p className="text-sm font-medium text-brand-100">ClinicDesk · Live queue</p>
      <div className="mt-6 w-full max-w-sm rounded-3xl bg-white p-6 text-center text-slate-900 shadow-2xl">
        {q.isPending ? (
          <div className="flex justify-center py-10">
            <Spinner />
          </div>
        ) : q.isError || !d ? (
          <p className="py-10 text-slate-600">This token link is not valid. Please check the WhatsApp message from your clinic.</p>
        ) : (
          <>
            <p className="text-sm text-slate-500">{d.doctor_name}</p>
            <p className="mt-2 text-sm font-medium uppercase tracking-wide text-slate-500">Your token</p>
            <p className="tabular text-7xl font-bold text-brand-700">{d.token_no}</p>
            {yourTurn ? (
              <p className="mt-4 rounded-xl bg-emerald-50 py-3 text-lg font-semibold text-emerald-700" role="status">
                It&apos;s your turn — please go in.
              </p>
            ) : done ? (
              <p className="mt-4 text-slate-600">This token is {d.status}. Thank you!</p>
            ) : (
              <dl className="mt-5 grid grid-cols-3 gap-2 text-center">
                <div className="rounded-xl bg-slate-50 p-3">
                  <dt className="text-xs text-slate-500">Now serving</dt>
                  <dd className="tabular text-2xl font-semibold">{d.current_token_no ?? "–"}</dd>
                </div>
                <div className="rounded-xl bg-slate-50 p-3">
                  <dt className="text-xs text-slate-500">Ahead of you</dt>
                  <dd className="tabular text-2xl font-semibold">{d.ahead ?? "–"}</dd>
                </div>
                <div className="rounded-xl bg-slate-50 p-3">
                  <dt className="text-xs text-slate-500">About</dt>
                  <dd className="tabular text-2xl font-semibold">{d.eta ? `${minutesUntil(d.eta)}m` : "–"}</dd>
                </div>
              </dl>
            )}
            <p className="mt-5 text-xs text-slate-400">Updates automatically · estimate only</p>
          </>
        )}
      </div>
    </div>
  );
}
