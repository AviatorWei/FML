import { useRef, useState } from "react";
import { api } from "../api.js";
import { Card, ErrorBox, PageHeader, PosChip, StatPill } from "../components/ui.jsx";

export default function Bids() {
  const [drag, setDrag] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);
  const inputRef = useRef(null);

  async function handleFile(file) {
    if (!file) return;
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.uploadBids(file);
      setResult(res);
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  const bids = result?.bids || [];

  return (
    <div>
      <PageHeader
        title="Upload Bids"
        subtitle="Drop a sealed-bid xlsx. It is parsed into individual bids — no submission until you confirm."
      />

      <div className="grid gap-5 lg:grid-cols-[360px_1fr]">
        <Card>
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDrag(true);
            }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDrag(false);
              handleFile(e.dataTransfer.files?.[0]);
            }}
            onClick={() => inputRef.current?.click()}
            className={`cursor-pointer rounded-2xl border-2 border-dashed p-8 text-center transition ${
              drag ? "border-pitch-500 bg-pitch-50" : "border-pitch-200 hover:bg-pitch-50/50"
            }`}
          >
            <div className="mx-auto mb-3 grid h-14 w-14 place-items-center rounded-2xl bg-gradient-to-br from-pitch-400 to-pitch-600 text-2xl text-white shadow-card">
              ⬆
            </div>
            <div className="text-sm font-semibold text-ink-900">
              {busy ? "Parsing…" : "Drop bid .xlsx here"}
            </div>
            <div className="mt-1 text-xs text-pitch-800/60">or click to browse</div>
            <input
              ref={inputRef}
              type="file"
              accept=".xlsx"
              className="hidden"
              onChange={(e) => handleFile(e.target.files?.[0])}
            />
          </div>

          <div className="mt-4 rounded-xl bg-pitch-50/60 p-3 text-xs text-pitch-800/70">
            <div className="font-semibold text-pitch-800">Expected file name</div>
            <code className="mt-1 block rounded bg-white px-2 py-1 text-[11px]">
              FME_&lt;year&gt;_Bid&lt;N&gt;_&lt;CODE&gt;.xlsx
            </code>
            <div className="mt-2">
              Columns: <b>Order · Price · ID · Name · Team · Pos</b>
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          {error && <ErrorBox message={error} />}

          {!result && !error && (
            <Card className="text-sm text-pitch-800/60">
              Parsed bids will appear here, listed by rank and checked against the
              auction's minimum-bid rule.
            </Card>
          )}

          {result && (
            <>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                <StatPill label="Manager" value={result.manager_code} />
                <StatPill label="Round" value={result.round_index} tone="sky" />
                <StatPill label="Bids" value={result.bid_count} tone="amber" />
                <StatPill label="Total" value={`${result.total_amount}m`} tone="slate" />
              </div>

              <Card className="!p-0 overflow-hidden">
                <div className="flex items-center justify-between px-5 py-3">
                  <h2 className="text-sm font-bold text-ink-900">
                    {result.source_file}
                  </h2>
                  <span className="text-xs text-pitch-800/60">
                    min bid {result.min_bid_rule}m
                    {result.manager_id ? ` · manager #${result.manager_id}` : ""}
                  </span>
                </div>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-y border-pitch-100 bg-pitch-50/40">
                        <th className="th text-center">Rank</th>
                        <th className="th">Player</th>
                        <th className="th">Pos</th>
                        <th className="th">Team</th>
                        <th className="th text-center">ID</th>
                        <th className="th text-center">Amount</th>
                        <th className="th text-center">Valid</th>
                      </tr>
                    </thead>
                    <tbody>
                      {bids.map((b, i) => {
                        const ok = b.amount >= result.min_bid_rule;
                        return (
                          <tr key={i} className="border-b border-pitch-50">
                            <td className="td text-center font-bold text-pitch-700/70">
                              {b.rank_in_position}
                            </td>
                            <td className="td font-semibold">{b.player_name || `#${b.player_id}`}</td>
                            <td className="td">{b.position ? <PosChip pos={b.position} /> : "—"}</td>
                            <td className="td text-pitch-800/70">{b.real_team || "—"}</td>
                            <td className="td text-center text-pitch-800/60">{b.player_id}</td>
                            <td className="td text-center font-extrabold text-pitch-700">
                              {b.amount}m
                            </td>
                            <td className="td text-center">
                              <span
                                className={`pill ${
                                  ok ? "bg-pitch-100 text-pitch-700" : "bg-rose-100 text-rose-600"
                                }`}
                              >
                                {ok ? "OK" : "low"}
                              </span>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </Card>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
