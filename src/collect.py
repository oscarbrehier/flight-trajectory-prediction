import time
import os
import logging
from datetime import datetime, timezone

import pandas as pd
import requests

from src import opensky
from src import config

INTERVAL = 25
SAVE_EVERY = 60 * 60

logger = logging.getLogger(__name__)

def setup_logging():
    """Log to daily file in logs/ and to the terminal"""
    os.makedirs("logs", exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(f"logs/collect_{today}.log"),
            logging.StreamHandler(),
        ],
    )


class StateCollector:
    """Poll OpenSky for aircraft in a bounding box and save the result to Parquet.

    Snapshots are kept in memory and written to data/raw/ every
    `save_frequency` seconds, one file per chunk, named after the
    chunk's first snapshot time (UTC).
    """

    def __init__(self, bbox, name, interval=INTERVAL, save_frequency=SAVE_EVERY):
        """
        Args:
                bbox: Dict with lamin, lomin, lamax, lomax (degrees).
                name: Short label used in file names, e.g. "paris".
                interval: Seconds to wait between API calls.
                save_frequency: Seconds between saves to disk.
        """
        self.bbox = bbox
        self.name = name
        self.interval = interval
        self.save_frequency = save_frequency
        self.snapshots = []
        self.last_saved = time.time()

    def poll_once(self):
        """Fetch one snapshot and keep it in memory. Network errors are logged out, not raised."""
        try:
            df = opensky.fetch_snapshot(**self.bbox)
            self.snapshots.append(df)
            logger.info(f"Fetched {len(df)} aircraft")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to fetch snapshot: {e}")

    def save_data(self):
        """Combine collected snapshots into one Parquet file in data/raw/, the reset."""

        if not self.snapshots:
            logger.warning("No snapshots collected, nothing saved.")
            return
        all_states = pd.concat(self.snapshots, ignore_index=True)
        start_label = all_states["snapshot_time"].min().strftime("%Y-%m-%d_%H-%M")
        path = f"data/raw/states_{self.name}_{start_label}.parquet"
        all_states.to_parquet(path, index=False)
        logger.info(
            f"Saved {len(all_states)} rows from {len(self.snapshots)} snapshots to {path}"
        )
        self.snapshots = []
        self.last_saved = time.time()

    def run(self):
        """Poll forever, saving every `save_frequency`."""
        while True:
            self.poll_once()
            if time.time() - self.last_saved > self.save_frequency:
                self.save_data()
            time.sleep(INTERVAL)


def main():
    setup_logging()
    os.makedirs("data/raw", exist_ok=True)

    collector = StateCollector(config.PARIS_BBOX, name="paris")
    logger.info(f"Collector started: {collector.name}, every {collector.interval}s")

    try:
        collector.run()
    except KeyboardInterrupt:
        logger.info("Ctrl+C received, saving and exiting")
        collector.save_data()
    except Exception:
        logger.exception("Unexpected error, saving and exiting")
        collector.save_data()
        raise


if __name__ == "__main__":
    main()
