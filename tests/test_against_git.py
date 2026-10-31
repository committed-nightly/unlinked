"""The suite that makes this repository worth anything.

Each test builds a repository in the shape unlinked claims to find, then
runs the real git command whose behaviour the finding's text describes, and
fails if git does something else. If git changes its mind about any of
this, these break before a user has to notice.
"""

import os

import pytest

from unlinked.analyse import (
    NO_ENTRY, NO_GITLINK, NO_URL, STALE_URL, UPDATE_NONE, audit,
)
from unlinked.facts import gather
from unlinked.resolve import resolve_urls

from . import git_oracle as g

pytestmark = pytest.mark.git


@pytest.fixture(autouse=True)
def _needs_git():
    if not g.have_git():
        pytest.skip("git is not installed")


def kinds_at(result, where):
    return {f.kind for f in result.findings if f.where == where}


def only_kinds(result):
    return sorted(f.kind for f in result.findings)


# --------------------------------------------------------------------------
# no-entry: a gitlink nothing in .gitmodules maps.
# --------------------------------------------------------------------------

@pytest.fixture
def orphan_gitlink(tmp_path):
    """A repository with two submodules, one of which lost its .gitmodules
    block while keeping its gitlink."""
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    libb = g.make_remote(root, "libb")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.add_submodule(super_path, libb, "vendor/libb")
    g.gitmodules_drop(super_path, "vendor/libb")
    g.commit_all(super_path, "drop libb from .gitmodules")
    return super_path


def test_finds_the_orphan_gitlink(orphan_gitlink):
    result = audit(gather(orphan_gitlink))
    assert kinds_at(result, "vendor/libb") == {NO_ENTRY}
    assert only_kinds(result) == [NO_ENTRY]


def test_recursive_clone_exits_zero_and_leaves_it_empty(orphan_gitlink, tmp_path):
    """The claim in the no-entry text, measured.

    This is the reason the finding exists: the command everybody uses
    succeeds, so there is no error to go looking for.
    """
    into = str(tmp_path / "fresh")
    proc = g.clone(orphan_gitlink, into, recurse=True)
    assert proc.returncode == 0, proc.stderr
    assert g.populated(into, "vendor/liba")
    assert not g.populated(into, "vendor/libb")


def test_update_init_exits_128_and_strands_the_others(orphan_gitlink, tmp_path):
    """The second half of the claim: one orphan takes the rest down with it."""
    into = str(tmp_path / "plain")
    assert g.clone(orphan_gitlink, into).returncode == 0
    proc = g.submodule_update(into)
    assert proc.returncode == 128, proc.stdout + proc.stderr
    assert "No url found for submodule path 'vendor/libb'" in proc.stderr
    # liba is fine in every committed sense and is still not there.
    assert not g.populated(into, "vendor/liba")


def test_git_status_stays_clean_so_nothing_prompts_you(orphan_gitlink, tmp_path):
    into = str(tmp_path / "quiet")
    g.clone(orphan_gitlink, into, recurse=True)
    proc = g.git("status", "--porcelain", cwd=into)
    assert proc.stdout == ""


# --------------------------------------------------------------------------
# no-gitlink: a .gitmodules block with no gitlink to match.
# --------------------------------------------------------------------------

@pytest.fixture
def ghost_entry(tmp_path):
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.gitmodules_set(super_path, "ghost", "path", "vendor/ghost")
    g.gitmodules_set(super_path, "ghost", "url", liba)
    g.commit_all(super_path, "declare a submodule with no gitlink")
    return super_path


def test_finds_the_ghost_entry(ghost_entry):
    result = audit(gather(ghost_entry))
    assert kinds_at(result, ".gitmodules:ghost") == {NO_GITLINK}


def test_git_never_registers_a_ghost_entry(ghost_entry, tmp_path):
    """The claim: the block is inert, not merely unsatisfied."""
    into = str(tmp_path / "fresh")
    assert g.clone(ghost_entry, into).returncode == 0
    proc = g.submodule_update(into)
    assert proc.returncode == 0, proc.stderr
    # git mentions liba and has nothing at all to say about ghost.
    assert "vendor/liba" in proc.stdout
    assert "ghost" not in proc.stdout + proc.stderr
    assert g.config_url(into, "ghost") is None
    assert not os.path.exists(os.path.join(into, "vendor/ghost"))


