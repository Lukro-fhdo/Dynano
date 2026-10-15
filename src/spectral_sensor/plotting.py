import matplotlib.pyplot as plt


def plot_timeseries(
    sensor_data,
    time_column,
    signal_column,
    *,
    xlabel,
    ylabel,
    title="",
    sensor_styles=None,
):
    """Plottet eine Signalspalte je Sensor gegen eine Zeitspalte.

    Die übergebenen Tabellen werden nicht verändert.
    """
    fig, ax = plt.subplots(figsize=(10, 5))


    for sensor_name, table in sensor_data.items():
        style = sensor_styles.get(sensor_name, {}) if sensor_styles else {}
        ax.plot(
            table[time_column],
            table[signal_column],
            color=style.get("color"),
            label=style.get("label", sensor_name),
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


def plot_measurements(
    sensor_data,
    markers,
    *,
    marker_labels=None,
    **plot_options,
):
    """Plot time series with event markers and optional labels."""
    fig, ax = plot_timeseries(sensor_data, **plot_options)

    time_column = plot_options["time_column"]

    for number, (index, marker) in enumerate( markers.dropna(subset=[time_column]).iterrows()):
        timestamp = marker[time_column]

        ax.axvline(
            timestamp,
            color="0.6",
            linestyle=":",
            linewidth=0.7,
            label="Event markers" if number == 0 else "_nolegend_",
        )

        if marker_labels is not None and index in marker_labels:
            ax.text(
                timestamp,
                0.98,
                marker_labels[index],
                transform=ax.get_xaxis_transform(),
                rotation=90,
                ha="right",
                va="top",
                fontsize=8,
            )

    ax.legend()
    return fig, ax

from pathlib import Path


def save_plot(fig, output_folder, filename):
    """Save a figure as vector PDF and PNG."""
    output_folder = Path(output_folder)
    output_folder.mkdir(parents=True, exist_ok=True)

    fig.savefig(
        output_folder / f"{filename}.pdf",
        bbox_inches="tight",
    )
    fig.savefig(
        output_folder / f"{filename}.png",
        dpi=300,
        bbox_inches="tight",
    )

def plot_window_statistics(
    statistics,
    group_column,
    signal_column,
    *,
    xlabel,
    ylabel,
    title="",
    color="#004488",
):
    """Plot replicate window statistics as boxplots with individual values."""
    groups = sorted(statistics[group_column].dropna().unique())

    values_by_group = [
        statistics.loc[
            statistics[group_column] == group,
            signal_column,
        ].dropna().to_numpy()
        for group in groups
    ]

    fig, ax = plt.subplots(figsize=(9, 5))

    ax.boxplot(
        values_by_group,
        tick_labels=[str(group) for group in groups],
        patch_artist=True,
        showfliers=False,
        boxprops={"facecolor": color, "alpha": 0.25},
        medianprops={"color": color, "linewidth": 1.5},
        whiskerprops={"color": color},
        capprops={"color": color},
    )

    for position, values in enumerate(values_by_group, start=1):
        ax.scatter(
            [position] * len(values),
            values,
            color="black",
            s=20,
            zorder=3,
        )

    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()

    return fig, ax