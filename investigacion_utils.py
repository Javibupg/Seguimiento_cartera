from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf

from cache_precios import cargar_cierres


EXCEL_PATH = Path("Libro_inversiones.xlsx")
DATO_NO_DISPONIBLE = "Dato no disponible"


def _es_si(valor):
    if pd.isna(valor):
        return False
    return str(valor).strip().lower() in {"si", "sí", "s", "yes", "y", "true", "1"}


def cargar_activos_investigacion(path=EXCEL_PATH):
    try:
        df = pd.read_excel(path, sheet_name="Listado de activos")
    except Exception:
        return pd.DataFrame(columns=["Ticker", "Nombre", "Seguimiento", "Benchmark"])

    df.columns = df.columns.str.strip()

    for col in ["Ticker", "Nombre", "Seguimiento", "Benchmark"]:
        if col not in df.columns:
            df[col] = pd.NA

    df = df[["Ticker", "Nombre", "Seguimiento", "Benchmark"]].copy()
    df["Ticker"] = df["Ticker"].fillna("").astype(str).str.strip()
    df["Nombre"] = df["Nombre"].fillna(df["Ticker"]).astype(str).str.strip()
    df["Benchmark"] = df["Benchmark"].where(df["Benchmark"].notna(), None)
    df["Benchmark"] = df["Benchmark"].map(
        lambda x: str(x).strip() if x is not None and str(x).strip() else None
    )
    df = df[df["Ticker"].ne("") & df["Seguimiento"].map(_es_si)]
    return df.reset_index(drop=True)


def opciones_activos_investigacion(activos):
    if activos.empty:
        return []
    return [
        {"label": f"{row.Nombre} ({row.Ticker})", "value": row.Ticker}
        for row in activos.itertuples(index=False)
    ]


def obtener_activo(activos, ticker):
    if activos.empty:
        return {"Ticker": ticker, "Nombre": ticker, "Benchmark": None}

    fila = activos[activos["Ticker"].eq(ticker)]
    if fila.empty:
        fila = activos.iloc[[0]]
    return fila.iloc[0].to_dict()


@lru_cache(maxsize=128)
def descargar_precios_investigacion(ticker, periodo="5y"):
    if not ticker:
        return pd.Series(dtype="float64")
    return cargar_cierres(ticker, period=periodo)


def _rentabilidad_periodo(precios, sesiones):
    precios = precios.dropna()
    if len(precios) <= sesiones:
        return None
    base = precios.iloc[-sesiones]
    if pd.isna(base) or base == 0:
        return None
    return float(precios.iloc[-1] / base - 1)


def _rentabilidad_ytd(precios):
    precios = precios.dropna()
    if precios.empty:
        return None

    precios_ytd = precios[precios.index.year == precios.index[-1].year]
    if len(precios_ytd) < 2 or precios_ytd.iloc[0] == 0:
        return None
    return float(precios_ytd.iloc[-1] / precios_ytd.iloc[0] - 1)


def _max_drawdown(precios):
    precios = precios.dropna()
    if len(precios) < 2 or precios.iloc[0] == 0:
        return None

    base = precios / precios.iloc[0]
    drawdown = base / base.cummax() - 1
    return float(drawdown.min())


def _rsi(precios, periodo=14):
    precios = precios.dropna()
    if len(precios) <= periodo + 1:
        return None

    delta = precios.diff()
    ganancias = delta.clip(lower=0).rolling(periodo).mean()
    perdidas = -delta.clip(upper=0).rolling(periodo).mean()
    rs = ganancias / perdidas.replace(0, np.nan)
    rsi = 100 - 100 / (1 + rs)
    rsi = rsi.dropna()
    return None if rsi.empty else float(rsi.iloc[-1])


def _distancia_a_media(precios, ventana):
    precios = precios.dropna()
    if len(precios) < ventana:
        return None

    media = precios.rolling(ventana).mean().dropna()
    if media.empty or media.iloc[-1] == 0:
        return None
    return float(precios.iloc[-1] / media.iloc[-1] - 1)


