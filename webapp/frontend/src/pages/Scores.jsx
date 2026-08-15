import { useEffect, useState } from "react";
import { api } from "../api.js";
import {
  Card,
  EmptyState,
  ErrorBox,
  Loading,
  PageHeader,
  StatusBadge,
  Tabs,
} from "../components/ui.jsx";

const TABS = [
  { value: "live", label: "Live" },
  { value: "finalized", label: "History" },
  { value: "all", label: "All" },
];

function Score({ value }) {
  return (
    <span className="grid h-9 w-9 place-items-center rounded-lg bg-ink-900 text-base font-extrabold text-white">
      {value ?? "–"}
    </span>
  );
}

function FixtureRow({ fx }) {
  const homeWin = fx.outcome === "HOME_WIN";
  const awayWin = fx.outcome === "AWAY_WIN";
  return (
    <div className="flex items-center gap-3 rounded-xl px-3 py-2.5 hover:bg-pitch-50">
      <div className={`flex-1 text-right text-sm font-semibold ${homeWin ? "text-pitch-700" : "text-ink-900"}`}>
        {fx.home.name}
      </div>
      <div className="flex items-center gap-1.5">
        <Score value={fx.home_goals} />
        <span className="text-xs font-bold text-pitch-700/50">:</span>
        <Score value={fx.away_goals} />
      </div>
      <div className={`flex-1 text-sm font-semibold ${awayWin ? "text-pitch-700" : "text-ink-900"}`}>
        {fx.away.name}
      </div>
      {fx.group && (
        <span className="pill bg-pitch-50 text-pitch-700">Grp {fx.group}</span>
      )}
      {!fx.played && <span className="pill bg-slate-100 text-slate-500">Scheduled</span>}
    </div>
  );
}

export default function Scores() {
  const [tab, setTab] = useState("live");
  const [data, setData] = useState(null);
  const [time, setTime] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  async function load(status) {
    setLoading(true);
    setError(null);
    try {
      const [res, t] = await Promise.all([api.scores(status), api.time()]);
      setData(res);
      setTime(t);
    } catch (e) {
      setError(e.message);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    load(tab);
  }, [tab]);

  // light auto-refresh on the Live tab
  useEffect(() => {
    if (tab !== "live") return;
    const id = setInterval(() => load("live"), 20000);
    return () => clearInterval(id);
  }, [tab]);

  const gws = data?.gameweeks || [];

  return (
    <div>
      <PageHeader
        title="Live Scores"
        subtitle="Real-time gameweek scores and the result history of previous rounds."
        right={
          <div className="flex items-center gap-3">
            {time && (
              <span className="hidden text-xs font-medium text-pitch-800/60 sm:block">
                Server · {new Date(time.utc).toLocaleString()}
              </span>
            )}
            <Tabs tabs={TABS} value={tab} onChange={setTab} />
          </div>
        }
      />

      {error && <ErrorBox message={error} />}
      {loading && <Loading label="Fetching scores…" />}

      {!loading && !error && gws.length === 0 && (
        <EmptyState
          title={tab === "live" ? "No live matches right now" : "No matches to show"}
          hint="Run the engine through a gameweek to populate scores."
        />
      )}

      <div className="space-y-5">
        {gws.map((gw) => (
          <Card key={gw.id}>
            <div className="mb-3 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-bold uppercase tracking-wide text-pitch-800">
                  {gw.phase === "GROUP" ? "Group Stage" : gw.phase} · Gameweek {gw.index}
                </h2>
              </div>
              <StatusBadge status={gw.status} />
            </div>
            <div className="divide-y divide-pitch-50">
              {gw.fixtures.length === 0 ? (
                <div className="py-6 text-center text-sm text-pitch-800/50">No fixtures.</div>
              ) : (
                gw.fixtures.map((fx) => <FixtureRow key={fx.fixture_id} fx={fx} />)
              )}
            </div>
          </Card>
        ))}
      </div>
    </div>
  );
}
