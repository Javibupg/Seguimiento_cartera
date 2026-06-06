from pathlib import Path
import json
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

import pandas as pd

EXCEL_PATH = Path("Libro_inversiones.xlsx")
MONEDAS_SOPORTADAS = {"EUR", "USD"}
SUFIJOS_EUR = (".MI", ".PA", ".MC", ".DE", ".AS", ".BR", ".VI", ".F", ".MU", ".BE", ".HM", ".DU")
FX_FALLBACK_USDEUR = 0.92
VERSION_CODIGO = "posiciones_v5_grafico_activos_rebase_eventos"
print(f"[Dashboard inversiones] {VERSION_CODIGO} cargado desde {Path(__file__).resolve()}")


def _limpiar_texto(s):
    return s.astype(str).str.lower().str.strip()


def _sin_inf(s):
    return s.replace([float("inf"), -float("inf")], 0).fillna(0)


def _inferir_divisa_activo(activo):
    ticker = str(activo).upper().strip()
    return "EUR" if ticker.endswith(SUFIJOS_EUR) else "USD"


def _normalizar_divisas(df, default="USD", inferir_por_activo=False):
    df = df.copy()

    if "Currency" not in df.columns and "Divisa" in df.columns:
        df["Currency"] = df["Divisa"]

    if "Currency" not in df.columns:
        if inferir_por_activo and "Activo" in df.columns:
            df["Currency"] = df["Activo"].map(_inferir_divisa_activo)
        else:
            df["Currency"] = default

    df["Currency"] = df["Currency"].fillna(default).astype(str).str.upper().str.strip()

    no_soportadas = sorted(set(df["Currency"].dropna()) - MONEDAS_SOPORTADAS)
    if no_soportadas:
        raise ValueError(
            "Ahora mismo la app solo soporta activos/cash en EUR y USD. "
            f"Divisas encontradas no soportadas: {no_soportadas}."
        )

    return df


def _preparar_tipo_cambio_eur(df):
    df = df.copy()

    if "Tipo_cambio_EUR" not in df.columns:
        df["Tipo_cambio_EUR"] = pd.NA

    df["Tipo_cambio_EUR"] = pd.to_numeric(df["Tipo_cambio_EUR"], errors="coerce")
    df.loc[df["Currency"] == "EUR", "Tipo_cambio_EUR"] = df.loc[df["Currency"] == "EUR", "Tipo_cambio_EUR"].fillna(1.0)

    return df


def cargar_operaciones(path=EXCEL_PATH):
    df = pd.read_excel(path, sheet_name="Operaciones")
    df.columns = df.columns.str.strip()
    df["Activo"] = df["Activo"].astype(str).str.strip()
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    df["Orden"] = _limpiar_texto(df["Orden"])
    df["signo"] = df["Orden"].map({"compra": 1, "venta": -1})

    if df["signo"].isna().any():
        raise ValueError("Hay operaciones distintas de 'compra' o 'venta' en la hoja Operaciones.")

    df = _normalizar_divisas(df, default="USD", inferir_por_activo=True)
    df = _preparar_tipo_cambio_eur(df)

    df["Numero_acciones"] = pd.to_numeric(df["Numero_acciones"], errors="coerce")
    df["Precio_ejecutado"] = pd.to_numeric(df["Precio_ejecutado"], errors="coerce")
    df["acciones_firmadas"] = df["Numero_acciones"] * df["signo"]

    # Importe en la divisa original de cada activo.
    df["Importe"] = df["Numero_acciones"] * df["Precio_ejecutado"]

    # Importe en EUR. Para activos USD, Tipo_cambio_EUR debe ser USD->EUR.
    df["Importe_EUR"] = df["Importe"] * df["Tipo_cambio_EUR"]

    return df.sort_values("Fecha").reset_index(drop=True)


def cargar_movimientos_cash(path=EXCEL_PATH):
    cash = pd.read_excel(path, sheet_name="Cash")
    cash.columns = cash.columns.str.strip()
    cash["Fecha"] = pd.to_datetime(cash["Fecha"])
    cash["Tipo"] = _limpiar_texto(cash["Tipo"])
    cash["signo"] = cash["Tipo"].map({"aportación": 1, "aportacion": 1, "retirada": -1})

    if cash["signo"].isna().any():
        raise ValueError("Hay movimientos distintos de 'aportación' o 'retirada' en la hoja Cash.")

    if "Currency" not in cash.columns and "Divisa" not in cash.columns:
        if "Tipo_cambio_EUR" in cash.columns:
            tipo = pd.to_numeric(cash["Tipo_cambio_EUR"], errors="coerce")
            cash["Currency"] = tipo.map(lambda x: "EUR" if pd.notna(x) and abs(x - 1.0) < 1e-12 else "USD")
        else:
            cash["Currency"] = "EUR"

    cash = _normalizar_divisas(cash, default="EUR", inferir_por_activo=False)
    cash = _preparar_tipo_cambio_eur(cash)

    cash["Importe"] = pd.to_numeric(cash["Importe"], errors="coerce")
    cash["Importe_firmado"] = cash["Importe"] * cash["signo"]
    cash["Importe_firmado_EUR"] = cash["Importe_firmado"] * cash["Tipo_cambio_EUR"]

    return cash.sort_values("Fecha").reset_index(drop=True)


