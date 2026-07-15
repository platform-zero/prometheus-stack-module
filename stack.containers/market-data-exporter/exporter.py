#!/usr/bin/env python3
import csv
from datetime import date, timedelta
import json
import os
import subprocess
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HTTP_TIMEOUT_SECONDS = float(os.environ.get("MARKET_DATA_HTTP_TIMEOUT_SECONDS", "8"))
CACHE_TTL_SECONDS = int(os.environ.get("MARKET_DATA_CACHE_TTL_SECONDS", "21600"))
FRED_LOOKBACK_DAYS = int(os.environ.get("MARKET_DATA_FRED_LOOKBACK_DAYS", "90"))

FRED_SERIES_BY_REGION = {
    "australia": {
        "SPASTT01AUM661N": "Australia Share Prices",
    },
    "china": {
        "SPASTT01CNM661N": "China Share Prices",
    },
    "europe": {
        "SPASTT01EZM661N": "Euro Area Share Prices",
        "SPASTT01DEM661N": "Germany Share Prices",
        "SPASTT01FRM661N": "France Share Prices",
        "SPASTT01GBM661N": "United Kingdom Share Prices",
    },
    "asia": {
        "SPASTT01JPM661N": "Japan Share Prices",
        "SPASTT01INM661N": "India Share Prices",
        "SPASTT01KRM661N": "Korea Share Prices",
    },
    "united_states": {
        "SP500": "S&P 500",
        "NASDAQCOM": "NASDAQ Composite",
        "DJIA": "Dow Jones Industrial Average",
        "DGS10": "10-Year Treasury Yield",
        "BAMLC0A0CM": "US Corporate AAA OAS",
        "VIXCLS": "VIX",
    },
    "global": {
        "DCOILWTICO": "WTI Crude Oil",
        "DCOILBRENTEU": "Brent Crude Oil",
    },
}

RBA_FX_SERIES = {
    "AUDUSD": ("A$1=USD", "AUD/USD"),
    "AUDTWI": ("Trade-weighted Index May 1970 = 100", "AUD Trade-Weighted Index"),
    "AUDCNY": ("A$1=CNY", "AUD/CNY"),
    "AUDJPY": ("A$1=JPY", "AUD/JPY"),
    "AUDEUR": ("A$1=EUR", "AUD/EUR"),
    "AUDGBP": ("A$1=GBP", "AUD/GBP"),
    "AUDNZD": ("A$1=NZD", "AUD/NZD"),
}

COINGECKO_ASSETS = {
    "bitcoin": "Bitcoin",
    "ethereum": "Ethereum",
}

FX_QUOTES = {
    "AUD": "USD/AUD",
    "CNY": "USD/CNY",
    "EUR": "USD/EUR",
    "GBP": "USD/GBP",
    "JPY": "USD/JPY",
    "CHF": "USD/CHF",
    "INR": "USD/INR",
    "KRW": "USD/KRW",
    "NZD": "USD/NZD",
    "SGD": "USD/SGD",
}

cache = {
    "updated_at": 0,
    "body": "",
    "healthy": False,
}


def env_map(name, defaults):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return defaults
    result = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" in item:
            key, label = item.split(":", 1)
        else:
            key, label = item, item
        result[key.strip()] = label.strip()
    return result or defaults


def env_region_map(name, defaults):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return defaults
    result = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        region = "custom"
        if "|" in item:
            region, item = item.split("|", 1)
        if ":" in item:
            key, label = item.split(":", 1)
        else:
            key, label = item, item
        result.setdefault(region.strip(), {})[key.strip()] = label.strip()
    return result or defaults


def fetch_text(url):
    result = subprocess.run(
        ["wget", "-q", "-T", str(int(HTTP_TIMEOUT_SECONDS)), "-O", "-", url],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=HTTP_TIMEOUT_SECONDS + 2,
    )
    return result.stdout


def metric_labels(labels):
    parts = []
    for key, value in labels.items():
        escaped = str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        parts.append(f'{key}="{escaped}"')
    return "{" + ",".join(parts) + "}"


