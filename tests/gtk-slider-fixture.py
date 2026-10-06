#!/usr/bin/env python3
"""GTK clients reporting entry, button, scroll, and held-button slider events."""
import json
import os
import sys
from pathlib import Path
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib, Gdk

output = Path(sys.argv[2])
window = Gtk.Window(title=sys.argv[1])
window.set_default_size(600, 500)
window.set_decorated(False)
box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
box.set_border_width(20)
window.add(box)
box.pack_start(Gtk.Label(label=sys.argv[1]), False, False, 0)
entry = Gtk.Entry()
entry.set_placeholder_text('Verification input')
box.pack_start(entry, False, False, 0)
button = Gtk.Button(label='Click verification button')
box.pack_start(button, False, False, 0)
label = Gtk.Label(label='Clicks: 0')
box.pack_start(label, False, False, 0)
slider = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 0, 100, 1)
slider.set_value(20)
box.pack_start(slider, False, False, 0)
drag_motion = 0
def slider_motion(widget, event):
    global drag_motion
    if event.state & Gdk.ModifierType.BUTTON1_MASK:
        drag_motion += 1
    return False
slider.add_events(Gdk.EventMask.POINTER_MOTION_MASK)
slider.connect('motion-notify-event', slider_motion)
scroll = Gtk.ScrolledWindow()
box.pack_start(scroll, True, True, 0)
rows = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
for i in range(80):
    rows.pack_start(Gtk.Label(label=f'Verification row {i + 1}'), False, False, 0)
scroll.add(rows)
clicks = 0

def report(*unused):
    widgets = {}
    for name, widget in [('entry', entry), ('button', button), ('scroll', scroll), ('slider', slider)]:
        pos = widget.translate_coordinates(window, 0, 0)
        allocation = widget.get_allocation()
        if pos:
            widgets[name] = dict(x=pos[0], y=pos[1], width=allocation.width, height=allocation.height)
    data = dict(pid=os.getpid(), text=entry.get_text(), clicks=clicks,
                scroll=scroll.get_vadjustment().get_value(), selection=list(entry.get_selection_bounds()), slider=slider.get_value(), drag_motion=drag_motion, widgets=widgets)
    temporary = output.with_suffix('.tmp')
    temporary.write_text(json.dumps(data))
    temporary.replace(output)
    return False

def clicked(*unused):
    global clicks
    clicks += 1
    label.set_text(f'Clicks: {clicks}')
    report()

entry.connect('changed', report)
slider.connect('value-changed', report)
button.connect('clicked', clicked)
scroll.get_vadjustment().connect('value-changed', report)
window.connect('configure-event', report)
window.connect('destroy', Gtk.main_quit)
window.show_all()
entry.grab_focus()
GLib.timeout_add(100, report)
Gtk.main()
