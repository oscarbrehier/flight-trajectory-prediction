import numpy as np

EARTH_RADIUS_KM = 6371.0

CDG_COORDS = {
	"lat": 49.01,
	"lon": 2.55
}

def haversine_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points on Earth in km."""
    
    lat1_rad = np.radians(lat1)
    lon1_rad = np.radians(lon1)
    lat2_rad = np.radians(lat2)
    lon2_rad = np.radians(lon2)

    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad

    a = (
        np.square(np.sin(dlat / 2))
        + np.cos(lat1_rad) * np.cos(lat2_rad) * np.square(np.sin(dlon / 2))
	)
    distance = 2 * EARTH_RADIUS_KM * np.arcsin(np.sqrt(a))
    return distance