def cargar_listado_activos(path=EXCEL_PATH):
    """Devuelve un diccionario Ticker -> Nombre desde la hoja 'Listado de activos'."""
    try:
        listado = pd.read_excel(path, sheet_name="Listado de activos")
    except Exception:
        return {}

    listado.columns = listado.columns.str.strip()
    if "Ticker" not in listado.columns or "Nombre" not in listado.columns:
        return {}

    listado["Ticker"] = listado["Ticker"].astype(str).str.strip()
    listado["Nombre"] = listado["Nombre"].astype(str).str.strip()
    listado = listado.dropna(subset=["Ticker", "Nombre"])
    return dict(zip(listado["Ticker"], listado["Nombre"]))



def _fx_fallback_desde_excel(*tablas, fallback=FX_FALLBACK_USDEUR):
    """Usa el último Tipo_cambio_EUR disponible para USD como respaldo si Yahoo FX falla."""
    valores = []
    for tabla in tablas:
        if tabla is None or tabla.empty or "Tipo_cambio_EUR" not in tabla.columns:
            continue
        t = tabla.copy()
        if "Currency" in t.columns:
            t = t[t["Currency"].astype(str).str.upper().eq("USD")]
        vals = pd.to_numeric(t["Tipo_cambio_EUR"], errors="coerce")
        valores.extend(vals[(vals > 0) & vals.notna()].tolist())
    return float(valores[-1]) if valores else float(fallback)


def _precios_desde_operaciones(df, tickers, fecha_inicio=None, indice=None):
    """Fallback local: construye una serie de precios con el último precio ejecutado."""
    tickers = [tickers] if isinstance(tickers, str) else list(tickers)
    if df is None or df.empty:
        return pd.DataFrame(columns=tickers)

    if fecha_inicio is None:
        fecha_inicio = df["Fecha"].min()
    fecha_inicio = pd.to_datetime(fecha_inicio).normalize()

    if indice is None:
        fecha_fin = max(pd.Timestamp.today().normalize(), pd.to_datetime(df["Fecha"].max()).normalize())
        idx = pd.bdate_range(fecha_inicio, fecha_fin)
    else:
        idx = pd.DatetimeIndex(indice)

    precios = pd.DataFrame(index=idx, columns=tickers, dtype="float64")
    for ticker in tickers:
        ops = df[df["Activo"].eq(ticker)].sort_values("Fecha")
        if ops.empty:
            continue
        serie = pd.Series(
            pd.to_numeric(ops["Precio_ejecutado"], errors="coerce").values,
            index=pd.to_datetime(ops["Fecha"]).dt.normalize(),
            dtype="float64",
        ).dropna()
        if serie.empty:
            continue
        serie = serie.groupby(level=0).last()
        precios[ticker] = serie.reindex(idx).ffill().bfill()
    return precios.ffill().dropna(how="all")


def _rellenar_precios_con_fallback(precios, tickers, df, fecha_inicio=None):
    """Completa tickers sin precio de Yahoo con el último precio ejecutado del Excel."""
    tickers = [tickers] if isinstance(tickers, str) else list(tickers)
    fallback = _precios_desde_operaciones(df, tickers, fecha_inicio=fecha_inicio)
    if precios is None or precios.empty:
        return fallback
    precios = precios.reindex(columns=tickers)
    if not fallback.empty:
        idx = precios.index.union(fallback.index).sort_values()
        precios = precios.reindex(idx).ffill()
        fallback = fallback.reindex(idx).ffill().bfill()
        precios = precios.combine_first(fallback)
    return precios.ffill().dropna(how="all")

def _alinear_flujos(fechas, importes, indice):
    """Coloca cada flujo en la primera fecha disponible del índice >= a su fecha real."""
    idx = pd.DatetimeIndex(indice)
    serie = pd.Series(0.0, index=idx)

    for fecha, importe in zip(pd.to_datetime(fechas), importes):
        if pd.isna(importe) or len(idx) == 0:
            continue
        pos = idx.searchsorted(fecha)
        if pos < len(idx):
            serie.iloc[pos] += float(importe)

    return serie


def calcular_capital_acumulado(cash, indice, columna_importe="Importe_firmado_EUR"):
    if columna_importe not in cash.columns:
        raise ValueError(f"No existe la columna '{columna_importe}' en la hoja Cash.")
    flujos = _alinear_flujos(cash["Fecha"], cash[columna_importe], indice.index)
    return flujos, flujos.cumsum()


