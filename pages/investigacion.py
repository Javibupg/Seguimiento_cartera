import math

import dash
import pandas as pd
from dash import Input, Output, callback, dcc, html

from investigacion_utils import (
    DATO_NO_DISPONIBLE,
    analizar_empresa,
    calcular_contexto_precio,
    cargar_activos_investigacion,
    crear_grafico_precio,
    descargar_precios_investigacion,
    obtener_activo,
    opciones_activos_investigacion,
)


dash.register_page(
    __name__,
    path="/investigacion",
    name="Investigación",
    title="Investigación value",
    order=3,
)


COLOR_TEXTO = "#0f172a"
COLOR_MUTED = "#64748b"
COLOR_NEUTRO = "#64748b"
PERIODOS_PRECIO = {
    "6m": {"label": "6M", "offset": pd.DateOffset(months=6)},
    "1y": {"label": "1A", "offset": pd.DateOffset(years=1)},
    "3y": {"label": "3A", "offset": pd.DateOffset(years=3)},
    "5y": {"label": "5A", "offset": None},
}

TIPOS_ACTIVO = {
    "EQUITY": "Acción",
    "ETF": "ETF",
    "MUTUALFUND": "Fondo",
    "INDEX": "Índice",
    "CRYPTOCURRENCY": "Criptoactivo",
    "UNKNOWN": "Sin clasificar",
}


def _es_numero(valor):
    if valor is None or isinstance(valor, bool):
        return False
    try:
        return math.isfinite(float(valor))
    except (TypeError, ValueError):
        return False


def _numero_es(valor, decimales=2):
    if not _es_numero(valor):
        return DATO_NO_DISPONIBLE
    texto = f"{float(valor):,.{decimales}f}"
    return texto.replace(",", "#").replace(".", ",").replace("#", ".")


def _porcentaje(valor, decimales=1, con_signo=False):
    if not _es_numero(valor):
        return DATO_NO_DISPONIBLE
    numero = float(valor) * 100
    prefijo = "+" if con_signo and numero > 0 else ""
    return f"{prefijo}{_numero_es(numero, decimales)}%"


def _compacto(valor, moneda=None):
    if not _es_numero(valor):
        return DATO_NO_DISPONIBLE

    valor = float(valor)
    absoluto = abs(valor)
    if absoluto >= 1_000_000_000:
        texto = f"{_numero_es(valor / 1_000_000_000, 2)} mil M"
    elif absoluto >= 1_000_000:
        texto = f"{_numero_es(valor / 1_000_000, 1)} M"
    elif absoluto >= 1_000:
        texto = f"{_numero_es(valor / 1_000, 1)} mil"
    else:
        texto = _numero_es(valor, 0)
    return f"{texto} {moneda}" if moneda else texto


def _precio(valor, moneda=None):
    if not _es_numero(valor):
        return DATO_NO_DISPONIBLE
    texto = _numero_es(valor, 2)
    return f"{texto} {moneda}" if moneda else texto


def _formatear_metrica(metrica, moneda=None):
    if metrica.get("valor_formateado"):
        return metrica["valor_formateado"]

    valor = metrica.get("valor")
    tipo = metrica.get("tipo")
    moneda_metrica = metrica.get("moneda") or moneda
    if tipo in {"porcentaje", "percent"}:
        return _porcentaje(valor, metrica.get("decimales", 1))
    if tipo in {"multiple", "ratio", "veces"}:
        return f"{_numero_es(valor, metrica.get('decimales', 1))}x" if _es_numero(valor) else DATO_NO_DISPONIBLE
    if tipo in {"moneda", "moneda_compacta", "importe"}:
        return _compacto(valor, moneda_metrica)
    if tipo in {"precio", "moneda_por_accion"}:
        return _precio(valor, moneda_metrica)
    if tipo in {"entero", "integer"}:
        return _numero_es(valor, 0)
    if tipo == "puntos_porcentuales":
        return f"{_porcentaje(valor, metrica.get('decimales', 1), True).replace('%', '')} pp"
    if tipo == "piotroski":
        return f"{_numero_es(valor, 0)} pts" if _es_numero(valor) else DATO_NO_DISPONIBLE
    if tipo == "fraccion":
        return _numero_es(valor, 0)
    if tipo == "texto":
        return str(valor) if valor not in (None, "") else DATO_NO_DISPONIBLE
    if _es_numero(valor):
        return _numero_es(valor, metrica.get("decimales", 2))
    return DATO_NO_DISPONIBLE


