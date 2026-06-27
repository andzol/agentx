"""Entrypoint. Loads every task YAML (local tasks/ dir or a GCS bucket, see
config.py), runs each one in isolation, and exits nonzero if any task
failed so Cloud Run / Cloud Scheduler surface the failure."""

import argparse
import logging
import sys
from datetime import date

import config
import php_poster
import sheets_writer
from scrape_listing import extract_amazon_listing, extract_goodreads_listopia, fetch_html
from scrape_product import ProductScraper

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("runner")


def _best_seller_row(product: dict) -> list:
    today = date.today()
    date_str = f"{today.month}/{today.day}/{today.year}"
    return [
        product["title"],
        product["author"],
        f"{product['url']}?ref=joelbooks",
        product["cover"],
        product["cover"],
        product["author"],
        product["year"],
        product["year"],
        date_str,
    ]


def run_amazon_listing_task(task: dict, product_scraper: ProductScraper, dry_run: bool) -> dict:
    html = fetch_html(task["url"])
    product_urls = extract_amazon_listing(html, task["url"], task.get("mode", "all_items"))
    logger.info("[%s] found %d product URL(s)", task["name"], len(product_urls))

    products = [product_scraper.scrape(url) for url in product_urls]

    if dry_run:
        for p in products:
            logger.info("[%s] DRY RUN extracted: %s", task["name"], p)
        return {"name": task["name"], "ok": True, "count": len(products)}

    if task["output"] == "sheets":
        rows_with_keys = [
            (f"{p['url']}?ref=joelbooks", _best_seller_row(p)) for p in products
        ]
        written = sheets_writer.append_rows_deduped(
            task["sheet_id"], task["tab"], task["dedup_column"], rows_with_keys
        )
        return {"name": task["name"], "ok": True, "count": written}

    if task["output"] == "php":
        for p in products:
            php_poster.post_product(task["endpoint"], p)
        return {"name": task["name"], "ok": True, "count": len(products)}

    raise ValueError(f"Unknown output type: {task['output']}")


def run_goodreads_listopia_task(task: dict, dry_run: bool) -> dict:
    html = fetch_html(task["url"])
    lists = extract_goodreads_listopia(html, task["url"])
    logger.info("[%s] found %d list(s)", task["name"], len(lists))

    if dry_run:
        for entry in lists:
            logger.info("[%s] DRY RUN extracted: %s", task["name"], entry)
        return {"name": task["name"], "ok": True, "count": len(lists)}

    rows_with_keys = [(entry["url"], [entry["title"], entry["url"], entry["date"]]) for entry in lists]
    written = sheets_writer.append_rows_deduped(
        task["sheet_id"], task["tab"], task["dedup_column"], rows_with_keys
    )
    return {"name": task["name"], "ok": True, "count": written}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Extract data but skip Sheets/PHP writes")
    args = parser.parse_args()

    tasks = list(config.load_tasks())
    if not tasks:
        logger.error("No tasks found")
        sys.exit(1)

    results = []
    with ProductScraper() as product_scraper:
        for task in tasks:
            name = task.get("name", task.get("_source", "unknown"))
            try:
                if task["type"] == "amazon_listing":
                    result = run_amazon_listing_task(task, product_scraper, args.dry_run)
                elif task["type"] == "goodreads_listopia":
                    result = run_goodreads_listopia_task(task, args.dry_run)
                else:
                    raise ValueError(f"Unknown task type: {task['type']}")
                results.append(result)
                logger.info("[%s] OK - %d item(s)", name, result["count"])
            except Exception:
                logger.exception("[%s] FAILED", name)
                results.append({"name": name, "ok": False, "count": 0})

    failures = [r for r in results if not r["ok"]]
    logger.info("Summary: %d/%d tasks succeeded", len(results) - len(failures), len(results))
    if failures:
        logger.error("Failed tasks: %s", [r["name"] for r in failures])
        sys.exit(1)


if __name__ == "__main__":
    main()
