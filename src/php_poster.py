"""Posts scraped product data to the legacy PHP endpoints (joelbooks.com,
birdsheaven.com), unchanged from addToDatabase() in
Amazon Tracker/background.js so the downstream PHP/sheet sync needs no
changes."""

import logging
import os
from datetime import date

import requests

logger = logging.getLogger(__name__)


def _row_for_product(product: dict) -> list:
    return [
        product["title"],
        product["title"],
        product["cover"],
        product["cover"],
        f"https://www.amazon.com/dp/{product['asin']}?ref=joelbooks",
        product["author"],
        product["author"],
        product["price"],
        product["price"],
        product["content"],
        product["asin"],
        _today_mdy(),
    ]


def _today_mdy() -> str:
    today = date.today()
    return f"{today.month}/{today.day}/{today.year}"


def post_product(endpoint: str, product: dict) -> None:
    values = _row_for_product(product)
    form_data = {
        "action": "insert",
        "book_title": values[0],
        "book_name": values[1],
        "cover_image": values[2],
        "book_cover_src": values[3],
        "book_url": values[4],
        "author_name": values[5],
        "author_name_2": values[6],
        "book_price": values[7],
        "book_price_2": values[8],
        "book_description": values[9],
        "asin": values[10],
        "date_added": values[11],
    }
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
    }
    token = os.environ.get("AGENTX_PHP_TOKEN")
    if token:
        headers["X-AgentX-Token"] = token
    resp = requests.post(endpoint, data=form_data, headers=headers, timeout=20)
    resp.raise_for_status()
    body = resp.text.strip()
    if "Error" in body or "error" in body:
        logger.error("PHP error for %s: %s", product.get("asin"), body)
        raise RuntimeError(f"PHP endpoint returned error: {body}")
    logger.info("Posted %s to %s -> %s | %s", product.get("asin"), endpoint, resp.status_code, body)
