"""Scrapes Amazon product detail pages (/dp/ASIN). Confirmed via live testing
that these pages return Amazon's CAPTCHA wall to a plain `requests` fetch, so
a real (headless) browser session is required here — unlike the listing
pages handled in scrape_listing.py."""

import logging
import re
import time

from playwright.sync_api import sync_playwright

from config import USER_AGENT, PRODUCT_PAGE_DELAY_SECONDS

logger = logging.getLogger(__name__)

ASIN_RE = re.compile(r"/dp/(\w{10})|/gp/product/(\w{10})")
YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")


def _title_case_if_all_caps(text: str) -> str:
    if text and text == text.upper():
        return " ".join(w.capitalize() for w in text.lower().split())
    return text


class ProductScraper:
    """Reuses one browser + context across every product page in a run,
    with a short delay between visits to keep the bot footprint small."""

    def __enter__(self):
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=True)
        self._context = self._browser.new_context(user_agent=USER_AGENT)
        self._first_visit = True
        return self

    def __exit__(self, exc_type, exc, tb):
        self._context.close()
        self._browser.close()
        self._playwright.stop()

    def scrape(self, url: str) -> dict:
        if not self._first_visit:
            time.sleep(PRODUCT_PAGE_DELAY_SECONDS)
        self._first_visit = False

        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            return self._extract(page, url)
        finally:
            page.close()

    @staticmethod
    def _extract(page, url: str) -> dict:
        def text_or_na(selector: str) -> str:
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else "N/A"

        raw_title = text_or_na("#productTitle")
        title = re.split(r"(\(.*\)|:)", raw_title)[0].strip()
        title = _title_case_if_all_caps(title)

        series = "N/A"
        series_el = page.query_selector("#seriesBulletWidget_feature_div")
        if series_el:
            series_match = re.search(r"Book (\d+) of \d+: (.*)", series_el.inner_text().strip())
            if series_match:
                series = f"{series_match.group(2)} Book {series_match.group(1)}"

        author_el = page.query_selector(".author a")
        author = author_el.inner_text().strip() if author_el else "N/A"

        year = ProductScraper._publication_year(page)

        asin_match = ASIN_RE.search(url)
        asin = next((g for g in (asin_match.groups() if asin_match else []) if g), "N/A")

        cover_el = page.query_selector("#landingImage")
        cover = cover_el.get_attribute("src") if cover_el else "N/A"

        content = text_or_na('[data-feature-name="bookDescription"]')
        if content == "N/A":
            content = text_or_na("#drengr_DesktopTabbedDescriptionOverviewContent_feature_div")
        if content == "N/A":
            content = text_or_na("#drengr_desktopTabbedDescriptionOverviewContent_feature_div")
        content = ProductScraper._filter_description(content)

        price = ProductScraper._price(page)
        reviews = ProductScraper._review_count(page)

        return {
            "title": title,
            "series": series,
            "author": author,
            "year": year,
            "asin": asin,
            "keywords": "",
            "cover": cover,
            "content": content,
            "price": price,
            "reviews": reviews,
            "url": url,
        }

    @staticmethod
    def _publication_year(page) -> str:
        el = page.query_selector("#rpi-attribute-book_details-publication_date")
        if el:
            span = el.query_selector(".rpi-attribute-value span")
            if span and YEAR_RE.search(span.inner_text().strip()):
                return span.inner_text().strip().split(" ")[-1]

        for bold in page.query_selector_all("li span.a-text-bold"):
            if "Publication date" in bold.text_content():
                sibling = bold.evaluate_handle("el => el.nextElementSibling")
                sibling_el = sibling.as_element()
                if sibling_el:
                    text = sibling_el.text_content().strip()
                    if YEAR_RE.search(text):
                        return text.split(" ")[-1]
        return "N/A"

    @staticmethod
    def _price(page) -> float | None:
        container = page.query_selector("#mediamatrix_feature_div")
        if not container:
            return None
        selected = container.query_selector("span.a-button-selected")
        if not selected:
            return None
        price_el = selected.query_selector("span.a-size-base.a-color-price.ebook-price-value")
        if not price_el:
            return None
        try:
            return float(price_el.inner_text().strip().lstrip("$"))
        except ValueError:
            return None

    @staticmethod
    def _review_count(page):
        el = page.query_selector("#acrCustomerReviewText.a-size-base")
        if not el:
            return None
        match = re.search(r"\d+", el.text_content())
        return int(match.group()) if match else None

    @staticmethod
    def _filter_description(text: str) -> str:
        if text == "N/A":
            return text
        text = re.sub(r"\s*Read more\s*$", "", text)
        text = re.sub(r"Join.*today.*!\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r".*Add to Cart.*\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"[\r\n]+", " ", text)
        text = text.replace("★★★★★", "")
        text = re.sub(r"★\s*★\s*★\s*★\s*★", "", text)
        return text
