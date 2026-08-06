import json

import pytest

from app.evaluation.judge import _clamp01, _extract_json


def test_extract_json_parses_plain_json():
    assert _extract_json('{"faithfulness": 0.9}') == {"faithfulness": 0.9}


def test_extract_json_strips_markdown_fences():
    text = '```json\n{"faithfulness": 0.5, "answer_relevancy": 1.0}\n```'
    assert _extract_json(text) == {"faithfulness": 0.5, "answer_relevancy": 1.0}


def test_extract_json_finds_object_amid_surrounding_prose():
    text = 'Sure, here is my evaluation:\n{"faithfulness": 0.7}\nLet me know if you need more.'
    assert _extract_json(text) == {"faithfulness": 0.7}


def test_extract_json_raises_on_garbage():
    # judge_answer catches exactly JSONDecodeError, so this must be the type raised.
    with pytest.raises(json.JSONDecodeError):
        _extract_json("not json at all")


def test_clamp01_clamps_out_of_range_values():
    assert _clamp01(1.5) == 1.0
    assert _clamp01(-0.3) == 0.0
    assert _clamp01(0.42) == 0.42


def test_clamp01_returns_zero_for_non_numeric():
    assert _clamp01("not a number") == 0.0
    assert _clamp01(None) == 0.0
