from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

from yahoo_session import obtener_sesion_yahoo

from cache_precios import cargar_cierres_varios

EXCEL_PATH = Path("Libro_inversiones.xlsx")
MONEDAS_SOPORTADAS = {"EUR", "USD"}
SUFIJOS_EUR = (".MI", ".PA", ".MC", ".DE", ".AS", ".BR", ".VI", ".F", ".MU", ".BE", ".HM", ".DU")
FX_FALLBACK_USDEUR = 0.92


def _limpiar_texto(s):
    return s.astype(str).str.lower().str.strip()


def _sin_inf(s):
    return s.replace([float("inf"), -float("inf")], 0).fillna(0)


def _valor_info(info, claves):
    for clave in claves:
        valor = info.get(clave)
        if valor is not None and valor != "":
            return valor
    return None


def _fecha_yahoo(valor):
    if valor is None or pd.isna(valor):
        return None

    try:
        if isinstance(valor, (int, float)):
            fecha = pd.to_datetime(valor, unit="s")
        else:
            fecha = pd.to_datetime(valor)
    except Exception:
        return None

    if pd.isna(fecha):
        return None

    if getattr(fecha, "tzinfo", None) is not None:
        fecha = fecha.tz_localize(None)

    return pd.Timestamp(fecha).normalize()


def _precio_actual_info(info):
    for campo in ["currentPrice", "regularMarketPrice", "previousClose"]:
        valor = _valor_info(info, [campo])
        if valor is not None and float(valor) > 0:
            return float(valor)
    return None


def _dividendos_historicos(ticker_yahoo):
    try:
        dividendos = ticker_yahoo.dividends
    except Exception:
        return pd.Series(dtype="float64")

    if dividendos is None or dividendos.empty:
        return pd.Series(dtype="float64")

    dividendos = dividendos.copy()
    dividendos.index = pd.to_datetime(dividendos.index)
    if getattr(dividendos.index, "tz", None) is not None:
        dividendos.index = dividendos.index.tz_localize(None)
    return dividendos.dropna().astype(float)


def _frecuencia_dividendos_anual(dividendos):
    if dividendos.empty:
        return None

    fecha_inicio = pd.Timestamp.today().normalize() - pd.DateOffset(months=18)
    recientes = dividendos[dividendos.index >= fecha_inicio]

    if len(recientes) >= 2:
        return min(max(round(len(recientes) / 1.5), 1), 12)

    fecha_inicio = pd.Timestamp.today().normalize() - pd.DateOffset(years=3)
    recientes = dividendos[dividendos.index >= fecha_inicio]

    if len(recientes) >= 2:
        return min(max(round(len(recientes) / 3), 1), 12)

    return 1


def _dividendo_anualizado_forward(dividendos, info=None):
    dividendo_anual_info = _valor_info(info or {}, ["dividendRate"])
    try:
        dividendo_anual_info = None if dividendo_anual_info is None else float(dividendo_anual_info)
    except (TypeError, ValueError):
        dividendo_anual_info = None

    if dividendo_anual_info is not None and dividendo_anual_info > 0:
        return dividendo_anual_info

    if dividendos.empty:
        return None

    ultimo_dividendo = float(dividendos.iloc[-1])
    frecuencia = _frecuencia_dividendos_anual(dividendos)

    if ultimo_dividendo <= 0 or not frecuencia:
        return None

    return ultimo_dividendo * frecuencia


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


def _fx_fallback_desde_excel(path=EXCEL_PATH, fallback=FX_FALLBACK_USDEUR):
    """Usa el último tipo USD->EUR del Excel si Yahoo no devuelve USDEUR=X."""
    valores = []

    for hoja in ["Operaciones", "Cash"]:
        try:
            tabla = pd.read_excel(path, sheet_name=hoja)
        except Exception:
            continue

        tabla.columns = tabla.columns.str.strip()

        if "Tipo_cambio_EUR" not in tabla.columns:
            continue

        if "Currency" not in tabla.columns and "Divisa" in tabla.columns:
            tabla["Currency"] = tabla["Divisa"]

        tipos = pd.to_numeric(tabla["Tipo_cambio_EUR"], errors="coerce")

        if "Currency" in tabla.columns:
            es_usd = tabla["Currency"].fillna("").astype(str).str.upper().str.strip().eq("USD")
            tipos = tipos[es_usd]

        tipos = tipos[(tipos > 0) & tipos.notna()]
        valores.extend(tipos.tolist())

    return float(valores[-1]) if valores else float(fallback)


def _normalizar_banco(df):
    """Garantiza una columna Banco limpia, aunque en Excel venga como banco/BANCO."""
    df = df.copy()

    columnas_lower = {str(col).strip().lower(): col for col in df.columns}
    if "banco" in columnas_lower and columnas_lower["banco"] != "Banco":
        df = df.rename(columns={columnas_lower["banco"]: "Banco"})

    if "Banco" not in df.columns:
        df["Banco"] = "Sin banco"

    df["Banco"] = (
        df["Banco"]
        .fillna("Sin banco")
        .astype(str)
        .str.strip()
        .replace({"": "Sin banco", "nan": "Sin banco", "None": "Sin banco"})
    )

    return df


