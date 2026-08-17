"""Motor de investigación fundamental orientado a inversión value.

Yahoo Finance no garantiza la presencia de todos sus campos. Esta capa conserva
los ausentes como ``None`` (N/D en pantalla), tolera fallos parciales y publica
siempre la cobertura junto a la puntuación. Los valores económicos negativos sí
se evalúan, normalmente con cero puntos; nunca se confunden con un dato ausente.
"""

from __future__ import annotations

from collections import OrderedDict, namedtuple
from functools import wraps
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlparse

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf

from cache_precios import cargar_cierres
from yahoo_session import obtener_sesion_yahoo


EXCEL_PATH = Path("Libro_inversiones.xlsx")
DATO_NO_DISPONIBLE = "N/D"
CACHE_TTL_SEGUNDOS = 45 * 60

COLOR_FAVORABLE = "#15803d"
COLOR_NEUTRAL = "#d97706"
COLOR_RIESGO = "#dc2626"
COLOR_SIN_DATOS = "#64748b"

_CacheInfo = namedtuple("CacheInfo", "hits misses maxsize currsize")


def _ttl_cache(ttl=CACHE_TTL_SEGUNDOS, maxsize=128, cachear=None, ttl_rechazado=0):
    """Cache TTL acotada con interfaz similar a functools.lru_cache."""

    def decorar(funcion):
        cache = OrderedDict()
        lock = threading.RLock()
        hits = 0
        misses = 0

        @wraps(funcion)
        def envuelta(*args, **kwargs):
            nonlocal hits, misses
            clave = (args, tuple(sorted(kwargs.items())))
            ahora = time.monotonic()
            try:
                hash(clave)
            except TypeError:
                return funcion(*args, **kwargs)
            with lock:
                entrada = cache.get(clave)
                if entrada is not None and ahora - entrada[0] < entrada[2]:
                    hits += 1
                    cache.move_to_end(clave)
                    return entrada[1]
                if entrada is not None:
                    cache.pop(clave, None)
                misses += 1
            resultado = funcion(*args, **kwargs)
            duracion = ttl if cachear is None or cachear(resultado) else ttl_rechazado
            if duracion <= 0:
                return resultado
            with lock:
                cache[clave] = (ahora, resultado, duracion)
                cache.move_to_end(clave)
                while len(cache) > maxsize:
                    cache.popitem(last=False)
            return resultado

        def cache_clear():
            nonlocal hits, misses
            with lock:
                cache.clear()
                hits = misses = 0

        def cache_info():
            with lock:
                return _CacheInfo(hits, misses, maxsize, len(cache))

        envuelta.cache_clear = cache_clear
        envuelta.cache_info = cache_info
        return envuelta

    return decorar


def _es_si(valor):
    if pd.isna(valor):
        return False
    return str(valor).strip().lower() in {"si", "sí", "s", "yes", "y", "true", "1"}


def cargar_activos_investigacion(path=EXCEL_PATH):
    columnas = ["Ticker", "Nombre", "Seguimiento", "Benchmark"]
    try:
        df = pd.read_excel(path, sheet_name="Listado de activos")
    except Exception:
        return pd.DataFrame(columns=columnas)
    df.columns = df.columns.astype(str).str.strip()
    for columna in columnas:
        if columna not in df.columns:
            df[columna] = pd.NA
    df = df[columnas].copy()
    df["Ticker"] = df["Ticker"].fillna("").astype(str).str.strip()
    df["Nombre"] = df["Nombre"].where(df["Nombre"].notna(), df["Ticker"])
    df["Nombre"] = df["Nombre"].astype(str).str.strip()
    df["Benchmark"] = df["Benchmark"].map(
        lambda valor: str(valor).strip()
        if valor is not None and not pd.isna(valor) and str(valor).strip()
        else None
    )
    return df[df["Ticker"].ne("") & df["Seguimiento"].map(_es_si)].reset_index(drop=True)


def opciones_activos_investigacion(activos):
    if activos is None or activos.empty:
        return []
    return [
        {"label": f"{fila.Nombre} ({fila.Ticker})", "value": fila.Ticker}
        for fila in activos.itertuples(index=False)
    ]


def obtener_activo(activos, ticker):
    if activos is None or activos.empty:
        return {"Ticker": ticker, "Nombre": ticker, "Benchmark": None}
    fila = activos[activos["Ticker"].astype(str).eq(str(ticker))]
    if fila.empty:
        return {"Ticker": ticker, "Nombre": ticker, "Benchmark": None}
    return fila.iloc[0].to_dict()


def _serie_precios(datos):
    if datos is None:
        return pd.Series(dtype="float64")
    if isinstance(datos, pd.DataFrame):
        for columna in ("Adj Close", "Close"):
            if columna in datos.columns:
                datos = datos[columna]
                break
        if isinstance(datos, pd.DataFrame):
            datos = datos.iloc[:, 0] if not datos.empty else pd.Series(dtype="float64")
    if not isinstance(datos, pd.Series):
        try:
            datos = pd.Series(datos)
        except Exception:
            return pd.Series(dtype="float64")
    serie = pd.to_numeric(datos, errors="coerce").replace([np.inf, -np.inf], np.nan).dropna().astype(float)
    try:
        serie.index = pd.to_datetime(serie.index).tz_localize(None)
        serie = serie[~serie.index.duplicated(keep="last")].sort_index()
    except Exception:
        pass
    return serie


@_ttl_cache(
    ttl=CACHE_TTL_SEGUNDOS,
    maxsize=128,
    cachear=lambda serie: isinstance(serie, pd.Series) and not serie.empty,
    ttl_rechazado=30,
)
def descargar_precios_investigacion(ticker, periodo="5y"):
    if not ticker:
        return pd.Series(dtype="float64")
    try:
        return _serie_precios(cargar_cierres(str(ticker), period=periodo))
    except Exception:
        return pd.Series(dtype="float64", name=str(ticker))


def _numero(valor):
    if valor is None or isinstance(valor, (dict, list, tuple, pd.Series, pd.DataFrame)):
        return None
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return None
    return numero if np.isfinite(numero) else None


def _primero(*valores):
    for valor in valores:
        numero = _numero(valor)
        if numero is not None:
            return numero
    return None


def _dato_info(info, *campos):
    for campo in campos:
        valor = info.get(campo)
        if valor not in (None, ""):
            return valor
    return None


def _normalizar_etiqueta(texto):
    return re.sub(r"[^a-z0-9]", "", str(texto).lower())


def _normalizar_estado(estado):
    if not isinstance(estado, pd.DataFrame) or estado.empty:
        return pd.DataFrame()
    resultado = estado.copy()
    if isinstance(resultado.index, pd.DatetimeIndex) and not isinstance(resultado.columns, pd.DatetimeIndex):
        resultado = resultado.T
    return resultado.loc[~resultado.index.duplicated(keep="first")].dropna(how="all", axis=0).dropna(how="all", axis=1)


def _obtener_estado(objeto, getter, propiedades):
    errores = []
    metodo = getattr(objeto, getter, None)
    if callable(metodo):
        for kwargs in ({"freq": "yearly"}, {}):
            try:
                estado = _normalizar_estado(metodo(**kwargs))
                if not estado.empty:
                    return estado, errores
            except TypeError as exc:
                errores.append(str(exc))
                continue
            except Exception as exc:
                errores.append(str(exc))
                break
    for propiedad in propiedades:
        try:
            estado = _normalizar_estado(getattr(objeto, propiedad, None))
            if not estado.empty:
                return estado, errores
        except Exception as exc:
            errores.append(str(exc))
    return pd.DataFrame(), errores


def _paquete_yahoo_tiene_datos(paquete):
    if not isinstance(paquete, dict):
        return False
    if paquete.get("info"):
        return True
    return any(
        isinstance(paquete.get(clave), pd.DataFrame) and not paquete[clave].empty
        for clave in ("income", "cashflow", "balance")
    )


