import { useEffect, useState } from "react";
import { api, download } from "../../api.js";
import { Card, PageHeader, Loading } from "../../components/ui.jsx";
import { Btn, Toast, useToast, inputCls } from "../../components/admin.jsx";

const CARDS = (m) => [
  {
    title: "Player list",
    desc: "ID / Name / Nation / Pos / Team / Price — PlayerListExporter format",
    count: `${m.counts?.players ?? 0} players`,
    formats: [
      ["xlsx", "/api/export/players.xlsx"],
      ["csv", "/api/export/players.csv"],
    ],
  },
  {
    title: "Bid templates",
    desc: "FME_<year>_Bid<N>_<CODE>.xlsx per manager (free agents only)",
    count: `${m.counts?.managers ?? 0} managers`,
    needsRound: true,
    formats: [["zip (all)", "/api/export/bid-template?round={round}"]],
  },
  {
    title: "Auction announcement 暗标公示",
    desc: "AuctionAnnouncementFormatter — public sealed-bid disclosure",
    count: `${(m.auction_rounds || []).length} rounds`,
    needsRound: true,
    formats: [["txt", "/api/export/auction/{round}/announcement.txt"]],
  },
  {
    title: "Auction results",
    desc: "Winner + price per player for one round",
    count: `${m.counts?.auction_results ?? 0} awards total`,
    needsRound: true,
    formats: [
      ["csv", "/api/export/auction/{round}/results.csv"],
      ["xlsx", "/api/export/auction/{round}/results.xlsx"],
    ],
  },
  {
    title: "Rosters",
    desc: "All entries incl. acquired via / price / timestamps",
    count: `${m.counts?.roster_entries ?? 0} entries`,
    formats: [
      ["xlsx", "/api/export/rosters.xlsx?include_released=true"],
      ["csv", "/api/export/rosters.csv?include_released=true"],
    ],
  },
  {
    title: "Roster snapshots",
    desc: "Knockout-phase frozen rosters",
    count: `${m.counts?.roster_snapshots ?? 0} snapshots`,
    formats: [["json", "/api/export/roster-snapshots.json"]],
  },
  {
    title: "Lineups",
    desc: "Per gameweek, one row per starter (slot + PK order)",
    count: `${m.counts?.lineups ?? 0} lineups`,
    formats: [["csv", "/api/export/lineups.csv"]],
  },
  {
    title: "Match events",
    desc: "Round-trips with the bulk event importer",
    count: `${m.counts?.events ?? 0} events`,
    formats: [["csv", "/api/export/events.csv"]],
  },
  {
    title: "Standings + results",
    desc: "League, per-group sheets, full results log",
    count: `${m.counts?.results ?? 0} results`,
    formats: [
      ["xlsx", "/api/export/standings.xlsx"],
      ["csv", "/api/export/standings.csv"],
    ],
  },
  {
    title: "Athletics",
    desc: "Players / Managers / Per-pair breakdowns (3 sheets)",
    count: "3 tables",
    formats: [["xlsx", "/api/export/athletics.xlsx"]],
  },
  {
    title: "Transfer ledger",
    desc: "Free signs · trades · releases · dismissals (4 sheets)",
    count: `${(m.counts?.free_signs ?? 0) + (m.counts?.trades ?? 0) + (m.counts?.releases ?? 0) + (m.counts?.dismissals ?? 0)} rows`,
    formats: [["xlsx", "/api/export/transfers.xlsx"]],
  },
  {
    title: "Prize / bonus ledger",
    desc: "BonusAward rows",
    count: `${m.counts?.bonus_awards ?? 0} awards`,
    formats: [["csv", "/api/export/prizes.csv"]],
  },
  {
    title: "Full season archive",
    desc: "Everything above in one zip",
    count: "—",
    formats: [["zip", "/api/export/season.zip"]],
  },
];

export default function Exports() {
  const [manifest, setManifest] = useState(null);
  const [err, setErr] = useState(null);
  const [round, setRound] = useState(1);
  const [busy, setBusy] = useState("");
  const [toast, show] = useToast();

  useEffect(() => {
    api
      .exportManifest()
      .then((m) => {
        setManifest(m);
        if (m.auction_rounds?.length) setRound(m.auction_rounds[m.auction_rounds.length - 1]);
      })
      .catch((e) => setErr(e.message));
  }, []);

  if (err)
    return (
      <div>
        <PageHeader title="Export Center" />
        <Card>Failed to load manifest: {err}</Card>
      </div>
    );
  if (!manifest) return <Loading label="Loading export manifest…" />;

  const dl = async (path) => {
    const real = path.replace("{round}", round);
    setBusy(real);
    try {
      const name = await download(real);
      show(`Downloaded ${name}`);
    } catch (e) {
      show(e.message, "error");
    } finally {
      setBusy("");
    }
  };

  return (
    <div>
      <PageHeader
        title="Export Center"
        subtitle={`Every artefact as a file — generated ${new Date(
          manifest.generated_at
        ).toLocaleString()}`}
        right={
          <label className="flex items-center gap-2 text-sm font-semibold text-pitch-800">
            Auction round
            <select
              className={inputCls + " w-24"}
              value={round}
              onChange={(e) => setRound(Number(e.target.value))}
            >
              {(manifest.auction_rounds?.length ? manifest.auction_rounds : [1]).map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </label>
        }
      />
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {CARDS(manifest).map((c) => (
          <Card key={c.title}>
            <div className="text-sm font-bold text-ink-900">{c.title}</div>
            <div className="mt-0.5 text-xs text-pitch-800/60">{c.desc}</div>
            <div className="mt-3 flex items-center justify-between gap-2">
              <span className="pill bg-slate-100 text-slate-600">{c.count}</span>
              <div className="flex gap-1.5">
                {c.formats.map(([label, path], i) => (
                  <Btn
                    key={label}
                    tone={i === 0 ? "primary" : "ghost"}
                    disabled={busy === path.replace("{round}", round)}
                    onClick={() => dl(path)}
                  >
                    {busy === path.replace("{round}", round) ? "…" : `⬇ ${label}`}
                  </Btn>
                ))}
              </div>
            </div>
          </Card>
        ))}
      </div>
      <Toast toast={toast} />
    </div>
  );
}
