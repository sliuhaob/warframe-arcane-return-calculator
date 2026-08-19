#!/usr/bin/env python3
"""Fetch 48-hour max-rank Arcane prices and calculate collection returns.

Uses Warframe.market's public APIs and only Python's standard library.
"""

from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


API_BASE = "https://api.warframe.market/v2"
STATS_API_BASE = "https://api.warframe.market/v1"
FANDOM_API_BASE = "https://warframe.fandom.com/api.php"
FANDOM_DISSOLUTION_DATA_TITLE = "Module:Arcane/data"
USER_AGENT = "WarframeArcaneReturnCalculator/1.0 (+https://github.com/sliuhaob/warframe-arcane-return-calculator)"
ARCANE_TAG = "arcane_enhancement"
DEFAULT_MIN_DAILY_VOLUME = 10
SECONDARY_FILTER_MIN_DAILY_VOLUME = 10
SECONDARY_FILTER_MAX_DAILY_VOLUME = 20
SECONDARY_FILTER_MIN_AVERAGE_PRICE = 80.0
PACK_COST_VOSFOR = 200
PACK_COST_CREDITS = 50_000
PACK_DRAWS = 3
CACHE_MAX_AGE_SECONDS = 24 * 60 * 60
# Official public limit is 3 requests/second. 0.4 s leaves a safety margin.
MIN_REQUEST_INTERVAL_SECONDS = 0.4
PLATFORMS = ("pc", "ps4", "xbox", "switch", "mobile")
ITEM_LANGUAGE = "zh-hans"

# The current public wiki data predates these three Höllvania legendary Arcanes.
# They use the 84-Vosfor legendary value used by the other non-Eidolon legendary
# Arcane Collection rewards. Exact values from the wiki data always take priority.
DISSOLUTION_VOSFOR_OVERRIDES_BY_SLUG = {
    "arcane_escapist": 84,
    "arcane_hot_shot": 84,
    "arcane_universal_fallout": 84,
}


class ApiError(RuntimeError):
    """Raised when Warframe.market returns an unusable response."""


@dataclass
class PriceRow:
    name_zh: str
    name_en: str
    slug: str
    game_ref: str
    max_rank: int
    dissolution_vosfor: int
    average_price_48h: float | None
    volume_48h: int
    statistics_48h_start: str
    statistics_48h_end: str
    latest_daily_volume: int
    volume_date: str
    item_url: str
    fetched_at: str


@dataclass(frozen=True)
class PackTier:
    name_zh: str
    probability: float
    slugs: tuple[str, ...]


@dataclass(frozen=True)
class ArcanePack:
    name_zh: str
    name_en: str
    tiers: tuple[PackTier, ...]


@dataclass
class PackItemResult:
    pack_name_zh: str
    pack_name_en: str
    tier_name_zh: str
    slug: str
    probability_per_draw: float
    expected_quantity_per_pack: float
    copies_to_max: int
    valuation_method: str
    market_unit_equivalent_price: float
    dissolution_vosfor: int
    recycle_unit_equivalent_price: float
    unit_equivalent_price: float
    expected_platinum_contribution: float


@dataclass
class PackSummary:
    rank: int
    pack_name_zh: str
    pack_name_en: str
    arcane_count: int
    priced_count: int
    volume_qualified_count: int
    min_daily_volume: int
    direct_market_platinum_per_pack: float
    recycling_pack_fraction: float
    recycling_platinum_per_pack: float
    recycle_target_pack_name_zh: str
    recycle_value_per_200_vosfor: float
    expected_platinum_per_pack: float
    expected_platinum_per_1000_vosfor: float
    p10_platinum_per_pack: float
    median_platinum_per_pack: float
    p90_platinum_per_pack: float
    maximum_platinum_per_pack: float
    legendary_chance_per_pack: float
    relative_return_index: float
    fetched_at: str


