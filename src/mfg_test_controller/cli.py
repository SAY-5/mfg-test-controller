"""Click command-line interface for the manufacturing test controller."""

from __future__ import annotations

import asyncio
from pathlib import Path

import click

from mfg_test_controller.config import (
    DeviceProfile,
    FaultConfig,
    load_device_profile,
    load_test_plan,
)
from mfg_test_controller.device.profiles import builtin_profile, builtin_profile_names
from mfg_test_controller.device.simulated import SimulatedDevice
from mfg_test_controller.report import render_console, render_json, render_markdown
from mfg_test_controller.runner import run_plan_locally
from mfg_test_controller.server import DeviceServer
from mfg_test_controller.store import RunStore

DEFAULT_PROFILE_DIR = Path("profiles")


def _load_plan_profiles(plan_profile_names: set[str]) -> list[DeviceProfile]:
    """Resolve the device profiles a plan needs, from disk or built-ins."""
    profiles: list[DeviceProfile] = []
    for name in sorted(plan_profile_names):
        disk_path = DEFAULT_PROFILE_DIR / f"{name}.yaml"
        if disk_path.exists():
            profiles.append(load_device_profile(disk_path))
        elif name in builtin_profile_names():
            profiles.append(builtin_profile(name))
        else:
            raise click.ClickException(f"no profile found for device {name!r}")
    return profiles


@click.group()
@click.version_option(package_name="mfg-test-controller")
def cli() -> None:
    """Manufacturing test controller simulator."""


@cli.command()
@click.argument("plan_path", type=click.Path(exists=True, dir_okay=False))
@click.option(
    "--only-failed",
    is_flag=True,
    help="Re-run only steps that " "failed in the most recent run of this plan.",
)
@click.option("--db", default="sqlite:///test-runs.db", help="Run history DB URL.")
@click.option(
    "--json-out", type=click.Path(dir_okay=False), help="Write the JSON report to this path."
)
@click.option(
    "--md-out", type=click.Path(dir_okay=False), help="Write the Markdown report to this path."
)
def run(
    plan_path: str,
    only_failed: bool,
    db: str,
    json_out: str | None,
    md_out: str | None,
) -> None:
    """Run a YAML test plan against simulated devices over loopback TCP."""
    plan = load_test_plan(plan_path)
    profiles = _load_plan_profiles({step.device for step in plan.steps})
    store = RunStore(db)

    only: list[str] | None = None
    if only_failed:
        recent = [r for r in store.list_runs(limit=50) if r.plan_name == plan.name]
        if not recent:
            raise click.ClickException("no prior run of this plan to take failed steps from")
        last = store.get_run(recent[0].id)
        assert last is not None
        only = [s.name for s in last.steps if not s.passed]
        if not only:
            click.echo("no failed steps in the most recent run; nothing to do")
            return

    report = asyncio.run(run_plan_locally(plan, profiles, only_failed=only))
    device_kinds = {p.name: p.kind for p in profiles}
    run_id = store.save_report(report, device_kinds)

    click.echo(render_console(report))
    click.echo(f"saved as run #{run_id}")
    if json_out is not None:
        Path(json_out).write_text(render_json(report))
        click.echo(f"json report: {json_out}")
    if md_out is not None:
        Path(md_out).write_text(render_markdown(report))
        click.echo(f"markdown report: {md_out}")
    if not report.all_passed:
        raise SystemExit(1)


@cli.command()
def devices() -> None:
    """List the built-in device profiles."""
    for name in builtin_profile_names():
        profile = builtin_profile(name)
        click.echo(
            f"{profile.name:<14} unit_id={profile.unit_id} " f"registers={len(profile.registers)}"
        )


