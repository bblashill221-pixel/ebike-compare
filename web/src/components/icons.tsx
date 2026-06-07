// Hand-drawn spec icons, fully colored per metric:
//   battery -> 3/4-charged cells (emerald), motor -> electric motor w/ power bolt
//   (amber), weight -> dumbbell (violet), range -> route to a destination pin (sky),
//   torque -> cyclist climbing a steep hill (rose), gears -> tooth ring (indigo).

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
      <g className="text-emerald-600" {...base}>
        <rect x="2" y="7" width="17" height="10" rx="2" />
        <path d="M21.7 10.6v2.8" strokeWidth={2.4} />
      </g>
      {/* highlight: 3 of 4 cells charged */}
      <g className="text-emerald-500" fill="currentColor">
        <rect x="4.1" y="9.1" width="2.7" height="5.8" rx="0.6" />
        <rect x="7.5" y="9.1" width="2.7" height="5.8" rx="0.6" />
        <rect x="10.9" y="9.1" width="2.7" height="5.8" rx="0.6" />
      </g>
      {/* empty fourth cell */}
      <rect
        className="text-emerald-300"
        x="14.5"
        y="9.3"
        width="2.3"
        height="5.4"
        rx="0.5"
        stroke="currentColor"
        strokeWidth="1"
      />
    </Svg>
  );
}

export function MotorIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-amber-600" {...base}>
        {/* finned motor housing */}
        <rect x="3" y="8" width="12.5" height="8" rx="1.8" />
        <path d="M6 9.9v4.2M12.6 9.9v4.2" strokeWidth={1.3} />
        {/* drive shaft */}
        <path d="M15.5 12h4.3" strokeWidth={2.2} />
        {/* mounting feet */}
        <path d="M5.6 16l-1.3 2.2M13 16l1.3 2.2" strokeWidth={1.4} />
      </g>
      {/* highlight: power bolt on the housing */}
      <path
        className="text-amber-500"
        fill="currentColor"
        d="M10.1 9.4 7.8 12.4h1.7l-0.9 2.3 2.7-3.1H9.6l0.5-2.2Z"
      />
    </Svg>
  );
}

export function WeightIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      {/* bar */}
      <path className="text-violet-600" {...base} d="M8.6 12h6.8" strokeWidth={1.9} />
      {/* outer plates */}
      <g className="text-violet-400" {...base} strokeWidth={1.5}>
        <rect x="3.9" y="10" width="1.9" height="4" rx="0.6" />
        <rect x="18.2" y="10" width="1.9" height="4" rx="0.6" />
      </g>
      {/* highlight: inner plates */}
      <g className="text-violet-500" fill="currentColor">
        <rect x="6.2" y="8.6" width="2.2" height="6.8" rx="0.7" />
        <rect x="15.6" y="8.6" width="2.2" height="6.8" rx="0.7" />
      </g>
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
      <circle className="text-sky-400" cx="4" cy="19" r="1.5" fill="currentColor" />
      <g className="text-sky-600" {...base}>
        <path d="M17.3 3.6a3.4 3.4 0 0 1 3.4 3.4c0 2.5-3.4 5.6-3.4 5.6s-3.4-3.1-3.4-5.6a3.4 3.4 0 0 1 3.4-3.4Z" />
      </g>
      <circle className="text-sky-500" cx="17.3" cy="7" r="1.4" fill="currentColor" />
    </Svg>
  );
}

export function TorqueIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      {/* steep hill */}
      <path className="text-rose-300" {...base} d="M2.5 19.5h19V9.5l-19 10Z" />
      {/* highlight: cyclist grinding up the slope */}
      <g className="text-rose-600" {...base} strokeWidth={1.5}>
        <circle cx="8.3" cy="14.3" r="1.9" />
        <circle cx="13.6" cy="11.5" r="1.9" />
        <path d="M8.3 14.3l5.3-2.8" />
        <path d="M11 12.9l1.1-4.6" />
      </g>
      <circle className="text-rose-600" cx="12.4" cy="7" r="1.2" fill="currentColor" />
    </Svg>
  );
}

export function GearsIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-indigo-500" {...base} strokeWidth={1.6}>
        {/* tooth ring */}
        <circle cx="12" cy="12" r="4.6" />
        <path d="M16.6 12h1.8M15.25 15.25l1.28 1.28M12 16.6v1.8M8.75 15.25l-1.28 1.28M7.4 12H5.6M8.75 8.75 7.47 7.47M12 7.4V5.6M15.25 8.75l1.28-1.28" />
      </g>
      {/* hub */}
      <circle className="text-indigo-600" cx="12" cy="12" r="1.8" stroke="currentColor" strokeWidth="1.6" />
    </Svg>
  );
}