def test_entry_with_no_path_at_all(tmp_path):
    root = str(tmp_path)
    super_path = g.make_super(root)
    g.gitmodules_set(super_path, "nameonly", "url", "https://example.invalid/x.git")
    g.commit_all(super_path, "a block with no path")
    result = audit(gather(super_path))
    assert only_kinds(result) == [NO_GITLINK]


# --------------------------------------------------------------------------
# no-url: declared, pinned, nowhere to clone from.
# --------------------------------------------------------------------------

@pytest.fixture
def missing_url(tmp_path):
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.git("config", "--file", ".gitmodules", "--unset",
          "submodule.vendor/liba.url", cwd=super_path)
    g.commit_all(super_path, "lose the url")
    return super_path


def test_finds_the_missing_url(missing_url):
    result = audit(gather(missing_url))
    assert kinds_at(result, ".gitmodules:vendor/liba") == {NO_URL}


def test_missing_url_is_what_git_complains_about(missing_url, tmp_path):
    into = str(tmp_path / "fresh")
    g.clone(missing_url, into)
    proc = g.submodule_update(into)
    assert proc.returncode == 128
    assert "No url found for submodule path 'vendor/liba'" in proc.stderr


# --------------------------------------------------------------------------
# update-none: skipped, exit 0, empty directory.
# --------------------------------------------------------------------------

@pytest.fixture
def update_none(tmp_path):
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.gitmodules_set(super_path, "vendor/liba", "update", "none")
    g.commit_all(super_path, "update = none")
    return super_path


def test_finds_update_none(update_none):
    result = audit(gather(update_none))
    assert kinds_at(result, ".gitmodules:vendor/liba") == {UPDATE_NONE}


def test_update_none_skips_silently_and_exits_zero(update_none, tmp_path):
    into = str(tmp_path / "fresh")
    g.clone(update_none, into)
    proc = g.submodule_update(into)
    assert proc.returncode == 0, proc.stderr
    assert "Skipping submodule 'vendor/liba'" in proc.stdout + proc.stderr
    assert not g.populated(into, "vendor/liba")


def test_update_none_is_not_reported_when_the_value_is_anything_else(tmp_path):
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    for value in ("checkout", "rebase", "merge"):
        g.gitmodules_set(super_path, "vendor/liba", "update", value)
        g.commit_all(super_path, f"update = {value}")
        result = audit(gather(super_path))
        assert only_kinds(result) == [], f"{value} was reported"


# --------------------------------------------------------------------------
# stale-url: the committed URL changed and this clone did not notice.
# --------------------------------------------------------------------------

@pytest.fixture
def stale_url(tmp_path):
    """A clone that was initialised against liba, in a superproject whose
    .gitmodules has since been repointed at libb."""
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    libb = g.make_remote(root, "libb")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    into = str(tmp_path / "working")
    g.clone(super_path, into)
    g.submodule_update(into)
    g.gitmodules_set(into, "vendor/liba", "url", libb)
    g.commit_all(into, "repoint at libb")
    return into, liba, libb


def test_finds_the_stale_url(stale_url):
    into, liba, _libb = stale_url
    result = audit(gather(into))
    assert kinds_at(result, ".gitmodules:vendor/liba") == {STALE_URL}
    finding = result.findings[0]
    assert finding.extra["configured"] == liba
    assert finding.scope == "local"


def test_the_stale_url_is_where_git_really_fetches_from(stale_url):
    """The claim: .git/config wins, and goes on winning."""
    into, liba, libb = stale_url
    proc = g.git(*g.FILE_OK, "submodule", "foreach", "--quiet",
                 "git remote get-url origin", cwd=into)
    assert liba in proc.stdout
    assert libb not in proc.stdout


def test_submodule_sync_is_the_fix_and_clears_the_finding(stale_url):
    into, _liba, libb = stale_url
    assert g.sync_url(into, "vendor/liba") == libb
    result = audit(gather(into))
    assert only_kinds(result) == []


def test_committed_only_hides_the_local_finding(stale_url):
    into, _liba, _libb = stale_url
    assert only_kinds(audit(gather(into), local_checks=False)) == []


# --------------------------------------------------------------------------
# The resolver, checked against git's own answer rather than a table.
# --------------------------------------------------------------------------