def cargar_operaciones(path=EXCEL_PATH):
    df = pd.read_excel(path, sheet_name="Operaciones")
    df.columns = df.columns.str.strip()
    df = _normalizar_banco(df)
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
    tipos_externos = {"aportación", "aportacion", "retirada"}
    cash["signo"] = cash["Tipo"].map({"aportación": 1, "aportacion": 1, "retirada": -1, "dividendo": 1})
    cash["Es_flujo_externo"] = cash["Tipo"].isin(tipos_externos)

    if cash["signo"].isna().any():
        raise ValueError("Hay movimientos distintos de 'aportación', 'retirada' o 'dividendo' en la hoja Cash.")

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
    """Devuelve Ticker -> Nombre desde la hoja Listado de activos."""
    try:
        listado = pd.read_excel(path, sheet_name="Listado de activos")
    except Exception:
        return {}

    listado.columns = listado.columns.str.strip()

    if "Ticker" not in listado.columns or "Nombre" not in listado.columns:
        return {}

    listado = listado.dropna(subset=["Ticker"]).copy()
    listado["Ticker"] = listado["Ticker"].astype(str).str.strip()
    listado["Nombre"] = listado["Nombre"].fillna(listado["Ticker"]).astype(str).str.strip()
    listado = listado[listado["Ticker"].ne("")]
    return dict(zip(listado["Ticker"], listado["Nombre"]))


def _alinear_flujos(fechas, importes, indice):
    """Coloca cada flujo en la primera fecha disponible del índice >= a su fecha real."""
    idx = pd.DatetimeIndex(indice)
    serie = pd.Series(0.0, index=idx)

    for fecha, importe in zip(pd.to_datetime(fechas), importes):
        if pd.isna(importe):
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
    return df.groupby("Activo")["acciones_firmadas"].sum().loc[lambda x: x != 0]


def descargar_precios(tickers, fecha_inicio):
    tickers = [tickers] if isinstance(tickers, str) else list(tickers)
    return cargar_cierres_varios(tickers, start=fecha_inicio)


def descargar_fx_usdeur(fecha_inicio, indice=None):
    try:
        fx = descargar_precios("USDEUR=X", fecha_inicio)
    except Exception:
        fx = pd.DataFrame()

    if fx.empty:
        valor_fallback = _fx_fallback_desde_excel()
        idx = (
            pd.DatetimeIndex(indice)
            if indice is not None
            else pd.bdate_range(pd.to_datetime(fecha_inicio).normalize(), pd.Timestamp.today().normalize())
        )
        serie = pd.Series(valor_fallback, index=idx, name="USDEUR=X", dtype="float64")
        serie.attrs["usa_fallback"] = True
        return serie

    col = "USDEUR=X" if "USDEUR=X" in fx.columns else fx.columns[0]
    fx = fx[col].dropna().astype(float)

    if fx.empty:
        valor_fallback = _fx_fallback_desde_excel()
        idx = (
            pd.DatetimeIndex(indice)
            if indice is not None
            else pd.bdate_range(pd.to_datetime(fecha_inicio).normalize(), pd.Timestamp.today().normalize())
        )
        serie = pd.Series(valor_fallback, index=idx, name="USDEUR=X", dtype="float64")
        serie.attrs["usa_fallback"] = True
        return serie

    if indice is not None:
        fx = fx.reindex(pd.DatetimeIndex(indice)).ffill().bfill()

    fx.attrs["usa_fallback"] = False
    return fx


def _fx_en_fecha(fecha, indice, fx_usdeur):
    idx = pd.DatetimeIndex(indice)
    pos = idx.searchsorted(pd.to_datetime(fecha))

    if pos >= len(idx):
        pos = len(idx) - 1

    return float(fx_usdeur.iloc[pos])


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
    precios = descargar_precios(tickers, fecha_inicio)

    if precios.empty:
        vacia = pd.Series(dtype="float64")
        return vacia, vacia, vacia, vacia

    fx_usdeur = descargar_fx_usdeur(fecha_inicio, precios.index)

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
    flujos_operaciones_eur = _alinear_flujos(
        df["Fecha"],
        importes_operaciones_eur * signo_cash_operacion,
        precios.index,
    )

    importes_cash_eur = _importes_cash_eur(cash, precios.index, fx_usdeur)
    flujos_cash_eur = _alinear_flujos(cash["Fecha"], importes_cash_eur, precios.index)
    importes_externos_eur = importes_cash_eur.where(cash["Es_flujo_externo"], 0.0)
    flujos_externos_eur = _alinear_flujos(cash["Fecha"], importes_externos_eur, precios.index)

    cash_diario_eur = (flujos_operaciones_eur + flujos_cash_eur).cumsum()
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

    # Alias conservadores para código antiguo que esperaba estas columnas.
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


def calcular_rentabilidad_anualizada_por_activo(df, cash, fecha_inicio_periodo, divisa="EUR"):
    """Calcula la rentabilidad anualizada del precio de cada posicion abierta."""
    columnas = ["Activo", "Nombre", "Valor_actual", "Rentabilidad_anualizada"]
    if df is None or df.empty:
        return pd.DataFrame(columns=columnas)

    divisa = divisa.upper()
    if divisa not in MONEDAS_SOPORTADAS:
        raise ValueError(f"Divisa no soportada: {divisa}")

    distribucion, _, _ = calcular_distribucion_actual_multidivisa(df, cash)
    if distribucion.empty:
        return pd.DataFrame(columns=columnas)

    tickers = distribucion["Activo"].tolist()
    fecha_inicio = pd.to_datetime(fecha_inicio_periodo).normalize()
    precios = descargar_precios(tickers, fecha_inicio).reindex(columns=tickers).ffill().bfill()
    if precios.empty:
        return pd.DataFrame(columns=columnas)

    fx_usdeur = descargar_fx_usdeur(fecha_inicio, precios.index).ffill().bfill()
    divisas_activos = df.groupby("Activo")["Currency"].last().reindex(tickers)
    factores = pd.DataFrame(
        {
            ticker: (
                fx_usdeur
                if divisas_activos[ticker] == "USD" and divisa == "EUR"
                else 1 / fx_usdeur
                if divisas_activos[ticker] == "EUR" and divisa == "USD"
                else 1.0
            )
            for ticker in tickers
        },
        index=precios.index,
    )

    dias = max((precios.index[-1] - precios.index[0]).days, 1)
    rentabilidades = ((precios * factores).iloc[-1] / (precios * factores).iloc[0]) ** (365 / dias) - 1
    resultado = distribucion[["Activo", f"Valor_{divisa}"]].rename(
        columns={f"Valor_{divisa}": "Valor_actual"}
    )
    resultado["Nombre"] = resultado["Activo"].map(cargar_listado_activos()).fillna(resultado["Activo"])
    resultado["Rentabilidad_anualizada"] = resultado["Activo"].map(rentabilidades)
    return resultado.sort_values("Valor_actual", ascending=False).reset_index(drop=True)