PACKS: tuple[ArcanePack, ...] = (
    ArcanePack(
        "科维兽赋能组合包",
        "Cavia Arcane Collection",
        (
            PackTier("低稀有度", 0.45, ("melee_fortification", "melee_retaliation")),
            PackTier(
                "稀有",
                0.50,
                (
                    "arcane_battery",
                    "arcane_ice_storm",
                    "secondary_fortifier",
                    "secondary_surge",
                    "melee_afflictions",
                    "melee_animosity",
                    "melee_exposure",
                    "melee_influence",
                    "melee_vortex",
                ),
            ),
            PackTier("传奇", 0.05, ("melee_crescendo", "melee_duplicate")),
        ),
    ),
    ArcanePack(
        "双衍王境赋能组合包",
        "Duviri Arcane Collection",
        (
            PackTier("低稀有度", 0.45, ("arcane_intention", "magus_aggress")),
            PackTier(
                "稀有",
                0.50,
                (
                    "arcane_power_ramp",
                    "primary_blight",
                    "primary_exhilarate",
                    "primary_obstruct",
                    "shotgun_vendetta",
                    "akimbo_slip_shot",
                    "secondary_outburst",
                ),
            ),
            PackTier("传奇", 0.05, ("arcane_reaper", "longbow_sharpshot", "secondary_shiver")),
        ),
    ),
    ArcanePack(
        "夜灵赋能组合包",
        "Eidolon Arcane Collection",
        (
            PackTier(
                "普通",
                0.40,
                (
                    "arcane_consequence",
                    "arcane_ice",
                    "arcane_momentum",
                    "arcane_nullifier",
                    "arcane_tempo",
                    "arcane_warmth",
                ),
            ),
            PackTier(
                "罕见",
                0.35,
                (
                    "arcane_acceleration",
                    "arcane_agility",
                    "arcane_awakening",
                    "arcane_deflection",
                    "arcane_eruption",
                    "arcane_guardian",
                    "arcane_healing",
                    "arcane_phantasm",
                    "arcane_resistance",
                    "arcane_strike",
                    "arcane_trickery",
                    "arcane_velocity",
                    "arcane_victory",
                ),
            ),
            PackTier(
                "稀有",
                0.20,
                (
                    "arcane_aegis",
                    "arcane_arachne",
                    "arcane_avenger",
                    "arcane_fury",
                    "arcane_precision",
                    "arcane_pulse",
                    "arcane_rage",
                    "arcane_ultimatum",
                ),
            ),
            PackTier("传奇", 0.05, ("arcane_barrier", "arcane_energize", "arcane_grace")),
        ),
    ),
    ArcanePack(
        "坚守者赋能组合包",
        "Holdfasts Arcane Collection",
        (
            PackTier(
                "稀有",
                1.0,
                (
                    "arcane_blessing",
                    "arcane_rise",
                    "molt_augmented",
                    "molt_efficiency",
                    "molt_reconstruct",
                    "molt_vigor",
                    "fractalized_reset",
                    "primary_frostbite",
                    "cascadia_accuracy",
                    "cascadia_empowered",
                    "cascadia_flare",
                    "cascadia_overcharge",
                    "conjunction_voltage",
                    "emergence_dissipate",
                    "emergence_renewed",
                    "emergence_savior",
                    "eternal_eradicate",
                    "eternal_logistics",
                    "eternal_onslaught",
                ),
            ),
        ),
    ),
    ArcanePack(
        "殁世幽都赋能组合包",
        "Necralisk Arcane Collection",
        (
            PackTier(
                "稀有",
                1.0,
                (
                    "arcane_double_back",
                    "arcane_steadfast",
                    "theorem_contagion",
                    "theorem_demulcent",
                    "theorem_infection",
                    "primary_plated_round",
                    "secondary_encumber",
                    "secondary_kinship",
                    "residual_boils",
                    "residual_malodor",
                    "residual_shock",
                    "residual_viremia",
                ),
            ),
        ),
    ),
    ArcanePack(
        "奥斯唐赋能组合包",
        "Ostron Arcane Collection",
        (
            PackTier("普通", 0.10, ("magus_husk", "magus_vigor", "virtuos_null", "virtuos_tempo")),
            PackTier(
                "罕见",
                0.30,
                (
                    "exodia_triumph",
                    "exodia_valor",
                    "magus_cadence",
                    "magus_cloud",
                    "magus_replenish",
                    "virtuos_fury",
                    "virtuos_strike",
                ),
            ),
            PackTier(
                "稀有",
                0.60,
                (
                    "exodia_brave",
                    "exodia_force",
                    "exodia_hunt",
                    "exodia_might",
                    "magus_elevate",
                    "magus_nourish",
                    "virtuos_ghost",
                    "virtuos_shadow",
                ),
            ),
        ),
    ),
    ArcanePack(
        "索拉里斯赋能组合包",
        "Solaris Arcane Collection",
        (
            PackTier(
                "普通",
                0.15,
                (
                    "magus_accelerant",
                    "magus_anomaly",
                    "magus_drive",
                    "magus_firewall",
                    "magus_overload",
                    "virtuos_spike",
                    "virtuos_surge",
                ),
            ),
            PackTier("罕见", 0.15, ("magus_glitch", "magus_repair", "virtuos_forge", "virtuos_trojan")),
            PackTier(
                "稀有",
                0.70,
                (
                    "pax_bolt",
                    "pax_charge",
                    "pax_seeker",
                    "pax_soar",
                    "magus_destruct",
                    "magus_lockdown",
                    "magus_melt",
                    "magus_revert",
                ),
            ),
        ),
    ),
    ArcanePack(
        "钢铁赋能组合包（仲裁）",
        "Steel Arcane Collection",
        (
            PackTier(
                "稀有",
                1.0,
                (
                    "arcane_blade_charger",
                    "arcane_bodyguard",
                    "arcane_pistoleer",
                    "arcane_primary_charger",
                    "arcane_tanker",
                    "primary_deadhead",
                    "primary_dexterity",
                    "primary_merciless",
                    "secondary_deadhead",
                    "secondary_dexterity",
                    "secondary_merciless",
                ),
            ),
        ),
    ),
    ArcanePack(
        "霍瓦尼亚赋能组合包",
        "Hollvania Arcane Collection",
        (
            PackTier(
                "稀有",
                0.95,
                (
                    "arcane_bellicose",
                    "arcane_camisado",
                    "arcane_crepuscular",
                    "arcane_impetus",
                    "arcane_truculence",
                    "primary_crux",
                    "secondary_enervate",
                    "melee_doughty",
                ),
            ),
            PackTier(
                "传奇",
                0.05,
                ("arcane_escapist", "arcane_hot_shot", "arcane_universal_fallout"),
            ),
        ),
    ),
)


