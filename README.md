# HP OfficeJet Pro 91xx Certificate Automator

A Python/Playwright automation suite to handle SSL certificate renewal for HP OfficeJet Pro 9100/9700 series printers (and others using the modern HP Web EWS with OAuth).

## The Problem
Modern HP Pro printers require certificates to be generated via a specific CSR workflow initiated by the printer. They also protect the EWS with a complex OAuth 2.0 Authorization Code flow, making standard `curl` or `requests` scripts difficult to maintain.

## The Solution
This service uses **Playwright** to act as a headless user agent, navigating the printer's UI to:
1.  Authenticate via the printer's OAuth handshake.
2.  Request a new Certificate Signing Request (CSR).
3.  Sign the CSR using **Certbot** (via Cloudflare DNS challenge).
4.  Upload the signed certificate back to the printer.

It includes **Self-Healing Logic**: If the printer currently has an invalid/expired/self-signed certificate, the script detects the SSL error, automatically switches to insecure mode, and proceeds with the fix.

## Prerequisites
* **Hardware:** HP OfficeJet Pro 9120e, 9125e, 9730e, or similar.
* **OS:** Linux (Raspberry Pi OS / Ubuntu / Debian).
* **DNS:** A domain managed by Cloudflare (required for the DNS-01 challenge used in this script).

## Installation

1.  **Clone the repository:**
    ```bash
    git clone https://github.com/chriv/ojp91xx-cert-renew.git
    cd ojp91xx-cert-renew
    ```

2.  **Create Configuration:**
    Copy the sample config and fill in your details.
    ```bash
    cp config.env.sample config.env
    nano config.env
    ```
    * `PRINTER_HOSTNAME`: The printer's hostname (e.g., `hpi1234567`).
    * `PRINTER_DOMAIN_NAME`: The domain name that you control for Cloudflare (e.g., `example.com`)
    * `PRINTER_PIN`: The admin PIN found on the printer sticker (or set manually).
    * `CERTBOT_EMAIL`: Email for Let's Encrypt notifications.
    * `RENEWAL_THRESHOLD_DAYS`: The number of days (or less) that should be left until certificate expiration before issuing a new certificate (`30` is normal)

3.  **Create Cloudflare Credentials:**
    Create a file named `cloudflare.ini` in the project directory.
    You will need to have an API Token with Zone Edit permissions for your domain.
    ```ini
    dns_cloudflare_api_token = YOUR_CLOUDFLARE_API_TOKEN
    ```

4.  **Run the Installer:**
    ```bash
    chmod +x setup.sh
    sudo ./setup.sh
    ```
    The installer will:
    * Set up a Python Virtual Environment (`.venv`) in `/opt/`.
    * Install Playwright and the Chromium browser binary.
    * Install Systemd units (`ojp91xx-cert-renew.service` and `.timer`).

## Usage

The service installs a Systemd timer that runs daily (`02:00` local time).

**Manual Run:**
```bash
sudo systemctl start ojp91xx-cert-renew.service
```

**View Logs:**
```bash
journalctl -u ojp91xx-cert-renew.service -f
```

## Directory Structure
* `/opt/ojp91xx-cert-renew/`: Application code and virtual environment.
* `/etc/ojp91xx-cert-renew/`: Configuration files (`config.env`, `cloudflare.ini`).