def metric_line(name, labels, value):
    return f"{name}{metric_labels(labels)} {value}"


def market_labels(region, source, symbol, label):
    return {
        "region": region,
        "source": source,
        "symbol": symbol,
        "label": label,
    }


def emit_market_metrics(lines, labels, latest, previous, reported_timestamp):
    change = latest - previous
    pct_change = (change / previous * 100) if previous else 0
    lines.append(metric_line("market_data_latest_value", labels, latest))
    lines.append(metric_line("market_data_previous_value", labels, previous))
    lines.append(metric_line("market_data_daily_change", labels, change))
    lines.append(metric_line("market_data_daily_change_percent", labels, pct_change))
    lines.append(metric_line("market_data_reported_timestamp_seconds", labels, reported_timestamp))
    lines.append(metric_line("market_data_source_up", labels, 1))


def parse_date(date_value):
    for fmt in ("%Y-%m-%d", "%d-%b-%Y"):
        try:
            return int(time.mktime(time.strptime(date_value, fmt)))
        except ValueError:
            continue
    return 0


def latest_fred_points(series_id):
    start = (date.today() - timedelta(days=FRED_LOOKBACK_DAYS)).isoformat()
    query = urllib.parse.urlencode({"id": series_id, "cosd": start})
    text = fetch_text(f"https://fred.stlouisfed.org/graph/fredgraph.csv?{query}")
    rows = []
    for row in csv.DictReader(text.splitlines()):
        date_value = row.get("observation_date", "")
        value = row.get(series_id, "")
        if date_value and value not in ("", "."):
            rows.append((date_value, float(value)))
    return rows[-2:]


def collect_fred(lines, errors):
    region_series = env_region_map("MARKET_DATA_FRED_SERIES", FRED_SERIES_BY_REGION)
    for region, series in region_series.items():
        for symbol, label in series.items():
            labels = market_labels(region, "fred", symbol, label)
            try:
                points = latest_fred_points(symbol)
                if not points:
                    raise RuntimeError("no observations returned")
                latest_date, latest = points[-1]
                previous = points[-2][1] if len(points) > 1 else latest
                emit_market_metrics(lines, labels, latest, previous, parse_date(latest_date))
            except Exception as exc:
                errors.append(f"fred:{symbol}:{exc}")
                lines.append(metric_line("market_data_source_up", labels, 0))


def collect_rba_fx(lines, errors):
    series = env_map("MARKET_DATA_RBA_FX_SERIES", RBA_FX_SERIES)
    labels_by_title = {title: (symbol, label) for symbol, (title, label) in series.items()}
    try:
        text = fetch_text("https://www.rba.gov.au/statistics/tables/csv/f11.1-data.csv").lstrip("\ufeff")
        rows = list(csv.reader(text.splitlines()))
        titles = next(row for row in rows if row and row[0] == "Title")
        data_rows = [
            row for row in rows
            if row and len(row) == len(titles) and row[0][:2].isdigit() and "-" in row[0]
        ]
    except Exception as exc:
        errors.append(f"rba:{exc}")
        for symbol, (_, label) in series.items():
            labels = market_labels("australia", "rba", symbol, label)
            lines.append(metric_line("market_data_source_up", labels, 0))
        return

    for index, title in enumerate(titles):
        if title not in labels_by_title:
            continue
        symbol, label = labels_by_title[title]
        labels = market_labels("australia", "rba", symbol, label)
        values = []
        for row in data_rows:
            value = row[index].strip() if index < len(row) else ""
            if value:
                values.append((row[0], float(value)))
        if not values:
            lines.append(metric_line("market_data_source_up", labels, 0))
            continue
        latest_date, latest = values[-1]
        previous = values[-2][1] if len(values) > 1 else latest
        emit_market_metrics(lines, labels, latest, previous, parse_date(latest_date))


