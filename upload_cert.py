from playwright.sync_api import sync_playwright
import logging
import sys
import os
import glob

# --- Configuration ---
PRINTER_URL = os.environ.get("PRINTER_URL")
PIN = os.environ.get("PRINTER_PIN")
CERT_PATH = "issued_0000_cert.pem"
CHAIN_PATH = "issued_0001_chain.pem"

# --- Setup Logger ---
logger = logging.getLogger("upload_cert")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler(sys.stdout)
formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
handler.setFormatter(formatter)
logger.addHandler(handler)

# --- Main Function ---
def upload_certificate(allow_invalid_cert=False):
    if not os.path.exists(CERT_PATH) or not os.path.exists(CHAIN_PATH):
        logger.error("Certificate or chain file is missing.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=allow_invalid_cert)
        page = context.new_page()

        logger.info("Navigating to printer login page...")
        page.goto(PRINTER_URL)

        logger.info("Logging in...")
        page.get_by_role("menuitem", name="Security").click()
        page.locator("#menu-security-certificateManagement").get_by_role("navigation", name="Certificate Management").click()
        page.get_by_role("textbox", name="Enter PIN").fill(PIN)
        page.get_by_role("button", name="Sign In").click()

        logger.info("Navigating to certificate installation...")
        page.get_by_text("Create").click()
        page.get_by_text("Create New Self-Signed").click()  # Placeholder interaction to trigger menu
        page.get_by_text("Install Identity Certificate").click()
        page.get_by_role("button", name="Next").click()

        logger.info("Uploading certificate...")
        upload_button = page.locator("input[type='file']").first
        # upload_button.set_input_files(CERT_PATH)
        # logger.info("First file uploaded.")

        logger.info("Uploading chain...")
        upload_button.set_input_files(CHAIN_PATH)
        logger.info("Second file uploaded.")

        logger.info("Submitting installation...")
        page.get_by_role("button", name="Install").click()
        page.get_by_role("button", name="OK").click()

        logger.info("Certificate installation complete. Deleting all .pem files...")
        browser.close()

    for pem_file in glob.glob("*.pem"):
        try:
            os.remove(pem_file)
            logger.info(f"Deleted {pem_file}")
        except Exception as e:
            logger.warning(f"Failed to delete {pem_file}: {e}")

if __name__ == "__main__":
    allow_invalid = "--insecure" in sys.argv or "--ignore-https-errors" in sys.argv
    upload_certificate(allow_invalid_cert=allow_invalid)
