"""Posts scraped product data to a legacy site by SSHing into its host and
running a private PHP CLI script that inserts directly into MySQL.

This exists because the site's hosting (SiteGround) runs an automatic
network-level anti-bot/WAF layer that silently challenges plain HTTP POSTs
from Cloud Run's IP range before they ever reach PHP - no amount of
request-header tuning fixes it. SSH command execution is a different
protocol the WAF never touches, so we upload a payload over SFTP and run a
CLI script that does the same INSERT the old HTTP endpoint did (see
cli_insert_free_books.php, deployed once to a private, non-web-accessible
directory on the server - never reachable by URL, so it can't be scanned or
quarantined as a suspicious web-facing script either)."""

import io
import json
import logging
import os
import time
import uuid
from datetime import date

import paramiko

logger = logging.getLogger(__name__)

CONNECT_DELAY_SECONDS = 2


def _row_dict_for_product(product: dict) -> dict:
    today = date.today()

    def _s(value) -> str:
        # free_books columns are all NOT NULL; a scraper miss (Python None,
        # e.g. price/reviews selectors not matching) must never become a
        # JSON null, or mysqli throws an uncaught NOT NULL exception on
        # insert (PHP 8.1+ default), which surfaces as a bare exit=255 with
        # no output at all - very hard to diagnose from the Python side.
        return "N/A" if value is None else str(value)

    return {
        "book_title": _s(product["title"]),
        "book_name": _s(product["title"]),
        "cover_image": _s(product["cover"]),
        "book_cover_src": _s(product["cover"]),
        "book_url": f"https://www.amazon.com/dp/{product['asin']}?ref=joelbooks",
        "author_name": _s(product["author"]),
        "author_name_2": _s(product["author"]),
        "book_price": _s(product["price"]),
        "book_price_2": _s(product["price"]),
        "book_description": _s(product["content"]),
        "asin": product["asin"],
        "date_added": f"{today.month}/{today.day}/{today.year}",
    }


class SSHPoster:
    """Opens a fresh SSH connection per product rather than reusing one
    connection for many exec calls, since paramiko's channel handling over a
    long-lived connection got unreliable across ~30 sequential exec calls."""

    def __init__(self, host: str, port: int, username: str, remote_script: str, remote_tmp_dir: str):
        self.host = host
        self.port = port
        self.username = username
        self.remote_script = remote_script
        self.remote_tmp_dir = remote_tmp_dir
        self.pkey = None

    def __enter__(self):
        # Read from an env var (Secret Manager mounted as env var) rather than
        # a file mount - Cloud Run's secret-volume FUSE mount has been
        # observed to raise a transient "Input/output error" on first read.
        key_content = os.environ["AGENTX_SSH_KEY_CONTENT"]
        self.pkey = paramiko.Ed25519Key.from_private_key(io.StringIO(key_content))
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass

    def post_product(self, product: dict) -> None:
        time.sleep(CONNECT_DELAY_SECONDS)
        payload = _row_dict_for_product(product)
        remote_path = f"{self.remote_tmp_dir}/payload_{uuid.uuid4().hex}.json"

        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(self.host, port=self.port, username=self.username, pkey=self.pkey, timeout=20)
        try:
            sftp = client.open_sftp()
            try:
                with sftp.open(remote_path, "w") as f:
                    f.write(json.dumps(payload))

                command = f"php {self.remote_script} {remote_path}"
                _stdin, stdout, stderr = client.exec_command(command, timeout=30)
                exit_status = stdout.channel.recv_exit_status()
                out = stdout.read().decode().strip()
                err = stderr.read().decode().strip()
                if exit_status != 0 or "OK" not in out:
                    raise RuntimeError(
                        f"CLI insert failed for {product.get('asin')}: exit={exit_status} stdout={out} stderr={err}"
                    )
                logger.info("Inserted %s via SSH+PHP-CLI on %s", product.get("asin"), self.host)
            finally:
                try:
                    sftp.remove(remote_path)
                except IOError:
                    pass
                sftp.close()
        finally:
            client.close()
