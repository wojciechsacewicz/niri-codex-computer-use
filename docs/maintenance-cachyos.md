# Maintaining the CachyOS integration

This repository is a patch layer. It stores source pins, patches, tests, and packaging. `make prepare` fetches shallow upstream checkouts into ignored `build/` directories. We do not vendor the niri source tree or maintain a second copy of its history.

## Upstream changes

`make check-updates` reports niri's latest stable release and development branch separately. It also reports the compositor patch project and community Codex builder's default HEAD. The command never edits pins or installs anything. JSON output is available with `python3 scripts/check-updates.py --json`. Network failures remain visible and return a nonzero status.

Update one source pin at a time. Read the upstream changes, refresh patches, prepare fresh build trees, and run the native checks. Do not silently drop a patch to make a build pass. The daily GitHub workflow reports upstream revisions in its job summary. It does not publish issues, open PRs, or update users' machines.

We support reviewed stable niri releases. A new stable release may need patch changes before we can publish a compatible version. Development `main` is a compatibility target, not an automatic installation source. We cannot promise zero maintenance while niri's input changes remain outside upstream.

## GitHub releases and Topgrade

GitHub is the only distribution destination. There is no AUR entry or separate pacman repository.

The companion's `update` command checks the project's latest non-prerelease GitHub release, resolves its tag to an exact commit, reads the package version from that commit, and compares it with pacman's installed version. It never installs an older version. It builds from pinned source, runs the package's native checks, and requests installation through polkit only after they pass. A failed build preserves its logs and leaves the installation alone. Before installation, the updater also runs the installed Codex app's SDK checks and exercises its actual helper against the candidate compositor on a private display. An incompatible desktop blocks promotion. No compositor or desktop service is restarted.

The source build requires the build and test dependencies from the exported recipe. Missing dependencies stop the update before installation. We do not install dependencies or change system repositories behind the user's back. First builds can take several minutes and use disk space for Cargo dependencies. Prebuilt GitHub packages may be added later after release verification and a distribution policy are agreed.

```sh
niri-codex-computer-use update --check
niri-codex-computer-use update --build-only
niri-codex-computer-use update
niri-codex-computer-use setup-topgrade
```

The last command creates a dedicated user `topgrade.d` drop-in. It preserves the main Topgrade configuration and refuses to overwrite an existing custom drop-in. Remove that one file to disable the integration. Topgrade runs the same updater, including its checks and normal polkit prompt. It does not rebuild anything if no newer stable release is published.

The companion updater handles our compositor, strict helper, session launcher, and diagnostics. Codex desktop keeps its existing updater. Its packaged builder retains the adapter sources, strict helper, and validator. The plugin version includes a hash of the adapter modules and helper, so changes invalidate stale plugin caches. The validator checks the new package's actual SDK before promotion. That covers tested contracts, not every possible future change.

## Release checks

1. Increment `packaging/arch/release.json` and the local `PKGBUILD` together. Update the changelog.
2. Commit the reviewed integration, then run `make package-source`. The exported `PKGBUILD` and `.SRCINFO` point to that exact project commit. Publish the commit before sharing the recipe.
3. Run the Arch source-build workflow. It builds the patched compositor and backend, runs isolated input/screenshot tests, and checks the package's actual launcher and source lock. PR jobs test their checkout through a temporary local source URL; the distributed recipe always uses the public repository.
4. For Codex integration changes, build a desktop candidate, run its SDK checks, and rebuild using the sources embedded in its actual package.
5. Test a real login and native CUA with representative apps. Check focus, pointer, clipboard, screenshots, and the visible agent cursor. Record what passed and what remains unsupported.
6. Publish a stable `vMAJOR.MINOR.PATCH` release only after those checks. Prereleases do not reach the companion updater.

There is no stable release yet. The package and isolated tests do not establish real-login readiness. A maintainer must not publish a stable release from CI alone.

## Diagnostics and rollback

`niri-codex-computer-use doctor` reads package and systemd state without launching anything. Exit code 0 means the patched session has the expected configuration, 1 means an installation or service error, and 2 means activation is pending. The diagnostic also checks the companion binaries for missing shared libraries. A library ABI change is reported as a rebuild requirement, including when the stock session is active. The updater does not report an ABI-broken installation as up to date. None of these codes proves CUA input passed.

Keep stock niri installed. Its login session is the compositor rollback. Keep the accepted companion archive and the saved Codex package when validating an update. Reinstall them through pacman if a release regresses.

Keep local machine paths, logs, process IDs, checkpoints, and packages in ignored `.local/`, `build/`, or `dist/` directories. Publish the source pins, patches, tests, and controlled fixture images. Preserve original notices and licenses.
