# EVE LP → ISK Optimizer — Project Guide

Context for Claude Code (and humans) working in this repo.

## What this is

A **read-only** tool that ranks EVE Online Loyalty Point (LP) store offers by ISK
profit per LP, valuing the rewards at **Jita** market prices. Two front-ends share
one core: a **Tkinter desktop GUI** and a **command-line tool**.

It is **EULA-safe**: it only reads public web APIs (CCP ESI + Fuzzwork market
aggregates). It never touches the game client, reads no game memory, and sends no
input to the game — same category as a fitting calculator or market spreadsheet.
Do **not** add any gameplay automation / input injection / client interaction.

## Architecture

```
eve_lp/
  esi.py        ESI client: loyalty offers, name<->id resolution (public, no auth)
  market.py     Jita prices via Fuzzwork aggregates API (batched)
  optimizer.py  Core math: profit, ISK/LP, fees, ranking (OfferResult dataclass)
  cli.py        argparse CLI, table rendering, CSV export, fmt_isk()
  gui.py        Tkinter UI (dark theme, HiDPI-aware) — reuses cli/esi/market/optimizer
  __main__.py   `python -m eve_lp` -> cli.main
```

Both front-ends call `optimizer.evaluate_offers(...)` + `optimizer.rank(...)`, so
GUI and CLI numbers always match. `gui.py` imports `fmt_isk` from `cli.py`.

## Data sources & key constants

- **ESI** base `https://esi.evetech.net/latest` (public endpoints only):
  `/loyalty/stores/{corp_id}/offers/`, `POST /universe/ids/`, `POST /universe/names/`.
  Offer schema: `offer_id, type_id, quantity, lp_cost, isk_cost, ak_cost,
  required_items[{type_id, quantity}]`. Send a descriptive `User-Agent`.
- **Fuzzwork** `https://market.fuzzwork.co.uk/aggregates/?station=<id>&types=<csv>`
  — returns string-valued `buy`/`sell` aggregates (percentile/min/max/…). Batched
  ~100 types per request.
- **Jita 4-4** station id `60003760` (default valuation station).
- Corp ids (resolved dynamically, but for reference): **Caldari Navy `1000035`**,
  **Corporate Police Force `1000043`**.
- Fee defaults assume maxed skills: sales tax **3.37%**, broker **1.5%**.

## Valuation model (see optimizer.py)

```
proceeds = Jita value of reward − selling fees      (sell strategy: tax+broker; buy: tax only)
cost     = offer isk_cost + Jita buy cost of required "+items"
profit   = proceeds − cost
ISK/LP   = profit / lp_cost                          ← ranking metric
```

Required "+items" are valued at the cheapest Jita sell order (what you'd pay to
buy them); buying from a sell order incurs no fee. The GUI detail pane also shows
the **all-in shopping list** = each required item × max runs for the user's LP.

## Running

Self-bootstrapping launchers (create venv + install deps on first run):

- Windows: `run-gui.bat` / `run-cli.bat`
- macOS/Linux: `./run-gui.sh` / `./run-cli.sh`  (override interp with `PYTHON=...`)

Manual: `python -m eve_lp.gui` (UI) or `python -m eve_lp --corp "Caldari Navy:169675"` (CLI).

GUI needs **Tkinter** (bundled on Windows/macOS python.org installers; Linux needs
`python3-tk` / `python3-tkinter` / `tk`).

## Dev / verification conventions

- This is a **headless agent environment** — you cannot interactively click the
  GUI. Verify changes with:
  - `python -m py_compile eve_lp/*.py`
  - `python -m eve_lp.gui --selftest` — builds the whole window and auto-closes
    after 0.5s (catches Tkinter/ttk errors without blocking).
  - Headless data checks via a short `python - <<'PY' … PY` snippet that calls the
    `esi`/`market`/`optimizer` modules directly and prints numbers.
- To launch the GUI for the user (Windows): `Start-Process pythonw.exe -ArgumentList
  "-m","eve_lp.gui"`. Note: the venv `pythonw.exe` is a redirector, so one window =
  two `pythonw` processes (launcher + child) — that is expected, not a duplicate.
- `.gitattributes` pins `*.sh`/`*.py` to LF and `*.bat` to CRLF — keep it.

## Environment notes (this machine)

- Windows 11, single Python **3.12.10** at `%LOCALAPPDATA%\Programs\Python\Python312`
  (the Microsoft Store `python.exe` alias stubs were removed). Project venv in `.venv`.
- 4K display at 125% scaling; the GUI is DPI-aware (`_enable_hidpi()` in gui.py) and
  scales by the monitor DPI.

## Conventions

- Keep the GUI/CLI thin; put shared logic in `optimizer.py`.
- Network calls in the GUI must stay off the UI thread (`threading` + `root.after`).
- Commit messages end with the `Co-Authored-By: Claude …` trailer.
