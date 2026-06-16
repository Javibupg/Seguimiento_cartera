import pandas as pd
import dash
from dash import html, dcc, callback, Input, Output, dash_table
import plotly.graph_objects as go

from cartera_utils import calcular_optimizacion_montecarlo_sharpe
from datos import ESTILO_BOTON, RF_ANUAL, RF_FECHA, calcular_distribucion_actual, cash, operaciones
from auxfun import crear_tarjeta, titulo_tarjeta


N_SIMULACIONES_MONTECARLO = 10000
TOOLTIP_MONTECARLO = (
    "Se simulan 10.000 carteras aleatorias con distintos pesos usando 1 año de histórico. "
    "Cada punto muestra rentabilidad esperada y volatilidad anualizadas; "
    "la cartera recomendada se elige dentro de un entorno casi óptimo, priorizando la menor diferencia de pesos frente a la cartera actual. "
    f"Sharpe calculado con tipo libre de riesgo EUR: {RF_ANUAL * 100:.2f}% anual"
    f"{' (' + RF_FECHA + ')' if RF_FECHA else ' (fallback)'}."
)


dash.register_page(
    __name__,
    path="/distribucion",
    name="Distribución",
    title="Distribución de cartera",
    order=2,
)


def formatear_importe(valor, simbolo="€"):
    return f"{simbolo}{valor:,.2f}"


def preparar_distribucion_sin_cash(df):
    """Recalcula pesos únicamente entre activos, sin cash residual."""
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()

    if "Activo" in df.columns:
        df = df[df["Activo"].str.lower() != "cash"].copy()

    if "Valor_EUR" not in df.columns:
        df["Valor_EUR"] = 0.0

    if "Valor_USD" not in df.columns:
        df["Valor_USD"] = 0.0

    if "Precio_pagado_EUR" not in df.columns:
        if "Coste_total_EUR" in df.columns:
            df["Precio_pagado_EUR"] = df["Coste_total_EUR"]
        elif "Precio_medio_pagado_EUR" in df.columns and "Acciones" in df.columns:
            df["Precio_pagado_EUR"] = df["Precio_medio_pagado_EUR"] * df["Acciones"]
        else:
            df["Precio_pagado_EUR"] = 0.0

    if "Acciones" not in df.columns:
        df["Acciones"] = 0.0

    if "Divisa" not in df.columns:
        df["Divisa"] = "-"

    valor_total = df["Valor_EUR"].sum()
    df["Peso"] = df["Valor_EUR"] / valor_total if valor_total != 0 else 0

    return df.sort_values("Valor_EUR", ascending=False).reset_index(drop=True)


