"""Working out where a relative submodule URL actually points.

.gitmodules almost always holds a relative URL -- `git submodule add
../sibling.git` writes one -- while .git/config holds the absolute URL git
worked out when the submodule was initialised. Comparing those two strings
directly would report every submodule ever added as a mismatch, so the
relative one has to be resolved first.

git's rules for that are not obvious. `../x` drops the last path segment of
the superproject's URL, so on `https://h/acme/super.git` it means
`https://h/acme/x`; `./x` drops nothing, so it means
`https://h/acme/super.git/x`; and with no remote at all it resolves against
the superproject's own directory on disk.

Rather than reimplement that, unlinked builds a throwaway repository, points
it at the same URL, and runs `git submodule sync` -- which is the code path
that does the resolving. The answer therefore comes from the git that is
installed, which is the git that will actually do the fetching.
"""

import tempfile

from .gitcmd import GitError, config_pairs, run, run_ok, split_subsection

PLACEHOLDER = "unlinked://placeholder"


def is_relative(url):
    """Relative in git's sense: ./ or ../ . Nothing else counts."""
    return url.startswith("./") or url.startswith("../")


def resolve_urls(entries, remote_url, root):
    """Return {name: resolved_url} for every entry with a URL.

    Absolute URLs are returned unchanged; git leaves them alone too.
    Relative ones go through the scratch repository. A failure there is not
    fatal -- the name is simply absent from the result, and the caller
    treats an unresolved URL as unknown rather than as a mismatch.
    """
    resolved = {}
    relative = {}
    for entry in entries:
        if not entry.url:
            continue
        if is_relative(entry.url):
            relative[entry.name] = entry.url
        else:
            resolved[entry.name] = entry.url

    if not relative:
        return resolved

    # With no remote, git resolves against the superproject's own path, so
    # the scratch repository has to be told where the real one lives or the
    # answer would depend on where our temporary directory happened to be.
    base = remote_url or root
    try:
        resolved.update(_ask_git(relative, base))
    except GitError:
        pass
    return resolved


def _ask_git(relative, base):
    with tempfile.TemporaryDirectory(prefix="unlinked-") as scratch:
        run(("init", "--quiet", scratch))
        run(("config", "remote.origin.url", base), cwd=scratch)

        for index, (name, url) in enumerate(sorted(relative.items()), start=1):
            path = f"s{index}"
            run(("config", "--file", ".gitmodules", f"submodule.{name}.path", path), cwd=scratch)
            run(("config", "--file", ".gitmodules", f"submodule.{name}.url", url), cwd=scratch)
            # `submodule sync` only touches submodules that are already
            # initialised, so each one needs a URL in config to overwrite
            # and a gitlink in the index to be found by. The sha need not
            # exist as an object; nothing resolves it.
            run(("config", f"submodule.{name}.url", PLACEHOLDER), cwd=scratch)
            run(("update-index", "--add", "--cacheinfo", f"160000,{'0' * 39}1,{path}"), cwd=scratch)

        # Offline by construction: sync only rewrites config.
        ok, _ = run_ok(("submodule", "sync"), cwd=scratch)
        if not ok:
            return {}

        _, out = run_ok(("config", "-z", "--get-regexp", r"^submodule\..*\.url"), cwd=scratch)
        answers = {}
        for key, value in config_pairs(out):
            name, leaf = split_subsection(key)
            if leaf == "url" and name in relative and value != PLACEHOLDER:
                answers[name] = value
        return answers


def same_place(a, b):
    """Whether two URLs name the same remote, as far as we can tell.

    Only the differences that are definitely cosmetic are forgiven: a
    trailing slash, and a trailing `.git`. `https://h/a/b` and
    `https://h/a/b.git` are the same repository on every host anyone uses,
    and reporting that pair as a mismatch would be noise. Anything else --
    scheme, host, user, a different path -- is a real difference, because
    fetching from it really does go somewhere else.
    """
    return _canon(a) == _canon(b)


def _canon(url):
    url = url.rstrip("/")
    if url.endswith(".git"):
        url = url[: -len(".git")]
    return url
