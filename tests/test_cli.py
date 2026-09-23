#!/usr/bin/env python3
"""Focused tests for the user-facing tauceti-review CLI."""
import json
import pathlib
import sys
import types

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "runner"))
import cli  # noqa: E402
import reviewers  # noqa: E402


def test_pr_ref_oids_uses_old_gh_compatible_rest_fields():
    calls = []

    def fake_run(cmd, **kwargs):
        calls.append((cmd, kwargs))
        return types.SimpleNamespace(
            stdout=json.dumps({"head": {"sha": "head-sha"}, "base": {"sha": "base-sha"}})
        )

    original = cli.run
    cli.run = fake_run
    try:
        assert cli.pr_ref_oids("owner/repo", 42) == ("head-sha", "base-sha")
    finally:
        cli.run = original

    assert len(calls) == 1
    cmd, kwargs = calls[0]
    assert cmd[:2] == ["gh", "api"] and cmd[2].endswith("/pulls/42"), calls
    assert kwargs.get("capture") is True


def test_pr_ref_lookup_does_not_require_new_pr_view_field():
    source = pathlib.Path(cli.__file__).read_text()
    assert '"headRefOid,baseRefOid"' not in source


def test_build_status_context_reaches_the_trusted_prompt():
    # The actual shape returned for TauCeti PR #8073, whose sandboxed build and
    # workflow-pinned audits passed. There is no CheckRun.name/conclusion here.
    meta = {
        "headRefOid": "reviewed-head",
        "statusCheckRollup": [
            {"__typename": "StatusContext", "context": "build", "state": "SUCCESS"},
        ],
    }
    status = cli.ci_build_status(meta, "reviewed-head")
    assert status == "success"
    assert "passed `lake build` and the axiom audit" in reviewers.ci_status_block(
        status, "reviewed-head"
    )


def test_check_run_build_is_still_recognized():
    meta = {
        "headRefOid": "reviewed-head",
        "statusCheckRollup": [
            {"__typename": "CheckRun", "name": "build", "conclusion": "SUCCESS"},
        ],
    }
    assert cli.ci_build_status(meta, "reviewed-head") == "success"


def test_node_types_are_discriminated_by_typename():
    # The two vocabularies must never cross-read: a StatusContext carries `state`, a
    # CheckRun carries `conclusion`. Keying on `__typename` keeps that structural.
    meta = {
        "headRefOid": "reviewed-head",
        "statusCheckRollup": [
            {"__typename": "StatusContext", "context": "build", "state": "SUCCESS"},
            {"__typename": "CheckRun", "name": "build", "conclusion": "SUCCESS"},
        ],
    }
    assert cli.ci_build_status(meta, "reviewed-head") == "success"
    # A CheckRun that has not concluded must not be read through the StatusContext branch.
    meta["statusCheckRollup"][1] = {
        "__typename": "CheckRun", "name": "build", "conclusion": None, "state": "SUCCESS",
    }
    assert cli.ci_build_status(meta, "reviewed-head") == ""
    # StatusContext-only states that are not SUCCESS stay untrusted.
    for state in ("ERROR", "EXPECTED", "PENDING"):
        assert cli.ci_build_status({
            "headRefOid": "reviewed-head",
            "statusCheckRollup": [
                {"__typename": "StatusContext", "context": "build", "state": state}],
        }, "reviewed-head") == "", state


def test_build_hint_never_uses_another_head_or_unverified_success():
    success = {"context": "build", "state": "SUCCESS"}
    for meta in (
        {"headRefOid": "newer-head", "statusCheckRollup": [success]},
        {"statusCheckRollup": [success]},
        {"headRefOid": "reviewed-head", "statusCheckRollup": None},
        {"headRefOid": "reviewed-head", "statusCheckRollup": [
            {"context": "scope", "state": "SUCCESS"}]},
        {"headRefOid": "reviewed-head", "statusCheckRollup": [
            {"context": "build", "state": "PENDING"}]},
        {"headRefOid": "reviewed-head", "statusCheckRollup": [
            {"context": "build", "state": "FAILURE"}]},
        {"headRefOid": "reviewed-head", "statusCheckRollup": [
            {"name": "build", "conclusion": "SKIPPED"}]},
        {"headRefOid": "reviewed-head", "statusCheckRollup": [
            success, {"name": "build", "conclusion": None, "status": "IN_PROGRESS"}]},
        {"headRefOid": "reviewed-head", "statusCheckRollup": [
            success, {"name": "build", "conclusion": "FAILURE"}]},
    ):
        status = cli.ci_build_status(meta, "reviewed-head")
        assert status == "", meta
        assert reviewers.ci_status_block(status, "reviewed-head") == "", meta


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
        print(f"ok  {test.__name__}")
    print(f"\nall {len(tests)} CLI checks passed")