def figura_distribucion(df, tipo_grafico):
    if df.empty:
        fig = go.Figure()
        fig.update_layout(
            title="No hay posiciones abiertas para mostrar",
            template="plotly_white",
            height=550,
        )
        return fig

    if tipo_grafico == "barras":
        fig = go.Figure()

        fig.add_trace(
            go.Bar(
                x=df["Activo"],
                y=df["Peso"] * 100,
                text=df["Peso"].map(lambda x: f"{x * 100:.2f}%"),
                textposition="outside",
                hovertemplate=(
                    "Activo: %{x}<br>"
                    "Peso: %{y:.2f}%"
                    "<extra></extra>"
                ),
            )
        )

        fig.update_layout(
            title={
                "text": "Distribución de la cartera por activo",
                "x": 0.05,
                "xanchor": "left",
            },
            template="plotly_white",
            height=550,
            margin=dict(l=40, r=40, t=80, b=40),
            yaxis_title="Peso en cartera",
            yaxis_ticksuffix="%",
            xaxis_title="Activo",
        )

        return fig

    fig = go.Figure()

    fig.add_trace(
        go.Pie(
            labels=df["Activo"],
            values=df["Valor_EUR"],
            hole=0.45,
            textinfo="label+percent",
            hovertemplate=(
                "Activo: %{label}<br>"
                "Valor: €%{value:,.2f}<br>"
                "Peso: %{percent}"
                "<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        title={
            "text": "Distribución de la cartera por activo",
            "x": 0.05,
            "xanchor": "left",
        },
        template="plotly_white",
        height=550,
        margin=dict(l=40, r=40, t=80, b=40),
        legend=dict(
            orientation="v",
            yanchor="middle",
            y=0.5,
            xanchor="left",
            x=1.02,
        ),
    )

    return fig


def tabla_distribucion(df):
    if df.empty:
        return html.Div(
            "No hay posiciones abiertas.",
            style={"color": "#6b7280", "padding": "20px"},
        )

    tabla = df.copy()

    tabla["Acciones"] = tabla["Acciones"].map(lambda x: f"{x:,.4f}")
    tabla["Precio_pagado_EUR"] = tabla["Precio_pagado_EUR"].map(lambda x: f"€{x:,.2f}")
    tabla["Valor_EUR"] = tabla["Valor_EUR"].map(lambda x: f"€{x:,.2f}")
    tabla["Peso"] = tabla["Peso"].map(lambda x: f"{x * 100:.2f}%")

    tabla = tabla.rename(
        columns={
            "Divisa": "Divisa activo",
            "Precio_pagado_EUR": "Precio pagado total EUR",
            "Valor_EUR": "Precio actual total EUR",
        }
    )

    columnas = [
        "Activo",
        "Divisa activo",
        "Acciones",
        "Precio pagado total EUR",
        "Precio actual total EUR",
        "Peso",
    ]

    return dash_table.DataTable(
        data=tabla[columnas].to_dict("records"),
        columns=[{"name": col, "id": col} for col in columnas],
        page_action="none",
        fixed_rows={"headers": True},
        style_table={
            "height": "350px",
            "overflowY": "auto",
            "overflowX": "auto",
        },
        style_cell={
            "fontFamily": "Arial, sans-serif",
            "fontSize": "14px",
            "padding": "10px",
            "textAlign": "center",
            "minWidth": "120px",
            "whiteSpace": "normal",
        },
        style_header={
            "backgroundColor": "#f3f4f6",
            "fontWeight": "700",
            "color": "#111827",
        },
        style_data={
            "backgroundColor": "white",
            "color": "#111827",
        },
    )


def figura_montecarlo(resultado):
    simulaciones = resultado.get("simulaciones", pd.DataFrame())
    frontera = resultado.get("frontera", pd.DataFrame())
    actual = resultado.get("actual", {})
    optima = resultado.get("optima", {})
    misma_vola = resultado.get("misma_vola", {})

    if simulaciones.empty:
        fig = go.Figure()
        fig.update_layout(
            title=resultado.get("aviso") or "No hay datos suficientes para simular carteras",
            template="plotly_white",
            height=620,
        )
        return fig

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=simulaciones["Volatilidad"] * 100,
            y=simulaciones["Rentabilidad"] * 100,
            mode="markers",
            name="Carteras simuladas",
            marker={
                "size": 6,
                "opacity": 0.45,
                "color": simulaciones["Sharpe"],
                "colorscale": "Viridis",
                "showscale": True,
                "colorbar": {"title": "Sharpe"},
            },
            customdata=simulaciones["Sharpe"],
            hovertemplate=(
                "Volatilidad: %{x:.2f}%<br>"
                "Rentabilidad esperada: %{y:.2f}%<br>"
                "Sharpe: %{customdata:.2f}"
                "<extra></extra>"
            ),
        )
    )

    if not frontera.empty:
        fig.add_trace(
            go.Scatter(
                x=frontera["Volatilidad"] * 100,
                y=frontera["Rentabilidad"] * 100,
                mode="lines",
                name="Frontera aproximada",
                line={"width": 3, "color": "#111827"},
                hovertemplate=(
                    "Frontera<br>"
                    "Volatilidad: %{x:.2f}%<br>"
                    "Rentabilidad esperada: %{y:.2f}%"
                    "<extra></extra>"
                ),
            )
        )

    def add_punto_clave(datos, nombre, color, simbolo, tamano, hover_titulo):
        if not datos:
            return

        x = datos.get("Volatilidad", 0) * 100
        y = datos.get("Rentabilidad", 0) * 100

        fig.add_trace(
            go.Scatter(
                x=[x],
                y=[y],
                mode="markers",
                name=f"{nombre} halo",
                marker={
                    "size": tamano + 4,
                    "symbol": simbolo,
                    "color": "rgba(255,255,255,0.9)",
                    "line": {"width": 2, "color": "#0f172a"},
                },
                hoverinfo="skip",
                showlegend=False,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=[x],
                y=[y],
                mode="markers",
                name=nombre,
                marker={
                    "size": tamano,
                    "symbol": simbolo,
                    "color": color,
                    "line": {"width": 2, "color": "#0f172a"},
                },
                customdata=[datos.get("Sharpe", 0)],
                hovertemplate=(
                    f"{hover_titulo}<br>"
                    "Volatilidad: %{x:.2f}%<br>"
                    "Rentabilidad esperada: %{y:.2f}%<br>"
                    "Sharpe: %{customdata:.2f}"
                    "<extra></extra>"
                ),
            )
        )

    add_punto_clave(actual, "Cartera actual", "#f97316", "diamond", 9, "Cartera actual")
    add_punto_clave(optima, "Sharpe eficiente", "#16a34a", "star", 11, "Cartera Sharpe eficiente")
    add_punto_clave(
        misma_vola,
        "Máx. rentabilidad misma vola",
        "#2563eb",
        "circle",
        10,
        "Máxima rentabilidad con volatilidad no superior a la actual",
    )

    def add_label(datos, texto, ax, ay):
        if not datos:
            return
        fig.add_annotation(
            x=datos.get("Volatilidad", 0) * 100,
            y=datos.get("Rentabilidad", 0) * 100,
            text=texto,
            showarrow=True,
            arrowhead=2,
            arrowsize=1,
            arrowwidth=1,
            arrowcolor="#64748b",
            ax=ax,
            ay=ay,
            bgcolor="rgba(255,255,255,0.92)",
            bordercolor="rgba(100,116,139,0.35)",
            borderwidth=1,
            borderpad=4,
            font={"size": 12, "color": "#111827"},
        )

    add_label(actual, "Actual", 30, 35)
    add_label(optima, "Sharpe eficiente", -45, -28)
    add_label(misma_vola, "Máx. rent. misma vola", 45, -35)

    puntos_clave = [actual, optima, misma_vola]
    vols_clave = [p.get("Volatilidad", 0) * 100 for p in puntos_clave if p]
    rents_clave = [p.get("Rentabilidad", 0) * 100 for p in puntos_clave if p]
    max_vol = max([float(simulaciones["Volatilidad"].max() * 100), *vols_clave, 10])
    max_rent = max([float(simulaciones["Rentabilidad"].max() * 100), *rents_clave, 10])

    fig.update_layout(
        title={"text": "Simulación Monte Carlo · rentabilidad vs volatilidad", "x": 0.05, "xanchor": "left"},
        template="plotly_white",
        height=620,
        margin=dict(l=40, r=40, t=80, b=115),
        xaxis={"title": "Volatilidad anualizada", "ticksuffix": "%", "range": [0, max_vol * 1.05]},
        yaxis={"title": "Rentabilidad esperada anualizada", "ticksuffix": "%", "range": [0, max_rent * 1.08]},
        legend={
            "orientation": "h",
            "yanchor": "top",
            "y": -0.18,
            "xanchor": "center",
            "x": 0.5,
            "bgcolor": "rgba(255,255,255,0.75)",
            "font": {"size": 12},
        },
    )
    return fig


