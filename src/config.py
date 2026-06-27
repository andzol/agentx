import os
import logging
from pathlib import Path
from typing import Iterator

import yaml

logger = logging.getLogger(__name__)

LOCAL_TASKS_DIR = Path(__file__).resolve().parent.parent / "tasks"
GCS_BUCKET = os.environ.get("TASKS_BUCKET")  # if unset, fall back to local tasks/ dir
GCS_PREFIX = os.environ.get("TASKS_PREFIX", "tasks/")
SHEETS_SA_KEY_PATH = os.environ.get("SHEETS_SA_KEY_PATH", "/secrets/sheets-sa-key.json")
USER_AGENT = os.environ.get(
    "SCRAPE_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)
PRODUCT_PAGE_DELAY_SECONDS = float(os.environ.get("PRODUCT_PAGE_DELAY_SECONDS", "3"))


def load_tasks() -> Iterator[dict]:
    """Yield task dicts, one per YAML file. Reads from GCS if TASKS_BUCKET is
    set, otherwise from the local tasks/ directory bundled in the image."""
    if GCS_BUCKET:
        yield from _load_tasks_from_gcs()
    else:
        yield from _load_tasks_from_local()


def _load_tasks_from_local() -> Iterator[dict]:
    for path in sorted(LOCAL_TASKS_DIR.glob("*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            task = yaml.safe_load(f)
        task["_source"] = str(path)
        yield task


def _load_tasks_from_gcs() -> Iterator[dict]:
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(GCS_BUCKET)
    blobs = list(bucket.list_blobs(prefix=GCS_PREFIX))
    if not blobs:
        logger.warning("No task files found in gs://%s/%s", GCS_BUCKET, GCS_PREFIX)
    for blob in blobs:
        if not blob.name.endswith(".yaml"):
            continue
        content = blob.download_as_text()
        task = yaml.safe_load(content)
        task["_source"] = f"gs://{GCS_BUCKET}/{blob.name}"
        yield task
