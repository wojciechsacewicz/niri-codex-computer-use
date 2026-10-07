#!/usr/bin/env python3
"""Check vendor niri background control inside a private Xvfb display."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import socket
import subprocess
import tempfile
import threading
import time

parser = argparse.ArgumentParser()
parser.add_argument('--niri', type=Path, required=True)
parser.add_argument('--xvfb', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--stress-cycles', type=int, default=0)
parser.add_argument('--stress-scale', type=float, default=1.0)
parser.add_argument('--parent-wayland-socket', type=Path)
parser.add_argument('--parent-niri-socket', type=Path)
args = parser.parse_args()
if not 0 <= args.stress_cycles <= 1000 or not 1 <= args.stress_scale <= 2:
    parser.error('stress cycles must be 0..1000 and scale 1..2')
if bool(args.parent_wayland_socket) != bool(args.parent_niri_socket):
    parser.error('GPU nesting requires both parent Wayland and niri socket paths')
for parent in [args.parent_wayland_socket, args.parent_niri_socket]:
    if parent and (not parent.is_absolute() or not parent.is_socket()):
        parser.error('parent sockets must be existing absolute socket paths')
args.output.mkdir(parents=True, exist_ok=True)
args.output = args.output.resolve()
(args.output / 'result.json').unlink(missing_ok=True)
root = Path(__file__).resolve().parent
initial_test_hashes = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ['nested-control.py', 'gtk-fixture.py']}
initial_binary_hash = hashlib.sha256(args.niri.read_bytes()).hexdigest()
processes = []
logs = []
parent_pump_stop = threading.Event()
parent_pump = None
parent_pump_errors = []


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
    for key in ['WAYLAND_DISPLAY', 'WAYLAND_SOCKET', 'NIRI_SOCKET', 'DBUS_SESSION_BUS_ADDRESS', 'DBUS_SESSION_BUS_PID', 'DBUS_STARTER_ADDRESS', 'DBUS_STARTER_BUS_TYPE', 'AT_SPI_BUS_ADDRESS', 'NIRI_CONFIG', 'NIRI_AGENT_LAUNCH', 'MANAGERPID', 'SYSTEMD_EXEC_PID']:
        env.pop(key, None)
    env.update(XDG_RUNTIME_DIR=runtime.name, WINIT_UNIX_BACKEND='x11',
               NO_AT_BRIDGE='1', GIO_USE_VFS='local', LIBGL_ALWAYS_SOFTWARE='1', LP_NUM_THREADS='2', GALLIUM_DRIVER='llvmpipe')
    display = next(n for n in range(91, 110) if not Path(f'/tmp/.X11-unix/X{n}').exists())
    env['DISPLAY'] = f':{display}'
    auth = Path(runtime.name) / 'Xauthority'
    env['XAUTHORITY'] = str(auth)
    bus_log = (args.output / 'dbus.log').open('w'); logs.append(bus_log)
    bus_config = Path(runtime.name) / 'dbus.conf'
    bus_config.write_text(f'''<busconfig>
  <type>session</type>
  <listen>unix:tmpdir={runtime.name}</listen>
  <auth>EXTERNAL</auth>
  <policy context="default">
    <allow own="*"/>
    <allow send_destination="*"/>
    <allow receive_sender="*"/>
  </policy>
</busconfig>
''')
    bus = subprocess.Popen(['dbus-daemon', '--config-file=' + str(bus_config), '--nofork', '--print-address=1'],
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
    if args.stress_cycles:
        config.write_text(config.read_text().replace('layout {\n', 'layout {\n    shadow {\n        on\n        softness 30\n        spread 5\n        offset x=0 y=5\n    }\n')
                          + '\noutput "winit" { scale ' + str(args.stress_scale) + '; }\n'
                          + 'window-rule { geometry-corner-radius 12; }\n')
    theme = os.environ.get('NCCU_TEST_CURSOR_THEME')
    if theme:
        config.write_text(config.read_text() + '\ncursor { xcursor-theme ' + json.dumps(theme) + '; xcursor-size 24; }\n')
    subprocess.run([str(args.niri.resolve()), 'validate', '-c', str(config)], env=env,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5)
    renderer_env = env.copy()
    if args.parent_wayland_socket:
        for key in ['LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER', 'DISPLAY']:
            renderer_env.pop(key, None)
        renderer_env.update(WAYLAND_DISPLAY=str(args.parent_wayland_socket),
                            WINIT_UNIX_BACKEND='wayland', NIRI_AGENT_LAUNCH='1',
                            RUST_LOG='niri=info,smithay::backend::egl=info,smithay::backend::renderer::gles=debug')
    if args.parent_niri_socket:
        parent_env = {**env, 'NIRI_SOCKET': str(args.parent_niri_socket)}
        initial_parent = json.loads(subprocess.check_output([str(args.niri.resolve()), 'msg', '-j', 'focused-window'], env=parent_env, timeout=5))
        if initial_parent is None:
            raise RuntimeError('GPU background verification needs an already focused foreground app; no test window was opened')
    niri = spawn([str(args.niri.resolve()), '-c', str(config)], renderer_env, 'niri')
    ipc_path = wait_for(lambda: next(Path(runtime.name).glob('niri.*.sock'), None), 'nested niri IPC', 20)
    wayland = wait_for(lambda: next((p for p in Path(runtime.name).glob('wayland-*') if not p.name.endswith('.lock')), None), 'nested Wayland')
    env.update(NIRI_SOCKET=str(ipc_path), WAYLAND_DISPLAY=wayland.name, GDK_BACKEND='wayland')

    def ipc(request, socket_path=None):
        with socket.socket(socket.AF_UNIX) as client:
            client.settimeout(5)
            client.connect(str(socket_path or ipc_path))
            client.sendall(json.dumps(request).encode() + b'\n')
            client.shutdown(socket.SHUT_WR)
            response = b''
            while b'\n' not in response:
                chunk = client.recv(65536)
                if not chunk:
                    break
                response += chunk
            if not response:
                raise RuntimeError(f'IPC closed without a response; compositor exit status={niri.poll()}')
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

    if args.parent_niri_socket:
        def owned_parent_window():
            return next((window for window in ipc('Windows', args.parent_niri_socket)['Windows'] if window.get('pid') == niri.pid), None)
        parent_window = wait_for(owned_parent_window, 'owned nested GPU window')
        assert ipc('FocusedWindow', args.parent_niri_socket)['FocusedWindow']['id'] != parent_window['id'], 'Nested GPU launch took human focus'
        # Hidden Wayland clients wait for frame callbacks; pump only our test window.
        def pump_parent():
            while not parent_pump_stop.is_set():
                try:
                    ipc({'AgentScreenshot': {'window_id': parent_window['id'], 'path': str(args.output / 'nested-parent.png'), 'show_pointer': False}}, args.parent_niri_socket)
                except Exception as error:
                    parent_pump_errors.append(str(error))
                    return
                parent_pump_stop.wait(0.25)
        parent_pump = threading.Thread(target=pump_parent, daemon=True)
        parent_pump.start()

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
    if args.parent_niri_socket:
        ipc({'AgentScreenshot': {'window_id': parent_window['id'], 'path': str(args.output / 'agent-cursor-screen.png'), 'show_pointer': False}}, args.parent_niri_socket)
    else:
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
    if args.stress_cycles:
        from PIL import Image
        started = time.monotonic()
        with ThreadPoolExecutor(max_workers=3) as captures:
            for cycle in range(args.stress_cycles):
                ipc({'Action': {'MoveWindowToWorkspace': {'window_id': agent['id'], 'reference': {'Index': 1 + cycle % 2}, 'focus': False}}})
                ipc({'Action': {'SetWindowWidth': {'id': agent['id'], 'change': {'SetFixed': 430 + (cycle % 5) * 65}}}})
                send([{'Motion': {'x': 45.0, 'y': 60.0}}, {'Axis': {'vertical': 24.0, 'horizontal': 0.0}}])
                image_path = args.output / 'lifecycle-window.png'
                ipc({'AgentScreenshot': {'window_id': agent['id'], 'path': str(image_path), 'show_pointer': True}})
                with Image.open(image_path) as image:
                    assert image.width > 0 and image.height > 0
                    image.verify()
                if cycle % 8 == 7:
                    old_id = agent['id']
                    pending = [captures.submit(ipc, {'AgentScreenshot': {'window_id': old_id, 'path': str(args.output / f'closing-{index}.png'), 'show_pointer': True}}) for index in range(3)]
                    ipc({'Action': {'CloseWindow': {'id': old_id}}})
                    wait_for(lambda: find_window('Agent verification') is None, 'closed agent window')
                    for future in pending:
                        try:
                            future.result(timeout=5)
                        except RuntimeError as error:
                            assert 'no window with id' in str(error), str(error)
                    (args.output / 'agent.json').unlink(missing_ok=True)
                    spawn([sys.executable, str(root / 'gtk-fixture.py'), 'Agent verification', str(args.output / 'agent.json')], agent_env, f'lifecycle-{cycle}')
                    agent = wait_for(lambda: find_window('Agent verification'), 'reopened agent window')
                    state = wait_for(lambda: read_state('agent') if read_state('agent').get('widgets') else None, 'reopened widgets')
                assert niri.poll() is None, 'Compositor exited during window lifecycle stress'
                assert focused() == human['id'], 'Lifecycle stress changed human focus'
                assert read_state('human')['text'] == 'human-before human-after', 'Lifecycle input reached the human'
        assert subprocess.check_output(['xdotool', 'getmouselocation', '--shell'], env=env, text=True) == pointer_before
        assert subprocess.check_output(['wl-paste', '--no-newline'], env=env) == clipboard_before
        print(json.dumps({'lifecycle_cycles': args.stress_cycles, 'scale': args.stress_scale, 'seconds': round(time.monotonic() - started, 2)}), flush=True)
    assert not parent_pump_errors, f'Parent frame pump failed: {parent_pump_errors}'
    assert hashlib.sha256(args.niri.read_bytes()).hexdigest() == initial_binary_hash, 'Compositor binary changed during the check'
    assert {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in initial_test_hashes} == initial_test_hashes, 'Test sources changed during the check'
    result = dict(binary_sha256={'niri': initial_binary_hash}, test_sha256=initial_test_hashes, status='passed', background_text=True, background_click=True, background_scroll=True,
                  background_unicode=True, background_drag=True, offscreen_input=True, focused_client_refused=True,
                  human_focus_unchanged=True, human_pointer_unchanged=True, clipboard_unchanged=True,
                  input_streams_isolated=True, lifecycle_cycles=args.stress_cycles, lifecycle_scale=args.stress_scale,
                  renderer_backend='parent-wayland' if args.parent_wayland_socket else 'private-x11-software',
                  screenshot=screenshot, windows=windows())
finally:
    if sys.exc_info()[0] is not None:
        (args.output / 'failure-processes.json').write_text(json.dumps([{'pid': child.pid, 'exit_status': child.poll()} for child in processes], indent=2) + '\n')
    parent_pump_stop.set()
    if parent_pump:
        parent_pump.join(timeout=6)
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
