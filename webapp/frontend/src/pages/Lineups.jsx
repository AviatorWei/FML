import { useEffect, useMemo, useState } from "react";
import { api } from "../api.js";
import { Card, PageHeader, Loading, EmptyState, PosChip } from "../components/ui.jsx";
import { Btn, Field, ManagerPicker, Toast, useToast, inputCls } from "../components/admin.jsx";

// Fallback until /api/lineups/constraints loads (FME-2021 shape).
const DEFAULT_RULES = {
  positions: ["G", "D", "M", "F"],
  starters_min: 8,
  starters_max: 10,
  appearance_caps: { G: 1, D: 3, M: 4, F: 2 },
  group_caps: [],
  must_have_positions: ["G"],
  backward_substitution: { D: ["M", "F"], M: ["F"] },
};

export default function Lineups() {
  const [managerId, setManagerId] = useState(null);
  const [gws, setGws] = useState([]);
  const [gw, setGw] = useState(null);
  const [roster, setRoster] = useState([]);
  const [starters, setStarters] = useState([]); // [{player_id, slot_position}]
  const [pkOrder, setPkOrder] = useState([]);
  const [verdict, setVerdict] = useState(null);
  const [existing, setExisting] = useState(null);
  const [busy, setBusy] = useState(false);
  const [rules, setRules] = useState(DEFAULT_RULES);
  const [toast, show] = useToast();

  useEffect(() => {
    api.lineupConstraints().then(setRules).catch(() => {});
    api.gameweeks().then((r) => {
      setGws(r.gameweeks);
      const open = r.gameweeks.find((g) => g.status === "PENDING");
      setGw(open ? open.index : r.gameweeks[0]?.index ?? null);
    });
  }, []);

  // roster of the selected manager (players endpoint filtered client-side by owner)
  useEffect(() => {
    if (!managerId) return;
    api.managers().then((r) => {
      const mgr = r.managers.find((m) => m.id === managerId);
      if (!mgr) return;
      api.players({ limit: 1000, sort: "name" }).then((res) => {
        setRoster(res.players.filter((p) => p.owner === mgr.name));
      });
    });
  }, [managerId]);

  // preload an already-submitted lineup
  useEffect(() => {
    if (!managerId || gw == null) return;
    api.lineups(gw).then((r) => {
      const mine = r.lineups.find((l) => l.manager_id === managerId);
      setExisting(mine || null);
      if (mine) {
        setStarters(
          mine.starters.map((s) => ({ player_id: s.player_id, slot_position: s.slot_position }))
        );
        setPkOrder(mine.pk_order || []);
      } else {
        setStarters([]);
        setPkOrder([]);
      }
      setVerdict(null);
    });
  }, [managerId, gw]);

  const gwObj = gws.find((g) => g.index === gw);
  const deadline = gwObj?.lineup_deadline ? new Date(gwObj.lineup_deadline) : null;
  const locked = gwObj && gwObj.status !== "PENDING";

  // Rule-driven slots/caps (supports both 4-position FME and 5-position FML/FMC)
  const SLOTS = rules.positions;
  const CAPS = rules.appearance_caps;
  const allowedSlots = (pos) => [pos, ...(rules.backward_substitution?.[pos] || [])];
  const capLabel = (sl) => (CAPS[sl] != null ? `/${CAPS[sl]}` : "");
  const groupCount = (positions) =>
    starters.filter((s) => positions.includes(s.slot_position)).length;
  const rulesText =
    `${rules.starters_min}–${rules.starters_max} starters · ` +
    Object.entries(CAPS).map(([p, c]) => `${p}≤${c}`).join(" ") +
    (rules.group_caps || [])
      .map((g) => ` · ${g.positions.join("+")}≤${g.max}`)
      .join("");

  const byId = useMemo(() => new Map(roster.map((p) => [p.id, p])), [roster]);
  const inLineup = (pid) => starters.some((s) => s.player_id === pid);

  const add = (p) => {
    if (inLineup(p.id)) return;
    setStarters([...starters, { player_id: p.id, slot_position: p.position }]);
    setVerdict(null);
  };
  const remove = (pid) => {
    setStarters(starters.filter((s) => s.player_id !== pid));
    setPkOrder(pkOrder.filter((x) => x !== pid));
    setVerdict(null);
  };
  const setSlot = (pid, slot) => {
    setStarters(starters.map((s) => (s.player_id === pid ? { ...s, slot_position: slot } : s)));
    setVerdict(null);
  };

  const validate = async () => {
    try {
      const v = await api.lineupValidate({ manager_id: managerId, starters, gameweek: gw });
      setVerdict(v);
      const cupIssues = v.cup_blocked?.length || 0;
      show(
        !v.valid ? v.error : cupIssues ? `${cupIssues} starter(s) blocked by cup rules` : "Validation passed",
        v.valid && !cupIssues ? "ok" : "error"
      );
    } catch (e) {
      show(e.message, "error");
    }
  };

  const submit = async () => {
    setBusy(true);
    try {
      const r = await api.lineupSubmit(gw, managerId, {
        manager_id: managerId,
        starters,
        pk_order: pkOrder.length ? pkOrder : null,
      });
      setVerdict(r);
      show("Lineup submitted ✓ (server time stamped)");
    } catch (e) {
      show(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const slotCount = (slot) => starters.filter((s) => s.slot_position === slot).length;
  const movePk = (pid, dir) => {
    const i = pkOrder.indexOf(pid);
    const j = i + dir;
    if (i < 0 || j < 0 || j >= pkOrder.length) return;
    const next = [...pkOrder];
    [next[i], next[j]] = [next[j], next[i]];
    setPkOrder(next);
  };

  return (
    <div>
      <PageHeader
        title="Lineup Entry"
        subtitle={rulesText}
        right={
          <div className="flex items-end gap-3">
            <Field label="Manager">
              <ManagerPicker value={managerId} onChange={setManagerId} allowEmpty emptyLabel="Pick manager…" />
            </Field>
            <Field label="Gameweek">
              <select
                className={inputCls + " w-44"}
                value={gw ?? ""}
                onChange={(e) => setGw(Number(e.target.value))}
              >
                {gws.map((g) => (
                  <option key={g.id} value={g.index}>
                    {g.competition === "CUP" ? "🏆 " : ""}GW{g.index} · {g.phase} · {g.status}
                  </option>
                ))}
              </select>
            </Field>
          </div>
        }
      />

      {deadline && (
        <div
          className={`mb-4 rounded-xl px-4 py-2.5 text-sm font-semibold ${
            locked ? "bg-rose-50 text-rose-700" : "bg-pitch-50 text-pitch-800"
          }`}
        >
          {locked
            ? `Gameweek is ${gwObj.status} — lineups are locked.`
            : `Lineup deadline: ${deadline.toLocaleString()}`}
          {existing && (
            <span className="ml-3 text-xs font-medium">
              (last submitted {new Date(existing.posted_at).toLocaleString()})
            </span>
          )}
        </div>
      )}

      {!managerId ? (
        <EmptyState title="Pick a manager to edit their lineup" />
      ) : (
        <div className="grid gap-5 lg:grid-cols-2">
          <Card>
            <div className="mb-3 text-sm font-bold">Roster ({roster.length})</div>
            {roster.length === 0 ? (
              <EmptyState title="Empty roster" hint="Acquire players via auction or free sign first." />
            ) : (
              <div className="max-h-[520px] space-y-1.5 overflow-auto pr-1">
                {roster.map((p) => (
                  <div
                    key={p.id}
                    className="flex items-center gap-2 rounded-lg border border-pitch-50 px-3 py-1.5 text-sm"
                  >
                    <PosChip pos={p.position} />
                    <span className="font-semibold">{p.name}</span>
                    <span className="text-xs text-slate-500">
                      #{p.id} · {p.real_team} · {p.acquired_price ?? 0}m
                    </span>
                    {inLineup(p.id) ? (
                      <span className="ml-auto pill bg-pitch-100 text-pitch-700">in lineup</span>
                    ) : (
                      <Btn tone="ghost" className="ml-auto" onClick={() => add(p)}>
                        add
                      </Btn>
                    )}
                  </div>
                ))}
              </div>
            )}
          </Card>

          <div className="space-y-5">
            <Card>
              <div className="mb-3 flex items-center justify-between">
                <div className="text-sm font-bold">
                  Starters ({starters.length}/{rules.starters_max})
                </div>
                <div className="flex flex-wrap gap-1.5 text-xs font-bold">
                  {SLOTS.map((sl) => (
                    <span
                      key={sl}
                      className={`pill ${
                        CAPS[sl] != null && slotCount(sl) > CAPS[sl]
                          ? "bg-rose-50 text-rose-700"
                          : "bg-slate-100 text-slate-600"
                      }`}
                    >
                      {sl} {slotCount(sl)}{capLabel(sl)}
                    </span>
                  ))}
                  {(rules.group_caps || []).map((g, i) => (
                    <span
                      key={`g${i}`}
                      className={`pill ${
                        groupCount(g.positions) > g.max
                          ? "bg-rose-50 text-rose-700"
                          : "bg-violet-50 text-violet-700"
                      }`}
                    >
                      {g.positions.join("+")} {groupCount(g.positions)}/{g.max}
                    </span>
                  ))}
                </div>
              </div>
              {starters.length === 0 ? (
                <EmptyState title="No starters yet" hint="Add players from the roster." />
              ) : (
                <div className="space-y-1.5">
                  {SLOTS.slice()
                    .reverse()
                    .map((slot) =>
                      starters
                        .filter((s) => s.slot_position === slot)
                        .map((s) => {
                          const p = byId.get(s.player_id);
                          if (!p) return null;
                          return (
                            <div
                              key={s.player_id}
                              className="flex items-center gap-2 rounded-lg bg-pitch-50/60 px-3 py-1.5 text-sm"
                            >
                              <span className="font-semibold">{p.name}</span>
                              <span className="text-xs text-slate-500">({p.position})</span>
                              <span className="ml-auto text-xs font-semibold text-slate-500">
                                slot
                              </span>
                              <select
                                className="rounded-lg border border-pitch-100 px-2 py-1 text-xs font-bold"
                                value={s.slot_position}
                                onChange={(e) => setSlot(s.player_id, e.target.value)}
                              >
                                {SLOTS.map((sl) => (
                                  <option
                                    key={sl}
                                    value={sl}
                                    disabled={!allowedSlots(p.position).includes(sl)}
                                  >
                                    {sl}
                                    {!allowedSlots(p.position).includes(sl) ? " (drop!)" : ""}
                                  </option>
                                ))}
                              </select>
                              <button
                                className="text-xs font-bold text-rose-500"
                                onClick={() => remove(s.player_id)}
                              >
                                ✕
                              </button>
                            </div>
                          );
                        })
                    )}
                </div>
              )}
              <div className="mt-4 flex gap-2">
                <Btn tone="ghost" onClick={validate} disabled={!starters.length}>
                  Validate (rule 四 preview)
                </Btn>
                <Btn onClick={submit} disabled={busy || locked || !starters.length}>
                  Submit lineup
                </Btn>
              </div>
              {verdict && (
                <div className="mt-3 rounded-xl bg-pitch-50 p-3 text-sm">
                  {verdict.valid === false ? (
                    <div className="font-semibold text-rose-700">✕ {verdict.error}</div>
                  ) : (
                    <>
                      <div className="font-semibold text-pitch-700">
                        ✓ {verdict.accepted.length} starter(s) accepted
                      </div>
                      {verdict.dropped.length > 0 && (
                        <div className="mt-1 space-y-0.5">
                          {verdict.dropped.map((d) => (
                            <div key={d.player_id} className="text-amber-700">
                              ⚠ {byId.get(d.player_id)?.name || `#${d.player_id}`} dropped —{" "}
                              {d.reason} (scores nothing, rule 四.9)
                            </div>
                          ))}
                        </div>
                      )}
                      {verdict.cup_blocked?.length > 0 && (
                        <div className="mt-1 space-y-0.5">
                          {verdict.cup_blocked.map((b) => (
                            <div key={b.player_id} className="font-semibold text-violet-700">
                              🏆 {b.player || `#${b.player_id}`} blocked — {b.reason}
                            </div>
                          ))}
                        </div>
                      )}
                    </>
                  )}
                </div>
              )}
            </Card>

            <Card>
              <div className="mb-2 flex items-center justify-between">
                <div className="text-sm font-bold">PK order (knockout)</div>
                <Btn
                  tone="gray"
                  onClick={() => setPkOrder(starters.map((s) => s.player_id))}
                  disabled={!starters.length}
                >
                  Use starter order
                </Btn>
              </div>
              {pkOrder.length === 0 ? (
                <div className="text-xs text-slate-500">
                  Optional for group stage; required for knockout gameweeks.
                </div>
              ) : (
                <div className="space-y-1">
                  {pkOrder.map((pid, i) => (
                    <div key={pid} className="flex items-center gap-2 rounded-lg border border-pitch-50 px-3 py-1 text-sm">
                      <span className="w-5 font-extrabold text-pitch-700">{i + 1}.</span>
                      <span className="font-semibold">{byId.get(pid)?.name || `#${pid}`}</span>
                      <span className="ml-auto flex gap-1">
                        <button className="px-1 text-slate-500" onClick={() => movePk(pid, -1)}>
                          ↑
                        </button>
                        <button className="px-1 text-slate-500" onClick={() => movePk(pid, 1)}>
                          ↓
                        </button>
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Card>
          </div>
        </div>
      )}
      <Toast toast={toast} />
    </div>
  );
}
