#!/usr/bin/env python3
"""Validate initial and post-tailoring ATS dimension scores."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


DIMENSION_MAX = {
    "role_title_alignment": 20,
    "must_have_skills": 25,
    "evidence_strength": 20,
    "seniority": 10,
    "domain_product_relevance": 10,
    "location_work_comp_authorization": 10,
    "application_feasibility_freshness": 5,
}
LOCKED_DIMENSIONS = {
    "seniority",
    "domain_product_relevance",
    "location_work_comp_authorization",
    "application_feasibility_freshness",
}
CHANGEABLE_DIMENSIONS = set(DIMENSION_MAX) - LOCKED_DIMENSIONS


def validate(payload: dict[str, object]) -> dict[str, object]:
    errors: list[str] = []
    initial = payload.get("initial") or {}
    tailored = payload.get("tailored") or {}
    changes = payload.get("changes") or []

    for label, scores in (("initial", initial), ("tailored", tailored)):
        missing = sorted(set(DIMENSION_MAX) - set(scores))
        extra = sorted(set(scores) - set(DIMENSION_MAX))
        if missing:
            errors.append(f"{label} is missing dimensions: {', '.join(missing)}")
        if extra:
            errors.append(f"{label} has unknown dimensions: {', '.join(extra)}")
        for dimension, maximum in DIMENSION_MAX.items():
            value = scores.get(dimension)
            if not isinstance(value, int) or isinstance(value, bool):
                errors.append(f"{label}.{dimension} must be a whole number")
            elif value < 0 or value > maximum:
                errors.append(f"{label}.{dimension} must be between 0 and {maximum}")

    if not errors:
        for dimension in sorted(LOCKED_DIMENSIONS):
            if tailored[dimension] != initial[dimension]:
                errors.append(
                    f"locked dimension changed: {dimension} "
                    f"{initial[dimension]} -> {tailored[dimension]}"
                )

        documented = {
            change.get("dimension")
            for change in changes
            if isinstance(change, dict)
            and change.get("resume_line")
            and change.get("reason")
        }
        for dimension in sorted(CHANGEABLE_DIMENSIONS):
            if tailored[dimension] > initial[dimension] and dimension not in documented:
                errors.append(
                    f"increase in {dimension} lacks a changed resume_line and reason"
                )

        initial_total = sum(initial.values())
        tailored_total = sum(tailored.values())
        hard_cap = payload.get("hard_cap")
        if hard_cap is not None:
            if not isinstance(hard_cap, int) or isinstance(hard_cap, bool) or not 0 <= hard_cap <= 100:
                errors.append("hard_cap must be a whole number between 0 and 100")
            elif tailored_total > hard_cap:
                errors.append(f"tailored score {tailored_total} exceeds hard cap {hard_cap}")
        if payload.get("dealbreaker") and (initial_total != 0 or tailored_total != 0):
            errors.append("dealbreaker jobs must keep both scores at 0")
    else:
        initial_total = sum(value for value in initial.values() if isinstance(value, int))
        tailored_total = sum(value for value in tailored.values() if isinstance(value, int))

    return {
        "valid": not errors,
        "errors": errors,
        "initial_ats_score": initial_total,
        "tailored_ats_score": tailored_total,
        "score_delta": tailored_total - initial_total,
        "locked_dimensions": sorted(LOCKED_DIMENSIONS),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("score_file", type=Path)
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.score_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"valid": False, "errors": [str(exc)]}, indent=2))
        return 2
    result = validate(payload)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
