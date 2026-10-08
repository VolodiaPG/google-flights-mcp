"""MCP server exposing cheapest_flights.find_cheapest as a tool (stdio transport)."""

import argparse
import asyncio
from typing import Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from cheapest_flights import _date, _iata, _nights, find_cheapest

mcp = MCPServer("cheapest-flights")


@mcp.tool()
async def search_cheapest_flights(
    origin: str,
    destination: str,
    start: str,
    end: str,
    nights: str | None = None,
    top: int = 10,
    max_stops: int | None = None,
    max_price: int | None = None,
    seat: Literal["economy", "premium-economy", "business", "first"] = "economy",
    adults: int = 1,
    currency: str = "EUR",
) -> dict:
    """Find the cheapest Google Flights itineraries between two airports within a date window.

    Searches every day from `start` to `end` (YYYY-MM-DD, inclusive, not in the past). One-way by
    default. Set `nights` ("7" or "5-9") for round trips: each departure date is paired with each stay
    length and the return must be on or before `end`. Round-trip `price` is the round-trip total, but
    `legs`/times describe only the outbound flight. One request is made per date (max 200), so keep
    windows narrow. Results are sorted cheapest first; `errors` lists dates whose search failed
    (e.g. throttling) -- if every search failed, wait before retrying.

    Args:
        origin: Origin IATA airport code, e.g. "CDG".
        destination: Destination IATA airport code, e.g. "LIS".
        start: First departure date, YYYY-MM-DD.
        end: Last departure date (one-way) or latest return date (round trip), YYYY-MM-DD.
        nights: Round-trip stay length, "N" or "MIN-MAX". Omit for one-way.
        top: Number of cheapest itineraries to return.
        max_stops: Maximum stops per itinerary (0 = direct only).
        max_price: Only return itineraries up to this price.
        seat: Cabin class.
        adults: Number of adult passengers (1-9).
        currency: ISO currency code for prices.
    """
    try:
        return await asyncio.to_thread(
            find_cheapest,
            _iata(origin), _iata(destination), _date(start), _date(end),
            nights=_nights(nights) if nights else None, top=top, max_stops=max_stops,
            max_price=max_price, seat=seat, adults=adults, currency=currency,
        )
    except (ValueError, argparse.ArgumentTypeError) as e:
        raise ToolError(str(e)) from e  # surface bad input to the agent instead of a generic failure


def main():
    mcp.run()


if __name__ == "__main__":
    main()
