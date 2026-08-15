import { useEffect, useState } from "react";
import { api } from "../../api.js";
import { Card, PageHeader, Loading, EmptyState, StatusBadge } from "../../components/ui.jsx";
import { Btn, DropZone, Field, PlayerSearch, Toast, useToast, inputCls } from "../../components/admin.jsx";

const EVENT_TYPES = [
  ["GOAL", "⚽ Goal"],
  ["OWN_GOAL", "🥅 Own goal"],
  ["ASSIST", "🎯 Assist"],
  ["YELLOW", "🟨 Yellow"],
  ["SECOND_YELLOW_RED", "🟨🟥 2nd yellow"],
  ["RED", "🟥 Red"],
  ["SAVED_PENALTY_BY_GK", "🧤 Saved pen (GK)"],
  ["MISSED_PENALTY", "❌ Missed pen"],
];

const TYPE_TONE = {
  GOAL: "bg-pitch-100 text-pitch-700",
  OWN_GOAL: "bg-amber-50 text-amber-700",
  ASSIST: "bg-sky-50 text-sky-700",
  YELLOW: "bg-amber-50 text-amber-700",
  SECOND_YELLOW_RED: "bg-rose-50 text-rose-700",
  RED: "bg-rose-50 text-rose-700",
  SAVED_PENALTY_BY_GK: "bg-pitch-50 text-pitch-700",
  MISSED_PENALTY: "bg-slate-100 text-slate-600",
};

