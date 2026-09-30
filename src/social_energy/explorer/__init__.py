"""An interactive, local explorer of co-presence, places and self-reports.

``write_bundle`` turns already-filtered presence tables into an ID-free bundle under the data
root; ``make_server`` serves it with the browser app on ``127.0.0.1`` only.
"""

from .bundle import BundleInput, read_bundle, write_bundle

__all__ = ["BundleInput", "read_bundle", "write_bundle"]
