"""Scrapers for pages that Amazon/Goodreads will serve to a plain HTTP
request (no browser needed) — confirmed via live testing: bestseller/category
listing pages and the Goodreads listopia page return full markup to a bare
`requests` fetch. Amazon product *detail* pages do not (see scrape_product.py)."""

import logging
from datetime import datetime, timezone
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from config import USER_AGENT

logger = logging.getLogger(__name__)

REQUEST_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch_html(url: str) -> str:
    resp = requests.get(url, headers=REQUEST_HEADERS, timeout=20)
    resp.raise_for_status()
    return resp.text


def extract_amazon_listing_urls(html: str, base_url: str) -> list[str]:
    """Mirrors extractAmazonBestSellerURLs() from addtext_logic.js: pull every
    product link out of the bestseller grid, de-duplicated, in page order."""
    soup = BeautifulSoup(html, "html.parser")
    origin = f"{urlparse(base_url).scheme}://{urlparse(base_url).netloc}"

    seen = set()
    urls = []
    for grid_item in soup.find_all(id="gridItemRoot"):
        for link in grid_item.find_all("a", href=True):
            href = link["href"]
            if "/dp/" in href or "/gp/" in href or "/book/" in href:
                absolute = href if href.startswith("http") else origin + href
                if absolute not in seen:
                    seen.add(absolute)
                    urls.append(absolute)
    return urls


def extract_amazon_listing(html: str, base_url: str, mode: str) -> list[str]:
    """mode='first_item' -> rank-1 product URL only; mode='all_items' -> every
    product URL on the page."""
    urls = extract_amazon_listing_urls(html, base_url)
    if mode == "first_item":
        return urls[:1]
    return urls


def extract_goodreads_listopia(html: str, base_url: str) -> list[dict]:
    """Mirrors extractListopiaLists() from addtext_logic.js."""
    soup = BeautifulSoup(html, "html.parser")
    parsed = urlparse(base_url)
    now = datetime.now(timezone.utc).isoformat()

    seen_urls = set()
    lists = []
    for link in soup.find_all("a", href=True):
        href = link["href"]
        if "/list/show/" not in href:
            continue
        title = link.get_text(strip=True)
        url = f"{parsed.scheme}://{parsed.netloc}{href}"
        if title and url not in seen_urls:
            seen_urls.add(url)
            lists.append({"title": title, "url": url, "date": now})
    return lists
