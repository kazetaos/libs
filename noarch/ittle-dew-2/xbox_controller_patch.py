#!/usr/bin/env python3
"""
Ittle Dew 2+ (Linux 64-bit) -- Xbox controller patch.

Button prompts (ID2_Data/resources.assets). The PC build shows gamepad buttons
as coloured circles labelled with raw joystick numbers ("0", "1", ...):

  * buttons 0-3      -> A / B / X / Y on the existing green/red/blue/yellow circles
  * button 4 / 5     -> LB / RB bumper icons
  * button 6 / 7     -> Xbox View / Menu icons
  * button 8, 9, 10  -> "Guide", "LS", "RS" labels
  * d-pad (11-14)    -> arrow icons (stray "AltGr" entries removed)

The new icons are written into the PS4 prompt sprites, which the PC build
never uses. The Menu art comes from the game's own unused Xbox One texture.

D-pad (ID2_Data/globalgamemanagers + resources.assets). The PC build only
binds the left stick and keyboard arrows to movement. Linux reports an Xbox
d-pad either as a hat (joystick axes 6/7) or as buttons 11-14, so both are
bound to movement and menu navigation.

Requirements:  python3 -m pip install UnityPy
Usage:
  python3 xbox_controller_patch.py [GAME_DIR]            apply the patch
  python3 xbox_controller_patch.py [GAME_DIR] --restore  undo it
  python3 xbox_controller_patch.py [GAME_DIR] --make-patch [OUT]
      leave the game alone and write a git binary patch (default
      xbox_controller.patch); others can then apply it from the game
      directory with `git apply OUT` (undo: `git apply -R OUT`), no Python needed
GAME_DIR defaults to the directory containing this script.

The first run saves each untouched file as <name>.orig; every run patches
from those backups, so applying twice is safe.
"""
import argparse
import base64
import hashlib
import io
import os
import shutil
import struct
import sys

ORIG_SHA256 = {
    "resources.assets": "4c53372b2250d818b3b207882158470585126a65509d0343637062eaf3515d3c",
    "globalgamemanagers": "4d31419e034df679f519ccac3f85de91e2e96a2ff2af2d2b9df33b18d1b5ea87",
}

# Object path IDs inside resources.assets
OVERLAY_DATA = 2586          # StandardInputOverlayData (the PC prompt table)
MENU_SOURCE_TEX = 550        # Xbone_Key_Lines (unused Xbox One Menu art)
# d-pad arrow sprites (Pad_button_11..14 hold up, down, left, right art)
SPR_ARROW_UP, SPR_ARROW_DOWN, SPR_ARROW_LEFT, SPR_ARROW_RIGHT = 785, 803, 763, 854
# InputButton objects
BTN_HORZ, BTN_VERT = 2522, 2523
BTN_DOWN, BTN_LEFT, BTN_RIGHT, BTN_UP = 2526, 2531, 2534, 2536
# (sprite, texture) pairs of unused PS4 prompts that get new art
SLOT_MENU = (850, 527)       # PS4_Key_Options
SLOT_VIEW = (872, 644)       # PS4_Key_TouchPad
SLOT_LB = (793, 221)         # PS4_Key_L1
SLOT_RB = (842, 475)         # PS4_Key_R1

JOY0 = 330                   # UnityEngine.KeyCode.JoystickButton0

# Linux joydev Xbox layout: 0 A, 1 B, 2 X, 3 Y, 4 LB, 5 RB, 6 Back/View,
# 7 Start/Menu, 8 Guide, 9 LS, 10 RS, 11-14 d-pad left/right/up/down
# (xpad's BTN_TRIGGER_HAPPY1-4); axes 6/7 are the d-pad hat.
DPAD_LEFT, DPAD_RIGHT, DPAD_UP, DPAD_DOWN = JOY0 + 11, JOY0 + 12, JOY0 + 13, JOY0 + 14

