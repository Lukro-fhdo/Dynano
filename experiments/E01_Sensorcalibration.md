# 1 Sensor calibration

To get an estimated concentration estimation, we calibrate the used sensors to our SPION charge. we use citrate SPIONS with $c = 5.0\ mg\ mL^{-1}$ with citrate coating. Therefore concentration probes of 0, 2.5 5, 10, 15, 25, 50, 75 and 100% were produced as a mixture of Distilled water and SPION suspension. 

After thermal stabilization time of $t = 15\ min$ a suspension sample of 0.5 mL is injected into the air fillid tube. The resulting suspension bolus is surrounded by air to make it movable by a syringe and prevent mixing of the concentration samples. Each concentration is measured 60 seconds and reapeated three times. This measurement protocol for sensor calibration on the SPIONs concentration is applied to all three sensors available.

All three Sensors are calibrated once. applied to the same tube of 500 mm with equal distance. thus an volume of $V = 500 \cdot \pi \cdot 1,585^2 $


# Calibration Sample Preparation: SPION Dilution Series

## Materials

- **SPION Stock**: Citrate-coated, c = 5.0 mg/mL, charge = XL004
- **Diluent**: Distilled water (H₂O dist.)
- **Target volume**: 2.0 mL per sample
- **Number**: 8 concentrations

---

## Pipetting Scheme


| Sample | Concentration | V(SPION) [µL] | V(H₂O) [µL] | c(final) [mg/mL] | ✓ |
|---|---|---|---|---|---|
| C000 | 0% | 0 | 2000 | 0.000 | [x] |
| C002 | 2.5% | 50 | 1950 | 0.125 | [x] |
| C005 | 5% | 100 | 1900 | 0.250 | [x] |
| C010 | 10% | 200 | 1800 | 0.500 | [x] |
| C025 | 25% | 500 | 1500 | 1.250 | [x] |
| C050 | 50% | 1000 | 1000 | 2.500 | [x] |
| C075 | 75% | 1500 | 500 | 3.750 | [x] |
| C100 | 100% | 2000 | 0 | 5.000 | [x] |


---

## Protocol


### Preparation

1. Label **8 Eppendorf tubes (2 mL)**: C000, C002, C005, C010, C025, C050, C075, C100
3. Calibrate pipettes: 1000 µL, 200 µL, 50 µL

### Pipetting

**Order**: C000 → C100 (ascending, contamination minimization)

4. **C000**: 2000 µL H₂O dist.
5. **C002**: 1950 µL H₂O + 50 µL SPION
6. **C005**: 1900 µL H₂O + 100 µL SPION
7. **C010**: 1800 µL H₂O + 200 µL SPION
8. **C025**: 1500 µL H₂O + 500 µL SPION
9. **C050**: 1000 µL H₂O + 1000 µL SPION
10. **C075**: 500 µL H₂O + 1500 µL SPION
11. **C100**: 2000 µL SPION (stock undiluted)


## Material Consumption (Total)

- **SPION Stock**: 7.25 mL
- **H₂O dist.**: 8.75 mL
- **Tubes**: 8 × 2 mL


## Results — Sensor Calibration

Concentration series of a 5 mg/mL SPION stock, three sensors, three replicates per
level, 640 nm, 25 ms integration time. Intensities in ADC counts.

### Table 1 — Calibration series, group means

| Level | c [mg/mL] | S0 mean ± SD | S0 CV | S1 mean ± SD | S1 CV | S2 mean ± SD | S2 CV |
|---|---:|---:|---:|---:|---:|---:|---:|
| `H20` | 0.000 | 6175.8 ± 25.2 | 0.41% | 6807.3 ± 37.0 | 0.54% | 5772.1 ± 31.5 | 0.55% |
| `C002` | 0.125 | 5095.3 ± 9.3 | 0.18% | 5678.2 ± 13.5 | 0.24% | 4826.3 ± 7.6 | 0.16% |
| `C005` | 0.250 | 4450.4 ± 5.9 | 0.13% | 4970.3 ± 4.2 | 0.08% | 4245.2 ± 3.9 | 0.09% |
| `C010` | 0.500 | 3109.0 ± 6.6 | 0.21% | 3550.7 ± 24.7 | 0.70% | 3053.4 ± 9.3 | 0.30% |
| `C025` | 1.250 | 1277.5 ± 15.0 | 1.17% | 1467.8 ± 6.3 | 0.43% | 1272.1 ± 4.3 | 0.34% |
| `C050` | 2.500 | 349.7 ± 2.2 | 0.64% | 420.0 ± 3.5 | 0.82% | 376.4 ± 4.4 | 1.18% |
| `C075` | 3.750 | 158.5 ± 5.7 | 3.59% | 195.7 ± 0.9 | 0.45% | 173.7 ± 0.4 | 0.24% |
| `C100` | 5.000 | 87.8 ± 2.9 | 3.26% | 112.5 ± 0.9 | 0.78% | 100.7 ± 0.2 | 0.22% |

### Table 2 — Normalised transmission I/I₀

