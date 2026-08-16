import React, { useState } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, NavLink, Navigate, Route, Routes } from "react-router-dom";
import "./index.css";

import { getAdminToken, setAdminToken, isAdmin } from "./api.js";

import Scores from "./pages/Scores.jsx";
import Standings from "./pages/Standings.jsx";
import Players from "./pages/Players.jsx";
import Bids from "./pages/Bids.jsx";
import FreeSign from "./pages/FreeSign.jsx";
import Lineups from "./pages/Lineups.jsx";
import Exports from "./pages/admin/Exports.jsx";
import AuctionDesk from "./pages/admin/AuctionDesk.jsx";
import Events from "./pages/admin/Events.jsx";
import Gameweeks from "./pages/admin/Gameweeks.jsx";
import Roster from "./pages/admin/Roster.jsx";

const NAV = [
  { to: "/scores", label: "Live Scores", icon: "⚽" },
  { to: "/standings", label: "Standings", icon: "🏆" },
  { to: "/players", label: "Players", icon: "📊" },
  { to: "/bids", label: "Bids", icon: "📝" },
  { to: "/free-sign", label: "Free Signings", icon: "✍️" },
  { to: "/lineups", label: "Lineups", icon: "📋" },
];

const ADMIN_NAV = [
  { to: "/admin/auction", label: "Auction Desk", icon: "🔨" },
  { to: "/admin/events", label: "Events", icon: "⚡" },
  { to: "/admin/gameweeks", label: "Gameweeks", icon: "📅" },
  { to: "/admin/roster", label: "Roster", icon: "👥" },
  { to: "/admin/exports", label: "Exports", icon: "📦" },
];

function AdminGate({ children }) {
  if (!isAdmin()) {
    return (
      <div className="rounded-2xl border border-dashed border-pitch-200 bg-white/60 p-10 text-center">
        <div className="text-base font-semibold text-ink-900">Admin token required</div>
        <div className="mt-1 text-sm text-pitch-800/60">
          Click the 🔑 in the header and enter the admin token (dev default:{" "}
          <code className="rounded bg-pitch-50 px-1">fmlwc-admin</code>).
        </div>
      </div>
    );
  }
  return children;
}

function navBtnClass({ isActive }) {
  return `rounded-xl px-3 py-2 text-sm font-semibold transition ${
    isActive ? "bg-pitch-600 text-white shadow-card" : "text-pitch-800/80 hover:bg-pitch-50"
  }`;
}

function Shell() {
  const [admin, setAdmin] = useState(isAdmin());

  const toggleAdmin = () => {
    if (admin) {
      if (confirm("Sign out of admin mode?")) {
        setAdminToken("");
        setAdmin(false);
      }
      return;
    }
    const t = prompt("Admin token:", getAdminToken());
    if (t) {
      setAdminToken(t.trim());
      setAdmin(true);
    }
  };

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-pitch-100 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div className="flex items-center gap-2.5">
            <div className="grid h-9 w-9 place-items-center rounded-xl bg-gradient-to-br from-pitch-400 to-pitch-600 text-lg shadow-card">
              ⚽
            </div>
            <div>
              <div className="text-base font-extrabold leading-none tracking-tight text-ink-900">
                FMLWC
              </div>
              <div className="text-[11px] font-medium text-pitch-700/70">Fantasy Hub</div>
            </div>
          </div>
          <nav className="flex flex-wrap items-center gap-1">
            {NAV.map((n) => (
              <NavLink key={n.to} to={n.to} className={navBtnClass}>
                <span className="mr-1.5">{n.icon}</span>
                {n.label}
              </NavLink>
            ))}
            {admin && (
              <>
                <span className="mx-1 h-6 w-px bg-pitch-100" />
                {ADMIN_NAV.map((n) => (
                  <NavLink key={n.to} to={n.to} className={navBtnClass}>
                    <span className="mr-1.5">{n.icon}</span>
                    {n.label}
                  </NavLink>
                ))}
              </>
            )}
            <button
              onClick={toggleAdmin}
              title={admin ? "Admin mode on — click to sign out" : "Enter admin token"}
              className={`ml-1 rounded-xl px-3 py-2 text-sm font-semibold transition ${
                admin ? "bg-amber-100 text-amber-800" : "text-pitch-800/50 hover:bg-pitch-50"
              }`}
            >
              🔑{admin ? " Admin" : ""}
            </button>
          </nav>
        </div>
      </header>

      <main className="mx-auto max-w-6xl px-4 py-8">
        <Routes>
          <Route path="/" element={<Navigate to="/scores" replace />} />
          <Route path="/scores" element={<Scores />} />
          <Route path="/standings" element={<Standings />} />
          <Route path="/players" element={<Players />} />
          <Route path="/bids" element={<Bids />} />
          <Route path="/free-sign" element={<FreeSign />} />
          <Route path="/lineups" element={<Lineups />} />
          <Route path="/admin/exports" element={<AdminGate><Exports /></AdminGate>} />
          <Route path="/admin/auction" element={<AdminGate><AuctionDesk /></AdminGate>} />
          <Route path="/admin/events" element={<AdminGate><Events /></AdminGate>} />
          <Route path="/admin/gameweeks" element={<AdminGate><Gameweeks /></AdminGate>} />
          <Route path="/admin/roster" element={<AdminGate><Roster /></AdminGate>} />
          <Route path="*" element={<Navigate to="/scores" replace />} />
        </Routes>
      </main>

      <footer className="mx-auto max-w-6xl px-4 pb-10 pt-2 text-center text-xs text-pitch-800/50">
        FMLWC · rule-configurable fantasy football engine
      </footer>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <BrowserRouter>
      <Shell />
    </BrowserRouter>
  </React.StrictMode>
);
