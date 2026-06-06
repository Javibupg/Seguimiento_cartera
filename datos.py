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

# Cálculos comunes de toda la app. La divisa base interna es EUR.
operaciones = cargar_operaciones()
cash = cargar_movimientos_cash()
series_cartera = calcular_series_cartera_multidivisa(operaciones, cash)

# La tabla de operaciones cerradas es informativa. No debe bloquear el arranque
# de la app si falta algún tipo de cambio histórico o si Yahoo no responde.
try:
    operaciones_cerradas = calcular_operaciones_cerradas(operaciones)
except Exception as e:
    print(f"Aviso: no se pudieron calcular las operaciones cerradas: {e}")
    operaciones_cerradas = pd.DataFrame()

# Alias para no romper imports antiguos.
cartera_eur = series_cartera.get("Valor_cartera_EUR", pd.Series(dtype="float64")) if not series_cartera.empty else pd.Series(dtype="float64")
flujos_eur = series_cartera.get("Flujos_EUR", pd.Series(dtype="float64")) if not series_cartera.empty else pd.Series(dtype="float64")
capital_eur = series_cartera.get("Capital_EUR", pd.Series(dtype="float64")) if not series_cartera.empty else pd.Series(dtype="float64")
twr_eur = series_cartera.get("TWR_EUR", pd.Series(dtype="float64")) if not series_cartera.empty else pd.Series(dtype="float64")

cartera_usd = series_cartera.get("Valor_cartera_USD", pd.Series(dtype="float64")) if not series_cartera.empty else pd.Series(dtype="float64")
flujos_usd = series_cartera.get("Flujos_USD", pd.Series(dtype="float64")) if not series_cartera.empty else pd.Series(dtype="float64")
capital_usd = series_cartera.get("Capital_USD", pd.Series(dtype="float64")) if not series_cartera.empty else pd.Series(dtype="float64")
twr_usd = series_cartera.get("TWR_USD", pd.Series(dtype="float64")) if not series_cartera.empty else pd.Series(dtype="float64")

desglose_fx = series_cartera


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


def preparar_datos_divisa(periodo, divisa="eur"):
    divisa = divisa.lower()

    if series_cartera.empty:
        return pd.DataFrame(columns=["valor", "capital", "flujos", "twr"])

    sufijo = divisa.upper()
    datos = pd.DataFrame({
        "valor": series_cartera[f"Valor_cartera_{sufijo}"],
        "capital": series_cartera[f"Capital_{sufijo}"],
        "flujos": series_cartera[f"Flujos_{sufijo}"],
        "twr": series_cartera[f"TWR_{sufijo}"],
    }).dropna()

    datos = filtrar_periodo(datos, periodo)
    datos["twr"] = rebasear_twr(datos["twr"])
    return datos


def preparar_datos_eur(periodo):
    return preparar_datos_divisa(periodo, "eur")


def preparar_datos_usd(periodo):
    return preparar_datos_divisa(periodo, "usd")


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


def simbolo_divisa(divisa):
    return "€" if divisa.lower() == "eur" else "$"


def calcular_distribucion_actual():
    return calcular_distribucion_actual_multidivisa(operaciones, cash)

def calcular_historico_posicion(activo):
    return calcular_historico_posicion_abierta(operaciones, cash, activo)

def obtener_opciones_posiciones_abiertas():
    posiciones = calcular_posiciones_actuales(operaciones)
    nombres = cargar_listado_activos()
    if posiciones.empty:
        return []
    tickers = sorted(posiciones.index.tolist(), key=lambda t: nombres.get(t, t))
    return [{"label": f"{nombres.get(t, t)} ({t})", "value": t} for t in tickers]

