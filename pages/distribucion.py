import pandas as pd
import dash
from dash import html, dcc, callback, Input, Output, dash_table
import plotly.graph_objects as go

from datos import (
    ESTILO_BOTON,
    PERIODOS,
    calcular_distribucion_actual,
    calcular_historico_posicion,
    obtener_opciones_posiciones_abiertas,
)
from cartera_utils import cargar_listado_activos
from auxfun import crear_tarjeta, formatear_resultado_con_rentabilidad


dash.register_page(
    __name__,
    path="/distribucion",
    name="Posiciones",
    title="Posiciones abiertas",
    order=2,
)


VERDE = "#16a34a"
ROJO = "#dc2626"
GRIS = "#6b7280"

ESTILO_CAJA = {
    "backgroundColor": "white",
    "padding": "24px",
    "borderRadius": "18px",
    "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
    "marginBottom": "30px",
}


def formatear_importe(valor, simbolo="€"):
    return f"{simbolo}{valor:,.2f}"


def simbolo_activo(divisa):
    return "€" if str(divisa).upper() == "EUR" else "$"


def formatear_importe_activo(valor, divisa):
    return formatear_importe(valor, simbolo_activo(divisa))


def formatear_fecha(fecha):
    if pd.isna(fecha):
        return "-"
    return pd.to_datetime(fecha).strftime("%d/%m/%Y")


def span_pct(valor):
    color = VERDE if valor >= 0 else ROJO
    signo = "+" if valor >= 0 else ""
    return html.Span(
        f"({signo}{valor * 100:.2f}%)",
        style={"color": color, "fontSize": "21px", "fontWeight": "700", "marginLeft": "7px"},
    )


def span_peso(valor):
    return html.Span(
        f"({valor * 100:.2f}%)",
        style={"color": GRIS, "fontSize": "21px", "fontWeight": "700", "marginLeft": "7px"},
    )


def valor_tarjeta_activo(ticker, valor, tipo="rentabilidad"):
    if ticker is None:
        return "-"
    return [html.Span(str(ticker)), span_pct(valor) if tipo == "rentabilidad" else span_peso(valor)]


def preparar_posiciones(df):
    """Limpia la tabla de posiciones, añade nombres y recalcula pesos sin cash residual."""
    if df is None or df.empty:
        return pd.DataFrame()

    df = df.copy()
    if "Activo" in df.columns:
        df = df[df["Activo"].str.lower() != "cash"].copy()

    nombres = cargar_listado_activos()
    df["Ticker"] = df["Activo"]
    df["Nombre"] = df["Ticker"].map(nombres).fillna(df["Ticker"])

    valor_total = df["Valor_EUR"].sum()
    df["Peso"] = df["Valor_EUR"] / valor_total if valor_total != 0 else 0

    return df.sort_values("Valor_EUR", ascending=False).reset_index(drop=True)


def tarjeta_resultado_total(df):
    if df.empty:
        return "€0.00"
    coste = df["Coste_total_EUR"].sum()
    resultado = df["Resultado_abierto_EUR"].sum()
    rentabilidad = resultado / coste if coste else 0
    return formatear_resultado_con_rentabilidad(resultado, rentabilidad, "€")


def tarjeta_mejor_posicion(df):
    if df.empty:
        return "-"
    fila = df.loc[df["Rentabilidad_abierta"].idxmax()]
    return valor_tarjeta_activo(fila["Ticker"], fila["Rentabilidad_abierta"], "rentabilidad")


def tarjeta_peor_posicion(df):
    if df.empty:
        return "-"
    fila = df.loc[df["Rentabilidad_abierta"].idxmin()]
    return valor_tarjeta_activo(fila["Ticker"], fila["Rentabilidad_abierta"], "rentabilidad")


def tarjeta_mayor_peso(df):
    if df.empty:
        return "-"
    fila = df.loc[df["Peso"].idxmax()]
    return valor_tarjeta_activo(fila["Ticker"], fila["Peso"], "peso")


