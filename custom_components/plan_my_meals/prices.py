"""Async supermarket price lookup and formatting for Plan My Meals."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import unicodedata
import urllib.parse
from html import unescape
from typing import TYPE_CHECKING, Any, Awaitable, Callable

if TYPE_CHECKING:
    import aiohttp

from .const import DEFAULT_COUNTRY, DEFAULT_CURRENCY, SUPERMARKETS_BY_COUNTRY

_LOGGER = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

FetchAsyncFn = Callable[[str, int], Awaitable[str]]


def normalize_text(text: str) -> str:
    """Normalize text for matching (strip parentheses, accents, lowercase)."""
    s = re.sub(r"\s*\([^)]*\)\s*", " ", str(text or ""))
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s).lower().strip()


def extract_domain(url: str) -> str:
    """Extract normalized domain without www. prefix."""
    try:
        host = urllib.parse.urlparse(url).netloc.lower().strip()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host.split(":")[0]


def canonical_supermarket(domain: str, country: str = DEFAULT_COUNTRY) -> tuple[str, str] | None:
    """Return (canonical_domain, display_name) if domain matches a known supermarket."""
    dom = (domain or "").lower().strip()
    if dom.startswith("www."):
        dom = dom[4:]
    catalog = SUPERMARKETS_BY_COUNTRY.get(country.upper(), SUPERMARKETS_BY_COUNTRY["PT"])
    for key, name in catalog.items():
        if dom == key or dom.endswith("." + key):
            return key, name
    return None


def parse_price(raw: Any) -> float | None:
    """Parse European/US decimal price values into a positive float."""
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        val = float(raw)
        return round(val, 2) if 0 < val < 500 else None
    txt = str(raw).strip().replace("\xa0", " ").replace("€", "").strip()
    m = re.search(r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d{1,2})|\d+(?:[.,]\d{1,2})?)", txt)
    if not m:
        return None
    num = m.group(1).replace(" ", "")
    if "," in num and "." in num:
        num = num.replace(".", "").replace(",", ".")
    elif "," in num:
        num = num.replace(",", ".")
    try:
        val = float(num)
    except ValueError:
        return None
    return round(val, 2) if 0 < val < 500 else None


def format_short_price(price: float, currency: str = DEFAULT_CURRENCY) -> str:
    """Format 9.0 -> '9€' and 2.49 -> '2,49€'."""
    val = round(float(price), 2)
    if abs(val - round(val)) < 1e-9:
        return f"{int(round(val))}{currency}"
    return f"{val:.2f}".replace(".", ",") + currency


def extract_unit_from_text(text: str) -> str:
    """Extract normalized pack/quantity unit (e.g. '1 kg', '500 g', '1 L', '6 un') from product text."""
    s = re.sub(r"\s+", " ", unescape(str(text or ""))).strip()
    if not s:
        return ""
    # Strip leading "emb." / "embalagem" / "aprox."
    s_clean = re.sub(r"^(?:emb\.?|embalagem|aprox\.?)\s*", "", s, flags=re.IGNORECASE).strip()

    # Multipack like "4x125g" or "6 x 33 cl"
    m_multi = re.search(
        r"\b(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(kg|g|gr|ml|cl|dl|l|lt|un|unid|unidades?)\b",
        s_clean,
        flags=re.IGNORECASE,
    )
    if m_multi:
        cnt, qty, unit = m_multi.group(1), m_multi.group(2).replace(".", ","), m_multi.group(3).lower()
        u_norm = {"gr": "g", "lt": "L", "l": "L", "unid": "un", "unidade": "un", "unidades": "un"}.get(unit, unit)
        return f"{cnt}x{qty} {u_norm}"

    # Single quantity like "1 kg", "500g", "1,5 L", "750 ml", "6 un"
    m = re.search(
        r"\b(\d+(?:[.,]\d+)?)\s*(kg|g|gr|ml|cl|dl|l|lt|un|unid|unidades?|d[uú]zia|latas?|doses?)\b",
        s_clean,
        flags=re.IGNORECASE,
    )
    if m:
        qty_raw, unit = m.group(1).replace(".", ","), m.group(2).lower()
        # Drop trailing ,0 or ,00
        qty_clean = re.sub(r",0+$", "", qty_raw)
        u_map = {
            "gr": "g",
            "lt": "L",
            "l": "L",
            "unid": "un",
            "unidade": "un",
            "unidades": "un",
            "duzia": "dúzia",
            "dúzia": "dúzia",
            "lata": "lata",
            "latas": "latas",
            "dose": "dose",
            "doses": "doses",
        }
        u_norm = u_map.get(unit, unit)
        return f"{qty_clean} {u_norm}"

    # Standalone weight/volume label like "kg" or "un"
    m_bare = re.search(r"\b(kg|un|unid|litro)\b", s_clean, flags=re.IGNORECASE)
    if m_bare:
        u = m_bare.group(1).lower()
        return {"unid": "un", "litro": "1 L", "kg": "1 kg", "un": "1 un"}.get(u, u)
    return ""


def normalize_unit_price(raw: str, currency: str = DEFAULT_CURRENCY) -> str:
    """Normalize scraped unit price strings like '1.89 €/Kg' -> '1,89 €/kg'."""
    txt = re.sub(r"\s+", " ", unescape(str(raw or ""))).strip()
    if not txt:
        return ""
    m = re.search(
        r"(\d+(?:[.,]\d{1,2})?)\s*(?:€|eur)?\s*/\s*(kg|g|100\s*g|l|lt|ml|100\s*ml|un|unid|dose)",
        txt,
        flags=re.IGNORECASE,
    )
    if not m:
        return ""
    pr = parse_price(m.group(1))
    if pr is None:
        return ""
    u_raw = re.sub(r"\s+", "", m.group(2).lower())
    u_map = {"lt": "L", "l": "L", "unid": "un"}
    u_norm = u_map.get(u_raw, u_raw)
    pr_str = f"{pr:.2f}".replace(".", ",")
    return f"{pr_str} {currency}/{u_norm}"


def compute_unit_price(price: float | None, unit_str: str, currency: str = DEFAULT_CURRENCY) -> str:
    """Compute price per kg / L / un from pack price and pack unit string."""
    if price is None or price <= 0 or not unit_str:
        return ""
    s = unit_str.strip().lower()
    # Multipack e.g. 4x125 g
    m_multi = re.match(r"^(\d+)\s*[x×]\s*(\d+(?:[.,]\d+)?)\s*(kg|g|ml|cl|dl|l|un)$", s)
    if m_multi:
        mult = float(m_multi.group(1))
        qty = float(m_multi.group(2).replace(",", ".")) * mult
        u = m_multi.group(3)
    else:
        m = re.match(r"^(\d+(?:[.,]\d+)?)\s*(kg|g|ml|cl|dl|l|un|dúzia)$", s)
        if not m:
            return ""
        qty = float(m.group(1).replace(",", "."))
        u = m.group(2)
    if qty <= 0:
        return ""
    if u == "kg":
        val, base = price / qty, "kg"
    elif u == "g":
        val, base = price / (qty / 1000.0), "kg"
    elif u == "l":
        val, base = price / qty, "L"
    elif u == "ml":
        val, base = price / (qty / 1000.0), "L"
    elif u == "cl":
        val, base = price / (qty / 100.0), "L"
    elif u == "dl":
        val, base = price / (qty / 10.0), "L"
    elif u == "un":
        val, base = price / qty, "un"
    elif u == "dúzia":
        val, base = price / (qty * 12.0), "un"
    else:
        return ""
    if val <= 0 or val >= 10000:
        return ""
    return f"{val:.2f}".replace(".", ",") + f" {currency}/{base}"


def format_price_tag(
    price: float | None,
    supermarket: str,
    currency: str = DEFAULT_CURRENCY,
) -> str:
    """Format price + store label, e.g. '9€ Auchan'."""
    if price is None or float(price) <= 0:
        return ""
    store = (supermarket or "").strip()
    pr = format_short_price(float(price), currency=currency)
    return f"{pr} {store}".strip()


def format_shopping_item(
    name: str,
    qty: str = "",
    price: float | None = None,
    supermarket: str = "",
    currency: str = DEFAULT_CURRENCY,
    include_qty: bool = True,
    include_price: bool = True,
) -> str:
    """Format a shopping list item: e.g. 'Ovomaltine (2 un) (9€ Auchan)'."""
    base = str(name or "").strip()
    if not base:
        return ""
    parts = [base]
    if include_qty and qty and str(qty).strip():
        parts.append(f"({str(qty).strip()})")
    if include_price:
        tag = format_price_tag(price, supermarket, currency=currency)
        if tag:
            parts.append(f"({tag})")
    return " ".join(parts)


def is_relevant(query: str, title: str) -> bool:
    """True if title shares at least half of meaningful query words."""
    stop = {"de", "da", "do", "das", "dos", "com", "sem", "para", "em", "na", "no", "e", "ou", "a", "o"}
    q_tokens = [t for t in re.findall(r"[a-z0-9]+", normalize_text(query)) if len(t) >= 2 and t not in stop]
    if not q_tokens:
        return True
    t_tokens = set(re.findall(r"[a-z0-9]+", normalize_text(title)))
    hits = sum(1 for t in q_tokens if t in t_tokens)
    return hits >= max(1, len(q_tokens) // 2)


def extract_json_ld_offers(html: str, base_url: str) -> list[dict[str, Any]]:
    """Extract Product/Offer JSON-LD blocks from an HTML page."""
    offers: list[dict[str, Any]] = []
    scripts = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        html or "",
        flags=re.DOTALL | re.IGNORECASE,
    )
    for raw in scripts:
        try:
            parsed = json.loads(raw.strip())
        except ValueError:
            continue
        nodes = parsed if isinstance(parsed, list) else [parsed]
        expanded: list[dict[str, Any]] = []
        for n in nodes:
            if isinstance(n, dict) and isinstance(n.get("@graph"), list):
                expanded.extend(x for x in n["@graph"] if isinstance(x, dict))
            elif isinstance(n, dict) and isinstance(n.get("itemListElement"), list):
                for el in n["itemListElement"]:
                    sub = el.get("item", el) if isinstance(el, dict) else None
                    if isinstance(sub, dict):
                        expanded.append(sub)
            elif isinstance(n, dict):
                expanded.append(n)
        for item in expanded:
            name = str(item.get("name") or "").strip()
            url_item = str(item.get("url") or "").strip()
            raw_offers = item.get("offers")
            if isinstance(raw_offers, dict):
                olist = [raw_offers]
            elif isinstance(raw_offers, list):
                olist = [o for o in raw_offers if isinstance(o, dict)]
            else:
                olist = [item] if item.get("price") or item.get("lowPrice") else []
            for off in olist:
                pr = parse_price(off.get("price") or off.get("lowPrice"))
                if pr is None:
                    continue
                curr = str(off.get("priceCurrency") or "").upper()
                if curr and curr != "EUR":
                    continue
                u = str(off.get("url") or url_item or base_url).strip()
                if u and not u.startswith(("http://", "https://")):
                    u = urllib.parse.urljoin(base_url, u)
                if name:
                    unit = extract_unit_from_text(name)
                    if not unit and isinstance(item.get("weight"), dict):
                        w = item["weight"]
                        unit = extract_unit_from_text(f"{w.get('value', '')} {w.get('unitCode', '')}")
                    unit_price = compute_unit_price(pr, unit)
                    offers.append({
                        "title": name[:200],
                        "price": pr,
                        "unit": unit,
                        "unit_price": unit_price,
                        "url": u or base_url,
                        "domain": extract_domain(u or base_url),
                    })
    return offers


def extract_continente(html: str, query: str, base_url: str) -> list[dict[str, Any]]:
    """Extract offers (with pack unit & unit price) from Continente search HTML."""
    offers = [o for o in extract_json_ld_offers(html, base_url) if is_relevant(query, o["title"])]
    if offers:
        return offers
    res: list[dict[str, Any]] = []
    text = html or ""

    # Primary: Continente SFCC product tiles embed clean JSON in data-product-tile-impression
    imp_matches = list(
        re.finditer(
            r'data-product-tile-impression=(["\'])(.*?)\1',
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
    )
    for idx, m in enumerate(imp_matches[:30]):
        try:
            data = json.loads(unescape(m.group(2)))
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        title = re.sub(r"\s+", " ", unescape(str(data.get("name") or ""))).strip()
        pr = parse_price(data.get("price"))
        if not title or pr is None or not is_relevant(query, title):
            continue
        pid = str(data.get("id") or "").strip()
        end_pos = imp_matches[idx + 1].start() if idx + 1 < len(imp_matches) else m.end() + 12000
        tile_chunk = text[m.end() : min(end_pos, m.end() + 12000)]

        # Pack quantity e.g. <p class="pwc-tile--quantity"> emb. 1 kg </p>
        unit = ""
        m_qty = re.search(r'class="[^"]*pwc-tile--quantity[^"]*"[^>]*>([\s\S]*?)</p>', tile_chunk, flags=re.I)
        if m_qty:
            qty_txt = re.sub(r"<[^>]+>", " ", m_qty.group(1))
            unit = extract_unit_from_text(qty_txt)
        if not unit:
            unit = extract_unit_from_text(title)

        # Secondary price (price per kg/L/un) if rendered
        unit_price = ""
        m_sec = re.search(r'class="[^"]*pwc-tile--price-secondary[^"]*"[^>]*>([\s\S]*?)</div>', tile_chunk, flags=re.I)
        if m_sec:
            sec_txt = re.sub(r"<[^>]+>", " ", m_sec.group(1))
            unit_price = normalize_unit_price(sec_txt)
        if not unit_price:
            unit_price = compute_unit_price(pr, unit)

        # Direct product URL
        url = ""
        if pid:
            m_url = re.search(rf'href="([^"]*?/produto/[^"]*{re.escape(pid)}[^"]*\.html)"', tile_chunk, flags=re.I)
            if m_url:
                url = urllib.parse.urljoin("https://www.continente.pt/", m_url.group(1))
        if not url:
            m_url = re.search(r'href="([^"]*?/produto/[^"]+\.html)"', tile_chunk, flags=re.I)
            if m_url:
                url = urllib.parse.urljoin("https://www.continente.pt/", m_url.group(1))

        res.append({
            "title": title[:200],
            "price": pr,
            "unit": unit,
            "unit_price": unit_price,
            "url": url or base_url,
            "domain": "continente.pt",
        })
        if len(res) >= 12:
            break

    if res:
        return res

    # Legacy fallback regex
    matches = re.findall(
        r'href="([^"]*?/produto/[^"]+)"[^>]*>([^<]{3,140})</a>([\s\S]{0,1500}?)(\d[\d.]*,\d{2})\s*€',
        text,
        flags=re.IGNORECASE,
    )
    for href, title_raw, _mid, pr_raw in matches[:8]:
        title = re.sub(r"\s+", " ", unescape(title_raw)).strip()
        pr = parse_price(pr_raw)
        if pr is not None and is_relevant(query, title):
            unit = extract_unit_from_text(title)
            res.append({
                "title": title[:200],
                "price": pr,
                "unit": unit,
                "unit_price": compute_unit_price(pr, unit),
                "url": urllib.parse.urljoin("https://www.continente.pt/", href),
                "domain": "continente.pt",
            })
    return res


def extract_auchan(html: str, query: str, base_url: str) -> list[dict[str, Any]]:
    """Extract offers (with pack unit & unit price) from Auchan search HTML."""
    offers = [o for o in extract_json_ld_offers(html, base_url) if is_relevant(query, o["title"])]
    if offers:
        return offers
    res: list[dict[str, Any]] = []
    text = html or ""

    # Primary: Auchan SFCC product tiles embed clean JSON in data-gtm and data-urls
    gtm_matches = list(
        re.finditer(
            r'data-gtm=(["\'])(.*?)\1',
            text,
            flags=re.DOTALL | re.IGNORECASE,
        )
    )
    for idx, m in enumerate(gtm_matches[:30]):
        try:
            data = json.loads(unescape(m.group(2)))
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        title = re.sub(r"\s+", " ", unescape(str(data.get("name") or ""))).strip()
        pr = parse_price(data.get("price"))
        if not title or pr is None or not is_relevant(query, title):
            continue
        pid = str(data.get("id") or "").strip()
        start_ctx = max(0, m.start() - 2500)
        end_pos = gtm_matches[idx + 1].start() if idx + 1 < len(gtm_matches) else m.end() + 10000
        tile_chunk = text[start_ctx : min(end_pos, m.end() + 10000)]

        # Product URL from data-urls JSON or href
        url = ""
        m_urls = re.search(r'data-urls=(["\'])(.*?)\1', tile_chunk[:3500], flags=re.DOTALL | re.I)
        if m_urls:
            try:
                uobj = json.loads(unescape(m_urls.group(2)))
                if isinstance(uobj, dict):
                    raw_u = str(uobj.get("absoluteProductUrl") or uobj.get("productUrl") or "").strip()
                    if raw_u:
                        url = urllib.parse.urljoin("https://www.auchan.pt/", raw_u)
            except ValueError:
                pass
        if not url and pid:
            m_href = re.search(rf'href="([^"]*?/pt/[^"]*/{re.escape(pid)}\.html[^"]*)"', tile_chunk, flags=re.I)
            if m_href:
                url = urllib.parse.urljoin("https://www.auchan.pt/", m_href.group(1))

        # Unit price e.g. <span class="auc-measures--price-per-unit">1.89 €/Kg</span>
        unit_price = ""
        m_up = re.search(r'measures--price-per-unit[^>]*>([^<]+)', tile_chunk, flags=re.I)
        if m_up:
            unit_price = normalize_unit_price(m_up.group(1))

        unit = extract_unit_from_text(title)
        if not unit and unit_price:
            m_base = re.search(r"/\s*(kg|L|un)\b", unit_price)
            if m_base:
                unit = f"1 {m_base.group(1)}"
        if not unit_price:
            unit_price = compute_unit_price(pr, unit)

        res.append({
            "title": title[:200],
            "price": pr,
            "unit": unit,
            "unit_price": unit_price,
            "url": url or base_url,
            "domain": "auchan.pt",
        })
        if len(res) >= 12:
            break

    if res:
        return res

    # Legacy fallback regex
    matches = re.findall(
        r'href="([^"]*?/pt/[^"]+/\d+\.html[^"]*)"[^>]*>([^<]{3,140})</a>([\s\S]{0,1500}?)(\d[\d.]*,\d{2})\s*€',
        text,
        flags=re.IGNORECASE,
    )
    for href, title_raw, _mid, pr_raw in matches[:8]:
        title = re.sub(r"\s+", " ", unescape(title_raw)).strip()
        pr = parse_price(pr_raw)
        if pr is not None and is_relevant(query, title):
            unit = extract_unit_from_text(title)
            res.append({
                "title": title[:200],
                "price": pr,
                "unit": unit,
                "unit_price": compute_unit_price(pr, unit),
                "url": urllib.parse.urljoin("https://www.auchan.pt/", href),
                "domain": "auchan.pt",
            })
    return res


async def default_fetch(session: aiohttp.ClientSession, url: str, timeout: int = 10) -> str:
    """Fetch an HTML page asynchronously."""
    import aiohttp

    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8",
    }
    async with session.get(
        url,
        headers=headers,
        timeout=aiohttp.ClientTimeout(total=timeout),
        allow_redirects=True,
    ) as resp:
        resp.raise_for_status()
        return await resp.text(errors="replace")


async def _search_duckduckgo_stores(
    query: str,
    fetch_fn: FetchAsyncFn,
    allowed_domains: set[str],
    country: str,
    skip_domains: set[str] | None = None,
) -> list[dict[str, Any]]:
    """Use DuckDuckGo Lite to discover product pages on supermarkets (Pingo Doce, Lidl, Aldi, etc.)."""
    q = urllib.parse.quote_plus(f"{query} supermercado preço")
    ddg_url = f"https://lite.duckduckgo.com/lite/?q={q}"
    try:
        html = await fetch_fn(ddg_url, 10)
    except Exception:
        return []
    raw_links: list[str] = []
    # DDG Lite wraps result links in //duckduckgo.com/l/?uddg=<url_encoded>
    for enc in re.findall(r'uddg=([^&"\']+)', html or ""):
        dec = urllib.parse.unquote(unescape(enc))
        if dec.startswith(("http://", "https://")):
            raw_links.append(dec)
    raw_links.extend(re.findall(r'href="(https?://[^"]+)"', html or ""))

    skip = skip_domains or set()
    candidate_urls: list[str] = []
    seen_domains: set[str] = set()
    for link in raw_links:
        dom = extract_domain(link)
        canon = canonical_supermarket(dom, country=country)
        if not canon:
            continue
        c_dom, _name = canon
        if c_dom in skip:
            continue
        if allowed_domains and c_dom not in allowed_domains:
            continue
        if c_dom in seen_domains:
            continue
        seen_domains.add(c_dom)
        candidate_urls.append(link)
        if len(candidate_urls) >= 5:
            break

    async def _fetch_page(u: str) -> list[dict[str, Any]]:
        try:
            page = await fetch_fn(u, 10)
        except Exception:
            return []
        return [o for o in extract_json_ld_offers(page, u) if is_relevant(query, o["title"])][:2]

    if not candidate_urls:
        return []
    results = await asyncio.gather(*(_fetch_page(u) for u in candidate_urls), return_exceptions=True)
    out: list[dict[str, Any]] = []
    for r in results:
        if isinstance(r, list):
            out.extend(r)
    return out


async def search_supermarkets(
    term: str,
    *,
    session: aiohttp.ClientSession | None = None,
    fetch_fn: FetchAsyncFn | None = None,
    country: str = DEFAULT_COUNTRY,
    enabled_supermarkets: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Search configured supermarkets in parallel and return cheapest offer per supermarket."""
    query = normalize_text(term)
    if not query:
        return []

    allowed = set(enabled_supermarkets or [])
    own_session = False
    if fetch_fn is None:
        if session is None:
            import aiohttp

            session = aiohttp.ClientSession()
            own_session = True
        sess = session

        async def _fetch(url: str, timeout: int = 10) -> str:
            return await default_fetch(sess, url, timeout)

        fetch_fn = _fetch

    try:
        q = urllib.parse.quote_plus(query)
        tasks: list[Awaitable[list[dict[str, Any]]]] = []
        direct_domains: set[str] = set()

        if country.upper() == "PT":
            if not allowed or "continente.pt" in allowed:
                direct_domains.add("continente.pt")

                async def _cont() -> list[dict[str, Any]]:
                    u = f"https://www.continente.pt/pesquisa/?q={q}"
                    try:
                        return extract_continente(await fetch_fn(u, 10), query, u)
                    except Exception:
                        return []
                tasks.append(_cont())

            if not allowed or "auchan.pt" in allowed:
                direct_domains.add("auchan.pt")

                async def _auchan() -> list[dict[str, Any]]:
                    u = f"https://www.auchan.pt/pt/pesquisa?q={q}"
                    try:
                        return extract_auchan(await fetch_fn(u, 10), query, u)
                    except Exception:
                        return []
                tasks.append(_auchan())

        tasks.append(_search_duckduckgo_stores(query, fetch_fn, allowed, country, skip_domains=direct_domains))
        batches = await asyncio.gather(*tasks, return_exceptions=True)

        by_store: dict[str, dict[str, Any]] = {}
        for batch in batches:
            if not isinstance(batch, list):
                continue
            for offer in batch:
                dom = offer.get("domain") or extract_domain(offer.get("url", ""))
                canon = canonical_supermarket(dom, country=country)
                if not canon:
                    continue
                c_dom, store_name = canon
                if allowed and c_dom not in allowed:
                    continue
                pr = parse_price(offer.get("price"))
                if pr is None:
                    continue
                title = str(offer.get("title") or term).strip()[:200]
                unit = str(offer.get("unit") or "").strip() or extract_unit_from_text(title)
                unit_price = str(offer.get("unit_price") or "").strip() or compute_unit_price(pr, unit)
                cand = {
                    "supermarket": store_name,
                    "store_domain": c_dom,
                    "title": title,
                    "price": pr,
                    "unit": unit,
                    "unit_price": unit_price,
                    "url": str(offer.get("url") or "").strip(),
                }
                cur = by_store.get(store_name)
                if cur is None or cand["price"] < cur["price"]:
                    by_store[store_name] = cand

        return sorted(by_store.values(), key=lambda x: (x["price"], x["supermarket"]))
    finally:
        if own_session and session is not None:
            await session.close()