def _aviso_error_yahoo(errores):
    texto = " ".join(str(error) for error in (errores or [])).lower()
    if "certificate" in texto or "ssl" in texto or "curl: (60)" in texto:
        return "No se ha podido establecer una conexión segura con Yahoo Finance."
    if "429" in texto or "rate limit" in texto or "too many requests" in texto:
        return "Yahoo Finance ha limitado temporalmente las consultas; vuelve a intentarlo en unos minutos."
    if "timeout" in texto or "timed out" in texto:
        return "Yahoo Finance ha tardado demasiado en responder; los bloques disponibles se mantienen."
    return "Algunas fuentes de Yahoo fallaron; la ficha usa únicamente los bloques disponibles."


@_ttl_cache(
    ttl=CACHE_TTL_SEGUNDOS,
    maxsize=96,
    cachear=_paquete_yahoo_tiene_datos,
    ttl_rechazado=30,
)
def _descargar_paquete_yahoo(ticker):
    """Descarga cada familia de datos por separado para admitir fallos parciales."""
    ticker = str(ticker or "").strip()
    paquete = {
        "info": {}, "income": pd.DataFrame(), "cashflow": pd.DataFrame(),
        "balance": pd.DataFrame(), "news": [], "errores": [],
    }
    if not ticker:
        paquete["errores"].append("Ticker vacío.")
        return paquete
    try:
        objeto = yf.Ticker(ticker, session=obtener_sesion_yahoo())
    except Exception as exc:
        paquete["errores"].append(f"No se pudo abrir Yahoo Finance: {exc}")
        return paquete
    try:
        info = objeto.get_info() if callable(getattr(objeto, "get_info", None)) else objeto.info
        paquete["info"] = info if isinstance(info, dict) else {}
    except Exception as exc:
        paquete["errores"].append(f"Ficha general no disponible: {exc}")
        try:
            info = objeto.info
            paquete["info"] = info if isinstance(info, dict) else {}
        except Exception:
            pass
    for clave, getter, propiedades in (
        ("income", "get_income_stmt", ("income_stmt", "financials")),
        ("cashflow", "get_cash_flow", ("cashflow", "cash_flow")),
        ("balance", "get_balance_sheet", ("balance_sheet", "balancesheet")),
    ):
        estado, errores = _obtener_estado(objeto, getter, propiedades)
        paquete[clave] = estado
        if estado.empty and errores:
            paquete["errores"].append(f"{clave}: {errores[-1]}")
    noticias = None
    metodo_news = getattr(objeto, "get_news", None)
    if callable(metodo_news):
        for kwargs in ({"count": 10, "tab": "news"}, {"count": 10}, {}):
            try:
                noticias = metodo_news(**kwargs)
                if noticias is not None:
                    break
            except TypeError:
                continue
            except Exception as exc:
                paquete["errores"].append(f"Noticias no disponibles: {exc}")
                break
    if noticias is None:
        try:
            noticias = objeto.news
        except Exception:
            noticias = []
    paquete["news"] = _normalizar_noticias(noticias)
    return paquete


def _fila(estado, aliases):
    if estado is None or estado.empty:
        return pd.Series(dtype="float64")
    indice = {_normalizar_etiqueta(nombre): nombre for nombre in estado.index}
    for alias in aliases:
        nombre = indice.get(_normalizar_etiqueta(alias))
        if nombre is not None:
            fila = estado.loc[nombre]
            if isinstance(fila, pd.DataFrame):
                fila = fila.iloc[0]
            return pd.to_numeric(fila, errors="coerce").replace([np.inf, -np.inf], np.nan)
    return pd.Series(dtype="float64")


def _anio_columna(columna):
    if isinstance(columna, (int, np.integer)) and 1900 <= int(columna) <= 2200:
        return int(columna)
    if isinstance(columna, (float, np.floating)) and columna.is_integer() and 1900 <= int(columna) <= 2200:
        return int(columna)
    try:
        return int(pd.Timestamp(columna).year)
    except Exception:
        coincidencia = re.search(r"(19|20)\d{2}", str(columna))
        return int(coincidencia.group(0)) if coincidencia else None


def _por_anio(serie):
    resultado = {}
    if serie is None:
        return resultado
    for columna, valor in serie.items():
        anio = _anio_columna(columna)
        numero = _numero(valor)
        if anio is not None and numero is not None and anio not in resultado:
            resultado[anio] = numero
    return resultado


def _mapa_filas(estado, definiciones):
    return {clave: _por_anio(_fila(estado, aliases)) for clave, aliases in definiciones.items()}


FILAS_INCOME = {
    "ingresos": ("Total Revenue", "Operating Revenue", "Revenue"),
    "ebit": ("EBIT", "Operating Income", "Normalized EBIT"),
    "ebitda": ("EBITDA", "Normalized EBITDA", "Reconciled EBITDA"),
    "beneficio_neto": ("Net Income", "Net Income Common Stockholders", "Normalized Income"),
    "beneficio_pretax": ("Pretax Income", "Income Before Tax"),
    "impuestos": ("Tax Provision", "Income Tax Expense"),
    "intereses": ("Interest Expense", "Interest Expense Non Operating"),
    "acciones_diluidas": ("Diluted Average Shares", "Basic Average Shares"),
    "beneficio_bruto": ("Gross Profit",),
}
FILAS_CASHFLOW = {
    "cfo": ("Operating Cash Flow", "Total Cash From Operating Activities"),
    "capex": ("Capital Expenditure", "Capital Expenditures"),
    "fcf_reportado": ("Free Cash Flow",),
}
FILAS_BALANCE = {
    "deuda": ("Total Debt", "Total Debt And Capital Lease Obligation"),
    "caja": (
        "Cash Cash Equivalents And Short Term Investments", "Cash And Short Term Investments",
        "Cash And Cash Equivalents", "Cash Financial",
    ),
    "patrimonio": ("Stockholders Equity", "Total Stockholder Equity"),
    "capital_invertido": ("Invested Capital",),
    "activo_corriente": ("Current Assets", "Total Current Assets"),
    "pasivo_corriente": ("Current Liabilities", "Total Current Liabilities"),
    "activos": ("Total Assets",),
}


def _construir_historico(income, cashflow, balance):
    inc = _mapa_filas(income, FILAS_INCOME)
    cash = _mapa_filas(cashflow, FILAS_CASHFLOW)
    bal = _mapa_filas(balance, FILAS_BALANCE)
    anios = sorted(
        {anio for grupo in (inc, cash, bal) for mapa in grupo.values() for anio in mapa},
        reverse=True,
    )[:4]
    historico = []
    for anio in anios:
        registro = {"ejercicio": anio}
        for grupo in (inc, cash, bal):
            for clave, mapa in grupo.items():
                registro[clave] = mapa.get(anio)
        cfo = registro.get("cfo")
        capex = registro.get("capex")
        fcf = registro.pop("fcf_reportado", None)
        if fcf is None and cfo is not None and capex is not None:
            fcf = cfo - abs(capex)
        elif cfo is None and fcf is not None and capex is not None:
            cfo = fcf + abs(capex)
            registro["cfo"] = cfo
        registro["fcf"] = fcf
        deuda, caja = registro.get("deuda"), registro.get("caja")
        registro["deuda_neta"] = deuda - caja if deuda is not None and caja is not None else None
        ingresos, ebit = registro.get("ingresos"), registro.get("ebit")
        registro["margen_operativo"] = ebit / ingresos if ebit is not None and ingresos not in (None, 0) else None
        registro["margen_fcf"] = fcf / ingresos if fcf is not None and ingresos not in (None, 0) else None
        acciones = registro.get("acciones_diluidas")
        registro["fcf_accion"] = fcf / acciones if fcf is not None and acciones and acciones > 0 else None
        historico.append(registro)
    return historico


def _valores(historico, clave, limite=None):
    registros = historico[:limite] if limite else historico
    return [r.get(clave) for r in registros if _numero(r.get(clave)) is not None]


def _mediana(historico, clave, limite=3):
    valores = _valores(historico, clave, limite)
    return float(np.median(valores)) if valores else None


