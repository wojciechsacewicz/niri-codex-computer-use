# Changelog

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

Real companion login and native CUA app acceptance remain pending. This version is not a stable release.