def calcular_metricas_activo(precios):
    precios = precios.dropna()
    if precios.empty:
        return [
            {"titulo": "Precio actual", "valor": None, "tipo": "precio"},
            {"titulo": "Precio vs MM50", "valor": None, "tipo": "porcentaje"},
            {"titulo": "Precio vs MM200", "valor": None, "tipo": "porcentaje"},
        ]

    precio = float(precios.iloc[-1])
    ult_252 = precios.tail(252)
    max_52s = float(ult_252.max()) if not ult_252.empty else None
    min_52s = float(ult_252.min()) if not ult_252.empty else None
    rent_diaria = precios.pct_change().dropna().tail(252)
    volatilidad = float(rent_diaria.std() * np.sqrt(252)) if len(rent_diaria) > 30 else None

    return [
        {"titulo": "Precio actual", "valor": precio, "tipo": "precio"},
        {"titulo": "Precio vs MM50", "valor": _distancia_a_media(precios, 50), "tipo": "porcentaje"},
        {"titulo": "Precio vs MM200", "valor": _distancia_a_media(precios, 200), "tipo": "porcentaje"},
        {
            "titulo": "Distancia a max. 52s",
            "valor": precio / max_52s - 1 if max_52s else None,
            "tipo": "porcentaje",
        },
        {
            "titulo": "Distancia a min. 52s",
            "valor": precio / min_52s - 1 if min_52s else None,
            "tipo": "porcentaje",
        },
        {"titulo": "Rentabilidad 1M", "valor": _rentabilidad_periodo(precios, 21), "tipo": "porcentaje"},
        {"titulo": "Rentabilidad 3M", "valor": _rentabilidad_periodo(precios, 63), "tipo": "porcentaje"},
        {"titulo": "Rentabilidad 6M", "valor": _rentabilidad_periodo(precios, 126), "tipo": "porcentaje"},
        {"titulo": "Rentabilidad YTD", "valor": _rentabilidad_ytd(precios), "tipo": "porcentaje"},
        {"titulo": "Rentabilidad 1A", "valor": _rentabilidad_periodo(precios, 252), "tipo": "porcentaje"},
        {"titulo": "Volatilidad 1A", "valor": volatilidad, "tipo": "porcentaje"},
        {"titulo": "Max drawdown 1A", "valor": _max_drawdown(precios.tail(252)), "tipo": "porcentaje"},
        {"titulo": "RSI 14", "valor": _rsi(precios), "tipo": "numero"},
    ]


def calcular_metricas_relativas(precios, benchmark):
    if not benchmark:
        return [{"titulo": "Benchmark", "valor": None, "tipo": "texto", "detalle": "No indicado en el Excel"}]

    precios_benchmark = descargar_precios_investigacion(benchmark)
    datos = pd.concat(
        [precios.rename("activo"), precios_benchmark.rename("benchmark")],
        axis=1,
    ).dropna()

    if len(datos) < 30:
        return [{"titulo": "Benchmark", "valor": benchmark, "tipo": "texto", "detalle": "Sin histórico suficiente"}]

    rent = datos.pct_change().dropna().tail(252)
    beta = None
    correlacion = None

    if len(rent) > 30 and rent["benchmark"].var() != 0:
        beta = float(rent["activo"].cov(rent["benchmark"]) / rent["benchmark"].var())
        correlacion = float(rent["activo"].corr(rent["benchmark"]))

    def exceso(sesiones):
        r_activo = _rentabilidad_periodo(datos["activo"], sesiones)
        r_benchmark = _rentabilidad_periodo(datos["benchmark"], sesiones)
        if r_activo is None or r_benchmark is None:
            return None
        return r_activo - r_benchmark

    ratio = datos["activo"] / datos["benchmark"]

    return [
        {"titulo": "Benchmark", "valor": benchmark, "tipo": "texto"},
        {"titulo": "Exceso 1M", "valor": exceso(21), "tipo": "porcentaje"},
        {"titulo": "Exceso 3M", "valor": exceso(63), "tipo": "porcentaje"},
        {"titulo": "Exceso 6M", "valor": exceso(126), "tipo": "porcentaje"},
        {"titulo": "Exceso 1A", "valor": exceso(252), "tipo": "porcentaje"},
        {"titulo": "Beta 1A", "valor": beta, "tipo": "numero"},
        {"titulo": "Correlación 1A", "valor": correlacion, "tipo": "numero"},
        {"titulo": "Fuerza relativa 6M", "valor": _rentabilidad_periodo(ratio, 126), "tipo": "porcentaje"},
    ]