def _suma(historico, clave, limite=3):
    valores = _valores(historico, clave, limite)
    return float(sum(valores)) if valores else None


def _actual(historico, clave):
    for registro in historico:
        numero = _numero(registro.get(clave))
        if numero is not None:
            return numero
    return None


def _cagr(historico, clave):
    puntos = [(r["ejercicio"], _numero(r.get(clave))) for r in historico if _numero(r.get(clave)) is not None]
    if len(puntos) < 2:
        return None
    reciente_anio, reciente = puntos[0]
    antiguo_anio, antiguo = puntos[-1]
    periodos = reciente_anio - antiguo_anio
    if periodos <= 0 or antiguo is None or antiguo <= 0 or reciente is None:
        return None
    if reciente <= 0:
        return -1.0
    return float((reciente / antiguo) ** (1 / periodos) - 1)


def _interpolar(valor, anclas):
    valor = _numero(valor)
    if valor is None:
        return None
    anclas = sorted(anclas, key=lambda par: par[0])
    if valor <= anclas[0][0]:
        return float(anclas[0][1])
    if valor >= anclas[-1][0]:
        return float(anclas[-1][1])
    for (x0, y0), (x1, y1) in zip(anclas, anclas[1:]):
        if x0 <= valor <= x1:
            return float(y0 + (valor - x0) * (y1 - y0) / (x1 - x0))
    return None


def _estado_puntuacion(puntuacion, referencia=False):
    if referencia:
        return "neutral"
    if puntuacion is None:
        return "sin-dato"
    if puntuacion >= 70:
        return "favorable"
    if puntuacion >= 40:
        return "neutral"
    return "adverse"


def _metrica(titulo, valor, tipo, puntuacion, peso, detalle, descripcion, *, cobertura=1.0, disponible=None, referencia=False):
    if disponible is None:
        disponible = _numero(valor) is not None
    if not disponible:
        valor, puntuacion, cobertura = None, None, 0.0
    elif puntuacion is not None:
        puntuacion = max(0.0, min(100.0, float(puntuacion)))
    return {
        "titulo": titulo, "valor": valor, "tipo": tipo,
        "estado": _estado_puntuacion(puntuacion, referencia),
        "detalle": detalle, "descripcion": descripcion,
        "puntuacion": puntuacion, "peso": float(peso),
        "cobertura": max(0.0, min(1.0, float(cobertura))) if disponible else 0.0,
    }


def _piotroski_parcial(historico):
    if len(historico) < 2:
        return None, 0, []
    actual, previo = historico[0], historico[1]
    criterios = []

    def agregar(nombre, condicion, disponible=True):
        if disponible:
            criterios.append((nombre, bool(condicion)))

    ni, cfo = _numero(actual.get("beneficio_neto")), _numero(actual.get("cfo"))
    activos, activos_prev = _numero(actual.get("activos")), _numero(previo.get("activos"))
    ni_prev = _numero(previo.get("beneficio_neto"))
    agregar("beneficio positivo", ni > 0 if ni is not None else False, ni is not None)
    agregar("flujo operativo positivo", cfo > 0 if cfo is not None else False, cfo is not None)
    roa = ni / activos if ni is not None and activos and activos > 0 else None
    roa_prev = ni_prev / activos_prev if ni_prev is not None and activos_prev and activos_prev > 0 else None
    agregar("ROA mejora", roa > roa_prev if roa is not None and roa_prev is not None else False, roa is not None and roa_prev is not None)
    agregar("CFO supera beneficio", cfo > ni if cfo is not None and ni is not None else False, cfo is not None and ni is not None)
    deuda, deuda_prev = _numero(actual.get("deuda")), _numero(previo.get("deuda"))
    apal = deuda / activos if deuda is not None and activos and activos > 0 else None
    apal_prev = deuda_prev / activos_prev if deuda_prev is not None and activos_prev and activos_prev > 0 else None
    agregar("apalancamiento baja", apal < apal_prev if apal is not None and apal_prev is not None else False, apal is not None and apal_prev is not None)
    ac, pc = _numero(actual.get("activo_corriente")), _numero(actual.get("pasivo_corriente"))
    ac_prev, pc_prev = _numero(previo.get("activo_corriente")), _numero(previo.get("pasivo_corriente"))
    liquidez = ac / pc if ac is not None and pc and pc > 0 else None
    liquidez_prev = ac_prev / pc_prev if ac_prev is not None and pc_prev and pc_prev > 0 else None
    agregar("liquidez mejora", liquidez > liquidez_prev if liquidez is not None and liquidez_prev is not None else False, liquidez is not None and liquidez_prev is not None)
    acciones, acciones_prev = _numero(actual.get("acciones_diluidas")), _numero(previo.get("acciones_diluidas"))
    agregar("sin dilución", acciones <= acciones_prev if acciones is not None and acciones_prev is not None else False, acciones is not None and acciones_prev is not None)
    bruto, ventas = _numero(actual.get("beneficio_bruto")), _numero(actual.get("ingresos"))
    bruto_prev, ventas_prev = _numero(previo.get("beneficio_bruto")), _numero(previo.get("ingresos"))
    margen = bruto / ventas if bruto is not None and ventas and ventas > 0 else None
    margen_prev = bruto_prev / ventas_prev if bruto_prev is not None and ventas_prev and ventas_prev > 0 else None
    agregar("margen bruto mejora", margen > margen_prev if margen is not None and margen_prev is not None else False, margen is not None and margen_prev is not None)
    rotacion = ventas / activos if ventas is not None and activos and activos > 0 else None
    rotacion_prev = ventas_prev / activos_prev if ventas_prev is not None and activos_prev and activos_prev > 0 else None
    agregar("rotación mejora", rotacion > rotacion_prev if rotacion is not None and rotacion_prev is not None else False, rotacion is not None and rotacion_prev is not None)
    return sum(int(cumple) for _, cumple in criterios), len(criterios), criterios


def _tasa_fiscal_normalizada(historico):
    tasas = []
    for registro in historico[:3]:
        pretax, impuestos = _numero(registro.get("beneficio_pretax")), _numero(registro.get("impuestos"))
        if pretax is not None and pretax > 0 and impuestos is not None and impuestos >= 0:
            tasas.append(min(max(impuestos / pretax, 0.0), 0.40))
    return float(np.median(tasas)) if tasas else None


def _capital_invertido(registro):
    directo = _numero(registro.get("capital_invertido"))
    if directo is not None:
        return directo
    deuda, patrimonio, caja = (_numero(registro.get(k)) for k in ("deuda", "patrimonio", "caja"))
    return deuda + patrimonio - caja if deuda is not None and patrimonio is not None and caja is not None else None


