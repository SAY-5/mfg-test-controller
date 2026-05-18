"""Station report rendering: JSON and Markdown."""

from __future__ import annotations

import json
from typing import Any

from mfg_test_controller.controller.sequencer import StationReport


def report_to_dict(report: StationReport) -> dict[str, Any]:
    """Convert a :class:`StationReport` into a JSON-serialisable dict."""
    first = report.first_failure
    return {
        "plan": report.plan_name,
        "summary": {
            "total": report.total,
            "passed": report.passed,
            "failed": report.failed,
            "all_passed": report.all_passed,
            "duration_s": round(report.duration_s, 4),
            "first_failure": first.name if first is not None else None,
        },
        "steps": [
            {
                "name": o.name,
                "device": o.device,
                "action": o.action,
                "register": o.register,
                "passed": o.passed,
                "measured": o.measured,
                "detail": o.detail,
                "duration_s": round(o.duration_s, 4),
            }
            for o in report.outcomes
        ],
    }


def render_json(report: StationReport) -> str:
    """Render a station report as indented JSON."""
    return json.dumps(report_to_dict(report), indent=2)


def render_markdown(report: StationReport) -> str:
    """Render a station report as a Markdown document."""
    verdict = "PASS" if report.all_passed else "FAIL"
    lines = [
        f"# Station report: {report.plan_name}",
        "",
        f"Result: {verdict}",
        "",
        f"- Total steps: {report.total}",
        f"- Passed: {report.passed}",
        f"- Failed: {report.failed}",
        f"- Wall-clock duration: {report.duration_s:.3f} s",
    ]
    first = report.first_failure
    if first is not None:
        lines.append(f"- First failing step: {first.name}")
    lines += [
        "",
        "| # | Step | Device | Action | Register | Result | Detail |",
        "|---|------|--------|--------|----------|--------|--------|",
    ]
    for index, o in enumerate(report.outcomes, start=1):
        result = "pass" if o.passed else "fail"
        detail = o.detail.replace("|", "\\|")
        lines.append(
            f"| {index} | {o.name} | {o.device} | {o.action} "
            f"| {o.register} | {result} | {detail} |"
        )
    lines.append("")
    return "\n".join(lines)


def render_console(report: StationReport) -> str:
    """Render a compact plain-text summary for terminal output."""
    verdict = "PASS" if report.all_passed else "FAIL"
    lines = [f"Plan: {report.plan_name}  [{verdict}]"]
    for index, o in enumerate(report.outcomes, start=1):
        mark = "ok  " if o.passed else "FAIL"
        lines.append(f"  {index:>2} {mark} {o.name}: {o.detail}")
    lines.append(f"  {report.passed}/{report.total} passed " f"in {report.duration_s:.3f}s")
    return "\n".join(lines)
