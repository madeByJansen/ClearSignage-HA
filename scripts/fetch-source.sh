#!/usr/bin/env bash
# Fetch the ClearSignage source into the build context (Epic 119 Pass 4).
#
# This repository holds packaging and nothing else. ClearSignage's source is fetched at
# build time rather than vendored, for the reason DP34 already gives about role
# applications: another product's *source* does not enter a repo that is not its own —
# its built artefact does. Keeping that line here means this repo can never quietly fork
# the runtime it is supposed to package.
#
# Only four paths are copied, and the omissions are the point: `hosted/` is the
# supervisor, `device/` is one screen, `shared/` is the single-sourced operator UI, and
# `clearvenue/` is the venue role this add-on runs (DP92) — the till, enrolment, and the
# replication lane that feeds a screen its prices. The appliance's image builder, its
# systemd units, its Android port and the cloud Worker are all absent, because a hosted
# instance is none of those things.
#
# `clearvenue/` is the newest of the four and the reason the add-on execs `-m clearvenue`
# rather than `-m hosted`: a venue is a supervisor plus its own surfaces, and which
# platform hosts it is a value inside that package rather than a second implementation.
set -euo pipefail

# prod, not main: a published add-on image is a release and reaches customers'
# Home Assistant installs, so the default has to be code that went through the
# release gate. Overridden per build by the pipeline's branch choice, or by an
# exact tag/commit when reproducing a published image.
REF="${CLEARSIGNAGE_REF:-prod}"
REPO="${CLEARSIGNAGE_REPO:-https://github.com/madeByJansen/clearsignage.git}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
DEST="${HERE}/clearsignage/src"
WORK="$(mktemp -d)"
trap 'rm -rf "${WORK}"' EXIT

echo "Fetching ${REPO} @ ${REF}"
git clone --quiet --depth 1 --branch "${REF}" "${REPO}" "${WORK}/clearsignage" 2>/dev/null \
    || {
        # A commit SHA cannot be cloned with --branch; fall back to fetching it directly.
        git init --quiet "${WORK}/clearsignage"
        git -C "${WORK}/clearsignage" remote add origin "${REPO}"
        git -C "${WORK}/clearsignage" fetch --quiet --depth 1 origin "${REF}"
        git -C "${WORK}/clearsignage" checkout --quiet FETCH_HEAD
    }

rm -rf "${DEST}"
mkdir -p "${DEST}"
for path in hosted device shared clearvenue; do
    cp -a "${WORK}/clearsignage/${path}" "${DEST}/${path}"
done

# Tests are not shipped into an image an operator runs. They are run in ClearSignage's
# own pipeline, against the same source this pinned.
find "${DEST}" -type d -name tests -prune -exec rm -rf {} + 2>/dev/null || true

RESOLVED="$(git -C "${WORK}/clearsignage" rev-parse HEAD)"
printf '%s\n' "${RESOLVED}" > "${DEST}/CLEARSIGNAGE_REF"
echo "Fetched ${RESOLVED} into ${DEST}"

# Fail loudly rather than building an image that cannot start. Each of these is something
# the Dockerfile or the runtime reaches for by name, so a rename upstream is caught here
# rather than at 3am on somebody's Home Assistant.
for required in \
    "${DEST}/device/requirements.txt" \
    "${DEST}/device/constraints.txt" \
    "${DEST}/device/app/main.py" \
    "${DEST}/shared/pyproject.toml" \
    "${DEST}/hosted/__main__.py" \
    "${DEST}/clearvenue/__main__.py" \
    "${DEST}/clearvenue/hosts/__init__.py"
do
    [ -f "${required}" ] || { echo "missing from source: ${required}" >&2; exit 1; }
done
echo "Source layout verified."
