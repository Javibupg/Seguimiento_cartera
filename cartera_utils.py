from pathlib import Path
from datetime import date, timedelta

import pandas as pd
import yfinance as yf


EXCEL_PATH = Path("Libro_inversiones.xlsx")


def cargar_operaciones(path=EXCEL_PATH):
    """
    Lee el Excel de inversiones, calcula el importe de cada operación y devuelve un DataFrame limpio.
    """
    df = pd.read_excel(path, sheet_name="Operaciones")
    df.columns = df.columns.str.strip()
    
    df["Fecha"] = pd.to_datetime(df["Fecha"])
    df["Orden"] = df["Orden"].str.lower().str.strip()
    df["signo"] = df["Orden"].map({
        "compra": 1,
        "venta": -1
    })
    df["acciones_firmadas"] = df["Numero_acciones"] * df["signo"]
    df["Importe"] = df["Numero_acciones"] * df["Precio_ejecutado"]
    df = df.sort_values("Fecha").reset_index(drop=True)

    return df


def cargar_movimientos_cash(path=EXCEL_PATH):
    """
    Lee la hoja Cash con aportaciones y retiradas reales de dinero.
    """
    cash = pd.read_excel(path, sheet_name="Cash")
    cash.columns = cash.columns.str.strip()

    # Por si la fecha viene como número de Excel
    cash["Fecha"] = pd.to_datetime(cash["Fecha"])
    cash["Tipo"] = cash["Tipo"].str.lower().str.strip()
    cash["signo"] = cash["Tipo"].map({
        "aportación": 1,
        "retirada": -1
    })
    cash["Importe_firmado"] = cash["Importe"] * cash["signo"]
    cash["Importe_firmado_EUR"] = cash["Importe_firmado"] * cash["Tipo_cambio_EUR"]
    cash = cash.sort_values("Fecha").reset_index(drop=True)

    return cash


def calcular_capital_acumulado(cash, indice, columna_importe="Importe_firmado"):
    """
    Calcula el capital neto aportado a la cartera usando solo la hoja Cash.
    Si una aportación cae en fin de semana/festivo, se asigna al siguiente día con precio disponible.
    """
    if columna_importe not in cash.columns:
        raise ValueError(f"No existe la columna '{columna_importe}' en la hoja Cash.")

    flujos = pd.Series(0.0, index=indice.index)

    for fecha, importe in cash.groupby("Fecha")[columna_importe].sum().items():
        fechas_validas = flujos.index[flujos.index >= fecha]
        if len(fechas_validas) > 0:
            flujos.loc[fechas_validas[0]] += importe

    capital_acumulado = flujos.cumsum()

    return flujos, capital_acumulado


def calcular_posiciones_actuales(df):
    """
    Calcula cuántas acciones quedan actualmente de cada activo.
    """
    posiciones = (
        df.groupby("Activo")["acciones_firmadas"]
        .sum()
        .loc[lambda x: x != 0]
    )

    return posiciones


def calcular_rentabilidad_diaria_ajustada(valor_cartera, flujos):
    """
    Calcula rentabilidades diarias ajustadas por aportaciones y retiradas externas.
    Esta es la base de la TWR, la volatilidad y el Sharpe.
    """
    flujos = flujos.reindex(valor_cartera.index, fill_value=0)
    rent_diaria = (valor_cartera - valor_cartera.shift(1) - flujos) / valor_cartera.shift(1)
    rent_diaria = rent_diaria.replace([float("inf"), -float("inf")], pd.NA).fillna(0)

    return rent_diaria


def calcular_rentabilidad_twr(valor_cartera, flujos):
    """
    Calcula la rentabilidad TWR de la cartera.
    No se ve distorsionada por nuevas aportaciones o retiradas de dinero.
    """
    rent_diaria = calcular_rentabilidad_diaria_ajustada(valor_cartera, flujos)
    rentabilidad_twr = (1 + rent_diaria).cumprod() - 1

    return rentabilidad_twr