def _metricas_fundamentales(info, historico, moneda_incompatible):
    precio = _primero(_dato_info(info, "currentPrice", "regularMarketPrice", "previousClose"))
    acciones_info = _primero(_dato_info(info, "sharesOutstanding", "impliedSharesOutstanding"))
    acciones = _primero(acciones_info, _actual(historico, "acciones_diluidas"))
    market_cap = _primero(_dato_info(info, "marketCap"), precio * acciones if precio and acciones else None)
    deuda = _primero(_actual(historico, "deuda"), _dato_info(info, "totalDebt"))
    caja = _primero(_actual(historico, "caja"), _dato_info(info, "totalCash"))
    deuda_neta = deuda - caja if deuda is not None and caja is not None else None
    enterprise_value = _primero(
        _dato_info(info, "enterpriseValue"),
        market_cap + deuda_neta if market_cap is not None and deuda_neta is not None else None,
    )

    fcf_norm = _mediana(historico, "fcf")
    fcf_ttm = _primero(_dato_info(info, "freeCashflow"))
    beneficio_norm = _mediana(historico, "beneficio_neto")
    ebit_norm = _mediana(historico, "ebit")
    ebitda_norm = _mediana(historico, "ebitda")
    ebitda_ttm = _primero(_dato_info(info, "ebitda"))
    ebitda_base = _primero(ebitda_norm, ebitda_ttm)
    sector = str(_dato_info(info, "sector") or "").lower()
    peso_norm = 0.60 if sector in {"energy", "basic materials", "materials"} else 0.40

    fcf_yield_norm = fcf_norm / market_cap if fcf_norm is not None and market_cap and market_cap > 0 else None
    fcf_yield_ttm = fcf_ttm / market_cap if fcf_ttm is not None and market_cap and market_cap > 0 else None
    if fcf_yield_norm is not None and fcf_yield_ttm is not None:
        fcf_yield = peso_norm * fcf_yield_norm + (1 - peso_norm) * fcf_yield_ttm
    else:
        fcf_yield = _primero(fcf_yield_norm, fcf_yield_ttm)
    earnings_yield = beneficio_norm / market_cap if beneficio_norm is not None and market_cap and market_cap > 0 else None
    ev_ebit = enterprise_value / ebit_norm if enterprise_value is not None and ebit_norm not in (None, 0) else None
    ev_ebitda = enterprise_value / ebitda_base if enterprise_value is not None and ebitda_base not in (None, 0) else None
    if moneda_incompatible:
        fcf_yield_norm = fcf_yield_ttm = None
        fcf_yield = earnings_yield = ev_ebit = ev_ebitda = None

    valoracion = [
        _metrica(
            "FCF yield (normalizado/TTM)", fcf_yield, "porcentaje",
            _interpolar(fcf_yield, [(0, 0), (.02, 20), (.04, 45), (.06, 70), (.08, 85), (.10, 100)]), 14,
            f"Normalizado: {formatear_valor(fcf_yield_norm, 'porcentaje')} · TTM: {formatear_valor(fcf_yield_ttm, 'porcentaje')}",
            "Caja libre frente al precio pagado; combina TTM y mediana de hasta tres ejercicios.",
        ),
        _metrica(
            "Earnings yield normalizado", earnings_yield, "porcentaje",
            _interpolar(earnings_yield, [(0, 0), (.025, 15), (.04, 40), (.055, 65), (.075, 85), (.10, 100)]), 10,
            "Inversa económica del PER usando beneficio neto mediano.",
            "Beneficio normalizado de hasta tres ejercicios dividido por capitalización bursátil.",
        ),
        _metrica(
            "EV / EBIT normalizado", ev_ebit, "ratio",
            0 if ebit_norm is not None and ebit_norm <= 0 else _interpolar(ev_ebit, [(0, 100), (8, 100), (10, 90), (12, 75), (15, 55), (20, 25), (25, 0)]), 10,
            "Enterprise value actual sobre EBIT mediano.",
            "Múltiplo independiente de financiación; EBIT negativo puntúa cero.",
        ),
        _metrica(
            "EV / EBITDA normalizado", ev_ebitda, "ratio",
            0 if ebitda_base is not None and ebitda_base <= 0 else _interpolar(ev_ebitda, [(0, 100), (6, 100), (8, 85), (10, 70), (12, 50), (16, 20), (20, 0)]), 6,
            "Enterprise value actual sobre EBITDA mediano (o TTM como respaldo).",
            "Referencia antes de amortizaciones; debe contrastarse con capex y FCF.",
        ),
        _metrica(
            "PER forward (referencia)", _primero(_dato_info(info, "forwardPE")), "ratio", None, 0,
            "Estimación de consenso de Yahoo; no entra en el score.",
            "Expectativa de analistas, menos robusta que los datos realizados.", referencia=True,
        ),
        _metrica(
            "Precio / valor contable (referencia)", _primero(_dato_info(info, "priceToBook")), "ratio", None, 0,
            "Depende mucho del sector; no entra en el score.",
            "Precio frente al patrimonio contable por acción.", referencia=True,
        ),
    ]

    if deuda_neta is not None and deuda_neta <= 0:
        nd_ebitda = deuda_neta / ebitda_base if ebitda_base and ebitda_base > 0 else 0.0
        score_nd_ebitda = 100
        nd_fcf = deuda_neta / fcf_norm if fcf_norm and fcf_norm > 0 else 0.0
        score_nd_fcf = 100
    else:
        nd_ebitda = deuda_neta / ebitda_base if deuda_neta is not None and ebitda_base not in (None, 0) else None
        score_nd_ebitda = (
            0 if deuda_neta is not None and deuda_neta > 0 and ebitda_base is not None and ebitda_base <= 0
            else _interpolar(nd_ebitda, [(0, 100), (.5, 95), (1, 85), (2, 65), (3, 40), (4, 15), (5, 0)])
        )
        nd_fcf = deuda_neta / fcf_norm if deuda_neta is not None and fcf_norm not in (None, 0) else None
        score_nd_fcf = (
            0 if deuda_neta is not None and deuda_neta > 0 and fcf_norm is not None and fcf_norm <= 0
            else _interpolar(nd_fcf, [(0, 100), (2, 90), (3, 75), (5, 45), (8, 15), (10, 0)])
        )

    interes_actual = _actual(historico, "intereses")
    interes = abs(interes_actual) if interes_actual is not None else None
    ebit_actual = _actual(historico, "ebit")
    cobertura_intereses = ebit_actual / interes if ebit_actual is not None and interes and interes > 0 else None
    activo_corriente = _actual(historico, "activo_corriente")
    pasivo_corriente = _actual(historico, "pasivo_corriente")
    current_ratio = _primero(
        activo_corriente / pasivo_corriente if activo_corriente is not None and pasivo_corriente and pasivo_corriente > 0 else None,
        _dato_info(info, "currentRatio"),
    )
    deudas_netas = [(r["ejercicio"], _numero(r.get("deuda_neta"))) for r in historico if _numero(r.get("deuda_neta")) is not None]
    tendencia_deuda = score_tendencia = None
    if len(deudas_netas) >= 2:
        actual_dn, antigua_dn = deudas_netas[0][1], deudas_netas[-1][1]
        if antigua_dn > 0:
            tendencia_deuda = actual_dn / antigua_dn - 1
            score_tendencia = _interpolar(tendencia_deuda, [(-.30, 100), (0, 70), (.20, 40), (.50, 10), (1, 0)])
        elif actual_dn <= 0:
            tendencia_deuda, score_tendencia = 0.0, 100
        else:
            tendencia_deuda, score_tendencia = 1.0, 0
    patrimonio = _actual(historico, "patrimonio")
    deuda_equity = deuda / patrimonio if deuda is not None and patrimonio and patrimonio > 0 else None
    solvencia = [
        _metrica("Deuda neta / EBITDA", nd_ebitda, "ratio", score_nd_ebitda, 10,
                 "Caja neta obtiene la máxima puntuación.", "Años teóricos de EBITDA para cubrir deuda neta."),
        _metrica("Cobertura de intereses", cobertura_intereses, "ratio",
                 _interpolar(cobertura_intereses, [(1, 0), (1.5, 15), (2.5, 45), (4, 70), (6, 85), (10, 100)]), 6,
                 "EBIT del último ejercicio / gasto financiero.", "Holgura operativa para pagar intereses."),
        _metrica("Deuda neta / FCF normalizado", nd_fcf, "ratio", score_nd_fcf, 4,
                 "Usa FCF mediano de hasta tres ejercicios.", "Años teóricos de FCF para cancelar deuda neta."),
        _metrica("Tendencia de deuda neta", tendencia_deuda, "porcentaje", score_tendencia, 3,
                 "Cambio entre el ejercicio más antiguo y el último.", "Indica desapalancamiento o deterioro del balance."),
        _metrica("Current ratio", current_ratio, "ratio",
                 _interpolar(current_ratio, [(.8, 0), (1, 25), (1.2, 50), (1.5, 75), (2, 100)]), 2,
                 "Activo corriente / pasivo corriente.", "Cobertura de obligaciones de corto plazo."),
        _metrica("Deuda / patrimonio (referencia)", deuda_equity, "ratio", None, 0,
                 "No puntúa: recompras y patrimonio negativo pueden distorsionarlo.",
                 "Apalancamiento contable de referencia.", referencia=True),
    ]

    tasa_fiscal = _tasa_fiscal_normalizada(historico)
    capitales = [_capital_invertido(r) for r in historico[:2]]
    capitales = [c for c in capitales if c is not None]
    capital_medio = float(np.mean(capitales)) if capitales else None
    roic = ebit_norm * (1 - tasa_fiscal) / capital_medio if ebit_norm is not None and tasa_fiscal is not None and capital_medio and capital_medio > 0 else None
    suma_fcf, suma_ingresos = _suma(historico, "fcf"), _suma(historico, "ingresos")
    margen_fcf = suma_fcf / suma_ingresos if suma_fcf is not None and suma_ingresos and suma_ingresos > 0 else None
    suma_beneficio = _suma(historico, "beneficio_neto")
    conversion = suma_fcf / suma_beneficio if suma_fcf is not None and suma_beneficio and suma_beneficio > 0 else None
    conversion_disponible = suma_fcf is not None and suma_beneficio is not None
    score_conversion = 0 if conversion is None and conversion_disponible else _interpolar(conversion, [(0, 0), (.5, 25), (.8, 65), (1, 90), (1.2, 100)])
    piotroski, piotroski_disponibles, _ = _piotroski_parcial(historico)
    score_piotroski = 100 * piotroski / piotroski_disponibles if piotroski_disponibles else None
    fcf_anuales = _valores(historico, "fcf", 4)
    positivos = sum(valor > 0 for valor in fcf_anuales)
    score_positivos = 100 * positivos / len(fcf_anuales) if fcf_anuales else None
    calidad = [
        _metrica("ROIC normalizado", roic, "porcentaje",
                 _interpolar(roic, [(0, 0), (.05, 25), (.08, 50), (.12, 70), (.15, 85), (.20, 100)]), 8,
                 f"Tasa fiscal normalizada: {formatear_valor(tasa_fiscal, 'porcentaje')}.",
                 "Rentabilidad operativa después de impuestos sobre capital invertido medio."),
        _metrica("Margen FCF (3 años)", margen_fcf, "porcentaje",
                 _interpolar(margen_fcf, [(0, 0), (.03, 30), (.07, 60), (.12, 80), (.20, 100)]), 5,
                 "FCF agregado / ingresos agregados.", "Parte de las ventas convertida en caja libre."),
        _metrica("Conversión de beneficio en FCF", conversion, "ratio", score_conversion, 5,
                 "FCF agregado / beneficio agregado; beneficio no positivo puntúa cero.",
                 "Calidad de caja del beneficio contable.", disponible=conversion_disponible),
        _metrica("Piotroski parcial", piotroski, "piotroski", score_piotroski, 4,
                 f"{piotroski or 0}/{piotroski_disponibles} señales positivas; cobertura {piotroski_disponibles}/9.",
                 "Chequeo parcial de rentabilidad, balance y eficiencia.",
                 cobertura=piotroski_disponibles / 9 if piotroski_disponibles else 0,
                 disponible=piotroski_disponibles > 0),
        _metrica("Ejercicios con FCF positivo", positivos if fcf_anuales else None, "fraccion", score_positivos, 3,
                 f"{positivos}/{len(fcf_anuales)} ejercicios disponibles.", "Persistencia de caja libre.",
                 cobertura=len(fcf_anuales) / 4 if fcf_anuales else 0, disponible=bool(fcf_anuales)),
    ]

    cagr_ingresos = _cagr(historico, "ingresos")
    cagr_fcf_accion = _cagr(historico, "fcf_accion")
    cagr_acciones = _cagr(historico, "acciones_diluidas")
    margenes = [(r["ejercicio"], _numero(r.get("margen_operativo"))) for r in historico if _numero(r.get("margen_operativo")) is not None]
    cambio_margen = margenes[0][1] - margenes[-1][1] if len(margenes) >= 2 else None
    crecimiento = [
        _metrica("CAGR ingresos", cagr_ingresos, "porcentaje",
                 _interpolar(cagr_ingresos, [(-.10, 0), (-.05, 15), (0, 40), (.03, 60), (.06, 80), (.10, 100)]), 3,
                 "CAGR entre el primer y último ejercicio.", "Ayuda a distinguir ganga de contracción estructural."),
        _metrica("CAGR FCF por acción", cagr_fcf_accion, "porcentaje",
                 _interpolar(cagr_fcf_accion, [(-.10, 0), (-.05, 15), (0, 40), (.03, 60), (.08, 80), (.15, 100)]), 3,
                 "Exige FCF por acción inicial positivo.", "Crecimiento de caja atribuible a cada acción."),
        _metrica("CAGR acciones diluidas", cagr_acciones, "porcentaje",
                 _interpolar(cagr_acciones, [(-.03, 100), (0, 80), (.02, 55), (.05, 20), (.10, 0)]), 3,
                 "Negativo significa recompras; positivo, dilución.", "Cambio anual de la base accionarial."),
        _metrica("Cambio margen operativo", cambio_margen, "puntos_porcentuales",
                 _interpolar(cambio_margen, [(-.05, 0), (-.02, 35), (0, 75), (.02, 100)]), 1,
                 "Diferencia entre margen más antiguo y último.", "Mejora o deterioro de economía operativa."),
    ]
    auxiliares = {
        "precio": precio, "acciones": acciones, "market_cap": market_cap,
        "enterprise_value": enterprise_value, "deuda": deuda, "caja": caja,
        "deuda_neta": deuda_neta, "fcf_normalizado": fcf_norm,
        "ebitda_normalizado": ebitda_base, "tasa_fiscal": tasa_fiscal,
        "cagr_ingresos": cagr_ingresos, "cagr_acciones": cagr_acciones,
        "cobertura_intereses": cobertura_intereses, "nd_ebitda": nd_ebitda,
        "patrimonio": patrimonio,
    }
    return {
        "valoracion": valoracion, "solvencia": solvencia,
        "calidad": calidad, "crecimiento": crecimiento,
    }, auxiliares


