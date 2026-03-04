#!/usr/bin/env python3
"""Ferramenta simples para analisar dados de um anúncio da Shopee.

Extração principal:
- Data de criação do anúncio (quando disponível como `ctime` no JSON da página)
- Unidades vendidas (`historical_sold`/`sold`)
- Média de vendas por dia e por mês
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from dataclasses import dataclass
from typing import Any, Iterable

from urllib import error as urlerror
from urllib.request import Request, urlopen


@dataclass
class ProductMetrics:
    url: str
    name: str | None
    created_at: dt.datetime | None
    sold_units: int | None
    avg_per_day: float | None
    avg_per_month: float | None


def fetch_html(url: str, timeout: int = 20) -> str:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
    }
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def extract_json_payloads(html: str) -> Iterable[dict[str, Any]]:
    # 1) Next.js payload
    next_data_match = re.search(
        r'<script[^>]*id="__NEXT_DATA__"[^>]*>(?P<data>.*?)</script>',
        html,
        re.DOTALL,
    )
    if next_data_match:
        raw = next_data_match.group("data").strip()
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                yield parsed
        except json.JSONDecodeError:
            pass

    # 2) window.__INITIAL_STATE__ payload
    state_match = re.search(
        r"window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*;",
        html,
        re.DOTALL,
    )
    if state_match:
        raw = state_match.group(1).strip()
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                yield parsed
        except json.JSONDecodeError:
            pass


def walk_json(data: Any):
    if isinstance(data, dict):
        yield data
        for value in data.values():
            yield from walk_json(value)
    elif isinstance(data, list):
        for item in data:
            yield from walk_json(item)


def find_first_int(payloads: Iterable[dict[str, Any]], keys: tuple[str, ...]) -> int | None:
    for payload in payloads:
        for node in walk_json(payload):
            for key in keys:
                value = node.get(key)
                if isinstance(value, int):
                    return value
                if isinstance(value, str) and value.isdigit():
                    return int(value)
    return None


def find_first_str(payloads: Iterable[dict[str, Any]], keys: tuple[str, ...]) -> str | None:
    for payload in payloads:
        for node in walk_json(payload):
            for key in keys:
                value = node.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return None


def compute_metrics(url: str, now: dt.datetime | None = None) -> ProductMetrics:
    now = now or dt.datetime.now(dt.timezone.utc)
    html = fetch_html(url)
    payloads = list(extract_json_payloads(html))

    # Campos comuns na Shopee
    ctime = find_first_int(payloads, ("ctime", "create_time", "created_time"))
    sold = find_first_int(payloads, ("historical_sold", "sold", "sold_count"))
    name = find_first_str(payloads, ("name", "item_name", "title"))

    created_at = None
    avg_per_day = None
    avg_per_month = None

    if ctime:
        created_at = dt.datetime.fromtimestamp(ctime, tz=dt.timezone.utc)

    if created_at and sold is not None:
        days = max((now - created_at).days, 1)
        avg_per_day = sold / days
        avg_per_month = avg_per_day * 30

    return ProductMetrics(
        url=url,
        name=name,
        created_at=created_at,
        sold_units=sold,
        avg_per_day=avg_per_day,
        avg_per_month=avg_per_month,
    )


def format_output(metrics: ProductMetrics) -> str:
    lines = ["=== Análise Shopee ===", f"URL: {metrics.url}"]
    lines.append(f"Produto: {metrics.name or 'não identificado'}")

    if metrics.created_at:
        lines.append(
            "Data de criação do anúncio: "
            + metrics.created_at.astimezone().strftime("%d/%m/%Y %H:%M:%S %Z")
        )
    else:
        lines.append("Data de criação do anúncio: não encontrada")

    if metrics.sold_units is not None:
        lines.append(f"Unidades vendidas: {metrics.sold_units}")
    else:
        lines.append("Unidades vendidas: não encontradas")

    if metrics.avg_per_day is not None and metrics.avg_per_month is not None:
        lines.append(f"Média de vendas por dia: {metrics.avg_per_day:.2f}")
        lines.append(f"Média de vendas por mês (~30d): {metrics.avg_per_month:.2f}")
    else:
        lines.append("Média de vendas: não foi possível calcular")

    lines.append(
        "\nObs.: A Shopee pode bloquear scraping ou mudar o formato da página, "
        "o que pode impedir a extração de dados."
    )
    return "\n".join(lines)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Analisa métricas básicas de um produto da Shopee via URL."
    )
    parser.add_argument("url", help="URL do produto na Shopee")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        metrics = compute_metrics(args.url)
        print(format_output(metrics))
        return 0
    except urlerror.HTTPError as exc:
        print(f"Erro HTTP ao acessar a Shopee: {exc}", file=sys.stderr)
    except urlerror.URLError as exc:
        print(f"Erro de rede ao acessar a Shopee: {exc}", file=sys.stderr)
    except Exception as exc:  # pragma: no cover
        print(f"Erro inesperado: {exc}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