def calcular_posiciones_actuales(df):
    if df.empty:
        return pd.Series(dtype="float64")
    return df.groupby("Activo")["acciones_firmadas"].sum().loc[lambda x: abs(x) > 1e-10]


def _descargar_precio_yahoo_chart(ticker, fecha_inicio):
    """
    Descarga precios ajustados desde la API chart de Yahoo.
    Usa la API chart de Yahoo directamente para evitar el error de descargas fallidas.
    """
    try:
        inicio = pd.to_datetime(fecha_inicio)
        period1 = int(inicio.timestamp())
        period2 = int(time.time()) + 86400
        url = (
            "https://query1.finance.yahoo.com/v8/finance/chart/"
            f"{quote(str(ticker), safe='')}?period1={period1}&period2={period2}"
            "&interval=1d&events=history&includeAdjustedClose=true"
        )
        req = Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(req, timeout=8) as r:
            data = json.loads(r.read().decode("utf-8"))

        chart = data.get("chart", {})
        if chart.get("error") or not chart.get("result"):
            return pd.Series(dtype="float64", name=ticker)

        result = chart["result"][0]
        timestamps = result.get("timestamp") or []
        if not timestamps:
            return pd.Series(dtype="float64", name=ticker)

        indicadores = result.get("indicators", {})
        precios = None
        adjclose = indicadores.get("adjclose") or []
        quote_data = indicadores.get("quote") or []

        if adjclose and adjclose[0].get("adjclose"):
            precios = adjclose[0]["adjclose"]
        elif quote_data and quote_data[0].get("close"):
            precios = quote_data[0]["close"]

        if precios is None:
            return pd.Series(dtype="float64", name=ticker)

        idx = pd.to_datetime(timestamps, unit="s", utc=True).tz_convert(None).normalize()
        serie = pd.Series(precios, index=idx, name=ticker, dtype="float64").dropna()
        if serie.empty:
            return pd.Series(dtype="float64", name=ticker)

        return serie.groupby(level=0).last().sort_index()
    except Exception:
        return pd.Series(dtype="float64", name=ticker)


def descargar_precios(tickers, fecha_inicio):
    """Descarga precios ajustados. Si un ticker falla, lo deja como columna vacía sin romper la app."""
    tickers = [tickers] if isinstance(tickers, str) else list(tickers)
    series = [_descargar_precio_yahoo_chart(t, fecha_inicio) for t in tickers]
    series = [s for s in series if s is not None and not s.empty]

    if not series:
        return pd.DataFrame(columns=tickers)

    precios = pd.concat(series, axis=1).sort_index()
    precios = precios.reindex(columns=tickers)
    return precios.ffill().dropna(how="all")


def descargar_fx_usdeur(fecha_inicio, indice=None, fallback=FX_FALLBACK_USDEUR):
    fx = descargar_precios("USDEUR=X", fecha_inicio)

    if not fx.empty:
        col = "USDEUR=X" if "USDEUR=X" in fx.columns else fx.columns[0]
        serie = fx[col].dropna().astype(float)
    else:
        if indice is not None and len(indice) > 0:
            serie = pd.Series(float(fallback), index=pd.DatetimeIndex(indice), name="USDEUR=X")
        else:
            idx = pd.bdate_range(pd.to_datetime(fecha_inicio), pd.Timestamp.today().normalize())
            serie = pd.Series(float(fallback), index=idx, name="USDEUR=X")

    if indice is not None:
        serie = serie.reindex(pd.DatetimeIndex(indice)).ffill().bfill()

    return serie


def _fx_en_fecha(fecha, indice, fx_usdeur):
    idx = pd.DatetimeIndex(indice)
    if len(idx) == 0 or fx_usdeur.empty:
        return FX_FALLBACK_USDEUR

    pos = idx.searchsorted(pd.to_datetime(fecha))
    if pos >= len(idx):
        pos = len(idx) - 1

    valor = fx_usdeur.iloc[pos]
    return FX_FALLBACK_USDEUR if pd.isna(valor) else float(valor)


def _tipo_cambio_eur_por_fila(df, indice, fx_usdeur):
    tipos = []

    for _, fila in df.iterrows():
        divisa = fila["Currency"]

        if divisa == "EUR":
            tipos.append(1.0)
            continue

        tipo_excel = fila.get("Tipo_cambio_EUR", pd.NA)

        if pd.notna(tipo_excel) and float(tipo_excel) > 0:
            tipos.append(float(tipo_excel))
        else:
            tipos.append(_fx_en_fecha(fila["Fecha"], indice, fx_usdeur))

    return pd.Series(tipos, index=df.index, dtype="float64")


def _importes_operaciones_eur(df, indice, fx_usdeur):
    tipos = _tipo_cambio_eur_por_fila(df, indice, fx_usdeur)
    return df["Importe"].astype(float) * tipos


def _importes_cash_eur(cash, indice, fx_usdeur):
    tipos = _tipo_cambio_eur_por_fila(cash, indice, fx_usdeur)
    return cash["Importe_firmado"].astype(float) * tipos


