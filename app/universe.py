"""Market universe: every tradable US equity, with a sector tag.

Primary source is Alpaca's /v2/assets (us_equity, active, tradable). Because the
free feed carries no sector, we classify with a curated map first, then keyword
heuristics, else "Other". A large built-in fallback list keeps DEMO / offline
mode fully functional.
"""
from __future__ import annotations

import re
from typing import Any

from . import storage
from .alpaca import AlpacaBroker, Broker

_GOOD_EXCHANGES = {"NYSE", "NASDAQ", "ARCA", "AMEX", "BATS", "NYSEARCA", "NASDAQGS", "NASDAQGM", "NASDAQCM"}

# ~220 liquid / well-known tickers -> sector (curated beats heuristics)
SECTOR_MAP: dict[str, str] = {
    # Technology
    "AAPL": "Technology", "MSFT": "Technology", "NVDA": "Technology", "AMD": "Technology",
    "INTC": "Technology", "AVGO": "Technology", "QCOM": "Technology", "TXN": "Technology",
    "MU": "Technology", "AMAT": "Technology", "LRCX": "Technology", "ADI": "Technology",
    "KLAC": "Technology", "MRVL": "Technology", "NXPI": "Technology", "ON": "Technology",
    "SMCI": "Technology", "ARM": "Technology", "TSM": "Technology", "ASML": "Technology",
    "CRM": "Technology", "ORCL": "Technology", "ADBE": "Technology", "NOW": "Technology",
    "SNOW": "Technology", "PANW": "Technology", "CRWD": "Technology", "ZS": "Technology",
    "DDOG": "Technology", "NET": "Technology", "TEAM": "Technology", "WDAY": "Technology",
    "INTU": "Technology", "IBM": "Technology", "CSCO": "Technology", "ACN": "Technology",
    "SHOP": "Technology", "SQ": "Technology", "PYPL": "Technology", "UBER": "Technology",
    "PLTR": "Technology", "DELL": "Technology", "HPQ": "Technology", "HPE": "Technology",
    "MSTR": "Technology", "COIN": "Financials",
    # Communication / Media
    "GOOGL": "Communication", "GOOG": "Communication", "META": "Communication",
    "NFLX": "Communication", "DIS": "Communication", "CMCSA": "Communication",
    "T": "Communication", "VZ": "Communication", "TMUS": "Communication", "ATVI": "Communication",
    "EA": "Communication", "TTWO": "Communication", "SPOT": "Communication", "PINS": "Communication",
    "SNAP": "Communication", "ROKU": "Communication", "WBD": "Communication", "PARA": "Communication",
    # Consumer discretionary
    "AMZN": "Consumer Disc.", "TSLA": "Consumer Disc.", "HD": "Consumer Disc.", "LOW": "Consumer Disc.",
    "NKE": "Consumer Disc.", "SBUX": "Consumer Disc.", "MCD": "Consumer Disc.", "BKNG": "Consumer Disc.",
    "ABNB": "Consumer Disc.", "GM": "Consumer Disc.", "F": "Consumer Disc.", "RIVN": "Consumer Disc.",
    "LCID": "Consumer Disc.", "NIO": "Consumer Disc.", "LULU": "Consumer Disc.", "TGT": "Consumer Disc.",
    "DG": "Consumer Disc.", "ROST": "Consumer Disc.", "EBAY": "Consumer Disc.", "ETSY": "Consumer Disc.",
    "DASH": "Consumer Disc.", "MAR": "Consumer Disc.", "HLT": "Consumer Disc.", "CCL": "Consumer Disc.",
    "DAL": "Industrials", "UAL": "Industrials", "AAL": "Industrials", "LUV": "Industrials",
    # Consumer staples
    "WMT": "Consumer Staples", "COST": "Consumer Staples", "PG": "Consumer Staples",
    "KO": "Consumer Staples", "PEP": "Consumer Staples", "PM": "Consumer Staples",
    "MO": "Consumer Staples", "CL": "Consumer Staples", "MDLZ": "Consumer Staples",
    "TGT2": "Consumer Staples",
    # Financials
    "JPM": "Financials", "BAC": "Financials", "WFC": "Financials", "C": "Financials",
    "GS": "Financials", "MS": "Financials", "BLK": "Financials", "SCHW": "Financials",
    "AXP": "Financials", "V": "Financials", "MA": "Financials", "BRK.B": "Financials",
    "PGR": "Financials", "USB": "Financials", "PNC": "Financials", "TFC": "Financials",
    "SOFI": "Financials", "HOOD": "Financials", "SCHW2": "Financials",
    # Healthcare
    "UNH": "Healthcare", "JNJ": "Healthcare", "LLY": "Healthcare", "PFE": "Healthcare",
    "MRK": "Healthcare", "ABBV": "Healthcare", "TMO": "Healthcare", "ABT": "Healthcare",
    "DHR": "Healthcare", "BMY": "Healthcare", "AMGN": "Healthcare", "GILD": "Healthcare",
    "CVS": "Healthcare", "MDT": "Healthcare", "ISRG": "Healthcare", "REGN": "Healthcare",
    "VRTX": "Healthcare", "MRNA": "Healthcare", "BNTX": "Healthcare", "BIIB": "Healthcare",
    "HUM": "Healthcare", "CI": "Healthcare", "ELV": "Healthcare",
    # Energy
    "XOM": "Energy", "CVX": "Energy", "COP": "Energy", "SLB": "Energy", "EOG": "Energy",
    "OXY": "Energy", "PSX": "Energy", "VLO": "Energy", "MPC": "Energy", "KMI": "Energy",
    "WMB": "Energy", "HES": "Energy", "HAL": "Energy", "DVN": "Energy", "FANG": "Energy",
    "MRO": "Energy", "APA": "Energy",
    # Industrials
    "BA": "Industrials", "CAT": "Industrials", "GE": "Industrials", "HON": "Industrials",
    "UPS": "Industrials", "RTX": "Industrials", "LMT": "Industrials", "DE": "Industrials",
    "MMM": "Industrials", "UNP": "Industrials", "CSX": "Industrials", "NSC": "Industrials",
    "FDX": "Industrials", "EMR": "Industrials", "ETN": "Industrials", "ITW": "Industrials",
    "GD": "Industrials", "NOC": "Industrials", "PH": "Industrials", "UBER2": "Industrials",
    # Materials
    "LIN": "Materials", "APD": "Materials", "SHW": "Materials", "FCX": "Materials",
    "NEM": "Materials", "DOW": "Materials", "NUE": "Materials", "ALB": "Materials",
    "DOW2": "Materials",
    # Utilities / Real estate
    "NEE": "Utilities", "DUK": "Utilities", "SO": "Utilities", "D": "Utilities",
    "AEP": "Utilities", "EXC": "Utilities", "XEL": "Utilities",
    "AMT": "Real Estate", "PLD": "Real Estate", "SPG": "Real Estate", "O": "Real Estate",
    "PSA": "Real Estate", "CCI": "Real Estate", "EQIX": "Real Estate", "DLR": "Real Estate",
    # ETFs / indices
    "SPY": "ETF", "QQQ": "ETF", "IWM": "ETF", "DIA": "ETF", "VTI": "ETF", "VOO": "ETF",
    "ARKK": "ETF", "XLK": "ETF", "XLF": "ETF", "XLE": "ETF", "XLV": "ETF", "XLY": "ETF",
    "XLP": "ETF", "XLI": "ETF", "XLB": "ETF", "XLU": "ETF", "XLRE": "ETF", "XLC": "ETF",
    "GLD": "ETF", "SLV": "ETF", "USO": "ETF", "TLT": "ETF", "HYG": "ETF", "LQD": "ETF",
    "SOXX": "ETF", "SMH": "ETF", "SQQQ": "ETF", "TQQQ": "ETF", "SPXL": "ETF", "VIX": "Index",
    "IBIT": "ETF", "BITO": "ETF",
}

