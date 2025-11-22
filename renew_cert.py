import subprocess
import os
import sys

VERBOSE = "--verbose" in sys.argv
CERT_FLAG = "cert_invalid.flag"

def run_issue_cert():
    cmd = [sys.executable, "issue_cert.py"]
    if VERBOSE:
        cmd.append("--verbose")
    result = subprocess.run(cmd)
    return result.returncode == 0

def run_upload_cert():
    cmd = [sys.executable, "upload_cert.py"]
    if os.path.exists(CERT_FLAG):
        cmd.append("--insecure")
    if VERBOSE:
        cmd.append("--verbose")
    result = subprocess.run(cmd)
    return result.returncode == 0

if __name__ == "__main__":
    if run_issue_cert():
        run_upload_cert()
    try:
        if os.path.exists(CERT_FLAG):
            os.remove(CERT_FLAG)
    except Exception as e:
        print(f"Warning: failed to clean up {CERT_FLAG}: {e}")
