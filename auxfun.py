from dash import html, dash_table
import plotly.graph_objects as go
from plotly.subplots import make_subplots

VERDE, ROJO = "#16a34a", "#dc2626"


def formatear_resultado_con_rentabilidad(importe, rentabilidad, simbolo):
    color, signo = (VERDE, "+") if rentabilidad >= 0 else (ROJO, "")
    return [f"{simbolo}{importe:,.2f} ", html.Span(f"({signo}{rentabilidad * 100:.2f}%)", style={"color": color, "fontSize": "20px", "fontWeight": "700", "marginLeft": "6px"})]


def titulo_tarjeta(titulo, tooltip=None):
    hijos = [html.Span(titulo)]
    if tooltip:
        hijos.append(html.Span("?", title=tooltip, style={"display": "inline-flex", "alignItems": "center", "justifyContent": "center", "width": "17px", "height": "17px", "borderRadius": "50%", "border": "1px solid #9ca3af", "color": "#6b7280", "fontSize": "11px", "fontWeight": "700", "cursor": "help", "marginLeft": "6px"}))
    return hijos


def crear_tarjeta(titulo, valor, id_titulo=None, id_valor=None, tooltip=None):
    props_titulo = {
        "children": titulo_tarjeta(titulo, tooltip),
        "style": {
            "display": "flex",
            "alignItems": "center",
            "fontSize": "15px",
            "color": "#6b7280",
            "marginBottom": "10px",
        },
    }

    if id_titulo is not None:
        props_titulo["id"] = id_titulo

    props_valor = {
        "children": valor,
        "style": {
            "fontSize": "30px",
            "fontWeight": "700",
            "color": "#111827",
        },
    }

    if id_valor is not None:
        props_valor["id"] = id_valor

    return html.Div(
        style={
            "backgroundColor": "white",
            "padding": "24px",
            "borderRadius": "18px",
            "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
        },
        children=[
            html.Div(**props_titulo),
            html.Div(**props_valor),
        ],
    )


def aplicar_layout_base(fig, titulo):
    fig.update_layout(title={"text": titulo, "x": 0.05, "xanchor": "left", "y": 0.99, "yanchor": "top"}, template="plotly_white", height=650, margin=dict(l=40, r=40, t=100, b=40), hovermode="x unified", legend=dict(orientation="v", yanchor="top", y=0.98, xanchor="left", x=0.02, bgcolor="rgba(255,255,255,0.75)", bordercolor="rgba(0,0,0,0.10)", borderwidth=1))
    return fig


def crear_figura_dos_paneles(titulo):
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.75, 0.25], vertical_spacing=0.06, specs=[[{"type": "scatter"}], [{"type": "scatter"}]])
    return aplicar_layout_base(fig, titulo)


def _add_capital(fig, capital, simbolo, nombre, titulo_y):
    fig.add_trace(go.Scatter(x=capital.index, y=capital.values, mode="lines", name=nombre, line=dict(width=2, shape="hv", color="green"), fill="tozeroy", fillcolor="rgba(0,128,0,0.12)", hovertemplate="Fecha: %{x}<br>" + f"{nombre}: {simbolo}%{{y:,.2f}}<extra></extra>"), row=2, col=1)
    fig.update_yaxes(title_text=titulo_y, tickprefix=simbolo, separatethousands=True, row=2, col=1)
    fig.update_xaxes(title_text="Fecha", row=2, col=1)


def calcular_drawdown(twr):
    base = 1 + twr
    return base / base.cummax() - 1


def crear_grafico_twr(twr, capital, simbolo="$", titulo="Rentabilidad TWR de la cartera", nombre="Rentabilidad TWR", titulo_capital="Capital invertido"):
    fig = crear_figura_dos_paneles(titulo)
    fig.add_trace(go.Scatter(x=twr.index, y=twr.values * 100, mode="lines", name=nombre, line=dict(width=3), hovertemplate="Fecha: %{x}<br>Rentabilidad TWR: %{y:.2f}%<extra></extra>"), row=1, col=1)
    _add_capital(fig, capital, simbolo, titulo_capital, titulo_capital)
    fig.update_yaxes(title_text="Rentabilidad TWR", ticksuffix="%", row=1, col=1)
    return fig


