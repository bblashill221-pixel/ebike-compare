// Feature columns per parsed-component kind (the `_kind` stamped by
// parse_components.parse_component). Each column maps a component field to a
// header + optional fixed unit suffix. Special key "__make" merges
// manufacturer + model; "details" is the trailing free-text "Extra".

export type Column = { key: string; header: string; unit?: string };

const c = (key: string, header: string, unit?: string): Column => ({ key, header, unit });
const MAKE = c("__make", "Make");
const EXTRA = c("details", "Extra");

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
          c("torque_nm", "Torque", " Nm"), c("voltage_v", "Voltage", " V"), MAKE, EXTRA],
  battery: [c("capacity_wh", "Capacity", " Wh"), c("total_capacity_wh", "Total", " Wh"),
            c("pack_count", "Packs"), c("voltage_v", "Voltage", " V"), c("amphours_ah", "Ah", " Ah"),
            c("cell_brand", "Cells"), c("cell_format", "Format"), c("removable", "Removable"),
            MAKE, EXTRA],
  charger: [c("output_v", "Output", " V"), c("amps_a", "Amps", " A"), MAKE, EXTRA],
  controller: [c("voltage_v", "Voltage", " V"), c("amps_a", "Amps", " A"), EXTRA],
  sensor: [c("type", "Type"), c("magnets", "Magnets"), EXTRA],
  pedal_assist: [c("levels", "Levels"), c("boost", "Boost"), EXTRA],
  display: [c("type", "Type"), c("size_in", "Size", "″"), c("bluetooth", "Bluetooth"), MAKE, EXTRA],
  throttle: [c("type", "Type"), c("side", "Side"), MAKE, EXTRA],

  frame: [c("material", "Material"), c("integrated_battery", "Integrated battery"),
          c("folding", "Folding"), EXTRA],
  fork: [c("type", "Type"), c("travel_mm", "Travel", " mm"), c("lockout", "Lockout"),
         c("thru_axle", "Thru-axle"), MAKE, EXTRA],
  shock: [c("type", "Type"), c("size", "Size"), MAKE, EXTRA],

  derailleur: [c("speeds", "Speeds"), c("gearing", "Gearing"), MAKE, EXTRA],
  cassette: [c("speeds", "Speeds"), c("cog_range", "Range"), c("gearing", "Gearing"), MAKE, EXTRA],
  chain: [c("links", "Links"), MAKE, EXTRA],
  chainring: [c("teeth", "Teeth"), c("narrow_wide", "Narrow-wide"), MAKE, EXTRA],
  crankset: [c("length_mm", "Length", " mm"), c("chainring_t", "Chainring T"), MAKE, EXTRA],
  bottom_bracket: [c("type", "Type"), c("torque_sensor", "Torque sensor"), c("sealed", "Sealed"),
                   c("width_mm", "Width", " mm"), EXTRA],
  pedals: [c("type", "Type"), c("material", "Material"), c("thread", "Thread"), EXTRA],

  brake: [c("actuation", "Type"), c("kind", "Style"), c("rotor_mm", "Rotor", " mm"),
          c("rotor_thickness_mm", "Thickness", " mm"), c("pistons", "Pistons"), MAKE, EXTRA],

  wheel: [c("size_in", "Size", "″"), c("holes", "Holes"), c("gauge", "Gauge"), c("axle", "Axle"),
          c("valve", "Valve"), c("double_wall", "Double-wall"), c("material", "Material"),
          c("tubeless", "Tubeless"), EXTRA],
  tire: [c("diameter_in", "Diameter", "″"), c("width_in", "Width", "″"),
         c("width_mm", "Width", " mm"), c("size", "ISO"), c("tubeless", "Tubeless"), MAKE, EXTRA],
  rims: [c("material", "Material"), c("double_wall", "Double-wall"), c("size_in", "Size", "″"), EXTRA],
  spokes: [c("gauge", "Gauge"), c("material", "Material"), EXTRA],
  tubes: [c("valve", "Valve"), c("valve_mm", "Valve width", " mm"), EXTRA],

  handlebars: [c("type", "Type"), c("width_mm", "Width", " mm"), c("rise_mm", "Rise", " mm"),
               c("clamp_mm", "Clamp", " mm"), c("backsweep_deg", "Backsweep", "°"),
               c("material", "Material"), MAKE, EXTRA],
  stem: [c("type", "Type"), c("length_mm", "Length", " mm"), c("clamp_mm", "Clamp", " mm"),
         c("angle_deg", "Angle", "°"), c("adjustable", "Adjustable"), c("material", "Material"),
         MAKE, EXTRA],
  seatpost: [c("type", "Type"), c("diameter_mm", "Diameter", " mm"), c("travel_mm", "Travel", " mm"),
             c("length_mm", "Length", " mm"), c("material", "Material"), MAKE, EXTRA],
  saddle: [c("width_mm", "Width", " mm"), MAKE, EXTRA],
  grips: [c("material", "Material"), c("lock_on", "Lock-on"), c("ergonomic", "Ergonomic"), MAKE, EXTRA],
  seat_binder: [c("type", "Type"), c("diameter_mm", "Diameter", " mm"), c("material", "Material"), EXTRA],

  light: [c("lumens", "Lumens", " lm"), c("lux", "Lux", " lx"), c("brake_light", "Brake light"),
          c("turn_signal", "Turn signals"), c("integrated", "Integrated"), EXTRA],
  cert: [c("standards", "Standards"), EXTRA],
};
