.PHONY: help prepare build build-niri build-backend test-native test-x11 check-updates package package-source doctor desktop install-companion
help:
	@printf '%s\n' 'make prepare        Fetch pinned sources and apply reviewed patches' 'make build          Build the compositor and backend' 'make test-native    Run isolated background-control checks' 'make test-x11       Check an existing X11 window without accessibility' 'make check-updates  Report stable and development upstream revisions' 'make doctor         Inspect the installation without changing it' 'make package        Package previously tested local build outputs' 'make package-source Export a standalone recipe for committed public sources'
prepare:
	python3 scripts/prepare-sources.py all
build:
	bash scripts/build.sh all
build-niri:
	bash scripts/build.sh niri
build-backend:
	bash scripts/build.sh codex
test-native:
	bash scripts/test-native.sh
test-x11:
	bash scripts/test-native.sh x11
check-updates:
	python3 scripts/check-updates.py
package:
	bash scripts/package.sh
package-source:
	bash scripts/package-source.sh
doctor:
	python3 scripts/doctor.py
desktop:
	bash scripts/build-desktop.sh
install-companion:
	bash scripts/install-companion.sh
