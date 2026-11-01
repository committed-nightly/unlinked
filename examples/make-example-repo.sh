#!/bin/sh
# Build the repository the README quotes.
#
# The example cannot be committed as files: a broken submodule declaration
# needs a real gitlink to be broken about, and committing one into this
# repository would hand everybody who clones it an empty directory and a
# `git submodule update --init` that exits 128. So it gets built instead,
# which has the better property anyway -- the README's output is reproduced
# from scratch on every CI run rather than pasted and left to rot.
#
# Usage: examples/make-example-repo.sh /path/to/build/in
# Prints the path of the finished superproject.
set -eu

dest=${1:?usage: make-example-repo.sh DEST}
mkdir -p "$dest"
dest=$(cd "$dest" && pwd)

export GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=example GIT_AUTHOR_EMAIL=example@invalid
export GIT_COMMITTER_NAME=example GIT_COMMITTER_EMAIL=example@invalid
# Fixed dates, so the commit the gitlink is pinned at has the same hash on
# every machine and the README can quote unlinked's output exactly.
export GIT_AUTHOR_DATE='2026-01-01T00:00:00+0000'
export GIT_COMMITTER_DATE='2026-01-01T00:00:00+0000'

# Local paths as submodule URLs are refused by default since git 2.38.
# Everything here is under a temporary directory we just created.
git_file() { git -c protocol.file.allow=always "$@"; }

for name in logging parser widgets; do
    mkdir -p "$dest/remotes/$name"
    (
        cd "$dest/remotes/$name"
        git init --quiet -b main .
        echo "$name" > README
        git add -A
        git commit --quiet -m init
    )
done

super="$dest/app"
mkdir -p "$super"
cd "$super"
git init --quiet -b main .
echo "app" > README
git add -A
git commit --quiet -m init
git config remote.origin.url https://github.com/example/app.git

for name in logging parser widgets; do
    git_file submodule add --quiet "$dest/remotes/$name" "vendor/$name"
done
git commit --quiet -m "vendor logging, parser and widgets"

# 1. no-entry -- somebody removed the block and left the gitlink. This is
#    what `git rm --cached` does if you stop there.
git config --file .gitmodules --remove-section submodule.vendor/widgets
git commit --quiet -am "stop vendoring widgets"

# 2. no-gitlink -- a block whose directory moved, with the old path left
#    behind. The submodule still works; this second block is scenery.
git config --file .gitmodules submodule.vendor/old-parser.path vendor/old-parser
git config --file .gitmodules submodule.vendor/old-parser.url \
    https://github.com/example/parser.git
git commit --quiet -am "note where parser used to live"

# 3. update-none -- added so a slow clone would skip it, which also means
#    nobody's checkout has ever contained it.
git config --file .gitmodules submodule.vendor/logging.update none
git commit --quiet -am "skip logging on clone"

# 4. stale-url -- the submodule is initialised here, and then the committed
#    URL changes. This clone goes on fetching the old one.
git_file submodule update --init --quiet vendor/parser >/dev/null 2>&1 || true
git config --file .gitmodules submodule.vendor/parser.url ../parser.git
git commit --quiet -am "move parser to the org account"

printf '%s\n' "$super"
