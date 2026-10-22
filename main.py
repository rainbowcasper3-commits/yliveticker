# -*- coding: utf-8 -*-
"""
main.py - Yahoo Finance Live Ticker cu comenzi interactive.

Comenzi disponibile in consola:
  find_ticker <query>        - cauta tickers dupa simbol sau denumire companie
  add_ticker_<SIMBOL>        - adauga un ticker la lista urmarita live
  list_tickers               - afiseaza tickerele urmarite curent
  remove_ticker_<SIMBOL>     - elimina un ticker din lista activa
  help                       - afiseaza toate comenzile disponibile
  quit / exit                - opreste aplicatia
"""

import sys
import io
import threading
import time
from datetime import datetime

# Fortam UTF-8 pe stdout pentru compatibilitate Windows
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf-8-sig"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

import yliveticker
from ticker_search import find_ticker, add_ticker, print_search_results, get_ticker_price


# --- State global partajat ----------------------------------------------------
# Lista curenta de tickers urmariti (modificata dinamic)
active_tickers: list[str] = ["BTC-USD", "AAPL", "EURUSD=X", "TSLA"]

# Obiectul YLiveTicker curent (reinceput cand lista se schimba)
_ws_instance = None
_ws_lock  = threading.Lock()
_stop_evt = threading.Event()

# Ultimele date primite live, indexate dupa simbol
_last_data: dict = {}
_data_lock = threading.Lock()


# --- Callback WebSocket -------------------------------------------------------
def on_ticker(ws, msg: dict) -> None:
    """Primit la fiecare actualizare WebSocket de la Yahoo Finance."""
    symbol = msg.get("id", "N/A")
    price  = msg.get("price")
    change = msg.get("change")
    cp     = msg.get("changePercent")
    volume = msg.get("dayVolume")
    ts     = msg.get("timestamp")

    with _data_lock:
        _last_data[symbol] = msg

    time_str = (
        datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
        if ts else datetime.now().strftime("%H:%M:%S")
    )

    if change is not None and change > 0:
        arrow, sign = "^", "+"
    elif change is not None and change < 0:
        arrow, sign = "v", ""
    else:
        arrow, sign = " ", ""

    change_str = (
        f"{arrow} {sign}{change:.2f} ({sign}{cp:.2f}%)"
        if change is not None and cp is not None
        else "N/A"
    )
    vol_str = f"{int(volume):,}" if volume else "N/A"

    print(
        f"\r[{time_str}] {symbol:<10} Pret: {price:<12}  "
        f"Schimbare: {change_str:<24} Volum: {vol_str}"
    )


# --- Thread WebSocket ---------------------------------------------------------
def _ws_thread_func() -> None:
    """Ruleaza WebSocket-ul intr-un thread separat; reincepe la schimbare lista."""
    global _ws_instance
    while not _stop_evt.is_set():
        with _ws_lock:
            tickers = list(active_tickers)

        if not tickers:
            time.sleep(2)
            continue

        try:
            inst = yliveticker.YLiveTicker(
                on_ticker=on_ticker,
                ticker_names=tickers,
                reconnect=5,
                ping_interval=15,
                ping_timeout=10,
            )
            with _ws_lock:
                _ws_instance = inst
        except Exception as e:
            print(f"\n[WS EROARE] {e}")
            time.sleep(3)


def _restart_ws() -> None:
    """Inchide conexiunea curenta; thread-ul o va redeschide cu lista actualizata."""
    with _ws_lock:
        if _ws_instance:
            try:
                _ws_instance.ws.close()
            except Exception:
                pass


# --- Comenzi ------------------------------------------------------------------
def cmd_find_ticker(args: str) -> None:
    """find_ticker <query> - cauta tickers dupa simbol sau denumire companie."""
    query = args.strip()
    if not query:
        print("  Folosire: find_ticker <simbol sau denumire>")
        print("  Exemplu:  find_ticker Apple")
        print("  Exemplu:  find_ticker BTC")
        return

    print(f"\n  ... Caut tickers pentru: '{query}' ...")
    results = find_ticker(query)
    print_search_results(results)

    global _last_search_results
    _last_search_results = results


def cmd_add_ticker(symbol: str) -> None:
    """add_ticker_<SIMBOL> - adauga ticker-ul la lista activa si reconecteaza."""
    symbol = symbol.upper().strip()
    if not symbol:
        print("  Folosire: add_ticker_<SIMBOL>   (ex: add_ticker_AAPL)")
        return

    print(f"  ... Verificare simbol '{symbol}' pe Yahoo Finance ...")
    price_data = get_ticker_price(symbol)
    if price_data["price"] is None:
        print(f"  [X] Simbolul '{symbol}' nu a putut fi verificat sau nu exista.")
        print(f"      Folositi 'find_ticker {symbol}' pentru a verifica simbolul corect.")
        return

    was_added = add_ticker(symbol, active_tickers)
    if not was_added:
        print(f"  [!] {symbol} este deja in lista activa.")
        return

    price = price_data["price"]
    cp    = price_data.get("changePercent")
    cur   = price_data.get("currency", "")
    cp_str = f" ({cp:+.2f}%)" if cp is not None else ""
    print(f"  [OK] {symbol} adaugat! Pret curent: {price:,.2f} {cur}{cp_str}")
    print(f"  --> Lista actualizata: {', '.join(active_tickers)}")
    print(f"  ... Reconectare la stream WebSocket ...")
    _restart_ws()