def _texto_fecha(valor):
    if valor in (None, ""):
        return DATO_NO_DISPONIBLE
    try:
        fecha = pd.to_datetime(valor, utc=True)
        return fecha.strftime("%d/%m/%Y")
    except Exception:
        return str(valor)


def _ayuda(texto):
    if not texto:
        return None
    return html.Span("?", title=texto, className="research-help", tabIndex="0")


def tarjeta_metrica(metrica, moneda=None):
    estado = {
        "riesgo": "adverse",
        "sin_datos": "sin-dato",
        "referencia": "reference",
    }.get(metrica.get("estado"), metrica.get("estado") or "sin-dato")
    titulo = metrica.get("titulo") or metrica.get("nombre") or "Métrica"
    descripcion = metrica.get("descripcion")
    detalle = metrica.get("detalle") or ""
    return html.Div(
        className=f"research-metric-card {estado}",
        children=[
            html.Div(
                [html.Span(titulo), _ayuda(descripcion)] if descripcion else titulo,
                className="research-metric-title",
            ),
            html.Div(_formatear_metrica(metrica, moneda), className="research-metric-value"),
            html.Div(detalle, className="research-metric-detail"),
        ],
    )


def construir_metricas(metricas, moneda=None):
    if not metricas:
        return html.Div(
            "No hay datos suficientes para calcular este bloque.",
            className="research-empty",
        )
    return [tarjeta_metrica(metrica, moneda) for metrica in metricas]


def _seccion(titulo, introduccion, identificador, contenido_id, etiqueta=None):
    return html.Section(
        id=identificador,
        className="research-section research-surface",
        children=[
            html.Div(
                className="research-section-header",
                children=[
                    html.Div([html.H3(titulo), html.P(introduccion, className="research-section-intro")]),
                    html.Span(etiqueta, className="research-section-tag") if etiqueta else None,
                ],
            ),
            html.Div(id=contenido_id, className="research-metric-grid"),
        ],
    )


activos_investigacion = cargar_activos_investigacion()
opciones_activos = opciones_activos_investigacion(activos_investigacion)
activo_inicial = opciones_activos[0]["value"] if opciones_activos else None