def tabla_pesos_optimos(resultado):
    pesos = resultado.get("pesos", pd.DataFrame())

    if pesos.empty:
        return html.Div(
            resultado.get("aviso") or "No hay pesos óptimos para mostrar.",
            style={"color": "#6b7280", "padding": "20px"},
        )

    def peso_con_cambio(peso, cambio_pp):
        color = "#16a34a" if cambio_pp >= 0 else "#dc2626"
        return [
            html.Span(f"{peso * 100:.2f}%"),
            html.Span(
                f" ({cambio_pp:+.2f}%)",
                style={"color": color, "fontWeight": "700", "marginLeft": "4px"},
            ),
        ]

    header_style = {
        "backgroundColor": "#f3f4f6",
        "fontWeight": "700",
        "color": "#111827",
        "padding": "11px 12px",
        "textAlign": "center",
        "borderBottom": "1px solid #d1d5db",
    }
    cell_style = {
        "padding": "11px 12px",
        "textAlign": "center",
        "borderBottom": "1px solid #e5e7eb",
        "fontSize": "14px",
    }

    return html.Div(
        style={"overflowX": "auto"},
        children=html.Table(
            style={"width": "100%", "borderCollapse": "collapse", "backgroundColor": "white"},
            children=[
                html.Thead(
                    html.Tr(
                        [
                            html.Th("Activo", style=header_style),
                            html.Th("Peso actual", style=header_style),
                            html.Th("Peso sharpe máx.", style=header_style),
                            html.Th("Peso rent. max.", style=header_style),
                        ]
                    )
                ),
                html.Tbody(
                    [
                        html.Tr(
                            [
                                html.Td(fila.get("Nombre", fila["Activo"]), style=cell_style),
                                html.Td(f"{fila['Peso_actual'] * 100:.2f}%", style=cell_style),
                                html.Td(peso_con_cambio(fila["Peso_optimo"], fila["Cambio_pp"]), style=cell_style),
                                html.Td(
                                    peso_con_cambio(fila["Peso_misma_vola"], fila["Cambio_misma_vola_pp"]),
                                    style=cell_style,
                                ),
                            ]
                        )
                        for _, fila in pesos.iterrows()
                    ]
                ),
            ],
        ),
    )