# value: (sprite path id or None to keep, label text, text scale)
PROMPTS = {
    JOY0 + 0: (None, "A", 1.0),
    JOY0 + 1: (None, "B", 1.0),
    JOY0 + 2: (None, "X", 1.0),
    JOY0 + 3: (None, "Y", 1.0),
    JOY0 + 4: (SLOT_LB[0], "", 1.0),
    JOY0 + 5: (SLOT_RB[0], "", 1.0),
    JOY0 + 6: (SLOT_VIEW[0], "", 1.0),
    JOY0 + 7: (SLOT_MENU[0], "", 1.0),
    JOY0 + 8: (None, "Guide", 0.5),
    JOY0 + 9: (None, "LS", 0.8),
    JOY0 + 10: (None, "RS", 0.8),
    DPAD_LEFT: (SPR_ARROW_LEFT, "", 1.0),
    DPAD_RIGHT: (SPR_ARROW_RIGHT, "", 1.0),
    DPAD_UP: (SPR_ARROW_UP, "", 1.0),
    DPAD_DOWN: (SPR_ARROW_DOWN, "", 1.0),
}

# New Unity input axes for the d-pad hat. Hat Y reports up as negative, so it
# is inverted like the game's left-stick axis.
DPAD_AXES = (("dpadX", 6, False), ("dpadY", 7, True))
# InputButton -> (extra joystick buttons, extra axes)
BINDINGS = {
    BTN_HORZ: ([], ["dpadX"]),
    BTN_VERT: ([], ["dpadY"]),
    BTN_UP: ([DPAD_UP], []),
    BTN_DOWN: ([DPAD_DOWN], []),
    BTN_LEFT: ([DPAD_LEFT], []),
    BTN_RIGHT: ([DPAD_RIGHT], []),
}

ICON_VIEW = (
"""
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
""")
ICON_LB = (
"""
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
f0d7fJoRoK2MAAAAAElFTkSuQmCC
""")
ICON_RB = (
"""
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
""")


def die(msg):
    sys.exit("error: " + msg)


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def png(b64):
    from PIL import Image
    return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGBA")


class Reader:
    def __init__(self, raw):
        self.raw, self.p = raw, 0

    def get(self, fmt):
        v = struct.unpack_from(fmt, self.raw, self.p)
        self.p += struct.calcsize(fmt)
        return v[0] if len(v) == 1 else v

    def string(self):
        n = self.get("<i")
        s = self.raw[self.p:self.p + n].decode()
        self.p = (self.p + n + 3) & ~3
        return s


def pack_string(s):
    b = s.encode()
    return struct.pack("<i", len(b)) + b + b"\0" * ((-len(b)) % 4)


def patch_overlay_table(obj):
    """Rewrite the KeyData[] list of StandardInputOverlayData."""
    r = Reader(obj.get_raw_data())
    r.get("<iq"); r.get("<i"); r.get("<iq")          # GameObject, enabled, script
    if r.string() != "StandardInputOverlayData":
        die("unexpected prompt table object; is this the right game version?")
    r.get("<iq"); r.get("<i"); r.get("<iq"); r.get("<i"); r.get("<fff")
    head = r.raw[:r.p]
    entries = []
    for _ in range(r.get("<i")):
        code = r.get("<i"); fid, pid = r.get("<iq"); text = r.string(); scale = r.get("<f")
        entries.append([code, fid, pid, text, scale])
    tail = r.raw[r.p:]

    out = []
    for code, fid, pid, text, scale in entries:
        if JOY0 + 11 <= code <= JOY0 + 19 and text == "AltGr":
            continue  # bogus duplicates that hid the d-pad icons
        if code in PROMPTS:
            new_pid, text, scale = PROMPTS[code]
            if new_pid is not None:
                fid, pid = 0, new_pid
        out.append((code, fid, pid, text, scale))

    body = bytearray(head) + struct.pack("<i", len(out))
    for code, fid, pid, text, scale in out:
        body += struct.pack("<iiq", code, fid, pid) + pack_string(text) + struct.pack("<f", scale)
    body += tail
    obj.set_raw_data(bytes(body))


