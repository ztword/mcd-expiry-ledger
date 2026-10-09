"""麦麦到期清单 · mcd-expiry-ledger.

Every coupon, point balance, lottery draw and unclaimed prize in your
McDonald's China account is quietly counting down.  This package puts all of
those clocks on one page, ranks them by *what you lose if you wait*, and hands
back an executable liquidation plan — all built on the official McDonald's
China MCP server.

Zero dependencies beyond the Python standard library.
"""

__version__ = "1.0.0"
__author__ = "ztword"
__license__ = "MIT"

from .client import McpClient, McpError
from .ledger import Asset, LedgerEngine, ScanResult
from .demo import DemoClient
from .report import render_html

__all__ = [
    "McpClient", "McpError", "Asset", "LedgerEngine", "ScanResult",
    "DemoClient", "render_html", "__version__",
]
