// Hand-drawn spec icons. Each icon pairs a neutral outline with a colored
// "highlight" element that signals what the metric represents:
//   battery -> charge bolt (emerald), motor -> power bolt in the hub (amber),
//   weight  -> load band (violet),    range -> route to a destination pin (sky),
//   torque  -> rotation arrow around a nut (rose).

interface IconProps {
  className?: string;
}

function Svg({ className = "h-4 w-4", children }: IconProps & { children: React.ReactNode }) {
  return (
    <svg viewBox="0 0 24 24" fill="none" className={className} aria-hidden="true">
      {children}
    </svg>
  );
}

const base = {
  stroke: "currentColor",
  strokeWidth: 1.7,
  strokeLinecap: "round" as const,
  strokeLinejoin: "round" as const,
};

export function BatteryIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-slate-400" {...base}>
        <rect x="2" y="7.5" width="17" height="9" rx="2" />
        <path d="M21.7 10.7v2.6" strokeWidth={2.4} />
      </g>
      {/* highlight: charge bolt */}
      <path
        className="text-emerald-500"
        fill="currentColor"
        d="M11.6 8.6 8.2 12.7h2.5l-1.3 2.7 3.9-4.3h-2.5l0.8-2.5Z"
      />
    </Svg>
  );
}

export function MotorIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-slate-400" {...base}>
        <circle cx="12" cy="12" r="8" />
        <path d="M12 4v1.6M12 18.4V20M4 12h1.6M18.4 12H20" strokeWidth={1.4} />
      </g>
      {/* highlight: power bolt in the hub */}
      <path
        className="text-amber-500"
        fill="currentColor"
        d="M13 7.4 9.4 12.4h2.4l-1.2 4.2 3.9-5.4h-2.4l0.9-3.8Z"
      />
    </Svg>
  );
}

export function WeightIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-slate-400" {...base}>
        <path d="M9 7.5a3 3 0 0 1 6 0" />
        <path d="M6.8 7.5h10.4l1.7 9.4a1.6 1.6 0 0 1-1.6 1.9H6.7a1.6 1.6 0 0 1-1.6-1.9l1.7-9.4Z" />
      </g>
      {/* highlight: load band */}
      <path className="text-violet-500" {...base} stroke="currentColor" strokeWidth={2} d="M6.2 13.4h11.6" />
    </Svg>
  );
}

export function RangeIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      {/* highlight: the route itself */}
      <path
        className="text-sky-500"
        {...base}
        strokeDasharray="2.6 2.4"
        d="M4 19c4.4 0 3.4-5 7.2-5.4 2.6-.3 3.6-1 4.6-2.4"
      />
      <circle className="text-slate-400" cx="4" cy="19" r="1.5" fill="currentColor" />
      <g className="text-slate-400" {...base}>
        <path d="M17.3 3.6a3.4 3.4 0 0 1 3.4 3.4c0 2.5-3.4 5.6-3.4 5.6s-3.4-3.1-3.4-5.6a3.4 3.4 0 0 1 3.4-3.4Z" />
      </g>
      <circle className="text-sky-500" cx="17.3" cy="7" r="1.4" fill="currentColor" />
    </Svg>
  );
}

export function TorqueIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      {/* nut */}
      <path
        className="text-slate-400"
        {...base}
        d="M12 8.8l2.8 1.6v3.2L12 15.2l-2.8-1.6v-3.2L12 8.8Z"
      />
      {/* highlight: rotation arrow */}
      <g className="text-rose-500" {...base}>
        <path d="M18.9 9.1A7.4 7.4 0 1 0 19.4 13" />
        <path d="M19.4 13l2-2.4M19.4 13l-2.9-.9" />
      </g>
    </Svg>
  );
}

export function GearsIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-slate-400" {...base}>
        <circle cx="9" cy="12" r="5.5" />
        <circle cx="17.5" cy="12" r="3" />
      </g>
      <circle className="text-slate-500" cx="9" cy="12" r="1.4" fill="currentColor" />
    </Svg>
  );
}
