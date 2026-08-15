import { useEffect, useState } from "react";
import { api } from "../api.js";
import {
  Card,
  EmptyState,
  ErrorBox,
  Loading,
  PageHeader,
  PosChip,
} from "../components/ui.jsx";

const POSITIONS = ["", "G", "D", "M", "F"];
const SORTS = [
  { value: "goals", label: "Goals" },
  { value: "assists", label: "Assists" },
  { value: "points", label: "Fantasy Pts" },
  { value: "value", label: "Value" },
  { value: "name", label: "Name" },
];

export default function Players() {
  const [q, setQ] = useState("");
  const [position, setPosition] = useState("");
  const [sort, setSort] = useState("goals");
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let alive = true;
    const t = setTimeout(async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await api.players({ q, position, sort, limit: 150 });
        if (alive) setData(res);
      } catch (e) {
        if (alive) setError(e.message);
      } finally {
        if (alive) setLoading(false);
      }
    }, 250);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [q, position, sort]);

  const players = data?.players || [];

  return (
    <div>
      <PageHeader
        title="Player Scoreboard"
        subtitle="Every player's scoring line, owner, and auction price."
        right={
          data && (
            <span className="text-xs font-medium text-pitch-800/60">
              {data.total} players
            </span>
          )
        }
      />

      <Card className="mb-5">
        <div className="flex flex-wrap items-center gap-3">
          <input
            className="input max-w-xs"
            placeholder="Search player name…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <div className="flex items-center gap-1.5">
            {POSITIONS.map((p) => (
              <button
                key={p || "all"}
                onClick={() => setPosition(p)}
                className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition ${
                  position === p
                    ? "bg-pitch-600 text-white"
                    : "bg-pitch-50 text-pitch-700 hover:bg-pitch-100"
                }`}
              >
                {p || "All"}
              </button>
            ))}
          </div>
          <div className="ml-auto flex items-center gap-2">
            <span className="text-xs font-semibold text-pitch-800/60">Sort</span>
            <select
              className="input w-auto"
              value={sort}
              onChange={(e) => setSort(e.target.value)}
            >
              {SORTS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </Card>

      {error && <ErrorBox message={error} />}
      {loading && <Loading label="Loading players…" />}

      {!loading && !error && players.length === 0 && (
        <EmptyState title="No players match your filters" />
      )}

      {!loading && !error && players.length > 0 && (
        <Card className="!p-0 overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full">
              <thead>
                <tr className="border-b border-pitch-100 bg-pitch-50/40">
                  <th className="th w-10">#</th>
                  <th className="th">Player</th>
                  <th className="th">Pos</th>
                  <th className="th">Club</th>
                  <th className="th">Owner</th>
                  <th className="th text-center">G</th>
                  <th className="th text-center">A</th>
                  <th className="th text-center">YC</th>
                  <th className="th text-center">RC</th>
                  <th className="th text-center">Price</th>
                  <th className="th text-center">FPts</th>
                </tr>
              </thead>
              <tbody>
                {players.map((p) => (
                  <tr key={p.id} className="border-b border-pitch-50 hover:bg-pitch-50/50">
                    <td className="td font-bold text-pitch-700/70">{p.rank}</td>
                    <td className="td font-semibold">{p.name}</td>
                    <td className="td"><PosChip pos={p.position} /></td>
                    <td className="td text-pitch-800/70">{p.real_team}</td>
                    <td className="td">
                      {p.owner ? (
                        <span className="pill bg-pitch-50 text-pitch-700">{p.owner}</span>
                      ) : (
                        <span className="pill bg-slate-100 text-slate-500">Free</span>
                      )}
                    </td>
                    <td className="td text-center font-semibold">{p.goals}</td>
                    <td className="td text-center">{p.assists}</td>
                    <td className="td text-center">{p.yellows}</td>
                    <td className="td text-center">{p.reds}</td>
                    <td className="td text-center text-pitch-800/70">
                      {p.acquired_price != null ? `${p.acquired_price}m` : "—"}
                    </td>
                    <td className="td text-center text-base font-extrabold text-pitch-700">
                      {p.fantasy_points}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
