# Changelog

## 0.1.2, unreleased

- Reuse the human cursor theme and image for the separate tinted agent cursor.
- Keep a random agent color stable across windows and idle periods.
- Support indexed clicks and scrolling, documented button/direction aliases, and keysym modifier names.
- Use OpenAI's bundled Linux helper for the installed-app catalog.
- Refuse ambiguous app launches instead of binding an unrelated new window.
- Correct Unicode input classification for Helium, Chromium app windows, and Electron applications.
- Exercise the native JavaScript API through an isolated compositor and real backend.

The real companion login, GTK input, and vision-only Chromium control passed. Concurrent input to two XWayland apps remains unsupported. A real session also crashed in the installed compositor; the cause remains under investigation. The new API and cursor changes have not yet been installed or validated in a real session. Cursor changes require activating the updated compositor at the next login.

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
