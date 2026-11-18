import pandas as pd
import requests

from src.opensky_auth import tokens

STATE_COLUMNS = [
		"icao24",
		"callsign",
		"origin_country",
		"time_position",
		"last_contact",
		"longitude",
		"latitude",
		"baro_altitude",
		"on_ground",
		"velocity",
		"true_track",
		"vertical_rate",
		"sensors",
		"geo_altitude",
		"squawk",
		"spi",
		"position_source",
		"category"
]

def fetch_snapshot(lamin, lomin, lamax, lomax):
    """Fetch the current state of all aircraft inside a bounding box from OpenSky.
    
    Args:
        lamin, lamax: Minimum and maximum latitude, in degrees.
        lomin, lomax: Minimum and maximum longitude, in degrees.
        
    Returns a DataFrame with one row per aircraft (see states_to_dataframe).
    Raises an HTTPError if the request fails.
    """
    params = {
		"lamin": lamin,
		"lomin": lomin,
		"lamax": lamax,
		"lomax": lomax,
		"extended": 1
	}
    
    response = requests.get(
		"https://opensky-network.org/api/states/all",
		headers=tokens.headers(),
		params=params,
		timeout=10
	)
    
    response.raise_for_status()
    
    data = response.json()
    df = states_to_dataframe(data)
    
    return df


def states_to_dataframe(data):
    """Convert an OpenSky /states/all response into a DataFrame with one row per aircraft.
    
    Columns follow STATE_COLUMNS plus snapshot_time: the response's
    timestamp as a UTC datetime, the same for every row.
    Returns an empty DataFrame with those columns
    if the bounding box contains no aircraft.
    """
    
    df = pd.DataFrame(data["states"], columns=STATE_COLUMNS)
    df["snapshot_time"] = pd.to_datetime(data["time"], unit="s", utc=True)
    return df

def prepare_map_data(df):
	"""Prepare state vectors for the live map.
	
	Keeps only airborne aircraft with a known position 
 	(where latitude and longitude are not missing),
	and adds a geo_altitude_ft column, converting geo_altitude from meters to feet.
	Returns a new DataFrame, the input data is not modified.
	"""
	new_df = df[~df["on_ground"]].copy()
	new_df = new_df.dropna(subset=["latitude", "longitude"])
	new_df["geo_altitude_ft"] = new_df["geo_altitude"] * 3.28084
	new_df["velocity_kt"] = new_df["velocity"] * 1.94384
	return new_df