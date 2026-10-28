"""ircable — talk to IRCA / Zoppas BLE heaters and towel rails.

Two layers, deliberately separated:

* :mod:`ircable.protocol` is pure byte manipulation with no I/O and no
  dependencies, so it is fully testable without a Bluetooth radio.
* :mod:`ircable.client` wraps it in a bleak connection.

Protocol documentation: docs/OLLE_BLE_PROTOCOL.md
"""

from .protocol import (  # noqa: F401
    Action,
    Alarm,
    CommandStatus,
    Mode,
    Result,
    Status,
    WindowDetection,
    SERVICE_UUID,
    MS_CELSIUS,
    MS_FAHRENHEIT,
    MS_POWER,
)

__version__ = "0.1.0"

__all__ = [
    "Action", "Alarm", "CommandStatus", "Mode", "Result", "Status",
    "WindowDetection", "SERVICE_UUID", "MS_CELSIUS", "MS_FAHRENHEIT",
    "MS_POWER", "IrcaClient", "IrcaError",
]


def __getattr__(name):
    # Import the client lazily so `import ircable` works without bleak
    # installed - the protocol layer alone has no dependencies.
    if name in ("IrcaClient", "IrcaError"):
        from .client import IrcaClient, IrcaError  # noqa: F401
        return {"IrcaClient": IrcaClient, "IrcaError": IrcaError}[name]
    raise AttributeError(name)
