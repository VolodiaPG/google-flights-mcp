# cheapest-flights

CLI that finds the cheapest flights between two airports over a date window, using
[fast-flights](https://github.com/AWeirdDev/flights) (Google Flights). Usable as a CLI or as an MCP server.

```sh
uv run cheapest-flights ORIGIN DEST --start YYYY-MM-DD --end YYYY-MM-DD [options]
```

| Mode       | How                                                                      |
| ---------- | ------------------------------------------------------------------------ |
| One-way    | every date from `--start` to `--end` is searched                         |
| Round trip | add `--nights N` or `--nights MIN-MAX`; return must be on/before `--end` |

Options: `--top N` (10), `--max-stops N` (0 = direct), `--max-price N`, `--seat`, `--adults`,
`--currency` (EUR), `--workers` (4), `--table` (human output instead of JSON).

## Output (JSON on stdout, progress on stderr)

`results` is sorted by price (ties: shorter flying time). Each entry has `price`, `currency`, `depart_date`,
`return_date`, `airlines`, `stops`, `departure`, `arrival`, `flying_minutes` (excludes layovers), `legs`.
`errors` lists dates whose search failed (`failed_searches` counts them); exit code is 1 only if _every_ search failed
(typically Google throttling — wait or reduce `--workers`).

Notes:

- Round-trip `price` is the Google round-trip total; `legs` / times describe the **outbound** flight only.
- One HTTP request per date (or date/stay pair), capped at 200 per run.
- Google's EU consent wall is bypassed with a consent cookie; fast-flights alone returns nothing from the EU.

## MCP server

`cheapest-flights-mcp` (stdio) exposes one tool, `search_cheapest_flights`, with the same parameters as the CLI
(`origin`, `destination`, `start`, `end`, `nights`, `top`, `max_stops`, `max_price`, `seat`, `adults`, `currency`)
and the same JSON result. Bad input comes back as a tool error with the reason.

Register it with Claude Code:

```sh
claude mcp add --scope user cheapest-flights -- uv run --project /Users/volodia/Documents/vacances cheapest-flights-mcp
```

or in any MCP client config:

```json
{
  "mcpServers": {
    "cheapest-flights": {
      "command": "uv",
      "args": [
        "run",
        "--project",
        "/Users/volodia/Documents/vacances",
        "cheapest-flights-mcp"
      ]
    }
  }
}
```

Tests: `uv run pytest`
