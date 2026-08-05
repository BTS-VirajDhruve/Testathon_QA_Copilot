"use client";

export function PageHeader({
  title,
  subtitle,
  meta,
  actions,
}: {
  title: string;
  subtitle?: string;
  meta?: string;
  actions?: React.ReactNode;
}) {
  return (
    <header className="panel flex flex-wrap items-start justify-between gap-3 px-5 py-4">
      <div className="min-w-0">
        <h1 className="font-display text-2xl tracking-tight text-ink-900">{title}</h1>
        {subtitle ? <p className="mt-1 text-sm text-ink-700/80">{subtitle}</p> : null}
        {meta ? <p className="mt-1 text-xs text-ink-600/65">{meta}</p> : null}
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </header>
  );
}
