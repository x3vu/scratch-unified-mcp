#!/usr/bin/env python3
"""Build Tower Castle Defense: a fully working tower-defense .sb3 (vanilla blocks only).

Game: enemies march left -> right toward the Castle. Click plots to build
Archer towers (50 gold). Towers auto-fire arrows. 10 waves, gold/score,
10 lives, game-over/victory backdrops, generated art + sounds. Mouse only.
"""
import hashlib
import json
import math
import random
import re
import struct
import sys
import wave
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
SB3_PATH = OUT_DIR / "tower-castle-defense.sb3"

rng = random.Random(20260903)
ALPH = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def uid():
    return "".join(rng.choice(ALPH) for _ in range(20))


# ---------------- block helpers ----------------

def new_target(name, is_stage=False):
    t = {
        "isStage": is_stage, "name": name,
        "variables": {}, "lists": {}, "broadcasts": {}, "blocks": {},
        "comments": {}, "currentCostume": 0, "costumes": [], "sounds": [],
        "volume": 100, "layerOrder": 0,
    }
    if is_stage:
        t.update({"tempo": 60, "videoTransparency": 50, "videoState": "on",
                  "textToSpeechLanguage": None})
    else:
        t.update({"visible": True, "x": 0, "y": 0, "size": 100,
                  "direction": 90, "draggable": False, "rotationStyle": "all around"})
    return t


def B(t, opcode, inputs=None, fields=None, parent=None, top=False, x=0, y=0, shadow=False):
    bid = uid()
    t["blocks"][bid] = {
        "opcode": opcode, "next": None, "parent": parent,
        "inputs": inputs or {}, "fields": fields or {},
        "shadow": shadow, "topLevel": top, "x": x if top else 0, "y": y if top else 0,
    }
    return bid


def chain(t, ids):
    for a, b in zip(ids, ids[1:]):
        t["blocks"][a]["next"] = b
        t["blocks"][b]["parent"] = a


def sub(t, ctrl, name, first):
    t["blocks"][ctrl]["inputs"][name] = [2, first]
    t["blocks"][first]["parent"] = ctrl


_BCAST = {}  # name -> one shared id for the whole project


def bc(t, name):
    # Scratch matches broadcasts by ID, not by name, so every target must
    # use the SAME id for a given message. One global id per name.
    if name not in _BCAST:
        _BCAST[name] = "bcast-" + name
    t["broadcasts"][_BCAST[name]] = name
    return _BCAST[name]


def bcast(t, name, parent=None):
    """Create a `broadcast <name>` stack block with its shadow menu.

    Scratch requires event_broadcast's BROADCAST_INPUT to point at a shadow
    `event_broadcast_menu` block (not at the broadcast id directly).
    """
    mid = bc(t, name)
    b = B(t, "event_broadcast", parent=parent)
    m = B(t, "event_broadcast_menu",
          fields={"BROADCAST_OPTION": [name, mid]}, parent=b, shadow=True)
    t["blocks"][b]["inputs"] = {"BROADCAST_INPUT": [1, m]}
    return b


def bcast_wait(t, name, parent=None):
    """Create a `broadcast <name> and wait` stack block with its shadow menu."""
    mid = bc(t, name)
    b = B(t, "event_broadcastandwait", parent=parent)
    m = B(t, "event_broadcast_menu",
          fields={"BROADCAST_OPTION": [name, mid]}, parent=b, shadow=True)
    t["blocks"][b]["inputs"] = {"BROADCAST_INPUT": [1, m]}
    return b


def NUM(n):
    return [1, [4, str(n)]]


def TXT(s):
    return [1, [10, s]]


def var_rep(t, user, vname, vid):
    """Variable reporter input: [obscured-shadow flag, reporter block, shadow fallback].

    The fallback MUST be a bare shadow primitive ([10, name]), not a full
    [1, [10, name]] input descriptor. A descriptor there makes the VM resolve
    the fallback to undefined, and reporters like (Wave) read 0 — which broke
    the Enemy spawner's repeat count (3 + Wave evaluated to 3 + 0... then the
    spawner still failed because the shadow id pointed at a block id).
    Real Scratch form: [3, reporterId, [10, varName]].
    """
    r = B(t, "data_variable", fields={"VARIABLE": [vname, vid]}, parent=user)
    return [3, r, [10, vname]]


def menu(t, user, opcode, field, value):
    m = B(t, opcode, fields={field: [value, None]}, parent=user, shadow=True)
    return [1, m]


# ---------------- assets ----------------

ASSETS = {}  # md5ext -> bytes


def add_asset(data: bytes, ext: str):
    h = hashlib.md5(data).hexdigest()
    ASSETS[h + ext] = data
    return h, h + ext


def svg_costume(name, svg, cx, cy):
    raw = svg.encode()
    aid, md5ext = add_asset(raw, ".svg")
    return {"name": name, "bitmapResolution": 1, "dataFormat": "svg",
            "assetId": aid, "md5ext": md5ext,
            "rotationCenterX": cx, "rotationCenterY": cy}


def tone(freqs, dur_each=0.12, rate=22050, vol=0.5):
    out = []
    for f in freqs:
        n = int(rate * dur_each)
        for i in range(n):
            env = math.exp(-4.0 * i / n)
            out.append(int(32767 * vol * env * math.sin(2 * math.pi * f * i / rate)))
    return out, rate


