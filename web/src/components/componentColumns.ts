// Feature columns per parsed-component kind (the `_kind` stamped by
// parse_components.parse_component). Each column maps a component field to a
// header + optional fixed unit suffix. Make (manufacturer) and Model are SEPARATE
// columns (e.g. Make "Shimano" / Model "ARDM310DLC"); "details" is the trailing
// free-text "Details".

export type Column = { key: string; header: string; unit?: string };

const c = (key: string, header: string, unit?: string): Column => ({ key, header, unit });
const MAKE = c("manufacturer", "Make");
const MODEL = c("model", "Model");
const EXTRA = c("details", "Details");

export const KIND_LABEL: Record<string, string> = {
  motor: "Motor", battery: "Battery", charger: "Charger", controller: "Controller",
  sensor: "Sensor", pedal_assist: "Pedal assist", display: "Display", throttle: "Throttle",
  frame: "Frame", fork: "Fork / suspension", shock: "Rear shock",
  derailleur: "Derailleur", cassette: "Cassette", chain: "Chain", chainring: "Chainring",
  crankset: "Crankset", bottom_bracket: "Bottom bracket", pedals: "Pedals",
  brake: "Brakes", wheel: "Wheel", tire: "Tire", rims: "Rim", spokes: "Spokes", tubes: "Tubes",
  handlebars: "Handlebar", stem: "Stem", seatpost: "Seatpost", saddle: "Saddle",
  grips: "Grips", seat_binder: "Seat binder", light: "Lights", cert: "Certifications",
};