def collect_crypto(lines, errors):
    assets = env_map("MARKET_DATA_COINGECKO_ASSETS", COINGECKO_ASSETS)
    ids = ",".join(assets.keys())
    query = urllib.parse.urlencode({
        "ids": ids,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
    })
    try:
        payload = json.loads(fetch_text(f"https://api.coingecko.com/api/v3/simple/price?{query}"))
    except Exception as exc:
        errors.append(f"coingecko:{exc}")
        payload = {}
    now = int(time.time())
    for asset_id, label in assets.items():
        labels = market_labels("crypto", "coingecko", asset_id, label)
        data = payload.get(asset_id) or {}
        value = data.get("usd")
        pct_change = data.get("usd_24h_change")
        if value is None:
            lines.append(metric_line("market_data_source_up", labels, 0))
            continue
        change = value * pct_change / 100 if pct_change is not None else 0
        previous = value - change
        emit_market_metrics(lines, labels, value, previous, now)


def collect_fx(lines, errors):
    quotes = env_map("MARKET_DATA_FX_QUOTES", FX_QUOTES)
    symbols = ",".join(quotes.keys())
    query = urllib.parse.urlencode({"from": "USD", "to": symbols})
    try:
        payload = json.loads(fetch_text(f"https://api.frankfurter.app/latest?{query}"))
    except Exception as exc:
        errors.append(f"frankfurter:{exc}")
        payload = {}
    timestamp = parse_date(payload.get("date", ""))
    rates = payload.get("rates") or {}
    for symbol, label in quotes.items():
        region = {
            "AUD": "australia",
            "CNY": "china",
            "EUR": "europe",
            "GBP": "europe",
            "JPY": "asia",
            "CHF": "europe",
            "INR": "asia",
            "KRW": "asia",
            "NZD": "australia",
            "SGD": "asia",
        }.get(symbol, "global_fx")
        labels = market_labels(region, "frankfurter", f"USD{symbol}", label)
        value = rates.get(symbol)
        if value is None:
            lines.append(metric_line("market_data_source_up", labels, 0))
            continue
        emit_market_metrics(lines, labels, value, value, timestamp)


def render_metrics():
    lines = [
        "# HELP market_data_latest_value Latest market value reported by the source.",
        "# TYPE market_data_latest_value gauge",
        "# HELP market_data_previous_value Previous daily market value reported by the source.",
        "# TYPE market_data_previous_value gauge",
        "# HELP market_data_daily_change Latest minus previous market value.",
        "# TYPE market_data_daily_change gauge",
        "# HELP market_data_daily_change_percent Daily market move in percent.",
        "# TYPE market_data_daily_change_percent gauge",
        "# HELP market_data_reported_timestamp_seconds Source-reported observation timestamp.",
        "# TYPE market_data_reported_timestamp_seconds gauge",
        "# HELP market_data_source_up Whether the market data source was collected successfully.",
        "# TYPE market_data_source_up gauge",
    ]
    errors = []
    collect_fred(lines, errors)
    collect_rba_fx(lines, errors)
    collect_crypto(lines, errors)
    collect_fx(lines, errors)
    lines.append(metric_line("market_data_exporter_last_scrape_timestamp_seconds", {}, int(time.time())))
    lines.append(metric_line("market_data_exporter_scrape_errors_total", {}, len(errors)))
    for index, error in enumerate(errors):
        lines.append(metric_line("market_data_exporter_scrape_error", {"index": index, "error": error}, 1))
    return "\n".join(lines) + "\n", not errors


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/healthz", "/-/ready"):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"ok\n" if cache["healthy"] or not cache["body"] else b"degraded\n")
            return
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return

        now = int(time.time())
        if now - cache["updated_at"] > CACHE_TTL_SECONDS or not cache["body"]:
            cache["body"], cache["healthy"] = render_metrics()
            cache["updated_at"] = now

        body = cache["body"].encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}", flush=True)


if __name__ == "__main__":
    port = int(os.environ.get("MARKET_DATA_EXPORTER_PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    print(f"market-data-exporter listening on :{port}", flush=True)
    server.serve_forever()