_SECTOR_KEYWORDS = [
    ("ETF", ("etf", "ishares", "spdr", "invesco", "vanguard", "proshares", "direxion",
             "wisdomtree", "index fund", "exchange traded", "etn", "closed-end", "closed end")),
    ("Financials", ("bancorp", "bancshares", "bank", "financial", "capital", "holdings corp", "insur", "mortgage", "credit")),
    ("Healthcare", ("pharma", "therapeut", "biotech", "bioscien", "medical", "health", "hospital", "genomic", "oncology")),
    ("Energy", ("energy", "petroleum", "oil", "gas", "drilling", "refin", "resources")),
    ("Technology", ("technolog", "software", "semiconductor", "semicond", "digital", "cyber", "systems", "solutions", "comput", "data", "cloud", "ai ", "artificial")),
    ("Materials", ("mining", "metals", "steel", "chemical", "materials", "gold", "lithium", "copper")),
    ("Utilities", ("utilities", "electric", "power", "water")),
    ("Real Estate", ("reit", "realty", "properties", "real estate")),
    ("Industrials", ("industries", "industrial", "aerospace", "defense", "machinery", "logistics", "airlines", "manufactur")),
    ("Consumer Disc.", ("restaurant", "retail", "apparel", "motors", "hotels", "resorts", "travel", "foods2")),
    ("Consumer Staples", ("beverages", "foods", "consumer products", "household")),
    ("Communication", ("media", "entertainment", "telecom", "communications", "broadcast")),
]