RELATIVE_CASES = [
    ("https://github.com/acme/super.git", "../sub.git"),
    ("https://github.com/acme/super.git", "../../other/sub.git"),
    ("https://github.com/acme/super.git", "./nested/sub.git"),
    ("https://github.com/acme/super", "../sub.git"),
    ("git@github.com:acme/super.git", "../sub.git"),
    ("git@github.com:acme/super.git", "../../other/sub.git"),
    ("ssh://git@h/a/b/super.git", "../../other/sub.git"),
    ("/abs/path/super", "../../other/sub.git"),
    ("../sibling/super", "../sub.git"),
]


@pytest.mark.parametrize("remote,relative", RELATIVE_CASES)
def test_resolver_agrees_with_real_git(tmp_path, remote, relative):
    """unlinked's resolved URL must be the one git would write.

    git is the oracle here, not a list of expected strings: if these two
    ever disagree, the stale-url finding is reporting a difference that
    does not exist.
    """
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    into = str(tmp_path / "working")
    g.clone(super_path, into)
    g.submodule_update(into)

    g.git("config", "remote.origin.url", remote, cwd=into)
    g.gitmodules_set(into, "vendor/liba", "url", relative)
    g.commit_all(into, "relative url")

    facts = gather(into)
    ours = resolve_urls(facts.entries, facts.remote_url, facts.root)["vendor/liba"]
    theirs = g.sync_url(into, "vendor/liba")
    assert ours == theirs


def test_resolver_agrees_with_git_when_there_is_no_remote(tmp_path):
    """The case where git resolves against the superproject's own directory,
    which is the one a scratch repository would get wrong if it did not
    know where the real repository lives."""
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.gitmodules_set(super_path, "vendor/liba", "url", "../remotes/liba")
    g.commit_all(super_path, "relative url, no remote")
    g.git("config", "--unset", "remote.origin.url", cwd=super_path, check=False)

    facts = gather(super_path)
    ours = resolve_urls(facts.entries, facts.remote_url, facts.root)["vendor/liba"]
    theirs = g.sync_url(super_path, "vendor/liba")
    assert ours == theirs


def test_a_relative_url_alone_is_not_a_finding(tmp_path):
    """The false positive this tool would otherwise produce on every
    repository that ever ran `git submodule add ../sibling`."""
    root = str(tmp_path)
    g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, os.path.join(root, "remotes", "liba"),
                    "vendor/liba")
    g.gitmodules_set(super_path, "vendor/liba", "url", "../remotes/liba")
    g.commit_all(super_path, "use the relative form")
    g.sync_url(super_path, "vendor/liba")
    assert only_kinds(audit(gather(super_path))) == []


# --------------------------------------------------------------------------
# Not finding things.
# --------------------------------------------------------------------------

def test_a_healthy_repository_reports_nothing(tmp_path):
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    libb = g.make_remote(root, "libb")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.add_submodule(super_path, libb, "deps/libb")
    into = str(tmp_path / "working")
    g.clone(super_path, into)
    g.submodule_update(into)
    result = audit(gather(into))
    assert only_kinds(result) == []
    assert not result.declares_nothing


def test_a_repository_with_no_submodules_is_not_called_clean(tmp_path):
    """logbook#59: "nothing to report" and "nothing to check" are different
    answers, and conflating them is how a check that asserts nothing passes
    for months."""
    super_path = g.make_super(str(tmp_path))
    result = audit(gather(super_path))
    assert result.declares_nothing
    assert only_kinds(result) == []


def test_a_wholly_uninitialised_clone_says_nothing_per_submodule(tmp_path):
    """A fresh clone has initialised nothing, and that is not news. Twenty
    notes saying so on a repository with twenty submodules is how output
    gets skipped -- so it becomes one sentence in the summary instead."""
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    libb = g.make_remote(root, "libb")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.add_submodule(super_path, libb, "vendor/libb")
    into = str(tmp_path / "working")
    g.clone(super_path, into)
    result = audit(gather(into))
    assert only_kinds(result) == []
    assert result.notes == []
    assert result.uninitialised is True


def test_a_half_initialised_clone_notes_the_gap(tmp_path):
    """The shape worth saying something about: `submodule update --init`
    stops at the first submodule it cannot do, so one left behind while its
    neighbours are fine is often where it stopped."""
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    libb = g.make_remote(root, "libb")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.add_submodule(super_path, libb, "vendor/libb")
    into = str(tmp_path / "working")
    g.clone(super_path, into)
    # --init takes a path, and registers only that one. libb's URL never
    # reaches .git/config, which is exactly the gap being tested.
    g.submodule_update(into, "vendor/liba")
    assert g.config_url(into, "vendor/liba") is not None
    assert g.config_url(into, "vendor/libb") is None

    result = audit(gather(into))
    assert only_kinds(result) == []
    assert result.uninitialised is False
    assert [(n.kind, n.path) for n in result.notes] == [
        ("not-initialised", "vendor/libb"),
    ]


