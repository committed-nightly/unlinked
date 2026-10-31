"""What a repository says about its submodules.

Three separate things get called "the submodules" and they disagree with
each other constantly, which is the whole reason this tool exists:

  gitlinks   mode 160000 entries in a commit's tree. The pinned commit.
  entries    `[submodule "name"]` blocks in .gitmodules. The declaration.
  local      submodule.* in .git/config. What this one clone will do.

A submodule only works when all three line up, and git's error messages
name whichever one it noticed first.
"""

from .gitcmd import GitError, config_pairs, parse_z, run, run_ok, split_subsection

GITLINK_MODE = "160000"


class Entry:
    """One `[submodule "<name>"]` block in .gitmodules."""

    def __init__(self, name, settings):
        self.name = name
        self.settings = settings

    @property
    def path(self):
        return self.settings.get("path")

    @property
    def url(self):
        return self.settings.get("url")

    @property
    def update(self):
        return self.settings.get("update")

    def __repr__(self):  # pragma: no cover - debugging only
        return f"Entry({self.name!r}, {self.settings!r})"


class Facts:
    def __init__(self, root, rev, gitlinks, entries, local, remote_url,
                 entries_source, bare):
        self.root = root
        self.rev = rev
        self.gitlinks = gitlinks          # path -> commit sha
        self.entries = entries            # list[Entry], config order
        self.local = local                # name -> {key: value}
        self.remote_url = remote_url
        self.entries_source = entries_source
        self.bare = bare

    @property
    def declares_nothing(self):
        return not self.gitlinks and not self.entries


def gather(path, rev="HEAD"):
    """Ask git everything unlinked needs. Raises GitError if it cannot.

    Every question after the first is asked from the top level of the
    repository, never from `path`. Run from a subdirectory, `git ls-tree`
    reports paths relative to the cwd and `--file .gitmodules` looks for a
    file that is not there -- which made every submodule in the repository
    look like it had no gitlink, purely because of where you were standing.
    """
    root = run(("rev-parse", "--show-toplevel"), cwd=path).strip()
    if not root:
        # A bare repository has no toplevel. There is still a tree to read.
        root = run(("rev-parse", "--absolute-git-dir"), cwd=path).strip()
    bare = run(("rev-parse", "--is-bare-repository"), cwd=root).strip() == "true"

    # Resolve the rev up front so a typo'd --rev is an error and not an
    # empty tree reported as "no submodules here".
    ok, _ = run_ok(("rev-parse", "--verify", f"{rev}^{{tree}}"), cwd=root)
    if not ok:
        raise GitError(f"{rev}: not a revision in this repository")

    gitlinks = _gitlinks(root, rev)
    entries, source = _entries(root, rev, bare)
    local = _local(root)
    _, remote = run_ok(("config", "--local", "--get", "remote.origin.url"), cwd=root)

    return Facts(root, rev, gitlinks, entries, local, remote.strip(), source, bare)


def _gitlinks(path, rev):
    # --full-tree so the listing is rooted at the repository rather than at
    # the cwd, and so the paths match what .gitmodules declares.
    out = run(("ls-tree", "-r", "-z", "--full-tree", rev), cwd=path)
    links = {}
    for record in parse_z(out):
        info, sep, name = record.partition("\t")
        if not sep:
            continue
        fields = info.split(" ")
        if len(fields) == 3 and fields[0] == GITLINK_MODE:
            links[name] = fields[2]
    return links


def _entries(path, rev, bare):
    """Read .gitmodules, preferring the worktree copy because git does.

    `git submodule` acts on the file in the working tree; an uncommitted
    edit there is live. With no worktree copy -- a bare repository, or
    somebody deleted it without committing that -- fall back to the blob.
    """
    source = f"{rev}:.gitmodules"
    if not bare:
        ok, out = run_ok(
            ("config", "-z", "--file", ".gitmodules", "--list"), cwd=path,
        )
        if ok:
            return _parse_entries(out), ".gitmodules"
        # Distinguish "no such file" from "that file is not parseable". The
        # second is an error: no finding we could print would be true.
        import os

        if os.path.exists(os.path.join(path, ".gitmodules")):
            raise GitError(".gitmodules: git cannot parse this file")

    ok, out = run_ok(("config", "-z", "--blob", f"{rev}:.gitmodules", "--list"), cwd=path)
    if not ok:
        return [], None
    return _parse_entries(out), source


def _parse_entries(out):
    order = []
    settings = {}
    for key, value in config_pairs(out):
        name, leaf = split_subsection(key)
        if name is None:
            continue
        if name not in settings:
            settings[name] = {}
            order.append(name)
        # Last one wins, which is what git does for a repeated key.
        settings[name][leaf] = value
    return [Entry(name, settings[name]) for name in order]


def _local(path):
    ok, out = run_ok(
        ("config", "--local", "-z", "--get-regexp", r"^submodule\."), cwd=path,
    )
    if not ok:
        return {}
    local = {}
    for key, value in config_pairs(out):
        name, leaf = split_subsection(key)
        if name is None:
            continue
        local.setdefault(name, {})[leaf] = value
    return local