| Level | c [mg/mL] | S0 | S1 | S2 | mean |
|---|---:|---:|---:|---:|---:|
| `H20` | 0.000 | 1.00000 | 1.00000 | 1.00000 | 1.00000 |
| `C002` | 0.125 | 0.82504 | 0.83414 | 0.83614 | 0.83178 |
| `C005` | 0.250 | 0.72063 | 0.73015 | 0.73546 | 0.72874 |
| `C010` | 0.500 | 0.50342 | 0.52160 | 0.52898 | 0.51800 |
| `C025` | 1.250 | 0.20685 | 0.21562 | 0.22039 | 0.21429 |
| `C050` | 2.500 | 0.05662 | 0.06169 | 0.06522 | 0.06118 |
| `C075` | 3.750 | 0.02567 | 0.02874 | 0.03009 | 0.02817 |
| `C100` | 5.000 | 0.01421 | 0.01652 | 0.01744 | 0.01606 |

### Table 3 — Replicate reproducibility

| Level | Sensor | Rep 1 | Rep 2 | Rep 3 | Spread | Rel. spread |
|---|---|---:|---:|---:|---:|---:|
| `H20` | S0 | 6151.4 | 6174.1 | 6201.8 | 50.4 | 0.82% |
| `H20` | S1 | 6768.8 | 6810.4 | 6842.7 | 73.9 | 1.09% |
| `H20` | S2 | 5738.1 | 5778.0 | 5800.3 | 62.2 | 1.08% |
| `C002` | S0 | 5085.0 | 5097.9 | 5102.9 | 18.0 | 0.35% |
| `C002` | S1 | 5693.6 | 5672.8 | 5668.3 | 25.3 | 0.45% |
| `C002` | S2 | 4817.9 | 4828.7 | 4832.4 | 14.6 | 0.30% |
| `C005` | S0 | 4453.9 | 4453.8 | 4443.6 | 10.3 | 0.23% |
| `C005` | S1 | 4975.1 | 4968.4 | 4967.4 | 7.7 | 0.15% |
| `C005` | S2 | 4241.2 | 4249.0 | 4245.3 | 7.9 | 0.19% |
| `C010` | S0 | 3101.9 | 3110.0 | 3115.1 | 13.2 | 0.42% |
| `C010` | S1 | 3577.9 | 3544.6 | 3529.6 | 48.3 | 1.36% |
| `C010` | S2 | 3061.0 | 3056.0 | 3043.1 | 17.9 | 0.59% |
| `C025` | S0 | 1291.6 | 1279.0 | 1261.8 | 29.8 | 2.33% |
| `C025` | S1 | 1473.3 | 1469.1 | 1460.9 | 12.3 | 0.84% |
| `C025` | S2 | 1267.9 | 1276.5 | 1272.1 | 8.6 | 0.68% |
| `C050` | S0 | 351.6 | 350.2 | 347.2 | 4.4 | 1.25% |
| `C050` | S1 | 416.0 | 422.4 | 421.5 | 6.4 | 1.52% |
| `C050` | S2 | 371.3 | 379.4 | 378.6 | 8.0 | 2.14% |
| `C075` | S0 | 152.1 | 160.6 | 162.9 | 10.8 | 6.82% |
| `C075` | S1 | 194.9 | 196.6 | 195.5 | 1.7 | 0.88% |
| `C075` | S2 | 173.4 | 174.2 | 173.5 | 0.7 | 0.43% |
| `C100` | S0 | 85.9 | 91.1 ⚠ | 86.3 | 5.2 | 5.89% |
| `C100` | S1 | 111.5 | 113.1 | 112.8 | 1.6 | 1.45% |
| `C100` | S2 | 100.6 | 100.5 | 100.9 | 0.4 | 0.40% |

### Table 4 — Apparent β per concentration interval

Single-beam Beer-Lambert evaluated between adjacent levels. A constant material
β would make these columns flat.

| Interval | Δc [mg/mL] | S0 | S1 | S2 |
|---|---:|---:|---:|---:|
| `H20`→`C002` | 0.125 | 0.4854 | 0.4577 | 0.4516 |
| `C002`→`C005` | 0.125 | 0.3415 | 0.3361 | 0.3238 |
| `C005`→`C010` | 0.250 | 0.4526 | 0.4244 | 0.4158 |
| `C010`→`C025` | 0.750 | 0.3741 | 0.3716 | 0.3683 |
| `C025`→`C050` | 1.250 | 0.3270 | 0.3158 | 0.3073 |
| `C050`→`C075` | 1.250 | 0.1997 | 0.1927 | 0.1952 |
| `C075`→`C100` | 1.250 | 0.1492 | 0.1397 | 0.1377 |

| Cumulative from `H20` | c [mg/mL] | S0 | S1 | S2 |
|---|---:|---:|---:|---:|
| → `C002` | 0.125 | 0.4854 | 0.4577 | 0.4516 |
| → `C005` | 0.250 | 0.4134 | 0.3969 | 0.3877 |
| → `C010` | 0.500 | 0.4330 | 0.4106 | 0.4018 |
| → `C025` | 1.250 | 0.3977 | 0.3872 | 0.3817 |
| → `C050` | 2.500 | 0.3623 | 0.3515 | 0.3445 |
| → `C075` | 3.750 | 0.3081 | 0.2986 | 0.2947 |
| → `C100` | 5.000 | 0.2684 | 0.2589 | 0.2555 |
