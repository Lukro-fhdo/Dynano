Dynano — Optisches Sensormodell für SPION-Detektion

Auswertung von Spektralsensor-Messungen an einem Mikrofluidikkanal.
Der bisherige `spectral_experiment_analyzer.py` wird schrittweise in kleine,
verständliche Funktionen unter `src/spectral_sensor/` aufgeteilt.

## Arbeitsweise

Ein Jupyter-Notebook beginnt mit einem Metadaten- und Parameterblock:
Dateipfade, Experiment, Wellenlänge, Markerindizes, Fensterdauer,
Baseline-Fenster, Referenzfenster und Ausgabeordner. Darunter folgen kurze
Funktionsaufrufe und sichtbare Ergebnisse. Rohdaten bleiben unverändert.

## Module — Stand 11.09.2026

| Modul | Funktionen |
| --- | --- |
| `io.py` | `read_sensor_csv`, `read_marker_rows`, `read_protocol`, `discover_files`, `save_results` |
| `preprocessing.py` | `synchronize_time`, `marker_time`, `select_time_window` |
| `normalization.py` | `baseline_correction`, `normalize_signal` |
| `analysis.py` | `get_min`, `get_peak`, `get_integral` |
| `plotting.py` | `plot_timeseries` |

## Ablauf einer Auswertung

1. Sensoren, Marker und Protokoll einlesen.
2. Mit `synchronize_time` eine gemeinsame Zeitachse erzeugen.
3. Rohsignale plotten und die Markertabelle ansehen.
4. Mit `marker_time` den Fensterstart wählen und mit `select_time_window`
   alle Sensoren auf dasselbe Zeitfenster zuschneiden.
5. Die Baseline vor der Injektion bestimmen und das Signal korrigieren.
6. Ein Referenzfenster auswählen, dessen Minima mit `get_min` bestimmen
   und damit die Signale normieren.
7. Signale plotten sowie Peak-Höhe, Peak-Zeitpunkt und Integral berechnen.
8. Peak- und Integraltabelle über `sensor` zusammenführen. Mit `save_results`
   eine CSV je Sensor und `metrics.csv` speichern.

## Zeitachsen und Berechnungen

- Eingabezeitstempel sind Millisekunden. `time_s` bezeichnet Sekunden seit dem
  frühesten Zeitstempel aller Sensoren und Marker. Sensoruhren werden nicht
  gegeneinander korrigiert und Messpunkte nicht interpoliert.
- `marker_time` verwendet den Tabellenindex, nicht die STEP-Nummer im Text.
- Zeitfenster umfassen `[start_s, start_s + window_s)`.
  `time_from_start_s` ist die Zeit relativ zu diesem gemeinsamen Fensterstart.
- Die Baseline ist der Median im gewählten Zeitraum vor der Injektion.
- Als 100-%-Referenz dient das Minimum im ausdrücklich ausgewählten Referenzfenster.

```text
absorption_adc = baseline_adc - raw_adc
normalized_0_1 = absorption_adc / (baseline_adc - reference_adc_100pct)
```

Die Normierung wird nicht auf 0 bis 1 begrenzt. Fehlende Baselines oder
ungültige Nenner ergeben NaN. Für das korrigierte ADC-Signal haben Peaks die
Einheit ADC und Integrale ADC·s. Die Integration verwendet die tatsächlichen
Messzeiten; `positive_only=True` setzt negative Signalwerte vorher auf null.
Ungültige Zeit-Signal-Paare werden entfernt, verbleibende Punkte auch über
Messlücken hinweg verbunden. Bei weniger als zwei gültigen Punkten wird 0 geliefert.

## Nachvollziehbarkeit und offene Punkte

- Dateipfade, Einstellungen und Referenzauswahl zentral im Notebook festhalten.
  `read_protocol` liest Dateiname, Experimentname, Batch, Startzeit und
  Wellenlängen aus `Protocol.md`; nicht den gesamten Versuchsablauf.
- Der CSV-Export speichert noch keine separate Metadatendatei. Vorhandene
  gleichnamige Ergebnisdateien werden überschrieben.
- Die automatische Suche verwendet `Spectralsensor`, vorhandene Dateien heißen
  `SpectralSensor`. Vorerst ausdrücklich angegebene Dateipfade verwenden.
- Der gemeldete Versatz von Sensor 3 trat im Zeitfensterplot auf; der Rohdatenplot
  war plausibel. Die Ursache ist noch nicht bestätigt. Nächster Schritt ist ein
  vollständiger Notebook-Durchlauf für eine konkrete Messung, mit Prüfung der
  Zeitachsen direkt nach der Fensterauswahl.
- Nach Änderungen an Modulen diese vor dem erneuten Berechnen laden. Bereits
  berechnete Tabellen ändern sich durch `reload()` nicht. Für den Abschluss:
  Kernel neu starten und alle Zellen von oben nach unten ausführen.
- Eine vollständige numerische Gleichheit mit dem bisherigen Analyzer ist noch
  nicht belegt. Weitere Kalibrations- und Replikatfunktionen sind nicht übertragen.

Abhängigkeiten: `requirements.txt`; `get_integral` benötigt wegen
`np.trapezoid` NumPy ab 2.0. Die bisherigen Notebook-Imports verwenden
`src.spectral_sensor`; dafür muss der Projektordner im Python-Suchpfad liegen.