def figura_posiciones(df, tipo_grafico):
    if df.empty:
        fig = go.Figure()
        fig.update_layout(title="No hay posiciones abiertas para mostrar", template="plotly_white", height=550)
        return fig

    eje_x = df["Nombre"]
    hover_activo = df["Nombre"] + " (" + df["Ticker"] + ")"

    if tipo_grafico == "barras":
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=eje_x,
                y=df["Peso"] * 100,
                text=df["Peso"].map(lambda x: f"{x * 100:.2f}%"),
                textposition="outside",
                customdata=hover_activo,
                hovertemplate="Activo: %{customdata}<br>Peso: %{y:.2f}%<extra></extra>",
            )
        )
        fig.update_layout(
            title={"text": "Distribución de la cartera por activo", "x": 0.05, "xanchor": "left"},
            template="plotly_white",
            height=550,
            margin=dict(l=40, r=40, t=80, b=40),
            yaxis_title="Peso en cartera",
            yaxis_ticksuffix="%",
            xaxis_title="Activo",
        )
        return fig

    if tipo_grafico == "resultado":
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=eje_x,
                y=df["Resultado_abierto_EUR"],
                text=df["Resultado_abierto_EUR"].map(lambda x: f"€{x:,.2f}"),
                textposition="outside",
                customdata=pd.concat([hover_activo, df[["Rentabilidad_abierta", "Coste_total_EUR", "Valor_EUR"]]], axis=1),
                hovertemplate=(
                    "Activo: %{customdata[0]}<br>"
                    "Resultado abierto: €%{y:,.2f}<br>"
                    "Rentabilidad abierta: %{customdata[1]:.2%}<br>"
                    "Coste total: €%{customdata[2]:,.2f}<br>"
                    "Valor actual: €%{customdata[3]:,.2f}"
                    "<extra></extra>"
                ),
            )
        )
        fig.update_layout(
            title={"text": "Resultado abierto por posición", "x": 0.05, "xanchor": "left"},
            template="plotly_white",
            height=550,
            margin=dict(l=40, r=40, t=80, b=40),
            yaxis_title="Resultado abierto EUR",
            yaxis_tickprefix="€",
            xaxis_title="Activo",
        )
        return fig

    if tipo_grafico == "dispersion":
        max_valor = df["Valor_EUR"].max()
        tamanos = 12 + 38 * (df["Valor_EUR"] / max_valor if max_valor else 0)

        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df["Peso"] * 100,
                y=df["Rentabilidad_abierta"] * 100,
                mode="markers+text",
                text=df["Ticker"],
                textposition="top center",
                marker={"size": tamanos, "opacity": 0.75},
                customdata=pd.concat([hover_activo, df[["Resultado_abierto_EUR", "Valor_EUR", "Coste_total_EUR"]]], axis=1),
                hovertemplate=(
                    "Activo: %{customdata[0]}<br>"
                    "Peso: %{x:.2f}%<br>"
                    "Rentabilidad abierta: %{y:.2f}%<br>"
                    "Resultado abierto: €%{customdata[1]:,.2f}<br>"
                    "Valor actual: €%{customdata[2]:,.2f}<br>"
                    "Coste total: €%{customdata[3]:,.2f}"
                    "<extra></extra>"
                ),
            )
        )
        fig.add_hline(y=0, line_width=1, line_dash="dash")
        fig.update_layout(
            title={"text": "Peso vs rentabilidad abierta", "x": 0.05, "xanchor": "left"},
            template="plotly_white",
            height=550,
            margin=dict(l=40, r=40, t=80, b=40),
            xaxis_title="Peso en cartera",
            yaxis_title="Rentabilidad abierta",
            xaxis_ticksuffix="%",
            yaxis_ticksuffix="%",
        )
        return fig

    fig = go.Figure()
    fig.add_trace(
        go.Pie(
            labels=df["Nombre"],
            values=df["Valor_EUR"],
            hole=0.45,
            textinfo="label+percent",
            customdata=df["Ticker"],
            hovertemplate="Activo: %{label} (%{customdata})<br>Valor: €%{value:,.2f}<br>Peso: %{percent}<extra></extra>",
        )
    )
    fig.update_layout(
        title={"text": "Distribución de la cartera por activo", "x": 0.05, "xanchor": "left"},
        template="plotly_white",
        height=550,
        margin=dict(l=40, r=40, t=80, b=40),
        legend={"orientation": "v", "yanchor": "middle", "y": 0.5, "xanchor": "left", "x": 1.02},
    )
    return fig


