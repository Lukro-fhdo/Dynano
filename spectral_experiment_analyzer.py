"""Übersichtliche Auswertung von Spektralsensor-Experimenten.

Die Klasse ist auf Messordner im folgenden Format ausgelegt::

    Experimentordner/
    ├── Protocol.md
    ├── Markers_<zeitstempel>.csv
    ├── Spectralsensor 1_<zeitstempel>.csv
    ├── Spectralsensor 2_<zeitstempel>.csv
    └── Spectralsensor 3_<zeitstempel>.csv

Typischer Einstieg::

    from spectral_experiment_analyzer import SpectralExperimentAnalyzer

    run = SpectralExperimentAnalyzer("Data/E02_C20x15_50_static_test")
    run.overview()
    run.check()
    run.plot_raw(640, start_step=3)
    stats = run.injection_statistics(640, window_s=50)

Die Implementierung fasst die wiederverwendbaren Teile des ursprünglichen
Jupyter Notebooks zusammen: robuster Import, gemeinsame Zeitachse, Marker-
fenster, Kennwerte, Rohdatenplots sowie exponentielle und affine calibration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Optional, Sequence

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

# Legacy entry point at repository root; the implementation lives under src/.
from src.spectral_sensor import io as experiment_io

try:  # SciPy wird nur für das Fitten benötigt.
    from scipy.optimize import curve_fit, least_squares
except ImportError:  # pragma: no cover - nur relevant in Minimalumgebungen
    curve_fit = None
    least_squares = None


_NUMBER_COLUMN = re.compile(r"^\d+$")
_STEP_PATTERN = re.compile(r"STEP\s*[_-]?\s*(\d+)", re.IGNORECASE)
_FLOAT_PATTERN = r"([0-9]+(?:[.,][0-9]+)?)"


@dataclass
class CalibrationModel:
    """Serialisierbares calibrationmodell für einen sensor und eine wavelength."""

    model_type: str
    sensor_id: int
    wavelength_nm: int
    parameters: dict[str, float]
    valid_range_pct: tuple[float, float] = (0.0, 100.0)
    fit_metrics: dict[str, float] = field(default_factory=dict)
    source: str = ""
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def intensity(self, concentration_pct: Any) -> np.ndarray:
        """Berechnet I(c) für die unterstützten Vorwärtsmodelle."""
        c = np.asarray(concentration_pct, dtype=float)
        p = self.parameters

        if self.model_type == "exponential":
            return p["I0"] * np.exp(-p["alpha"] * c)
        if self.model_type == "offset_exponential":
            return p["I_inf"] + (p["I0"] - p["I_inf"]) * np.exp(
                -p["alpha"] * c
            )
        if self.model_type == "affine_0_100":
            return p["I_0pct"] - (c / 100.0) * (p["I_0pct"] - p["I_100pct"])
        if self.model_type == "log_poly":
            raise ValueError("log_poly ist ein reines Rückrechnungsmodell c(I).")
        raise ValueError(f"Unbekannter Modelltyp: {self.model_type}")

    def concentration(
        self,
        intensity: Any,
        *,
        clip: bool = True,
    ) -> np.ndarray:
        """Rechnet ADC-Werte in concentration [%] zurück."""
        intensity_array = np.asarray(intensity, dtype=float)
        p = self.parameters

        if self.model_type == "exponential":
            ratio = np.clip(intensity_array / p["I0"], 1e-12, None)
            result = -np.log(ratio) / p["alpha"]
        elif self.model_type == "offset_exponential":
            denominator = p["I0"] - p["I_inf"]
            ratio = np.clip(
                (intensity_array - p["I_inf"]) / max(denominator, 1e-12),
                1e-12,
                None,
            )
            result = -np.log(ratio) / p["alpha"]
        elif self.model_type == "affine_0_100":
            denominator = p["I_0pct"] - p["I_100pct"]
            if abs(denominator) < 1e-12:
                result = np.full_like(intensity_array, np.nan, dtype=float)
            else:
                result = 100.0 * (p["I_0pct"] - intensity_array) / denominator
        elif self.model_type == "log_poly":
            coeffs = np.asarray(p["coefficients"], dtype=float)
            result = np.polyval(coeffs, np.log(np.clip(intensity_array, 1e-12, None)))
        else:
            raise ValueError(f"Unbekannter Modelltyp: {self.model_type}")

        if clip:
            result = np.clip(result, *self.valid_range_pct)
        return result

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["valid_range_pct"] = list(self.valid_range_pct)
        return data

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "CalibrationModel":
        values = dict(data)
        values["valid_range_pct"] = tuple(values.get("valid_range_pct", (0, 100)))
        return cls(**values)


class SpectralExperimentAnalyzer:
    """Lädt und analysiert einen vollständigen Spektralsensor-Messordner.

    Parameters
    ----------
    folder:
        folder mit ``Protocol.md``, ``Markers*.csv`` und den sensor-CSV-files.
    sensor_roles:
        Optionale Zuordnung ``{sensor_id: rolle}``. Standardmäßig werden die
        verwendeten IDs 1001/1000/1002 als upstream/downstream/reference
        bezeichnet. Dabei entspricht sensor 1001 Outlet A und sensor 1000
        Outlet B. Unbekannte IDs erhalten ``sensor_<id>``.
    auto_load:
        Lädt die Daten direkt beim Erzeugen des Objekts.
    """

    DEFAULT_SENSOR_ROLES = {
        1000: "downstream",
        1001: "upstream",
        1002: "reference",
    }

    DEFAULT_SENSOR_OUTLETS = {
        1000: "B",  # downstream
        1001: "A",  # upstream
        1002: "reference",
    }

    # Farbenblindfreundliche Okabe-Ito-Palette. Farbe und Linienstil werden
    # gemeinsam verwendet, damit die Kurven auch in Graustufen unterscheidbar
    # bleiben. Hier kannst du die Darstellung zentral anpassen.
    DEFAULT_SENSOR_STYLES = {
        # Aktuelle Rollenbezeichnungen
        "Branch A": {
            "color": "#0072B2",      # Blau
            "linestyle": "-",
            "linewidth": 1.7,
        },
        "Branch B": {
            "color": "#D55E00",      # Vermillion/Orange
            "linestyle": "--",
            "linewidth": 1.7,
        },
        "Reference": {
            "color": "#009E73",      # Bluish green
            "linestyle": "-.",
            "linewidth": 1.7,
        },
        # Legacy-Bezeichnungen bleiben kompatibel
        "upstream": {
            "color": "#0072B2",
            "linestyle": "-",
            "linewidth": 1.7,
        },
        "downstream": {
            "color": "#D55E00",
            "linestyle": "--",
            "linewidth": 1.7,
        },
        "reference": {
            "color": "#009E73",
            "linestyle": "-.",
            "linewidth": 1.7,
        },
    }

    DEFAULT_FALLBACK_SENSOR_STYLE = {
        "color": "#666666",
        "linestyle": ":",
        "linewidth": 1.5,
    }

    def __init__(
        self,
        folder: str | Path,
        *,
        sensor_roles: Optional[Mapping[int, str]] = None,
        auto_load: bool = True,
    ) -> None:
        self.folder = Path(folder).expanduser().resolve()
        self._roles_were_provided = sensor_roles is not None
        self.sensor_roles = {
            **self.DEFAULT_SENSOR_ROLES,
            **{int(k): str(v) for k, v in (sensor_roles or {}).items()},
        }

        self.files: dict[str, Any] = {}
        self.metadata: dict[str, Any] = {}
        self.sensors: dict[int, pd.DataFrame] = {}
        self.sensor_files: dict[int, Path] = {}
        self.markers = pd.DataFrame()
        self.t0_raw_ms: Optional[float] = None
        self.wavelengths: list[int] = []
        self.calibration_models: dict[int, CalibrationModel] = {}

        if auto_load:
            self.load()

    # ------------------------------------------------------------------
    # Import und Aufbereitung
    # ------------------------------------------------------------------
    def load(self) -> "SpectralExperimentAnalyzer":
        """Erkennt, lädt und synchronisiert alle Experimentdateien."""
        if not self.folder.exists():
            raise FileNotFoundError(f"Messordner nicht gefunden: {self.folder}")

        self.files = self._discover_files()
        self.metadata = self._read_protocol(self.files.get("protocol"))
        self.markers = self._read_markers(self.files["markers"])
        self.sensors = {}
        self.sensor_files = {}

        for path in self.files["sensors"]:
            frame = self._read_sensor(path)
            ids = frame["sensor_id"].dropna().astype(int).unique().tolist()
            if not ids:
                raise ValueError(f"Keine sensor-ID in {path.name} gefunden.")

            # Falls künftig mehrere IDs in einer file stehen, werden sie sauber getrennt.
            for sensor_id in ids:
                part = frame.loc[frame["sensor_id"] == sensor_id].copy()
                if sensor_id in self.sensors:
                    self.sensors[sensor_id] = pd.concat(
                        [self.sensors[sensor_id], part], ignore_index=True
                    ).sort_values("timestamp_raw_ms")
                else:
                    self.sensors[sensor_id] = part
                self.sensor_files[sensor_id] = path

        self._synchronize_time()
        self._detect_wavelengths()
        return self

    def _discover_files(self) -> dict[str, Any]:
        return experiment_io.discover_files(self.folder)

    @staticmethod
    def _read_sensor(path: Path) -> pd.DataFrame:
        frame = experiment_io.read_sensor_csv(path)
        frame.columns = [str(column).strip() for column in frame.columns]

        rename = {}
        if "device" in frame.columns and "sensor" not in frame.columns:
            rename["device"] = "sensor"
        frame = frame.rename(columns=rename)

        required = {"sensor", "timestamp"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"Fehlende Spalten in {path.name}: {sorted(missing)}")

        frame["sensor_id"] = pd.to_numeric(frame["sensor"], errors="coerce").astype(
            "Int64"
        )
        frame["timestamp_raw_ms"] = pd.to_numeric(
            frame["timestamp"], errors="coerce"
        )

        spectral_columns = [c for c in frame.columns if _NUMBER_COLUMN.fullmatch(c)]
        for column in spectral_columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")

        frame = frame.dropna(subset=["sensor_id", "timestamp_raw_ms"]).copy()
        return frame.drop(columns=["sensor", "timestamp"], errors="ignore")

    @staticmethod
    def _read_markers(path: Path) -> pd.DataFrame:
        """Liest Marker ohne Header-Annahme und trennt nur die ersten 2 Kommas."""
        frame = experiment_io.read_marker_rows(path)

        parsed = frame["label"].apply(SpectralExperimentAnalyzer._parse_marker_label)
        parsed_frame = pd.DataFrame(parsed.tolist(), index=frame.index)
        frame = pd.concat([frame, parsed_frame], axis=1)
        frame["step"] = pd.to_numeric(frame["step"], errors="coerce").astype("Int64")

        # Zustände gelten ab dem Marker bis zur nächsten Umschaltung.
        frame["magnet_state"] = frame["magnet_event"].ffill().fillna("unknown")
        return frame.sort_values("timestamp_raw_ms", na_position="last").reset_index(
            drop=True
        )

    @staticmethod
    def _parse_marker_label(label: str) -> dict[str, Any]:
        text = str(label).strip()
        lower = text.lower()

        step_match = _STEP_PATTERN.search(text)
        step = int(step_match.group(1)) if step_match else None
        description = text.split(":", 1)[1].strip() if ":" in text else text

        if "inject" in lower:
            action = "inject"
        elif "move robot" in lower:
            action = "move_robot"
        elif "start peristaltic" in lower:
            action = "start_peristaltic"
        elif "stop" in lower:
            action = "stop"
        elif "wait" in lower or "warte" in lower:
            action = "wait"
        elif "start sensor" in lower:
            action = "start_sensor"
        else:
            action = "other"

        volume_match = re.search(_FLOAT_PATTERN + r"\s*(?:u|µ)l\b", text, re.IGNORECASE)
        injection_rate_match = re.search(
            r"@\s*" + _FLOAT_PATTERN + r"\s*(?:u|µ)l\s*/\s*min",
            text,
            re.IGNORECASE,
        )
        peristaltic_match = re.search(
            _FLOAT_PATTERN + r"\s*ml\s*/\s*min", text, re.IGNORECASE
        )
        wait_match = re.search(
            _FLOAT_PATTERN + r"\s*min\b", text, re.IGNORECASE
        )
        position_match = re.search(
            r"move\s+robot\s+to\s+([^@()]+)", text, re.IGNORECASE
        )

        magnet_event: Optional[str] = None
        if re.search(r"(?:magnet\s+on|_on\b|\bon\s*\))", lower):
            magnet_event = "on"
        elif re.search(r"(?:no\s+magnet|magnet\s+off|_off\b)", lower):
            magnet_event = "off"

        return {
            "step": step,
            "description": description,
            "action": action,
            "volume_ul": SpectralExperimentAnalyzer._match_float(volume_match),
            "injection_rate_ul_min": SpectralExperimentAnalyzer._match_float(
                injection_rate_match
            ),
            "peristaltic_rate_ml_min": SpectralExperimentAnalyzer._match_float(
                peristaltic_match
            ),
            "wait_min": SpectralExperimentAnalyzer._match_float(wait_match),
            "robot_position": position_match.group(1).strip()
            if position_match
            else None,
            "magnet_event": magnet_event,
        }

    @staticmethod
    def _match_float(match: Optional[re.Match[str]]) -> Optional[float]:
        if not match:
            return None
        return float(match.group(1).replace(",", "."))

    @staticmethod
    def _read_protocol(path: Optional[Path]) -> dict[str, Any]:
        return experiment_io.read_protocol(path)

    def _synchronize_time(self) -> None:
        starts = [
            float(frame["timestamp_raw_ms"].min())
            for frame in self.sensors.values()
            if not frame.empty
        ]
        marker_start = pd.to_numeric(
            self.markers["timestamp_raw_ms"], errors="coerce"
        ).min()
        if pd.notna(marker_start):
            starts.append(float(marker_start))
        if not starts:
            raise ValueError("Kein gültiger timestamp gefunden.")

        self.t0_raw_ms = min(starts)
        for sensor_id, frame in self.sensors.items():
            prepared = frame.sort_values("timestamp_raw_ms").reset_index(drop=True)
            prepared["time_s"] = (
                prepared["timestamp_raw_ms"] - self.t0_raw_ms
            ) / 1000.0
            prepared["time_min"] = prepared["time_s"] / 60.0
            self.sensors[sensor_id] = prepared

        self.markers["time_s"] = (
            self.markers["timestamp_raw_ms"] - self.t0_raw_ms
        ) / 1000.0
        self.markers["time_min"] = self.markers["time_s"] / 60.0

    def _detect_wavelengths(self) -> None:
        wavelength_sets = []
        for frame in self.sensors.values():
            wavelength_sets.append(
                {int(column) for column in frame.columns if _NUMBER_COLUMN.fullmatch(column)}
            )
        self.wavelengths = sorted(set().union(*wavelength_sets)) if wavelength_sets else []

    # ------------------------------------------------------------------
    # Übersicht und Qualitätskontrolle
    # ------------------------------------------------------------------
    def overview(self, *, print_output: bool = True) -> pd.DataFrame:
        """Erzeugt eine kompakte Übersicht je sensor und gibt sie optional aus."""
        rows = []
        for sensor_id, frame in sorted(self.sensors.items()):
            timestamps = frame["timestamp_raw_ms"]
            diffs = timestamps.diff().dropna()
            positive_diffs = diffs[diffs > 0]
            sample_rate = (
                1000.0 / float(positive_diffs.median())
                if not positive_diffs.empty
                else np.nan
            )
            rows.append(
                {
                    "sensor_id": sensor_id,
                    "role": self.role(sensor_id),
                    "file": self.sensor_files[sensor_id].name,
                    "rows": len(frame),
                    "duration_min": float(frame["time_min"].max() - frame["time_min"].min()),
                    "sample_rate_hz": sample_rate,
                    "wavelengths_nm": ", ".join(
                        str(wl) for wl in self._sensor_wavelengths(sensor_id)
                    ),
                }
            )
        result = pd.DataFrame(rows)

        if print_output:
            print(f"Experiment: {self.metadata.get('experiment_name', self.folder.name)}")
            if self.metadata.get("batch_number"):
                print(f"Batch:      {self.metadata['batch_number']}")
            print(f"folder:     {self.folder}")
            print(f"sensors:   {len(self.sensors)}")
            print(f"Marker:     {len(self.markers)}")
            print(f"Steps:      {self._step_summary()}")
            print(f"Kanäle:     {', '.join(map(str, self.wavelengths))} nm")
            print(result.to_string(index=False))
        return result

    def check(self, *, print_output: bool = True) -> pd.DataFrame:
        """Prüft Dateiformat, Zeitachsen, Marker und Sensorüberlappung."""
        checks: list[dict[str, str]] = []

        def add(status: str, check: str, details: str) -> None:
            checks.append({"status": status, "check": check, "details": details})

        add("OK", "Sensordateien", f"{len(self.sensors)} sensor-IDs geload.")
        add("OK", "Markerdatei", self.files["markers"].name)
        add(
            "OK" if self.files.get("protocol") else "WARNUNG",
            "Protokoll",
            self.files["protocol"].name
            if self.files.get("protocol")
            else "Kein Protocol*.md gefunden.",
        )

        add(
            "OK" if self._roles_were_provided else "WARNUNG",
            "Sensorrollen",
            "Explizit übergeben."
            if self._roles_were_provided
            else (
                "Standardzuordnung 1001=upstream/Outlet A, "
                "1000=downstream/Outlet B und 1002=reference verwendet."
            ),
        )

        parse_errors = self.markers["parse_error"].astype(str).str.len().gt(0).sum()
        add(
            "OK" if parse_errors == 0 else "FEHLER",
            "Markerparser",
            f"{parse_errors} fehlerhafte Markerzeile(n).",
        )

        steps = self.markers["step"].dropna().astype(int).tolist()
        if steps:
            unique_steps = sorted(set(steps))
            expected = list(range(unique_steps[0], unique_steps[-1] + 1))
            missing_steps = sorted(set(expected) - set(unique_steps))
            duplicates = sorted({step for step in steps if steps.count(step) > 1})
            status = "OK" if not missing_steps and not duplicates else "WARNUNG"
            add(
                status,
                "Marker-steps",
                f"Bereich {unique_steps[0]}–{unique_steps[-1]}; "
                f"fehlend={missing_steps or 'keine'}, doppelt={duplicates or 'keine'}.",
            )
        else:
            add("FEHLER", "Marker-steps", "Keine STEP-Nummern erkannt.")

        marker_min = self.markers["timestamp_raw_ms"].min()
        marker_max = self.markers["timestamp_raw_ms"].max()

        for sensor_id, frame in sorted(self.sensors.items()):
            timestamp = frame["timestamp_raw_ms"]
            duplicate_count = int(timestamp.duplicated().sum())
            monotonic = bool(timestamp.is_monotonic_increasing)
            missing_values = int(frame[[str(w) for w in self._sensor_wavelengths(sensor_id)]].isna().sum().sum())
            overlaps = bool(timestamp.min() <= marker_max and timestamp.max() >= marker_min)

            add(
                "OK" if monotonic else "FEHLER",
                f"Zeitfolge sensor {sensor_id}",
                "monoton steigend" if monotonic else "nicht monoton steigend",
            )
            add(
                "OK" if duplicate_count == 0 else "WARNUNG",
                f"Doppelte timestamp sensor {sensor_id}",
                str(duplicate_count),
            )
            add(
                "OK" if missing_values == 0 else "WARNUNG",
                f"Fehlwerte sensor {sensor_id}",
                f"{missing_values} Spektralwerte fehlen.",
            )
            add(
                "OK" if overlaps else "FEHLER",
                f"Markerüberlappung sensor {sensor_id}",
                "Zeitbereiche überlappen." if overlaps else "Keine Überlappung.",
            )

        common = set(self.wavelengths)
        for sensor_id in self.sensors:
            common &= set(self._sensor_wavelengths(sensor_id))
        add(
            "OK" if common else "FEHLER",
            "Gemeinsame wavelengthn",
            ", ".join(map(str, sorted(common))) if common else "keine",
        )

        report = pd.DataFrame(checks)
        if print_output:
            print(report.to_string(index=False))
        return report

    def timeline(self, *, print_output: bool = True) -> pd.DataFrame:
        """Liefert die maschinenlesbar aufbereitete Marker-Timeline."""
        columns = [
            "step",
            "time_s",
            "time_min",
            "action",
            "volume_ul",
            "injection_rate_ul_min",
            "peristaltic_rate_ml_min",
            "wait_min",
            "robot_position",
            "magnet_state",
            "description",
        ]
        result = self.markers[columns].copy()
        if print_output:
            print(result.to_string(index=False))
        return result

    def show_timeline(self, *, print_output: bool = True) -> pd.DataFrame:
        """Alias für :meth:`timeline`, passend zur kurzen Notebook-API."""
        return self.timeline(print_output=print_output)

    # ------------------------------------------------------------------
    # Auswahl, Fenster und Kennwerte
    # ------------------------------------------------------------------
    def step_timestamp(self, step: int) -> float:
        """Gibt den ersten Roh-timestamp eines Steps in Millisekunden zurück."""
        matches = self.markers.loc[self.markers["step"] == int(step), "timestamp_raw_ms"]
        matches = pd.to_numeric(matches, errors="coerce").dropna()
        if matches.empty:
            raise KeyError(f"STEP_{step} wurde nicht gefunden. Erkannte Steps: {self.steps}")
        return float(matches.iloc[0])

    @property
    def steps(self) -> list[int]:
        return sorted(self.markers["step"].dropna().astype(int).unique().tolist())

    @property
    def injection_steps(self) -> list[int]:
        return sorted(
            self.markers.loc[
                self.markers["action"] == "inject", "step"
            ].dropna().astype(int).unique().tolist()
        )

    def window(
        self,
        step: int,
        *,
        window_s: float = 50.0,
        offset_s: float = 0.0,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> dict[int, pd.DataFrame]:
        """Schneidet je sensor ein Zeitfenster nach einem Marker aus."""
        start_ms = self.step_timestamp(step) + float(offset_s) * 1000.0
        end_ms = start_ms + float(window_s) * 1000.0
        selected = self._resolve_sensor_ids(sensor_ids)
        result: dict[int, pd.DataFrame] = {}

        for sensor_id in selected:
            frame = self.sensors[sensor_id]
            part = frame.loc[
                (frame["timestamp_raw_ms"] >= start_ms)
                & (frame["timestamp_raw_ms"] < end_ms)
            ].copy()
            part["time_from_marker_s"] = (
                part["timestamp_raw_ms"] - self.step_timestamp(step)
            ) / 1000.0
            result[sensor_id] = part
        return result

    def step_statistics(
        self,
        wavelength: int | str = 640,
        *,
        steps: Optional[Sequence[int]] = None,
        window_s: float = 50.0,
        offset_s: float = 0.0,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> pd.DataFrame:
        """Berechnet Standardkennwerte für definierte Markerfenster."""
        wavelength_name = self._validate_wavelength(wavelength)
        selected_steps = list(steps) if steps is not None else self.steps
        rows: list[dict[str, Any]] = []

        for step in selected_steps:
            marker = self._marker_for_step(step)
            windows = self.window(
                step,
                window_s=window_s,
                offset_s=offset_s,
                sensor_ids=sensor_ids,
            )
            for sensor_id, frame in windows.items():
                values = pd.to_numeric(frame[wavelength_name], errors="coerce")
                valid = frame.loc[values.notna()].copy()
                values = values.dropna().to_numpy(dtype=float)
                if values.size == 0:
                    continue

                relative_time = valid["time_from_marker_s"].to_numpy(dtype=float)
                area = self._trapezoid(values, relative_time)
                rows.append(
                    {
                        "step": int(step),
                        "action": marker.get("action"),
                        "description": marker.get("description"),
                        "magnet_state": marker.get("magnet_state"),
                        "volume_ul": marker.get("volume_ul"),
                        "sensor_id": sensor_id,
                        "role": self.role(sensor_id),
                        "wavelength_nm": int(wavelength_name),
                        "window_s": float(window_s),
                        "offset_s": float(offset_s),
                        "n": int(values.size),
                        "mean": float(np.mean(values)),
                        "median": float(np.median(values)),
                        "std": float(np.std(values, ddof=1)) if values.size > 1 else 0.0,
                        "min": float(np.min(values)),
                        "max": float(np.max(values)),
                        "start": float(values[0]),
                        "end": float(values[-1]),
                        "delta": float(values[-1] - values[0]),
                        "peak_max": float(np.max(values)),
                        "peak_max_time_s": float(relative_time[int(np.argmax(values))]),
                        "peak_min": float(np.min(values)),
                        "peak_min_time_s": float(relative_time[int(np.argmin(values))]),
                        "auc_adc_s": float(area),
                    }
                )

        return pd.DataFrame(rows)

    def injection_statistics(
        self,
        wavelength: int | str = 640,
        *,
        window_s: float = 50.0,
        offset_s: float = 0.0,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> pd.DataFrame:
        """Kurzform für die Statistik aller Injektionsmarker."""
        return self.step_statistics(
            wavelength,
            steps=self.injection_steps,
            window_s=window_s,
            offset_s=offset_s,
            sensor_ids=sensor_ids,
        )

    def injections(
        self,
        wavelength: int | str = 640,
        *,
        window_s: float = 50.0,
        offset_s: float = 0.0,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> pd.DataFrame:
        """Alias für :meth:`injection_statistics`."""
        return self.injection_statistics(
            wavelength,
            window_s=window_s,
            offset_s=offset_s,
            sensor_ids=sensor_ids,
        )

    def compare_conditions(
        self,
        wavelength: int | str = 640,
        *,
        condition: str = "magnet_state",
        window_s: float = 50.0,
        steps: Optional[Sequence[int]] = None,
    ) -> pd.DataFrame:
        """Fasst Injektionsstatistiken nach einer Markerbedingung zusammen."""
        selected_steps = list(steps) if steps is not None else self.injection_steps
        stats = self.step_statistics(
            wavelength, steps=selected_steps, window_s=window_s
        )
        if stats.empty:
            return stats
        if condition not in stats.columns:
            raise KeyError(
                f"Bedingung '{condition}' ist nicht verfügbar. "
                f"Mögliche Spalten: {list(stats.columns)}"
            )

        return (
            stats.groupby([condition, "sensor_id", "role"], dropna=False)
            .agg(
                injections=("step", "nunique"),
                adc_mean=("mean", "mean"),
                adc_std_between_injections=("mean", "std"),
                delta_mean=("delta", "mean"),
                min_mean=("min", "mean"),
                max_mean=("max", "mean"),
            )
            .reset_index()
        )

    # ------------------------------------------------------------------
    # Plotfunktionen
    # ------------------------------------------------------------------
    def plot_raw(
        self,
        wavelength: int | str = 640,
        *,
        start_step: Optional[int] = None,
        end_step: Optional[int] = None,
        sensor_ids: Optional[Iterable[int]] = None,
        show_markers: bool = True,
        time_unit: str = "min",
        ax: Optional[plt.Axes] = None,
    ) -> tuple[plt.Figure, plt.Axes]:
        """Plottet den Rohdatenverlauf mehrerer sensors auf gemeinsamer Zeitachse."""
        wavelength_name = self._validate_wavelength(wavelength)
        if time_unit not in {"s", "min"}:
            raise ValueError("time_unit muss 's' oder 'min' sein.")

        selected = self._resolve_sensor_ids(sensor_ids)
        start_ms = self.step_timestamp(start_step) if start_step is not None else None
        end_ms = self.step_timestamp(end_step) if end_step is not None else None
        origin_ms = start_ms if start_ms is not None else float(self.t0_raw_ms)
        divisor = 1000.0 if time_unit == "s" else 60000.0

        if ax is None:
            fig, ax = plt.subplots(figsize=(12, 5))
        else:
            fig = ax.figure

        for sensor_id in selected:
            frame = self.sensors[sensor_id]
            mask = pd.Series(True, index=frame.index)
            if start_ms is not None:
                mask &= frame["timestamp_raw_ms"] >= start_ms
            if end_ms is not None:
                mask &= frame["timestamp_raw_ms"] < end_ms
            part = frame.loc[mask]
            x = (part["timestamp_raw_ms"] - origin_ms) / divisor
            role = self.role(sensor_id)
            style = self.sensor_style(sensor_id)
            ax.plot(
                x,
                part[wavelength_name],
                color=style["color"],
                linestyle=style["linestyle"],
                linewidth=style["linewidth"],
                label=f"{role} ({sensor_id})",
            )

        if show_markers:
            marker_mask = pd.Series(True, index=self.markers.index)
            if start_ms is not None:
                marker_mask &= self.markers["timestamp_raw_ms"] >= start_ms
            if end_ms is not None:
                marker_mask &= self.markers["timestamp_raw_ms"] < end_ms
            for _, marker in self.markers.loc[marker_mask].iterrows():
                if pd.isna(marker["timestamp_raw_ms"]):
                    continue
                x = (float(marker["timestamp_raw_ms"]) - origin_ms) / divisor
                ax.axvline(x, linestyle=":", linewidth=0.8, alpha=0.45)
                if pd.notna(marker["step"]):
                    ax.text(
                        x,
                        0.98,
                        f"S{int(marker['step'])}",
                        transform=ax.get_xaxis_transform(),
                        ha="center",
                        va="top",
                        fontsize=7,
                    )

        origin_label = f"STEP_{start_step}" if start_step is not None else "Messstart"
        ax.set_xlabel(f"Zeit ab {origin_label} [{time_unit}]")
        ax.set_ylabel(f"ADC @ {wavelength_name} nm")
        ax.set_title(
            f"{self.metadata.get('experiment_name', self.folder.name)} – raw data"
        )
        ax.grid(True, which="major", linewidth=0.45, linestyle=":", alpha=0.22)
        ax.legend(title="sensor", fontsize=8, title_fontsize=8, frameon=False)
        fig.tight_layout()
        return fig, ax

    def plot_step_windows(
        self,
        steps: Sequence[int],
        wavelength: int | str = 640,
        *,
        window_s: float = 50.0,
        sensor_ids: Optional[Iterable[int]] = None,
        calibrated: bool = False,
    ) -> tuple[plt.Figure, np.ndarray]:
        """Zeigt mehrere Markerfenster als je einen Plot pro sensor."""
        wavelength_name = self._validate_wavelength(wavelength)
        selected = self._resolve_sensor_ids(sensor_ids)
        fig, axes = plt.subplots(
            len(selected),
            1,
            figsize=(11, max(3.2, 3.2 * len(selected))),
            sharex=True,
            squeeze=False,
        )
        flat_axes = axes.ravel()

        for axis, sensor_id in zip(flat_axes, selected):
            for step in steps:
                frame = self.window(step, window_s=window_s, sensor_ids=[sensor_id])[
                    sensor_id
                ]
                values = frame[wavelength_name].to_numpy(dtype=float)
                ylabel = f"ADC @ {wavelength_name} nm"
                if calibrated:
                    model = self._require_model(sensor_id, int(wavelength_name))
                    values = model.concentration(values)
                    ylabel = "concentration [%]"
                axis.plot(frame["time_from_marker_s"], values, label=f"STEP_{step}")
            axis.set_ylabel(ylabel)
            axis.set_title(f"{self.role(sensor_id)} ({sensor_id})")
            axis.grid(True, alpha=0.3)
            axis.legend()

        flat_axes[-1].set_xlabel("Zeit ab Marker [s]")
        fig.tight_layout()
        return fig, axes

    def plot_steps(
        self,
        steps: Sequence[int],
        wavelength: int | str = 640,
        *,
        window_s: float = 50.0,
        sensor_ids: Optional[Iterable[int]] = None,
        calibrated: bool = False,
    ) -> tuple[plt.Figure, np.ndarray]:
        """Alias für :meth:`plot_step_windows`."""
        return self.plot_step_windows(
            steps,
            wavelength,
            window_s=window_s,
            sensor_ids=sensor_ids,
            calibrated=calibrated,
        )

    def reference_100pct(
        self,
        wavelength: int | str = 640,
        *,
        reference_injection_step: int = 6,
        method: str = "absolute_min",
        evaluation_offset_s: float = 0.0,
        evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        stability_window_s: float = 5.0,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> pd.DataFrame:
        """Bestimmt den ADC-Wert für 100 % concentration nach einer Injektion.

        Zwei Verfahren stehen zur Verfügung:

        ``method="stable_min"``
            Sucht das Minimum einer geglätteten Kurve und mittelt ein lokales,
            stabiles Fenster um dieses Minimum.

        ``method="absolute_min"``
            Verwendet den kleinsten tatsächlich gemessenen ADC-Einzelwert im
            Suchbereich. Es erfolgt keine Glättung und keine Mittelung.

        Der Suchbereich beginnt relativ zu ``reference_injection_step``. Sein
        Ende wird entweder über ``reference_end_step`` oder über
        ``evaluation_window_s`` festgelegt. Der Standard entspricht dem
        funktionierenden ``BEISPIEL_ABSOLUTES_MINIMUM``: absolutes Minimum
        von STEP_6 bis unmittelbar vor STEP_8.

        Wichtig: Sobald ``reference_end_step`` gesetzt ist, hat dieser Vorrang
        vor ``evaluation_window_s``. Für die feste 20-bis-30-s-Auswertung muss
        ``reference_end_step=None`` bleiben. Der Klassenstandard entspricht
        jedoch bewusst dem funktionierenden Legacy-Beispiel: absolutes Minimum
        von STEP_6 bis unmittelbar vor STEP_8.
        """
        wavelength_name = self._validate_wavelength(wavelength)
        selected = self._resolve_sensor_ids(sensor_ids)
        method = str(method).strip().lower()
        if method not in {"stable_min", "absolute_min"}:
            raise ValueError("method muss 'stable_min' oder 'absolute_min' sein.")
        if evaluation_offset_s < 0:
            raise ValueError("evaluation_offset_s darf nicht negativ sein.")
        if method == "stable_min" and stability_window_s <= 0:
            raise ValueError("stability_window_s muss größer als 0 sein.")

        injection_ms = self.step_timestamp(reference_injection_step)
        start_ms = injection_ms + float(evaluation_offset_s) * 1000.0

        if reference_end_step is not None:
            end_ms = self.step_timestamp(reference_end_step)
            if end_ms <= start_ms:
                raise ValueError(
                    "reference_end_step liegt nicht nach dem Beginn des "
                    "Referenz-Suchbereichs."
                )
            effective_window_s = (end_ms - start_ms) / 1000.0
        else:
            if evaluation_window_s is None or evaluation_window_s <= 0:
                raise ValueError(
                    "Ohne reference_end_step muss evaluation_window_s größer "
                    "als 0 sein."
                )
            effective_window_s = float(evaluation_window_s)
            end_ms = start_ms + effective_window_s * 1000.0

        rows: list[dict[str, Any]] = []
        for sensor_id in selected:
            frame = self.sensors[sensor_id]
            part = frame.loc[
                (frame["timestamp_raw_ms"] >= start_ms)
                & (frame["timestamp_raw_ms"] < end_ms),
                ["timestamp_raw_ms", wavelength_name],
            ].copy()
            part[wavelength_name] = pd.to_numeric(
                part[wavelength_name], errors="coerce"
            )
            part = part.dropna(subset=[wavelength_name])

            base_row = {
                "sensor_id": sensor_id,
                "role": self.role(sensor_id),
                "wavelength_nm": int(wavelength_name),
                "reference_injection_step": int(reference_injection_step),
                "reference_method": method,
                "evaluation_offset_s": float(evaluation_offset_s),
                "evaluation_window_s": float(effective_window_s),
                "reference_end_step": reference_end_step,
                "reference_search_end": (
                    f"STEP_{int(reference_end_step)}"
                    if reference_end_step is not None
                    else f"offset+{float(effective_window_s):g}s"
                ),
                "stability_window_s": (
                    float(stability_window_s) if method == "stable_min" else np.nan
                ),
            }

            if part.empty:
                rows.append(
                    {
                        **base_row,
                        "reference_adc_100pct": np.nan,
                        "absolute_min_adc": np.nan,
                        "stable_min_adc": np.nan,
                        "reference_std_adc": np.nan,
                        "reference_time_s_after_injection": np.nan,
                        "n": 0,
                    }
                )
                continue

            absolute_idx = part[wavelength_name].idxmin()
            absolute_min_adc = float(part.loc[absolute_idx, wavelength_name])
            absolute_min_ms = float(part.loc[absolute_idx, "timestamp_raw_ms"])

            if method == "absolute_min":
                reference_adc = absolute_min_adc
                reference_std = 0.0
                reference_ms = absolute_min_ms
                stable_min_adc = absolute_min_adc
                n_used = 1
            else:
                dt_ms = float(part["timestamp_raw_ms"].diff().median())
                if not np.isfinite(dt_ms) or dt_ms <= 0:
                    dt_ms = 250.0

                smoothing_points = max(
                    3,
                    int(round(float(stability_window_s) * 1000.0 / dt_ms)),
                )
                if smoothing_points % 2 == 0:
                    smoothing_points += 1

                rolling_median = part[wavelength_name].rolling(
                    smoothing_points,
                    center=True,
                    min_periods=max(3, smoothing_points // 2),
                ).median()
                center_idx = (
                    rolling_median.idxmin()
                    if rolling_median.notna().any()
                    else absolute_idx
                )
                reference_ms = float(part.loc[center_idx, "timestamp_raw_ms"])
                half_width_ms = float(stability_window_s) * 500.0
                stable = part.loc[
                    (part["timestamp_raw_ms"] >= reference_ms - half_width_ms)
                    & (part["timestamp_raw_ms"] <= reference_ms + half_width_ms)
                ]
                stable_values = stable[wavelength_name].to_numpy(dtype=float)
                if stable_values.size == 0:
                    stable_values = np.asarray(
                        [float(part.loc[center_idx, wavelength_name])], dtype=float
                    )

                reference_adc = float(np.mean(stable_values))
                reference_std = (
                    float(np.std(stable_values, ddof=1))
                    if stable_values.size > 1
                    else 0.0
                )
                stable_min_adc = float(np.min(stable_values))
                n_used = int(stable_values.size)

            rows.append(
                {
                    **base_row,
                    "reference_adc_100pct": reference_adc,
                    "absolute_min_adc": absolute_min_adc,
                    "stable_min_adc": stable_min_adc,
                    "reference_std_adc": reference_std,
                    "reference_time_s_after_injection": float(
                        (reference_ms - injection_ms) / 1000.0
                    ),
                    "n": n_used,
                }
            )

        return pd.DataFrame(rows)

    def plot_reference_100pct(
        self,
        wavelength: int | str = 640,
        *,
        reference_injection_step: int = 6,
        method: str = "absolute_min",
        plot_window_s: Optional[float] = None,
        evaluation_offset_s: float = 0.0,
        evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        stability_window_s: float = 5.0,
        baseline_window_s: float = 10.0,
        sensor_ids: Optional[Iterable[int]] = None,
        show_reference_window: bool = False,
    ) -> tuple[plt.Figure, np.ndarray]:
        """Visualisiert die Referenz; der Suchbereich ist standardmäßig verborgen."""
        wavelength_name = self._validate_wavelength(wavelength)
        selected = self._resolve_sensor_ids(sensor_ids)
        references = self.reference_100pct(
            wavelength_name,
            reference_injection_step=reference_injection_step,
            method=method,
            evaluation_offset_s=evaluation_offset_s,
            evaluation_window_s=evaluation_window_s,
            reference_end_step=reference_end_step,
            stability_window_s=stability_window_s,
            sensor_ids=selected,
        ).set_index("sensor_id")
        if plot_window_s is None:
            if reference_end_step is not None:
                search_end_s = (
                    self.step_timestamp(reference_end_step)
                    - self.step_timestamp(reference_injection_step)
                ) / 1000.0
                effective_plot_window_s = max(60.0, search_end_s + 5.0)
            else:
                effective_plot_window_s = max(
                    60.0,
                    float(evaluation_offset_s)
                    + float(evaluation_window_s or 0.0)
                    + 5.0,
                )
        else:
            effective_plot_window_s = float(plot_window_s)

        windows = self.window(
            reference_injection_step,
            window_s=effective_plot_window_s,
            sensor_ids=selected,
        )

        fig, axes = plt.subplots(
            len(selected),
            1,
            figsize=(11, max(3.2, 3.0 * len(selected))),
            sharex=True,
            squeeze=False,
        )
        flat_axes = axes.ravel()
        injection_ms = self.step_timestamp(reference_injection_step)
        for axis, sensor_id in zip(flat_axes, selected):
            frame = windows[sensor_id]
            style = self.sensor_style(sensor_id)

            # 0-% calibration baseline: median of the samples directly before
            # the 100-% reference injection.
            sensor_frame = self.sensors[sensor_id]
            baseline_values = pd.to_numeric(
                sensor_frame.loc[
                    (
                        sensor_frame["timestamp_raw_ms"]
                        >= injection_ms - float(baseline_window_s) * 1000.0
                    )
                    & (sensor_frame["timestamp_raw_ms"] < injection_ms),
                    wavelength_name,
                ],
                errors="coerce",
            ).dropna()
            baseline_adc = (
                float(baseline_values.median())
                if not baseline_values.empty
                else np.nan
            )

            axis.plot(
                frame["time_from_marker_s"],
                frame[wavelength_name],
                color=style["color"],
                linestyle="-",
                linewidth=style["linewidth"],
                label=f"{self.role(sensor_id)} ({sensor_id})",
            )

            reference_row = references.loc[sensor_id]
            if show_reference_window:
                window_end = (
                    float(reference_row["evaluation_offset_s"])
                    + float(reference_row["evaluation_window_s"])
                )
                axis.axvspan(
                    float(reference_row["evaluation_offset_s"]),
                    window_end,
                    alpha=0.16,
                    label="100-%-Suchbereich",
                )

            reference_adc = float(reference_row["reference_adc_100pct"])
            reference_time = float(
                reference_row["reference_time_s_after_injection"]
            )

            if np.isfinite(baseline_adc):
                axis.axhline(
                    baseline_adc,
                    color=style["color"],
                    linestyle="--",
                    linewidth=1.0,
                    alpha=0.8,
                    label=f"0 % / baseline = {baseline_adc:.1f} ADC",
                )

            axis.axhline(
                reference_adc,
                color=style["color"],
                linestyle="--",
                linewidth=1.0,
                alpha=0.8,
                label=f"100 % = {reference_adc:.1f} ADC",
            )
            axis.scatter(
                [reference_time],
                [reference_adc],
                color=style["color"],
                edgecolor="white",
                linewidth=0.6,
                s=34,
                zorder=4,
                label=(
                    "absolutes Minimum"
                    if str(method).lower() == "absolute_min"
                    else "stabile Referenz"
                ),
            )
            axis.set_ylabel(f"ADC @ {wavelength_name} nm")
            axis.set_title(f"{self.role(sensor_id)} ({sensor_id})")
            axis.grid(True, which="major", linewidth=0.45, linestyle=":", alpha=0.22)
            axis.legend(fontsize=8, frameon=False)

        flat_axes[-1].set_xlabel(
            f"Zeit ab Referenzinjektion STEP_{reference_injection_step} [s]"
        )
        method_title = (
            "absolutes Minimum"
            if str(method).lower() == "absolute_min"
            else "stabiles Minimum"
        )
        fig.suptitle(f"100-%-Referenz: {method_title}", y=1.01)
        fig.tight_layout()
        return fig, axes

    def normalized_injection_window(
        self,
        step: int,
        wavelength: int | str = 640,
        *,
        window_s: float = 60.0,
        baseline_window_s: float = 10.0,
        reference_injection_step: int = 6,
        reference_method: str = "absolute_min",
        reference_offset_s: float = 0.0,
        reference_evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        reference_stability_window_s: float = 5.0,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> dict[int, pd.DataFrame]:
        """Liefert ein Injektionsfenster mit raw data und 0…1-Normierung.

        ``0`` ist die Median-baseline direkt vor der jeweiligen Injektion.
        ``1`` ist der mit ``reference_method`` bestimmte Wert der
        100-%-Referenzinjektion.
        """
        wavelength_name = self._validate_wavelength(wavelength)
        selected = self._resolve_sensor_ids(sensor_ids)
        references = self.reference_100pct(
            wavelength_name,
            reference_injection_step=reference_injection_step,
            method=reference_method,
            evaluation_offset_s=reference_offset_s,
            evaluation_window_s=reference_evaluation_window_s,
            reference_end_step=reference_end_step,
            stability_window_s=reference_stability_window_s,
            sensor_ids=selected,
        )
        reference_map = references.set_index("sensor_id")[
            "reference_adc_100pct"
        ].to_dict()

        marker_ms = self.step_timestamp(step)
        result: dict[int, pd.DataFrame] = {}
        for sensor_id in selected:
            frame = self.sensors[sensor_id]
            baseline_values = pd.to_numeric(
                frame.loc[
                    (frame["timestamp_raw_ms"] >= marker_ms - baseline_window_s * 1000.0)
                    & (frame["timestamp_raw_ms"] < marker_ms),
                    wavelength_name,
                ],
                errors="coerce",
            ).dropna()
            baseline_adc = (
                float(baseline_values.median())
                if not baseline_values.empty
                else np.nan
            )
            reference_adc = float(reference_map.get(sensor_id, np.nan))
            denominator = baseline_adc - reference_adc

            part = self.window(
                step,
                window_s=window_s,
                sensor_ids=[sensor_id],
            )[sensor_id].copy()
            raw = pd.to_numeric(part[wavelength_name], errors="coerce")
            part["raw_adc"] = raw
            part["baseline_adc"] = baseline_adc
            part["reference_adc_100pct"] = reference_adc
            part["absorption_adc"] = baseline_adc - raw
            part["normalized_0_1"] = (
                (baseline_adc - raw) / denominator
                if np.isfinite(denominator) and abs(denominator) > 1e-12
                else np.nan
            )
            result[sensor_id] = part
        return result

    def injection_plot_metadata(self, step: int) -> dict[str, Any]:
        """Liefert einheitliche Metadaten für Titel und Exportdateinamen."""
        step = int(step)
        marker = self._marker_for_step(step)
        sample_codes: list[str] = []
        replicate: Optional[int] = None
        injection_number: Optional[int] = None

        manifest = getattr(self, "sample_manifest", None)
        if isinstance(manifest, pd.DataFrame) and not manifest.empty and "step" in manifest:
            sample_rows = manifest.loc[
                pd.to_numeric(manifest["step"], errors="coerce") == step
            ].copy()
            if not sample_rows.empty:
                if "label" in sample_rows:
                    sample_codes = sample_rows["label"].dropna().astype(str).tolist()
                if "replicate" in sample_rows and sample_rows["replicate"].notna().any():
                    replicate = int(sample_rows["replicate"].dropna().iloc[0])
                if "injection_number" in sample_rows and sample_rows["injection_number"].notna().any():
                    injection_number = int(sample_rows["injection_number"].dropna().iloc[0])

        volume_ul = (
            float(marker["volume_ul"])
            if pd.notna(marker.get("volume_ul"))
            else np.nan
        )
        rate_ul_min = (
            float(marker["injection_rate_ul_min"])
            if pd.notna(marker.get("injection_rate_ul_min"))
            else np.nan
        )
        magnet_state = str(marker.get("magnet_state") or "unknown")

        if injection_number is None and step in self.injection_steps:
            injection_number = self.injection_steps.index(step) + 1

        if replicate is None and np.isfinite(volume_ul):
            prior = self.markers.loc[
                (self.markers["action"] == "inject")
                & (pd.to_numeric(self.markers["step"], errors="coerce") <= step)
                & np.isclose(
                    pd.to_numeric(self.markers["volume_ul"], errors="coerce"),
                    volume_ul,
                    equal_nan=False,
                )
                & (self.markers["magnet_state"].astype(str) == magnet_state)
            ]
            replicate = int(len(prior)) if len(prior) else None

        return {
            "step": step,
            "sample_codes": sample_codes,
            "volume_ul": volume_ul,
            "injection_rate_ul_min": rate_ul_min,
            "replicate": replicate,
            "injection_number": injection_number,
            "magnet_state": magnet_state,
        }

    def format_injection_plot_title(
        self,
        step: int,
        *,
        title_style: str = "ieee",
        include_sample_codes: bool = True,
        include_step: bool = True,
    ) -> str:
        """Formatiert einen kompakten, wissenschaftlichen Injektionstitel.

        ``title_style="ieee"`` verwendet Größenzeichen, eindeutige units
        und eine kurze zweite Metadatenzeile. ``"samples"`` priorisiert die
        Sample-Codes; ``"step"`` reproduziert den alten STEP-Titel.
        """
        meta = self.injection_plot_metadata(step)
        style = str(title_style).strip().lower()
        if style not in {"ieee", "samples", "step"}:
            raise ValueError("title_style muss 'ieee', 'samples' oder 'step' sein.")

        if style == "step":
            return f"STEP_{meta['step']}"

        volume = (
            f"{meta['volume_ul']:g}"
            if np.isfinite(meta["volume_ul"])
            else "n/a"
        )
        rate = (
            f"{meta['injection_rate_ul_min']:g}"
            if np.isfinite(meta["injection_rate_ul_min"])
            else "n/a"
        )
        replicate = (
            str(meta["replicate"])
            if meta["replicate"] is not None
            else "n/a"
        )
        scientific_line = (
            rf"$V_{{\mathrm{{inj}}}}={volume}\,\mu\mathrm{{L}}$, "
            rf"$Q_{{\mathrm{{inj}}}}={rate}\,\mu\mathrm{{L}}\,\mathrm{{min}}^{{-1}}$, "
            f"replicate {replicate}"
        )

        details: list[str] = []
        display_sample_code = ""
        if meta["sample_codes"]:
            first_code = str(meta["sample_codes"][0])
            replicate_token = str(meta["replicate"]) if meta["replicate"] is not None else r"\d+"
            display_sample_code = re.sub(
                rf"_[AB]_{replicate_token}$",
                f"_AB_{meta['replicate']}",
                first_code,
                flags=re.IGNORECASE,
            )
        if include_sample_codes and display_sample_code:
            details.append("Sample pair: " + display_sample_code)
        details.append(f"magnet {meta['magnet_state']}")
        if include_step:
            details.append(f"STEP_{meta['step']}")
        detail_line = " | ".join(details)

        if style == "samples" and display_sample_code:
            return "Sample pair: " + display_sample_code + "\n" + scientific_line
        return scientific_line + ("\n" + detail_line if detail_line else "")

    def _injection_export_stem(
        self,
        step: int,
        wavelength: int | str,
        *,
        filename_mode: str = "metadata",
    ) -> str:
        """Erzeugt reproduzierbare, dateisystemsichere Plotdateinamen."""
        meta = self.injection_plot_metadata(step)
        mode = str(filename_mode).strip().lower()
        if mode not in {"metadata", "samples", "step"}:
            raise ValueError("filename_mode muss 'metadata', 'samples' oder 'step' sein.")

        if mode == "samples" and meta["sample_codes"]:
            prefix = "__".join(meta["sample_codes"])
        elif mode == "step":
            prefix = f"STEP_{meta['step']:02d}"
        else:
            volume = f"{meta['volume_ul']:g}uL" if np.isfinite(meta["volume_ul"]) else "unknown-volume"
            rate = (
                f"{meta['injection_rate_ul_min']:g}uL-min"
                if np.isfinite(meta["injection_rate_ul_min"])
                else "unknown-rate"
            )
            replicate = f"rep{meta['replicate']}" if meta["replicate"] is not None else "repNA"
            prefix = f"STEP_{meta['step']:02d}_{volume}_{rate}_{replicate}"

        safe = re.sub(r"[^A-Za-z0-9_.-]+", "-", prefix).strip("-")
        return f"{safe}_{int(wavelength)}nm"

    def sample_timeseries_data(
        self,
        step: int,
        wavelength: int | str = 640,
        *,
        window_s: float = 60.0,
        baseline_window_s: float = 10.0,
        reference_injection_step: int = 6,
        reference_method: str = "absolute_min",
        reference_offset_s: float = 0.0,
        reference_evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        reference_stability_window_s: float = 5.0,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> pd.DataFrame:
        """Erzeugt eine verlustfreie Long-Format-Tabelle für eine Injektion.

        Jede Zeile ist ein originaler sensor-Messpunkt. Es findet keine
        zeitliche Interpolation zwischen sensors statt. Zusätzlich zu den
        Rohwerten werden die baseline-korrigierte absolute Absorption in
        ADC-Counts und die dimensionslose 0…1-Normierung ausgegeben.
        """
        wavelength_name = self._validate_wavelength(wavelength)
        windows = self.normalized_injection_window(
            int(step),
            wavelength_name,
            window_s=window_s,
            baseline_window_s=baseline_window_s,
            reference_injection_step=reference_injection_step,
            reference_method=reference_method,
            reference_offset_s=reference_offset_s,
            reference_evaluation_window_s=reference_evaluation_window_s,
            reference_end_step=reference_end_step,
            reference_stability_window_s=reference_stability_window_s,
            sensor_ids=sensor_ids,
        )
        meta = self.injection_plot_metadata(int(step))
        marker = self._marker_for_step(int(step))
        rows: list[pd.DataFrame] = []
        for sensor_id, frame in windows.items():
            part = pd.DataFrame({
                "timestamp_raw_ms": pd.to_numeric(
                    frame["timestamp_raw_ms"], errors="coerce"
                ),
                "time_from_injection_s": pd.to_numeric(
                    frame["time_from_marker_s"], errors="coerce"
                ),
                "raw_adc": pd.to_numeric(frame["raw_adc"], errors="coerce"),
                "baseline_adc": pd.to_numeric(
                    frame["baseline_adc"], errors="coerce"
                ),
                "reference_adc_100pct": pd.to_numeric(
                    frame["reference_adc_100pct"], errors="coerce"
                ),
                "absolute_absorption_adc": pd.to_numeric(
                    frame["absorption_adc"], errors="coerce"
                ),
                "normalized_absorption_0_1": pd.to_numeric(
                    frame["normalized_0_1"], errors="coerce"
                ),
            })
            part.insert(0, "role", self.role(sensor_id))
            part.insert(0, "sensor_id", int(sensor_id))
            rows.append(part)

        result = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
        if result.empty:
            return result

        common_metadata = {
            "experiment": self.metadata.get("experiment_name", self.folder.name),
            "batch_number": self.metadata.get("batch_number"),
            "step": int(step),
            "injection_number": meta.get("injection_number"),
            "replicate": meta.get("replicate"),
            "volume_ul": meta.get("volume_ul"),
            "injection_rate_ul_min": meta.get("injection_rate_ul_min"),
            "magnet_state": marker.get("magnet_state"),
            "wavelength_nm": int(wavelength_name),
            "reference_method": str(reference_method),
            "reference_injection_step": int(reference_injection_step),
            "reference_offset_s": float(reference_offset_s),
            "reference_end_step": reference_end_step,
        }
        for name, value in reversed(list(common_metadata.items())):
            result.insert(0, name, value)
        return result

    def _selected_analysis_steps(
        self,
        steps: Optional[Sequence[int]],
        reference_injection_step: int,
    ) -> list[int]:
        """Ermittelt Sample-Steps aus expliziter Auswahl oder Manifest."""
        if steps is not None:
            return sorted({int(step) for step in steps})

        manifest = getattr(self, "sample_manifest", None)
        if (
            isinstance(manifest, pd.DataFrame)
            and not manifest.empty
            and "step" in manifest.columns
        ):
            return sorted(
                pd.to_numeric(manifest["step"], errors="coerce")
                .dropna()
                .astype(int)
                .unique()
                .tolist()
            )
        return [
            int(step)
            for step in self.injection_steps
            if int(step) != int(reference_injection_step)
        ]

    def _sample_rows_for_step(self, step: int) -> pd.DataFrame:
        """Liefert Manifestzeilen eines Steps oder eine neutrale Ersatzzeile."""
        manifest = getattr(self, "sample_manifest", None)
        if (
            isinstance(manifest, pd.DataFrame)
            and not manifest.empty
            and "step" in manifest.columns
        ):
            rows = manifest.loc[
                pd.to_numeric(manifest["step"], errors="coerce") == int(step)
            ].copy()
            if not rows.empty:
                return rows

        meta = self.injection_plot_metadata(int(step))
        return pd.DataFrame([{
            "label": f"STEP_{int(step):02d}",
            "sample_no": np.nan,
            "outlet": np.nan,
            "replicate": meta.get("replicate"),
            "volume_ul": meta.get("volume_ul"),
            "injection_rate_ul_min": meta.get("injection_rate_ul_min"),
            "magnet_state": meta.get("magnet_state"),
        }])

    def outlet_for_sensor(self, sensor_id: int) -> str:
        """Ordnet sensors den physikalischen Outlets zu."""
        sensor_id = int(sensor_id)
        if sensor_id in self.DEFAULT_SENSOR_OUTLETS:
            return self.DEFAULT_SENSOR_OUTLETS[sensor_id]
        role = self.role(sensor_id).lower()
        if role == "upstream":
            return "A"
        if role == "downstream":
            return "B"
        return "reference" if role == "reference" else ""

    def _paired_sample_metadata(self, step: int) -> dict[str, Any]:
        """Fasst die A/B-Manifestzeilen einer Injektion zu einem Datensatz zusammen."""
        rows = self._sample_rows_for_step(int(step))
        plot_meta = self.injection_plot_metadata(int(step))
        marker = self._marker_for_step(int(step))

        labels = [
            str(value)
            for value in rows.get("label", pd.Series(dtype=str)).dropna().tolist()
        ]
        outlets = [
            str(value)
            for value in rows.get("outlet", pd.Series(dtype=str)).dropna().tolist()
        ]
        replicate_values = pd.to_numeric(
            rows.get("replicate", pd.Series(dtype=float)), errors="coerce"
        ).dropna()
        replicate = (
            int(replicate_values.iloc[0])
            if not replicate_values.empty
            else plot_meta.get("replicate")
        )

        if labels:
            first_label = labels[0]
            first_outlet = outlets[0] if outlets else ""
            suffix = f"_{first_outlet}_{replicate}" if replicate is not None else ""
            if suffix and first_label.endswith(suffix):
                pair_code = first_label[: -len(suffix)] + f"_AB_{replicate}"
            else:
                pair_code = f"STEP_{int(step):02d}_AB_rep{replicate or 'NA'}"
        else:
            pair_code = f"STEP_{int(step):02d}_AB_rep{replicate or 'NA'}"

        def first_value(column: str, fallback: Any = np.nan) -> Any:
            if column in rows.columns:
                values = rows[column].dropna()
                if not values.empty:
                    return values.iloc[0]
            return fallback

        return {
            "pair_code": pair_code,
            "sample_codes": labels,
            "step": int(step),
            "replicate": replicate,
            "volume_ul": first_value("volume_ul", plot_meta.get("volume_ul")),
            "injection_rate_ul_min": first_value(
                "injection_rate_ul_min", plot_meta.get("injection_rate_ul_min")
            ),
            "magnet_state": first_value(
                "magnet_state", marker.get("magnet_state")
            ),
        }

    @staticmethod
    def _safe_file_token(value: Any) -> str:
        return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-")

    def export_sample_csv(
        self,
        output_folder: str | Path,
        wavelength: int | str = 640,
        *,
        steps: Optional[Sequence[int]] = None,
        window_s: float = 60.0,
        baseline_window_s: float = 10.0,
        reference_injection_step: int = 6,
        reference_method: str = "absolute_min",
        reference_offset_s: float = 0.0,
        reference_evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        reference_stability_window_s: float = 5.0,
        sensor_ids: Optional[Iterable[int]] = None,
        include_normalized: bool = True,
        include_combined_files: bool = False,
    ) -> Path:
        """Exportiert eine CSV je Injektion/Wiederholung mit A und B gemeinsam.

        Die Ablage folgt dem Wide-Format für Forschungsdaten: eine Beobachtung
        (Injektion/Wiederholung) entspricht einer file, die physikalischen
        Kanäle stehen als getrennte Spalten nebeneinander.

        Sensorzuordnung:
            - sensor 1001: upstream, Outlet A
            - sensor 1000: downstream, Outlet B
            - sensor 1002: reference

        Beispiel::

            sample_csv/
            ├── info.txt
            ├── E02_50R_AB_1.csv
            └── E02_50_AB_1.csv

        Jeder sensor besitzt eine eigene Zeitspalte, da keine Interpolation der
        Originaldaten vorgenommen wird. Die kompakten Spalten heißen
        ``t_A/raw_A/abs_A/norm_A``, entsprechend für B und Ref.
        ``include_combined_files`` bleibt nur aus Kompatibilitätsgründen als
        wirkungsloser parameter erhalten.
        """
        output = Path(output_folder)
        sample_root = output / "sample_csv"
        sample_root.mkdir(parents=True, exist_ok=True)

        selected_steps = self._selected_analysis_steps(
            steps, reference_injection_step
        )
        reference_table = self.reference_100pct(
            wavelength,
            reference_injection_step=reference_injection_step,
            method=reference_method,
            evaluation_offset_s=reference_offset_s,
            evaluation_window_s=reference_evaluation_window_s,
            reference_end_step=reference_end_step,
            stability_window_s=reference_stability_window_s,
            sensor_ids=sensor_ids,
        )

        sample_lines: list[str] = []
        baseline_lines: list[str] = []
        exported_files: list[str] = []
        for step in selected_steps:
            data = self.sample_timeseries_data(
                int(step),
                wavelength,
                window_s=window_s,
                baseline_window_s=baseline_window_s,
                reference_injection_step=reference_injection_step,
                reference_method=reference_method,
                reference_offset_s=reference_offset_s,
                reference_evaluation_window_s=reference_evaluation_window_s,
                reference_end_step=reference_end_step,
                reference_stability_window_s=reference_stability_window_s,
                sensor_ids=sensor_ids,
            )
            if data.empty:
                continue

            pair = self._paired_sample_metadata(int(step))
            wide_sensor_frames: list[pd.DataFrame] = []
            available_sensor_ids = set(data["sensor_id"].dropna().astype(int).unique())
            for sensor_id in [
                sid for sid in self._resolve_sensor_ids(sensor_ids)
                if sid in available_sensor_ids
            ]:
                sensor_data = data.loc[data["sensor_id"] == sensor_id].copy()
                sensor_data = sensor_data.sort_values("time_from_injection_s")
                outlet = self.outlet_for_sensor(sensor_id)
                if outlet == "A":
                    token = "A"
                elif outlet == "B":
                    token = "B"
                elif self.role(sensor_id).lower() == "reference":
                    token = "Ref"
                else:
                    token = f"S{int(sensor_id)}"

                columns: dict[str, pd.Series] = {
                    f"t_{token}": pd.to_numeric(
                        sensor_data["time_from_injection_s"], errors="coerce"
                    ).reset_index(drop=True),
                    f"raw_{token}": pd.to_numeric(
                        sensor_data["raw_adc"], errors="coerce"
                    ).reset_index(drop=True),
                    f"abs_{token}": pd.to_numeric(
                        sensor_data["absolute_absorption_adc"], errors="coerce"
                    ).reset_index(drop=True),
                }
                if include_normalized:
                    columns[f"norm_{token}"] = pd.to_numeric(
                        sensor_data["normalized_absorption_0_1"], errors="coerce"
                    ).reset_index(drop=True)
                wide_sensor_frames.append(pd.DataFrame(columns))

            if not wide_sensor_frames:
                continue

            baseline_values: dict[str, float] = {}
            for sensor_id in self._resolve_sensor_ids(sensor_ids):
                sensor_data = data.loc[data["sensor_id"] == sensor_id]
                if sensor_data.empty:
                    continue
                outlet = self.outlet_for_sensor(sensor_id)
                if outlet == "A":
                    token = "A"
                elif outlet == "B":
                    token = "B"
                elif self.role(sensor_id).lower() == "reference":
                    token = "Ref"
                else:
                    token = f"S{int(sensor_id)}"
                values = pd.to_numeric(sensor_data["baseline_adc"], errors="coerce").dropna()
                if not values.empty:
                    baseline_values[token] = float(values.iloc[0])

            baseline_text = ", ".join(
                f"I_baseline,{token}={value:.10g} ADC"
                for token, value in baseline_values.items()
            )
            baseline_lines.append(f"{pair['pair_code']}: {baseline_text}")

            sample_frame = pd.concat(wide_sensor_frames, axis=1)
            filename = f"{self._safe_file_token(pair['pair_code'])}.csv"
            sample_frame.to_csv(sample_root / filename, index=False)
            exported_files.append(filename)
            sample_lines.append(
                f"{pair['pair_code']} | STEP_{pair['step']} | rep {pair['replicate']} | "
                f"V={pair['volume_ul']} uL | Q={pair['injection_rate_ul_min']} uL/min | "
                f"magnet={pair['magnet_state']} | source labels: "
                f"{', '.join(pair['sample_codes'])} | {filename}"
            )

        info_lines = [
            "TECHNICAL INFORMATION",
            "=====================",
            f"Experiment: {self.metadata.get('experiment_name', self.folder.name)}",
            f"Batch: {self.metadata.get('batch_number', '')}",
            f"Source folder: {self.folder}",
            f"Wavelength: {int(wavelength)} nm",
            f"Sample window: 0 to {float(window_s):g} s after injection",
            f"baseline: median of {float(baseline_window_s):g} s before each injection",
            "",
            "SENSOR / OUTLET MAPPING",
            "=======================",
            "1001: upstream, Outlet A",
            "1000: downstream, Outlet B",
            "1002: reference sensor, no outlet assignment",
            "",
            "100 % REFERENCE",
            "===============",
            f"Method: {reference_method}",
            f"Reference injection: STEP_{int(reference_injection_step)}",
            f"Search offset: {float(reference_offset_s):g} s",
            f"Search window: {reference_evaluation_window_s}",
            f"Search end: STEP_{reference_end_step}" if reference_end_step is not None else "Search end: offset + search window",
        ]
        reference_tokens: dict[int, str] = {1001: "A", 1000: "B", 1002: "Ref"}
        for _, row in reference_table.iterrows():
            sensor_id = int(row["sensor_id"])
            token = reference_tokens.get(sensor_id, f"S{sensor_id}")
            info_lines.append(
                f"I_100%,{token}={float(row['reference_adc_100pct']):.10g} ADC; "
                f"t_min,{token}={float(row['reference_time_s_after_injection']):.10g} s; "
                f"sensor={sensor_id} ({row['role']})"
            )
        info_lines.extend([
            "",
            "BASELINES PER SAMPLE",
            "====================",
            *baseline_lines,
            "",
            "SIGNALS AND FORMULAS",
            "====================",
            "raw_X(t) = measured intensity I_X(t) [ADC]",
            "abs_X(t) = I_baseline,X - raw_X(t) [ADC]",
            "norm_X(t) = abs_X(t) / (I_baseline,X - I_100%,X) [-]",
            "X is A, B or Ref.",
            "",
            "CSV COLUMNS",
            "===========",
            "t_A, raw_A, abs_A, norm_A: sensor 1001, upstream, Outlet A",
            "t_B, raw_B, abs_B, norm_B: sensor 1000, downstream, Outlet B",
            "t_Ref, raw_Ref, abs_Ref, norm_Ref: sensor 1002, reference",
            "Time columns are seconds after the injection marker.",
            "Signal columns raw/abs are ADC counts; norm is dimensionless.",
            "Each sensor retains its own original time vector; no interpolation is applied.",
            "Separator: comma; decimal: point; encoding: UTF-8",
            "",
            "PLOT RECONSTRUCTION",
            "===================",
            "Raw plot: plot raw_X against t_X.",
            "Absolute plot: plot abs_X against t_X.",
            "Normalized plot: plot norm_X against t_X.",
            "",
            "SAMPLES",
            "=======",
            *sample_lines,
            "",
            f"Exported CSV files: {len(exported_files)}",
        ])
        (sample_root / "info.txt").write_text(
            "\n".join(info_lines).rstrip() + "\n", encoding="utf-8"
        )
        return sample_root

    def replicate_metrics(
        self,
        wavelength: int | str = 640,
        *,
        steps: Optional[Sequence[int]] = None,
        window_s: float = 60.0,
        baseline_window_s: float = 10.0,
        reference_injection_step: int = 6,
        reference_method: str = "absolute_min",
        reference_offset_s: float = 0.0,
        reference_evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        reference_stability_window_s: float = 5.0,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> pd.DataFrame:
        """Berechnet Peak- und Integralwerte einmal je Injektion und sensor."""
        rows: list[dict[str, Any]] = []
        selected_steps = self._selected_analysis_steps(
            steps, reference_injection_step
        )
        for step in selected_steps:
            data = self.sample_timeseries_data(
                int(step),
                wavelength,
                window_s=window_s,
                baseline_window_s=baseline_window_s,
                reference_injection_step=reference_injection_step,
                reference_method=reference_method,
                reference_offset_s=reference_offset_s,
                reference_evaluation_window_s=reference_evaluation_window_s,
                reference_end_step=reference_end_step,
                reference_stability_window_s=reference_stability_window_s,
                sensor_ids=sensor_ids,
            )
            if data.empty:
                continue
            pair = self._paired_sample_metadata(int(step))

            available_sensor_ids = set(data["sensor_id"].dropna().astype(int).unique())
            for sensor_id in [
                sid for sid in self._resolve_sensor_ids(sensor_ids)
                if sid in available_sensor_ids
            ]:
                sensor_data = data.loc[data["sensor_id"] == sensor_id].copy()
                t = pd.to_numeric(
                    sensor_data["time_from_injection_s"], errors="coerce"
                ).to_numpy(dtype=float)
                absolute = pd.to_numeric(
                    sensor_data["absolute_absorption_adc"], errors="coerce"
                ).to_numpy(dtype=float)
                normalized = pd.to_numeric(
                    sensor_data["normalized_absorption_0_1"], errors="coerce"
                ).to_numpy(dtype=float)
                valid = np.isfinite(t) & np.isfinite(absolute)
                t = t[valid]
                absolute = absolute[valid]
                normalized = normalized[valid]
                if t.size == 0:
                    continue
                order = np.argsort(t)
                t = t[order]
                absolute = absolute[order]
                normalized = normalized[order]
                peak_idx = int(np.nanargmax(absolute))
                positive = np.clip(absolute, 0.0, None)

                rows.append({
                    "sample_pair_code": pair["pair_code"],
                    "sample_codes": " | ".join(pair["sample_codes"]),
                    "step": int(step),
                    "replicate": pair["replicate"],
                    "volume_ul": pair["volume_ul"],
                    "injection_rate_ul_min": pair["injection_rate_ul_min"],
                    "magnet_state": pair["magnet_state"],
                    "sensor_id": int(sensor_id),
                    "role": self.role(sensor_id),
                    "sensor_outlet": self.outlet_for_sensor(sensor_id),
                    "n_points": int(t.size),
                    "peak_absolute_adc": float(absolute[peak_idx]),
                    "peak_time_s": float(t[peak_idx]),
                    "peak_normalized": float(np.nanmax(normalized)),
                    "integral_absolute_adc_s": self._trapezoid(absolute, t),
                    "integral_positive_adc_s": self._trapezoid(positive, t),
                    "integral_normalized_s": self._trapezoid(normalized, t),
                    "mean_absolute_adc": float(np.nanmean(absolute)),
                    "std_absolute_adc": float(np.nanstd(absolute, ddof=1)) if absolute.size > 1 else 0.0,
                })
        return pd.DataFrame(rows)

    def replicate_summary(
        self,
        metrics: Optional[pd.DataFrame] = None,
        **kwargs: Any,
    ) -> pd.DataFrame:
        """Fasst Kennwerte je Bedingung und sensor als Mittelwert ± SD zusammen."""
        data = metrics if metrics is not None else self.replicate_metrics(**kwargs)
        if data.empty:
            return data.copy()
        group_columns = [
            "volume_ul",
            "injection_rate_ul_min",
            "magnet_state",
            "sensor_id",
            "role",
        ]
        return (
            data.groupby(group_columns, dropna=False)
            .agg(
                n_replicates=("replicate", "nunique"),
                peak_absolute_mean_adc=("peak_absolute_adc", "mean"),
                peak_absolute_std_adc=("peak_absolute_adc", "std"),
                peak_time_mean_s=("peak_time_s", "mean"),
                peak_time_std_s=("peak_time_s", "std"),
                peak_normalized_mean=("peak_normalized", "mean"),
                peak_normalized_std=("peak_normalized", "std"),
                integral_absolute_mean_adc_s=("integral_absolute_adc_s", "mean"),
                integral_absolute_std_adc_s=("integral_absolute_adc_s", "std"),
                integral_positive_mean_adc_s=("integral_positive_adc_s", "mean"),
                integral_positive_std_adc_s=("integral_positive_adc_s", "std"),
                integral_normalized_mean_s=("integral_normalized_s", "mean"),
                integral_normalized_std_s=("integral_normalized_s", "std"),
            )
            .reset_index()
        )

    def replicate_mean_curves(
        self,
        wavelength: int | str = 640,
        *,
        steps: Optional[Sequence[int]] = None,
        window_s: float = 60.0,
        time_step_s: float = 0.25,
        baseline_window_s: float = 10.0,
        reference_injection_step: int = 6,
        reference_method: str = "absolute_min",
        reference_offset_s: float = 0.0,
        reference_evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        reference_stability_window_s: float = 5.0,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> pd.DataFrame:
        """Berechnet zeitaufgelöste Replicate-Mittelwerte und SD je sensor.

        Outlet A/B wird nicht als statistische Gruppierungsvariable verwendet,
        weil es bereits eindeutig durch sensor 1001/1000 beschrieben ist.
        """
        if time_step_s <= 0:
            raise ValueError("time_step_s muss größer als 0 sein.")
        grid = np.arange(0.0, float(window_s) + time_step_s * 0.5, time_step_s)
        records: list[dict[str, Any]] = []
        selected_steps = self._selected_analysis_steps(
            steps, reference_injection_step
        )

        for step in selected_steps:
            data = self.sample_timeseries_data(
                int(step),
                wavelength,
                window_s=window_s,
                baseline_window_s=baseline_window_s,
                reference_injection_step=reference_injection_step,
                reference_method=reference_method,
                reference_offset_s=reference_offset_s,
                reference_evaluation_window_s=reference_evaluation_window_s,
                reference_end_step=reference_end_step,
                reference_stability_window_s=reference_stability_window_s,
                sensor_ids=sensor_ids,
            )
            if data.empty:
                continue
            pair = self._paired_sample_metadata(int(step))

            available_sensor_ids = set(data["sensor_id"].dropna().astype(int).unique())
            for sensor_id in [
                sid for sid in self._resolve_sensor_ids(sensor_ids)
                if sid in available_sensor_ids
            ]:
                sensor_data = data.loc[data["sensor_id"] == sensor_id].copy()
                t = pd.to_numeric(
                    sensor_data["time_from_injection_s"], errors="coerce"
                ).to_numpy(dtype=float)
                absolute = pd.to_numeric(
                    sensor_data["absolute_absorption_adc"], errors="coerce"
                ).to_numpy(dtype=float)
                normalized = pd.to_numeric(
                    sensor_data["normalized_absorption_0_1"], errors="coerce"
                ).to_numpy(dtype=float)
                valid = np.isfinite(t) & np.isfinite(absolute) & np.isfinite(normalized)
                t = t[valid]
                absolute = absolute[valid]
                normalized = normalized[valid]
                if t.size < 2:
                    continue
                order = np.argsort(t)
                t = t[order]
                absolute = absolute[order]
                normalized = normalized[order]
                unique_t, unique_idx = np.unique(t, return_index=True)
                absolute = absolute[unique_idx]
                normalized = normalized[unique_idx]
                records.append({
                    "volume_ul": pair["volume_ul"],
                    "injection_rate_ul_min": pair["injection_rate_ul_min"],
                    "magnet_state": pair["magnet_state"],
                    "replicate": pair["replicate"],
                    "sensor_id": int(sensor_id),
                    "role": self.role(sensor_id),
                    "sensor_outlet": self.outlet_for_sensor(sensor_id),
                    "absolute": np.interp(
                        grid, unique_t, absolute, left=np.nan, right=np.nan
                    ),
                    "normalized": np.interp(
                        grid, unique_t, normalized, left=np.nan, right=np.nan
                    ),
                })

        if not records:
            return pd.DataFrame()

        group_columns = [
            "volume_ul",
            "injection_rate_ul_min",
            "magnet_state",
            "sensor_id",
            "role",
            "sensor_outlet",
        ]
        rows: list[dict[str, Any]] = []
        records_frame = pd.DataFrame(records)
        for keys, group in records_frame.groupby(group_columns, dropna=False):
            absolute_stack = np.vstack(group["absolute"].to_list())
            normalized_stack = np.vstack(group["normalized"].to_list())
            absolute_count = np.sum(np.isfinite(absolute_stack), axis=0)
            normalized_count = np.sum(np.isfinite(normalized_stack), axis=0)
            absolute_sum = np.nansum(absolute_stack, axis=0)
            normalized_sum = np.nansum(normalized_stack, axis=0)
            absolute_mean = np.divide(
                absolute_sum, absolute_count,
                out=np.full_like(absolute_sum, np.nan, dtype=float),
                where=absolute_count > 0,
            )
            normalized_mean = np.divide(
                normalized_sum, normalized_count,
                out=np.full_like(normalized_sum, np.nan, dtype=float),
                where=normalized_count > 0,
            )
            absolute_squared = np.nansum(
                np.square(absolute_stack - absolute_mean), axis=0
            )
            normalized_squared = np.nansum(
                np.square(normalized_stack - normalized_mean), axis=0
            )
            absolute_std = np.sqrt(np.divide(
                absolute_squared, absolute_count - 1,
                out=np.full_like(absolute_squared, np.nan, dtype=float),
                where=absolute_count > 1,
            ))
            normalized_std = np.sqrt(np.divide(
                normalized_squared, normalized_count - 1,
                out=np.full_like(normalized_squared, np.nan, dtype=float),
                where=normalized_count > 1,
            ))
            metadata = dict(zip(group_columns, keys))
            for idx, time_value in enumerate(grid):
                rows.append({
                    **metadata,
                    "time_s": float(time_value),
                    "n_replicates": int(normalized_count[idx]),
                    "absolute_mean_adc": float(absolute_mean[idx]),
                    "absolute_std_adc": float(absolute_std[idx]) if np.isfinite(absolute_std[idx]) else np.nan,
                    "normalized_mean": float(normalized_mean[idx]),
                    "normalized_std": float(normalized_std[idx]) if np.isfinite(normalized_std[idx]) else np.nan,
                })
        return pd.DataFrame(rows)

    def export_replicate_statistics(
        self,
        output_folder: str | Path,
        wavelength: int | str = 640,
        *,
        steps: Optional[Sequence[int]] = None,
        window_s: float = 60.0,
        time_step_s: float = 0.25,
        baseline_window_s: float = 10.0,
        reference_injection_step: int = 6,
        reference_method: str = "absolute_min",
        reference_offset_s: float = 0.0,
        reference_evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        reference_stability_window_s: float = 5.0,
        sensor_ids: Optional[Iterable[int]] = None,
        dpi: int = 300,
    ) -> Path:
        """Exportiert Replikatstatistik und vergleicht sensors gemeinsam."""
        output = Path(output_folder) / "statistics"
        curve_plot_dir = output / "mean_std_curves"
        output.mkdir(parents=True, exist_ok=True)
        curve_plot_dir.mkdir(parents=True, exist_ok=True)

        common = dict(
            steps=steps,
            window_s=window_s,
            baseline_window_s=baseline_window_s,
            reference_injection_step=reference_injection_step,
            reference_method=reference_method,
            reference_offset_s=reference_offset_s,
            reference_evaluation_window_s=reference_evaluation_window_s,
            reference_end_step=reference_end_step,
            reference_stability_window_s=reference_stability_window_s,
            sensor_ids=sensor_ids,
        )
        metrics = self.replicate_metrics(wavelength, **common)
        summary = self.replicate_summary(metrics)
        curves = self.replicate_mean_curves(
            wavelength, time_step_s=time_step_s, **common
        )
        metrics.to_csv(output / "replicate_metrics.csv", index=False)
        summary.to_csv(output / "replicate_summary.csv", index=False)
        curves.to_csv(output / "replicate_mean_curves.csv", index=False)

        condition_columns = [
            "volume_ul", "injection_rate_ul_min", "magnet_state"
        ]
        if not curves.empty:
            for keys, condition in curves.groupby(condition_columns, dropna=False):
                volume, rate, magnet = keys
                fig, ax = plt.subplots(figsize=(8.4, 4.8))
                available_sensor_ids = set(condition["sensor_id"].dropna().astype(int).unique())
                for sensor_id in [
                    sid for sid in self._resolve_sensor_ids(sensor_ids)
                    if sid in available_sensor_ids
                ]:
                    sensor_curve = condition.loc[condition["sensor_id"] == sensor_id].sort_values("time_s")
                    style = self.sensor_style(int(sensor_id))
                    x = sensor_curve["time_s"].to_numpy(dtype=float)
                    mean = sensor_curve["normalized_mean"].to_numpy(dtype=float)
                    std = sensor_curve["normalized_std"].to_numpy(dtype=float)
                    ax.plot(
                        x, mean,
                        color=style["color"],
                        linestyle=style["linestyle"],
                        linewidth=style["linewidth"],
                        label=f"{self.role(int(sensor_id))} ({int(sensor_id)})",
                    )
                    ax.fill_between(
                        x,
                        mean - np.nan_to_num(std, nan=0.0),
                        mean + np.nan_to_num(std, nan=0.0),
                        color=style["color"], alpha=0.16, linewidth=0,
                    )
                ax.set_xlim(0, window_s)
                ax.set_xlabel("Time after injection (s)")
                ax.set_ylabel("Normalized absorption (–)")
                ax.set_title(
                    f"Replicate mean ± SD | V={volume:g} µL, "
                    f"Q={rate:g} µL min⁻¹, magnet {magnet}"
                )
                ax.grid(True, linestyle=":", linewidth=0.45, alpha=0.25)
                ax.legend(frameon=False, fontsize=8)
                fig.tight_layout()
                stem = self._safe_file_token(
                    f"V{volume:g}uL_Q{rate:g}uL-min_{magnet}"
                )
                fig.savefig(curve_plot_dir / f"mean_std_{stem}.png", dpi=dpi)
                plt.close(fig)

        if not summary.empty:
            conditions = (
                summary[condition_columns]
                .drop_duplicates()
                .sort_values(condition_columns)
                .reset_index(drop=True)
            )
            condition_keys = [tuple(row) for row in conditions.to_numpy()]
            condition_labels = [
                f"{float(v):g} µL, {float(q):g} µL min⁻¹ | {m}"
                for v, q, m in condition_keys
            ]
            x = np.arange(len(condition_keys), dtype=float)
            available_sensor_ids = set(summary["sensor_id"].dropna().astype(int).unique())
            sensor_list = [
                sid for sid in self._resolve_sensor_ids(sensor_ids)
                if sid in available_sensor_ids
            ]
            width = 0.18 if len(sensor_list) >= 3 else 0.24
            offsets = (np.arange(len(sensor_list)) - (len(sensor_list) - 1) / 2.0) * width

            def comparison_plot(
                mean_column: str,
                std_column: str,
                ylabel: str,
                title: str,
                filename: str,
            ) -> None:
                fig, ax = plt.subplots(figsize=(max(8.4, len(x) * 1.2), 5.0))
                for offset, sensor_id in zip(offsets, sensor_list):
                    sensor_rows = summary.loc[summary["sensor_id"] == sensor_id].copy()
                    lookup = {
                        tuple(row[col] for col in condition_columns): row
                        for _, row in sensor_rows.iterrows()
                    }
                    means = []
                    stds = []
                    for key in condition_keys:
                        row = lookup.get(key)
                        means.append(float(row[mean_column]) if row is not None else np.nan)
                        stds.append(
                            float(row[std_column])
                            if row is not None and pd.notna(row[std_column])
                            else 0.0
                        )
                    style = self.sensor_style(sensor_id)
                    ax.errorbar(
                        x + offset,
                        means,
                        yerr=stds,
                        fmt="o",
                        color=style["color"],
                        capsize=4,
                        linewidth=1.2,
                        markersize=5,
                        label=f"{self.role(sensor_id)} ({sensor_id})",
                    )
                ax.set_xticks(x)
                ax.set_xticklabels(condition_labels, rotation=30, ha="right")
                ax.set_ylabel(ylabel)
                ax.set_title(title)
                ax.grid(True, axis="y", linestyle=":", linewidth=0.45, alpha=0.25)
                ax.legend(frameon=False, fontsize=8)
                fig.tight_layout()
                fig.savefig(output / filename, dpi=dpi)
                plt.close(fig)

            comparison_plot(
                "peak_absolute_mean_adc",
                "peak_absolute_std_adc",
                "Peak absolute absorption (ADC counts)",
                "Peak mean ± SD | sensor comparison",
                "peak_mean_std_sensor_comparison.png",
            )
            comparison_plot(
                "integral_positive_mean_adc_s",
                "integral_positive_std_adc_s",
                "Positive integral (ADC counts·s)",
                "Integral mean ± SD | sensor comparison",
                "integral_mean_std_sensor_comparison.png",
            )

        stats_info = [
            "REPLICATE STATISTICS",
            "====================",
            "sensor mapping: 1001 = upstream / Outlet A; 1000 = downstream / Outlet B; 1002 = reference.",
            "Outlet is not a grouping variable because it is fixed by sensor identity.",
            "replicate_metrics.csv: one row per injection/replicate and sensor",
            "replicate_summary.csv: mean, standard deviation and n per condition and sensor",
            "replicate_mean_curves.csv: interpolated mean and SD curves",
            f"Curve grid: {float(time_step_s):g} s",
            f"Analysis window: 0 to {float(window_s):g} s",
            "Peak: maximum baseline-corrected absolute absorption",
            "Positive integral: trapezoidal integral after clipping negative values to zero",
            "Groups: injection volume, injection rate, magnet state and sensor",
            "Interpolation is used only for replicate mean curves, not for exported sample CSVs.",
        ]
        (output / "info.txt").write_text(
            "\n".join(stats_info) + "\n", encoding="utf-8"
        )
        return output

    def export_sample_analysis(
        self,
        output_folder: str | Path,
        wavelength: int | str = 640,
        *,
        steps: Optional[Sequence[int]] = None,
        window_s: float = 60.0,
        baseline_window_s: float = 10.0,
        reference_injection_step: int = 6,
        reference_method: str = "absolute_min",
        reference_offset_s: float = 0.0,
        reference_evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        reference_stability_window_s: float = 5.0,
        sensor_ids: Optional[Iterable[int]] = None,
        title_style: str = "ieee",
        include_normalized_csv: bool = True,
        statistics_time_step_s: float = 0.25,
        dpi: int = 300,
    ) -> Path:
        """Komplettexport: Sample-CSV, Kontrollplots und Replicate-Statistik.

        Der Methodenstandard entspricht exakt ``BEISPIEL_ABSOLUTES_MINIMUM``:
        absolutes Minimum ab STEP_6 bis unmittelbar vor STEP_8.
        """
        output = Path(output_folder)
        output.mkdir(parents=True, exist_ok=True)

        # CSV-Export wählt ohne explizite steps automatisch die Manifest-Steps.
        self.export_sample_csv(
            output,
            wavelength,
            steps=steps,
            window_s=window_s,
            baseline_window_s=baseline_window_s,
            reference_injection_step=reference_injection_step,
            reference_method=reference_method,
            reference_offset_s=reference_offset_s,
            reference_evaluation_window_s=reference_evaluation_window_s,
            reference_end_step=reference_end_step,
            reference_stability_window_s=reference_stability_window_s,
            sensor_ids=sensor_ids,
            include_normalized=include_normalized_csv,
            include_combined_files=False,
        )

        self.export_replicate_statistics(
            output,
            wavelength,
            steps=steps,
            window_s=window_s,
            time_step_s=statistics_time_step_s,
            baseline_window_s=baseline_window_s,
            reference_injection_step=reference_injection_step,
            reference_method=reference_method,
            reference_offset_s=reference_offset_s,
            reference_evaluation_window_s=reference_evaluation_window_s,
            reference_end_step=reference_end_step,
            reference_stability_window_s=reference_stability_window_s,
            sensor_ids=sensor_ids,
            dpi=dpi,
        )

        if steps is None:
            manifest = getattr(self, "sample_manifest", None)
            if (
                isinstance(manifest, pd.DataFrame)
                and not manifest.empty
                and "step" in manifest.columns
            ):
                plot_steps = sorted(
                    pd.to_numeric(manifest["step"], errors="coerce")
                    .dropna()
                    .astype(int)
                    .unique()
                    .tolist()
                )
            else:
                plot_steps = [
                    int(step) for step in self.injection_steps
                    if int(step) != int(reference_injection_step)
                ]
        else:
            plot_steps = [int(step) for step in steps]

        self.export_injection_plots(
            output,
            wavelength,
            steps=plot_steps,
            window_s=window_s,
            baseline_window_s=baseline_window_s,
            reference_injection_step=reference_injection_step,
            reference_method=reference_method,
            reference_offset_s=reference_offset_s,
            reference_evaluation_window_s=reference_evaluation_window_s,
            reference_end_step=reference_end_step,
            reference_stability_window_s=reference_stability_window_s,
            sensor_ids=sensor_ids,
            show_evaluation_window=False,
            export_reference_plot=True,
            show_reference_window=False,
            title_style=title_style,
            include_sample_codes=True,
            include_step_in_title=True,
            filename_mode="metadata",
            dpi=dpi,
        )
        return output

    def plot_injection(
        self,
        step: int,
        wavelength: int | str = 640,
        *,
        window_s: float = 60.0,
        baseline_window_s: float = 10.0,
        normalized: bool = False,
        evaluation_offset_s: float = 20.0,
        evaluation_window_s: float = 10.0,
        reference_injection_step: int = 6,
        reference_method: str = "absolute_min",
        reference_offset_s: float = 0.0,
        reference_evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        reference_stability_window_s: float = 5.0,
        sensor_ids: Optional[Iterable[int]] = None,
        show_evaluation_window: bool = False,
        title_style: str = "ieee",
        include_sample_codes: bool = True,
        include_step_in_title: bool = True,
        title_fontsize: float = 10.0,
        ax: Optional[plt.Axes] = None,
    ) -> tuple[plt.Figure, plt.Axes]:
        """Plottet eine Injektion über 60 s, roh oder 0…1-normalisiert.

        ``title_style`` beeinflusst ausschließlich die Beschriftung. Die
        Referenzberechnung wird immer nur über die ``reference_*``-parameter
        gesteuert.
        """
        wavelength_name = self._validate_wavelength(wavelength)
        selected = self._resolve_sensor_ids(sensor_ids)
        marker = self._marker_for_step(step)
        windows = self.normalized_injection_window(
            step,
            wavelength_name,
            window_s=window_s,
            baseline_window_s=baseline_window_s,
            reference_injection_step=reference_injection_step,
            reference_method=reference_method,
            reference_offset_s=reference_offset_s,
            reference_evaluation_window_s=reference_evaluation_window_s,
            reference_end_step=reference_end_step,
            reference_stability_window_s=reference_stability_window_s,
            sensor_ids=selected,
        )

        if ax is None:
            fig, ax = plt.subplots(figsize=(10, 4.8))
        else:
            fig = ax.figure

        for sensor_id in selected:
            frame = windows[sensor_id]
            y = frame["normalized_0_1"] if normalized else frame[wavelength_name]
            role = self.role(sensor_id)
            style = self.sensor_style(sensor_id)
            ax.plot(
                frame["time_from_marker_s"],
                y,
                color=style["color"],
                linestyle=style["linestyle"],
                linewidth=style["linewidth"],
                label=f"{role} ({sensor_id})",
            )

        if show_evaluation_window:
            ax.axvspan(
                evaluation_offset_s,
                evaluation_offset_s + evaluation_window_s,
                alpha=0.12,
                label="Auswertefenster",
            )

        if normalized:
            ax.axhline(
                0.0,
                color="#777777",
                linestyle=":",
                linewidth=0.9,
                alpha=0.75,
                zorder=0,
            )
            ax.axhline(
                1.0,
                color="#222222",
                linestyle="--",
                linewidth=0.9,
                alpha=0.65,
                zorder=0,
            )
            ax.set_ylabel("Normalized absorption (–)", fontsize=9)
        else:
            ax.set_ylabel(
                f"Signal intensity at {wavelength_name} nm (ADC counts)",
                fontsize=9,
            )

        title = self.format_injection_plot_title(
            step,
            title_style=title_style,
            include_sample_codes=include_sample_codes,
            include_step=include_step_in_title,
        )
        ax.set_title(title, fontsize=title_fontsize, pad=8)
        ax.set_xlabel("Time after injection (s)", fontsize=9)
        ax.set_xlim(0, window_s)
        ax.tick_params(axis="both", labelsize=8)
        ax.grid(True, which="major", linewidth=0.45, linestyle=":", alpha=0.22)
        ax.legend(
            title="sensor",
            fontsize=8,
            title_fontsize=8,
            frameon=False,
        )
        fig.tight_layout()
        return fig, ax

    def plot_each_injection(
        self,
        wavelength: int | str = 640,
        *,
        steps: Optional[Sequence[int]] = None,
        normalized: bool = False,
        **kwargs: Any,
    ) -> dict[int, tuple[plt.Figure, plt.Axes]]:
        """Erzeugt je ausgewählter Injektion einen separaten Plot."""
        selected_steps = list(steps) if steps is not None else self.injection_steps
        return {
            int(step): self.plot_injection(
                int(step), wavelength, normalized=normalized, **kwargs
            )
            for step in selected_steps
        }

    def export_injection_plots(
        self,
        output_folder: str | Path,
        wavelength: int | str = 640,
        *,
        steps: Optional[Sequence[int]] = None,
        window_s: float = 60.0,
        baseline_window_s: float = 10.0,
        evaluation_offset_s: float = 20.0,
        evaluation_window_s: float = 10.0,
        reference_injection_step: int = 6,
        reference_method: str = "absolute_min",
        reference_offset_s: float = 0.0,
        reference_evaluation_window_s: Optional[float] = None,
        reference_end_step: Optional[int] = 8,
        reference_stability_window_s: float = 5.0,
        sensor_ids: Optional[Iterable[int]] = None,
        show_evaluation_window: bool = False,
        export_reference_plot: bool = True,
        show_reference_window: bool = False,
        title_style: str = "ieee",
        include_sample_codes: bool = True,
        include_step_in_title: bool = True,
        filename_mode: str = "metadata",
        dpi: int = 300,
    ) -> Path:
        """Exportiert Roh- und Normplots sowie standardmäßig den Referenzplot."""
        output = Path(output_folder)
        raw_dir = output / "injection_plots_raw"
        norm_dir = output / "injection_plots_normalized"
        raw_dir.mkdir(parents=True, exist_ok=True)
        norm_dir.mkdir(parents=True, exist_ok=True)

        selected_steps = list(steps) if steps is not None else self.injection_steps
        for step in selected_steps:
            stem = self._injection_export_stem(
                int(step),
                wavelength,
                filename_mode=filename_mode,
            )

            common = dict(
                window_s=window_s,
                baseline_window_s=baseline_window_s,
                evaluation_offset_s=evaluation_offset_s,
                evaluation_window_s=evaluation_window_s,
                reference_injection_step=reference_injection_step,
                reference_method=reference_method,
                reference_offset_s=reference_offset_s,
                reference_evaluation_window_s=reference_evaluation_window_s,
                reference_end_step=reference_end_step,
                reference_stability_window_s=reference_stability_window_s,
                sensor_ids=sensor_ids,
                show_evaluation_window=show_evaluation_window,
                title_style=title_style,
                include_sample_codes=include_sample_codes,
                include_step_in_title=include_step_in_title,
            )

            raw_fig, _ = self.plot_injection(
                int(step), wavelength, normalized=False, **common
            )
            raw_fig.savefig(raw_dir / f"{stem}_raw.png", dpi=dpi)
            plt.close(raw_fig)

            norm_fig, _ = self.plot_injection(
                int(step), wavelength, normalized=True, **common
            )
            norm_fig.savefig(norm_dir / f"{stem}_normalized.png", dpi=dpi)
            plt.close(norm_fig)

        reference = self.reference_100pct(
            wavelength,
            reference_injection_step=reference_injection_step,
            method=reference_method,
            evaluation_offset_s=reference_offset_s,
            evaluation_window_s=reference_evaluation_window_s,
            reference_end_step=reference_end_step,
            stability_window_s=reference_stability_window_s,
            sensor_ids=sensor_ids,
        )
        reference.to_csv(
            output / f"reference_100pct_{int(wavelength)}nm.csv",
            index=False,
        )

        if export_reference_plot:
            reference_figure, _ = self.plot_reference_100pct(
                wavelength,
                reference_injection_step=reference_injection_step,
                method=reference_method,
                evaluation_offset_s=reference_offset_s,
                evaluation_window_s=reference_evaluation_window_s,
                reference_end_step=reference_end_step,
                stability_window_s=reference_stability_window_s,
                baseline_window_s=baseline_window_s,
                sensor_ids=sensor_ids,
                show_reference_window=show_reference_window,
            )
            reference_figure.savefig(
                output / f"reference_100pct_{int(wavelength)}nm.png",
                dpi=dpi,
            )
            plt.close(reference_figure)
        return output

    # ------------------------------------------------------------------
    # calibration
    # ------------------------------------------------------------------
    def fit_calibration(
        self,
        concentration_by_step: Mapping[int, float],
        wavelength: int | str = 640,
        *,
        model: str = "offset_exponential",
        window_s: float = 57.0,
        offset_s: float = 0.0,
        polynomial_degree: int = 2,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> dict[int, CalibrationModel]:
        """Fittet ein calibrationmodell aus Marker-Steps mit bekannter concentration.

        Beispiel::

            models = run.fit_calibration(
                {2: 0, 3: 2.5, 4: 5, 5: 10, 6: 25, 7: 50, 8: 100},
                wavelength=640,
                model="offset_exponential",
            )
        """
        if curve_fit is None or least_squares is None:
            raise ImportError("Für calibrationfits muss scipy installiert sein.")

        model = model.lower()
        allowed = {"exponential", "offset_exponential", "log_poly"}
        if model not in allowed:
            raise ValueError(f"model muss einer von {sorted(allowed)} sein.")

        wavelength_name = self._validate_wavelength(wavelength)
        selected = self._resolve_sensor_ids(sensor_ids)
        stats = self.step_statistics(
            wavelength_name,
            steps=list(concentration_by_step),
            window_s=window_s,
            offset_s=offset_s,
            sensor_ids=selected,
        )
        stats["concentration_pct"] = stats["step"].map(
            {int(k): float(v) for k, v in concentration_by_step.items()}
        )

        models: dict[int, CalibrationModel] = {}
        for sensor_id, group in stats.groupby("sensor_id"):
            group = group.dropna(subset=["mean", "concentration_pct"])
            group = group.loc[group["mean"] > 0].sort_values("concentration_pct")
            minimum_points = 4 if model == "offset_exponential" else 3
            if len(group) < minimum_points:
                raise ValueError(
                    f"sensor {sensor_id}: mindestens {minimum_points} calibrationpunkte "
                    f"für {model} benötigt, gefunden: {len(group)}."
                )

            c_data = group["concentration_pct"].to_numpy(dtype=float)
            intensity_data = group["mean"].to_numpy(dtype=float)

            if model == "exponential":
                fitted = self._fit_exponential(c_data, intensity_data)
            elif model == "offset_exponential":
                fitted = self._fit_offset_exponential(c_data, intensity_data)
            else:
                fitted = self._fit_log_poly(
                    c_data, intensity_data, degree=polynomial_degree
                )

            calibration = CalibrationModel(
                model_type=model,
                sensor_id=int(sensor_id),
                wavelength_nm=int(wavelength_name),
                parameters=fitted["parameters"],
                fit_metrics=fitted["metrics"],
                source=str(self.folder),
            )
            models[int(sensor_id)] = calibration

        self.calibration_models.update(models)
        return models

    def make_affine_calibration(
        self,
        references: Mapping[int, Mapping[str, float]],
        wavelength: int | str = 640,
        *,
        valid_range_pct: tuple[float, float] = (0.0, 100.0),
    ) -> dict[int, CalibrationModel]:
        """Erzeugt affine 0–100-%-Modelle aus expliziten Referenzwerten.

        ``references`` hat die Form::

            {
                1000: {"I_0pct": 7500, "I_100pct": 138},
                1001: {"I_0pct": 6100, "I_100pct": 83},
                1002: {"I_0pct": 5500, "I_100pct": 100},
            }
        """
        wavelength_name = self._validate_wavelength(wavelength)
        models = {}
        for sensor_id, values in references.items():
            sensor_id = int(sensor_id)
            if sensor_id not in self.sensors:
                raise KeyError(f"sensor {sensor_id} ist nicht geload.")
            i_zero = float(values["I_0pct"])
            i_full = float(values["I_100pct"])
            if np.isclose(i_zero, i_full):
                raise ValueError(
                    f"sensor {sensor_id}: I_0pct und I_100pct dürfen nicht identisch sein."
                )
            models[sensor_id] = CalibrationModel(
                model_type="affine_0_100",
                sensor_id=sensor_id,
                wavelength_nm=int(wavelength_name),
                parameters={"I_0pct": i_zero, "I_100pct": i_full},
                valid_range_pct=valid_range_pct,
                source=str(self.folder),
            )
        self.calibration_models.update(models)
        return models

    def apply_calibration(
        self,
        models: Optional[Mapping[int, CalibrationModel]] = None,
        *,
        wavelength: Optional[int | str] = None,
        clip: bool = True,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> pd.DataFrame:
        """Wendet calibrationmodelle auf die kompletten Zeitreihen an."""
        models_to_use = {
            int(k): v for k, v in (models or self.calibration_models).items()
        }
        if not models_to_use:
            raise ValueError("Keine calibrationmodelle vorhanden.")

        selected = self._resolve_sensor_ids(sensor_ids or models_to_use.keys())
        rows = []
        for sensor_id in selected:
            if sensor_id not in models_to_use:
                raise KeyError(f"Kein calibrationmodell für sensor {sensor_id} vorhanden.")
            calibration = models_to_use[sensor_id]
            wavelength_nm = int(wavelength or calibration.wavelength_nm)
            wavelength_name = self._validate_wavelength(wavelength_nm)
            if wavelength_nm != calibration.wavelength_nm:
                raise ValueError(
                    f"Modell für {calibration.wavelength_nm} nm kann nicht auf "
                    f"{wavelength_nm} nm angewendet werden."
                )

            frame = self.sensors[sensor_id]
            adc = pd.to_numeric(frame[wavelength_name], errors="coerce").to_numpy(
                dtype=float
            )
            raw_concentration = calibration.concentration(adc, clip=False)
            concentration = calibration.concentration(adc, clip=clip)
            rows.append(
                pd.DataFrame(
                    {
                        "sensor_id": sensor_id,
                        "role": self.role(sensor_id),
                        "timestamp_raw_ms": frame["timestamp_raw_ms"].to_numpy(),
                        "time_s": frame["time_s"].to_numpy(),
                        "time_min": frame["time_min"].to_numpy(),
                        "wavelength_nm": wavelength_nm,
                        "adc": adc,
                        "concentration_raw_pct": raw_concentration,
                        "concentration_pct": concentration,
                    }
                )
            )
        return pd.concat(rows, ignore_index=True)

    def evaluate(
        self,
        models: Optional[Mapping[int, CalibrationModel]] = None,
        *,
        wavelength: Optional[int | str] = None,
        clip: bool = True,
        sensor_ids: Optional[Iterable[int]] = None,
    ) -> pd.DataFrame:
        """Kurzer Alias für :meth:`apply_calibration`."""
        return self.apply_calibration(
            models,
            wavelength=wavelength,
            clip=clip,
            sensor_ids=sensor_ids,
        )

    def save_calibrations(
        self,
        path: str | Path,
        models: Optional[Mapping[int, CalibrationModel]] = None,
    ) -> Path:
        models_to_save = models or self.calibration_models
        if not models_to_save:
            raise ValueError("Keine calibrationmodelle zum Speichern vorhanden.")
        output = Path(path)
        output.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "models": [model.to_dict() for model in models_to_save.values()],
        }
        output.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return output

    def load_calibrations(self, path: str | Path) -> dict[int, CalibrationModel]:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        models = {
            model.sensor_id: model
            for model in (
                CalibrationModel.from_dict(item) for item in payload["models"]
            )
        }
        self.calibration_models.update(models)
        return models

    @staticmethod
    def _fit_exponential(c: np.ndarray, intensity: np.ndarray) -> dict[str, Any]:
        def function(values: np.ndarray, i_zero: float, alpha: float) -> np.ndarray:
            return i_zero * np.exp(-alpha * values)

        parameters, _ = curve_fit(
            function,
            c,
            intensity,
            p0=[float(np.max(intensity)), 0.05],
            bounds=([0.0, 1e-9], [np.inf, np.inf]),
            maxfev=50_000,
        )
        i_zero, alpha = map(float, parameters)
        predicted = function(c, i_zero, alpha)
        metrics = SpectralExperimentAnalyzer._fit_metrics(intensity, predicted)
        back = -np.log(np.clip(intensity / i_zero, 1e-12, None)) / alpha
        metrics["rmse_concentration_pct"] = float(
            np.sqrt(np.mean(np.square(back - c)))
        )
        return {
            "parameters": {"I0": i_zero, "alpha": alpha},
            "metrics": metrics,
        }

    @staticmethod
    def _fit_offset_exponential(
        c: np.ndarray, intensity: np.ndarray
    ) -> dict[str, Any]:
        def forward(
            concentration: np.ndarray, i_zero: float, alpha: float, i_inf: float
        ) -> np.ndarray:
            return i_inf + (i_zero - i_inf) * np.exp(-alpha * concentration)

        i_zero_guess = float(np.max(intensity))
        i_at_max_concentration = float(intensity[int(np.argmax(c))])
        i_inf_upper = max(0.98 * i_at_max_concentration, 1e-6)
        i_inf_guess = min(float(np.min(intensity)) * 0.7, 0.9 * i_at_max_concentration)
        scale_i = max(float(np.ptp(intensity)), 1.0)
        scale_c = max(float(np.ptp(c)), 1.0)

        def residuals(theta: np.ndarray) -> np.ndarray:
            i_zero, alpha, i_inf = map(float, theta)
            modeled = forward(c, i_zero, alpha, i_inf)
            adc_residual = (modeled - intensity) / scale_i
            denominator = max(i_zero - i_inf, 1e-12)
            ratio = np.clip((intensity - i_inf) / denominator, 1e-12, None)
            back = -np.log(ratio) / max(alpha, 1e-12)
            concentration_residual = (back - c) / scale_c
            return np.concatenate([adc_residual, np.sqrt(1.3) * concentration_residual])

        result = least_squares(
            residuals,
            x0=np.array([i_zero_guess, 0.05, max(0.0, i_inf_guess)]),
            bounds=(
                np.array([0.5 * i_zero_guess, 1e-9, 0.0]),
                np.array([1.5 * i_zero_guess, 1.0, i_inf_upper]),
            ),
            loss="soft_l1",
            max_nfev=50_000,
        )
        i_zero, alpha, i_inf = map(float, result.x)
        predicted = forward(c, i_zero, alpha, i_inf)
        metrics = SpectralExperimentAnalyzer._fit_metrics(intensity, predicted)
        denominator = max(i_zero - i_inf, 1e-12)
        ratio = np.clip((intensity - i_inf) / denominator, 1e-12, None)
        back = -np.log(ratio) / max(alpha, 1e-12)
        metrics["rmse_concentration_pct"] = float(
            np.sqrt(np.mean(np.square(np.clip(back, 0, 100) - c)))
        )
        metrics["optimizer_cost"] = float(result.cost)
        return {
            "parameters": {"I0": i_zero, "alpha": alpha, "I_inf": i_inf},
            "metrics": metrics,
        }

    @staticmethod
    def _fit_log_poly(
        c: np.ndarray, intensity: np.ndarray, *, degree: int
    ) -> dict[str, Any]:
        if degree < 1:
            raise ValueError("polynomial_degree muss mindestens 1 sein.")
        coefficients = np.polyfit(np.log(intensity), c, degree)
        back = np.polyval(coefficients, np.log(intensity))
        rmse = float(np.sqrt(np.mean(np.square(back - c))))
        return {
            "parameters": {"coefficients": coefficients.tolist()},
            "metrics": {"rmse_concentration_pct": rmse},
        }

    @staticmethod
    def _fit_metrics(observed: np.ndarray, predicted: np.ndarray) -> dict[str, float]:
        residual = observed - predicted
        sst = float(np.sum(np.square(observed - np.mean(observed))))
        ssr = float(np.sum(np.square(residual)))
        return {
            "r2_adc": np.nan if sst == 0 else 1.0 - ssr / sst,
            "rmse_adc": float(np.sqrt(np.mean(np.square(residual)))),
            "mae_adc": float(np.mean(np.abs(residual))),
        }

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------
    def export(
        self,
        output_folder: str | Path,
        *,
        wavelength: int | str = 640,
        window_s: float = 50.0,
        include_plot: bool = True,
        include_calibrated: bool = True,
    ) -> Path:
        """Exportiert Standardtabellen und einen Rohdatenplot."""
        output = Path(output_folder)
        output.mkdir(parents=True, exist_ok=True)

        self.overview(print_output=False).to_csv(output / "run_overview.csv", index=False)
        self.check(print_output=False).to_csv(output / "quality_checks.csv", index=False)
        self.timeline(print_output=False).to_csv(output / "parsed_markers.csv", index=False)
        self.injection_statistics(wavelength, window_s=window_s).to_csv(
            output / "injection_statistics.csv", index=False
        )

        if self.calibration_models:
            self.save_calibrations(output / "calibration_used.json")
            if include_calibrated:
                self.apply_calibration().to_csv(
                    output / "calibrated_timeseries.csv", index=False
                )

        if include_plot:
            figure, _ = self.plot_raw(wavelength)
            figure.savefig(output / f"raw_{int(wavelength)}nm.png", dpi=160)
            plt.close(figure)

        summary = self._markdown_summary(wavelength, window_s)
        (output / "run_summary.md").write_text(summary, encoding="utf-8")
        return output

    # ------------------------------------------------------------------
    # Hilfsfunktionen
    # ------------------------------------------------------------------
    def role(self, sensor_id: int) -> str:
        return self.sensor_roles.get(int(sensor_id), f"sensor_{int(sensor_id)}")

    def sensor_style(self, sensor_id: int) -> dict[str, Any]:
        """Gibt den zentral definierten Plotstil eines Sensors zurück.

        Passe ``DEFAULT_SENSOR_STYLES`` oben in der Klasse an, um Farben,
        Linienstile oder Linienbreiten projektweit zu ändern.
        """
        role = self.role(sensor_id)
        style = dict(self.DEFAULT_FALLBACK_SENSOR_STYLE)
        style.update(self.DEFAULT_SENSOR_STYLES.get(role, {}))
        return style

    def _resolve_sensor_ids(
        self, sensor_ids: Optional[Iterable[int]]
    ) -> list[int]:
        if sensor_ids is None:
            priority = {1001: 0, 1000: 1, 1002: 2}
            selected = sorted(
                self.sensors,
                key=lambda sensor_id: (priority.get(int(sensor_id), 99), int(sensor_id)),
            )
        else:
            selected = [int(v) for v in sensor_ids]
        missing = sorted(set(selected) - set(self.sensors))
        if missing:
            raise KeyError(f"Nicht geladene sensor-IDs: {missing}")
        return selected

    def _sensor_wavelengths(self, sensor_id: int) -> list[int]:
        return sorted(
            int(column)
            for column in self.sensors[int(sensor_id)].columns
            if _NUMBER_COLUMN.fullmatch(column)
        )

    def _validate_wavelength(self, wavelength: int | str) -> str:
        name = str(int(wavelength))
        missing = [
            sensor_id
            for sensor_id, frame in self.sensors.items()
            if name not in frame.columns
        ]
        if missing:
            raise ValueError(
                f"wavelength {name} nm fehlt bei sensor(en) {missing}. "
                f"Erkannte Kanäle: {self.wavelengths}"
            )
        return name

    def _marker_for_step(self, step: int) -> dict[str, Any]:
        matches = self.markers.loc[self.markers["step"] == int(step)]
        if matches.empty:
            raise KeyError(f"STEP_{step} wurde nicht gefunden.")
        return matches.iloc[0].to_dict()

    def _step_summary(self) -> str:
        if not self.steps:
            return "keine erkannt"
        return f"{self.steps[0]}–{self.steps[-1]} ({len(self.steps)} steps)"

    @staticmethod
    def _trapezoid(values: np.ndarray, x: np.ndarray) -> float:
        if values.size < 2:
            return 0.0
        function = getattr(np, "trapezoid", np.trapz)
        return float(function(values, x))

    def _require_model(self, sensor_id: int, wavelength_nm: int) -> CalibrationModel:
        if sensor_id not in self.calibration_models:
            raise KeyError(f"Kein calibrationmodell für sensor {sensor_id} vorhanden.")
        model = self.calibration_models[sensor_id]
        if model.wavelength_nm != wavelength_nm:
            raise ValueError(
                f"Modell von sensor {sensor_id} gilt für {model.wavelength_nm} nm, "
                f"nicht für {wavelength_nm} nm."
            )
        return model

    def _markdown_summary(self, wavelength: int | str, window_s: float) -> str:
        experiment = self.metadata.get("experiment_name", self.folder.name)
        batch = self.metadata.get("batch_number", "–")
        duration = max(frame["time_min"].max() for frame in self.sensors.values())
        return (
            f"# Auswertung: {experiment}\n\n"
            f"- Batch: {batch}\n"
            f"- sensors: {len(self.sensors)}\n"
            f"- Marker/Steps: {len(self.markers)} / {self._step_summary()}\n"
            f"- Messdauer: {duration:.2f} min\n"
            f"- Auswertewellenlänge: {int(wavelength)} nm\n"
            f"- Injektionsfenster: {float(window_s):g} s\n"
            f"- calibrationmodelle: {len(self.calibration_models)}\n"
        )


# Kürzerer Alias für Notebook-Zellen.
ExperimentAnalyzer = SpectralExperimentAnalyzer


__all__ = [
    "CalibrationModel",
    "ExperimentAnalyzer",
    "SpectralExperimentAnalyzer",
]
