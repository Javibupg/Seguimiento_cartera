from functools import lru_cache
from pathlib import Path

import pandas as pd
import yfinance as yf


CACHE_DIR = Path(".cache/precios")
VENTANA_SOLAPE = pd.Timedelta(days=7)


def _archivo(ticker):
    seguro = "".join(c if c.isalnum() else "_" for c in ticker)
    return CACHE_DIR / f"{seguro}.csv"


def _leer(ticker):
    path = _archivo(ticker)
    if not path.exists():
        return pd.Series(dtype="float64", name=ticker)
    try:
        serie = pd.read_csv(path, index_col=0, parse_dates=True)["Close"].astype(float)
        serie.name = ticker
        return serie.sort_index()
    except Exception:
        return pd.Series(dtype="float64", name=ticker)


def _guardar(ticker, serie):
    if serie.empty:
        return
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    serie.dropna().sort_index().to_frame("Close").to_csv(_archivo(ticker))


def _fecha_inicio(start=None, period=None):
    if start is not None:
        return pd.to_datetime(start).normalize()
    hoy = pd.Timestamp.today().normalize()
    periodos = {
        "5d": pd.Timedelta(days=10),
        "6mo": pd.DateOffset(months=6),
        "5y": pd.DateOffset(years=5),
    }
    return hoy - periodos.get(period, pd.DateOffset(years=5))


def _ultimo_dia_objetivo():
    hoy = pd.Timestamp.today().normalize()
    return hoy if hoy.weekday() < 5 else hoy - pd.offsets.BDay(1)


def _descargar(ticker, start):
    try:
        datos = yf.download(ticker, start=start, auto_adjust=True, progress=False, threads=False)
    except Exception:
        return pd.Series(dtype="float64", name=ticker)
    if datos.empty:
        return pd.Series(dtype="float64", name=ticker)
    if isinstance(datos.columns, pd.MultiIndex):
        if "Close" in datos.columns.get_level_values(0):
            close = datos["Close"]
        elif "Close" in datos.columns.get_level_values(-1):
            close = datos.xs("Close", axis=1, level=-1)
        else:
            return pd.Series(dtype="float64", name=ticker)
    else:
        close = datos["Close"] if "Close" in datos.columns else datos
    if isinstance(close, pd.DataFrame):
        close = close.iloc[:, 0]
    close.index = pd.to_datetime(close.index).tz_localize(None)
    close.name = ticker
    return close.dropna().astype(float)


@lru_cache(maxsize=64)
def cargar_cierres(ticker, start=None, period=None):
    inicio = _fecha_inicio(start, period)
    cache = _leer(ticker)

    if cache.empty or cache.index.min() > inicio:
        nuevo = _descargar(ticker, inicio)
    elif cache.index.max().normalize() < _ultimo_dia_objetivo():
        nuevo = _descargar(ticker, max(inicio, cache.index.max() - VENTANA_SOLAPE))
    else:
        nuevo = pd.Series(dtype="float64", name=ticker)

    if not nuevo.empty:
        cache = pd.concat([cache, nuevo]).sort_index()
        cache = cache[~cache.index.duplicated(keep="last")]
        _guardar(ticker, cache)

    if cache.empty:
        return pd.Series(dtype="float64", name=ticker)

    cache = cache.loc[cache.index >= inicio]
    cache.name = ticker
    return cache


def cargar_cierres_varios(tickers, start=None):
    tickers = [tickers] if isinstance(tickers, str) else list(tickers)
    series = [cargar_cierres(ticker, start=start) for ticker in tickers]
    if not series:
        return pd.DataFrame()
    return pd.concat(series, axis=1).reindex(columns=tickers).ffill().dropna(how="all")
