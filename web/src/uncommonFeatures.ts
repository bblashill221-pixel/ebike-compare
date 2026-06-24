// Curated "uncommon features" grouped for display (the card under Dimension Scores).
// analyze.uncommon_features emits a flat list of these labels per bike; we group them
// here and drop any group with no entries for that bike.

export const FEATURE_GROUPS: { label: string; emoji: string; members: string[] }[] = [
  { label: "Security & Tracking", emoji: "🔒", members: ["GPS Tracking", "Find My", "Anti-Theft Alarm", "Fingerprint Unlock"] },
  { label: "Smart System", emoji: "📡", members: ["App Control", "Over-the-air Updates", "Smart Helmet", "CANbus System"] },
  { label: "Premium Drivetrain", emoji: "⚙️", members: ["Electronic Shifting", "Internal Gear Hub", "Belt Drive", "Gearbox (Pinion/Rohloff)", "High-End Drivetrain"] },
  { label: "Premium Ride Kit", emoji: "🚲", members: ["Carbon Frame", "Dropper Post", "Dual Battery", "Regen Braking", "ABS", "4-Piston Brakes"] },
];

/** Group a bike's flat feature list, keeping member order and DROPPING empty groups. */
export function groupFeatures(features: string[] | undefined): { label: string; emoji: string; items: string[] }[] {
  const have = new Set(features ?? []);
  return FEATURE_GROUPS
    .map((g) => ({ label: g.label, emoji: g.emoji, items: g.members.filter((m) => have.has(m)) }))
    .filter((g) => g.items.length > 0);
}
