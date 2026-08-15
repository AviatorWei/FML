import { useEffect, useMemo, useState } from "react";
import { api, download } from "../../api.js";
import { Card, PageHeader, Loading, EmptyState, StatusBadge, PosChip } from "../../components/ui.jsx";
import { Btn, DropZone, Field, Toast, useToast, inputCls } from "../../components/admin.jsx";

const STATUS_TONE = {
  AWARDED: "bg-pitch-100 text-pitch-700",
  LOST: "bg-slate-100 text-slate-500",
  VALID: "bg-sky-50 text-sky-700",
  SUBMITTED: "bg-slate-100 text-slate-600",
  INVALID_PER_BID: "bg-rose-50 text-rose-700",
  INVALID_POS_CAP: "bg-rose-50 text-rose-700",
  INVALID_BUDGET: "bg-rose-50 text-rose-700",
  INVALID_INELIGIBLE: "bg-rose-50 text-rose-700",
};

function BidTable({ bids }) {
  const grouped = useMemo(() => {
    const g = new Map();
    for (const b of bids) {
      if (!g.has(b.player_id)) g.set(b.player_id, []);
      g.get(b.player_id).push(b);
    }
    return [...g.entries()];
  }, [bids]);

  if (!bids.length) return <EmptyState title="No bids yet" hint="Upload sheets first." />;
  return (
    <div className="space-y-4">
      {grouped.map(([pid, rows]) => (
        <div key={pid} className="overflow-hidden rounded-xl border border-pitch-100">
          <div className="flex items-center gap-2 bg-pitch-50 px-3 py-2 text-sm font-bold">
            {rows[0].player} <PosChip pos={rows[0].position} />
            <span className="text-xs font-medium text-pitch-800/50">
              #{pid} · {rows[0].real_team}
            </span>
          </div>
          <table className="w-full text-sm">
            <tbody>
              {rows.map((b) => (
                <tr key={b.bid_id} className="border-t border-pitch-50">
                  <td className="px-3 py-1.5 font-semibold">{b.manager}</td>
                  <td className="px-3 py-1.5">{b.amount}m</td>
                  <td className="px-3 py-1.5 text-xs text-slate-500">rank {b.rank}</td>
                  <td className="px-3 py-1.5">
                    <span className={`pill ${STATUS_TONE[b.status] || "bg-slate-100"}`}>
                      {b.status}
                    </span>
                    {b.reason && (
                      <span className="ml-2 text-xs text-rose-600">{b.reason}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
    </div>
  );
}

export default function AuctionDesk() {
  const [rounds, setRounds] = useState(null);
  const [sel, setSel] = useState(null);
  const [bids, setBids] = useState([]);
  const [report, setReport] = useState(null);
  const [uploadReport, setUploadReport] = useState(null);
  const [creating, setCreating] = useState({ index: "", opens_at: "", closes_at: "" });
  const [busy, setBusy] = useState(false);
  const [toast, show] = useToast();

  const refresh = () =>
    api
      .adminRounds()
      .then((r) => {
        setRounds(r.rounds);
        if (r.rounds.length && sel == null) setSel(r.rounds[r.rounds.length - 1].id);
      })
      .catch((e) => show(e.message, "error"));

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (sel == null) return;
    api.adminRoundBids(sel).then((r) => setBids(r.bids)).catch(() => setBids([]));
    setReport(null);
    setUploadReport(null);
  }, [sel]);

  if (!rounds) return <Loading label="Loading auction rounds…" />;
  const round = rounds.find((r) => r.id === sel);

  const createRound = async () => {
    try {
      await api.adminRoundCreate({
        index: Number(creating.index),
        opens_at: creating.opens_at,
        closes_at: creating.closes_at,
      });
      show(`Round ${creating.index} opened`);
      setCreating({ index: "", opens_at: "", closes_at: "" });
      refresh();
    } catch (e) {
      show(e.message, "error");
    }
  };

  const upload = async (files) => {
    setBusy(true);
    try {
      const r = await api.adminRoundUpload(sel, files);
      setUploadReport(r.files);
      const ok = r.files.filter((f) => f.ok).length;
      show(`${ok}/${r.files.length} sheet(s) ingested`);
      api.adminRoundBids(sel).then((x) => setBids(x.bids));
      refresh();
    } catch (e) {
      show(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const resolve = async (dryRun) => {
    setBusy(true);
    try {
      const r = await api.adminRoundResolve(sel, dryRun);
      setReport(r);
      setBids(r.bids);
      show(dryRun ? "Dry run complete — nothing written" : "Round committed");
      if (!dryRun) refresh();
    } catch (e) {
      show(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div>
      <PageHeader
        title="Auction Desk"
        subtitle="Round → sheets → dry-run resolve → commit → publish. Nothing is written until commit."
      />

      <div className="mb-5 flex flex-wrap items-end gap-3">
        <Field label="Round">
          <select
            className={inputCls + " w-44"}
            value={sel ?? ""}
            onChange={(e) => setSel(Number(e.target.value))}
          >
            {rounds.map((r) => (
              <option key={r.id} value={r.id}>
                Round {r.index} — {r.status}
              </option>
            ))}
          </select>
        </Field>
        <div className="ml-auto flex items-end gap-2">
          <Field label="New round #">
            <input
              className={inputCls + " w-20"}
              value={creating.index}
              onChange={(e) => setCreating({ ...creating, index: e.target.value })}
            />
          </Field>
          <Field label="Opens (ISO)">
            <input
              className={inputCls + " w-44"}
              placeholder="2026-07-04T12:00"
              value={creating.opens_at}
              onChange={(e) => setCreating({ ...creating, opens_at: e.target.value })}
            />
          </Field>
          <Field label="Closes (ISO)">
            <input
              className={inputCls + " w-44"}
              placeholder="2026-07-06T20:00"
              value={creating.closes_at}
              onChange={(e) => setCreating({ ...creating, closes_at: e.target.value })}
            />
          </Field>
          <Btn onClick={createRound} disabled={!creating.index}>
            + Open round
          </Btn>
        </div>
      </div>

      {!round ? (
        <EmptyState title="No auction rounds" hint="Open a round to begin." />
      ) : (
        <div className="space-y-5">
          <Card>
            <div className="mb-3 flex items-center justify-between">
              <div className="text-sm font-bold">
                Round {round.index} <StatusBadge status={round.status} />
              </div>
              <div className="text-xs text-slate-500">
                {round.submissions.length} submission(s)
              </div>
            </div>
            {round.status !== "CLOSED" && (
              <DropZone
                hint="Drop FME_<year>_Bid<N>_<CODE>.xlsx sheets here (multi-file)"
                accept=".xlsx"
                onFiles={upload}
              />
            )}
            {round.submissions.length > 0 && (
              <div className="mt-3 flex flex-wrap gap-2">
                {round.submissions.map((s) => (
                  <span key={s.manager_id} className="pill bg-pitch-50 text-pitch-800">
                    {s.manager} · {s.source_file || "sheet"} ·{" "}
                    {new Date(s.received_at).toLocaleTimeString()}
                  </span>
                ))}
              </div>
            )}
            {uploadReport && (
              <div className="mt-3 space-y-1 text-sm">
                {uploadReport.map((f, i) => (
                  <div key={i} className={f.ok ? "text-pitch-700" : "text-rose-600"}>
                    {f.ok ? "✓" : "✕"} {f.file}
                    {f.ok && ` — ${f.manager}, ${f.bids} bids, ${f.total}m total`}
                    {f.error && ` — ${f.error}`}
                    {f.warnings?.map((w, j) => (
                      <span key={j} className="ml-2 text-amber-600">
                        ⚠ {w}
                      </span>
                    ))}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card>
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <div className="text-sm font-bold">Resolution</div>
              <div className="flex gap-2">
                <Btn tone="ghost" disabled={busy || round.status === "CLOSED"} onClick={() => resolve(true)}>
                  Dry-run resolve
                </Btn>
                <Btn
                  disabled={busy || round.status === "CLOSED" || !report?.dry_run}
                  onClick={() => resolve(false)}
                  title={!report?.dry_run ? "Run a dry run first" : ""}
                >
                  Commit for real
                </Btn>
                {round.status === "CLOSED" && (
                  <>
                    <Btn
                      tone="ghost"
                      onClick={() =>
                        download(`/api/export/auction/${round.index}/announcement.txt`).catch(
                          (e) => show(e.message, "error")
                        )
                      }
                    >
                      ⬇ 暗标公示
                    </Btn>
                    <Btn
                      tone="gray"
                      onClick={() =>
                        download(`/api/export/auction/${round.index}/results.csv`).catch((e) =>
                          show(e.message, "error")
                        )
                      }
                    >
                      ⬇ results.csv
                    </Btn>
                  </>
                )}
              </div>
            </div>

            {report && (
              <div className="mb-4 rounded-xl bg-pitch-50 p-4 text-sm">
                <div className="mb-2 font-bold">
                  {report.dry_run ? "DRY RUN — nothing was written" : "COMMITTED"} ·{" "}
                  {report.awards.length} award(s) · {report.invalidated} bid(s) invalidated ·{" "}
                  {report.total_spend}m total spend
                </div>
                <div className="flex flex-wrap gap-2">
                  {report.awards.map((a) => (
                    <span key={a.player_id} className="pill bg-white text-pitch-800">
                      {a.player} → {a.winner} ({a.price}m)
                    </span>
                  ))}
                </div>
                {report.balance_deltas.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-2">
                    {report.balance_deltas.map((d) => (
                      <span key={d.manager} className="pill bg-sky-50 text-sky-700">
                        {d.manager}: {d.before}m → {d.after}m
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}

            <BidTable bids={bids} />
          </Card>
        </div>
      )}
      <Toast toast={toast} />
    </div>
  );
}
