"""Building real repositories, and asking git what it does with them.

Nothing in here asserts an opinion about submodules. Each helper either
builds a repository in a known broken shape or runs a real git command and
reports what happened, so a test can compare unlinked's answer against
git's behaviour rather than against the author's recollection of it
(logbook#48).

Local paths are used as submodule URLs, which git refuses by default since
the 2.38 security fix, so every command that would touch one passes
`protocol.file.allow=always`. That is a deliberate relaxation for a
temporary repository under /tmp and is why these tests never go near a
network.
"""

import os
import shutil
import subprocess

FILE_OK = ("-c", "protocol.file.allow=always")

ENV = {
    **os.environ,
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_TERMINAL_PROMPT": "0",
    "HOME": "/nonexistent-unlinked-home",
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def git(*args, cwd, check=True):
    proc = subprocess.run(("git", *args), cwd=cwd, capture_output=True, text=True, env=ENV)
    if check and proc.returncode != 0:
        raise AssertionError(f"git {' '.join(args)} failed in {cwd}:\n{proc.stderr}")
    return proc


def have_git():
    return shutil.which("git") is not None


def make_remote(root, name, branch="main"):
    """A tiny repository to be used as a submodule."""
    path = os.path.join(root, "remotes", name)
    os.makedirs(path)
    git("init", "--quiet", "-b", branch, ".", cwd=path)
    with open(os.path.join(path, "f"), "w") as handle:
        handle.write(name + "\n")
    git("add", "-A", cwd=path)
    git("commit", "--quiet", "-m", "init", cwd=path)
    return path


def make_super(root, name="super", branch="main"):
    path = os.path.join(root, name)
    os.makedirs(path)
    git("init", "--quiet", "-b", branch, ".", cwd=path)
    with open(os.path.join(path, "README"), "w") as handle:
        handle.write("top\n")
    git("add", "-A", cwd=path)
    git("commit", "--quiet", "-m", "init", cwd=path)
    return path


def add_submodule(super_path, remote_path, at, message=None):
    git(*FILE_OK, "submodule", "add", "--quiet", remote_path, at, cwd=super_path)
    git("commit", "--quiet", "-m", message or f"add {at}", cwd=super_path)


def gitmodules_set(super_path, name, key, value):
    git("config", "--file", ".gitmodules", f"submodule.{name}.{key}", value, cwd=super_path)


def gitmodules_drop(super_path, name):
    git("config", "--file", ".gitmodules", "--remove-section", f"submodule.{name}", cwd=super_path)


def commit_all(super_path, message):
    git("add", "-A", cwd=super_path)
    git("commit", "--quiet", "-m", message, cwd=super_path)


def clone(super_path, into, recurse=False):
    args = [*FILE_OK, "clone", "--quiet"]
    if recurse:
        args.append("--recurse-submodules")
    proc = subprocess.run(("git", *args, super_path, into), capture_output=True, text=True, env=ENV)
    return proc


def submodule_update(repo, *extra):
    """Run `git submodule update --init` and report exactly what git did."""
    return subprocess.run(
        ("git", *FILE_OK, "submodule", "update", "--init", *extra),
        cwd=repo,
        capture_output=True,
        text=True,
        env=ENV,
    )


def populated(repo, path):
    """Whether a submodule directory actually has the checkout in it."""
    full = os.path.join(repo, path)
    return os.path.isdir(full) and bool([n for n in os.listdir(full) if n != ".git"])


def config_url(repo, name):
    proc = git("config", "--local", "--get", f"submodule.{name}.url", cwd=repo, check=False)
    return proc.stdout.strip() if proc.returncode == 0 else None


def sync_url(repo, name):
    """What real git computes for this submodule's URL. The oracle for
    unlinked's own resolver."""
    git(*FILE_OK, "submodule", "sync", "--quiet", cwd=repo, check=False)
    return config_url(repo, name)
