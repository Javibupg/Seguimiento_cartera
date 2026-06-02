import dash
from dash import html, dcc, Input, Output, callback

from auxfun import crear_tarjeta, crear_tabla_operaciones_cerradas, crear_grafico_twr, crear_grafico_drawdown, formatear_resultado_con_rentabilidad
from datos import PERIODOS, ESTILO_BOTON, TOOLTIP_TWR, tooltip_sharpe, preparar_datos_divisa, calcular_metricas_periodo, formatear_importe, titulo_primera_tarjeta, titulo_resultado, simbolo_divisa, operaciones_cerradas


dash.register_page(
    __name__,
    path="/",
    name="Resumen",
    title="Resumen de cartera",
    order=1,
)

layout = html.Div(children=[
    html.H2("Resumen de cartera", style={"color": "#111827", "marginBottom": "5px"}),
    html.P("Vista principal de rentabilidad TWR, capital invertido, drawdown y operaciones cerradas.", style={"color": "#6b7280", "marginBottom": "30px"}),
    html.Div(style={"backgroundColor": "white", "padding": "20px 24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginBottom": "30px"}, children=[
        html.Div("Vista", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
        dcc.RadioItems(id="selector-divisa", options=[{"label": "EUR", "value": "eur"}, {"label": "USD", "value": "usd"}], value="eur", inline=True, labelStyle=ESTILO_BOTON, inputStyle={"marginRight": "8px"})
    ]),
    html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)", "gap": "20px", "marginBottom": "30px"}, children=[
        crear_tarjeta("Capital invertido EUR", "€0.00", id_titulo="tarjeta-total-titulo", id_valor="tarjeta-total-valor"),
        crear_tarjeta("Valor actual EUR", "€0.00", id_titulo="tarjeta-valor-titulo", id_valor="tarjeta-valor-valor"),
        crear_tarjeta("Resultado EUR", "€0.00", id_titulo="tarjeta-resultado-titulo", id_valor="tarjeta-resultado-valor", tooltip=TOOLTIP_TWR),
        crear_tarjeta("Volatilidad anualizada EUR", "0.00%", id_titulo="tarjeta-vol-titulo", id_valor="tarjeta-vol-valor"),
        crear_tarjeta("Sharpe EUR", "0.00", id_titulo="tarjeta-sharpe-titulo", id_valor="tarjeta-sharpe-valor", tooltip=tooltip_sharpe()),
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


@callback(
    Output("grafico-cartera", "figure"),
    Output("tarjeta-total-titulo", "children"), Output("tarjeta-total-valor", "children"),
    Output("tarjeta-valor-titulo", "children"), Output("tarjeta-valor-valor", "children"),
    Output("tarjeta-resultado-titulo", "children"), Output("tarjeta-resultado-valor", "children"),
    Output("tarjeta-vol-titulo", "children"), Output("tarjeta-vol-valor", "children"),
    Output("tarjeta-sharpe-titulo", "children"), Output("tarjeta-sharpe-valor", "children"),
    Input("selector-divisa", "value"), Input("selector-grafico", "value"), Input("selector-periodo", "value"),
)
def actualizar_dashboard(divisa, tipo_grafico, periodo):
    datos = preparar_datos_divisa(periodo, divisa)
    divisa_txt = divisa.upper()
    simbolo = simbolo_divisa(divisa)
    nombre_periodo = PERIODOS[periodo]["nombre"]

    titulo_base = f"{'Drawdown' if tipo_grafico == 'drawdown' else 'Rentabilidad'} TWR {divisa_txt} y capital invertido"
    fig = (
        crear_grafico_drawdown(datos["twr"], datos["capital"], simbolo, titulo_base, f"Drawdown {divisa_txt}", f"Capital invertido {divisa_txt}")
        if tipo_grafico == "drawdown"
        else crear_grafico_twr(datos["twr"], datos["capital"], simbolo, titulo_base, f"Rentabilidad TWR {divisa_txt}", f"Capital invertido {divisa_txt}")
    )
    fig.update_layout(title={"text": f"{fig.layout.title.text} · {nombre_periodo}", "x": 0.05, "xanchor": "left", "y": 0.99, "yanchor": "top"})

    primera, valor_final, resultado, twr, vol, sharpe = calcular_metricas_periodo(datos["valor"], datos["capital"], datos["flujos"], datos["twr"], periodo)

    return (
        fig,
        titulo_primera_tarjeta(divisa_txt, periodo), formatear_importe(primera, simbolo),
        f"Valor actual {divisa_txt}", formatear_importe(valor_final, simbolo),
        titulo_resultado(divisa_txt, periodo), formatear_resultado_con_rentabilidad(resultado, twr, simbolo),
        f"Volatilidad anualizada {divisa_txt}", f"{vol * 100:.2f}%",
        f"Sharpe {divisa_txt}", f"{sharpe:.2f}",
    )