def test_submodule_name_containing_a_dot(tmp_path):
    """`submodule.vendor/lib.a.path` has to split on the last dot, not the
    first, or the name comes out as `vendor/lib` and nothing matches."""
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/lib.a")
    facts = gather(super_path)
    assert [e.name for e in facts.entries] == ["vendor/lib.a"]
    assert facts.entries[0].path == "vendor/lib.a"
    assert only_kinds(audit(facts)) == []


def test_name_that_differs_from_path_is_matched_by_path(tmp_path):
    """git looks a submodule up by name in .git/config and by path in the
    tree. A repository where the two differ is legal and common after a
    directory move, and must not be reported."""
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.git("mv", "vendor/liba", "vendor/renamed", cwd=super_path)
    g.commit_all(super_path, "move it, keeping the old name")
    facts = gather(super_path)
    assert facts.entries[0].name == "vendor/liba"
    assert facts.entries[0].path == "vendor/renamed"
    assert "vendor/renamed" in facts.gitlinks
    assert only_kinds(audit(facts)) == []


def test_duplicate_url_takes_the_last_one_like_git_does(tmp_path):
    """A .gitmodules with two `url =` lines for one submodule is a real
    shape -- FreeCAD has one in its history -- and which one wins decides
    where the clone comes from. Whatever git registers is what unlinked
    must think the URL is, or every comparison after it is against the
    wrong string."""
    root = str(tmp_path)
    first = g.make_remote(root, "first")
    second = g.make_remote(root, "second")
    super_path = g.make_super(root)
    g.add_submodule(super_path, first, "vendor/x")
    with open(f"{super_path}/.gitmodules", "w") as handle:
        handle.write(
            '[submodule "vendor/x"]\n\tpath = vendor/x\n'
            f"\turl = {first}\n\turl = {second}\n"
        )
    g.commit_all(super_path, "two urls")

    into = str(tmp_path / "working")
    g.clone(super_path, into)
    g.submodule_update(into)

    facts = gather(into)
    assert facts.entries[0].url == g.config_url(into, "vendor/x")


def test_rev_reads_the_declarations_as_they_were(tmp_path):
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.git("tag", "good", cwd=super_path)
    # Not commit_all: `git add -A` would put the gitlink straight back.
    g.git("rm", "--quiet", "--cached", "vendor/liba", cwd=super_path)
    g.git("commit", "--quiet", "-m", "drop the gitlink, keep the block",
          cwd=super_path)

    assert only_kinds(audit(gather(super_path, rev="good"))) == []
    assert only_kinds(audit(gather(super_path))) == [NO_GITLINK]


def test_rev_reads_that_revs_gitmodules_not_the_worktrees(tmp_path):
    """Found by running this over 1500 commits of FreeCAD: the gitlinks came
    from --rev and .gitmodules came from the working tree, so four healthy
    submodules were reported as broken because today's file does not
    describe a commit from 2024. Both halves must come from the same rev."""
    root = str(tmp_path)
    liba = g.make_remote(root, "liba")
    super_path = g.make_super(root)
    g.add_submodule(super_path, liba, "vendor/liba")
    g.git("tag", "then", cwd=super_path)

    # History moves on: the submodule is renamed, so today's .gitmodules
    # declares a path that did not exist at `then`, and does not declare
    # the one that did.
    g.git("mv", "vendor/liba", "vendor/moved", cwd=super_path)
    g.gitmodules_drop(super_path, "vendor/liba")
    g.gitmodules_set(super_path, "vendor/moved", "path", "vendor/moved")
    g.gitmodules_set(super_path, "vendor/moved", "url", liba)
    g.commit_all(super_path, "rename the submodule properly")

    assert only_kinds(audit(gather(super_path))) == []

    old = gather(super_path, rev="then")
    assert old.entries_source == "then:.gitmodules"
    assert [e.path for e in old.entries] == ["vendor/liba"]
    assert sorted(old.gitlinks) == ["vendor/liba"]
    assert only_kinds(audit(old, local_checks=False)) == []
