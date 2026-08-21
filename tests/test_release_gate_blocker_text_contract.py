from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_rule_matrix_module():
    path = Path(__file__).with_name("test_release_gate_rule_matrix.py")
    spec = importlib.util.spec_from_file_location("release_gate_rule_matrix_contract", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_gate_blocker_needles_are_pairwise_non_overlapping() -> None:
    """Keep the rule matrix's substring assertions unambiguous.

    The matrix intentionally checks ``expected_blocker in blocker`` so each case
    can focus on the stable semantic part of a Danish diagnostic. That is only
    precise while no distinct expected blocker needle contains another. If a
    future rule introduces such a prefix/substring collision, this test forces
    the matrix to switch those cases to a more specific discriminator instead
    of silently allowing the wrong rule to satisfy an assertion.
    """

    matrix = _load_rule_matrix_module()
    needles = sorted({case[2] for case in matrix.CASES})
    collisions: list[tuple[str, str]] = []

    for index, left in enumerate(needles):
        for right in needles[index + 1 :]:
            if left in right or right in left:
                collisions.append((left, right))

    assert collisions == [], f"Ambiguous release-gate blocker needles: {collisions}"