def cmd_remove_ticker(symbol: str) -> None:
    """remove_ticker_<SIMBOL> - elimina un ticker din lista activa."""
    symbol = symbol.upper().strip()
    if symbol in [t.upper() for t in active_tickers]:
        active_tickers[:] = [t for t in active_tickers if t.upper() != symbol]
        print(f"  [OK] {symbol} eliminat din lista activa.")
        print(f"  --> Lista actualizata: {', '.join(active_tickers) or '(goala)'}")
        if active_tickers:
            _restart_ws()
        else:
            print("  [!] Lista este goala. Adauga un ticker cu add_ticker_<SIMBOL>.")
    else:
        print(f"  [X] {symbol} nu se afla in lista activa.")
        print(f"  --> Tickers activi: {', '.join(active_tickers)}")


def cmd_list_tickers() -> None:
    """list_tickers - afiseaza tickerele urmarite curent si pretul lor live."""
    print(f"\n  {'Ticker':<12} {'Pret':<14} {'Schimbare':<26} {'Volum'}")
    print(f"  {'-'*62}")
    with _data_lock:
        for symbol in active_tickers:
            d = _last_data.get(symbol)
            if d:
                p  = d.get("price", 0) or 0
                c  = d.get("change", 0) or 0
                cp = d.get("changePercent", 0) or 0
                v  = d.get("dayVolume")
                arrow = "^" if c >= 0 else "v"
                sign  = "+" if c >= 0 else ""
                vol_str = f"{int(v):,}" if v else "N/A"
                print(f"  {symbol:<12} {p:<14,.2f} {arrow} {sign}{c:.2f} ({sign}{cp:.2f}%)   {vol_str}")
            else:
                print(f"  {symbol:<12} (in asteptare...)")
    print()


def cmd_help() -> None:
    """Afiseaza toate comenzile disponibile."""
    print("""
  +--------------------------------------------------------------+
  |       Yahoo Finance Live Ticker - Comenzi disponibile        |
  +--------------------------------------------------------------+
  |  find_ticker <query>       Cauta tickers dupa simbol/firma   |
  |    ex: find_ticker Apple                                      |
  |    ex: find_ticker BTC                                        |
  |    ex: find_ticker Tesla                                      |
  |                                                               |
  |  add_ticker_<SIMBOL>       Adauga ticker la stream live       |
  |    ex: add_ticker_AAPL                                        |
  |    ex: add_ticker_BTC-USD                                     |
  |    ex: add_ticker_NVDA                                        |
  |                                                               |
  |  remove_ticker_<SIMBOL>    Elimina ticker din stream          |
  |    ex: remove_ticker_TSLA                                     |
  |                                                               |
  |  list_tickers              Afiseaza tickerele active + preturi|
  |  help                      Afiseaza acest meniu               |
  |  quit / exit               Opreste aplicatia                  |
  +--------------------------------------------------------------+
""")


# --- Bucla de comenzi interactiva --------------------------------------------
def command_loop() -> None:
    """
    Ruleaza in thread principal: citeste comenzi de la utilizator si le executa.
    WebSocket-ul ruleaza in background pe un thread separat.
    """
    global _last_search_results
    _last_search_results = []

    # Pauza scurta sa apara primul mesaj WS inainte de prompt
    time.sleep(1.0)
    cmd_help()

    while not _stop_evt.is_set():
        try:
            raw = input("\n>>> ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not raw:
            continue

        lower = raw.lower()

        # find_ticker ----------------------------------------------------------
        if lower.startswith("find_ticker"):
            args = raw[len("find_ticker"):].strip()
            cmd_find_ticker(args)

        # add_ticker_SYMBOL ----------------------------------------------------
        elif lower.startswith("add_ticker_"):
            symbol = raw[len("add_ticker_"):]
            cmd_add_ticker(symbol)

        # remove_ticker_SYMBOL ------------------------------------------------
        elif lower.startswith("remove_ticker_"):
            symbol = raw[len("remove_ticker_"):]
            cmd_remove_ticker(symbol)

        # list_tickers ---------------------------------------------------------
        elif lower == "list_tickers":
            cmd_list_tickers()

        # help -----------------------------------------------------------------
        elif lower in ("help", "?", "h"):
            cmd_help()

        # quit / exit ----------------------------------------------------------
        elif lower in ("quit", "exit", "q"):
            break

        else:
            print(f"  [?] Comanda necunoscuta: '{raw}'")
            print("      Tastati 'help' pentru lista de comenzi.")

    _stop_evt.set()
    _restart_ws()
    print("\n  Sesiune inchisa. La revedere!\n")


# --- Entry point --------------------------------------------------------------
def main() -> None:
    print("=" * 65)
    print("  Yahoo Finance Live Ticker")
    print(f"  Tickers activi: {', '.join(active_tickers)}")
    print("  Tastati 'help' pentru lista de comenzi.")
    print("=" * 65)

    # Pornim WebSocket pe un thread de fundal
    ws_thread = threading.Thread(target=_ws_thread_func, daemon=True)
    ws_thread.start()

    # Bucla de comenzi ruleaza in thread-ul principal
    try:
        command_loop()
    except KeyboardInterrupt:
        pass
    finally:
        _stop_evt.set()
        _restart_ws()
        sys.exit(0)


if __name__ == "__main__":
    main()
