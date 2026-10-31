#!/bin/sh
# Reproduce the measurements every finding in unlinked is based on.
#
# Nothing here uses unlinked. It builds the four broken shapes and runs the
# git commands whose behaviour the findings describe, printing the exit code
# each time, because the exit code is the whole point: three of these four
# are green.
#
# Usage: probe/ask-git.sh [workdir]
set -eu

work=${1:-$(mktemp -d)}
mkdir -p "$work"
work=$(cd "$work" && pwd)

export GIT_CONFIG_NOSYSTEM=1
export GIT_AUTHOR_NAME=probe GIT_AUTHOR_EMAIL=probe@invalid
export GIT_COMMITTER_NAME=probe GIT_COMMITTER_EMAIL=probe@invalid

# Local paths as submodule URLs need this since git 2.38. Everything here
# is under a directory we just made.
g() { git -c protocol.file.allow=always "$@"; }

say() { printf '\n=== %s\n' "$*"; }

# What is actually inside a submodule directory, ignoring its .git. Not
# `ls`, which shellcheck is right about and which would also hide the
# difference between "empty" and "does not exist".
contents() {
    [ -d "$1" ] || { printf '(no such directory)'; return; }
    find "$1" -mindepth 1 -maxdepth 1 ! -name .git -printf '%f ' 2>/dev/null
}

remote() {
    mkdir -p "$work/remotes/$1"
    ( cd "$work/remotes/$1" && git init --quiet -b main . \
        && echo "$1" > WHICH && git add -A && git commit --quiet -m init )
}

super() {
    rm -rf "${work:?}/$1"
    mkdir -p "$work/$1"
    ( cd "$work/$1" && git init --quiet -b main . \
        && echo top > README && git add -A && git commit --quiet -m init )
}

printf 'git %s\n' "$(git --version | awk '{print $3}')"
remote liba
remote libb

# ---------------------------------------------------------------------------
say 'no-entry: a gitlink with no .gitmodules block'
super app
cd "$work/app"
g submodule add --quiet "$work/remotes/liba" vendor/liba
g submodule add --quiet "$work/remotes/libb" vendor/libb
git commit --quiet -m "two submodules"
git config --file .gitmodules --remove-section submodule.vendor/libb
git commit --quiet -am "drop libb from .gitmodules, keep the gitlink"

printf -- '-- git clone --recurse-submodules\n'
rm -rf "${work:?}/c1"
g clone --quiet --recurse-submodules "$work/app" "$work/c1" || true
printf 'exit=%d\n' $?
printf 'vendor/liba: [%s]\n' "$(contents "$work/c1/vendor/liba")"
printf 'vendor/libb: [%s]\n' "$(contents "$work/c1/vendor/libb")"
printf -- '-- git status --porcelain in that clone: [%s]\n' \
    "$(git -C "$work/c1" status --porcelain)"

printf -- '-- git submodule update --init, in a plain clone\n'
rm -rf "${work:?}/c2"
g clone --quiet "$work/app" "$work/c2"
( cd "$work/c2" && g submodule update --init 2>&1 || printf 'exit=%d\n' $? )
printf 'vendor/liba is populated: %s\n' \
    "$([ -n "$(contents "$work/c2/vendor/liba")" ] && echo yes || echo no)"

# ---------------------------------------------------------------------------
say 'no-gitlink: a .gitmodules block with no gitlink'
super ghost
cd "$work/ghost"
g submodule add --quiet "$work/remotes/liba" vendor/liba
git commit --quiet -m "one submodule"
git config --file .gitmodules submodule.ghost.path vendor/ghost
git config --file .gitmodules submodule.ghost.url "$work/remotes/libb"
git commit --quiet -am "declare a submodule with no gitlink"
rm -rf "${work:?}/c3"
g clone --quiet "$work/ghost" "$work/c3"
printf -- '-- git submodule update --init\n'
( cd "$work/c3" && g submodule update --init 2>&1; printf 'exit=%d\n' $? )
printf 'ghost in .git/config: %s\n' \
    "$(git -C "$work/c3" config --get submodule.ghost.url || echo '(never registered)')"
printf 'vendor/ghost exists: %s\n' \
    "$([ -e "$work/c3/vendor/ghost" ] && echo yes || echo no)"

# ---------------------------------------------------------------------------
say 'update-none: skipped, and the directory stays empty'
super skip
cd "$work/skip"
g submodule add --quiet "$work/remotes/liba" vendor/liba
git commit --quiet -m "one submodule"
git config --file .gitmodules submodule.vendor/liba.update none
git commit --quiet -am "update = none"
rm -rf "${work:?}/c4"
g clone --quiet "$work/skip" "$work/c4"
( cd "$work/c4" && g submodule update --init 2>&1; printf 'exit=%d\n' $? )
printf 'vendor/liba: [%s]\n' "$(contents "$work/c4/vendor/liba")"

# ---------------------------------------------------------------------------
say 'stale-url: .git/config wins, for as long as it exists'
super repoint
cd "$work/repoint"
g submodule add --quiet "$work/remotes/liba" vendor/liba
git commit --quiet -m "one submodule"
rm -rf "${work:?}/c5"
g clone --quiet "$work/repoint" "$work/c5"
cd "$work/c5"
g submodule update --init --quiet
printf 'initialised against: %s\n' "$(git config --get submodule.vendor/liba.url)"
git config --file .gitmodules submodule.vendor/liba.url "$work/remotes/libb"
git commit --quiet -am "repoint at libb"
printf '.gitmodules now says: %s\n' \
    "$(git config --file .gitmodules --get submodule.vendor/liba.url)"
printf '.git/config still says: %s\n' "$(git config --get submodule.vendor/liba.url)"
printf 'the submodule really fetches from: %s\n' \
    "$(g submodule foreach --quiet 'git remote get-url origin')"
g submodule sync --quiet
printf 'after git submodule sync: %s\n' "$(git config --get submodule.vendor/liba.url)"

# ---------------------------------------------------------------------------
say 'relative URLs: what git resolves them to'
cd "$work/c5"
for rel in '../sub.git' '../../other/sub.git' './nested/sub.git'; do
    git config remote.origin.url 'https://github.com/acme/super.git'
    git config --file .gitmodules submodule.vendor/liba.url "$rel"
    g submodule sync --quiet
    printf '%-22s -> %s\n' "$rel" "$(git config --get submodule.vendor/liba.url)"
done

printf '\nworkdir: %s\n' "$work"
