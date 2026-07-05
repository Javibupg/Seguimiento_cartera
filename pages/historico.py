import numpy as np
import pandas as pd
import plotly.graph_objects as go
from dash import Input, Output, callback, dcc, html
from plotly.subplots import make_subplots

import dash
from auxfun import crear_data_table, estilos_signo
from cartera_utils import calcular_rentabilidades_diarias_ajustadas
from datos import series_cartera


dash.register_page(
    __name__,
    path="/historico",
    name="Hist\u00f3rico",
    title="Hist\u00f3rico de cartera",
    order=4,
)


COLOR_TEXTO = "#111827"
COLOR_MUTED = "#6b7280"
VERDE = "#16a34a"
ROJO = "#dc2626"
AZUL = "#2563eb"
SIMBOLO_EUR = "\u20ac"
MESES = (
    "Enero",
    "Febrero",
    "Marzo",
    "Abril",
    "Mayo",
    "Junio",
    "Julio",
    "Agosto",
    "Septiembre",
    "Octubre",
    "Noviembre",
    "Diciembre",
)

ESTILO_CAJA = {
    "backgroundColor": "white",
    "padding": "24px",
    "borderRadius": "18px",
    "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
    "marginBottom": "30px",
}

ESTILO_BOTON = {
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

ESTILO_INPUT_OCULTO = {"display": "none"}


def _formatear_importe(valor, con_signo=False):
    if valor is None or pd.isna(valor):
        return "-"

    valor = float(valor)
    if con_signo:
        signo = "+" if valor > 0 else "-" if valor < 0 else ""
        return f"{signo}{SIMBOLO_EUR}{abs(valor):,.2f}"
    return f"{SIMBOLO_EUR}{valor:,.2f}"


def _formatear_porcentaje(valor, con_signo=False):
    if valor is None or pd.isna(valor):
        return "-"

    valor = float(valor)
    signo = "+" if con_signo and valor > 0 else ""
    return f"{signo}{valor * 100:.2f}%"


def _datos_base():
    if series_cartera.empty:
        return pd.DataFrame()

    columnas = ["Valor_cartera_EUR", "Flujos_EUR", "Capital_EUR"]
    if any(col not in series_cartera.columns for col in columnas):
        return pd.DataFrame()

    datos = (
        series_cartera[columnas]
        .rename(
            columns={
                "Valor_cartera_EUR": "valor",
                "Flujos_EUR": "flujos",
                "Capital_EUR": "capital",
            }
        )
        .apply(pd.to_numeric, errors="coerce")
        .dropna(subset=["valor"])
        .sort_index()
    )

    if datos.empty:
        return datos

    datos["rent_diaria"] = calcular_rentabilidades_diarias_ajustadas(datos["valor"], datos["flujos"])
    datos["valor_inicio"] = datos["valor"].shift(1).fillna(datos["valor"] - datos["flujos"].fillna(0))
    return datos


def _etiqueta_periodo(periodo, periodicidad):
    return str(periodo.year) if periodicidad == "anual" else f"{MESES[periodo.month - 1]} {periodo.year}"


def _max_drawdown(rentabilidades):
    curva = (1 + rentabilidades.dropna()).cumprod()
    drawdown = curva / curva.cummax() - 1
    return float(drawdown.min()) if not drawdown.empty else 0.0


def _volatilidad_anualizada(rentabilidades):
    rentabilidades = rentabilidades.dropna()
    std = rentabilidades.std()
    if len(rentabilidades) < 2 or std == 0:
        return 0.0
    return float(std * np.sqrt(252))


def calcular_historico_periodos(periodicidad):
    datos = _datos_base()
    if datos.empty:
        return pd.DataFrame()

    filas = []
    periodos = datos.index.to_period("Y" if periodicidad == "anual" else "M")

    for periodo, grupo in datos.groupby(periodos):
        valor_inicio = grupo["valor_inicio"].iloc[0]
        valor_final = grupo["valor"].iloc[-1]
        capital_final = grupo["capital"].iloc[-1]
        flujos = grupo["flujos"].fillna(0)
        flujo_neto = flujos.sum()
        rentabilidades = grupo["rent_diaria"].fillna(0)

        filas.append(
            {
                "Periodo": _etiqueta_periodo(periodo, periodicidad),
                "orden": periodo.end_time,
                "valor_final": float(valor_final),
                "capital_final": float(capital_final),
                "flujo_neto": float(flujo_neto),
                "resultado": float(valor_final - valor_inicio - flujo_neto),
                "twr": float((1 + rentabilidades).prod() - 1),
                "volatilidad": _volatilidad_anualizada(rentabilidades),
                "drawdown": _max_drawdown(rentabilidades),
            }
        )

    return pd.DataFrame(filas)


def crear_grafico_historico(tabla, periodicidad):
    if tabla.empty:
        fig = go.Figure()
        fig.update_layout(
            title="No hay datos suficientes para mostrar el hist\u00f3rico",
            template="plotly_white",
            height=520,
        )
        return fig

    datos = tabla.sort_values("orden")
    if periodicidad == "mensual":
        datos = datos.tail(18)
    colores = np.where(datos["twr"] >= 0, VERDE, ROJO)
    titulo = "Rentabilidad TWR y flujo neto por " + ("a\u00f1o" if periodicidad == "anual" else "mes")

    fig = make_subplots(specs=[[{"secondary_y": True}]])
    fig.add_trace(
        go.Bar(
            x=datos["Periodo"],
            y=datos["twr"] * 100,
            name="TWR periodo",
            marker_color=colores,
            hovertemplate="Periodo: %{x}<br>TWR: %{y:.2f}%<extra></extra>",
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=datos["Periodo"],
            y=datos["flujo_neto"],
            mode="lines+markers",
            name="Flujo neto EUR",
            line={"width": 3, "color": AZUL},
            marker={"size": 7, "color": AZUL},
            hovertemplate="Periodo: %{x}<br>Flujo neto: \u20ac%{y:,.2f}<extra></extra>",
        ),
        secondary_y=True,
    )

    fig.update_layout(
        title={"text": titulo, "x": 0.05, "xanchor": "left"},
        template="plotly_white",
        height=520,
        margin=dict(l=40, r=50, t=80, b=80),
        hovermode="x unified",
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.02,
            "xanchor": "right",
            "x": 1,
        },
    )
    fig.update_yaxes(title_text="TWR periodo", ticksuffix="%", zeroline=True, secondary_y=False)
    fig.update_yaxes(
        title_text="Flujo neto EUR",
        tickprefix=SIMBOLO_EUR,
        separatethousands=True,
        zeroline=True,
        secondary_y=True,
    )
    fig.update_xaxes(title_text="Periodo")
    return fig