@lru_cache(maxsize=128)
def obtener_fundamentales(ticker):
    try:
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.get_info() if hasattr(ticker_obj, "get_info") else ticker_obj.info
    except Exception:
        ticker_obj = None
        info = {}

    def dato(campo):
        valor = info.get(campo)
        if valor in (None, ""):
            return None
        if isinstance(valor, float) and (pd.isna(valor) or np.isinf(valor)):
            return None
        return valor

    def porcentaje_yahoo(campo):
        valor = dato(campo)
        if valor is None:
            return None

        return float(valor)

    def precio_actual():
        for campo in ["currentPrice", "regularMarketPrice", "previousClose"]:
            valor = dato(campo)
            if valor is not None and float(valor) > 0:
                return float(valor)
        precios = descargar_precios_investigacion(ticker, "5d")
        return None if precios.empty else float(precios.iloc[-1])

    def dividend_yield_real():
        precio = precio_actual()
        if precio is None or precio <= 0 or ticker_obj is None:
            return None

        dividendo_anual_info = dato("dividendRate")
        try:
            dividendo_anual_info = None if dividendo_anual_info is None else float(dividendo_anual_info)
        except (TypeError, ValueError):
            dividendo_anual_info = None

        if dividendo_anual_info is not None and dividendo_anual_info > 0:
            return dividendo_anual_info / precio

        try:
            dividendos = ticker_obj.dividends
        except Exception:
            return None

        if dividendos is None or dividendos.empty:
            return None

        dividendos = dividendos.copy()
        dividendos.index = pd.to_datetime(dividendos.index)
        if getattr(dividendos.index, "tz", None) is not None:
            dividendos.index = dividendos.index.tz_localize(None)

        if dividendos.empty:
            return None

        fecha_inicio = pd.Timestamp.today().normalize() - pd.DateOffset(months=18)
        dividendos_recientes = dividendos[dividendos.index >= fecha_inicio]

        if len(dividendos_recientes) >= 2:
            frecuencia = min(max(round(len(dividendos_recientes) / 1.5), 1), 12)
        else:
            fecha_inicio = pd.Timestamp.today().normalize() - pd.DateOffset(years=3)
            dividendos_recientes = dividendos[dividendos.index >= fecha_inicio]
            frecuencia = min(max(round(len(dividendos_recientes) / 3), 1), 12) if len(dividendos_recientes) >= 2 else 1

        dividendo_anualizado = float(dividendos.iloc[-1]) * frecuencia
        return dividendo_anualizado / precio if dividendo_anualizado > 0 else None

    return [
        {"titulo": "PER trailing", "valor": dato("trailingPE"), "tipo": "numero"},
        {"titulo": "PER forward", "valor": dato("forwardPE"), "tipo": "numero"},
        {"titulo": "Price / Book", "valor": dato("priceToBook"), "tipo": "numero"},
        {"titulo": "EV / EBITDA", "valor": dato("enterpriseToEbitda"), "tipo": "numero"},
        {"titulo": "Dividend yield", "valor": dividend_yield_real(), "tipo": "porcentaje"},
        {"titulo": "Margen neto", "valor": porcentaje_yahoo("profitMargins"), "tipo": "porcentaje"},
        {"titulo": "ROE", "valor": porcentaje_yahoo("returnOnEquity"), "tipo": "porcentaje"},
        {"titulo": "Crecimiento ingresos", "valor": porcentaje_yahoo("revenueGrowth"), "tipo": "porcentaje"},
    ]


@lru_cache(maxsize=1)
def calcular_metricas_macro():
    indicadores = [
        ("^VIX", "VIX", "numero"),
        ("^TNX", "Bono USA 10Y", "tnx"),
        ("EURUSD=X", "EUR/USD", "numero"),
        ("BZ=F", "Brent", "numero"),
    ]

    metricas = []
    for ticker, nombre, tipo_indicador in indicadores:
        precios = descargar_precios_investigacion(ticker, "6mo")

        if precios.empty:
            metricas.append({"titulo": nombre, "valor": None, "tipo": "numero"})
            continue

        detalle = None
        variacion_1m = _rentabilidad_periodo(precios, 21)
        if variacion_1m is not None:
            detalle = f"1M: {formatear_valor(variacion_1m, 'porcentaje')}"

        valor = float(precios.iloc[-1])
        tipo = "numero"
        if tipo_indicador == "tnx":
            # Yahoo publica ^TNX como yield * 10. Se muestra como porcentaje real.
            valor = valor / 1000
            tipo = "porcentaje"

        metricas.append(
            {
                "titulo": nombre,
                "valor": valor,
                "tipo": tipo,
                "detalle": detalle,
            }
        )

    return metricas