def calcular_vol_sharpe(
    valor_cartera,
    flujos,
    ventana=None,
    rf_anual=0.0,
    min_observaciones_volatilidad=1,
    min_observaciones_sharpe=1,
    devolver_observaciones=False,
):
    rent = calcular_rentabilidades_diarias_ajustadas(valor_cartera, flujos).iloc[1:].dropna()

    if ventana is not None:
        rent = rent.tail(ventana)

    observaciones = len(rent)
    volatilidad = None
    sharpe = None

    if observaciones >= min_observaciones_volatilidad:
        desviacion = rent.std()
        volatilidad = 0.0 if desviacion == 0 else desviacion * 252 ** 0.5

        if observaciones >= min_observaciones_sharpe and desviacion > 0:
            rf_diario = (1 + rf_anual) ** (1 / 252) - 1
            sharpe = ((rent.mean() - rf_diario) / desviacion) * 252 ** 0.5

    if devolver_observaciones:
        return volatilidad, sharpe, observaciones
    return volatilidad, sharpe


def calcular_distribucion_actual_multidivisa(df, cash):
    posiciones = calcular_posiciones_actuales(df)

    if posiciones.empty:
        return pd.DataFrame(), 0.0, 0.0

    tickers = posiciones.index.tolist()
    fecha_inicio = min(df["Fecha"].min(), cash["Fecha"].min())
    precios = descargar_precios(tickers, fecha_inicio)

    if precios.empty:
        return pd.DataFrame(), 0.0, 0.0

    fx_usdeur = descargar_fx_usdeur(fecha_inicio, precios.index)
    fx_actual = float(fx_usdeur.dropna().iloc[-1])
    ultimos_precios = precios.ffill().iloc[-1].reindex(tickers)
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

    compras = df[df["Orden"] == "compra"].copy()
    if not compras.empty:
        compras["Importe_EUR_calc"] = _importes_operaciones_eur(compras, precios.index, fx_usdeur)
        coste_medio_eur = (
            compras.groupby("Activo").agg(
                acciones_compradas=("Numero_acciones", "sum"),
                importe_comprado_eur=("Importe_EUR_calc", "sum"),
            )
        )
        coste_medio_eur["Precio_medio_EUR"] = coste_medio_eur["importe_comprado_eur"] / coste_medio_eur["acciones_compradas"]
        distribucion["Precio_medio_pagado_EUR"] = distribucion["Activo"].map(coste_medio_eur["Precio_medio_EUR"])
    else:
        distribucion["Precio_medio_pagado_EUR"] = 0.0

    distribucion["Precio_pagado_EUR"] = distribucion["Acciones"] * distribucion["Precio_medio_pagado_EUR"].fillna(0)
    distribucion["Precio_pagado_USD"] = distribucion["Precio_pagado_EUR"] / fx_actual

    valor_total_eur = float(distribucion["Valor_EUR"].sum())
    valor_total_usd = float(distribucion["Valor_USD"].sum())
    distribucion["Peso"] = distribucion["Valor_EUR"] / valor_total_eur if valor_total_eur != 0 else 0

    distribucion = distribucion.sort_values("Valor_EUR", ascending=False).reset_index(drop=True)
    return distribucion, valor_total_eur, valor_total_usd


