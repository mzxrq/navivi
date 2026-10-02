import { Check } from "./icons";

interface CheckboxProps {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  disabled?: boolean;
}

// The native input stays on top (invisible) so clicks, labels, Space and focus all behave as usual; the box is drawn under it.
export function Checkbox({ checked, onChange, label, disabled }: CheckboxProps) {
  return (
    <span className="relative inline-flex w-4 h-4 shrink-0">
      <input
        type="checkbox"
        aria-label={label}
        checked={checked}
        disabled={disabled}
        onChange={(e) => onChange(e.target.checked)}
        className="peer absolute inset-0 m-0 w-full h-full opacity-0 cursor-pointer disabled:cursor-default"
      />
      <span
        aria-hidden
        className={`pointer-events-none flex items-center justify-center w-4 h-4 rounded-[5px] border transition-colors peer-focus-visible:ring-2 peer-focus-visible:ring-navi/40 peer-disabled:opacity-50 ${
          checked
            ? "bg-navi border-navi text-white"
            : "bg-white dark:bg-zinc-950/40 border-zinc-300 dark:border-white/20 peer-hover:border-zinc-400 dark:peer-hover:border-white/40"
        }`}
      >
        {checked && <Check className="w-3 h-3" strokeWidth={3} />}
      </span>
    </span>
  );
}
