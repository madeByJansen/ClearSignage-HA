#!/bin/bash
# Record the version that was just published, on the branch as it stands now.
#
# Home Assistant reads the version from `clearsignage/config.yaml` **in this repository**:
# the Supervisor tracks an installed app by that literal and pulls image:<version>. So a
# version that is published and not committed reaches nobody — the Supervisor goes on
# offering the version the file still names. Recording is part of publishing, which is why
# this exits non-zero when it cannot, unlike ClearSignage's QA report courier that this
# script is otherwise modelled on: there, "the report could not be committed" is not a QA
# result; here, "the release did not reach anyone" is the release.
#
# The one rule that matters: the version is committed onto whatever the branch tip is
# **now**, never onto the commit the build checked out. Two architectures take a while to
# build, so main has often moved by the time there is an image, and a push parented on the
# old tip is rejected.
#
# The commit is built with plumbing, so nothing here touches the working tree or the
# workspace index: it is the fetched tip's own tree with the manifest blob replaced. That
# is what makes the retry safe — a rejected push leaves nothing behind to undo, and
# re-reading the moved branch is the whole of the retry. It also matters that the
# *pipeline's* checkout is left alone: the stages after this one run the scripts this
# build checked out, not whatever main has moved on to.
#
# The manifest that gets stamped is the branch's, not the workspace's. The workspace copy
# was stamped before the build so the image could carry the version, and committing that
# file would carry any other difference between the build's commit and the tip along with
# it.
#
# Environment:
#   RECORD_VERSION   the version that was published (required)
#   RECORD_REMOTE    remote to fetch and push (default: origin; credentials come from
#                    GIT_ASKPASS, never from the URL)
#   RECORD_BRANCH    branch to record on      (default: main)
#   RECORD_MANIFEST  path in the repo         (default: clearsignage/config.yaml)
#   RECORD_TAG       tag to create            (default: v<version>; empty skips tagging)
#   RECORD_ATTEMPTS  how many times to re-read a moved branch (default: 3)
#   RECORD_STAMPER   the stamper to use       (default: next-image-version.py beside this)
#   RECORD_PYTHON    interpreter for it       (default: python3)
#   WORKSPACE        where the scratch index goes, if set

set -uo pipefail

VERSION="${RECORD_VERSION:-}"
REMOTE="${RECORD_REMOTE:-origin}"
BRANCH="${RECORD_BRANCH:-main}"
MANIFEST="${RECORD_MANIFEST:-clearsignage/config.yaml}"
ATTEMPTS="${RECORD_ATTEMPTS:-3}"
HERE="$(cd "$(dirname "$0")" && pwd)"
STAMPER="${RECORD_STAMPER:-${HERE}/next-image-version.py}"
# The interpreter is a knob so the tests can drive this with the one running them,
# rather than depending on what the agent's system python3 happens to have installed.
PYTHON="${RECORD_PYTHON:-python3}"
TAG="${RECORD_TAG-v${VERSION}}"

STAMPED=""
INDEX=""
cleanup() {
    [ -n "$STAMPED" ] && rm -f "$STAMPED"
    [ -n "$INDEX" ] && rm -f "$INDEX"
    return 0
}
trap cleanup EXIT

if [ -z "$VERSION" ]; then
    echo "RECORD_VERSION is required: this records a version that was published." >&2
    exit 2
fi

# Said in full every time it fails, because the state it describes is invisible: the
# registry has the image, the repository does not name it, and no install is offered it.
give_up() {
    echo "$1" >&2
    echo "THE IMAGE IS PUBLISHED but its version was not recorded." >&2
    echo "ghcr.io/madebyjansen/clearsignage-ha:${VERSION} exists; ${BRANCH} still names an" >&2
    echo "older version, so Home Assistant will not offer it. Set" >&2
    echo "version: \"${VERSION}\" in ${MANIFEST} on ${BRANCH} to fix this — no rebuild is" >&2
    echo "needed, and rebuilding would only choose a different version. A branch protection" >&2
    echo "rule on ${BRANCH} will fail this every time until the Jenkins credential can push" >&2
    echo "to it." >&2
    exit 1
}

