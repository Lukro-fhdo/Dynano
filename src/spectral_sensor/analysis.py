import pandas as pd

def get_min(sensor_data, wavelength_nm):
    """Liefert den kleinsten ADC-Wert je Sensor."""
    minima = {}

    for sensor_name, table in sensor_data.items():
        values = pd.to_numeric(
            table[str(wavelength_nm)], errors="coerce"
        ).dropna()
        minima[sensor_name] = values.min()

    return minima


def get_peak(sensor_data, time_column, signal_column):
    """Liefert das größte Signal und seinen Zeitpunkt je Sensor.

    Bei gleichen Maxima gilt der erste Wert in der Tabellenreihenfolge.
    """
    results = []

    for sensor_name, table in sensor_data.items():
        signal = pd.to_numeric(table[signal_column], errors="coerce")
        valid = signal.dropna()

        if valid.empty:
            peak_value = float("nan")
            peak_time = float("nan")
        else:
            peak_index = valid.idxmax()
            peak_value = valid.loc[peak_index]
            peak_time = table.loc[peak_index, time_column]

        results.append({
            "sensor": sensor_name,
            "peak_value": peak_value,
            "peak_time_s": peak_time,
        })

    return pd.DataFrame(results)

import numpy as np


def get_integral(
    sensor_data,
    time_column,
    signal_column,
    positive_only=False,
):
    """Berechnet die Fläche unter dem Signal mit der Trapezregel.

    positive_only=True setzt negative Signalwerte vor der Integration auf 0.
    """
    results = []

    for sensor_name, table in sensor_data.items():
        time = pd.to_numeric(table[time_column], errors="coerce")
        signal = pd.to_numeric(table[signal_column], errors="coerce")

        valid = np.isfinite(time) & np.isfinite(signal)
        values = pd.DataFrame({
            "time": time[valid],
            "signal": signal[valid],
        }).sort_values("time")

        if positive_only:
            values["signal"] = values["signal"].clip(lower=0)

        if len(values) < 2:
            integral = 0.0
        else:
            integral = np.trapezoid(
                values["signal"].to_numpy(),
                x=values["time"].to_numpy(),
            )

        results.append({
            "sensor": sensor_name,
            "integral": integral,
        })

    return pd.DataFrame(results)

def injection_metrics(sensor_data):
    """Calculate signal metrics for one injection, indexed by sensor."""
    metrics = get_peak(
        sensor_data, "time_from_start_s", "absorption_adc"
    ).set_index("sensor").rename(columns={
        "peak_value": "peak_absolute_adc",
    })

    metrics["peak_normalized"] = get_peak(
        sensor_data, "time_from_start_s", "normalized_0_1"
    ).set_index("sensor")["peak_value"]

    for name, signal, positive_only in [
        ("integral_absolute_adc_s", "absorption_adc", False),
        ("integral_positive_adc_s", "absorption_adc", True),
        ("integral_normalized_s", "normalized_0_1", False),
    ]:
        metrics[name] = get_integral(
            sensor_data,
            "time_from_start_s",
            signal,
            positive_only=positive_only,
        ).set_index("sensor")["integral"]

    for sensor, table in sensor_data.items():
        signal = table["absorption_adc"]
        metrics.loc[sensor, "n_points"] = len(table)
        metrics.loc[sensor, "mean_absolute_adc"] = signal.mean()
        metrics.loc[sensor, "std_absolute_adc"] = signal.std()

    metrics["n_points"] = metrics["n_points"].astype(int)
    return metrics