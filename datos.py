import pandas as pd

from auxfun import titulo_tarjeta
from cartera_utils import (
    calcular_cash_disponible,
    calcular_distribucion_actual_multidivisa,
    calcular_inversiones_por_banco,
    calcular_operaciones_abiertas,
    calcular_operaciones_cerradas,
    calcular_proximos_dividendos,
    calcular_series_cartera_multidivisa,
    calcular_vol_sharpe,
    cargar_movimientos_cash,
    cargar_operaciones,
    obtener_rf_anual_eur,
)

RF_ANUAL, RF_FECHA = obtener_rf_anual_eur()
TOOLTIP_TWR = "Rentabilidad TWR no anualizada. Ajusta las aportaciones y retiradas para que meter dinero nuevo no baje ni suba artificialmente la rentabilidad."
TOOLTIP_RESULTADO = "Ganancia o perdida ajustada por aportaciones y retiradas. El porcentaje se calcula sobre el capital expuesto del periodo para que importe y porcentaje sean comparables."
MIN_SESIONES_VOLATILIDAD = 20
MIN_SESIONES_SHARPE = 120
MIN_DIAS_TWR_ANUALIZADO = 150

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
    operaciones_abiertas = calcular_operaciones_abiertas(operaciones, cash)
except Exception as e:
    print(f"Aviso: no se pudieron calcular las operaciones abiertas: {e}")
    operaciones_abiertas = pd.DataFrame()

try:
    cash_disponible = calcular_cash_disponible(operaciones, cash)
except Exception as e:
    print(f"Aviso: no se pudo calcular el cash disponible: {e}")
    cash_disponible = pd.DataFrame()

try:
    operaciones_cerradas = calcular_operaciones_cerradas(operaciones)
except Exception as e:
    print(f"Aviso: no se pudieron calcular las operaciones cerradas: {e}")
    operaciones_cerradas = pd.DataFrame()

try:
    inversiones_por_banco = calcular_inversiones_por_banco(operaciones, cash)
except Exception as e:
    print(f"Aviso: no se pudo calcular el resumen por banco: {e}")
    inversiones_por_banco = pd.DataFrame()

try:
    proximos_dividendos = calcular_proximos_dividendos(operaciones)
except Exception as e:
    print(f"Aviso: no se pudieron calcular los próximos dividendos: {e}")
    proximos_dividendos = pd.DataFrame()

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


def tooltip_volatilidad(sesiones):
    base = "Desviacion tipica de retornos diarios anualizada con raiz de 252."
    if sesiones < MIN_SESIONES_VOLATILIDAD:
        return f"{base} Requiere al menos {MIN_SESIONES_VOLATILIDAD} sesiones; la ventana tiene {sesiones}."
    return f"{base} Calculada con {sesiones} sesiones de mercado."


def calcular_twr_anualizado(twr):
    if twr.empty:
        return None, 0

    dias = max((twr.index[-1] - twr.index[0]).days, 0)
    if dias < MIN_DIAS_TWR_ANUALIZADO:
        return None, dias

    return (1 + float(twr.iloc[-1])) ** (365 / dias) - 1, dias


def tooltip_twr_anualizado(dias):
    base = "Tasa compuesta anual equivalente del TWR de la ventana seleccionada."
    if dias < MIN_DIAS_TWR_ANUALIZADO:
        return f"{base} Requiere al menos {MIN_DIAS_TWR_ANUALIZADO} dias; la ventana tiene {dias}."
    return f"{base} Calculada sobre {dias} dias."


def tooltip_sharpe(sesiones=None):
    if RF_FECHA:
        base = f"Tipo libre de riesgo considerado: {RF_ANUAL * 100:.2f}% anual ({RF_FECHA})."
    else:
        base = "No se pudo descargar el dato del BCE; se usa fallback del 2,00%."

    if sesiones is None:
        return base
    if sesiones < MIN_SESIONES_SHARPE:
        return f"{base} Requiere al menos {MIN_SESIONES_SHARPE} sesiones; la ventana tiene {sesiones}."
    return f"{base} Calculado con {sesiones} sesiones de mercado."


def filtrar_periodo(datos, periodo):
    if datos is None or datos.empty or periodo == "max":
        return datos.copy()
    fecha_inicio = datos.index.max() - PERIODOS[periodo]["offset"]
    filtrado = datos.loc[datos.index >= fecha_inicio].copy()
    return filtrado if not filtrado.empty else datos.tail(1).copy()


def rebasear_twr(s):
    return s * 0 if s.empty else (1 + s) / (1 + s.iloc[0]) - 1