export default function Events() {
  const [gws, setGws] = useState(null);
  const [gw, setGw] = useState(null);
  const [events, setEvents] = useState([]);
  const [gwStatus, setGwStatus] = useState("");
  const [tally, setTally] = useState([]);
  const [player, setPlayer] = useState(null);
  const [etype, setEtype] = useState("GOAL");
  const [minute, setMinute] = useState("");
  const [et, setEt] = useState(false);
  const [so, setSo] = useState(false);
  const [importReport, setImportReport] = useState(null);
  const [pendingFile, setPendingFile] = useState(null);
  const [toast, show] = useToast();

  useEffect(() => {
    api.gameweeks().then((r) => {
      setGws(r.gameweeks);
      const live = r.gameweeks.find((g) => g.status === "LIVE");
      setGw(live ? live.index : r.gameweeks[0]?.index ?? null);
    });
  }, []);

  const refresh = (index = gw) => {
    if (index == null) return;
    api
      .adminEvents(index)
      .then((r) => {
        setEvents(r.events);
        setGwStatus(r.status);
      })
      .catch((e) => show(e.message, "error"));
    api.adminTally(index).then((r) => setTally(r.fixtures)).catch(() => setTally([]));
  };

  useEffect(() => {
    refresh(gw);
  }, [gw]);

  if (!gws) return <Loading label="Loading gameweeks…" />;
  if (!gws.length) return <EmptyState title="No gameweeks" hint="Create gameweeks first (Admin → Gameweeks)." />;

  const add = async () => {
    if (!player) return show("Pick a player first", "error");
    try {
      const r = await api.adminEventAdd({
        gameweek: gw,
        player_id: player.id,
        event_type: etype,
        minute: minute === "" ? null : Number(minute),
        is_extra_time: et,
        is_shootout: so,
      });
      (r.warnings || []).forEach((w) => show(`⚠ ${w}`, "error"));
      if (!r.warnings?.length) show(`${player.name} · ${etype} recorded`);
      setPlayer(null);
      setMinute("");
      setEt(false);
      setSo(false);
      refresh();
    } catch (e) {
      show(e.message, "error");
    }
  };

  const del = async (id) => {
    try {
      await api.adminEventDelete(id);
      refresh();
    } catch (e) {
      show(e.message, "error");
    }
  };

  const doImport = async (file, dryRun) => {
    try {
      const r = await api.adminEventsImport(file, dryRun);
      setImportReport(r);
      setPendingFile(dryRun && r.ok ? file : null);
      show(
        r.ok
          ? dryRun
            ? `Dry run: ${r.would_import} event(s) would import`
            : `${r.imported} event(s) imported`
          : `${r.errors.length} error(s) — nothing imported`,
        r.ok ? "ok" : "error"
      );
      if (!dryRun && r.ok) refresh();
    } catch (e) {
      show(e.message, "error");
    }
  };

  return (
    <div>
      <PageHeader
        title="Event Entry"
        subtitle="Events are keyed by (gameweek, player) — no fixture id needed. Gameweek must be LIVE."
        right={
          <div className="flex items-center gap-2">
            <select
              className={inputCls + " w-48"}
              value={gw ?? ""}
              onChange={(e) => setGw(Number(e.target.value))}
            >
              {gws.map((g) => (
                <option key={g.id} value={g.index}>
                  GW{g.index} · {g.phase} · {g.status}
                </option>
              ))}
            </select>
            <StatusBadge status={gwStatus} />
          </div>
        }
      />

      <Card className="mb-5">
        <div className="mb-2 text-sm font-bold">New event</div>
        <div className="grid gap-3 md:grid-cols-[1fr_auto_auto_auto_auto]">
          <div>
            {player ? (
              <div className="flex items-center gap-2 rounded-lg border border-pitch-200 bg-pitch-50 px-3 py-2 text-sm font-semibold">
                {player.name}
                <span className="text-xs text-slate-500">
                  #{player.id} · {player.position} · {player.real_team}
                </span>
                <button className="ml-auto text-rose-600" onClick={() => setPlayer(null)}>
                  ✕
                </button>
              </div>
            ) : (
              <PlayerSearch onPick={setPlayer} />
            )}
          </div>
          <input
            className={inputCls + " w-20"}
            placeholder="min"
            value={minute}
            onChange={(e) => setMinute(e.target.value.replace(/\D/g, ""))}
          />
          <label className="flex items-center gap-1.5 text-sm font-semibold">
            <input type="checkbox" checked={et} onChange={(e) => setEt(e.target.checked)} /> ET
          </label>
          <label className="flex items-center gap-1.5 text-sm font-semibold">
            <input type="checkbox" checked={so} onChange={(e) => setSo(e.target.checked)} />{" "}
            Shootout
          </label>
          <Btn onClick={add} disabled={gwStatus !== "LIVE"}>
            Add event ⏎
          </Btn>
        </div>
        <div className="mt-3 flex flex-wrap gap-1.5">
          {EVENT_TYPES.map(([v, label]) => (
            <button
              key={v}
              onClick={() => setEtype(v)}
              className={`rounded-lg border px-3 py-1.5 text-xs font-bold transition ${
                etype === v
                  ? "border-pitch-500 bg-pitch-100 text-pitch-800"
                  : "border-pitch-100 bg-white text-slate-600 hover:bg-pitch-50"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        {gwStatus !== "LIVE" && (
          <div className="mt-3 rounded-lg bg-amber-50 px-3 py-2 text-xs font-semibold text-amber-700">
            Gameweek is {gwStatus} — set it LIVE (Admin → Gameweeks) before entering events.
          </div>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-2">
        <Card>
          <div className="mb-3 text-sm font-bold">Event log — GW{gw} ({events.length})</div>
          {events.length === 0 ? (
            <EmptyState title="No events yet" />
          ) : (
            <div className="max-h-[480px] space-y-1.5 overflow-auto pr-1">
              {events.map((e) => (
                <div
                  key={e.id}
                  className="flex items-center gap-2 rounded-lg border border-pitch-50 px-3 py-1.5 text-sm"
                >
                  <span className="font-semibold">{e.player}</span>
                  <span className={`pill ${TYPE_TONE[e.event_type] || ""}`}>
                    {e.event_type}
                    {e.is_extra_time && " · ET"}
                    {e.is_shootout && " · SO"}
                  </span>
                  {e.minute != null && (
                    <span className="text-xs text-slate-500">{e.minute}'</span>
                  )}
                  <button
                    className="ml-auto text-xs font-bold text-rose-500 hover:text-rose-700"
                    onClick={() => del(e.id)}
                    disabled={gwStatus !== "LIVE"}
                  >
                    ✕
                  </button>
                </div>
              ))}
            </div>
          )}
        </Card>

        <div className="space-y-5">
          <Card>
            <div className="mb-3 text-sm font-bold">
              Live valid-goal tally <span className="font-normal text-xs text-slate-500">(rule 零.4 — shootout excluded, starters only)</span>
            </div>
            {tally.length === 0 ? (
              <EmptyState title="No fixtures in this gameweek" />
            ) : (
              <div className="space-y-2">
                {tally.map((f) => (
                  <div
                    key={f.fixture_id}
                    className="flex items-center justify-between rounded-lg bg-pitch-50/60 px-3 py-2 text-sm"
                  >
                    <span className="font-semibold">
                      {f.home} <span className="text-slate-400">vs</span> {f.away}
                      {f.group && <span className="ml-1 text-xs text-slate-500">(Grp {f.group})</span>}
                      {f.bracket_slot && (
                        <span className="ml-1 text-xs text-slate-500">({f.bracket_slot})</span>
                      )}
                    </span>
                    <span className="flex items-center gap-2">
                      {(!f.home_lineup || !f.away_lineup) && (
                        <span className="pill bg-amber-50 text-amber-700">lineup missing</span>
                      )}
                      <span className="text-base font-extrabold">
                        {f.home_goals} : {f.away_goals}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            )}
          </Card>

          <Card>
            <div className="mb-2 text-sm font-bold">Bulk CSV import</div>
            <div className="mb-2 text-xs text-slate-500">
              Columns: gameweek, player_id, event_type, minute, is_extra_time, is_shootout —
              round-trips with the events.csv export.
            </div>
            <DropZone
              hint="Drop events.csv (dry-run first)"
              multiple={false}
              accept=".csv"
              onFiles={(f) => doImport(f[0], true)}
            />
            {importReport && (
              <div className="mt-3 text-sm">
                {importReport.errors?.map((e, i) => (
                  <div key={i} className="text-rose-600">
                    line {e.line}: {e.error}
                  </div>
                ))}
                {importReport.ok && importReport.dry_run && pendingFile && (
                  <div className="mt-2 flex items-center gap-3">
                    <span className="font-semibold text-pitch-700">
                      ✓ {importReport.would_import} event(s) ready to import
                    </span>
                    <Btn onClick={() => doImport(pendingFile, false)}>Commit import</Btn>
                  </div>
                )}
              </div>
            )}
          </Card>
        </div>
      </div>
      <Toast toast={toast} />
    </div>
  );
}
