import {
  BatteryIcon, MotorIcon, PayloadIcon, RangeIcon, SensorIcon, SpeedIcon, TorqueIcon,
  WeightIcon, StarIcon, GearsIcon, BrakeIcon, ForkIcon, TireIcon, FoldIcon, TagIcon,
} from "./icons";

/** Small icon for a single Highlights entry: magnitude standouts reuse their spec-tile
 *  icon; equipment maps to the closest icon, with a star as the generic fallback. */
export function standoutIcon(label: string, className: string) {
  const l = label.toLowerCase();
  // the value-meter lead highlight ("Exceptional value" / "Value score unavailable …")
  if (l.includes("value")) return <TagIcon className={className} />;
  if (l.includes("long range")) return <RangeIcon className={className} />;
  if (l.includes("torque sensor") || l.includes("sensor")) return <SensorIcon type="torque" className={className} />;
  if (l.includes("torque")) return <TorqueIcon className={className} />;
  if (l.includes("battery") || l.includes("cell")) return <BatteryIcon className={className} />;
  if (l.includes("motor")) return <MotorIcon className={className} />;
  if (l.includes("lightweight")) return <WeightIcon className={className} />;
  if (l.includes("speed")) return <SpeedIcon className={className} />;
  if (l.includes("payload")) return <PayloadIcon className={className} />;
  if (l.includes("brake")) return <BrakeIcon className={className} />;
  if (l.includes("fork") || l.includes("suspension")) return <ForkIcon className={className} />;
  if (l.includes("tire")) return <TireIcon className={className} />;
  if (l.includes("fold")) return <FoldIcon className={className} />;
  if (l.includes("gear hub") || l.includes("gearbox") || l.includes("drivetrain") || l.includes("shifting")) return <GearsIcon className={className} />;
  return <StarIcon className={className} />;
}

/** The bike's standouts as a star-headed list — one entry per line, each with its small
 *  icon and "Label: value". Shared by BikeCard and BikeDetail so both read identically. */
export function HighlightsList({ standouts }: { standouts?: { label: string; value?: string }[] }) {
  if (!standouts || standouts.length === 0) return null;
  return (
    <div>
      <div className="mb-0.5 flex items-center gap-1.5">
        <StarIcon className="h-[18px] w-[18px]" />
        <span className="text-xs font-semibold text-slate-700">Highlights</span>
      </div>
      <div className="space-y-0.5 text-[11px] leading-snug text-slate-600">
        {standouts.map((s) => (
          <div key={s.label} className="flex items-center gap-1.5">
            <span className="shrink-0 [&_*]:!text-brand-600">{standoutIcon(s.label, "h-3.5 w-3.5")}</span>
            <span>{s.value ? `${s.label}: ${s.value}` : s.label}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
