import webbrowser
from threading import Timer
import pandas as pd
from dash import Dash, html, dcc, Input, Output

from cartera_utils import *
from auxfun import *

RF_ANUAL, RF_FECHA = obtener_rf_anual_eur()
TOOLTIP_TWR = "Rentabilidad TWR no anualizada. Ajusta las aportaciones y retiradas para que meter dinero nuevo no baje ni suba artificialmente la rentabilidad."

def tooltip_sharpe():
    fecha = f" Última observación BCE: {RF_FECHA}." if RF_FECHA else " Si no hay conexión, se usa fallback 2,00%."
    return f"Sharpe anualizado calculado con rentabilidades diarias ajustadas por flujos y tipo libre de riesgo EUR BCE: {RF_ANUAL * 100:.2f}%." + fecha


def titulo_sharpe(divisa):
    return titulo_tarjeta(f"Sharpe {divisa}", tooltip_sharpe())

PERIODOS = {
    "1w": {"label": "1S", "nombre": "1 semana", "offset": pd.DateOffset(weeks=1)},
    "1m": {"label": "1M", "nombre": "1 mes", "offset": pd.DateOffset(months=1)},
    "6m": {"label": "6M", "nombre": "6 meses", "offset": pd.DateOffset(months=6)},
    "1y": {"label": "1A", "nombre": "1 año", "offset": pd.DateOffset(years=1)},
    "5y": {"label": "5A", "nombre": "5 años", "offset": pd.DateOffset(years=5)},
    "max": {"label": "Máx", "nombre": "máximo", "offset": None},
}

ESTILO_BOTON = {"display": "inline-block", "padding": "10px 18px", "marginRight": "10px", "border": "1px solid #d1d5db", "borderRadius": "10px", "cursor": "pointer", "backgroundColor": "#f9fafb", "fontWeight": "600"}

# =========================
# Cálculos base
# =========================
operaciones = cargar_operaciones()
cash = cargar_movimientos_cash()
cartera_usd = calcular_historico_cartera(operaciones, cash)
flujos_usd, capital_usd = calcular_capital_acumulado(cash, cartera_usd, "Importe_firmado")
twr_usd = calcular_twr(cartera_usd, flujos_usd)
desglose_fx = calcular_desglose_fx_eur(operaciones, cash)
operaciones_cerradas = calcular_operaciones_cerradas(operaciones)


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


# =========================
# App
# =========================
app = Dash(__name__)
app.title = "Dashboard de inversiones"
app.layout = html.Div(style={"fontFamily": "Arial, sans-serif", "backgroundColor": "#f3f4f6", "minHeight": "100vh", "padding": "40px"}, children=[
    html.Div(style={"maxWidth": "1100px", "margin": "0 auto"}, children=[
        html.H1("Dashboard de inversiones", style={"color": "#111827", "marginBottom": "5px"}),
        html.P("Seguimiento de cartera con rentabilidad TWR ajustada por aportaciones y retiradas", style={"color": "#6b7280", "marginBottom": "30px"}),
        html.Div(style={"backgroundColor": "white", "padding": "20px 24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginBottom": "30px"}, children=[
            html.Div("Vista", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
            dcc.RadioItems(id="selector-divisa", options=[{"label": "USD", "value": "usd"}, {"label": "EUR", "value": "eur"}], value="usd", inline=True, labelStyle=ESTILO_BOTON, inputStyle={"marginRight": "8px"})
        ]),
        html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)", "gap": "20px", "marginBottom": "30px"}, children=[
            crear_tarjeta("Capital invertido USD", "$0.00", id_titulo="tarjeta-total-titulo", id_valor="tarjeta-total-valor"),
            crear_tarjeta("Valor actual USD", "$0.00", id_titulo="tarjeta-valor-titulo", id_valor="tarjeta-valor-valor"),
            crear_tarjeta("Resultado USD", "$0.00", id_titulo="tarjeta-resultado-titulo", id_valor="tarjeta-resultado-valor", tooltip=TOOLTIP_TWR),
            crear_tarjeta("Volatilidad anualizada USD", "0.00%", id_titulo="tarjeta-vol-titulo", id_valor="tarjeta-vol-valor"),
            crear_tarjeta("Sharpe USD", "0.00", id_titulo="tarjeta-sharpe-titulo", id_valor="tarjeta-sharpe-valor", tooltip=tooltip_sharpe()),
        ]),
        html.Div(style={"backgroundColor": "white", "padding": "24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)"}, children=[
            html.Div("Tipo de gráfico", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
            dcc.RadioItems(id="selector-grafico", options=[{"label": "Rentabilidad", "value": "rentabilidad"}, {"label": "Drawdown", "value": "drawdown"}], value="rentabilidad", inline=True, labelStyle=ESTILO_BOTON, inputStyle={"marginRight": "8px"}, style={"marginBottom": "20px"}),
            html.Div("Periodo", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
            dcc.RadioItems(id="selector-periodo", options=[{"label": v["label"], "value": k} for k, v in PERIODOS.items()], value="max", inline=True, labelStyle=ESTILO_BOTON, inputStyle={"marginRight": "8px"}, style={"marginBottom": "20px"}),
            dcc.Graph(id="grafico-cartera", config={"displayModeBar": True, "scrollZoom": True})
        ]),
        html.Div(style={"backgroundColor": "white", "padding": "24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginTop": "30px"}, children=[
            html.H3("Operaciones cerradas", style={"color": "#111827", "marginBottom": "20px"}),
            crear_tabla_operaciones_cerradas(operaciones_cerradas)
        ])
    ])
])