def classify(symbol: str, name: str | None = None) -> str:
    sym = (symbol or "").upper()
    if sym in SECTOR_MAP:
        return SECTOR_MAP[sym]
    nm = (name or "").lower()
    for sector, keys in _SECTOR_KEYWORDS:
        if any(k in nm for k in keys):
            return sector
    return "Other"


# large fallback universe (~360 liquid names) used when Alpaca is unavailable
FALLBACK: list[str] = sorted(set(SECTOR_MAP.keys()) | {
    "A", "AA", "AAL", "AAP", "ABNB", "ABT", "ACN", "ADBE", "ADI", "ADP", "ADSK", "AEP",
    "AIG", "AMAT", "AMC", "AMGN", "AMT", "AMZN", "ANET", "APA", "APD", "APO", "APTV", "ARM",
    "ASML", "ATVI", "AVGO", "AXP", "AZN", "BA", "BAC", "BABA", "BBY", "BIDU", "BIIB", "BK",
    "BKNG", "BLK", "BMY", "BRK.B", "BSX", "BXP", "C", "CAG", "CAT", "CB", "CCI", "CCL",
    "CDNS", "CDW", "CE", "CF", "CHTR", "CL", "CMCSA", "CMG", "COF", "COIN", "COP", "COST",
    "CRM", "CRWD", "CSCO", "CSX", "CTAS", "CVNA", "CVS", "CVX", "D", "DAL", "DASH", "DDOG",
    "DE", "DELL", "DG", "DHI", "DHR", "DIS", "DKNG", "DLR", "DOCU", "DOW", "DRI", "DDOG",
    "EA", "EBAY", "ELV", "EMR", "ENPH", "EOG", "EQIX", "ETN", "ETSY", "EXC", "F", "FANG",
    "FAST", "FCX", "FDX", "FIS", "FITB", "FSLR", "GD", "GE", "GILD", "GM", "GOOG", "GOOGL",
    "GS", "HD", "HES", "HON", "HOOD", "HPQ", "HUM", "IBM", "ICE", "INTC", "INTU", "ISRG",
    "JNJ", "JPM", "KHC", "KLAC", "KMI", "KO", "LCID", "LIN", "LLY", "LMT", "LOW", "LRCX",
    "LULU", "LUV", "MA", "MAR", "MCD", "MDB", "MDLZ", "MDT", "MELI", "META", "MMM", "MO",
    "MPC", "MRK", "MRNA", "MRO", "MRVL", "MS", "MSFT", "MU", "NEE", "NEM", "NFLX", "NIO",
    "NKE", "NOC", "NOW", "NSC", "NUE", "NVDA", "NXPI", "O", "ODFL", "ON", "ORCL", "OXY",
    "PANW", "PARA", "PCAR", "PEP", "PFE", "PG", "PGR", "PH", "PINS", "PLD", "PLTR", "PM",
    "PNC", "PSA", "PSX", "PYPL", "QCOM", "REGN", "RIVN", "ROKU", "ROST", "RTX", "SBUX",
    "SCHW", "SHOP", "SHW", "SLB", "SNAP", "SNOW", "SO", "SOFI", "SPG", "SPOT", "SQ", "TEAM",
    "TGT", "TMO", "TMUS", "TSLA", "TSM", "TTWO", "TXN", "T", "UBER", "UAL", "UNH", "UNP",
    "UPS", "USB", "V", "VLO", "VRTX", "VZ", "WBD", "WDAY", "WFC", "WMB", "WMT", "XEL",
    "XOM", "ZS", "XPEV", "LI", "BIDU", "JD", "PDD", "BABA", "TSM", "SE", "GRAB", "CPNG",
})


