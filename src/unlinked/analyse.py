"""Deciding which declarations git never acts on.

Two kinds of finding, kept apart because the fix is in a different place:

  committed   wrong in the repository, so wrong for everyone who clones it
  local       wrong in this clone only, and a command fixes it here

Every kind below was measured against git 2.56 before it was written; the
probe/ scripts reproduce the measurements.
"""

from .resolve import resolve_urls, same_place

# Committed: these travel with the repository.
NO_ENTRY = "no-entry"
NO_GITLINK = "no-gitlink"
NO_URL = "no-url"
UPDATE_NONE = "update-none"
# Local: these are true of the clone in front of you.
STALE_URL = "stale-url"

COMMITTED_KINDS = (NO_ENTRY, NO_GITLINK, NO_URL, UPDATE_NONE)
LOCAL_KINDS = (STALE_URL,)

NOT_INITIALISED = "not-initialised"
NOTE_KINDS = (NOT_INITIALISED,)


class Finding:
    def __init__(self, kind, where, detail, name=None, path=None, extra=None):
        self.kind = kind
        self.where = where
        self.detail = detail
        self.name = name
        self.path = path
        self.extra = extra or {}

    @property
    def scope(self):
        if self.kind in LOCAL_KINDS:
            return "local"
        if self.kind in NOTE_KINDS:
            return "note"
        return "committed"

    def as_dict(self):
        out = {
            "kind": self.kind,
            "scope": self.scope,
            "where": self.where,
            "detail": self.detail,
        }
        if self.name is not None:
            out["name"] = self.name
        if self.path is not None:
            out["path"] = self.path
        out.update(self.extra)
        return out


class Audit:
    def __init__(self, facts, findings, notes, uninitialised=False):
        self.facts = facts
        self.findings = findings
        self.notes = notes
        # True when the repository has submodules and this clone has not
        # initialised a single one. Not a finding -- but the summary should
        # not imply the local checks found anything either way.
        self.uninitialised = uninitialised

    @property
    def dead(self):
        return self.findings

    @property
    def declares_nothing(self):
        return self.facts.declares_nothing


def audit(facts, local_checks=True):
    findings = []
    notes = []

    by_path = {}
    for entry in facts.entries:
        if entry.path is not None:
            # First declaration of a path wins the mapping; git looks a
            # path up by name, so a second entry for the same path is not
            # an override but a separate submodule that shares a directory.
            by_path.setdefault(entry.path, entry)

    findings += _orphan_gitlinks(facts, by_path)
    findings += _entry_problems(facts, by_path)
    uninitialised = False
    if local_checks and not facts.bare:
        found, noted, uninitialised = _local_problems(facts)
        findings += found
        notes += noted

    order = {kind: i for i, kind in enumerate(COMMITTED_KINDS + LOCAL_KINDS)}
    findings.sort(key=lambda f: (order.get(f.kind, 99), f.where))
    return Audit(facts, findings, notes, uninitialised=uninitialised)


def _orphan_gitlinks(facts, by_path):
    """A gitlink the declaration does not cover.

    `git clone --recurse-submodules` exits 0 on this and leaves an empty
    directory; `git submodule update --init` exits 128 and, because it
    stops, leaves the repository's *other* submodules unpopulated too.
    """
    out = []
    for path in sorted(facts.gitlinks):
        if path in by_path:
            continue
        out.append(
            Finding(
                NO_ENTRY,
                path,
                f"a gitlink here is pinned at {facts.gitlinks[path][:12]}, and "
                f"nothing in .gitmodules maps it to a URL -- `git clone "
                f"--recurse-submodules` leaves this directory empty and exits 0, "
                f"and `git submodule update --init` exits 128 without populating "
                f"any submodule in the repository",
                path=path,
                extra={"commit": facts.gitlinks[path]},
            )
        )
    return out


