"""Render demo-video/calibra-demo.mp4 (1920x1080, 30 fps) from real repository data.

Inputs (all real, nothing synthesized):
  demo-video/build/data.json          from prepare_data.py
  demo-video/evidence/*.txt           captured `calibra analyze` / `calibra prune` stdout
  $FRAMES (raw rgb24 96x96)           decoded pusht/videos/observation.image/.../file-000.mp4
  web/public/logo.png                 Calibra wordmark

Usage:
  python demo-video/scripts/render.py --frames <pusht_frames.rgb>                  # full render
  python demo-video/scripts/render.py --frames <...> --stills 4 12 30 45 56        # PNG stills
"""

from __future__ import annotations

import argparse
import json
import math
import subprocess
import sys
from functools import lru_cache
from multiprocessing import Pool
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
DV = ROOT / "demo-video"
W, H, FPS = 1920, 1080, 30
DURATION = 59.0

# ── palette (from brand/ and web/src) ────────────────────────────────────────
BG = (10, 10, 10)
PANEL = (19, 19, 19)
BORDER = (40, 40, 40)
TEXT = (242, 242, 240)
MUTED = (146, 146, 142)
DIM = (92, 92, 89)
ACCENT = (137, 0, 255)
ACCENT_L = (178, 112, 255)
GREEN = (88, 214, 141)
RANDOM_C = (150, 150, 146)

HEL = "/System/Library/Fonts/HelveticaNeue.ttc"
MENLO = "/System/Library/Fonts/Menlo.ttc"
SYMBOLS = "/System/Library/Fonts/Apple Symbols.ttf"


@lru_cache(maxsize=None)
def font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    if weight == "mono":
        return ImageFont.truetype(MENLO, size, index=0)
    if weight == "monobold":
        return ImageFont.truetype(MENLO, size, index=1)
    if weight == "symbol":
        return ImageFont.truetype(SYMBOLS, size)
    idx = {"regular": 0, "bold": 1, "medium": 10, "light": 7}[weight]
    return ImageFont.truetype(HEL, size, index=idx)


# ── data ─────────────────────────────────────────────────────────────────────
DATA = json.loads((DV / "build/data.json").read_text())
BENCH = DATA["benchmark"]
FULL_MSE = BENCH["full_baseline"]["mse"]
SWEEP = BENCH["sweep"]
ROW25 = next(r for r in SWEEP if r["keep_fraction"] == 0.25)
CAL25 = (ROW25["calibra_mse"] / FULL_MSE - 1) * 100  # 0.77
RND25 = (ROW25["random_mse"] / FULL_MSE - 1) * 100  # 2.16
T25 = DATA["targeted_25"]["methods"]["calibra"]["overall"]
P_TARGETED = T25["p_paired"]
N_SEEDS_TARGETED = DATA["targeted_meta"]["n_seeds"]
RARE_CAL = ROW25["calibra_rare_coverage"] * 100
RARE_RND = ROW25["random_rare_coverage"] * 100
N_TRAIN = BENCH["n_train_episodes"]
N_TEST = BENCH["n_test_episodes"]
K25 = ROW25["n_episodes"]
N_RANDOM_SEEDS = 5  # lerobot_coreset_benchmark.py default; random_mse is the 5-seed mean
assert round(CAL25, 1) == 0.8 and round(RND25, 1) == 2.2, (CAL25, RND25)
assert N_TRAIN == 165 and N_TEST == 41 and K25 == 41

EP_IDS = DATA["episode_ids"]
RANGES = {k: tuple(v) for k, v in DATA["ranges"].items()}
TRACES = {k: np.asarray(v, dtype=float) for k, v in DATA["traces"].items()}
CLI_KEPT = DATA["cli_kept"]
TRAIN_IDS = DATA["bench_train_ids"]
BENCH_KEPT = DATA["bench_kept_reselected"]

ANALYZE = (DV / "evidence/analyze_pusht.txt").read_text().splitlines()
PRUNE = (DV / "evidence/prune_pusht_25.txt").read_text().splitlines()

FRAMES = None


def init_frames(path: str) -> None:
    global FRAMES
    n = Path(path).stat().st_size // (96 * 96 * 3)
    FRAMES = np.memmap(path, dtype=np.uint8, mode="r", shape=(n, 96, 96, 3))


LOGO = None


def logo_rgba(width: int) -> Image.Image:
    global LOGO
    if LOGO is None:
        im = Image.open(ROOT / "web/public/logo.png").convert("L")
        bbox = im.point(lambda v: 255 if v > 60 else 0).getbbox()
        LOGO = im.crop(bbox)
    h = round(LOGO.height * width / LOGO.width)
    mask = LOGO.resize((width, h), Image.LANCZOS)
    mask = mask.point(lambda v: max(0, min(255, int((v - 10) * 255 / 232))))
    out = Image.new("RGBA", (width, h), TEXT + (0,))
    out.putalpha(mask)
    return out


# ── helpers ──────────────────────────────────────────────────────────────────
def clamp(x, a=0.0, b=1.0):
    return max(a, min(b, x))


def prog(t, t0, dur):
    return clamp((t - t0) / dur) if dur > 0 else float(t >= t0)


