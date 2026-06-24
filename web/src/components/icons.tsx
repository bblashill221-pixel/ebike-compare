// Hand-drawn spec icons, fully colored per metric:
//   battery -> 3/4-charged cells (emerald), motor -> electric motor w/ power bolt
//   (amber), weight -> hanging cast weight w/ ring (violet), range -> route pin (sky),
//   torque -> cyclist climbing a steep hill (rose), gears -> tooth ring (indigo),
//   front light -> headlamp w/ forward beam (yellow), tail light -> rear lamp w/
//   backward glow (rose), turn signal -> indicator arrow w/ blink ticks (orange).

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
      {/* ring / loop handle */}
      <circle className="text-violet-600" cx="12" cy="5" r="2.5" stroke="currentColor"
        strokeWidth={2} fill="none" />
      {/* flared cast-weight body */}
      <path className="text-violet-400" stroke="currentColor" strokeWidth={1.2} strokeLinejoin="round"
        fill="currentColor"
        d="M9.4 7.2 C10.2 8 13.8 8 14.6 7.2 C16 7.2 16.6 8.6 17 10.4 L18.6 17.4
           C18.9 18.6 18.1 19.6 16.9 19.6 L7.1 19.6 C5.9 19.6 5.1 18.6 5.4 17.4
           L7 10.4 C7.4 8.6 8 7.2 9.4 7.2 Z" />
    </Svg>
  );
}

export function PayloadIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      {/* upper arm + forearm: thick bent tube */}
      <path className="text-orange-300" stroke="currentColor" strokeWidth={3.6}
        strokeLinecap="round" strokeLinejoin="round" fill="none"
        d="M5.5 17 H12.2 C14.5 17 15.6 15.6 15.6 13.2 V9.5" />
      {/* bicep bulge on top of the upper arm */}
      <path className="text-orange-300" stroke="currentColor" strokeWidth={1.2} strokeLinejoin="round"
        fill="currentColor"
        d="M5.6 15.6 C5 11.4 8.4 9 11.8 10.6 C13.3 11.3 13.8 13 13.5 14.6 L13 15.6 Z" />
      {/* fist */}
      <circle className="text-orange-300" cx="15.6" cy="6.2" r="3" stroke="currentColor"
        strokeWidth={1.2} fill="currentColor" />
      {/* bicep contour */}
      <path className="text-orange-600" stroke="currentColor" strokeWidth={1.4} strokeLinecap="round"
        fill="none" d="M7.2 13.8 C7.2 11.6 8.8 10.6 10.8 11.2" />
      {/* fist knuckles */}
      <path className="text-orange-600" stroke="currentColor" strokeWidth={1.2} strokeLinecap="round"
        fill="none" d="M14.4 4.6 L14.4 7.2 M16.6 4.6 L16.6 7.2" />
    </Svg>
  );
}

export function SpeedIcon({ className }: IconProps) {
  // a man running flat-out: forward-leaning sprinter mid-stride, with speed
  // streaks trailing behind. Represents a model's top speed.
  return (
    <Svg className={className}>
      {/* speed streaks behind the runner */}
      <g className="text-blue-300" {...base} strokeWidth={1.7}>
        <path d="M2 6.5h3.4" />
        <path d="M1.3 10h4" />
        <path d="M2.4 13.6h2.8" />
      </g>
      {/* head */}
      <circle className="text-blue-600" cx="15" cy="4.8" r="2" fill="currentColor" />
      {/* torso + limbs of the sprinter */}
      <g className="text-blue-600" {...base} strokeWidth={1.8}>
        {/* leaning torso */}
        <path d="M14.4 7 11.2 12.6" />
        {/* leading arm pumping forward, trailing arm swung back */}
        <path d="M13.4 8.2 16.9 9.5 18.1 7.4" />
        <path d="M12.8 8.7 9.2 7.3" />
        {/* driving front leg + trailing back leg */}
        <path d="M11.2 12.6 14.4 14.6 15.2 19.2" />
        <path d="M11.2 12.6 8.3 15.7 5.4 16.2" />
      </g>
    </Svg>
  );
}

