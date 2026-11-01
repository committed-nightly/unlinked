"""The command line: exit codes, and what gets printed on each of them.

The exit code is the part other programs read, and the thing it must never
do is say 0 about a repository unlinked failed to look at.
"""

import errno
import json

import pytest

from unlinked.cli import main
from unlinked.gitcmd import _why_it_would_not_start

from . import git_oracle as g

pytestmark = pytest.mark.git


@pytest.fixture(autouse=True)
def _needs_git():
    if not g.have_git():
        pytest.skip("git is not installed")


@pytest.fixture
def broken(tmp_path):
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    libb = g.make_remote(root, "libb")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.add_submodule(super_path, libb, "vendor/libb")
    g.gitmodules_drop(super_path, "vendor/libb")
    g.commit_all(super_path, "drop libb")
    return super_path


def test_exit_1_and_names_the_place(broken, capsys):
    assert main([broken]) == 1
    out = capsys.readouterr().out
    assert "vendor/libb" in out
    assert "no-entry" in out


def test_exit_0_on_a_healthy_repository(tmp_path, capsys):
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    assert main([super_path]) == 0
    assert "Every submodule declaration lines up" in capsys.readouterr().out


def test_exit_0_but_says_there_was_nothing_to_check(tmp_path, capsys):
    """logbook#59. A repository with no submodules must not get the same
    sentence as one whose submodules are all fine -- that sentence is how a
    check ends up asserting nothing for months without anyone noticing."""
    super_path = g.make_super(str(tmp_path))
    assert main([super_path]) == 0
    out = capsys.readouterr().out
    assert "No submodules here" in out
    assert "Nothing to check." in out
    assert "lines up" not in out


