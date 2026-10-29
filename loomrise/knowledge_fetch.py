"""Bounded HTTPS text fetch for authorized knowledge URLs."""

from __future__ import annotations

from html.parser import HTMLParser
import http.client
import ipaddress
import socket
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit

_MAX_BYTES = 5 * 1024 * 1024
_MAX_REDIRECTS = 3


class _TextOnly(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.ignored = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self.ignored += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self.ignored:
            self.ignored -= 1

    def handle_data(self, data: str) -> None:
        if not self.ignored and data.strip():
            self.parts.append(data.strip())


def _validate_url(url: str) -> tuple[str, str, str]:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
        or parsed.password is not None or parsed.port not in (None, 443)
    ):
        raise ValueError("URL 摄入仅接受无凭据的 HTTPS 默认端口地址")
    host = parsed.hostname.encode("idna").decode("ascii")
    target = urlunsplit(("", "", parsed.path or "/", parsed.query, ""))
    return host, target, parsed.hostname


def _public_addresses(host: str) -> list[str]:
    try:
        rows = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise OSError("URL 主机名解析失败") from exc
    addresses = list(dict.fromkeys(row[4][0] for row in rows))
    if not addresses or any(not ipaddress.ip_address(value).is_global for value in addresses):
        raise ValueError("URL 解析到非公网地址，已拒绝抓取")
    return addresses


def _read_once(host: str, ip: str, target: str) -> tuple[int, str | None, bytes, str, str | None]:
    class PinnedConnection(http.client.HTTPSConnection):
        def connect(self) -> None:
            sock = socket.create_connection((ip, self.port), self.timeout, self.source_address)
            self.sock = self._context.wrap_socket(sock, server_hostname=host)

    connection = PinnedConnection(host, timeout=8, context=ssl.create_default_context())
    try:
        connection.request("GET", target, headers={
            "Accept": "text/html,text/plain;q=0.9",
            "User-Agent": "Loomrise-KnowledgeFetcher/1",
            "Connection": "close",
        })
        response = connection.getresponse()
        content_type = response.getheader("Content-Type", "text/plain")
        content_encoding = response.getheader("Content-Encoding")
        location = response.getheader("Location")
        if response.status in {301, 302, 303, 307, 308}:
            return response.status, location, b"", content_type, content_encoding
        if response.status < 200 or response.status >= 300:
            raise OSError(f"URL 返回 HTTP {response.status}")
        if content_encoding not in (None, "identity"):
            raise OSError("URL 返回了不支持的压缩编码")
        body = response.read(_MAX_BYTES + 1)
        if len(body) > _MAX_BYTES:
            raise ValueError("URL 内容超过 5 MiB")
        return response.status, None, body, content_type, content_encoding
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        if isinstance(exc, (ValueError, OSError)):
            raise
        raise OSError("URL 读取失败") from exc
    finally:
        connection.close()


def fetch_https_text(url: str, *, redirects: int = 0) -> str:
    host, target, _ = _validate_url(url)
    addresses = _public_addresses(host)
    last_error: OSError | None = None
    for address in addresses:
        try:
            status, location, body, content_type, _ = _read_once(host, address, target)
            if location:
                if redirects >= _MAX_REDIRECTS:
                    raise ValueError("URL 重定向次数超过限制")
                return fetch_https_text(urljoin(url, location), redirects=redirects + 1)
            charset = "utf-8"
            for part in content_type.split(";")[1:]:
                key, _, value = part.partition("=")
                if key.strip().lower() == "charset" and value.strip():
                    charset = value.strip().strip('"\'')
            text = body.decode(charset)
            if "html" in content_type.lower():
                parser = _TextOnly()
                parser.feed(text)
                text = "\n".join(parser.parts)
            text = "\n".join(line.strip() for line in text.splitlines() if line.strip())
            if not text:
                raise ValueError("URL 未包含可摄入的文本内容")
            return text
        except UnicodeError as exc:
            raise ValueError("URL 内容无法按声明编码解析") from exc
        except OSError as exc:
            last_error = exc
    raise last_error or OSError("URL 无可用公网地址")


__all__ = ["fetch_https_text"]
