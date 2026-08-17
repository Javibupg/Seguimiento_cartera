import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

import investigacion_utils as iu


def _estado(filas):
    columnas = pd.to_datetime(["2025-12-31", "2024-12-31", "2023-12-31", "2022-12-31"])
    return pd.DataFrame(filas, index=columnas).T


def _paquete_empresa(deuda=(100, 120, 140, 160), caja=(200, 180, 160, 140), moneda="EUR", moneda_financiera="EUR"):
    income = _estado(
        {
            "Total Revenue": [1_000, 900, 800, 700],
            "EBITDA": [160, 140, 120, 100],
            "EBIT": [120, 100, 80, 70],
            "Net Income": [80, 70, 60, 50],
            "Pretax Income": [100, 90, 80, 70],
            "Tax Provision": [20, 18, 16, 14],
            "Interest Expense": [10, 10, 9, 8],
            "Diluted Average Shares": [100, 101, 102, 103],
            "Gross Profit": [500, 440, 380, 330],
        }
    )
    cashflow = _estado(
        {
            "Free Cash Flow": [100, 90, 80, 70],
            "Operating Cash Flow": [150, 135, 120, 105],
            "Capital Expenditure": [-50, -45, -40, -35],
        }
    )
    balance = _estado(
        {
            "Total Debt": deuda,
            "Cash Cash Equivalents And Short Term Investments": caja,
            "Stockholders Equity": [600, 560, 520, 480],
            "Invested Capital": [500, 500, 500, 500],
            "Current Assets": [400, 370, 340, 310],
            "Current Liabilities": [200, 195, 190, 185],
            "Total Assets": [1_200, 1_100, 1_000, 900],
        }
    )
    info = {
        "quoteType": "EQUITY",
        "longName": "Empresa de prueba",
        "sector": "Industrials",
        "industry": "Specialty Business Services",
        "currency": moneda,
        "financialCurrency": moneda_financiera,
        "currentPrice": 12,
        "sharesOutstanding": 100,
        "marketCap": 1_200,
        "enterpriseValue": 1_100,
        "freeCashflow": 105,
        "ebitda": 160,
        "forwardPE": 11,
        "priceToBook": 2,
    }
    return {
        "info": info,
        "income": income,
        "cashflow": cashflow,
        "balance": balance,
        "news": [
            {
                "titulo": "La empresa publica resultados",
                "fuente": "Fuente de prueba",
                "fecha": "2026-08-01T08:00:00+00:00",
                "url": "https://example.com/resultados",
            }
        ],
        "errores": [],
    }


