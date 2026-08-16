import { useEffect, useRef, useState } from "react";
import { api } from "../api.js";

// ---------------------------------------------------------------------------
// Small shared building blocks for the admin + input pages
// ---------------------------------------------------------------------------

export function Btn({ children, tone = "primary", className = "", ...props }) {
  const tones = {
    primary: "bg-pitch-600 text-white hover:bg-pitch-700",
    ghost: "bg-pitch-50 text-pitch-800 hover:bg-pitch-100",
    gray: "bg-slate-100 text-slate-700 hover:bg-slate-200",
    danger: "bg-rose-50 text-rose-700 hover:bg-rose-100",
    warn: "bg-amber-50 text-amber-700 hover:bg-amber-100",
  };
  return (
    <button
      className={`rounded-lg px-3 py-1.5 text-sm font-semibold transition disabled:cursor-not-allowed disabled:opacity-40 ${tones[tone]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}

export function Field({ label, children }) {
  return (
    <label className="block text-sm">
      <span className="mb-1 block text-xs font-semibold uppercase tracking-wide text-pitch-800/60">
        {label}
      </span>
      {children}
    </label>
  );
}

export const inputCls =
  "w-full rounded-lg border border-pitch-100 bg-white px-3 py-2 text-sm outline-none focus:border-pitch-400";

export function Toast({ toast }) {
  if (!toast) return null;
  return (
    <div
      className={`fixed bottom-6 left-1/2 z-50 -translate-x-1/2 rounded-xl px-5 py-2.5 text-sm font-semibold text-white shadow-lg ${
        toast.tone === "error" ? "bg-rose-600" : "bg-ink-900 bg-slate-900"
      }`}
    >
      {toast.msg}
    </div>
  );
}

export function useToast() {
  const [toast, setToast] = useState(null);
  const timer = useRef(null);
  const show = (msg, tone = "ok") => {
    clearTimeout(timer.current);
    setToast({ msg: String(msg), tone });
    timer.current = setTimeout(() => setToast(null), 3500);
  };
  return [toast, show];
}

// ---------------------------------------------------------------------------
// Manager picker (dropdown fed by /api/managers)
// ---------------------------------------------------------------------------

export function ManagerPicker({ value, onChange, allowEmpty = false, emptyLabel = "All managers" }) {
  const [managers, setManagers] = useState([]);
  useEffect(() => {
    api.managers().then((r) => setManagers(r.managers || [])).catch(() => {});
  }, []);
  return (
    <select
      className={inputCls}
      value={value ?? ""}
      onChange={(e) => onChange(e.target.value ? Number(e.target.value) : null)}
    >
      {allowEmpty && <option value="">{emptyLabel}</option>}
      {managers.map((m) => (
        <option key={m.id} value={m.id}>
          {m.name} ({m.balance}m · {m.roster_size} players)
        </option>
      ))}
    </select>
  );
}

// ---------------------------------------------------------------------------
// Player typeahead (same lookup as the free-sign page)
// ---------------------------------------------------------------------------

export function PlayerSearch({ onPick, placeholder = "Search player by name or ID…" }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState([]);
  const [open, setOpen] = useState(false);
  const box = useRef(null);

  useEffect(() => {
    if (!q.trim()) {
      setHits([]);
      return;
    }
    const t = setTimeout(() => {
      api
        .playerSearch(q.trim())
        .then((r) => {
          setHits(r.players || []);
          setOpen(true);
        })
        .catch(() => setHits([]));
    }, 200);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    const close = (e) => {
      if (box.current && !box.current.contains(e.target)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  return (
    <div className="relative" ref={box}>
      <input
        className={inputCls}
        value={q}
        placeholder={placeholder}
        onChange={(e) => setQ(e.target.value)}
        onFocus={() => hits.length && setOpen(true)}
      />
      {open && hits.length > 0 && (
        <div className="absolute z-30 mt-1 max-h-64 w-full overflow-auto rounded-xl border border-pitch-100 bg-white shadow-lg">
          {hits.map((p) => (
            <button
              key={p.id}
              className="flex w-full items-center justify-between px-3 py-2 text-left text-sm hover:bg-pitch-50"
              onClick={() => {
                onPick(p);
                setQ("");
                setOpen(false);
              }}
            >
              <span>
                <span className="font-semibold">{p.name}</span>{" "}
                <span className="text-xs text-slate-500">
                  #{p.id} · {p.position} · {p.real_team}
                </span>
              </span>
              <span
                className={`pill ${
                  p.free_agent ? "bg-pitch-100 text-pitch-700" : "bg-slate-100 text-slate-500"
                }`}
              >
                {p.free_agent ? "free" : p.owner || "owned"}
              </span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// File drop zone
// ---------------------------------------------------------------------------

export function DropZone({ onFiles, hint, multiple = true, accept }) {
  const [drag, setDrag] = useState(false);
  const input = useRef(null);
  return (
    <div
      className={`cursor-pointer rounded-2xl border-2 border-dashed p-8 text-center text-sm font-semibold transition ${
        drag ? "border-pitch-500 bg-pitch-100" : "border-pitch-200 bg-pitch-50 text-pitch-800"
      }`}
      onClick={() => input.current?.click()}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        onFiles([...e.dataTransfer.files]);
      }}
    >
      ⬆ {hint || "Drop files here or click to browse"}
      <input
        ref={input}
        type="file"
        multiple={multiple}
        accept={accept}
        className="hidden"
        onChange={(e) => {
          onFiles([...e.target.files]);
          e.target.value = "";
        }}
      />
    </div>
  );
}