layout = html.Div(
    className="research-page",
    children=[
        html.H2("Investigación · Value Lab", style={"color": COLOR_TEXTO, "marginBottom": "5px"}),
        html.P(
            "Una ficha de underwriting para responder tres preguntas: cuánto pagas, cuánto debe y cuánto efectivo genera.",
            style={"color": COLOR_MUTED, "marginTop": "0", "marginBottom": "0"},
        ),
        html.Div(
            className="research-selector research-surface",
            children=[
                html.Div(
                    className="research-selector-row",
                    children=[
                        html.Div(
                            [
                                html.Label("Empresa en seguimiento", className="research-label"),
                                dcc.Dropdown(
                                    id="selector-activo-investigacion",
                                    options=opciones_activos,
                                    value=activo_inicial,
                                    clearable=False,
                                    placeholder="Selecciona un activo",
                                ),
                            ]
                        ),
                        html.P(
                            "Los activos salen de “Listado de activos”. El score solo se aplica a empresas; ETF, fondos e índices mantienen el contexto de precio y noticias.",
                            className="research-selector-note",
                        ),
                    ],
                )
            ],
        ),
        html.Div(id="aviso-investigacion"),
        dcc.Store(id="store-valor-razonable-investigacion"),
        dcc.Loading(
            type="circle",
            color="#2563eb",
            children=html.Div(
                [
                    html.Div(id="cabecera-investigacion", className="research-company-header research-surface"),
                    html.Nav(
                        className="research-anchor-nav",
                        children=[
                            html.A("Tesis", href="#tesis-investigacion"),
                            html.A("Valoración", href="#valoracion-investigacion"),
                            html.A("Balance", href="#solvencia-investigacion"),
                            html.A("Calidad", href="#calidad-investigacion"),
                            html.A("Histórico", href="#historico-seccion-investigacion"),
                            html.A("Precio", href="#precio-investigacion"),
                            html.A("Noticias", href="#noticias-seccion-investigacion"),
                        ],
                    ),
                    html.Section(
                        id="tesis-investigacion",
                        className="research-decision research-surface",
                        children=html.Div(id="resumen-investigacion"),
                    ),
                    _seccion(
                        "Valoración y margen de seguridad",
                        "Caja y beneficio normalizados frente al precio pagado. El DCF es un rango orientativo, no una cifra exacta.",
                        "valoracion-investigacion",
                        "metricas-valoracion-investigacion",
                        "Peso 40%",
                    ),
                    html.Section(
                        id="dcf-seccion-investigacion",
                        className="research-section research-surface",
                        children=[
                            html.Div(
                                className="research-section-header",
                                children=[
                                    html.Div(
                                        [
                                            html.H3("Rango de valor razonable"),
                                            html.P(
                                                "Tres escenarios de flujo de caja libre para evitar depender de un único supuesto.",
                                                className="research-section-intro",
                                            ),
                                        ]
                                    ),
                                    html.Span("DCF conservador", className="research-section-tag"),
                                ],
                            ),
                            html.Div(id="dcf-investigacion"),
                        ],
                    ),
                    _seccion(
                        "Balance y deuda",
                        "Capacidad real de atender la deuda con EBITDA, EBIT y flujo de caja; no solo el importe absoluto.",
                        "solvencia-investigacion",
                        "metricas-solvencia-investigacion",
                        "Peso 25%",
                    ),
                    _seccion(
                        "Calidad y generación de caja",
                        "Retorno sobre el capital, conversión del beneficio a caja y consistencia de los estados financieros.",
                        "calidad-investigacion",
                        "metricas-calidad-investigacion",
                        "Peso 25%",
                    ),
                    _seccion(
                        "Crecimiento y asignación de capital",
                        "Busca evitar trampas de valor: deterioro del negocio, dilución o caída estructural de márgenes.",
                        "crecimiento-investigacion",
                        "metricas-crecimiento-investigacion",
                        "Peso 10%",
                    ),
                    html.Section(
                        id="historico-seccion-investigacion",
                        className="research-section research-surface",
                        children=[
                            html.Div(
                                className="research-section-header",
                                children=[
                                    html.Div(
                                        [
                                            html.H3("Histórico fundamental"),
                                            html.P(
                                                "Cuatro ejercicios comparables para detectar normalización, ciclicidad y deterioro.",
                                                className="research-section-intro",
                                            ),
                                        ]
                                    ),
                                    html.Span("Datos realizados", className="research-section-tag"),
                                ],
                            ),
                            html.Div(id="historico-investigacion"),
                        ],
                    ),
                    html.Section(
                        id="precio-investigacion",
                        className="research-section research-surface",
                        children=[
                            html.Div(
                                className="research-section-header",
                                children=[
                                    html.Div(
                                        [
                                            html.H3("Precio y contexto de entrada"),
                                            html.P(
                                                "El momentum se muestra como contexto, pero no altera el Value Score.",
                                                className="research-section-intro",
                                            ),
                                        ]
                                    ),
                                    html.Span("Fuera del score", className="research-section-tag"),
                                ],
                            ),
                            html.Div(
                                className="research-chart-controls",
                                children=[
                                    html.Span("Periodo", className="research-label", style={"marginBottom": "4px"}),
                                    dcc.RadioItems(
                                        id="selector-periodo-investigacion",
                                        options=[{"label": valor["label"], "value": clave} for clave, valor in PERIODOS_PRECIO.items()],
                                        value="5y",
                                        inline=True,
                                        inputStyle={"display": "none"},
                                    ),
                                ],
                            ),
                            dcc.Loading(
                                type="circle",
                                color="#2563eb",
                                children=dcc.Graph(
                                    id="grafico-precio-investigacion",
                                    config={"displayModeBar": True, "scrollZoom": False, "responsive": True},
                                ),
                            ),
                            html.Div(id="contexto-precio-investigacion", className="research-metric-grid"),
                        ],
                    ),
                    html.Section(
                        id="noticias-seccion-investigacion",
                        className="research-section research-surface",
                        children=[
                            html.Div(
                                className="research-section-header",
                                children=[
                                    html.Div(
                                        [
                                            html.H3("Noticias recientes"),
                                            html.P(
                                                "Titulares gratuitos relacionados con la empresa. Sirven para localizar catalizadores y riesgos; no entran en el score.",
                                                className="research-section-intro",
                                            ),
                                        ]
                                    ),
                                    html.Span("Yahoo Finance", className="research-section-tag"),
                                ],
                            ),
                            html.Div(id="noticias-investigacion"),
                        ],
                    ),
                    html.Div(id="fuente-investigacion", className="research-footer"),
                ]
            ),
        ),
    ],
)


