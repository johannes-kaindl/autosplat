# SPDX-License-Identifier: AGPL-3.0-or-later

"""PyInstaller entry point for AutoSplat.app — delegates to the desktop launcher."""

from autosplat.desktop import main

if __name__ == "__main__":
    main()