export const COLUMN_CONFIG: Record<string, Column[]> = {
  motor: [c("power_w", "Nominal", " W"), c("peak_w", "Peak", " W"), c("placement", "Drive"),
          c("torque_nm", "Torque", " Nm"), c("voltage_v", "Voltage", " V"), MAKE, MODEL, EXTRA],
  // "Capacity" renders combined as "720 Wh (48V × 15Ah)" (see ComponentTable),
  // so the standalone Voltage / Ah columns are folded in to save space.
  battery: [c("capacity_wh", "Capacity"), c("total_capacity_wh", "Total", " Wh"),
            c("pack_count", "Packs"),
            c("cell_brand", "Cells"), c("cell_format", "Format"), c("removable", "Removable"),
            c("weight_lb", "Weight", " lb"), c("primary_weight_lb", "Primary weight", " lb"),
            c("secondary_weight_lb", "Secondary weight", " lb"),
            MAKE, MODEL, EXTRA],
  charger: [c("output_v", "Output", " V"), c("amps_a", "Amps", " A"), MAKE, MODEL, EXTRA],
  controller: [c("voltage_v", "Voltage", " V"), c("amps_a", "Amps", " A"), EXTRA],
  sensor: [c("type", "Type"), c("magnets", "Magnets"), EXTRA],
  pedal_assist: [c("levels", "Levels"), c("boost", "Boost"), EXTRA],
  display: [c("type", "Type"), c("size_in", "Size", "″"), c("bluetooth", "Bluetooth"), MAKE, MODEL, EXTRA],
  throttle: [c("type", "Type"), c("side", "Side"), MAKE, MODEL, EXTRA],

  frame: [c("material", "Material"), c("style", "Style"),
          c("integrated_battery", "Integrated battery"),
          c("removable_battery", "Removable battery"),
          c("battery_position", "Battery position"),
          c("cable_routing", "Cable routing"), c("headtube", "Headtube"),
          c("brake_mount", "Brake mount"), c("mounts", "Mounts"),
          c("folding", "Folding"), EXTRA],
  fork: [c("type", "Type"), c("travel_mm", "Travel", " mm"), c("lockout", "Lockout"),
         c("thru_axle", "Thru-axle"), MAKE, MODEL, EXTRA],
  shock: [c("type", "Type"), c("size", "Size"), MAKE, MODEL, EXTRA],

  derailleur: [c("speeds", "Speeds"), c("gearing", "Gearing"), MAKE, MODEL, EXTRA],
  cassette: [c("speeds", "Speeds"), c("cog_range", "Range"), c("gearing", "Gearing"), MAKE, MODEL, EXTRA],
  chain: [c("links", "Links"), MAKE, MODEL, EXTRA],
  chainring: [c("teeth", "Teeth"), c("narrow_wide", "Narrow-wide"), MAKE, MODEL, EXTRA],
  crankset: [c("length_mm", "Length", " mm"), c("chainring_t", "Chainring T"), MAKE, MODEL, EXTRA],
  bottom_bracket: [c("type", "Type"), c("torque_sensor", "Torque sensor"), c("sealed", "Sealed"),
                   c("width_mm", "Width", " mm"), EXTRA],
  pedals: [c("type", "Type"), c("material", "Material"), c("thread", "Thread"), EXTRA],

  // "kind" (Style) is omitted: every e-bike brake in the data is "disc", so it
  // adds no information (actuation already says hydraulic/mechanical).
  brake: [c("actuation", "Type"), c("rotor_mm", "Rotor", " mm"),
          c("rotor_thickness_mm", "Thickness", " mm"), c("pistons", "Pistons"), MAKE, MODEL, EXTRA],

  wheel: [c("size_in", "Size", "″"), c("holes", "Holes"), c("gauge", "Gauge"), c("axle", "Axle"),
          c("valve", "Valve"), c("double_wall", "Double-wall"), c("material", "Material"),
          c("tubeless", "Tubeless"), EXTRA],
  tire: [c("diameter_in", "Diameter", "″"), c("width_in", "Width", "″"),
         c("width_mm", "Width", " mm"), c("size", "ISO"), c("tubeless", "Tubeless"),
         c("manufacturer", "Make"), c("model", "Model"), EXTRA],
  rims: [c("material", "Material"), c("double_wall", "Double-wall"), c("size_in", "Size", "″"), EXTRA],
  spokes: [c("gauge", "Gauge"), c("material", "Material"), EXTRA],
  tubes: [c("valve", "Valve"), c("valve_mm", "Valve width", " mm"), EXTRA],

  handlebars: [c("type", "Type"), c("width_mm", "Width", " mm"), c("rise_mm", "Rise", " mm"),
               c("clamp_mm", "Clamp", " mm"), c("upsweep_deg", "Upsweep", "°"),
               c("backsweep_deg", "Backsweep", "°"),
               c("material", "Material"), c("by_size", "By size"), MAKE, MODEL, EXTRA],
  stem: [c("type", "Type"), c("length_mm", "Length", " mm"), c("clamp_mm", "Clamp", " mm"),
         c("angle_deg", "Angle", "°"), c("adjustable", "Adjustable"), c("material", "Material"),
         c("by_size", "By size"), MAKE, MODEL, EXTRA],
  seatpost: [c("type", "Type"), c("diameter_mm", "Diameter", " mm"), c("travel_mm", "Travel", " mm"),
             c("length_mm", "Length", " mm"), c("offset_mm", "Offset", " mm"),
             c("material", "Material"), MAKE, MODEL, EXTRA],
  saddle: [c("width_mm", "Width", " mm"), MAKE, MODEL, EXTRA],
  grips: [c("material", "Material"), c("lock_on", "Lock-on"), c("ergonomic", "Ergonomic"), MAKE, MODEL, EXTRA],
  seat_binder: [c("type", "Type"), c("diameter_mm", "Diameter", " mm"), c("material", "Material"), EXTRA],

  light: [c("lumens", "Lumens", " lm"), c("lux", "Lux", " lx"), c("brake_light", "Brake light"),
          c("turn_signal", "Turn signals"), c("integrated", "Integrated"), EXTRA],
  cert: [c("standards", "Standards"), EXTRA],
};
