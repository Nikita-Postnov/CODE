"""Run NPCore clipboard regression cases in isolated Qt subprocesses.

An offscreen clipboard platform can deadlock a process; each test has its
own timeout so CI identifies the exact scenario rather than hanging forever.
"""
import re
import subprocess
import sys
from pathlib import Path

path = Path(__file__).with_name("test_np_screenshot_npcore_storage.py")
source = path.read_text(encoding="utf-8")
names = re.findall(r"^    def (test_[A-Za-z0-9_]+)\(", source, re.M)
failed = []
for name in names:
    print("RUN", name, flush=True)
    try:
        result = subprocess.run(
            [sys.executable, str(path), "ScreenshotNPCoreUploadTests." + name],
            capture_output=True, text=True, timeout=18, check=False)
    except subprocess.TimeoutExpired:
        print("TIMEOUT", name, flush=True)
        failed.append(name)
        continue
    if result.returncode:
        print("FAIL", name, result.stdout, result.stderr, flush=True)
        failed.append(name)
    else:
        print("PASS", name, flush=True)
print("SUMMARY", len(names) - len(failed), "/", len(names), flush=True)
if failed:
    print("FAILED", ", ".join(failed), flush=True)
    raise SystemExit(1)