def _valor_metrica(metricas, titulo):
    for metrica in metricas:
        if metrica.get("titulo") == titulo:
            valor = metrica.get("valor")
            if valor is None:
                return None
            try:
                if pd.isna(valor) or np.isinf(valor):
                    return None
            except TypeError:
                pass
            return valor
    return None


def _estado_desde_puntuacion(puntuacion):
    if puntuacion >= 1.5:
        return "Riesgo alto"
    if puntuacion >= 0.75:
        return "Vigilar"
    return "Normal"


def _color_estado(estado):
    if estado == "Riesgo alto":
        return "#dc2626"
    if estado == "Vigilar":
        return "#d97706"
    if estado == "Oportunidad":
        return "#2563eb"
    return "#16a34a"


def _media_puntuaciones(puntuaciones):
    puntuaciones = [p for p in puntuaciones if p is not None]
    if not puntuaciones:
        return None
    return float(sum(puntuaciones) / len(puntuaciones))


def _puntuacion_valoracion(metricas_fundamentales):
    puntuaciones = []
    detalles = []

    per_forward = _valor_metrica(metricas_fundamentales, "PER forward")
    per_trailing = _valor_metrica(metricas_fundamentales, "PER trailing")
    ev_ebitda = _valor_metrica(metricas_fundamentales, "EV / EBITDA")
    price_book = _valor_metrica(metricas_fundamentales, "Price / Book")

    per = per_forward if per_forward is not None else per_trailing
    if per is not None and per > 0:
        if per >= 35:
            puntuaciones.append(2)
            detalles.append("PER elevado")
        elif per >= 25:
            puntuaciones.append(1)
            detalles.append("PER exigente")
        elif per <= 15:
            puntuaciones.append(0)
            detalles.append("PER razonable")
        else:
            puntuaciones.append(0)
            detalles.append("PER moderado")

    if ev_ebitda is not None and ev_ebitda > 0:
        if ev_ebitda >= 25:
            puntuaciones.append(2)
            detalles.append("EV/EBITDA elevado")
        elif ev_ebitda >= 16:
            puntuaciones.append(1)
            detalles.append("EV/EBITDA exigente")
        elif ev_ebitda <= 10:
            puntuaciones.append(0)
            detalles.append("EV/EBITDA razonable")
        else:
            puntuaciones.append(0)
            detalles.append("EV/EBITDA moderado")

    if price_book is not None and price_book > 0:
        if price_book >= 10:
            puntuaciones.append(2)
            detalles.append("Price/Book alto")
        elif price_book >= 5:
            puntuaciones.append(1)
            detalles.append("Price/Book exigente")
        elif price_book <= 3:
            puntuaciones.append(0)
            detalles.append("Price/Book moderado")
        else:
            puntuaciones.append(0)
            detalles.append("Price/Book medio")

    puntuacion = _media_puntuaciones(puntuaciones)
    if puntuacion is None:
        return None, "Sin suficientes datos de valoración."

    return puntuacion, ". ".join(detalles[:3]) or "Valoración sin señales extremas."


def _puntuacion_tendencia(metricas_activo):
    puntuaciones = []
    detalles = []

    mm50 = _valor_metrica(metricas_activo, "Precio vs MM50")
    mm200 = _valor_metrica(metricas_activo, "Precio vs MM200")
    rsi = _valor_metrica(metricas_activo, "RSI 14")
    drawdown = _valor_metrica(metricas_activo, "Max drawdown 1A")

    if mm200 is not None:
        if mm200 <= -0.08:
            puntuaciones.append(2)
            detalles.append("por debajo de MM200")
        elif mm200 < 0:
            puntuaciones.append(1)
            detalles.append("ligeramente bajo MM200")
        elif mm200 >= 0.25:
            puntuaciones.append(1)
            detalles.append("muy extendido sobre MM200")
        else:
            puntuaciones.append(0)
            detalles.append("por encima de MM200")

    if mm50 is not None:
        if mm50 <= -0.06:
            puntuaciones.append(1)
            detalles.append("debilidad frente a MM50")
        elif mm50 >= 0.12:
            puntuaciones.append(1)
            detalles.append("sobreextensión frente a MM50")
        else:
            puntuaciones.append(0)

    if rsi is not None:
        if rsi >= 75:
            puntuaciones.append(2)
            detalles.append("RSI sobrecomprado")
        elif rsi >= 65:
            puntuaciones.append(1)
            detalles.append("RSI alto")
        elif rsi <= 30:
            puntuaciones.append(1)
            detalles.append("RSI débil")
        else:
            puntuaciones.append(0)

    if drawdown is not None:
        if drawdown <= -0.30:
            puntuaciones.append(2)
            detalles.append("drawdown profundo")
        elif drawdown <= -0.15:
            puntuaciones.append(1)
            detalles.append("drawdown relevante")
        else:
            puntuaciones.append(0)

    puntuacion = _media_puntuaciones(puntuaciones)
    if puntuacion is None:
        return None, "Sin suficientes datos técnicos."

    return puntuacion, ". ".join(detalles[:3]) or "Tendencia sin señales extremas."


