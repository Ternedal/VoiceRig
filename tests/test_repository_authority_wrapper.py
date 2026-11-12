"""Behavioural contract for verify-repository-authority.ps1 (ModelRig #2390 F3, #2109).

The real wrapper runs in PowerShell 7 against a fake ``gh`` in a throw-away Git
checkout on branch ``main``. It must bind its verdict to that checkout's exact
HEAD, refuse when GitHub's main head is another revision, refuse a dirty or
non-main checkout before reading anything, and with ``-Json`` print exactly one
JSON object.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "verify-repository-authority.ps1"
PWSH = shutil.which("pwsh")

pytestmark = [
    pytest.mark.skipif(PWSH is None, reason="PowerShell 7 (pwsh) is required"),
    pytest.mark.skipif(os.name == "nt", reason="the fake gh is a POSIX executable script"),
]

CHECKS = ["unit", "packaged-contract", "ownership-smoke", "windows-service-smoke",
          "Analyze (python)", "Analyze (javascript-typescript)"]

FAKE_GH = """#!{python}
import os, sys
from pathlib import Path
root = Path(os.environ["FAKE_GH_DIR"])
(root / "calls.log").open("a").write(" ".join(sys.argv[1:]) + "\\n")
args = sys.argv[1:]
if args[:1] == ["auth"]:
    sys.exit(0 if (root / "authed").exists() else 1)
if args[:1] != ["api"] or len(args) < 2:
    sys.exit(1)
path = args[1]
name = "protection.json" if path.endswith("/branches/main/protection") else (
    "branch.json" if path.endswith("/branches/main") else None)
if name is None or not (root / name).exists():
    print("gh: Not Found (HTTP 404)", file=sys.stderr)
    sys.exit(1)
sys.stdout.write((root / name).read_text())
"""


def good_protection() -> dict:
    return {
        "required_status_checks": {"strict": True,
                                   "checks": [{"context": c, "app_id": 15368} for c in CHECKS]},
        "required_pull_request_reviews": {"required_approving_review_count": 0},
        "enforce_admins": {"enabled": True},
        "required_conversation_resolution": {"enabled": True},
        "allow_force_pushes": {"enabled": False},
        "allow_deletions": {"enabled": False},
    }


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout.strip()


@pytest.fixture
def rig(tmp_path: Path):
    checkout = tmp_path / "VoiceRig"
    checkout.mkdir()
    shutil.copy2(WRAPPER, checkout / WRAPPER.name)
    git(checkout, "init", "-q", "-b", "main")
    git(checkout, "add", ".")
    git(checkout, "commit", "-q", "-m", "init")
    head = git(checkout, "rev-parse", "HEAD")

    fake = tmp_path / "fake-gh"
    fake.mkdir()
    gh = fake / "gh"
    gh.write_text(FAKE_GH.format(python=sys.executable))
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)
    (fake / "authed").write_text("")
    (fake / "branch.json").write_text(json.dumps({"name": "main", "protected": True, "commit": {"sha": head}}))
    (fake / "protection.json").write_text(json.dumps(good_protection()))

    def run(*extra: str):
        env = {**os.environ, "FAKE_GH_DIR": str(fake), "PATH": f"{fake}{os.pathsep}{os.environ['PATH']}"}
        return subprocess.run([PWSH, "-NoProfile", "-File", str(checkout / WRAPPER.name), *extra],
                              cwd=checkout, env=env, capture_output=True, text=True, timeout=120)

    return types.SimpleNamespace(checkout=checkout, fake=fake, head=head, run=run)


def verdict(completed) -> dict:
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 1, f"-Json must print exactly one line: {completed.stdout!r} {completed.stderr!r}"
    return json.loads(lines[0])


def test_pass_is_bound_to_the_exact_checkout_head(rig):
    completed = rig.run("-Json")
    result = verdict(completed)
    assert completed.returncode == 0, completed.stderr
    assert result["format"] == "voicerig-repository-authority" and result["version"] == 1
    assert result["passed"] is True and result["errors"] == []
    assert result["head"] == rig.head == result["github_head"]
    assert result["repository"] == "Ternedal/VoiceRig" and result["branch"] == "main"
    assert len(result["required_checks"]) == 6


def test_github_main_on_another_revision_fails(rig):
    (rig.fake / "branch.json").write_text(json.dumps({"protected": True, "commit": {"sha": "a" * 40}}))
    completed = rig.run("-Json")
    result = verdict(completed)
    assert completed.returncode == 2
    assert result["passed"] is False
    assert "GitHub main head does not match the expected checkout revision" in result["errors"]


@pytest.mark.parametrize("change, error", [
    (lambda p: p["required_status_checks"]["checks"].pop(), "missing required check/source binding: Analyze (javascript-typescript):15368"),
    (lambda p: p["required_status_checks"].update(strict=False), "required_status_checks.strict is not true"),
    (lambda p: p.update(enforce_admins={"enabled": False}), "administrator enforcement is not enabled"),
    (lambda p: p.update(allow_force_pushes={"enabled": True}), "force pushes are allowed"),
    (lambda p: p.pop("required_conversation_resolution"), "conversation resolution is not required"),
    (lambda p: p.pop("required_pull_request_reviews"), "pull requests are not required"),
])
def test_each_protection_rule_is_enforced(rig, change, error):
    protection = good_protection()
    change(protection)
    (rig.fake / "protection.json").write_text(json.dumps(protection))
    completed = rig.run("-Json")
    result = verdict(completed)
    assert completed.returncode == 2 and error in result["errors"], result["errors"]


def test_unreadable_protection_fails_rather_than_passing(rig):
    (rig.fake / "protection.json").unlink()
    completed = rig.run("-Json")
    assert completed.returncode == 2
    assert "main protection is unavailable" in verdict(completed)["errors"]


def test_a_dirty_checkout_is_refused_before_github_is_read(rig):
    (rig.checkout / "stray.txt").write_text("x")
    completed = rig.run("-Json")
    assert completed.returncode == 1
    assert "clean main checkout" in completed.stderr + completed.stdout
    assert not (rig.fake / "calls.log").exists(), "nothing may be read from GitHub for a dirty checkout"


def test_another_branch_is_refused(rig):
    git(rig.checkout, "switch", "-q", "-c", "feature")
    completed = rig.run("-Json")
    assert completed.returncode == 1
    assert "must run from branch main" in completed.stderr + completed.stdout


def test_unauthenticated_gh_is_refused(rig):
    (rig.fake / "authed").unlink()
    completed = rig.run("-Json")
    assert completed.returncode == 1
    assert "not authenticated" in completed.stderr + completed.stdout


def test_human_output_names_the_head(rig):
    completed = rig.run()
    assert completed.returncode == 0, completed.stderr
    assert "VoiceRig repository authority: PASS" in completed.stdout
    assert rig.head in completed.stdout
