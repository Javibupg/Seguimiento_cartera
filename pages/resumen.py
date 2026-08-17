import dash
from dash import html, dcc, Input, Output, callback

from auxfun import (
    crear_grafico_drawdown,
    crear_grafico_twr,
    crear_mapa_calor_activos,
    crear_tabla_inversiones_por_banco,
    crear_tabla_operaciones_abiertas,
    crear_tabla_operaciones_cerradas,
    crear_tabla_proximos_dividendos,
    crear_tarjeta,
    titulo_tarjeta,
)
from cartera_utils import (
    calcular_inversiones_por_banco,
    calcular_operaciones_abiertas,
    calcular_operaciones_cerradas,
    calcular_posiciones_actuales,
    calcular_rentabilidad_anualizada_por_activo,
    calcular_series_cartera_multidivisa,
)
from datos import (
    PERIODOS,
    calcular_metricas_periodo,
    cash,
    formatear_importe,
    operaciones,
    preparar_datos_divisa,
    proximos_dividendos,
    simbolo_divisa,
    titulo_sharpe,
    titulo_twr_anualizado,
    titulo_volatilidad,
    tooltip_sharpe,
    tooltip_twr_anualizado,
)


ESTILO_BOTON_RESUMEN = {
    "display": "inline-block",
    "padding": "4px 8px",
    "marginRight": "6px",
    "border": "1px solid #d9d9d9",
    "borderRadius": "2px",
    "backgroundColor": "#f3f4f6",
    "color": "#1f2937",
    "fontSize": "12px",
    "fontWeight": "500",
    "lineHeight": "1.2",
    "cursor": "pointer",
}

ESTILO_INPUT_OCULTO = {
    "display": "none",
}

BANCO_TODA_LA_CARTERA = "__toda_la_cartera__"
TOOLTIP_CAPITAL_TOTAL = "Aportaciones acumuladas menos retiradas. No se altera al cambiar la ventana temporal."


def _opciones_banco():
    bancos = set(operaciones["Banco"].dropna())
    bancos.update(cash["Banco"].dropna())
    return [
        {"label": "Toda la cartera", "value": BANCO_TODA_LA_CARTERA},
        *[{"label": banco, "value": banco} for banco in sorted(bancos)],
    ]


def _datos_banco(banco):
    if banco == BANCO_TODA_LA_CARTERA:
        return operaciones, cash

    return (
        operaciones[operaciones["Banco"].eq(banco)].copy(),
        cash[cash["Banco"].eq(banco)].copy(),
    )


def _preparar_datos_resumen(periodo, divisa, banco):
    if banco == BANCO_TODA_LA_CARTERA:
        series = calcular_series_cartera_multidivisa(operaciones, cash)
        return preparar_datos_divisa(periodo, divisa, series=series)

    operaciones_banco, cash_banco = _datos_banco(banco)
    series_banco = calcular_series_cartera_multidivisa(operaciones_banco, cash_banco)
    return preparar_datos_divisa(periodo, divisa, series=series_banco)


def _titulo_capital_total(divisa):
    return titulo_tarjeta(f"Capital total invertido {divisa}", TOOLTIP_CAPITAL_TOTAL)


def _formatear_twr(valor):
    signo = "+" if valor > 0 else ""
    return f"{signo}{valor * 100:.2f}%"


def _fecha_inicio_desde_periodo(datos, periodo):
    if periodo == "max" or datos.empty:
        return None
    return datos.index.min()


def _filtrar_operaciones_cerradas(df, fecha_inicio):
    if fecha_inicio is None or df.empty or "Fecha_fin" not in df.columns:
        return df
    return df[df["Fecha_fin"] >= fecha_inicio].copy()


def _crear_tabla_operaciones_abiertas_periodo(fecha_inicio, operaciones_banco, cash_banco):
    if fecha_inicio is None:
        return crear_tabla_operaciones_abiertas(
            calcular_operaciones_abiertas(operaciones_banco, cash_banco),
            mostrar_rentabilidad=False,
        )

    return crear_tabla_operaciones_abiertas(
        calcular_operaciones_abiertas(operaciones_banco, cash_banco, fecha_inicio),
        etiqueta_capital="Capital al inicio + compras EUR",
        mostrar_rentabilidad=False,
    )


def _crear_tabla_inversiones_banco_periodo(fecha_inicio, divisa):
    divisa_txt = divisa.upper()
    if fecha_inicio is None:
        texto = f"Aportaciones netas, valor actual y TWR acumulado en {divisa_txt} por banco."
        tabla = crear_tabla_inversiones_por_banco(
            calcular_inversiones_por_banco(operaciones, cash, divisa_twr=divisa_txt),
            etiqueta_twr=f"TWR acumulado {divisa_txt}",
        )
        return texto, tabla

    texto = f"Aportaciones netas, valor actual y TWR de la ventana seleccionada en {divisa_txt} por banco."
    tabla = crear_tabla_inversiones_por_banco(
        calcular_inversiones_por_banco(operaciones, cash, fecha_inicio, divisa_txt),
        etiqueta_twr=f"TWR periodo {divisa_txt}",
    )
    return texto, tabla