def _calcular_base_cartera_eur(df, cash):
    tickers = sorted(df["Activo"].unique())
    fecha_inicio = min(df["Fecha"].min(), cash["Fecha"].min())
    precios = _rellenar_precios_con_fallback(descargar_precios(tickers, fecha_inicio), tickers, df, fecha_inicio=fecha_inicio)

    if precios.empty:
        vacia = pd.Series(dtype="float64")
        return vacia, vacia, vacia, vacia

    fx_fallback = _fx_fallback_desde_excel(df, cash)
    fx_usdeur = descargar_fx_usdeur(fecha_inicio, precios.index, fallback=fx_fallback)

    posiciones = pd.DataFrame(0.0, index=precios.index, columns=tickers)
    for ticker, ops in df.groupby("Activo"):
        eventos = _alinear_flujos(ops["Fecha"], ops["acciones_firmadas"], precios.index)
        posiciones[ticker] = eventos.cumsum()

    divisas = df.groupby("Activo")["Currency"].last().reindex(tickers)
    factores_eur = pd.DataFrame(1.0, index=precios.index, columns=tickers)

    for ticker, divisa in divisas.items():
        if divisa == "USD":
            factores_eur[ticker] = fx_usdeur
        elif divisa != "EUR":
            raise ValueError(f"Divisa no soportada para {ticker}: {divisa}")

    valor_activos_eur = (posiciones * precios * factores_eur).sum(axis=1)

    signo_cash_operacion = df["Orden"].map({"compra": -1, "venta": 1})
    importes_operaciones_eur = _importes_operaciones_eur(df, precios.index, fx_usdeur)
    flujos_operaciones_eur = _alinear_flujos(df["Fecha"], importes_operaciones_eur * signo_cash_operacion, precios.index)

    importes_cash_eur = _importes_cash_eur(cash, precios.index, fx_usdeur)
    flujos_externos_eur = _alinear_flujos(cash["Fecha"], importes_cash_eur, precios.index)

    cash_diario_eur = (flujos_operaciones_eur + flujos_externos_eur).cumsum()
    cartera_eur = valor_activos_eur + cash_diario_eur
    capital_eur = flujos_externos_eur.cumsum()

    return cartera_eur, flujos_externos_eur, capital_eur, fx_usdeur


def calcular_series_cartera_multidivisa(df, cash):
    cartera_eur, flujos_eur, capital_eur, fx_usdeur = _calcular_base_cartera_eur(df, cash)

    if cartera_eur.empty:
        return pd.DataFrame()

    datos = pd.DataFrame(index=cartera_eur.index)
    datos["FX_EUR_por_USD"] = fx_usdeur
    datos["Valor_cartera_EUR"] = cartera_eur
    datos["Flujos_EUR"] = flujos_eur
    datos["Capital_EUR"] = capital_eur
    datos["TWR_EUR"] = calcular_twr(datos["Valor_cartera_EUR"], datos["Flujos_EUR"])

    datos["Valor_cartera_USD"] = _sin_inf(datos["Valor_cartera_EUR"] / datos["FX_EUR_por_USD"])
    datos["Flujos_USD"] = _sin_inf(datos["Flujos_EUR"] / datos["FX_EUR_por_USD"])
    datos["Capital_USD"] = datos["Flujos_USD"].cumsum()
    datos["TWR_USD"] = calcular_twr(datos["Valor_cartera_USD"], datos["Flujos_USD"])

    datos["TWR_total_EUR"] = datos["TWR_EUR"]
    datos["Valor_cartera"] = datos["Valor_cartera_EUR"]

    return datos


def calcular_historico_cartera(df, cash, divisa="EUR"):
    datos = calcular_series_cartera_multidivisa(df, cash)
    col = f"Valor_cartera_{divisa.upper()}"

    if datos.empty or col not in datos.columns:
        return pd.Series(dtype="float64")

    return datos[col]


def calcular_valor_actual_cartera(df, cash, divisa="EUR"):
    cartera = calcular_historico_cartera(df, cash, divisa=divisa)
    return 0.0 if cartera.empty else cartera.iloc[-1]


def calcular_rentabilidades_diarias_ajustadas(valor_cartera, flujos):
    valor = valor_cartera.dropna().astype(float)
    flujos = flujos.reindex(valor.index).fillna(0).astype(float)
    previo = valor.shift(1)
    rent = (valor - flujos) / previo - 1
    rent[(previo <= 0) | previo.isna()] = 0
    return _sin_inf(rent)


def calcular_twr(valor_cartera, flujos):
    rent = calcular_rentabilidades_diarias_ajustadas(valor_cartera, flujos)
    return (1 + rent).cumprod() - 1


def calcular_desempeno_cartera(df, cash, divisa="EUR"):
    datos = calcular_series_cartera_multidivisa(df, cash)

    if datos.empty:
        return pd.Series(dtype="float64")

    return datos[f"TWR_{divisa.upper()}"]


