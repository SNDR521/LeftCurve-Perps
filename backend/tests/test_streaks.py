from app.core.streaks import max_streaks


def test_empty():
    assert max_streaks([]) == {}


def test_single_occurrence():
    assert max_streaks([["a"]]) == {"a": 1}


def test_unbroken_run():
    assert max_streaks([["a"], ["a"], ["a"]]) == {"a": 3}


def test_broken_run_takes_longest():
    # a a _ a a a  -> longest run of 3
    assert max_streaks([["a"], ["a"], [], ["a"], ["a"], ["a"]]) == {"a": 3}


def test_gap_resets():
    assert max_streaks([["a"], [], ["a"]]) == {"a": 1}


def test_multi_tag_per_trade():
    # a runs over trades 0,1 (2); b appears on 0 and 2 (max run 1)
    assert max_streaks([["a", "b"], ["a"], ["b"]]) == {"a": 2, "b": 1}


def test_none_tags_safe():
    assert max_streaks([None, ["a"], None]) == {"a": 1}