class WarframeMarketClient:
    def __init__(
        self,
        platform: str,
        crossplay: bool,
        timeout: float = 20.0,
        retries: int = 5,
    ) -> None:
        self.headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json",
            # The item report always contains Simplified Chinese and English names.
            "Language": ITEM_LANGUAGE,
            "Platform": platform,
            "Crossplay": str(crossplay).lower(),
        }
        self.timeout = timeout
        self.retries = retries
        self._last_request_started = 0.0

    def get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        query = f"?{urlencode(params)}" if params else ""
        url = f"{API_BASE}{path}{query}"
        payload = self._request_json(url)
        if payload.get("error"):
            raise ApiError(f"API 返回错误：{payload['error']}")
        return payload.get("data")

    def get_market_statistics(
        self,
        slug: str,
        max_rank: int,
    ) -> tuple[float | None, int, str, str, int, str]:
        """Return 48-hour VWAP plus the latest closed daily volume for an exact rank."""
        url = f"{STATS_API_BASE}/items/{slug}/statistics"
        payload = self._request_json(url)
        statistics_closed = payload.get("payload", {}).get("statistics_closed", {})

        hourly = [
            record
            for record in statistics_closed.get("48hours", [])
            if isinstance(record, dict)
            and record.get("mod_rank") == max_rank
            and isinstance(record.get("volume"), (int, float))
            and record.get("volume", 0) > 0
            and isinstance(record.get("wa_price", record.get("avg_price")), (int, float))
        ]
        volume_48h = int(sum(float(record["volume"]) for record in hourly))
        average_price_48h = (
            sum(
                float(
                    record.get("wa_price")
                    if isinstance(record.get("wa_price"), (int, float))
                    else record["avg_price"]
                )
                * float(record["volume"])
                for record in hourly
            )
            / volume_48h
            if volume_48h > 0
            else None
        )
        hourly_dates = [str(record.get("datetime") or "") for record in hourly]
        statistics_48h_start = min(hourly_dates) if hourly_dates else ""
        statistics_48h_end = max(hourly_dates) if hourly_dates else ""

        daily = [
            record
            for record in statistics_closed.get("90days", [])
            if isinstance(record, dict)
            and record.get("mod_rank") == max_rank
            and isinstance(record.get("volume"), int)
        ]
        latest = max(daily, key=lambda record: str(record.get("datetime") or ""), default=None)
        latest_daily_volume = int(latest["volume"]) if latest else 0
        volume_date = str(latest.get("datetime") or "") if latest else ""
        return (
            average_price_48h,
            volume_48h,
            statistics_48h_start,
            statistics_48h_end,
            latest_daily_volume,
            volume_date,
        )

    def _request_json(self, url: str) -> dict[str, Any]:

        for attempt in range(self.retries + 1):
            elapsed = time.monotonic() - self._last_request_started
            if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
                time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
            self._last_request_started = time.monotonic()

            try:
                request = Request(url, headers=self.headers)
                with urlopen(request, timeout=self.timeout) as response:
                    payload = json.load(response)
                if not isinstance(payload, dict):
                    raise ApiError(f"API 响应格式不正确：{url}")
                return payload
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt >= self.retries:
                    raise ApiError(f"HTTP {exc.code}: {url}") from exc
                retry_after = exc.headers.get("Retry-After")
                delay = _retry_delay(attempt, retry_after)
            except (URLError, TimeoutError, json.JSONDecodeError) as exc:
                if attempt >= self.retries:
                    raise ApiError(f"请求失败：{url}（{exc}）") from exc
                delay = _retry_delay(attempt)

            print(f"请求暂时失败，{delay:.1f} 秒后重试（{attempt + 1}/{self.retries}）...", file=sys.stderr)
            time.sleep(delay)

        raise AssertionError("unreachable")


