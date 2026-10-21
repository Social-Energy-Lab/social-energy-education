"""Matching an export's rows to its SD card by exact PPG sequences (eda.ingest._row_lags).

Made-up PPG noise; the export's clock runs 7.5 s ahead of the card's on the rows they share.
"""

from types import SimpleNamespace

import numpy as np

from social_energy.eda import ingest
from social_energy.eda.ingest import MATCH_EVERY, _row_lags, _SdIndex


def test_rows_far_from_any_card_record_keep_no_lag():
    """The card holds the export's first 3 x MATCH_EVERY rows (device time i / 128). The
    export goes on for 6 x MATCH_EVERY more rows the card never saw. Rows within
    2 x MATCH_EVERY of the last matching probe take its lag of 7.5 s; rows beyond do not
    (they keep the export's own clock and the fallback, flagged, in _correct_export)."""
    rng = np.random.default_rng(0)
    n = 9 * MATCH_EVERY
    adc = rng.integers(1000, 3000, n)
    shared = 3 * MATCH_EVERY
    sd_t = np.arange(shared) / 128.0
    e = SimpleNamespace(t=np.arange(n) / 128.0 + 7.5, segment=np.zeros(n, np.int64))
    lag, run, flag = _row_lags(e, adc, {"r": _SdIndex(sd_t, adc[:shared])})
    last_probe = (shared - ingest.MATCH_CONFIRM - 1) // MATCH_EVERY * MATCH_EVERY
    reach = last_probe + 2 * MATCH_EVERY
    assert np.allclose(lag[: reach + 1], 7.5)
    assert np.isnan(lag[reach + 1 :]).all()
    assert (run[: reach + 1] == "r").all() and not flag.any()
