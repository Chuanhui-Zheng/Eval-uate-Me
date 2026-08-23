"""Tests: statistics."""
from helpers import *  # noqa: F401,F403


# ---- sample size, permutation test, Holm, by-tag comparison ----


def test_sample_size_matches_hand_computed_values_and_is_consistent():
    from evalharness.stats import (detectable_effect_paired, detectable_effect_unpaired, sample_size_paired,
                                   sample_size_unpaired)
    # hand check: (1.95996*sqrt(2*.55*.45) + .84162*sqrt(.25+.24))^2 / .1^2 = 387.35 -> 388
    assert sample_size_unpaired(0.5, 0.1) == 388
    assert sample_size_unpaired(0.5, 0.1, power=0.9) > 388 and sample_size_unpaired(0.5, 0.2) < 388
    assert sample_size_unpaired(0.5, -0.1) > 0                          # a drop needs about as many cases as a rise
    # hand check: (1.95996+.84162)^2 * (0.3 - 0.1^2) / 0.1^2 = 7.8489 * 29 = 227.6 -> 228
    assert sample_size_paired(0.1, 0.3) == 228
    assert sample_size_paired(0.1, 0.1) < sample_size_paired(0.1, 0.3)   # fewer disagreements: fewer cases needed
    assert detectable_effect_unpaired(388, 0.5) == pytest.approx(0.1, abs=0.002)   # the inverse question
    assert detectable_effect_paired(228, 0.3) == pytest.approx(0.1, abs=0.002)
    nan = detectable_effect_unpaired(5, 0.5)
    assert nan != nan                                                  # 5 cases cannot detect anything
    for bad in (lambda: sample_size_unpaired(0.5, 0), lambda: sample_size_unpaired(0.95, 0.1),
                lambda: sample_size_paired(0.4, 0.2), lambda: sample_size_paired(0, 0.2)):
        with pytest.raises(ValueError):
            bad()


def test_holm_and_permutation_test():
    from evalharness.stats import holm_adjust, paired_permutation_p
    # sorted p: .01, .03, .04 -> x3, x2, x1 = .03, .06, .04 -> made monotone: .03, .06, .06
    assert holm_adjust([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])
    assert holm_adjust([0.5]) == [0.5] and holm_adjust([0.4, 0.6]) == pytest.approx([0.8, 0.8])
    assert holm_adjust([0.2, 0.9, 0.9, 0.9])[0] == pytest.approx(0.8)    # 4 * .2, capped later steps stay <= 1
    assert max(holm_adjust([0.9, 0.9])) == 1.0
    assert paired_permutation_p([1] * 10) == pytest.approx(2 / 1024)      # exact: all + or all -
    assert paired_permutation_p([0, 0, 0]) == 1.0 and paired_permutation_p([1, -1]) == 1.0
    assert paired_permutation_p([1] * 6 + [-1] * 4) > 0.5                 # mixed: no evidence
    big = paired_permutation_p([1.0] * 30)                                # Monte Carlo branch
    assert 0 < big < 0.001 and big == paired_permutation_p([1.0] * 30)    # reproducible


def test_power_command(tmp_path, capsys):
    assert main(["power", "--baseline", "0.5", "--delta", "0.1"]) == 0
    assert "388 cases per system" in capsys.readouterr().out
    assert main(["power", "--baseline", "0.5", "--delta", "0.1", "--paired", "--discordant", "0.3"]) == 0
    assert "228 cases" in capsys.readouterr().out
    assert main(["power", "--baseline", "0.7", "--n", "40"]) == 0
    out = capsys.readouterr().out
    assert "smallest reliably detectable difference" in out and "large gap" in out
    f = write_eval(tmp_path, [{"id": str(i), "input": "a", "expected": "a"} for i in range(50)])
    assert main(["power", "--baseline", "0.7", "--config", str(f)]) == 0 and "with 50 cases" in capsys.readouterr().out
    for bad in (["--baseline", "0.5"], ["--baseline", "0.5", "--delta", "0.1", "--n", "5"],
                ["--baseline", "0.5", "--delta", "0.1", "--paired"], ["--baseline", "0.95", "--delta", "0.1"]):
        assert main(["power", *bad]) == 2
    capsys.readouterr()
    assert main(["power", "--baseline", "0.5", "--delta", "0.1", "--paired"]) == 2
    assert "needs --discordant" in capsys.readouterr().err


def test_compare_by_tag_applies_holm_correction(tmp_path, capsys):
    base, cand = _two_systems(tmp_path)
    assert main(["compare", str(base), str(cand)]) == 0
    out = capsys.readouterr().out
    assert "p = " in out and "by tag (2 compared; p-values Holm-adjusted" in out
    easy = next(l for l in out.splitlines() if l.strip().startswith("easy"))
    hard = next(l for l in out.splitlines() if l.strip().startswith("hard"))
    assert "delta +100.0%" in easy and "significant after correction" in easy          # 12/12 fixed: p = 2/4096
    assert "delta +8.3%" in hard and "significant after correction" not in hard        # 1 of 12 fixed: luck-sized
    assert "adjusted p=1.000" in hard                                                   # raw p = 1.0
