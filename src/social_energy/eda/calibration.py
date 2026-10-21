"""Shimmer3 GSR+ unit conversion: raw counts to µS, g and mV.

The GSR formula and feedback resistors reproduce Shimmer Base's calibrated export sample by
sample (checked on DSA 2026 data, docs/context/instruments/eda.md).
"""

from __future__ import annotations

import numpy as np

#: Feedback resistor per GSR auto-range index, kΩ.
GSR_FEEDBACK_KOHM = (40.2, 287.0, 1000.0, 3300.0)
#: Shimmer's floor on skin resistance, kΩ (so conductance never exceeds 125 µS).
MIN_SKIN_KOHM = 8.0
ADC_MAX = 4095  # 12-bit converter
ACC_COUNTS_PER_G = 8192.0  # ±4 g range
ADC_REF_MV = 3000.0


def gsr_microsiemens(gsr_range: np.ndarray, adc: np.ndarray) -> np.ndarray:
    """Skin conductance in µS; NaN where the reading carries no resistance.

    Invalid: ADC 0 or above 4095 (not a 12-bit reading), and ADC ≤ 682, where
    ``adc * 6/4095 - 1 <= 0`` (open circuit or saturated input).
    """
    rf = np.asarray(GSR_FEEDBACK_KOHM)[np.clip(np.asarray(gsr_range), 0, 3)]
    adc = np.asarray(adc, dtype=np.float64)
    denom = adc * 6.0 / ADC_MAX - 1.0
    valid = (adc > 0) & (adc <= ADC_MAX) & (denom > 0)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.where(valid, rf / denom, np.nan)
    r = np.where(valid & (r < MIN_SKIN_KOHM), MIN_SKIN_KOHM, r)
    return 1000.0 / r


def accel_g(counts: np.ndarray) -> np.ndarray:
    return np.asarray(counts, dtype=np.float64) / ACC_COUNTS_PER_G


def ppg_mv(adc: np.ndarray) -> np.ndarray:
    return np.asarray(adc, dtype=np.float64) * ADC_REF_MV / ADC_MAX
