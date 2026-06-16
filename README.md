# EVE LP → ISK Optimizer

A small, read-only command-line tool that finds the **best Loyalty Point (LP) to
ISK conversions** for your EVE Online character and values the rewards at **Jita**
market prices.

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
* The `requests` library

### Installing Python on Windows

The `python` you may see on a fresh Windows install is just a Microsoft Store
stub. Install the real thing:

```powershell
winget install --id Python.Python.3.12 -e
```

Close and reopen your terminal afterwards, then verify:

```powershell
python --version
```

## Install

```powershell
git clone https://github.com/itaskaev2/eve-lp-optimizer.git
cd eve-lp-optimizer

# (recommended) isolated environment
python -m venv .venv
.\.venv\Scripts\Activate.ps1

pip install -r requirements.txt
```

## Interactive UI (recommended)

A point-and-click desktop app (Tkinter, bundled with Python — no extra installs):

```powershell
python -m eve_lp.gui
```

or just double-click **`run-gui.bat`** in the project folder.

Pick a corporation, enter your LP, click **Load offers**, then **click any row**
in the list to see its full requirements on the right — LP, ISK, and every item
you must hand in (the "+items"), each priced at Jita. Click a column header to
re-sort (by ISK/LP, profit, max runs, …).

## Command-line usage

Pass each corporation as `Name:LP` (or `CorpID:LP`). For the example character:

```powershell
python -m eve_lp --corp "Caldari Navy:169675" --corp "Corporate Police Force:444399"
```

Show more rows, export a full CSV, and value rewards as an instant sell to buy
orders instead of a listed sell order:

```powershell
python -m eve_lp `
  --corp "Caldari Navy:169675" `
  --corp "Corporate Police Force:444399" `
  --top 30 --strategy buy --csv results.csv
```

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
