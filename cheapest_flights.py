"""Find the cheapest flights between two airports over a date window.

One-way: every date in [start, end] is searched.
Round trip (--nights): every departure date is paired with each stay length,
and the return must land on or before `end`. Prices are Google Flights totals
(round-trip price for round trips) in the requested currency.

Output is JSON on stdout (or a table with --table); diagnostics go to stderr.
"""

import argparse
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta

from fast_flights import FlightQuery, FlightsNotFound, Passengers, create_query
from fast_flights.fetcher import URL
from fast_flights.parser import parse
from primp import Client

# Google serves an EU consent wall (no data) unless a consent cookie is sent.
CONSENT_COOKIE = "SOCS=CAESEwgDEgk0ODE3Nzk3MjQaAmVuIAEaBgiA_LyaBg; CONSENT=PENDING+987"
MAX_SEARCHES = 200  # guard against accidentally hammering Google
RETRIES = 3


@dataclass(frozen=True)
class Search:
    origin: str
    destination: str
    depart: date
    ret: date | None  # None = one-way


def build_searches(origin, destination, start, end, nights):
    """Expand the window into concrete (depart[, return]) searches."""
    if nights is None:
        days = (end - start).days + 1
        return [Search(origin, destination, start + timedelta(d), None) for d in range(days)]
    lo, hi = nights
    return [
        Search(origin, destination, d, d + timedelta(n))
        for d in (start + timedelta(i) for i in range((end - start).days + 1))
        for n in range(lo, hi + 1)
        if d + timedelta(n) <= end
    ]


def fetch(search, *, seat, adults, currency, max_stops, max_price):
    """Run one Google Flights search and return its itineraries as dicts."""
    legs = [FlightQuery(date=search.depart, from_airport=search.origin, to_airport=search.destination)]
    if search.ret:
        legs.append(FlightQuery(date=search.ret, from_airport=search.destination, to_airport=search.origin))
    query = create_query(
        flights=legs,
        seat=seat,
        trip="round-trip" if search.ret else "one-way",
        passengers=Passengers(adults=adults),
        language="en-US",
        currency=currency,
        max_stops=max_stops,
        max_price=max_price,
    )
    client = Client(impersonate="chrome_145", impersonate_os="macos", referer=True, cookie_store=True)
    for attempt in range(RETRIES):
        try:
            html = client.get(URL, params=query.params(), headers={"Cookie": CONSENT_COOKIE}).text
            results = parse(html)
            break
        except FlightsNotFound:
            return []
        except Exception:
            if attempt == RETRIES - 1:
                raise
            time.sleep(2**attempt)
    return [_itinerary(f, search, currency) for f in results]


def _itinerary(flight, search, currency):
    first, last = flight.flights[0], flight.flights[-1]
    return {
        "price": flight.price,
        "currency": currency,
        "depart_date": search.depart.isoformat(),
        "return_date": search.ret.isoformat() if search.ret else None,
        "origin": search.origin,
        "destination": search.destination,
        "airlines": flight.airlines,
        "stops": len(flight.flights) - 1,
        "departure": _fmt(first.departure),
        "arrival": _fmt(last.arrival),
        "flying_minutes": sum(s.duration for s in flight.flights),
        "legs": [f"{s.from_airport.code}->{s.to_airport.code} {_fmt(s.departure)}" for s in flight.flights],
    }


def _fmt(dt):
    y, m, d = dt.date
    hh, mm = dt.time
    return f"{y:04d}-{m:02d}-{d:02d} {hh:02d}:{mm:02d}"


def search_all(searches, workers, **opts):
    """Run searches concurrently; return (itineraries, errors)."""
    itineraries, errors = [], []

    def run(s):
        try:
            return s, fetch(s, **opts), None
        except Exception as e:  # one bad date must not sink the whole sweep
            return s, [], f"{type(e).__name__}: {e}"

    with ThreadPoolExecutor(max_workers=workers) as pool:
        for s, found, err in pool.map(run, searches):
            itineraries += found
            if err:
                errors.append({"depart_date": s.depart.isoformat(), "error": err})
    return itineraries, errors


def _iata(value):
    if not re.fullmatch(r"[A-Za-z]{3}", value):
        raise argparse.ArgumentTypeError(f"{value!r} is not a 3-letter IATA airport code")
    return value.upper()


def _date(value):
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a YYYY-MM-DD date") from None