def _retry_delay(attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        try:
            return max(0.0, float(retry_after))
        except ValueError:
            pass
    return min(30.0, 1.5 * (2**attempt)) + random.uniform(0.0, 0.5)


def cache_path() -> Path:
    return Path(__file__).resolve().parent / ".cache" / f"items_{ITEM_LANGUAGE}.json"


def load_items(
    client: WarframeMarketClient,
    refresh: bool,
) -> list[dict[str, Any]]:
    path = cache_path()
    if not refresh and path.exists():
        age = time.time() - path.stat().st_mtime
        if age < CACHE_MAX_AGE_SECONDS:
            try:
                cached = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(cached, list):
                    print(f"使用物品清单缓存：{path}", file=sys.stderr)
                    return cached
            except (OSError, json.JSONDecodeError):
                pass

    print("正在下载物品清单...", file=sys.stderr)
    items = client.get("/items")
    if not isinstance(items, list):
        raise ApiError("物品清单格式不正确")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")
    return items


def load_dissolution_vosfor_values(
    client: WarframeMarketClient,
) -> tuple[dict[str, int], dict[str, int]]:
    """Return unranked Arcane dissolution values keyed by game ref and English name."""
    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "format": "json",
        "titles": FANDOM_DISSOLUTION_DATA_TITLE,
        "formatversion": 2,
    }
    payload = client._request_json(f"{FANDOM_API_BASE}?{urlencode(params)}")
    pages = ((payload.get("query") or {}).get("pages") or [])
    try:
        content = pages[0]["revisions"][0]["slots"]["main"]["content"]
    except (IndexError, KeyError, TypeError) as exc:
        raise ApiError("无法读取赋能分解荧尘数据") from exc

    entry_pattern = re.compile(
        r'^\s*\["([^"]+)"\]\s*=\s*\{(.*?)'
        r'(?=^\s*\["[^"]+"\]\s*=\s*\{|^\s*}\s*,?\s*$)',
        re.MULTILINE | re.DOTALL,
    )
    by_game_ref: dict[str, int] = {}
    by_name: dict[str, int] = {}
    for name, block in entry_pattern.findall(str(content)):
        dissolution_match = re.search(r"\bDissolution\s*=\s*(false|\d+)", block)
        game_ref_match = re.search(r'\bInternalName\s*=\s*"([^"]+)"', block)
        if dissolution_match is None or dissolution_match.group(1) == "false":
            continue
        value = int(dissolution_match.group(1))
        by_name[name] = value
        if game_ref_match is not None:
            by_game_ref[game_ref_match.group(1)] = value

    if not by_game_ref:
        raise ApiError("赋能分解荧尘数据为空")
    return by_game_ref, by_name


def localized_name(item: dict[str, Any], language: str) -> str:
    i18n = item.get("i18n") or {}
    localized = i18n.get(language) or i18n.get("en") or {}
    return str(localized.get("name") or item.get("slug") or "")


