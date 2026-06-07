interface Props {
  value: string;
  onChange: (v: string) => void;
  placeholder?: string;
}

export function SearchBar({ value, onChange, placeholder }: Props) {
  return (
    <div className="relative">
      <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-slate-400">⌕</span>
      <input
        type="search"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder ?? "Search e-bikes (model, brand, tech)…"}
        className="w-full rounded-lg border-slate-300 pl-9 text-sm shadow-sm focus:border-brand-500 focus:ring-brand-500"
      />
    </div>
  );
}
