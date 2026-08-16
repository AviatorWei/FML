import { useEffect, useState } from "react";
import { api } from "../api.js";
import { Card, EmptyState, ErrorBox, Loading, PageHeader, Tabs } from "../components/ui.jsx";

const TABS = [
  { value: "league", label: "League" },
  { value: "groups", label: "Group Stage" },
  { value: "tournament", label: "Tournament" },
];

function StandingsTable({ rows, highlightTop = 0 }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full">
        <thead>
          <tr className="border-b border-pitch-100">
            <th className="th w-10">#</th>
            <th className="th">Manager</th>
            <th className="th text-center">P</th>
            <th className="th text-center">W</th>
            <th className="th text-center">D</th>
            <th className="th text-center">L</th>
            <th className="th text-center">GF</th>
            <th className="th text-center">GA</th>
            <th className="th text-center">GD</th>
            <th className="th text-center">Pts</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.manager_id}
              className={`border-b border-pitch-50 ${
                highlightTop && r.rank <= highlightTop ? "bg-pitch-50/60" : ""
              }`}
            >
              <td className="td font-bold text-pitch-700">{r.rank}</td>
              <td className="td font-semibold">{r.name}</td>
              <td className="td text-center">{r.played}</td>
              <td className="td text-center">{r.win}</td>
              <td className="td text-center">{r.draw}</td>
              <td className="td text-center">{r.loss}</td>
              <td className="td text-center">{r.gf}</td>
              <td className="td text-center">{r.ga}</td>
              <td className="td text-center font-medium">
                {r.gd > 0 ? `+${r.gd}` : r.gd}
              </td>
              <td className="td text-center text-base font-extrabold text-pitch-700">{r.points}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BracketSlot({ team }) {
  return (
    <div className="flex items-center justify-between rounded-lg bg-white px-3 py-2 text-sm shadow-card">
      <span className="font-semibold text-ink-900">{team?.name || "TBD"}</span>
      {team?.seed && <span className="pill bg-pitch-50 text-pitch-700">{team.seed}</span>}
    </div>
  );
}

function Bracket({ data }) {
  return (
    <div className="space-y-6">
      <div>
        <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-pitch-800">
          Quarterfinals
        </h3>
        <div className="grid gap-3 sm:grid-cols-2">
          {data.quarterfinals.map((m) => (
            <Card key={m.slot} className="!p-3">
              <div className="mb-2 text-xs font-bold text-pitch-700/60">{m.slot}</div>
              <div className="space-y-1.5">
                <BracketSlot team={m.home} />
                <BracketSlot team={m.away} />
              </div>
            </Card>
          ))}
        </div>
      </div>
      <div className="grid gap-6 sm:grid-cols-2">
        <div>
          <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-pitch-800">
            Semifinals
          </h3>
          <div className="space-y-3">
            {data.semifinals.map((m) => (
              <Card key={m.slot} className="!p-3">
                <div className="mb-2 text-xs font-bold text-pitch-700/60">{m.slot}</div>
                <div className="space-y-1.5">
                  <BracketSlot team={m.home} />
                  <BracketSlot team={m.away} />
                </div>
              </Card>
            ))}
          </div>
        </div>
        <div>
          <h3 className="mb-2 text-sm font-bold uppercase tracking-wide text-pitch-800">Final</h3>
          <Card className="!p-3">
            <div className="mb-2 text-xs font-bold text-pitch-700/60">{data.final.slot}</div>
            <div className="space-y-1.5">
              <BracketSlot team={data.final.home} />
              <BracketSlot team={data.final.away} />
            </div>
          </Card>
        </div>
      </div>
      {data.note && <p className="text-xs text-pitch-800/50">{data.note}</p>}
    </div>
  );
}

export default function Standings() {
  const [tab, setTab] = useState("league");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        let res;
        if (tab === "league") res = await api.standingsLeague();
        else if (tab === "groups") res = await api.standingsGroups();
        else res = await api.standingsTournament();
        if (alive) setData(res);
      } catch (e) {
        if (alive) setError(e.message);
      } finally {
        if (alive) setLoading(false);
      }
    })();
    return () => {
      alive = false;
    };
  }, [tab]);

  return (
    <div>
      <PageHeader
        title="Standings"
        subtitle="League table, group-stage tables, and the knockout bracket."
        right={<Tabs tabs={TABS} value={tab} onChange={setTab} />}
      />

      {error && <ErrorBox message={error} />}
      {loading && <Loading label="Loading standings…" />}

      {!loading && !error && tab === "league" && (
        <Card>
          {data?.table?.length ? (
            <StandingsTable rows={data.table} />
          ) : (
            <EmptyState title="No results yet" />
          )}
        </Card>
      )}

      {!loading && !error && tab === "groups" && (
        <div className="grid gap-5 lg:grid-cols-2">
          {Object.entries(data?.groups || {}).map(([letter, rows]) => (
            <Card key={letter}>
              <h2 className="mb-3 flex items-center gap-2 text-sm font-bold uppercase tracking-wide text-pitch-800">
                <span className="grid h-6 w-6 place-items-center rounded-lg bg-pitch-600 text-xs text-white">
                  {letter}
                </span>
                Group {letter}
              </h2>
              <StandingsTable rows={rows} highlightTop={2} />
            </Card>
          ))}
        </div>
      )}

      {!loading && !error && tab === "tournament" && data && <Bracket data={data} />}
    </div>
  );
}
