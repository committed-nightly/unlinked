"""The README's worked example, compared whole rather than grepped.

The dogfood job greps this output for the findings it names. A grep per
interesting line is the right shape for "this finding is reported" and the
wrong shape for the claim the step is named after -- that the block in the
README is what the tool prints. It cannot see a line that should not be
there, and against the summary it cannot see the half of the sentence it
did not quote: the summary is filled to 88 columns, so it breaks
mid-sentence and anything appended to it lands on the second physical
line, leaving the first byte-identical.

So the block is compared here, where a diff is readable, it runs on both
Python versions, and a wrapped paragraph can be treated as the paragraph
it is.

In two parts, because the example's `stale-url` detail quotes the
repository's own absolute path and the README quotes it built at
`/tmp/unlinked-example`:

* the findings, unwrapped -- substituting the path changes its length and
  so the wrap, and unwrapping is the one normalisation that does not mean
  reimplementing `textwrap.fill` in the test;
* the summary, byte for byte including its wrap, which it can be because
  the summary names no path.
"""

import pathlib
import re
import subprocess

import pytest

from unlinked.cli import main

from . import git_oracle as g

pytestmark = pytest.mark.git

ROOT = pathlib.Path(__file__).resolve().parents[1]
QUOTED_AT = "/tmp/unlinked-example"


@pytest.fixture(autouse=True)
def _needs_git():
    if not g.have_git():
        pytest.skip("git is not installed")


def readme_block(index=0):
    """The body of the index-th fenced block in README.md, without fences."""
    text = (ROOT / "README.md").read_text()
    blocks = re.findall(r"^```[^\n]*\n(.*?)^```$", text, re.MULTILINE | re.DOTALL)
    assert blocks, "no fenced block in README.md"
    return blocks[index]


def split_report(text):
    """A rendered report as (findings paragraph, summary paragraph).

    The summary is always the last blank-line-separated paragraph, and is
    the only one `render` writes with no indent.
    """
    paragraphs = text.strip("\n").split("\n\n")
    assert len(paragraphs) == 2, f"expected findings and a summary, got {len(paragraphs)}"
    return paragraphs[0], paragraphs[1]


def unwrap_findings(paragraph):
    """One logical line per finding: `where  kind` plus its wrapped detail.

    Continuation lines are the ones `render` indents; everything else opens
    a finding. Collapsing the runs of spaces this creates is what makes the
    result independent of where the text happened to break.
    """
    logical = []
    for line in paragraph.split("\n"):
        if line.startswith("    ") and logical:
            logical[-1] += " " + line.strip()
        else:
            logical.append(line)
    return [re.sub(r" +", " ", line) for line in logical]


def run(args, capsys):
    code = main(args)
    return code, capsys.readouterr().out


@pytest.fixture
def example(tmp_path):
    """The repository the README quotes, built by the script the README names."""
    dest = tmp_path / "built"
    subprocess.run(
        [str(ROOT / "examples" / "make-example-repo.sh"), str(dest)],
        check=True,
        capture_output=True,
        text=True,
    )
    return dest


def test_readme_quotes_the_findings_the_example_prints(example, capsys):
    expected = readme_block()
    assert expected.startswith("$ unlinked\n"), "README example no longer opens with a prompt"
    expected = expected[len("$ unlinked\n") :]

    code, out = run([str(example / "app")], capsys)
    assert code == 1
    actual = out.replace(str(example), QUOTED_AT)

    assert unwrap_findings(split_report(actual)[0]) == unwrap_findings(split_report(expected)[0])


def test_readme_quotes_the_summary_exactly_as_it_wraps(example, capsys):
    """Byte for byte, wrap included. This is the paragraph every grep in the
    dogfood job reads only part of, and the one that grows a sentence when
    `_local_note` has something to say."""
    _, expected = split_report(readme_block()[len("$ unlinked\n") :])

    _, out = run([str(example / "app")], capsys)
    _, actual = split_report(out)

    assert actual == expected
    assert actual == (
        "Found 3 declarations git never acts on and 1 URL this clone has frozen, across 4\n"
        "submodules. Read 3 gitlinks and 3 .gitmodules entries."
    )


def test_the_example_still_builds_every_shape_the_readme_tabulates(example, capsys):
    """A guard on the two tests above: if the example repository ever stopped
    being broken, a block comparison would happily pass a README quoting a
    clean run. These are the kinds from the README's own table."""
    _, out = run([str(example / "app"), "-q"], capsys)
    for kind in ("no-entry", "no-gitlink", "update-none", "stale-url"):
        assert kind in out, f"the example no longer produces a {kind}"


def test_terse_summary_is_one_whole_line(example, capsys):
    """The sentence the dogfood job asserts, as one line, so that a
    whole-line assertion on it can actually fail."""
    code, out = run([str(example / "app"), "--committed-only", "-q"], capsys)
    assert code == 1
    assert out.splitlines()[-1] == (
        "Found 3 declarations git never acts on, across 3 submodules. "
        "Read 3 gitlinks and 3 .gitmodules entries."
    )


def test_committed_only_drops_the_local_finding_and_nothing_else(example, capsys):
    """The claim the dogfood step is named for, made as a comparison of both
    runs rather than as a grep for the one line that should differ."""
    _, full = run([str(example / "app"), "-q"], capsys)
    _, committed = run([str(example / "app"), "--committed-only", "-q"], capsys)

    kept = committed.splitlines()
    dropped = [line.split()[1] for line in full.splitlines() if line not in kept and "  " in line]
    assert dropped == ["stale-url"], f"--committed-only changed more than the local finding: {dropped}"

    # The denominator is a fact about what was read, not about which checks
    # ran, so it is identical in both modes. The grep this replaces stopped
    # at 'submodules.' and never reached it.
    read = "Read 3 gitlinks and 3 .gitmodules entries."
    assert full.splitlines()[-1].endswith(read)
    assert kept[-1].endswith(read)