PILARES = (
    ("valoracion", "Valoración", 40),
    ("solvencia", "Solvencia", 25),
    ("calidad", "Calidad y caja", 25),
    ("crecimiento", "Crecimiento y capital", 10),
)


def _calcular_pilares(metricas):
    pilares = []
    for clave, nombre, peso_total in PILARES:
        numerador = peso_disponible = 0.0
        for metrica in metricas[clave]:
            peso = float(metrica.get("peso") or 0)
            puntuacion = _numero(metrica.get("puntuacion"))
            cobertura = float(metrica.get("cobertura") or 0)
            if peso > 0 and puntuacion is not None and cobertura > 0:
                efectivo = peso * cobertura
                numerador += efectivo * puntuacion
                peso_disponible += efectivo
        valor = numerador / peso_disponible if peso_disponible else None
        cobertura_pilar = peso_disponible / peso_total if peso_total else 0
        pilares.append({
            "clave": clave, "nombre": nombre,
            "valor": round(valor, 1) if valor is not None else None,
            "cobertura": round(min(cobertura_pilar, 1), 3), "peso": peso_total / 100,
        })
    disponibles = [p for p in pilares if p["valor"] is not None and p["cobertura"] > 0]
    peso_disponible = sum(p["peso"] * p["cobertura"] for p in disponibles)
    score = (
        sum(p["valor"] * p["peso"] * p["cobertura"] for p in disponibles) / peso_disponible
        if peso_disponible else None
    )
    cobertura = sum(p["peso"] * p["cobertura"] for p in pilares)
    return pilares, round(score, 1) if score is not None else None, round(cobertura, 3)


