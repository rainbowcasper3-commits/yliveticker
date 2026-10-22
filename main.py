# -*- coding: utf-8 -*-
"""
main.py  -  Yahoo! Finance Live Ticker  (interactive dashboard)

Controls:
  [M]  Open ticker menu (find / add / remove / browse)
  [F]  Filter active tickers on the dashboard
  [R]  Reset filter
  [Ctrl+C]  Quit
"""

import sys
import io
import threading
import time
import msvcrt
from datetime import datetime
from collections import deque

# Force UTF-8 output on Windows
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from rich.console import Console, Group
from rich.table import Table
from rich.live import Live
from rich.panel import Panel
from rich.text import Text
from rich.align import Align
from rich.rule import Rule
from rich import box

import yliveticker
from ticker_search import find_ticker, add_ticker, get_ticker_price

console = Console()

# ─────────────────────────────────────────────────────────────────────────────
#  Shared state
# ─────────────────────────────────────────────────────────────────────────────
active_tickers: list = ["BTC-USD", "AAPL", "EURUSD=X", "TSLA"]
ticker_data: dict = {}          # symbol -> live data dict
data_lock    = threading.Lock()
stop_event   = threading.Event()
ws_instance  = None
ws_lock      = threading.Lock()
update_count = 0
connected    = False
dash_filter  = ""               # live filter string shown on dashboard


# ─────────────────────────────────────────────────────────────────────────────
#  WebSocket layer
# ─────────────────────────────────────────────────────────────────────────────
def _on_ticker(ws, msg: dict) -> None:
    global update_count, connected
    symbol = msg.get("id", "")
    if not symbol:
        return

    with data_lock:
        if symbol not in ticker_data:
            ticker_data[symbol] = {
                "price":         None,
                "prev_price":    None,
                "change":        None,
                "changePercent": None,
                "dayHigh":       None,
                "dayLow":        None,
                "volume":        None,
                "openPrice":     None,
                "exchange":      msg.get("exchange", ""),
                "history":       deque(maxlen=20),
                "last_update":   None,
                "flash":         None,   # "up" | "down" | None
            }

        d = ticker_data[symbol]
        prev = d["price"]
        new  = msg.get("price")

        d["prev_price"]    = prev
        d["price"]         = new
        d["change"]        = msg.get("change")
        d["changePercent"] = msg.get("changePercent")
        d["dayHigh"]       = msg.get("dayHigh")
        d["dayLow"]        = msg.get("dayLow")
        d["volume"]        = msg.get("dayVolume")
        d["openPrice"]     = msg.get("openPrice")
        d["last_update"]   = datetime.now().strftime("%H:%M:%S")

        if new is not None and prev is not None:
            d["flash"] = "up" if new >= prev else "down"

        if new is not None:
            d["history"].append(new)

        update_count += 1
        connected = True


def _ws_thread() -> None:
    global ws_instance, connected
    while not stop_event.is_set():
        with ws_lock:
            tickers = list(active_tickers)
        if not tickers:
            time.sleep(1)
            continue
        try:
            connected = False
            inst = yliveticker.YLiveTicker(
                on_ticker=_on_ticker,
                ticker_names=tickers,
                reconnect=5,
                ping_interval=15,
                ping_timeout=10,
            )
            with ws_lock:
                ws_instance = inst
        except Exception:
            time.sleep(3)


def _restart_ws() -> None:
    global connected
    connected = False
    with ws_lock:
        if ws_instance:
            try:
                ws_instance.ws.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
#  Formatting helpers
# ─────────────────────────────────────────────────────────────────────────────
def _sparkline(history) -> str:
    chars = " ▂▃▄▅▆▇█"
    h = list(history)
    if len(h) < 2:
        return " " * 12
    lo, hi = min(h), max(h)
    if lo == hi:
        return "▄" * 12
    out = ""
    for v in h[-12:]:
        idx = int((v - lo) / (hi - lo) * (len(chars) - 1))
        out += chars[idx]
    return out.ljust(12)


