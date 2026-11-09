from playwright.sync_api import sync_playwright
import time
import logging
import sys
import subprocess
import os
import re
from urllib.parse import urlparse
from datetime import datetime, timedelta, timezone
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
# Renew when this fraction of the certificate's lifetime (or less) remains.
# Let's Encrypt recommends renewing with about 1/3 of the lifetime remaining;
# this adapts automatically as lifetimes shrink (90 -> 64 -> 45 days).
RENEWAL_FRACTION = float(os.environ.get("RENEWAL_FRACTION", 1 / 3))
# Never wait until fewer than this many days remain, however short the lifetime.
RENEWAL_MIN_DAYS = int(os.environ.get("RENEWAL_MIN_DAYS", 7))
# Legacy fixed threshold. Only used if set and RENEWAL_FRACTION is not.
LEGACY_THRESHOLD_DAYS = os.environ.get("RENEWAL_THRESHOLD_DAYS")
DOWNLOAD_TIMEOUT = 30
CERT_INVALID_MARKER = "cert_invalid.flag"

# Exit codes (read by renew_cert.py)
EXIT_NO_RENEWAL = 0   # Certificate still valid; nothing to do
EXIT_FAILURE = 1      # Something went wrong; systemd marks the unit failed
EXIT_ISSUED = 10      # New certificate issued; upload required

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
class PrinterUnreachable(Exception):
    pass

def get_printer_cert_validity(domain):
    """Return (not_before, not_after) of the printer's certificate as aware UTC datetimes.

    Returns None if the certificate fails verification (expired, self-signed, wrong name),
    which triggers renewal in insecure mode. Raises PrinterUnreachable on network errors,
    which must NOT trigger renewal.
    """
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, 443), timeout=10) as raw:
            with context.wrap_socket(raw, server_hostname=domain) as conn:
                der_cert = conn.getpeercert(binary_form=True)
    except ssl.SSLCertVerificationError as e:
        logger.warning(f"Printer certificate failed verification: {e}")
        try:
            with open(CERT_INVALID_MARKER, "w") as f:
                f.write("cert invalid\n")
        except Exception as write_err:
            logger.warning(f"Failed to write marker file: {write_err}")
        return None
    except (OSError, ssl.SSLError) as e:
        raise PrinterUnreachable(f"Could not connect to {domain}:443: {e}") from e

    cert = x509.load_der_x509_certificate(der_cert, backend=default_backend())
    return cert.not_valid_before_utc, cert.not_valid_after_utc

def renewal_threshold(not_before, not_after):
    """Days remaining at (or below) which the certificate should be renewed."""
    if LEGACY_THRESHOLD_DAYS and "RENEWAL_FRACTION" not in os.environ:
        logger.warning("RENEWAL_THRESHOLD_DAYS is deprecated; use RENEWAL_FRACTION instead.")
        return float(LEGACY_THRESHOLD_DAYS)
    lifetime_days = (not_after - not_before).total_seconds() / 86400
    return max(lifetime_days * RENEWAL_FRACTION, RENEWAL_MIN_DAYS)

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
        try:
            validity = get_printer_cert_validity(printer_domain)
        except PrinterUnreachable as e:
            logger.error(str(e))
            logger.error("Printer unreachable; not attempting renewal. Will retry on next run.")
            sys.exit(EXIT_FAILURE)
        if validity:
            not_before, not_after = validity
            days_left = (not_after - datetime.now(timezone.utc)).total_seconds() / 86400
            threshold = renewal_threshold(not_before, not_after)
            logger.info(f"Current printer certificate expires {not_after:%Y-%m-%d %H:%M} UTC "
                        f"({days_left:.1f} days left; renewal threshold {threshold:.1f} days).")
            if days_left > threshold:
                logger.info("Certificate is still valid. No renewal needed.")
                try:
                    if os.path.exists(CERT_INVALID_MARKER):
                        os.remove(CERT_INVALID_MARKER)
                except Exception as e:
                    logger.warning(f"Failed to clean up marker file: {e}")
                sys.exit(EXIT_NO_RENEWAL)
        else:
            logger.warning("Certificate is invalid/expired/self-signed. Forcing insecure mode for Playwright.")
            allow_invalid_cert = True  # <--- Force Playwright to ignore errors

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

    result = subprocess.run(certbot_cmd, capture_output=True, text=True)

    if result.returncode != 0:
        logger.error("Certbot failed:")
        logger.error(result.stdout.strip())
        logger.error(result.stderr.strip())
        sys.exit(EXIT_FAILURE)

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

    sys.exit(EXIT_ISSUED)

if __name__ == "__main__":
    verbose_flag = "--verbose" in sys.argv or "--debug" in sys.argv
    staging_flag = "--staging" in sys.argv
    allow_invalid_cert_flag = "--insecure" in sys.argv or "--ignore-https-errors" in sys.argv
    force_flag = "--force-new" in sys.argv
    generate_csr(verbose=verbose_flag, staging=staging_flag, allow_invalid_cert=allow_invalid_cert_flag, force_new=force_flag)
