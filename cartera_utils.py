from pathlib import Path
import pandas as pd
import yfinance as yf

EXCEL_PATH = Path("Libro_inversiones.xlsx")


def _limpiar_texto(s):
    return s.astype(str).str.lower().str.strip()


def _sin_inf(s):
    return s.replace([float("inf"), -float("inf")], 0).fillna(0)


def cargar_operaciones(path=EXCEL_PATH):
    df = pd.read_excel(path, sheet_name="Operaciones")
    df.columns = df.columns.str.strip()
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    df["Orden"] = _limpiar_texto(df["Orden"])
    df["signo"] = df["Orden"].map({"compra": 1, "venta": -1})
    if df["signo"].isna().any():
        raise ValueError("Hay operaciones distintas de 'compra' o 'venta' en la hoja Operaciones.")
    df["acciones_firmadas"] = df["Numero_acciones"] * df["signo"]
    df["Importe"] = df["Numero_acciones"] * df["Precio_ejecutado"]
    return df.sort_values("Fecha").reset_index(drop=True)


def cargar_movimientos_cash(path=EXCEL_PATH):
    cash = pd.read_excel(path, sheet_name="Cash")
    cash.columns = cash.columns.str.strip()
    cash["Fecha"] = pd.to_datetime(cash["Fecha"])
    cash["Tipo"] = _limpiar_texto(cash["Tipo"])
    cash["signo"] = cash["Tipo"].map({"aportación": 1, "aportacion": 1, "retirada": -1})
    if cash["signo"].isna().any():
        raise ValueError("Hay movimientos distintos de 'aportación' o 'retirada' en la hoja Cash.")
    cash["Importe_firmado"] = cash["Importe"] * cash["signo"]
    cash["Importe_firmado_EUR"] = cash["Importe_firmado"] * cash["Tipo_cambio_EUR"]
    return cash.sort_values("Fecha").reset_index(drop=True)


def _alinear_flujos(fechas, importes, indice):
    """Coloca cada flujo en la primera fecha disponible del índice >= a su fecha real."""
    idx = pd.DatetimeIndex(indice)
    serie = pd.Series(0.0, index=idx)
    for fecha, importe in zip(pd.to_datetime(fechas), importes):
        pos = idx.searchsorted(fecha)
        if pos < len(idx):
            serie.iloc[pos] += float(importe)
    return serie


def calcular_capital_acumulado(cash, indice, columna_importe="Importe_firmado"):
    if columna_importe not in cash.columns:
        raise ValueError(f"No existe la columna '{columna_importe}' en la hoja Cash.")
    flujos = _alinear_flujos(cash["Fecha"], cash[columna_importe], indice.index)
    return flujos, flujos.cumsum()


def calcular_posiciones_actuales(df):
    return df.groupby("Activo")["acciones_firmadas"].sum().loc[lambda x: x != 0]


def descargar_precios(tickers, fecha_inicio):
    tickers = [tickers] if isinstance(tickers, str) else list(tickers)
    precios = yf.download(tickers=tickers, start=fecha_inicio, auto_adjust=True, progress=False)["Close"]
    if isinstance(precios, pd.Series):
        precios = precios.to_frame(name=tickers[0])
    return precios.ffill().dropna(how="all")


def calcular_historico_cartera(df, cash):
    tickers = sorted(df["Activo"].unique())
    fecha_inicio = min(df["Fecha"].min(), cash["Fecha"].min())
    precios = descargar_precios(tickers, fecha_inicio)
    if precios.empty:
        return pd.Series(dtype="float64")

    posiciones = pd.DataFrame(0.0, index=precios.index, columns=tickers)
    for ticker, ops in df.groupby("Activo"):
        eventos = _alinear_flujos(ops["Fecha"], ops["acciones_firmadas"], precios.index)
        posiciones[ticker] = eventos.cumsum()

    signo_cash_operacion = df["Orden"].map({"compra": -1, "venta": 1})
    flujos_operaciones = _alinear_flujos(df["Fecha"], df["Importe"] * signo_cash_operacion, precios.index)
    flujos_externos = _alinear_flujos(cash["Fecha"], cash["Importe_firmado"], precios.index)
    cash_diario = (flujos_operaciones + flujos_externos).cumsum()
    return (posiciones * precios).sum(axis=1) + cash_diario


def calcular_valor_actual_cartera(df, cash):
    cartera = calcular_historico_cartera(df, cash)
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


def calcular_desempeno_cartera(df, cash):
    cartera = calcular_historico_cartera(df, cash)
    flujos, _ = calcular_capital_acumulado(cash, cartera)
    return calcular_twr(cartera, flujos)


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


def calcular_desglose_fx_eur(df, cash):
    cartera_usd = calcular_historico_cartera(df, cash)
    if cartera_usd.empty:
        return pd.DataFrame()

    fecha_inicio = min(df["Fecha"].min(), cash["Fecha"].min())
    fx = descargar_precios("USDEUR=X", fecha_inicio)["USDEUR=X"].reindex(cartera_usd.index).ffill()
    flujos_usd, capital_usd = calcular_capital_acumulado(cash, cartera_usd, "Importe_firmado")
    flujos_eur, capital_eur = calcular_capital_acumulado(cash, cartera_usd, "Importe_firmado_EUR")

    valor_eur = cartera_usd * fx
    resultado_total_eur = valor_eur - capital_eur
    efecto_activos_eur = (cartera_usd - capital_usd) * fx
    efecto_fx_eur = resultado_total_eur - efecto_activos_eur

    twr_total_eur = calcular_twr(valor_eur, flujos_eur)
    twr_activos_usd = calcular_twr(cartera_usd, flujos_usd)
    twr_fx_eur = _sin_inf((1 + twr_total_eur) / (1 + twr_activos_usd) - 1)

    desglose = pd.DataFrame(index=cartera_usd.index)
    desglose["Valor_cartera_USD"], desglose["Capital_USD"], desglose["Flujos_USD"] = cartera_usd, capital_usd, flujos_usd
    desglose["FX_EUR_por_USD"] = fx
    desglose["Valor_cartera_EUR"], desglose["Capital_EUR"], desglose["Flujos_EUR"] = valor_eur, capital_eur, flujos_eur
    desglose["Resultado_total_EUR"], desglose["Efecto_activos_EUR"], desglose["Efecto_FX_EUR"] = resultado_total_eur, efecto_activos_eur, efecto_fx_eur
    desglose["TWR_total_EUR"], desglose["TWR_activos_USD"], desglose["TWR_FX_EUR"] = twr_total_eur, twr_activos_usd, twr_fx_eur

    for col in ["Rentabilidad_total_EUR", "Rentabilidad_activos_EUR", "Rentabilidad_FX_EUR"]:
        desglose[col] = 0.0
    desglose["Rentabilidad_total_EUR"] = _sin_inf(resultado_total_eur / capital_eur)
    desglose["Rentabilidad_activos_EUR"] = _sin_inf(efecto_activos_eur / capital_eur)
    desglose["Rentabilidad_FX_EUR"] = _sin_inf(efecto_fx_eur / capital_eur)
    return desglose


def calcular_operaciones_cerradas(df):
    compras = df[df["Orden"] == "compra"].groupby("Activo").agg(Fecha_inicio=("Fecha", "min"), Acciones_compradas=("Numero_acciones", "sum"), Capital_comprado=("Importe", "sum"))
    ventas = df[df["Orden"] == "venta"].groupby("Activo").agg(Fecha_fin=("Fecha", "max"), Acciones_vendidas=("Numero_acciones", "sum"), Valor_venta_total=("Importe", "sum"))
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