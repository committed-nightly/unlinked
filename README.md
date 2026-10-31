# unlinked

Say which of your submodule declarations git never acts on.

A submodule needs three things to agree: a gitlink in the tree, a block in
`.gitmodules`, and a URL in `.git/config`. When they disagree, the usual
result is an empty directory and an exit code of 0 — `git clone
--recurse-submodules` does not consider a submodule it was never told about
to be a problem, and `git status` has nothing to say about it either. This
reads all three and tells you which declarations do nothing.

```
$ unlinked
vendor/widgets  no-entry
    a gitlink here is pinned at 51f45708bb81, and nothing in .gitmodules maps it to a
    URL -- `git clone --recurse-submodules` leaves this directory empty and exits 0, and
    `git submodule update --init` exits 128 without populating any submodule in the
    repository
.gitmodules:vendor/old-parser  no-gitlink
    declares path 'vendor/old-parser', which is not a gitlink in HEAD -- `git submodule
    init` never registers it, `git submodule update` never clones it, and the whole
    block is inert
.gitmodules:vendor/logging  update-none
    `update = none` means `git submodule update` prints `Skipping submodule
    'vendor/logging'` and exits 0, leaving the directory empty -- a checkout of this
    repository never contains it unless somebody passes --checkout
.gitmodules:vendor/parser  stale-url
    this clone fetches 'vendor/parser' from '/tmp/unlinked-example/remotes/parser', but
    .gitmodules now says 'https://github.com/example/parser.git' (declared as
    '../parser.git'). git froze the URL into .git/config when the submodule was
    initialised and never revisits it, so the committed change has no effect here, or in
    anyone else's existing clone, until `git submodule sync` is run

Found 3 declarations git never acts on and 1 URL this clone has frozen, across 4
submodules. Read 3 gitlinks and 3 .gitmodules entries.
```

That repository is built by a script, so the output above is reproducible
rather than pasted:

```sh
examples/make-example-repo.sh /tmp/unlinked-example
unlinked /tmp/unlinked-example/app
```

## Install

```sh
pip install -e .
```

Python 3.10+, no dependencies. It shells out to `git`, which it needs on
PATH; it never contacts a network, and never writes to the repository you
point it at.

## Use

```sh
unlinked                     # this repository
unlinked path/to/repo        # another one
unlinked --rev v2.0.0        # the declarations as they were at a tag
unlinked --committed-only    # skip what is only true of this clone
unlinked -q                  # one line per finding
unlinked --json
```

Exit code is 0 when there is nothing to report, 1 when there is, and 2 when
unlinked could not get an answer — not a repository, no such rev, a
`.gitmodules` git refuses to parse. On exit 2 nothing goes to stdout, so a
run that failed to read a repository can never be mistaken for a clean one.

A repository with no submodules at all says so (`No submodules here`) rather
than reporting that everything is fine, because those are different answers
and only one of them means anything was checked.

## What it finds

The first four are committed, so they are true for everyone who clones the
repository. The last is true of the clone you are standing in.

| kind | what it means |
| --- | --- |
| `no-entry` | a gitlink in the tree that `.gitmodules` does not map to a URL |
| `no-gitlink` | a `.gitmodules` block whose path is not a gitlink — the whole block is inert |
| `no-url` | a declared gitlink with no `url`, so there is nowhere to clone it from |
| `update-none` | `update = none`, so no ordinary checkout ever contains it |
| `stale-url` | `.gitmodules` was repointed and this clone still fetches the old URL |

And one note, which is not a finding: `not-initialised`, for a submodule
left behind while its neighbours are initialised. `git submodule update
--init` stops at the first submodule it cannot do, so a gap in the middle is
often where it stopped. A clone where *nothing* is initialised gets one
sentence in the summary instead — that is what a fresh clone looks like, and
saying it twenty times is how output gets ignored.

## Why git does not just tell you

Because for most of these it exits 0. Measured against git 2.56, and
reproducible with `probe/ask-git.sh`:

| | `clone --recurse-submodules` | `submodule update --init` |
| --- | --- | --- |
| `no-entry` | **exit 0**, empty directory | exit 128 |
| `no-gitlink` | **exit 0**, block ignored entirely | **exit 0**, never mentioned |
| `no-url` | exit 128 | exit 128 |
| `update-none` | **exit 0**, empty directory | **exit 0**, "Skipping submodule" |
| `stale-url` | **exit 0**, fetches the old URL | **exit 0**, fetches the old URL |

`no-url` is the exception: git is loud about it both ways. It is still worth
reporting, because the declaration is just as dead as the others and you
would rather read it here than in a failed clone.

Two of those deserve spelling out.

**One orphan gitlink strands the others.** `git submodule update --init`
exits 128 on a `no-entry`, and because it stops there, the submodules it had
already registered are left unpopulated too. The visible symptom is a
*different* submodule being empty, and the error message names a path you
were not asking about.

**`git status` stays clean.** An empty submodule directory is not a
modification, so nothing prompts you. The repository looks fine right up to
the point where a build fails on a missing header.

## Relative URLs, and why this does not cry wolf

`git submodule add ../sibling.git` writes the relative URL into
`.gitmodules` and the resolved absolute one into `.git/config`. Comparing
those two strings directly would report every submodule ever added that way
as a mismatch, so `stale-url` has to resolve the relative form first — and
git's rules for that are their own small surprise:

```
remote.origin.url = https://github.com/acme/super.git

../sub.git           -> https://github.com/acme/sub.git
../../other/sub.git  -> https://github.com/other/sub.git
./nested/sub.git     -> https://github.com/acme/super.git/nested/sub.git
```

`..` drops a path segment; `.` drops nothing, so `./x` lands *underneath*
`super.git`. With no remote at all, git resolves against the superproject's
own directory on disk.

unlinked reimplements none of that. It builds a throwaway repository, points
it at the same URL, and runs the real `git submodule sync` — the code path
that does the resolving — so the answer comes from the git that is
installed, which is the git that will do the fetching. Ten parametrised
tests assert that unlinked's answer equals git's for the shapes above; if
the two ever disagree, the suite fails rather than the user finding out.

A difference of only a trailing `/` or a trailing `.git` is not reported.

## Checked against repositories nobody here wrote

Every tool is clean against the inputs its own author invented, which is why
this one is also run over real ones (`logbook#48`):

- **13 repositories at `HEAD`** — git, grpc, rust, esp-idf, FreeCAD, qmk,
  cocos2d-x, zephyr, protobuf, terminal, mbed-os, VeraCrypt and
  bitcoin-core/gui — covering 74 real submodule declarations. No findings,
  no false positives.
- **3,100 commits of history** — 1,500 of FreeCAD, 1,200 of grpc, 400 of
  cocos2d-x, each audited at its own revision. No findings.

Finding nothing in healthy repositories is the result being claimed there,
not that these checks fire often. The sweep earned its keep anyway: `--rev`
originally read the *working tree's* `.gitmodules` against a historical
rev's gitlinks, and called four healthy FreeCAD submodules broken because
today's file does not describe a commit from 2024. Three commits reported it
before the bug was fixed; none do now.

## Deliberately not done

- **Nothing is fixed.** `git submodule sync`, `git submodule update --init`
  and an editor are the fixes, and which one you want depends on whether the
  declaration or the gitlink is the mistake. unlinked names the command
  where it knows it.
- **`submodule.<name>.branch` is not checked.** It means something only
  under `git submodule update --remote`, and a repository that never runs
  that is not wrong to carry one. A claim about it needs a sharper
  measurement than this shift had.
- **`ignore` and `shallow` are not checked.** They change what git shows
  you rather than whether it acts, which is a different question.
- **A `submodule.*` section in `.git/config` for a submodule that no longer
  exists is not reported.** Dead, but harmless, and in a file nobody shares.

## Licence

MIT.
