import os
import logging
from pathlib import Path
from typing import Iterator

import yaml

logger = logging.getLogger(__name__)

LOCAL_TASKS_DIR = Path(__file__).resolve().parent.parent / "tasks"
GITHUB_TASKS_REPO = os.environ.get("GITHUB_TASKS_REPO")  # e.g. "andzol/agentx"; if unset, fall back to local tasks/ dir
GITHUB_TASKS_BRANCH = os.environ.get("GITHUB_TASKS_BRANCH", "main")
GITHUB_TASKS_PATH = os.environ.get("GITHUB_TASKS_PATH", "tasks")
SHEETS_SA_KEY_PATH = os.environ.get("SHEETS_SA_KEY_PATH", "/secrets/sheets-sa-key.json")
USER_AGENT = os.environ.get(
    "SCRAPE_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
)
PRODUCT_PAGE_DELAY_SECONDS = float(os.environ.get("PRODUCT_PAGE_DELAY_SECONDS", "3"))


def load_tasks() -> Iterator[dict]:
    """Yield task dicts, one per YAML file. Reads from the GITHUB_TASKS_REPO
    folder if set (fetched fresh on every run, so a new task just needs a
    git push - no rebuild/redeploy), otherwise from the local tasks/
    directory bundled in the image."""
    if GITHUB_TASKS_REPO:
        yield from _load_tasks_from_github()
    else:
        yield from _load_tasks_from_local()


def _load_tasks_from_local() -> Iterator[dict]:
    for path in sorted(LOCAL_TASKS_DIR.glob("*.yaml")):
        with open(path, "r", encoding="utf-8") as f:
            task = yaml.safe_load(f)
        task["_source"] = str(path)
        yield task


def _load_tasks_from_github() -> Iterator[dict]:
    import requests

    listing_url = (
        f"https://api.github.com/repos/{GITHUB_TASKS_REPO}/contents/"
        f"{GITHUB_TASKS_PATH}?ref={GITHUB_TASKS_BRANCH}"
    )
    resp = requests.get(listing_url, headers={"Accept": "application/vnd.github+json"}, timeout=20)
    resp.raise_for_status()
    entries = resp.json()

    yaml_entries = [e for e in entries if e["name"].endswith(".yaml")]
    if not yaml_entries:
        logger.warning("No task files found in %s/%s@%s", GITHUB_TASKS_REPO, GITHUB_TASKS_PATH, GITHUB_TASKS_BRANCH)

    for entry in sorted(yaml_entries, key=lambda e: e["name"]):
        raw = requests.get(entry["download_url"], timeout=20)
        raw.raise_for_status()
        task = yaml.safe_load(raw.text)
        task["_source"] = entry["download_url"]
        yield task
