import os
import sys
from pathlib import Path

os.environ["AI_PROVIDER"] = os.getenv("PYTEST_AI_PROVIDER", "mock")

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