def _puntuacion_relativa(metricas_relativas):
    puntuaciones = []
    detalles = []

    exceso_6m = _valor_metrica(metricas_relativas, "Exceso 6M")
    exceso_1a = _valor_metrica(metricas_relativas, "Exceso 1A")
    fuerza_6m = _valor_metrica(metricas_relativas, "Fuerza relativa 6M")

    for titulo, valor in [
        ("exceso 6M", exceso_6m),
        ("exceso 1A", exceso_1a),
        ("fuerza relativa 6M", fuerza_6m),
    ]:
        if valor is None:
            continue
        if valor <= -0.08:
            puntuaciones.append(2)
            detalles.append(f"{titulo} débil")
        elif valor < 0:
            puntuaciones.append(1)
            detalles.append(f"{titulo} negativo")
        else:
            puntuaciones.append(0)

    puntuacion = _media_puntuaciones(puntuaciones)
    if puntuacion is None:
        return None, "Sin benchmark o histórico suficiente."

    if not detalles:
        detalles.append("mejor comportamiento que el benchmark")

    return puntuacion, ". ".join(detalles[:3])


def _puntuacion_macro(metricas_macro):
    puntuaciones = []
    detalles = []

    vix = _valor_metrica(metricas_macro, "VIX")
    bono_10y = _valor_metrica(metricas_macro, "Bono USA 10Y")
    brent = _valor_metrica(metricas_macro, "Brent")

    if vix is not None:
        if vix >= 30:
            puntuaciones.append(2)
            detalles.append("VIX alto")
        elif vix >= 20:
            puntuaciones.append(1)
            detalles.append("VIX en zona de vigilancia")
        else:
            puntuaciones.append(0)
            detalles.append("VIX contenido")

    if bono_10y is not None:
        if bono_10y >= 0.05:
            puntuaciones.append(2)
            detalles.append("tipos largos muy altos")
        elif bono_10y >= 0.0425:
            puntuaciones.append(1)
            detalles.append("tipos largos exigentes")
        else:
            puntuaciones.append(0)

    if brent is not None:
        if brent >= 100:
            puntuaciones.append(2)
            detalles.append("Brent alto")
        elif brent >= 90:
            puntuaciones.append(1)
            detalles.append("Brent en vigilancia")
        else:
            puntuaciones.append(0)

    puntuacion = _media_puntuaciones(puntuaciones)
    if puntuacion is None:
        return None, "Sin suficientes datos macro."

    return puntuacion, ". ".join(detalles[:3]) or "Macro sin señales extremas."