def resumen_optimizacion(resultado, tipo):
    datos = resultado.get(tipo, {})
    if not datos:
        return "-"
    return html.Div(
        style={"fontSize": "15px", "lineHeight": "1.35", "fontWeight": "700"},
        children=[
            html.Div(
                f"Rent. {datos.get('Rentabilidad', 0) * 100:.2f}% · "
                f"Vol. {datos.get('Volatilidad', 0) * 100:.2f}%"
            ),
            html.Div(f"Sharpe {datos.get('Sharpe', 0):.2f}"),
        ],
    )


def tarjeta_optimizacion(titulo, id_valor):
    return html.Div(
        style={
            "backgroundColor": "#f9fafb",
            "padding": "16px 18px",
            "borderRadius": "12px",
            "border": "1px solid #e5e7eb",
        },
        children=[
            html.Div(
                titulo,
                style={"fontSize": "13px", "color": "#64748b", "fontWeight": "700", "marginBottom": "8px"},
            ),
            html.Div(id=id_valor, children="-", style={"color": "#111827"}),
        ],
    )


layout = html.Div(
    children=[
        html.H2(
            "Distribución de cartera",
            style={"color": "#111827", "marginBottom": "5px"},
        ),
        html.P(
            "Peso actual de cada activo sobre el total invertido en posiciones abiertas. Los importes principales se muestran en EUR.",
            style={"color": "#6b7280", "marginBottom": "30px"},
        ),

        html.Div(
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(3, 1fr)",
                "gap": "20px",
                "marginBottom": "30px",
            },
            children=[
                crear_tarjeta("Nº activos", "0", id_valor="dist-n-activos"),
                crear_tarjeta("Valor cartera EUR", "€0.00", id_valor="dist-valor-eur"),
                crear_tarjeta("Valor cartera USD", "$0.00", id_valor="dist-valor-usd"),
            ],
        ),

        html.Div(
            style={
                "backgroundColor": "white",
                "padding": "24px",
                "borderRadius": "18px",
                "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
                "marginBottom": "30px",
            },
            children=[
                html.Div(
                    "Tipo de gráfico",
                    style={
                        "fontSize": "14px",
                        "fontWeight": "700",
                        "color": "#374151",
                        "marginBottom": "8px",
                    },
                ),
                dcc.RadioItems(
                    id="selector-grafico-distribucion",
                    options=[
                        {"label": "Circular", "value": "circular"},
                        {"label": "Barras", "value": "barras"},
                    ],
                    value="circular",
                    inline=True,
                    labelStyle=ESTILO_BOTON,
                    inputStyle={"marginRight": "8px"},
                    style={"marginBottom": "20px"},
                ),
                dcc.Graph(
                    id="grafico-distribucion",
                    config={"displayModeBar": True},
                ),
            ],
        ),

        html.Div(
            style={
                "backgroundColor": "white",
                "padding": "24px",
                "borderRadius": "18px",
                "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
                "marginBottom": "30px",
            },
            children=[
                html.H3(
                    "Detalle por activo",
                    style={"color": "#111827", "marginBottom": "20px"},
                ),
                html.Div(id="tabla-distribucion"),
            ],
        ),

        html.Div(
            style={
                "backgroundColor": "white",
                "padding": "24px",
                "borderRadius": "18px",
                "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
            },
            children=[
                dcc.Store(id="montecarlo-trigger", data=N_SIMULACIONES_MONTECARLO),
                html.H3(
                    titulo_tarjeta("Optimización por Sharpe", TOOLTIP_MONTECARLO),
                    style={"color": "#111827", "marginBottom": "8px", "display": "flex", "alignItems": "center"},
                ),
                html.P(
                    "Simula carteras con distintos pesos para comparar rentabilidad esperada, volatilidad y Sharpe. "
                    "Usa 1 año de histórico, anualiza con 252 sesiones y solo muestra carteras con rentabilidad esperada positiva.",
                    style={"color": "#6b7280", "marginTop": "0", "marginBottom": "18px"},
                ),
                html.Div(id="aviso-montecarlo", style={"color": "#b45309", "fontWeight": "700", "marginBottom": "14px"}),
                html.Div(
                    style={
                        "display": "grid",
                        "gridTemplateColumns": "repeat(3, 1fr)",
                        "gap": "20px",
                        "marginBottom": "20px",
                    },
                    children=[
                        tarjeta_optimizacion("Cartera actual", "montecarlo-actual"),
                        tarjeta_optimizacion("Sharpe eficiente", "montecarlo-optima"),
                        tarjeta_optimizacion("Máx. rent. misma vola", "montecarlo-misma-vola"),
                    ],
                ),
                dcc.Loading(
                    type="circle",
                    children=dcc.Graph(id="grafico-montecarlo-sharpe", config={"displayModeBar": True}),
                ),
                html.H4("Distribución óptima", style={"color": "#111827", "marginBottom": "14px"}),
                html.Div(id="tabla-pesos-optimos"),
            ],
        ),
    ]
)