def _crear_dcf(aux, moneda, moneda_financiera, moneda_incompatible):
    base = {"disponible": False, "escenarios": [], "supuestos": {}, "motivo": None}
    if moneda_incompatible:
        base["motivo"] = "Moneda de cotización y moneda financiera distintas."
        return base
    requeridos = ("fcf_normalizado", "deuda_neta", "acciones", "precio", "cagr_ingresos", "tasa_fiscal")
    if any(_numero(aux.get(clave)) is None for clave in requeridos):
        base["motivo"] = "Faltan FCF, deuda, acciones, precio, crecimiento o tasa fiscal fiables."
        return base
    interes = aux.get("intereses_normalizados")
    if interes is None and aux.get("deuda") == 0:
        interes = 0.0
    if interes is None:
        base["motivo"] = "No hay gasto financiero suficiente para normalizar FCFF."
        return base
    fcff = aux["fcf_normalizado"] + abs(interes) * (1 - aux["tasa_fiscal"])
    if fcff <= 0 or aux["acciones"] <= 0 or aux["precio"] <= 0:
        base["motivo"] = "FCFF, número de acciones o precio no son positivos."
        return base
    observado = aux["cagr_ingresos"]
    parametros = (
        ("Conservador", min(max(observado - .03, -.05), .03), .12, .01, "#dc2626"),
        ("Base", min(max(observado, -.02), .06), .10, .02, "#2563eb"),
        ("Optimista", min(max(observado + .02, 0), .09), .09, .025, "#15803d"),
    )
    escenarios = []
    for nombre, crecimiento, descuento, terminal, color in parametros:
        flujo = fcff
        valor_presente = 0.0
        for anio in range(1, 6):
            flujo *= 1 + crecimiento
            valor_presente += flujo / (1 + descuento) ** anio
        valor_terminal = flujo * (1 + terminal) / (descuento - terminal)
        valor_empresa = valor_presente + valor_terminal / (1 + descuento) ** 5
        valor_accion = (valor_empresa - aux["deuda_neta"]) / aux["acciones"]
        escenarios.append({
            "nombre": nombre, "valor": float(valor_accion),
            "margen": float(valor_accion / aux["precio"] - 1), "color": color,
            "crecimiento": crecimiento, "tasa_descuento": descuento,
            "crecimiento_terminal": terminal,
        })
    return {
        "disponible": True, "escenarios": escenarios,
        "supuestos": {
            "fcff_normalizado": fcff, "deuda_neta": aux["deuda_neta"],
            "acciones": aux["acciones"], "moneda": moneda_financiera or moneda,
            "horizonte": "5 años + valor terminal",
            "metodo": "FCFF normalizado y tasas de descuento explícitas por escenario",
            "nota": "Estimación orientativa; no es precio objetivo ni recomendación.",
        },
        "motivo": None,
    }


def _normalizar_noticias(noticias):
    if isinstance(noticias, dict):
        noticias = noticias.get("items") or noticias.get("news") or []
    if not isinstance(noticias, (list, tuple)):
        return []
    resultado, vistos = [], set()
    for item in noticias:
        if not isinstance(item, dict):
            continue
        contenido = item.get("content") if isinstance(item.get("content"), dict) else item
        titulo = contenido.get("title") or item.get("title")
        proveedor = contenido.get("provider")
        fuente = proveedor.get("displayName") or proveedor.get("name") if isinstance(proveedor, dict) else proveedor
        fuente = fuente or contenido.get("publisher") or item.get("publisher") or "Yahoo Finance"
        url_obj = contenido.get("canonicalUrl") or contenido.get("clickThroughUrl")
        url = url_obj.get("url") if isinstance(url_obj, dict) else url_obj
        url = url or contenido.get("link") or item.get("link")
        try:
            if url and urlparse(str(url)).scheme.lower() not in {"http", "https"}:
                url = None
        except Exception:
            url = None
        fecha_raw = contenido.get("pubDate") or contenido.get("displayTime") or item.get("providerPublishTime")
        fecha = None
        try:
            if isinstance(fecha_raw, (int, float)):
                fecha = pd.to_datetime(fecha_raw, unit="s", utc=True).isoformat()
            elif fecha_raw:
                fecha = pd.to_datetime(fecha_raw, utc=True).isoformat()
        except Exception:
            fecha = str(fecha_raw) if fecha_raw else None
        clave = (str(titulo or "").strip().lower(), str(url or "").strip())
        if not titulo or clave in vistos:
            continue
        vistos.add(clave)
        resultado.append({"titulo": str(titulo).strip(), "fuente": str(fuente), "fecha": fecha, "url": url})
        if len(resultado) == 6:
            break
    return resultado


def _extraer_fecha_estados(*estados):
    fechas = []
    for estado in estados:
        if estado is None or estado.empty:
            continue
        for columna in estado.columns:
            try:
                fecha = pd.Timestamp(columna)
                fechas.append(fecha.tz_localize(None) if fecha.tzinfo is not None else fecha)
            except Exception:
                pass
    return max(fechas) if fechas else None


def _fortalezas_riesgos(metricas, limite=4):
    puntuables = [m for bloque in metricas.values() for m in bloque if _numero(m.get("puntuacion")) is not None]

    def resumir(metrica):
        valor = formatear_valor(metrica.get("valor"), metrica.get("tipo"))
        detalle = metrica.get("detalle") or ""
        return f"{metrica['titulo']}: {valor}. {detalle}".strip()

    fortalezas = [
        resumir(m)
        for m in sorted(puntuables, key=lambda m: m["puntuacion"], reverse=True)
        if m["puntuacion"] >= 70
    ][:limite]
    riesgos = [
        resumir(m)
        for m in sorted(puntuables, key=lambda m: m["puntuacion"])
        if m["puntuacion"] < 40
    ][:limite]
    return fortalezas, riesgos