def calcular_operaciones_abiertas(df, cash, fecha_inicio_periodo=None):
    distribucion, _, _ = calcular_distribucion_actual_multidivisa(df, cash)

    if distribucion.empty:
        return pd.DataFrame()

    if fecha_inicio_periodo is not None:
        fecha_inicio_periodo = pd.to_datetime(fecha_inicio_periodo).normalize()
        tickers = distribucion["Activo"].tolist()
        precios = descargar_precios(tickers, fecha_inicio_periodo)

        if precios.empty:
            return pd.DataFrame()

        fx_usdeur = descargar_fx_usdeur(fecha_inicio_periodo, precios.index)
        fx_inicio = float(fx_usdeur.ffill().bfill().iloc[0])
        precios_inicio = precios.ffill().bfill().iloc[0].reindex(tickers)
        divisas = df.groupby("Activo")["Currency"].last().reindex(tickers)

        posiciones_inicio = (
            df[df["Fecha"] < fecha_inicio_periodo]
            .groupby("Activo")["acciones_firmadas"]
            .sum()
            .reindex(tickers)
            .fillna(0.0)
        )
        factores_inicio = divisas.map({"EUR": 1.0, "USD": fx_inicio}).fillna(1.0)
        valor_inicio = posiciones_inicio * precios_inicio * factores_inicio

        ops_periodo = df[df["Fecha"] >= fecha_inicio_periodo].copy()
        if ops_periodo.empty:
            compras_periodo = pd.Series(0.0, index=tickers)
            ventas_periodo = pd.Series(0.0, index=tickers)
        else:
            ops_periodo["Importe_EUR_calc"] = _importes_operaciones_eur(ops_periodo, precios.index, fx_usdeur)
            compras_periodo = (
                ops_periodo[ops_periodo["Orden"].eq("compra")]
                .groupby("Activo")["Importe_EUR_calc"]
                .sum()
                .reindex(tickers)
                .fillna(0.0)
            )
            ventas_periodo = (
                ops_periodo[ops_periodo["Orden"].eq("venta")]
                .groupby("Activo")["Importe_EUR_calc"]
                .sum()
                .reindex(tickers)
                .fillna(0.0)
            )

        nombres = cargar_listado_activos()
        abiertas = distribucion.copy()
        abiertas["Nombre"] = abiertas["Activo"].map(nombres).fillna(abiertas["Activo"])
        abiertas["Periodo"] = fecha_inicio_periodo.strftime("%d/%m/%y") + "-Actual"
        abiertas["Precio_pagado_EUR"] = (
            valor_inicio.reindex(abiertas["Activo"]).values
            + compras_periodo.reindex(abiertas["Activo"]).values
        )
        abiertas["Resultado"] = (
            ventas_periodo.reindex(abiertas["Activo"]).values
            + abiertas["Valor_EUR"]
            - abiertas["Precio_pagado_EUR"]
        )
        abiertas["Rentabilidad"] = abiertas["Resultado"] / abiertas["Precio_pagado_EUR"].replace(0, pd.NA)
        abiertas["Rentabilidad"] = abiertas["Rentabilidad"].fillna(0.0)
        dias = max((pd.Timestamp.today().normalize() - fecha_inicio_periodo).days, 1)
        abiertas["Rent. anualizada"] = _sin_inf((1 + abiertas["Rentabilidad"]) ** (365 / dias) - 1)

        return abiertas[
            [
                "Activo",
                "Nombre",
                "Periodo",
                "Acciones",
                "Precio_pagado_EUR",
                "Valor_EUR",
                "Resultado",
                "Rentabilidad",
                "Rent. anualizada",
            ]
        ].sort_values("Resultado", ascending=False).reset_index(drop=True)

    fechas_inicio = df[df["Orden"] == "compra"].groupby("Activo")["Fecha"].min()
    nombres = cargar_listado_activos()
    abiertas = distribucion.copy()
    abiertas["Nombre"] = abiertas["Activo"].map(nombres).fillna(abiertas["Activo"])
    abiertas["Fecha_inicio"] = abiertas["Activo"].map(fechas_inicio)
    abiertas["Periodo"] = abiertas["Fecha_inicio"].dt.strftime("%d/%m/%y") + "-Abierta"
    abiertas["Resultado"] = abiertas["Valor_EUR"] - abiertas["Precio_pagado_EUR"]
    abiertas["Rentabilidad"] = abiertas["Resultado"] / abiertas["Precio_pagado_EUR"].replace(0, pd.NA)
    abiertas["Rentabilidad"] = abiertas["Rentabilidad"].fillna(0.0)
    dias = (pd.Timestamp.today().normalize() - abiertas["Fecha_inicio"]).dt.days.clip(lower=1)
    abiertas["Rent. anualizada"] = _sin_inf((1 + abiertas["Rentabilidad"]) ** (365 / dias) - 1)

    return abiertas[
        [
            "Activo",
            "Nombre",
            "Periodo",
            "Acciones",
            "Precio_pagado_EUR",
            "Valor_EUR",
            "Resultado",
            "Rentabilidad",
            "Rent. anualizada",
        ]
    ].sort_values("Resultado", ascending=False).reset_index(drop=True)


def calcular_cash_disponible(df, cash):
    movimientos = []
    cash = _normalizar_banco(cash) if cash is not None else pd.DataFrame()

    if not cash.empty:
        movimientos.append(
            cash[["Banco", "Currency", "Importe_firmado"]]
            .rename(columns={"Importe_firmado": "Importe"})
        )
        dividendos = (
            cash[cash["Tipo"].eq("dividendo")]
            .groupby(["Banco", "Currency"])["Importe"]
            .sum()
            .rename("Dividendos")
        )
    else:
        dividendos = pd.Series(
            dtype="float64",
            name="Dividendos",
            index=pd.MultiIndex.from_tuples([], names=["Banco", "Currency"]),
        )

    if df is not None and not df.empty:
        ops = _normalizar_banco(df)
        ops_cash = ops[["Banco", "Currency", "Importe", "Orden"]].copy()
        ops_cash["Importe"] *= ops_cash["Orden"].map({"compra": -1, "venta": 1})
        movimientos.append(ops_cash[["Banco", "Currency", "Importe"]])

    if not movimientos:
        return pd.DataFrame()

    resumen = (
        pd.concat(movimientos, ignore_index=True)
        .groupby(["Banco", "Currency"])["Importe"]
        .sum()
        .rename("Cash")
        .to_frame()
        .join(dividendos, how="outer")
        .fillna(0.0)
        .reset_index()
    )
    resumen = resumen[(resumen["Cash"].abs() > 1e-9) | (resumen["Dividendos"].abs() > 1e-9)]

    if resumen.empty:
        return resumen

    fechas = []
    if df is not None and not df.empty:
        fechas.append(df["Fecha"].min())
    if not cash.empty:
        fechas.append(cash["Fecha"].min())
    fecha_inicio = min(fechas) if fechas else pd.Timestamp.today().normalize()

    fx_actual = (
        float(descargar_fx_usdeur(fecha_inicio).dropna().iloc[-1])
        if resumen["Currency"].eq("USD").any()
        else 1.0
    )
    resumen["Tipo_cambio_EUR"] = resumen["Currency"].map({"EUR": 1.0, "USD": fx_actual})
    resumen["Valor_EUR"] = resumen["Cash"] * resumen["Tipo_cambio_EUR"]
    resumen["Dividendos_EUR"] = resumen["Dividendos"] * resumen["Tipo_cambio_EUR"]

    return resumen.sort_values(["Banco", "Currency"]).reset_index(drop=True)


