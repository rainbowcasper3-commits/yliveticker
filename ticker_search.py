"""
ticker_search.py — Modul de căutare și gestionare tickers Yahoo Finance.

Funcții principale:
  - find_ticker(query)  : caută tickers după simbol sau denumire companie
  - get_ticker_price(symbol) : preia date live de preț pentru un ticker
  - add_ticker(symbol, ticker_list) : adaugă un ticker la lista activă
"""

import json
import urllib.request
import urllib.parse
from datetime import datetime


# ─── Constante API Yahoo Finance ──────────────────────────────────────────────
SEARCH_URL = "https://query1.finance.yahoo.com/v1/finance/search"
CHART_URL  = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
HEADERS    = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
TIMEOUT    = 10  # secunde


# ─── Utilitar HTTP ─────────────────────────────────────────────────────────────
def _get_json(url: str) -> dict | None:
    """Efectuează un GET la URL și returnează JSON-ul parsat, sau None la eroare."""
    try:
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[EROARE] Cerere HTTP eșuată: {e}")
        return None


# ─── Căutare tickers ───────────────────────────────────────────────────────────
def find_ticker(query: str, max_results: int = 8) -> list[dict]:
    """
    Caută tickers pe Yahoo Finance după simbol sau denumire companie.

    Args:
        query:       Textul de căutat (ex: 'Apple', 'AAPL', 'Bitcoin')
        max_results: Numărul maxim de rezultate returnate (implicit 8)

    Returns:
        Listă de dicționare cu informații despre fiecare ticker găsit.
        Fiecare dicționar conține cheile:
          symbol, name, type, exchange, sector, industry, currency, price,
          change, changePercent, dayHigh, dayLow, volume
    """
    params = urllib.parse.urlencode({
        "q": query,
        "quotesCount": max_results,
        "newsCount": 0,
        "enableFuzzyQuery": "true",
        "quotesQueryId": "tss_match_phrase_query",
    })
    data = _get_json(f"{SEARCH_URL}?{params}")
    if not data:
        return []

    quotes = data.get("quotes", [])
    results = []

    for q in quotes:
        if not q.get("isYahooFinance"):
            continue
        symbol = q.get("symbol", "")
        result = {
            "symbol":   symbol,
            "name":     q.get("longname") or q.get("shortname", "N/A"),
            "type":     q.get("typeDisp", "N/A"),
            "exchange": q.get("exchDisp", q.get("exchange", "N/A")),
            "sector":   q.get("sectorDisp", ""),
            "industry": q.get("industryDisp", ""),
        }
        # Preia prețul curent pentru fiecare simbol găsit
        price_data = get_ticker_price(symbol)
        result.update(price_data)
        results.append(result)

    return results


# ─── Preț curent ──────────────────────────────────────────────────────────────
def get_ticker_price(symbol: str) -> dict:
    """
    Preia datele de preț actuale pentru un simbol de pe Yahoo Finance.

    Args:
        symbol: Simbolul tickerului (ex: 'AAPL', 'BTC-USD')

    Returns:
        Dicționar cu: price, change, changePercent, dayHigh, dayLow,
                      volume, currency, marketState
    """
    url  = CHART_URL.format(symbol=urllib.parse.quote(symbol))
    url += "?interval=1d&range=1d"
    data = _get_json(url)

    empty = {
        "price": None, "change": None, "changePercent": None,
        "dayHigh": None, "dayLow": None, "volume": None,
        "currency": "N/A", "marketState": "N/A",
    }

    if not data:
        return empty

    try:
        meta = data["chart"]["result"][0]["meta"]
        return {
            "price":         meta.get("regularMarketPrice"),
            "change":        meta.get("regularMarketChange"),
            "changePercent": meta.get("regularMarketChangePercent"),
            "dayHigh":       meta.get("regularMarketDayHigh"),
            "dayLow":        meta.get("regularMarketDayLow"),
            "volume":        meta.get("regularMarketVolume"),
            "currency":      meta.get("currency", "N/A"),
            "marketState":   meta.get("marketState", "N/A"),
        }
    except (KeyError, IndexError, TypeError):
        return empty


# ─── Adăugare ticker la lista activă ─────────────────────────────────────────
def add_ticker(symbol: str, ticker_list: list[str]) -> bool:
    """
    Adaugă un ticker la lista activă dacă nu există deja.

    Args:
        symbol:      Simbolul tickerului de adăugat (ex: 'AAPL')
        ticker_list: Lista curentă de tickers urmărite (modificată in-place)

    Returns:
        True dacă a fost adăugat, False dacă exista deja.
    """
    symbol = symbol.upper().strip()
    if symbol in [t.upper() for t in ticker_list]:
        return False   # deja există
    ticker_list.append(symbol)
    return True


# --- Afisare rezultate cautare ------------------------------------------------
def print_search_results(results: list[dict]) -> None:
    """Afiseaza rezultatele cautarii formatate in consola."""
    if not results:
        print("  [X] Nu au fost gasite rezultate.")
        return

    sep = "-" * 72
    print(f"\n  {'Nr':<4} {'Simbol':<10} {'Denumire':<30} {'Tip':<10} {'Bursa':<8}")
    print(f"  {sep}")

    for i, r in enumerate(results, 1):
        price_str = _format_price(r)
        change_str = _format_change(r)
        sector_str = (
            f"  Sector: {r['sector']} / {r['industry']}" if r.get("sector") else ""
        )
        hi_lo = _format_hi_lo(r)

        print(f"  [{i:<2}] {r['symbol']:<10} {r['name'][:28]:<30} {r['type']:<10} {r['exchange']:<8}")
        print(f"       Pret: {price_str}  Schimbare: {change_str}  {hi_lo}")
        if sector_str:
            print(f"  {sector_str}")
        print()

    print("  -> Adauga un ticker cu comanda: add_ticker_<SIMBOL>")
    print("     Exemplu: add_ticker_AAPL\n")


def _format_price(r: dict) -> str:
    p = r.get("price")
    cur = r.get("currency", "")
    if p is None:
        return "N/A"
    return f"{p:>12,.2f} {cur}"


def _format_change(r: dict) -> str:
    c  = r.get("change")
    cp = r.get("changePercent")
    if c is None or cp is None:
        return "N/A"
    sign  = "+" if c >= 0 else ""
    arrow = "^" if c >= 0 else "v"
    return f"{arrow} {sign}{c:.2f} ({sign}{cp:.2f}%)"


def _format_hi_lo(r: dict) -> str:
    hi = r.get("dayHigh")
    lo = r.get("dayLow")
    if hi is None or lo is None:
        return ""
    return f"H:{hi:.2f} / L:{lo:.2f}"
