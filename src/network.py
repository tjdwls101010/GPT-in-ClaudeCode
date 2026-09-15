"""Verified TLS, including Python.org macOS installs without bundled roots."""

import os
import ssl
import sys


def tls_context():
    context = ssl.create_default_context()
    if sys.platform == "darwin" and not context.get_ca_certs() and not os.environ.get("SSL_CERT_FILE"):
        context.load_verify_locations("/etc/ssl/cert.pem")
    return context
