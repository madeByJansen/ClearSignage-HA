# ClearVenue — Home Assistant apps

Home Assistant packaging for ClearVenue. Product code remains in the private
`madeByJansen/ClearSignage` repository. This repository has **one permanent branch,
`main`**, with three independent apps. Feature branches are used for review only.

| Channel | App | Slug / folder | Upstream branch | GHCR image |
| --- | --- | --- | --- | --- |
| stable | ClearVenue | `clearvenue` | `prod` | `ghcr.io/madebyjansen/clearvenue` |
| beta | ClearVenue Beta | `clearvenue_beta` | `beta` | `ghcr.io/madebyjansen/clearvenue-beta` |
| dev | ClearVenue Dev | `clearvenue_dev` | `main` | `ghcr.io/madebyjansen/clearvenue-dev` |

There are no existing installations to migrate. The old `clearsignage` app is removed.
Each slug has independent `/data` and upgrades only from its own image. Changing channels
means installing a different app; it does not transfer data. Because the apps use host
networking and the same runtime ports, **run only one channel on a Home Assistant host
at a time**. Use separate HA hosts for simultaneous testing.

## Building and publishing

Configure one Jenkins job to read `jenkinsfile-ha` from packaging **main**. It exposes:

- `CHANNEL`: `stable` (default), `beta`, or `dev`. The upstream branch, app folder and
  image are selected together by `scripts/channels.py`.
- `CLEARSIGNAGE_REF_OVERRIDE`: optional full 40-character upstream commit SHA for a
  reproducible source checkout or debug build. It never changes the destination channel.
- `PUSH`: true publishes; false builds both architectures and discards the output.

Normal channel builds require no version or pin edits. The pipeline chooses `YYYYMMDD.NN`
from that channel's GHCR tags, builds ARM64 and AMD64 images, then publishes the versioned
multi-architecture index and `latest` **within that channel's package**. First publication
handles a missing package only after successfully listing the owner's packages; access
failures abort rather than guessing a version.

After publishing, the recorder updates only the selected channel's `config.yaml` on the
latest packaging `main`, retries a concurrent branch update, and adds a channel-qualified
Git tag: `stable/vYYYYMMDD.NN`, `beta/vYYYYMMDD.NN`, or `dev/vYYYYMMDD.NN`. The version
counter is independent per package, so different channels can legitimately share a number.
Pruning keeps the current and previous release in that package and preserves untagged
manifests that might still be referenced. Feature-branch publishing is refused; validate
this branch with `PUSH=false` until its changes have been reviewed and merged separately.

To **publish an exact-commit override**, set `clearsignage_revision` in the selected
channel's `release.yaml` to that same full SHA first. Empty pins are normal. Debug builds
with `PUSH=false` do not require approval pins. A source SHA makes source selection
reproducible; base-image tags and installer versions are not a byte-for-byte image lock.

The existing Jenkins credential IDs are retained:

- `GithubPAT-Workplain-com`: read the private upstream source and write packaging commits
  and tags on main. Main's protection rules must permit the publishing identity.
- `ghcr-clearsignage`: read/write packages, and `delete:packages` for pruning.

No token is embedded in a repository URL. The new packages need the same private read
access as the old package. Configure `ghcr.io` credentials in Home Assistant before
installation. The OCI source label intentionally still points at the upstream
ClearSignage repository.

The manual GitHub Actions workflow supports the same channel mapping and gates. It is an
**alternative publisher**, not an additional concurrent publisher: use either Jenkins or
Actions. Their concurrency locks cannot coordinate with each other. Actions needs
`CLEARSIGNAGE_PAT` for private source access, package access for its token, and permission
to record on main and delete old package versions.

If recording fails after a successful image push, the job fails with the exact manifest
and image needing repair. Re-run the recorder with `CHANNEL` and `RECORD_VERSION`, or
update only that channel's version to the already-published tag. Do not rebuild merely to
repair the record.

Local single-architecture build (requires Python with PyYAML, Docker and upstream access):

```bash
CHANNEL=dev ./scripts/build.sh aarch64
CHANNEL=beta CLEARSIGNAGE_REF_OVERRIDE=<full-sha> ./scripts/build.sh amd64
```

`fetch-source.sh` copies `hosted/`, `device/`, `shared/`, `clearvenue/`, and `event_share/`
into the selected app's ignored `src/`, strips tests, verifies required runtime files and
records the resolved SHA. Both pipelines remove private source from the workspace after
the build. Local builders should remove their selected `src/` when finished.

