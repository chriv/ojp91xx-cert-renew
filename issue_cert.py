from playwright.sync_api import sync_playwright
import time
import logging
import sys
import subprocess
import os
import re
from urllib.parse import urlparse
from datetime import datetime, timedelta
from cryptography import x509
from cryptography.hazmat.backends import default_backend
import ssl
import socket

# --- Configuration ---
PRINTER_URL = os.environ.get("PRINTER_URL")
PIN = os.environ.get("PRINTER_PIN")
EMAIL = os.environ.get("CERTBOT_EMAIL")
# We hardcode the path to the config dir we will create in setup.sh
CLOUDFLARE_INI_PATH = "/etc/ojp91xx-cert-renew/cloudflare.ini"
RENEWAL_THRESHOLD_DAYS = int(os.environ.get("RENEWAL_THRESHOLD_DAYS", 30))
DOWNLOAD_TIMEOUT = 30
CERT_INVALID_MARKER = "cert_invalid.flag"

if not all([PRINTER_URL, PIN, EMAIL]):
    print("CRITICAL: Missing required env vars (PRINTER_URL, PRINTER_PIN, CERTBOT_EMAIL)")
    sys.exit(1)

# --- Setup Logger ---
logger = logging.getLogger("hp_certbot")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# --- Certificate Expiration Check on Printer ---
def get_printer_cert_expiration(domain):
    try:
        context = ssl.create_default_context()
        with context.wrap_socket(socket.socket(), server_hostname=domain) as conn:
            conn.settimeout(5)
            conn.connect((domain, 443))
            der_cert = conn.getpeercert(binary_form=True)
            cert = x509.load_der_x509_certificate(der_cert, backend=default_backend())
            return cert.not_valid_after
    except Exception as e:
        logger.warning(f"Failed to retrieve printer certificate: {e}")
        try:
            with open(CERT_INVALID_MARKER, "w") as f:
                f.write("cert invalid\n")
        except Exception as write_err:
            logger.warning(f"Failed to write marker file: {write_err}")
        return None

# --- Main Script ---
def generate_csr(verbose=False, staging=False, allow_invalid_cert=False, force_new=False):
    if verbose:
        logger.setLevel(logging.DEBUG)

    parsed_url = urlparse(PRINTER_URL)
    printer_domain = parsed_url.hostname
    if not printer_domain:
        logger.error("Could not extract domain from PRINTER_URL.")
        sys.exit(1)

    if not force_new:
        expiration = get_printer_cert_expiration(printer_domain)
        if expiration:
            days_left = (expiration - datetime.utcnow()).days
            logger.info(f"Current printer certificate expires in {days_left} day(s).")
            if days_left >= RENEWAL_THRESHOLD_DAYS:
                logger.info("Certificate is still valid. No renewal needed.")
                try:
                    if os.path.exists(CERT_INVALID_MARKER):
                        os.remove(CERT_INVALID_MARKER)
                except Exception as e:
                    logger.warning(f"Failed to clean up marker file: {e}")
                return
        else:
            logger.warning("Certificate check failed (likely invalid/self-signed). Forcing insecure mode for Playwright.")
            allow_invalid_cert = True  # <--- Force Playwright to ignore errors
            days_left = 0

    with sync_playwright() as p:
        logger.debug("Launching browser in headless mode...")
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(accept_downloads=True, ignore_https_errors=allow_invalid_cert)
        page = context.new_page()

        logger.info("Navigating to printer login page...")
        page.goto(PRINTER_URL)

        logger.info("Logging in...")
        page.get_by_role("menuitem", name="Security").click()
        page.locator("#menu-security-certificateManagement").get_by_role("navigation", name="Certificate Management").click()
        page.get_by_role("textbox", name="Enter PIN").fill(PIN)
        page.get_by_role("button", name="Sign In").click()

        logger.info("Navigating to CSR creation...")
        page.get_by_text("OU=", exact=False).first.click()
        #page.get_by_text(f"CN={printer_domain}", exact=True).click()
        page.get_by_text(re.compile(r"CN=.*")).first.click()
        page.get_by_text("Create").click()
        page.locator("#mat-select-value-5").click()
        page.get_by_text("Create Certificate Signing").click()
        page.get_by_role("button", name="Next").click()
        page.get_by_role("button", name="Create").click()

        logger.info("Waiting for CSR download...")
        with page.expect_download(timeout=DOWNLOAD_TIMEOUT * 1000) as download_info:
            page.get_by_role("button", name="Save").click()
        download = download_info.value
        csr_path = download.path()

        timestamp = int(time.time())
        final_csr_path = f"csr_{timestamp}.pem"
        download.save_as(final_csr_path)
        logger.info(f"CSR saved to: {final_csr_path}")

        page.get_by_role("button", name="OK").click()
        browser.close()
        logger.debug("Browser closed.")

    logger.info("Requesting certificate via certbot...")

    certbot_cmd = [
        "/usr/bin/certbot", "certonly",
        "--csr", final_csr_path,
        "--dns-cloudflare",
        "--dns-cloudflare-credentials", CLOUDFLARE_INI_PATH,
        "--email", EMAIL,
        "--agree-tos",
        "--non-interactive",
        "-d", printer_domain
    ]

    if staging:
        certbot_cmd.append("--test-cert")

    logger.debug("Running certbot command:")
    logger.debug(" ".join(certbot_cmd))

    result = subprocess.run(" ".join(certbot_cmd), shell=True, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("Certbot failed:")
        logger.error(result.stdout.strip())
        logger.error(result.stderr.strip())
        return

    logger.info("Certificate issued successfully.")

    cwd = os.getcwd()
    for fname in os.listdir(cwd):
        if fname.startswith("000") and fname.endswith(".pem"):
            src_path = os.path.join(cwd, fname)
            dst_path = os.path.join(cwd, f"issued_{fname}")
            try:
                os.rename(src_path, dst_path)
                logger.info(f"Moved {fname} to {dst_path}")
            except Exception as e:
                logger.warning(f"Failed to move {fname}: {e}")

if __name__ == "__main__":
    verbose_flag = "--verbose" in sys.argv or "--debug" in sys.argv
    staging_flag = "--staging" in sys.argv
    allow_invalid_cert_flag = "--insecure" in sys.argv or "--ignore-https-errors" in sys.argv
    force_flag = "--force-new" in sys.argv
    generate_csr(verbose=verbose_flag, staging=staging_flag, allow_invalid_cert=allow_invalid_cert_flag, force_new=force_flag)
