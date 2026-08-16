export function PageHeader({ title, subtitle, right }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div>
        <h1 className="text-2xl font-extrabold tracking-tight text-ink-900">{title}</h1>
        {subtitle && <p className="mt-1 text-sm text-pitch-800/70">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

export function Card({ children, className = "" }) {
  return <div className={`card p-5 ${className}`}>{children}</div>;
}

export function PosChip({ pos }) {
  return (
    <span className={`pill pos-${pos}`}>{pos}</span>
  );
}

export function StatPill({ label, value, tone = "pitch" }) {
  const tones = {
    pitch: "bg-pitch-50 text-pitch-800",
    amber: "bg-amber-50 text-amber-700",
    sky: "bg-sky-50 text-sky-700",
    slate: "bg-slate-100 text-slate-700",
  };
  return (
    <div className={`rounded-xl px-4 py-3 ${tones[tone]}`}>
      <div className="text-xs font-semibold uppercase tracking-wide opacity-70">{label}</div>
      <div className="mt-0.5 text-xl font-extrabold">{value}</div>
    </div>
  );
}

export function Loading({ label = "Loading…" }) {
  return (
    <div className="flex items-center gap-3 py-10 text-pitch-700">
      <span className="h-3 w-3 animate-ping rounded-full bg-pitch-500" />
      <span className="text-sm font-medium">{label}</span>
    </div>
  );
}

export function EmptyState({ title, hint }) {
  return (
    <div className="rounded-2xl border border-dashed border-pitch-200 bg-white/60 p-10 text-center">
      <div className="text-base font-semibold text-ink-900">{title}</div>
      {hint && <div className="mt-1 text-sm text-pitch-800/60">{hint}</div>}
    </div>
  );
}

export function ErrorBox({ message }) {
  return (
    <div className="rounded-xl border border-rose-200 bg-rose-50 px-4 py-3 text-sm font-medium text-rose-700">
      {message}
    </div>
  );
}

export function Tabs({ tabs, value, onChange }) {
  return (
    <div className="inline-flex rounded-xl bg-pitch-50 p-1">
      {tabs.map((t) => (
        <button
          key={t.value}
          onClick={() => onChange(t.value)}
          className={`rounded-lg px-4 py-2 text-sm font-semibold transition ${
            value === t.value
              ? "bg-white text-pitch-800 shadow-card"
              : "text-pitch-700/70 hover:text-pitch-800"
          }`}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

export function StatusBadge({ status }) {
  const map = {
    LIVE: "bg-rose-100 text-rose-700",
    FINALIZED: "bg-pitch-100 text-pitch-700",
    PENDING: "bg-slate-100 text-slate-600",
    OPEN: "bg-pitch-100 text-pitch-700",
    CLOSED: "bg-slate-100 text-slate-600",
  };
  return (
    <span className={`pill ${map[status] || "bg-slate-100 text-slate-600"}`}>
      {status === "LIVE" && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-rose-500" />}
      {status}
    </span>
  );
}
