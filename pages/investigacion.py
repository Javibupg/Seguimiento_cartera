import dash
import pandas as pd
from dash import Input, Output, callback, dcc, html

from investigacion_utils import (
    DATO_NO_DISPONIBLE,
    calcular_flags_inversion,
    calcular_metricas_activo,
    calcular_metricas_macro,
    calcular_metricas_relativas,
    cargar_activos_investigacion,
    crear_grafico_precio,
    descargar_precios_investigacion,
    formatear_valor,
    obtener_activo,
    obtener_fundamentales,
    opciones_activos_investigacion,
)


dash.register_page(
    __name__,
    path="/investigacion",
    name="Investigación",
    title="Investigación de activos",
    order=3,
)


COLOR_TEXTO = "#111827"
COLOR_MUTED = "#6b7280"
COLOR_BORDE = "#e5e7eb"
VERDE = "#16a34a"
ROJO = "#dc2626"
PERIODOS_PRECIO = {
    "1m": {"label": "1M", "offset": pd.DateOffset(months=1)},
    "6m": {"label": "6M", "offset": pd.DateOffset(months=6)},
    "1y": {"label": "1A", "offset": pd.DateOffset(years=1)},
    "5y": {"label": "5A", "offset": pd.DateOffset(years=5)},
    "max": {"label": "Máx", "offset": None},
}
ESTILO_BOTON_PERIODO = {
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


DESCRIPCIONES_METRICAS = {
    "Activo": "Activo seleccionado en la hoja Listado de activos.",
    "Benchmark": "Índice o activo de referencia usado para calcular las métricas relativas.",
    "Última fecha": "Última fecha con precio disponible descargado desde Yahoo Finance.",
    "Precio actual": "Último precio de cierre disponible del activo.",
    "Precio vs MM50": "Diferencia porcentual entre el precio actual y la media móvil de 50 sesiones.",
    "Precio vs MM200": "Diferencia porcentual entre el precio actual y la media móvil de 200 sesiones.",
    "Distancia a max. 52s": "Caída o distancia del precio actual respecto al máximo de las últimas 52 semanas.",
    "Distancia a min. 52s": "Subida o distancia del precio actual respecto al mínimo de las últimas 52 semanas.",
    "Rentabilidad 1M": "Rentabilidad aproximada del activo en las últimas 21 sesiones.",
    "Rentabilidad 3M": "Rentabilidad aproximada del activo en las últimas 63 sesiones.",
    "Rentabilidad 6M": "Rentabilidad aproximada del activo en las últimas 126 sesiones.",
    "Rentabilidad YTD": "Rentabilidad desde el inicio del año natural hasta el último dato disponible.",
    "Rentabilidad 1A": "Rentabilidad aproximada del activo en las últimas 252 sesiones.",
    "Volatilidad 1A": "Volatilidad anualizada calculada con las rentabilidades diarias del último año.",
    "Max drawdown 1A": "Máxima caída desde un máximo local durante el último año.",
    "RSI 14": "Indicador técnico de 14 sesiones. Valores altos suelen indicar sobrecompra y bajos sobreventa.",
    "Exceso 1M": "Rentabilidad del activo menos la rentabilidad del benchmark en el último mes.",
    "Exceso 3M": "Rentabilidad del activo menos la rentabilidad del benchmark en los últimos tres meses.",
    "Exceso 6M": "Rentabilidad del activo menos la rentabilidad del benchmark en los últimos seis meses.",
    "Exceso 1A": "Rentabilidad del activo menos la rentabilidad del benchmark en el último año.",
    "Beta 1A": "Sensibilidad del activo frente al benchmark usando rentabilidades diarias del último año.",
    "Correlación 1A": "Relación estadística entre las rentabilidades diarias del activo y del benchmark en el último año.",
    "Fuerza relativa 6M": "Evolución del ratio activo/benchmark en los últimos seis meses.",
    "PER trailing": "Precio dividido entre el beneficio por acción de los últimos doce meses.",
    "PER forward": "Precio dividido entre el beneficio por acción estimado por el mercado.",
    "Price / Book": "Precio de mercado frente al valor contable de la empresa.",
    "EV / EBITDA": "Valor de empresa dividido entre EBITDA. Útil para comparar valoración entre compañías.",
    "Dividend yield": "Rentabilidad anualizada por dividendo: dividendo anual esperado dividido entre el precio actual.",
    "Margen neto": "Beneficio neto sobre ingresos.",
    "ROE": "Rentabilidad sobre fondos propios.",
    "Crecimiento ingresos": "Crecimiento reciente de ingresos reportado por Yahoo Finance.",
    "VIX": "Índice de volatilidad implícita del S&P 500. Suele subir cuando aumenta el miedo de mercado.",
    "Bono USA 10Y": "Rentabilidad del bono estadounidense a 10 años. Sirve como referencia de tipos largos.",
    "EUR/USD": "Tipo de cambio euro/dólar.",
    "Brent": "Precio del petróleo Brent, útil como indicador macro y para sectores energéticos.",
}


def ayuda_metrica(titulo):
    descripcion = DESCRIPCIONES_METRICAS.get(titulo)
    if not descripcion:
        return None

    return html.Span(
        "?",
        title=descripcion,
        style={
            "display": "inline-flex",
            "alignItems": "center",
            "justifyContent": "center",
            "width": "16px",
            "height": "16px",
            "borderRadius": "50%",
            "border": "1px solid #9ca3af",
            "color": COLOR_MUTED,
            "fontSize": "10px",
            "fontWeight": "800",
            "cursor": "help",
            "marginLeft": "6px",
        },
    )


def tarjeta_metrica(titulo, valor, tipo=None, detalle=None):
    color = COLOR_TEXTO
    ayuda = ayuda_metrica(titulo)

    if tipo == "porcentaje" and valor is not None:
        try:
            color = VERDE if float(valor) >= 0 else ROJO
        except Exception:
            color = COLOR_TEXTO

    return html.Div(
        style={
            "backgroundColor": "white",
            "border": f"1px solid {COLOR_BORDE}",
            "borderRadius": "14px",
            "padding": "16px",
            "minHeight": "100px",
            "boxShadow": "0 1px 3px rgba(15,23,42,0.06)",
        },
        children=[
            html.Div(
                [html.Span(titulo), ayuda] if ayuda else titulo,
                style={
                    "display": "flex",
                    "alignItems": "center",
                    "fontSize": "13px",
                    "fontWeight": "700",
                    "color": COLOR_MUTED,
                    "marginBottom": "8px",
                },
            ),
            html.Div(
                formatear_valor(valor, tipo),
                style={
                    "fontSize": "22px",
                    "fontWeight": "800",
                    "color": color,
                    "lineHeight": "1.15",
                },
            ),
            html.Div(
                detalle or "",
                style={
                    "fontSize": "12px",
                    "color": COLOR_MUTED,
                    "marginTop": "7px",
                    "minHeight": "16px",
                },
            ),
        ],
    )


def tarjeta_flag(flag):
    color = flag.get("color", COLOR_MUTED)
    puntuacion = flag.get("puntuacion")
    score = "Sin score" if puntuacion is None else f"Score {puntuacion:.1f}/2"

    return html.Div(
        style={
            "backgroundColor": "white",
            "border": f"1px solid {COLOR_BORDE}",
            "borderLeft": f"5px solid {color}",
            "borderRadius": "14px",
            "padding": "16px",
            "minHeight": "118px",
            "boxShadow": "0 1px 3px rgba(15,23,42,0.06)",
        },
        children=[
            html.Div(
                flag.get("titulo"),
                style={
                    "fontSize": "13px",
                    "fontWeight": "800",
                    "color": COLOR_MUTED,
                    "marginBottom": "8px",
                },
            ),
            html.Div(
                flag.get("estado"),
                style={
                    "fontSize": "20px",
                    "fontWeight": "850",
                    "color": color,
                    "lineHeight": "1.15",
                },
            ),
            html.Div(
                score,
                style={
                    "fontSize": "12px",
                    "fontWeight": "700",
                    "color": COLOR_MUTED,
                    "marginTop": "8px",
                },
            ),
            html.Div(
                flag.get("detalle") or "",
                style={
                    "fontSize": "12px",
                    "color": COLOR_MUTED,
                    "marginTop": "7px",
                    "lineHeight": "1.35",
                },
            ),
        ],
    )


def bloque_metricas(titulo, subtitulo, id_contenedor):
    return html.Div(
        style={
            "backgroundColor": "white",
            "padding": "24px",
            "borderRadius": "18px",
            "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
            "marginTop": "30px",
        },
        children=[
            html.H3(
                titulo,
                style={"color": COLOR_TEXTO, "marginBottom": "6px"},
            ),
            html.P(
                subtitulo,
                style={"color": COLOR_MUTED, "marginTop": "0", "marginBottom": "20px"},
            ),
            html.Div(
                id=id_contenedor,
                style={
                    "display": "grid",
                    "gridTemplateColumns": "repeat(auto-fit, minmax(180px, 1fr))",
                    "gap": "14px",
                },
            ),
        ],
    )


activos_investigacion = cargar_activos_investigacion()
opciones_activos = opciones_activos_investigacion(activos_investigacion)
activo_inicial = opciones_activos[0]["value"] if opciones_activos else None


layout = html.Div(
    children=[
        html.H2(
            "Investigación de activos",
            style={"color": COLOR_TEXTO, "marginBottom": "5px"},
        ),
        html.P(
            "Análisis de precio, métricas relativas, fundamentales y riesgo macro para los activos marcados en la hoja Listado de activos.",
            style={"color": COLOR_MUTED, "marginBottom": "30px"},
        ),

        html.Div(
            style={
                "backgroundColor": "white",
                "padding": "20px 24px",
                "borderRadius": "18px",
                "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
                "marginBottom": "30px",
            },
            children=[
                html.Div(
                    "Activo",
                    style={
                        "fontSize": "14px",
                        "fontWeight": "700",
                        "color": "#374151",
                        "marginBottom": "8px",
                    },
                ),
                dcc.Dropdown(
                    id="selector-activo-investigacion",
                    options=opciones_activos,
                    value=activo_inicial,
                    clearable=False,
                    placeholder="Selecciona un activo",
                    style={"maxWidth": "520px"},
                ),
            ],
        ),

        html.Div(id="aviso-investigacion", style={"color": "#b45309", "fontWeight": "700", "marginBottom": "18px"}),

        html.Div(
            id="cabecera-investigacion",
            style={
                "display": "grid",
                "gridTemplateColumns": "repeat(auto-fit, minmax(220px, 1fr))",
                "gap": "20px",
                "marginBottom": "30px",
            },
        ),

        html.Div(
            style={
                "backgroundColor": "white",
                "padding": "24px",
                "borderRadius": "18px",
                "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
            },
            children=[
                html.Div("Periodo", style={"fontSize": "14px", "fontWeight": "700", "color": "#374151", "marginBottom": "8px"}),
                dcc.RadioItems(
                    id="selector-periodo-investigacion",
                    options=[{"label": v["label"], "value": k} for k, v in PERIODOS_PRECIO.items()],
                    value="max",
                    inline=True,
                    labelStyle=ESTILO_BOTON_PERIODO,
                    inputStyle={"display": "none"},
                    style={"marginBottom": "20px"},
                ),
                dcc.Loading(
                    type="circle",
                    children=dcc.Graph(
                        id="grafico-precio-investigacion",
                        config={"displayModeBar": True, "scrollZoom": True},
                    ),
                ),
            ],
        ),

        bloque_metricas(
            "Señales de inversión",
            "Flags orientativos basados en valoración, tendencia, fuerza relativa y contexto macro. No son una recomendación automática.",
            "flags-inversion-investigacion",
        ),

        bloque_metricas(
            "Métricas del activo",
            "Precio frente a medias móviles, rentabilidades, volatilidad, drawdown y RSI.",
            "metricas-activo-investigacion",
        ),
        bloque_metricas(
            "Métricas relativas",
            "Comparación contra el benchmark indicado en el Excel.",
            "metricas-relativas-investigacion",
        ),
        bloque_metricas(
            "Métricas fundamentales",
            "Datos de valoración de Yahoo Finance. Si no están disponibles, se muestra dato no disponible.",
            "metricas-fundamentales-investigacion",
        ),
        bloque_metricas(
            "Riesgo macro",
            "Indicadores generales para contextualizar el momento de mercado.",
            "metricas-macro-investigacion",
        ),
    ],
)


def construir_tarjetas(metricas):
    return [
        tarjeta_metrica(
            metrica.get("titulo"),
            metrica.get("valor"),
            metrica.get("tipo"),
            metrica.get("detalle"),
        )
        for metrica in metricas
    ]


def construir_flags(flags):
    return [tarjeta_flag(flag) for flag in flags]


def filtrar_periodo(precios, periodo):
    offset = PERIODOS_PRECIO.get(periodo, PERIODOS_PRECIO["max"])["offset"]
    if precios.empty or offset is None:
        return precios
    fin = precios.index.max()
    filtrado = precios.loc[precios.index >= fin - offset]
    return filtrado if not filtrado.empty else precios.tail(1)


@callback(
    Output("aviso-investigacion", "children"),
    Output("cabecera-investigacion", "children"),
    Output("grafico-precio-investigacion", "figure"),
    Output("flags-inversion-investigacion", "children"),
    Output("metricas-activo-investigacion", "children"),
    Output("metricas-relativas-investigacion", "children"),
    Output("metricas-fundamentales-investigacion", "children"),
    Output("metricas-macro-investigacion", "children"),
    Input("selector-activo-investigacion", "value"),
    Input("selector-periodo-investigacion", "value"),
)
def actualizar_investigacion(ticker, periodo):
    if not ticker or activos_investigacion.empty:
        fig = crear_grafico_precio(
            descargar_precios_investigacion(""),
            "",
            "Sin activo",
        )
        fig.update_xaxes(rangeselector={"visible": False})
        aviso = "No hay activos marcados con Seguimiento = sí en la hoja Listado de activos."
        return aviso, [], fig, [], [], [], [], []

    activo = obtener_activo(activos_investigacion, ticker)
    ticker = activo["Ticker"]
    nombre = activo["Nombre"]
    benchmark = activo.get("Benchmark")

    precios = descargar_precios_investigacion(ticker)
    fig = crear_grafico_precio(filtrar_periodo(precios, periodo), ticker, nombre, precios)
    fig.update_xaxes(rangeselector={"visible": False})

    ultima_fecha = precios.index[-1].strftime("%d/%m/%Y") if not precios.empty else None

    cabecera = [
        tarjeta_metrica("Activo", f"{nombre} ({ticker})", "texto"),
        tarjeta_metrica("Benchmark", benchmark or DATO_NO_DISPONIBLE, "texto"),
        tarjeta_metrica("Última fecha", ultima_fecha, "texto"),
    ]

    metricas_activo = calcular_metricas_activo(precios)
    metricas_relativas = calcular_metricas_relativas(precios, benchmark)
    metricas_fundamentales = obtener_fundamentales(ticker)
    metricas_macro = calcular_metricas_macro()
    flags_inversion = calcular_flags_inversion(
        metricas_activo,
        metricas_relativas,
        metricas_fundamentales,
        metricas_macro,
    )

    return (
        "",
        cabecera,
        fig,
        construir_flags(flags_inversion),
        construir_tarjetas(metricas_activo),
        construir_tarjetas(metricas_relativas),
        construir_tarjetas(metricas_fundamentales),
        construir_tarjetas(metricas_macro),
    )