export function RangeIcon({ className }: IconProps) {
  // point route: a start point with a dashed route up to the destination pin
  return (
    <Svg className={className}>
      {/* the route itself */}
      <path
        className="text-sky-500"
        {...base}
        strokeDasharray="2.6 2.4"
        d="M4 19c4.4 0 3.4-5 7.2-5.4 2.6-.3 3.6-1 4.6-2.4"
      />
      {/* start point */}
      <circle className="text-sky-400" cx="4" cy="19" r="1.5" fill="currentColor" />
      {/* destination pin */}
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

export function FrontLightIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      {/* headlamp housing, mounted facing right */}
      <g className="text-yellow-600" {...base}>
        <circle cx="8.5" cy="12" r="4" />
        <path d="M8.5 16v2.5M5.6 9.1 4 7.5" strokeWidth={1.5} />
      </g>
      {/* lens */}
      <circle className="text-yellow-500" cx="9.6" cy="12" r="1.6" fill="currentColor" />
      {/* highlight: forward beam */}
      <g className="text-yellow-500" {...base} strokeWidth={1.9}>
        <path d="M14.5 8.6l5-2.1" />
        <path d="M15.3 12h5.6" />
        <path d="M14.5 15.4l5 2.1" />
      </g>
    </Svg>
  );
}

export function TailLightIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      {/* rear lamp housing, glowing backward (left) */}
      <g className="text-rose-600" {...base}>
        <rect x="14" y="8.5" width="6" height="7" rx="1.6" />
        <path d="M17 15.5v3M17 5.5v3" strokeWidth={1.5} />
      </g>
      {/* lit lens */}
      <rect className="text-rose-500" x="15.6" y="10.1" width="2.8" height="3.8" rx="0.8" fill="currentColor" />
      {/* highlight: rearward glow */}
      <g className="text-rose-500" {...base} strokeWidth={1.9}>
        <path d="M10.5 8.6 5.5 6.5" />
        <path d="M9.7 12H4.1" />
        <path d="M10.5 15.4l-5 2.1" />
      </g>
    </Svg>
  );
}

export function TurnSignalIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      {/* indicator arrow */}
      <path
        className="text-orange-500"
        fill="currentColor"
        d="M13.2 5.6 20 12l-6.8 6.4v-3.9H7.6a1 1 0 0 1-1-1V10.5a1 1 0 0 1 1-1h5.6V5.6Z"
      />
      {/* highlight: blink ticks */}
      <g className="text-orange-400" {...base} strokeWidth={1.8}>
        <path d="M4 8.2 2.6 6.8" />
        <path d="M3.4 12H1.5" />
        <path d="M4 15.8l-1.4 1.4" />
      </g>
    </Svg>
  );
}

export function WeightCapacityIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      {/* bathroom scale body */}
      <g className="text-teal-600" {...base}>
        <rect x="3.5" y="4.5" width="17" height="15" rx="2.5" />
        {/* readout window */}
        <rect x="9" y="6.8" width="6" height="3.4" rx="0.8" />
        {/* foot pads */}
        <path d="M6.3 14.2v2.4M17.7 14.2v2.4" strokeWidth={1.4} />
      </g>
      {/* highlight: dial needle reading mid-scale */}
      <g className="text-teal-500" fill="currentColor">
        <circle cx="12" cy="8.5" r="0.9" />
      </g>
      <path className="text-teal-500" {...base} strokeWidth={1.5} d="M12 8.5l2.4-1.1" />
    </Svg>
  );
}

export function RiderHeightIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-teal-600" {...base}>
        {/* short rider (left) */}
        <circle cx="7" cy="10" r="1.7" />
        <path d="M7 11.7V16" />
        <path d="M4.9 13.2H9.1" />
        <path d="M7 16l-1.4 4M7 16l1.4 4" />
        {/* tall rider (right) */}
        <circle cx="16.6" cy="4.9" r="1.9" />
        <path d="M16.6 6.8V16" />
        <path d="M14.3 8.9H18.9" />
        <path d="M16.6 16l-1.5 4M16.6 16l1.5 4" />
      </g>
    </Svg>
  );
}

// Pedal-assist sensor type. Torque -> capital "T" (rose); cadence -> capital "C"
// (sky); both -> a small "T" top-left, a split from the bottom-left corner up to
// the top-right corner, and a small "C" bottom-right. Unknown/absent -> the dual
// layout muted in slate.
export function SensorIcon({ className, type }: IconProps & { type?: string | null }) {
  const t = (type || "").toLowerCase();
  const hasT = t.includes("torque");
  const hasC = t.includes("cadence");
  const both = hasT && hasC;
  const known = hasT || hasC;
  const letter = (ch: string, x: number, y: number, size: number, color: string) => (
    <text
      x={x}
      y={y}
      textAnchor="middle"
      dominantBaseline="central"
      className={color}
      fill="currentColor"
      fontFamily="ui-sans-serif, system-ui, sans-serif"
      fontWeight={700}
      fontSize={size}
    >
      {ch}
    </text>
  );
  // unknown/absent -> a single "?" so a missing sensor can't read as a real
  // cadence+torque sensor (the card tile forces every icon to brand-blue)
  if (!known) {
    return <Svg className={className}>{letter("?", 12, 12.5, 16, "text-slate-400")}</Svg>;
  }
  // both -> split layout with cornered letters
  if (both) {
    return (
      <Svg className={className}>
        <line
          x1="4" y1="20" x2="20" y2="4"
          stroke="currentColor" className="text-slate-300"
          strokeWidth={1.5} strokeLinecap="round"
        />
        {letter("T", 7, 7, 10, "text-rose-600")}
        {letter("C", 17, 17, 10, "text-sky-600")}
      </Svg>
    );
  }
  // single sensor -> one centered letter
  return (
    <Svg className={className}>
      {hasT ? letter("T", 12, 12.5, 17, "text-rose-600")
            : letter("C", 12, 12.5, 17, "text-sky-600")}
    </Svg>
  );
}

