import unittest
from unittest.mock import patch, sentinel

import pandas as pd

import cache_precios
import investigacion_utils
import yahoo_session


class YahooSessionTests(unittest.TestCase):
    def test_cache_fallida_expira_en_ttl_corto(self):
        llamadas = []

        @investigacion_utils._ttl_cache(
            ttl=2_700,
            cachear=lambda resultado: bool(resultado),
            ttl_rechazado=30,
        )
        def descargar():
            llamadas.append(1)
            return {}

        with patch.object(investigacion_utils.time, "monotonic", side_effect=[0, 10, 31]):
            descargar()
            descargar()
            descargar()

        self.assertEqual(len(llamadas), 2)

    def test_sesion_mantiene_verificacion_tls(self):
        with (
            patch.object(yahoo_session, "_SESSION", None),
            patch.object(yahoo_session, "_bundle_configurado", return_value="bundle-seguro.pem"),
            patch.object(yahoo_session.curl_requests, "Session", return_value=sentinel.session) as crear,
        ):
            sesion = yahoo_session.obtener_sesion_yahoo()

        self.assertIs(sesion, sentinel.session)
        crear.assert_called_once_with(impersonate="chrome", verify="bundle-seguro.pem")

    def test_descarga_precios_usa_la_sesion_compartida(self):
        indice = pd.to_datetime(["2026-08-14"])
        datos = pd.DataFrame({"Close": [100.0]}, index=indice)
        cache_precios.ULTIMA_DESCARGA_POR_TICKER.clear()
        with (
            patch.object(cache_precios, "obtener_sesion_yahoo", return_value=sentinel.session),
            patch.object(cache_precios.yf, "download", return_value=datos) as descargar,
        ):
            resultado = cache_precios._descargar("TEST", pd.Timestamp("2026-08-01"))

        self.assertEqual(resultado.iloc[-1], 100.0)
        self.assertIs(descargar.call_args.kwargs["session"], sentinel.session)


if __name__ == "__main__":
    unittest.main()
