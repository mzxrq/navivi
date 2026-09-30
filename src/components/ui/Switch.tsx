interface SwitchProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}

/** Small on/off switch. `label` is the accessible name. */
export function Switch({ checked, onChange, label, disabled }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={(e) => {
        e.stopPropagation();
        onChange(!checked);
      }}
      className={`relative w-7 h-4 rounded-full shrink-0 transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-navi/40 disabled:opacity-40 disabled:cursor-not-allowed ${
        checked ? "bg-navi" : "bg-zinc-300 dark:bg-zinc-700"
      }`}
    >
      <span
        className={`absolute top-0.5 left-0.5 w-3 h-3 rounded-full bg-white shadow-sm transition-transform ${
          checked ? "translate-x-3" : ""
        }`}
      />
    </button>
  );
}
