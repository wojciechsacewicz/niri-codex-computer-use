#!/usr/bin/env python3
"""Check the MCP backend against patched niri inside a private Xvfb session."""
import argparse
import hashlib
import json
import os
import re
from pathlib import Path
import signal
import select
import shutil
import sys
import socket
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser()
parser.add_argument('--niri', type=Path, required=True)
parser.add_argument('--xvfb', type=Path, required=True)
parser.add_argument('--backend', type=Path, required=True)
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--agent-backend', choices=['wayland', 'x11'], default='wayland')
args = parser.parse_args()
args.output.mkdir(parents=True, exist_ok=True)
args.output = args.output.resolve()
root = Path(__file__).resolve().parent
for name in ['niri', 'xvfb', 'backend']:
    binary = getattr(args, name).resolve(strict=True)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        parser.error(f'--{name} must name an executable file')
    setattr(args, name, binary)
if not shutil.which('bwrap'):
    parser.error('bwrap is required to isolate backend device access')
# A previous successful result must not survive a failed rerun.
(args.output / 'result.json').unlink(missing_ok=True)
(args.output / 'failure.json').unlink(missing_ok=True)
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
    for key in ['WAYLAND_DISPLAY', 'WAYLAND_SOCKET', 'NIRI_SOCKET', 'DBUS_SESSION_BUS_ADDRESS', 'DBUS_SESSION_BUS_PID', 'DBUS_STARTER_ADDRESS',
                'DBUS_STARTER_BUS_TYPE', 'AT_SPI_BUS_ADDRESS', 'NIRI_CONFIG',
                'NIRI_AGENT_LAUNCH', 'MANAGERPID', 'SYSTEMD_EXEC_PID']:
        env.pop(key, None)
    # The private session has no systemd manager for accessibility-bus activation.
    env.update(XDG_RUNTIME_DIR=runtime.name, WINIT_UNIX_BACKEND='x11',
               ATSPI_DBUS_IMPLEMENTATION='dbus-daemon', GIO_USE_VFS='local',
               LIBGL_ALWAYS_SOFTWARE='1', LP_NUM_THREADS='2', GALLIUM_DRIVER='llvmpipe')
    display = next(n for n in range(91, 110) if not Path(f'/tmp/.X11-unix/X{n}').exists())
    env['DISPLAY'] = f':{display}'
    auth = Path(runtime.name) / 'Xauthority'
    env['XAUTHORITY'] = str(auth)
    bus_log = (args.output / 'dbus.log').open('w')
    logs.append(bus_log)
    # Limit activation to AT-SPI; host portals mount FUSE paths in the test runtime.
    services = Path(runtime.name) / 'dbus-services'
    services.mkdir()
    (services / 'org.a11y.Bus.service').symlink_to('/usr/share/dbus-1/services/org.a11y.Bus.service')
    bus_config = Path(runtime.name) / 'dbus.conf'
    bus_config.write_text(f'''<busconfig>
  <type>session</type>
  <listen>unix:tmpdir={runtime.name}</listen>
  <auth>EXTERNAL</auth>
  <servicedir>{services}</servicedir>
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
    binary_hashes = {name: hashlib.sha256(getattr(args, name).read_bytes()).hexdigest()
                     for name in ['niri', 'backend']}
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
    subprocess.run([str(args.niri), 'validate', '-c', str(config)], env=env,
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5)
    niri = spawn([str(args.niri), '-c', str(config)], env, 'niri')
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
            if not response:
                raise EOFError('niri closed IPC without a reply')
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

    spawn([sys.executable, str(root / 'gtk-slider-fixture.py'), 'Human verification', str(args.output / 'human.json')], env, 'human')
    human = wait_for(lambda: find_window('Human verification'), 'human window')
    wait_for(lambda: read_state('human').get('widgets'), 'human widget state')
    subprocess.run(['wtype', 'human-before '], env=env, check=True, timeout=5)
    wait_for(lambda: read_state('human')['text'] == 'human-before ', 'foreground human typing')
    agent_env = {**env, 'NIRI_AGENT_LAUNCH': '1'}
    satellite_env = None
    if args.agent_backend == 'x11':
        def owned_satellite_display():
            # Match only X sockets held by this nested compositor, never host DISPLAY.
            inodes = set()
            for fd in Path(f'/proc/{niri.pid}/fd').iterdir():
                try:
                    link = os.readlink(fd)
                except FileNotFoundError:
                    continue
                if link.startswith('socket:['):
                    inodes.add(link[8:-1])
            for line in Path(f'/proc/{niri.pid}/net/unix').read_text().splitlines()[1:]:
                fields = line.split()
                if len(fields) == 8 and fields[6] in inodes:
                    match = re.fullmatch(r'@?/tmp/\.X11-unix/X(\d+)', fields[7])
                    if match:
                        return ':' + match.group(1)
            return None
        satellite_display = wait_for(owned_satellite_display, 'owned normal satellite X socket')
        assert satellite_display != env['DISPLAY'], 'Agent would connect to outer Xvfb'
        satellite_env = {**env, 'DISPLAY': satellite_display, 'GDK_BACKEND': 'x11', 'NO_AT_BRIDGE': '1'}
        satellite_env.pop('XAUTHORITY', None)
        satellite_env.pop('NIRI_AGENT_LAUNCH', None)
        agent_env = satellite_env
        (args.output / 'architecture.json').write_text(json.dumps({
            'outer_display': env['DISPLAY'], 'satellite_display': satellite_display,
            'nested_niri_pid': niri.pid, 'wayland_display': env['WAYLAND_DISPLAY'],
            'agent_backend': 'x11', 'agent_no_at_bridge': True,
            'display_discovery': 'nested niri owned socket inode via /proc',
            'satellite': 'normal niri on-demand integration', 'agent_relaunched': False,
        }, indent=2) + '\n')
    spawn([sys.executable, str(root / 'gtk-slider-fixture.py'), 'Agent verification', str(args.output / 'agent.json')], agent_env, 'agent')
    agent = wait_for(lambda: find_window('Agent verification'), 'agent window')
    state = wait_for(lambda: read_state('agent') if read_state('agent').get('widgets') else None, 'agent widgets')
    if args.agent_backend == 'x11':
        # Normal app opening may focus it. The human returns to their Wayland app
        # before any agent operation; the same existing X11 window stays open.
        ipc({'Action': {'FocusWindow': {'id': human['id']}}})
        wait_for(lambda: focused() == human['id'], 'human returns to Wayland app')
        x11_ids = subprocess.check_output(['xdotool', 'search', '--pid', str(state['pid'])],
            env=satellite_env, text=True, timeout=5).splitlines()
        assert x11_ids, 'Agent fixture is not on the owned satellite X display'
        (args.output / 'agent-x11-windows.json').write_text(json.dumps(x11_ids) + '\n')
    assert focused() == human['id'], 'Agent launch changed human focus'
    # XTEST acts only on the private nested display, never the actual desktop.
    subprocess.run(['xdotool', 'mousemove', '30', '30'], env=env, check=True, timeout=5)
    pointer_before = subprocess.check_output(['xdotool', 'getmouselocation', '--shell'], env=env, text=True)
    subprocess.run(['wl-copy', '--type', 'text/plain'], input=b'niri-cua-clipboard-canary', env=env, check=True, timeout=5)
    clipboard_before = subprocess.check_output(['wl-paste', '--no-newline'], env=env)

    backend_env = {**env, 'CODEX_COMPUTER_USE_NIRI_AGENT_REQUIRED': '1',
                   'CODEX_COMPUTER_USE_NIRI_AGENT': '1', 'TMPDIR': runtime.name}
    bin_dir = Path(runtime.name) / 'bin'
    bin_dir.mkdir()
    (bin_dir / 'niri').symlink_to(args.niri)
    backend_env['PATH'] = str(bin_dir) + os.pathsep + backend_env.get('PATH', '')

    def start_backend(environment, name):
        log = (args.output / (name + '.log')).open('w')
        logs.append(log)
        # Hide host input devices even if a regression reaches foreground fallback.
        command = ['bwrap', '--die-with-parent', '--unshare-user', '--unshare-pid',
                   '--unshare-ipc', '--unshare-net', '--ro-bind', '/', '/',
                   '--dev', '/dev', '--proc', '/proc',
                   '--bind', runtime.name, runtime.name,
                   '--bind', str(args.output), str(args.output),
                   '--', str(args.backend), 'mcp']
        backend = subprocess.Popen(command, env=environment, stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=log, text=True,
                                   start_new_session=True)
        processes.append(backend)
        sequence = 0

        def rpc(method, params):
            nonlocal sequence
            sequence += 1
            backend.stdin.write(json.dumps({'jsonrpc': '2.0', 'id': sequence,
                                           'method': method, 'params': params}) + '\n')
            backend.stdin.flush()
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                if not select.select([backend.stdout], [], [], 1)[0]:
                    continue
                line = backend.stdout.readline()
                if not line:
                    raise RuntimeError('backend exited; see its log')
                response = json.loads(line)
                if response.get('id') == sequence:
                    if 'error' in response:
                        raise RuntimeError(str(response['error']))
                    return response['result']
            raise RuntimeError('backend RPC timed out; request is not replayed')

        rpc('initialize', {'protocolVersion': '2024-11-05', 'capabilities': {},
                          'clientInfo': {'name': 'isolated-backend-check', 'version': '1'}})
        backend.stdin.write(json.dumps({'jsonrpc': '2.0',
                                       'method': 'notifications/initialized'}) + '\n')
        backend.stdin.flush()
        return rpc

    rpc = start_backend(backend_env, 'backend')

    def tool_data(result):
        data = result.get('structuredContent')
        if data is None:
            text = '\n'.join(item['text'] for item in result.get('content', [])
                             if item.get('type') == 'text')
            data = json.loads(text)
        return data

    def tool(name, values):
        result = rpc('tools/call', {'name':name,'arguments':values})
        if result.get('isError'): raise RuntimeError(str(result))
        data = tool_data(result)
        if isinstance(data,dict) and data.get('ok') is False: raise RuntimeError(str(data))
        assert focused() == human['id'], 'Backend tool changed human focus'
        return data
    listed = tool('list_windows', {})
    assert any(w['window_id'] == agent['id'] for w in listed['windows'])
    shot = tool('screenshot', {'window_id':agent['id']})
    assert shot.get('cropped_to_window') is True
    if args.agent_backend == 'x11':
        ipc({'AgentScreenshot': {'window_id': agent['id'],
            'path': str(args.output / 'agent-window-initial.png'), 'show_pointer': False}})
        assert (args.output / 'agent-window-initial.png').stat().st_size > 100

    def mcp_point(widget):
        x,y = center(widget)
        return {'x':round(x),'y':round(y),'relative':True,'window_id':agent['id']}

    def center(widget):
        rect = state['widgets'][widget]
        return rect['x'] + rect['width'] / 2, rect['y'] + rect['height'] / 2

    observed_failures = []

    def expect_state(check, description):
        try:
            wait_for(check, description, 3 if args.agent_backend == 'x11' else 10)
            return True
        except RuntimeError:
            if args.agent_backend != 'x11':
                raise
            observed_failures.append({'check': description, 'actual_agent_state': read_state('agent')})
            return False

    tool('click', mcp_point('entry'))
    tool('type_text', {'window_id':agent['id'],'text':'agent-only text'})
    wait_for(lambda: read_state('agent')['text'] == 'agent-only text', 'background agent typing')
    unicode_failure = None
    try:
        tool('type_text', {'window_id': agent['id'], 'text': ' ąć🙂'})
        wait_for(lambda: read_state('agent')['text'] == 'agent-only text ąć🙂',
                 'background Unicode typing', 3 if args.agent_backend == 'x11' else 10)
    except RuntimeError as error:
        if args.agent_backend != 'x11':
            raise
        refused = 'X11 non-ASCII text is unsupported' in str(error)
        if refused:
            assert read_state('agent')['text'] == 'agent-only text', 'Unicode refusal sent partial text'
            denied = tool_data(rpc('tools/call', {'name': 'type_text',
                'arguments': {'window_id': agent['id'], 'text': 'must-not-arrive ąć🙂'}}))
            assert denied['ok'] is False and 'no input was sent' in denied['message']
            assert read_state('agent')['text'] == 'agent-only text', 'Mixed text refusal sent ASCII prefix'
        unicode_failure = {'operation': 'type_text', 'expected': 'agent-only text ąć🙂',
                           'actual': read_state('agent')['text'], 'refused_before_input': refused}
        observed_failures.append(unicode_failure)
        (args.output / 'unicode-failure.json').write_text(json.dumps(unicode_failure, indent=2) + '\n')

    tool('click', mcp_point('button'))
    wait_for(lambda: read_state('agent')['clicks'] == 1, 'background button click')
    tool('scroll', {**mcp_point('scroll'),'direction':'down','pages':2})
    scroll_ok = expect_state(lambda: read_state('agent')['scroll'] > 0, 'background scrolling')
    time.sleep(0.3)  # Let the vendor cursor animation complete for visual evidence.
    capture = 'from PIL import ImageGrab;import os,sys;ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(sys.argv[1])'
    subprocess.run([sys.executable, '-c', capture, str(args.output / 'agent-cursor-screen.png')], env=env, check=True, timeout=5)
    focused_refusal = tool_data(rpc('tools/call', {'name': 'type_text',
        'arguments': {'window_id': human['id'], 'text': 'must-not-arrive'}}))
    assert focused_refusal['ok'] is False
    assert 'real keyboard focus' in focused_refusal['message']
    assert focused() == human['id']
    # Move the agent to another workspace without following it, and verify fresh hidden output.
    ipc({'Action': {'MoveWindowToWorkspace': {'window_id': agent['id'], 'reference': {'Index':2}, 'focus':False}}})
    assert focused() == human['id']
    tool('click', mcp_point('entry'))
    tool('press_key', {'window_id':agent['id'],'key':'End'})
    tool('type_text', {'window_id':agent['id'],'text':' hidden-fresh'})
    wait_for(lambda: read_state('agent')['text'].endswith(' hidden-fresh'), 'off-screen background typing')
    tool('press_key', {'window_id':agent['id'],'key':'Ctrl+A'})
    assert read_state('agent')['slider'] == 20
    rect = state['widgets']['slider']
    tool('drag', {'window_id':agent['id'], 'start_x':round(rect['x'] + rect['width'] * 0.2),
        'start_y':round(rect['y'] + rect['height']/2), 'end_x':round(rect['x'] + rect['width']*0.8),
        'end_y':round(rect['y'] + rect['height']/2), 'relative':True})
    drag_ok = expect_state(lambda: read_state('agent')['slider'] > 60 and read_state('agent')['drag_motion'] > 0, 'backend held-button drag')
    for name, values in [('press_key', {'window_id':agent['id'],'key':'DefinitelyUnknownKey'}),
        ('click', {'x':20,'y':20}), ('type_text', {'text':'must not reach human'}),
        ('click', {'window_id':agent['id'],'element_index':1})]:
        denied = rpc('tools/call', {'name':name,'arguments':values})
        data = tool_data(denied)
        assert data['ok'] is False and 'foreground fallback refused' in data['message']
    shot = tool('screenshot', {'window_id': agent['id'], 'raise_window': False})
    assert shot['cropped_to_window'] is True
    screenshot = ipc({'AgentScreenshot': {'window_id': agent['id'],
        'path': str(args.output / 'agent-window.png'), 'show_pointer': False}})
    assert (args.output / 'agent-window.png').stat().st_size > 100

    unavailable_env = {**backend_env, 'NIRI_SOCKET': str(Path(runtime.name) / 'missing-agent.sock')}
    unavailable_rpc = start_backend(unavailable_env, 'backend-unavailable')
    strict_cases = [
        ('click', {'window_id': agent['id'], 'x': 1, 'y': 2, 'relative': True}),
        ('type_text', {'window_id': agent['id'], 'text': 'never sent'}),
        ('press_key', {'window_id': agent['id'], 'key': 'Ctrl+A'}),
        ('scroll', {'window_id': agent['id'], 'direction': 'down', 'relative': True}),
        ('drag', {'window_id': agent['id'], 'start_x': 1, 'start_y': 2,
                  'end_x': 3, 'end_y': 4, 'relative': True}),
        ('click', {'x': 1, 'y': 2}),
        ('press_key', {'key': 'DefinitelyUnknownKey'}),
        ('type_text', {'text': 'never sent'}),
    ]
    for name, values in strict_cases:
        denied = tool_data(unavailable_rpc('tools/call', {'name': name, 'arguments': values}))
        assert denied['ok'] is False and 'foreground fallback refused' in denied['message']
        assert focused() == human['id']

    subprocess.run(['wtype', 'human-after'], env=env, check=True, timeout=5)
    wait_for(lambda: read_state('human')['text'] == 'human-before human-after', 'human continues typing')
    assert read_state('agent')['text'].endswith(' hidden-fresh'), 'Human keys reached the agent'
    assert subprocess.check_output(['xdotool', 'getmouselocation', '--shell'], env=env, text=True) == pointer_before
    assert subprocess.check_output(['wl-paste', '--no-newline'], env=env) == clipboard_before
    assert focused() == human['id']
    same_x11_refused = None
    if args.agent_backend == 'x11':
        spawn([sys.executable, str(root / 'gtk-slider-fixture.py'), 'X11 human verification',
               str(args.output / 'human-x11.json')], satellite_env, 'human-x11')
        human_x11 = wait_for(lambda: find_window('X11 human verification'), 'second normal X11 window')
        wait_for(lambda: read_state('human-x11').get('widgets'), 'X11 human widget state')
        ipc({'Action': {'FocusWindow': {'id': human_x11['id']}}})
        wait_for(lambda: focused() == human_x11['id'], 'human X11 focus for conflict check')
        conflict_before = read_state('agent')
        denied = tool_data(rpc('tools/call', {'name': 'type_text',
            'arguments': {'window_id': agent['id'], 'text': 'must-not-arrive-same-X11'}}))
        assert denied['ok'] is False and 'real keyboard focus' in denied['message']
        assert focused() == human_x11['id'], 'Conflict refusal changed X11 human focus'
        assert read_state('agent') == conflict_before, 'Refused X11 input changed target'
        assert read_state('human-x11')['text'] == '', 'Refused X11 input reached human'
        same_x11_refused = True
        (args.output / 'same-x11-refusal.json').write_text(json.dumps(denied, indent=2) + '\n')
        ipc({'Action': {'FocusWindow': {'id': human['id']}}})
        wait_for(lambda: focused() == human['id'], 'restore human Wayland focus')
    api_dir = root.parent / 'build/codex-desktop-linux/linux-features/computer-use-linux'
    node = os.environ.get('NCCU_NODE') or shutil.which('node')
    assert node and api_dir.is_dir(), 'Prepared native API sources and Node are required'
    sandbox = ['bwrap', '--die-with-parent', '--unshare-user', '--unshare-pid',
               '--unshare-ipc', '--unshare-net', '--ro-bind', '/', '/',
               '--dev', '/dev', '--proc', '/proc', '--bind', runtime.name, runtime.name,
               '--bind', str(args.output), str(args.output), '--', str(args.backend), 'mcp']
    script = """
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {createNativeBackendService} = await import(pathToFileURL(process.env.NCCU_API_DIR + '/native-backend-service.mjs'));
const {installLinuxComputerUse} = await import(pathToFileURL(process.env.NCCU_API_DIR + '/native-client.mjs'));
const sandbox = JSON.parse(process.env.NCCU_API_SANDBOX);
const service = createNativeBackendService({command:sandbox[0],args:sandbox.slice(1),environment:{...process.env,CODEX_LINUX_APP_DIR:''}});
globalThis.nodeRepl={write(){},rpc:(_,request)=>service.handleRpc(request)};
try {
 const cua = installLinuxComputerUse({});
 const app = await cua.getApp({windowId:Number(process.env.NCCU_API_WINDOW)});
 const state = JSON.parse(await app.getAXState({emit:false}));
 assert.equal(state.accessibility_error, null, 'Native API accessibility failed');
 const entry = state.accessibility_tree.find(node=>node.role==='text' && node.editable);
 assert.ok(entry, 'Expected an editable entry: ' + JSON.stringify({accessibility_error:state.accessibility_error,nodes:state.accessibility_tree.slice(0,16)}));
 await app.click(entry.index,{mouseButton:'l'});
 await app.pressKey('Control_L+a');
 await app.paste('native-api exact ✓ 🦊');
 const fresh = JSON.parse(await app.getAXState({emit:false}));
 const button = fresh.accessibility_tree.find(node=>node.role==='button' && node.name==='Click verification button');
 assert.ok(button, 'Expected the fixture button: ' + JSON.stringify(fresh.accessibility_tree.slice(0,16)));
 await app.click(button.index,{mouseButton:'l'});
 const after = JSON.parse(await app.getAXState({emit:false}));
 const scroll = after.accessibility_tree.find(node=>node.role==='scroll bar' && node.bounds);
 assert.ok(scroll, 'Expected a bounded scroll bar: ' + JSON.stringify(after.accessibility_tree.slice(0,16)));
 await app.scroll(scroll.index,'d',{pixels:200});
 await app.getAXState({emit:false});
 console.log('Native API indexed clicks, aliases, keys and paste passed.');
} finally {service.shutdown();}
"""
    if args.agent_backend == 'x11':
        script = """
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const {createNativeBackendService} = await import(pathToFileURL(process.env.NCCU_API_DIR + '/native-backend-service.mjs'));
const {installLinuxComputerUse} = await import(pathToFileURL(process.env.NCCU_API_DIR + '/native-client.mjs'));
const sandbox = JSON.parse(process.env.NCCU_API_SANDBOX);
const service = createNativeBackendService({command:sandbox[0],args:sandbox.slice(1),environment:{...process.env,CODEX_LINUX_APP_DIR:''}});
globalThis.nodeRepl={write(){},rpc:(_,request)=>service.handleRpc(request)};
try {
 const app = await installLinuxComputerUse({}).getApp({windowId:Number(process.env.NCCU_API_WINDOW)});
 const state = JSON.parse(await app.getAXState({emit:false}));
 const {writeFileSync} = await import('node:fs');
 writeFileSync(process.env.NCCU_API_STATE_OUT, JSON.stringify(state,null,2));
 assert.ok(!state.accessibility_tree.some(node=>node.editable ||
   (node.role==='button' && node.name==='Click verification button')),
   'No-AX fixture unexpectedly exposes its interactive widgets');
 const points = JSON.parse(process.env.NCCU_API_POINTS);
 assert.ok((await app.getScreenshot({emit:false})).length > 100);
 await assert.rejects(app.click(0), /accessibility|element index/i);
 await assert.rejects(app.scroll(0,'d',{pixels:200}), /accessibility|element index/i);
 await app.click(points.entry,{mouseButton:'l'});
 await app.pressKey('Control_L+a');
 await app.paste('native-api pixel text');
 await assert.rejects(app.paste('must-not-arrive ąć🙂'), /X11 non-ASCII text is unsupported/);
 await app.click(points.button,{mouseButton:'l'});
 await app.scroll(points.scroll,'d',{pixels:200});
 console.log('Native API X11 pixels passed; AX observation saved; numeric click/scroll refused.');
} finally {service.shutdown();}
"""
    api_hashes = {name: hashlib.sha256((api_dir / name).read_bytes()).hexdigest()
                  for name in ['native-client.mjs', 'native-protocol.mjs', 'native-backend-service.mjs']}
    api_before = read_state('agent')
    api_env = {**backend_env, 'NCCU_API_DIR': str(api_dir),
               'NCCU_API_SANDBOX': json.dumps(sandbox), 'NCCU_API_WINDOW': str(agent['id']),
               'NCCU_API_STATE_OUT': str(args.output / 'native-api-x11-state.json'),
               'NCCU_API_POINTS': json.dumps({name: [round(v) for v in center(name)]
                   for name in ['entry', 'button', 'scroll']})}
    run = subprocess.run([node, '--input-type=module'], input=script, env=api_env,
                         text=True, capture_output=True, timeout=30)
    (args.output / 'native-api.log').write_text(run.stdout + run.stderr)
    assert run.returncode == 0, 'Native API checks failed; see native-api.log'
    api_text = 'native-api pixel text' if args.agent_backend == 'x11' else 'native-api exact ✓ 🦊'
    wait_for(lambda: read_state('agent')['text'] == api_text, 'native API exact text')
    wait_for(lambda: read_state('agent')['clicks'] == api_before['clicks'] + 1, 'native API indexed button click')
    native_scroll_ok = expect_state(lambda: read_state('agent')['scroll'] > api_before['scroll'],
        'native API pixel scrolling' if args.agent_backend == 'x11' else 'native API indexed scrolling')
    assert read_state('human')['text'] == 'human-before human-after', 'Native API keys reached the human'
    assert focused() == human['id'], 'Native API changed human focus'
    assert subprocess.check_output(['xdotool', 'getmouselocation', '--shell'], env=env, text=True) == pointer_before
    assert subprocess.check_output(['wl-paste', '--no-newline'], env=env) == clipboard_before
    assert all(hashlib.sha256(getattr(args, name).read_bytes()).hexdigest() == value
               for name, value in binary_hashes.items()), 'Test binaries changed during the run'
    assert all(hashlib.sha256((api_dir / name).read_bytes()).hexdigest() == value
               for name, value in api_hashes.items()), 'Native API sources changed during the run'
    result = dict(binary_sha256={'niri': hashlib.sha256(args.niri.read_bytes()).hexdigest(), 'codex-computer-use-linux': hashlib.sha256(args.backend.read_bytes()).hexdigest()}, test_sha256={name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in ['backend-mcp-check.py', 'gtk-slider-fixture.py']}, status='failed' if observed_failures else 'passed', observed_failures=observed_failures, unicode_failure=unicode_failure, backend_mcp=True, background_text=True, background_click=True, background_scroll=scroll_ok, background_keys=True, background_drag=drag_ok, strict_rejections=True, strict_refusal_count=len(strict_cases), drag_start=20, drag_value=read_state('agent')['slider'], drag_motion=read_state('agent')['drag_motion'],
                  network_isolation='bubblewrap-net',
                  api_sha256={name: hashlib.sha256((api_dir / name).read_bytes()).hexdigest() for name in ['native-client.mjs', 'native-protocol.mjs', 'native-backend-service.mjs']},
                  native_api=native_scroll_ok and unicode_failure is None, native_pixel_click_text=True, indexed_actions=args.agent_backend == 'wayland', documented_aliases=True,
                  agent_backend=args.agent_backend, no_ax=args.agent_backend == 'x11',
                  numeric_ax_refused=args.agent_backend == 'x11', native_scroll=native_scroll_ok,
                  same_x11_focus_refused=same_x11_refused,
                  existing_window_id=agent['id'], existing_agent_pid=state['pid'],
                  background_unicode=unicode_failure is None, offscreen_input=True, focused_client_refused=True,
                  human_focus_unchanged=True, human_pointer_unchanged=True, clipboard_unchanged=True,
                  input_streams_isolated=True, screenshot=screenshot, windows=windows())
except BaseException as error:
    (args.output / 'failure.json').write_text(json.dumps({
        'status': 'failed', 'agent_backend': args.agent_backend,
        'error': str(error), 'error_type': type(error).__name__,
    }, indent=2) + '\n')
    raise
finally:
    if 'ipc' in locals():
        try:
            ipc({'Action': {'Quit': {'skip_confirmation': True}}})
            niri.wait(timeout=3)
        except (OSError, RuntimeError, EOFError, subprocess.TimeoutExpired, json.JSONDecodeError):
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
    for child in processes:
        for pipe in [child.stdin, child.stdout]:
            if pipe is not None:
                pipe.close()
    for log in logs:
        log.close()
    runtime.cleanup()

result['owned_processes_reaped'] = all(child.poll() is not None for child in processes)
assert result['owned_processes_reaped']
(args.output / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
print(json.dumps({k: v for k, v in result.items() if k not in ['windows', 'screenshot', 'observed_failures']}), flush=True)

if result['status'] != 'passed':
    raise SystemExit(1)
