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