def filtrar_periodo(precios, periodo):
    configuracion = PERIODOS_PRECIO.get(periodo, PERIODOS_PRECIO["5y"])
    offset = configuracion["offset"]
    if precios.empty or offset is None:
        return precios
    fin = precios.index.max()
    filtrado = precios.loc[precios.index >= fin - offset]
    return filtrado if not filtrado.empty else precios.tail(1)


def _clave(diccionario, *nombres, defecto=None):
    if not isinstance(diccionario, dict):
        return defecto
    for nombre in nombres:
        valor = diccionario.get(nombre)
        if valor is not None:
            return valor
    return defecto


def construir_cabecera(analisis, activo, precios):
    empresa = analisis.get("empresa") or {}
    ticker = activo.get("Ticker") or empresa.get("ticker") or ""
    nombre = _clave(empresa, "nombre", "long_name", defecto=activo.get("Nombre") or ticker)
    moneda = _clave(empresa, "moneda", "currency")
    precio = _clave(empresa, "precio", "current_price")
    if not _es_numero(precio) and not precios.empty:
        precio = float(precios.iloc[-1])
    capitalizacion = _clave(empresa, "capitalizacion", "market_cap")
    tipo = str(_clave(empresa, "tipo", "quote_type", defecto="")).upper()
    sector = _clave(empresa, "sector") or "Sector no disponible"
    industria = _clave(empresa, "industria", "industry")
    fecha_estados = _clave(empresa, "fecha_estados", "report_date")
    fecha_precio = precios.index[-1] if not precios.empty else None

    descripcion = " · ".join(valor for valor in [sector, industria] if valor)
    return [
        html.Div(
            [
                html.Div(
                    className="research-badges",
                    children=[
                        html.Span(ticker, className="research-badge"),
                        html.Span(TIPOS_ACTIVO.get(tipo, tipo.title() or "Activo"), className="research-badge neutral"),
                        html.Span(moneda, className="research-badge neutral") if moneda else None,
                    ],
                ),
                html.H2(nombre, className="research-company-title"),
                html.P(descripcion, className="research-company-subtitle"),
            ]
        ),
        html.Div(
            className="research-company-stats",
            children=[
                html.Div([html.Span("Último precio"), html.Strong(_precio(precio, moneda))], className="research-company-stat"),
                html.Div([html.Span("Capitalización"), html.Strong(_compacto(capitalizacion, moneda))], className="research-company-stat"),
                html.Div(
                    [html.Span("Datos"), html.Strong(_texto_fecha(fecha_estados or fecha_precio))],
                    className="research-company-stat",
                ),
            ],
        ),
    ]


def _lista_tesis(titulo, elementos, clase):
    elementos = [str(elemento) for elemento in (elementos or []) if elemento]
    if not elementos:
        elementos = ["Sin señales concluyentes con los datos disponibles."]
    return html.Div(
        className=f"research-thesis-box {clase}",
        children=[
            html.P(titulo, className="research-thesis-title"),
            html.Ul([html.Li(elemento) for elemento in elementos[:4]]),
        ],
    )


def _pilar(pilar):
    valor = _clave(pilar, "valor", "score")
    cobertura = _clave(pilar, "cobertura", "coverage", defecto=0)
    peso = _clave(pilar, "peso", "weight")
    nombre = _clave(pilar, "nombre", "titulo", defecto=str(pilar.get("clave", "Pilar")).title())
    ancho = max(0, min(100, float(valor))) if _es_numero(valor) else 0
    if not _es_numero(valor):
        color_pilar = COLOR_NEUTRO
    elif float(valor) >= 70:
        color_pilar = "#15803d"
    elif float(valor) >= 40:
        color_pilar = "#d97706"
    else:
        color_pilar = "#dc2626"
    meta = f"Cobertura {_porcentaje(cobertura, 0)}"
    if _es_numero(peso):
        meta += f" · Peso {_porcentaje(peso, 0)}"
    return html.Div(
        className="research-pillar",
        children=[
            html.Div(
                className="research-pillar-top",
                children=[
                    html.Span(nombre, className="research-pillar-name"),
                    html.Span(f"{_numero_es(valor, 0)}/100" if _es_numero(valor) else "N/D", className="research-pillar-score"),
                ],
            ),
            html.Div(html.Span(style={"width": f"{ancho}%", "backgroundColor": color_pilar}), className="research-progress"),
            html.Div(meta, className="research-pillar-meta"),
        ],
    )


