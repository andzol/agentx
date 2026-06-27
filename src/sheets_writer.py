"""Google Sheets writer using a service account (no interactive login,
unlike chrome.identity.getAuthToken() in the original extension). Adds a
dedup check before appending, which the original extension didn't have."""

import logging

from google.oauth2 import service_account
from googleapiclient.discovery import build

from config import SHEETS_SA_KEY_PATH

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

_service = None


def _get_service():
    global _service
    if _service is None:
        creds = service_account.Credentials.from_service_account_file(
            SHEETS_SA_KEY_PATH, scopes=SCOPES
        )
        _service = build("sheets", "v4", credentials=creds)
    return _service


def get_existing_column_values(sheet_id: str, tab: str, column: str) -> set[str]:
    service = _get_service()
    range_ = f"{tab}!{column}:{column}"
    result = (
        service.spreadsheets()
        .values()
        .get(spreadsheetId=sheet_id, range=range_)
        .execute()
    )
    values = result.get("values", [])
    return {row[0] for row in values if row}


def append_rows(sheet_id: str, tab: str, rows: list[list]) -> int:
    """Appends rows and returns how many were written. No-op if rows is empty."""
    if not rows:
        return 0
    service = _get_service()
    body = {"values": rows}
    range_ = f"{tab}!A1"
    service.spreadsheets().values().append(
        spreadsheetId=sheet_id,
        range=range_,
        valueInputOption="USER_ENTERED",
        insertDataOption="INSERT_ROWS",
        body=body,
    ).execute()
    logger.info("Appended %d row(s) to sheet %s tab %s", len(rows), sheet_id, tab)
    return len(rows)


def append_rows_deduped(sheet_id: str, tab: str, dedup_column: str, rows_with_keys: list[tuple[str, list]]) -> int:
    """rows_with_keys: list of (dedup_key, row). Skips rows whose dedup_key
    already exists in dedup_column on the sheet."""
    existing = get_existing_column_values(sheet_id, tab, dedup_column)
    new_rows = [row for key, row in rows_with_keys if key not in existing]
    skipped = len(rows_with_keys) - len(new_rows)
    if skipped:
        logger.info("Skipped %d duplicate row(s) for sheet %s", skipped, sheet_id)
    return append_rows(sheet_id, tab, new_rows)