def _fmt_price(val) -> Text:
    if val is None:
        return Text("          ---", style="dim")
    s = f"{val:>14,.4f}" if val < 1.0 else f"{val:>14,.2f}"
    return Text(s, style="bold white")


def _fmt_change(change, pct) -> Text:
    if change is None or pct is None:
        return Text("                 ---", style="dim")
    sign  = "+" if change >= 0 else ""
    arrow = "▲" if change >= 0 else "▼"
    style = "bold bright_green" if change >= 0 else "bold bright_red"
    return Text(f"{arrow} {sign}{change:,.2f}  ({sign}{pct:.2f}%)", style=style)


def _fmt_vol(vol) -> Text:
    if vol is None:
        return Text("---", style="dim")
    if vol >= 1_000_000_000:
        return Text(f"{vol / 1_000_000_000:.2f}B", style="cyan")
    if vol >= 1_000_000:
        return Text(f"{vol / 1_000_000:.2f}M", style="cyan")
    return Text(f"{vol:,.0f}", style="cyan")


def _fmt_scalar(val, decimals=2) -> Text:
    if val is None:
        return Text("---", style="dim")
    return Text(f"{val:,.{decimals}f}", style="dim white")


# ─────────────────────────────────────────────────────────────────────────────
#  Dashboard layout builder
# ─────────────────────────────────────────────────────────────────────────────
def _build_dashboard() -> Group:
    now = datetime.now().strftime("%Y-%m-%d   %H:%M:%S")

    # ── Header ────────────────────────────────────────────────────────────────
    filter_hint = f"   [Filter: [yellow]{dash_filter}[/yellow]]" if dash_filter else ""
    header = Panel(
        Align.center(
            Text.assemble(
                ("Yahoo! Finance  Live Ticker", "bold cyan"),
                (f"   |   {now}", "white"),
            )
        ),
        subtitle=filter_hint if filter_hint else None,
        border_style="steel_blue1",
        height=3,
    )

    # ── Data table ────────────────────────────────────────────────────────────
    table = Table(
        show_header=True,
        header_style="bold white on grey23",
        border_style="grey42",
        box=box.SIMPLE_HEAVY,
        show_lines=True,        # <── row separators = database look
        expand=True,
        padding=(0, 1),
    )

    table.add_column("Symbol",      style="bold yellow",   min_width=10, no_wrap=True)
    table.add_column("Price",       justify="right",       min_width=16, no_wrap=True)
    table.add_column("Change",      justify="right",       min_width=22, no_wrap=True)
    table.add_column("High",        justify="right",       min_width=11, no_wrap=True)
    table.add_column("Low",         justify="right",       min_width=11, no_wrap=True)
    table.add_column("Open",        justify="right",       min_width=11, no_wrap=True)
    table.add_column("Volume",      justify="right",       min_width=10, no_wrap=True)
    table.add_column("Trend",       justify="center",      min_width=14, no_wrap=True)
    table.add_column("Updated",     justify="center",      min_width=10, no_wrap=True)

    with data_lock:
        visible = [
            t for t in active_tickers
            if dash_filter.upper() in t.upper()
        ]

    with data_lock:
        for symbol in visible:
            d = ticker_data.get(symbol)

            if not d or d["price"] is None:
                table.add_row(
                    Text(symbol, style="bold yellow"),
                    Text("     waiting...", style="dim"),
                    Text("---", style="dim"),
                    Text("---", style="dim"),
                    Text("---", style="dim"),
                    Text("---", style="dim"),
                    Text("---", style="dim"),
                    Text("", style="dim"),
                    Text("---", style="dim"),
                )
                continue

            # Price cell — flashes green / red on tick
            price_t = _fmt_price(d["price"])
            if d["flash"] == "up":
                price_t.stylize("bold bright_green")
            elif d["flash"] == "down":
                price_t.stylize("bold bright_red")

            spark_style = "green" if (d["change"] or 0) >= 0 else "red"

            table.add_row(
                Text(symbol, style="bold yellow"),
                price_t,
                _fmt_change(d["change"], d["changePercent"]),
                _fmt_scalar(d["dayHigh"]),
                _fmt_scalar(d["dayLow"]),
                _fmt_scalar(d["openPrice"]),
                _fmt_vol(d["volume"]),
                Text(_sparkline(d["history"]), style=spark_style),
                Text(d["last_update"] or "---", style="dim cyan"),
            )

    # ── Footer ────────────────────────────────────────────────────────────────
    conn_style = "bold bright_green" if connected else "bold yellow"
    conn_str   = "● Connected" if connected else "○ Connecting..."
    footer = Panel(
        Align.center(Text.assemble(
            ("Status: ",     "white"),
            (conn_str,       conn_style),
            (f"   Tickers: {len(active_tickers)}",  "cyan"),
            (f"   Updates: {update_count}",          "cyan"),
            ("     [M] Menu   [F] Filter   [R] Reset filter   [Ctrl+C] Quit",
             "dim magenta"),
        )),
        border_style="steel_blue1",
        height=3,
    )

    return Group(header, table, footer)