@app.callback(
    Output("grafico-cartera", "figure"),
    Output("tarjeta-total-titulo", "children"), Output("tarjeta-total-valor", "children"),
    Output("tarjeta-valor-titulo", "children"), Output("tarjeta-valor-valor", "children"),
    Output("tarjeta-resultado-titulo", "children"), Output("tarjeta-resultado-valor", "children"),
    Output("tarjeta-vol-titulo", "children"), Output("tarjeta-vol-valor", "children"),
    Output("tarjeta-sharpe-titulo", "children"), Output("tarjeta-sharpe-valor", "children"),
    Input("selector-divisa", "value"), Input("selector-grafico", "value"), Input("selector-periodo", "value"),
)
def actualizar_dashboard(divisa, tipo_grafico, periodo):
    nombre_periodo = PERIODOS[periodo]["nombre"]

    if divisa == "eur":
        datos = preparar_datos_eur(periodo)
        if datos.empty:
            fig = crear_grafico_desglose_eur(datos)
            return fig, "Capital invertido EUR", "€0.00", "Valor actual EUR", "€0.00", titulo_resultado("EUR", periodo), "€0.00", "Volatilidad anualizada EUR", "0.00%", "Sharpe EUR", "0.00"

        fig = crear_grafico_drawdown_eur(datos) if tipo_grafico == "drawdown" else crear_grafico_desglose_eur(datos)
        fig.update_layout(title={"text": f"{fig.layout.title.text} · {nombre_periodo}", "x": 0.05, "xanchor": "left", "y": 0.99, "yanchor": "top"})
        primera, valor_final, resultado, twr, vol, sharpe = calcular_metricas_periodo(datos["Valor_cartera_EUR"], datos["Capital_EUR"], datos["Flujos_EUR"], datos["TWR_total_EUR"], periodo)
        return fig, titulo_primera_tarjeta("EUR", periodo), formatear_importe(primera, "€"), "Valor actual EUR", formatear_importe(valor_final, "€"), titulo_resultado("EUR", periodo), formatear_resultado_con_rentabilidad(resultado, twr, "€"), "Volatilidad anualizada EUR", f"{vol * 100:.2f}%", "Sharpe EUR", f"{sharpe:.2f}"

    datos = preparar_datos_usd(periodo)
    fig = crear_grafico_drawdown(datos["twr"], datos["capital"], "$", "Drawdown TWR USD y capital invertido", "Drawdown USD", "Capital invertido USD") if tipo_grafico == "drawdown" else crear_grafico_twr(datos["twr"], datos["capital"], "$", "Rentabilidad TWR USD y capital invertido", "Rentabilidad TWR USD", "Capital invertido USD")
    fig.update_layout(title={"text": f"{fig.layout.title.text} · {nombre_periodo}", "x": 0.05, "xanchor": "left", "y": 0.99, "yanchor": "top"})
    primera, valor_final, resultado, twr, vol, sharpe = calcular_metricas_periodo(datos["valor"], datos["capital"], datos["flujos"], datos["twr"], periodo)
    return fig, titulo_primera_tarjeta("USD", periodo), formatear_importe(primera, "$"), "Valor actual USD", formatear_importe(valor_final, "$"), titulo_resultado("USD", periodo), formatear_resultado_con_rentabilidad(resultado, twr, "$"), "Volatilidad anualizada USD", f"{vol * 100:.2f}%", "Sharpe USD", f"{sharpe:.2f}"


if __name__ == "__main__":
    port = 8050
    Timer(1, lambda: webbrowser.open_new(f"http://127.0.0.1:{port}")).start()
    app.run(debug=True, port=port, use_reloader=False)
