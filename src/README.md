# Dynano — Optisches Sensormodell für SPION-Detektion

Python-Funktionen zur Auswertung von Spektralsensor-Messungen an einem
Mikrofluidikkanal. Der bisherige `spectral_experiment_analyzer.py` wird
schrittweise in verständliche Module unter `src/spectral_sensor/` aufgeteilt.

## Arbeitsweise

Die Anwendung erfolgt in Jupyter-Notebooks: oben ein Metadaten- und
Parameterblock mit Dateipfaden, Wellenlänge, Markerauswahl und Zeitfenstern;
darunter kurze Funktionsaufrufe und sichtbare Ergebnisse.
Die Funktionen erhalten ihre Eingaben ausdrücklich. Rohdaten bleiben erhalten.

## Aktueller Stand

| Modul | Vorhandene Funktionen |
| --- | --- |
| `io.py` | `read_sensor_csv`, `read_marker_rows`, `read_protocol`, `discover_files` |
| `preprocessing.py` | `synchronize_time`, `marker_time`, `select_time_window` |
| `normalization.py` | `baseline_correction`, `get_min`, `normalize_signal` |
| `plotting.py` | `plot_timeseries` für Rohdaten, Ausschnitte und normierte Signale |
| `analysis.py` | Noch leer; nächster Arbeitsschritt |

Der Ablauf ist: **Einlesen → gemeinsame Zeitachse → Zeitfenster →
Baseline-Korrektur → Normierung → Plot.**

- Sensordaten liegen als Dictionary mit einer pandas-Tabelle je Sensor vor.
- `synchronize_time` ergänzt Sekunden seit dem frühesten Sensor- oder Markerzeitpunkt.
  Die ursprünglichen Zeitstempel in Millisekunden bleiben erhalten.
- `marker_time` liest die Zeit über den Tabellenindex, nicht über die STEP-Nummer.
- `select_time_window` schließt den Start ein und das Ende aus. Zusätzlich wird
  `time_from_start_s` als Zeit seit Fensterstart ergänzt.
- Die Baseline ist der Median im gewählten Zeitfenster vor der Injektion.
- `get_min` bestimmt je Sensor das Minimum im ausgewählten Referenzfenster.
- `plot_timeseries` erhält Zeit- und Signalspalte; die x-Grenzen folgen den Daten.

```text
absorption_adc = baseline_adc - raw_adc
normalized_0_1 = absorption_adc / (baseline_adc - reference_adc_100pct)
```

Die Normierung wird nicht auf 0 bis 1 begrenzt. Fehlende Baselines oder
ungültige Nenner ergeben NaN.

## Nachvollziehbarkeit

Dateipfade, Experimentangaben, Wellenlänge und Auswertezeiten werden im Notebook
festgehalten. Zeitparameter tragen ihre Einheit im Namen (`start_s`, `window_s`,
`baseline_window_s`). `read_protocol` liest Dateiname, Experimentname, Batch,
Startzeit und angegebene Wellenlängen aus `Protocol.md`, nicht den gesamten Ablauf.

## Noch offen

- `get_min` nach `analysis.py` verschieben; Peak-Werte und Integrale ergänzen.
- Automatische Dateisuche: `Spectralsensor` im Suchmuster weicht von
  `SpectralSensor` in den vorhandenen Dateinamen ab. Vorerst explizite Pfade verwenden.
- Den vollständigen Ablauf im Notebook prüfen. Eine vollständige numerische
  Gleichheit aller neuen Module mit dem bisherigen Analyzer ist noch nicht belegt.
- Weitere Analyzer-Funktionen und Ergebnisexporte schrittweise übernehmen.

Abhängigkeiten stehen in `requirements.txt`. Die Beispiele verwenden derzeit
Imports wie `from src.spectral_sensor.preprocessing import synchronize_time`;
der Projektordner muss dafür im Python-Suchpfad liegen.
