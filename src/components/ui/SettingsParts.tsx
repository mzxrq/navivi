export const inputClass =
  "h-8 min-w-0 px-2.5 rounded-lg bg-white dark:bg-zinc-950/40 border border-zinc-200 dark:border-white/10 text-[13px] text-zinc-900 dark:text-zinc-100 placeholder:text-zinc-400 outline-none focus:border-navi focus:ring-2 focus:ring-navi/20 transition";
export const selectClass = `${inputClass} pr-7 cursor-pointer`;
export const secondaryButton =
  "inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-lg border border-zinc-200 dark:border-white/10 bg-white dark:bg-white/5 text-[12px] font-medium text-zinc-700 dark:text-zinc-200 hover:bg-zinc-50 dark:hover:bg-white/10 disabled:opacity-40 disabled:pointer-events-none transition-colors";
export const primaryButton =
  "inline-flex items-center justify-center gap-1.5 h-8 px-3 rounded-lg bg-navi text-white text-[12px] font-semibold hover:brightness-110 disabled:opacity-40 disabled:pointer-events-none transition";

export function Section({
  title,
  hint,
  children,
}: {
  title: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <section>
      <div className="flex items-baseline justify-between mb-2 px-0.5">
        <h4 className="text-[12px] font-semibold text-zinc-500 dark:text-zinc-400">
          {title}
        </h4>
        {hint && (
          <span className="text-[11px] text-zinc-400 dark:text-zinc-500">
            {hint}
          </span>
        )}
      </div>
      <div className="rounded-xl border border-zinc-200 dark:border-white/10 divide-y divide-zinc-100 dark:divide-white/5">
        {children}
      </div>
    </section>
  );
}

export function Row({
  title,
  description,
  badge,
  stacked,
  children,
}: {
  title: string;
  description?: string;
  badge?: React.ReactNode;
  stacked?: boolean;
  children: React.ReactNode;
}) {
  const text = (
    <div className="min-w-0">
      <div className="flex items-center gap-2">
        <span className="text-[13px] font-medium text-zinc-900 dark:text-zinc-100">
          {title}
        </span>
        {badge}
      </div>
      {description && (
        <p className="mt-0.5 text-[12px] leading-relaxed text-zinc-500 dark:text-zinc-400">
          {description}
        </p>
      )}
    </div>
  );
  if (stacked) {
    return (
      <div className="px-4 py-3 space-y-2.5">
        {text}
        {children}
      </div>
    );
  }
  return (
    <div className="flex items-center justify-between gap-6 px-4 py-3">
      {text}
      <div className="shrink-0">{children}</div>
    </div>
  );
}