# ─────────────────────────────────────────────────────────────────────────────
#  Ticker-menu helpers  (run while Live is stopped)
# ─────────────────────────────────────────────────────────────────────────────
def _search_results_table(results: list) -> Table:
    """Build a Rich table from find_ticker() results."""
    t = Table(
        show_header=True,
        header_style="bold white on grey23",
        border_style="grey42",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
        expand=True,
        padding=(0, 1),
    )
    t.add_column("No.",      width=4,  justify="right")
    t.add_column("Symbol",   min_width=10, style="bold yellow")
    t.add_column("Name",     min_width=28)
    t.add_column("Type",     min_width=8)
    t.add_column("Exchange", min_width=8)
    t.add_column("Price",    min_width=14, justify="right")
    t.add_column("Change",   min_width=20, justify="right")
    t.add_column("High",     min_width=10, justify="right")
    t.add_column("Low",      min_width=10, justify="right")

    for i, r in enumerate(results, 1):
        p   = r.get("price")
        c   = r.get("change")
        cp  = r.get("changePercent")
        hi  = r.get("dayHigh")
        lo  = r.get("dayLow")
        cur = r.get("currency", "")

        p_str  = f"{p:,.2f} {cur}" if p is not None else "---"
        hi_str = f"{hi:,.2f}"      if hi is not None else "---"
        lo_str = f"{lo:,.2f}"      if lo is not None else "---"

        if c is not None and cp is not None:
            sign  = "+" if c >= 0 else ""
            arrow = "▲" if c >= 0 else "▼"
            c_text = Text(f"{arrow} {sign}{c:.2f} ({sign}{cp:.2f}%)",
                          style="bright_green" if c >= 0 else "bright_red")
        else:
            c_text = Text("---", style="dim")

        t.add_row(str(i), r["symbol"], r["name"][:30],
                  r["type"], r["exchange"][:10],
                  p_str, c_text, hi_str, lo_str)

    return t


def _active_tickers_table(filter_str: str = "") -> Table:
    """Build a Rich table from the current active tickers."""
    t = Table(
        show_header=True,
        header_style="bold white on grey23",
        border_style="grey42",
        box=box.SIMPLE_HEAVY,
        show_lines=True,
        expand=True,
        padding=(0, 1),
    )
    t.add_column("No.",      width=4,  justify="right")
    t.add_column("Symbol",   min_width=12, style="bold yellow")
    t.add_column("Price",    min_width=16, justify="right")
    t.add_column("Change",   min_width=22, justify="right")
    t.add_column("High",     min_width=11, justify="right")
    t.add_column("Low",      min_width=11, justify="right")
    t.add_column("Volume",   min_width=10, justify="right")
    t.add_column("Updated",  min_width=10, justify="center")

    visible = (
        [tk for tk in active_tickers if filter_str.upper() in tk.upper()]
        if filter_str else list(active_tickers)
    )

    with data_lock:
        for i, symbol in enumerate(visible, 1):
            d = ticker_data.get(symbol)
            if d and d["price"] is not None:
                p  = d["price"]
                c  = d["change"]
                cp = d["changePercent"]
                sign  = "+" if (c or 0) >= 0 else ""
                arrow = "▲" if (c or 0) >= 0 else "▼"
                c_str = (f"{arrow} {sign}{c:.2f} ({sign}{cp:.2f}%)"
                         if c is not None and cp is not None else "---")
                c_style = "bright_green" if (c or 0) >= 0 else "bright_red"

                t.add_row(
                    str(i), symbol,
                    f"{p:,.2f}",
                    Text(c_str, style=c_style),
                    f"{d['dayHigh']:,.2f}"  if d["dayHigh"]  else "---",
                    f"{d['dayLow']:,.2f}"   if d["dayLow"]   else "---",
                    _fmt_vol(d["volume"]).plain,
                    d["last_update"] or "---",
                )
            else:
                t.add_row(str(i), symbol,
                          "waiting...", "---", "---", "---", "---", "---")

    return t


