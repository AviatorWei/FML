import { useEffect, useState } from "react";
import { api, download } from "../../api.js";
import { Card, PageHeader, Loading, EmptyState, PosChip } from "../../components/ui.jsx";
import {
  Btn,
  DropZone,
  Field,
  ManagerPicker,
  PlayerSearch,
  Toast,
  useToast,
  inputCls,
} from "../../components/admin.jsx";

const VIA_TONE = {
  AUCTION: "bg-sky-50 text-sky-700",
  FREE_SIGN: "bg-amber-50 text-amber-700",
  TRADE: "bg-slate-100 text-slate-600",
  KO_PICK: "bg-pitch-50 text-pitch-700",
  INJURY_GRANT: "bg-rose-50 text-rose-700",
};

export default function Roster() {
  const [filter, setFilter] = useState({ managerId: null, includeReleased: false });
  const [entries, setEntries] = useState(null);
  const [trades, setTrades] = useState([]);
  const [add, setAdd] = useState({ managerId: null, player: null, via: "AUCTION", price: 0 });
  const [injury, setInjury] = useState({ player: null, refund: "", grant: false, grantee: null });
  const [trade, setTrade] = useState({ initiator: null, counterparty: null, legs: [] });
  const [importReport, setImportReport] = useState(null);
  const [pendingFile, setPendingFile] = useState(null);
  const [cup, setCup] = useState(null);
  const [cupRoster, setCupRoster] = useState([]);
  const [toast, show] = useToast();

  const refresh = () => {
    api.adminRoster(filter).then((r) => setEntries(r.entries)).catch((e) => show(e.message, "error"));
    api.adminTrades().then((r) => setTrades(r.trades)).catch(() => {});
    api.cupStatus().then(setCup).catch(() => {});
    api.cupRoster().then((r) => setCupRoster(r.entries)).catch(() => {});
  };
  useEffect(() => {
    refresh();
  }, [filter]);

  if (!entries) return <Loading label="Loading roster…" />;

  const act = (fn, ok) => async (...args) => {
    try {
      await fn(...args);
      show(ok);
      refresh();
    } catch (e) {
      show(e.message, "error");
    }
  };

  const doAdd = act(
    () =>
      api.adminRosterAdd({
        manager_id: add.managerId,
        player_id: add.player.id,
        via: add.via,
        price: Number(add.price) || 0,
      }),
    "Roster entry added"
  );
  const doRelease = (e) =>
    act(
      () => api.adminRosterRelease({ manager_id: e.manager_id, player_id: e.player_id }),
      `${e.player} released (RELEASED_LIFETIME block recorded)`
    )();
  const doDismiss = (e) => {
    const reason = prompt(`Dismiss ${e.player} from ${e.manager}? Reason (optional):`);
    if (reason === null) return;
    act(
      () =>
        api.adminDismiss({ manager_id: e.manager_id, player_id: e.player_id, reason: reason || null }),
      `${e.player} dismissed (DISMISSED_LIFETIME block recorded)`
    )();
  };
  const doInjury = act(
    () =>
      api.adminInjury({
        player_id: injury.player.id,
        refund_amount: injury.refund === "" ? null : Number(injury.refund),
        free_sign_grant: injury.grant,
        granted_to_manager_id: injury.grantee,
      }),
    "Injury adjustment recorded"
  );

  const addLeg = (side) =>
    setTrade({ ...trade, legs: [...trade.legs, { side, player_id: null, cash_amount: null, _label: "" }] });
  const doTrade = act(
    () =>
      api.adminTradeCreate({
        initiator_id: trade.initiator,
        counterparty_id: trade.counterparty,
        legs: trade.legs.map(({ side, player_id, cash_amount }) => ({ side, player_id, cash_amount })),
      }),
    "Trade proposed"
  );

  const doImport = async (file, dryRun) => {
    try {
      const r = await api.adminRosterImport(file, dryRun);
      setImportReport(r);
      setPendingFile(dryRun && r.ok ? file : null);
      show(
        r.ok
          ? dryRun
            ? `Dry run: ${r.would_add} entr(ies) would be added, ${r.skipped.length} skipped`
            : `${r.added} entr(ies) added`
          : `${r.errors.length} error(s)`,
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
        title="Roster Editor"
        subtitle="Every write runs engine checks (free agency, eligibility, balance) and records acquired_via"
        right={
          <div className="flex items-end gap-2">
            <Field label="Manager">
              <ManagerPicker
                value={filter.managerId}
                onChange={(v) => setFilter({ ...filter, managerId: v })}
                allowEmpty
              />
            </Field>
            <label className="flex items-center gap-1.5 pb-2 text-sm font-semibold">
              <input
                type="checkbox"
                checked={filter.includeReleased}
                onChange={(e) => setFilter({ ...filter, includeReleased: e.target.checked })}
              />
              show released
            </label>
            <Btn tone="ghost" onClick={() => download("/api/export/rosters.csv?include_released=true").catch((e) => show(e.message, "error"))}>
              ⬇ Export
            </Btn>
          </div>
        }
      />

      <Card className="mb-5">
        <div className="mb-2 text-sm font-bold">Add roster entry</div>
        <div className="flex flex-wrap items-end gap-3">
          <div className="w-56">
            <Field label="Manager">
              <ManagerPicker value={add.managerId} onChange={(v) => setAdd({ ...add, managerId: v })} allowEmpty emptyLabel="—" />
            </Field>
          </div>
          <div className="w-72">
            <Field label="Player (free agents only)">
              {add.player ? (
                <div className="flex items-center gap-2 rounded-lg border border-pitch-200 bg-pitch-50 px-3 py-2 text-sm font-semibold">
                  {add.player.name}
                  <button className="ml-auto text-rose-600" onClick={() => setAdd({ ...add, player: null })}>
                    ✕
                  </button>
                </div>
              ) : (
                <PlayerSearch onPick={(p) => setAdd({ ...add, player: p })} />
              )}
            </Field>
          </div>
          <Field label="Via">
            <select className={inputCls + " w-36"} value={add.via} onChange={(e) => setAdd({ ...add, via: e.target.value })}>
              {["AUCTION", "FREE_SIGN", "TRADE", "KO_PICK", "INJURY_GRANT"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </Field>
          <Field label="Price (m)">
            <input className={inputCls + " w-24"} value={add.price} onChange={(e) => setAdd({ ...add, price: e.target.value.replace(/\D/g, "") })} />
          </Field>
          <Btn onClick={doAdd} disabled={!add.managerId || !add.player}>
            + Add
          </Btn>
        </div>
      </Card>

      <Card className="mb-5">
        {entries.length === 0 ? (
          <EmptyState title="No roster entries" />
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wide text-slate-400">
                  <th className="px-3 py-2">Manager</th>
                  <th className="px-3 py-2">Player</th>
                  <th className="px-3 py-2">Pos</th>
                  <th className="px-3 py-2">Via</th>
                  <th className="px-3 py-2">Price</th>
                  <th className="px-3 py-2">Acquired</th>
                  <th className="px-3 py-2">Status</th>
                  <th className="px-3 py-2"></th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.id} className={`border-t border-pitch-50 ${e.released_at ? "opacity-50" : ""}`}>
                    <td className="px-3 py-1.5 font-semibold">{e.manager}</td>
                    <td className="px-3 py-1.5">
                      {e.player} <span className="text-xs text-slate-400">#{e.player_id}</span>
                    </td>
                    <td className="px-3 py-1.5">
                      <PosChip pos={e.position} />
                    </td>
                    <td className="px-3 py-1.5">
                      <span className={`pill ${VIA_TONE[e.via] || ""}`}>{e.via}</span>
                    </td>
                    <td className="px-3 py-1.5">{e.price}m</td>
                    <td className="px-3 py-1.5 text-xs text-slate-500">
                      {new Date(e.acquired_at).toLocaleDateString()}
                    </td>
                    <td className="px-3 py-1.5">
                      {e.released_at ? (
                        <span className="pill bg-rose-50 text-rose-600">
                          released {new Date(e.released_at).toLocaleDateString()}
                        </span>
                      ) : (
                        <span className="pill bg-pitch-100 text-pitch-700">active</span>
                      )}
                    </td>
                    <td className="px-3 py-1.5">
                      {!e.released_at && (
                        <span className="flex gap-1.5">
                          <Btn tone="danger" onClick={() => doRelease(e)}>
                            release
                          </Btn>
                          <Btn tone="gray" onClick={() => doDismiss(e)}>
                            dismiss
                          </Btn>
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <div className="grid gap-5 lg:grid-cols-3">
        <Card>
          <div className="mb-2 text-sm font-bold">Injury adjustment</div>
          <div className="space-y-2">
            {injury.player ? (
              <div className="flex items-center gap-2 rounded-lg border border-pitch-200 bg-pitch-50 px-3 py-2 text-sm font-semibold">
                {injury.player.name}
                <button className="ml-auto text-rose-600" onClick={() => setInjury({ ...injury, player: null })}>
                  ✕
                </button>
              </div>
            ) : (
              <PlayerSearch onPick={(p) => setInjury({ ...injury, player: p })} placeholder="Injured player…" />
            )}
            <Field label="Refund (m, blank = acquired price)">
              <input className={inputCls} value={injury.refund} onChange={(e) => setInjury({ ...injury, refund: e.target.value.replace(/\D/g, "") })} />
            </Field>
            <label className="flex items-center gap-1.5 text-sm font-semibold">
              <input type="checkbox" checked={injury.grant} onChange={(e) => setInjury({ ...injury, grant: e.target.checked })} />
              grant a free sign
            </label>
            {injury.grant && (
              <Field label="Grant to (blank = owner)">
                <ManagerPicker value={injury.grantee} onChange={(v) => setInjury({ ...injury, grantee: v })} allowEmpty emptyLabel="— owner —" />
              </Field>
            )}
            <Btn onClick={doInjury} disabled={!injury.player}>
              Record injury
            </Btn>
          </div>
        </Card>

        <Card>
          <div className="mb-2 text-sm font-bold">Propose trade</div>
          <div className="space-y-2">
            <Field label="Initiator">
              <ManagerPicker value={trade.initiator} onChange={(v) => setTrade({ ...trade, initiator: v })} allowEmpty emptyLabel="—" />
            </Field>
            <Field label="Counterparty">
              <ManagerPicker value={trade.counterparty} onChange={(v) => setTrade({ ...trade, counterparty: v })} allowEmpty emptyLabel="—" />
            </Field>
            {trade.legs.map((leg, i) => (
              <div key={i} className="rounded-lg border border-pitch-100 p-2 text-xs">
                <div className="mb-1 font-bold">{leg.side} gives:</div>
                {leg.player_id || leg.cash_amount ? (
                  <div className="flex items-center gap-2 font-semibold">
                    {leg._label}
                    <button
                      className="ml-auto text-rose-600"
                      onClick={() => setTrade({ ...trade, legs: trade.legs.filter((_, j) => j !== i) })}
                    >
                      ✕
                    </button>
                  </div>
                ) : (
                  <div className="space-y-1.5">
                    <PlayerSearch
                      placeholder="player…"
                      onPick={(p) =>
                        setTrade({
                          ...trade,
                          legs: trade.legs.map((l, j) =>
                            j === i ? { ...l, player_id: p.id, _label: p.name } : l
                          ),
                        })
                      }
                    />
                    <input
                      className={inputCls}
                      placeholder="…or cash amount (m)"
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && e.target.value) {
                          const v = Number(e.target.value);
                          setTrade({
                            ...trade,
                            legs: trade.legs.map((l, j) =>
                              j === i ? { ...l, cash_amount: v, _label: `${v}m cash` } : l
                            ),
                          });
                        }
                      }}
                    />
                  </div>
                )}
              </div>
            ))}
            <div className="flex gap-2">
              <Btn tone="ghost" onClick={() => addLeg("INITIATOR")}>
                + initiator leg
              </Btn>
              <Btn tone="ghost" onClick={() => addLeg("COUNTERPARTY")}>
                + counterparty leg
              </Btn>
            </div>
            <Btn onClick={doTrade} disabled={!trade.initiator || !trade.counterparty || !trade.legs.length}>
              Propose
            </Btn>
          </div>
          {trades.length > 0 && (
            <div className="mt-3 space-y-1.5 border-t border-pitch-50 pt-2">
              {trades.slice(0, 6).map((t) => (
                <div key={t.id} className="rounded-lg bg-pitch-50/60 px-2.5 py-1.5 text-xs">
                  <span className="font-bold">
                    {t.initiator} ⇄ {t.counterparty}
                  </span>{" "}
                  <span className="pill bg-white">{t.status}</span>
                  <div className="text-slate-500">
                    {t.legs.map((l) => l.player || `${l.cash_amount}m`).join(" · ")}
                  </div>
                  {t.status === "PROPOSED" && (
                    <div className="mt-1 flex gap-1.5">
                      {["accept", "reject", "cancel"].map((a) => (
                        <Btn
                          key={a}
                          tone={a === "accept" ? "primary" : "gray"}
                          onClick={() =>
                            act(() => api.adminTradeAction(t.id, a), `Trade ${a}ed`)()
                          }
                        >
                          {a}
                        </Btn>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </Card>

        <Card>
          <div className="mb-2 text-sm font-bold">Bulk roster import</div>
          <div className="mb-2 text-xs text-slate-500">
            CSV columns: Manager, PlayerID, Via, Price — round-trips with the rosters.csv export.
          </div>
          <DropZone
            hint="Drop rosters.csv (dry-run first)"
            multiple={false}
            accept=".csv"
            onFiles={(f) => doImport(f[0], true)}
          />
          {importReport && (
            <div className="mt-2 text-xs">
              {importReport.errors?.map((e, i) => (
                <div key={i} className="text-rose-600">
                  line {e.line}: {e.error}
                </div>
              ))}
              {importReport.skipped?.slice(0, 5).map((sk, i) => (
                <div key={i} className="text-amber-600">
                  line {sk.line}: player {sk.player_id} skipped ({sk.reason})
                </div>
              ))}
              {importReport.ok && importReport.dry_run && pendingFile && (
                <Btn className="mt-2" onClick={() => doImport(pendingFile, false)}>
                  Commit import ({importReport.would_add})
                </Btn>
              )}
            </div>
          )}
        </Card>
      </div>

      {cup?.enabled && (
        <Card className="mt-5">
          <div className="mb-2 flex items-center justify-between">
            <div className="text-sm font-bold">🏆 League ↔ Cup relationship (第七十七/七十八条)</div>
            <span
              className={`pill ${
                cup.separation_active ? "bg-rose-50 text-rose-700" : "bg-pitch-100 text-pitch-700"
              }`}
            >
              {cup.separation_active
                ? `separated ${cup.separated_at ? new Date(cup.separated_at).toLocaleString() : ""} — games independent`
                : "group stage — one shared roster"}
            </span>
          </div>
          <div className="mb-3 text-xs text-slate-500">
            Cup-only teams: {cup.extra_teams.join(", ") || "—"} · dual teams:{" "}
            {cup.league_teams_in_cup.join(", ") || "—"}. During the cup group stage every
            owned cup-eligible player is implicitly in the cup list and operations affect
            both games. When the first cup knockout gameweek goes LIVE the cup list forks
            and league/cup operations become independent (dual players can stay — and
            start — in both).
          </div>
          <div className="mb-3 flex items-center gap-2">
            {!cup.separation_active && (
              <Btn
                tone="warn"
                onClick={() =>
                  act(() => api.cupSeparate(), "Cup roster forked — games are now independent")()
                }
              >
                Fork now (manual separation)
              </Btn>
            )}
            <span className="pill bg-slate-100 text-slate-600">
              cup list: {cupRoster.length} entries
            </span>
          </div>
          {cupRoster.length > 0 && (
            <div className="flex max-h-40 flex-wrap gap-1.5 overflow-auto">
              {cupRoster.map((e, i) => (
                <span
                  key={i}
                  className={`pill ${
                    e.kind === "CUP_ONLY" ? "bg-violet-50 text-violet-700" : "bg-sky-50 text-sky-700"
                  }`}
                  title={e.kind}
                >
                  {e.manager}: {e.player} ({e.real_team})
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