@callback(
    Output("grafico-distribucion", "figure"),
    Output("tabla-distribucion", "children"),
    Output("dist-n-activos", "children"),
    Output("dist-valor-eur", "children"),
    Output("dist-valor-usd", "children"),
    Input("selector-grafico-distribucion", "value"),
)
def actualizar_distribucion(tipo_grafico):
    df, valor_eur, valor_usd = calcular_distribucion_actual()
    df = preparar_distribucion_sin_cash(df)

    if not df.empty:
        valor_eur = float(df["Valor_EUR"].sum())
        valor_usd = float(df["Valor_USD"].sum())

    n_activos = len(df) if df is not None else 0

    return (
        figura_distribucion(df, tipo_grafico),
        tabla_distribucion(df),
        str(n_activos),
        formatear_importe(valor_eur, "€"),
        formatear_importe(valor_usd, "$"),
    )


@callback(
    Output("grafico-montecarlo-sharpe", "figure"),
    Output("tabla-pesos-optimos", "children"),
    Output("montecarlo-actual", "children"),
    Output("montecarlo-optima", "children"),
    Output("montecarlo-misma-vola", "children"),
    Output("aviso-montecarlo", "children"),
    Input("montecarlo-trigger", "data"),
)
def actualizar_montecarlo(n_simulaciones):
    resultado = calcular_optimizacion_montecarlo_sharpe(
        operaciones,
        cash,
        rf_anual=RF_ANUAL,
        n_simulaciones=int(n_simulaciones or N_SIMULACIONES_MONTECARLO),
    )

    return (
        figura_montecarlo(resultado),
        tabla_pesos_optimos(resultado),
        resumen_optimizacion(resultado, "actual"),
        resumen_optimizacion(resultado, "optima"),
        resumen_optimizacion(resultado, "misma_vola"),
        resultado.get("aviso") or "",
    )