# The tag records what shipped; it is not what makes it shipped. Pushed after the commit
# lands, never forced onto a tag the remote already has, and re-checked on a run that had
# nothing to commit — a previous run may have pushed the commit and died before the tag.
push_tag() {
    target="$1"
    [ -n "$TAG" ] || return 0
    if git ls-remote --exit-code --tags "$REMOTE" "refs/tags/${TAG}" >/dev/null 2>&1; then
        echo "Tag ${TAG} is already on the remote; leaving it alone."
        return 0
    fi
    # -f only overwrites a *local* tag left by an earlier attempt; the push below is not
    # forced, so the remote's own tag can never be replaced by this.
    git -c user.name="Jenkins" -c user.email="ci@workplain.com" \
        tag -af "$TAG" "$target" -m "ClearSignage HA ${VERSION}" >/dev/null 2>&1 ||
        { echo "Could not create the tag ${TAG} locally; the version is recorded." >&2; return 0; }
    if git push -q "$REMOTE" "refs/tags/${TAG}" 2>/dev/null; then
        echo "Tagged ${TAG}."
    else
        echo "Could not push the tag ${TAG}; the version is recorded, which is what installs read." >&2
    fi
    return 0
}

# One scratch file for every attempt: each write truncates it, so a retry cannot leave
# temporary files behind on the agent.
STAMPED="$(mktemp)"

attempt=1
while [ "$attempt" -le "$ATTEMPTS" ]; do
    # stderr dropped: a failure prints the URL back, and a URL can carry a token.
    if ! git fetch -q "$REMOTE" "refs/heads/${BRANCH}" 2>/dev/null; then
        give_up "Could not read ${BRANCH} from ${REMOTE} (branch gone, or no access)."
    fi
    base="$(git rev-parse FETCH_HEAD)"

    # The branch's manifest, stamped through the same function the build used, into a
    # file rather than a variable — command substitution eats the trailing newline, and
    # the bytes committed have to be the bytes a stamp produces.
    if ! git cat-file blob "${base}:${MANIFEST}" 2>/dev/null |
        "$PYTHON" "$STAMPER" --stdin --set "$VERSION" > "$STAMPED"; then
        give_up "Could not stamp ${VERSION} into ${MANIFEST} as it stands on ${BRANCH}."
    fi

    blob="$(git hash-object -w "$STAMPED")"
    [ -n "$blob" ] || give_up "Could not store the stamped manifest as a git object."

    # A scratch index, so the workspace's own staging area is never disturbed.
    INDEX="${WORKSPACE:-.}/.record-version-index"
    rm -f "$INDEX"
    tree=""
    if GIT_INDEX_FILE="$INDEX" git read-tree "$base" &&
        GIT_INDEX_FILE="$INDEX" git update-index --add --cacheinfo "100644,${blob},${MANIFEST}"; then
        tree="$(GIT_INDEX_FILE="$INDEX" git write-tree)"
    fi
    rm -f "$INDEX"
    [ -n "$tree" ] || give_up "Could not build the commit that records ${VERSION}."

    # Judged against the branch rather than the workspace: "it is already recorded" is a
    # fact about what a Supervisor reading this repository would find.
    if [ "$tree" = "$(git rev-parse "${base}^{tree}")" ]; then
        echo "${BRANCH} already records ${VERSION}."
        push_tag "$base"
        exit 0
    fi

    # [skip ci] because this lane commits its own output: a push trigger on this branch
    # would start a build that publishes a version that commits that it published, and so
    # on. Nothing triggers on push today, and this is what keeps that from becoming a
    # loop the day something does.
    commit="$(git -c user.name="Jenkins" -c user.email="ci@workplain.com" \
        commit-tree "$tree" -p "$base" -m "ClearSignage HA ${VERSION} [skip ci]")"
    [ -n "$commit" ] || give_up "Could not build the commit that records ${VERSION}."

    if git push -q "$REMOTE" "${commit}:refs/heads/${BRANCH}" 2>/dev/null; then
        echo "Recorded ${VERSION} on ${BRANCH}."
        push_tag "$commit"
        exit 0
    fi

    echo "Push to ${BRANCH} was rejected on attempt ${attempt} — it moved while this build ran; re-reading it."
    attempt=$((attempt + 1))
done

give_up "Could not push to ${BRANCH} after ${ATTEMPTS} attempts."
