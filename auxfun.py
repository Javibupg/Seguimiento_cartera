from dash import html, dash_table
import plotly.graph_objects as go
from plotly.subplots import make_subplots


def formatear_resultado_con_rentabilidad(importe, rentabilidad, simbolo):
    color = "#16a34a" if rentabilidad >= 0 else "#dc2626"
    signo = "+" if rentabilidad >= 0 else ""

    return [
        f"{simbolo}{importe:,.2f} ",
        html.Span(
            f"({signo}{rentabilidad * 100:.2f}%)",
            style={
                "color": color,
                "fontSize": "20px",
                "fontWeight": "700",
                "marginLeft": "6px"
            }
        )
    ]


def aplicar_layout_base(fig, titulo):
    fig.update_layout(
        title={
            "text": titulo,
            "x": 0.05,
            "xanchor": "left",
            "y": 0.99,
            "yanchor": "top"
        },
        template="plotly_white",
        height=650,
        margin=dict(l=40, r=40, t=100, b=40),
        hovermode="x unified",
        legend=dict(
            orientation="v",
            yanchor="top",
            y=0.98,
            xanchor="left",
            x=0.02,
            bgcolor="rgba(255,255,255,0.75)",
            bordercolor="rgba(0,0,0,0.10)",
            borderwidth=1
        )
    )

    return fig


def calcular_drawdown(rentabilidad):
    valor_relativo = 1 + rentabilidad
    maximo_acumulado = valor_relativo.cummax()
    return valor_relativo / maximo_acumulado - 1


def crear_grafico_drawdown_base(rentabilidad, capital_acumulado, simbolo, titulo, nombre_drawdown, nombre_capital, titulo_capital):
    drawdown = calcular_drawdown(rentabilidad)
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.06, specs=[[{"type": "scatter"}], [{"type": "scatter"}]])

    fig.add_trace(
        go.Scatter(
            x=drawdown.index,
            y=drawdown.values * 100,
            mode="lines",
            name=nombre_drawdown,
            line=dict(width=3, color="crimson"),
            fill="tozeroy",
            fillcolor="rgba(220, 20, 60, 0.15)",
            hovertemplate="Fecha: %{x}<br>" + f"{nombre_drawdown}: %{{y:.2f}}%" + "<extra></extra>"
        ),
        row=1,
        col=1
    )

    fig.add_trace(
        go.Scatter(
            x=capital_acumulado.index,
            y=capital_acumulado.values,
            mode="lines",
            name=nombre_capital,
            line=dict(width=2, shape="hv", color="green"),
            fill="tozeroy",
            fillcolor="rgba(0, 128, 0, 0.12)",
            hovertemplate="Fecha: %{x}<br>" + f"{nombre_capital}: {simbolo}%{{y:,.2f}}" + "<extra></extra>"
        ),
        row=2,
        col=1
    )

    aplicar_layout_base(fig, titulo)
    fig.update_yaxes(title_text="Drawdown", ticksuffix="%", row=1, col=1)
    fig.update_yaxes(title_text=titulo_capital, tickprefix=simbolo, separatethousands=True, row=2, col=1)
    fig.update_xaxes(title_text="Fecha", row=2, col=1)

    return fig


def titulo_tarjeta(titulo, tooltip=None):
    hijos = [html.Span(titulo)]
    if tooltip:
        hijos.append(
            html.Span(
                "?",
                title=tooltip,
                style={
                    "display": "inline-flex",
                    "alignItems": "center",
                    "justifyContent": "center",
                    "width": "17px",
                    "height": "17px",
                    "borderRadius": "50%",
                    "border": "1px solid #9ca3af",
                    "color": "#6b7280",
                    "fontSize": "11px",
                    "fontWeight": "700",
                    "cursor": "help",
                    "marginLeft": "6px"
                }
            )
        )
    return hijos


def crear_tarjeta(titulo, valor, id_titulo=None, id_valor=None, tooltip=None):
    return html.Div(
        style={
            "backgroundColor": "white",
            "padding": "24px",
            "borderRadius": "18px",
            "boxShadow": "0 4px 14px rgba(0,0,0,0.08)"
        },
        children=[
            html.Div(
                titulo_tarjeta(titulo, tooltip),
                id=id_titulo,
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "fontSize": "15px",
                    "color": "#6b7280",
                    "marginBottom": "10px"
                }
            ),
            html.Div(
                valor,
                id=id_valor,
                style={
                    "fontSize": "30px",
                    "fontWeight": "700",
                    "color": "#111827"
                }
            )
        ]
    )


def crear_grafico_cartera(rentabilidad, flujos, capital_acumulado):
    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.06,
        specs=[
            [{"type": "scatter"}],
            [{"type": "scatter"}]
        ]
    )

    # Gráfico superior: rentabilidad
    fig.add_trace(
        go.Scatter(
            x=rentabilidad.index,
            y=rentabilidad.values * 100,
            mode="lines",
            name="Rentabilidad cartera",
            line=dict(width=3),
            hovertemplate=(
                "Fecha: %{x}<br>"
                "Rentabilidad: %{y:.2f}%"
                "<extra></extra>"
            )
        ),
        row=1,
        col=1
    )

    # Gráfico inferior: capital acumulado sombreado
    fig.add_trace(
        go.Scatter(
            x=capital_acumulado.index,
            y=capital_acumulado.values,
            mode="lines",
            name="Capital invertido",
            line=dict(width=2, shape="hv", color="green"),
            fill="tozeroy",
            fillcolor="rgba(0, 128, 0, 0.12)",
            hovertemplate=(
                "Fecha: %{x}<br>"
                "Capital invertido: $%{y:,.2f}"
                "<extra></extra>"
            )
        ),
        row=2,
        col=1
    )

    aplicar_layout_base(fig, "Rentabilidad de la cartera y capital invertido")

    fig.update_yaxes(
        title_text="Rentabilidad sobre capital invertido",
        ticksuffix="%",
        row=1,
        col=1
    )

    fig.update_yaxes(
        title_text="Capital invertido USD",
        tickprefix="$",
        separatethousands=True,
        row=2,
        col=1
    )

    fig.update_xaxes(
        title_text="Fecha",
        row=2,
        col=1
    )

    return fig