def tabla_posiciones(df):
    if df.empty:
        return html.Div("No hay posiciones abiertas.", style={"color": GRIS, "padding": "20px"})

    tabla = df.copy()
    tabla["Activo"] = tabla["Nombre"]
    tabla["Acciones"] = tabla["Acciones"].map(lambda x: f"{x:,.4f}")
    tabla["Fecha inicial"] = tabla["Fecha_primera_compra"].map(formatear_fecha)
    tabla["Última compra"] = tabla["Fecha_ultima_compra"].map(formatear_fecha)
    tabla["Precio medio compra"] = tabla.apply(lambda r: formatear_importe_activo(r["Precio_medio_pagado"], r["Divisa"]), axis=1)
    tabla["Precio actual"] = tabla.apply(lambda r: formatear_importe_activo(r["Precio_actual"], r["Divisa"]), axis=1)
    tabla["Coste total EUR"] = tabla["Coste_total_EUR"].map(lambda x: f"€{x:,.2f}")
    tabla["Valor actual EUR"] = tabla["Valor_EUR"].map(lambda x: f"€{x:,.2f}")
    tabla["Resultado abierto EUR"] = tabla["Resultado_abierto_EUR"].map(lambda x: f"€{x:,.2f}")
    tabla["Rentabilidad abierta"] = tabla["Rentabilidad_abierta"].map(lambda x: f"{x * 100:.2f}%")
    tabla["Peso"] = tabla["Peso"].map(lambda x: f"{x * 100:.2f}%")
    tabla = tabla.rename(columns={"Divisa": "Divisa activo", "Dias_en_cartera": "Días"})

    columnas = [
        "Activo", "Ticker", "Divisa activo", "Acciones", "Fecha inicial", "Última compra", "Días",
        "Precio medio compra", "Precio actual", "Coste total EUR", "Valor actual EUR",
        "Resultado abierto EUR", "Rentabilidad abierta", "Peso",
    ]

    return dash_table.DataTable(
        data=tabla[columnas].to_dict("records"),
        columns=[{"name": col, "id": col} for col in columnas],
        page_action="none",
        fixed_rows={"headers": True},
        sort_action="native",
        style_table={"height": "420px", "overflowY": "auto", "overflowX": "auto"},
        style_cell={
            "fontFamily": "Arial, sans-serif",
            "fontSize": "14px",
            "padding": "10px",
            "textAlign": "center",
            "minWidth": "125px",
            "whiteSpace": "normal",
        },
        style_header={"backgroundColor": "#f3f4f6", "fontWeight": "700", "color": "#111827"},
        style_data={"backgroundColor": "white", "color": "#111827"},
        style_data_conditional=[
            {"if": {"column_id": "Resultado abierto EUR"}, "color": VERDE, "fontWeight": "700"},
            {"if": {"filter_query": "{Resultado abierto EUR} contains '-'", "column_id": "Resultado abierto EUR"}, "color": ROJO, "fontWeight": "700"},
            {"if": {"column_id": "Rentabilidad abierta"}, "color": VERDE, "fontWeight": "700"},
            {"if": {"filter_query": "{Rentabilidad abierta} contains '-'", "column_id": "Rentabilidad abierta"}, "color": ROJO, "fontWeight": "700"},
        ],
    )


def filtrar_historico_posicion(datos, periodo):
    if datos is None or datos.empty:
        return pd.DataFrame()
    if periodo == "max":
        return datos.copy()
    fecha_inicio = datos.index.max() - PERIODOS[periodo]["offset"]
    filtrado = datos.loc[datos.index >= fecha_inicio].copy()
    return filtrado if not filtrado.empty else datos.tail(1).copy()


def _rebasear_precio(datos, columna_precio):
    if datos.empty or columna_precio not in datos.columns:
        return pd.Series(0.0, index=datos.index)
    s = pd.to_numeric(datos[columna_precio], errors="coerce").ffill().bfill()
    if s.empty or pd.isna(s.iloc[0]) or abs(float(s.iloc[0])) < 1e-12:
        return pd.Series(0.0, index=datos.index)
    return s / float(s.iloc[0]) - 1


def _serie_eventos(datos, columna):
    if columna not in datos.columns:
        return pd.Series(0.0, index=datos.index)
    return pd.to_numeric(datos[columna], errors="coerce").fillna(0.0)


