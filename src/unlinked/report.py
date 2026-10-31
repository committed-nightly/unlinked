"""Printing findings.

Place and kind on one line, the reason wrapped underneath. Every finding
here needs a sentence: "git ignores this" is not useful without the part
that says what git does instead, and that is usually the only place the
reader learns there was no error message to miss.

The summary counts declarations, not findings. One block can be wrong in
two ways at once -- no URL and `update = none` -- and counting findings
would make that look like two broken submodules.
"""

import json
import textwrap


def _plural(count, word, suffix="s"):
    return f"{count} {word}{'' if count == 1 else suffix}"


def _wrap(text, indent="    "):
    # Not on hyphens: these lines quote URLs and paths, and breaking
    # `--recurse-submodules` across two lines makes it uncopyable.
    return textwrap.fill(text, width=88, initial_indent=indent,
                         subsequent_indent=indent, break_on_hyphens=False,
                         break_long_words=False)


def render(audit, terse=False):
    lines = []
    for finding in audit.findings + audit.notes:
        if terse:
            lines.append(f"{finding.where}  {finding.kind:<16}  {finding.detail}")
        else:
            lines.append(f"{finding.where}  {finding.kind}")
            lines.append(_wrap(finding.detail))
    if lines:
        lines.append("")
    lines.append(summary(audit))
    return "\n".join(lines)


def summary(audit):
    facts = audit.facts
    declared = len(facts.entries)
    links = len(facts.gitlinks)

    if audit.declares_nothing:
        # Not a clean bill of health, because there was nothing to check.
        # A tool that says "all good" about a repository with no submodules
        # teaches you to believe it about one that has them (logbook#59).
        return (f"No submodules here: no gitlinks in {facts.rev} and no "
                f"entries in .gitmodules. Nothing to check.")

    broken = {f.path or f.name for f in audit.findings}
    seen = (f"{_plural(links, 'gitlink')} and {declared} .gitmodules "
            f"{'entry' if declared == 1 else 'entries'}")

    if not audit.findings:
        tail = ""
        if audit.notes:
            tail = (f" {_plural(len(audit.notes), 'note')} below: nothing git "
                    f"refuses to act on.")
        return (f"Every submodule declaration lines up. Read {seen} in "
                f"{facts.root}.{tail}")

    committed = sum(1 for f in audit.findings if f.scope == "committed")
    local = sum(1 for f in audit.findings if f.scope == "local")
    parts = []
    if committed:
        parts.append(f"{_plural(committed, 'declaration')} git never acts on")
    if local:
        parts.append(f"{_plural(local, 'URL')} this clone has frozen")
    return (f"Found {' and '.join(parts)}, across "
            f"{_plural(len(broken), 'submodule')}. Read {seen}.")


def render_json(audit):
    from .analyse import counts

    return json.dumps(
        {
            "root": audit.facts.root,
            "rev": audit.facts.rev,
            "gitmodules_source": audit.facts.entries_source,
            "declares_nothing": audit.declares_nothing,
            "counts": counts(audit),
            "findings": [f.as_dict() for f in audit.findings],
            "notes": [f.as_dict() for f in audit.notes],
        },
        indent=2,
        sort_keys=True,
    )
