import os
import sys

# Add root directory to sys.path
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(CURRENT_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# Mark as serverless environment
os.environ["VERCEL"] = "1"
os.environ["USE_WEBHOOK"] = "1"

from main import app

# Vercel entrypoint
