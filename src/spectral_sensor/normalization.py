import pandas as pd
import numpy as np

from .preprocessing import marker_time, select_time_window


def normalize_signal(corrected_sensors, references):
    """Normiert das korrigierte Signal anhand der 100-%-Referenz."""
    normalized_sensors = {}

    for sensor_name, table in corrected_sensors.items():
        normalized = table.copy()
        reference_adc = references[sensor_name]
        denominator = normalized["baseline_adc"] - reference_adc

        valid = np.isfinite(denominator) & (denominator.abs() > 1e-12)

        normalized["reference_adc_100pct"] = reference_adc
        normalized["normalized_0_1"] = (
            normalized["absorption_adc"] / denominator.where(valid)
        )
        normalized_sensors[sensor_name] = normalized

    return normalized_sensors


def baseline_correction(
    synced_sensors,
    window_sensors,
    wavelength_nm,
    start_s,
    baseline_window_s,
):
    """Berechnet die Baseline vor dem Fenster und die ADC-Differenz.

    Die Baseline umfasst [start_s - baseline_window_s, start_s).
    Die Eingabetabellen bleiben unverändert.
    """
    corrected_sensors = {}
    column = str(wavelength_nm)

    for sensor_name, window in window_sensors.items():
        sensor = synced_sensors[sensor_name]

        baseline_mask = (
            (sensor["time_s"] >= start_s - baseline_window_s)
            & (sensor["time_s"] < start_s)
        )

        baseline_values = pd.to_numeric(
            sensor.loc[baseline_mask, column],
            errors="coerce",
        ).dropna()

        baseline_adc = baseline_values.median()

        corrected = window.copy()
        raw_adc = pd.to_numeric(corrected[column], errors="coerce")

        corrected["baseline_adc"] = baseline_adc
        corrected["absorption_adc"] = baseline_adc - raw_adc
        corrected_sensors[sensor_name] = corrected

    return corrected_sensors

def prepare_injections(
    synced_sensors,
    synced_markers,
    injections,
    reference_values,
    wavelength_nm,
    window_s,
    baseline_window_s,
):
    """Cut, baseline-correct, and normalize each assigned injection."""
    prepared = {}

    for marker_index in injections["marker_index"]:
        start_s = marker_time(synced_markers, marker_index)

        window = select_time_window(
            synced_sensors, start_s, window_s
        )

        corrected = baseline_correction(
            synced_sensors,
            window,
            wavelength_nm,
            start_s,
            baseline_window_s,
        )

        prepared[marker_index] = normalize_signal(
            corrected, reference_values
        )

    return prepared
