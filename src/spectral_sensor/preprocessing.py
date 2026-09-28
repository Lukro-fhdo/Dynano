import pandas as pd

def synchronize_time(sensor_data, markers):
    """Ergänzt eine gemeinsame Zeitachse in Sekunden.

    Eingabe: Zeitstempel in Millisekunden.
    Ausgabe: Kopien der Tabellen und der gemeinsame Startzeitpunkt.
    """
    start_times = [
        table["timestamp"].min()
        for table in sensor_data.values()
    ]
    start_times.append(markers["timestamp_raw_ms"].min())
    start_ms = min(start_times)

    prepared_sensors = {}

    for sensor_name, table in sensor_data.items():
        prepared = table.copy()
        prepared["time_s"] = (prepared["timestamp"] - start_ms) / 1000
        prepared_sensors[sensor_name] = prepared

    prepared_markers = markers.copy()
    prepared_markers["time_s"] = (
        prepared_markers["timestamp_raw_ms"] - start_ms
    ) / 1000

    return prepared_sensors, prepared_markers, start_ms

def select_time_window(synced_sensors, start_s, window_s):
    """Wählt Messpunkte ab start_s bis vor start_s + window_s aus."""
    end_s = start_s + window_s
    selected_sensors = {}

    for sensor_name, table in synced_sensors.items():
        mask = (
            (table["time_s"] >= start_s)
            & (table["time_s"] < end_s)
        )
        selected_sensors[sensor_name] = table.loc[mask].copy()
        selected_sensors[sensor_name]["time_from_start_s"] = (
            selected_sensors[sensor_name]["time_s"] - start_s
        )

    return selected_sensors

def marker_time(markers, marker_num):
    """Gibt die Markerzeit in Sekunden über den Tabellenindex zurück."""
    return float(markers.loc[marker_num, "time_s"])

def synchronize_measurements(sensor_data, marker_data):
    """Align each measurement series with its own marker timestamps."""
    synced_sensors = {}
    synced_markers = {}

    for name, table in sensor_data.items():
        sensors, markers, _ = synchronize_time(
            {name: table},
            marker_data[name],
        )
        synced_sensors[name] = sensors[name]
        synced_markers[name] = markers

    return synced_sensors, synced_markers

def assign_markers(marker_data, label_assignment):
    """Attach supplied metadata to matching marker labels."""
    rows = []

    for sensor_name, markers in marker_data.items():
        for marker_index, marker in markers.iterrows():
            label = str(marker["label"]).strip()

            if label not in label_assignment:
                continue

            rows.append({
                "sensor": sensor_name,
                "marker_index": marker_index,
                "label": label,
                "start_s": marker["time_s"],
                **label_assignment[label],
            })

    return pd.DataFrame(rows)