def construir_resumen(analisis):
    score = analisis.get("score") or {}
    valor = _clave(score, "valor", "score")
    cobertura = _clave(score, "cobertura", "coverage", defecto=0)
    veredicto = _clave(score, "veredicto", "verdict", defecto="Sin conclusión fiable")
    confianza = _clave(score, "confianza", "confidence", defecto="Baja")
    color = _clave(score, "color", defecto=COLOR_NEUTRO)
    pilares = score.get("pilares") or analisis.get("pilares") or []
    fortalezas = analisis.get("fortalezas") or []
    riesgos = analisis.get("riesgos") or []
    bloqueos = analisis.get("bloqueos") or []

    avance = max(0, min(100, float(valor))) if _es_numero(valor) else 0
    fondo_ring = f"conic-gradient({color} 0 {avance}%, #e2e8f0 {avance}% 100%)"
    return html.Div(
        [
            html.Div(
                className="research-decision-grid",
                children=[
                    html.Div(
                        className="research-score-column",
                        children=[
                            html.Div(
                                className="research-score-ring",
                                style={"background": fondo_ring},
                                children=html.Div(
                                    className="research-score-inner",
                                    children=[
                                        html.Span(_numero_es(valor, 0) if _es_numero(valor) else "N/D", className="research-score-value"),
                                        html.Span("Value Score", className="research-score-denominator"),
                                    ],
                                ),
                            ),
                            html.P(veredicto, className="research-verdict", style={"color": color}),
                            html.P(
                                f"Confianza {str(confianza).lower()} · cobertura {_porcentaje(cobertura, 0)}",
                                className="research-confidence",
                            ),
                        ],
                    ),
                    html.Div(
                        [
                            html.Div([_pilar(pilar) for pilar in pilares], className="research-pillar-grid")
                            if pilares
                            else html.Div("No hay pilares calculables.", className="research-empty"),
                            html.Div(
                                className="research-thesis-grid",
                                children=[
                                    _lista_tesis("A favor", fortalezas, "strengths"),
                                    _lista_tesis("Riesgos a revisar", riesgos, "risks"),
                                ],
                            ),
                        ]
                    ),
                ],
            ),
            html.Div(
                [html.Strong("Bloqueos del veredicto: "), " · ".join(map(str, bloqueos))],
                className="research-blocker",
            )
            if bloqueos
            else None,
            html.P(
                "El score ordena la investigación; no sustituye revisar el negocio, las cuentas ni el precio que exige tu rentabilidad objetivo.",
                className="research-note",
            ),
        ]
    )


def construir_historico(historico, moneda):
    if not historico:
        return html.Div("Yahoo Finance no ofrece una serie anual suficiente para este activo.", className="research-empty")

    columnas = [
        ("Ejercicio", ("ejercicio", "periodo", "year"), "texto"),
        ("Ingresos", ("ingresos", "revenue"), "moneda"),
        ("EBIT", ("ebit",), "moneda"),
        ("FCF", ("fcf", "free_cash_flow"), "moneda"),
        ("Bº neto", ("beneficio_neto", "net_income"), "moneda"),
        ("Deuda neta", ("deuda_neta", "net_debt"), "moneda"),
        ("Margen FCF", ("margen_fcf", "fcf_margin"), "porcentaje"),
    ]

    filas = []
    for registro in historico[:4]:
        celdas = []
        for _, claves, tipo in columnas:
            valor = _clave(registro, *claves)
            if tipo == "moneda":
                texto = _compacto(valor, moneda)
            elif tipo == "porcentaje":
                texto = _porcentaje(valor, 1)
            else:
                texto = str(valor) if valor is not None else DATO_NO_DISPONIBLE
            celdas.append(html.Td(texto))
        filas.append(html.Tr(celdas))

    return html.Div(
        className="research-table-wrap",
        children=html.Table(
            className="research-table",
            children=[html.Thead(html.Tr([html.Th(nombre) for nombre, _, _ in columnas])), html.Tbody(filas)],
        ),
    )


