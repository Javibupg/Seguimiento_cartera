import webbrowser
from dash import Dash, html, dcc, Input, Output
from threading import Timer

from cartera_utils import *
from auxfun import *


# =========================
# Cálculos
# =========================

operaciones = cargar_operaciones()
cash = cargar_movimientos_cash()

valor_cartera_usd = calcular_historico_cartera(operaciones, cash)
flujos, capital_acumulado = calcular_capital_acumulado(cash, valor_cartera_usd)
historico_desempeno = calcular_rentabilidad_twr(valor_cartera_usd, flujos)
operaciones_cerradas = calcular_operaciones_cerradas(operaciones)
desglose_fx = calcular_desglose_fx_eur(operaciones, cash)

valor_actual = valor_cartera_usd.iloc[-1] if not valor_cartera_usd.empty else 0
total_invertido = capital_acumulado.iloc[-1] if not capital_acumulado.empty else 0
beneficio_perdida = valor_actual - total_invertido
rentabilidad_usd = historico_desempeno.iloc[-1] if not historico_desempeno.empty else 0
vol_usd, sharpe_usd = calcular_vol_sharpe(valor_cartera_usd, flujos)

if desglose_fx.empty:
    total_invertido_eur = 0
    valor_actual_eur = 0
    beneficio_perdida_eur = 0
    rentabilidad_eur = 0
    vol_eur = 0
    sharpe_eur = 0
else:
    total_invertido_eur = desglose_fx["Capital_EUR"].iloc[-1]
    valor_actual_eur = desglose_fx["Valor_cartera_EUR"].iloc[-1]
    beneficio_perdida_eur = desglose_fx["Resultado_total_EUR"].iloc[-1]
    rentabilidad_eur = desglose_fx["Rentabilidad_TWR_EUR"].iloc[-1]
    flujos_eur = desglose_fx["Capital_EUR"].diff().fillna(desglose_fx["Capital_EUR"])
    vol_eur, sharpe_eur = calcular_vol_sharpe(desglose_fx["Valor_cartera_EUR"], flujos_eur)


# =========================
# App
# =========================

app = Dash(__name__)
app.title = "Dashboard de inversiones"

app.layout = html.Div(
    style={
        "fontFamily": "Arial, sans-serif",
        "backgroundColor": "#f3f4f6",
        "minHeight": "100vh",
        "padding": "40px"
    },
    children=[
        html.Div(
            style={"maxWidth": "1100px", "margin": "0 auto"},
            children=[
                html.H1(
                    "Dashboard de inversiones",
                    style={"color": "#111827", "marginBottom": "5px"}
                ),

                html.P(
                    "Seguimiento de cartera en USD y desglose EUR/FX",
                    style={"color": "#6b7280", "marginBottom": "30px"}
                ),
                
                html.Div(
                    style={
                        "backgroundColor": "white",
                        "padding": "20px 24px",
                        "borderRadius": "18px",
                        "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
                        "marginBottom": "30px"
                    },
                    children=[
                        html.Div(
                            "Vista",
                            style={
                                "fontSize": "14px",
                                "fontWeight": "700",
                                "color": "#374151",
                                "marginBottom": "8px"
                            }
                        ),
                        dcc.RadioItems(
                            id="selector-divisa",
                            options=[
                                {"label": "USD", "value": "usd"},
                                {"label": "EUR", "value": "eur"}
                            ],
                            value="usd",
                            inline=True,
                            labelStyle={
                                "display": "inline-block",
                                "padding": "10px 18px",
                                "marginRight": "10px",
                                "border": "1px solid #d1d5db",
                                "borderRadius": "10px",
                                "cursor": "pointer",
                                "backgroundColor": "#f9fafb",
                                "fontWeight": "600"
                            },
                            inputStyle={"marginRight": "8px"}
                        )
                    ]
                ),

                html.Div(
                    style={
                        "display": "grid",
                        "gridTemplateColumns": "repeat(3, 1fr)",
                        "gap": "20px",
                        "marginBottom": "30px"
                    },
                    children=[
                        crear_tarjeta(
                            "Total invertido USD",
                            f"${total_invertido:,.2f}",
                            id_titulo="tarjeta-total-titulo",
                            id_valor="tarjeta-total-valor"
                        ),
                        crear_tarjeta(
                            "Valor actual USD",
                            f"${valor_actual:,.2f}",
                            id_titulo="tarjeta-valor-titulo",
                            id_valor="tarjeta-valor-valor"
                        ),
                        crear_tarjeta(
                            "Resultado USD",
                            f"${beneficio_perdida:,.2f}",
                            id_titulo="tarjeta-resultado-titulo",
                            id_valor="tarjeta-resultado-valor"
                        ),
                        crear_tarjeta(
                            "Rentabilidad TWR USD",
                            f"{rentabilidad_usd * 100:.2f}%",
                            id_titulo="tarjeta-rentabilidad-titulo",
                            id_valor="tarjeta-rentabilidad-valor"
                        ),
                        crear_tarjeta(
                            "Volatilidad anualizada USD",
                            f"{vol_usd * 100:.2f}%",
                            id_titulo="tarjeta-vol-titulo",
                            id_valor="tarjeta-vol-valor"
                        ),
                        crear_tarjeta(
                            "Sharpe USD",
                            f"{sharpe_usd:.2f}",
                            id_titulo="tarjeta-sharpe-titulo",
                            id_valor="tarjeta-sharpe-valor"
                        ),
                    ]
                ),

                html.Div(
                    style={
                        "backgroundColor": "white",
                        "padding": "24px",
                        "borderRadius": "18px",
                        "boxShadow": "0 4px 14px rgba(0,0,0,0.08)"
                    },
                    children=[
                        html.Div(
                            "Tipo de gráfico",
                            style={
                                "fontSize": "14px",
                                "fontWeight": "700",
                                "color": "#374151",
                                "marginBottom": "8px"
                            }
                        ),

                        dcc.RadioItems(
                            id="selector-grafico",
                            options=[
                                {"label": "Rentabilidad", "value": "rentabilidad"},
                                {"label": "Drawdown", "value": "drawdown"}
                            ],
                            value="rentabilidad",
                            inline=True,
                            labelStyle={
                                "display": "inline-block",
                                "padding": "10px 18px",
                                "marginRight": "10px",
                                "border": "1px solid #d1d5db",
                                "borderRadius": "10px",
                                "cursor": "pointer",
                                "backgroundColor": "#f9fafb",
                                "fontWeight": "600"
                            },
                            inputStyle={
                                "marginRight": "8px"
                            },
                            style={
                                "marginBottom": "20px"
                            }
                        ),

                        dcc.Graph(
                            id="grafico-cartera",
                            config={"displayModeBar": True, "scrollZoom": True}
                        )
                    ]
                ),

                html.Div(
                    style={
                        "backgroundColor": "white",
                        "padding": "24px",
                        "borderRadius": "18px",
                        "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
                        "marginTop": "30px"
                    },
                    children=[
                        html.H3(
                            "Operaciones cerradas",
                            style={"color": "#111827", "marginBottom": "20px"}
                        ),
                        crear_tabla_operaciones_cerradas(operaciones_cerradas)
                    ]
                )
            ]
        )
    ]
)