def calcular_vol_sharpe(valor_cartera, flujos, ventana=None, rf_anual=0.0):
    rent = calcular_rentabilidades_diarias_ajustadas(valor_cartera, flujos).iloc[1:].dropna()

    if ventana is not None:
        rent = rent.tail(ventana)

    if rent.empty or rent.std() == 0:
        return 0, 0

    rf_diario = (1 + rf_anual) ** (1 / 252) - 1
    vol = rent.std() * 252 ** 0.5
    sharpe = ((rent.mean() - rf_diario) / rent.std()) * 252 ** 0.5
    return vol, sharpe


def _calcular_coste_abierto_pmp(df, indice, fx_usdeur):
    """
    Coste de las posiciones abiertas usando precio medio ponderado (PMP).
    En ventas parciales, se reduce el coste de la posición abierta al PMP vigente.
    """
    columnas = [
        "Activo", "Acciones_abiertas", "Coste_abierto", "Coste_abierto_EUR",
        "Precio_medio_pagado", "Precio_medio_pagado_EUR", "Fecha_primera_compra", "Fecha_ultima_compra",
    ]

    if df.empty:
        return pd.DataFrame(columns=columnas)

    ops = df.copy().sort_values(["Activo", "Fecha"])
    ops["Importe_EUR_calc"] = _importes_operaciones_eur(ops, indice, fx_usdeur)

    registros = []
    eps = 1e-10

    for activo, g in ops.groupby("Activo", sort=True):
        acciones_abiertas = 0.0
        coste_abierto = 0.0
        coste_abierto_eur = 0.0
        fecha_primera = None
        fecha_ultima_compra = None

        for _, fila in g.sort_values("Fecha").iterrows():
            orden = fila["Orden"]
            acciones = float(fila["Numero_acciones"])
            importe = float(fila["Importe"]) if pd.notna(fila["Importe"]) else 0.0
            importe_eur = float(fila["Importe_EUR_calc"]) if pd.notna(fila["Importe_EUR_calc"]) else 0.0

            if orden == "compra":
                if acciones_abiertas <= eps:
                    acciones_abiertas = 0.0
                    coste_abierto = 0.0
                    coste_abierto_eur = 0.0
                    fecha_primera = fila["Fecha"]

                acciones_abiertas += acciones
                coste_abierto += importe
                coste_abierto_eur += importe_eur
                fecha_ultima_compra = fila["Fecha"]

            elif orden == "venta" and acciones_abiertas > eps:
                acciones_vendidas = min(acciones, acciones_abiertas)
                precio_medio = coste_abierto / acciones_abiertas if acciones_abiertas else 0.0
                precio_medio_eur = coste_abierto_eur / acciones_abiertas if acciones_abiertas else 0.0

                coste_abierto -= acciones_vendidas * precio_medio
                coste_abierto_eur -= acciones_vendidas * precio_medio_eur
                acciones_abiertas -= acciones_vendidas

                if acciones_abiertas <= eps:
                    acciones_abiertas = 0.0
                    coste_abierto = 0.0
                    coste_abierto_eur = 0.0
                    fecha_primera = None
                    fecha_ultima_compra = None

        if acciones_abiertas > eps:
            registros.append({
                "Activo": activo,
                "Acciones_abiertas": acciones_abiertas,
                "Coste_abierto": coste_abierto,
                "Coste_abierto_EUR": coste_abierto_eur,
                "Precio_medio_pagado": coste_abierto / acciones_abiertas,
                "Precio_medio_pagado_EUR": coste_abierto_eur / acciones_abiertas,
                "Fecha_primera_compra": fecha_primera,
                "Fecha_ultima_compra": fecha_ultima_compra,
            })

    return pd.DataFrame(registros, columns=columnas)


def _ultimos_precios_con_fallback(precios, tickers, df):
    if precios.empty:
        ultimos = pd.Series(index=tickers, dtype="float64")
    else:
        ultimos = precios.ffill().iloc[-1].reindex(tickers)

    fallback = df.sort_values("Fecha").groupby("Activo")["Precio_ejecutado"].last().reindex(tickers)
    return pd.to_numeric(ultimos, errors="coerce").fillna(fallback)