@cli.command()
@click.argument("run_id", type=int, required=False)
@click.option("--db", default="sqlite:///test-runs.db", help="Run history DB URL.")
@click.option(
    "--format", "fmt", type=click.Choice(["console", "json", "markdown"]), default="console"
)
def report(run_id: int | None, db: str, fmt: str) -> None:
    """Show a stored run, or list recent runs when no id is given."""
    store = RunStore(db)
    if run_id is None:
        runs = store.list_runs()
        if not runs:
            click.echo("no runs recorded yet")
            return
        for r in runs:
            verdict = "PASS" if r.failed_steps == 0 else "FAIL"
            click.echo(
                f"#{r.id:<4} {r.plan_name:<28} {verdict} " f"{r.passed_steps}/{r.total_steps}"
            )
        return

    stored = store.get_run(run_id)
    if stored is None:
        raise click.ClickException(f"no run with id {run_id}")
    if fmt == "json":
        import json

        click.echo(
            json.dumps(
                {
                    "id": stored.id,
                    "plan": stored.plan_name,
                    "passed": stored.passed_steps,
                    "failed": stored.failed_steps,
                    "total": stored.total_steps,
                    "duration_s": stored.duration_s,
                    "steps": [
                        {"name": s.name, "passed": s.passed, "detail": s.detail}
                        for s in sorted(stored.steps, key=lambda s: s.ordinal)
                    ],
                },
                indent=2,
            )
        )
        return

    verdict = "PASS" if stored.failed_steps == 0 else "FAIL"
    click.echo(f"Run #{stored.id}: {stored.plan_name}  [{verdict}]")
    for s in sorted(stored.steps, key=lambda s: s.ordinal):
        mark = "ok  " if s.passed else "FAIL"
        click.echo(f"  {s.ordinal + 1:>2} {mark} {s.name}: {s.detail}")
    click.echo(
        f"  {stored.passed_steps}/{stored.total_steps} passed " f"in {stored.duration_s:.3f}s"
    )


@cli.command()
@click.argument("plan_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--db", default="sqlite:///test-runs.db", help="Run history DB URL.")
def replay(plan_path: str, db: str) -> None:
    """Re-run a plan and compare its pass count to the most recent stored run."""
    plan = load_test_plan(plan_path)
    store = RunStore(db)
    prior = [r for r in store.list_runs(limit=50) if r.plan_name == plan.name]
    profiles = _load_plan_profiles({step.device for step in plan.steps})
    report_ = asyncio.run(run_plan_locally(plan, profiles))
    store.save_report(report_, {p.name: p.kind for p in profiles})

    click.echo(render_console(report_))
    if prior:
        before = prior[0]
        click.echo(
            f"previous run #{before.id}: {before.passed_steps}/" f"{before.total_steps} passed"
        )
        delta = report_.passed - before.passed_steps
        click.echo(f"change in passing steps: {delta:+d}")


@cli.command("simulate-fault")
@click.option(
    "--profile", "profile_path", required=True, type=click.Path(exists=True, dir_okay=False)
)
@click.option(
    "--fault",
    "fault_kind",
    required=True,
    type=click.Choice(["drift", "stuck", "delay", "crc_corrupt", "drop"]),
)
@click.option("--register", type=int, default=None, help="Register address the fault targets.")
@click.option("--amount", type=int, default=5, help="Drift amount per request.")
def simulate_fault(
    profile_path: str,
    fault_kind: str,
    register: int | None,
    amount: int,
) -> None:
    """Load a profile, inject one fault, and show the device behaviour change."""
    profile = load_device_profile(profile_path)
    baseline = SimulatedDevice(profile)

    faulted_profile = profile.model_copy(
        update={
            "faults": [
                FaultConfig(
                    kind=fault_kind,
                    register_addr=register,
                    amount=amount,
                    delay_seconds=0.05,
                    after_requests=1,
                )
            ]
        }
    )
    faulted = SimulatedDevice(faulted_profile)

    click.echo(f"profile: {profile.name}  fault: {fault_kind}")
    for spec in profile.registers:
        bank = baseline.registers.bank(spec.kind)
        click.echo(
            f"  {spec.name:<20} {spec.kind:<8} addr={spec.address} "
            f"baseline={bank[spec.address]}"
        )
    click.echo("fault configured; run a plan against this profile to observe it")
    _ = faulted


@cli.command()
@click.option(
    "--profile", "profile_path", required=True, type=click.Path(exists=True, dir_okay=False)
)
@click.option("--host", default="0.0.0.0")
@click.option("--port", type=int, required=True)
def serve(profile_path: str, host: str, port: int) -> None:
    """Serve a single simulated device over TCP (used by docker-compose)."""
    profile = load_device_profile(profile_path)
    device = SimulatedDevice(profile)
    server = DeviceServer(device, host, port)
    click.echo(f"serving {profile.name} on {host}:{port}")
    try:
        asyncio.run(server.serve_forever())
    except KeyboardInterrupt:
        click.echo("stopped")


if __name__ == "__main__":
    cli()