def find_arcanes(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    arcanes = [
        item
        for item in items
        if ARCANE_TAG in (item.get("tags") or [])
        and isinstance(item.get("maxRank"), int)
        and item["maxRank"] >= 0
    ]
    return sorted(arcanes, key=lambda item: str(item.get("slug", "")))


def fetch_prices(
    client: WarframeMarketClient,
    arcanes: list[dict[str, Any]],
    language: str,
    dissolution_by_game_ref: dict[str, int],
    dissolution_by_name: dict[str, int],
) -> list[PriceRow]:
    fetched_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    rows: list[PriceRow] = []
    total = len(arcanes)

    for index, item in enumerate(arcanes, 1):
        slug = str(item["slug"])
        game_ref = str(item.get("gameRef") or "")
        max_rank = int(item["maxRank"])
        dissolution_vosfor = DISSOLUTION_VOSFOR_OVERRIDES_BY_SLUG.get(
            slug,
            dissolution_by_game_ref.get(
                game_ref,
                dissolution_by_name.get(localized_name(item, "en"), 0),
            ),
        )
        print(f"[{index:>3}/{total}] {localized_name(item, language)} (R{max_rank})", file=sys.stderr)
        (
            average_price_48h,
            volume_48h,
            statistics_48h_start,
            statistics_48h_end,
            daily_volume,
            volume_date,
        ) = client.get_market_statistics(slug, max_rank)

        rows.append(
            PriceRow(
                name_zh=localized_name(item, "zh-hans"),
                name_en=localized_name(item, "en"),
                slug=slug,
                game_ref=game_ref,
                max_rank=max_rank,
                dissolution_vosfor=dissolution_vosfor,
                average_price_48h=average_price_48h,
                volume_48h=volume_48h,
                statistics_48h_start=statistics_48h_start,
                statistics_48h_end=statistics_48h_end,
                latest_daily_volume=daily_volume,
                volume_date=volume_date,
                item_url=f"https://warframe.market/items/{slug}",
                fetched_at=fetched_at,
            )
        )

    rows.sort(
        key=lambda row: (
            row.average_price_48h is None,
            row.average_price_48h if row.average_price_48h is not None else 0,
            row.name_en.casefold(),
        )
    )
    return rows


def copies_to_max_rank(max_rank: int) -> int:
    """Number of unranked copies needed to build one Arcane at max_rank."""
    return (max_rank + 1) * (max_rank + 2) // 2


def _pack_distribution(outcomes: list[tuple[float, float]]) -> list[tuple[float, float]]:
    distribution: dict[float, float] = {0.0: 1.0}
    for _ in range(PACK_DRAWS):
        next_distribution: dict[float, float] = {}
        for current_value, current_probability in distribution.items():
            for value, probability in outcomes:
                combined = round(current_value + value, 12)
                next_distribution[combined] = (
                    next_distribution.get(combined, 0.0) + current_probability * probability
                )
        distribution = next_distribution
    return sorted(distribution.items())


def _weighted_percentile(distribution: list[tuple[float, float]], quantile: float) -> float:
    cumulative = 0.0
    for value, probability in distribution:
        cumulative += probability
        if cumulative + 1e-12 >= quantile:
            return value
    return distribution[-1][0]


def calculate_pack_returns(
    rows: list[PriceRow],
    min_daily_volume: int,
) -> tuple[list[PackItemResult], list[PackSummary]]:
    by_slug = {row.slug: row for row in rows}
    item_results: list[PackItemResult] = []
    summaries: list[PackSummary] = []
    fetched_at = rows[0].fetched_at if rows else ""

    # For every pack, split the immediate return into:
    #   A = directly marketable Platinum-equivalent value per pack
    #   B = expected fraction of another 200-Vosfor pack recovered by dissolving
    #       low-volume or unpriced Arcane rewards.
    # Recycled Vosfor from each pack is spent on that same pack.  Therefore every
    # pack has its own fixed point V_pack = A_pack + B_pack * V_pack.
    pack_models: list[dict[str, Any]] = []
    for pack in PACKS:
        specs: list[dict[str, Any]] = []
        direct_market_value = 0.0
        recycling_pack_fraction = 0.0
        priced_count = 0
        volume_qualified_count = 0
        legendary_probability_per_draw = 0.0

        for tier in pack.tiers:
            if not tier.slugs:
                continue
            probability_per_item = tier.probability / len(tier.slugs)
            if tier.name_zh == "传奇":
                legendary_probability_per_draw += tier.probability

            for slug in tier.slugs:
                row = by_slug.get(slug)
                if row is None:
                    raise ApiError(f"组合包 {pack.name_en} 中的物品不存在于市场清单：{slug}")
                copies = copies_to_max_rank(row.max_rank)
                market_unit_value = (
                    row.average_price_48h / copies
                    if row.average_price_48h is not None
                    else 0.0
                )
                valuation_method = valuation_method_for_row(row, min_daily_volume)
                market_qualified = valuation_method == "市场出售"
                if row.average_price_48h is not None:
                    priced_count += 1
                if market_qualified:
                    volume_qualified_count += 1
                    direct_market_value += (
                        PACK_DRAWS * probability_per_item * market_unit_value
                    )
                else:
                    recycling_pack_fraction += (
                        PACK_DRAWS
                        * probability_per_item
                        * row.dissolution_vosfor
                        / PACK_COST_VOSFOR
                    )
                specs.append(
                    {
                        "tier_name_zh": tier.name_zh,
                        "slug": slug,
                        "row": row,
                        "probability_per_item": probability_per_item,
                        "copies": copies,
                        "market_unit_value": market_unit_value,
                        "market_qualified": market_qualified,
                        "valuation_method": valuation_method,
                    }
                )

        pack_models.append(
            {
                "pack": pack,
                "specs": specs,
                "direct_market_value": direct_market_value,
                "recycling_pack_fraction": recycling_pack_fraction,
                "priced_count": priced_count,
                "volume_qualified_count": volume_qualified_count,
                "legendary_probability_per_draw": legendary_probability_per_draw,
            }
        )

    if not pack_models:
        return item_results, summaries
    if max(model["recycling_pack_fraction"] for model in pack_models) >= 1:
        raise ApiError("分解回收率达到或超过 100%，无法收敛计算")

    for model in pack_models:
        model["recycle_pack_value"] = model["direct_market_value"] / (
            1 - model["recycling_pack_fraction"]
        )

    for model in pack_models:
        pack = model["pack"]
        recycle_pack_value = model["recycle_pack_value"]
        recycle_value_per_vosfor = recycle_pack_value / PACK_COST_VOSFOR
        outcomes: list[tuple[float, float]] = []
        for spec in model["specs"]:
            row = spec["row"]
            recycle_unit_value = row.dissolution_vosfor * recycle_value_per_vosfor
            if spec["market_qualified"]:
                valuation_method = spec["valuation_method"]
                unit_value = spec["market_unit_value"]
            elif row.dissolution_vosfor > 0:
                valuation_method = spec["valuation_method"]
                unit_value = recycle_unit_value
            else:
                valuation_method = "无回收价值"
                unit_value = 0.0
            contribution = PACK_DRAWS * spec["probability_per_item"] * unit_value
            outcomes.append((unit_value, spec["probability_per_item"]))
            item_results.append(
                PackItemResult(
                    pack_name_zh=pack.name_zh,
                    pack_name_en=pack.name_en,
                    tier_name_zh=spec["tier_name_zh"],
                    slug=spec["slug"],
                    probability_per_draw=spec["probability_per_item"],
                    expected_quantity_per_pack=PACK_DRAWS * spec["probability_per_item"],
                    copies_to_max=spec["copies"],
                    valuation_method=valuation_method,
                    market_unit_equivalent_price=spec["market_unit_value"],
                    dissolution_vosfor=row.dissolution_vosfor,
                    recycle_unit_equivalent_price=recycle_unit_value,
                    unit_equivalent_price=unit_value,
                    expected_platinum_contribution=contribution,
                )
            )

        distribution = _pack_distribution(outcomes)
        recycling_platinum = model["recycling_pack_fraction"] * recycle_pack_value
        expected_per_pack = model["direct_market_value"] + recycling_platinum
        summaries.append(
            PackSummary(
                rank=0,
                pack_name_zh=pack.name_zh,
                pack_name_en=pack.name_en,
                arcane_count=sum(len(tier.slugs) for tier in pack.tiers),
                priced_count=model["priced_count"],
                volume_qualified_count=model["volume_qualified_count"],
                min_daily_volume=min_daily_volume,
                direct_market_platinum_per_pack=model["direct_market_value"],
                recycling_pack_fraction=model["recycling_pack_fraction"],
                recycling_platinum_per_pack=recycling_platinum,
                recycle_target_pack_name_zh=pack.name_zh,
                recycle_value_per_200_vosfor=recycle_pack_value,
                expected_platinum_per_pack=expected_per_pack,
                expected_platinum_per_1000_vosfor=(1000 / PACK_COST_VOSFOR) * expected_per_pack,
                p10_platinum_per_pack=_weighted_percentile(distribution, 0.10),
                median_platinum_per_pack=_weighted_percentile(distribution, 0.50),
                p90_platinum_per_pack=_weighted_percentile(distribution, 0.90),
                maximum_platinum_per_pack=distribution[-1][0],
                legendary_chance_per_pack=1 - (1 - model["legendary_probability_per_draw"]) ** PACK_DRAWS,
                relative_return_index=0.0,
                fetched_at=fetched_at,
            )
        )

    summaries.sort(key=lambda summary: summary.expected_platinum_per_pack, reverse=True)
    highest_return = summaries[0].expected_platinum_per_pack if summaries else 0.0
    for rank, summary in enumerate(summaries, 1):
        summary.rank = rank
        summary.relative_return_index = (
            100 * summary.expected_platinum_per_pack / highest_return if highest_return else 0.0
        )
    return item_results, summaries


def valuation_method_for_row(row: PriceRow, min_daily_volume: int) -> str:
    """Return the market/recycling treatment for one max-rank Arcane."""
    if row.average_price_48h is None:
        return "分解再投" if row.dissolution_vosfor > 0 else "无回收价值"
    if row.latest_daily_volume < min_daily_volume:
        return (
            "分解再投"
            if row.dissolution_vosfor > 0
            else "无回收价值"
        )
    if (
        SECONDARY_FILTER_MIN_DAILY_VOLUME
        <= row.latest_daily_volume
        <= SECONDARY_FILTER_MAX_DAILY_VOLUME
        and row.average_price_48h < SECONDARY_FILTER_MIN_AVERAGE_PRICE
    ):
        return (
            "分解再投"
            if row.dissolution_vosfor > 0
            else "无回收价值"
        )
    return "市场出售"


PRICE_CSV_HEADERS = (
    "组合包收益排名",
    "洛德组合包",
    "概率池",
    "单次抽中概率(%)",
    "每包期望数量",
    "近48小时成交量加权平均价(满级/白金)",
    "近48小时成交数量",
    "48小时统计起始",
    "48小时统计结束",
    "最近日成交数量",
    "成交量统计日期",
    "数量门槛",
    "计价方式",
    "市场等价单价(白金/个)",
    "分解荧尘(个/赋能)",
    "分解再投等价单价(白金/个)",
    "最终计价单价(白金/个)",
    "单包期望贡献(白金)",
    "中文名",
    "英文名",
    "满级等级",
    "物品链接",
    "抓取时间",
    "slug",
)


def write_csv(
    rows: list[PriceRow],
    item_results: list[PackItemResult],
    summaries: list[PackSummary],
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    item_by_slug = {item.slug: item for item in item_results}
    pack_rank = {summary.pack_name_en: summary.rank for summary in summaries}
    min_daily_volume = summaries[0].min_daily_volume if summaries else DEFAULT_MIN_DAILY_VOLUME
    tier_order = {"普通": 0, "低稀有度": 0, "罕见": 1, "稀有": 2, "传奇": 3}
    sorted_rows = sorted(
        rows,
        key=lambda row: (
            pack_rank.get(item_by_slug[row.slug].pack_name_en, 999)
            if row.slug in item_by_slug
            else 999,
            tier_order.get(item_by_slug[row.slug].tier_name_zh, 9)
            if row.slug in item_by_slug
            else 9,
            -(
                item_by_slug[row.slug].expected_platinum_contribution
                if row.slug in item_by_slug
                and item_by_slug[row.slug].expected_platinum_contribution is not None
                else 0
            ),
            row.name_en.casefold(),
        ),
    )
    # utf-8-sig lets Excel on Windows recognize Chinese text automatically.
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(PRICE_CSV_HEADERS)
        for row in sorted_rows:
            item = item_by_slug.get(row.slug)
            rank = pack_rank.get(item.pack_name_en, "") if item else ""
            writer.writerow(
                (
                    rank,
                    item.pack_name_zh if item else "不在洛德组合包",
                    item.tier_name_zh if item else "",
                    round(100 * item.probability_per_draw, 4) if item else "",
                    round(item.expected_quantity_per_pack, 6) if item else "",
                    "" if row.average_price_48h is None else round(row.average_price_48h, 4),
                    row.volume_48h,
                    row.statistics_48h_start,
                    row.statistics_48h_end,
                    row.latest_daily_volume,
                    row.volume_date,
                    min_daily_volume,
                    item.valuation_method
                    if item
                    else valuation_method_for_row(row, min_daily_volume),
                    round(item.market_unit_equivalent_price, 4) if item else "",
                    row.dissolution_vosfor,
                    round(item.recycle_unit_equivalent_price, 4) if item else "",
                    round(item.unit_equivalent_price, 4) if item else "",
                    round(item.expected_platinum_contribution, 4)
                    if item and item.expected_platinum_contribution is not None
                    else "",
                    row.name_zh,
                    row.name_en,
                    row.max_rank,
                    row.item_url,
                    row.fetched_at,
                    row.slug,
                )
            )


def write_pack_summary_csv(summaries: list[PackSummary], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            (
                "排名",
                "组合包",
                "英文名",
                "赋能种类数",
                "有价格种类数",
                "数量达标且有价格种类数",
                "最近日数量门槛",
                "每包成本(溶解液)",
                "每包成本(信用点)",
                "每包赋能数",
                "直接市场期望白金/包",
                "回收组合包比例/包",
                "分解再投资期望白金/包",
                "荧尘再投资目标",
                "每200荧尘长期价值(白金)",
                "期望白金/包",
                "期望白金/1000溶解液",
                "P10白金/包",
                "中位数白金/包",
                "P90白金/包",
                "理论最高白金/包",
                "至少一个传奇概率(%)",
                "相对收益指数(最高=100)",
                "抓取时间",
            )
        )
        for summary in summaries:
            writer.writerow(
                (
                    summary.rank,
                    summary.pack_name_zh,
                    summary.pack_name_en,
                    summary.arcane_count,
                    summary.priced_count,
                    summary.volume_qualified_count,
                    summary.min_daily_volume,
                    PACK_COST_VOSFOR,
                    PACK_COST_CREDITS,
                    PACK_DRAWS,
                    round(summary.direct_market_platinum_per_pack, 4),
                    round(summary.recycling_pack_fraction, 6),
                    round(summary.recycling_platinum_per_pack, 4),
                    summary.recycle_target_pack_name_zh,
                    round(summary.recycle_value_per_200_vosfor, 4),
                    round(summary.expected_platinum_per_pack, 4),
                    round(summary.expected_platinum_per_1000_vosfor, 4),
                    round(summary.p10_platinum_per_pack, 4),
                    round(summary.median_platinum_per_pack, 4),
                    round(summary.p90_platinum_per_pack, 4),
                    round(summary.maximum_platinum_per_pack, 4),
                    round(100 * summary.legendary_chance_per_pack, 4),
                    round(summary.relative_return_index, 2),
                    summary.fetched_at,
                )
            )


def write_json(
    rows: list[PriceRow],
    item_results: list[PackItemResult],
    summaries: list[PackSummary],
    output: Path,
) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(
            {
                "methodology": {
                    "packCostVosfor": PACK_COST_VOSFOR,
                    "packCostCredits": PACK_COST_CREDITS,
                    "drawsPerPack": PACK_DRAWS,
                    "priceWindow": "closed hourly records from statistics_closed.48hours, exact max rank",
                    "priceMetric": "volume-weighted average of each hourly wa_price, weighted again by hourly volume",
                    "volumeWindow": "latest closed day from the 90-day chart, exact max rank",
                    "minDailyVolume": summaries[0].min_daily_volume if summaries else None,
                    "secondaryFilterMinDailyVolume": SECONDARY_FILTER_MIN_DAILY_VOLUME,
                    "secondaryFilterMaxDailyVolume": SECONDARY_FILTER_MAX_DAILY_VOLUME,
                    "secondaryFilterMinAveragePrice": SECONDARY_FILTER_MIN_AVERAGE_PRICE,
                    "valuation": "market-qualified rewards use max-rank 48-hour volume-weighted average price / copies required; rewards below the daily volume threshold, rewards with daily volume 10-20 inclusive and max-rank average price below 80, or rewards without 48-hour trades are dissolved and their Vosfor is recursively reinvested into the same collection that produced them",
                    "fixedPoint": "V_pack = direct_market_value_pack / (1 - recycling_pack_fraction_pack)",
                    "recycleRule": "each collection reinvests its recovered Vosfor into itself",
                    "recycleTargetPack": "各自来源组合包",
                    "recycleValuePer200Vosfor": None,
                    "creditValuation": "ignored; every additional recycled 200 Vosfor pack still costs 50,000 Credits",
                    "dissolutionDataSource": "https://warframe.fandom.com/wiki/Module:Arcane/data",
                },
                "packSummary": [asdict(summary) for summary in summaries],
                "packItems": [asdict(item) for item in item_results],
                "prices": [asdict(row) for row in rows],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def print_preview(rows: list[PriceRow], limit: int, min_daily_volume: int) -> None:
    priced = [row for row in rows if row.average_price_48h is not None]
    if not priced or limit <= 0:
        return
    print("\n近 48 小时加权平均价最低的赋能：")
    for row in priced[:limit]:
        valuation_status = valuation_method_for_row(row, min_daily_volume)
        print(
            f"{row.name_zh:<28} R{row.max_rank}  {row.average_price_48h:>7.2f} 白金  "
            f"48h量 {row.volume_48h:>4}  最近日量 {row.latest_daily_volume:>4}  {valuation_status}"
        )


def print_pack_ranking(summaries: list[PackSummary]) -> None:
    print("\n洛德组合包期望收益排行：")
    print("排名  组合包                    期望/包    中位数     P90    相对指数")
    for summary in summaries:
        print(
            f"{summary.rank:>2}    {summary.pack_name_zh:<22}"
            f"{summary.expected_platinum_per_pack:>7.2f}"
            f"{summary.median_platinum_per_pack:>10.2f}"
            f"{summary.p90_platinum_per_pack:>9.2f}"
            f"{summary.relative_return_index:>10.1f}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="读取 Warframe.market 所有满级赋能的近 48 小时成交量加权平均价并导出。"
    )
    parser.add_argument("-o", "--output", type=Path, default=Path("满级赋能近48小时平均价.csv"), help="CSV 输出路径")
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("洛德组合包收益排行.csv"),
        help="组合包收益排行 CSV 输出路径",
    )
    parser.add_argument("--json", type=Path, help="可选的 JSON 输出路径")
    parser.add_argument("--platform", choices=PLATFORMS, default="pc", help="平台（默认：pc）")
    parser.add_argument(
        "--no-crossplay",
        action="store_true",
        help="仅查询指定平台，不包含跨平台交易订单",
    )
    parser.add_argument("--refresh-items", action="store_true", help="忽略 24 小时物品清单缓存")
    parser.add_argument(
        "--min-volume",
        type=int,
        default=DEFAULT_MIN_DAILY_VOLUME,
        help="第一层筛选：最近日成交数量低于此值时按分解荧尘再投资计价（默认：10；另固定剔除日量10-20且均价<80）",
    )
    parser.add_argument("--preview", type=int, default=15, metavar="N", help="在终端预览最便宜的 N 条（默认：15）")
    parser.add_argument("--timeout", type=float, default=20.0, help="单次请求超时秒数（默认：20）")
    args = parser.parse_args()
    if args.min_volume < 0:
        parser.error("--min-volume 不能小于 0")
    return args


def main() -> int:
    args = parse_args()
    client = WarframeMarketClient(
        platform=args.platform,
        crossplay=not args.no_crossplay,
        timeout=args.timeout,
    )

    try:
        items = load_items(client, args.refresh_items)
        arcanes = find_arcanes(items)
        if not arcanes:
            raise ApiError(f"物品清单中没有找到标签为 {ARCANE_TAG!r} 的可升级赋能")
        print(f"共找到 {len(arcanes)} 种赋能，开始读取满级近 48 小时均价和最近日成交数量...", file=sys.stderr)
        dissolution_by_game_ref, dissolution_by_name = load_dissolution_vosfor_values(client)
        rows = fetch_prices(
            client,
            arcanes,
            ITEM_LANGUAGE,
            dissolution_by_game_ref,
            dissolution_by_name,
        )
        item_results, summaries = calculate_pack_returns(rows, args.min_volume)
        write_csv(rows, item_results, summaries, args.output)
        write_pack_summary_csv(summaries, args.summary_output)
        if args.json:
            write_json(rows, item_results, summaries, args.json)
    except (ApiError, OSError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\n已取消。", file=sys.stderr)
        return 130

    priced_count = sum(row.average_price_48h is not None for row in rows)
    print_preview(rows, args.preview, args.min_volume)
    print_pack_ranking(summaries)
    print(f"\n完成：{len(rows)} 种赋能，其中 {priced_count} 种有近 48 小时满级成交记录。")
    print(f"CSV：{args.output.resolve()}")
    print(f"组合包排行：{args.summary_output.resolve()}")
    if args.json:
        print(f"JSON：{args.json.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
