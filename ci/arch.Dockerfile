FROM archlinux:base-devel
RUN pacman -Syu --noconfirm --needed base-devel git rust clang python nodejs niri cairo glib2 libinput libpipewire libxkbcommon libxkbcommon-x11 mesa pango pixman seatd libdisplay-info libxrandr libxft xorg-server-xvfb xorg-xauth xdotool wtype wl-clipboard bubblewrap dbus gtk3 python-gobject python-pillow \
    && useradd --create-home --uid 1000 builder
WORKDIR /work