def _add_marcadores_operaciones(fig, datos, columna_y):
    compras = datos[_serie_eventos(datos, "Compra_acciones") > 0].copy()
    ventas = datos[_serie_eventos(datos, "Venta_acciones") > 0].copy()

    if not compras.empty:
        fig.add_trace(
            go.Scatter(
                x=compras.index,
                y=compras[columna_y] * 100,
                mode="markers",
                name="Compras",
                marker={"size": 12, "symbol": "triangle-up", "color": VERDE, "line": {"width": 1, "color": "white"}},
                customdata=compras[["Compra_acciones", "Compra_importe_EUR", "Precio_EUR"]],
                hovertemplate=(
                    "Compra<br>"
                    "Fecha: %{x}<br>"
                    "Rentabilidad EUR: %{y:.2f}%<br>"
                    "Acciones: %{customdata[0]:,.4f}<br>"
                    "Importe: €%{customdata[1]:,.2f}<br>"
                    "Precio EUR: €%{customdata[2]:,.2f}"
                    "<extra></extra>"
                ),
            )
        )

    if not ventas.empty:
        fig.add_trace(
            go.Scatter(
                x=ventas.index,
                y=ventas[columna_y] * 100,
                mode="markers",
                name="Ventas",
                marker={"size": 12, "symbol": "triangle-down", "color": ROJO, "line": {"width": 1, "color": "white"}},
                customdata=ventas[["Venta_acciones", "Venta_importe_EUR", "Precio_EUR"]],
                hovertemplate=(
                    "Venta<br>"
                    "Fecha: %{x}<br>"
                    "Rentabilidad EUR: %{y:.2f}%<br>"
                    "Acciones: %{customdata[0]:,.4f}<br>"
                    "Importe: €%{customdata[1]:,.2f}<br>"
                    "Precio EUR: €%{customdata[2]:,.2f}"
                    "<extra></extra>"
                ),
            )
        )


def figura_rentabilidad_posicion(activo, periodo):
    if not activo:
        fig = go.Figure()
        fig.update_layout(title="Selecciona una posición", template="plotly_white", height=550)
        return fig

    datos = calcular_historico_posicion(activo)
    if datos.empty:
        fig = go.Figure()
        fig.update_layout(title="No hay datos suficientes para esta posición", template="plotly_white", height=550)
        return fig

    datos = filtrar_historico_posicion(datos, periodo)
    if datos.empty:
        fig = go.Figure()
        fig.update_layout(title="No hay datos suficientes para esta ventana", template="plotly_white", height=550)
        return fig

    datos = datos.copy()
    datos["Rentabilidad_EUR_graf"] = _rebasear_precio(datos, "Precio_EUR")
    datos["Rentabilidad_activo_graf"] = _rebasear_precio(datos, "Precio")

    nombres = cargar_listado_activos()
    nombre = nombres.get(activo, activo)
    divisa = datos["Divisa"].iloc[-1]
    nombre_periodo = PERIODOS[periodo]["nombre"]

    fig = go.Figure()
    fig.add_trace(
        go.Scatter(
            x=datos.index,
            y=datos["Rentabilidad_EUR_graf"] * 100,
            mode="lines",
            name="Rentabilidad EUR",
            line={"width": 3},
            hovertemplate="Fecha: %{x}<br>Rentabilidad EUR: %{y:.2f}%<extra></extra>",
        )
    )

    if str(divisa).upper() == "USD":
        fig.add_trace(
            go.Scatter(
                x=datos.index,
                y=datos["Rentabilidad_activo_graf"] * 100,
                mode="lines",
                name="Rentabilidad USD",
                line={"width": 2, "dash": "dash"},
                hovertemplate="Fecha: %{x}<br>Rentabilidad USD: %{y:.2f}%<extra></extra>",
            )
        )

    _add_marcadores_operaciones(fig, datos, "Rentabilidad_EUR_graf")

    fig.add_hline(y=0, line_width=1, line_dash="dash")
    fig.update_layout(
        title={"text": f"Rentabilidad de {nombre} ({activo}) · {nombre_periodo}", "x": 0.05, "xanchor": "left"},
        template="plotly_white",
        height=550,
        margin=dict(l=40, r=40, t=80, b=40),
        hovermode="x unified",
        yaxis_title="Rentabilidad del activo desde inicio de ventana",
        yaxis_ticksuffix="%",
        xaxis_title="Fecha",
        legend={"orientation": "v", "yanchor": "top", "y": 0.98, "xanchor": "left", "x": 0.02},
    )
    return fig

opciones_activos = obtener_opciones_posiciones_abiertas()
valor_activo_inicial = opciones_activos[0]["value"] if opciones_activos else None

