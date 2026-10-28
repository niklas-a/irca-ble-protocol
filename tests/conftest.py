"""Make the bundled ``ircable`` library importable from the test suite.

The library lives inside the integration directory because HACS only installs
``custom_components/<domain>/``. Adding that directory to the path lets tests
``from ircable import protocol`` exactly as the integration does.
"""
import os
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INTEGRATION = os.path.join(REPO_ROOT, "custom_components", "irca_ble")

for path in (INTEGRATION, REPO_ROOT):
    if path not in sys.path:
        sys.path.insert(0, path)
