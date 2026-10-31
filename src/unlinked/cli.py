"""unlinked: say which of your submodule declarations git never acts on."""

import argparse
import sys

from .analyse import audit as run_audit
from .facts import gather
from .gitcmd import GitError
from .report import render, render_json

USAGE = """\
  unlinked                    this repository
  unlinked path/to/repo       another one
  unlinked --rev v2.0.0       the declarations as they were at a tag
"""


def build_parser():
    parser = argparse.ArgumentParser(
        prog="unlinked",
        description="Say which of your submodule declarations git never acts on.",
        epilog=USAGE,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "repo",
        nargs="?",
        default=".",
        metavar="REPO",
        help="a git repository; default is the current directory",
    )
    parser.add_argument(
        "--rev",
        default="HEAD",
        metavar="REV",
        help="which commit's gitlinks to read (default HEAD)",
    )
    parser.add_argument(
        "--committed-only",
        action="store_true",
        help="skip the checks about this particular clone, leaving only what is wrong for everyone",
    )
    parser.add_argument("-q", "--quiet", action="store_true", help="one line per finding")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    try:
        facts = gather(args.repo, rev=args.rev)
    except GitError as exc:
        # Never a finding. A question we could not ask is not an answer, and
        # printing a clean result here would be a lie about a repository we
        # failed to read.
        print(f"unlinked: {args.repo}: {exc}", file=sys.stderr)
        return 2

    # Asked about an older rev, the local checks have nothing to say: this
    # clone's .git/config was frozen against whatever .gitmodules said at
    # init time, and comparing it with a historical declaration would
    # report a difference that was never a mistake.
    local = not args.committed_only and args.rev == "HEAD"
    audit = run_audit(facts, local_checks=local)

    if args.json:
        print(render_json(audit))
    else:
        print(render(audit, terse=args.quiet))
    return 1 if audit.findings else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