def crear_grafico_drawdown(twr, capital, simbolo="$", titulo="Drawdown TWR de la cartera", nombre="Drawdown", titulo_capital="Capital invertido"):
    dd = calcular_drawdown(twr)
    fig = crear_figura_dos_paneles(titulo)
    fig.add_trace(go.Scatter(x=dd.index, y=dd.values * 100, mode="lines", name=nombre, line=dict(width=3, color="crimson"), fill="tozeroy", fillcolor="rgba(220,20,60,0.15)", hovertemplate="Fecha: %{x}<br>Drawdown: %{y:.2f}%<extra></extra>"), row=1, col=1)
    _add_capital(fig, capital, simbolo, titulo_capital, titulo_capital)
    fig.update_yaxes(title_text="Drawdown", ticksuffix="%", row=1, col=1)
    return fig


def crear_grafico_desglose_eur(datos):
    if datos.empty:
        fig = go.Figure()
        fig.update_layout(title="No hay datos suficientes para calcular el desglose EUR/FX", template="plotly_white", height=600)
        return fig

    fig = crear_figura_dos_paneles("Rentabilidad TWR EUR: total, activos y FX")
    series = [("TWR_total_EUR", "Rentabilidad total EUR", 3), ("TWR_activos_USD", "Efecto activos", 2), ("TWR_FX_EUR", "Efecto FX", 2)]
    for col, nombre, ancho in series:
        fig.add_trace(go.Scatter(x=datos.index, y=datos[col] * 100, mode="lines", name=nombre, line=dict(width=ancho), hovertemplate="Fecha: %{x}<br>" + f"{nombre}: %{{y:.2f}}%<extra></extra>"), row=1, col=1)
    _add_capital(fig, datos["Capital_EUR"], "€", "Capital invertido EUR", "Capital invertido EUR")
    fig.update_yaxes(title_text="Rentabilidad TWR", ticksuffix="%", row=1, col=1)
    return fig


def crear_grafico_drawdown_eur(datos):
    if datos.empty:
        fig = go.Figure()
        fig.update_layout(title="No hay datos suficientes para calcular el drawdown EUR", template="plotly_white", height=600)
        return fig
    return crear_grafico_drawdown(datos["TWR_total_EUR"], datos["Capital_EUR"], "€", "Drawdown TWR EUR y capital invertido", "Drawdown EUR", "Capital invertido EUR")


def crear_tabla_operaciones_cerradas(df):
    if df.empty:
        return html.Div("Todavía no hay operaciones cerradas.", style={"color": "#6b7280", "padding": "20px"})
    tabla = df.copy()
    tabla["Capital_invertido"] = tabla["Capital_invertido"].map(lambda x: f"${x:,.2f}")
    for col in ["Rentabilidad", "Rent. anualizada"]:
        tabla[col] = tabla[col].map(lambda x: f"{x * 100:.2f}%")
    tabla = tabla.rename(columns={"Capital_invertido": "Capital invertido"})
    columnas = ["Activo", "Periodo", "Rentabilidad", "Rent. anualizada", "Capital invertido"]
    return dash_table.DataTable(data=tabla[columnas].to_dict("records"), columns=[{"name": c, "id": c} for c in columnas], page_action="none", fixed_rows={"headers": True}, style_table={"height": "300px", "overflowY": "auto", "overflowX": "auto"}, style_cell={"fontFamily": "Arial, sans-serif", "fontSize": "14px", "padding": "10px", "textAlign": "center", "minWidth": "120px", "whiteSpace": "normal"}, style_header={"backgroundColor": "#f3f4f6", "fontWeight": "700", "color": "#111827"}, style_data={"backgroundColor": "white", "color": "#111827"})
