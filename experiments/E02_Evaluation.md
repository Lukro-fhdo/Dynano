# Test Report — E02: Magnetic Drug Targeting at a Y-Bifurcation

**Experiment:** E02  
**Protocol name:** Referenz Messung no Robot  
**Start time:** 2026-05-21 15:07:12  
**SPION batch:** XL004  
**SPION stock concentration:** 5 mg/mL, citrate-coated particles  
**Report status:** Experimental setup and sample plan summary; no quantitative sensor-signal analysis included.

## 1. Objective

This experiment evaluates SPION distribution at a simple Y-bifurcation under static magnetic influence. SPION suspension is injected into a water background flow, and the output volumes are collected separately at outlet **A**  and outlet **B**.

The main comparison is between:

- reference injections without magnet, and
- injections with the magnet positioned directly at the bifurcation.
- comparison of different injection volumes

---

## 2. Experimental Setup an Method

The setup consists of a Tygon LMT 55 tube system with **3.17 mm inner diameter** and a simple Y-connector bifurcation. Distilled water is used as background medium. The background flow through the upstream and downstream paths is driven by an Ismatec Reglo ICC peristaltic pump with seperate channels, to provide constant flow in both path. The used channels are calibrated to the designated flowrate, using the pumps internal calibration function. SPIONs are injected through a B. Braun pink 18G injection needle at the injection point upstream the reference sensor and bifurcation.

![Test Setup Overview](E02_20x15_mag_steering/E02_Setup.jpeg)

A **20 × 15 mm cone magnet** is mounted on a **20 mm pot magnet** and positioned by a Denso Cobotta robot. For the magnetic test condition, the magnet is placed directly at the bifurcation.


![Test Setup Overview](E02_20x15_mag_steering/E02_Magnet_pos.png)



### Key parameters

| Category          | Parameter                              |                                      Value |
| ----------------- | -------------------------------------- | -----------------------------------------: |
| Tubing            | Material / type                        |                               Tygon LMT 55 |
| Tubing            | Inner diameter                         |                                    3.17 mm |
| Background medium | Fluid                                  |                            Distilled water |
| Background flow   | Path A                                 |                                  10 mL/min |
| Background flow   | Path B                                 |                                  10 mL/min |
| Background flow   | Total at injection point               |                                  20 mL/min |
| Injection         | SPION flow rate                        |                                  10 mL/min |
| Injection         | Needle                                 | B. Braun Sterican, pink, 18G, 1.20 × 40 mm |
| Sample collection | Volume per outlet after each injection |                                      10 mL |
| Magnet            | Configuration                          | Cone magnet 20 × 15 mm on 20 mm pot magnet |
| Robot             | Positioning system                     |                              Denso Cobotta |
| Control software  | Synchronization                        |                                  DynanoGUI |



## Sensor Assignment

- `A`: Sensor 1001, Outlet A, ID = 1
- `B`: Sensor 1000, Outlet B, ID = 2
- `Ref`: Sensor 1002, reference sensor, ID = 0

For each sensor, the CSV columns are `t_X`, `raw_X`, `abs_X`, and `norm_X`, with $X \in \{A,B,\mathrm{Ref}\}$.

## Raw Signal

$$I_X(t)=\mathrm{raw}_X(t)$$

The raw signal is the measured ADC value at the sensor-specific time $t_X$.

## Baseline

$$I_{\mathrm{Baseline},X}=\operatorname{median}\left\{I_X(t)\mid -T_B\leq t<0\right\}$$

The baseline is the median of the final $T_B=10\,\mathrm{s}$ before the respective injection.

## 100% Reference

$$I_{100\%,X}=\min_{t\in[t_{\mathrm{STEP6}},\,t_{\mathrm{STEP8}})} I_X(t)$$

For each sensor, the absolute minimum between STEP 6 and STEP 8 is used as the 100% reference.

## Baseline-Corrected Signal

$$\mathrm{abs}_X(t)=I_{\mathrm{Baseline},X}-I_X(t)$$

`abs_X` describes the signal change relative to the baseline in ADC counts.

## Normalized Signal

$$\mathrm{norm}_X(t)=\frac{I_{\mathrm{Baseline},X}-I_X(t)}{I_{\mathrm{Baseline},X}-I_{100\%,X}}$$

A value of $0$ corresponds to the baseline, and a value of $1$ corresponds to the 100% reference.

## Peak

$$P_{X,r}=\max_{0\leq t\leq T}\mathrm{abs}_{X,r}(t)$$

The peak is the maximum baseline-corrected signal response of replicate $r$.

## Integral

$$J_{X,r}=\int_0^T\max\!\left(\mathrm{abs}_{X,r}(t),0\right)\,\mathrm{d}t$$

The positive integral represents the total signal response in ADC·s.

## Mean Curve Across Replicates

$$\overline{a}_X(t)=\frac{1}{n}\sum_{r=1}^{n}\mathrm{norm}_{X,r}(t)$$

For the calculation of the mean and standard deviation, the replicate curves are interpolated onto a common time grid only within the statistical analysis.

## Mean and Standard Deviation

