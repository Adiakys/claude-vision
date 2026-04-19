"""Unit tests for the Region dataclass and parser. No GUI tests."""

import pytest

from claude_vision.errors import InvalidConfigError
from claude_vision.region import Region


def test_parse_valid_spec():
    assert Region.parse("10,20,300,400") == Region(10, 20, 300, 400)


def test_parse_accepts_whitespace():
    assert Region.parse(" 10 , 20 , 300 , 400 ") == Region(10, 20, 300, 400)


@pytest.mark.parametrize("spec", ["10,20,300", "10,20,300,400,500", "10,20", ""])
def test_parse_rejects_wrong_arity(spec: str):
    with pytest.raises(InvalidConfigError):
        Region.parse(spec)


@pytest.mark.parametrize("spec", ["a,b,c,d", "10,20,300,xx", "1.5,2,3,4"])
def test_parse_rejects_non_integer(spec: str):
    with pytest.raises(InvalidConfigError):
        Region.parse(spec)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"left": 0, "top": 0, "width": 0, "height": 100},
        {"left": 0, "top": 0, "width": 100, "height": 0},
        {"left": 0, "top": 0, "width": -1, "height": 100},
    ],
)
def test_rejects_zero_or_negative_dimensions(kwargs):
    with pytest.raises(InvalidConfigError):
        Region(**kwargs)


def test_rejects_negative_origin():
    with pytest.raises(InvalidConfigError):
        Region(left=-1, top=0, width=100, height=100)
    with pytest.raises(InvalidConfigError):
        Region(left=0, top=-1, width=100, height=100)


def test_as_mss_dict_shape():
    region = Region(left=10, top=20, width=300, height=400)
    assert region.as_mss_dict() == {
        "left": 10, "top": 20, "width": 300, "height": 400,
    }


def test_as_pil_bbox_shape():
    region = Region(left=10, top=20, width=300, height=400)
    # PIL expects (left, top, right, bottom)
    assert region.as_pil_bbox() == (10, 20, 310, 420)


def test_region_is_frozen():
    region = Region(left=0, top=0, width=100, height=100)
    with pytest.raises(Exception):
        region.left = 5  # type: ignore[misc]
