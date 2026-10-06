# Maintaining the CachyOS integration

We track three upstreams in `sources.lock.json`: the compositor patches, niri, and the community Codex desktop builder. Run `make check-updates` to report their latest commits. It never changes a working installation.

Update one source pin at a time. Read its changes, refresh the relevant patches, prepare fresh build trees, and run the native checks. Do not solve a failed patch by silently dropping it. Keep the accepted package until the new one passes.

For a Codex update, the packaged builder retains the native source modules, strict backend, and runtime validator. The plugin version includes a hash of its adapter modules and backend, so changing them invalidates stale plugin caches. The validator uses the new package's own SDK and rejects incompatible contracts before promotion. That covers the tested contracts; a new app release can still require a code change.

Before a release, verify the sources embedded in the actual package and rebuild a candidate using that packaged update-builder. Then test native CUA in a real login session. Isolated GTK checks do not establish compatibility with every app.

Keep user-specific paths, logs, process IDs, checkpoints, and built packages in ignored `.local/`, `build/`, or `dist/` directories. Publish source pins, patches, test code, and controlled fixture images. Keep original notices and licenses when importing changes.

CI checks patch application, script syntax, and adapter contracts. It does not replace the release checks that need a compiled compositor and the actual Codex SDK. Dependabot keeps the pinned GitHub Actions under review.
