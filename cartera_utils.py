from pathlib import Path

import pandas as pd
import yfinance as yf

EXCEL_PATH = Path("Libro_inversiones.xlsx")
MONEDAS_SOPORTADAS = {"EUR", "USD"}
SUFIJOS_EUR = (".MI", ".PA", ".MC", ".DE", ".AS", ".BR", ".VI", ".F", ".MU", ".BE", ".HM", ".DU")


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
    datos = yf.download(tickers=tickers, start=fecha_inicio, auto_adjust=True, progress=False)

    if datos.empty:
        return pd.DataFrame(columns=tickers)

    if isinstance(datos.columns, pd.MultiIndex):
        if "Close" in datos.columns.get_level_values(0):
            precios = datos["Close"]
        elif "Close" in datos.columns.get_level_values(-1):
            precios = datos.xs("Close", axis=1, level=-1)
        else:
            return pd.DataFrame(columns=tickers)
    else:
        precios = datos["Close"] if "Close" in datos.columns else datos

    if isinstance(precios, pd.Series):
        precios = precios.to_frame(name=tickers[0])

    precios = precios.reindex(columns=tickers)
    return precios.ffill().dropna(how="all")


def descargar_fx_usdeur(fecha_inicio, indice=None):
    fx = descargar_precios("USDEUR=X", fecha_inicio)

    if fx.empty:
        raise ValueError("No se pudo descargar el tipo de cambio USDEUR=X desde Yahoo Finance.")

    col = "USDEUR=X" if "USDEUR=X" in fx.columns else fx.columns[0]
    fx = fx[col].dropna().astype(float)

    if indice is not None:
        fx = fx.reindex(pd.DatetimeIndex(indice)).ffill().bfill()

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
