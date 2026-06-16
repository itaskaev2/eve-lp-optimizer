# EVE LP → ISK Optimizer

A small, read-only tool — **desktop UI + command line** — that finds the **best
Loyalty Point (LP) to ISK conversions** for your EVE Online character and values
the rewards at **Jita** market prices. Runs on Windows, macOS and Linux.

It works entirely off public data:

* **CCP ESI** (`/loyalty/stores/{corp}/offers/`) for the LP store catalogue, and
* **[Fuzzwork](https://market.fuzzwork.co.uk/) aggregates** for live Jita prices.

It never touches the game client, reads no game memory, and sends no input to the
game — so it stays well within CCP's [Third-Party Developer
guidelines](https://developers.eveonline.com/) and the EULA (it's the same class
of tool as a fitting calculator or a market spreadsheet).

---

## What it does

For every offer in a corporation's LP store it computes:

```
proceeds = Jita value of the rewarded item  − selling fees (sales tax / broker)
cost     = the offer's ISK cost  +  Jita cost of any required input items
profit   = proceeds − cost
ISK/LP   = profit / LP cost            ← offers are ranked by this
```

It then prints, per corporation, the most ISK-efficient offers, how many times
you can run each with your current LP balance, and the total projected profit.

## Requirements

* **Python 3.9+**
* The `requests` library — installed automatically by the helper scripts below.
* **Tkinter** — for the GUI only. It ships with the official python.org installers
  on Windows and macOS. Install it separately on Linux (and Homebrew Python):

  | Platform | Command |
  |----------|---------|
  | Debian / Ubuntu | `sudo apt install python3-tk` |
  | Fedora | `sudo dnf install python3-tkinter` |
  | Arch | `sudo pacman -S tk` |
  | macOS (Homebrew) | `brew install python-tk` |

  The command-line tool needs no Tkinter.

## Quick start

Clone the repo, then run the helper script for your OS. On first run it creates an
isolated virtual environment, installs dependencies, and launches the app.

### Windows

```powershell
git clone https://github.com/itaskaev2/eve-lp-optimizer.git
cd eve-lp-optimizer
.\run-gui.bat
```

…or just **double-click `run-gui.bat`** in Explorer. No Python yet? Install it and
re-run the script:

```powershell
winget install --id Python.Python.3.12 -e
```

(The `python` on a clean Windows install is a Microsoft Store stub — the winget
package above is the real interpreter.)

### macOS / Linux

```bash
git clone https://github.com/itaskaev2/eve-lp-optimizer.git
cd eve-lp-optimizer
chmod +x run-gui.sh run-cli.sh   # first time only
./run-gui.sh
```

The scripts use `python3` by default; override it, e.g. `PYTHON=python3.12 ./run-gui.sh`.

### Helper scripts

| Mode | Windows | macOS / Linux | What it does |
|------|---------|---------------|--------------|
| GUI | `run-gui.bat` | `run-gui.sh` | Bootstrap venv, then open the desktop app |
| CLI | `run-cli.bat` | `run-cli.sh` | Bootstrap venv, then run the command-line tool (args are passed through) |

```bash
# CLI via helper (args forwarded to the tool):
./run-cli.sh --corp "Caldari Navy:169675" --corp "Corporate Police Force:444399" --top 30
```

## Manual setup (any OS)

If you'd rather not use the scripts:

```bash
python -m venv .venv
# Windows (PowerShell):  .\.venv\Scripts\Activate.ps1
# macOS / Linux:         source .venv/bin/activate
pip install -r requirements.txt

python -m eve_lp.gui                              # GUI
python -m eve_lp --corp "Caldari Navy:169675"     # CLI
```

## Interactive UI

Pick a corporation, enter your LP, click **Load offers**, then **click any row**
to see its full requirements on the right — LP, ISK, and every item you must hand
in (the "+items") priced at Jita, plus a total shopping list to spend your whole
LP balance. Filter **with / without +items**, and click a column header to re-sort
(ISK/LP, profit, max runs, …). The UI is dark-themed and HiDPI-aware (crisp on 4K).

## Command-line usage

Pass each corporation as `Name:LP` (or `CorpID:LP`):

```bash
python -m eve_lp --corp "Caldari Navy:169675" --corp "Corporate Police Force:444399"
```

Show more rows, export a full CSV, and value rewards as an instant sell to buy
orders instead of a listed sell order:

```bash
python -m eve_lp --corp "Caldari Navy:169675" --top 30 --strategy buy --csv results.csv
```

> Line continuation differs by shell: PowerShell uses a backtick `` ` ``, while
> bash/zsh use `\`. The single-line form above works everywhere.

### Options

| Flag | Default | Meaning |
|------|---------|---------|
| `--corp NAME[:LP]` | (required) | Corporation + your LP balance. Repeatable. |
| `--top N` | `20` | Rows shown per corporation. |
| `--strategy {sell,buy}` | `sell` | `sell` = list a Jita sell order; `buy` = dump to buy orders. |
| `--price-field` | `percentile` | Fuzzwork field used for valuation (`percentile` is robust against outliers). |
| `--sales-tax` | `3.37` | Sales tax %. 7.5% base, −11%/level Accounting → ~3.37% at V. |
| `--broker-fee` | `1.5` | Broker fee % on sell orders. 3.0% base, −0.3%/level Broker Relations → ~1.5% at V. |
| `--min-isk-per-lp` | — | Hide offers below this ISK/LP. |
| `--include-unpriced` | off | Also list offers with no/illiquid Jita data. |
| `--station` | `60003760` | Market station id (default Jita 4-4). |
| `--csv PATH` | — | Write full ranked results to CSV. |
| `--user-agent` | env `EVE_LP_USER_AGENT` | CCP asks that this identify you — set it to include your email. |

### Example output

```
================================================================================
 Caldari Navy - 169,675 LP available
================================================================================
 #  Item                                  LP cost  ISK/LP  Profit/run  Cost/run  Max runs  Total profit
 1  Caldari Navy Ballistic Control...       1,200   1,480       1.78M     3.10M       141        250.6M
 ...

 Best play: 141x "Caldari Navy Ballistic Control System" using all 169,675 LP
            -> ~250.6M ISK profit (needs ~437M ISK upfront).
```

## How fees are modelled

* **`sell` strategy** (default): you list a sell order, so both the **broker fee**
  (on order creation) and **sales tax** (on sale) reduce your proceeds.
* **`buy` strategy**: you sell instantly into existing buy orders, so only **sales
  tax** applies.
* **Required input items** are valued at the cheapest Jita **sell** order — what
  you'd actually pay to buy them — with no fee, since buying from a sell order is
  free.

Adjust `--sales-tax` / `--broker-fee` to match your own skills and standings.

## Caveats

* Prices are aggregates and move constantly; treat ISK/LP as a ranking guide, not
  a guarantee.
* **Liquidity matters.** A spectacular ISK/LP on a thinly-traded item may be hard
  to actually offload at that price. Use `--csv` and sanity-check daily volume in
  game before committing a lot of LP.
* Some offers require faction tags / datacores / other inputs — those costs are
  included automatically when they're priced in Jita.

## License

MIT — see [LICENSE](LICENSE).
