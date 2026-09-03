# Data Convention

## File Formats

**Protocol.md** — Experiment metadata (name, batch, devices, sensor parameters)

**Markers CSV** — `sensor_id, timestamp_ms, marker_text`  
Marker text follows the scheme: `STEP_N: Description`

**SpectralSensor CSV** — `sensor, timestamp, 405nm, 415nm, ..., 855nm`  
Timestamps in ms since epoch.

## Units

| Quantity | Symbol | Unit |
|----------|--------|------|
| Inner radius | r_i | mm |
| Outer radius | r_a | mm |
| Silicone absorption coefficient | α_S | 1/mm |
| Concentration | c | mg/mL |
| Cumulative concentration | C | mg/mL · mm |
| SPION absorption coefficient | β | mL/(mg·mm) |
| Intensity | I_0, I_sensor | ADC counts |

## Naming Convention (from sensormodell.tex)

- `I_0` — incident intensity / baseline (c = 0)
- `I_sensor` — measured intensity
- `alpha_S` — silicone absorption coefficient
- `beta` — concentration-dependent absorption coefficient
- `C` — cumulative concentration (integral over channel cross-section)
- `c` — local concentration c(x, y, z, t)
- `r_i`, `r_a` — inner and outer radius

## Raw Data Location

Raw measurement data are stored locally in `~/Documents/10_Projekte/Versuche/`
and are not tracked in this repository.

## DFG Requirements

- Raw data are **not** version-controlled (see `.gitignore`)
- Metadata (Protocol.md) are archived together with each experiment
- Retention period: 10 years from publication
- Data should comply with FAIR principles (findable, accessible, interoperable, reusable)