def summarize_offers(
    term: str,
    offers: list[dict[str, Any]],
    currency: str = DEFAULT_CURRENCY,
) -> dict[str, Any]:
    """Compute min price, store, unit, direct URL, average price, and formatted tag."""
    if not offers:
        return {
            "term": term,
            "term_norm": normalize_text(term),
            "min_price": None,
            "min_store": "",
            "min_domain": "",
            "min_url": "",
            "min_unit": "",
            "min_unit_price": "",
            "avg_price": None,
            "store_count": 0,
            "tag": "",
            "offers": [],
        }
    enriched: list[dict[str, Any]] = []
    for o in offers:
        item = dict(o)
        pr = float(item["price"])
        unit = str(item.get("unit") or "").strip() or extract_unit_from_text(str(item.get("title") or ""))
        unit_price = str(item.get("unit_price") or "").strip() or compute_unit_price(pr, unit, currency=currency)
        item["unit"] = unit
        item["unit_price"] = unit_price
        enriched.append(item)
    ordered = sorted(enriched, key=lambda o: (float(o["price"]), o["supermarket"]))
    best = ordered[0]
    avg = round(sum(float(o["price"]) for o in ordered) / len(ordered), 2)
    return {
        "term": term,
        "term_norm": normalize_text(term),
        "min_price": round(float(best["price"]), 2),
        "min_store": best["supermarket"],
        "min_domain": best["store_domain"],
        "min_url": best.get("url") or "",
        "min_unit": best.get("unit") or "",
        "min_unit_price": best.get("unit_price") or "",
        "avg_price": avg,
        "store_count": len(ordered),
        "tag": format_price_tag(best["price"], best["supermarket"], currency=currency),
        "offers": ordered,
    }
