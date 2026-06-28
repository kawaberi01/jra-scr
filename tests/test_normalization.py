import pytest

from jra_srb.errors import BadRequestError
from jra_srb.models import BetType, CourseCode
from jra_srb.normalization import normalize_bet_type, normalize_course, normalize_race_input, normalize_race_no


def test_normalize_japanese_course_name():
    assert normalize_course("中山") == CourseCode.nakayama
    assert normalize_course("阪神") == CourseCode.hanshin
    assert normalize_course("東京") == CourseCode.tokyo


def test_normalize_japanese_bet_type():
    assert normalize_bet_type("3連単") == BetType.trifecta
    assert normalize_bet_type("三連単") == BetType.trifecta
    assert normalize_bet_type("馬連") == BetType.quinella


@pytest.mark.parametrize("value", ["11R", "11レース", "第11レース", 11])
def test_normalize_race_no(value):
    assert normalize_race_no(value) == 11


def test_normalize_race_input_with_combination():
    normalized = normalize_race_input("中山", "11R", "3連単", "1,2,3")

    assert normalized.course == CourseCode.nakayama
    assert normalized.race_no == 11
    assert normalized.bet_type == BetType.trifecta
    assert normalized.combination == ["1", "2", "3"]


def test_normalize_rejects_unknown_course():
    with pytest.raises(BadRequestError, match="unsupported course"):
        normalize_course("未対応")


def test_normalize_rejects_unknown_bet_type():
    with pytest.raises(BadRequestError, match="unsupported bet_type"):
        normalize_bet_type("未対応")


def test_normalize_rejects_out_of_range_race_no():
    with pytest.raises(BadRequestError, match="between 1 and 12"):
        normalize_race_no("13R")