def construir_dcf(dcf, moneda):
    if not dcf or not dcf.get("disponible"):
        motivo = _clave(dcf or {}, "motivo", "reason", defecto="No hay flujo de caja, acciones o moneda comparables suficientes.")
        return html.Div(motivo, className="research-empty")

    escenarios = dcf.get("escenarios") or []
    tarjetas = []
    for escenario in escenarios:
        margen = _clave(escenario, "margen", "margin")
        color = _clave(escenario, "color", defecto=COLOR_NEUTRO)
        tarjetas.append(
            html.Div(
                className="research-dcf-card",
                children=[
                    html.Div(_clave(escenario, "nombre", "name", defecto="Escenario"), className="research-dcf-name"),
                    html.Div(_precio(_clave(escenario, "valor", "value"), moneda), className="research-dcf-value"),
                    html.Div(
                        f"{_porcentaje(margen, 1, True)} vs precio" if _es_numero(margen) else "Margen N/D",
                        className="research-dcf-margin",
                        style={"color": color},
                    ),
                ],
            )
        )

    supuestos = dcf.get("supuestos") or dcf.get("assumptions")
    if isinstance(supuestos, dict):
        moneda_dcf = supuestos.get("moneda") or moneda
        partes = []
        if _es_numero(supuestos.get("fcff_normalizado")):
            partes.append(f"FCFF normalizado: {_compacto(supuestos['fcff_normalizado'], moneda_dcf)}")
        if _es_numero(supuestos.get("deuda_neta")):
            partes.append(f"Deuda neta: {_compacto(supuestos['deuda_neta'], moneda_dcf)}")
        for clave, etiqueta in (("horizonte", "Horizonte"), ("metodo", "Método"), ("nota", "Nota")):
            if supuestos.get(clave):
                partes.append(f"{etiqueta}: {supuestos[clave]}")
        supuestos = " · ".join(partes)
    elif isinstance(supuestos, (list, tuple)):
        supuestos = " · ".join(map(str, supuestos))
    return html.Div(
        [
            html.Div(tarjetas, className="research-dcf-grid"),
            html.P(supuestos, className="research-note") if supuestos else None,
        ]
    )


def _texto_noticia_fecha(valor):
    if not valor:
        return "Fecha no disponible"
    try:
        fecha = pd.to_datetime(valor, utc=True)
        return fecha.strftime("%d/%m/%Y · %H:%M")
    except Exception:
        return str(valor)


def construir_noticias(noticias):
    if not noticias:
        return html.Div(
            "No hay titulares disponibles ahora mismo. El resto del análisis sigue siendo válido.",
            className="research-empty",
        )

    articulos = []
    for noticia in noticias[:6]:
        titulo = _clave(noticia, "titulo", "title", defecto="Noticia")
        url = _clave(noticia, "url", "link")
        fuente = _clave(noticia, "fuente", "publisher", "provider", defecto="Yahoo Finance")
        fecha = _clave(noticia, "fecha", "published_at", "pubDate")
        resumen = _clave(noticia, "resumen", "summary", "description")
        enlace = html.A(titulo, href=url, target="_blank", rel="noopener noreferrer") if url else html.Strong(titulo)
        articulos.append(
            html.Article(
                className="research-news-item",
                children=[
                    enlace,
                    html.Div(f"{fuente} · {_texto_noticia_fecha(fecha)}", className="research-news-meta"),
                    html.P(resumen, className="research-news-summary") if resumen else None,
                ],
            )
        )
    return html.Div(articulos, className="research-news-list")


