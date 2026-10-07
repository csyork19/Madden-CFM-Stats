# Madden League Stats: Broadcast + Team Hub

Two pages driven by one data file that is generated from a Madden Companion export.

| File | What it is |
|---|---|
| `broadcast.html` | Scoreboard, award races, league leaders (passing, rushing, receiving, interceptions, sacks, tackles), team rankings, rosters |
| `team-hub.html` | One team: tiles, roster, player card, weekly game log |
| `streams.html` | One stream slot per game, tagged Twitch or YouTube |
| `streams.js` | Stream links you fill in by hand (week, then `AWAY@HOME`) |
| `build_league_data.py` | Reads the export CSVs and writes `league-data.js` |
| `serve.py` | Local server that rebuilds the data on every page load |
| `fetch_export.py` | Downloads the latest CSV export from Madden Exporter and rebuilds the data |
| `league-data.js` | Generated data (do not edit by hand) |
| `canvas-source/` | The original canvas boards, for reference; they only run inside the Claude canvas |

## Run it

Live (recommended): the data is rebuilt from the CSVs each time a page loads.

    python3 serve.py /path/to/madden-export-league-XXXX
    # open http://localhost:8000/

One-off: write `league-data.js` once, then double-click `broadcast.html`.

    python3 build_league_data.py /path/to/madden-export-league-XXXX

The folder argument is optional. Without it the scripts use the export this
project sits in or next to, else the newest `madden-export-*` in `~/Downloads`.
Needs Python 3 only, no packages.

## How weeks are picked up

Nothing about the number of weeks is hard-coded. The build script scans:

- `stats/reg/<N>/<Team>/player-stats.csv`: every numbered folder is a played week
- `schedules/reg/week-N.csv`: scores and home/away for that week
- `teams.csv`, `players.csv`: teams, colours, rosters, ratings

Add `stats/reg/3`, `4`, ... (or point at a newer export) and the week arrows,
"season thru week N" totals, standings and game logs extend automatically.

If a week has stats but an empty schedule file, matchups come from the stat
rows and scores are rebuilt from scoring plays, then checked against the season
totals in `teams.csv`. Scores that cannot be confirmed are labelled `FINAL · EST`.

## Small settings

- League name: replace `[YOUR LEAGUE NAME]` in both HTML files.
- Accent colour and roster rows: the `mountDC(Component, {...})` line at the bottom of `broadcast.html`.

## Streams

`streams.html` lists every game of the selected week with one video slot each.
Edit `streams.js` to set a game's `platform` (`twitch` or `youtube`) and `url`.
With no link the slot shows a placeholder; with a link the play button loads the
player in place. Twitch only embeds when the page is served (`python3 serve.py`),
not when the file is double-clicked; the "Open on" button works either way.

## Headshots

The Broadcast page and the Team Hub player card load each headshot from EA's Madden ratings site using
the export's `portraitId`. Nothing is downloaded or stored here, so it needs an
internet connection; players without a portrait fall back to the jersey number.

## Award races

MVP, OPOY, DPOY, OROY and DROY on the Broadcast page are unofficial: the export
has no award data, so players are ranked by a production score built from their
season stats (`off_score` and `def_score` in `build_league_data.py`). MVP adds 3
points per team win and weights quarterbacks 1.25x; OPOY excludes quarterbacks;
rookies are players with 0 years of experience. Change the weights there.

## Fetching the export automatically

`fetch_export.py` opens your Madden Exporter data page, clicks "Download CSV",
unzips the file into `exports/` and rebuilds `league-data.js`.

    pip3 install playwright                    # one time
    python3 -m playwright install chromium     # one time
    python3 fetch_export.py                    # first run: sign in in the window
    python3 fetch_export.py --headless         # later runs, no window

The first run opens a browser window; sign in there once. The login is kept in
`.exporter-profile/` (treat that folder as private), so the script never needs
your password. Use `--league <id>` if the account has more than one export.
`build_league_data.py` and `serve.py` use the newest download in `exports/`
automatically. You still have to export from the Companion app first; this
script only collects what is already on the site.
