"""A small Tkinter desktop UI for the LP -> ISK optimizer.

Left:  a sortable list of LP store offers ranked by ISK/LP.
Right: click any row to see exactly what it costs to make - LP, ISK, and the
       items you must hand in (the "+items"), each priced at Jita.

Run with:  python -m eve_lp.gui      (or pythonw to hide the console)
"""

from __future__ import annotations

import argparse
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from .cli import fmt_isk
from .esi import EsiClient, EsiError
from .market import JitaMarket, TRADE_HUBS, MarketError
from .optimizer import FeeSettings, evaluate_offers, rank

# Pre-fill convenience: known corporations and the example character's balances.
KNOWN_CORPS = {
    "Caldari Navy": "169675",
    "Corporate Police Force": "444399",
}
DEFAULT_CORP = "Corporate Police Force"

# Dark theme palette.
DARK_BG = "#1b1b1b"
DARK_FIELD = "#262626"
DARK_FG = "#e6e6e6"
DARK_ACCENT = "#3a3a3a"
DARK_ACTIVE = "#4a4a4a"
DARK_SEL = "#2d5a88"

# Treeview columns: (id, heading, width, anchor, sort attribute on OfferResult).
COLUMNS = [
    ("rank", "#", 40, "e", None),
    ("item", "Item", 320, "w", "item_name"),
    ("lp", "LP cost", 90, "e", "lp_cost"),
    ("isklp", "ISK/LP", 80, "e", "isk_per_lp"),
    ("profit", "Profit/run", 90, "e", "profit"),
    ("cost", "Cost/run", 90, "e", "total_cost"),
    ("runs", "Max runs", 80, "e", "max_runs"),
    ("total", "Total profit", 100, "e", "total_profit"),
]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("EVE LP -> ISK Optimizer")
        self.scale = self._init_scaling()
        s = self.scale
        root.geometry(f"{int(1080 * s)}x{int(620 * s)}")
        root.minsize(int(820 * s), int(460 * s))
        self._apply_theme()

        self.esi = EsiClient()
        self.market = JitaMarket()

        # state
        self.all_results = []        # full ranked list from the last load
        self.results = []            # list[OfferResult] currently displayed (filtered/sorted)
        self.loaded_corp = ""
        self.row_map = {}            # tree iid -> OfferResult
        self.offers_cache = {}       # corp_id -> (offers, names)
        self.available_lp = None
        self.hub_name = "Jita"
        self.sort_attr = None
        self.sort_reverse = True

        self._build_controls()
        self._build_body()
        self._build_status()
        self._load_corp_list_async()

    # -- scaling / theme ---------------------------------------------------
    def _init_scaling(self) -> float:
        """Scale Tk to the monitor DPI and return the pixel scale vs 96 DPI."""
        try:
            dpi = float(self.root.winfo_fpixels("1i"))  # real DPI once DPI-aware
        except Exception:
            dpi = 96.0
        try:
            # point-based fonts (incl. ttk defaults) now render at physical size
            self.root.tk.call("tk", "scaling", dpi / 72.0)
        except Exception:
            pass
        return max(1.0, dpi / 96.0)

    def _apply_theme(self) -> None:
        bg, field, fg = DARK_BG, DARK_FIELD, DARK_FG
        accent, active, sel = DARK_ACCENT, DARK_ACTIVE, DARK_SEL
        self.root.configure(background=bg)

        # the combobox dropdown is a classic Tk listbox; darken it via options
        self.root.option_add("*TCombobox*Listbox.background", field)
        self.root.option_add("*TCombobox*Listbox.foreground", fg)
        self.root.option_add("*TCombobox*Listbox.selectBackground", sel)
        self.root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")

        style = ttk.Style()
        style.theme_use("clam")  # most colour-customisable built-in theme
        style.configure(".", background=bg, foreground=fg, fieldbackground=field,
                        bordercolor=accent, lightcolor=bg, darkcolor=bg,
                        insertcolor=fg, focuscolor=sel)
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TCheckbutton", background=bg, foreground=fg)
        style.map("TCheckbutton", background=[("active", bg)])
        style.configure("TButton", background=accent, foreground=fg, bordercolor=accent)
        style.map("TButton",
                  background=[("active", active), ("disabled", "#2a2a2a")],
                  foreground=[("disabled", "#777777")])
        style.configure("TEntry", fieldbackground=field, foreground=fg, insertcolor=fg)
        style.configure("TCombobox", fieldbackground=field, foreground=fg,
                        background=accent, arrowcolor=fg)
        style.map("TCombobox",
                  fieldbackground=[("readonly", field), ("disabled", bg)],
                  foreground=[("readonly", fg), ("disabled", "#777777")],
                  arrowcolor=[("disabled", "#777777")])
        style.configure("Treeview", background=field, fieldbackground=field,
                        foreground=fg, rowheight=int(22 * self.scale), bordercolor=accent)
        style.map("Treeview",
                  background=[("selected", sel)], foreground=[("selected", "#ffffff")])
        style.configure("Treeview.Heading", background=accent, foreground=fg, relief="flat")
        style.map("Treeview.Heading", background=[("active", active)])
        style.configure("TScrollbar", background=accent, troughcolor=bg,
                        arrowcolor=fg, bordercolor=bg)
        style.map("TScrollbar", background=[("active", active)])
        style.configure("TPanedwindow", background=bg)

    # -- UI construction ---------------------------------------------------
    def _build_controls(self) -> None:
        bar = ttk.Frame(self.root, padding=(8, 8, 8, 4))
        bar.pack(side="top", fill="x")

        ttk.Label(bar, text="Corporation:").grid(row=0, column=0, sticky="w")
        self.corp_var = tk.StringVar(value=DEFAULT_CORP)
        self.corp_box = ttk.Combobox(bar, textvariable=self.corp_var, width=28,
                                     values=sorted(KNOWN_CORPS))
        self.corp_box.grid(row=0, column=1, padx=(4, 12))
        self.corp_box.bind("<<ComboboxSelected>>", self._on_corp_selected)

        ttk.Label(bar, text="Your LP:").grid(row=0, column=2, sticky="w")
        self.lp_var = tk.StringVar(value=KNOWN_CORPS[DEFAULT_CORP])
        ttk.Entry(bar, textvariable=self.lp_var, width=12).grid(row=0, column=3, padx=(4, 12))

        ttk.Label(bar, text="Strategy:").grid(row=0, column=4, sticky="w")
        self.strategy_var = tk.StringVar(value="sell")
        ttk.Combobox(bar, textvariable=self.strategy_var, width=6, state="readonly",
                     values=["sell", "buy"]).grid(row=0, column=5, padx=(4, 12))

        ttk.Label(bar, text="Tax %:").grid(row=0, column=6, sticky="w")
        self.tax_var = tk.StringVar(value="3.37")
        ttk.Entry(bar, textvariable=self.tax_var, width=6).grid(row=0, column=7, padx=(4, 8))

        ttk.Label(bar, text="Broker %:").grid(row=0, column=8, sticky="w")
        self.broker_var = tk.StringVar(value="1.5")
        ttk.Entry(bar, textvariable=self.broker_var, width=6).grid(row=0, column=9, padx=(4, 12))

        self.unpriced_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar, text="Show unpriced", variable=self.unpriced_var
                        ).grid(row=0, column=10, padx=(0, 12))

        self.load_btn = ttk.Button(bar, text="Load offers", command=self.load)
        self.load_btn.grid(row=0, column=11)

        # second row (one frame): market hub + item filter + live search
        filt = ttk.Frame(bar)
        filt.grid(row=1, column=0, columnspan=12, sticky="w", pady=(6, 0))

        ttk.Label(filt, text="Hub:").pack(side="left")
        self.hub_var = tk.StringVar(value="Jita")
        hub_box = ttk.Combobox(filt, textvariable=self.hub_var, width=9, state="readonly",
                               values=list(TRADE_HUBS))
        hub_box.pack(side="left", padx=(4, 12))
        # changing hub re-prices the current list (only if something is loaded)
        hub_box.bind("<<ComboboxSelected>>",
                     lambda _e: self.load() if self.all_results else None)

        ttk.Label(filt, text="Items:").pack(side="left")
        self.items_filter_var = tk.StringVar(value="All offers")
        items_box = ttk.Combobox(filt, textvariable=self.items_filter_var, width=26,
                                 state="readonly",
                                 values=["All offers",
                                         "Without +items (pure LP+ISK)",
                                         "With +items only"])
        items_box.pack(side="left", padx=(4, 12))
        items_box.bind("<<ComboboxSelected>>", self._refresh_view)

        ttk.Label(filt, text="Search:").pack(side="left")
        self.search_var = tk.StringVar()
        search_entry = ttk.Entry(filt, textvariable=self.search_var, width=24)
        search_entry.pack(side="left", padx=(4, 2))
        ttk.Button(filt, text="✕", width=2,
                   command=lambda: self.search_var.set("")).pack(side="left")
        self.search_var.trace_add("write", lambda *_: self._refresh_view())

    def _build_body(self) -> None:
        panes = ttk.PanedWindow(self.root, orient="horizontal")
        panes.pack(side="top", fill="both", expand=True, padx=8, pady=4)

        # left: offer list
        left = ttk.Frame(panes)
        self.tree = ttk.Treeview(left, columns=[c[0] for c in COLUMNS],
                                 show="headings", selectmode="browse")
        for cid, heading, width, anchor, attr in COLUMNS:
            self.tree.heading(cid, text=heading,
                              command=(lambda a=attr: self._sort_by(a)) if attr else (lambda: None))
            self.tree.column(cid, width=int(width * self.scale), anchor=anchor,
                             stretch=(cid == "item"))
        vsb = ttk.Scrollbar(left, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        left.rowconfigure(0, weight=1)
        left.columnconfigure(0, weight=1)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_tree_double_click)
        panes.add(left, weight=3)

        # right: detail panel
        right = ttk.Frame(panes)
        ttk.Label(right, text="Requirements", padding=(2, 2)).pack(anchor="w")
        self.detail = tk.Text(right, wrap="word", width=46, height=10,
                              state="disabled", font=("Consolas", 10),
                              background="#1b1b1b", foreground="#e6e6e6",
                              padx=8, pady=8, relief="flat")
        dsb = ttk.Scrollbar(right, orient="vertical", command=self.detail.yview)
        self.detail.configure(yscrollcommand=dsb.set)
        self.detail.pack(side="left", fill="both", expand=True)
        dsb.pack(side="right", fill="y")
        self.detail.tag_configure("h1", foreground="#7fd1ff",
                                  font=("Consolas", 11, "bold"))
        self.detail.tag_configure("h2", foreground="#9be29b",
                                  font=("Consolas", 10, "bold"))
        self.detail.tag_configure("warn", foreground="#ffb86b")
        # clickable item names -> copy to clipboard
        self.detail.tag_configure("copyable", foreground="#7fd1ff", underline=True)
        self.detail.tag_bind("copyable", "<Enter>",
                             lambda _e: self.detail.configure(cursor="hand2"))
        self.detail.tag_bind("copyable", "<Leave>",
                             lambda _e: self.detail.configure(cursor=""))
        self._set_detail([("Click an offer on the left to see what it takes to "
                           "make it.\n", None),
                          ("Tip: click any underlined item name to copy it.\n", "h2")])
        panes.add(right, weight=2)

    def _build_status(self) -> None:
        self.status_var = tk.StringVar(value="Ready. Pick a corporation and click "
                                             "‘Load offers’.")
        ttk.Label(self.root, textvariable=self.status_var, relief="sunken",
                  anchor="w", padding=(6, 3)).pack(side="bottom", fill="x")

    # -- corporation list (loaded in the background) -----------------------
    def _load_corp_list_async(self) -> None:
        """Fetch every NPC corporation name off-thread and fill the picker."""
        def worker():
            try:
                ids = self.esi.npc_corporation_ids()
                names = self.esi.names_for_ids(ids)
                corp_names = sorted(set(names.values()), key=str.lower)
                self.root.after(0, lambda: self._set_corp_list(corp_names))
            except Exception as exc:  # keep the two known corps as fallback
                self.root.after(0, lambda: self._set_status(
                    f"Using built-in corp list (couldn't fetch full list: {exc})"))
        threading.Thread(target=worker, daemon=True).start()

    def _set_corp_list(self, corp_names) -> None:
        current = self.corp_var.get()
        self.corp_box.configure(values=corp_names)
        self.corp_var.set(current)  # keep the current selection
        self._set_status(f"{len(corp_names)} corporations available. "
                         f"Pick one (default {DEFAULT_CORP}) and click ‘Load offers’.")

    # -- events ------------------------------------------------------------
    def _on_corp_selected(self, _event=None) -> None:
        lp = KNOWN_CORPS.get(self.corp_var.get().strip())
        if lp is not None:
            self.lp_var.set(lp)

    def _fees(self) -> FeeSettings:
        def num(var, default):
            try:
                return float(var.get().replace(",", "").strip())
            except (ValueError, AttributeError):
                return default
        return FeeSettings(
            sales_tax_pct=num(self.tax_var, 3.37),
            broker_fee_pct=num(self.broker_var, 1.5),
            output_strategy=self.strategy_var.get(),
        )

    def _parse_lp(self):
        raw = self.lp_var.get().replace(",", "").replace("_", "").strip()
        if not raw:
            return None
        try:
            return int(raw)
        except ValueError:
            return None

    # -- loading (off the UI thread) --------------------------------------
    def load(self) -> None:
        corp = self.corp_var.get().strip()
        if not corp:
            messagebox.showwarning("Missing corporation", "Enter a corporation name or id.")
            return
        self.available_lp = self._parse_lp()
        fees = self._fees()
        self.hub_name = self.hub_var.get()
        self.market.station_id = TRADE_HUBS.get(self.hub_name, TRADE_HUBS["Jita"])
        self.load_btn.configure(state="disabled")
        self._set_status(f"Loading offers for {corp} @ {self.hub_name} …")
        threading.Thread(target=self._load_worker, args=(corp, fees), daemon=True).start()

    def _load_worker(self, corp: str, fees: FeeSettings) -> None:
        try:
            corp_id, corp_name = self.esi.resolve_corporation(corp)
            if corp_id in self.offers_cache:
                offers, names = self.offers_cache[corp_id]
            else:
                offers = self.esi.loyalty_offers(corp_id)
                type_ids = set()
                for off in offers:
                    type_ids.add(off["type_id"])
                    for req in off.get("required_items") or []:
                        type_ids.add(req["type_id"])
                names = self.esi.names_for_ids(type_ids)
                self.offers_cache[corp_id] = (offers, names)

            type_ids = {off["type_id"] for off in offers}
            for off in offers:
                for req in off.get("required_items") or []:
                    type_ids.add(req["type_id"])
            prices = self.market.prices(type_ids)

            results = evaluate_offers(offers, prices, names, fees, self.available_lp)
            ranked = rank(results, include_unpriced=self.unpriced_var.get())
            self.root.after(0, lambda: self._on_loaded(corp_name, ranked))
        except (EsiError, MarketError) as exc:
            self.root.after(0, lambda: self._on_error(str(exc)))
        except Exception as exc:  # pragma: no cover - defensive
            self.root.after(0, lambda: self._on_error(repr(exc)))

    def _on_loaded(self, corp_name: str, ranked) -> None:
        self.all_results = ranked
        self.loaded_corp = corp_name
        self.sort_attr = "isk_per_lp"
        self.sort_reverse = True
        self._refresh_view()
        self.load_btn.configure(state="normal")

    def _on_error(self, message: str) -> None:
        self.load_btn.configure(state="normal")
        self._set_status("Error: " + message)
        messagebox.showerror("Load failed", message)

    # -- table -------------------------------------------------------------
    def _populate(self) -> None:
        self.tree.delete(*self.tree.get_children())
        self.row_map.clear()
        show_runs = self.available_lp is not None
        for idx, r in enumerate(self.results, start=1):
            label = r.item_name if r.quantity == 1 else f"{r.quantity}x {r.item_name}"
            if r.required_items:
                label += "  (+items)"
            if not r.priced:
                label += "  [unpriced]"
            values = (
                idx, label, f"{r.lp_cost:,}",
                f"{r.isk_per_lp:,.0f}" if r.priced else "-",
                fmt_isk(r.profit) if r.priced else "-",
                fmt_isk(r.total_cost),
                f"{r.max_runs:,}" if show_runs else "",
                fmt_isk(r.total_profit) if show_runs else "",
            )
            iid = self.tree.insert("", "end", values=values)
            self.row_map[iid] = r
        # auto-select the first (best) row
        children = self.tree.get_children()
        if children:
            self.tree.selection_set(children[0])
            self.tree.focus(children[0])
        else:
            self._set_detail([("No offers match the current filter.\n", "warn")])

    def _filtered(self):
        results = self.all_results
        mode = self.items_filter_var.get()
        if mode.startswith("Without"):
            results = [r for r in results if not r.required_items]
        elif mode.startswith("With"):
            results = [r for r in results if r.required_items]
        term = self.search_var.get().strip().lower()
        if term:
            results = [r for r in results if term in r.item_name.lower()]
        return list(results)

    def _refresh_view(self, _event=None) -> None:
        view = self._filtered()
        if self.sort_attr:
            keyfn = (str.lower) if self.sort_attr == "item_name" else (lambda v: v)
            view.sort(key=lambda r: keyfn(getattr(r, self.sort_attr)),
                      reverse=self.sort_reverse)
        self.results = view
        self._populate()
        lp_txt = f"{self.available_lp:,} LP" if self.available_lp is not None else "LP not set"
        term = self.search_var.get().strip()
        search_txt = f', search="{term}"' if term else ""
        self._set_status(
            f"{self.loaded_corp}: showing {len(view)} of {len(self.all_results)} offers "
            f"[{self.items_filter_var.get()}{search_txt}]  "
            f"({lp_txt}, {self.hub_name}, strategy={self.strategy_var.get()}). "
            f"Click a row for requirements.")

    def _sort_by(self, attr) -> None:
        if not self.all_results or attr is None:
            return
        if self.sort_attr == attr:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_attr = attr
            self.sort_reverse = attr != "item_name"  # text ascending, numbers descending
        self._refresh_view()

    def _on_select(self, _event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        r = self.row_map.get(sel[0])
        if r is not None:
            self._render_detail(r)

    def _on_tree_double_click(self, _event=None) -> None:
        sel = self.tree.selection()
        if sel:
            r = self.row_map.get(sel[0])
            if r is not None:
                self._copy_text(r.item_name)

    # -- detail panel ------------------------------------------------------
    def _render_detail(self, r) -> None:
        n = lambda v: f"{v:,.0f}"
        segs = []
        if r.quantity != 1:
            segs.append((f"{r.quantity}x ", "h1"))
        segs.append((r.item_name, "h1", r.item_name))  # clickable -> copy
        segs.append(("\n", "h1"))
        segs.append(("\nYou pay\n", "h2"))
        segs.append((f"  Loyalty Points : {r.lp_cost:,} LP\n", None))
        segs.append((f"  ISK            : {n(r.isk_cost)} ISK\n", None))

        if r.required_items:
            segs.append(("\nItems to hand in  (the “+items”)\n", "h2"))
            for ri in r.required_items:
                priced = "" if ri.priced else "   [no Jita price]"
                segs.append((f"  {ri.quantity:>4}x ", None))
                segs.append((ri.name, None, ri.name))  # clickable -> copy
                segs.append(("\n", None))
                segs.append(
                    (f"         @ {n(ri.unit_cost)} = {n(ri.total_cost)} ISK{priced}\n",
                     None if ri.priced else "warn"))
            segs.append((f"  Items subtotal : {n(r.required_cost)} ISK\n", None))
        else:
            segs.append(("\nItems to hand in : none (pure LP + ISK)\n", "h2"))

        strat = "list sell order" if self.strategy_var.get() == "sell" else "instant sell to buy orders"
        segs.append((f"\nReward value in {self.hub_name} ({strat}, after fees)\n", "h2"))
        segs.append((f"  {n(r.net_value)} ISK\n", None))

        segs.append(("\nResult (per run)\n", "h2"))
        segs.append((f"  Total cost / run : {n(r.total_cost)} ISK\n", None))
        segs.append((f"  Profit / run     : {n(r.profit)} ISK\n", None))
        segs.append((f"  ISK per LP       : {n(r.isk_per_lp)}\n", None))

        if self.available_lp is not None and r.lp_cost and r.max_runs > 0:
            runs = r.max_runs
            leftover = self.available_lp - r.lp_cost * runs
            segs.append((f"\nTo withdraw ALL {self.available_lp:,} LP  "
                         f"({runs:,} runs)\n", "h1"))
            if r.required_items:
                segs.append(("  Total items you must buy:\n", "h2"))
                for ri in r.required_items:
                    flag = "" if ri.priced else "   [no Jita price]"
                    segs.append((f"   {ri.quantity * runs:>7,} x  ", None))
                    segs.append((ri.name, None, ri.name))  # clickable -> copy
                    segs.append(("\n", None))
                    segs.append((f"             = {n(ri.total_cost * runs)} ISK{flag}\n",
                                 None if ri.priced else "warn"))
                segs.append((f"  Items total : {n(r.required_cost * runs)} ISK\n", "h2"))
            else:
                segs.append(("  Items to buy : none (pure LP + ISK)\n", None))
            segs.append((f"  LP spent     : {r.lp_cost * runs:,} LP  "
                         f"(leftover {leftover:,})\n", None))
            segs.append((f"  ISK outlay   : {n(r.total_cost * runs)} ISK\n", None))
            segs.append((f"  Net profit   : {n(r.total_profit)} ISK\n", "h2"))
        elif self.available_lp is not None and r.lp_cost:
            segs.append(("\n  Not enough LP for a single run of this offer.\n", "warn"))

        if not r.priced:
            segs.append(("\n⚠ Some part of this offer has no Jita price; treat "
                         "the numbers as incomplete.\n", "warn"))
        self._set_detail(segs)

    def _set_detail(self, segments) -> None:
        """Render the detail pane. Each segment is (text, style_tag[, copy_value]);
        when copy_value is given the text becomes a clickable copy-to-clipboard link."""
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        for t in self.detail.tag_names():       # clear last render's link tags
            if t.startswith("copy-"):
                self.detail.tag_delete(t)
        link_i = 0
        for seg in segments:
            text = seg[0]
            style = seg[1] if len(seg) > 1 else None
            copy_value = seg[2] if len(seg) > 2 else None
            tags = []
            if style:
                tags.append(style)
            if copy_value is not None:
                link_tag = f"copy-{link_i}"
                link_i += 1
                tags.extend(("copyable", link_tag))
                self.detail.tag_bind(
                    link_tag, "<Button-1>",
                    lambda _e, val=copy_value: self._copy_text(val))
            self.detail.insert("end", text, tuple(tags))
        self.detail.configure(state="disabled")

    def _copy_text(self, value: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(value)
        self.root.update()  # keep the clipboard contents after focus changes
        self._set_status(f"Copied: {value}")

    def _set_status(self, text: str) -> None:
        self.status_var.set(text)


def _enable_hidpi() -> None:
    """Declare the process DPI-aware on Windows so Tk renders crisply on
    4K/HiDPI screens instead of being bitmap-stretched (which looks blurry)."""
    if sys.platform != "win32":
        return
    import ctypes
    user32 = ctypes.windll.user32
    try:  # Per-Monitor v2 (Windows 10 1703+): sharpest
        user32.SetProcessDpiAwarenessContext.restype = ctypes.c_bool
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:  # Per-Monitor (Windows 8.1+)
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except Exception:
        pass
    try:  # System DPI aware (Vista+)
        user32.SetProcessDPIAware()
    except Exception:
        pass


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Interactive LP -> ISK optimizer (Tkinter UI).")
    parser.add_argument("--selftest", action="store_true",
                        help="Build the window and close it immediately (smoke test).")
    args = parser.parse_args(argv)

    _enable_hidpi()
    root = tk.Tk()
    App(root)
    if args.selftest:
        root.after(500, root.destroy)
        root.mainloop()
        print("selftest ok")
        return 0
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