def ease(x):  # easeOutCubic
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_io(x):
    x = clamp(x)
    return 4 * x**3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def mix(c1, c2, a):
    return tuple(int(round(c1[i] + (c2[i] - c1[i]) * a)) for i in range(3))


def text(base: Image.Image, xy, s, f, color=TEXT, alpha=1.0, anchor="la"):
    if alpha <= 0.003 or not s:
        return
    d = ImageDraw.Draw(base)
    xy = (round(xy[0]), round(xy[1]))
    l, t_, r, b = [int(v) for v in d.textbbox(xy, s, font=f, anchor=anchor)]
    pad = 4
    layer = Image.new("RGBA", (r - l + 2 * pad, b - t_ + 2 * pad), color + (0,))
    ImageDraw.Draw(layer).text(
        (xy[0] - l + pad, xy[1] - t_ + pad), s, font=f, fill=color + (int(255 * alpha),), anchor=anchor
    )
    base.alpha_composite(layer, (l - pad, t_ - pad))


def text_w(s, f):
    return f.getlength(s)


def rrect(base, box, r, fill=None, outline=None, width=1, alpha=1.0):
    if alpha <= 0.003:
        return
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    layer = Image.new("RGBA", (x1 - x0 + 1, y1 - y0 + 1), (0, 0, 0, 0))
    a = int(255 * alpha)
    ImageDraw.Draw(layer).rounded_rectangle(
        (0, 0, x1 - x0, y1 - y0),
        r,
        fill=(fill + (a,)) if fill else None,
        outline=(outline + (a,)) if outline else None,
        width=width,
    )
    base.alpha_composite(layer, (x0, y0))


def ep_frame(eid: str, t: float, phase: float = 0.0) -> np.ndarray:
    a, b = RANGES[eid]
    n = b - a
    i = a + int((t * 10 + phase) % n)
    return FRAMES[i]


@lru_cache(maxsize=6000)
def _tile(idx: int, size: int) -> Image.Image:
    return Image.fromarray(np.asarray(FRAMES[idx])).resize((size, size), Image.BILINEAR)


def tile_img(eid: str, t: float, size: int, phase: float = 0.0) -> Image.Image:
    a, b = RANGES[eid]
    i = a + int((t * 10 + phase) % (b - a))
    return _tile(i, size)


def phase_of(eid: str) -> float:
    return (int(eid) * 37) % 60


def paste_tile(base, im, x, y, alpha=1.0, brightness=1.0, radius=6):
    if alpha <= 0.003:
        return
    if brightness < 0.999:
        arr = (np.asarray(im, dtype=np.float32) * brightness + np.array(BG) * (1 - brightness)).astype(np.uint8)
        im = Image.fromarray(arr)
    im = im.convert("RGBA")
    mask = Image.new("L", im.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, im.size[0] - 1, im.size[1] - 1), radius, fill=int(255 * alpha))
    im.putalpha(mask)
    base.alpha_composite(im, (int(round(x)), int(round(y))))


def eyebrow(base, s, title, t_in, t):
    a = ease(prog(t, t_in, 0.5))
    text(base, (96, 62), s, font(22, "bold"), ACCENT_L, a)
    text(base, (96, 96 + 10 * (1 - a)), title, font(46, "bold"), TEXT, a)


# ── scene 1: hook (0 - 8.4) ──────────────────────────────────────────────────
S1_COLS, S1_TILE, S1_GAP = 18, 68, 6


@lru_cache(maxsize=32)
def _scrim_mask() -> Image.Image:
    from PIL import ImageFilter

    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).rounded_rectangle((300, 330, W - 300, 740), 120, fill=215)
    return m.filter(ImageFilter.GaussianBlur(70))


def _scrim(a: float) -> Image.Image:
    q = round(a * 20) / 20
    return _scrim_cached(q)


@lru_cache(maxsize=32)
def _scrim_cached(q: float) -> Image.Image:
    im = Image.new("RGBA", (W, H), BG + (0,))
    im.putalpha(_scrim_mask().point(lambda v: int(v * q)))
    return im


def scene_hook(t: float) -> Image.Image:
    base = Image.new("RGBA", (W, H), BG + (255,))
    rows = math.ceil(len(EP_IDS) / S1_COLS)
    gw = S1_COLS * S1_TILE + (S1_COLS - 1) * S1_GAP
    gh = rows * S1_TILE + (rows - 1) * S1_GAP
    x0, y0 = (W - gw) / 2, (950 - gh) / 2 + 6
    dim = 1 - 0.76 * ease_io(prog(t, 1.3, 0.9))
    rng = np.random.default_rng(7)
    delays = rng.uniform(0, 1.0, len(EP_IDS))
    for k, eid in enumerate(EP_IDS):
        r, c = divmod(k, S1_COLS)
        n_in_row = min(S1_COLS, len(EP_IDS) - r * S1_COLS)
        off = (S1_COLS - n_in_row) * (S1_TILE + S1_GAP) / 2
        a = ease(prog(t, delays[k], 0.45))
        paste_tile(base, tile_img(eid, t, S1_TILE, phase_of(eid)),
                   x0 + off + c * (S1_TILE + S1_GAP), y0 + r * (S1_TILE + S1_GAP) + 8 * (1 - a), a, dim)
    sa = ease_io(prog(t, 1.3, 0.9))
    if sa > 0:
        base.alpha_composite(_scrim(sa))
    # headline
    a1 = ease(prog(t, 1.7, 0.7))
    f = font(108, "bold")
    text(base, (W / 2, 418 + 24 * (1 - a1)), "Do you need all your", f, TEXT, a1, "mm")
    text(base, (W / 2, 548 + 24 * (1 - a1)), "robotics training data?", f, TEXT, a1, "mm")
    a2 = ease(prog(t, 3.8, 0.6))
    text(base, (W / 2, 690), f"lerobot/pusht  ·  {len(EP_IDS)} human demonstrations  ·  25,650 frames",
         font(34, "regular"), (196, 196, 192), a2, "mm")
    return base


