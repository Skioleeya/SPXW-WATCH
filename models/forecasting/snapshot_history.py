"""
models/forecasting/snapshot_history.py
=========================================
Load historical ATM implied-vol and spot prices from surface snapshot CSVs.

Used for:
    • IV rank / IV percentile (current ATM IV vs historical range)
    • Vol risk premium history (IV − realized RV over time)

Snapshot format (one row per option):
    Timestamp, Symbol, Spot, DataMode, Expiry, Strike, IV, ...

For each trading day, the front-expiry ATM IV is estimated by:
    1. Reading the latest snapshot file in SNAPSHOT_DIR/{symbol}/{YYYYMMDD}/
    2. Selecting the front (shortest) expiry
    3. Linear interpolation of IV at the Spot price
"""

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd


_REQUIRED_COLS = {"Spot", "Expiry", "Strike", "IV"}


def load_atm_iv_history(
    symbol: str,
    snapshot_base_dir,
    lookback_days: int = 30,
) -> pd.DataFrame:
    """
    Daily front-expiry ATM IV history from surface snapshot files.

    Parameters
    ----------
    symbol : str
        Ticker symbol (e.g. "QQQ").
    snapshot_base_dir : str or Path
        Root snapshot directory (e.g. Path("surface_snapshots")).
    lookback_days : int
        How many recent trading days to include.

    Returns
    -------
    DataFrame with columns: date (str YYYYMMDD), spot (float), atm_iv (float fraction)
    Sorted ascending by date.  Empty DataFrame if no snapshots found.
    """
    base = Path(snapshot_base_dir) / symbol
    if not base.exists():
        return pd.DataFrame(columns=["date", "spot", "atm_iv"])

    date_dirs = sorted(
        [d for d in base.iterdir() if d.is_dir() and d.name.isdigit() and len(d.name) == 8],
        reverse=True,
    )[:lookback_days]

    records = []
    for date_dir in date_dirs:
        date_str = date_dir.name
        snap = _pick_snapshot_file(date_dir, symbol)
        if snap is None:
            continue
        record = _extract_atm_iv(snap, date_str)
        if record is not None:
            records.append(record)

    if not records:
        return pd.DataFrame(columns=["date", "spot", "atm_iv"])

    return (
        pd.DataFrame(records)
        .sort_values("date")
        .reset_index(drop=True)
    )


def _pick_snapshot_file(date_dir: Path, symbol: str) -> Optional[Path]:
    """Return the best snapshot file for a given date directory."""
    # Prefer the _latest_surface file; fall back to the most recent timestamped file.
    latest = date_dir / f"{symbol}_latest_surface.csv"
    if latest.exists():
        return latest
    candidates = sorted(date_dir.glob(f"{symbol}_surface_*.csv"), reverse=True)
    return candidates[0] if candidates else None


def _extract_atm_iv(fpath: Path, date_str: str) -> Optional[dict]:
    """Read one snapshot file and return {date, spot, atm_iv} or None."""
    try:
        df = pd.read_csv(fpath, usecols=lambda c: c in _REQUIRED_COLS, nrows=1000)
    except Exception:
        return None

    if not _REQUIRED_COLS.issubset(df.columns):
        return None

    for col in ("Spot", "Strike", "IV"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.dropna(subset=["Spot", "Strike", "IV"])
    if df.empty:
        return None

    spot = float(df["Spot"].iloc[0])

    # Front expiry = smallest YYYYMMDD string
    front_expiry = str(df["Expiry"].astype(str).min())
    front = df[df["Expiry"].astype(str) == front_expiry].sort_values("Strike")
    if len(front) < 3:
        return None

    atm_iv = float(np.interp(spot, front["Strike"].values, front["IV"].values))
    if not (0.005 < atm_iv < 5.0):
        return None

    return {"date": date_str, "spot": spot, "atm_iv": atm_iv}


def compute_iv_rank(current_atm_iv: float, history_df: pd.DataFrame):
    """
    Compute IV rank and IV percentile from historical ATM IV data.

    IV Rank  = (current − min) / (max − min), range [0, 1]
    IV Pctile = fraction of history below current, range [0, 1]

    Returns (iv_rank, iv_pctile) or (None, None) if history is too short.
    """
    if history_df.empty or len(history_df) < 5:
        return None, None

    hist = history_df["atm_iv"].dropna().values
    if len(hist) < 2:
        return None, None

    lo, hi = hist.min(), hist.max()
    if hi <= lo:
        return None, None

    iv_rank = float((current_atm_iv - lo) / (hi - lo))
    iv_pctile = float(np.mean(hist < current_atm_iv))

    return max(0.0, min(1.0, iv_rank)), max(0.0, min(1.0, iv_pctile))
