"""Messdateien lesen.

Sensor-CSV: unveränderte Tabelle aus der Datei.
Marker: ID, Zeitstempel in Millisekunden, Text und mögliche Lesefehler.
Protokoll: Experimentname, Batch, Startzeit und Wellenlängen.

Bereinigung, Zeitachsen und Berechnungen bleiben im Analyzer.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import re

import numpy as np
import pandas as pd


def discover_files(folder: Path) -> dict[str, Any]:
    """Findet Sensor-, Marker- und optionale Protokolldateien im Messordner."""
    sensor_files = sorted(folder.glob("Spectralsensor*.csv"))
    marker_files = sorted(folder.glob("Markers*.csv"))
    protocol_files = sorted(folder.glob("Protocol*.md"))

    if not sensor_files:
        raise FileNotFoundError(
            f"Keine file 'Spectralsensor*.csv' in {folder} gefunden."
        )
    if not marker_files:
        raise FileNotFoundError(
            f"Keine file 'Markers*.csv' in {folder} gefunden."
        )
    if len(marker_files) > 1:
        raise ValueError(
            "Mehrere Markerdateien gefunden. Pro Messordner wird genau eine erwartet: "
            + ", ".join(path.name for path in marker_files)
        )

    return {
        "sensors": sensor_files,
        "markers": marker_files[0],
        "protocol": protocol_files[0] if protocol_files else None,
    }


def read_sensor_csv(path: Path) -> pd.DataFrame:
    """Liest die CSV unverändert; die Aufbereitung übernimmt der Analyzer."""
    return pd.read_csv(path)


def read_marker_rows(path: Path) -> pd.DataFrame:
    """Liest rohe Markerzeilen; trennt nur die ersten zwei Kommas."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", errors="replace") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            line = raw_line.rstrip("\r\n")
            if not line.strip():
                continue
            parts = line.split(",", 2)
            if len(parts) != 3:
                rows.append(
                    {
                        "line_number": line_number,
                        "marker_id": np.nan,
                        "timestamp_raw_ms": np.nan,
                        "label": line.strip(),
                        "parse_error": "Zeile enthält weniger als zwei Kommas.",
                    }
                )
                continue

            marker_id, timestamp, label = (part.strip() for part in parts)
            marker_id_num = pd.to_numeric(marker_id, errors="coerce")
            timestamp_num = pd.to_numeric(timestamp, errors="coerce")

            # Eine echte Headerzeile wird übersprungen; fehlerhafte Datenzeilen bleiben sichtbar.
            header_like = (
                pd.isna(marker_id_num)
                and pd.isna(timestamp_num)
                and marker_id.lower() in {"marker_id", "device", "sensor"}
            )
            if header_like:
                continue

            rows.append(
                {
                    "line_number": line_number,
                    "marker_id": marker_id_num,
                    "timestamp_raw_ms": timestamp_num,
                    "label": label,
                    "parse_error": ""
                    if pd.notna(timestamp_num)
                    else "timestamp ist nicht numerisch.",
                }
            )

    frame = pd.DataFrame(rows)
    if frame.empty:
        raise ValueError(f"Markerdatei ist leer: {path}")

    return frame


def read_protocol(path: Optional[Path]) -> dict[str, Any]:
    """Liest die Metadaten aus Protocol.md; ohne Datei bleibt das Ergebnis leer."""
    if path is None or not path.exists():
        return {}

    text = path.read_text(encoding="utf-8", errors="replace")
    metadata: dict[str, Any] = {"protocol_file": path.name}

    patterns = {
        "experiment_name": r"^Experiment Name:\s*(.+)$",
        "batch_number": r"^Batch Number:\s*(.+)$",
        "start_time": r"^Start Time:\s*(.+)$",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, text, flags=re.MULTILINE)
        if match:
            metadata[key] = match.group(1).strip().replace("\\_", "_")

    bands = [
        int(value)
        for value in re.findall(r"Timeline Band:.*?\((\d+)\s*nm\)", text)
    ]
    if bands:
        metadata["timeline_band_nm"] = bands[0]
        metadata["timeline_bands_nm"] = sorted(set(bands))
    return metadata

def save_results(sensor_data, metrics, output_folder):
    """Speichert Zeitreihen je Sensor und eine gemeinsame Kennwerttabelle."""
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    for sensor_name, table in sensor_data.items():
        table.to_csv(output_folder / f"{sensor_name}.csv", index=False)

    metrics.to_csv(output_folder / "metrics.csv", index=False)

