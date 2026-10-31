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


class GitError(Exception):
    """git could not answer. Never a finding -- always an exit 2."""


def run(args, cwd=None, check=True):
    """Run git and return stdout. Raise GitError when it fails."""
    try:
        proc = subprocess.run(
            ("git", *args),
            cwd=cwd,
            capture_output=True,
            text=True,
            # A submodule URL is not ours to execute and a hook is not ours to
            # run. Nothing here needs either.
            env=_env(),
        )
    except FileNotFoundError:
        raise GitError("git is not on PATH") from None
    except OSError as exc:  # pragma: no cover - depends on the OS
        raise GitError(f"could not run git: {exc}") from None
    if check and proc.returncode != 0:
        detail = proc.stderr.strip().splitlines()
        first = detail[0] if detail else f"git exited {proc.returncode}"
        raise GitError(first.removeprefix("fatal: ").removeprefix("error: "))
    return proc.stdout


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
    rest = key[len(prefix):]
    name, sep, leaf = rest.rpartition(".")
    if not sep:
        return None, None
    return name, leaf