def calcular_optimizacion_montecarlo_sharpe(
    df,
    cash,
    rf_anual=0.0,
    n_simulaciones=8000,
    anios_historico=1,
    seed=42,
):
    posiciones = calcular_posiciones_actuales(df)

    if posiciones.empty:
        return {
            "simulaciones": pd.DataFrame(),
            "frontera": pd.DataFrame(),
            "pesos": pd.DataFrame(),
            "actual": {},
            "optima": {},
            "aviso": "No hay posiciones abiertas para optimizar.",
        }

    tickers = [ticker for ticker in posiciones.index.tolist() if str(ticker).lower() != "cash"]

    if len(tickers) < 2:
        return {
            "simulaciones": pd.DataFrame(),
            "frontera": pd.DataFrame(),
            "pesos": pd.DataFrame(),
            "actual": {},
            "optima": {},
            "aviso": "Se necesitan al menos dos activos abiertos para simular combinaciones de pesos.",
        }

    fecha_inicio = pd.Timestamp.today().normalize() - pd.DateOffset(years=anios_historico)
    try:
        precios = descargar_precios(tickers, fecha_inicio)
    except Exception as e:
        return {
            "simulaciones": pd.DataFrame(),
            "frontera": pd.DataFrame(),
            "pesos": pd.DataFrame(),
            "actual": {},
            "optima": {},
            "aviso": f"No se pudo descargar el histórico de precios: {e}",
        }

    if precios.empty:
        return {
            "simulaciones": pd.DataFrame(),
            "frontera": pd.DataFrame(),
            "pesos": pd.DataFrame(),
            "actual": {},
            "optima": {},
            "aviso": "No se pudo descargar histórico suficiente para los activos abiertos.",
        }

    precios = precios.reindex(columns=tickers).ffill().dropna(how="all")
    try:
        fx_usdeur = descargar_fx_usdeur(fecha_inicio, precios.index)
    except Exception as e:
        return {
            "simulaciones": pd.DataFrame(),
            "frontera": pd.DataFrame(),
            "pesos": pd.DataFrame(),
            "actual": {},
            "optima": {},
            "aviso": f"No se pudo descargar el tipo de cambio EUR/USD: {e}",
        }
    aviso_fx = (
        "Aviso: Yahoo no devolvió el histórico EUR/USD; para activos USD se usa el último tipo de cambio disponible del Excel."
        if fx_usdeur.attrs.get("usa_fallback", False)
        else None
    )
    divisas = df.groupby("Activo")["Currency"].last().reindex(tickers)

    precios_eur = precios.copy()
    for ticker, divisa in divisas.items():
        if divisa == "USD":
            precios_eur[ticker] = precios_eur[ticker] * fx_usdeur

    rentabilidades = (
        precios_eur.pct_change()
        .replace([np.inf, -np.inf], np.nan)
        .dropna(axis=1, thresh=60)
        .dropna()
    )

    tickers_validos = rentabilidades.columns.tolist()
    if len(tickers_validos) < 2:
        return {
            "simulaciones": pd.DataFrame(),
            "frontera": pd.DataFrame(),
            "pesos": pd.DataFrame(),
            "actual": {},
            "optima": {},
            "aviso": "No hay suficientes datos históricos comparables entre activos.",
        }

    media_anual = rentabilidades.mean() * 252
    cov_anual = rentabilidades.cov() * 252

    rng = np.random.default_rng(seed)
    pesos = rng.dirichlet(np.ones(len(tickers_validos)), size=n_simulaciones)

    rent_esperada = pesos @ media_anual.values
    volatilidad = np.sqrt(np.einsum("ij,jk,ik->i", pesos, cov_anual.values, pesos))
    sharpe = np.divide(
        rent_esperada - rf_anual,
        volatilidad,
        out=np.zeros_like(rent_esperada),
        where=volatilidad > 0,
    )

    simulaciones = pd.DataFrame(
        {
            "Volatilidad": volatilidad,
            "Rentabilidad": rent_esperada,
            "Sharpe": sharpe,
        }
    )

    mascara_positiva = (simulaciones["Rentabilidad"] > 0) & (simulaciones["Volatilidad"] > 0)
    simulaciones = simulaciones.loc[mascara_positiva].reset_index(drop=True)
    pesos = pesos[mascara_positiva.values]

    if simulaciones.empty:
        return {
            "simulaciones": pd.DataFrame(),
            "frontera": pd.DataFrame(),
            "pesos": pd.DataFrame(),
            "actual": {},
            "optima": {},
            "misma_vola": {},
            "aviso": "No se han encontrado carteras simuladas con rentabilidad esperada positiva.",
        }

    try:
        distribucion, _, _ = calcular_distribucion_actual_multidivisa(df, cash)
    except Exception as e:
        return {
            "simulaciones": pd.DataFrame(),
            "frontera": pd.DataFrame(),
            "pesos": pd.DataFrame(),
            "actual": {},
            "optima": {},
            "aviso": f"No se pudo calcular la distribución actual para comparar pesos: {e}",
        }
    distribucion = distribucion[distribucion["Activo"].isin(tickers_validos)].copy()
    total_actual = distribucion["Valor_EUR"].sum()
    pesos_actuales = (
        distribucion.set_index("Activo")["Valor_EUR"].reindex(tickers_validos).fillna(0.0) / total_actual
        if total_actual
        else pd.Series(1 / len(tickers_validos), index=tickers_validos)
    )

    rent_actual = float(pesos_actuales.values @ media_anual.reindex(tickers_validos).values)
    vol_actual = float(np.sqrt(pesos_actuales.values @ cov_anual.reindex(index=tickers_validos, columns=tickers_validos).values @ pesos_actuales.values))
    sharpe_actual = (rent_actual - rf_anual) / vol_actual if vol_actual > 0 else 0.0

    pesos_actual_array = pesos_actuales.reindex(tickers_validos).values

    def _indice_mas_parecido(indices):
        if len(indices) == 0:
            return None
        distancias = np.abs(pesos[indices] - pesos_actual_array).sum(axis=1)
        return int(indices[int(distancias.argmin())])

    idx_optimo_sim = int(simulaciones["Sharpe"].idxmax())
    optimo_sim = simulaciones.loc[idx_optimo_sim]
    sharpe_objetivo = float(optimo_sim["Sharpe"])
    umbral_sharpe = sharpe_objetivo - max(0.02, abs(sharpe_objetivo) * 0.02)
    indices_entorno_sharpe = simulaciones.index[simulaciones["Sharpe"] >= umbral_sharpe].to_numpy()
    idx_optimo_cercano = _indice_mas_parecido(indices_entorno_sharpe)
    if idx_optimo_cercano is None:
        idx_optimo_cercano = idx_optimo_sim
    optimo_cercano = simulaciones.loc[idx_optimo_cercano]

    if sharpe_actual >= umbral_sharpe:
        pesos_optimos = pesos_actuales.reindex(tickers_validos)
        optima = {
            "Rentabilidad": rent_actual,
            "Volatilidad": vol_actual,
            "Sharpe": sharpe_actual,
        }
    else:
        pesos_optimos = pd.Series(pesos[idx_optimo_cercano], index=tickers_validos)
        optima = {
            "Rentabilidad": float(optimo_cercano["Rentabilidad"]),
            "Volatilidad": float(optimo_cercano["Volatilidad"]),
            "Sharpe": float(optimo_cercano["Sharpe"]),
        }

    candidatas_misma_vola = simulaciones[simulaciones["Volatilidad"] <= vol_actual]
    if candidatas_misma_vola.empty:
        idx_misma_vola = int((simulaciones["Volatilidad"] - vol_actual).abs().idxmin())
        entorno_misma_vola = simulaciones.index[[idx_misma_vola]].to_numpy()
    else:
        idx_misma_vola = int(candidatas_misma_vola["Rentabilidad"].idxmax())
        rent_objetivo_misma_vola = float(simulaciones.loc[idx_misma_vola, "Rentabilidad"])
        entorno_misma_vola = candidatas_misma_vola.index[
            candidatas_misma_vola["Rentabilidad"] >= rent_objetivo_misma_vola * 0.98
        ].to_numpy()

    idx_misma_vola_cercano = _indice_mas_parecido(entorno_misma_vola)
    if idx_misma_vola_cercano is None:
        idx_misma_vola_cercano = idx_misma_vola
    candidata_misma_vola = simulaciones.loc[idx_misma_vola_cercano]

    if rent_actual >= float(simulaciones.loc[idx_misma_vola, "Rentabilidad"]) * 0.98:
        pesos_misma_vola = pesos_actuales.reindex(tickers_validos)
        misma_vola = {
            "Rentabilidad": rent_actual,
            "Volatilidad": vol_actual,
            "Sharpe": sharpe_actual,
        }
    else:
        pesos_misma_vola = pd.Series(pesos[idx_misma_vola_cercano], index=tickers_validos)
        misma_vola = {
            "Rentabilidad": float(candidata_misma_vola["Rentabilidad"]),
            "Volatilidad": float(candidata_misma_vola["Volatilidad"]),
            "Sharpe": float(candidata_misma_vola["Sharpe"]),
        }


    nombres_activos = cargar_listado_activos()
    pesos_tabla = pd.DataFrame(
        {
            "Activo": tickers_validos,
            "Nombre": [nombres_activos.get(ticker, ticker) for ticker in tickers_validos],
            "Peso_actual": pesos_actuales.reindex(tickers_validos).values,
            "Peso_optimo": pesos_optimos.reindex(tickers_validos).values,
            "Peso_misma_vola": pesos_misma_vola.reindex(tickers_validos).values,
        }
    )
    pesos_tabla["Cambio_pp"] = (pesos_tabla["Peso_optimo"] - pesos_tabla["Peso_actual"]) * 100
    pesos_tabla["Cambio_misma_vola_pp"] = (pesos_tabla["Peso_misma_vola"] - pesos_tabla["Peso_actual"]) * 100
    pesos_tabla = pesos_tabla.sort_values("Peso_optimo", ascending=False).reset_index(drop=True)

    frontera = (
        simulaciones.assign(
            tramo_vol=pd.cut(simulaciones["Volatilidad"], bins=35, duplicates="drop")
        )
        .dropna(subset=["tramo_vol"])
        .sort_values("Rentabilidad")
        .groupby("tramo_vol", observed=False)
        .tail(1)
        .sort_values("Volatilidad")
        .drop(columns="tramo_vol")
        .reset_index(drop=True)
    )

    return {
        "simulaciones": simulaciones,
        "frontera": frontera,
        "pesos": pesos_tabla,
        "actual": {
            "Rentabilidad": rent_actual,
            "Volatilidad": vol_actual,
            "Sharpe": sharpe_actual,
        },
        "optima": optima,
        "misma_vola": misma_vola,
        "aviso": aviso_fx,
    }