def _nights(value):
    m = re.fullmatch(r"(\d+)(?:-(\d+))?", value)
    if not m or int(m[1]) > int(m[2] or m[1]):
        raise argparse.ArgumentTypeError(f"{value!r} must be N or MIN-MAX (e.g. 7 or 5-9)")
    return int(m[1]), int(m[2] or m[1])


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="cheapest-flights",
        description="Find the cheapest flights between two airports within a date window.",
    )
    p.add_argument("origin", type=_iata, help="origin IATA code, e.g. CDG")
    p.add_argument("destination", type=_iata, help="destination IATA code, e.g. LIS")
    p.add_argument("--start", required=True, type=_date, help="first departure date (YYYY-MM-DD)")
    p.add_argument("--end", required=True, type=_date, help="last date of the window (YYYY-MM-DD); "
                   "last departure for one-way, latest return for round trips")
    p.add_argument("--nights", type=_nights, help="round trip stay length, N or MIN-MAX (omit for one-way)")
    p.add_argument("--top", type=int, default=10, help="number of cheapest itineraries to return (default 10)")
    p.add_argument("--max-stops", type=int, help="maximum stops (0 = direct only)")
    p.add_argument("--max-price", type=int, help="ignore itineraries above this price")
    p.add_argument("--seat", default="economy", choices=["economy", "premium-economy", "business", "first"])
    p.add_argument("--adults", type=int, default=1, help="number of adults (default 1)")
    p.add_argument("--currency", default="EUR", help="ISO currency code (default EUR)")
    p.add_argument("--workers", type=int, default=4, help="parallel searches (default 4)")
    p.add_argument("--table", action="store_true", help="print a human-readable table instead of JSON")
    return p.parse_args(argv)


def render_table(results):
    if not results:
        return "no flights found"
    header = ("PRICE", "DEPART", "RETURN", "STOPS", "AIRLINES", "DEPARTS", "ARRIVES", "MIN")
    rows = [header] + [
        (f"{r['price']} {r['currency']}", r["depart_date"], r["return_date"] or "-", str(r["stops"]),
         ", ".join(r["airlines"]), r["departure"], r["arrival"], str(r["flying_minutes"]))
        for r in results
    ]
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(row, widths)).rstrip() for row in rows)


def find_cheapest(origin, destination, start, end, *, nights=None, top=10, max_stops=None,
                  max_price=None, seat="economy", adults=1, currency="EUR", workers=4):
    """Search the window and return the `top` cheapest itineraries (raises ValueError on bad input)."""
    if end < start:
        raise ValueError("end must not be before start")
    if start < date.today():
        raise ValueError("start is in the past")
    if top < 1 or workers < 1 or not 1 <= adults <= 9:
        raise ValueError("top and workers must be >= 1 and adults between 1 and 9")
    searches = build_searches(origin, destination, start, end, nights)
    if not searches:
        raise ValueError("window too short for the requested nights")
    if len(searches) > MAX_SEARCHES:
        raise ValueError(f"{len(searches)} searches exceeds the limit of {MAX_SEARCHES}; narrow the window")

    print(f"searching {len(searches)} date(s)...", file=sys.stderr)
    itineraries, errors = search_all(
        searches, workers, seat=seat, adults=adults, currency=currency.upper(),
        max_stops=max_stops, max_price=max_price,
    )
    itineraries.sort(key=lambda i: (i["price"], i["flying_minutes"]))
    return {
        "origin": origin, "destination": destination,
        "start": start.isoformat(), "end": end.isoformat(),
        "searches": len(searches), "failed_searches": len(errors),
        "results": itineraries[:top], "errors": errors,
    }


def main(argv=None):
    args = parse_args(argv)
    try:
        out = find_cheapest(
            args.origin, args.destination, args.start, args.end, nights=args.nights, top=args.top,
            max_stops=args.max_stops, max_price=args.max_price, seat=args.seat, adults=args.adults,
            currency=args.currency, workers=args.workers,
        )
    except ValueError as e:
        sys.exit(f"error: {e}")

    if args.table:
        print(render_table(out["results"]))
        for e in out["errors"]:
            print(f"error {e['depart_date']}: {e['error']}", file=sys.stderr)
    else:
        print(json.dumps(out, indent=2))
    # Non-zero only when nothing at all could be fetched, so agents can detect a block.
    if out["errors"] and len(out["errors"]) == out["searches"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
