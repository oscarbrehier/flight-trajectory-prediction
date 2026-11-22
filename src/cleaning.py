import glob

import pandas as pd

from src import geo


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

def split_flights(df, max_gap_s=600):
	"""Assign each row to a flight by adding a flight_id column.
 
 	Rows are grouped per aircraft (icao24) and ordered by time_position.,
	A new flight starts at an aircraft's first point, or after a gap
	greater than `max_gap_s` seconds since it's previous point.
	flight_id is "<icao24>_<n>", with n counting from 1 per aircraft.
	
	Returns a new DataFrame, sorted by icao24 and time_position with a new
	index. The input is not modified.
	"""
	out = df.sort_values(by=["icao24", "time_position"]).reset_index(drop=True)
	gap_s = out.groupby("icao24")["time_position"].diff()
	new_flight = (gap_s.isna()) | (gap_s > max_gap_s)
	flight_number = new_flight.groupby(out["icao24"]).cumsum()
	out["flight_id"] = out["icao24"] + '_' + flight_number.astype(str)
	return out

def keep_arrivals(
	df,
	airport_coords,
	max_distance_km=7,
	max_altitude_m=500,
	min_airborne_alt_m=1000
):
	"""Keep only flights which landed at the given airport.
 
 	A flight counts as an arrival if:
  		- it is last point is within `max_distance_km` of the airport
    	- that last point was on the ground or below `max_altitude_m`
     	- and at some point the flight was above `min_airborne_alt_m`
      		(this rules out aircraft that only moved while on ground).
        
    Args:
    	df: Flights DataFrame from split_flights (needs flight_id, latitude
     		longitude, geo_altitude, on_ground) sorted by time.
       	airport_coords: Dict with `lat` and `lon` of the airport in degrees.
        max_distance_km: Max distance of the last point to the airport.
        max_altitude_m: Max altitude of the last point, if not on ground.
        min_airborne_alt_m: Altitude the flight must have exceeded at least once.
        
    Returns a new DataFrame with all the rows of the arriving flights. The input
    is not modified.
    """
	final_point = df.groupby("flight_id").tail(1).copy()
	final_point["distance_to_airport_km"] = geo.haversine_km(final_point["latitude"], final_point["longitude"], airport_coords["lat"], airport_coords["lon"])
 
	airborne_flight_ids = df[df["geo_altitude"] > min_airborne_alt_m]["flight_id"].unique()
 
	is_close = final_point["distance_to_airport_km"] < max_distance_km
	is_low = (final_point["on_ground"]) | (final_point["geo_altitude"] < max_altitude_m)
	was_airborne = final_point["flight_id"].isin(airborne_flight_ids)
	arrival_endpoints = final_point[is_close & is_low & was_airborne]
 
	arrivals = df[df["flight_id"].isin(arrival_endpoints["flight_id"])]
	return arrivals.reset_index(drop=True)