# ── scene 2: analyze + prune (8 - 22.4) ──────────────────────────────────────
TERM = (96, 186, 1096, 930)
PLOT_PANEL = (1136, 186, 1824, 930)
ANALYZE_LINES = [ln for i, ln in enumerate(ANALYZE[:23]) if i not in (3, 11)]
def _wrap_prune(lines, width=72):
    out = []
    for ln in lines:
        while len(ln) > width:
            cut = ln.rfind(",", 0, width) + 1 or width
            out.append(ln[:cut])
            ln = "        " + ln[cut:]
        out.append(ln)
    return out


PRUNE_LINES = _wrap_prune(PRUNE[:16])
CMD1 = "$ calibra analyze pusht --profile pusht"
CMD2 = "$ calibra prune pusht --keep 0.25 --strategy diversity --profile pusht"


def term_line(base, x, y, s, alpha, f):
    """Draw one real output line; Menlo lacks the emoji check, so draw it with a symbol font."""
    color = TEXT
    if s.startswith("$"):
        text(base, (x, y), "$", f, ACCENT_L, alpha)
        text(base, (x + text_w("$ ", f), y), s[2:], f, TEXT, alpha)
        return
    if "✅" in s:
        pre, post = s.split("✅", 1)
        cx = x + text_w(pre, f)
        ck = Image.new("RGBA", (40, 40), (0, 0, 0, 0))
        ImageDraw.Draw(ck).line([(4, 22), (14, 32), (34, 8)], fill=GREEN + (int(255 * alpha),), width=6, joint="curve")
        base.alpha_composite(ck.resize((20, 20), Image.LANCZOS), (int(cx), int(y + 2)))
        text(base, (cx + text_w("  ", f), y), post.lstrip(), f, TEXT, alpha)
        return
    if s.strip().startswith(("━", "─")):
        color = DIM
    elif s.strip() in ("CALIBRA ANALYSIS", "CALIBRA PRUNING SUMMARY"):
        text(base, (x, y), s, font(f.size, "monobold"), ACCENT_L, alpha)
        return
    elif s.strip() in ("Dataset", "Integrity", "Train on the kept episodes (no export needed):"):
        text(base, (x, y), s, font(f.size, "monobold"), TEXT, alpha)
        return
    text(base, (x, y), s, f, color, alpha)


def draw_terminal(base, t):
    a = ease(prog(t, 0.0, 0.5))
    x0, y0, x1, y1 = TERM
    rrect(base, TERM, 14, fill=(14, 14, 14), outline=BORDER, width=2, alpha=a)
    rrect(base, (x0, y0, x1, y0 + 44), 14, fill=(24, 24, 24), alpha=a)
    rrect(base, (x0, y0 + 30, x1, y0 + 44), 0, fill=(24, 24, 24), alpha=a)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        rrect(base, (x0 + 20 + i * 22, y0 + 16, x0 + 32 + i * 22, y0 + 28), 6, fill=c, alpha=a * 0.85)
    text(base, ((x0 + x1) / 2, y0 + 22), "calibra  ·  real output, local lerobot/pusht copy", font(17, "regular"),
         MUTED, a, "mm")
    f = font(19, "mono")
    lh = 29
    tx, ty = x0 + 28, y0 + 66
    clear_at = 6.0
    if t < clear_at:
        n_ch = int(len(CMD1) * prog(t, 0.5, 1.1))
        caret = n_ch < len(CMD1) or (int(t * 2) % 2 == 0 and t < 2.0)
        term_line(base, tx, ty, CMD1[:n_ch] + ("▌" if caret else ""), a, f)
        shown = int(len(ANALYZE_LINES) * prog(t, 1.9, 2.1))
        fade = 1 - prog(t, clear_at - 0.35, 0.35)
        for i, ln in enumerate(ANALYZE_LINES[:shown]):
            term_line(base, tx, ty + (i + 1) * lh, ln, a * fade, f)
    else:
        n_ch = int(len(CMD2) * prog(t, clear_at + 0.2, 1.3))
        caret = n_ch < len(CMD2)
        term_line(base, tx, ty, CMD2[:n_ch] + ("▌" if caret else ""), a, f)
        shown = int(len(PRUNE_LINES) * prog(t, clear_at + 1.8, 1.6))
        for i, ln in enumerate(PRUNE_LINES[:shown]):
            hl = "Coreset size" in ln
            if hl and prog(t, clear_at + 3.5, 0.4) > 0:
                ha = ease(prog(t, clear_at + 3.5, 0.4))
                yy = ty + (i + 1) * lh
                rrect(base, (tx - 10, yy - 5, x1 - 18, yy + lh - 3), 6, fill=(44, 18, 74), alpha=ha)
            term_line(base, tx, ty + (i + 1) * lh, ln, a, f)