def calcular_vol_sharpe(valor_cartera, flujos, ventana=252, rf_anual=0):
    """
    Calcula volatilidad anualizada y Sharpe usando rentabilidades diarias
    ajustadas por aportaciones/retiros.
    """
    rent_diaria = calcular_rentabilidad_diaria_ajustada(valor_cartera, flujos).dropna()

    if ventana is not None:
        rent_diaria = rent_diaria.tail(ventana)

    if rent_diaria.empty or rent_diaria.std() == 0:
        return 0, 0

    vol = rent_diaria.std() * (252 ** 0.5)
    rf_diario = (1 + rf_anual) ** (1 / 252) - 1
    sharpe = ((rent_diaria.mean() - rf_diario) / rent_diaria.std()) * (252 ** 0.5)

    return vol, sharpe


def descargar_precios(tickers, fecha_inicio):
    """
    Descarga precios históricos ajustados desde Yahoo Finance.
    """
    if isinstance(tickers, str):
        tickers = [tickers]
    else:
        tickers = list(tickers)

    precios = yf.download(
        tickers=tickers,
        start=fecha_inicio,
        auto_adjust=True,
        progress=False
    )["Close"]

    if isinstance(precios, pd.Series):
        precios = precios.to_frame(name=tickers[0])

    return precios.ffill()


def calcular_valor_actual_cartera(df, cash):
    """
    Calcula el valor actual de la cartera incluyendo acciones y cash.
    """
    cartera = calcular_historico_cartera(df, cash)

    if cartera.empty:
        return 0.0

    return cartera.iloc[-1]


def calcular_historico_cartera(df, cash):
    """
    Calcula el valor histórico de la cartera incluyendo acciones y cash.
    """
    tickers = sorted(df["Activo"].unique())
    fecha_inicio = min(df["Fecha"].min(), cash["Fecha"].min())

    precios = descargar_precios(tickers, fecha_inicio)

    posiciones = pd.DataFrame(
        0.0,
        index=precios.index,
        columns=tickers
    )

    cash_diario = pd.Series(
        0.0,
        index=precios.index
    )

    # Compras y ventas de acciones
    for _, fila in df.iterrows():
        ticker = fila["Activo"]
        fecha = fila["Fecha"]
        acciones = fila["acciones_firmadas"]
        importe = fila["Importe"]

        posiciones.loc[posiciones.index >= fecha, ticker] += acciones

        if fila["Orden"] == "compra":
            cash_diario.loc[cash_diario.index >= fecha] -= importe

        elif fila["Orden"] == "venta":
            cash_diario.loc[cash_diario.index >= fecha] += importe

    # Aportaciones y retiradas reales de dinero
    for _, fila in cash.iterrows():
        fecha = fila["Fecha"]
        importe = fila["Importe_firmado"]

        cash_diario.loc[cash_diario.index >= fecha] += importe

    valor_acciones = (posiciones * precios).sum(axis=1)

    cartera = valor_acciones + cash_diario

    return cartera


def calcular_rentabilidad_sobre_capital_aportado(df, cash):
    """
    Calcula la rentabilidad simple sobre capital neto aportado.
    Ojo: esta métrica puede bajar artificialmente cuando se mete dinero nuevo.
    """
    cartera = calcular_historico_cartera(df, cash)
    _, capital_acumulado = calcular_capital_acumulado(cash, cartera)
    rentabilidad = (cartera - capital_acumulado) / capital_acumulado
    rentabilidad = rentabilidad.replace([float("inf"), -float("inf")], 0).fillna(0)

    return rentabilidad


def calcular_desempeno_cartera(df, cash):
    """
    Calcula la rentabilidad TWR de la cartera, ajustada por aportaciones y retiradas.
    """
    cartera = calcular_historico_cartera(df, cash)
    flujos, _ = calcular_capital_acumulado(cash, cartera)

    return calcular_rentabilidad_twr(cartera, flujos)


