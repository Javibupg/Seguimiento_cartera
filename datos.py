import pandas as pd

from cartera_utils import *
from auxfun import titulo_tarjeta

RF_ANUAL, RF_FECHA = obtener_rf_anual_eur()
TOOLTIP_TWR = "Rentabilidad TWR no anualizada. Ajusta las aportaciones y retiradas para que meter dinero nuevo no baje ni suba artificialmente la rentabilidad."

PERIODOS = {
    "1w": {"label": "1S", "nombre": "1 semana", "offset": pd.DateOffset(weeks=1)},
    "1m": {"label": "1M", "nombre": "1 mes", "offset": pd.DateOffset(months=1)},
    "6m": {"label": "6M", "nombre": "6 meses", "offset": pd.DateOffset(months=6)},
    "1y": {"label": "1A", "nombre": "1 año", "offset": pd.DateOffset(years=1)},
    "5y": {"label": "5A", "nombre": "5 años", "offset": pd.DateOffset(years=5)},
    "max": {"label": "Máx", "nombre": "máximo", "offset": None},
}

ESTILO_BOTON = {"display": "inline-block", "padding": "10px 18px", "marginRight": "10px", "border": "1px solid #d1d5db", "borderRadius": "10px", "cursor": "pointer", "backgroundColor": "#f9fafb", "fontWeight": "600"}

# Cálculos comunes de toda la app.
operaciones = cargar_operaciones()
cash = cargar_movimientos_cash()
cartera_usd = calcular_historico_cartera(operaciones, cash)
flujos_usd, capital_usd = calcular_capital_acumulado(cash, cartera_usd, "Importe_firmado")
twr_usd = calcular_twr(cartera_usd, flujos_usd)
desglose_fx = calcular_desglose_fx_eur(operaciones, cash)
operaciones_cerradas = calcular_operaciones_cerradas(operaciones)


def tooltip_sharpe():
    fecha = f" Última observación BCE: {RF_FECHA}." if RF_FECHA else " Si no hay conexión, se usa fallback 2,00%."
    return f"Sharpe anualizado calculado con rentabilidades diarias ajustadas por flujos y tipo libre de riesgo EUR BCE: {RF_ANUAL * 100:.2f}%." + fecha


def filtrar_periodo(datos, periodo):
    if datos is None or datos.empty or periodo == "max":
        return datos.copy()
    fecha_inicio = datos.index.max() - PERIODOS[periodo]["offset"]
    filtrado = datos.loc[datos.index >= fecha_inicio].copy()
    return filtrado if not filtrado.empty else datos.tail(1).copy()


def rebasear_twr(s):
    return s * 0 if s.empty else (1 + s) / (1 + s.iloc[0]) - 1


def preparar_datos_usd(periodo):
    datos = pd.DataFrame({"valor": cartera_usd, "capital": capital_usd, "flujos": flujos_usd, "twr": twr_usd}).dropna()
    datos = filtrar_periodo(datos, periodo)
    datos["twr"] = rebasear_twr(datos["twr"])
    return datos


def preparar_datos_eur(periodo):
    if desglose_fx.empty:
        return desglose_fx.copy()
    datos = filtrar_periodo(desglose_fx, periodo)
    for col in ["TWR_total_EUR", "TWR_activos_USD", "TWR_FX_EUR"]:
        datos[col] = rebasear_twr(datos[col])
    return datos


def calcular_metricas_periodo(valor, capital, flujos, twr, periodo):
    if valor.empty:
        return 0, 0, 0, 0, 0, 0
    primera = capital.iloc[-1] if periodo == "max" else valor.iloc[0]
    resultado = valor.iloc[-1] - capital.iloc[-1] if periodo == "max" else valor.iloc[-1] - valor.iloc[0] - flujos.iloc[1:].sum()
    vol, sharpe = calcular_vol_sharpe(valor, flujos, ventana=None, rf_anual=RF_ANUAL)
    return primera, valor.iloc[-1], resultado, twr.iloc[-1], vol, sharpe


def formatear_importe(valor, simbolo):
    return f"{simbolo}{valor:,.2f}"


def titulo_primera_tarjeta(divisa, periodo):
    return f"Capital invertido {divisa}" if periodo == "max" else f"Valor inicial {divisa}"


def titulo_resultado(divisa, periodo):
    texto = f"Resultado {divisa}" if periodo == "max" else f"Resultado {divisa} · {PERIODOS[periodo]['label']}"
    return titulo_tarjeta(texto, TOOLTIP_TWR)


def calcular_distribucion_actual():
    posiciones = calcular_posiciones_actuales(operaciones)

    if posiciones.empty or cartera_usd.empty:
        return pd.DataFrame(), 0.0, 0.0, 0.0

    tickers = posiciones.index.tolist()

    precios = descargar_precios(tickers, operaciones["Fecha"].min())
    ultimos_precios = precios.ffill().iloc[-1].reindex(tickers)

    distribucion = pd.DataFrame({
        "Activo": tickers,
        "Acciones": posiciones.reindex(tickers).values,
        "Precio_actual": ultimos_precios.values,
    })

    distribucion["Valor_USD"] = distribucion["Acciones"] * distribucion["Precio_actual"]

    valor_acciones = float(distribucion["Valor_USD"].sum())
    valor_total = valor_acciones
    cash_actual = 0.0

    distribucion["Peso"] = (
        distribucion["Valor_USD"] / valor_acciones
        if valor_acciones != 0
        else 0
    )

    distribucion = (
        distribucion
        .sort_values("Valor_USD", ascending=False)
        .reset_index(drop=True)
    )

    return distribucion, valor_acciones, cash_actual, valor_total
