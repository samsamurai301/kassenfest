from kassenfest.eval.scoring import box_hit, norm, same


def test_norm_makes_formats_comparable():
    assert norm("01.10.2026") == norm("2026-10-01") == "2026-10-01"
    assert norm("7:05") == norm("07.05") == "07:05"
    assert norm("10/2026") == norm("2026-10") == "2026-10"
    assert norm("A 123 456 780") == "a123456780"
    assert norm("  Müller,   Anna ") == "müller, anna"
    assert norm(["I10", "E11.9"]) == norm(["e11.9", "i10"])
    assert norm("") is None and norm([]) is None


def test_unticked_box_equals_blank_field():
    assert same(False, None) and same(None, False)
    assert not same(True, None)
    assert not same(0, None) or norm(0) == 0  # counts are not booleans
    assert same(["E11.9"], ["e11.9"])


def test_box_hit_uses_truth_centre():
    assert box_hit((0, 0, 100, 100), (40, 40, 60, 60))
    assert not box_hit((0, 0, 30, 30), (40, 40, 60, 60))