def calcular_distribucion_actual_multidivisa(df, cash):
    posiciones = calcular_posiciones_actuales(df)

    if posiciones.empty:
        return pd.DataFrame(), 0.0, 0.0

    tickers = posiciones.index.tolist()
    fecha_inicio = min(df["Fecha"].min(), cash["Fecha"].min())
    precios = _rellenar_precios_con_fallback(descargar_precios(tickers, fecha_inicio), tickers, df, fecha_inicio=fecha_inicio)

    if precios.empty:
        precios = pd.DataFrame([_ultimos_precios_con_fallback(precios, tickers, df)], index=[pd.Timestamp.today().normalize()])

    fx_fallback = _fx_fallback_desde_excel(df, cash)
    fx_usdeur = descargar_fx_usdeur(fecha_inicio, precios.index, fallback=fx_fallback)
    fx_actual = float(fx_usdeur.dropna().iloc[-1]) if not fx_usdeur.dropna().empty else FX_FALLBACK_USDEUR
    fecha_valoracion = precios.index.max()
    ultimos_precios = _ultimos_precios_con_fallback(precios, tickers, df)
    divisas = df.groupby("Activo")["Currency"].last().reindex(tickers)

    distribucion = pd.DataFrame({
        "Activo": tickers,
        "Divisa": divisas.values,
        "Acciones": posiciones.reindex(tickers).values,
        "Precio_actual": ultimos_precios.values,
    })

    distribucion["Tipo_cambio_EUR"] = distribucion["Divisa"].map({"EUR": 1.0, "USD": fx_actual})
    distribucion["Precio_actual_EUR"] = distribucion["Precio_actual"] * distribucion["Tipo_cambio_EUR"]
    distribucion["Valor_EUR"] = distribucion["Acciones"] * distribucion["Precio_actual_EUR"]
    distribucion["Precio_actual_USD"] = distribucion["Precio_actual_EUR"] / fx_actual
    distribucion["Valor_USD"] = distribucion["Valor_EUR"] / fx_actual

    costes = _calcular_coste_abierto_pmp(df, precios.index, fx_usdeur)
    if not costes.empty:
        distribucion = distribucion.merge(costes.drop(columns=["Acciones_abiertas"]), on="Activo", how="left")
    else:
        distribucion["Coste_abierto"] = 0.0
        distribucion["Coste_abierto_EUR"] = 0.0
        distribucion["Precio_medio_pagado"] = 0.0
        distribucion["Precio_medio_pagado_EUR"] = 0.0
        distribucion["Fecha_primera_compra"] = pd.NaT
        distribucion["Fecha_ultima_compra"] = pd.NaT

    for col in ["Coste_abierto", "Coste_abierto_EUR", "Precio_medio_pagado", "Precio_medio_pagado_EUR"]:
        distribucion[col] = pd.to_numeric(distribucion[col], errors="coerce").fillna(0.0)

    distribucion["Coste_total"] = distribucion["Coste_abierto"]
    distribucion["Coste_total_EUR"] = distribucion["Coste_abierto_EUR"]
    distribucion["Precio_pagado"] = distribucion["Coste_total"]
    distribucion["Precio_pagado_EUR"] = distribucion["Coste_total_EUR"]
    distribucion["Precio_pagado_USD"] = distribucion["Coste_total_EUR"] / fx_actual

    distribucion["Resultado_abierto_EUR"] = distribucion["Valor_EUR"] - distribucion["Coste_total_EUR"]
    distribucion["Resultado_abierto_USD"] = distribucion["Resultado_abierto_EUR"] / fx_actual
    distribucion["Rentabilidad_abierta"] = _sin_inf(distribucion["Resultado_abierto_EUR"] / distribucion["Coste_total_EUR"])

    distribucion["Fecha_primera_compra"] = pd.to_datetime(distribucion["Fecha_primera_compra"], errors="coerce")
    distribucion["Fecha_ultima_compra"] = pd.to_datetime(distribucion["Fecha_ultima_compra"], errors="coerce")
    distribucion["Dias_en_cartera"] = (fecha_valoracion - distribucion["Fecha_primera_compra"]).dt.days.fillna(0).astype(int)

    valor_total_eur = float(distribucion["Valor_EUR"].sum())
    valor_total_usd = float(distribucion["Valor_USD"].sum())
    resultado_total_eur = float(distribucion["Resultado_abierto_EUR"].sum())

    distribucion["Peso"] = distribucion["Valor_EUR"] / valor_total_eur if valor_total_eur != 0 else 0
    distribucion["Contribucion_resultado"] = distribucion["Resultado_abierto_EUR"] / resultado_total_eur if resultado_total_eur != 0 else 0

    distribucion = distribucion.sort_values("Valor_EUR", ascending=False).reset_index(drop=True)
    return distribucion, valor_total_eur, valor_total_usd


