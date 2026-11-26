import pandas as pd

from src import geo

def speed_ratio(df, time_col="time_position", min_reported_kmh=50):
    """Ratio implied speed (from positions) to reported speed, per point.
    
    The implied speed is the distance between consecutive points of
    the same flight divided by the time between them. The reported
    speed is the aircraft's own `velocity`. For good data, the ratio
    is close to 1.
    
    Args:
        df: DataFrame with flight_id, latitude, longitude, velocity
            and `time_col`, sorted by time within each flight.
        time_col: Clock to use: "time_position" (Unix seconds) or
            "snapshot_time" (datetime).
        min_reported_kmh: Points with a reported speed below this get
            NaN, to avoid dividing by ~0 (taxiing, standing still).
            
    Returns a Series aligned with df's index. NaN for each flight's
    first point and for points below `min_reported_kmh`."""
    grouped = df.groupby("flight_id")
    
    prev_lat = grouped["latitude"].shift()
    prev_lon = grouped["longitude"].shift()
    step_km = geo.haversine_km(
        prev_lat,
        prev_lon,
        df["latitude"],
        df["longitude"]
    )

    step = grouped[time_col].diff()
    if pd.api.types.is_timedelta64_dtype(step):
        step = step.dt.total_seconds()
    
    implied_speed_kmh = step_km / (step / 3600)
    reported_speed_kmh = df["velocity"] * 3.6
    
    ratio = implied_speed_kmh / (reported_speed_kmh)
    return ratio.where(reported_speed_kmh >= min_reported_kmh)