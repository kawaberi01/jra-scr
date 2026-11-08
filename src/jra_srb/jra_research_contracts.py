"""概要: SQL専用研究の設定・入力・結果・特徴量契約を定義する。
作成日: 2026-10-15
入力: 非秘密のJSON設定、SQLから抽出した時点入力と公式結果。
出力: 検証済み設定、不変の研究入力、正規化digest。
実行例: uv run python scripts/run_jra_research.py profiles
注意事項: DBやHTTPへ接続しない。結果は予測入力と別の型に保持する。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any


FEATURE_NAMES = (
    "log_win_odds", "normalized_win_market_share", "horse_log_starts",
    "horse_win_rate", "horse_top3_rate", "horse_finish_strength",
    "horse_course_top3_rate", "days_since_last_scaled",
    "log_o2_marginal_over_o1_share",
)
MASKED_NAMES = frozenset((
    "age_scaled", "distance_scaled", "frame_no_scaled", "horse_distance_log_starts",
    "horse_distance_top3_rate", "horse_surface_log_starts", "horse_surface_top3_rate",
    "is_maiden", "is_newcomer", "is_obstacle", "is_open_or_stakes", "jockey_log_starts",
    "jockey_top3_rate", "jockey_win_rate", "sex_female", "sex_gelding", "sex_male",
    "surface_dirt", "surface_turf", "trainer_log_starts", "trainer_top3_rate",
    "trainer_win_rate", "weight_carried_scaled",
))
CONTRACT_VERSION = "jra-research-input-v1"
PROFILE_ID = "cross_pool_sql_masked_v2"
EXPECTED_FEATURE_NAMES = MASKED_NAMES | frozenset(FEATURE_NAMES) | frozenset((
    "field_size_scaled", "horse_no_scaled", "horse_has_history", "horse_course_log_starts",
    *("course_" + course for course in ("chukyo", "fukushima", "hakodate", "hanshin", "kokura", "kyoto", "nakayama", "niigata", "sapporo", "tokyo")),
))


class ResearchError(RuntimeError):
    """秘密を含まない理由コードとCLI終了コードを持つ研究エラー。"""

    def __init__(self, reason: str, exit_code: int = 4, **details: Any):
        """固定の理由コードと非秘密の診断値を保持する。"""
        super().__init__(reason)
        self.reason, self.exit_code, self.details = reason, exit_code, details


def canonical_json(value: Any) -> str:
    """nullと有限数値を保持したUTF-8向けcanonical JSONを返す。"""
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def digest(value: Any) -> str:
    """canonical JSONの内容SHA256を返す。"""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def timestamp(value: str) -> datetime:
    """分単位表記も受け入れ、timezone必須のUTC日時へ変換する。"""
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None or result.utcoffset() is None:
            raise ValueError("timezone")
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError):
        raise ResearchError("invalid_timestamp") from None


def horse_number(value: Any) -> str:
    """中央競馬の馬番を01〜18の2桁へ検証付き正規化する。"""
    text = str(value).strip()
    if not text.isascii() or not text.isdigit() or not 1 <= int(text) <= 18:
        raise ResearchError("invalid_horse_number")
    return f"{int(text):02d}"


def finite(value: Any) -> float:
    """bool/欠損/非有限値を拒否して数値を返す。"""
    if isinstance(value, bool) or value is None:
        raise ResearchError("unexpected_null")
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        raise ResearchError("unexpected_null") from None
    if not math.isfinite(result):
        raise ResearchError("nonfinite_value")
    return result


def _keys(value: dict, allowed: set[str], required: set[str]) -> None:
    """未知キーと必須キー不足を拒否する。"""
    if not isinstance(value, dict) or set(value) - allowed or required - set(value):
        raise ResearchError("invalid_config_keys", 2)


@dataclass(frozen=True, slots=True)
class ResearchConfig:
    """非秘密の実験設定を厳密検証し、期間と上限を固定する。"""

    raw: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path) -> ResearchConfig:
        """JSON設定を読み、型・期間・profile・上限を検査する。"""
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            raise ResearchError("invalid_config_file", 2) from None
        return cls.parse(value)

    @classmethod
    def parse(cls, value: dict) -> ResearchConfig:
        """型違いも含め全設定エラーをCLI終了コード2へ統一する。"""
        try:
            return cls._parse_validated(value)
        except ResearchError as error:
            raise ResearchError(error.reason, 2, **error.details) from None
        except (KeyError, TypeError, ValueError, OverflowError):
            raise ResearchError("invalid_config_structure", 2) from None

    @classmethod
    def _parse_validated(cls, value: dict) -> ResearchConfig:
        """設定辞書を検証し、不正な意味変更を拒否する。"""
        required = {"schema_version", "profile_id", "source_policy", "date_from", "date_through",
                    "horizon", "splits", "seed", "model", "ticket", "quality", "limits"}
        _keys(value, required, required)
        if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["horizon"] not in {"T30", "T10"}:
            raise ResearchError("invalid_config_version", 2)
        policy = value["source_policy"]
        _keys(policy, {"policy_id", "source_key", "snapshot_id", "build_identity_sha256"},
              {"policy_id", "source_key", "snapshot_id"})
        if policy["policy_id"] != "frozen_prediction_v1" or type(policy["snapshot_id"]) is not int or policy["snapshot_id"] < 1:
            raise ResearchError("unsupported_source_policy", 2)
        if policy["source_key"] != "prediction-full-20261008":
            raise ResearchError("unexpected_source_key", 2)
        if "build_identity_sha256" in policy and not re.fullmatch(r"[0-9a-f]{64}", policy["build_identity_sha256"]):
            raise ResearchError("invalid_build_identity_hash", 2)
        _keys(value["splits"], {"train", "dev", "evaluation"}, {"train", "dev", "evaluation"})
        try:
            first, last = date.fromisoformat(value["date_from"]), date.fromisoformat(value["date_through"])
            periods = []
            for name in ("train", "dev", "evaluation"):
                limits = value["splits"][name]
                if len(limits) != 2:
                    raise ValueError("period")
                start, end = map(date.fromisoformat, limits)
                if not first <= start <= end <= last:
                    raise ValueError("period")
                periods.append((start, end))
            if first > last or any(a[1] >= b[0] for a, b in zip(periods, periods[1:])):
                raise ValueError("overlap")
            if str(first) != value["date_from"] or str(last) != value["date_through"] or any(
                [str(start), str(end)] != value["splits"][name]
                for name, (start, end) in zip(("train", "dev", "evaluation"), periods, strict=True)):
                raise ValueError("noncanonical_date")
        except (ValueError, TypeError):
            raise ResearchError("invalid_date_partition", 2) from None
        _keys(value["model"], {"C", "solver", "max_iter"}, {"C", "solver", "max_iter"})
        if finite(value["model"]["C"]) <= 0 or value["model"]["solver"] != "lbfgs" or type(value["model"]["max_iter"]) is not int or value["model"]["max_iter"] < 1:
            raise ResearchError("invalid_model_config", 2)
        _keys(value["ticket"], {"stake_yen", "odds_min", "odds_max", "min_expected_return", "max_tickets_per_race"},
              {"stake_yen", "odds_min", "odds_max", "min_expected_return", "max_tickets_per_race"})
        ticket = value["ticket"]
        if type(ticket["stake_yen"]) is not int or type(ticket["max_tickets_per_race"]) is not int or ticket["stake_yen"] != 100 or ticket["max_tickets_per_race"] != 1 or not 1 <= finite(ticket["odds_min"]) <= finite(ticket["odds_max"]) or finite(ticket["min_expected_return"]) <= 0:
            raise ResearchError("invalid_ticket_config", 2)
        _keys(value["quality"], {"availability", "require_atomic_snapshot"}, {"availability", "require_atomic_snapshot"})
        if value["quality"]["availability"] != "research_only" or not isinstance(value["quality"]["require_atomic_snapshot"], bool):
            raise ResearchError("unsupported_quality", 2)
        maximums = {"batch_races": 500, "fetch_rows": 10000, "query_timeout_seconds": 90,
                    "memory_bytes": 16 * 1024 ** 3, "max_candidate_rows": 10000000, "max_label_scan_rows": 10000000}
        _keys(value["limits"], set(maximums), set(maximums))
        if any(type(value["limits"][k]) is not int or not 1 <= value["limits"][k] <= bound for k, bound in maximums.items()):
            raise ResearchError("invalid_resource_limit", 2)
        if type(value["seed"]) is not int or not 0 <= value["seed"] < 2 ** 32:
            raise ResearchError("invalid_seed", 2)
        if not isinstance(value["profile_id"], str):
            raise ResearchError("invalid_profile", 2)
        if value["profile_id"] == PROFILE_ID and value["horizon"] != "T30":
            raise ResearchError("profile_horizon_mismatch", 2)
        return cls(json.loads(canonical_json(value)))

    def split(self, race_date: str) -> str | None:
        """開催日の固定分割名を返し、対象外ならNoneを返す。"""
        for name, (start, end) in self.raw["splits"].items():
            if start <= race_date <= end:
                return name
        return None

    @property
    def snapshot(self) -> int:
        """実験へ明示されたsnapshot番号を返す。"""
        return self.raw["source_policy"]["snapshot_id"]


@dataclass(frozen=True, slots=True)
class InputRace:
    """対象結果を含まない予測時点の入力だけを保持する。"""

    race_key: str
    race_date: str
    venue: str
    horizon: str
    cutoff_utc: str
    horses: tuple[str, ...]
    odds: tuple[float, ...]
    features: tuple[tuple[float, ...], ...]
    snapshot: int
    evidence: tuple[str, ...]

    def content(self) -> dict:
        """digest対象の予測入力を返す。"""
        return asdict(self)


@dataclass(frozen=True, slots=True)
class OutcomeBundle:
    """同じ版・同じHRの公式結果と100円当りの払戻円を保持する。"""

    race_key: str
    horses: tuple[str, ...]
    ranks: tuple[int, ...]
    payouts: tuple[int, ...]
    hr_sha256: str


@dataclass(slots=True)
class ResearchDataset:
    """メモリ内入力と結果・coverage・来歴を分離して保持する。"""

    races: list[InputRace] = field(default_factory=list)
    outcomes: dict[str, OutcomeBundle] = field(default_factory=dict)
    excluded: list[dict] = field(default_factory=list)
    provenance: dict = field(default_factory=dict)
    candidate_count: int = 0

    def content_digest(self) -> str:
        """業務キー順の全利用入力と公式結果をdigest化する。"""
        stream = hashlib.sha256((CONTRACT_VERSION + "\n").encode())
        for race in sorted(self.races, key=lambda r: r.race_key):
            outcome = self.outcomes.get(race.race_key)
            stream.update((canonical_json({"input": race.content(), "outcome": asdict(outcome) if outcome else None}) + "\n").encode("utf-8"))
        stream.update(canonical_json(sorted(self.excluded, key=lambda x: x["race_key"])).encode("utf-8"))
        return stream.hexdigest()

    def coverage(self) -> dict:
        """重複しない採用/除外数と理由・対象範囲を返す。"""
        from collections import Counter
        return {"coverage_basis": "stored_races", "candidate_races": self.candidate_count,
                "adopted_races": len(self.races), "adopted_horses": sum(len(r.horses) for r in self.races),
                "excluded_races": len(self.excluded), "excluded_by_reason": dict(Counter(r["reason"] for r in self.excluded)),
                "by_year": dict(Counter(r.race_date[:4] for r in self.races)),
                "first_date": min((r.race_date for r in self.races), default=None),
                "last_date": max((r.race_date for r in self.races), default=None)}
