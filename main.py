import time
import logging
from yliveticker import YLiveTicker

# Configurare format de logare pentru a urmări starea conexiunii
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger("YLiveTickerApp")

def print_ticker_data(is_alive, ticker_data):
    """Callback apelat la fiecare update primit de la Yahoo Finance."""
    if is_alive:
        logger.info(f"Date primite: {ticker_data}")
    else:
        logger.warning(f"Conexiune inactivă. Status: {ticker_data}")

def main():
    tickers = ["AAPL", "TSLA", "BTC-USD"]
    backoff_delay = 2  # Timpul de start pentru reconectare (secunde)
    max_backoff = 60   # Timpul maxim de așteptare

    logger.info("Pornire serviciu YLiveTicker cu suport de Auto-Reconnect...")

    while True:
        try:
            logger.info(f"Conectare la Yahoo Finance pentru simbolurile: {tickers}...")
            
            # Inițializarea clientului yliveticker
            YLiveTicker(
                on_ticker=print_ticker_data,
                yahoo_ticker_list=tickers
            )
            
        except Exception as e:
            logger.error(f"S-a produs o eroare în fluxul de date: {e}")
        
        # Dacă bucla se oprește sau pică conexiunea, aplicăm backoff-ul
        logger.warning(f"Conexiunea s-a întrerupt. Reîncercare în {backoff_delay} secunde...")
        time.sleep(backoff_delay)
        
        # Creștem timpul de așteptare exponential, dar fără să depășim maximul
        backoff_delay = min(backoff_delay * 2, max_backoff)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.info("Aplicația a fost oprită manual de utilizator.")