### The screen release the image carries

Screens that joined a ClearVenue take their software from it (ClearSignage DP210), so
updating this app is how a venue's wall screens are updated, with no download host.
`scripts/build-screen-release.sh` makes that possible: after the version is chosen it
fetches the exact upstream commit the image is built from, runs ClearSignage's own
`packaging/build-release.sh` and `packaging/sign_update_manifest.py` with this app's
version and channel, checks the signature against the keyring that commit gives screens,
and places `manifest-<channel>.json` and `clearsignage-<version>.tar.gz` in
`src/screen-release/`. The Dockerfile's `COPY src/` carries them to
`/opt/clearsignage/screen-release`, which `CLEARVENUE_SCREEN_RELEASE_DIR` names.

- Jenkins signs with the global `update-signing-private-key` credential, the release job's
  own key. Actions needs it as the `UPDATE_SIGNING_PRIVATE_KEY` repository secret.
- A publish (`PUSH=true`) without the key **fails**: an image that silently carried no
  release would leave every joined screen where it is. A dry run without it warns and builds
  an image that offers its screens nothing.
- A screen only takes the release for its own channel: the stable app carries
  `manifest-stable.json`, beta `manifest-beta.json`, dev `manifest-dev.json`.

A local build carries one only if asked:

```bash
CHANNEL=dev ./scripts/fetch-source.sh
CHANNEL=dev SCREEN_RELEASE_VERSION=20261003.01 \
  UPDATE_SIGNING_PRIVATE_KEY="$(cat update_signing_private.pem)" \
  ./scripts/build-screen-release.sh
```

## Maintaining packaging

`clearvenue/` is the canonical shared Dockerfile, docs, build bases, translations and s6
service. After editing those files, run:

```bash
python scripts/sync-channel-packaging.py
python scripts/sync-channel-packaging.py --check
python -m pip install pytest pyyaml
python -m pytest tests -q
```

The helper updates shared files in beta/dev while preserving each channel's `config.yaml`
and `release.yaml`. Manifest settings other than channel identity and version must stay
consistent; tests enforce this and test all three apps. Upstream runtime environment
variables and `/opt/clearsignage` paths retain their names because they are source API
contracts, not HA slugs.

Tests exercise packaging, branch selection against local Git repositories, isolated
version recording and retry behavior, publish gates, registry bootstrap, pruning and
legacy cleanup selection. They do not replace a Docker build or an HA OS installation
check. After the first published build of each channel, check both platforms and install
it on a test HA host before relying on it for venue service.

## Repository rename and rollout

The intended repository URL is `https://github.com/madeByJansen/ClearVenue-HA`.
Rename the GitHub repository in **Settings → General → Repository name** before using the
new URL. The available connector has no rename operation. After renaming, update the
Jenkins SCM URL and local Git remote. The source repository remains `ClearSignage`.

Once this feature branch has been reviewed and merged by the owner, publish each channel
once from packaging main before offering it for installation. Until then, the newly
named images and their manifest versions are not a published release.

## Retiring old-slug releases

Remove old artifacts only after main advertises the new apps and all three advertised
versions have both architectures published. The cleanup helper checks those conditions
against GitHub and GHCR before it can delete anything:

```bash
# GHCR_TOKEN must have contents write and read/delete:packages permissions.
python scripts/cleanup-legacy-releases.py
# Review the dry-run list, then execute the identical selection:
python scripts/cleanup-legacy-releases.py --apply
```

If the repository has not yet been renamed, pass
`--repository madeByJansen/ClearSignage-HA`. This is an intentional legacy URL reference.
The helper deletes only the old `clearsignage-ha` GHCR package (including untagged layers),
unqualified version tags such as `v20260928.01`, and any GitHub Releases attached to those
old tags. It never deletes new channel images or channel-qualified tags, and is safe to
rerun after partial completion. GitHub may refuse deletion based on permissions or package
download limits; a failure is reported instead of being ignored. There were no GitHub
Releases at the implementation review; GHCR packages and Git tags are separate artifacts.

Regular channel retention can be previewed independently:

```bash
python scripts/prune-ghcr-releases.py --channel beta --current YYYYMMDD.NN
# Add --apply to delete the listed old beta versions.
```

## Installing

Add `ghcr.io` credentials to Home Assistant's Docker registries first, then add the
repository URL under Settings → Apps → Install app → ⋮ → **Repositories**. Choose
ClearVenue, ClearVenue Beta or ClearVenue Dev. See the app's Documentation tab for runtime
configuration, backups, and limitations.
