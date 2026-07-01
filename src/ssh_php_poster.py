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

import json
import logging
import os
import uuid
from datetime import date

import paramiko

logger = logging.getLogger(__name__)


def _row_dict_for_product(product: dict) -> dict:
    today = date.today()
    return {
        "book_title": product["title"],
        "book_name": product["title"],
        "cover_image": product["cover"],
        "book_cover_src": product["cover"],
        "book_url": f"https://www.amazon.com/dp/{product['asin']}?ref=joelbooks",
        "author_name": product["author"],
        "author_name_2": product["author"],
        "book_price": product["price"],
        "book_price_2": product["price"],
        "book_description": product["content"],
        "asin": product["asin"],
        "date_added": f"{today.month}/{today.day}/{today.year}",
    }


class SSHPoster:
    def __init__(self, host: str, port: int, username: str, remote_script: str, remote_tmp_dir: str):
        self.host = host
        self.port = port
        self.username = username
        self.remote_script = remote_script
        self.remote_tmp_dir = remote_tmp_dir
        self.client = None
        self.sftp = None

    def __enter__(self):
        key_path = os.environ["AGENTX_SSH_KEY_PATH"]
        pkey = paramiko.Ed25519Key.from_private_key_file(key_path)
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.client.connect(self.host, port=self.port, username=self.username, pkey=pkey, timeout=20)
        self.sftp = self.client.open_sftp()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.sftp:
            self.sftp.close()
        if self.client:
            self.client.close()

    def post_product(self, product: dict) -> None:
        payload = _row_dict_for_product(product)
        remote_path = f"{self.remote_tmp_dir}/payload_{uuid.uuid4().hex}.json"
        with self.sftp.open(remote_path, "w") as f:
            f.write(json.dumps(payload))
        try:
            command = f"php {self.remote_script} {remote_path}"
            _stdin, stdout, stderr = self.client.exec_command(command, timeout=30)
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
                self.sftp.remove(remote_path)
            except IOError:
                pass
