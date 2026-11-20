import glob

import pandas as pd


def load_raw(name):
    """Load and combine all raw state files for one collector.

    Args:
        name: Collector name used in the file names

    Return one DataFrame with the rows of every matching file, in file (time) order.
    Raises FileNotFoundError if no file matches the pattern
    """
    pattern = f"data/raw/states_{name}_*.parquet"
    state_files = sorted(glob.glob(pattern))
    if not state_files:
        raise FileNotFoundError(f"No raw files matching '{pattern}'")

    states = [pd.read_parquet(f) for f in state_files]
    return pd.concat(states, ignore_index=True)


def remove_duplicates(df):
    """Remove repeated positions of the same aircraft.

    A row is considered duplicate when another one has the same
    icao24 and time_position. The first occurreence is kept.

    Returns a new DataFrame with a new index. The input is not modified.
    """
    return df.drop_duplicates(subset=["icao24", "time_position"]).reset_index(drop=True)

def remove_missing_positions(df):
    """Drop rows where position of the aircraft is missing.
    
    All rows where either time_position, latitude or
    longitude is null will be dropped since a row without
    a time or position can't be placed on a trajectory.
    
    Returns a new DataFrame with a new index. The input is not modified.
    """
    return df.dropna(subset=["time_position", "latitude", "longitude"]).reset_index(drop=True)