def calcular_flags_inversion(metricas_activo, metricas_relativas, metricas_fundamentales, metricas_macro):
    categorias = []

    for titulo, funcion, metricas in [
        ("Valoración", _puntuacion_valoracion, metricas_fundamentales),
        ("Tendencia", _puntuacion_tendencia, metricas_activo),
        ("Fuerza relativa", _puntuacion_relativa, metricas_relativas),
        ("Riesgo macro", _puntuacion_macro, metricas_macro),
    ]:
        puntuacion, detalle = funcion(metricas)
        estado = "Sin datos" if puntuacion is None else _estado_desde_puntuacion(puntuacion)
        categorias.append(
            {
                "titulo": titulo,
                "estado": estado,
                "puntuacion": puntuacion,
                "detalle": detalle,
                "color": "#6b7280" if puntuacion is None else _color_estado(estado),
            }
        )

    puntuaciones = [flag["puntuacion"] for flag in categorias if flag["puntuacion"] is not None]
    puntuacion_total = _media_puntuaciones(puntuaciones)

    mm200 = _valor_metrica(metricas_activo, "Precio vs MM200")
    rsi = _valor_metrica(metricas_activo, "RSI 14")
    puntuacion_valoracion = categorias[0]["puntuacion"]
    toma_beneficios = (
        puntuacion_valoracion is not None
        and puntuacion_valoracion >= 1
        and mm200 is not None
        and mm200 >= 0.15
        and rsi is not None
        and rsi >= 65
    )

    if puntuacion_total is None:
        estado_total = "Sin datos"
        detalle_total = "No hay datos suficientes para generar una señal agregada."
        color_total = "#6b7280"
    elif toma_beneficios:
        estado_total = "Posible toma de beneficios"
        detalle_total = "Coinciden valoración exigente, precio extendido sobre MM200 y RSI alto."
        color_total = "#d97706"
    elif puntuacion_total >= 1.5:
        estado_total = "Riesgo alto"
        detalle_total = "Varias categorías están en rojo. Conviene revisar la posición antes de ampliar."
        color_total = "#dc2626"
    elif puntuacion_total >= 0.75:
        estado_total = "Vigilar"
        detalle_total = "Hay señales mixtas. Mantener seguimiento antes de tomar una decisión."
        color_total = "#d97706"
    else:
        estado_total = "Normal"
        detalle_total = "No aparecen señales agregadas de riesgo elevado."
        color_total = "#16a34a"

    return [
        {
            "titulo": "Señal agregada",
            "estado": estado_total,
            "puntuacion": puntuacion_total,
            "detalle": detalle_total,
            "color": color_total,
        },
        *categorias,
    ]


def crear_grafico_precio(precios, ticker, nombre, precios_medias=None):
    fig = go.Figure()
    precios = precios.dropna()
    precios_medias = precios if precios_medias is None else precios_medias.dropna()

    if precios.empty:
        fig.update_layout(
            title=f"{nombre} ({ticker})",
            template="plotly_white",
            height=620,
            annotations=[
                {
                    "text": "No hay datos de precio disponibles",
                    "xref": "paper",
                    "yref": "paper",
                    "x": 0.5,
                    "y": 0.5,
                    "showarrow": False,
                    "font": {"size": 16, "color": "#6b7280"},
                }
            ],
        )
        return fig

    media_50 = precios_medias.rolling(50).mean().reindex(precios.index)
    media_200 = precios_medias.rolling(200).mean().reindex(precios.index)

    fig.add_trace(
        go.Scatter(
            x=precios.index,
            y=precios,
            mode="lines",
            name="Precio",
            line={"width": 2.6, "color": "#2563eb"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=media_50.index,
            y=media_50,
            mode="lines",
            name="MM50",
            line={"width": 1.5, "color": "#f59e0b"},
        )
    )
    fig.add_trace(
        go.Scatter(
            x=media_200.index,
            y=media_200,
            mode="lines",
            name="MM200",
            line={"width": 1.5, "color": "#64748b"},
        )
    )

    fig.update_layout(
        title={"text": f"{nombre} ({ticker})", "x": 0.05, "xanchor": "left"},
        template="plotly_white",
        height=620,
        margin=dict(l=40, r=40, t=90, b=40),
        hovermode="x unified",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1,
        ),
        xaxis=dict(
            rangeselector=dict(
                buttons=[
                    dict(count=1, label="1M", step="month", stepmode="backward"),
                    dict(count=6, label="6M", step="month", stepmode="backward"),
                    dict(count=1, label="1A", step="year", stepmode="backward"),
                    dict(count=5, label="5A", step="year", stepmode="backward"),
                    dict(step="all", label="Máx"),
                ]
            )
        ),
        yaxis_title="Precio",
    )
    return fig


def formatear_valor(valor, tipo=None):
    if valor is None or valor == DATO_NO_DISPONIBLE:
        return DATO_NO_DISPONIBLE
    if isinstance(valor, float) and (pd.isna(valor) or np.isinf(valor)):
        return DATO_NO_DISPONIBLE

    if tipo == "texto":
        return str(valor) if valor else DATO_NO_DISPONIBLE
    if tipo == "porcentaje":
        return f"{float(valor) * 100:,.2f}%"
    if tipo == "precio":
        return f"{float(valor):,.2f}"
    if tipo == "numero":
        return f"{float(valor):,.2f}"
    if isinstance(valor, (int, float, np.number)):
        return f"{float(valor):,.2f}"
    return str(valor)