def _filtrar_dividendos_por_banco(operaciones_banco):
    if proximos_dividendos.empty or "Activo" not in proximos_dividendos:
        return proximos_dividendos

    activos = calcular_posiciones_actuales(operaciones_banco).index
    return proximos_dividendos[proximos_dividendos["Activo"].isin(activos)].copy()


dash.register_page(
    __name__,
    path="/",
    name="Resumen",
    title="Resumen de cartera",
    order=1,
)

layout = html.Div(children=[
    html.H2("Resumen de cartera", style={"color": "#111827", "marginBottom": "5px"}),
    html.P("Rentabilidad, valoración y riesgo de la cartera.", style={"color": "#6b7280", "marginBottom": "30px"}),
    html.Div(style={"backgroundColor": "white", "padding": "20px 24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginBottom": "30px"}, children=[
        html.Div("Vista", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
        dcc.RadioItems(id="selector-divisa", options=[{"label": "EUR", "value": "eur"}, {"label": "USD", "value": "usd"}], value="eur", inline=True, labelStyle=ESTILO_BOTON_RESUMEN, inputStyle=ESTILO_INPUT_OCULTO),
        html.Div("Banco", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginTop": "18px", "marginBottom": "8px"}),
        dcc.Dropdown(
            id="selector-banco",
            options=_opciones_banco(),
            value=BANCO_TODA_LA_CARTERA,
            clearable=False,
            searchable=False,
            style={"maxWidth": "360px"},
        ),
    ]),
    html.Div(style={"display": "grid", "gridTemplateColumns": "repeat(auto-fit, minmax(190px, 1fr))", "gap": "16px", "marginBottom": "30px"}, children=[
        crear_tarjeta("Capital total invertido EUR", "€0.00", id_titulo="tarjeta-total-titulo", id_valor="tarjeta-total-valor", tooltip=TOOLTIP_CAPITAL_TOTAL),
        crear_tarjeta("Valor actual EUR", "€0.00", id_titulo="tarjeta-valor-titulo", id_valor="tarjeta-valor-valor"),
        crear_tarjeta("TWR anualizado EUR", "N/D", id_titulo="tarjeta-twr-titulo", id_valor="tarjeta-twr-valor", tooltip=tooltip_twr_anualizado(0)),
        crear_tarjeta("Volatilidad anualizada EUR", "0.00%", id_titulo="tarjeta-vol-titulo", id_valor="tarjeta-vol-valor"),
        crear_tarjeta("Sharpe EUR", "0.00", id_titulo="tarjeta-sharpe-titulo", id_valor="tarjeta-sharpe-valor", tooltip=tooltip_sharpe()),
    ]),
    html.Div(style={"backgroundColor": "white", "padding": "24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)"}, children=[
        html.Div("Tipo de gráfico", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
        dcc.RadioItems(id="selector-grafico", options=[{"label": "Rentabilidad", "value": "rentabilidad"}, {"label": "Drawdown", "value": "drawdown"}], value="rentabilidad", inline=True, labelStyle=ESTILO_BOTON_RESUMEN, inputStyle=ESTILO_INPUT_OCULTO, style={"marginBottom": "20px"}),
        html.Div("Periodo", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
        dcc.RadioItems(id="selector-periodo", options=[{"label": v["label"], "value": k} for k, v in PERIODOS.items()], value="max", inline=True, labelStyle=ESTILO_BOTON_RESUMEN, inputStyle=ESTILO_INPUT_OCULTO, style={"marginBottom": "20px"}),
        dcc.Graph(id="grafico-cartera", config={"displayModeBar": True, "scrollZoom": True})
    ]),
    html.Div(style={"backgroundColor": "white", "padding": "24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginTop": "30px"}, children=[
        html.H3("Mapa de rentabilidad anualizada por activo", style={"color": "#111827", "marginBottom": "12px"}),
        dcc.Graph(id="mapa-calor-activos", config={"displayModeBar": False, "responsive": True}),
    ]),
    html.Div(style={"backgroundColor": "white", "padding": "24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginTop": "30px"}, children=[
        html.H3("Operaciones abiertas", style={"color": "#111827", "marginBottom": "20px"}),
        html.Div(id="tabla-operaciones-abiertas")
    ]),
    html.Div(style={"backgroundColor": "white", "padding": "24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginTop": "30px"}, children=[
        html.H3("Operaciones cerradas", style={"color": "#111827", "marginBottom": "20px"}),
        html.Div(id="tabla-operaciones-cerradas")
    ]),
    html.Div(style={"backgroundColor": "white", "padding": "24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginTop": "30px"}, children=[
        html.H3("Próximos dividendos", style={"color": "#111827", "marginBottom": "8px"}),
        html.P(
            "Dividendos anunciados o estimados para las posiciones abiertas con dividendo disponible. El dividend yield se muestra anualizado; si Yahoo no publica fecha futura, se indica como sin fecha anunciada.",
            style={"color": "#6b7280", "marginBottom": "20px"},
        ),
        html.Div(id="tabla-proximos-dividendos")
    ]),
    html.Div(style={"backgroundColor": "white", "padding": "24px", "borderRadius": "18px", "boxShadow": "0 4px 14px rgba(0,0,0,0.08)", "marginTop": "30px"}, children=[
        html.H3("Inversiones por banco", style={"color": "#111827", "marginBottom": "8px"}),
        html.P(
            "Aportaciones netas, valor actual y TWR por banco.",
            id="texto-inversiones-banco",
            style={"color": "#6b7280", "marginBottom": "20px"},
        ),
        html.Div(id="tabla-inversiones-banco")
    ])
])


@callback(
    Output("grafico-cartera", "figure"),
    Output("mapa-calor-activos", "figure"),
    Output("tarjeta-total-titulo", "children"), Output("tarjeta-total-valor", "children"),
    Output("tarjeta-valor-titulo", "children"), Output("tarjeta-valor-valor", "children"),
    Output("tarjeta-twr-titulo", "children"), Output("tarjeta-twr-valor", "children"),
    Output("tarjeta-vol-titulo", "children"), Output("tarjeta-vol-valor", "children"),
    Output("tarjeta-sharpe-titulo", "children"), Output("tarjeta-sharpe-valor", "children"),
    Output("tabla-operaciones-abiertas", "children"),
    Output("tabla-operaciones-cerradas", "children"),
    Output("texto-inversiones-banco", "children"),
    Output("tabla-inversiones-banco", "children"),
    Output("tabla-proximos-dividendos", "children"),
    Input("selector-divisa", "value"), Input("selector-grafico", "value"), Input("selector-periodo", "value"),
    Input("selector-banco", "value"),
)
def actualizar_dashboard(divisa, tipo_grafico, periodo, banco):
    operaciones_banco, cash_banco = _datos_banco(banco)
    datos = _preparar_datos_resumen(periodo, divisa, banco)
    divisa_txt = divisa.upper()
    simbolo = simbolo_divisa(divisa)
    nombre_periodo = PERIODOS[periodo]["nombre"]
    nombre_banco = "Toda la cartera" if banco == BANCO_TODA_LA_CARTERA else banco

    titulo_base = f"{'Drawdown' if tipo_grafico == 'drawdown' else 'Rentabilidad'} TWR {divisa_txt} y capital total invertido · {nombre_banco}"
    fig = (
        crear_grafico_drawdown(datos["twr"], datos["capital"], simbolo, titulo_base, f"Drawdown {divisa_txt}", f"Capital total invertido {divisa_txt}")
        if tipo_grafico == "drawdown"
        else crear_grafico_twr(datos["twr"], datos["capital"], simbolo, titulo_base, f"Rentabilidad TWR {divisa_txt}", f"Capital total invertido {divisa_txt}")
    )
    fig.update_layout(title={"text": f"{fig.layout.title.text} · {nombre_periodo}", "x": 0.05, "xanchor": "left", "y": 0.99, "yanchor": "top"})

    metricas = calcular_metricas_periodo(datos["valor"], datos["capital"], datos["flujos"], datos["twr"], periodo)
    fecha_inicio = _fecha_inicio_desde_periodo(datos, periodo)
    mapa_activos = crear_mapa_calor_activos(
        calcular_rentabilidad_anualizada_por_activo(
            operaciones_banco, cash_banco, datos.index.min(), divisa_txt
        ),
        simbolo,
        f"Rentabilidad anualizada por activo · {nombre_periodo} · {nombre_banco}",
    )
    fecha_inicio_comparativa = _fecha_inicio_desde_periodo(
        preparar_datos_divisa(periodo, divisa), periodo
    )
    tabla_abiertas = _crear_tabla_operaciones_abiertas_periodo(fecha_inicio, operaciones_banco, cash_banco)
    tabla_cerradas = crear_tabla_operaciones_cerradas(
        _filtrar_operaciones_cerradas(calcular_operaciones_cerradas(operaciones_banco), fecha_inicio),
    )
    texto_banco, tabla_banco = _crear_tabla_inversiones_banco_periodo(
        fecha_inicio_comparativa, divisa
    )
    tabla_dividendos = crear_tabla_proximos_dividendos(
        _filtrar_dividendos_por_banco(operaciones_banco)
    )

    return (
        fig,
        mapa_activos,
        _titulo_capital_total(divisa_txt),
        formatear_importe(metricas["capital_total"], simbolo),
        f"Valor actual {divisa_txt}",
        formatear_importe(metricas["valor_final"], simbolo),
        titulo_twr_anualizado(divisa_txt, metricas["dias_twr"]),
        "N/D" if metricas["twr_anualizado"] is None else _formatear_twr(metricas["twr_anualizado"]),
        titulo_volatilidad(divisa_txt, metricas["sesiones_riesgo"]),
        "N/D" if metricas["vol"] is None else f"{metricas['vol'] * 100:.2f}%",
        titulo_sharpe(divisa_txt, metricas["sesiones_riesgo"]),
        "N/D" if metricas["sharpe"] is None else f"{metricas['sharpe']:.2f}",
        tabla_abiertas,
        tabla_cerradas,
        texto_banco,
        tabla_banco,
        tabla_dividendos,
    )