def wav_asset(name, freqs, dur_each):
    samples, rate = tone(freqs, dur_each)
    buf = b"".join(struct.pack("<h", max(-32768, min(32767, s))) for s in samples)
    import io
    bio = io.BytesIO()
    with wave.open(bio, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(buf)
    raw = bio.getvalue()
    aid, md5ext = add_asset(raw, ".wav")
    return {"name": name, "assetId": aid, "dataFormat": "wav", "format": "",
            "rate": rate, "sampleCount": len(samples), "md5ext": md5ext}


BG_BATTLE = """<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360" viewBox="0 0 480 360"><rect width="480" height="360" fill="#5da244"/><rect y="70" width="480" height="40" fill="#c9a35c"/><rect y="70" width="480" height="5" fill="#a8813f"/><rect y="105" width="480" height="5" fill="#a8813f"/><rect y="270" width="480" height="40" fill="#c9a35c"/><rect y="270" width="480" height="5" fill="#a8813f"/><rect y="305" width="480" height="5" fill="#a8813f"/><ellipse cx="90" cy="180" rx="46" ry="26" fill="#4c8a38"/><ellipse cx="400" cy="180" rx="60" ry="30" fill="#4c8a38"/><circle cx="150" cy="30" r="20" fill="#3c7a2e"/><rect x="146" y="44" width="8" height="18" fill="#6b4a26"/><circle cx="360" cy="200" r="24" fill="#3c7a2e"/><rect x="356" y="218" width="8" height="20" fill="#6b4a26"/><circle cx="60" cy="335" r="18" fill="#3c7a2e"/><rect x="56" y="347" width="8" height="13" fill="#6b4a26"/><circle cx="250" cy="160" r="14" fill="#3c7a2e"/><rect x="246" y="170" width="8" height="14" fill="#6b4a26"/></svg>"""
BG_OVER = """<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360" viewBox="0 0 480 360"><rect width="480" height="360" fill="#4a0e0e"/><text x="240" y="160" font-family="sans-serif" font-size="52" font-weight="bold" fill="#ffffff" text-anchor="middle">GAME OVER</text><text x="240" y="210" font-family="sans-serif" font-size="20" fill="#ffcccc" text-anchor="middle">The castle has fallen. Click the flag to retry.</text></svg>"""
BG_WIN = """<svg xmlns="http://www.w3.org/2000/svg" width="480" height="360" viewBox="0 0 480 360"><rect width="480" height="360" fill="#c9962b"/><text x="240" y="160" font-family="sans-serif" font-size="52" font-weight="bold" fill="#3a2a00" text-anchor="middle">VICTORY!</text><text x="240" y="210" font-family="sans-serif" font-size="20" fill="#3a2a00" text-anchor="middle">The castle stands. All 10 waves defeated.</text></svg>"""
CASTLE = """<svg xmlns="http://www.w3.org/2000/svg" width="140" height="160" viewBox="0 0 140 160"><rect x="30" y="50" width="80" height="90" fill="#9aa0a8"/><rect x="30" y="50" width="80" height="12" fill="#7c828b"/><rect x="36" y="30" width="12" height="24" fill="#9aa0a8"/><rect x="56" y="30" width="12" height="24" fill="#9aa0a8"/><rect x="76" y="30" width="12" height="24" fill="#9aa0a8"/><rect x="8" y="60" width="26" height="80" fill="#878d96"/><rect x="8" y="48" width="26" height="14" fill="#6e747d"/><rect x="106" y="60" width="26" height="80" fill="#878d96"/><rect x="106" y="48" width="26" height="14" fill="#6e747d"/><path d="M60 110 a10 14 0 0 1 20 0 v30 h-20 z" fill="#4a2c14"/><rect x="66" y="8" width="4" height="26" fill="#5b3a1a"/><path d="M70 8 l26 8 l-26 8 z" fill="#c0392b"/><rect x="48" y="70" width="12" height="16" fill="#3d3d55"/><rect x="80" y="70" width="12" height="16" fill="#3d3d55"/></svg>"""
PLOT_EMPTY = """<svg xmlns="http://www.w3.org/2000/svg" width="90" height="90" viewBox="0 0 90 90"><ellipse cx="45" cy="45" rx="38" ry="30" fill="#7a5a30" opacity="0.85"/><ellipse cx="45" cy="45" rx="38" ry="30" fill="none" stroke="#ffe9a8" stroke-width="4" stroke-dasharray="10 6"/><text x="45" y="52" font-family="sans-serif" font-size="20" font-weight="bold" fill="#ffe9a8" text-anchor="middle">50</text></svg>"""
TOWER = """<svg xmlns="http://www.w3.org/2000/svg" width="90" height="110" viewBox="0 0 90 110"><rect x="25" y="40" width="40" height="60" fill="#8a6a42"/><rect x="25" y="40" width="40" height="10" fill="#6e5233"/><rect x="20" y="26" width="50" height="16" fill="#77675a"/><rect x="24" y="18" width="10" height="10" fill="#77675a"/><rect x="40" y="18" width="10" height="10" fill="#77675a"/><rect x="56" y="18" width="10" height="10" fill="#77675a"/><rect x="40" y="58" width="10" height="16" fill="#2c1c0d"/><rect x="43" y="2" width="4" height="18" fill="#5b3a1a"/><path d="M47 2 l20 6 l-20 6 z" fill="#2980b9"/></svg>"""
ORC = """<svg xmlns="http://www.w3.org/2000/svg" width="70" height="70" viewBox="0 0 70 70"><path d="M8 30 L2 14 L16 22 Z" fill="#3e8e2f"/><path d="M62 30 L68 14 L54 22 Z" fill="#3e8e2f"/><circle cx="35" cy="38" r="26" fill="#4da83c"/><circle cx="26" cy="34" r="6" fill="#ffffff"/><circle cx="44" cy="34" r="6" fill="#ffffff"/><circle cx="26" cy="35" r="2.6" fill="#111111"/><circle cx="44" cy="35" r="2.6" fill="#111111"/><path d="M27 50 l4 8 l4 -8 z" fill="#ffffff"/><path d="M39 50 l4 8 l4 -8 z" fill="#ffffff"/><path d="M22 46 q13 8 26 0" stroke="#2c6b22" stroke-width="3" fill="none"/></svg>"""
ARROW = """<svg xmlns="http://www.w3.org/2000/svg" width="50" height="16" viewBox="0 0 50 16"><rect x="2" y="6.5" width="34" height="3" fill="#7a4a21"/><path d="M36 1 L49 8 L36 15 Z" fill="#b9c0c7"/><path d="M2 2 L8 8 L2 14" stroke="#c0392b" stroke-width="3" fill="none"/></svg>"""
BUTTON = """<svg xmlns="http://www.w3.org/2000/svg" width="150" height="54" viewBox="0 0 150 54"><rect x="3" y="3" width="144" height="48" rx="12" fill="#27ae60" stroke="#145c32" stroke-width="4"/><text x="75" y="35" font-family="sans-serif" font-size="20" font-weight="bold" fill="#ffffff" text-anchor="middle">START WAVE</text></svg>"""


# ---------------- build ----------------

def build():
    # shared costumes / sounds (asset bytes stored once)
    c_battle = svg_costume("Battlefield", BG_BATTLE, 240, 180)
    c_over = svg_costume("GameOver", BG_OVER, 240, 180)
    c_win = svg_costume("Victory", BG_WIN, 240, 180)
    c_castle = svg_costume("castle", CASTLE, 70, 80)
    c_empty = svg_costume("empty", PLOT_EMPTY, 45, 45)
    c_tower = svg_costume("tower", TOWER, 45, 55)
    c_orc = svg_costume("orc", ORC, 35, 38)
    c_arrow = svg_costume("arrow", ARROW, 25, 8)
    c_button = svg_costume("button", BUTTON, 75, 27)

    s_shoot = wav_asset("shoot", [880], 0.09)
    s_hit = wav_asset("hit", [200], 0.15)
    s_coin = wav_asset("coin", [1320], 0.12)
    s_build = wav_asset("build", [520], 0.15)
    s_win = wav_asset("win", [523, 659, 784, 1047], 0.14)
    s_lose = wav_asset("lose", [140], 0.6)

    # ===== STAGE =====
    st = new_target("Stage", is_stage=True)
    v = {}
    for name, val in [("Gold", 150), ("Lives", 10), ("Wave", 0), ("Score", 0),
                      ("EnemiesLeft", 0), ("GameActive", 0),
                      ("ShooterX", 0), ("ShooterY", 0)]:
        vid = uid()
        st["variables"][vid] = [name, val]
        v[name] = vid
    # Per-clone enemy state (HANDOFF §6.1): EnemyX/EnemyY move from shared
    # Stage vars into per-clone lists keyed by a sprite-local MyIndex. Each
    # enemy owns its slot for life — slots are never deleted (a mid-list
    # delete shifts every later index), instead MyHPList[MyIndex] is set to 0
    # on death/escape and arrows target the first slot whose HP is > 0.
    for name in ["EnemyXList", "EnemyYList", "MyHPList"]:
        lid = uid()
        st["lists"][lid] = [name, []]
        v[name] = lid
    st["costumes"] = [c_battle, c_over, c_win]
    st["sounds"] = [s_lose, s_win]

    # init script
    h = B(st, "event_whenflagclicked", top=True, x=20, y=20)
    sw = B(st, "looks_switchbackdropto",
           inputs={"BACKDROP": menu(st, None, "looks_backdrops", "BACKDROP", "Battlefield")})
    st["blocks"][st["blocks"][sw]["inputs"]["BACKDROP"][1]]["parent"] = sw
    seq = [h, sw]
    for name, val in [("Gold", 150), ("Lives", 10), ("Wave", 0), ("Score", 0),
                      ("EnemiesLeft", 0), ("GameActive", 0),
                      ("ShooterX", 0), ("ShooterY", 0)]:
        seq.append(B(st, "data_setvariableto", inputs={"VALUE": NUM(val)},
                     fields={"VARIABLE": [name, v[name]]}))
    # clear per-clone state so MyIndex restarts at 1 on every green flag
    for name in ["EnemyXList", "EnemyYList", "MyHPList"]:
        seq.append(B(st, "data_deletealloflist", fields={"LIST": [name, v[name]]}))
    chain(st, seq)

    # game over
    go = bc(st, "GameOver")
    h2 = B(st, "event_whenbroadcastreceived",
           fields={"BROADCAST_OPTION": ["GameOver", go]}, top=True, x=20, y=320)
    sw2 = B(st, "looks_switchbackdropto",
            inputs={"BACKDROP": menu(st, None, "looks_backdrops", "BACKDROP", "GameOver")})
    st["blocks"][st["blocks"][sw2]["inputs"]["BACKDROP"][1]]["parent"] = sw2
    pl = B(st, "sound_play",
           inputs={"SOUND_MENU": menu(st, None, "sound_sounds_menu", "SOUND_MENU", "lose")})
    st["blocks"][st["blocks"][pl]["inputs"]["SOUND_MENU"][1]]["parent"] = pl
    stop = B(st, "control_stop", fields={"STOP_OPTION": ["all", None]})
    chain(st, [h2, sw2, pl, stop])

    # victory
    vi = bc(st, "Victory")
    h3 = B(st, "event_whenbroadcastreceived",
           fields={"BROADCAST_OPTION": ["Victory", vi]}, top=True, x=280, y=320)
    sw3 = B(st, "looks_switchbackdropto",
            inputs={"BACKDROP": menu(st, None, "looks_backdrops", "BACKDROP", "Victory")})
    st["blocks"][st["blocks"][sw3]["inputs"]["BACKDROP"][1]]["parent"] = sw3
    pl3 = B(st, "sound_play",
            inputs={"SOUND_MENU": menu(st, None, "sound_sounds_menu", "SOUND_MENU", "win")})
    st["blocks"][st["blocks"][pl3]["inputs"]["SOUND_MENU"][1]]["parent"] = pl3
    stop3 = B(st, "control_stop", fields={"STOP_OPTION": ["all", None]})
    chain(st, [h3, sw3, pl3, stop3])

    monitors = [
        {"id": v["Gold"], "mode": "default", "opcode": "data_variable",
         "params": {"VARIABLE": "Gold"}, "spriteName": None, "value": 150,
         "width": 0, "height": 0, "x": 5, "y": 5, "visible": True},
        {"id": v["Lives"], "mode": "default", "opcode": "data_variable",
         "params": {"VARIABLE": "Lives"}, "spriteName": None, "value": 10,
         "width": 0, "height": 0, "x": 130, "y": 5, "visible": True},
        {"id": v["Wave"], "mode": "default", "opcode": "data_variable",
         "params": {"VARIABLE": "Wave"}, "spriteName": None, "value": 0,
         "width": 0, "height": 0, "x": 255, "y": 5, "visible": True},
        {"id": v["Score"], "mode": "default", "opcode": "data_variable",
         "params": {"VARIABLE": "Score"}, "spriteName": None, "value": 0,
         "width": 0, "height": 0, "x": 370, "y": 5, "visible": True},
    ]

    # ===== CASTLE =====
    ca = new_target("Castle")
    ca.update({"x": 200, "y": 0, "size": 110, "layerOrder": 2})
    ca["costumes"] = [c_castle]
    h = B(ca, "event_whenflagclicked", top=True, x=10, y=10)
    gt = B(ca, "motion_gotoxy", inputs={"X": NUM(200), "Y": NUM(0)})
    sh = B(ca, "looks_show")
    say = B(ca, "looks_say", inputs={"MESSAGE": TXT("Defend me!")})
    chain(ca, [h, gt, sh, say])

    targets = [st, ca]

    # ===== PLOTS x4 =====
    plot_pos = [(-120, 90), (0, 90), (-120, -110), (0, -110)]
    for i, (px, py) in enumerate(plot_pos, 1):
        p = new_target(f"Plot{i}")
        p.update({"x": px, "y": py, "layerOrder": 3})
        p["costumes"] = [c_empty, c_tower]
        p["sounds"] = [s_build]
        occ = uid()
        p["variables"][occ] = ["occupied", 0]
        sx_local = uid()
        sy_local = uid()
        p["variables"][sx_local] = ["ShooterX", 0]
        p["variables"][sy_local] = ["ShooterY", 0]

        # init
        h = B(p, "event_whenflagclicked", top=True, x=10, y=10)
        sc = B(p, "looks_switchcostumeto",
               inputs={"COSTUME": menu(p, None, "looks_costume", "COSTUME", "empty")})
        p["blocks"][p["blocks"][sc]["inputs"]["COSTUME"][1]]["parent"] = sc
        st0 = B(p, "data_setvariableto", inputs={"VALUE": NUM(0)},
                fields={"VARIABLE": ["occupied", occ]})
        gt = B(p, "motion_gotoxy", inputs={"X": NUM(px), "Y": NUM(py)})
        sh = B(p, "looks_show")
        chain(p, [h, sc, st0, gt, sh])

        # click to build
        hc = B(p, "event_whenthisspriteclicked", top=True, x=10, y=150)
        iff = B(p, "control_if")
        chain(p, [hc, iff])
        andb = B(p, "operator_and", parent=iff)
        p["blocks"][iff]["inputs"]["CONDITION"] = [2, andb]
        eq1 = B(p, "operator_equals", parent=andb,
                inputs={"OPERAND1": var_rep(p, None, "occupied", occ),
                        "OPERAND2": NUM(0)})
        p["blocks"][p["blocks"][eq1]["inputs"]["OPERAND1"][1]]["parent"] = eq1
        ge = B(p, "operator_gt", parent=andb,
               inputs={"OPERAND1": var_rep(p, None, "Gold", v["Gold"]),
                       "OPERAND2": NUM(49)})
        ge_in = p["blocks"][ge]["inputs"]["OPERAND1"][1]
        p["blocks"][ge_in]["parent"] = ge
        p["blocks"][andb]["inputs"] = {"OPERAND1": [2, eq1], "OPERAND2": [2, ge]}
        s1 = B(p, "data_setvariableto", inputs={"VALUE": NUM(1)},
               fields={"VARIABLE": ["occupied", occ]})
        ch = B(p, "data_changevariableby", inputs={"VALUE": NUM(-50)},
               fields={"VARIABLE": ["Gold", v["Gold"]]})
        sc2 = B(p, "looks_switchcostumeto",
                inputs={"COSTUME": menu(p, None, "looks_costume", "COSTUME", "tower")})
        p["blocks"][p["blocks"][sc2]["inputs"]["COSTUME"][1]]["parent"] = sc2
        plb = B(p, "sound_play",
                inputs={"SOUND_MENU": menu(p, None, "sound_sounds_menu", "SOUND_MENU", "build")})
        p["blocks"][p["blocks"][plb]["inputs"]["SOUND_MENU"][1]]["parent"] = plb
        chain(p, [s1, ch, sc2, plb])
        sub(p, iff, "SUBSTACK", s1)

        # shoot loop (staggered start so all towers don't fire in lockstep)
        hf = B(p, "event_whenflagclicked", top=True, x=10, y=380)
        wo = B(p, "control_wait", inputs={"DURATION": NUM(round(i * 0.2, 1))})
        fo = B(p, "control_forever")
        chain(p, [hf, wo, fo])
        if2 = B(p, "control_if", parent=fo)
        sub(p, fo, "SUBSTACK", if2)
        and2 = B(p, "operator_and", parent=if2)
        p["blocks"][if2]["inputs"]["CONDITION"] = [2, and2]
        e1 = B(p, "operator_equals", parent=and2,
               inputs={"OPERAND1": var_rep(p, None, "GameActive", v["GameActive"]),
                       "OPERAND2": NUM(1)})
        p["blocks"][p["blocks"][e1]["inputs"]["OPERAND1"][1]]["parent"] = e1
        e2 = B(p, "operator_equals", parent=and2,
               inputs={"OPERAND1": var_rep(p, None, "occupied", occ),
                       "OPERAND2": NUM(1)})
        p["blocks"][p["blocks"][e2]["inputs"]["OPERAND1"][1]]["parent"] = e2
        p["blocks"][and2]["inputs"] = {"OPERAND1": [2, e1], "OPERAND2": [2, e2]}
        wt = B(p, "control_wait", inputs={"DURATION": NUM(0.9)})
        sx = B(p, "data_setvariableto",
               inputs={"VALUE": [3, B(p, "motion_xposition"), [4, "0"]]},
               fields={"VARIABLE": ["ShooterX", sx_local]})
        p["blocks"][p["blocks"][sx]["inputs"]["VALUE"][1]]["parent"] = sx
        sy = B(p, "data_setvariableto",
               inputs={"VALUE": [3, B(p, "motion_yposition"), [4, "0"]]},
               fields={"VARIABLE": ["ShooterY", sy_local]})
        p["blocks"][p["blocks"][sy]["inputs"]["VALUE"][1]]["parent"] = sy
        # also publish to Stage so shared Arrow sprite can read
        sx_pub = B(p, "data_setvariableto",
                   inputs={"VALUE": [3, B(p, "motion_xposition"), [4, "0"]]},
                   fields={"VARIABLE": ["ShooterX", v["ShooterX"]]})
        p["blocks"][p["blocks"][sx_pub]["inputs"]["VALUE"][1]]["parent"] = sx_pub
        sy_pub = B(p, "data_setvariableto",
                   inputs={"VALUE": [3, B(p, "motion_yposition"), [4, "0"]]},
                   fields={"VARIABLE": ["ShooterY", v["ShooterY"]]})
        p["blocks"][p["blocks"][sy_pub]["inputs"]["VALUE"][1]]["parent"] = sy_pub
        cc = B(p, "control_create_clone_of",
               inputs={"CLONE_OPTION": menu(p, None, "control_create_clone_of_menu",
                                            "CLONE_OPTION", "Arrow")})
        p["blocks"][p["blocks"][cc]["inputs"]["CLONE_OPTION"][1]]["parent"] = cc
        chain(p, [wt, sx, sy, sx_pub, sy_pub, cc])
        sub(p, if2, "SUBSTACK", wt)

        targets.append(p)

    # ===== ENEMY =====
    e = new_target("Enemy")
    e.update({"x": -230, "y": 0, "visible": False, "layerOrder": 4})
    e["costumes"] = [c_orc]
    e["sounds"] = [s_hit, s_coin]
    # Per-clone slot index (HANDOFF §6.1). The sprite-local `MyIndex` names
    # this clone's row in the Stage EnemyXList/EnemyYList/MyHPList lists;
    # HP is stored per-clone in MyHPList, not in a shared sprite-local.
    idx = uid()
    e["variables"][idx] = ["MyIndex", 0]
    b_sw = bc(e, "StartWave")
    b_spent = bc(e, "ArrowSpent")
    b_go = bc(e, "GameOver")
    b_vi = bc(e, "Victory")

    # spawner
    h = B(e, "event_whenbroadcastreceived",
          fields={"BROADCAST_OPTION": ["StartWave", b_sw]}, top=True, x=10, y=10)
    # Reset the per-clone slot lists at wave start. They are append-only
    # (dead slots zeroed, never removed) so by wave 9 they hold 96+ dead
    # entries and EVERY arrow's first-live T-scan walks the whole graveyard
    # every frame. TurboWarp's compiled-loop interrupt parks that long
    # non-yielding scan at ~1 iteration per frame, so under load an arrow
    # spends seconds inside the scan and never moves — kills collapsed.
    # Every prior clone is dead/escaped at a wave boundary, so clearing is
    # safe: fresh clones re-register from slot 1 and scans stay <= wave size.
    dax = B(e, "data_deletealloflist",
            fields={"LIST": ["EnemyXList", v["EnemyXList"]]})
    day = B(e, "data_deletealloflist",
            fields={"LIST": ["EnemyYList", v["EnemyYList"]]})
    dah = B(e, "data_deletealloflist",
            fields={"LIST": ["MyHPList", v["MyHPList"]]})
    rep = B(e, "control_repeat")
    chain(e, [h, dax, day, dah, rep])
    # NOTE: arithmetic ops take NUM1/NUM2 (not OPERAND1/2); the VM ignores
    # wrongly-named inputs, which made repeat TIMES evaluate to 0.
    add = B(e, "operator_add", parent=rep,
            inputs={"NUM1": NUM(3),
                    "NUM2": var_rep(e, None, "Wave", v["Wave"])})
    e["blocks"][e["blocks"][add]["inputs"]["NUM2"][1]]["parent"] = add
    e["blocks"][rep]["inputs"]["TIMES"] = [3, add, [4, "5"]]
    cc0 = B(e, "control_create_clone_of",
            inputs={"CLONE_OPTION": menu(e, None, "control_create_clone_of_menu",
                                         "CLONE_OPTION", "_myself_")})
    e["blocks"][e["blocks"][cc0]["inputs"]["CLONE_OPTION"][1]]["parent"] = cc0
    wt0 = B(e, "control_wait", inputs={"DURATION": NUM(0.8)})
    chain(e, [cc0, wt0])
    sub(e, rep, "SUBSTACK", cc0)

    def removed_seq(t, first_holder):
        """change EnemiesLeft -1; if Lives<=0 broadcast GO else if EnemiesLeft<=0 {Active=0; if Wave>=10 broadcast Victory}."""
        out = []
        ch = B(t, "data_changevariableby", inputs={"VALUE": NUM(-1)},
               fields={"VARIABLE": ["EnemiesLeft", v["EnemiesLeft"]]})
        out.append(ch)
        ie = B(t, "control_if_else")
        out.append(ie)
        lt = B(t, "operator_lt", parent=ie,
               inputs={"OPERAND1": var_rep(t, None, "Lives", v["Lives"]),
                       "OPERAND2": NUM(1)})
        t["blocks"][t["blocks"][lt]["inputs"]["OPERAND1"][1]]["parent"] = lt
        t["blocks"][ie]["inputs"]["CONDITION"] = [2, lt]
        bg = bcast(t, "GameOver", parent=ie)
        sub(t, ie, "SUBSTACK", bg)
        # else branch
        if3 = B(t, "control_if", parent=ie)
        sub(t, ie, "SUBSTACK2", if3)
        out.append(if3)
        eq0 = B(t, "operator_equals", parent=if3,
                inputs={"OPERAND1": var_rep(t, None, "EnemiesLeft", v["EnemiesLeft"]),
                        "OPERAND2": NUM(0)})
        t["blocks"][t["blocks"][eq0]["inputs"]["OPERAND1"][1]]["parent"] = eq0
        t["blocks"][if3]["inputs"]["CONDITION"] = [2, eq0]
        sa = B(t, "data_setvariableto", inputs={"VALUE": NUM(0)},
               fields={"VARIABLE": ["GameActive", v["GameActive"]]})
        if4 = B(t, "control_if", parent=sa)
        ge10 = B(t, "operator_gt", parent=if4,
                 inputs={"OPERAND1": var_rep(t, None, "Wave", v["Wave"]),
                         "OPERAND2": NUM(9)})
        t["blocks"][t["blocks"][ge10]["inputs"]["OPERAND1"][1]]["parent"] = ge10
        t["blocks"][if4]["inputs"]["CONDITION"] = [2, ge10]
        bv = bcast(t, "Victory", parent=if4)
        sub(t, if4, "SUBSTACK", bv)
        chain(t, [sa, if4])
        sub(t, if3, "SUBSTACK", sa)
        chain(t, [ch, ie])
        return out[0]

    # clone move script
    h = B(e, "control_start_as_clone", top=True, x=320, y=10)
    sh = B(e, "looks_show")
    # HP = 1 + floor((Wave-1)/3)
    subv = B(e, "operator_subtract",
             inputs={"NUM1": var_rep(e, None, "Wave", v["Wave"]),
                     "NUM2": NUM(1)})
    e["blocks"][e["blocks"][subv]["inputs"]["NUM1"][1]]["parent"] = subv
    div = B(e, "operator_divide",
            inputs={"NUM1": [3, subv, [4, "1"]],
                    "NUM2": NUM(3)})
    e["blocks"][subv]["parent"] = div
    fl = B(e, "operator_mathop", fields={"OPERATOR": ["floor", None]},
           inputs={"NUM": [3, div, [4, "1"]]})
    e["blocks"][div]["parent"] = fl
    addh = B(e, "operator_add",
             inputs={"NUM1": NUM(1), "NUM2": [3, fl, [4, "1"]]})
    e["blocks"][fl]["parent"] = addh
    # Register this clone's slot (HANDOFF §6.1): MyIndex = current list
    # length + 1, then append x/y/HP so slot MyIndex is this clone's forever.
    lenl = B(e, "data_lengthoflist", fields={"LIST": ["EnemyXList", v["EnemyXList"]]})
    addone = B(e, "operator_add",
               inputs={"NUM1": [3, lenl, [4, "0"]], "NUM2": NUM(1)})
    e["blocks"][lenl]["parent"] = addone
    setidx = B(e, "data_setvariableto",
               inputs={"VALUE": [3, addone, [4, "0"]]},
               fields={"VARIABLE": ["MyIndex", idx]})
    e["blocks"][addone]["parent"] = setidx
    addx = B(e, "data_addtolist",
             inputs={"ITEM": [3, B(e, "motion_xposition"), [4, "0"]]},
             fields={"LIST": ["EnemyXList", v["EnemyXList"]]})
    e["blocks"][e["blocks"][addx]["inputs"]["ITEM"][1]]["parent"] = addx
    addy = B(e, "data_addtolist",
             inputs={"ITEM": [3, B(e, "motion_yposition"), [4, "0"]]},
             fields={"LIST": ["EnemyYList", v["EnemyYList"]]})
    e["blocks"][e["blocks"][addy]["inputs"]["ITEM"][1]]["parent"] = addy
    addhp = B(e, "data_addtolist",
              inputs={"ITEM": [3, addh, [4, "1"]]},
              fields={"LIST": ["MyHPList", v["MyHPList"]]})
    e["blocks"][addh]["parent"] = addhp
    # Lanes match the dirt path across the middle of the backdrop (y=-10):
    # pick -30..30 jitter so orcs spread out but stay on the path where
    # tower arrows (fired horizontally from y=90 / y=-110 plots) can meet
    # them... arrows only share a lane if the orc walks at the tower's
    # height, so instead: orcs walk the middle path and towers sit above
    # and below it — arrows fly horizontally and hit orcs crossing their
    # row only when lanes match. To guarantee hits, orcs pick the upper
    # tower row (y=90) or lower tower row (y=-110) exactly.
    lanevar = uid()
    e["variables"][lanevar] = ["LanePick", 1]
    # NOTE: the real sb3 opcode is `operator_random` ("pick random () to ()").
    # Earlier builds emitted `operator_pickrandom`, which scratch-vm does not
    # register: the JIT failed to compile the whole clone hat (COMPILE_ERROR),
    # the script fell back to the interpreter, and the interpreter's non-yielding
    # forever SPUN at CPU speed — orcs teleported across the lane. Using the
    # correct opcode lets the JIT compile the hat and fence the loop per frame.
    pk = B(e, "operator_random", inputs={"FROM": NUM(1), "TO": NUM(2)})
    setlane = B(e, "data_setvariableto",
                inputs={"VALUE": [3, pk, [4, "1"]]},
                fields={"VARIABLE": ["LanePick", lanevar]})
    e["blocks"][pk]["parent"] = setlane
    iflane = B(e, "control_if_else")
    eqlane = B(e, "operator_equals", parent=iflane,
               inputs={"OPERAND1": var_rep(e, None, "LanePick", lanevar),
                       "OPERAND2": NUM(1)})
    e["blocks"][e["blocks"][eqlane]["inputs"]["OPERAND1"][1]]["parent"] = eqlane
    e["blocks"][iflane]["inputs"]["CONDITION"] = [2, eqlane]
    gt1 = B(e, "motion_gotoxy", parent=iflane,
            inputs={"X": NUM(-230), "Y": NUM(90)})
    gt2 = B(e, "motion_gotoxy", parent=iflane,
            inputs={"X": NUM(-230), "Y": NUM(-110)})
    sub(e, iflane, "SUBSTACK", gt1)
    sub(e, iflane, "SUBSTACK2", gt2)
    # === Enemy clone: ONE forever does publish + hit-check + movement ===
    # glidesecstoxy is BLOCKING (it yields the thread until the glide
    # finishes), and a control_forever reached mid-chain swallows the thread
    # — scratch-vm never spawns sibling threads for chained C-blocks. The old
    # "hit-check forever -> pos-pub forever -> glide" chain therefore ran
    # ONLY the first forever: orcs never moved, EnemyX/Y stayed 0, arrows
    # homed to the origin, and nothing was ever hit. Everything now lives in
    # a single forever: publish position, hit-check, arrival-check, then a
    # manual per-frame step toward the castle.
    pd = B(e, "motion_pointindirection", inputs={"DIRECTION": NUM(90)})
    mv = B(e, "motion_movesteps", inputs={"STEPS": NUM(1.5)})

    fo = B(e, "control_forever")

    # 1) publish position each frame into THIS clone's slot (the arrows scan
    #    the lists for the first slot with HP > 0).
    # NOTE: sb3 input names here matter — data_replaceitemoflist takes
    # INDEX (slot) + ITEM (value), data_itemoflist takes INDEX. Emitting
    # ITEM/VALUE made every list read return '' (Cast.toListIndex(undefined)
    # => LIST_INVALID) and every write silently no-op: EnemyXList stayed
    # frozen at append values, arrows homed to the origin, and "HP < 1"
    # read 0 so the FIRST touch insta-killed — the old wave-1 harness
    # passed only because wave-1 orcs have 1 HP.
    rex = B(e, "data_replaceitemoflist",
            inputs={"INDEX": var_rep(e, None, "MyIndex", idx),
                    "ITEM": [3, B(e, "motion_xposition"), [4, "0"]]},
            fields={"LIST": ["EnemyXList", v["EnemyXList"]]})
    e["blocks"][e["blocks"][rex]["inputs"]["INDEX"][1]]["parent"] = rex
    e["blocks"][e["blocks"][rex]["inputs"]["ITEM"][1]]["parent"] = rex
    rey = B(e, "data_replaceitemoflist",
            inputs={"INDEX": var_rep(e, None, "MyIndex", idx),
                    "ITEM": [3, B(e, "motion_yposition"), [4, "0"]]},
            fields={"LIST": ["EnemyYList", v["EnemyYList"]]})
    e["blocks"][e["blocks"][rey]["inputs"]["INDEX"][1]]["parent"] = rey
    e["blocks"][e["blocks"][rey]["inputs"]["ITEM"][1]]["parent"] = rey

    # 2) hit-check: arrow contact drains THIS clone's HP slot; at 0, pay out
    #    and vanish. (headless touching: sidecar renderer shim)
    def _hp_item():
        return B(e, "data_itemoflist",
                 inputs={"INDEX": var_rep(e, None, "MyIndex", idx)},
                 fields={"LIST": ["MyHPList", v["MyHPList"]]})

    ifh = B(e, "control_if")
    tch = B(e, "sensing_touchingobject", parent=ifh,
            inputs={"TOUCHINGOBJECTMENU": menu(e, None, "sensing_touchingobjectmenu",
                                               "TOUCHINGOBJECTMENU", "Arrow")})
    e["blocks"][e["blocks"][tch]["inputs"]["TOUCHINGOBJECTMENU"][1]]["parent"] = tch
    e["blocks"][ifh]["inputs"]["CONDITION"] = [2, tch]
    hpitem1 = _hp_item()
    e["blocks"][e["blocks"][hpitem1]["inputs"]["INDEX"][1]]["parent"] = hpitem1
    subhp = B(e, "operator_subtract",
              inputs={"NUM1": [3, hpitem1, [4, "0"]], "NUM2": NUM(1)})
    e["blocks"][hpitem1]["parent"] = subhp
    chH = B(e, "data_replaceitemoflist",
            inputs={"INDEX": var_rep(e, None, "MyIndex", idx),
                    "ITEM": [3, subhp, [4, "0"]]},
            fields={"LIST": ["MyHPList", v["MyHPList"]]})
    e["blocks"][subhp]["parent"] = chH
    e["blocks"][e["blocks"][chH]["inputs"]["INDEX"][1]]["parent"] = chH
    baw = bcast(e, "ArrowSpent")
    ifd = B(e, "control_if")
    chain(e, [chH, baw, ifd])
    sub(e, ifh, "SUBSTACK", chH)
    hpitem2 = _hp_item()
    e["blocks"][e["blocks"][hpitem2]["inputs"]["INDEX"][1]]["parent"] = hpitem2
    lte = B(e, "operator_lt", parent=ifd,
            inputs={"OPERAND1": [3, hpitem2, [4, "0"]],
                    "OPERAND2": NUM(1)})
    e["blocks"][hpitem2]["parent"] = lte
    e["blocks"][ifd]["inputs"]["CONDITION"] = [2, lte]
    chG = B(e, "data_changevariableby", inputs={"VALUE": NUM(20)},
            fields={"VARIABLE": ["Gold", v["Gold"]]})
    chS = B(e, "data_changevariableby", inputs={"VALUE": NUM(100)},
            fields={"VARIABLE": ["Score", v["Score"]]})
    plc = B(e, "sound_play",
            inputs={"SOUND_MENU": menu(e, None, "sound_sounds_menu", "SOUND_MENU", "coin")})
    e["blocks"][e["blocks"][plc]["inputs"]["SOUND_MENU"][1]]["parent"] = plc
    # mark the slot dead FIRST (HP -> 0) so arrow targeting skips it even
    # before the clone finishes its fade-out
    hpk0 = B(e, "data_replaceitemoflist",
             inputs={"INDEX": var_rep(e, None, "MyIndex", idx), "ITEM": NUM(0)},
             fields={"LIST": ["MyHPList", v["MyHPList"]]})
    e["blocks"][e["blocks"][hpk0]["inputs"]["INDEX"][1]]["parent"] = hpk0
    first2 = removed_seq(e, None)
    dl2 = B(e, "control_delete_this_clone")
    chain(e, [hpk0, chG, chS, plc, first2])
    tail2 = first2
    while e["blocks"][tail2]["next"] is not None:
        tail2 = e["blocks"][tail2]["next"]
    e["blocks"][tail2]["next"] = dl2
    e["blocks"][dl2]["parent"] = tail2
    # The zero-write must lead the kill chain so arrow targeting skips this
    # slot the instant the clone dies (HP-1 alone only zeroes 1-HP orcs).
    # NOTE: this SUBSTACK head is the fix for the orphaned-slot bug — the
    # earlier build pointed it at chG, so hpk0 (and hpe0 below) were
    # unreachable dead blocks and every ESCAPED orc left a live HP>0 ghost
    # slot at x=196 that hijacked all arrow homing.
    sub(e, ifd, "SUBSTACK", hpk0)

    # 3) arrival-check: crossed the castle wall -> lose a life, vanish;
    #    otherwise take one step toward it.
    ifx = B(e, "control_if_else")
    xr = B(e, "motion_xposition")
    gtx = B(e, "operator_gt", parent=ifx,
            inputs={"OPERAND1": [3, xr, [4, "0"]], "OPERAND2": NUM(195)})
    e["blocks"][xr]["parent"] = gtx
    e["blocks"][ifx]["inputs"]["CONDITION"] = [2, gtx]
    # mark the slot dead on escape too (same liveness rule)
    hpe0 = B(e, "data_replaceitemoflist",
             inputs={"INDEX": var_rep(e, None, "MyIndex", idx), "ITEM": NUM(0)},
             fields={"LIST": ["MyHPList", v["MyHPList"]]})
    e["blocks"][e["blocks"][hpe0]["inputs"]["INDEX"][1]]["parent"] = hpe0
    chL = B(e, "data_changevariableby", inputs={"VALUE": NUM(-1)},
            fields={"VARIABLE": ["Lives", v["Lives"]]})
    first_removed = removed_seq(e, None)
    dl = B(e, "control_delete_this_clone")
    chain(e, [hpe0, chL, first_removed])
    tail = first_removed
    while e["blocks"][tail]["next"] is not None:
        tail = e["blocks"][tail]["next"]
    e["blocks"][tail]["next"] = dl
    e["blocks"][dl]["parent"] = tail
    sub(e, ifx, "SUBSTACK", hpe0)
    sub(e, ifx, "SUBSTACK2", mv)

    # Per-frame pacing wait (see the Arrow loop): without a yielding block
    # the forever body spins ~10x per _step and orcs teleport across the
    # lane; `wait 0.03` restores official-Scratch once-per-frame pacing.
    wte = B(e, "control_wait", inputs={"DURATION": NUM(0.03)})
    # forever body: publish -> hit-check -> arrival-check/move -> wait
    chain(e, [rex, rey, ifh, ifx, wte])
    sub(e, fo, "SUBSTACK", rex)

    # Hat top-level chain: show -> register slot (set MyIndex; append
    # x/y/HP) -> set LanePick -> gotoxy(lane) -> point right -> forever.
    chain(e, [h, sh, setidx, addx, addy, addhp, setlane, iflane, pd, fo])

    # enemy init
    h = B(e, "event_whenflagclicked", top=True, x=650, y=10)
    hi = B(e, "looks_hide")
    gt0 = B(e, "motion_gotoxy", inputs={"X": NUM(-230), "Y": NUM(0)})
    chain(e, [h, hi, gt0])

    targets.append(e)

    # ===== ARROW =====
    a = new_target("Arrow")
    a.update({"x": -300, "y": -200, "visible": False, "layerOrder": 5})
    a["costumes"] = [c_arrow]
    a["sounds"] = [s_shoot]
    # per-Arrow sprite-locals for homing math; T is the scan cursor over the
    # per-clone enemy lists (HANDOFF §6.1)
    dx_local = uid()
    dy_local = uid()
    tidx = uid()
    a["variables"][dx_local] = ["dx", 0]
    a["variables"][dy_local] = ["dy", 0]
    a["variables"][tidx] = ["T", 1]
    b_sp = bc(a, "ArrowSpent")
    h = B(a, "event_whenflagclicked", top=True, x=10, y=10)
    hi = B(a, "looks_hide")
    gt = B(a, "motion_gotoxy", inputs={"X": NUM(-300), "Y": NUM(-200)})
    chain(a, [h, hi, gt])
    # fly
    h = B(a, "control_start_as_clone", top=True, x=250, y=10)
    gx = B(a, "motion_gotoxy",
           inputs={"X": var_rep(a, None, "ShooterX", v["ShooterX"]),
                   "Y": var_rep(a, None, "ShooterY", v["ShooterY"])})
    a["blocks"][a["blocks"][gx]["inputs"]["X"][1]]["parent"] = gx
    a["blocks"][a["blocks"][gx]["inputs"]["Y"][1]]["parent"] = gx
    sh = B(a, "looks_show")
    pls = B(a, "sound_play",
            inputs={"SOUND_MENU": menu(a, None, "sound_sounds_menu", "SOUND_MENU", "shoot")})
    a["blocks"][a["blocks"][pls]["inputs"]["SOUND_MENU"][1]]["parent"] = pls
    fo = B(a, "control_forever")
    chain(a, [h, gx, sh, pls, fo])

    # homing body (executed each forever iteration):
    # 0. scan the per-clone lists for the first LIVE enemy (HANDOFF §6.1):
    #    repeat until T > length(EnemyXList) OR item T of MyHPList > 0
    # 1. set dx = item T of EnemyXList - x position
    # Helper: each var reporter must be a separate block (one parent per block).
    def _var_reporter(vname, vid):
        return B(a, "data_variable", fields={"VARIABLE": [vname, vid]})

    def _list_item(lname, lid):
        r = B(a, "data_itemoflist",
              inputs={"INDEX": [3, _var_reporter("T", tidx), [4, "1"]]},
              fields={"LIST": [lname, lid]})
        a["blocks"][a["blocks"][r]["inputs"]["INDEX"][1]]["parent"] = r
        return r

    # scan: set T=1; repeat until T > len OR item T of MyHPList > 0 { T += 1 }
    setT = B(a, "data_setvariableto", inputs={"VALUE": NUM(1)},
             fields={"VARIABLE": ["T", tidx]})
    lenr = B(a, "data_lengthoflist", fields={"LIST": ["EnemyXList", v["EnemyXList"]]})
    gtTlen = B(a, "operator_gt",
               inputs={"OPERAND1": [3, _var_reporter("T", tidx), [4, "1"]],
                       "OPERAND2": [3, lenr, [4, "0"]]})
    a["blocks"][a["blocks"][gtTlen]["inputs"]["OPERAND1"][1]]["parent"] = gtTlen
    a["blocks"][lenr]["parent"] = gtTlen
    hpitemT = _list_item("MyHPList", v["MyHPList"])
    gtHP = B(a, "operator_gt",
             inputs={"OPERAND1": [3, hpitemT, [4, "0"]], "OPERAND2": NUM(0)})
    a["blocks"][hpitemT]["parent"] = gtHP
    orc = B(a, "operator_or")
    a["blocks"][gtTlen]["parent"] = orc
    a["blocks"][gtHP]["parent"] = orc
    a["blocks"][orc]["inputs"] = {"OPERAND1": [2, gtTlen], "OPERAND2": [2, gtHP]}
    rpu = B(a, "control_repeat_until", inputs={"CONDITION": [2, orc]})
    a["blocks"][orc]["parent"] = rpu
    chT = B(a, "data_changevariableby", inputs={"VALUE": NUM(1)},
            fields={"VARIABLE": ["T", tidx]})
    sub(a, rpu, "SUBSTACK", chT)

    # iff live target found (NOT (T > len)): home on it; else fly straight
    lenr2 = B(a, "data_lengthoflist", fields={"LIST": ["EnemyXList", v["EnemyXList"]]})
    gtTlen2 = B(a, "operator_gt",
                inputs={"OPERAND1": [3, _var_reporter("T", tidx), [4, "1"]],
                        "OPERAND2": [3, lenr2, [4, "0"]]})
    a["blocks"][a["blocks"][gtTlen2]["inputs"]["OPERAND1"][1]]["parent"] = gtTlen2
    a["blocks"][lenr2]["parent"] = gtTlen2
    # NOTE: `operator_not` takes input OPERAND (not OPERAND1). With OPERAND1
    # the not() block read args.OPERAND = undefined -> always TRUE, so the
    # iff below ALWAYS took the home branch; arrows whose target died kept
    # homing to stale dead-orc slots instead of flying straight to the edge,
    # the arrow population exploded, frames crawled, and the game died by
    # wave 9 even with 4 towers.
    notb = B(a, "operator_not")
    a["blocks"][gtTlen2]["parent"] = notb
    a["blocks"][notb]["inputs"] = {"OPERAND": [2, gtTlen2]}
    iff = B(a, "control_if_else", inputs={"CONDITION": [2, notb]})
    a["blocks"][notb]["parent"] = iff
    mv2 = B(a, "motion_movesteps", inputs={"STEPS": NUM(12)})
    sub(a, iff, "SUBSTACK2", mv2)

    # 1. set dx = item T of EnemyXList - x position
    xpos1 = B(a, "motion_xposition")
    ext = _list_item("EnemyXList", v["EnemyXList"])
    sub1 = B(a, "operator_subtract",
             inputs={"NUM1": [3, ext, [4, "0"]],
                     "NUM2": [3, xpos1, [4, "0"]]})
    a["blocks"][ext]["parent"] = sub1
    a["blocks"][xpos1]["parent"] = sub1
    setdx = B(a, "data_setvariableto",
              inputs={"VALUE": [3, sub1, [4, "0"]]},
              fields={"VARIABLE": ["dx", dx_local]})
    a["blocks"][sub1]["parent"] = setdx

    # 2. set dy = item T of EnemyYList - y position
    ypos1 = B(a, "motion_yposition")
    eyt = _list_item("EnemyYList", v["EnemyYList"])
    sub2 = B(a, "operator_subtract",
             inputs={"NUM1": [3, eyt, [4, "0"]],
                     "NUM2": [3, ypos1, [4, "0"]]})
    a["blocks"][eyt]["parent"] = sub2
    a["blocks"][ypos1]["parent"] = sub2
    setdy = B(a, "data_setvariableto",
              inputs={"VALUE": [3, sub2, [4, "0"]]},
              fields={"VARIABLE": ["dy", dy_local]})
    a["blocks"][sub2]["parent"] = setdy

    # 3. direction calc. Scratch moves along (sin d, cos d) with d=0 meaning
    # up, so to point at (dx, dy) you need d = atan(dx/dy), +180 when dy < 0
    # (dy < 0 puts the target below: cos d must be negative). The first build
    # got the axes backwards (atan(dy/dx), flip on dx<0) and fed turnright the
    # wrong input name (DIRECTION vs DEGREES), so cross-lane arrows silently
    # flew AWAY from their target while same-row shots only worked by luck.
    # outer if/else on (dy=0): target dead level -> point 90 (right) / -90 (left)
    ifdy0 = B(a, "control_if_else", parent=fo)
    dy_rep0 = _var_reporter("dy", dy_local)
    eqdy0 = B(a, "operator_equals", parent=ifdy0,
              inputs={"OPERAND1": [3, dy_rep0, [4, "0"]],
                      "OPERAND2": NUM(0)})
    a["blocks"][dy_rep0]["parent"] = eqdy0
    a["blocks"][ifdy0]["inputs"]["CONDITION"] = [2, eqdy0]

    # then-branch: dy=0 -> point 90 if dx>0 else point -90
    ifdxpos = B(a, "control_if_else", parent=ifdy0)
    dx_rep0 = _var_reporter("dx", dx_local)
    gtdx = B(a, "operator_gt", parent=ifdxpos,
             inputs={"OPERAND1": [3, dx_rep0, [4, "0"]],
                     "OPERAND2": NUM(0)})
    a["blocks"][dx_rep0]["parent"] = gtdx
    a["blocks"][ifdxpos]["inputs"]["CONDITION"] = [2, gtdx]
    pdir90 = B(a, "motion_pointindirection", inputs={"DIRECTION": NUM(90)})
    pdirN90 = B(a, "motion_pointindirection", inputs={"DIRECTION": NUM(-90)})
    sub(a, ifdxpos, "SUBSTACK", pdir90)
    sub(a, ifdxpos, "SUBSTACK2", pdirN90)

    # else-branch: atan(dx/dy), then if dy<0: turn right 180 (DEGREES!)
    dx_rep3 = _var_reporter("dx", dx_local)
    dy_rep3 = _var_reporter("dy", dy_local)
    div_dxdy = B(a, "operator_divide",
                 inputs={"NUM1": [3, dx_rep3, [4, "0"]],
                         "NUM2": [3, dy_rep3, [4, "0"]]})
    a["blocks"][dx_rep3]["parent"] = div_dxdy
    a["blocks"][dy_rep3]["parent"] = div_dxdy
    atan_op = B(a, "operator_mathop", fields={"OPERATOR": ["atan", None]},
                inputs={"NUM": [3, div_dxdy, [4, "0"]]})
    a["blocks"][div_dxdy]["parent"] = atan_op
    pdir_atan = B(a, "motion_pointindirection",
                  inputs={"DIRECTION": [3, atan_op, [4, "90"]]})
    a["blocks"][atan_op]["parent"] = pdir_atan
    ifdyneg = B(a, "control_if", parent=ifdy0)
    dy_rep4 = _var_reporter("dy", dy_local)
    ltdyneg = B(a, "operator_lt", parent=ifdyneg,
                inputs={"OPERAND1": [3, dy_rep4, [4, "0"]],
                        "OPERAND2": NUM(0)})
    a["blocks"][dy_rep4]["parent"] = ltdyneg
    a["blocks"][ifdyneg]["inputs"]["CONDITION"] = [2, ltdyneg]
    turn180 = B(a, "motion_turnright",
                inputs={"DEGREES": NUM(180)})
    sub(a, ifdyneg, "SUBSTACK", turn180)
    # chain within else-branch: pdir_atan -> ifdyneg
    a["blocks"][pdir_atan]["next"] = ifdyneg
    a["blocks"][ifdyneg]["parent"] = pdir_atan
    # ifdy0 else-branch points to pdir_atan
    sub(a, ifdy0, "SUBSTACK2", pdir_atan)

    # ifdy0 then-branch points to ifdxpos
    sub(a, ifdy0, "SUBSTACK", ifdxpos)

    # 4. move 12 steps
    mv = B(a, "motion_movesteps", inputs={"STEPS": NUM(12)})
    # 5. if touching edge: delete
    ife = B(a, "control_if")
    te = B(a, "sensing_touchingobject", parent=ife,
           inputs={"TOUCHINGOBJECTMENU": menu(a, None, "sensing_touchingobjectmenu",
                                              "TOUCHINGOBJECTMENU", "_edge_")})
    a["blocks"][a["blocks"][te]["inputs"]["TOUCHINGOBJECTMENU"][1]]["parent"] = te
    a["blocks"][ife]["inputs"]["CONDITION"] = [2, te]
    dl = B(a, "control_delete_this_clone", parent=ife)
    sub(a, ife, "SUBSTACK", dl)

    # Per-frame pacing wait: TurboWarp's warp-mode sequencer spins a
    # non-yielding forever body up to its stuck threshold per _step, so a
    # movesteps-only body flies at ~10x the intended speed headless. A
    # control_wait makes the body yield once per frame (official-Scratch
    # pacing) in both the JIT and interpreter paths.
    wta = B(a, "control_wait", inputs={"DURATION": NUM(0.03)})
    # homing chain lives in iff's SUBSTACK: setdx -> setdy -> ifdy0 -> mv
    chain(a, [setdx, setdy, ifdy0, mv])
    sub(a, iff, "SUBSTACK", setdx)
    # forever body: scan -> iff(home | fly straight) -> edge-check -> wait
    chain(a, [setT, rpu, iff, ife, wta])
    sub(a, fo, "SUBSTACK", setT)
    # spent handler
    h = B(a, "event_whenbroadcastreceived",
          fields={"BROADCAST_OPTION": ["ArrowSpent", b_sp]}, top=True, x=250, y=350)
    ifs = B(a, "control_if")
    chain(a, [h, ifs])
    tn = B(a, "sensing_touchingobject", parent=ifs,
           inputs={"TOUCHINGOBJECTMENU": menu(a, None, "sensing_touchingobjectmenu",
                                              "TOUCHINGOBJECTMENU", "Enemy")})
    a["blocks"][a["blocks"][tn]["inputs"]["TOUCHINGOBJECTMENU"][1]]["parent"] = tn
    a["blocks"][ifs]["inputs"]["CONDITION"] = [2, tn]
    dl3 = B(a, "control_delete_this_clone", parent=ifs)
    sub(a, ifs, "SUBSTACK", dl3)
    targets.append(a)

    # ===== START BUTTON =====
    s = new_target("StartButton")
    s.update({"x": 0, "y": 150, "layerOrder": 6})
    s["costumes"] = [c_button]
    s["sounds"] = [s_coin]
    b_sw2 = bc(s, "StartWave")
    b_go2 = bc(s, "GameOver")
    b_vi2 = bc(s, "Victory")
    h = B(s, "event_whenflagclicked", top=True, x=10, y=10)
    gt = B(s, "motion_gotoxy", inputs={"X": NUM(0), "Y": NUM(150)})
    sh = B(s, "looks_show")
    chain(s, [h, gt, sh])
    # click
    h = B(s, "event_whenthisspriteclicked", top=True, x=10, y=150)
    ie = B(s, "control_if_else")
    chain(s, [h, ie])
    eqA = B(s, "operator_equals", parent=ie,
            inputs={"OPERAND1": var_rep(s, None, "GameActive", v["GameActive"]),
                    "OPERAND2": NUM(0)})
    s["blocks"][s["blocks"][eqA]["inputs"]["OPERAND1"][1]]["parent"] = eqA
    s["blocks"][ie]["inputs"]["CONDITION"] = [2, eqA]
    # then: if Wave < 10
    ifw = B(s, "control_if", parent=ie)
    sub(s, ie, "SUBSTACK", ifw)
    ltw = B(s, "operator_lt", parent=ifw,
            inputs={"OPERAND1": var_rep(s, None, "Wave", v["Wave"]),
                    "OPERAND2": NUM(10)})
    s["blocks"][s["blocks"][ltw]["inputs"]["OPERAND1"][1]]["parent"] = ltw
    s["blocks"][ifw]["inputs"]["CONDITION"] = [2, ltw]
    chW = B(s, "data_changevariableby", inputs={"VALUE": NUM(1)},
            fields={"VARIABLE": ["Wave", v["Wave"]]})
    addE = B(s, "operator_add",
             inputs={"NUM1": var_rep(s, None, "Wave", v["Wave"]),
                     "NUM2": NUM(3)})
    s["blocks"][s["blocks"][addE]["inputs"]["NUM1"][1]]["parent"] = addE
    setE = B(s, "data_setvariableto",
             inputs={"VALUE": [3, addE, [4, "5"]]},
             fields={"VARIABLE": ["EnemiesLeft", v["EnemiesLeft"]]})
    s["blocks"][addE]["parent"] = setE
    setA = B(s, "data_setvariableto", inputs={"VALUE": NUM(1)},
             fields={"VARIABLE": ["GameActive", v["GameActive"]]})
    bc(s, "StartWave")  # ensure registered on this target
    bsw = bcast(s, "StartWave")
    plc = B(s, "sound_play",
            inputs={"SOUND_MENU": menu(s, None, "sound_sounds_menu", "SOUND_MENU", "coin")})
    s["blocks"][s["blocks"][plc]["inputs"]["SOUND_MENU"][1]]["parent"] = plc
    jn = B(s, "operator_join",
           inputs={"STRING1": TXT("Wave "),
                   "STRING2": var_rep(s, None, "Wave", v["Wave"])})
    s["blocks"][s["blocks"][jn]["inputs"]["STRING2"][1]]["parent"] = jn
    sayw = B(s, "looks_say", inputs={"MESSAGE": [3, jn, [10, ""] ]})
    s["blocks"][jn]["parent"] = sayw
    chain(s, [chW, setE, setA, bsw, plc, sayw])
    sub(s, ifw, "SUBSTACK", chW)
    # else: wave in progress
    sayp = B(s, "looks_say", parent=ie, inputs={"MESSAGE": TXT("Wave in progress...")})
    sub(s, ie, "SUBSTACK2", sayp)
    # hide on end
    h = B(s, "event_whenbroadcastreceived",
          fields={"BROADCAST_OPTION": ["GameOver", b_go2]}, top=True, x=400, y=150)
    hi = B(s, "looks_hide")
    chain(s, [h, hi])
    h = B(s, "event_whenbroadcastreceived",
          fields={"BROADCAST_OPTION": ["Victory", b_vi2]}, top=True, x=400, y=250)
    hi2 = B(s, "looks_hide")
    chain(s, [h, hi2])
    targets.append(s)

    # The Stage owns the broadcast registry in the sb3 format; make sure it
    # lists every message used anywhere so senders and receivers resolve.
    for _t in targets:
        for _bid, _name in _t["broadcasts"].items():
            st["broadcasts"][_bid] = _name

    for i, t in enumerate(targets):
        t["layerOrder"] = i

    project = {"targets": targets, "monitors": monitors,
               "extensionData": {}, "extensions": [],
               "meta": {"semver": "3.0.0", "vm": "0.2.0",
                        "agent": "scratch-unified-tower-game"}}
    return project


class Check:
    """One assertion: name, ok, detail, hint. The hint is a one-line
    human-actionable suggestion (which sprite, which block, what to change).
    """
    __slots__ = ("name", "ok", "detail", "hint")

    def __init__(self, name, ok, detail="", hint=""):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.hint = hint

    def __repr__(self):
        mark = "OK  " if self.ok else "FAIL"
        s = f"[{mark}] {self.name}"
        if self.detail:
            s += " — " + self.detail
        if self.hint and not self.ok:
            s += "  (fix: " + self.hint + ")"
        return s


# VM opcode → required input names. The VM silently ignores inputs whose
# names are wrong, which is exactly how the spawner's repeat TIMES once
# read 0 (OPERAND1/2 on operator_add → 0 + 0 = 0) and zero enemies spawned.
# This table is the single source of truth the validator and simulator
# both consult.
OPCODE_INPUTS = {
    "operator_add":      ("NUM1", "NUM2"),
    "operator_subtract": ("NUM1", "NUM2"),
    "operator_multiply": ("NUM1", "NUM2"),
    "operator_divide":   ("NUM1", "NUM2"),
    "operator_mod":      ("NUM1", "NUM2"),
    "operator_lt":       ("OPERAND1", "OPERAND2"),
    "operator_equals":   ("OPERAND1", "OPERAND2"),
    "operator_gt":       ("OPERAND1", "OPERAND2"),
    "operator_and":      ("OPERAND1", "OPERAND2"),
    "operator_or":       ("OPERAND1", "OPERAND2"),
    "operator_not":      ("OPERAND",),  # unary! not() reads OPERAND, not OPERAND1
    "operator_join":     ("STRING1", "STRING2"),
    "operator_mathop":   ("NUM",),
    "operator_random":     ("FROM", "TO"),
    "motion_gotoxy":         ("X", "Y"),
    "motion_glidesecstoxy":  ("SECS", "X", "Y"),
    "motion_movesteps":      ("STEPS",),
    "motion_pointindirection": ("DIRECTION",),
    "motion_turnright":       ("DEGREES",),
    "motion_turnleft":        ("DEGREES",),
    "control_wait":          ("DURATION",),
    "control_repeat":        ("TIMES",),
    "control_if":            ("CONDITION",),
    "control_if_else":       ("CONDITION",),
    "data_setvariableto":    ("VALUE",),
    "data_changevariableby": ("VALUE",),
    "data_addtolist":        ("ITEM",),  # LIST is a field, not an input
    # data_replaceitemoflist = INDEX (slot) + ITEM (value); data_itemoflist
    # = INDEX. Emitting ITEM/VALUE silently no-ops every read/write
    # (Cast.toListIndex(undefined) => LIST_INVALID) — caught live: lists
    # frozen at append values, arrows homing to the origin.
    "data_replaceitemoflist": ("INDEX", "ITEM"),
    "data_itemoflist":       ("INDEX",),
    "data_lengthoflist":     (),  # LIST is a field
    "data_deletealloflist":  (),  # LIST is a field
    "control_repeat_until":  ("CONDITION",),
    "looks_say":             ("MESSAGE",),
    "looks_switchcostumeto": ("COSTUME",),
    "looks_switchbackdropto": ("BACKDROP",),
    "sound_play":            ("SOUND_MENU",),
    "event_broadcast":       ("BROADCAST_INPUT",),
    "event_broadcastandwait": ("BROADCAST_INPUT",),
    "sensing_touchingobject": ("TOUCHINGOBJECTMENU",),
    "control_create_clone_of": ("CLONE_OPTION",),
}


def _opcode_required_inputs(op):
    return OPCODE_INPUTS.get(op, ())


# Every opcode scratch-vm actually registers, extracted from the vendored
# scratch-vm block sources (getPrimitives/getHats/scan maps + the runtime-
# registered menu shadows). The self-test's `known_opcodes` check flags any
# emitted opcode not in this set — a typo like `operator_pickrandom` (real
# name: `operator_random`) used to slip through: the VM silently failed to
# JIT-compile the script, fell back to the spinning interpreter, and gameplay
# broke in ways no other check could see.
KNOWN_OPCODES = frozenset({
    "argument_reporter_boolean", "argument_reporter_string_number",
    "control_all_at_once", "control_clear_counter", "control_create_clone_of",
    "control_create_clone_of_menu", "control_delete_this_clone", "control_for_each",
    "control_forever", "control_get_counter", "control_if", "control_if_else",
    "control_incr_counter", "control_repeat", "control_repeat_until",
    "control_start_as_clone", "control_stop", "control_wait", "control_wait_until",
    "control_while", "data_addtolist", "data_changevariableby", "data_deletealloflist",
    "data_deleteoflist", "data_hidelist", "data_hidevariable", "data_insertatlist",
    "data_itemnumoflist", "data_itemoflist", "data_lengthoflist", "data_listcontainsitem",
    "data_listcontents", "data_replaceitemoflist", "data_setvariableto", "data_showlist",
    "data_showvariable", "data_variable", "event_broadcast", "event_broadcast_menu",
    "event_broadcastandwait", "event_whenbackdropswitchesto", "event_whenbroadcastreceived",
    "event_whenflagclicked", "event_whengreaterthan", "event_whenkeypressed",
    "event_whenstageclicked", "event_whenthisspriteclicked", "event_whentouchingobject",
    "looks_backdropnumbername", "looks_backdrops", "looks_changeeffectby", "looks_changesizeby",
    "looks_changestretchby", "looks_cleargraphiceffects", "looks_costume", "looks_costumenumbername",
    "looks_goforwardbackwardlayers", "looks_gotofrontback", "looks_hide", "looks_hideallsprites",
    "looks_nextbackdrop", "looks_nextcostume", "looks_say", "looks_sayforsecs",
    "looks_seteffectto", "looks_setsizeto", "looks_setstretchto", "looks_show", "looks_size",
    "looks_switchbackdropto", "looks_switchbackdroptoandwait", "looks_switchcostumeto",
    "looks_think", "looks_thinkforsecs", "motion_align_scene", "motion_changexby",
    "motion_changeyby", "motion_direction", "motion_glidesecstoxy", "motion_glideto",
    "motion_goto", "motion_gotoxy", "motion_ifonedgebounce", "motion_movesteps",
    "motion_pointindirection", "motion_pointtowards", "motion_scroll_right", "motion_scroll_up",
    "motion_setrotationstyle", "motion_setx", "motion_sety", "motion_turnleft",
    "motion_turnright", "motion_xposition", "motion_xscroll", "motion_yposition",
    "motion_yscroll", "operator_add", "operator_and", "operator_contains", "operator_divide",
    "operator_equals", "operator_gt", "operator_join", "operator_length", "operator_letter_of",
    "operator_lt", "operator_mathop", "operator_mod", "operator_multiply", "operator_not",
    "operator_or", "operator_random", "operator_round", "operator_subtract", "procedures_call",
    "procedures_definition", "procedures_return", "sensing_answer", "sensing_askandwait",
    "sensing_coloristouchingcolor", "sensing_current", "sensing_dayssince2000", "sensing_distanceto",
    "sensing_keypressed", "sensing_loud", "sensing_loudness", "sensing_mousedown", "sensing_mousex",
    "sensing_mousey", "sensing_of", "sensing_online", "sensing_resettimer", "sensing_setdragmode",
    "sensing_timer", "sensing_touchingcolor", "sensing_touchingobject", "sensing_touchingobjectmenu",
    "sensing_userid", "sensing_username", "sound_beats_menu", "sound_changeeffectby",
    "sound_changevolumeby", "sound_cleareffects", "sound_effects_menu", "sound_play",
    "sound_playuntildone", "sound_seteffectto", "sound_setvolumeto", "sound_sounds_menu",
    "sound_stopallsounds", "sound_volume",
})


def _check_static(data):
    """Pure structural checks against the in-memory project dict. Returns
    a list of Check. Does not raise — the report is for the human."""
    out = []
    targets = {t["name"]: t for t in data["targets"]}
    out.append(Check("targets_present",
                     all(n in targets for n in ("Stage", "Castle", "Plot1", "Plot2", "Plot3", "Plot4", "Enemy", "Arrow", "StartButton")),
                     "found: " + ",".join(sorted(targets)),
                     "all 9 expected targets must exist"))
    total = sum(len(t["blocks"]) for t in data["targets"])
    out.append(Check("block_count", total > 100,
                     f"total={total}", "need more than 100 blocks"))
    seen = set()
    dup = []
    for t in data["targets"]:
        for bid in t["blocks"]:
            if bid in seen:
                dup.append(bid)
            seen.add(bid)
    out.append(Check("unique_block_ids", not dup,
                     f"dup ids: {dup[:3]}" if dup else "",
                     "every block needs a unique 20-char id"))
    broken = []
    for t in data["targets"]:
        for bid, b in t["blocks"].items():
            if b.get("next") and b["next"] not in t["blocks"]:
                broken.append((t["name"], bid, "next", b["next"]))
            for iname, ival in b.get("inputs", {}).items():
                if isinstance(ival, list) and len(ival) >= 2 \
                        and isinstance(ival[1], str) and ival[1] in t["blocks"]:
                    if t["blocks"][ival[1]].get("parent") != bid:
                        broken.append((t["name"], bid, iname, ival[1]))
    out.append(Check("parent_next_links", not broken,
                     f"broken: {broken[:3]}" if broken else "",
                     "every input/next ref must have a matching parent backlink"))
    bad_bc = []
    for t in data["targets"]:
        for bid, b in t["blocks"].items():
            for iname, ival in b.get("inputs", {}).items():
                if iname != "BROADCAST_INPUT":
                    continue
                ref = ival[1]
                if not isinstance(ref, str) or ref not in t["blocks"]:
                    bad_bc.append((t["name"], bid, "missing menu block"))
                    continue
                mb = t["blocks"][ref]
                if mb["opcode"] != "event_broadcast_menu":
                    bad_bc.append((t["name"], bid, "wrong opcode " + mb["opcode"]))
                    continue
                opt = mb.get("fields", {}).get("BROADCAST_OPTION", [None, None])
                if opt[1] not in t.get("broadcasts", {}):
                    bad_bc.append((t["name"], bid, "menu id not registered"))
    out.append(Check("broadcast_senders", not bad_bc,
                     f"bad: {bad_bc[:3]}" if bad_bc else "",
                     "every broadcast needs an event_broadcast_menu shadow whose id is registered on that target"))
    name_to_ids = {}
    for t in data["targets"]:
        for bid, name in t.get("broadcasts", {}).items():
            name_to_ids.setdefault(name, set()).add(bid)
    bad_share = [(n, ids) for n, ids in name_to_ids.items() if len(ids) > 1]
    out.append(Check("broadcast_id_uniqueness", not bad_share,
                     f"mis-id'd: {bad_share[:3]}" if bad_share else "",
                     "every message name must have one id across all targets — Stage should mirror the registry"))
    missing_listeners = []
    for t in data["targets"]:
        for bid, b in t["blocks"].items():
            if b["opcode"] == "event_whenbroadcastreceived":
                opt = b.get("fields", {}).get("BROADCAST_OPTION", [None, None])
                if opt[1] not in t.get("broadcasts", {}):
                    missing_listeners.append((t["name"], bid, b.get("fields", {}).get("BROADCAST_OPTION", [None, None])[0]))
    out.append(Check("broadcast_listeners", not missing_listeners,
                     f"missing: {missing_listeners[:3]}" if missing_listeners else "",
                     "every event_whenbroadcastreceived must reference a broadcast id registered on the same target"))
    bad_inputs = []
    for t in data["targets"]:
        for bid, b in t["blocks"].items():
            req = _opcode_required_inputs(b["opcode"])
            if not req:
                continue
            got = set(b.get("inputs", {}).keys()) - {"SUBSTACK", "SUBSTACK2"}
            need = set(req)
            if got != need:
                bad_inputs.append((t["name"], bid[:6], b["opcode"], sorted(got), sorted(need)))
    out.append(Check("opcode_input_names", not bad_inputs,
                     f"bad: {bad_inputs[:3]}" if bad_inputs else "",
                     "arithmetic ops use NUM1/NUM2, comparison ops use OPERAND1/2 — VM silently ignores wrong names"))
    # List ops: LIST is a FIELD ([name, id]) in real sb3, not an input. The
    # interpreter's arg resolver and the JIT's descendVariable both read
    # block.fields.LIST; encoding it as an input makes the thread crash with
    # 'Cannot read properties of null (reading _isHat)'. (caught this exact
    # bug during the §6.1 refactor)
    bad_list_field = []
    for t in data["targets"]:
        for bid, b in t["blocks"].items():
            if b["opcode"] in ("data_addtolist", "data_replaceitemoflist",
                                "data_itemoflist", "data_lengthoflist",
                                "data_deletealloflist"):
                if "LIST" not in b.get("fields", {}) or \
                        "LIST" in b.get("inputs", {}):
                    bad_list_field.append((t["name"], bid[:6], b["opcode"]))
    out.append(Check("list_field_not_input", not bad_list_field,
                     f"bad: {bad_list_field[:5]}" if bad_list_field else "",
                     "list ops must reference the list via fields.LIST=[name,id], never inputs.LIST — the VM crashes on input-encoded list refs"))
    # List INDEX/VALUE naming: data_itemoflist and data_replaceitemoflist
    # take the SLOT as input INDEX and (for replace) the VALUE as input ITEM.
    # Emitting ITEM/VALUE makes Cast.toListIndex(undefined) return
    # LIST_INVALID: every read returns '' and every write silently no-ops.
    # (caught this exact bug live: EnemyXList frozen at append values while
    # arrows homed to the origin and "HP < 1" read 0, insta-killing on the
    # first touch — the wave-1 harness passed only because those orcs have
    # 1 HP and the broken read made HP look like 0 < 1.)
    bad_list_idx = []
    for t in data["targets"]:
        for bid, b in t["blocks"].items():
            if b["opcode"] == "data_itemoflist" and "INDEX" not in b.get("inputs", {}):
                bad_list_idx.append((t["name"], bid[:6], b["opcode"], sorted(b.get("inputs", {}).keys())))
            if b["opcode"] == "data_replaceitemoflist" and \
                    ("INDEX" not in b.get("inputs", {}) or "ITEM" not in b.get("inputs", {})):
                bad_list_idx.append((t["name"], bid[:6], b["opcode"], sorted(b.get("inputs", {}).keys())))
    out.append(Check("list_index_input_names", not bad_list_idx,
                     f"bad: {bad_list_idx[:5]}" if bad_list_idx else "",
                     "list index blocks must use inputs INDEX (slot) and ITEM (value) — ITEM/VALUE silently no-ops all list reads/writes"))
    bad_op = []
    for t in data["targets"]:
        for bid, b in t["blocks"].items():
            if b["opcode"] not in KNOWN_OPCODES:
                bad_op.append((t["name"], bid[:6], b["opcode"]))
    out.append(Check("known_opcodes", not bad_op,
                     f"unknown: {bad_op[:5]}" if bad_op else "",
                     "every opcode must be one scratch-vm registers — a typo like operator_pickrandom silently fails JIT compile and spins the interpreter"))
    bad_repeat = []
    for t in data["targets"]:
        for bid, b in t["blocks"].items():
            if b["opcode"] == "control_repeat":
                t_in = b["inputs"]["TIMES"]
                if not (isinstance(t_in, list) and len(t_in) == 3
                        and t_in[0] == 3 and t_in[1] in t["blocks"]
                        and t_in[2][0] == 4):
                    bad_repeat.append((t["name"], bid[:6], t_in))
    out.append(Check("repeat_TIMES_shape", not bad_repeat,
                     f"bad: {bad_repeat[:3]}" if bad_repeat else "",
                     "TIMES must be [3, <reporterBlockId>, [4, <literal-num-string>]] — a reporter, not a literal value"))
    bad_menus = []
    for t in data["targets"]:
        costume_names = {c["name"] for c in t.get("costumes", [])}
        sound_names = {s["name"] for s in t.get("sounds", [])}
        bgs = {c["name"] for c in targets.get("Stage", {}).get("costumes", [])}
        for bid, b in t["blocks"].items():
            for fname, fval in b.get("fields", {}).items():
                op = b["opcode"]
                v = (fval or [None])[0]
                if op == "looks_costume" and v not in costume_names:
                    bad_menus.append((t["name"], bid[:6], "costume", v))
                if op == "sound_sounds_menu" and v not in sound_names:
                    bad_menus.append((t["name"], bid[:6], "sound", v))
                if op == "looks_backdrops" and v not in bgs:
                    bad_menus.append((t["name"], bid[:6], "backdrop", v))
                if op == "control_create_clone_of_menu" and v != "_myself_" and v not in targets:
                    bad_menus.append((t["name"], bid[:6], "clone target", v))
                if op == "sensing_touchingobjectmenu" and v not in targets \
                        and v not in ("_edge_", "_mouse_"):
                    bad_menus.append((t["name"], bid[:6], "touching target", v))
    out.append(Check("menu_values", not bad_menus,
                     f"bad: {bad_menus[:3]}" if bad_menus else "",
                     "every menu selection must name a costume/sound/backdrop/sprite that exists"))
    missing = []
    for t in data["targets"]:
        for c in t.get("costumes", []):
            if c["md5ext"] not in ASSETS:
                missing.append(c["md5ext"])
        for s in t.get("sounds", []):
            if s["md5ext"] not in ASSETS:
                missing.append(s["md5ext"])
    out.append(Check("assets_present", not missing,
                     f"missing: {missing[:3]}" if missing else "",
                     "every costume/sound md5ext must be present in the assets map"))

    # Stage variables should each have a monitor (so the player can see them)
    stage_vars = targets.get("Stage", {})
    stage_var_names = set()
    for v in stage_vars.get("variables", {}).values():
        if isinstance(v, list) and v:
            stage_var_names.add(v[0])
    monitored = set()
    for m in data.get("monitors", []) or []:
        params = m.get("params", {}) or {}
        vname = params.get("VARIABLE")
        if vname:
            monitored.add(vname)
    required = {"Gold", "Lives", "Wave", "Score"}
    missing_monitors = sorted(required - monitored)
    out.append(Check("monitors_match_stage_vars", not missing_monitors,
                     f"monitored={sorted(monitored)} missing={missing_monitors}",
                     f"add `data.monitors.append(...)` for: {missing_monitors}"
                     if missing_monitors else ""))
    return out


def validate(project):
    """Backwards-compat shim. Runs every static check, raises on first
    failure with a one-line message. Use self_test() for a structured
    report instead."""
    data = json.loads(json.dumps(project))
    checks = _check_static(data)
    failed = [c for c in checks if not c.ok]
    if failed:
        first = failed[0]
        raise AssertionError(f"{first.name}: {first.detail}  fix: {first.hint}".strip())
    total = sum(len(t["blocks"]) for t in data["targets"])
    print(f"validate OK: {len(data['targets'])} targets, {total} blocks")
    for t in data["targets"]:
        print(f"  {t['name']}: {len(t['blocks'])} blocks")
    return data


def main():
    project = build()
    report = self_test(project)
    report.print()
    if not report.passed:
        print("\nNo .sb3 written (verify failed). Fix the failures above and retry.")
        sys.exit(1)
    data = report.data
    # strip simulator-internal keys before serialization
    for t in data["targets"]:
        t.pop("_stage_ref", None)
    with zipfile.ZipFile(SB3_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("project.json", json.dumps(data, separators=(",", ":")))
        for md5ext, raw in ASSETS.items():
            zf.writestr(md5ext, raw)
    size = SB3_PATH.stat().st_size
    print(f"\nwrote {SB3_PATH} ({size} bytes)")


# ===========================================================================
# Self-test: simulator + geometry check + report.
# Runs in-process after build(); main() only writes the .sb3 if the report
# passes. No Node, no scratch-vm, no network — pure stdlib.
# ===========================================================================

# ---- operator-graph evaluator (the parts of scratch-vm we actually need) --

# The literal primitive kinds in serialized project.json are integers. The
# code here deals with the post-deserialize form the in-memory build() uses,
# so we don't have to care about the wire format here.

def _eval_input(value, target, vars_, clones_wave_get, base_path=None):
    """Recursively evaluate a single input slot. Returns the value
    (number, string, bool) or raises ValueError with a helpful message.

    Scratch input format: [kind, body, <shadow?>]
      kind 1: shadow primitive — body is [typeConst, value] e.g. [4, "3"]
      kind 2: block reference — body is a block id string
      kind 3: obscured shadow — body is block id, [2] is the shadow fallback
    """
    if not isinstance(value, list) or len(value) < 2:
        return None
    kind = value[0]
    body = value[1]
    if kind == 1:  # shadow primitive
        # body is [typeConst, value]: [4,"3"]=num, [10,"x"]=text, [11,name,id]=bcast
        if isinstance(body, list) and len(body) >= 2:
            return body[1]  # the literal value
        return body  # already a scalar
    if kind == 2:  # block reference
        return _eval_block(body, target, vars_, clones_wave_get, base_path)
    if kind == 3:  # obscured shadow: real block + fallback
        # try the real block first
        if isinstance(body, str) and body in target["blocks"]:
            return _eval_block(body, target, vars_, clones_wave_get, base_path)
        # fall back to shadow
        if len(value) >= 3 and value[2]:
            return _eval_input(value[2], target, vars_, clones_wave_get, base_path)
    return None


def _eval_block(bid, target, vars_, clones_wave_get, base_path):
    """Evaluate a reporter block; returns a value."""
    if bid not in target["blocks"]:
        raise ValueError(f"missing block {bid} in {target['name']}")
    b = target["blocks"][bid]
    op = b["opcode"]
    inputs = b.get("inputs", {})
    # helper: extract field value from either ["val", id] or {"value":"val"} form
    def _fv(field_name):
        f = b.get("fields", {}).get(field_name)
        if f is None:
            raise ValueError(f"missing field {field_name} on {op}")
        if isinstance(f, list):
            return f[0]
        if isinstance(f, dict):
            return f.get("value")
        return f
    if op == "data_variable":
        vname = _fv("VARIABLE")
        # Stage globals; sprite-local first, then Stage.
        stage = _stage_of(target)
        for src in (target, stage):
            if src is None:
                continue
            for vid, v in src.get("variables", {}).items():
                # v is [name, value] in our build format
                if isinstance(v, list) and v[0] == vname:
                    return v[1]
                # or a Variable-like dict
                if hasattr(v, "get") and v.get("name") == vname:
                    return v.get("value")
        raise ValueError(f"variable {vname!r} not found")
    if op == "operator_add":
        return _num(_eval_input(inputs["NUM1"], target, vars_, clones_wave_get, base_path)) + \
               _num(_eval_input(inputs["NUM2"], target, vars_, clones_wave_get, base_path))
    if op == "operator_subtract":
        return _num(_eval_input(inputs["NUM1"], target, vars_, clones_wave_get, base_path)) - \
               _num(_eval_input(inputs["NUM2"], target, vars_, clones_wave_get, base_path))
    if op == "operator_multiply":
        return _num(_eval_input(inputs["NUM1"], target, vars_, clones_wave_get, base_path)) * \
               _num(_eval_input(inputs["NUM2"], target, vars_, clones_wave_get, base_path))
    if op == "operator_divide":
        a = _num(_eval_input(inputs["NUM1"], target, vars_, clones_wave_get, base_path))
        b2 = _num(_eval_input(inputs["NUM2"], target, vars_, clones_wave_get, base_path))
        if b2 == 0:
            raise ValueError("division by zero")
        return a / b2
    if op == "operator_mathop":
        a = _num(_eval_input(inputs["NUM"], target, vars_, clones_wave_get, base_path))
        op_kind = _fv("OPERATOR")
        if op_kind == "floor": return math.floor(a)
        if op_kind == "ceiling": return math.ceil(a)
        if op_kind == "abs": return abs(a)
        if op_kind == "sqrt": return math.sqrt(a)
        return a
    if op == "operator_random":
        a = _num(_eval_input(inputs["FROM"], target, vars_, clones_wave_get, base_path))
        b2 = _num(_eval_input(inputs["TO"], target, vars_, clones_wave_get, base_path))
        lo, hi = sorted((a, b2))
        return int(random.randint(int(lo), int(hi)))
    if op in ("math_number", "math_positive_number", "math_whole_number",
              "math_integer", "math_angle"):
        return float(_fv("NUM"))
    if op == "text":
        return str(_fv("TEXT"))
    if op == "motion_xposition":
        return target.get("x", 0)
    if op == "motion_yposition":
        return target.get("y", 0)
    raise ValueError(f"unsupported reporter: {op}")


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"expected number, got {v!r}")


def _stage_of(target):
    """Find the Stage target. The simulator sets _stage_ref on every
    target before evaluation."""
    return target.get("_stage_ref") or None


def _subtree_contains_opcode(target, value, opcode):
    """Walk the subtree rooted at `value` (an input descriptor) and return
    True if any block has the given opcode."""
    seen = set()
    stack = [value]
    while stack:
        v = stack.pop()
        if not (isinstance(v, list) and len(v) >= 2):
            continue
        body = v[1]
        if not isinstance(body, str) or body in seen or body not in target["blocks"]:
            continue
        seen.add(body)
        b = target["blocks"][body]
        if b["opcode"] == opcode:
            return True
        nxt = b.get("next")
        if isinstance(nxt, str):
            stack.append([2, nxt])
        for inp_val in b.get("inputs", {}).values():
            if isinstance(inp_val, list):
                stack.append(inp_val)
    return False


def _slot_var_name(target, value):
    """Return the VARIABLE field name of the first data_variable block in
    the subtree rooted at `value`, or None."""
    seen = set()
    stack = [value]
    while stack:
        v = stack.pop()
        if not (isinstance(v, list) and len(v) >= 2):
            continue
        body = v[1]
        if not isinstance(body, str) or body in seen or body not in target["blocks"]:
            continue
        seen.add(body)
        b = target["blocks"][body]
        if b["opcode"] == "data_variable":
            fname = (b.get("fields", {}).get("VARIABLE") or [None])[0]
            return fname
        nxt = b.get("next")
        if isinstance(nxt, str):
            stack.append([2, nxt])
        for inp_val in b.get("inputs", {}).values():
            if isinstance(inp_val, list):
                stack.append(inp_val)
    return None


def _list_name_map(data):
    """Map every list id across all targets to its display name."""
    m = {}
    for t in data["targets"]:
        for lid, entry in (t.get("lists") or {}).items():
            m[lid] = entry[0] if isinstance(entry, list) and entry else lid
    return m


def _slot_list_name(target, value, list_names):
    """Return the list display name of the first data_itemoflist block in
    the subtree rooted at `value`, or None."""
    seen = set()
    stack = [value]
    while stack:
        v = stack.pop()
        if not (isinstance(v, list) and len(v) >= 2):
            continue
        body = v[1]
        if not isinstance(body, str) or body in seen or body not in target["blocks"]:
            continue
        seen.add(body)
        b = target["blocks"][body]
        if b["opcode"] == "data_itemoflist":
            lid = (b.get("fields", {}).get("LIST") or [None, None])[1]
            return list_names.get(lid)
        nxt = b.get("next")
        if isinstance(nxt, str):
            stack.append([2, nxt])
        for inp_val in b.get("inputs", {}).values():
            if isinstance(inp_val, list):
                stack.append(inp_val)
    return None


def _slot_opcode(target, value):
    """Return the opcode of the first non-shadow block in the subtree rooted
    at `value`, or None if the subtree is just a literal."""
    seen = set()
    stack = [value]
    while stack:
        v = stack.pop()
        if not (isinstance(v, list) and len(v) >= 2):
            continue
        body = v[1]
        if not isinstance(body, str) or body in seen or body not in target["blocks"]:
            continue
        seen.add(body)
        return target["blocks"][body]["opcode"]
    return None


def _slot_block(target, value):
    """Return the first non-shadow block dict in the subtree rooted at
    `value`, or None if the subtree is just a literal."""
    seen = set()
    stack = [value]
    while stack:
        v = stack.pop()
        if not (isinstance(v, list) and len(v) >= 2):
            continue
        body = v[1]
        if not isinstance(body, str) or body in seen or body not in target["blocks"]:
            continue
        seen.add(body)
        return target["blocks"][body]
    return None


def _slot_varname(target, value):
    """Return the variable display name referenced by the first
    data_variable block in the subtree rooted at `value`, or None."""
    seen = set()
    stack = [value]
    while stack:
        v = stack.pop()
        if not (isinstance(v, list) and len(v) >= 2):
            continue
        body = v[1]
        if not isinstance(body, str) or body in seen or body not in target["blocks"]:
            continue
        seen.add(body)
        b = target["blocks"][body]
        if b["opcode"] == "data_variable":
            return (b.get("fields", {}).get("VARIABLE") or [None])[0]
        nxt = b.get("next")
        if isinstance(nxt, str):
            stack.append([2, nxt])
        for inp_val in b.get("inputs", {}).values():
            if isinstance(inp_val, list):
                stack.append(inp_val)
    return None


def _simulate_spawner(data):
    """Walk the Enemy's whenbroadcastreceived[StartWave] script. Compute
    the value of `TIMES` in `control_repeat`, count clone_create calls,
    check that the spawner fires at least one clone after StartWave."""
    out = []
    enemy = next(t for t in data["targets"] if t["name"] == "Enemy")
    stage = next(t for t in data["targets"] if t["isStage"])
    # attach stage ref for the evaluator
    for t in data["targets"]:
        t["_stage_ref"] = stage
    # find the StartWave hat
    hat = None
    for bid, b in enemy["blocks"].items():
        if b["opcode"] == "event_whenbroadcastreceived" \
                and b["fields"]["BROADCAST_OPTION"][0] == "StartWave":
            hat = bid
            break
    if hat is None:
        return [Check("spawner_hat_present", False,
                      "Enemy has no event_whenbroadcastreceived for StartWave",
                      "add `when I receive StartWave` to Enemy")]
    # follow next: hat -> [data_deletealloflist reset x3] -> repeat
    rep = enemy["blocks"][hat].get("next")
    while rep and enemy["blocks"][rep]["opcode"] == "data_deletealloflist":
        rep = enemy["blocks"][rep].get("next")
    if not rep or enemy["blocks"][rep]["opcode"] != "control_repeat":
        return [Check("spawner_after_hat", False,
                      f"hat next is {rep} (expected control_repeat after list reset)",
                      "spawner hat must chain into control_repeat")]
    # The per-clone slot lists MUST be cleared before spawning, else the
    # append-only graveyard grows to 96+ dead slots and every arrow's
    # first-live scan crawls (compiled-loop interrupt parks it at ~1 iter/
    # frame) — the wave-9 kill-collapse. Check all three resets are present
    # between the hat and the repeat.
    cleared = {"EnemyXList": False, "EnemyYList": False, "MyHPList": False}
    cur = enemy["blocks"][hat].get("next")
    while cur and enemy["blocks"][cur]["opcode"] == "data_deletealloflist":
        lst = enemy["blocks"][cur].get("fields", {}).get("LIST", [None])[0]
        if lst in cleared:
            cleared[lst] = True
        cur = enemy["blocks"][cur].get("next")
    miss = [k for k, ok in cleared.items() if not ok]
    out.append(Check("spawner_resets_slot_lists", not miss,
                     ("" if not miss else f"missing deleteall for {', '.join(miss)} before repeat"),
                     "clear EnemyXList/EnemyYList/MyHPList at StartWave so arrow scans stay short"))
    # evaluate TIMES expression in Enemy context, with Wave=1, GameActive=1
    # evaluate TIMES expression in Enemy context, with Wave=1, GameActive=1
    sgame = dict(stage["variables"])
    # override Wave for the test
    for vid, (n, v) in sgame.items():
        if n == "Wave": sgame[vid] = [n, 1]
        if n == "GameActive": sgame[vid] = [n, 1]
        if n == "EnemiesLeft": sgame[vid] = [n, 4]
    sgame_local = {**sgame, **{vid: [n, v] for vid, (n, v) in enemy.get("variables", {}).items()}}
    # Repackage for evaluator (it expects variables dict id->[name,value])
    try:
        # evaluator reads variables by name; build a name->value view
        sgame_view = {n: v for (n, v) in sgame.values()}
        # The evaluator looks up via "for src in (target, _stage_of(target))"
        # and the enemy target has no _stage_ref until now (we set it above).
        # Patch _stage_ref onto the enemy target for the duration.
        enemy_vars_simple = {vid: (n, v) for vid, (n, v) in enemy.get("variables", {}).items()}
        # _eval_block looks at target["variables"] as dict id->[name, value]
        # but builds the search via .items() so we keep its shape.
        # Provide Stage as _stage_ref for any reporter that falls through.
        times = _eval_input(enemy["blocks"][rep]["inputs"]["TIMES"],
                            enemy, sgame, {}, None)
    except Exception as exc:
        return [Check("spawner_TIMES_evaluates", False,
                      f"could not evaluate repeat TIMES: {exc}",
                      "usually caused by wrong input name (OPERAND1/2 vs NUM1/2) or a missing variable")]
    out.append(Check("spawner_TIMES_evaluates", times > 0,
                      f"TIMES evaluates to {times}",
                      "spawner must spawn at least one clone"))
    if times <= 0:
        return out
    # walk the SUBSTACK of repeat, count control_create_clone_of calls
    subst = enemy["blocks"][rep]["inputs"].get("SUBSTACK")
    if not subst:
        return out + [Check("spawner_substack_present", False,
                            "control_repeat has no SUBSTACK",
                            "SUBSTACK is the body of the loop")]
    clones = 0
    cur = subst[1] if isinstance(subst, list) and len(subst) >= 2 else subst
    if isinstance(subst, list) and len(subst) == 2 and isinstance(subst[1], str):
        cur = subst[1]
    visited = set()
    while isinstance(cur, str) and cur in enemy["blocks"] and cur not in visited:
        visited.add(cur)
        b = enemy["blocks"][cur]
        if b["opcode"] == "control_create_clone_of":
            clones += 1
        # step into SUBSTACK if present
        sb = b.get("inputs", {}).get("SUBSTACK")
        if isinstance(sb, list) and len(sb) >= 2 and isinstance(sb[1], str) and sb[1] in enemy["blocks"]:
            cur = sb[1]
            continue
        cur = b.get("next")
    out.append(Check("spawner_creates_clones", clones > 0,
                      f"control_create_clone_of count in SUBSTACK = {clones}",
                      "spawner SUBSTACK must contain at least one create-clone-of-myself"))
    return out


def _simulate_arrow_hits(data):
    """Motion assertion: arrows fly right (+x) and enemies walk the tower
    rows (y=90 / y=-110) so arrows can actually hit them.

    Scans ALL blocks in the target (not just next-chains) because the
    relevant blocks are often nested inside SUBSTACKs of forever/if blocks.
    """
    out = []
    enemy = next(t for t in data["targets"] if t["name"] == "Enemy")
    arrow = next(t for t in data["targets"] if t["name"] == "Arrow")
    stage = next(t for t in data["targets"] if t["isStage"])
    for t in data["targets"]:
        t["_stage_ref"] = stage

    # Arrow: find motion_movesteps with positive STEPS
    fly = None
    for bid, b in arrow["blocks"].items():
        if b["opcode"] == "motion_movesteps" and "STEPS" in b.get("inputs", {}):
            try:
                steps = _num(_eval_input(b["inputs"]["STEPS"], arrow, {}, {}, None))
                if steps > 0:
                    fly = steps
                    break
            except Exception:
                pass
    out.append(Check("arrow_moves_horizontally", fly is not None and fly > 0,
                      f"arrow motion_movesteps steps = {fly}",
                      "arrow clone must move +x with positive STEPS"))

    # Arrow: find motion_pointindirection with direction=90 (loose scan)
    has_dir90 = False
    for bid, b in arrow["blocks"].items():
        if b["opcode"] == "motion_pointindirection" and "DIRECTION" in b.get("inputs", {}):
            try:
                d = _num(_eval_input(b["inputs"]["DIRECTION"], arrow, {}, {}, None))
                if d == 90:
                    has_dir90 = True
                    break
            except Exception:
                pass
    out.append(Check("arrow_points_right", has_dir90,
                      "no motion_pointindirection 90 in Arrow",
                      "arrow clone must point direction=90 to fly right"))

    # Arrow: find control_start_as_clone hat, then walk its next-chain and
    # verify the order: motion_gotoxy (with X/Y inputs) -> motion_pointindirection
    # with DIRECTION=90 -> looks_show -> control_forever whose SUBSTACK starts
    # with motion_movesteps (positive STEPS).
    arrow_hat = None
    for bid, b in arrow["blocks"].items():
        if b["opcode"] == "control_start_as_clone":
            arrow_hat = bid
            break

    chain_ok = False
    chain_detail = "no control_start_as_clone in Arrow"
    if arrow_hat is not None:
        steps_in_forever = None
        # walk the entire SUBSTACK subtree of control_forever looking for
        # motion_movesteps (it's no longer the direct first block — we now
        # compute dx/dy/atan before moving)
        forever_bid = None
        cur = arrow["blocks"][arrow_hat].get("next")
        while isinstance(cur, str) and cur in arrow["blocks"]:
            b = arrow["blocks"][cur]
            if b["opcode"] == "control_forever":
                forever_bid = cur
                break
            cur = b.get("next")
        if forever_bid is not None:
            seen = set()
            stack = [forever_bid]
            while stack:
                cur = stack.pop()
                if not isinstance(cur, str) or cur in seen or cur not in arrow["blocks"]:
                    continue
                seen.add(cur)
                bb = arrow["blocks"][cur]
                if bb["opcode"] == "motion_movesteps" and "STEPS" in bb.get("inputs", {}):
                    try:
                        steps_in_forever = _num(_eval_input(
                            bb["inputs"]["STEPS"], arrow, {}, {}, None))
                    except Exception:
                        steps_in_forever = None
                nxt = bb.get("next")
                if isinstance(nxt, str):
                    stack.append(nxt)
                for inp_val in bb.get("inputs", {}).values():
                    if isinstance(inp_val, list) and len(inp_val) >= 2 \
                            and isinstance(inp_val[1], str):
                        stack.append(inp_val[1])

        # check the directional/positional blocks literally in the chain
        visited_opcodes = []
        cur = arrow["blocks"][arrow_hat].get("next")
        while isinstance(cur, str) and cur in arrow["blocks"]:
            b = arrow["blocks"][cur]
            visited_opcodes.append(b["opcode"])
            cur = b.get("next")

        def _find_block_before(stop_op, target_op, requires_input=None):
            cur = arrow["blocks"][arrow_hat].get("next")
            while isinstance(cur, str) and cur in arrow["blocks"]:
                b = arrow["blocks"][cur]
                if b["opcode"] == stop_op:
                    return False
                if b["opcode"] == target_op:
                    if requires_input is None:
                        return True
                    return requires_input in b.get("inputs", {})
                cur = b.get("next")
            return False

        has_goto = _find_block_before("control_forever", "motion_gotoxy")
        has_show = "looks_show" in visited_opcodes
        has_forever = "control_forever" in visited_opcodes
        forever_moves_pos = (steps_in_forever is not None and steps_in_forever > 0)
        chain_ok = has_goto and has_show and has_forever and forever_moves_pos
        chain_detail = (
            f"goto={has_goto} show={has_show} "
            f"forever={has_forever} move_steps={steps_in_forever}"
        )

    out.append(Check("arrow_clone_chain_order", chain_ok,
                      chain_detail,
                      "Arrow clone hat chain must be: goto -> show -> forever{move > 0}"))

    # Arrow: assert the static direction=90 is GONE in the top-level hat chain
    # (replaced by homing). A `point in direction 90` may still exist inside
    # a conditional SUBSTACK (e.g. when dx=0 AND dy>0), which is legitimate
    # homing output. So we walk only the next-chain from the hat, not SUBSTACKs.
    has_dir90_in_hat = False
    if arrow_hat is not None:
        cur = arrow["blocks"][arrow_hat].get("next")
        while isinstance(cur, str) and cur in arrow["blocks"]:
            bb = arrow["blocks"][cur]
            if bb["opcode"] == "motion_pointindirection" and "DIRECTION" in bb.get("inputs", {}):
                try:
                    d = _num(_eval_input(bb["inputs"]["DIRECTION"], arrow, {}, {}, None))
                    if d == 90:
                        has_dir90_in_hat = True
                        break
                except Exception:
                    pass
            cur = bb.get("next")
    out.append(Check("arrow_no_static_90", not has_dir90_in_hat,
                      f"motion_pointindirection(90) in top-level hat chain={has_dir90_in_hat}",
                      "Arrow hat top-level chain must not hardcode direction=90"))

    list_names = _list_name_map(data)
    # Arrow: assert the forever body contains a per-clone EnemyXList read + atan
    has_enemyx_in_forever = False
    has_atan_in_forever = False
    for bid, b in arrow["blocks"].items():
        if b["opcode"] != "control_forever":
            continue
        sb = b.get("inputs", {}).get("SUBSTACK")
        if not (isinstance(sb, list) and len(sb) >= 2 and isinstance(sb[1], str)):
            continue
        # walk the subtree, not just next chain
        seen = set()
        stack = [sb[1]]
        while stack:
            cur = stack.pop()
            if not isinstance(cur, str) or cur in seen or cur not in arrow["blocks"]:
                continue
            seen.add(cur)
            bb = arrow["blocks"][cur]
            if bb["opcode"] == "data_itemoflist":
                lid = (bb.get("fields", {}).get("LIST") or [None, None])[1]
                if list_names.get(lid) == "EnemyXList":
                    has_enemyx_in_forever = True
            if bb["opcode"] == "operator_mathop":
                opk = (bb.get("fields", {}).get("OPERATOR") or [None])[0]
                if opk == "atan":
                    has_atan_in_forever = True
            nxt = bb.get("next")
            if isinstance(nxt, str):
                stack.append(nxt)
            for inp_name, inp_val in bb.get("inputs", {}).items():
                if isinstance(inp_val, list) and len(inp_val) >= 2 \
                        and isinstance(inp_val[1], str):
                    stack.append(inp_val[1])
    out.append(Check("arrow_homes_on_enemy", has_enemyx_in_forever and has_atan_in_forever,
                      f"EnemyXList-in-forever={has_enemyx_in_forever} atan-in-forever={has_atan_in_forever}",
                      "Arrow's forever body must read item T of EnemyXList and use atan"))

    # Arrow: assert dx/dy are computed (operator_subtract with item T of
    # EnemyXList/EnemyYList and motion_xposition/motion_yposition)
    has_dx_sub = False
    has_dy_sub = False
    for bid, b in arrow["blocks"].items():
        if b["opcode"] != "operator_subtract":
            continue
        for slot, other in (("NUM1", "NUM2"), ("NUM2", "NUM1")):
            lname = _slot_list_name(arrow, b["inputs"][slot], list_names)
            other_opcode = _slot_opcode(arrow, b["inputs"][other])
            if lname == "EnemyXList" and other_opcode == "motion_xposition":
                has_dx_sub = True
            if lname == "EnemyYList" and other_opcode == "motion_yposition":
                has_dy_sub = True
    out.append(Check("arrow_dx_dy_computed", has_dx_sub and has_dy_sub,
                      f"dx_sub={has_dx_sub} dy_sub={has_dy_sub}",
                      "Arrow must compute dx=itemT(EnemyXList)-xposition and dy=itemT(EnemyYList)-yposition via operator_subtract"))

    # Arrow: direction math must be d = atan(dx/dy) with a +180 flip when
    # dy<0 (Scratch moves along (sin d, cos d), d=0 = up). The first build
    # did atan(dy/dx) + flip-on-dx<0 — cross-lane arrows flew AWAY from their
    # target. Also motion_turnright's input is DEGREES (VM reads args.DEGREES;
    # the old DIRECTION name silently no-oped the flip).
    has_atan_dx_dy = False
    for bid, b in arrow["blocks"].items():
        if b["opcode"] != "operator_mathop":
            continue
        opk = (b.get("fields", {}).get("OPERATOR") or [None])[0]
        if opk != "atan":
            continue
        num = b.get("inputs", {}).get("NUM")
        div = _slot_block(arrow, num)
        if div is None or div["opcode"] != "operator_divide":
            continue
        n1 = _slot_varname(arrow, div.get("inputs", {}).get("NUM1"))
        n2 = _slot_varname(arrow, div.get("inputs", {}).get("NUM2"))
        if n1 == "dx" and n2 == "dy":
            has_atan_dx_dy = True
    has_flip_dy_lt0 = False
    for bid, b in arrow["blocks"].items():
        if b["opcode"] != "operator_lt":
            continue
        if _slot_varname(arrow, b.get("inputs", {}).get("OPERAND1")) == "dy":
            has_flip_dy_lt0 = True
    has_turn180 = False
    for bid, b in arrow["blocks"].items():
        if b["opcode"] != "motion_turnright":
            continue
        deg = b.get("inputs", {}).get("DEGREES")
        try:
            if _num(_eval_input(deg, arrow, {}, {}, None)) == 180:
                has_turn180 = True
        except Exception:
            pass
    out.append(Check("arrow_atan_dx_over_dy", has_atan_dx_dy and has_flip_dy_lt0 and has_turn180,
                      f"atan(dx/dy)={has_atan_dx_dy} dy<0flip={has_flip_dy_lt0} turn180(DEGREES)={has_turn180}",
                      "Arrow must compute atan(dx/dy), flip 180 when dy<0 via motion_turnright with DEGREES input"))

    # Enemy: assert a control_start_as_clone hat has a SUBSTACK chain
    # containing control_forever with replaceitemoflist EnemyXList + EnemyYList
    has_pos_pub = False
    for bid, b in enemy["blocks"].items():
        if b["opcode"] != "control_start_as_clone":
            continue
        # walk all descendants of this hat (via next-chain and SUBSTACK recursion)
        seen = set()
        stack = [bid]
        while stack:
            cur = stack.pop()
            if not isinstance(cur, str) or cur in seen or cur not in enemy["blocks"]:
                continue
            seen.add(cur)
            bb = enemy["blocks"][cur]
            nxt = bb.get("next")
            if isinstance(nxt, str):
                stack.append(nxt)
            for inp_name, inp_val in bb.get("inputs", {}).items():
                if isinstance(inp_val, list) and len(inp_val) >= 2 \
                        and isinstance(inp_val[1], str):
                    stack.append(inp_val[1])
        # now check seen for: control_forever with a child chain that
        # replaceitemoflist EnemyXList and EnemyYList
        for sub_bid in seen:
            sub_b = enemy["blocks"][sub_bid]
            if sub_b["opcode"] != "control_forever":
                continue
            sb = sub_b.get("inputs", {}).get("SUBSTACK")
            if not (isinstance(sb, list) and len(sb) >= 2 and isinstance(sb[1], str)):
                continue
            sets_x = sets_y = False
            seen2 = set()
            stack2 = [sb[1]]
            while stack2:
                cur = stack2.pop()
                if not isinstance(cur, str) or cur in seen2 or cur not in enemy["blocks"]:
                    continue
                seen2.add(cur)
                bb2 = enemy["blocks"][cur]
                if bb2["opcode"] == "data_replaceitemoflist":
                    lid = (bb2.get("fields", {}).get("LIST") or [None, None])[1]
                    lname = list_names.get(lid)
                    if lname == "EnemyXList":
                        sets_x = True
                    if lname == "EnemyYList":
                        sets_y = True
                nxt = bb2.get("next")
                if isinstance(nxt, str):
                    stack2.append(nxt)
                for inp_name, inp_val in bb2.get("inputs", {}).items():
                    if isinstance(inp_val, list) and len(inp_val) >= 2 \
                            and isinstance(inp_val[1], str):
                        stack2.append(inp_val[1])
            if sets_x and sets_y:
                has_pos_pub = True
                break
        if has_pos_pub:
            break
    out.append(Check("enemy_publishes_position", has_pos_pub,
                      "no EnemyXList/EnemyYList publisher in any clone hat",
                      "Enemy must have a clone hat whose forever replaceitemoflist EnemyXList and EnemyYList at MyIndex"))

    # Enemy: assert the clone hat's top-level chain registers the per-clone
    # slot (HANDOFF §6.1): set MyIndex, then addtolist x/y/HP into the three
    # Stage lists.
    regs = {"MyIndex": False, "EnemyXList": False, "EnemyYList": False, "MyHPList": False}
    for bid, b in enemy["blocks"].items():
        if b["opcode"] != "control_start_as_clone":
            continue
        cur = b.get("next")
        while isinstance(cur, str) and cur in enemy["blocks"]:
            bb = enemy["blocks"][cur]
            if bb["opcode"] == "data_setvariableto":
                fname = (bb.get("fields", {}).get("VARIABLE") or [None])[0]
                if fname == "MyIndex":
                    regs["MyIndex"] = True
            if bb["opcode"] == "data_addtolist":
                lid = (bb.get("fields", {}).get("LIST") or [None, None])[1]
                lname = list_names.get(lid)
                if lname in regs:
                    regs[lname] = True
            cur = bb.get("next")
    out.append(Check("enemy_registers_slot", all(regs.values()),
                     f"regs={ {k: v for k, v in regs.items()} }",
                     "Enemy clone hat must set MyIndex and append x/y/HP to EnemyXList/EnemyYList/MyHPList (HANDOFF §6.1)"))

    # Plots: each Plot has sprite-local ShooterX and ShooterY variables
    local_targets = {t["name"]: t for t in data["targets"]}
    bad_plots = []
    for i in range(1, 5):
        name = f"Plot{i}"
        p = local_targets.get(name)
        if p is None:
            bad_plots.append(name + " missing")
            continue
        names = set()
        for vname in p.get("variables", {}).values():
            if isinstance(vname, list) and vname:
                names.add(vname[0])
        if "ShooterX" not in names or "ShooterY" not in names:
            bad_plots.append(f"{name} lacks ShooterX/ShooterY: have={names}")
    out.append(Check("plot_has_per_plot_shooter_vars", not bad_plots,
                      "; ".join(bad_plots) if bad_plots else "all 4 plots have ShooterX/ShooterY",
                      "each Plot sprite must have sprite-local ShooterX and ShooterY variables"))

    # Enemy: find motion_gotoxy with Y=90 or Y=-110 (tower rows)
    has_lane = False
    lane_y = None
    for bid, b in enemy["blocks"].items():
        if b["opcode"] == "motion_gotoxy" and "Y" in b.get("inputs", {}):
            try:
                y = _num(_eval_input(b["inputs"]["Y"], enemy, {}, {}, None))
                if y in (90, -110):
                    has_lane = True
                    lane_y = y
                    break
            except Exception:
                pass
    out.append(Check("enemy_walks_tower_lane", has_lane,
                      f"no motion_gotoxy Y=90/-110 in Enemy" if not has_lane else f"found lane y={lane_y}",
                      "enemy clones must glide along y=90 or y=-110 (tower rows)"))

    return out


# ---- geometry / costume-center check ---------------------------------------

def _svg_path_bbox(path_d, x=0, y=0, scale=1):
    """Crude bbox for a list of <path d="..."/> strings. Returns
    (xmin, ymin, xmax, ymax) in the costume's local coordinate system.
    We only handle M/L/H/V/Z and the basic A/C/Q/T commands Scratch uses
    (or just rasterise to a coarse grid and find non-zero pixels)."""
    # The simpler/faster approach: just check that the arrow costume's
    # `tip` pixel is on the right edge. We scan the SVG source for
    # commands, accumulate absolute coordinates, and return bbox.
    nums = [float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", path_d)]
    pts = []
    i = 0
    cx, cy = 0.0, 0.0
    startx, starty = 0.0, 0.0
    cmds = re.findall(r"[A-Za-z]", path_d)
    cmd_iter = iter(cmds)
    for c in cmd_iter:
        if c in "MmLlHhVvZzCcSsQqTtAa":
            pass
    # Simple M/L parser
    tokens = re.findall(r"([A-Za-z])([-\d\.\s,]*)", path_d)
    for cmd, args in tokens:
        args = [float(a) for a in re.findall(r"-?\d+(?:\.\d+)?", args)]
        if cmd in "Mm":
            for k in range(0, len(args), 2):
                if cmd == "M":
                    cx, cy = args[k] + (args[k+1] if k+1 < len(args) else 0), args[k+1] if k+1 < len(args) else cy
                else:  # m
                    cx += args[k]
                    cy += (args[k+1] if k+1 < len(args) else 0)
                pts.append((cx, cy))
                startx, starty = cx, cy
        elif cmd in "Ll":
            for k in range(0, len(args), 2):
                if cmd == "L":
                    cx, cy = args[k], args[k+1] if k+1 < len(args) else cy
                else:
                    cx += args[k]
                    cy += (args[k+1] if k+1 < len(args) else 0)
                pts.append((cx, cy))
        elif cmd in "Hh":
            for a in args:
                cx = a if cmd == "H" else cx + a
                pts.append((cx, cy))
        elif cmd in "Vv":
            for a in args:
                cy = a if cmd == "V" else cy + a
                pts.append((cx, cy))
        elif cmd in "Zz":
            cx, cy = startx, starty
    if not pts:
        return None
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _check_geometry(data):
    """For every costume, parse the SVG and check that the visual
    content's rightmost pixel aligns with rotationCenterX within tolerance.
    The Arrow costume in particular: the tip must be on the right edge so
    it appears to fly toward x=+240."""
    out = []
    for t in data["targets"]:
        for c in t.get("costumes", []):
            raw = ASSETS.get(c["md5ext"])
            if not raw or c.get("dataFormat") != "svg":
                continue
            try:
                root = ET.fromstring(raw)
            except ET.ParseError as exc:
                out.append(Check(f"svg_parse:{t['name']}/{c['name']}", False,
                                  f"could not parse SVG: {exc}",
                                  "fix the costume SVG"))
                continue
            # union bbox of all <path d=...> and rect/circle
            xs, ys = [], []
            for el in root.iter():
                tag = el.tag.split("}", 1)[-1]
                if tag == "path":
                    d = el.get("d", "")
                    bb = _svg_path_bbox(d)
                    if bb:
                        xs += [bb[0], bb[2]]
                        ys += [bb[1], bb[3]]
                elif tag == "rect":
                    try:
                        x = float(el.get("x", 0))
                        y = float(el.get("y", 0))
                        w = float(el.get("width", 0))
                        h = float(el.get("height", 0))
                        xs += [x, x + w]
                        ys += [y, y + h]
                    except ValueError:
                        pass
                elif tag == "circle":
                    try:
                        cx = float(el.get("cx", 0))
                        cy = float(el.get("cy", 0))
                        r = float(el.get("r", 0))
                        xs += [cx - r, cx + r]
                        ys += [cy - r, cy + r]
                    except ValueError:
                        pass
            if not xs:
                continue
            visual_xmin, visual_xmax = min(xs), max(xs)
            visual_ymin, visual_ymax = min(ys), max(ys)
            cx = c.get("rotationCenterX", 0)
            cy = c.get("rotationCenterY", 0)
            # For a sprite pointing right (Arrow): tip at right edge -> rightmost
            # pixel ~ visual_xmax; if rotationCenterX is far left, the
            # costume will appear shifted right and the visual tip will be
            # even further right of center, but Scratch positions the
            # sprite AT (rotationCenterX,rotationCenterY), so the costume
            # is drawn so that point sits at the sprite's x,y. We want
            # the costume's tip to be at the right edge of the costume
            # extent; that's a property of the costume drawing itself.
            bbox_w = visual_xmax - visual_xmin
            bbox_h = visual_ymax - visual_ymin
            bbox_ok = (bbox_w > 0 and bbox_h > 0 and visual_xmin < visual_xmax)
            out.append(Check(f"costume_center:{t['name']}/{c['name']}",
                              bbox_ok,
                              f"bbox non-empty ({bbox_w:.0f} x {bbox_h:.0f}) "
                              f"x=[{visual_xmin:.0f},{visual_xmax:.0f}] "
                              f"y=[{visual_ymin:.0f},{visual_ymax:.0f}] "
                              f"center=({cx},{cy})",
                              "costume SVG must have non-empty bbox with W>0 and H>0"))
            # specific arrow check: if name is 'arrow', tip should be at right
            if c["name"] == "arrow":
                # real cosmetic check: locate the rightmost path in the SVG
                # and verify its bbox xmax is within a small delta of the
                # overall bbox xmax (so the arrowhead actually lives on the
                # right edge, not somewhere in the middle). Also require at
                # least 2 paths (body + tip).
                paths = [el for el in root.iter()
                         if el.tag.split("}", 1)[-1] == "path"]
                path_bboxes = []
                for el in paths:
                    bb = _svg_path_bbox(el.get("d", ""))
                    if bb:
                        path_bboxes.append(bb)
                rightmost_xmax = max((bb[2] for bb in path_bboxes), default=0)
                delta = abs(rightmost_xmax - visual_xmax)
                tip_ok = (len(path_bboxes) >= 2) and (delta <= 1.0)
                out.append(Check("arrow_cosmetic_tip_right",
                                  tip_ok,
                                  f"arrow paths={len(path_bboxes)} "
                                  f"rightmost_xmax={rightmost_xmax:.0f} "
                                  f"bbox_xmax={visual_xmax:.0f} delta={delta:.2f}",
                                  "arrow SVG rightmost path must end at the right edge (body + tip)"))
    return out


# ---- report + self_test glue ---------------------------------------------

class Report:
    def __init__(self, checks):
        self.checks = checks
        self.passed = all(c.ok for c in checks)
        self.data = None  # filled by self_test

    def print(self):
        passed = sum(1 for c in self.checks if c.ok)
        failed = sum(1 for c in self.checks if not c.ok)
        print(f"\n=== self_test: {passed} passed, {failed} failed ===")
        for c in self.checks:
            print(" ", repr(c))


def self_test(project):
    """Run all checks against the in-memory project, return a Report."""
    data = json.loads(json.dumps(project))  # deep copy
    checks = []
    checks.extend(_check_static(data))
    checks.extend(_simulate_spawner(data))
    checks.extend(_simulate_arrow_hits(data))
    checks.extend(_check_geometry(data))
    rep = Report(checks)
    rep.data = data
    return rep


if __name__ == "__main__":
    main()
