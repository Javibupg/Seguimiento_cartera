import webbrowser
from threading import Timer

import dash
from dash import Dash, html, page_container, page_registry


app = Dash(__name__, use_pages=True, suppress_callback_exceptions=True)
app.title = "Dashboard de inversiones"


ESTILO_FONDO = {
    "fontFamily": "Arial, sans-serif",
    "backgroundColor": "#f3f4f6",
    "minHeight": "100vh",
    "padding": "40px",
}

ESTILO_CAJA = {
    "backgroundColor": "white",
    "padding": "20px 24px",
    "borderRadius": "18px",
    "boxShadow": "0 4px 14px rgba(0,0,0,0.08)",
    "marginBottom": "30px",
}

ESTILO_LINK = {
    "display": "inline-block",
    "padding": "10px 18px",
    "marginRight": "10px",
    "border": "1px solid #d1d5db",
    "borderRadius": "10px",
    "backgroundColor": "#f9fafb",
    "color": "#111827",
    "fontWeight": "600",
    "textDecoration": "none",
}


def menu_paginas():
    paginas = sorted(
        page_registry.values(),
        key=lambda p: p.get("order", 0),
    )

    return [
        html.A(
            pagina["name"],
            href=pagina["relative_path"],
            style=ESTILO_LINK,
        )
        for pagina in paginas
    ]


app.layout = html.Div(
    style=ESTILO_FONDO,
    children=[
        html.Div(
            style={"maxWidth": "1100px", "margin": "0 auto"},
            children=[
                html.H1(
                    "Dashboard de inversiones",
                    style={"color": "#111827", "marginBottom": "5px"},
                ),
                html.P(
                    "Seguimiento de cartera con rentabilidad TWR, divisas y distribución de posiciones",
                    style={"color": "#6b7280", "marginBottom": "30px"},
                ),

                html.Div(
                    style=ESTILO_CAJA,
                    children=[
                        html.Div(
                            "Páginas",
                            style={
                                "fontSize": "14px",
                                "fontWeight": "700",
                                "color": "#374151",
                                "marginBottom": "12px",
                            },
                        ),
                        html.Div(menu_paginas()),
                    ],
                ),

                page_container,
            ],
        ),
    ],
)


if __name__ == "__main__":
    port = 8050
    Timer(1, lambda: webbrowser.open_new(f"http://127.0.0.1:{port}")).start()
    app.run(debug=True, port=port, use_reloader=False)