def calcular_historico_posicion_abierta(df, cash, activo):
    """
    Histórico del activo seleccionado para la gráfica de rentabilidad por posición.

    A diferencia de la tabla de posiciones, esta serie no empieza en la primera
    compra de la posición viva: descarga el precio desde el inicio de la cartera
    para poder ver cómo se comportaba el activo antes de estar invertido.

    También alinea las compras y ventas a la primera sesión disponible igual o
    posterior a la fecha de la operación, para poder dibujar marcadores en la
    gráfica. La evolución de la posición viva se sigue calculando con PMP.
    """
    ops = df[df["Activo"].eq(activo)].copy().sort_values("Fecha")
    if ops.empty:
        return pd.DataFrame()

    fechas_inicio = [pd.to_datetime(df["Fecha"].min()), pd.to_datetime(ops["Fecha"].min())]
    if cash is not None and not cash.empty and "Fecha" in cash.columns:
        fechas_inicio.append(pd.to_datetime(cash["Fecha"].min()))
    fecha_inicio = min(fechas_inicio)

    precios = _rellenar_precios_con_fallback(
        descargar_precios(activo, fecha_inicio),
        [activo],
        ops,
        fecha_inicio=fecha_inicio,
    )

    if precios.empty or activo not in precios.columns:
        return pd.DataFrame()

    precio = precios[activo].dropna().astype(float)
    if precio.empty:
        return pd.DataFrame()

    fx_fallback = _fx_fallback_desde_excel(df, cash)
    fx_usdeur = descargar_fx_usdeur(fecha_inicio, precio.index, fallback=fx_fallback)
    divisa = ops["Currency"].iloc[-1]

    ops = ops.copy()
    ops["Importe_EUR_calc"] = _importes_operaciones_eur(ops, precio.index, fx_usdeur)

    compras = ops[ops["Orden"].eq("compra")]
    ventas = ops[ops["Orden"].eq("venta")]

    eventos = pd.DataFrame(index=precio.index)
    eventos["Compra_acciones"] = _alinear_flujos(compras["Fecha"], compras["Numero_acciones"], precio.index) if not compras.empty else 0.0
    eventos["Venta_acciones"] = _alinear_flujos(ventas["Fecha"], ventas["Numero_acciones"], precio.index) if not ventas.empty else 0.0
    eventos["Compra_importe"] = _alinear_flujos(compras["Fecha"], compras["Importe"], precio.index) if not compras.empty else 0.0
    eventos["Venta_importe"] = _alinear_flujos(ventas["Fecha"], ventas["Importe"], precio.index) if not ventas.empty else 0.0
    eventos["Compra_importe_EUR"] = _alinear_flujos(compras["Fecha"], compras["Importe_EUR_calc"], precio.index) if not compras.empty else 0.0
    eventos["Venta_importe_EUR"] = _alinear_flujos(ventas["Fecha"], ventas["Importe_EUR_calc"], precio.index) if not ventas.empty else 0.0

    ops_ordenadas = list(ops.sort_values("Fecha").iterrows())
    j = 0
    eps = 1e-10
    acciones_abiertas = 0.0
    coste_abierto = 0.0
    coste_abierto_eur = 0.0
    registros = []

    precio_base = float(precio.iloc[0])
    fx_serie = fx_usdeur.reindex(precio.index).ffill().bfill()
    precio_eur_serie = precio * fx_serie if str(divisa).upper() == "USD" else precio.copy()
    precio_eur_base = float(precio_eur_serie.iloc[0]) if not precio_eur_serie.empty else 0.0

    for fecha, px in precio.items():
        while j < len(ops_ordenadas) and pd.to_datetime(ops_ordenadas[j][1]["Fecha"]) <= fecha:
            fila = ops_ordenadas[j][1]
            n = float(fila["Numero_acciones"])
            importe = float(fila["Importe"]) if pd.notna(fila["Importe"]) else 0.0
            importe_eur = float(fila["Importe_EUR_calc"]) if pd.notna(fila["Importe_EUR_calc"]) else 0.0

            if fila["Orden"] == "compra":
                if acciones_abiertas <= eps:
                    acciones_abiertas = 0.0
                    coste_abierto = 0.0
                    coste_abierto_eur = 0.0
                acciones_abiertas += n
                coste_abierto += importe
                coste_abierto_eur += importe_eur

            elif fila["Orden"] == "venta" and acciones_abiertas > eps:
                vendidas = min(n, acciones_abiertas)
                pmp = coste_abierto / acciones_abiertas if acciones_abiertas else 0.0
                pmp_eur = coste_abierto_eur / acciones_abiertas if acciones_abiertas else 0.0
                coste_abierto -= vendidas * pmp
                coste_abierto_eur -= vendidas * pmp_eur
                acciones_abiertas -= vendidas

                if acciones_abiertas <= eps:
                    acciones_abiertas = 0.0
                    coste_abierto = 0.0
                    coste_abierto_eur = 0.0

            j += 1

        fx = float(fx_serie.loc[fecha]) if str(divisa).upper() == "USD" else 1.0
        px = float(px)
        precio_eur = px * fx
        valor_activo = acciones_abiertas * px
        valor_eur = valor_activo * fx

        registros.append({
            "Fecha": fecha,
            "Activo": activo,
            "Divisa": divisa,
            "Acciones": acciones_abiertas,
            "Invertido": acciones_abiertas > eps,
            "Precio": px,
            "Precio_EUR": precio_eur,
            "Coste_abierto": coste_abierto,
            "Coste_abierto_EUR": coste_abierto_eur,
            "Valor_activo": valor_activo,
            "Valor_EUR": valor_eur,
            "Rentabilidad_activo": px / precio_base - 1 if precio_base else 0.0,
            "Rentabilidad_EUR": precio_eur / precio_eur_base - 1 if precio_eur_base else 0.0,
            "Rentabilidad_posicion_activo": valor_activo / coste_abierto - 1 if coste_abierto > eps else pd.NA,
            "Rentabilidad_posicion_EUR": valor_eur / coste_abierto_eur - 1 if coste_abierto_eur > eps else pd.NA,
            "FX_EUR_por_USD": fx,
            "Compra_acciones": float(eventos.loc[fecha, "Compra_acciones"]),
            "Venta_acciones": float(eventos.loc[fecha, "Venta_acciones"]),
            "Compra_importe": float(eventos.loc[fecha, "Compra_importe"]),
            "Venta_importe": float(eventos.loc[fecha, "Venta_importe"]),
            "Compra_importe_EUR": float(eventos.loc[fecha, "Compra_importe_EUR"]),
            "Venta_importe_EUR": float(eventos.loc[fecha, "Venta_importe_EUR"]),
        })

    return pd.DataFrame(registros).set_index("Fecha")

