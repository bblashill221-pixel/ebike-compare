import type { EnumField, RangeField } from "./search/orama";
import type { BoolField } from "./search/orama";

// Shared filter labels, used by the facet panel and the active-filter pill bar.

export const ENUM_SECTIONS: { field: EnumField; label: string }[] = [
  { field: "product_types", label: "Type" },
  { field: "brand", label: "Brand" },
  { field: "frame_style", label: "Frame style" },
  { field: "drive_type", label: "Drive" },
  { field: "brake_type", label: "Brakes" },
  { field: "frame_material", label: "Frame" },
  { field: "suspension", label: "Suspension" },
];

export const RANGE_SECTIONS: { field: RangeField; label: string }[] = [
  { field: "price", label: "Price ($)" },
  { field: "battery_wh", label: "Battery (Wh)" },
  { field: "motor_w", label: "Motor (W)" },
  { field: "torque_nm", label: "Torque (Nm)" },
  { field: "range_mi", label: "Range (mi)" },
  { field: "weight_lb", label: "Weight (lb)" },
  { field: "max_load_lb", label: "Max load (lb)" },
  { field: "gears", label: "Gears" },
];

export const BOOL_LABELS: Record<BoolField, string> = {
  on_sale: "On sale",
  ul_listed: "UL listed",
  kids: "Exclude Kids Ebikes",
};
