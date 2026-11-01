"""Running git.

Everything unlinked knows about a repository, it learns by asking git. The
alternative is a hand-written .gitmodules parser and a hand-written URL
resolver, and both would be a second opinion about git's behaviour rather
than a reading of it (logbook#48).

NUL-separated plumbing output throughout: a submodule path may contain a
newline, and `git config --list` without -z would then hand back a value
split across what look like two settings.
"""

import subprocess

GIT = "git"


class GitError(Exception):
    """git could not answer. Never a finding -- always an exit 2."""


def run(args, cwd=None, check=True):
    """Run git and return stdout. Raise GitError when it fails."""
    try:
        proc = subprocess.run(
            (GIT, *args),
            cwd=cwd,
            capture_output=True,
            text=True,
            # A submodule URL is not ours to execute and a hook is not ours to
            # run. Nothing here needs either.
            env=_env(),
        )
    except OSError as exc:
        raise GitError(_why_it_would_not_start(exc, cwd)) from None
    if check and proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()
        first = detail[0] if detail else f"git exited {proc.returncode}"
        raise GitError(first.removeprefix("fatal: ").removeprefix("error: "))
    return proc.stdout


def _why_it_would_not_start(exc, cwd):
    """Say which of the two missing things actually stopped us.

    subprocess raises out of _execute_child, before git runs at all, both for
    an executable it cannot find and for a `cwd` it cannot enter -- and it
    chdirs in the child before it execs, so a directory that is not there
    loses first and git never gets as far as being missing. Reporting all of
    it as "git is not on PATH" sent anyone who typo'd the one positional
    argument off to audit their $PATH for a tool that was never the problem.

    CPython names the path it actually failed on in `.filename` -- the cwd,
    or "git" -- which is the direct answer to which of the two it was, and
    the one `unapplied` settled on for the same question. Given the culprit,
    the errno picks the wording.
    """
    import errno
    import os

    at_fault = exc.filename
    if at_fault is None and cwd is not None:
        # Not CPython, or a CPython that stopped setting .filename. Ask the
        # directory directly rather than fall back to the guess that was the
        # bug. os.path.isdir is false for an unreadable parent as well as an
        # absent path, which is fine here: both are the cwd's fault, and the
        # errno below still says which.
        if not (os.path.isdir(cwd) and os.access(cwd, os.X_OK)):
            at_fault = os.fspath(cwd)

    if at_fault is not None and at_fault != GIT:
        if exc.errno == errno.EACCES:
            return "directory is not accessible"
        if exc.errno == errno.ENOTDIR:
            return "not a directory"
        return "no such directory"
    if isinstance(exc, FileNotFoundError):
        return "git is not on PATH"
    # The directory is fine and git is there, so this is the executable
    # itself: present but not runnable, or the OS declining for its own
    # reasons.
    return f"could not run git: {exc.strerror or exc}"


def run_ok(args, cwd=None):
    """Run git and return (ok, stdout). For questions where failure is an answer."""
    try:
        out = run(args, cwd=cwd, check=True)
    except GitError:
        return False, ""
    return True, out


def _env():
    import os

    env = dict(os.environ)
    # `git config --list` would otherwise fold in ~/.gitconfig and
    # /etc/gitconfig. unlinked reports on a repository, not on whoever is
    # running it, and a submodule.<name>.url in someone's global config is
    # not something their colleagues share.
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GIT_OPTIONAL_LOCKS"] = "0"
    return env


def parse_z(out):
    """Split NUL-terminated git output into records, dropping the empty tail."""
    return [rec for rec in out.split("\0") if rec]


def config_pairs(out):
    """Turn `git config -z --list` output into (key, value) pairs.

    In -z mode a record is `key\\nvalue`, and a valueless key (`[x]\\n\\ty`)
    is a record with no newline at all. Keys with no value are dropped --
    `submodule.x.url` with nothing after it is not a URL.
    """
    pairs = []
    for record in parse_z(out):
        key, sep, value = record.partition("\n")
        if sep:
            pairs.append((key, value))
    return pairs


def split_subsection(key, section="submodule"):
    """Split `submodule.<name>.<key>` into (name, key).

    The name is a git subsection and may contain dots -- `vendor/lib.a` is a
    real thing people write -- so the split is on the last dot, not the
    first. The trailing key never contains one.
    """
    prefix = section + "."
    if not key.startswith(prefix):
        return None, None
    rest = key[len(prefix) :]
    name, sep, leaf = rest.rpartition(".")
    if not sep:
        return None, None
    return name, leaf