def _do_add_ticker(symbol: str) -> None:
    """Verify on Yahoo Finance then add to active list."""
    console.print(f"  [dim]Verifying '{symbol}' on Yahoo Finance...[/dim]")
    price_data = get_ticker_price(symbol)
    if price_data["price"] is None:
        console.print(f"  [bold red][X][/bold red] '{symbol}' not found or has no price data.")
        console.print( "      Use [cyan]Find & Add Ticker[/cyan] to search for the correct symbol.")
        return

    was_added = add_ticker(symbol, active_tickers)
    if not was_added:
        console.print(f"  [yellow][!] {symbol} is already in the active list.[/yellow]")
        return

    p   = price_data["price"]
    cp  = price_data.get("changePercent")
    cur = price_data.get("currency", "")
    cp_str = f" ({cp:+.2f}%)" if cp is not None else ""
    console.print(
        f"  [bold green][OK][/bold green] [bold yellow]{symbol}[/bold yellow] added!  "
        f"Current price: [bold white]{p:,.2f} {cur}[/bold white]{cp_str}"
    )
    console.print(
        f"  Active tickers: [yellow]{', '.join(active_tickers)}[/yellow]"
    )
    console.print("  [dim]Reconnecting stream...[/dim]")
    _restart_ws()


# ─────────────────────────────────────────────────────────────────────────────
#  Sub-menu screens
# ─────────────────────────────────────────────────────────────────────────────
def _menu_find_add() -> None:
    console.print(Rule("[bold cyan]Find & Add Ticker  (Yahoo Finance search)[/bold cyan]",
                        style="steel_blue1"))
    query = console.input("\n  Enter symbol or company name: ").strip()
    if not query:
        return

    console.print(f"  [dim]Searching for '{query}'...[/dim]")
    results = find_ticker(query, max_results=8)

    if not results:
        console.print("  [red]No results found.[/red]")
        return

    console.print(_search_results_table(results))
    console.print(
        "\n  Type a [bold]number[/bold] to select from the list above,  "
        "or type a [bold]symbol[/bold] directly,  or press [bold]Enter[/bold] to cancel."
    )
    choice = console.input("  Add: ").strip()

    if not choice:
        return

    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(results):
            _do_add_ticker(results[idx]["symbol"])
        else:
            console.print("  [red]Number out of range.[/red]")
    else:
        _do_add_ticker(choice.upper())


def _menu_add_direct() -> None:
    console.print(Rule("[bold cyan]Add Ticker by Symbol[/bold cyan]",
                        style="steel_blue1"))
    symbol = console.input("\n  Symbol (e.g. AAPL, BTC-USD, NVDA): ").strip().upper()
    if symbol:
        _do_add_ticker(symbol)


def _menu_remove() -> None:
    console.print(Rule("[bold cyan]Remove Ticker[/bold cyan]",
                        style="steel_blue1"))
    console.print(
        f"\n  Active tickers: [yellow]{', '.join(active_tickers)}[/yellow]\n"
    )
    symbol = console.input("  Symbol to remove (or Enter to cancel): ").strip().upper()
    if not symbol:
        return

    if symbol in [t.upper() for t in active_tickers]:
        active_tickers[:] = [t for t in active_tickers if t.upper() != symbol]
        console.print(f"  [green][OK][/green] [yellow]{symbol}[/yellow] removed.")
        console.print(
            f"  Active: [yellow]{', '.join(active_tickers) or '(empty)'}[/yellow]"
        )
        if active_tickers:
            _restart_ws()
        else:
            console.print(
                "  [yellow][!] List is empty — add a ticker with option 1 or 2.[/yellow]"
            )
    else:
        console.print(f"  [red]{symbol} is not in the active list.[/red]")