$$\overline{x}_X=\frac{1}{n}\sum_{r=1}^{n}x_{X,r}$$

$$s_X=\sqrt{\frac{1}{n-1}\sum_{r=1}^{n}\left(x_{X,r}-\overline{x}_X\right)^2}$$

The mean and sample standard deviation are calculated across all replicates for each experimental condition and sensor.

# Export Example

## Technical Parameters

- Experiment: `E02_C20x15_50%_static_test`
- Batch: `XL004`
- Wavelength: $640\,\mathrm{nm}$
- Evaluation window: $0$ to $60\,\mathrm{s}$ after injection
- Baseline window: $10\,\mathrm{s}$ before injection
- Reference injection: STEP 6
- Reference interval: STEP 6 to STEP 8

## 100% Reference Values

| Channel | Sensor | $I_{100\%}$ / ADC | Time of minimum / s |
|---|---:|---:|---:|
| A | 1001 | 114 | 9.902 |
| B | 1000 | 69 | 9.829 |
| Ref | 1002 | 63 | 4.103 |

## Baselines

| Sample | $I_{\mathrm{Baseline},A}$ / ADC | $I_{\mathrm{Baseline},B}$ / ADC | $I_{\mathrm{Baseline},\mathrm{Ref}}$ / ADC |
|---|---:|---:|---:|
| `E02_50R_AB_1` | 7616 | 5492 | 6129 |
| `E02_50R_AB_2` | 7594 | 5488 | 6099 |

## Reconstruction of One CSV Row

For the first row of `E02_50R_AB_1.csv`, Channel A contains:

- $t_A=0.000\,\mathrm{s}$
- $\mathrm{raw}_A=7614\,\mathrm{ADC}$
- $I_{\mathrm{Baseline},A}=7616\,\mathrm{ADC}$
- $I_{100\%,A}=114\,\mathrm{ADC}$

The baseline-corrected signal is therefore:

$$\mathrm{abs}_A=7616-7614=2\,\mathrm{ADC}$$

The normalized signal is:

$$\mathrm{norm}_A=\frac{2}{7616-114}=0.000267$$

The `abs_X` and `norm_X` columns stored in the CSV can therefore be reconstructed completely from `raw_X`, $I_{\mathrm{Baseline},X}$, and $I_{100\%,X}$.

## Reconstruction of the Plots

- Raw-data plot: `raw_X` versus `t_X`
- Baseline-corrected plot: `abs_X` versus `t_X`
- Normalized plot: `norm_X` versus `t_X`

All required baseline and reference values are collected in `sample_csv/info.txt`.


# Results

## Reference determination

The 100% reference intensity was defined independently for each sensor as the absolute minimum between STEP 6 and STEP 8. The resulting reference values were used for all subsequent normalizations.

![Absolute minimum used as 100% reference](E02_20x15_mag_steering/results/reference_100pct_640nm.png)

*Figure 1. Sensor-specific determination of $I_{100\%}$ from the absolute minimum after the reference injection.*

## Representative injection response

Figure 2 shows the raw sensor response for a representative 50 µL injection without magnetic separation. The sensor-specific baselines and reference values were retained for normalization.

![Representative raw injection response](E02_20x15_mag_steering/results/injection_plots_raw/STEP_08_50uL_10uL-min_rep1_640nm_raw.png)


*Figure 2. Raw response at 640 nm for STEP 8 ($V_{inj}=50\,\mu L$, $Q_{inj}=10\,\mu L\,min^{-1}$, replicate 1).* 

The normalized response is shown in Figure 3, where 0 denotes the pre-injection baseline and 1 denotes the sensor-specific 100% reference.

![Representative normalized injection response](E02_20x15_mag_steering/results/injection_plots_normalized/STEP_08_50uL_10uL-min_rep1_640nm_normalized.png)

*Figure 3. Normalized response of Branch A, Branch B, and the reference sensor for the same injection.*

## Replicate variability

For each condition, three replicate injections were evaluated. The solid or dashed lines in Figure 4 represent the replicate mean; the shaded bands show standard deviation.

![Mean and standard deviation of replicates](E02_20x15_mag_steering/results/statistics/mean_std_curves/mean_std_V100uL_Q10uL-min_on.png)

*Figure 4. Mean normalized response $\pm$ standard deviation for 50 µL injections with the magnet enabled ($n=3$).* 

## Peak and integral metrics

The peak was defined as the maximum normalized signal within 60 s after injection. The integral was calculated from the positive part of the normalized response using trapezoidal integration. Branch A, Branch B, and the reference sensor are compared directly.

![Peak comparison](E02_20x15_mag_steering/results/statistics/peak_mean_std_sensor_comparison.png)

*Figure 5. Mean peak response $\pm$ standard deviation for all experimental conditions ($n=3$).* 

![Integral comparison](E02_20x15_mag_steering/results/statistics/integral_mean_std_sensor_comparison.png)

*Figure 6. Mean positive signal integral $\pm$ standard deviation for all experimental conditions ($n=3$).* 

The numerical values underlying Figures 4–6 are provided in `replicate_metrics.csv`, `replicate_summary.csv`, and `replicate_mean_curves.csv`.