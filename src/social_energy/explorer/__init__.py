"""An interactive, local explorer of co-presence, places and self-reports.

``write_bundle`` turns already-filtered presence tables into a bundle under the data root whose
tables carry no IDs (only the team bundle's ``person.json`` names study IDs); ``make_server``
serves it with the browser app on ``127.0.0.1`` only.
"""

from .bundle import BundleInput, read_bundle, write_bundle
from .server import make_server

__all__ = ["BundleInput", "make_server", "read_bundle", "write_bundle"]
