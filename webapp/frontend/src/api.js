// Tiny fetch wrapper. In dev, Vite proxies /api -> http://localhost:8000.
const BASE = import.meta.env.VITE_API_BASE || "";

// ---------------------------------------------------------------------------
// Admin token (kept in localStorage; sent as X-Admin-Token on every request)
// ---------------------------------------------------------------------------

const TOKEN_KEY = "fmlwc_admin_token";
export const getAdminToken = () => localStorage.getItem(TOKEN_KEY) || "";
export const setAdminToken = (t) => {
  if (t) localStorage.setItem(TOKEN_KEY, t);
  else localStorage.removeItem(TOKEN_KEY);
};
export const isAdmin = () => !!getAdminToken();

function authHeaders(extra = {}) {
  const t = getAdminToken();
  return t ? { ...extra, "X-Admin-Token": t } : extra;
}

async function http(path, opts = {}) {
  const res = await fetch(BASE + path, {
    ...opts,
    headers: authHeaders(opts.headers || {}),
  });
  let body = null;
  try {
    body = await res.json();
  } catch {
    body = null;
  }
  if (!res.ok) {
    const msg = (body && (body.detail || body.error)) || `Request failed (${res.status})`;
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  return body;
}

const json = (method) => (path, payload) =>
  http(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
const post = json("POST");
const put = json("PUT");

function formUpload(path, files, fieldName = "file") {
  const fd = new FormData();
  const list = Array.isArray(files) ? files : [files];
  for (const f of list) fd.append(fieldName, f);
  return http(path, { method: "POST", body: fd });
}

// Download a file endpoint (auth header included) and trigger a save dialog.
export async function download(path) {
  const res = await fetch(BASE + path, { headers: authHeaders() });
  if (!res.ok) {
    let msg = `Download failed (${res.status})`;
    try {
      const body = await res.json();
      msg = body.detail || body.error || msg;
    } catch { /* binary */ }
    throw new Error(msg);
  }
  const dispo = res.headers.get("Content-Disposition") || "";
  const m = dispo.match(/filename="?([^";]+)"?/);
  const filename = m ? m[1] : path.split("/").pop().split("?")[0];
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
  return filename;
}

export const api = {
  time: () => http("/api/time"),
  overview: () => http("/api/overview"),
  managers: () => http("/api/managers"),

  standingsLeague: () => http("/api/standings/league"),
  standingsGroups: () => http("/api/standings/groups"),
  standingsTournament: () => http("/api/standings/tournament"),

  gameweeks: () => http("/api/scores/gameweeks"),
  scores: (status = "all", gameweek) =>
    http(`/api/scores?status=${status}${gameweek ? `&gameweek=${gameweek}` : ""}`),

  players: ({ q = "", position = "", sort = "goals", limit = 100, offset = 0 } = {}) => {
    const p = new URLSearchParams({ sort, limit, offset });
    if (q) p.set("q", q);
    if (position) p.set("position", position);
    return http(`/api/players?${p.toString()}`);
  },
  playerSearch: (q) => http(`/api/players/search?q=${encodeURIComponent(q)}`),

  auctionResults: (roundIndex) =>
    http(`/api/auction/results${roundIndex ? `?round_index=${roundIndex}` : ""}`),

  uploadBids: (file) => formUpload("/api/bids/upload", file),

  transferWindows: () => http("/api/transfer/windows"),
  freeSign: (manager_id, player_id) => post("/api/free-sign", { manager_id, player_id }),
  freeSignList: () => http("/api/free-sign/list"),
  freeSignRevoke: (id) => http(`/api/free-sign/${id}/revoke`, { method: "POST" }),
  freeSignCommitDue: () => http("/api/free-sign/commit-due", { method: "POST" }),

  // -- releases (rule 八: pending → revoke window → effective) -------------
  releasePropose: (manager_id, player_id) =>
    post("/api/releases", { manager_id, player_id }),
  releaseRevoke: (id) => http(`/api/releases/${id}/revoke`, { method: "POST" }),
  releaseCommitDue: () => http("/api/releases/commit-due", { method: "POST" }),
  releaseList: () => http("/api/releases/list"),

  // -- cup (dual-competition mode, fork model per 第七十七/七十八条) ----------
  cupStatus: () => http("/api/cup/status"),
  cupRoster: (managerId) =>
    http(`/api/cup/roster${managerId ? `?manager_id=${managerId}` : ""}`),
  cupSeparate: () => http("/api/cup/separate", { method: "POST" }),

  // -- lineup rules (positions, caps, group caps — nothing hardcoded) --------
  lineupConstraints: () => http("/api/lineups/constraints"),
  standingsReserve: () => http("/api/standings/reserve"),

  // -- exports (GET file downloads) ---------------------------------------
  exportManifest: () => http("/api/export/manifest"),
  download, // download("/api/export/players.xlsx") etc.

  // -- lineups --------------------------------------------------------------
  lineups: (gameweek) =>
    http(`/api/lineups${gameweek ? `?gameweek=${gameweek}` : ""}`),
  lineupValidate: (payload) => post("/api/lineups/validate", payload),
  lineupSubmit: (gameweekIndex, managerId, payload) =>
    put(`/api/lineups/${gameweekIndex}/${managerId}`, payload),

  // -- admin: auction desk ----------------------------------------------------
  adminRounds: () => http("/api/admin/auction/rounds"),
  adminRoundCreate: (payload) => post("/api/admin/auction/rounds", payload),
  adminRoundUpload: (roundId, files) =>
    formUpload(`/api/admin/auction/rounds/${roundId}/submissions`, files, "files"),
  adminRoundBids: (roundId) => http(`/api/admin/auction/rounds/${roundId}/bids`),
  adminRoundResolve: (roundId, dryRun) =>
    http(`/api/admin/auction/rounds/${roundId}/resolve?dry_run=${dryRun}`, { method: "POST" }),

  // -- admin: events ----------------------------------------------------------
  adminEvents: (gameweek) => http(`/api/admin/events?gameweek=${gameweek}`),
  adminEventAdd: (payload) => post("/api/admin/events", payload),
  adminEventDelete: (id) => http(`/api/admin/events/${id}`, { method: "DELETE" }),
  adminEventsImport: (file, dryRun) =>
    formUpload(`/api/admin/events/import?dry_run=${dryRun}`, file),
  adminTally: (gameweek) => http(`/api/admin/events/tally?gameweek=${gameweek}`),

  // -- admin: gameweeks ---------------------------------------------------------
  adminGameweeks: () => http("/api/admin/gameweeks"),
  adminGameweekCreate: (payload) => post("/api/admin/gameweeks", payload),
  adminFixtureCreate: (gwId, payload) => post(`/api/admin/gameweeks/${gwId}/fixtures`, payload),
  adminGameweekLive: (gwId) => http(`/api/admin/gameweeks/${gwId}/live`, { method: "POST" }),
  adminGameweekFinalize: (gwId, dryRun) =>
    http(`/api/admin/gameweeks/${gwId}/finalize?dry_run=${dryRun}`, { method: "POST" }),
  adminPkWinner: (gwId, payload) => post(`/api/admin/gameweeks/${gwId}/pk-winner`, payload),

  // -- admin: roster + transfers -----------------------------------------------
  adminRoster: ({ managerId, includeReleased = false } = {}) => {
    const p = new URLSearchParams();
    if (managerId) p.set("manager_id", managerId);
    if (includeReleased) p.set("include_released", "true");
    return http(`/api/admin/roster?${p.toString()}`);
  },
  adminRosterAdd: (payload) => post("/api/admin/roster", payload),
  adminRosterRelease: (payload) => post("/api/admin/roster/release", payload),
  adminRosterImport: (file, dryRun) =>
    formUpload(`/api/admin/roster/import?dry_run=${dryRun}`, file),
  adminDismiss: (payload) => post("/api/admin/dismissals", payload),
  adminInjury: (payload) => post("/api/admin/injuries", payload),
  adminTrades: () => http("/api/admin/trades"),
  adminTradeCreate: (payload) => post("/api/admin/trades", payload),
  adminTradeAction: (id, action) =>
    http(`/api/admin/trades/${id}/${action}`, { method: "POST" }),
  adminPick: (payload) => post("/api/admin/picks", payload),
  adminManagerCreate: (payload) => post("/api/admin/managers", payload),
  adminManagerUpdate: (id, payload) => put(`/api/admin/managers/${id}`, payload),
  adminWindowCreate: (payload) => post("/api/admin/windows", payload),
  adminPlayersImport: (file, dryRun) =>
    formUpload(`/api/admin/players/import?dry_run=${dryRun}`, file),
};