def make_full_quad(obj):
    """PS4 sprites are tight-cropped to their old outline; make them a full 128x128 quad."""
    h = 0.25  # 128 px / 256 px-per-unit / 2
    quad = b"".join(struct.pack("<5f", x, y, 0, 0, 0) for x, y in ((-h, h), (h, -h), (h, h), (-h, -h)))
    tt = obj.read_typetree()
    rd = tt["m_RD"]
    vd = rd["m_VertexData"]
    vd["m_VertexCount"] = 4
    vd["m_DataSize"] = list(quad) if isinstance(vd["m_DataSize"], list) else quad
    rd["m_IndexBuffer"] = [3, 0, 0, 0, 1, 0, 2, 0, 1, 0, 0, 0]
    sm = rd["m_SubMeshes"][0]
    sm["indexCount"], sm["vertexCount"] = 6, 4
    rd["m_SubMeshes"] = [sm]
    rd["textureRect"] = {"x": 0.0, "y": 0.0, "width": 128.0, "height": 128.0}
    rd["textureRectOffset"] = {"x": 0.0, "y": 0.0}
    obj.save_typetree(tt)


def patch_input_button(obj, add_buttons, add_axes):
    """Append key codes / axis names to an InputButton's default ButtonData."""
    r = Reader(obj.get_raw_data())
    r.get("<iq"); r.get("<i"); r.get("<iq")          # GameObject, enabled, script
    r.string()                                        # m_Name
    head = r.raw[:r.p]
    buttons = [r.get("<i") for _ in range(r.get("<i"))]
    axes = [r.string() for _ in range(r.get("<i"))]
    if r.p != len(r.raw):
        die("unexpected InputButton layout; is this the right game version?")
    buttons += [b for b in add_buttons if b not in buttons]
    axes += [a for a in add_axes if a not in axes]
    body = bytearray(head) + struct.pack("<i", len(buttons))
    body += struct.pack("<%di" % len(buttons), *buttons)
    body += struct.pack("<i", len(axes)) + b"".join(pack_string(a) for a in axes)
    obj.set_raw_data(bytes(body))


def patch_resources(objs):
    menu = objs[MENU_SOURCE_TEX].read().image.convert("RGBA")
    for (spr, tex), img in ((SLOT_MENU, menu), (SLOT_VIEW, png(ICON_VIEW)),
                            (SLOT_LB, png(ICON_LB)), (SLOT_RB, png(ICON_RB))):
        t = objs[tex].read()
        t.set_image(img)
        t.save()
        make_full_quad(objs[spr])

    patch_overlay_table(objs[OVERLAY_DATA])
    for pid, (buttons, axes) in BINDINGS.items():
        patch_input_button(objs[pid], buttons, axes)


def patch_globalgamemanagers(objs):
    mgr = [o for o in objs.values() if o.type.name == "InputManager"]
    if len(mgr) != 1:
        die("InputManager not found in globalgamemanagers")
    tt = mgr[0].read_typetree()
    template = next(a for a in tt["m_Axes"] if a["m_Name"] == "axis0")
    names = {a["m_Name"] for a in tt["m_Axes"]}
    for name, axis, invert in DPAD_AXES:
        if name in names:
            continue
        a = dict(template)
        a.update(m_Name=name, descriptiveName="", descriptiveNegativeName="", axis=axis, invert=invert)
        tt["m_Axes"].append(a)
    mgr[0].save_typetree(tt)


def apply(src, dst, patcher):
    import UnityPy
    env = UnityPy.load(src)
    files = [f for f in env.files.values() if hasattr(f, "objects")]
    if not files:
        die("could not read " + src)
    patcher(files[0].objects)

    data = files[0].save()  # serialise fully before touching the output file
    tmp = dst + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    shutil.copymode(src, tmp)
    os.replace(tmp, dst)