// --- card "Highlights" icons (brand-blue line icons) ---
export function LeafIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-brand-600" {...base}>
        <path d="M5 19c0-7 5-12 14-13 0 9-5 14-12 14a6 6 0 0 1-2-1Z" />
        <path d="M9 15c2.5-2.5 5-3.5 8-4" />
      </g>
    </Svg>
  );
}

export function CheckIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-brand-600" {...base}>
        <circle cx="12" cy="12" r="8.5" />
        <path d="m8.5 12 2.4 2.4 4.6-4.8" />
      </g>
    </Svg>
  );
}

export function BuildingIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-brand-600" {...base}>
        <path d="M5 20V7l6-3v16M11 20V9l8 3v8M3 20h18" />
        <path d="M7.5 8.5v0M7.5 11.5v0M7.5 14.5v0M14.5 13v0M14.5 16v0" />
      </g>
    </Svg>
  );
}

export function StarIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <path
        className="text-[#F59E0B]"
        fill="currentColor" stroke="currentColor" strokeWidth={1} strokeLinejoin="round"
        d="m12 3 2.6 5.27 5.82.85-4.21 4.1.99 5.78L12 16.77 6.8 19l.99-5.78-4.21-4.1 5.82-.85Z"
      />
    </Svg>
  );
}

// Folding: two hinged panels with a curved arrow folding one onto the other.
export function FoldIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-brand-600" {...base}>
        <path d="M4 18V8l7-3v13z" />
        <path d="M11 5l7 3v10l-7 3" />
        <circle cx="11" cy="12" r="0.9" fill="currentColor" stroke="none" />
        <path d="M14.5 4.5a5 5 0 0 1 0 5" strokeWidth={1.4} />
      </g>
    </Svg>
  );
}

// Brake: a disc rotor (ring + drilled holes) with a caliper at the top.
export function BrakeIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-brand-600" {...base}>
        <circle cx="11" cy="13" r="7.5" />
        <circle cx="11" cy="13" r="3" />
        <path d="M16 6.5h4.5v4" />
      </g>
      <g className="text-brand-600" fill="currentColor">
        <circle cx="11" cy="7.5" r="0.7" />
        <circle cx="16" cy="13" r="0.7" />
        <circle cx="11" cy="18.5" r="0.7" />
        <circle cx="6" cy="13" r="0.7" />
      </g>
    </Svg>
  );
}

// Suspension fork: twin stanchions into a crown, with a coil spring on one leg.
export function ForkIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-brand-600" {...base}>
        <path d="M7 3v6M17 3v6" />
        <path d="M7 9h10" />
        <path d="M8.5 9l-1.5 11M15.5 9l1.5 11" />
        <path d="M7 12.5l3 1.2M7.4 15l3 1.2M7.8 17.5l3 1.2" />
      </g>
    </Svg>
  );
}

// Tire: a wheel with a knobby tread ring and a hub.
export function TireIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-brand-600" {...base}>
        <circle cx="12" cy="12" r="9" />
        <circle cx="12" cy="12" r="5" />
        <circle cx="12" cy="12" r="1.6" fill="currentColor" stroke="none" />
      </g>
    </Svg>
  );
}

// Tag: a price tag with a punch hole (blue), for the Price metric.
export function TagIcon({ className }: IconProps) {
  return (
    <Svg className={className}>
      <g className="text-blue-600" {...base}>
        <path d="M3.6 12.6l8-8a2 2 0 0 1 1.4-.6H19a1.5 1.5 0 0 1 1.5 1.5v5.6a2 2 0 0 1-.6 1.4l-8 8a1.5 1.5 0 0 1-2.1 0l-6.2-6.2a1.5 1.5 0 0 1 0-2.1Z" />
        <circle cx="16" cy="8" r="1.3" fill="currentColor" stroke="none" />
      </g>
    </Svg>
  );
}
