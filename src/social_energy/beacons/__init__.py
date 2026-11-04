"""BLE proximity beacons: logger files → canonical contact, self-report and eco tables."""

from .coverage import coverage_by_hour
from .cycles import (
    estimate_clock_rate,
    lost_windows,
    power_cycles,
    read_clock_anchors,
    read_deliveries,
)
from .ingest import BeaconConfig, BeaconTables, ingest_logs, ingest_logs_to
from .presses import press_episodes
from .purge import (
    ManifestError,
    PurgedDeviceError,
    check_purged,
    find_purged_lines,
    purge_devices,
)
from .reference import reference_labels
from .sync import (
    apply_boots,
    fit_boots,
    ingest_with_sync,
    mirror_lag,
    period_day_lags,
    uptime_periods,
)
from .witness import decide, ingest_with_witnesses, votes_from_tables, witness_votes

__all__ = [
    "BeaconConfig",
    "BeaconTables",
    "ManifestError",
    "PurgedDeviceError",
    "apply_boots",
    "check_purged",
    "coverage_by_hour",
    "decide",
    "estimate_clock_rate",
    "find_purged_lines",
    "fit_boots",
    "ingest_logs",
    "ingest_logs_to",
    "ingest_with_sync",
    "ingest_with_witnesses",
    "lost_windows",
    "mirror_lag",
    "period_day_lags",
    "power_cycles",
    "press_episodes",
    "purge_devices",
    "read_clock_anchors",
    "read_deliveries",
    "reference_labels",
    "uptime_periods",
    "votes_from_tables",
    "witness_votes",
]