def _valor_base_dcf(dcf):
    if not dcf or not dcf.get("disponible"):
        return None
    escenarios = dcf.get("escenarios") or []
    for escenario in escenarios:
        nombre = str(_clave(escenario, "nombre", "name", defecto="")).lower()
        if "base" in nombre or "central" in nombre:
            return _clave(escenario, "valor", "value")
    return _clave(escenarios[len(escenarios) // 2], "valor", "value") if escenarios else None


def _salida_vacia(mensaje):
    vacio = html.Div("Sin datos disponibles.", className="research-empty")
    return (
        html.Div(mensaje, className="research-alert"),
        [],
        construir_resumen({}),
        vacio,
        vacio,
        vacio,
        vacio,
        vacio,
        vacio,
        vacio,
        vacio,
        "",
        None,
    )


@callback(
    Output("aviso-investigacion", "children"),
    Output("cabecera-investigacion", "children"),
    Output("resumen-investigacion", "children"),
    Output("metricas-valoracion-investigacion", "children"),
    Output("dcf-investigacion", "children"),
    Output("metricas-solvencia-investigacion", "children"),
    Output("metricas-calidad-investigacion", "children"),
    Output("metricas-crecimiento-investigacion", "children"),
    Output("historico-investigacion", "children"),
    Output("contexto-precio-investigacion", "children"),
    Output("noticias-investigacion", "children"),
    Output("fuente-investigacion", "children"),
    Output("store-valor-razonable-investigacion", "data"),
    Input("selector-activo-investigacion", "value"),
)
def actualizar_analisis_investigacion(ticker):
    if not ticker or activos_investigacion.empty:
        return _salida_vacia("No hay activos marcados con Seguimiento = sí en la hoja Listado de activos.")

    activo = obtener_activo(activos_investigacion, ticker)
    ticker = activo["Ticker"]
    precios = descargar_precios_investigacion(ticker)

    try:
        analisis = analizar_empresa(ticker, precios)
    except Exception:
        return _salida_vacia(
            "No se ha podido completar el análisis ahora mismo. Comprueba la conexión o el ticker y vuelve a intentarlo."
        )

    empresa = analisis.get("empresa") or {}
    moneda = _clave(empresa, "moneda", "currency")
    moneda_financiera = _clave(empresa, "moneda_financiera", "financial_currency", defecto=moneda)
    benchmark = activo.get("Benchmark")
    contexto = calcular_contexto_precio(precios, benchmark)
    metricas_contexto = contexto.get("metricas", []) if isinstance(contexto, dict) else contexto
    metricas = analisis.get("metricas") or {}
    dcf = analisis.get("dcf") or {}
    avisos = [aviso for aviso in analisis.get("avisos", []) if aviso]
    if isinstance(contexto, dict):
        avisos.extend(aviso for aviso in contexto.get("avisos", []) if aviso)

    aviso_componente = (
        html.Div([html.Div(aviso) for aviso in dict.fromkeys(avisos)], className="research-alert")
        if avisos
        else ""
    )
    fuente = analisis.get("fuente") or "Fuente: Yahoo Finance vía yfinance. Datos para uso informativo."
    valor_base = _valor_base_dcf(dcf)
    escenarios_grafico = dcf.get("escenarios") if dcf.get("disponible") else []

    return (
        aviso_componente,
        construir_cabecera(analisis, activo, precios),
        construir_resumen(analisis),
        construir_metricas(metricas.get("valoracion"), moneda),
        construir_dcf(dcf, moneda),
        construir_metricas(metricas.get("solvencia"), moneda),
        construir_metricas(metricas.get("calidad"), moneda),
        construir_metricas(metricas.get("crecimiento"), moneda),
        construir_historico(analisis.get("historico"), moneda_financiera),
        construir_metricas(metricas_contexto, moneda),
        construir_noticias(analisis.get("noticias")),
        fuente,
        {
            "valor": valor_base,
            "escenarios": escenarios_grafico,
            "moneda": moneda,
        }
        if _es_numero(valor_base)
        else None,
    )


@callback(
    Output("grafico-precio-investigacion", "figure"),
    Input("selector-activo-investigacion", "value"),
    Input("selector-periodo-investigacion", "value"),
    Input("store-valor-razonable-investigacion", "data"),
)
def actualizar_grafico_investigacion(ticker, periodo, valor_razonable):
    if not ticker or activos_investigacion.empty:
        return crear_grafico_precio(pd.Series(dtype="float64"), "", "Sin activo")

    activo = obtener_activo(activos_investigacion, ticker)
    precios = descargar_precios_investigacion(activo["Ticker"])
    escenarios = (valor_razonable or {}).get("escenarios") or []
    valor = {"escenarios": escenarios} if escenarios else (valor_razonable or {}).get("valor")
    moneda = (valor_razonable or {}).get("moneda")
    return crear_grafico_precio(
        filtrar_periodo(precios, periodo),
        activo["Ticker"],
        activo["Nombre"],
        precios_medias=precios,
        valor_razonable=valor,
        moneda=moneda,
    )
