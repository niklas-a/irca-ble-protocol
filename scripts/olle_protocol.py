"""Compatibility shim.

The protocol implementation now lives in the ``ircable`` package at the repo
root, so the Home Assistant integration and these standalone CLI tools share
one source of truth. The scripts in this directory are run directly rather
than installed, so put the repo root on the path and re-export.
"""
import os
import sys

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "custom_components", "irca_ble"))

from ircable.protocol import *          # noqa: F401,F403
from ircable.protocol import (          # noqa: F401  (names the tools use explicitly)
    Action,
    Alarm,
    CommandStatus,
    Mode,
    Result,
    Status,
    WindowDetection,
)
