"""The recorder that puts the published version on the branch — driven against real repos.

`clearvenue/config.yaml` is what Home Assistant reads: the Supervisor tracks an installed
app by the version in it and pulls `image:<version>`. So an image published without that
commit reaches nobody, and the commit has to land on the branch as it stands *now* — two
architectures take twenty minutes to build, and main has usually moved by the time there
is an image to name.

This logic was a Jenkinsfile heredoc that checked out main over the workspace and committed
from the working tree. The only assertion available against a Jenkinsfile is a grep, and a
grep cannot tell a push parented on the right commit from one parented on the wrong one —
so it is a script now, and these tests run it: two real git repositories, a real rejected
push, and a branch that genuinely moves between the image being published and the version
being recorded.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "record-published-version.sh"
STAMPER = REPO_ROOT / "scripts" / "next-image-version.py"
MANIFEST = "clearvenue/config.yaml"


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return done.stdout.strip()


def _commit(cwd: Path, name: str, body: str, message: str) -> None:
    path = cwd / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    _git(cwd, "add", name)
    _git(cwd, "-c", "user.name=Test", "-c", "user.email=test@example.com",
         "commit", "-q", "-m", message)


@pytest.fixture()
def origin_and_workspace(tmp_path):
    """A bare remote on main holding a real manifest, and a clone of it as Jenkins has."""
    origin = tmp_path / "origin.git"
    seed = tmp_path / "seed"
    workspace = tmp_path / "workspace"

    _git(tmp_path, "init", "-q", "--bare", "--initial-branch=main", str(origin))
    _git(tmp_path, "init", "-q", "--initial-branch=main", str(seed))
    # The repository manifest records the last published release.  Do not seed that
    # release into a test whose job is to record the same example version: once the
    # first real dated release was committed, that made every write-path case silently
    # take the idempotent "already records" path instead.  A pre-dated release models
    # the branch state before the publication under test and keeps this fixture valid
    # after every successful pipeline run updates the real manifest.
    manifest = (REPO_ROOT / MANIFEST).read_text(encoding="utf-8")
    manifest = re.sub(
        r"^version:.*$", 'version: "0.1.936"', manifest, count=1, flags=re.MULTILINE
    )
    _commit(seed, MANIFEST, manifest, "seed")
    _git(seed, "remote", "add", "origin", str(origin))
    _git(seed, "push", "-q", "origin", "main")

    _git(tmp_path, "clone", "-q", str(origin), str(workspace))
    return origin, seed, workspace


def _record(workspace: Path, origin: Path, version: str = "20260831.01", **env_extra):
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": str(workspace),
        "RECORD_VERSION": version,
        "RECORD_REMOTE": str(origin),
        "RECORD_STAMPER": str(STAMPER),
        # This interpreter, not the agent's: the stamper needs PyYAML and the suite
        # runs in a venv that has it.
        "RECORD_PYTHON": sys.executable,
        **env_extra,
    }
    done = subprocess.run(
        ["bash", str(SCRIPT)], cwd=workspace, capture_output=True, text=True, env=env
    )
    return done


def _recorded(origin: Path, workspace: Path, branch: str = "main") -> str:
    """Return the manifest a reader of the branch would find, as bytes-in-a-string."""
    _git(workspace, "fetch", "-q", str(origin), f"refs/heads/{branch}")
    return subprocess.run(
        ["git", "show", f"FETCH_HEAD:{MANIFEST}"],
        cwd=workspace, capture_output=True, text=True, check=True,
    ).stdout


def _tip(origin: Path, workspace: Path, branch: str = "main") -> str:
    _git(workspace, "fetch", "-q", str(origin), f"refs/heads/{branch}")
    return _git(workspace, "rev-parse", "FETCH_HEAD")


def test_the_version_lands_on_a_branch_that_moved_while_the_image_built(origin_and_workspace):
    """The failure this shape exists to avoid: the tip is not the commit that was built."""
    origin, seed, workspace = origin_and_workspace

    # Somebody merges a pull request while the two architectures are building.
    _commit(seed, "README.md", "merged mid-build\n", "a PR merged mid-build")
    _git(seed, "push", "-q", "origin", "main")

    done = _record(workspace, origin)

    assert done.returncode == 0, done.stderr
    assert "Recorded 20260831.01 on main." in done.stdout, done.stdout
    assert yaml.safe_load(_recorded(origin, workspace))["version"] == "20260831.01"
    # ...on top of their merge, not a fork from where the build started.
    assert _git(workspace, "show", "FETCH_HEAD:README.md") == "merged mid-build"


def test_only_the_version_line_changes_and_the_file_stays_byte_exact(origin_and_workspace):
    """A manifest that is mostly comments, rewritten by a machine every release.

    The trailing newline is in here on purpose: the stamped bytes travel through a pipe
    and a temporary file, and command substitution would have eaten it.
    """
    origin, seed, workspace = origin_and_workspace
    before = (REPO_ROOT / MANIFEST).read_text(encoding="utf-8")

    _record(workspace, origin)
    after = _recorded(origin, workspace)

    assert after.endswith("\n") and not after.endswith("\n\n")
    assert after.count("\n") == before.count("\n")
    for line in before.splitlines():
        if not line.startswith("version:"):
            assert line in after, line


def test_a_branch_that_moves_again_during_the_retry_is_re_read(origin_and_workspace, tmp_path):
    """The retry is a re-read, not a resend: each attempt is parented on the newer tip.

    Driven by a hook on the remote that rejects the first push it sees, which is the only
    way to produce the race deterministically.
    """
    origin, seed, workspace = origin_and_workspace
    hook = origin / "hooks" / "pre-receive"
    marker = tmp_path / "rejected-once"
    hook.write_text(
        "#!/bin/bash\n"
        f'if [ ! -f "{marker}" ]; then touch "{marker}"; echo "rejected once"; exit 1; fi\n'
        "exit 0\n",
        encoding="utf-8",
    )
    hook.chmod(0o755)

    done = _record(workspace, origin)

    assert done.returncode == 0, done.stderr
    assert "rejected on attempt 1" in done.stdout, done.stdout
    assert yaml.safe_load(_recorded(origin, workspace))["version"] == "20260831.01"


def test_a_version_already_on_the_branch_is_not_committed_again(origin_and_workspace):
    """Judged against the branch, because that is what an install reads."""
    origin, seed, workspace = origin_and_workspace
    _record(workspace, origin)
    before = _tip(origin, workspace)

    done = _record(workspace, origin)

    assert done.returncode == 0, done.stderr
    assert "already records 20260831.01" in done.stdout, done.stdout
    assert _tip(origin, workspace) == before


def test_recording_leaves_the_workspace_exactly_as_it_found_it(origin_and_workspace):
    """The stages after this one run the scripts *this build* checked out.

    The previous version checked main out over the workspace, which silently swapped the
    pruner and the manifest under the rest of the pipeline whenever main had moved. Built
    with plumbing there is nothing to swap and nothing to clean up: no commit to undo, no
    branch left behind, nothing staged.
    """
    origin, seed, workspace = origin_and_workspace
    head_before = _git(workspace, "rev-parse", "HEAD")
    branch_before = _git(workspace, "branch", "--show-current")
    manifest_before = (workspace / MANIFEST).read_text(encoding="utf-8")

    _record(workspace, origin)

    assert _git(workspace, "rev-parse", "HEAD") == head_before
    assert _git(workspace, "branch", "--show-current") == branch_before
    assert _git(workspace, "status", "--porcelain") == ""
    assert (workspace / MANIFEST).read_text(encoding="utf-8") == manifest_before
    assert not (workspace / ".record-version-index").exists()


def test_the_release_is_tagged_with_what_was_published(origin_and_workspace):
    origin, seed, workspace = origin_and_workspace

    done = _record(workspace, origin)

    assert "Tagged stable/v20260831.01." in done.stdout, done.stdout
    tags = _git(workspace, "ls-remote", "--tags", str(origin))
    assert "refs/tags/stable/v20260831.01" in tags

    # A rerun that has nothing to commit still checks the tag, because a previous run may
    # have pushed the commit and died before it.
    again = _record(workspace, origin)
    assert "already on the remote" in again.stdout, again.stdout


def test_a_recorder_that_cannot_push_fails_the_build_and_says_what_is_true(origin_and_workspace):
    """Unlike the QA report courier this is modelled on, silence here is not an option.

    The registry has the image and the repository does not name it, which is invisible
    from both ends: the build looks green and no install is offered the release.
    """
    origin, seed, workspace = origin_and_workspace
    hook = origin / "hooks" / "pre-receive"
    hook.write_text("#!/bin/bash\necho 'protected branch'\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    done = _record(workspace, origin, RECORD_ATTEMPTS="2")

    assert done.returncode == 1
    assert "THE IMAGE IS PUBLISHED but its version was not recorded." in done.stderr
    assert "20260831.01" in done.stderr
    assert "branch protection" in done.stderr
    assert _tip(origin, workspace) == _git(workspace, "rev-parse", "origin/main")


def test_a_branch_the_remote_does_not_have_is_a_failure_not_a_guess(origin_and_workspace):
    origin, seed, workspace = origin_and_workspace

    done = _record(workspace, origin, RECORD_BRANCH="no-such-branch")

    assert done.returncode == 1
    assert "Could not read no-such-branch" in done.stderr, done.stderr


def test_recording_nothing_is_refused_outright(origin_and_workspace):
    """An empty version would stamp the manifest with an empty string and commit it."""
    origin, seed, workspace = origin_and_workspace

    done = _record(workspace, origin, version="")

    assert done.returncode == 2
    assert "RECORD_VERSION is required" in done.stderr
    assert _tip(origin, workspace) == _git(workspace, "rev-parse", "origin/main")


def test_recording_each_channel_preserves_the_other_manifests_and_unique_tags(origin_and_workspace):
    origin, seed, workspace = origin_and_workspace
    manifests = {'stable': MANIFEST, 'beta': 'clearvenue_beta/config.yaml', 'dev': 'clearvenue_dev/config.yaml'}
    for channel in ('beta', 'dev'):
        content = (REPO_ROOT / manifests[channel]).read_text()
        content = re.sub(r'^version:.*$', 'version: "0.1.936"', content, flags=re.M)
        _commit(seed, manifests[channel], content, 'seed ' + channel)
    _git(seed, 'push', '-q', 'origin', 'main')
    before = {channel: _git(seed, 'show', 'HEAD:' + path) for channel, path in manifests.items()}
    for channel, path in manifests.items():
        result = _record(workspace, origin, CHANNEL=channel)
        assert result.returncode == 0, result.stderr
        _git(workspace, 'fetch', '-q', str(origin), 'main')
        for other, other_path in manifests.items():
            recorded = _git(workspace, 'show', 'FETCH_HEAD:' + other_path)
            if other == channel:
                assert yaml.safe_load(recorded)['version'] == '20260831.01'
                before[other] = recorded
            else:
                assert recorded == before[other]
        assert f'refs/tags/{channel}/v20260831.01' in _git(workspace, 'ls-remote', '--tags', str(origin))


def test_recorder_rejects_a_manifest_from_another_channel(origin_and_workspace):
    origin, seed, workspace = origin_and_workspace
    result = _record(workspace, origin, CHANNEL='dev', RECORD_MANIFEST=MANIFEST)
    assert result.returncode == 2
    assert 'does not match' in result.stderr