@app.callback(
    Output("grafico-cartera", "figure"),
    Output("tarjeta-total-titulo", "children"),
    Output("tarjeta-total-valor", "children"),
    Output("tarjeta-valor-titulo", "children"),
    Output("tarjeta-valor-valor", "children"),
    Output("tarjeta-resultado-titulo", "children"),
    Output("tarjeta-resultado-valor", "children"),
    Output("tarjeta-rentabilidad-titulo", "children"),
    Output("tarjeta-rentabilidad-valor", "children"),
    Output("tarjeta-vol-titulo", "children"),
    Output("tarjeta-vol-valor", "children"),
    Output("tarjeta-sharpe-titulo", "children"),
    Output("tarjeta-sharpe-valor", "children"),
    Input("selector-divisa", "value"),
    Input("selector-grafico", "value"),
)


def actualizar_dashboard(divisa, tipo_grafico):

    if divisa == "eur":
        if tipo_grafico == "drawdown":
            fig = crear_grafico_drawdown_eur(desglose_fx)
        else:
            fig = crear_grafico_desglose_eur(desglose_fx)

        return (
            fig,
            "Total invertido EUR",
            f"€{total_invertido_eur:,.2f}",
            "Valor actual EUR",
            f"€{valor_actual_eur:,.2f}",
            "Resultado EUR",
            f"€{beneficio_perdida_eur:,.2f}",
            "Rentabilidad TWR EUR",
            f"{rentabilidad_eur * 100:.2f}%",
            "Volatilidad anualizada EUR",
            f"{vol_eur * 100:.2f}%",
            "Sharpe EUR",
            f"{sharpe_eur:.2f}",
        )

    if tipo_grafico == "drawdown":
        fig = crear_grafico_drawdown(historico_desempeno, flujos, capital_acumulado)
    else:
        fig = crear_grafico_cartera(historico_desempeno, flujos, capital_acumulado)

    return (
        fig,
        "Total invertido USD",
        f"${total_invertido:,.2f}",
        "Valor actual USD",
        f"${valor_actual:,.2f}",
        "Resultado USD",
        f"${beneficio_perdida:,.2f}",
        "Rentabilidad TWR USD",
        f"{rentabilidad_usd * 100:.2f}%",
        "Volatilidad anualizada USD",
        f"{vol_usd * 100:.2f}%",
        "Sharpe USD",
        f"{sharpe_usd:.2f}",
    )


if __name__ == "__main__":
    port = 8050
    url = f"http://127.0.0.1:{port}"

    Timer(1, lambda: webbrowser.open_new(url)).start()
    app.run(debug=True, port=port, use_reloader=False)