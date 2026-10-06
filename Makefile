.PHONY: help prepare build build-niri build-backend test-native check-updates package desktop install-companion
help:
	@printf '%s\n' 'make prepare       Fetch pinned sources and apply reviewed patches' 'make build         Build the compositor and backend' 'make test-native   Run isolated background-control checks' 'make check-updates Report upstream activity without changing the installation' 'make package       Build the CachyOS companion package'
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
check-updates:
	python3 scripts/check-updates.py
package:
	bash scripts/package.sh
desktop:
	bash scripts/build-desktop.sh
install-companion:
	bash scripts/install-companion.sh