def export_injection(sensor_data, sensor_roles, wavelength_nm, path):
    """Save sensor signals side by side, retaining individual time vectors."""
    columns = {
        "time_from_start_s": "t",
        str(wavelength_nm): "raw",
        "absorption_adc": "abs",
        "normalized_0_1": "norm",
    }

    tables = []

    for sensor, role in sensor_roles.items():
        table = sensor_data[sensor][list(columns)].copy()
        table = table.reset_index(drop=True)
        table.columns = [
            f"{name}_{role}" for name in columns.values()
        ]
        tables.append(table)

    exported = pd.concat(tables, axis=1)

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    exported.to_csv(path, index=False)

def export_injection_info(
    normalized_injections,
    injections,
    sensor_roles,
    protocol_metadata,
    reference_window,
    data_dir,
    wavelength_nm,
    window_s,
    baseline_window_s,
    path,
):
    """Document metadata, references, baselines, and exported samples."""
    first_injection = next(iter(normalized_injections.values()))

    lines = [
        "TECHNICAL INFORMATION",
        "=====================",
        f"Experiment: {protocol_metadata['experiment_name']}",
        f"Batch: {protocol_metadata['batch_number']}",
        f"Protocol start: {protocol_metadata['start_time']}",
        f"Source folder: {data_dir}",
        f"Wavelength: {wavelength_nm} nm",
        f"Sample window: 0 <= t < {window_s:g} s after injection",
        f"Baseline: median of {baseline_window_s:g} s before each injection",
        "",
        "SENSOR / OUTLET MAPPING",
        "======================",
    ]

    for sensor, role in sensor_roles.items():
        software_id = first_injection[sensor]["sensor"].iloc[0]
        lines.append(
            f"{role}: {sensor}, software ID {software_id}"
        )

    lines.extend([
        "",
        "100 % REFERENCE",
        "===============",
        "Method: absolute minimum within the selected reference window",
        "Reference values are shared across injections.",
        "Times below are relative to the reference window start.",
    ])

    for sensor, role in sensor_roles.items():
        table = reference_window[sensor]
        signal = pd.to_numeric(
            table[str(wavelength_nm)], errors="coerce"
        ).dropna()
        minimum_index = signal.idxmin()
        minimum_time = table.loc[minimum_index, "time_from_start_s"]
        reference = first_injection[sensor]["reference_adc_100pct"].iloc[0]

        lines.append(
            f"{role}: reference={reference:g} ADC; "
            f"window minimum={signal.min():g} ADC; "
            f"time of minimum={minimum_time:.3f} s"
        )

    lines.extend([
        "",
        "BASELINES PER SAMPLE",
        "====================",
    ])

    samples = []

    for injection in injections.itertuples(index=False):
        condition = (
            f"{injection.volume_ul}R"
            if injection.magnet == "off"
            else str(injection.volume_ul)
        )
        name = f"E02_{condition}_AB_{injection.replicate}"
        sensors = normalized_injections[injection.marker_index]

        baselines = [
            f"{role}={sensors[sensor]['baseline_adc'].iloc[0]:g} ADC"
            for sensor, role in sensor_roles.items()
        ]
        lines.append(f"{name}: " + ", ".join(baselines))

        samples.append(
            f"{name} | marker index={injection.marker_index} | "
            f"rep={injection.replicate} | "
            f"V={injection.volume_ul:g} µL | "
            f"magnet={injection.magnet} | "
            f"{injection.label} | {name}.csv"
        )

    lines.extend([
        "",
        "SIGNALS AND FORMULAS",
        "====================",
        "raw_X(t) = measured intensity I_X(t) [ADC counts]",
        "abs_X(t) = baseline_X - raw_X(t) [ADC counts]",
        "norm_X(t) = abs_X(t) / (baseline_X - reference_X) [-]",
        "X is A, B, or Ref.",
        "Normalized signal change is not a concentration estimate.",
        "",
        "CSV COLUMNS",
        "===========",
        "t_A,raw_A,abs_A,norm_A,"
        "t_B,raw_B,abs_B,norm_B,"
        "t_Ref,raw_Ref,abs_Ref,norm_Ref",
        "Time columns: seconds after the injection marker.",
        "Each sensor retains its original time vector; no interpolation.",
        "Shorter columns are padded with empty fields.",
        "Separator: comma; decimal: point; encoding: UTF-8.",
        "No row index is exported.",
        "",
        "PLOT RECONSTRUCTION",
        "===================",
        "Raw signal: raw_X versus t_X.",
        "Baseline-corrected signal: abs_X versus t_X.",
        "Normalized signal: norm_X versus t_X.",
        "",
        "SAMPLES",
        "=======",
        "Marker labels are retained as recorded.",
        "Injection-rate units in marker labels have not been verified.",
        *samples,
        "",
        f"Exported CSV files: {len(injections)}",
    ])

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")