def test_exit_2_when_it_is_not_a_repository(tmp_path, capsys):
    assert main([str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == "", "nothing may go to stdout on a failed run"
    assert "unlinked:" in captured.err


def test_exit_2_on_a_path_that_does_not_exist(tmp_path, capsys):
    """The one that used to lie. `subprocess.run` raises FileNotFoundError
    for a cwd that is not there as well as for a git that is not there, and
    the handler blamed $PATH for both -- so a typo in REPO, the only
    positional argument, sent the reader off to audit their $PATH for a tool
    that was sitting on it."""
    assert main([str(tmp_path / "not-cloned-yet")]) == 2
    captured = capsys.readouterr()
    assert captured.out == "", "nothing may go to stdout on a failed run"
    assert "no such directory" in captured.err
    assert "PATH" not in captured.err, "git is on the PATH; saying otherwise is the bug"


def test_exit_2_when_the_path_is_a_file(tmp_path, capsys):
    """Where tab completion lands: `unlinked README.md`. The same mistake one
    errno along, in the sibling handler, which printed a bare [Errno 20] and
    a repr of the path."""
    handle = tmp_path / "README.md"
    handle.write_text("not a repository\n")
    assert main([str(handle)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not a directory" in captured.err
    assert "PATH" not in captured.err
    assert "Errno" not in captured.err, "an errno is not an explanation"


def test_a_genuinely_missing_git_is_still_reported_as_missing(tmp_path, monkeypatch, capsys):
    """The guard in the other direction. The fix must not turn a real
    "git is not on PATH" into a complaint about the directory, so: a cwd that
    certainly exists, and nothing on PATH."""
    empty = tmp_path / "bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert main([str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "git is not on PATH" in captured.err


def test_a_git_that_will_not_execute_is_not_blamed_on_the_directory(tmp_path, monkeypatch, capsys):
    """The case that earns the cwd check: identical EACCES, but the directory
    is fine, so it really is about the executable. A file with no execute bit
    fails to exec for root too, so this needs no uid and never skips -- CI
    asserts zero skips."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    (bindir / "git").write_text("#!/bin/sh\necho hi\n")  # mode 0644: present, not runnable
    monkeypatch.setenv("PATH", str(bindir))
    assert main([str(tmp_path)]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "could not run git" in captured.err
    assert "no such directory" not in captured.err


def test_a_directory_that_cannot_be_entered_is_described_as_such(tmp_path):
    """A `chmod 000` does not stop root, so this one cannot be built
    end-to-end without skipping itself in a root container -- and CI counts a
    skip as a test that did not run. Asserted against the handler instead,
    with the exception CPython would raise: `.filename` names the directory,
    so the directory is at fault, and EACCES supplies the wording."""
    closed = tmp_path / "behind-a-closed-door"
    denied = PermissionError(errno.EACCES, "Permission denied", str(closed))
    assert _why_it_would_not_start(denied, str(closed)) == "directory is not accessible"


def test_the_exception_wins_over_a_directory_that_looks_fine_now(tmp_path):
    """Why `.filename` is asked first and the stat is only a fallback: between
    the failed chdir and any stat of our own, the directory can come back.
    Then the stat says the cwd is fine and the only conclusion left is the
    wrong one -- that git is missing. The exception already knows."""
    gone_and_back = FileNotFoundError(errno.ENOENT, "No such file or directory", str(tmp_path))
    assert tmp_path.is_dir(), "the premise: the stat would now say this is fine"
    assert _why_it_would_not_start(gone_and_back, str(tmp_path)) == "no such directory"


def test_the_culprit_is_still_found_without_a_filename_on_the_exception(tmp_path):
    """`.filename` is a CPython detail. If it is ever absent the fallback asks
    the directory rather than reverting to the guess that was the bug."""
    absent = str(tmp_path / "not-cloned-yet")
    bare = FileNotFoundError(errno.ENOENT, "No such file or directory")
    assert bare.filename is None, "the premise of this test"
    assert _why_it_would_not_start(bare, absent) == "no such directory"
    # ...and with no cwd to blame it is still git that is missing.
    assert _why_it_would_not_start(bare, None) == "git is not on PATH"


def test_when_both_are_missing_the_directory_is_blamed(tmp_path, monkeypatch, capsys):
    """subprocess chdirs before it execs, so an absent cwd is the failure the
    OS reports even when git is absent too. Naming the directory is right:
    fixing the PATH would not get the user any further."""
    empty = tmp_path / "bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))
    assert main([str(tmp_path / "not-cloned-yet")]) == 2
    assert "no such directory" in capsys.readouterr().err


def test_exit_2_on_a_rev_that_does_not_exist(broken, capsys):
    assert main([broken, "--rev", "v99.0.0"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not a revision" in captured.err


def test_exit_2_on_an_unparseable_gitmodules(tmp_path, capsys):
    """A .gitmodules git refuses to read is an error, not a clean result:
    there is no finding we could print about it that would be true."""
    super_path = g.make_super(str(tmp_path))
    with open(f"{super_path}/.gitmodules", "w") as handle:
        handle.write('[submodule "x"\n  path = y\n')
    assert main([super_path]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "cannot parse" in captured.err


def test_quiet_still_reports_every_finding(broken, capsys):
    assert main([broken, "-q"]) == 1
    out = capsys.readouterr().out
    assert "no-entry" in out
    assert "vendor/libb" in out


def test_json_is_json_and_carries_the_counts(broken, capsys):
    assert main([broken, "--json"]) == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["kinds"] == {"no-entry": 1}
    assert payload["counts"]["committed"] == 1
    assert payload["declares_nothing"] is False
    assert payload["findings"][0]["path"] == "vendor/libb"
    assert payload["findings"][0]["scope"] == "committed"


def test_json_on_a_repository_with_no_submodules(tmp_path, capsys):
    super_path = g.make_super(str(tmp_path))
    assert main([super_path]) == 0
    capsys.readouterr()
    assert main([super_path, "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["declares_nothing"] is True
    assert payload["findings"] == []


def test_defaults_to_the_current_directory(broken, monkeypatch, capsys):
    monkeypatch.chdir(broken)
    assert main([]) == 1
    assert "vendor/libb" in capsys.readouterr().out


def test_runs_from_a_subdirectory(broken, monkeypatch, capsys):
    """git reports tree paths relative to the cwd unless told otherwise, so
    reading them from a subdirectory found no gitlinks at all and called
    every healthy submodule in the repository no-gitlink. The answer must
    not depend on where you are standing."""
    import os

    from unlinked.facts import gather

    os.makedirs(f"{broken}/deep/down", exist_ok=True)
    monkeypatch.chdir(f"{broken}/deep/down")

    facts = gather(".")
    assert sorted(facts.gitlinks) == ["vendor/liba", "vendor/libb"]
    assert [e.name for e in facts.entries] == ["vendor/liba"]
    assert facts.entries_source == ".gitmodules", "read the worktree copy"
    assert facts.root == os.path.realpath(broken)

    assert main([]) == 1
    out = capsys.readouterr().out
    assert "vendor/libb" in out
    assert "no-gitlink" not in out, "liba is fine and must not be reported"