def _posiciones_banco_hasta(ops, fecha_corte=None):
    if fecha_corte is not None:
        ops = ops[ops["Fecha"] < fecha_corte]

    if ops.empty:
        return pd.DataFrame(columns=["Banco", "Activo", "acciones_firmadas"])

    posiciones = (
        ops.groupby(["Banco", "Activo"])["acciones_firmadas"]
        .sum()
        .reset_index()
    )
    return posiciones[posiciones["acciones_firmadas"].abs() > 1e-12].copy()


def _valorar_posiciones_banco(posiciones, precios_ref, fx_ref, divisas):
    if posiciones.empty:
        return pd.Series(dtype="float64", name="Capital_sujeto_riesgo_EUR")

    posiciones = posiciones.copy()
    posiciones["Precio"] = posiciones["Activo"].map(precios_ref)
    posiciones["Divisa"] = posiciones["Activo"].map(divisas)
    posiciones["Tipo_cambio_EUR"] = posiciones["Divisa"].map({"EUR": 1.0, "USD": fx_ref})
    posiciones["Valor_EUR"] = (
        posiciones["acciones_firmadas"]
        * posiciones["Precio"]
        * posiciones["Tipo_cambio_EUR"]
    )
    return posiciones.groupby("Banco")["Valor_EUR"].sum().rename("Capital_sujeto_riesgo_EUR")


