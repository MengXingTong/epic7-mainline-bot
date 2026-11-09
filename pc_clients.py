"""Exact native-client executable registry; no process inspection or game input.

Steam and STOVE share the guarded PC transport, not an account/history identity.
The historical ``stove_pc`` config key remains valid for both distributions.
"""
from __future__ import annotations
import ntpath
import os

# Never infer a client from the installation directory, title alone, or Steam's
# launcher/overlay. Add a new executable only after inspecting its game window.
PC_EXECUTABLES = {
    'epicseven.exe': 'STOVE',
    'epicseven_steam.exe': 'Steam',
}


def pc_distribution(executable):
    """Return the distribution for an exact executable basename, else None."""
    return PC_EXECUTABLES.get(ntpath.basename(os.fspath(executable)).casefold())