def calcular_desglose_fx_eur(df, cash):
    """
    Desagrega el resultado de la cartera en EUR entre efecto activos y efecto FX
    """
    cartera_usd = calcular_historico_cartera(df, cash)

    if cartera_usd.empty:
        return pd.DataFrame()

    fecha_inicio = min(df["Fecha"].min(), cash["Fecha"].min())

    # Descargamos el tipo de cambio EUR por USD usando la función general
    fx = descargar_precios("USDEUR=X", fecha_inicio)["USDEUR=X"]
    fx = fx.reindex(cartera_usd.index).ffill()

    _, capital_usd = calcular_capital_acumulado( cash, cartera_usd, columna_importe="Importe_firmado")
    _, capital_eur = calcular_capital_acumulado(cash, cartera_usd, columna_importe="Importe_firmado_EUR")

    valor_cartera_eur = cartera_usd * fx
    resultado_total_eur = valor_cartera_eur - capital_eur

    # Efecto activos:
    efecto_activos_eur = (cartera_usd - capital_usd) * fx

    # Efecto FX:
    efecto_fx_eur = resultado_total_eur - efecto_activos_eur

    desglose = pd.DataFrame(index=cartera_usd.index)

    desglose["Valor_cartera_USD"] = cartera_usd
    desglose["Capital_USD"] = capital_usd
    desglose["FX_EUR_por_USD"] = fx

    desglose["Valor_cartera_EUR"] = valor_cartera_eur
    desglose["Capital_EUR"] = capital_eur

    desglose["Resultado_total_EUR"] = resultado_total_eur
    desglose["Efecto_activos_EUR"] = efecto_activos_eur
    desglose["Efecto_FX_EUR"] = efecto_fx_eur

    desglose["Rentabilidad_total_EUR"] = resultado_total_eur / capital_eur
    desglose["Rentabilidad_activos_EUR"] = efecto_activos_eur / capital_eur
    desglose["Rentabilidad_FX_EUR"] = efecto_fx_eur / capital_eur

    flujos_eur = capital_eur.diff().fillna(capital_eur)
    desglose["Rentabilidad_TWR_EUR"] = calcular_rentabilidad_twr(valor_cartera_eur, flujos_eur)

    columnas_rentabilidad = [
        "Rentabilidad_total_EUR",
        "Rentabilidad_activos_EUR",
        "Rentabilidad_FX_EUR",
        "Rentabilidad_TWR_EUR"
    ]

    desglose[columnas_rentabilidad] = (
        desglose[columnas_rentabilidad]
        .replace([float("inf"), -float("inf")], 0)
        .fillna(0)
    )

    return desglose


def calcular_operaciones_cerradas(df):
    """
    Calcula operaciones cerradas por activo usando precio medio de compra y venta.
    No aplica FIFO.
    """
    compras = df[df["Orden"] == "compra"].groupby("Activo").agg(
        Fecha_inicio=("Fecha", "min"),
        Acciones_compradas=("Numero_acciones", "sum"),
        Capital_comprado=("Importe", "sum")
    )

    ventas = df[df["Orden"] == "venta"].groupby("Activo").agg(
        Fecha_fin=("Fecha", "max"),
        Acciones_vendidas=("Numero_acciones", "sum"),
        Valor_venta_total=("Importe", "sum")
    )

    operaciones = compras.join(ventas, how="inner").reset_index()
    if operaciones.empty:
        return operaciones

    acciones_cerradas = operaciones[["Acciones_compradas", "Acciones_vendidas"]].min(axis=1)

    precio_medio_compra = operaciones["Capital_comprado"] / operaciones["Acciones_compradas"]
    precio_medio_venta = operaciones["Valor_venta_total"] / operaciones["Acciones_vendidas"]

    operaciones["Capital_invertido"] = acciones_cerradas * precio_medio_compra
    operaciones["Valor_venta"] = acciones_cerradas * precio_medio_venta
    operaciones["Resultado"] = operaciones["Valor_venta"] - operaciones["Capital_invertido"]
    operaciones["Rentabilidad"] = operaciones["Resultado"] / operaciones["Capital_invertido"]

    dias = (operaciones["Fecha_fin"] - operaciones["Fecha_inicio"]).dt.days
    operaciones["Rent. anualizada"] = (1 + operaciones["Rentabilidad"]) ** (365 / dias) - 1

    operaciones["Periodo"] = (
        operaciones["Fecha_inicio"].dt.strftime("%d/%m/%y")
        + "-"
        + operaciones["Fecha_fin"].dt.strftime("%d/%m/%y")
    )

    return operaciones[[
        "Activo", "Periodo", "Rentabilidad", "Rent. anualizada", "Capital_invertido"
    ]]
    
    