def _is_clean_symbol(sym: str) -> bool:
    if not sym or len(sym) > 5:
        return False
    if not re.fullmatch(r"[A-Z]+(\.[A-Z])?", sym):
        return False
    return True


_BAD_NAME = ("warrant", "unit", "right", "acquisition", "preferred", "when issued",
             "depositary", "%", "notes due")


async def load_from_alpaca(broker: Broker) -> int:
    """Fetch every tradable US equity from Alpaca and cache it."""
    if not isinstance(broker, AlpacaBroker):
        return 0
    from .config import settings
    raw = await broker._get(settings.trading_base, "/v2/assets",
                            status="active", asset_class="us_equity")
    rows: list[dict[str, Any]] = []
    for a in raw:
        sym = (a.get("symbol") or "").upper()
        name = a.get("name") or ""
        if not a.get("tradable") or a.get("exchange") not in _GOOD_EXCHANGES:
            continue
        if not _is_clean_symbol(sym):
            continue
        if any(b in name.lower() for b in _BAD_NAME):
            continue
        sector = classify(sym, name)
        if sector == "Other" and a.get("exchange") in ("ARCA", "NYSEARCA", "BATS"):
            sector = "ETF"
        rows.append({
            "symbol": sym, "name": name, "exchange": a.get("exchange"),
            "tradable": True, "fractionable": a.get("fractionable"),
            "shortable": a.get("shortable"), "sector": sector,
        })
    if rows:
        storage.replace_universe(rows)
    return len(rows)


def load_fallback() -> int:
    rows = [{"symbol": s, "name": s, "exchange": "NASDAQ", "tradable": True,
             "fractionable": True, "shortable": True, "sector": classify(s, s)} for s in FALLBACK]
    storage.replace_universe(rows)
    return len(rows)


async def ensure_universe(broker: Broker, *, force: bool = False) -> int:
    """Populate the universe cache if empty (or when forced)."""
    if force or storage.universe_count() == 0:
        n = 0
        try:
            n = await load_from_alpaca(broker)
        except Exception:  # noqa: BLE001
            n = 0
        if n == 0:
            n = load_fallback()
        return n
    return storage.universe_count()


def settings_trading(broker: AlpacaBroker) -> str:
    from .config import settings
    return settings.trading_base


def sector_breakdown() -> dict[str, int]:
    out: dict[str, int] = {}
    for r in storage.get_universe():
        out[r.get("sector") or "Other"] = out.get(r.get("sector") or "Other", 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))
