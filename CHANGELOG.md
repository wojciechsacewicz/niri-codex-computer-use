# Changelog

## 0.1.2, unreleased

- Reuse the human cursor theme and image for the separate tinted agent cursor.
- Keep a random agent color stable across windows and idle periods.
- Support indexed clicks and scrolling, documented button/direction aliases, and keysym modifier names.
- Use OpenAI's bundled Linux helper for the installed-app catalog.
- Refuse ambiguous app launches instead of binding an unrelated new window.
- Correct Unicode input classification for Helium, Chromium app windows, and Electron applications.
- Exercise the native JavaScript API through an isolated compositor and real backend.
- Match Linux SDK rules for existing-window binding, scroll distances, click options, and mutation results.
- Preserve available inventory results if native or browser discovery fails.
- Add existing X11 window checks without accessibility, plus local rendering and window-lifecycle stress checks.
- Refuse unsupported X11 Unicode before sending partial text.
- Re-enter pointer delivery after the agent cursor expires.
- Add a local public-file guard for private paths, session data, credentials, and image metadata.
- Report a replaced running compositor as awaiting relogin, rather than a failed installation.

The updated companion login and GTK checks through the actual `cua_repl` tool passed, including Unicode, indexed input, dragging, and fresh images on an inactive workspace at 150% scale. Vision-only Chromium control passed earlier. Concurrent input to two XWayland apps remains unsupported. An earlier real session crashed; the cause remains under investigation. These checks do not establish long-term stability. The diagnostic correction is prepared for the next package build. Compositor changes still require activation at the next login.

## 0.1.1, unreleased

- Fix the first-login failure caused by resetting an unloaded systemd unit.
- Build standalone Arch packages from pinned public source commits.
- Share the package payload between developer builds and source builds.
- Add GitHub stable-release updates and a user Topgrade drop-in.
- Add read-only installation/session diagnostics and stable/development upstream reports.
- Verify local Arch source builds with isolated background-input tests.
- Keep verification local; remove GitHub CI and scheduled repository automation.
- Disable GCC LTO for C wrappers while retaining Cargo's Rust LTO.
- Detect missing shared libraries after system updates.

Real companion login and initial native CUA app acceptance passed on CachyOS. No stable release is published yet.
