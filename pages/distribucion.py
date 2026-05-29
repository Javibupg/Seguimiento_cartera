import dash
from dash import html, dcc, callback, Input, Output, dash_table
import plotly.graph_objects as go

from datos import *
from auxfun import crear_tarjeta


dash.register_page(
    __name__,
    path="/distribucion",
    name="Distribución",
    title="Distribución de cartera",
    order=2,
)


ESTILO_BOTON = {
    "display": "inline-block",
    "padding": "10px 18px",
    "marginRight": "10px",
    "border": "1px solid #d1d5db",
    "borderRadius": "10px",
    "cursor": "pointer",
    "backgroundColor": "#f9fafb",
    "fontWeight": "600",
}


def formatear_importe(valor, simbolo="$"):
    return f"{simbolo}{valor:,.2f}"


def obtener_fx_actual():
    if desglose_fx.empty:
        return None

    fx = desglose_fx["FX_EUR_por_USD"].dropna()

    if fx.empty:
        return None

    return float(fx.iloc[-1])


def calcular_precio_medio_pagado():
    """
    Calcula el precio medio de compra por acción de cada activo.
    Luego lo usaremos para calcular el importe total pagado
    por la posición actualmente abierta.
    """
    compras = operaciones[operaciones["Orden"] == "compra"].copy()

    if compras.empty:
        return {}

    precios = (
        compras
        .groupby("Activo")
        .agg(
            acciones_compradas=("Numero_acciones", "sum"),
            importe_comprado=("Importe", "sum"),
        )
    )

    precios["Precio_medio_compra"] = (
        precios["importe_comprado"] / precios["acciones_compradas"]
    )

    return precios["Precio_medio_compra"].to_dict()


def preparar_distribucion_sin_cash(df):
    """
    Elimina el cash residual y recalcula los pesos únicamente entre activos.
    Además añade el precio medio pagado por cada posición.
    """
    if df is None or df.empty:
        return df

    df = df.copy()

    if "Activo" in df.columns:
        df = df[df["Activo"].str.lower() != "cash"].copy()

    precios_pagados = calcular_precio_medio_pagado()
    df["Precio_pagado"] = df["Acciones"] * df["Activo"].map(precios_pagados)

    valor_total = df["Valor_USD"].sum()

    if valor_total != 0:
        df["Peso"] = df["Valor_USD"] / valor_total
    else:
        df["Peso"] = 0

    return df.sort_values("Valor_USD", ascending=False).reset_index(drop=True)


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
            values=df["Valor_USD"],
            hole=0.45,
            textinfo="label+percent",
            hovertemplate=(
                "Activo: %{label}<br>"
                "Valor: $%{value:,.2f}<br>"
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
    tabla["Precio_pagado"] = tabla["Precio_pagado"].map(lambda x: f"${x:,.2f}")
    tabla["Precio_actual_total"] = tabla["Valor_USD"].map(lambda x: f"${x:,.2f}")
    tabla["Peso"] = tabla["Peso"].map(lambda x: f"{x * 100:.2f}%")

    tabla = tabla.rename(
        columns={
            "Precio_pagado": "Precio pagado",
            "Precio_actual_total": "Precio actual",
        }
    )

    columnas = [
        "Activo",
        "Acciones",
        "Precio pagado",
        "Precio actual",
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


layout = html.Div(
    children=[
        html.H2(
            "Distribución de cartera",
            style={"color": "#111827", "marginBottom": "5px"},
        ),
        html.P(
            "Peso actual de cada activo sobre el total invertido en acciones.",
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
                crear_tarjeta("Valor cartera USD", "$0.00", id_valor="dist-valor-usd"),
                crear_tarjeta("Valor cartera EUR", "€0.00", id_valor="dist-valor-eur"),
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
            },
            children=[
                html.H3(
                    "Detalle por activo",
                    style={"color": "#111827", "marginBottom": "20px"},
                ),
                html.Div(id="tabla-distribucion"),
            ],
        ),
    ]
)


@callback(
    Output("grafico-distribucion", "figure"),
    Output("tabla-distribucion", "children"),
    Output("dist-n-activos", "children"),
    Output("dist-valor-usd", "children"),
    Output("dist-valor-eur", "children"),
    Input("selector-grafico-distribucion", "value"),
)

def actualizar_distribucion(tipo_grafico):
    df, _, _, _ = calcular_distribucion_actual()

    df = preparar_distribucion_sin_cash(df)

    valor_usd = df["Valor_USD"].sum() if not df.empty else 0.0
    n_activos = len(df)

    fx_actual = obtener_fx_actual()
    valor_eur = valor_usd * fx_actual if fx_actual is not None else 0.0

    return (
        figura_distribucion(df, tipo_grafico),
        tabla_distribucion(df),
        str(n_activos),
        formatear_importe(valor_usd, "$"),
        formatear_importe(valor_eur, "€"),
    )