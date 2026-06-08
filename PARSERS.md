# Component parsers

Free-text e-bike spec values are parsed into structured fields by
[`parse_components.py`](parse_components.py) — the single source of truth. Scrapers emit only
a flat `specs.all` map of `{label: value}` strings; `spec_groups.group_specs()` snake-cases
each label, routes it to a parser via `parse_components._resolver()`, and calls
`parse_component(field, value, brand)` once per field during `normalize.py`.

Every parser:
- returns a dict, or `None` when the field is not a known component (then the raw string is kept);
- emits `details` — whatever it could not structure, so no information is ever dropped;
- emits `manufacturer` (+ `model`) when a known brand is recognised (`_find_brand` + `_leading_model`).

Repeated sub-logic is centralised in **shared field-extractors** at the top of the module, so a
fix lands in every parser at once: `material(text, *allowed)` (ordered `_MATERIAL_RULES`, where
`carbon` means carbon *fiber* and "carbon steel" is steel) and `voltage_v(text)`.

## Drivetrain
| Parser | Field aliases (`_resolver`) | Fields (besides `details`) |
|---|---|---|
| `_derailleur` | derailleur, shifter, shift_lever, e_shifter | manufacturer, model, gearing (`continuously_variable`), speeds |
| `_cassette` | cassette, freewheel | manufacturer, model, cog_range, gearing, speeds |
| `_chain` | chain | manufacturer, model, links |
| `_crankset` | crank* | manufacturer, model, length_mm, chainring_t |
| `_chainring` | chainring* | manufacturer, model, teeth, narrow_wide |
| `_bottom_bracket` | bottom_bracket | type, sealed, torque_sensor, width_mm |
| `_pedals` | pedals, pedal | thread, material, type (folding/platform) |

## Brakes
| Parser | Field aliases | Fields |
|---|---|---|
| `_brake` | brake (not rotor) | manufacturer, model, actuation (hydraulic/mechanical), kind (disc/rim), pistons, rotor_mm, rotor_thickness_mm |

## Frameset / suspension
| Parser | Field aliases | Fields |
|---|---|---|
| `_fork` | fork, suspension | manufacturer, model, type (rigid/air/coil), travel_mm, lockout, thru_axle |
| `_shock` | shock, rear_suspension | manufacturer, model, type (air/coil), size |
| `_frame` | frame | material, integrated_battery, folding |

## Ebike system
| Parser | Field aliases | Fields |
|---|---|---|
| `_motor` | motor, drive_unit | manufacturer, model, placement (mid/hub), power_w, peak_w, torque_nm, voltage_v |
| `_battery` | battery | cell_brand, manufacturer, model, capacity_wh, pack_count, total_capacity_wh, voltage_v, amphours_ah, cell_format, removable |
| `_charger` | charger | manufacturer, model, amps_a, output_v |
| `_controller` | controller | voltage_v, amps_a |
| `_sensor` | sensor | type (torque/cadence/speed), magnets |
| `_pedal_assist` | pedal_assist | levels, boost |
| `_throttle` | throttle | manufacturer, type (half_twist/twist/thumb), side |
| `_display` | display | manufacturer, model, type (touchscreen/color/lcd) |

## Wheelset
| Parser | Field aliases | Fields |
|---|---|---|
| `_tire` | tire, tyre | manufacturer, model, size, width_mm / diameter_in + width_in, tubeless |
| `_wheel` | *_wheel, wheel(s) | size_in, holes, gauge, axle, valve, double_wall, tubeless, material |
| `_rims` | rims, rim | material, double_wall, size_in |
| `_spokes` | spoke* | gauge, material (stainless/aluminum) |
| `_tubes` | tube* | valve, valve_mm |

> No `hub` parser exists yet, though the Wheelset group references hubs — those fields stay raw strings.

## Cockpit
| Parser | Field aliases | Fields |
|---|---|---|
| `_stem` | stem | manufacturer, model, material, type (quill/threadless/folding), adjustable, clamp_mm, length_mm, angle_deg |
| `_seatpost` | seatpost, seat_post | manufacturer, model, type (dropper/suspension), material, diameter_mm, travel_mm, offset_mm, length_mm |
| `_handlebars` | handlebar* | manufacturer, model, material, type (bmx/riser/cruiser/flat), clamp_mm, width_mm, rise_mm, backsweep_deg, upsweep_deg |
| `_saddle` | saddle | manufacturer, model, width_mm |
| `_seat_binder` | binder | diameter_mm, material, type (quick_release/bolt) |
| `_grips` | grip* | manufacturer, model, lock_on, ergonomic, material (leather/rubber/foam) |

## Safety / misc
| Parser | Field aliases | Fields |
|---|---|---|
| `_light` | light* | lumens, lux, brake_light, turn_signal, integrated |
| `_cert` | certif*/compliance/iso_standard | standards[] |

## Standalone measurements (not components)
Scalar spec fields are handled by `unitize(field, value)`, not a parser. The four
rider-facing toggle-able dimensions emit **both** units (native value parsed, counterpart
converted at build time):

| Field keyword | Output |
|---|---|
| speed / top speed / max speed | `_mph` + `_kph` |
| weight / payload / load / capacity | `_lb` + `_kg` |
| range | `_mi` + `_km` |
| wheelbase, reach, stack, standover, chainstay, … (geometry/length) | `_in` + `_mm` |
| torque | `_nm` |
| power / wattage | `_w` |
