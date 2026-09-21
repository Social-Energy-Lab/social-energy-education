"""BLE proximity beacons: logger files → canonical contact, self-report and eco tables."""

from .ingest import BeaconConfig, BeaconTables, ingest_logs

__all__ = ["BeaconConfig", "BeaconTables", "ingest_logs"]
