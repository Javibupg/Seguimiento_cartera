import webbrowser
from threading import Timer

import pandas as pd
from dash import Dash, html, dcc, Input, Output

from cartera_utils import *
from auxfun import *


# =========================
# Cálculos base
# =========================

operaciones = cargar_operaciones()
cash = cargar_movimientos_cash()

historico_desempeno = calcular_desempeno_cartera(operaciones, cash)
operaciones_cerradas = calcular_operaciones_cerradas(operaciones)
desglose_fx = calcular_desglose_fx_eur(operaciones, cash)

flujos, capital_acumulado = calcular_capital_acumulado(cash, historico_desempeno)
valor_cartera_usd = capital_acumulado * (1 + historico_desempeno)
flujos_eur = pd.Series(dtype="float64") if desglose_fx.empty else desglose_fx["Capital_EUR"].diff().fillna(desglose_fx["Capital_EUR"])


# =========================
# Periodos y métricas
# =========================

PERIODOS = {
    "1w": {"label": "1S", "nombre": "1 semana", "offset": pd.DateOffset(weeks=1)},
    "1m": {"label": "1M", "nombre": "1 mes", "offset": pd.DateOffset(months=1)},
    "6m": {"label": "6M", "nombre": "6 meses", "offset": pd.DateOffset(months=6)},
    "1y": {"label": "1A", "nombre": "1 año", "offset": pd.DateOffset(years=1)},
    "5y": {"label": "5A", "nombre": "5 años", "offset": pd.DateOffset(years=5)},
    "max": {"label": "Máx", "nombre": "máximo", "offset": None},
}

ESTILO_BOTON = {
    "display": "inline-block", "padding": "10px 18px", "marginRight": "10px",
    "border": "1px solid #d1d5db", "borderRadius": "10px", "cursor": "pointer",
    "backgroundColor": "#f9fafb", "fontWeight": "600"
}


def filtrar_periodo(datos, periodo):
    if datos is None or datos.empty or periodo == "max":
        return datos

    fecha_inicio = datos.index.max() - PERIODOS[periodo]["offset"]
    filtrado = datos.loc[datos.index >= fecha_inicio]

    return filtrado if not filtrado.empty else datos.tail(1)


def preparar_datos_usd(periodo):
    datos = pd.DataFrame({
        "valor": valor_cartera_usd,
        "capital": capital_acumulado,
        "flujos": flujos,
        "rentabilidad": historico_desempeno
    }).dropna()

    datos = filtrar_periodo(datos, periodo)
    if datos.empty:
        datos["rentabilidad_grafico"] = 0
        return datos

    if periodo == "max":
        datos["rentabilidad_grafico"] = datos["rentabilidad"]
    else:
        resultado_periodo = (datos["valor"] - datos["capital"]) - (datos["valor"].iloc[0] - datos["capital"].iloc[0])
        base = datos["valor"].iloc[0]
        datos["rentabilidad_grafico"] = resultado_periodo / base if base != 0 else 0

    datos["rentabilidad_grafico"] = datos["rentabilidad_grafico"].replace([float("inf"), -float("inf")], 0).fillna(0)
    return datos


def preparar_datos_eur(periodo):
    if desglose_fx.empty:
        return desglose_fx.copy()

    datos = desglose_fx.copy()
    datos["flujos"] = flujos_eur.reindex(datos.index).fillna(0)
    datos = filtrar_periodo(datos, periodo)

    if periodo != "max" and not datos.empty:
        base = datos["Valor_cartera_EUR"].iloc[0]
        divisor = base if base != 0 else 1

        for columna_resultado, columna_rentabilidad in [
            ("Resultado_total_EUR", "Rentabilidad_total_EUR"),
            ("Efecto_activos_EUR", "Rentabilidad_activos_EUR"),
            ("Efecto_FX_EUR", "Rentabilidad_FX_EUR"),
        ]:
            datos[columna_rentabilidad] = (datos[columna_resultado] - datos[columna_resultado].iloc[0]) / divisor

        columnas = ["Rentabilidad_total_EUR", "Rentabilidad_activos_EUR", "Rentabilidad_FX_EUR"]
        datos[columnas] = datos[columnas].replace([float("inf"), -float("inf")], 0).fillna(0)

    return datos


def calcular_metricas_periodo(valor, capital, flujos, periodo):
    if valor.empty:
        return 0, 0, 0, 0, 0, 0

    valor_inicio = valor.iloc[0]
    valor_final = valor.iloc[-1]
    capital_final = capital.iloc[-1]

    if periodo == "max":
        resultado = valor_final - capital_final
        rentabilidad = resultado / capital_final if capital_final != 0 else 0
        primera_tarjeta = capital_final
    else:
        resultado = (valor_final - capital_final) - (valor_inicio - capital.iloc[0])
        rentabilidad = resultado / valor_inicio if valor_inicio != 0 else 0
        primera_tarjeta = valor_inicio

    vol, sharpe = calcular_vol_sharpe(valor, flujos, ventana=None)
    return primera_tarjeta, valor_final, resultado, rentabilidad, vol, sharpe


def formatear_importe(valor, simbolo):
    return f"{simbolo}{valor:,.2f}"


def titulo_primera_tarjeta(divisa, periodo):
    return f"Capital invertido {divisa}" if periodo == "max" else f"Valor inicial {divisa}"


# =========================
# App
# =========================

app = Dash(__name__)
app.title = "Dashboard de inversiones"

