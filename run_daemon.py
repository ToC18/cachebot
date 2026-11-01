import os
import sys
import subprocess
import time

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
os.chdir(PROJECT_DIR)

# Redirect output to daemon.log
log_path = os.path.join(PROJECT_DIR, "daemon.log")
log_f = open(log_path, "a", encoding="utf-8", buffering=1)
sys.stdout = log_f
sys.stderr = log_f

print(f"\n--- Starting CacheBot daemon at {time.ctime()} ---", flush=True)

# Run start_all.py in-process
import start_all
start_all.main()
