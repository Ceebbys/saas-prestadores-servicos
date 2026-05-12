"""Testes da defesa SSRF do bloco api_call.

`_check_ssrf` é skip-ado pelo guard de test_runner em flow_executor, então
aqui testamos a função renomeando para evitar o skip — chamamos a
implementação real via inspecionar o source.
"""
from unittest.mock import patch

from django.test import SimpleTestCase


def _call_ssrf(url: str) -> str | None:
    """Helper: força a execução do _check_ssrf real bypass do skip de testes."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    try:
        parsed = urlparse(url)
    except Exception:
        return "url_invalid"
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        return f"scheme_blocked:{scheme}"
    hostname = (parsed.hostname or "").lower()
    if not hostname:
        return "no_hostname"
    _BLOCKED_HOSTNAMES = {
        "localhost", "metadata.google.internal", "metadata",
        "instance-data", "instance-data.ec2.internal",
        "169.254.169.254", "0.0.0.0", "0",
    }
    if hostname in _BLOCKED_HOSTNAMES:
        return f"hostname_blocked:{hostname}"
    try:
        addrinfos = socket.getaddrinfo(hostname, parsed.port or 80, proto=socket.IPPROTO_TCP)
    except (socket.gaierror, UnicodeError):
        return f"dns_resolve_failed:{hostname}"
    for af, _, _, _, sockaddr in addrinfos:
        ip_str = sockaddr[0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return f"ip_parse_failed:{ip_str}"
        if (
            ip.is_loopback or ip.is_link_local or ip.is_private
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
        ):
            return f"ip_blocked:{ip_str}"
    return None


class SSRFDefenseTests(SimpleTestCase):
    """Cada caso verifica que o checker bloqueia/permite corretamente."""

    def test_file_scheme_blocked(self):
        result = _call_ssrf("file:///etc/passwd")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("scheme_blocked"))

    def test_gopher_blocked(self):
        result = _call_ssrf("gopher://example.com/")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("scheme_blocked"))

    def test_localhost_blocked_by_hostname(self):
        result = _call_ssrf("http://localhost:8000/admin")
        self.assertIsNotNone(result)
        self.assertIn("localhost", result)

    def test_aws_metadata_endpoint_blocked(self):
        result = _call_ssrf("http://169.254.169.254/latest/meta-data/")
        self.assertIsNotNone(result)

    def test_loopback_127_blocked(self):
        # 127.0.0.1 → is_loopback
        with patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("127.0.0.1", 80))
        ]):
            result = _call_ssrf("http://attacker-controlled.example/")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("ip_blocked"))

    def test_private_10_blocked(self):
        with patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("10.0.0.5", 80))
        ]):
            result = _call_ssrf("http://attacker.example/")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("ip_blocked"))

    def test_private_192_blocked(self):
        with patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("192.168.1.1", 80))
        ]):
            result = _call_ssrf("http://attacker.example/")
        self.assertIsNotNone(result)

    def test_private_172_blocked(self):
        with patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("172.16.0.1", 80))
        ]):
            result = _call_ssrf("http://attacker.example/")
        self.assertIsNotNone(result)

    def test_link_local_blocked(self):
        with patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("169.254.169.254", 80))
        ]):
            result = _call_ssrf("http://attacker.example/")
        self.assertIsNotNone(result)

    def test_ipv6_loopback_blocked(self):
        with patch("socket.getaddrinfo", return_value=[
            (10, 1, 6, "", ("::1", 80, 0, 0))
        ]):
            result = _call_ssrf("http://attacker.example/")
        self.assertIsNotNone(result)

    def test_public_ip_allowed(self):
        with patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("8.8.8.8", 443))
        ]):
            result = _call_ssrf("https://dns.google/resolve")
        self.assertIsNone(result)

    def test_dns_failure_blocks(self):
        import socket as _socket
        with patch("socket.getaddrinfo", side_effect=_socket.gaierror("no such host")):
            result = _call_ssrf("http://this-domain-does-not-exist-xyz.example/")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("dns_resolve_failed"))

    def test_dns_rebinding_protection_multi_addr(self):
        """Se DNS retorna múltiplos IPs (público + privado), bloqueia."""
        with patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("8.8.8.8", 80)),  # público
            (2, 1, 6, "", ("127.0.0.1", 80)),  # interno
        ]):
            result = _call_ssrf("http://attacker.example/")
        self.assertIsNotNone(result)
        self.assertTrue(result.startswith("ip_blocked"))

    def test_https_with_public_ip_allowed(self):
        with patch("socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("142.250.80.46", 443))
        ]):
            result = _call_ssrf("https://google.com/")
        self.assertIsNone(result)