def _menu_browse() -> None:
    console.print(Rule("[bold cyan]Browse Active Tickers[/bold cyan]",
                        style="steel_blue1"))
    console.print(
        f"\n  You have [bold]{len(active_tickers)}[/bold] active ticker(s).  "
        "Type a name to filter, or press [bold]Enter[/bold] to show all.\n"
    )
    search = console.input("  Filter: ").strip()

    visible_count = (
        len([t for t in active_tickers if search.upper() in t.upper()])
        if search else len(active_tickers)
    )

    console.print(_active_tickers_table(search))

    if search:
        console.print(
            f"\n  Showing [bold]{visible_count}[/bold] of "
            f"[bold]{len(active_tickers)}[/bold] tickers  "
            f"[dim](filter: '{search}')[/dim]"
        )


def _show_menu(live: Live) -> None:
    """Pause Live, run the interactive menu, then resume."""
    live.stop()
    console.clear()

    console.print(Panel.fit(
        "[bold cyan]Yahoo! Finance Live Ticker  —  Ticker Menu[/bold cyan]",
        border_style="steel_blue1",
        padding=(0, 4),
    ))
    console.print("""
  [bold white]1.[/bold white]  [cyan]Find & Add Ticker[/cyan]      — search Yahoo Finance by name or symbol
  [bold white]2.[/bold white]  [cyan]Add Ticker[/cyan]             — add directly by symbol
  [bold white]3.[/bold white]  [cyan]Remove Ticker[/cyan]          — remove from active list
  [bold white]4.[/bold white]  [cyan]Browse Active Tickers[/cyan]  — view / search within your list
  [bold white]5.[/bold white]  [cyan]Back to Dashboard[/cyan]      — return to live view
""")
    choice = console.input("  [bold]Select (1–5): [/bold]").strip()

    if choice == "1":
        _menu_find_add()
    elif choice == "2":
        _menu_add_direct()
    elif choice == "3":
        _menu_remove()
    elif choice == "4":
        _menu_browse()
    elif choice in ("5", ""):
        pass
    else:
        console.print(f"  [red]Unknown option '{choice}'[/red]")

    console.input("\n  [dim]Press Enter to return to the dashboard...[/dim]")
    console.clear()
    live.start()


def _show_filter(live: Live) -> None:
    """Pause Live, set dash_filter, resume."""
    global dash_filter
    live.stop()
    f = console.input(
        "\n  [bold]Dashboard filter[/bold]  "
        "(type a ticker name to filter, or Enter to show all): "
    ).strip()
    dash_filter = f
    live.start()


# ─────────────────────────────────────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────────────────────────────────────
def main() -> None:
    console.print("[bold cyan]Starting Yahoo! Finance Live Ticker...[/bold cyan]")

    wst = threading.Thread(target=_ws_thread, daemon=True)
    wst.start()

    with Live(
        _build_dashboard(),
        console=console,
        screen=True,
        refresh_per_second=2,
    ) as live:
        try:
            while not stop_event.is_set():
                live.update(_build_dashboard())

                # Non-blocking keypress check (Windows)
                if msvcrt.kbhit():
                    key = msvcrt.getwch().lower()
                    if key == "m":
                        _show_menu(live)
                    elif key == "f":
                        _show_filter(live)
                    elif key == "r":
                        global dash_filter
                        dash_filter = ""
                    elif key == "\x03":    # Ctrl+C
                        break

                time.sleep(0.25)

        except KeyboardInterrupt:
            pass

    stop_event.set()
    _restart_ws()
    console.print("\n[cyan]Session closed. Goodbye![/cyan]\n")


if __name__ == "__main__":
    main()
