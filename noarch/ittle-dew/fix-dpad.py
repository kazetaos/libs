#!/usr/bin/env python3
"""Fix the D-pad mapping of Ittle Dew on Linux.

The game's InputManager (in IttleDew_Data/mainData) reads the D-pad from
joystick axes 5/6, the Windows layout. On Linux the D-pad hat is axes 6/7,
and its Y axis points the other way. This patches those two entries.

Usage: ./fix-dpad.py [path/to/mainData]   (default: next to this script)
Safe to run more than once; a backup is written to mainData.orig.
"""
import os
import shutil
import struct
import sys

JOYSTICK_AXIS = 2  # InputAxis.type value for joystick axes
# axis name -> (Windows axis, Linux axis, invert on Linux)
FIXES = {
    'Horizontal': (5, 6, 0),
    'Vertical': (6, 7, 1),
}


def find_axes(d):
    """Return (offset of first entry, entry count) of the InputManager axes array."""
    key = struct.pack('<I', 10) + b'Horizontal'
    i = d.find(key)
    while i >= 0:
        cnt = struct.unpack_from('<I', d, i - 4)[0]
        if 1 <= cnt <= 200:
            return i, cnt
        i = d.find(key, i + 1)
    sys.exit('InputManager axes not found; is this the right mainData?')


def read_string(d, p):
    n = struct.unpack_from('<I', d, p)[0]
    s = d[p + 4:p + 4 + n].decode('latin1')
    return s, (p + 4 + n + 3) & ~3


def main():
    here = os.path.dirname(os.path.abspath(__file__))
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(here, 'IttleDew_Data', 'mainData')
    d = bytearray(open(path, 'rb').read())

    p, cnt = find_axes(d)
    patched = already = 0
    for _ in range(cnt):
        name, p = read_string(d, p)
        for _ in range(6):  # descriptive names and button strings
            _, p = read_string(d, p)
        p += 12  # gravity, dead, sensitivity
        invert_at = p + 1  # snap, invert (padded to 4 bytes)
        p += 4
        typ, axis, _joy = struct.unpack_from('<iii', d, p)
        if typ == JOYSTICK_AXIS and name in FIXES:
            win, lin, inv = FIXES[name]
            if axis == win:
                struct.pack_into('<i', d, p + 4, lin)
                d[invert_at] = inv
                patched += 1
                print(f'{name}: axis {win} -> {lin}' + (', inverted' if inv else ''))
            elif axis == lin and d[invert_at] == inv:
                already += 1
        p += 12

    if patched:
        backup = path + '.orig'
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
            print(f'backup: {backup}')
        open(path, 'wb').write(d)
        print('D-pad fixed.')
    elif already == len(FIXES):
        print('Already patched, nothing to do.')
    else:
        sys.exit('D-pad entries not found; mainData layout differs from expected.')


if __name__ == '__main__':
    main()
