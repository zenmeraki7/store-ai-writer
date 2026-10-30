"""Read a product page from its link: name, details and main photo. Best effort, since some sites block automated reads."""
from __future__ import annotations

import base64
import html as htmlmod
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36 StoreAIWriter/1.0"
MAX_HTML, MAX_IMG = 2_000_000, 5_000_000


class LinkError(Exception):
    pass


def check_url(url: str) -> str:
    """Only public http(s) addresses are allowed, so a link can't be used to reach this computer or a private network."""
    u = urllib.parse.urlparse((url or "").strip())
    try:
        port = u.port
    except ValueError:
        port = -1
    if u.scheme not in ("http", "https") or not u.hostname:
        raise LinkError("Paste a full link that starts with https://")
    if port not in (None, 80, 443):
        raise LinkError("That link can't be read.")
    try:
        infos = socket.getaddrinfo(u.hostname, None)
    except OSError:
        raise LinkError("That address could not be found.")
    for info in infos:
        if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
            raise LinkError("That link can't be read.")
    return u.geturl()


class _Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)  # every hop is checked too
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _get(url: str, limit: int, accept: str):
    req = urllib.request.Request(check_url(url), headers={"User-Agent": UA, "Accept": accept, "Accept-Language": "en"})
    try:
        with urllib.request.build_opener(_Redirect).open(req, timeout=15) as r:
            data = r.read(limit + 1)
            return data, r.headers.get("Content-Type", ""), r.headers.get_content_charset() or "utf-8", r.geturl()
    except urllib.error.HTTPError as e:
        raise LinkError(f"That site didn't let us read the page (error {e.code}). Paste the product details instead.") from e
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LinkError("The page could not be reached.") from e


def _meta(htm: str, key: str) -> str:
    for m in re.finditer(r"<meta\b[^>]*>", htm, re.I):
        tag = m.group(0)
        k = re.search(r'(?:property|name)\s*=\s*["\']([^"\']+)["\']', tag, re.I)
        if k and k.group(1).lower() == key:
            c = re.search(r'content\s*=\s*(?:"([^"]*)"|\'([^\']*)\')', tag, re.I)
            if c:
                return htmlmod.unescape(c.group(1) or c.group(2) or "").strip()
    return ""


def _products(htm: str) -> list[dict]:
    out: list[dict] = []
    for m in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", htm, re.I | re.S):
        try:
            stack = [json.loads(m.group(1).strip())]
        except ValueError:
            continue
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack += d
            elif isinstance(d, dict):
                t = d.get("@type")
                if "Product" in (t if isinstance(t, list) else [t]):
                    out.append(d)
                stack += [v for v in d.values() if isinstance(v, (list, dict))]
    return out


def _text(v) -> str:
    if isinstance(v, dict):
        v = v.get("name") or ""
    if isinstance(v, list):
        v = ", ".join(_text(x) for x in v if x)
    return re.sub(r"\s+", " ", htmlmod.unescape(str(v or ""))).strip()


def _image(v) -> str:
    if isinstance(v, list):
        v = v[0] if v else ""
    if isinstance(v, dict):
        v = v.get("url") or ""
    return str(v or "")


def parse_product(htm: str, base: str) -> dict:
    prod = (_products(htm) or [{}])[0]
    title = _text(prod.get("name")) or _meta(htm, "og:title")
    if not title:
        t = re.search(r"<title[^>]*>(.*?)</title>", htm, re.I | re.S)
        title = _text(t.group(1)) if t else ""
    title = re.split(r"\s+[-|\u2013]\s+(?:Buy|Shop)\b|\s+\|\s+", title)[0].strip()
    desc = _text(prod.get("description")) or _meta(htm, "og:description") or _meta(htm, "description")
    lines = [desc] if desc else []
    for label, key in (("Brand", "brand"), ("Colour", "color"), ("Size", "size"), ("Material", "material"), ("Pattern", "pattern")):
        v = _text(prod.get(key))
        if v:
            lines.append(f"{label}: {v}")
    img = _image(prod.get("image")) or _meta(htm, "og:image")
    return {"name": title[:150], "description": "\n".join(lines)[:1800], "image_url": urllib.parse.urljoin(base, img) if img else ""}


def read_link(url: str) -> dict:
    data, _, charset, final = _get(url, MAX_HTML, "text/html,application/xhtml+xml")
    if len(data) > MAX_HTML:
        raise LinkError("That page is too large to read.")
    p = parse_product(data.decode(charset, "replace"), final)
    if not (p["name"] or p["description"]):
        raise LinkError("We couldn't find product details on that page. Paste them instead.")
    image = ""
    if p["image_url"]:
        try:
            raw, ctype, _, _ = _get(p["image_url"], MAX_IMG, "image/*")
            if raw and len(raw) <= MAX_IMG and ctype.lower().startswith("image/"):
                image = f"data:{ctype.split(';')[0]};base64," + base64.b64encode(raw).decode()
        except LinkError:
            pass  # the text is still useful without the photo
    return {"name": p["name"], "description": p["description"], "image": image, "source": urllib.parse.urlparse(final).hostname or ""}