class AnalisisValueTests(unittest.TestCase):
    def setUp(self):
        fechas = pd.bdate_range("2025-08-01", periods=260)
        self.precios = pd.Series(np.linspace(10, 12, len(fechas)), index=fechas)

    def test_empresa_completa_genera_score_dcf_e_historico(self):
        with patch.object(iu, "_descargar_paquete_yahoo", return_value=_paquete_empresa()):
            resultado = iu.analizar_empresa("TEST", self.precios)

        self.assertTrue(resultado["es_empresa"])
        self.assertIsNotNone(resultado["score"]["valor"])
        self.assertGreaterEqual(resultado["score"]["cobertura"], 0.70)
        self.assertEqual(len(resultado["score"]["pilares"]), 4)
        self.assertTrue(resultado["dcf"]["disponible"])
        self.assertEqual(len(resultado["dcf"]["escenarios"]), 3)
        self.assertEqual(len(resultado["historico"]), 4)
        self.assertAlmostEqual(resultado["historico"][0]["margen_fcf"], 0.10)

    def test_deuda_muy_alta_bloquea_el_veredicto(self):
        paquete = _paquete_empresa(deuda=(1_100, 1_050, 1_000, 950), caja=(0, 0, 0, 0))
        with patch.object(iu, "_descargar_paquete_yahoo", return_value=paquete):
            resultado = iu.analizar_empresa("DEUDA", self.precios)

        self.assertTrue(any("Deuda neta / EBITDA" in bloqueo for bloqueo in resultado["bloqueos"]))
        self.assertEqual(resultado["score"]["veredicto"], "No encaja por riesgos críticos")

    def test_etf_no_recibe_score_empresarial(self):
        paquete = {
            "info": {"quoteType": "ETF", "longName": "ETF de prueba", "currency": "EUR"},
            "income": pd.DataFrame(),
            "cashflow": pd.DataFrame(),
            "balance": pd.DataFrame(),
            "news": [],
            "errores": [],
        }
        with patch.object(iu, "_descargar_paquete_yahoo", return_value=paquete):
            resultado = iu.analizar_empresa("ETF", self.precios)

        self.assertFalse(resultado["es_empresa"])
        self.assertIsNone(resultado["score"]["valor"])
        self.assertEqual(resultado["score"]["cobertura"], 0)
        self.assertFalse(resultado["dcf"]["disponible"])
        self.assertFalse(any("estados financieros" in aviso for aviso in resultado["avisos"]))

    def test_fallo_total_no_se_presenta_como_etf(self):
        paquete = {
            "info": {},
            "income": pd.DataFrame(),
            "cashflow": pd.DataFrame(),
            "balance": pd.DataFrame(),
            "news": [],
            "errores": ["curl: (60) SSL certificate problem"],
        }
        with (
            patch.object(iu, "_descargar_paquete_yahoo", return_value=paquete),
            patch.object(iu, "descargar_precios_investigacion", return_value=pd.Series(dtype="float64")),
        ):
            resultado = iu.analizar_empresa("SIN_DATOS", pd.Series(dtype="float64"))

        self.assertFalse(resultado["es_empresa"])
        self.assertEqual(resultado["clasificacion"], "indeterminada")
        self.assertEqual(resultado["empresa"]["tipo"], "UNKNOWN")
        self.assertEqual(resultado["score"]["veredicto"], "Datos insuficientes para clasificar el activo")
        self.assertNotIn("fondos", resultado["score"]["veredicto"].lower())
        self.assertTrue(any("conexión segura" in aviso for aviso in resultado["avisos"]))

    def test_noticias_solas_no_validan_cache_fundamental(self):
        paquete = {
            "info": {},
            "income": pd.DataFrame(),
            "cashflow": pd.DataFrame(),
            "balance": pd.DataFrame(),
            "news": [{"titulo": "Titular"}],
        }
        self.assertFalse(iu._paquete_yahoo_tiene_datos(paquete))

    def test_monedas_incompatibles_anulan_dcf_y_ratios_propios(self):
        paquete = _paquete_empresa(moneda="USD", moneda_financiera="EUR")
        with patch.object(iu, "_descargar_paquete_yahoo", return_value=paquete):
            resultado = iu.analizar_empresa("FX", self.precios)

        self.assertFalse(resultado["dcf"]["disponible"])
        self.assertTrue(any("mezcla cotización" in aviso for aviso in resultado["avisos"]))
        fcf_yield = resultado["metricas"]["valoracion"][0]
        self.assertIsNone(fcf_yield["valor"])
        self.assertEqual(fcf_yield["cobertura"], 0)

    def test_contexto_precio_no_puntua(self):
        contexto = iu.calcular_contexto_precio(self.precios)
        self.assertTrue(contexto["fuera_score"])
        self.assertTrue(all(metrica["peso"] == 0 for metrica in contexto["metricas"]))
        rentabilidad = next(m for m in contexto["metricas"] if m["titulo"] == "Rentabilidad 1A")
        esperada = self.precios.iloc[-1] / self.precios.iloc[-253] - 1
        self.assertAlmostEqual(rentabilidad["valor"], esperada)

    def test_noticias_rechazan_enlaces_con_esquema_inseguro(self):
        noticias = iu._normalizar_noticias(
            [{"title": "Titular", "link": "javascript:alert('x')", "publisher": "Prueba"}]
        )
        self.assertEqual(len(noticias), 1)
        self.assertIsNone(noticias[0]["url"])


if __name__ == "__main__":
    unittest.main()