def analizar_empresa(ticker, precios=None):
    """Devuelve una ficha value estable y tolerante a fallos para ``ticker``.

    Las puntuaciones solo se emiten para empresas. El timing de precio se obtiene
    por separado mediante :func:`calcular_contexto_precio` y no entra en el score.
    """
    ticker = str(ticker or "").strip()
    paquete = _descargar_paquete_yahoo(ticker)
    info = paquete["info"]
    historico = _construir_historico(paquete["income"], paquete["cashflow"], paquete["balance"])
    serie = _serie_precios(precios)
    if serie.empty and ticker:
        serie = descargar_precios_investigacion(ticker, "5y")

    moneda = str(_dato_info(info, "currency") or "").upper() or None
    moneda_financiera = str(_dato_info(info, "financialCurrency") or "").upper() or None
    moneda_incompatible = bool(moneda and moneda_financiera and moneda != moneda_financiera)
    metricas, aux = _metricas_fundamentales(info, historico, moneda_incompatible)
    if aux["precio"] is None and not serie.empty:
        aux["precio"] = float(serie.iloc[-1])
    if aux["market_cap"] is None and aux["precio"] is not None and aux["acciones"] is not None:
        aux["market_cap"] = aux["precio"] * aux["acciones"]
    aux["intereses_normalizados"] = _mediana(historico, "intereses")

    tipo = str(_dato_info(info, "quoteType") or "").upper()
    tipos_no_empresa = {"ETF", "MUTUALFUND", "INDEX", "CRYPTOCURRENCY", "CURRENCY", "FUTURE"}
    es_no_empresa = tipo in tipos_no_empresa
    tiene_estados = bool(historico)
    tipo_indeterminado = not tipo and not tiene_estados
    es_empresa = not es_no_empresa and (
        tipo in {"EQUITY", "STOCK"} or (not tipo and tiene_estados)
    )
    pilares, valor_score, cobertura = _calcular_pilares(metricas)
    if not es_empresa:
        valor_score, cobertura = None, 0.0
        for pilar in pilares:
            pilar["valor"] = None
            pilar["cobertura"] = 0.0

    fecha_estados = _extraer_fecha_estados(paquete["income"], paquete["cashflow"], paquete["balance"])
    avisos = []
    if moneda_incompatible:
        avisos.append(
            f"Yahoo mezcla cotización en {moneda} con estados en {moneda_financiera}; "
            "se excluyen ratios derivados y DCF."
        )
    elif not es_no_empresa and (not moneda or not moneda_financiera):
        avisos.append("No se ha podido validar por completo la moneda de cotización frente a la de los estados.")
    if not historico and not es_no_empresa:
        avisos.append("Yahoo no ha devuelto estados financieros anuales utilizables.")
    if paquete["errores"]:
        avisos.append(_aviso_error_yahoo(paquete["errores"]))
    if str(_dato_info(info, "sector") or "").lower() in {"financial services", "financials"}:
        avisos.append(
            "En entidades financieras, deuda/EBITDA y current ratio son menos representativos; "
            "conviene revisar CET1 y calidad crediticia fuera de Yahoo."
        )

    bloqueos = []
    if aux["nd_ebitda"] is not None and aux["nd_ebitda"] > 4:
        bloqueos.append("Deuda neta / EBITDA superior a 4x.")
    if aux["cobertura_intereses"] is not None and aux["cobertura_intereses"] < 2:
        bloqueos.append("Cobertura de intereses inferior a 2x.")
    ultimos_fcf = _valores(historico, "fcf", 2)
    if len(ultimos_fcf) == 2 and all(valor < 0 for valor in ultimos_fcf):
        bloqueos.append("FCF negativo en los dos últimos ejercicios.")
    if aux["cagr_acciones"] is not None and aux["cagr_acciones"] > .08:
        bloqueos.append("Dilución superior al 8% anual.")
    if (
        aux["ebitda_normalizado"] is not None and aux["ebitda_normalizado"] <= 0
        and aux["deuda_neta"] is not None and aux["deuda_neta"] > 0
    ):
        bloqueos.append("EBITDA no positivo con deuda neta positiva.")
    datos_antiguos = False
    if fecha_estados is not None:
        hoy = pd.Timestamp.now().normalize()
        fecha_comparable = fecha_estados.tz_localize(None) if fecha_estados.tzinfo is not None else fecha_estados
        datos_antiguos = (hoy - fecha_comparable.normalize()).days > 500
        if datos_antiguos:
            bloqueos.append("Los últimos estados anuales disponibles tienen más de 500 días.")
    if aux["patrimonio"] is not None and aux["patrimonio"] < 0:
        avisos.append("Patrimonio contable negativo: puede deberse a pérdidas o recompras y requiere revisión manual.")

    motivo_dcf = (
        "No hay datos suficientes para clasificar el instrumento."
        if tipo_indeterminado
        else "No aplicable a este tipo de instrumento."
    )
    dcf = _crear_dcf(aux, moneda, moneda_financiera, moneda_incompatible) if es_empresa else {
        "disponible": False, "escenarios": [], "supuestos": {},
        "motivo": motivo_dcf,
    }
    pilar_por_clave = {p["clave"]: p for p in pilares}
    cobertura_suficiente = (
        cobertura >= .70
        and pilar_por_clave["valoracion"]["cobertura"] >= .50
        and pilar_por_clave["solvencia"]["cobertura"] >= .50
    )
    if tipo_indeterminado:
        veredicto, color, confianza = "Datos insuficientes para clasificar el activo", COLOR_SIN_DATOS, "Baja"
    elif not es_empresa:
        veredicto, color, confianza = "No aplicable a fondos, ETF o índices", COLOR_SIN_DATOS, "No aplicable"
    elif not cobertura_suficiente:
        veredicto, color, confianza = "Sin conclusión fiable", COLOR_SIN_DATOS, "Baja"
    else:
        confianza = "Alta" if cobertura >= .85 and not datos_antiguos and not moneda_incompatible else "Media"
        if bloqueos:
            veredicto, color = "No encaja por riesgos críticos", COLOR_RIESGO
        elif valor_score is not None and valor_score >= 75 and pilar_por_clave["valoracion"]["valor"] >= 70:
            margen_base = next((e["margen"] for e in dcf["escenarios"] if e["nombre"] == "Base"), None)
            if margen_base is not None and margen_base >= .20:
                veredicto, color = "Candidata a compra", COLOR_FAVORABLE
            else:
                veredicto, color = "Atractiva; profundizar", COLOR_FAVORABLE
        elif valor_score is not None and valor_score >= 65:
            veredicto, color = "Atractiva; profundizar", COLOR_FAVORABLE
        elif valor_score is not None and valor_score >= 50:
            veredicto, color = "En seguimiento", COLOR_NEUTRAL
        elif valor_score is not None and valor_score >= 35:
            veredicto, color = "Poco atractiva ahora", COLOR_NEUTRAL
        else:
            veredicto, color = "No encaja", COLOR_RIESGO

    fortalezas, riesgos = _fortalezas_riesgos(metricas)
    empresa = {
        "ticker": ticker,
        "nombre": _dato_info(info, "longName", "shortName") or ticker,
        "tipo": tipo or ("UNKNOWN" if tipo_indeterminado else None),
        "sector": _dato_info(info, "sector"),
        "industria": _dato_info(info, "industry"),
        "pais": _dato_info(info, "country"),
        "moneda": moneda,
        "moneda_financiera": moneda_financiera,
        "precio": aux["precio"],
        "capitalizacion": aux["market_cap"],
        "enterprise_value": aux["enterprise_value"],
        "fecha_estados": fecha_estados.date().isoformat() if fecha_estados is not None else None,
        "web": _dato_info(info, "website"),
    }
    return {
        "empresa": empresa,
        "es_empresa": es_empresa,
        "clasificacion": "indeterminada" if tipo_indeterminado else ("empresa" if es_empresa else "no_empresa"),
        "score": {
            "valor": valor_score, "cobertura": cobertura,
            "veredicto": veredicto, "color": color, "confianza": confianza,
            "pilares": pilares,
        },
        "metricas": metricas,
        "fortalezas": fortalezas,
        "riesgos": riesgos,
        "bloqueos": bloqueos,
        "historico": historico,
        "dcf": dcf,
        "noticias": paquete["news"],
        "avisos": avisos,
        "fuente": "Fuente: Yahoo Finance vía yfinance · datos gratuitos sujetos a disponibilidad y retrasos.",
    }


def _rentabilidad_periodo(precios, sesiones):
    precios = _serie_precios(precios)
    if len(precios) <= sesiones:
        return None
    base, ultimo = _numero(precios.iloc[-sesiones - 1]), _numero(precios.iloc[-1])
    return ultimo / base - 1 if base not in (None, 0) and ultimo is not None else None


def _max_drawdown(precios):
    precios = _serie_precios(precios)
    if len(precios) < 2:
        return None
    return _numero((precios / precios.cummax() - 1).min())


def _distancia_media(precios, ventana):
    precios = _serie_precios(precios)
    if len(precios) < ventana:
        return None
    media = _numero(precios.tail(ventana).mean())
    return precios.iloc[-1] / media - 1 if media not in (None, 0) else None