def _entry_problems(facts, by_path):
    out = []
    for entry in facts.entries:
        where = f".gitmodules:{entry.name}"

        if entry.path is None:
            out.append(
                Finding(
                    NO_GITLINK,
                    where,
                    "this block sets no `path`, so git has nothing to match it "
                    "against and never reads another word of it",
                    name=entry.name,
                )
            )
            continue

        if entry.path not in facts.gitlinks:
            out.append(
                Finding(
                    NO_GITLINK,
                    where,
                    f"declares path '{entry.path}', which is not a gitlink in "
                    f"{facts.rev} -- `git submodule init` never registers it, "
                    f"`git submodule update` never clones it, and the whole "
                    f"block is inert",
                    name=entry.name,
                    path=entry.path,
                )
            )
            continue

        if entry.url is None:
            out.append(
                Finding(
                    NO_URL,
                    where,
                    f"the gitlink at '{entry.path}' is declared but has no "
                    f"`url`, so git has nowhere to clone it from: `No url found "
                    f"for submodule path '{entry.path}' in .gitmodules`",
                    name=entry.name,
                    path=entry.path,
                )
            )

        if (entry.update or "").strip() == "none":
            out.append(
                Finding(
                    UPDATE_NONE,
                    where,
                    f"`update = none` means `git submodule update` prints "
                    f"`Skipping submodule '{entry.path}'` and exits 0, leaving "
                    f"the directory empty -- a checkout of this repository never "
                    f"contains it unless somebody passes --checkout",
                    name=entry.name,
                    path=entry.path,
                )
            )
    return out


def _local_problems(facts):
    """What this clone will do, as opposed to what the repository says."""
    found = []
    notes = []
    resolved = resolve_urls(facts.entries, facts.remote_url, facts.root)

    live = [e for e in facts.entries if e.path in facts.gitlinks and e.url is not None]
    initialised = [e for e in live if "url" in facts.local.get(e.name, {})]
    # A clone where nothing is initialised is just a clone nobody has run
    # `git submodule update --init` in yet, and saying so twenty times is
    # how output gets ignored. A clone where some are and some are not is
    # the interesting shape, so that is the only one that gets notes.
    note_uninitialised = bool(initialised) and len(initialised) < len(live)

    for entry in facts.entries:
        if entry.path is None or entry.path not in facts.gitlinks:
            continue  # already reported; nothing local follows from it
        configured = facts.local.get(entry.name, {}).get("url")

        if configured is None:
            if entry.url is not None and note_uninitialised:
                notes.append(
                    Finding(
                        NOT_INITIALISED,
                        f".gitmodules:{entry.name}",
                        f"not initialised in this clone, while the repository's "
                        f"other submodules are -- no submodule.{entry.name}.url "
                        f"in .git/config. `git submodule update --init` stops at "
                        f"the first one it cannot do, so a gap in the middle is "
                        f"often where it stopped",
                        name=entry.name,
                        path=entry.path,
                    )
                )
            continue

        want = resolved.get(entry.name)
        if want is None or same_place(want, configured):
            continue

        declared = entry.url
        via = "" if declared == want else f" (declared as '{declared}')"
        found.append(
            Finding(
                STALE_URL,
                f".gitmodules:{entry.name}",
                f"this clone fetches '{entry.path}' from '{configured}', but "
                f".gitmodules now says '{want}'{via}. git froze the URL into "
                f".git/config when the submodule was initialised and never "
                f"revisits it, so the committed change has no effect here, or "
                f"in anyone else's existing clone, until `git submodule sync` "
                f"is run",
                name=entry.name,
                path=entry.path,
                extra={"configured": configured, "declared": want},
            )
        )
    return found, notes, bool(live) and not initialised


def counts(audit_result):
    """The numbers the summary is made of, so a test can assert on them."""
    kinds = {}
    for finding in audit_result.findings:
        kinds[finding.kind] = kinds.get(finding.kind, 0) + 1
    return {
        "gitlinks": len(audit_result.facts.gitlinks),
        "entries": len(audit_result.facts.entries),
        "committed": sum(1 for f in audit_result.findings if f.scope == "committed"),
        "local": sum(1 for f in audit_result.findings if f.scope == "local"),
        "notes": len(audit_result.notes),
        "kinds": kinds,
    }
