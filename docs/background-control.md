# Background control

The goal is to let a person and Codex use different apps at the same time in one niri session. The person keeps their normal pointer and keyboard focus. Codex gets a visible agent cursor inside its target window.

The implementation comes from [lihaoze123/niri-computer-use](https://github.com/lihaoze123/niri-computer-use), pinned initially to revision `2e518b2d555936fe48e89efe43c8f7f2ef0225f9`. Its `AgentInput` and `AgentScreenshot` requests extend niri's local IPC interface.

## Limits inherited from upstream

The agent cannot operate an app client that currently holds the person's keyboard focus. This includes two windows created by the same browser process. Use a separate browser profile and process for agent work. XWayland apps share the satellite's Wayland client, so the same conflict also applies across separate X11 or Wine apps. A real X11 fixture confirmed that input is refused while a Wine app holds human focus.

The upstream pointer hold can suppress real pointer delivery to the agent client for 600 ms after input, or during an agent drag. If you move your mouse into that same client, its hover cursor can briefly change. Work in a separate app while the agent runs. Full same-client pointer independence is still an open limitation.

Applications can differ in how they handle input while inactive. Upstream reports testing terminals, GTK apps, and Chromium. That does not establish compatibility with every app or with our CachyOS build.

Wayland clipboard operations and drag-and-drop between apps need real seat focus or a valid grab. They are not part of the background guarantee. Typing text and dragging inside an app are separate operations.

## Acceptance checks

1. Keep a person typing in a separate test app while the agent clicks and types in its target.
2. Check that the person's pointer position, cursor shape, keyboard focus, active window, and workspace do not change.
3. Verify scrolling and dragging against the target app's resulting state.
4. Capture covered and off-screen windows, and check that the image is fresh.
5. Check that screenshots leave the clipboard unchanged and produce no notifications.
6. Inspect the visible agent cursor and its position within the target window.
7. Test same-client conflicts, missing agent IPC, disconnected services, and timeouts. Each must fail clearly without replaying input or taking over the person's controls.
8. Rebuild from the packaged update sources and check that the accepted integration survives the next build.

A build, an accessibility tree, or a working screenshot alone does not pass these checks.