def calcular_desglose_fx_eur(df, cash):
    return calcular_series_cartera_multidivisa(df, cash)


def calcular_operaciones_cerradas(df):
    df = df.copy()

    if df.empty:
        return pd.DataFrame()

    necesita_fx = "Importe_EUR" not in df.columns or df["Importe_EUR"].isna().any()

    if necesita_fx:
        fecha_inicio = df["Fecha"].min()
        fx_usdeur = descargar_fx_usdeur(fecha_inicio, fallback=_fx_fallback_desde_excel(df))
        df["Importe_EUR_calc"] = _importes_operaciones_eur(df, fx_usdeur.index, fx_usdeur)
    else:
        df["Importe_EUR_calc"] = df["Importe_EUR"].astype(float)

    activos_validos = df.groupby("Activo")["Importe_EUR_calc"].transform(lambda s: s.notna().all())
    df = df[activos_validos].copy()

    if df.empty:
        return pd.DataFrame()

    compras = df[df["Orden"] == "compra"].groupby("Activo").agg(
        Fecha_inicio=("Fecha", "min"),
        Acciones_compradas=("Numero_acciones", "sum"),
        Capital_comprado=("Importe_EUR_calc", "sum"),
    )
    ventas = df[df["Orden"] == "venta"].groupby("Activo").agg(
        Fecha_fin=("Fecha", "max"),
        Acciones_vendidas=("Numero_acciones", "sum"),
        Valor_venta_total=("Importe_EUR_calc", "sum"),
    )
    operaciones = compras.join(ventas, how="inner").reset_index()

    if operaciones.empty:
        return operaciones

    acciones_cerradas = operaciones[["Acciones_compradas", "Acciones_vendidas"]].min(axis=1)
    pmc = operaciones["Capital_comprado"] / operaciones["Acciones_compradas"]
    pmv = operaciones["Valor_venta_total"] / operaciones["Acciones_vendidas"]
    operaciones["Capital_invertido"] = acciones_cerradas * pmc
    operaciones["Valor_venta"] = acciones_cerradas * pmv
    operaciones["Resultado"] = operaciones["Valor_venta"] - operaciones["Capital_invertido"]
    operaciones["Rentabilidad"] = operaciones["Resultado"] / operaciones["Capital_invertido"]
    dias = (operaciones["Fecha_fin"] - operaciones["Fecha_inicio"]).dt.days.clip(lower=1)
    operaciones["Rent. anualizada"] = (1 + operaciones["Rentabilidad"]) ** (365 / dias) - 1
    operaciones["Periodo"] = operaciones["Fecha_inicio"].dt.strftime("%d/%m/%y") + "-" + operaciones["Fecha_fin"].dt.strftime("%d/%m/%y")

    return operaciones[["Activo", "Periodo", "Rentabilidad", "Rent. anualizada", "Capital_invertido"]]


def obtener_rf_anual_eur(fallback=0.02):
    """
    Descarga el último tipo libre de riesgo EUR conocido.
    Se usa la facilidad de depósito del BCE como proxy simple para el Sharpe.
    Devuelve (tipo_anual_decimal, fecha_observacion). Si falla internet, usa fallback.
    """
    url = "https://data-api.ecb.europa.eu/service/data/FM/D.U2.EUR.4F.KR.DFR.LEV?lastNObservations=1&format=csvdata"

    try:
        datos = pd.read_csv(url)
        valores = pd.to_numeric(datos.get("OBS_VALUE"), errors="coerce")
        if valores.notna().any():
            i = valores.dropna().index[-1]
            fecha = str(datos.loc[i, "TIME_PERIOD"]) if "TIME_PERIOD" in datos.columns else None
            return float(valores.loc[i]) / 100, fecha
    except Exception:
        pass

    return fallback, None
