from __future__ import annotations

from trellis_vectorstore.filters import translate_filter_expr


def test_string_equality():
    result = translate_filter_expr('name == "foo"')
    assert result == {"clause": '"name" = %s', "params": ["foo"]}


def test_bool_equality_true():
    result = translate_filter_expr("is_private == True")
    assert result == {"clause": '"is_private" = %s', "params": [True]}


def test_bool_equality_false():
    result = translate_filter_expr("is_private == False")
    assert result == {"clause": '"is_private" = %s', "params": [False]}


def test_like():
    result = translate_filter_expr('module_path like "%foo%"')
    assert result == {"clause": '"module_path" LIKE %s', "params": ["%foo%"]}


def test_compound_and():
    result = translate_filter_expr('is_private == False and class_name == "Foo"')
    assert result == {
        "clause": '"is_private" = %s AND "class_name" = %s',
        "params": [False, "Foo"],
    }


def test_unrecognized_fragment_skipped_not_raised():
    result = translate_filter_expr("this is not valid syntax at all")
    assert result is None


def test_unrecognized_fragment_calls_warn_callback():
    warnings = []
    result = translate_filter_expr("garbage", warn=warnings.append)
    assert result is None
    assert len(warnings) == 1
    assert "garbage" in warnings[0]


def test_partial_recognition_keeps_valid_conditions():
    # One recognizable clause + one garbage clause — the garbage is skipped
    # (with a warning), the valid clause still translates. This is EA's
    # original behavior, preserved deliberately.
    warnings = []
    result = translate_filter_expr('name == "foo" and nonsense here', warn=warnings.append)
    assert result == {"clause": '"name" = %s', "params": ["foo"]}
    assert len(warnings) == 1


def test_no_warn_callback_does_not_raise():
    # warn is optional — omitting it must not crash on an unrecognized fragment.
    result = translate_filter_expr("garbage")
    assert result is None
