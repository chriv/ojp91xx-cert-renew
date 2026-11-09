import subprocess
import os
import sys

VERBOSE = "--verbose" in sys.argv
CERT_FLAG = "cert_invalid.flag"

# Exit codes from issue_cert.py
EXIT_NO_RENEWAL = 0
EXIT_ISSUED = 10

def run_issue_cert():
    cmd = [sys.executable, "issue_cert.py"]
    if VERBOSE:
        cmd.append("--verbose")
    result = subprocess.run(cmd)
    return result.returncode

def run_upload_cert():
    cmd = [sys.executable, "upload_cert.py"]
    if os.path.exists(CERT_FLAG):
        cmd.append("--insecure")
    if VERBOSE:
        cmd.append("--verbose")
    result = subprocess.run(cmd)
    return result.returncode == 0

def cleanup_flag():
    try:
        if os.path.exists(CERT_FLAG):
            os.remove(CERT_FLAG)
    except Exception as e:
        print(f"Warning: failed to clean up {CERT_FLAG}: {e}")

if __name__ == "__main__":
    issue_rc = run_issue_cert()

    if issue_rc == EXIT_NO_RENEWAL:
        cleanup_flag()
        sys.exit(0)

    if issue_rc != EXIT_ISSUED:
        print(f"ERROR: issue_cert.py failed (exit code {issue_rc}); certificate not renewed.")
        cleanup_flag()
        sys.exit(1)

    uploaded = run_upload_cert()
    cleanup_flag()
    if not uploaded:
        print("ERROR: upload_cert.py failed; new certificate was issued but NOT installed on the printer.")
        sys.exit(1)
