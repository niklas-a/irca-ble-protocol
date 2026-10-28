"""Operational constants shared by the client and the HA integration."""

# The device advertises only a local name, never its service UUID, so this is
# the discovery handle. Sibling IRCA products (Deltacalor, StoneBLE) run the
# same stack but have not been confirmed - do not add names on speculation.
KNOWN_LOCAL_NAMES = ("olle",)

# Transient-connection model: connect, do the work, disconnect. See
# docs/BUILDING_AN_INTEGRATION.md §4 for why this beats a persistent link.
DEFAULT_POLL_INTERVAL = 90.0        # seconds between status polls
CONNECT_TIMEOUT = 20.0              # seconds to establish a connection
COMMAND_TIMEOUT = 6.0               # seconds to wait for a RESULT notification

# The firmware clamps anyway, but matching the vendor app's own limits keeps
# the UI honest. From res/values/dimens.xml.
CELSIUS_MIN, CELSIUS_MAX, CELSIUS_STEP = 15.0, 30.0, 0.5
FAHRENHEIT_MIN, FAHRENHEIT_MAX, FAHRENHEIT_STEP = 45.0, 90.0, 1.0
POWER_MIN, POWER_MAX, POWER_STEP = 1.0, 10.0, 1.0

BOOST_MIN_HOURS, BOOST_MAX_HOURS = 2, 10