def crear_grafico_drawdown(rentabilidad, flujos, capital_acumulado):
    return crear_grafico_drawdown_base(
        rentabilidad,
        capital_acumulado,
        "$",
        "Drawdown de la cartera y capital invertido",
        "Drawdown",
        "Capital invertido",
        "Capital invertido USD"
    )


def crear_grafico_desglose_eur(desglose_fx):
    if desglose_fx.empty:
        fig = go.Figure()
        fig.update_layout(
            title="No hay datos suficientes para calcular el desglose EUR/FX",
            template="plotly_white",
            height=600
        )
        return fig

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.75, 0.25],
        vertical_spacing=0.06,
        specs=[
            [{"type": "scatter"}],
            [{"type": "scatter"}]
        ]
    )

    fig.add_trace(
        go.Scatter(
            x=desglose_fx.index,
            y=desglose_fx["Rentabilidad_total_EUR"] * 100,
            mode="lines",
            name="Rentabilidad total EUR",
            line=dict(width=3),
            hovertemplate=(
                "Fecha: %{x}<br>"
                "Rentabilidad total EUR: %{y:.2f}%"
                "<extra></extra>"
            )
        ),
        row=1,
        col=1
    )

    fig.add_trace(
        go.Scatter(
            x=desglose_fx.index,
            y=desglose_fx["Rentabilidad_activos_EUR"] * 100,
            mode="lines",
            name="Efecto activos",
            line=dict(width=2),
            hovertemplate=(
                "Fecha: %{x}<br>"
                "Efecto activos: %{y:.2f}%"
                "<extra></extra>"
            )
        ),
        row=1,
        col=1
    )

    fig.add_trace(
        go.Scatter(
            x=desglose_fx.index,
            y=desglose_fx["Rentabilidad_FX_EUR"] * 100,
            mode="lines",
            name="Efecto FX",
            line=dict(width=2),
            hovertemplate=(
                "Fecha: %{x}<br>"
                "Efecto FX: %{y:.2f}%"
                "<extra></extra>"
            )
        ),
        row=1,
        col=1
    )

    fig.add_trace(
        go.Scatter(
            x=desglose_fx.index,
            y=desglose_fx["Capital_EUR"],
            mode="lines",
            name="Capital invertido EUR",
            line=dict(width=2, shape="hv", color="green"),
            fill="tozeroy",
            fillcolor="rgba(0, 128, 0, 0.12)",
            hovertemplate=(
                "Fecha: %{x}<br>"
                "Capital invertido: €%{y:,.2f}"
                "<extra></extra>"
            )
        ),
        row=2,
        col=1
    )

    aplicar_layout_base(fig, "Rentabilidad EUR: total, efecto activos y efecto FX")

    fig.update_yaxes(
        title_text="Rentabilidad sobre capital invertido",
        ticksuffix="%",
        row=1,
        col=1
    )

    fig.update_yaxes(
        title_text="Capital invertido EUR",
        tickprefix="€",
        separatethousands=True,
        row=2,
        col=1
    )

    fig.update_xaxes(
        title_text="Fecha",
        row=2,
        col=1
    )

    return fig


def crear_grafico_drawdown_eur(desglose_fx):
    if desglose_fx.empty:
        fig = go.Figure()
        fig.update_layout(title="No hay datos suficientes para calcular el drawdown EUR", template="plotly_white", height=600)
        return fig

    return crear_grafico_drawdown_base(
        desglose_fx["Rentabilidad_total_EUR"],
        desglose_fx["Capital_EUR"],
        "€",
        "Drawdown EUR y capital invertido",
        "Drawdown EUR",
        "Capital invertido EUR",
        "Capital invertido EUR"
    )


def crear_tabla_operaciones_cerradas(df):
    if df.empty:
        return html.Div("Todavía no hay operaciones cerradas.", style={"color": "#6b7280", "padding": "20px"})

    tabla = df.copy()

    tabla["Capital_invertido"] = tabla["Capital_invertido"].map(lambda x: f"${x:,.2f}")

    for col in ["Rentabilidad", "Rent. anualizada"]:
        tabla[col] = tabla[col].map(lambda x: f"{x * 100:.2f}%")

    tabla = tabla.rename(columns={"Capital_invertido": "Capital invertido"})

    columnas = ["Activo", "Periodo", "Rentabilidad", "Rent. anualizada", "Capital invertido"]

    return dash_table.DataTable(
        data=tabla[columnas].to_dict("records"),
        columns=[{"name": col, "id": col} for col in columnas],
        page_action="none",
        fixed_rows={"headers": True},
        style_table={"height": "300px", "overflowY": "auto", "overflowX": "auto"},
        style_cell={
            "fontFamily": "Arial, sans-serif", "fontSize": "14px",
            "padding": "10px", "textAlign": "center",
            "minWidth": "120px", "whiteSpace": "normal"
        },
        style_header={"backgroundColor": "#f3f4f6", "fontWeight": "700", "color": "#111827"},
        style_data={"backgroundColor": "white", "color": "#111827"}
    )

