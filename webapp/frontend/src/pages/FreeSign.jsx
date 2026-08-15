import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";
import {
  Card,
  ErrorBox,
  PageHeader,
  PosChip,
  StatusBadge,
} from "../components/ui.jsx";

function ServerClock({ tz }) {
  const [now, setNow] = useState(null);
  const offsetRef = useRef(0);

  useEffect(() => {
    let alive = true;
    api.time().then((t) => {
      if (!alive) return;
      offsetRef.current = t.epoch_ms - Date.now();
      setNow(new Date(Date.now() + offsetRef.current));
    });
    const id = setInterval(() => {
      setNow(new Date(Date.now() + offsetRef.current));
    }, 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  return (
    <div className="rounded-xl bg-ink-900 px-4 py-3 text-white">
      <div className="text-[11px] font-semibold uppercase tracking-wide text-pitch-200/80">
        Server time {tz ? `· ${tz}` : ""}
      </div>
      <div className="mt-0.5 font-mono text-lg font-bold tabular-nums">
        {now ? now.toUTCString().replace("GMT", "UTC") : "…"}
      </div>
    </div>
  );
}

export default function FreeSign() {
  const [managers, setManagers] = useState([]);
  const [managerId, setManagerId] = useState("");
  const [windows, setWindows] = useState(null);
  const [q, setQ] = useState("");
  const [matches, setMatches] = useState([]);
  const [selected, setSelected] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [outcome, setOutcome] = useState(null);
  const [recent, setRecent] = useState([]);

  async function refreshMeta() {
    const [m, w, list] = await Promise.all([
      api.managers(),
      api.transferWindows(),
      api.freeSignList(),
    ]);
    setManagers(m.managers);
    setWindows(w);
    setRecent(list.free_signs);
    if (!managerId && m.managers.length) setManagerId(String(m.managers[0].id));
  }

  useEffect(() => {
    refreshMeta().catch((e) => setError(e.message));
  }, []);

  // live player lookup
  useEffect(() => {
    let alive = true;
    if (!q.trim()) {
      setMatches([]);
      return;
    }
    const t = setTimeout(async () => {
      try {
        const res = await api.playerSearch(q.trim());
        if (alive) setMatches(res.players);
      } catch {
        if (alive) setMatches([]);
      }
    }, 250);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [q]);

  async function submit() {
    if (!selected || !managerId) return;
    setSubmitting(true);
    setError(null);
    setOutcome(null);
    try {
      const res = await api.freeSign(Number(managerId), selected.id);
      setOutcome(res);
      if (res.success) {
        setSelected(null);
        setQ("");
        setMatches([]);
        refreshMeta().catch(() => {});
      }
    } catch (e) {
      setError(e.message);
    } finally {
      setSubmitting(false);
    }
  }

  const active = windows?.active_window;

  async function revoke(id) {
    try {
      const r = await api.freeSignRevoke(id);
      if (!r.success) setError(r.error);
      refreshMeta().catch(() => {});
    } catch (e) {
      setError(e.message);
    }
  }

  async function commitDue() {
    try {
      const r = await api.freeSignCommitDue();
      setOutcome({ success: true, player: `${r.committed} sign(s)`, manager: "committed", fee: "—", revoke_window_seconds: 0 });
      refreshMeta().catch(() => {});
    } catch (e) {
      setError(e.message);
    }
  }

  return (
    <div>
      <PageHeader
        title="Free Signings"
        subtitle="Look up a free agent, confirm their details, and submit. The server stamps the time and validates against the active window."
        right={<ServerClock tz={windows?.windows ? null : null} />}
      />

      <div className="grid gap-5 lg:grid-cols-[1fr_360px]">
        <div className="space-y-5">
          {/* window status */}
          <Card>
            <div className="flex items-center justify-between">
              <h2 className="text-sm font-bold text-ink-900">Transfer window</h2>
              {active ? (
                <StatusBadge status="OPEN" />
              ) : (
                <span className="pill bg-slate-100 text-slate-600">Closed now</span>
              )}
            </div>
            {windows && (
              <div className="mt-3 space-y-2">
                {windows.windows.map((w) => (
                  <div
                    key={w.id}
                    className={`flex flex-wrap items-center justify-between gap-2 rounded-xl px-3 py-2 text-sm ${
                      w.is_open_now ? "bg-pitch-50" : "bg-slate-50"
                    }`}
                  >
                    <span className="font-medium text-ink-900">
                      {new Date(w.opens_at).toLocaleString()} →{" "}
                      {new Date(w.closes_at).toLocaleString()}
                    </span>
                    <span className="text-xs text-pitch-800/60">
                      fee {windows.free_sign_fee}m · revoke {windows.revoke_window_seconds}s
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          {/* signing form */}
          <Card>
            <h2 className="mb-3 text-sm font-bold text-ink-900">New signing</h2>

            <label className="mb-1 block text-xs font-semibold text-pitch-800/70">
              Manager
            </label>
            <select
              className="input mb-4"
              value={managerId}
              onChange={(e) => setManagerId(e.target.value)}
            >
              {managers.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.name} · {m.balance}m · {m.roster_size} players
                </option>
              ))}
            </select>

            <label className="mb-1 block text-xs font-semibold text-pitch-800/70">
              Find a player (name or ID)
            </label>
            <input
              className="input"
              placeholder="e.g. Kane or 42"
              value={q}
              onChange={(e) => {
                setQ(e.target.value);
                setSelected(null);
              }}
            />

            {matches.length > 0 && !selected && (
              <div className="mt-2 max-h-64 divide-y divide-pitch-50 overflow-y-auto rounded-xl border border-pitch-100">
                {matches.map((p) => (
                  <button
                    key={p.id}
                    onClick={() => setSelected(p)}
                    className="flex w-full items-center gap-3 px-3 py-2.5 text-left hover:bg-pitch-50"
                  >
                    <PosChip pos={p.position} />
                    <span className="flex-1 font-semibold text-ink-900">{p.name}</span>
                    <span className="text-xs text-pitch-800/60">{p.real_team}</span>
                    {p.free_agent ? (
                      <span className="pill bg-pitch-100 text-pitch-700">Free</span>
                    ) : (
                      <span className="pill bg-slate-100 text-slate-500">{p.owner}</span>
                    )}
                  </button>
                ))}
              </div>
            )}

            {selected && (
              <div className="mt-4 rounded-2xl border border-pitch-200 bg-pitch-50/50 p-4">
                <div className="flex items-center gap-3">
                  <PosChip pos={selected.position} />
                  <div className="flex-1">
                    <div className="font-bold text-ink-900">{selected.name}</div>
                    <div className="text-xs text-pitch-800/60">
                      {selected.real_team} · ID {selected.id}
                    </div>
                  </div>
                  {selected.free_agent ? (
                    <span className="pill bg-pitch-100 text-pitch-700">Free agent</span>
                  ) : (
                    <span className="pill bg-rose-100 text-rose-600">
                      Owned · {selected.owner}
                    </span>
                  )}
                </div>

                <button
                  className="btn-primary mt-4 w-full"
                  disabled={submitting || !active || !selected.free_agent}
                  onClick={submit}
                >
                  {submitting
                    ? "Submitting…"
                    : !active
                    ? "Window closed"
                    : !selected.free_agent
                    ? "Player not available"
                    : `Sign for ${windows?.free_sign_fee}m`}
                </button>
                <button
                  className="btn-ghost mt-2 w-full"
                  onClick={() => setSelected(null)}
                >
                  Choose another
                </button>
              </div>
            )}

            {error && (
              <div className="mt-3">
                <ErrorBox message={error} />
              </div>
            )}

            {outcome && (
              <div
                className={`mt-3 rounded-xl px-4 py-3 text-sm font-medium ${
                  outcome.success
                    ? "bg-pitch-100 text-pitch-800"
                    : "bg-rose-50 text-rose-700"
                }`}
              >
                {outcome.success
                  ? `Signed ${outcome.player} to ${outcome.manager} for ${outcome.fee}m. You have ${outcome.revoke_window_seconds}s to revoke.`
                  : `Rejected: ${outcome.error}`}
              </div>
            )}
          </Card>
        </div>

        {/* recent */}
        <Card>
          <div className="mb-3 flex items-center justify-between">
            <h2 className="text-sm font-bold text-ink-900">Recent signings</h2>
            <button
              className="rounded-lg bg-pitch-50 px-2.5 py-1 text-xs font-bold text-pitch-800 hover:bg-pitch-100"
              title="Commit all pending signs whose revoke window has elapsed"
              onClick={commitDue}
            >
              ⟳ process due
            </button>
          </div>
          {recent.length === 0 ? (
            <p className="text-sm text-pitch-800/50">No free signings yet.</p>
          ) : (
            <div className="space-y-2">
              {recent.slice(0, 12).map((fs) => (
                <div
                  key={fs.id}
                  className="flex items-center justify-between rounded-xl bg-pitch-50/60 px-3 py-2"
                >
                  <div>
                    <div className="text-sm font-semibold text-ink-900">{fs.player}</div>
                    <div className="text-xs text-pitch-800/60">→ {fs.manager}</div>
                  </div>
                  <span className="flex items-center gap-1.5">
                    <span
                      className={`pill ${
                        fs.revoked
                          ? "bg-slate-100 text-slate-500"
                          : fs.effective
                          ? "bg-pitch-100 text-pitch-700"
                          : "bg-amber-100 text-amber-700"
                      }`}
                    >
                      {fs.revoked ? "revoked" : fs.effective ? "done" : "pending"}
                    </span>
                    {!fs.revoked && !fs.effective && (
                      <button
                        className="rounded-lg bg-rose-50 px-2 py-0.5 text-xs font-bold text-rose-600 hover:bg-rose-100"
                        onClick={() => revoke(fs.id)}
                      >
                        revoke
                      </button>
                    )}
                  </span>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
    </div>
  );
}
