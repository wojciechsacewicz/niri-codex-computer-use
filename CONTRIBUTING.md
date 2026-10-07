# Contributing

PRs are welcome. Start with a small change that you can explain and test.

## What to include

Describe the problem, the behavior after your change, and the checks you ran. For desktop bugs, include the niri version, Codex app version, Linux distribution, display scaling, and the app you used to reproduce the problem.

Include screenshots or a short recording when they help. Remove credentials and private information before sharing logs or recordings.

## Background control is the contract

A successful action must keep the person's pointer, keyboard focus, active window, and workspace unchanged. Window screenshots must leave the clipboard unchanged and avoid desktop notifications. The visible agent cursor must follow the agent's input in its own window.

Reject unsupported or conflicting input. Do not fall back to taking over the person's mouse or keyboard. Do not replay an input action after a timeout or transport error.

Test with separate app processes. Two windows from the same Wayland client can share input state, so they are not a valid isolation test.

## Upstream work

Keep changes derived from upstream separate from our integration changes. Record the source revision and preserve copyright and license notices. Avoid changing unrelated compositor behavior.

When updating a dependency, check that its patches still apply and run the relevant tests before replacing a working installation. State anything you could not verify.

## Project hygiene

Use Conventional Commits when making commits. Keep build output, local machine paths, credentials, and session notes out of the repository. Documentation should be in plain English.

Enable the local privacy check with `git config --local core.hooksPath .githooks`. It checks staged files without printing suspected private values. Run `python3 scripts/check-public-files.py` to check tracked files. Review screenshots before adding them; the check detects PNG metadata, not private information in the pixels.
