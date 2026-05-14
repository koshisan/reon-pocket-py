"""reon-pocket-py — BLE control for the Sony Reon Pocket 3.

Public surface::

    from reon import ReonClient, Mode, scan, find_reon, pair, random_token
"""

from .client import ReonClient, ReonError, find_reon, scan
from .pair import pair, random_token
from .protocol import Mode

__version__ = "0.1.0"
__all__ = [
    "ReonClient",
    "ReonError",
    "Mode",
    "scan",
    "find_reon",
    "pair",
    "random_token",
    "__version__",
]
