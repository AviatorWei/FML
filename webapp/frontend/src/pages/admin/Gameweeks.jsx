import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { Card, PageHeader, Loading, EmptyState, StatusBadge } from "../../components/ui.jsx";
import { Btn, Field, ManagerPicker, Toast, useToast, inputCls } from "../../components/admin.jsx";

export default function Gameweeks() {
  const [gws, setGws] = useState(null);
  const [report, setReport] = useState(null);
  const [newGw, setNewGw] = useState({
    index: "",
    phase: "GROUP",
    lineup_deadline: "",
    competition: "LEAGUE",
  });
  const [fx, setFx] = useState({ gwId: null, home: null, away: null, group: "", slot: "" });
  const [pk, setPk] = useState({ fixtureId: "", managerId: null });
  const [busy, setBusy] = useState(false);
  const [toast, show] = useToast();

  const refresh = () =>
    api.adminGameweeks().then((r) => setGws(r.gameweeks)).catch((e) => show(e.message, "error"));

  useEffect(() => {
    refresh();
  }, []);

  if (!gws) return <Loading label="Loading gameweeks…" />;

  const createGw = async () => {
    try {
      await api.adminGameweekCreate({
        index: Number(newGw.index),
        phase: newGw.phase,
        lineup_deadline: newGw.lineup_deadline,
        competition: newGw.competition,
      });
      show(`Gameweek ${newGw.index} created (${newGw.competition})`);
      setNewGw({ index: "", phase: "GROUP", lineup_deadline: "", competition: "LEAGUE" });
      refresh();
    } catch (e) {
      show(e.message, "error");
    }
  };

  const addFixture = async () => {
    try {
      await api.adminFixtureCreate(fx.gwId, {
        home_manager_id: fx.home,
        away_manager_id: fx.away,
        group_letter: fx.group || null,
        bracket_slot: fx.slot || null,
      });
      show("Fixture added");
      refresh();
    } catch (e) {
      show(e.message, "error");
    }
  };

  const setLive = async (gw) => {
    try {
      await api.adminGameweekLive(gw.id);
      show(`GW${gw.index} is LIVE — lineups locked`);
      refresh();
    } catch (e) {
      show(e.message, "error");
    }
  };

  const finalize = async (gw, dryRun) => {
    setBusy(true);
    try {
      const r = await api.adminGameweekFinalize(gw.id, dryRun);
      setReport(r);
      show(dryRun ? "Settlement dry run — nothing written" : `GW${gw.index} finalized`);
      if (!dryRun) refresh();
    } catch (e) {
      show(e.message, "error");
    } finally {
      setBusy(false);
    }
  };

  const savePk = async (gw) => {
    try {
      await api.adminPkWinner(gw.id, {
        fixture_id: Number(pk.fixtureId),
        pk_winner_manager_id: pk.managerId,
      });
      show("PK winner recorded");
    } catch (e) {
      show(e.message, "error");
    }
  };

  return (
    <div>
      <PageHeader
        title="Gameweek Lifecycle"
        subtitle="PENDING → LIVE (lineups lock, events open) → FINALIZED (results, bonuses, athletics)"
      />

      <Card className="mb-5">
        <div className="mb-2 text-sm font-bold">Create gameweek + fixtures</div>
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Index">
            <input
              className={inputCls + " w-20"}
              value={newGw.index}
              onChange={(e) => setNewGw({ ...newGw, index: e.target.value })}
            />
          </Field>
          <Field label="Phase">
            <select
              className={inputCls + " w-28"}
              value={newGw.phase}
              onChange={(e) => setNewGw({ ...newGw, phase: e.target.value })}
            >
              {["GROUP", "QF", "SF", "F"].map((p) => (
                <option key={p}>{p}</option>
              ))}
            </select>
          </Field>
          <Field label="Competition">
            <select
              className={inputCls + " w-28"}
              value={newGw.competition}
              onChange={(e) => setNewGw({ ...newGw, competition: e.target.value })}
            >
              {["LEAGUE", "CUP"].map((c) => (
                <option key={c}>{c}</option>
              ))}
            </select>
          </Field>
          <Field label="Lineup deadline (ISO)">
            <input
              className={inputCls + " w-48"}
              placeholder="2026-07-09T18:00"
              value={newGw.lineup_deadline}
              onChange={(e) => setNewGw({ ...newGw, lineup_deadline: e.target.value })}
            />
          </Field>
          <Btn onClick={createGw} disabled={!newGw.index || !newGw.lineup_deadline}>
            + Gameweek
          </Btn>
          <div className="mx-2 h-8 w-px bg-pitch-100" />
          <Field label="Fixture in GW">
            <select
              className={inputCls + " w-24"}
              value={fx.gwId ?? ""}
              onChange={(e) => setFx({ ...fx, gwId: Number(e.target.value) })}
            >
              <option value="">—</option>
              {gws.map((g) => (
                <option key={g.id} value={g.id}>
                  GW{g.index}
                </option>
              ))}
            </select>
          </Field>
          <Field label="Home">
            <ManagerPicker value={fx.home} onChange={(v) => setFx({ ...fx, home: v })} allowEmpty emptyLabel="—" />
          </Field>
          <Field label="Away">
            <ManagerPicker value={fx.away} onChange={(v) => setFx({ ...fx, away: v })} allowEmpty emptyLabel="—" />
          </Field>
          <Field label="Group">
            <input
              className={inputCls + " w-14"}
              maxLength={1}
              value={fx.group}
              onChange={(e) => setFx({ ...fx, group: e.target.value.toUpperCase() })}
            />
          </Field>
          <Field label="Slot">
            <input
              className={inputCls + " w-20"}
              placeholder="QF1"
              value={fx.slot}
              onChange={(e) => setFx({ ...fx, slot: e.target.value })}
            />
          </Field>
          <Btn tone="ghost" onClick={addFixture} disabled={!fx.gwId || !fx.home || !fx.away}>
            + Fixture
          </Btn>
        </div>
      </Card>

      {gws.length === 0 ? (
        <EmptyState title="No gameweeks yet" />
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {gws.map((g) => (
            <Card key={g.id}>
              <div className="mb-1 flex items-center justify-between">
                <div className="flex items-center gap-1.5 text-sm font-bold">
                  GW{g.index} · {g.phase}
                  {g.competition === "CUP" && (
                    <span className="pill bg-violet-100 text-violet-700">🏆 CUP</span>
                  )}
                </div>
                <StatusBadge status={g.status} />
              </div>
              <div className="mb-2 text-xs text-slate-500">
                deadline {g.lineup_deadline ? new Date(g.lineup_deadline).toLocaleString() : "—"} ·{" "}
                {g.lineups_submitted}/{g.lineups_expected} lineups · {g.events} events ·{" "}
                {g.results} results
              </div>
              <div className="mb-3 space-y-1">
                {g.fixtures.map((f) => (
                  <div key={f.id} className="rounded-lg bg-pitch-50/60 px-2.5 py-1 text-xs font-semibold">
                    #{f.id} {f.home} vs {f.away}
                    {f.group && ` · Grp ${f.group}`}
                    {f.bracket_slot && ` · ${f.bracket_slot}`}
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap gap-2">
                {g.status === "PENDING" && (
                  <Btn tone="warn" onClick={() => setLive(g)}>
                    Set LIVE
                  </Btn>
                )}
                {g.status === "LIVE" && (
                  <>
                    <Btn tone="ghost" disabled={busy} onClick={() => finalize(g, true)}>
                      Dry-run settle
                    </Btn>
                    <Btn disabled={busy} onClick={() => finalize(g, false)}>
                      Finalize ▶
                    </Btn>
                  </>
                )}
                {g.phase !== "GROUP" && g.status !== "PENDING" && (
                  <details className="w-full">
                    <summary className="cursor-pointer text-xs font-bold text-pitch-700">
                      PK winner (knockout draw)
                    </summary>
                    <div className="mt-2 flex items-end gap-2">
                      <Field label="Fixture ID">
                        <input
                          className={inputCls + " w-20"}
                          value={pk.fixtureId}
                          onChange={(e) => setPk({ ...pk, fixtureId: e.target.value })}
                        />
                      </Field>
                      <Field label="Winner">
                        <ManagerPicker
                          value={pk.managerId}
                          onChange={(v) => setPk({ ...pk, managerId: v })}
                          allowEmpty
                          emptyLabel="—"
                        />
                      </Field>
                      <Btn tone="ghost" onClick={() => savePk(g)} disabled={!pk.fixtureId || !pk.managerId}>
                        Save
                      </Btn>
                    </div>
                  </details>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {report && (
        <Card className="mt-5">
          <div className="mb-2 text-sm font-bold">
            Settlement report — GW{report.gameweek}{" "}
            {report.dry_run && <span className="pill bg-amber-50 text-amber-700">DRY RUN</span>}
          </div>
          <div className="space-y-1.5">
            {report.fixtures.map((f) => (
              <div key={f.fixture_id} className="flex items-center justify-between rounded-lg bg-pitch-50/60 px-3 py-1.5 text-sm">
                <span className="font-semibold">
                  {f.home} {f.home_goals} : {f.away_goals} {f.away}
                </span>
                <span className="flex items-center gap-2 text-xs">
                  <span className="pill bg-white text-slate-600">{f.outcome}</span>
                  {f.missing_lineups.length > 0 && (
                    <span className="pill bg-amber-50 text-amber-700">
                      no lineup: {f.missing_lineups.join(", ")}
                    </span>
                  )}
                </span>
              </div>
            ))}
          </div>
          {report.bonuses.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-2">
              {report.bonuses.map((b, i) => (
                <span key={i} className="pill bg-sky-50 text-sky-700">
                  {b.manager}: {b.type} +{b.amount}m
                </span>
              ))}
            </div>
          )}
        </Card>
      )}
      <Toast toast={toast} />
    </div>
  );
}