def _twr_periodo_desde_serie(series, fecha_inicio_periodo=None, divisa="EUR"):
    columna_twr = f"TWR_{divisa.upper()}"
    if series.empty or columna_twr not in series:
        return 0.0

    twr = series[columna_twr].dropna()
    if twr.empty:
        return 0.0

    if fecha_inicio_periodo is not None:
        twr_periodo = twr.loc[twr.index >= fecha_inicio_periodo]
        twr = twr_periodo if not twr_periodo.empty else twr.tail(1)

    return float((1 + twr.iloc[-1]) / (1 + twr.iloc[0]) - 1)


def calcular_twr_por_banco(df, cash, fecha_inicio_periodo=None, divisa="EUR"):
    """Calcula TWR por banco y para el total en la divisa indicada."""
    ops = _normalizar_banco(df)
    movimientos_cash = _normalizar_banco(cash) if cash is not None else pd.DataFrame()

    if ops.empty:
        return pd.Series(dtype="float64", name="TWR")

    fecha_inicio_periodo = (
        pd.to_datetime(fecha_inicio_periodo).normalize()
        if fecha_inicio_periodo is not None
        else None
    )
    bancos = sorted(
        set(ops["Banco"].dropna())
        | set(movimientos_cash.get("Banco", pd.Series(dtype=str)).dropna())
    )
    resultados = {}

    for banco in bancos:
        ops_banco = ops[ops["Banco"].eq(banco)]
        cash_banco = movimientos_cash[movimientos_cash["Banco"].eq(banco)]
        serie_banco = calcular_series_cartera_multidivisa(ops_banco, cash_banco)
        resultados[banco] = _twr_periodo_desde_serie(serie_banco, fecha_inicio_periodo, divisa)

    serie_total = calcular_series_cartera_multidivisa(ops, movimientos_cash)
    resultados["TOTAL"] = _twr_periodo_desde_serie(serie_total, fecha_inicio_periodo, divisa)
    return pd.Series(resultados, name="TWR", dtype="float64")


def calcular_inversiones_por_banco(df, cash, fecha_inicio_periodo=None, divisa_twr="EUR"):
    """
    Resume capital aportado, valor actual y TWR por banco en EUR.
    """
    df = _normalizar_banco(df)
    movimientos_cash = _normalizar_banco(cash) if cash is not None else pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    fecha_inicio_periodo = (
        pd.to_datetime(fecha_inicio_periodo).normalize()
        if fecha_inicio_periodo is not None
        else None
    )

    ops = df.copy()
    bancos = sorted(
        set(ops["Banco"].dropna())
        | set(movimientos_cash.get("Banco", pd.Series(dtype=str)).dropna())
    )
    resumen = pd.DataFrame(index=bancos)

    if movimientos_cash.empty:
        capital_aportado = pd.Series(dtype="float64")
    else:
        es_externo = movimientos_cash["Es_flujo_externo"]
        flujos_externos = movimientos_cash[es_externo].copy()
        capital_aportado = flujos_externos.groupby("Banco")["Importe_firmado_EUR"].sum()

    resumen["Capital_invertido_EUR"] = capital_aportado.reindex(bancos).fillna(0.0)

    valores_actuales = {}
    for banco in bancos:
        serie_banco = calcular_series_cartera_multidivisa(
            ops[ops["Banco"].eq(banco)],
            movimientos_cash[movimientos_cash["Banco"].eq(banco)],
        )
        valores_actuales[banco] = (
            float(serie_banco["Valor_cartera_EUR"].iloc[-1])
            if not serie_banco.empty
            else 0.0
        )
    resumen["Capital_sujeto_riesgo_EUR"] = pd.Series(valores_actuales).reindex(bancos).fillna(0.0)

    twr_por_banco = calcular_twr_por_banco(ops, movimientos_cash, fecha_inicio_periodo, divisa_twr)
    resumen["TWR"] = twr_por_banco.reindex(resumen.index).fillna(0.0)
    resumen = resumen.reset_index(names="Banco")

    total = pd.DataFrame({
        "Banco": ["TOTAL"],
        "Capital_invertido_EUR": [resumen["Capital_invertido_EUR"].sum()],
        "Capital_sujeto_riesgo_EUR": [resumen["Capital_sujeto_riesgo_EUR"].sum()],
    })
    total["TWR"] = twr_por_banco.get("TOTAL", 0.0)

    resumen = resumen.sort_values("Capital_sujeto_riesgo_EUR", ascending=False)
    return pd.concat([resumen, total], ignore_index=True)[
        [
            "Banco",
            "Capital_invertido_EUR",
            "Capital_sujeto_riesgo_EUR",
            "TWR",
        ]
    ]