def crear_tabla_historico(tabla):
    if tabla.empty:
        return html.Div(
            "No hay datos suficientes para mostrar el hist\u00f3rico.",
            style={"color": COLOR_MUTED, "padding": "20px"},
        )

    datos = tabla.sort_values("orden", ascending=False).copy()
    datos["Flujo neto EUR"] = datos["flujo_neto"].map(lambda x: _formatear_importe(x, con_signo=True))
    datos["Valor final EUR"] = datos["valor_final"].map(_formatear_importe)
    datos["Capital final EUR"] = datos["capital_final"].map(_formatear_importe)
    datos["Resultado EUR"] = datos["resultado"].map(lambda x: _formatear_importe(x, con_signo=True))
    datos["TWR periodo"] = datos["twr"].map(lambda x: _formatear_porcentaje(x, con_signo=True))
    datos["Vol. anualizada"] = datos["volatilidad"].map(_formatear_porcentaje)
    datos["Max drawdown"] = datos["drawdown"].map(lambda x: _formatear_porcentaje(x, con_signo=True))

    columnas = [
        "Periodo",
        "Flujo neto EUR",
        "Valor final EUR",
        "Capital final EUR",
        "Resultado EUR",
        "TWR periodo",
        "Vol. anualizada",
        "Max drawdown",
    ]

    return crear_data_table(
        datos,
        columnas,
        min_width="130px",
        style_table={"height": "520px", "overflowY": "auto", "overflowX": "auto"},
        style_data_conditional=estilos_signo(["Flujo neto EUR", "Resultado EUR", "TWR periodo", "Max drawdown"]),
    )


layout = html.Div(
    children=[
        html.H2(
            "Hist\u00f3rico de cartera",
            style={"color": COLOR_TEXTO, "marginBottom": "5px"},
        ),
        html.P(
            "Evoluci\u00f3n mensual y anual de flujo neto, TWR, resultado y riesgo de la cartera en EUR.",
            style={"color": COLOR_MUTED, "marginBottom": "30px"},
        ),
        html.Div(
            style={**ESTILO_CAJA, "padding": "20px 24px"},
            children=[
                html.Div(
                    "Vista",
                    style={
                        "fontSize": "14px",
                        "fontWeight": "700",
                        "color": "#374151",
                        "marginBottom": "8px",
                    },
                ),
                dcc.RadioItems(
                    id="selector-historico-periodicidad",
                    options=[
                        {"label": "Mensual", "value": "mensual"},
                        {"label": "Anual", "value": "anual"},
                    ],
                    value="mensual",
                    inline=True,
                    labelStyle=ESTILO_BOTON,
                    inputStyle=ESTILO_INPUT_OCULTO,
                ),
            ],
        ),
        html.Div(
            style=ESTILO_CAJA,
            children=[
                dcc.Loading(
                    type="circle",
                    children=dcc.Graph(
                        id="grafico-historico",
                        config={"displayModeBar": True},
                    ),
                ),
            ],
        ),
        html.Div(
            style={**ESTILO_CAJA, "marginBottom": "0"},
            children=[
                html.H3(
                    "Detalle hist\u00f3rico",
                    style={"color": COLOR_TEXTO, "marginTop": "0", "marginBottom": "20px"},
                ),
                html.Div(id="tabla-historico"),
            ],
        ),
    ]
)


@callback(
    Output("grafico-historico", "figure"),
    Output("tabla-historico", "children"),
    Input("selector-historico-periodicidad", "value"),
)
def actualizar_historico(periodicidad):
    tabla = calcular_historico_periodos(periodicidad)
    return crear_grafico_historico(tabla, periodicidad), crear_tabla_historico(tabla)