def project(pt, box):
    x0, y0, x1, y1 = box
    return x0 + pt[0] / 512 * (x1 - x0), y0 + pt[1] / 512 * (y1 - y0)


def draw_traces(base, t):
    a = ease(prog(t, 0.3, 0.5))
    px0, py0, px1, py1 = PLOT_PANEL
    rrect(base, PLOT_PANEL, 14, fill=PANEL, outline=BORDER, width=2, alpha=a)
    sel_p = prog(t, 8.6, 4.0)
    n_sel = int(round(len(CLI_KEPT) * sel_p))
    title = "Episode action traces" if n_sel == 0 else "Calibra selection, in pick order"
    text(base, (px0 + 32, py0 + 30), title, font(26, "bold"), TEXT, a)
    text(base, (px0 + 32, py0 + 66), "x/y target positions, all 206 episodes", font(19, "regular"), MUTED, a)
    S = 2
    PS = 540
    box = (0, 0, PS * S, PS * S)
    layer = Image.new("RGB", (PS * S, PS * S), PANEL)
    d = ImageDraw.Draw(layer)
    n_show = int(len(EP_IDS) * prog(t, 0.9, 3.0))
    dimming = ease(prog(t, 8.4, 0.8))
    grey = mix((86, 86, 84), (46, 46, 45), dimming)
    kept_set = set(CLI_KEPT[:n_sel])
    for eid in EP_IDS[:n_show]:
        if eid in kept_set:
            continue
        pts = [project(p, box) for p in TRACES[eid]]
        d.line(pts, fill=grey, width=2 * S // 2 + 1, joint="curve")
    for j, eid in enumerate(CLI_KEPT[:n_sel]):
        pts = [project(p, box) for p in TRACES[eid]]
        fresh = j >= n_sel - 3
        d.line(pts, fill=(222, 190, 255) if fresh else ACCENT_L, width=3 * S, joint="curve")
    small = layer.resize((PS, PS), Image.LANCZOS).convert("RGBA")
    if a < 1:
        small.putalpha(int(255 * a))
    base.alpha_composite(small, (int((px0 + px1 - PS) / 2), py0 + 112))
    if n_sel > 0:
        ca = ease(prog(t, 8.6, 0.4))
        text(base, (px0 + 44, py1 - 30), f"Selected {n_sel} / {len(CLI_KEPT)}", font(24, "bold"), ACCENT_L, ca, "ls")
        ba = ease(prog(t, 12.8, 0.5))
        text(base, (px1 - 40, py1 - 30), f"{len(CLI_KEPT)} of {len(EP_IDS)} kept  ·  "
             f"{len(CLI_KEPT) / len(EP_IDS):.1%}", font(24, "bold"), TEXT, ba, "rs")


def scene_workflow(t: float) -> Image.Image:
    base = Image.new("RGBA", (W, H), BG + (255,))
    eyebrow(base, "STEP 1  ·  AUDIT AND SELECT", "Audit the dataset. Keep a diverse 25%.", 0.0, t)
    draw_terminal(base, t)
    draw_traces(base, t)
    return base


# ── scene 3: benchmark (22 - 42.4) ───────────────────────────────────────────
LP = (96, 186, 936, 870)
RP = (984, 186, 1824, 870)


def grid_positions(n, cols, tile, gap, box, top):
    x0, y0, x1, y1 = box
    rows = math.ceil(n / cols)
    gw = cols * tile + (cols - 1) * gap
    out = []
    for k in range(n):
        r, c = divmod(k, cols)
        n_in_row = min(cols, n - r * cols)
        off = (cols - n_in_row) * (tile + gap) / 2
        out.append((x0 + (x1 - x0 - gw) / 2 + off + c * (tile + gap), y0 + top + r * (tile + gap)))
    return out


L_TILE, L_COLS, L_GAP = 46, 15, 4
R_TILE, R_COLS, R_GAP = 80, 7, 8
LPOS = grid_positions(len(TRAIN_IDS), L_COLS, L_TILE, L_GAP, LP, 108)
RPOS = grid_positions(len(BENCH_KEPT), R_COLS, R_TILE, R_GAP, RP, 108)
L_INDEX = {eid: i for i, eid in enumerate(TRAIN_IDS)}


def bench_tiles(base, t):
    a = ease(prog(t, 0.0, 0.5))
    for box, title, sub, col in (
        (LP, "Full training set", f"{N_TRAIN} episodes", MUTED),
        (RP, "Calibra coreset", f"{K25} episodes  ·  25%", ACCENT_L),
    ):
        rrect(base, box, 14, fill=PANEL, outline=BORDER, width=2, alpha=a)
        text(base, (box[0] + 32, box[1] + 30), title, font(30, "bold"), TEXT, a)
        text(base, (box[0] + 32, box[1] + 70), sub, font(22, "medium"), col, a)
    kept = set(BENCH_KEPT)
    hl = ease(prog(t, 0.9, 0.6))
    for k, eid in enumerate(TRAIN_IDS):
        ta = ease(prog(t, 0.2 + k * 0.004, 0.4))
        x, y = LPOS[k]
        is_k = eid in kept
        bright = 1.0 - (0.45 * hl if not is_k else 0)
        if is_k and hl > 0:
            rrect(base, (x - 3, y - 3, x + L_TILE + 2, y + L_TILE + 2), 7, outline=ACCENT_L, width=2, alpha=hl * ta)
        paste_tile(base, tile_img(eid, t, L_TILE, phase_of(eid)), x, y, ta, bright, 5)
    for j, eid in enumerate(BENCH_KEPT):
        p = ease_io(prog(t, 1.8 + j * 0.03, 1.2))
        if p <= 0:
            continue
        sx, sy = LPOS[L_INDEX[eid]]
        tx, ty = RPOS[j]
        size = int(round(L_TILE + (R_TILE - L_TILE) * p))
        x = sx + (tx - sx) * p
        y = sy + (ty - sy) * p - math.sin(p * math.pi) * 40
        paste_tile(base, tile_img(eid, t, size, phase_of(eid)), x, y, 1.0, 1.0, 8)
    fa = ease(prog(t, 3.6, 0.6))
    text(base, (W / 2, 906), f"Real lerobot/pusht training demonstrations, not policy rollouts. Both sets train the same "
         f"BC-MLP for 120 epochs", font(22, "regular"), MUTED, fa, "mm")
    text(base, (W / 2, 938), f"and are scored on the same {N_TEST} held-out episodes.", font(22, "regular"), MUTED,
         fa, "mm")


CH = (96, 186, 1216, 870)
BARP = (1264, 186, 1824, 870)
FRACS = [r["keep_fraction"] for r in SWEEP]
CAL_REL = [(r["calibra_mse"] / FULL_MSE - 1) * 100 for r in SWEEP]
RND_REL = [(r["random_mse"] / FULL_MSE - 1) * 100 for r in SWEEP]
RND_SD = [r["random_mse_std"] / FULL_MSE * 100 for r in SWEEP]


def dashed(d, p0, p1, color, width, dash=14, gap=10):
    x0, y0 = p0
    x1, y1 = p1
    L = math.hypot(x1 - x0, y1 - y0)
    n = int(L // (dash + gap)) + 1
    for i in range(n):
        s = i * (dash + gap) / L
        e = min(1, (i * (dash + gap) + dash) / L)
        d.line([(x0 + (x1 - x0) * s, y0 + (y1 - y0) * s), (x0 + (x1 - x0) * e, y0 + (y1 - y0) * e)],
               fill=color, width=width)


def bench_chart(base, t):
    a = ease(prog(t, 0.0, 0.5))
    rrect(base, CH, 14, fill=PANEL, outline=BORDER, width=2, alpha=a)
    text(base, (CH[0] + 32, CH[1] + 30), "Held-out error above full-data training", font(30, "bold"), TEXT, a)
    text(base, (CH[0] + 32, CH[1] + 70), "Action-prediction MSE, lower is better", font(22, "regular"), MUTED, a)
    # legend
    lx = CH[2] - 32
    leg = [("Calibra", ACCENT_L), (f"Random (mean ± sd, {N_RANDOM_SEEDS} seeds)", RANDOM_C)]
    for name, c in reversed(leg):
        w_ = text_w(name, font(20, "medium"))
        text(base, (lx, CH[1] + 44), name, font(20, "medium"), TEXT, a, "rm")
        rrect(base, (lx - w_ - 40, CH[1] + 41, lx - w_ - 14, CH[1] + 47), 3, fill=c, alpha=a)
        lx -= w_ + 72
    # plot area
    S = 2
    pw, ph = 960, 520
    ox, oy = CH[0] + 110, CH[1] + 120
    layer = Image.new("RGB", (pw * S, ph * S), PANEL)
    d = ImageDraw.Draw(layer)
    ymax = 18.0
    xs = [40 + i * (pw - 80) / (len(FRACS) - 1) for i in range(len(FRACS))]

    def Y(v):
        return (ph - 50 - v / ymax * (ph - 80)) * S

    for v in (0, 5, 10, 15):
        d.line([(0, Y(v)), (pw * S, Y(v))], fill=(36, 36, 36), width=2)
    dashed(d, (0, Y(0)), (pw * S, Y(0)), (200, 200, 196), 3)
    draw_p = ease_io(prog(t, 1.0, 2.6))

    def poly(vals, color, width):
        pts = [(xs[i] * S, Y(v)) for i, v in enumerate(vals)]
        total = draw_p * (len(pts) - 1)
        k = int(total)
        seg = pts[: k + 1]
        if k < len(pts) - 1:
            fr = total - k
            seg = seg + [(pts[k][0] + (pts[k + 1][0] - pts[k][0]) * fr, pts[k][1] + (pts[k + 1][1] - pts[k][1]) * fr)]
        if len(seg) > 1:
            d.line(seg, fill=color, width=width * S, joint="curve")
        for i, p in enumerate(pts):
            if i <= total + 1e-6:
                r = (width + 3) * S
                d.ellipse((p[0] - r, p[1] - r, p[0] + r, p[1] + r), fill=color)

    # random error bars
    for i, (m, sd) in enumerate(zip(RND_REL, RND_SD)):
        if i <= draw_p * (len(xs) - 1) + 1e-6:
            x = xs[i] * S
            d.line([(x, Y(m - sd)), (x, Y(m + sd))], fill=(100, 100, 97), width=2 * S)
            d.line([(x - 8 * S, Y(m - sd)), (x + 8 * S, Y(m - sd))], fill=(100, 100, 97), width=2 * S)
            d.line([(x - 8 * S, Y(m + sd)), (x + 8 * S, Y(m + sd))], fill=(100, 100, 97), width=2 * S)
    hl = ease(prog(t, 4.0, 0.6))
    if hl > 0:
        x = xs[FRACS.index(0.25)] * S
        band = Image.new("RGB", layer.size, (40, 20, 66))
        m = Image.new("L", layer.size, 0)
        ImageDraw.Draw(m).rounded_rectangle((x - 46 * S, 20 * S, x + 46 * S, (ph - 36) * S), 12 * S,
                                            fill=int(150 * hl))
        layer.paste(band, (0, 0), m)
        d = ImageDraw.Draw(layer)
        for v in (0, 5, 10, 15):
            d.line([(0, Y(v)), (x - 46 * S, Y(v))], fill=(36, 36, 36), width=2)
        dashed(d, (0, Y(0)), (pw * S, Y(0)), (200, 200, 196), 3)
    poly(RND_REL, RANDOM_C, 3)
    poly(CAL_REL, ACCENT_L, 4)
    small = layer.resize((pw, ph), Image.LANCZOS).convert("RGBA")
    if a < 1:
        small.putalpha(int(255 * a))
    base.alpha_composite(small, (ox, oy))
    # axes labels
    for v in (0, 5, 10, 15):
        text(base, (ox - 16, oy + Y(v) / S), f"+{v}%" if v else "0%", font(20, "regular"), MUTED, a, "rm")
    for i, fr in enumerate(FRACS):
        text(base, (ox + xs[i], oy + ph - 18), f"{fr:.0%}", font(20, "medium"), MUTED, a, "mm")
    text(base, (ox + pw / 2, oy + ph + 22), f"Share of the {N_TRAIN} training episodes kept", font(20, "regular"),
         MUTED, a, "mm")
    text(base, (ox + 4, oy + Y(0) / S - 12), f"Full data ({N_TRAIN} episodes)", font(19, "medium"),
         (200, 200, 196), a * ease(prog(t, 0.8, 0.5)), "ls")
    if hl > 0:
        x = ox + xs[FRACS.index(0.25)]
        yc = oy + Y(CAL25) / S
        yr = oy + Y(RND25) / S
        lyr, lyc = oy + Y(7.4) / S, oy + Y(5.2) / S
        lx = x + 70
        dd = ImageDraw.Draw(base)
        dd.line([(x + 6, yr - 6), (lx - 10, lyr + 4)], fill=mix(BG, RANDOM_C, hl), width=2)
        dd.line([(x + 6, yc - 6), (lx - 10, lyc + 4)], fill=mix(BG, ACCENT_L, hl), width=2)
        text(base, (lx, lyr), f"Random +{RND25:.1f}%", font(28, "bold"), TEXT, hl, "lm")
        text(base, (lx, lyc), f"Calibra +{CAL25:.1f}%", font(28, "bold"), ACCENT_L, hl, "lm")


def bench_bars(base, t):
    a = ease(prog(t, 0.2, 0.5))
    rrect(base, BARP, 14, fill=PANEL, outline=BORDER, width=2, alpha=a)
    text(base, (BARP[0] + 32, BARP[1] + 30), "Rare behaviors kept at 25%", font(30, "bold"), TEXT, a)
    text(base, (BARP[0] + 32, BARP[1] + 70), "Training episodes in the sparsest 15%", font(22, "regular"), MUTED, a)
    text(base, (BARP[0] + 32, BARP[1] + 98), "of action space", font(22, "regular"), MUTED, a)
    g = ease_io(prog(t, 5.0, 1.2))
    bw, gap = 150, 70
    base_y = BARP[3] - 110
    maxh = 400
    bx = BARP[0] + (BARP[2] - BARP[0] - 2 * bw - gap) / 2
    for i, (name, v, c) in enumerate((("Calibra", RARE_CAL, ACCENT_L), ("Random", RARE_RND, RANDOM_C))):
        x = bx + i * (bw + gap)
        h = maxh * v / 100 * g
        if h > 1:
            rrect(base, (x, base_y - h, x + bw, base_y), 10, fill=c if i == 0 else (88, 88, 85), alpha=a)
        text(base, (x + bw / 2, base_y - h - 30), f"{v * g:.0f}%", font(40, "bold"), TEXT if i else ACCENT_L,
             a * ease(prog(t, 5.2, 0.5)), "mm")
        text(base, (x + bw / 2, base_y + 34), name, font(24, "medium"), MUTED, a, "mm")
    text(base, (BARP[0] + (BARP[2] - BARP[0]) / 2, BARP[3] - 34), f"random: mean of {N_RANDOM_SEEDS} seeds",
         font(18, "regular"), DIM, a, "mm")


def scene_bench(t: float) -> Image.Image:
    base = Image.new("RGBA", (W, H), BG + (255,))
    split = 8.0
    if t < split + 0.5:
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        eyebrow(lay, "STEP 2  ·  BENCHMARK ON LEROBOT/PUSHT", "Train on everything, or on Calibra's 25%?", 0.0, t)
        bench_tiles(lay, t)
        fa = 1 - ease(prog(t, split, 0.5))
        if fa < 1:
            lay.putalpha(lay.getchannel("A").point(lambda v: int(v * fa)))
        base.alpha_composite(lay)
    if t >= split:
        lay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        tt = t - split - 0.3
        eyebrow(lay, "STEP 2  ·  BENCHMARK ON LEROBOT/PUSHT", "Small budgets: Calibra stays closest to full data",
                0.0, tt)
        bench_chart(lay, tt)
        bench_bars(lay, tt)
        fa = ease(prog(tt, 1.0, 0.6))
        text(lay, (W / 2, 906), f"Offline metric: BC-MLP action-prediction MSE on {N_TEST} held-out episodes, "
             f"not closed-loop policy success.", font(22, "regular"), MUTED, fa, "mm")
        text(lay, (W / 2, 938), "Source: experiments/figures/benchmark_lerobot_pusht.json (Calibra v0.8.0 run)",
             font(20, "mono"), DIM, fa, "mm")
        base.alpha_composite(lay)
    return base


# ── scene 4: key result (42 - 52.4) ──────────────────────────────────────────
def scene_result(t: float) -> Image.Image:
    base = Image.new("RGBA", (W, H), BG + (255,))
    a0 = ease(prog(t, 0.0, 0.5))
    text(base, (W / 2, 120), "KEY RESULT  ·  LEROBOT/PUSHT", font(24, "bold"), ACCENT_L, a0, "mm")
    cx = [W / 2 - 430, W / 2 + 430]
    a1 = ease(prog(t, 0.4, 0.7))
    a2 = ease(prog(t, 1.2, 0.7))
    # count-up
    v1 = 25 * ease(prog(t, 0.4, 1.0))
    v2 = CAL25 * ease(prog(t, 1.2, 1.0))
    text(base, (cx[0], 330 + 20 * (1 - a1)), f"{v1:.0f}%", font(220, "bold"), ACCENT_L, a1, "mm")
    text(base, (cx[0], 480), "of the training data", font(38, "medium"), TEXT, a1, "mm")
    text(base, (cx[0], 528), f"{K25} of {N_TRAIN} episodes", font(28, "regular"), MUTED, a1, "mm")
    text(base, (cx[1], 330 + 20 * (1 - a2)), f"{v2:.1f}%", font(220, "bold"), TEXT, a2, "mm")
    text(base, (cx[1], 480), "higher prediction error", font(38, "medium"), TEXT, a2, "mm")
    text(base, (cx[1], 526), "than full-data training", font(38, "medium"), TEXT, a2, "mm")
    text(base, (cx[1], 574), f"held-out MSE {ROW25['calibra_mse']:.1f} vs {FULL_MSE:.1f}", font(28, "regular"),
         MUTED, a2, "mm")
    rrect(base, (W / 2 - 1, 230, W / 2 + 1, 586), 0, fill=BORDER, alpha=a1)
    a3 = ease(prog(t, 2.6, 0.6))
    rrect(base, (W / 2 - 640, 610, W / 2 + 640, 760), 16, fill=PANEL, outline=BORDER, width=2, alpha=a3)
    text(base, (W / 2, 654), f"Random 25% subsets: +{RND25:.1f}%  (mean of {N_RANDOM_SEEDS} seeds)", font(32, "medium"),
         TEXT, a3, "mm")
    a4 = ease(prog(t, 3.6, 0.6))
    text(base, (W / 2, 714), f"Separate {N_SEEDS_TARGETED}-seed run: Calibra beats random at 25%, "
         f"paired t-test p = {P_TARGETED:.3f}", font(28, "regular"), MUTED, a4, "mm")
    a5 = ease(prog(t, 4.4, 0.6))
    text(base, (W / 2, 830), f"Behavior cloning MLP, 120 epochs, {N_TRAIN} train / {N_TEST} held-out episodes. Offline "
         f"action-prediction error, not policy success rate.", font(22, "regular"), MUTED, a5, "mm")
    text(base, (W / 2, 864), "experiments/figures/benchmark_lerobot_pusht.json  ·  targeted_lerobot_pusht.json",
         font(19, "mono"), DIM, a5, "mm")
    return base


# ── scene 5: CTA (52 - 59) ───────────────────────────────────────────────────
def scene_cta(t: float) -> Image.Image:
    base = Image.new("RGBA", (W, H), BG + (255,))
    a0 = ease(prog(t, 0.2, 0.7))
    lg = logo_rgba(420)
    if a0 < 1:
        lg.putalpha(lg.getchannel("A").point(lambda v: int(v * a0)))
    base.alpha_composite(lg, (int(W / 2 - lg.width / 2), int(190 + 14 * (1 - a0))))
    a1 = ease(prog(t, 0.7, 0.6))
    text(base, (W / 2, 440), "Have a robotics dataset?", font(76, "bold"), TEXT, a1, "mm")
    a2 = ease(prog(t, 1.3, 0.6))
    text(base, (W / 2, 528), "Let's test Calibra on it.", font(52, "medium"), ACCENT_L, a2, "mm")
    a3 = ease(prog(t, 2.0, 0.6))
    url = "github.com/Calibra-Robotics/Calibra"
    f = font(40, "monobold")
    w_ = text_w(url, f)
    rrect(base, (W / 2 - w_ / 2 - 44, 618, W / 2 + w_ / 2 + 44, 712), 47, fill=(26, 12, 44), outline=ACCENT,
          width=3, alpha=a3)
    text(base, (W / 2, 665), url, f, TEXT, a3, "mm")
    a4 = ease(prog(t, 2.6, 0.6))
    text(base, (W / 2, 790), "pip install calibra-robotics   ·   open-source core, Apache 2.0", font(26, "mono"), MUTED,
         a4, "mm")
    return base


# ── timeline + captions ──────────────────────────────────────────────────────
SCENES = [  # (start, end, fn); neighbours overlap by 0.4s for crossfades
    (0.0, 8.4, scene_hook),
    (8.0, 22.4, scene_workflow),
    (22.0, 42.4, scene_bench),
    (42.0, 52.4, scene_result),
    (52.0, DURATION, scene_cta),
]
XF = 0.4

CAPTIONS = [
    (0.6, 7.8, "Robot learning teams train on every demonstration they collect."),
    (8.4, 14.0, "Calibra audits the dataset first: integrity, quality and coverage."),
    (14.0, 21.8, "Then it keeps a diverse 25%: quality filter plus greedy max-coverage selection."),
    (22.4, 29.8, f"PushT benchmark: all {N_TRAIN} training episodes vs. Calibra's {K25}."),
    (30.2, 41.8, "At 5 to 25% budgets, Calibra subsets stay closer to full-data error than random subsets."),
    (42.4, 51.8, "75% less training data. Only 0.8% higher prediction error than full-data training."),
    (52.4, DURATION + 1.0, "Have a robotics dataset? Let's test Calibra on it."),
]


def draw_caption(base, t):
    for t0, t1, s in CAPTIONS:
        if t0 - 0.3 <= t <= t1 + 0.3:
            a = min(ease(prog(t, t0 - 0.3, 0.3)), 1 - ease(prog(t, t1, 0.3)))
            f = font(30, "medium")
            w_ = text_w(s, f)
            rrect(base, (W / 2 - w_ / 2 - 28, 978, W / 2 + w_ / 2 + 28, 1036), 12, fill=(0, 0, 0), alpha=0.72 * a)
            text(base, (W / 2, 1007), s, f, TEXT, a, "mm")


def render(t: float) -> Image.Image:
    active = [(s, e, fn) for s, e, fn in SCENES if s <= t < e or (t >= DURATION - 1e-6 and e == DURATION)]
    if len(active) == 1:
        img = active[0][2](t - active[0][0])
    else:
        (s1, e1, f1), (s2, e2, f2) = active[:2]
        w = ease_io((t - s2) / XF)
        img = Image.blend(f1(t - s1), f2(t - s2), w)
    draw_caption(img, t)
    return img.convert("RGB")


def render_bytes(i: int) -> bytes:
    return render(i / FPS).tobytes()


def write_srt(path: Path) -> None:
    def ts(x):
        ms = int(round(x * 1000))
        return f"{ms // 3600000:02d}:{ms // 60000 % 60:02d}:{ms // 1000 % 60:02d},{ms % 1000:03d}"

    lines = []
    for i, (t0, t1, s) in enumerate(CAPTIONS, 1):
        lines += [str(i), f"{ts(t0)} --> {ts(min(t1, DURATION))}", s, ""]
    path.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", required=True)
    ap.add_argument("--stills", nargs="*", type=float)
    ap.add_argument("--out", default=str(DV / "calibra-demo.mp4"))
    ap.add_argument("--workers", type=int, default=8)
    args = ap.parse_args()
    init_frames(args.frames)
    print(f"cal25={CAL25:.3f}% rnd25={RND25:.3f}% p={P_TARGETED:.4f} seeds={N_SEEDS_TARGETED} "
          f"rare cal={RARE_CAL:.1f} rnd={RARE_RND:.1f}", file=sys.stderr)
    if args.stills:
        sd = DV / "build/stills"
        sd.mkdir(parents=True, exist_ok=True)
        for s in args.stills:
            render(s).save(sd / f"t{s:05.1f}.png")
            print("still", s, file=sys.stderr)
        return
    write_srt(DV / "calibra-demo.srt")
    n = int(round(DURATION * FPS))
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", str(FPS),
           "-i", "-", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo", "-shortest",
           "-c:v", "libx264", "-preset", "slow", "-crf", "17", "-pix_fmt", "yuv420p", "-profile:v", "high",
           "-tune", "animation", "-c:a", "aac", "-b:a", "96k", "-movflags", "+faststart", args.out]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    with Pool(args.workers, initializer=init_frames, initargs=(args.frames,)) as pool:
        for i, buf in enumerate(pool.imap(render_bytes, range(n), chunksize=4)):
            proc.stdin.write(buf)
            if i % 150 == 0:
                print(f"frame {i}/{n}", file=sys.stderr)
    proc.stdin.close()
    proc.wait()
    print("wrote", args.out, file=sys.stderr)


if __name__ == "__main__":
    main()
