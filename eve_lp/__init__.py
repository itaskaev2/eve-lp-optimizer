"""EVE Online Loyalty Point (LP) -> ISK optimizer.

A read-only tool that uses CCP's public ESI API (loyalty store offers) together
with Jita market prices (Fuzzwork aggregates) to rank LP store offers by ISK
profit per Loyalty Point. It does not touch the game client in any way.
"""

__version__ = "1.0.0"