layout = html.Div(
    children=[
        html.H2("Posiciones abiertas", style={"color": "#111827", "marginBottom": "5px"}),
        html.P(
            "Detalle de cada posición abierta. Las ventas parciales reducen el coste usando precio medio ponderado; los importes principales se muestran en EUR.",
            style={"color": GRIS, "marginBottom": "30px"},
        ),
        html.Div(
            style={"display": "grid", "gridTemplateColumns": "repeat(3, 1fr)", "gap": "20px", "marginBottom": "30px"},
            children=[
                crear_tarjeta("Nº activos", "0", id_valor="pos-n-activos"),
                crear_tarjeta("Valor cartera EUR", "€0.00", id_valor="pos-valor-eur"),
                crear_tarjeta("Resultado abierto EUR", "€0.00", id_valor="pos-resultado-eur"),
                crear_tarjeta("Mejor posición", "-", id_valor="pos-mejor"),
                crear_tarjeta("Peor posición", "-", id_valor="pos-peor"),
                crear_tarjeta("Mayor peso", "-", id_valor="pos-mayor-peso"),
            ],
        ),
        html.Div(
            style=ESTILO_CAJA,
            children=[
                html.Div("Vista", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
                dcc.RadioItems(
                    id="selector-grafico-distribucion",
                    options=[
                        {"label": "Circular", "value": "circular"},
                        {"label": "Barras", "value": "barras"},
                        {"label": "Resultado abierto", "value": "resultado"},
                        {"label": "Peso vs rentabilidad", "value": "dispersion"},
                    ],
                    value="circular",
                    inline=True,
                    labelStyle=ESTILO_BOTON,
                    inputStyle={"marginRight": "8px"},
                    style={"marginBottom": "20px"},
                ),
                dcc.Graph(id="grafico-distribucion", config={"displayModeBar": True}),
            ],
        ),
        html.Div(
            style=ESTILO_CAJA,
            children=[
                html.H3("Rentabilidad por posición", style={"color": "#111827", "marginBottom": "8px"}),
                html.P("La serie se recalcula desde 0% para cada ventana y muestra compras/ventas como marcadores sobre la rentabilidad del activo.", style={"color": GRIS, "marginTop": "0", "marginBottom": "16px"}),
                html.Div(
                    style={"display": "grid", "gridTemplateColumns": "2fr 3fr", "gap": "20px", "marginBottom": "18px"},
                    children=[
                        html.Div(
                            children=[
                                html.Div("Activo", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
                                dcc.Dropdown(
                                    id="selector-activo-posicion",
                                    options=opciones_activos,
                                    value=valor_activo_inicial,
                                    clearable=False,
                                    placeholder="Selecciona un activo",
                                ),
                            ]
                        ),
                        html.Div(
                            children=[
                                html.Div("Periodo", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
                                dcc.RadioItems(
                                    id="selector-periodo-posicion",
                                    options=[{"label": v["label"], "value": k} for k, v in PERIODOS.items()],
                                    value="max",
                                    inline=True,
                                    labelStyle=ESTILO_BOTON,
                                    inputStyle={"marginRight": "8px"},
                                ),
                            ]
                        ),
                    ],
                ),
                dcc.Graph(id="grafico-rentabilidad-posicion", config={"displayModeBar": True, "scrollZoom": True}),
            ],
        ),
        html.Div(
            style={**ESTILO_CAJA, "marginBottom": "0"},
            children=[
                html.H3("Detalle por posición", style={"color": "#111827", "marginBottom": "20px"}),
                html.Div(id="tabla-distribucion"),
            ],
        ),
    ]
)


@callback(
    Output("grafico-distribucion", "figure"),
    Output("tabla-distribucion", "children"),
    Output("pos-n-activos", "children"),
    Output("pos-valor-eur", "children"),
    Output("pos-resultado-eur", "children"),
    Output("pos-mejor", "children"),
    Output("pos-peor", "children"),
    Output("pos-mayor-peso", "children"),
    Input("selector-grafico-distribucion", "value"),
)
def actualizar_distribucion(tipo_grafico):
    df, valor_eur, _ = calcular_distribucion_actual()
    df = preparar_posiciones(df)

    if not df.empty:
        valor_eur = float(df["Valor_EUR"].sum())

    return (
        figura_posiciones(df, tipo_grafico),
        tabla_posiciones(df),
        str(len(df)),
        formatear_importe(valor_eur, "€"),
        tarjeta_resultado_total(df),
        tarjeta_mejor_posicion(df),
        tarjeta_peor_posicion(df),
        tarjeta_mayor_peso(df),
    )


@callback(
    Output("grafico-rentabilidad-posicion", "figure"),
    Input("selector-activo-posicion", "value"),
    Input("selector-periodo-posicion", "value"),
)
def actualizar_rentabilidad_posicion(activo, periodo):
    return figura_rentabilidad_posicion(activo, periodo)
