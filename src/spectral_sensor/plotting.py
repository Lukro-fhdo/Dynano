import matplotlib.pyplot as plt


def plot_timeseries(
    sensor_data,
    time_column,
    signal_column,
    *,
    xlabel,
    ylabel,
    title="",
):
    """Plottet eine Signalspalte je Sensor gegen eine Zeitspalte.

    Die übergebenen Tabellen werden nicht verändert.
    """
    fig, ax = plt.subplots(figsize=(10, 5))

    for sensor_name, table in sensor_data.items():
        ax.plot(
            table[time_column],
            table[signal_column],
            label=sensor_name,
        )

    
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.legend()
    ax.grid(alpha=0.3)

    x_min = min(
        table[time_column].min()
        for table in sensor_data.values()
        if not table.empty
    )
    x_max = max(
        table[time_column].max()
        for table in sensor_data.values()
        if not table.empty
    )

    ax.set_xlim(x_min, x_max)
    fig.tight_layout()

    return fig, ax