def calcular_contexto_precio(precios, benchmark=None):
    """Métricas de entrada/mercado, explícitamente fuera del Value Score."""
    serie = _serie_precios(precios)
    avisos = []
    if isinstance(benchmark, str):
        ticker_benchmark = benchmark
        serie_benchmark = descargar_precios_investigacion(benchmark, "5y")
    else:
        ticker_benchmark = getattr(benchmark, "name", None)
        serie_benchmark = _serie_precios(benchmark)
    precio = _numero(serie.iloc[-1]) if not serie.empty else None
    tramo_52 = serie.tail(252)
    maximo = _numero(tramo_52.max()) if not tramo_52.empty else None
    minimo = _numero(tramo_52.min()) if not tramo_52.empty else None
    rent_diaria = serie.pct_change().replace([np.inf, -np.inf], np.nan).dropna().tail(252)
    volatilidad = _numero(rent_diaria.std() * np.sqrt(252)) if len(rent_diaria) >= 30 else None
    metricas = [
        _metrica("Precio actual", precio, "precio", None, 0, "Último cierre disponible.", "Referencia de mercado; fuera del score.", referencia=True),
        _metrica("Precio vs MM200", _distancia_media(serie, 200), "porcentaje", None, 0, "Distancia a la media de 200 sesiones.", "Contexto de tendencia, no de valor intrínseco.", referencia=True),
        _metrica("Distancia al máximo 52s", precio / maximo - 1 if precio is not None and maximo else None, "porcentaje", None, 0, "Distancia al máximo anual.", "Contexto del rango de cotización.", referencia=True),
        _metrica("Distancia al mínimo 52s", precio / minimo - 1 if precio is not None and minimo else None, "porcentaje", None, 0, "Distancia al mínimo anual.", "Contexto del rango de cotización.", referencia=True),
        _metrica("Rentabilidad 6M", _rentabilidad_periodo(serie, 126), "porcentaje", None, 0, "Aproximación de 126 sesiones.", "Momentum solo como contexto.", referencia=True),
        _metrica("Rentabilidad 1A", _rentabilidad_periodo(serie, 252), "porcentaje", None, 0, "Aproximación de 252 sesiones.", "Momentum solo como contexto.", referencia=True),
        _metrica("Volatilidad 1A", volatilidad, "porcentaje", None, 0, "Desviación anualizada de retornos diarios.", "Variabilidad de mercado, no riesgo empresarial por sí sola.", referencia=True),
        _metrica("Máximo drawdown 1A", _max_drawdown(tramo_52), "porcentaje", None, 0, "Mayor caída desde máximos del último año.", "Comportamiento de precio fuera del score.", referencia=True),
    ]
    if not serie.empty and not serie_benchmark.empty:
        alineados = pd.concat([serie.rename("activo"), serie_benchmark.rename("benchmark")], axis=1).dropna()
        exceso = None
        if len(alineados) > 126:
            activo_6m = _rentabilidad_periodo(alineados["activo"], 126)
            bench_6m = _rentabilidad_periodo(alineados["benchmark"], 126)
            if activo_6m is not None and bench_6m is not None:
                exceso = activo_6m - bench_6m
        metricas.append(_metrica(
            "Exceso vs benchmark 6M (sin FX)", exceso, "porcentaje", None, 0,
            f"Frente a {ticker_benchmark or 'benchmark'}, sin convertir monedas.",
            "Fuerza relativa orientativa: puede incluir el efecto divisa y queda fuera del score.",
            referencia=True,
        ))
        avisos.append("La comparación con el benchmark se muestra sin ajustar el posible efecto divisa.")
    elif benchmark is not None:
        avisos.append("No hay histórico común suficiente con el benchmark.")
    return {
        "metricas": metricas,
        "precio_actual": precio,
        "fecha": serie.index[-1].date().isoformat() if not serie.empty and hasattr(serie.index[-1], "date") else None,
        "benchmark": ticker_benchmark,
        "fuera_score": True,
        "avisos": avisos,
    }


def crear_grafico_precio(
    precios,
    ticker,
    nombre,
    precios_medias=None,
    valor_razonable=None,
    fair_value=None,
    moneda=None,
):
    """Gráfico de precio con medias y valor(es) razonable(s) opcionales."""
    serie = _serie_precios(precios)
    serie_medias = _serie_precios(precios_medias) if precios_medias is not None else serie
    fig = go.Figure()
    if serie.empty:
        fig.update_layout(
            title=f"{nombre} ({ticker})", template="plotly_white", height=480,
            annotations=[dict(
                text="No hay precios disponibles", x=.5, y=.5,
                xref="paper", yref="paper", showarrow=False,
            )],
        )
        return fig
    fig.add_trace(go.Scatter(
        x=serie.index, y=serie, mode="lines", name="Precio",
        line={"width": 2.6, "color": "#2563eb"},
    ))
    for ventana, color in ((50, "#f59e0b"), (200, "#64748b")):
        media = serie_medias.rolling(ventana).mean().reindex(serie.index)
        fig.add_trace(go.Scatter(
            x=media.index, y=media, mode="lines", name=f"MM{ventana}",
            line={"width": 1.3, "color": color},
        ))

    razonable = fair_value if fair_value is not None else valor_razonable
    if isinstance(razonable, dict):
        escenarios = razonable.get("escenarios") or []
        if not escenarios and _numero(razonable.get("valor")) is not None:
            escenarios = [{"nombre": "razonable", "valor": razonable["valor"], "color": "#16a34a"}]
    elif isinstance(razonable, (list, tuple)):
        escenarios = razonable
    elif _numero(razonable) is not None:
        escenarios = [{"nombre": "razonable", "valor": razonable, "color": "#16a34a"}]
    else:
        escenarios = []
    for escenario in escenarios:
        valor = _numero(escenario.get("valor") if isinstance(escenario, dict) else None)
        if valor is None:
            continue
        fig.add_trace(go.Scatter(
            x=[serie.index[0], serie.index[-1]], y=[valor, valor], mode="lines",
            name=f"Valor {escenario.get('nombre', 'razonable')}",
            line={"width": 1.4, "dash": "dot", "color": escenario.get("color", "#16a34a")},
        ))
    fig.update_layout(
        title={"text": f"{nombre} ({ticker})", "x": .03, "xanchor": "left"},
        template="plotly_white", height=500,
        margin={"l": 42, "r": 24, "t": 72, "b": 36}, hovermode="x unified",
        legend={"orientation": "h", "y": 1.03, "x": 1, "xanchor": "right", "yanchor": "bottom"},
        yaxis_title=f"Precio ({moneda})" if moneda else "Precio",
    )
    return fig


def formatear_compacto(valor, decimales=1):
    numero = _numero(valor)
    if numero is None:
        return DATO_NO_DISPONIBLE
    signo = "-" if numero < 0 else ""
    absoluto = abs(numero)
    for divisor, sufijo in ((1e12, "B"), (1e9, "mil M"), (1e6, "M"), (1e3, "mil")):
        if absoluto >= divisor:
            return f"{signo}{absoluto / divisor:,.{decimales}f} {sufijo}"
    return f"{numero:,.{decimales}f}"


compacto = formatear_compacto


def formatear_valor(valor, tipo=None, moneda=None):
    if valor is None or valor == DATO_NO_DISPONIBLE:
        return DATO_NO_DISPONIBLE
    if tipo == "texto":
        return str(valor) if str(valor).strip() else DATO_NO_DISPONIBLE
    if tipo == "fecha":
        try:
            return pd.Timestamp(valor).strftime("%d/%m/%Y")
        except Exception:
            return str(valor)
    numero = _numero(valor)
    if numero is None:
        return DATO_NO_DISPONIBLE
    if tipo == "porcentaje":
        return f"{numero * 100:,.2f}%"
    if tipo == "puntos_porcentuales":
        return f"{numero * 100:+,.2f} pp"
    if tipo in {"multiplo", "multiple", "ratio", "veces"}:
        return f"{numero:,.2f}x"
    if tipo in {"compacto", "moneda_compacta"}:
        texto = formatear_compacto(numero)
        return f"{texto} {moneda}" if moneda else texto
    if tipo == "entero":
        return f"{numero:,.0f}"
    if tipo == "piotroski":
        return f"{numero:.0f} puntos"
    if tipo == "fraccion":
        return f"{numero:.0f}"
    if tipo in {"precio", "moneda"}:
        texto = f"{numero:,.2f}"
        return f"{texto} {moneda}" if moneda else texto
    return f"{numero:,.2f}"


# Compatibilidad temporal con consumidores antiguos. La nueva página utiliza
# analizar_empresa y calcular_contexto_precio directamente.
def calcular_metricas_activo(precios):
    return calcular_contexto_precio(precios)["metricas"]


def calcular_metricas_relativas(precios, benchmark):
    contexto = calcular_contexto_precio(precios, benchmark)
    return [m for m in contexto["metricas"] if "benchmark" in m["titulo"].lower()]


def obtener_fundamentales(ticker):
    resultado = analizar_empresa(ticker, descargar_precios_investigacion(ticker, "5y"))
    return [metrica for bloque in resultado["metricas"].values() for metrica in bloque]


@_ttl_cache(ttl=CACHE_TTL_SEGUNDOS, maxsize=1)
def calcular_metricas_macro():
    # El macro genérico se retira: no es parte de un análisis bottom-up.
    return []


def calcular_flags_inversion(metricas_activo, metricas_relativas, metricas_fundamentales, metricas_macro):
    return []