def make_patch(data_dir, jobs, out, force):
    """Write a git binary patch (apply with `git apply`) instead of patching the game."""
    import subprocess
    import tempfile

    if not shutil.which("git"):
        die("--make-patch needs git to generate the patch")
    with tempfile.TemporaryDirectory() as tmp:
        for name, patcher in jobs:
            target = os.path.join(data_dir, name)
            src = target + ".orig" if os.path.isfile(target + ".orig") else target
            if sha256(src) != ORIG_SHA256[name] and not force:
                die(src + " does not match the known Ittle Dew 2+ Linux build.\n"
                    "If you are sure it is the unpatched original, re-run with --force.")
            for side in ("orig", "new"):
                os.makedirs(os.path.join(tmp, side, "ID2_Data"), exist_ok=True)
            shutil.copy2(src, os.path.join(tmp, "orig", "ID2_Data", name))
            # read from the game dir so the texture stream (.resS) next to it resolves
            apply(src, os.path.join(tmp, "new", "ID2_Data", name), patcher)
        res = subprocess.run(["git", "diff", "--no-index", "--binary", "--full-index", "orig", "new"],
                             cwd=tmp, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if res.returncode != 1:  # 1 = files differ
            die("git diff failed: " + res.stderr.decode(errors="replace"))

    # make paths relative to the game dir: a/orig/ID2_Data/x -> a/ID2_Data/x
    lines = res.stdout.split(b"\n")
    for i, line in enumerate(lines):
        if line.startswith((b"diff --git ", b"--- ", b"+++ ")):
            lines[i] = line.replace(b"a/orig/", b"a/").replace(b"b/new/", b"b/")
    with open(out, "wb") as fh:
        fh.write(b"\n".join(lines))
    print("wrote " + out)
    print("apply from the game directory with:  git apply " + os.path.basename(out))
    print("undo with:                           git apply -R " + os.path.basename(out))


def main():
    ap = argparse.ArgumentParser(description="Xbox controller patch for Ittle Dew 2+ (Linux).")
    ap.add_argument("game_dir", nargs="?", default=os.path.dirname(os.path.abspath(__file__)))
    ap.add_argument("--restore", action="store_true", help="put the original files back")
    ap.add_argument("--force", action="store_true", help="patch even if an original file's checksum differs")
    ap.add_argument("--make-patch", metavar="OUT", nargs="?", const="xbox_controller.patch",
                    help="don't touch the game; write a git binary patch to OUT "
                         "(default: xbox_controller.patch)")
    args = ap.parse_args()

    data_dir = os.path.join(args.game_dir, "ID2_Data")
    jobs = (("resources.assets", patch_resources), ("globalgamemanagers", patch_globalgamemanagers))
    for name, _ in jobs:
        if not os.path.isfile(os.path.join(data_dir, name)):
            die("not found: " + os.path.join(data_dir, name))

    if args.restore:
        for name, _ in jobs:
            target = os.path.join(data_dir, name)
            if os.path.isfile(target + ".orig"):
                shutil.copy2(target + ".orig", target)
                print("restored original " + target)
        return

    try:
        import UnityPy  # noqa: F401
    except ImportError:
        die("UnityPy is required: python3 -m pip install UnityPy")

    if args.make_patch:
        make_patch(data_dir, jobs, os.path.abspath(args.make_patch), args.force)
        return

    for name, _ in jobs:
        target = os.path.join(data_dir, name)
        backup = target + ".orig"
        if not os.path.isfile(backup):
            shutil.copy2(target, backup)
            print("backed up original to " + backup)
        if sha256(backup) != ORIG_SHA256[name] and not args.force:
            die(backup + " does not match the known Ittle Dew 2+ Linux build.\n"
                "If you are sure it is the unpatched original, re-run with --force.")

    for name, patcher in jobs:
        target = os.path.join(data_dir, name)
        apply(target + ".orig", target, patcher)
        print("patched " + target)


if __name__ == "__main__":
    main()