app.layout = html.Div(
    style={"fontFamily": "Arial, sans-serif", "backgroundColor": "#f3f4f6", "minHeight": "100vh", "padding": "40px"},
    children=[
        html.Div(
            style={"maxWidth": "1100px", "margin": "0 auto"},
            children=[
                html.H1("Dashboard de inversiones", style={"color": "#111827", "marginBottom": "5px"}),
                html.P("Seguimiento de cartera en USD y desglose EUR/FX", style={"color": "#6b7280", "marginBottom": "30px"}),

                html.Div(
                    style={"backgroundColor": "white", "padding": "20px 24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginBottom": "30px"},
                    children=[
                        html.Div("Vista", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
                        dcc.RadioItems(
                            id="selector-divisa",
                            options=[{"label": "USD", "value": "usd"}, {"label": "EUR", "value": "eur"}],
                            value="usd", inline=True, labelStyle=ESTILO_BOTON, inputStyle={"marginRight": "8px"}
                        ),
                    ],
                ),

                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)", "gap": "20px", "marginBottom": "30px"},
                    children=[
                        crear_tarjeta("Capital invertido USD", "$0.00", id_titulo="tarjeta-total-titulo", id_valor="tarjeta-total-valor"),
                        crear_tarjeta("Valor actual USD", "$0.00", id_titulo="tarjeta-valor-titulo", id_valor="tarjeta-valor-valor"),
                        crear_tarjeta("Resultado USD", "$0.00", id_titulo="tarjeta-resultado-titulo", id_valor="tarjeta-resultado-valor"),
                        crear_tarjeta("Volatilidad anualizada USD", "0.00%", id_titulo="tarjeta-vol-titulo", id_valor="tarjeta-vol-valor"),
                        crear_tarjeta("Sharpe USD", "0.00", id_titulo="tarjeta-sharpe-titulo", id_valor="tarjeta-sharpe-valor"),
                    ],
                ),

                html.Div(
                    style={"backgroundColor": "white", "padding": "24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)"},
                    children=[
                        html.Div("Tipo de gráfico", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
                        dcc.RadioItems(
                            id="selector-grafico",
                            options=[{"label": "Rentabilidad", "value": "rentabilidad"}, {"label": "Drawdown", "value": "drawdown"}],
                            value="rentabilidad", inline=True, labelStyle=ESTILO_BOTON, inputStyle={"marginRight": "8px"}, style={"marginBottom": "20px"}
                        ),

                        html.Div("Periodo", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
                        dcc.RadioItems(
                            id="selector-periodo",
                            options=[{"label": v["label"], "value": k} for k, v in PERIODOS.items()],
                            value="max", inline=True, labelStyle=ESTILO_BOTON, inputStyle={"marginRight": "8px"}, style={"marginBottom": "20px"}
                        ),

                        dcc.Graph(id="grafico-cartera", config={"displayModeBar": True, "scrollZoom": True}),
                    ],
                ),

                html.Div(
                    style={"backgroundColor": "white", "padding": "24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginTop": "30px"},
                    children=[
                        html.H3("Operaciones cerradas", style={"color": "#111827", "marginBottom": "20px"}),
                        crear_tabla_operaciones_cerradas(operaciones_cerradas),
                    ],
                ),
            ],
        )
    ],
)


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
            return fig, "Capital invertido EUR", "€0.00", "Valor actual EUR", "€0.00", "Resultado EUR", "€0.00", "Volatilidad anualizada EUR", "0.00%", "Sharpe EUR", "0.00"

        fig = crear_grafico_drawdown_eur(datos) if tipo_grafico == "drawdown" else crear_grafico_desglose_eur(datos)
        fig.update_layout(title={"text": f"{fig.layout.title.text} · {nombre_periodo}", "x": 0.05, "xanchor": "left", "y": 0.99, "yanchor": "top"})

        primera, valor_final, resultado, rentabilidad, vol, sharpe = calcular_metricas_periodo(datos["Valor_cartera_EUR"], datos["Capital_EUR"], datos["flujos"], periodo)
        return (
            fig,
            titulo_primera_tarjeta("EUR", periodo), formatear_importe(primera, "€"),
            "Valor actual EUR", formatear_importe(valor_final, "€"),
            "Resultado EUR" if periodo == "max" else f"Resultado EUR · {PERIODOS[periodo]['label']}", formatear_resultado_con_rentabilidad(resultado, rentabilidad, "€"),
            "Volatilidad anualizada EUR", f"{vol * 100:.2f}%",
            "Sharpe EUR", f"{sharpe:.2f}",
        )

    datos = preparar_datos_usd(periodo)
    fig = crear_grafico_drawdown(datos["rentabilidad_grafico"], datos["flujos"], datos["capital"]) if tipo_grafico == "drawdown" else crear_grafico_cartera(datos["rentabilidad_grafico"], datos["flujos"], datos["capital"])
    fig.update_layout(title={"text": f"{fig.layout.title.text} · {nombre_periodo}", "x": 0.05, "xanchor": "left", "y": 0.99, "yanchor": "top"})

    primera, valor_final, resultado, rentabilidad, vol, sharpe = calcular_metricas_periodo(datos["valor"], datos["capital"], datos["flujos"], periodo)
    return (
        fig,
        titulo_primera_tarjeta("USD", periodo), formatear_importe(primera, "$"),
        "Valor actual USD", formatear_importe(valor_final, "$"),
        "Resultado USD" if periodo == "max" else f"Resultado USD · {PERIODOS[periodo]['label']}", formatear_resultado_con_rentabilidad(resultado, rentabilidad, "$"),
        "Volatilidad anualizada USD", f"{vol * 100:.2f}%",
        "Sharpe USD", f"{sharpe:.2f}",
    )


if __name__ == "__main__":
    port = 8050
    url = f"http://127.0.0.1:{port}"

    Timer(1, lambda: webbrowser.open_new(url)).start()
    app.run(debug=True, port=port, use_reloader=False)