def calcular_proximos_dividendos(df):
    posiciones = calcular_posiciones_actuales(df)

    if posiciones.empty:
        return pd.DataFrame()

    hoy = pd.Timestamp.today().normalize()
    filas = []

    for ticker, acciones in posiciones.items():
        try:
            ticker_yahoo = yf.Ticker(ticker, session=obtener_sesion_yahoo())
            info = ticker_yahoo.get_info() if hasattr(ticker_yahoo, "get_info") else ticker_yahoo.info
        except Exception:
            ticker_yahoo = None
            info = {}

        fecha_ex = _fecha_yahoo(_valor_info(info, ["exDividendDate"]))
        fecha_pago = _fecha_yahoo(_valor_info(info, ["dividendDate"]))
        fecha_proxima = fecha_pago or fecha_ex

        if fecha_proxima is not None and fecha_proxima < hoy:
            fecha_proxima = None

        dividendos = _dividendos_historicos(ticker_yahoo) if ticker_yahoo is not None else pd.Series(dtype="float64")
        dividendo_accion = None if dividendos.empty else float(dividendos.iloc[-1])
        dividendo_anual = _dividendo_anualizado_forward(dividendos, info)
        precio = _precio_actual_info(info)
        dividend_yield = dividendo_anual / precio if dividendo_anual is not None and precio else None
        importe_estimado = float(acciones) * dividendo_accion if dividendo_accion is not None else None
        divisa = _valor_info(info, ["currency", "financialCurrency"])

        if fecha_proxima is None and dividendo_accion is None and dividend_yield is None:
            continue

        if fecha_proxima is not None:
            estado = "Anunciado"
        elif dividendo_accion is not None or dividend_yield is not None:
            estado = "Sin fecha anunciada"
        else:
            estado = "Sin dato"

        filas.append(
            {
                "Activo": ticker,
                "Acciones": float(acciones),
                "Divisa": divisa,
                "Fecha": fecha_proxima,
                "Fecha_ex": fecha_ex,
                "Dividendo_accion": dividendo_accion,
                "Importe_estimado": importe_estimado,
                "Dividend_yield": dividend_yield,
                "Estado": estado,
            }
        )

    dividendos = pd.DataFrame(filas)

    if dividendos.empty:
        return dividendos

    dividendos["orden_fecha"] = dividendos["Fecha"].fillna(pd.Timestamp.max)
    dividendos = dividendos.sort_values(["orden_fecha", "Activo"]).drop(columns="orden_fecha")
    return dividendos.reset_index(drop=True)


def calcular_desglose_fx_eur(df, cash):
    """Compatibilidad: devuelve las series principales ya calculadas en EUR/USD."""
    return calcular_series_cartera_multidivisa(df, cash)


def calcular_operaciones_cerradas(df):
    """
    Calcula las operaciones cerradas en EUR.

    Si falta Tipo_cambio_EUR en alguna operación USD, no bloquea la app:
    estima el cambio USD->EUR con USDEUR=X en la primera sesión disponible
    igual o posterior a la fecha de la operación.
    """
    df = df.copy()

    if df.empty:
        return pd.DataFrame()

    necesita_fx = (
        "Importe_EUR" not in df.columns
        or df["Importe_EUR"].isna().any()
    )

    if necesita_fx:
        try:
            fecha_inicio = df["Fecha"].min()
            fx_usdeur = descargar_fx_usdeur(fecha_inicio)
            df["Importe_EUR_calc"] = _importes_operaciones_eur(df, fx_usdeur.index, fx_usdeur)
        except Exception:
            # Fallback conservador: usa lo que ya exista en Importe_EUR y,
            # para EUR, calcula el importe directamente en EUR. Así la app no
            # se rompe si Yahoo falla, aunque las operaciones USD sin cambio
            # seguirán sin entrar en la tabla de cerradas.
            df["Importe_EUR_calc"] = df.get("Importe_EUR", pd.Series(index=df.index, dtype="float64"))
            mask_eur = df["Currency"].eq("EUR") & df["Importe_EUR_calc"].isna()
            df.loc[mask_eur, "Importe_EUR_calc"] = df.loc[mask_eur, "Importe"]
    else:
        df["Importe_EUR_calc"] = df["Importe_EUR"].astype(float)

    # Evita que una conversión incompleta de un activo cerrado produzca
    # importes falsos por sumar NaN como cero. Si algún activo no puede
    # convertirse, se omite solo en la tabla de operaciones cerradas.
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
    nombres = cargar_listado_activos()
    operaciones["Nombre"] = operaciones["Activo"].map(nombres).fillna(operaciones["Activo"])

    return operaciones[
        [
            "Activo",
            "Nombre",
            "Periodo",
            "Fecha_fin",
            "Rentabilidad",
            "Rent. anualizada",
            "Capital_invertido",
        ]
    ]


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
