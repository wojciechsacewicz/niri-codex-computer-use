#!/usr/bin/env python3
"""Check vendor niri background control inside a private Xvfb display."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import socket
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--niri', type=Path, required=True)
parser.add_argument('--xvfb', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
args.output = args.output.resolve()
(args.output / 'result.json').unlink(missing_ok=True)
root = Path(__file__).resolve().parent
processes = []
logs = []


def spawn(command, env, name):
    log = (args.output / (name + '.log')).open('w')
    logs.append(log)
    child = subprocess.Popen(command, env=env, stdin=subprocess.DEVNULL, stdout=log,
                             stderr=subprocess.STDOUT, start_new_session=True)
    processes.append(child)
    return child


def wait_for(check, description, seconds=10):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        try:
            result = check()
            if result:
                return result
        except (OSError, json.JSONDecodeError, KeyError):
            pass
        time.sleep(0.05)
    raise RuntimeError('Timed out: ' + description)


def read_state(name):
    return json.loads((args.output / (name + '.json')).read_text())


runtime = tempfile.TemporaryDirectory(prefix='niri-cua-test-')
try:
    env = os.environ.copy()
    for key in ['WAYLAND_DISPLAY', 'WAYLAND_SOCKET', 'NIRI_SOCKET', 'DBUS_SESSION_BUS_ADDRESS', 'MANAGERPID', 'SYSTEMD_EXEC_PID']:
        env.pop(key, None)
    env.update(XDG_RUNTIME_DIR=runtime.name, WINIT_UNIX_BACKEND='x11',
               GIO_USE_VFS='local', LIBGL_ALWAYS_SOFTWARE='1', LP_NUM_THREADS='2', GALLIUM_DRIVER='llvmpipe')
    display = next(n for n in range(91, 110) if not Path(f'/tmp/.X11-unix/X{n}').exists())
    env['DISPLAY'] = f':{display}'
    auth = Path(runtime.name) / 'Xauthority'
    env['XAUTHORITY'] = str(auth)
    bus_log = (args.output / 'dbus.log').open('w'); logs.append(bus_log)
    bus = subprocess.Popen(['dbus-daemon', '--session', '--nofork', '--print-address=1'],
                           env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=bus_log, text=True, start_new_session=True)
    processes.append(bus)
    import select
    assert select.select([bus.stdout], [], [], 5)[0], 'Private D-Bus did not start'
    env['DBUS_SESSION_BUS_ADDRESS'] = bus.stdout.readline().strip()
    assert env['DBUS_SESSION_BUS_ADDRESS'].startswith('unix:'), 'Private D-Bus address invalid'
    cookie = os.urandom(16).hex()
    subprocess.run(['xauth', '-f', str(auth), 'add', env['DISPLAY'], '.', cookie],
                   env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    auth.chmod(0o600)
    spawn([str(args.xvfb.resolve()), env['DISPLAY'], '-screen', '0', '1280x800x24',
           '-nolisten', 'tcp', '-auth', str(auth)], env, 'xvfb')
    wait_for(lambda: Path(f'/tmp/.X11-unix/X{display}').exists(), 'private Xvfb')
    config = args.output / 'niri-test.kdl'
    config.write_text('''prefer-no-csd
hotkey-overlay {
    skip-at-startup
}
layout {
    gaps 8
    default-column-width {
        fixed 600
    }
}
input {
    keyboard {
        xkb {
            layout "us"
        }
    }
}
''')
    theme = os.environ.get('NCCU_TEST_CURSOR_THEME')
    if theme:
        config.write_text(config.read_text() + '\ncursor { xcursor-theme ' + json.dumps(theme) + '; xcursor-size 24; }\n')
    subprocess.run([str(args.niri.resolve()), 'validate', '-c', str(config)], env=env,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5)
    niri = spawn([str(args.niri.resolve()), '-c', str(config)], env, 'niri')
    ipc_path = wait_for(lambda: next(Path(runtime.name).glob('niri.*.sock'), None), 'nested niri IPC', 20)
    wayland = wait_for(lambda: next((p for p in Path(runtime.name).glob('wayland-*') if not p.name.endswith('.lock')), None), 'nested Wayland')
    env.update(NIRI_SOCKET=str(ipc_path), WAYLAND_DISPLAY=wayland.name, GDK_BACKEND='wayland')

    def ipc(request):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(5)
            client.connect(str(ipc_path))
            client.sendall(json.dumps(request).encode() + b'\n')
            client.shutdown(socket.SHUT_WR)
            response = b''
            while b'\n' not in response:
                chunk = client.recv(65536)
                if not chunk:
                    break
                response += chunk
            result = json.loads(response)
        if 'Err' in result:
            raise RuntimeError(str(result['Err']))
        return result['Ok']

    def windows():
        return ipc('Windows')['Windows']

    def find_window(title):
        return next((w for w in windows() if w['title'] == title), None)

    def focused():
        return ipc('FocusedWindow')['FocusedWindow']['id']

    spawn([sys.executable, str(root / 'gtk-fixture.py'), 'Human verification', str(args.output / 'human.json')], env, 'human')
    human = wait_for(lambda: find_window('Human verification'), 'human window')
    wait_for(lambda: read_state('human').get('widgets'), 'human widget state')
    subprocess.run(['wtype', 'human-before '], env=env, check=True, timeout=5)
    wait_for(lambda: read_state('human')['text'] == 'human-before ', 'foreground human typing')
    agent_env = {**env, 'NIRI_AGENT_LAUNCH': '1'}
    spawn([sys.executable, str(root / 'gtk-fixture.py'), 'Agent verification', str(args.output / 'agent.json')], agent_env, 'agent')
    agent = wait_for(lambda: find_window('Agent verification'), 'agent window')
    state = wait_for(lambda: read_state('agent') if read_state('agent').get('widgets') else None, 'agent widgets')
    assert focused() == human['id'], 'Agent launch changed human focus'
    # XTEST acts only on the private nested display, never the actual desktop.
    subprocess.run(['xdotool', 'mousemove', '30', '30'], env=env, check=True, timeout=5)
    pointer_before = subprocess.check_output(['xdotool', 'getmouselocation', '--shell'], env=env, text=True)
    subprocess.run(['wl-copy', '--type', 'text/plain'], input=b'niri-cua-clipboard-canary', env=env, check=True, timeout=5)
    clipboard_before = subprocess.check_output(['wl-paste', '--no-newline'], env=env)

    def send(events):
        ipc({'AgentInput': {'window_id': agent['id'], 'events': events}})
        assert focused() == human['id'], 'Agent input changed human focus'

    def center(widget):
        rect = state['widgets'][widget]
        return rect['x'] + rect['width'] / 2, rect['y'] + rect['height'] / 2

    def click(widget):
        x, y = center(widget)
        send([{'Motion': {'x': x, 'y': y}}, {'Button': {'button': 272, 'pressed': True}}, {'Button': {'button': 272, 'pressed': False}}])

    click('entry')
    send([{'Text': {'text': 'agent-only text', 'unicode_input': 'Keymap'}}])
    wait_for(lambda: read_state('agent')['text'] == 'agent-only text', 'background agent typing')
    send([{'Text': {'text': ' ąć🙂', 'unicode_input': 'Keymap'}}])
    wait_for(lambda: read_state('agent')['text'] == 'agent-only text ąć🙂', 'background Unicode typing')
    click('button')
    wait_for(lambda: read_state('agent')['clicks'] == 1, 'background button click')
    x, y = center('scroll')
    send([{'Motion': {'x': x, 'y': y}}, {'Axis': {'vertical': 150.0, 'horizontal': 0.0}}])
    wait_for(lambda: read_state('agent')['scroll'] > 0, 'background scrolling')
    # Drag inside the text entry, then capture the visible agent marker.
    rect = state['widgets']['entry']; y = rect['y'] + rect['height'] / 2
    points = [rect['x'] + 12 + step * 8 for step in range(13)]
    send([{'Motion': {'x': points[0], 'y': y}}, {'Button': {'button': 272, 'pressed': True}}])
    for x in points[1:]:
        send([{'Motion': {'x': x, 'y': y}}])
    send([{'Button': {'button': 272, 'pressed': False}}])
    wait_for(lambda: len(read_state('agent')['selection']) == 2, 'background text-selection drag')
    time.sleep(0.3)  # Let the vendor cursor animation complete for visual evidence.
    capture = 'from PIL import ImageGrab;import os,sys;ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(sys.argv[1])'
    subprocess.run([sys.executable, '-c', capture, str(args.output / 'agent-cursor-screen.png')], env=env, check=True, timeout=5)
    # Driving the human client must fail without entering it or sending input.
    try:
        ipc({'AgentInput': {'window_id': human['id'], 'events': [{'Text': {'text':'must-not-arrive', 'unicode_input':'Keymap'}}]}})
    except RuntimeError as error:
        assert 'real keyboard focus' in str(error), str(error)
    else:
        raise AssertionError('Focused-client conflict was not refused')
    # Move the agent to another workspace without following it, and verify fresh hidden output.
    ipc({'Action': {'MoveWindowToWorkspace': {'window_id': agent['id'], 'reference': {'Index':2}, 'focus':False}}})
    assert focused() == human['id']
    send([{'Key': {'keycode':107,'pressed':True}}, {'Key': {'keycode':107,'pressed':False}}])
    send([{'Text': {'text':' hidden-fresh', 'unicode_input':'Keymap'}}])
    wait_for(lambda: read_state('agent')['text'].endswith(' hidden-fresh'), 'off-screen background typing')
    screenshot = ipc({'AgentScreenshot': {'window_id': agent['id'], 'path': str(args.output / 'agent-window.png'), 'show_pointer': False}})
    assert (args.output / 'agent-window.png').stat().st_size > 100
    subprocess.run(['wtype', 'human-after'], env=env, check=True, timeout=5)
    wait_for(lambda: read_state('human')['text'] == 'human-before human-after', 'human continues typing')
    assert read_state('agent')['text'].endswith(' hidden-fresh'), 'Human keys reached the agent'
    assert subprocess.check_output(['xdotool', 'getmouselocation', '--shell'], env=env, text=True) == pointer_before
    assert subprocess.check_output(['wl-paste', '--no-newline'], env=env) == clipboard_before
    assert focused() == human['id']
    result = dict(binary_sha256={'niri': hashlib.sha256(args.niri.read_bytes()).hexdigest()}, test_sha256={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ['nested-control.py', 'gtk-fixture.py']}, status='passed', background_text=True, background_click=True, background_scroll=True,
                  background_unicode=True, background_drag=True, offscreen_input=True, focused_client_refused=True,
                  human_focus_unchanged=True, human_pointer_unchanged=True, clipboard_unchanged=True,
                  input_streams_isolated=True, screenshot=screenshot, windows=windows())
finally:
    if 'ipc' in locals():
        try:
            ipc({'Action': {'Quit': {'skip_confirmation': True}}})
            niri.wait(timeout=3)
        except (OSError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError):
            pass
    for child in reversed(processes):
        try:
            os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=3)
        except ProcessLookupError:
            pass
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
    for log in logs:
        log.close()
    runtime.cleanup()

result['owned_processes_reaped'] = all(child.poll() is not None for child in processes)
assert result['owned_processes_reaped']
(args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: v for k, v in result.items() if k not in ['windows', 'screenshot']}), flush=True)
