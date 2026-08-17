"""Sesion HTTPS reutilizable para Yahoo Finance.

``yfinance`` usa ``curl_cffi`` y, en Windows, esa libreria no siempre ve los
certificados instalados en el almacen de confianza del sistema. En ese caso
Yahoo falla antes de responder con ``CERTIFICATE_VERIFY_FAILED``. Esta capa
combina el bundle publico de ``certifi`` con las autoridades de confianza de
Windows y mantiene activa la verificacion TLS.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path
import ssl
import tempfile
import threading

import certifi
from curl_cffi import requests as curl_requests


_LOCK = threading.RLock()
_SESSION = None
_BUNDLE_GENERADO: Path | None = None


def _bundle_configurado() -> str | None:
    """Respeta un bundle corporativo configurado explicitamente."""
    for variable in ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE"):
        valor = os.environ.get(variable)
        if valor and Path(valor).is_file():
            return valor
    return None


def _crear_bundle_windows() -> str:
    """Crea un PEM temporal con certifi y el almacen ROOT de Windows."""
    global _BUNDLE_GENERADO

    if _BUNDLE_GENERADO is not None and _BUNDLE_GENERADO.is_file():
        return str(_BUNDLE_GENERADO)
    if not hasattr(ssl, "enum_certificates"):
        return certifi.where()

    bloques = [Path(certifi.where()).read_bytes().rstrip(), b""]
    vistos = set()
    for almacen in ("ROOT", "CA"):
        for certificado, codificacion, _confianza in ssl.enum_certificates(almacen):
            if codificacion != "x509_asn" or certificado in vistos:
                continue
            vistos.add(certificado)
            pem = ssl.DER_cert_to_PEM_cert(certificado).encode("ascii").rstrip()
            bloques.extend((pem, b""))

    destino = Path(tempfile.gettempdir()) / f"seguimiento_cartera_ca_{os.getpid()}.pem"
    destino.write_bytes(b"\n".join(bloques))
    _BUNDLE_GENERADO = destino
    return str(destino)


def obtener_sesion_yahoo():
    """Devuelve una unica sesion de curl_cffi con verificacion TLS activa."""
    global _SESSION

    with _LOCK:
        if _SESSION is None:
            bundle = _bundle_configurado() or _crear_bundle_windows()
            _SESSION = curl_requests.Session(impersonate="chrome", verify=bundle)
        return _SESSION


def _limpiar_bundle_temporal():
    if _BUNDLE_GENERADO is None:
        return
    try:
        _BUNDLE_GENERADO.unlink(missing_ok=True)
    except OSError:
        pass


atexit.register(_limpiar_bundle_temporal)
