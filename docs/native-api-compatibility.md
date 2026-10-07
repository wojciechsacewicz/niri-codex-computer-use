# Native API compatibility

The target is the standard `cua_repl` API, with niri handling background input and window rendering. Agents should use `cua.getState()`, `cua.listApps()`, `cua.listWindows()`, `cua.getApp({windowId})`, and the usual app methods. No alternate MCP or special prompting is required.

We compared the installed OpenAI runtime's `@oai/cua` documentation and Linux type definitions on 7 October 2026. The public Codex repository contains configuration and policy code; the installed desktop runtime supplies the native application API and Linux helper. OpenAI's [computer-use guide](https://learn.chatgpt.com/docs/computer-use) describes macOS and Windows availability. Its [Linux preview documentation](https://learn.chatgpt.com/docs/linux/linux-app#compatibility-and-limitations) does not yet promise Linux computer use. Our integration is an independent project.

| API | niri implementation |
| --- | --- |
| App and window discovery | OpenAI's bundled installed-app catalog, combined with niri's actual window IDs |
| App launch | Explicit `cua.computer.launch_app`; `getApp` binds an existing window without launching it |
| Accessibility state | Passive AT-SPI observation scoped to the selected window |
| Window images | niri renders the selected window, including covered and hidden workspace contents |
| Coordinate clicks and dragging | Targeted agent input, without desktop pointer movement |
| Element clicks and scrolling | Latest observed element identity, owning-frame coordinates, and verified capture scale/offsets |
| Keyboard and plain-text paste | Targeted input; modifier aliases and Chromium/Electron Unicode handling |
| Mouse and scroll aliases | Full names and documented shortcuts; Linux accepts `{ pixels }`, not page counts |
| Mutation results | Click, drag, scroll, key input, paste, and window mutations return `undefined`, matching the SDK |
| `selectText`, `setValue`, rich paste | Unsupported by the documented Linux API; requests are refused |
| Secondary accessibility actions | Not implemented in this adapter; requests do not fall back to foreground control |

Accessibility is optional for coordinate input and vision. Chromium with renderer accessibility disabled passed typing and clicking against screenshot pixels; its tree contained only an app and frame. Screenshots of hidden workspace contents remained fresh after input. The test did not capture the person's foreground app.

The image coordinate dimensions can differ from a downscaled image. Element actions handle the conversion. Coordinate actions use the reported capture coordinate space, as documented by the runtime.

The cursor uses the current human cursor image, theme, hotspot, scale, and animation frames. A compositor shader changes the agent copy's color. A random context identifier supplied by each backend instance keeps its color stable across windows and indicator expiry. The physical cursor is not recolored. Theme and app-supplied cursor images stay on the user's system.

## What remains unsupported

The target includes existing user-opened windows. We do not require app relaunches, separate agent X servers, or hooks into every process. A private nested compositor is used only for verification.

An agent cannot share a Wayland client with the person's keyboard focus. That includes two windows from one browser process and separate X11/Wine apps hosted by the same XWayland satellite. Refusal is deliberate; removing it would risk interference.

The existing-window X11 check exercises coordinate input and vision without accessibility. X11 non-ASCII text is refused before input because temporary keymap changes can corrupt the text. An initial MCP scroll has no effect, while a later native API scroll passes; the suite remains failed. Shared-client refusal still applies.

The bundled OpenAI Linux helper offers X11 background operations, but its `type_text` failed for a test app without an AT-SPI provider. It has not been enabled as an input fallback. An X11 route must pass no-accessibility, focus, pointer, clipboard, and cursor checks before becoming a supported alternative.

Apps can grab input, pause while hidden, or handle synthesized input differently. Cross-app drag-and-drop and clipboard sharing are outside the background guarantee. A passing GTK or Chromium test does not establish game, Wine, remote-desktop, or every-toolkit compatibility.

## Local verification

Run `make test-native` after preparing and building the sources. For existing X11 window checks, the backend suite also accepts `--agent-backend x11` and writes failed results when a capability does not work. The backend suite also exercises the native JavaScript app API through the real helper and compositor on private displays, with host input devices hidden and a private network namespace. It checks exact Unicode text, indexed actions, documented aliases, and unchanged human focus, pointer position, and clipboard. Node 22 or later is a test dependency.

`make test-x11` runs the existing-window X11 check separately. An overall failure remains visible even if some actions pass. Mocked adapter tests also check Linux scroll validation, indexed click limits, mutation return values, and discovery when one inventory provider fails.

Set `NCCU_TEST_CURSOR_THEME` to a locally installed theme when checking its visual output. Cursor changes require a new compositor session; updating package files does not replace the running compositor.

Keep verification local. This repository has no GitHub CI or scheduled workflows.

The compositor fixture accepts `--stress-cycles` and `--stress-scale` for repeated capture, resizing, hidden workspace moves, and closing windows while screenshots are pending. An optional GPU check accepts absolute `--parent-wayland-socket` and `--parent-niri-socket` paths for a patched niri session. It opens one temporary background test window and requires an already focused foreground app. It refuses to continue if that test window receives focus. Both modes use private test apps; the GPU frame pump captures only its own nested window. Software rendering and nested GPU checks do not prove KMS-session stability.
