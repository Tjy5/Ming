import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ai import factory as ai_factory  # noqa: E402
from fakes import FakeProvider  # noqa: E402

# Tests run against the deterministic test-only provider (AI_PROVIDER=fake).
# The product itself has no bundled provider — playing requires a configured
# AI provider. PYTEST_AI_PROVIDER can still override to a real provider.
ai_factory._PROVIDERS["fake"] = FakeProvider
os.environ["AI_PROVIDER"] = os.getenv("PYTEST_AI_PROVIDER", "fake")