def preparar_datos_divisa(periodo, divisa="eur", series=None):
    divisa = divisa.lower()
    series = series_cartera if series is None else series

    if series.empty:
        return pd.DataFrame(columns=["valor", "capital", "flujos", "twr"])

    sufijo = divisa.upper()
    datos = pd.DataFrame({
        "valor": series[f"Valor_cartera_{sufijo}"],
        "capital": series[f"Capital_{sufijo}"],
        "flujos": series[f"Flujos_{sufijo}"],
        "twr": series[f"TWR_{sufijo}"],
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
        return {
            "capital_total": 0,
            "referencia": 0,
            "valor_final": 0,
            "flujos_netos": 0,
            "resultado": 0,
            "rentabilidad_resultado": 0,
            "twr": 0,
            "twr_anualizado": None,
            "dias_twr": 0,
            "vol": None,
            "sharpe": None,
            "sesiones_riesgo": 0,
        }

    valor_final = valor.iloc[-1]
    capital_total = capital.iloc[-1]
    twr_anualizado, dias_twr = calcular_twr_anualizado(twr)

    if periodo == "max":
        referencia = capital.iloc[-1]
        flujos_netos = flujos.sum()
        resultado = valor_final - referencia
        base_resultado = referencia
    else:
        referencia = valor.iloc[0]
        flujos_netos = flujos.iloc[1:].sum() if len(flujos) > 1 else 0
        resultado = valor_final - referencia - flujos_netos
        base_resultado = calcular_capital_expuesto_periodo(valor, flujos)

    rentabilidad_resultado = resultado / base_resultado if abs(base_resultado) > 1e-12 else 0
    vol, sharpe, sesiones_riesgo = calcular_vol_sharpe(
        valor,
        flujos,
        ventana=None,
        rf_anual=RF_ANUAL,
        min_observaciones_volatilidad=MIN_SESIONES_VOLATILIDAD,
        min_observaciones_sharpe=MIN_SESIONES_SHARPE,
        devolver_observaciones=True,
    )
    return {
        "capital_total": capital_total,
        "referencia": referencia,
        "valor_final": valor_final,
        "flujos_netos": flujos_netos,
        "resultado": resultado,
        "rentabilidad_resultado": rentabilidad_resultado,
        "twr": twr.iloc[-1],
        "twr_anualizado": twr_anualizado,
        "dias_twr": dias_twr,
        "vol": vol,
        "sharpe": sharpe,
        "sesiones_riesgo": sesiones_riesgo,
    }


def calcular_capital_expuesto_periodo(valor, flujos):
    if valor.empty:
        return 0

    inicio = valor.index[0]
    fin = valor.index[-1]
    capital_expuesto = float(valor.iloc[0])
    duracion = (fin - inicio).total_seconds()

    if duracion <= 0:
        return capital_expuesto

    flujos_periodo = flujos.reindex(valor.index).fillna(0).iloc[1:]
    for fecha, flujo in flujos_periodo.items():
        if flujo == 0:
            continue
        peso = (fin - fecha).total_seconds() / duracion
        peso = min(max(peso, 0), 1)
        capital_expuesto += float(flujo) * peso

    return capital_expuesto


def formatear_importe(valor, simbolo, con_signo=False):
    if con_signo:
        signo = "+" if valor > 0 else "-" if valor < 0 else ""
        return f"{signo}{simbolo}{abs(valor):,.2f}"
    return f"{simbolo}{valor:,.2f}"


def titulo_primera_tarjeta(divisa, periodo):
    return f"Capital invertido {divisa}" if periodo == "max" else f"Valor inicial {divisa}"


def titulo_resultado(divisa, periodo):
    texto = f"Resultado {divisa}" if periodo == "max" else f"Resultado {divisa} - {PERIODOS[periodo]['label']}"
    return titulo_tarjeta(texto, TOOLTIP_RESULTADO)


def titulo_volatilidad(divisa, sesiones):
    return titulo_tarjeta(f"Volatilidad anualizada {divisa}", tooltip_volatilidad(sesiones))


def titulo_twr_anualizado(divisa, dias):
    return titulo_tarjeta(f"TWR anualizado {divisa}", tooltip_twr_anualizado(dias))


def titulo_sharpe(divisa, sesiones=None):
    return titulo_tarjeta(f"Sharpe {divisa}", tooltip_sharpe(sesiones))


def simbolo_divisa(divisa):
    return "€" if divisa.lower() == "eur" else "$"


def calcular_distribucion_actual():
    return calcular_distribucion_actual_multidivisa(operaciones, cash)
