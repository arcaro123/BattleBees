"""
THE BATTLEBEES - Joc estil "Battle Cats" amb abelles (Pygame): 24 nivells fins a la Vespa Reina.

TOT en un sol fitxer: els sprites (pixel art amb llum i ombres) i el so/música es generen per codi
la primera vegada i es guarden en memòria cau (carpeta ~/.bee_battle) per arrencar de pressa.

Instal·lació:   pip install pygame pillow
Execució:       python main.py
Exportar PNG:   python main.py --export        (guarda tots els sprites a ./sprites/)
Equilibrar:     python main.py --simulate      (sense gràfics: % de victòries i temps per nivell)
                  opcions: --runs N  --stage S  --lv L  --legends

Menú: Comença, Millora, Equipa, Missions, Càpsules, Bestiari, Estadístiques i Opcions.
La partida es desa sola a ~/.bee_battle/savegame.json (amb còpia de seguretat).

A la batalla:
  1-5 (o clic als botons) -> generar abelles de l'equip
  W (o clic)              -> millorar el rusc (més diners)
  ESPAI (o clic)          -> trompa de pol·len (quan estigui carregat)
  Q / E                   -> habilitats: Eixam (abelles gratis) / Cura
  TAB                     -> velocitat x1 / x2
  ESC o P                 -> pausa (Continua / Abandona)
  F11                     -> pantalla completa
"""
import array
import colorsys
import hashlib
import math
import os
import pickle
import random
import sys
import zlib
import asyncio

import pygame
from PIL import Image, ImageDraw  # pip install pillow

WEB = sys.platform == "emscripten"

def data_dir():
    """Carpeta de dades: al navegador, la que ve empaquetada amb el joc."""
    d = os.environ.get("BATTLEBEES_DATA")
    if not d and WEB:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_assets")
    if not d:
        d = os.path.join(os.path.expanduser("~"), ".bee_battle")
    try:
        os.makedirs(d, exist_ok=True)
        return d
    except OSError:
        return os.path.dirname(os.path.abspath(__file__))


# =====================================================================
#  MOTOR DE PIXEL ART (generat per codi)
# =====================================================================
# >>> ART_START
F = 0.5       # resolució: cada píxel del sprite = PIX x PIX píxels a pantalla
PIX = 2
DITH = 0.55       # intensitat del tramat (menys = ombres més suaus)
RAMP_N = 5        # nombre de tons per rampa
BAYER = [[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]
LIGHT = (-0.52, -0.68, 0.52)          # la llum ve de dalt a l'esquerra
_ln = math.sqrt(sum(v * v for v in LIGHT))
LIGHT = tuple(v / _ln for v in LIGHT)

# ---- animació: cicle de NF fotogrames + 2 poses d'atac (preparar / colpejar)
NF = 6


def _fi(frame):
    return frame if frame < NF else 0


def cyc(frame):
    return 2 * math.pi * _fi(frame) / NF


def wv(frame, amp=1.0, shift=0.0):
    return amp * math.sin(cyc(frame) + shift)


def wt(frame):
    """1 = ales amunt ... 0 = ales avall."""
    if frame == NF:
        return 1.0
    if frame == NF + 1:
        return 0.3
    return 0.5 + 0.5 * math.cos(cyc(frame))


def lerp_pts(a, b, t):
    return [(p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t) for p, q in zip(a, b)]


def h2(x, y, s=0):
    n = (int(x) * 374761393 + int(y) * 668265263 + s * 982451653) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n ^= n >> 16
    return (n & 0xFFFF) / 65535.0


def vnoise(x, y, s=0):
    xi, yi = math.floor(x), math.floor(y)
    xf, yf = x - xi, y - yi
    xf, yf = xf * xf * (3 - 2 * xf), yf * yf * (3 - 2 * yf)
    a, b, c, d = h2(xi, yi, s), h2(xi + 1, yi, s), h2(xi, yi + 1, s), h2(xi + 1, yi + 1, s)
    return a + (b - a) * xf + (c - a) * yf + (a - b - c + d) * xf * yf


def fbm(x, y, s=0, octaves=3):
    tot, amp, fr, norm = 0.0, 1.0, 1.0, 0.0
    for o in range(octaves):
        tot += vnoise(x * fr, y * fr, s + o * 17) * amp
        norm += amp
        amp *= 0.5
        fr *= 2.0
    return tot / norm


def _hmix(h, target, a):
    d = ((target - h + 0.5) % 1.0) - 0.5
    return (h + d * a) % 1.0


def make_ramp(base, n=None):
    n = RAMP_N if n is None else n
    """Rampa de to amb 'hue shifting': ombres fredes i foscos, llums càlides."""
    r, g, b = [v / 255 for v in base[:3]]
    h, s, v = colorsys.rgb_to_hsv(r, g, b)
    out = []
    for i in range(n):
        t = i / (n - 1)
        if t < 0.5:
            k = (0.5 - t) / 0.5
            vv, hh, ss = v * (1 - 0.62 * k), _hmix(h, 0.70, 0.10 * k), max(min(1, s * (1 + 0.12 * k)), 0.07 * k)
        else:
            k = (t - 0.5) / 0.5
            vv, hh, ss = min(1, v * (1 + 0.26 * k) + 0.11 * k), _hmix(h, 0.12, 0.12 * k), s * (1 - 0.28 * k)
        rr, gg, bb = colorsys.hsv_to_rgb(hh, ss, vv)
        out.append((int(rr * 255), int(gg * 255), int(bb * 255), 255))
    return out


def OLC(ramp, k=0.5):
    return tuple(int(c * k) for c in ramp[0][:3]) + (255,)


def lite(c, f):
    return tuple(int(v + (255 - v) * f) for v in c[:3]) + (255,)


def dark(c, f):
    return tuple(int(v * (1 - f)) for v in c[:3]) + (255,)


def _ri(ramp, i):
    """Índex d'una rampa de 5 tons escalat a la longitud real."""
    return int(round(i * (len(ramp) - 1) / 4.0))


def pick(ramp, t, px, py, dith=None):
    dith = DITH if dith is None else dith
    n = len(ramp)
    f = t * (n - 1) + ((BAYER[py & 3][px & 3] + 0.5) / 16 - 0.5) * dith
    i = int(f + 0.5)
    return ramp[0 if i < 0 else (n - 1 if i >= n else i)]


def ell_pts(cx, cy, rx, ry, ang=0.0, n=44):
    ca, sa = math.cos(ang), math.sin(ang)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        x, y = rx * math.cos(t), ry * math.sin(t)
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def rot(pts, px, py, a):
    ca, sa = math.cos(a), math.sin(a)
    return [(px + (x - px) * ca - (y - py) * sa, py + (x - px) * sa + (y - py) * ca) for x, y in pts]


class Canvas:
    """Llenç en 'unitats' (p.ex. 100x80). Cada unitat = F*scale píxels."""

    def __init__(self, w, h, scale=1.0, f=None):
        f = F if f is None else f
        self.k = scale * f
        self.w = max(1, round(w * self.k))
        self.h = max(1, round(h * self.k))
        self.im = Image.new("RGBA", (self.w, self.h), (0, 0, 0, 0))
        self.d = ImageDraw.Draw(self.im)

    def P(self, pts):
        return [(x * self.k, y * self.k) for x, y in pts]

    def poly(self, pts, col):
        self.d.polygon(self.P(pts), fill=tuple(col))

    def line(self, pts, col, wpx=1):
        self.d.line(self.P(pts), fill=tuple(col), width=wpx)

    def put(self, x, y, col):
        px, py = int(x * self.k), int(y * self.k)
        if 0 <= px < self.w and 0 <= py < self.h:
            self.im.putpixel((px, py), tuple(col))

    def layer(self):
        return Image.new("RGBA", self.im.size, (0, 0, 0, 0))

    def comp(self, layer):
        self.im.alpha_composite(layer)

    def paint(self, pts, fn, ol=None):
        P = self.P(pts)
        if ol is not None:
            self.d.line(P + [P[0]], fill=tuple(ol), width=3, joint="curve")
        m = Image.new("L", self.im.size, 0)
        ImageDraw.Draw(m).polygon(P, fill=255)
        box = m.getbbox()
        if not box:
            return
        mp, pix, k = m.load(), self.im.load(), self.k
        for py in range(box[1], box[3]):
            for px in range(box[0], box[2]):
                if mp[px, py]:
                    col = fn((px + 0.5) / k, (py + 0.5) / k, px, py)
                    if col is not None:
                        pix[px, py] = col

    def result(self):
        return self.im


def sh_ell(cx, cy, rx, ry, ang, ramp, fur=0.0, gloss=False, seed=0, rim=0.3, amb=0.2, tone=0.0):
    ca, sa = math.cos(ang), math.sin(ang)
    hi = lite(ramp[-1], 0.7)

    def fn(x, y, px, py):
        dx, dy = x - cx, y - cy
        u, v = (dx * ca + dy * sa) / rx, (-dx * sa + dy * ca) / ry
        r2 = min(1.0, u * u + v * v)
        z = math.sqrt(1 - r2)
        nx, ny = u * ca - v * sa, u * sa + v * ca
        lam = nx * LIGHT[0] + ny * LIGHT[1] + z * LIGHT[2]
        t = amb + (1 - amb) * max(0.0, lam) - rim * r2 ** 4 + tone
        if fur:
            t += (h2(px, py, seed) - 0.5) * fur
        if gloss and lam > 0.9 and r2 < 0.8:
            return hi
        return pick(ramp, t, px, py)
    return fn


def ep(c, cx, cy, rx, ry, base, ang=0.0, fur=0.0, gloss=False, seed=0, ol=True, tone=0.0, rim=0.3):
    ramp = base if isinstance(base, list) else make_ramp(base)
    c.paint(ell_pts(cx, cy, rx, ry, ang), sh_ell(cx, cy, rx, ry, ang, ramp, fur, gloss, seed, rim, 0.2, tone),
            OLC(ramp) if ol else None)


def pp(c, pts, base, ol=True, fur=0.0, seed=0, top=True):
    """Polígon amb degradat vertical suau (banyes, banyes, cossos angulosos)."""
    ramp = base if isinstance(base, list) else make_ramp(base)
    ys = [p[1] for p in pts]
    y0, y1 = min(ys), max(ys)

    def fn(x, y, px, py):
        t = (y - y0) / max(1e-6, y1 - y0)
        t = 0.78 - 0.55 * t if top else 0.5
        if fur:
            t += (h2(px, py, seed) - 0.5) * fur
        return pick(ramp, t, px, py)
    c.paint(pts, fn, OLC(ramp) if ol else None)


def body_pts(x0, x1, cy, hw, peak=0.6, n_tail=1.6, n_head=2.4, steps=30):
    L = x1 - x0
    top = []
    for i in range(steps + 1):
        t = i / steps
        if t < peak:
            u, n = (peak - t) / peak, n_tail
        else:
            u, n = (t - peak) / (1 - peak), n_head
        top.append((x0 + L * t, cy - hw * max(0.0, 1 - u ** n) ** (1 / n)))
    return top + [(x, 2 * cy - y) for x, y in reversed(top)]


def sh_abd(x0, x1, cy, hw, peak, nt, nh, tilt, ramp, bands, fur, gloss, seed, grooves=0):
    ca, sa = math.cos(tilt), math.sin(tilt)
    L, xm = x1 - x0, (x0 + x1) / 2
    hi = lite(ramp[-1], 0.7)

    def prof(xx):
        t = (xx - x0) / L
        if t <= 0 or t >= 1:
            return 0.5
        if t < peak:
            u, n = (peak - t) / peak, nt
        else:
            u, n = (t - peak) / (1 - peak), nh
        return max(0.5, hw * max(0.0, 1 - u ** n) ** (1 / n))

    def fn(x, y, px, py):
        dx, dy = x - x1, y - cy
        xx, yy = x1 + dx * ca + dy * sa, cy - dx * sa + dy * ca
        v = max(-1.0, min(1.0, (yy - cy) / prof(xx)))
        z = math.sqrt(1 - v * v)
        nx = ((xx - xm) / (L / 2)) * 0.4
        lam = nx * LIGHT[0] + v * LIGHT[1] + z * LIGHT[2]
        t = 0.2 + 0.8 * max(0.0, lam) - 0.22 * abs(v) ** 5
        if grooves and ((xx - x0) % grooves) < 0.9 and abs(v) < 0.96:
            t -= 0.13
        if fur:
            t += (h2(px, py, seed) - 0.5) * fur
        r = ramp
        for bx, bw, br in bands:
            if abs(xx - bx) <= bw / 2:
                r = br
                break
        if gloss and lam > 0.9 and abs(v) < 0.7:
            return lite(r[-1], 0.7)
        return pick(r, t, px, py)
    return fn


def lens(px, py, a, L, Wd, steps=16):
    r = math.radians(a)
    dx, dy = math.cos(r), -math.sin(r)
    nx, ny = -dy, dx
    top, bot = [], []
    for i in range(steps + 1):
        t = i / steps
        w = Wd / 2 * (math.sin(math.pi * t ** 0.72)) ** 0.9
        cx, cy = px + dx * L * t, py + dy * L * t
        top.append((cx + nx * w, cy + ny * w))
        bot.append((cx - nx * w, cy - ny * w))
    return top + bot[::-1]


WING_ANGS = ((112, 74), (136, 50), (160, 28))


def wings(c, px, py, frame, L, Wd, fill, edge, angs=WING_ANGS, blur=0):
    layer = c.layer()
    ld = ImageDraw.Draw(layer)
    t_ = wt(frame)
    if blur:       # estela de moviment: dues posicions fantasma de l'ala
        for dt_ in (-0.32, 0.32):
            tt = max(0.0, min(1.0, t_ + dt_))
            for idx in range(2):
                a = angs[2][idx] + (angs[0][idx] - angs[2][idx]) * tt
                l_, w_ = (L, Wd) if idx == 0 else (L * 0.8, Wd * 0.85)
                ld.polygon(c.P(lens(px, py, a, l_, w_)), fill=(fill[0], fill[1], fill[2], 38))
    for idx in range(2):
        a = angs[2][idx] + (angs[0][idx] - angs[2][idx]) * t_
        l_, w_ = (L, Wd) if idx == 0 else (L * 0.8, Wd * 0.85)
        pts = lens(px, py, a, l_, w_)
        P = c.P(pts)
        ld.polygon(P, fill=tuple(fill))
        r = math.radians(a)
        vein = (edge[0], edge[1], edge[2], 130)
        ld.line(c.P([(px, py), (px + math.cos(r) * l_ * 0.9, py - math.sin(r) * l_ * 0.9)]), fill=vein, width=1)
        for fr_, sp_ in ((0.45, 0.28), (0.7, 0.22)):
            mx, my = px + math.cos(r) * l_ * fr_, py - math.sin(r) * l_ * fr_
            nx, ny = -math.sin(r), -math.cos(r)
            ld.line(c.P([(mx, my), (mx + nx * w_ * sp_, my + ny * w_ * sp_)]), fill=vein, width=1)
        ld.line(P + [P[0]], fill=tuple(edge), width=1)
        hx = px + math.cos(r) * l_ * 0.55 - math.sin(r) * w_ * 0.18
        hy = py - math.sin(r) * l_ * 0.55 - math.cos(r) * w_ * 0.18
        ld.point((int(hx * c.k), int(hy * c.k)), fill=(255, 255, 255, 185))
    c.comp(layer)


def eye(c, cx, cy, rx, ry, ang=0.0, tint=(235, 230, 215), base=(30, 25, 30)):
    ramp = make_ramp(base)
    ca, sa = math.cos(ang), math.sin(ang)

    def fn(x, y, px, py):
        dx, dy = x - cx, y - cy
        u, v = (dx * ca + dy * sa) / rx, (-dx * sa + dy * ca) / ry
        r2 = u * u + v * v
        if r2 > 1:
            return None
        return ramp[_ri(ramp, 1)] if ((px + py) & 1) == 0 and r2 < 0.85 else ramp[0]
    c.paint(ell_pts(cx, cy, rx, ry, ang), fn, None)
    c.put(cx - rx * 0.30, cy - ry * 0.42, tint + (255,) if len(tint) == 3 else tint)
    c.put(cx + rx * 0.15, cy + ry * 0.35, lite(ramp[_ri(ramp, 2)], 0.3))


def tufts(c, pts, ramp, n, seed):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = pts[rnd.randrange(len(pts))]
        c.put(x + rnd.uniform(-1.5, 1.5), y + rnd.uniform(-1.5, 1.5), ramp[_ri(ramp, rnd.choice((2, 3, 3, 4)))])


# ---------------------------------------------------------------- ABELLES
def pad(im, n=6):
    out = Image.new("RGBA", (im.width + 2 * n, im.height), (0, 0, 0, 0))
    out.paste(im, (n, 0))
    return out


def lean(im, k):
    """Inclina el sprite fila a fila (k px a dalt): pose de preparar/colpejar."""
    box = im.getchannel("A").getbbox()
    out = Image.new("RGBA", im.size, (0, 0, 0, 0))
    if not box:
        return out
    y0, y1 = box[1], box[3]
    for y in range(y0, y1):
        sh = int(round(k * (y1 - 1 - y) / max(1, y1 - y0)))
        out.paste(im.crop((0, y, im.width, y + 1)), (sh, y))
    return out


def bee(sp, frame):
    pose = 0 if frame < NF else frame - NF + 1       # 0 = cicle, 1 = preparar, 2 = picada
    sc = sp.get("scale", 1.0)
    c = Canvas(100, 80, sc)
    ar, tr_, hr = make_ramp(sp["abd_col"]), make_ramp(sp["thx_col"]), make_ramp(sp["head_col"])
    x0, x1, cy, hw = sp["abd"]
    hw = hw * (1 + sp.get("heave", 0.035) * wv(frame, 1, 1.2))
    tilt = sp.get("tilt", -0.14) + (0.3 if pose == 1 else (-0.5 if pose == 2 else sp.get("tilt_amp", 0.04) * wv(frame, 1, 0.6)))
    tx, ty, trx, try_ = sp["thx"]
    hx, hy, hrx, hry = sp["head"]
    ty += wv(frame, sp.get("thx_bob", 0.0), 0.3)
    hy += wv(frame, sp.get("head_bob", 0.0), 0.9)
    dk = sp.get("ol") or OLC(ar)
    legc = OLC(tr_, 0.85)
    pk, nt, nh = sp.get("peak", 0.6), sp.get("n_tail", 1.6), sp.get("n_head", 2.4)
    ABD = rot(body_pts(x0, x1, cy, hw, pk, nt, nh), x1, cy, tilt)
    tail = rot([(x0 + 2, cy)], x1, cy, tilt)[0]
    if sp.get("stinger", True):
        ln = 8 + (4 if pose == 2 else 0)
        c.poly([(tail[0] + 3, tail[1] - 2), (tail[0] - ln + 3, tail[1] + 2.5 + (2 if pose == 2 else 0)),
                (tail[0] + 3, tail[1] + 2)], dk)
    j = wv(frame, sp.get("leg_amp", 2.5))
    leg_w = sp.get("leg_w", 1)
    for i, (lx, dx) in enumerate(((tx - 8, -5), (tx - 1, 0), (tx + 6, 6))):
        jj = j * (1 if i % 2 else -1)
        y0 = ty + try_ - 4
        if pose == 2:
            pts = [(lx, y0), (lx + dx * 0.4, y0 + 4), (lx + dx * 0.5, y0 + 8)]
        else:
            pts = [(lx, y0), (lx + dx * 0.5, y0 + 5), (lx + dx * 0.9 + jj * 0.6, y0 + 9), (lx + dx + jj, y0 + 13)]
        c.line(pts, legc, leg_w)
        c.put(pts[-1][0] + 1.5, pts[-1][1] + 1, legc)
    if sp.get("pollen"):
        ep(c, tx - 7, ty + try_ + 2, 4.6, 3.6, sp["pollen"], seed=9, fur=0.5)
    bands = [(bx, bw, make_ramp(bc)) for bx, bw, bc in sp.get("bands", [])]
    c.paint(ABD, sh_abd(x0, x1, cy, hw, pk, nt, nh, tilt, ar, bands, sp.get("fur_abd", 0.0), sp.get("gloss", False), 2,
                        sp.get("grooves", 7)), dk)
    if sp.get("tufts_abd"):
        tufts(c, [p for p in ABD[::2]], ar, 26, 3)
    if sp.get("tail"):
        sp["tail"](c)
    ep(c, tx, ty, trx, try_, tr_, fur=sp.get("fur_thx", 0.55), seed=4, ol=True)
    if sp.get("fuzz_thx"):
        tufts(c, ell_pts(tx, ty, trx, try_, 0, 22), tr_, 22, 5)
    ep(c, hx, hy, hrx, hry, hr, fur=0.2, seed=6)
    sw = wv(frame, 1.6, 0.8) if pose == 0 else (-2.0 if pose == 1 else 3.0)
    for off in (0, 3):
        c.line([(hx + off, hy - hry + 1), (hx + off + 4 + sw * 0.4, hy - hry - 7 + (3 if pose == 2 else 0)),
                (hx + off + 10 + sw, hy - hry - 9 - off * 0.4 + (4 if pose == 2 else 0))], dk)
    if sp.get("petiole"):
        ep(c, x1 + 2.5, cy + 1, 4.0, 3.0, ar, ol=True)
    eye(c, hx + 2.6, hy - 0.8, hrx * 0.66, hry * 0.78, base=sp.get("eye_col", (30, 25, 30)))
    if sp.get("angry"):
        c.line([(hx - 1, hy - hry * 0.9), (hx + hrx + 1, hy - 1.5)], dk, 1)
    op = 4 if pose == 2 else 0
    c.line([(hx + hrx - 1, hy + hry - 2), (hx + hrx + 3 + op, hy + hry + op * 0.8)], dk, 1)
    if pose == 2:
        c.line([(hx + hrx - 2, hy + hry - 1), (hx + hrx + 2, hy + hry + 3)], dk, 1)
    if sp.get("extra"):
        sp["extra"](c, frame)
    f0 = sp.get("wing_fill", (212, 226, 238, 96))
    wings(c, tx - 1, ty - try_ + 3, frame, sp.get("wing_len", 32), sp.get("wing_w", 10),
          (f0[0], f0[1], f0[2], max(40, f0[3] + int(28 * (wt(frame) - 0.5)))), sp.get("wing_edge", (96, 112, 134, 215)),
          blur=sp.get("wing_blur", 0))
    out = c.result()
    dxp = (0, -1, 2)[pose]
    if dxp:
        sh = Image.new("RGBA", out.size, (0, 0, 0, 0))
        sh.paste(out, (dxp, 0))
        out = sh
    return out


def _mud_ball(c, frame):
    ep(c, 84, 55 + (1 if wv(frame, 1) > 0.3 else 0), 5.5, 5.5, (116, 82, 56), fur=0.6, seed=11)


def _leaf_piece(c, frame):
    pts = [(74, 58), (84, 51), (94, 54), (92, 62), (82, 64)]
    pp(c, pts, (88, 130, 72), fur=0.3, seed=12)
    c.line([(76, 59), (92, 57)], (42, 78, 40))


def _crown(c, frame):
    pts = [(66, 36), (66, 26), (70, 31), (73, 23), (76, 31), (80, 26), (80, 36)]
    pp(c, pts, (226, 190, 70))
    c.put(73, 25, (255, 244, 190, 255))
    c.put(66, 28, (255, 244, 190, 255))
    c.put(80, 28, (255, 244, 190, 255))


def _mason_tuft(c):
    pp(c, [(8, 46), (18, 44), (18, 54), (8, 53)], (176, 104, 58), fur=0.6, seed=14)


BEES = {
    "honey": dict(abd=(8, 52, 49, 12), peak=0.62, abd_col=(214, 164, 52),
                  bands=[(24, 6, (52, 38, 28)), (34, 6, (52, 38, 28)), (44, 5, (52, 38, 28))],
                  thx=(56, 43, 11, 10), thx_col=(156, 110, 56), fuzz_thx=1, pollen=(222, 182, 62),
                  head=(70, 44, 7.5, 8), head_col=(82, 60, 42), scale=1.0, wing_len=34, wing_w=11),
    "bumble": dict(abd=(4, 54, 51, 19), peak=0.55, n_tail=2.0, abd_col=(40, 36, 36), fur_abd=0.55, tufts_abd=1,
                   bands=[(36, 12, (206, 168, 62)), (12, 14, (216, 212, 202))],
                   thx=(60, 43, 13, 12), thx_col=(208, 172, 66), fuzz_thx=1, fur_thx=0.8, pollen=(186, 124, 58),
                   head=(75, 47, 7.5, 8), head_col=(56, 50, 48), scale=1.25, wing_len=26, wing_w=9, tilt=-0.08),
    "carpenter": dict(abd=(2, 54, 49, 14), peak=0.58, n_tail=1.8, abd_col=(44, 42, 84), gloss=True,
                      thx=(60, 42, 12, 10.5), thx_col=(202, 164, 62), fuzz_thx=1,
                      head=(74, 44, 8, 8.5), head_col=(46, 44, 86), scale=1.3,
                      wing_fill=(120, 100, 160, 120), wing_edge=(66, 50, 106, 225), wing_len=40, wing_w=12),
    "sweat": dict(abd=(10, 52, 47, 7.5), peak=0.68, n_tail=1.5, abd_col=(70, 154, 114), gloss=True,
                  bands=[(24, 2.5, (38, 94, 70)), (31, 2.5, (38, 94, 70)), (38, 2.5, (38, 94, 70)),
                         (45, 2.5, (38, 94, 70))],
                  thx=(57, 43, 8, 7.5), thx_col=(90, 172, 130), head=(68, 44, 6, 6.5), head_col=(76, 158, 118),
                  scale=0.95, wing_len=36, wing_w=8, tilt=-0.06),
    "mason": dict(abd=(12, 50, 48, 12.5), peak=0.5, n_tail=2.0, abd_col=(60, 92, 164), gloss=True,
                  thx=(55, 43, 10, 9.5), thx_col=(172, 102, 56), fuzz_thx=1,
                  head=(68, 44, 7, 7.5), head_col=(42, 66, 126), scale=1.05, tail=_mason_tuft, extra=_mud_ball,
                  wing_len=30, wing_w=10),
    "leafcutter": dict(abd=(6, 50, 47, 10), peak=0.62, abd_col=(122, 96, 80),
                       bands=[(20, 4, (214, 204, 188)), (28, 4, (214, 204, 188)), (36, 4, (214, 204, 188)),
                              (44, 3, (214, 204, 188))],
                       thx=(54, 42, 9, 8.5), thx_col=(146, 112, 84), fuzz_thx=1,
                       head=(66, 44, 6.5, 7.5), head_col=(104, 82, 64), scale=0.95, extra=_leaf_piece,
                       wing_len=30, wing_w=9),
    "stingless": dict(abd=(10, 46, 48, 8), peak=0.6, n_tail=1.8, abd_col=(64, 54, 48),
                      bands=[(28, 3, (124, 104, 74)), (36, 3, (124, 104, 74))], stinger=False,
                      thx=(52, 43, 8, 7.5), thx_col=(98, 74, 54), head=(63, 44, 6, 6.5), head_col=(54, 44, 40),
                      scale=0.85, wing_len=26, wing_w=7),
    "orchid": dict(abd=(8, 52, 49, 10), peak=0.66, n_tail=1.5, abd_col=(44, 156, 156), gloss=True,
                   bands=[(24, 2.5, (22, 92, 114)), (32, 2.5, (22, 92, 114)), (40, 2.5, (22, 92, 114))],
                   thx=(58, 43, 9.5, 9), thx_col=(76, 182, 150), head=(71, 44, 7, 7.5), head_col=(54, 166, 166),
                   scale=1.0, wing_len=34, wing_w=8),
    "killer": dict(abd=(8, 52, 49, 12.5), peak=0.6, abd_col=(156, 114, 46),
                   bands=[(20, 7, (32, 24, 18)), (32, 7, (32, 24, 18)), (44, 6, (32, 24, 18))],
                   thx=(56, 43, 11.5, 10.5), thx_col=(90, 64, 36), fuzz_thx=1,
                   head=(70, 44, 7.5, 8), head_col=(44, 34, 26), scale=1.1, wing_len=34, wing_w=11),
    "cuckoo": dict(abd=(4, 52, 49, 13.5), peak=0.58, n_tail=1.9, abd_col=(156, 48, 42), gloss=True,
                   bands=[(20, 5, (36, 26, 26)), (40, 6, (36, 26, 26))],
                   thx=(57, 43, 11.5, 10.5), thx_col=(44, 40, 40), fuzz_thx=1,
                   head=(71, 44, 7.5, 8), head_col=(40, 36, 36), scale=1.1,
                   wing_fill=(126, 116, 106, 120), wing_edge=(64, 56, 48, 220)),
    "bluebanded": dict(abd=(8, 52, 49, 12), peak=0.6, abd_col=(42, 42, 52),
                       bands=[(22, 4, (116, 154, 194)), (31, 4, (116, 154, 194)), (40, 4, (116, 154, 194))],
                       thx=(56, 43, 10.5, 9.5), thx_col=(118, 122, 126), fuzz_thx=1,
                       head=(69, 44, 7.5, 8), head_col=(50, 50, 56), scale=1.0, wing_len=32, wing_w=10),
    "queen": dict(abd=(0, 56, 49, 14.5), peak=0.64, n_tail=1.5, abd_col=(220, 170, 58), gloss=True,
                  bands=[(18, 6, (64, 44, 28)), (29, 6, (64, 44, 28)), (40, 6, (64, 44, 28)), (50, 5, (64, 44, 28))],
                  thx=(60, 43, 11, 10), thx_col=(160, 112, 58), fuzz_thx=1,
                  head=(73, 44, 7, 7.5), head_col=(86, 64, 44), scale=1.5, wing_len=40, wing_w=12, extra=_crown),
}


# ---------------------------------------------------------------- ENEMICS
def _mandibles(c, frame):
    pp(c, [(79, 46), (96, 47), (92, 58), (83, 54)], (66, 40, 26))
    pp(c, [(84, 49), (89, 49), (87, 57)], (214, 208, 190), ol=False)


WASP = dict(abd=(4, 46, 46, 9.5), peak=0.7, n_tail=1.5, abd_col=(208, 176, 52), gloss=True, petiole=True, angry=True,
            bands=[(14, 5, (40, 34, 30)), (22, 5, (40, 34, 30)), (30, 5, (40, 34, 30)), (38, 4, (40, 34, 30))],
            thx=(57, 42, 8.5, 8.5), thx_col=(44, 40, 38), head=(68, 42, 7, 7.5), head_col=(208, 176, 52),
            eye_col=(70, 22, 18), scale=1.2, wing_len=40, wing_w=9, tilt=-0.1,
            wing_fill=(220, 200, 150, 105), wing_edge=(128, 96, 48, 220))
HORNET = dict(abd=(2, 46, 48, 15), peak=0.62, n_tail=1.6, abd_col=(190, 118, 52), petiole=True, angry=True,
              bands=[(14, 6, (76, 48, 30)), (24, 6, (76, 48, 30)), (34, 6, (76, 48, 30)), (44, 5, (76, 48, 30))],
              thx=(57, 42, 11.5, 11), thx_col=(80, 50, 32), fuzz_thx=1, head=(70, 43, 10, 9.5),
              head_col=(210, 134, 58), eye_col=(52, 20, 16), scale=1.5, wing_len=44, wing_w=13, extra=_mandibles,
              wing_fill=(176, 136, 90, 110), wing_edge=(100, 66, 30, 225))


def wasp(frame):
    return bee(WASP, frame)


def hornet(frame):
    return bee(HORNET, frame)


def ant(frame, body=(134, 60, 40), head=(150, 72, 48), scale=1.3):
    c = Canvas(100, 80, scale)
    br = make_ramp(body)
    lg = OLC(br, 0.9)
    s = wv(frame, 4)
    for i, bx in enumerate((42, 50, 58)):
        sg = s if i % 2 == 0 else -s
        c.line([(bx, 48), (bx + (i - 1) * 8 + sg * 0.5, 55), (bx + (i - 1) * 14 + sg * 1.4, 70)], lg)
    ep(c, 22, 47, 16, 11.5, br, 0.05, fur=0.3, seed=3)
    c.line([(18, 38), (17, 56)], OLC(br))
    c.line([(26, 37), (25, 57)], OLC(br))
    ep(c, 40, 48, 3.4, 3.2, br)
    ep(c, 50, 43, 11, 8, br, -0.1, fur=0.25, seed=4)
    ep(c, 47, 38, 5, 3.2, make_ramp(head), ol=False, rim=0)
    ep(c, 72, 44, 11, 9.5, make_ramp(head), fur=0.15, seed=6)
    mo = 1.5 + 1.5 * wv(frame, 1)
    pp(c, [(80, 46), (95, 47 - mo * 0.3), (90, 55 + mo), (82, 52)], (52, 34, 28))
    pp(c, [(83, 47), (92, 48), (88, 52 + mo * 0.5)], (200, 190, 170), ol=False)
    eye(c, 76, 40, 3.2, 3.8, tint=(230, 200, 170))
    c.line([(70, 35), (78, 38.5)], OLC(br), 1)
    for a in (0, 5):
        c.line([(78, 36), (85 + a + wv(frame, 1.2), 26 - a), (93 + a + wv(frame, 2), 28 - a)], lg)
    return c.result()


def spider(frame, scale=1.15, base=(84, 64, 94), head=(100, 78, 110), mark=(176, 134, 66), fur=0.3):
    c = Canvas(100, 80, scale)
    sr = make_ramp(base)
    leg = OLC(sr, 0.85)
    sw = wv(frame, 3)
    for i, fx in enumerate((-30, -14, 6, 24)):
        hx = 46 + i * 4
        c.line([(hx, 44), (hx + fx * 0.3 - 6, 16), (hx + fx + sw * (1 if i % 2 else -1), 70)], dark(leg, 0.25))
    ep(c, 31, 41, 21, 17, sr, 0.05, fur=fur, seed=5)
    pp(c, [(26, 33), (35, 33), (31, 41), (35, 49), (26, 49), (30, 41)], mark, ol=False)
    for i, fx in enumerate((-26, -10, 10, 28)):
        hx = 50 + i * 4
        c.line([(hx, 46), (hx + fx * 0.3 - 4, 22), (hx + fx - sw * (1 if i % 2 else -1), 70)], leg)
    ep(c, 60, 44, 12, 10, make_ramp(head), fur=0.2, seed=7)
    for ex, ey, r_ in ((66, 39, 2.3), (71, 38, 2.0), (67, 44, 1.8), (71.5, 43, 1.6)):
        ep(c, ex, ey, r_, r_, (176, 52, 46), ol=True, rim=0)
        c.put(ex - 0.5, ey - 0.6, (255, 220, 200, 255))
    pp(c, [(67, 50), (71, 50), (69.5, 58)], (222, 218, 206))
    pp(c, [(73, 49), (77, 48), (75.5, 56)], (222, 218, 206))
    return c.result()


def mantis(frame, scale=1.35, base=(116, 146, 72), crown=False):
    c = Canvas(100, 80, scale)
    gr = make_ramp(base)
    lg = OLC(gr, 0.9)
    for i, (bx, dx) in enumerate(((36, -6), (44, 0), (50, 7))):
        j = wv(frame, 3) * (1 if i % 2 else -1)
        c.line([(bx, 48), (bx + dx * 0.5 - 3, 58), (bx + dx * 1.5 + j, 71)], dark(lg, 0.2))
    ep(c, 22, 51, 20, 7.5, gr, -0.08, fur=0.2, seed=6)
    ep(c, 20, 47, 18, 3.5, make_ramp((170, 196, 110)), -0.08, ol=False, rim=0.1)
    ep(c, 47, 41, 17, 5.2, gr, -0.62, fur=0.15, seed=7)
    asw = wv(frame, 2.5, 0.5)
    c.line([(60, 32), (75 + asw * 0.4, 44)], gr[1], 3)
    c.line([(60, 31), (75 + asw * 0.4, 43)], gr[3], 1)
    c.line([(75 + asw * 0.4, 44), (82 + asw, 31 - asw * 0.5)], gr[1], 2)
    for sx in (66, 70, 74):
        c.poly([(sx - 1, 38 + (sx - 66) * 0.6), (sx + 1.5, 38 + (sx - 66) * 0.6), (sx + 2, 44 + (sx - 66) * 0.6)],
               OLC(gr))
    ep(c, 66, 26, 7.5, 6.5, make_ramp((146, 176, 98)), 0.1, fur=0.1, seed=8)
    ep(c, 70, 24.5, 3.8, 4.6, make_ramp((190, 200, 110)), ol=True)
    c.put(70.5, 24.5, (24, 22, 16, 255))
    c.put(69, 22.5, (255, 250, 220, 255))
    if crown:
        for k in range(4):
            pp(c, [(60 + k * 4, 21), (61.5 + k * 4, 10 - (k % 2) * 3), (63 + k * 4, 21)], make_ramp((226, 188, 70)))
    c.line([(65, 20), (62, 8), (66, 4)], lg)
    c.line([(69, 19), (74, 8), (80, 7)], lg)
    return c.result()


def beetle(frame, scale=1.3, base=(104, 64, 42), frost=False):
    c = Canvas(100, 80, scale)
    br = make_ramp(base)
    s = wv(frame, 3)
    for i, bx in enumerate((26, 38, 50)):
        sg = s if i % 2 == 0 else -s
        c.line([(bx, 58), (bx + 4 + sg * 0.4, 64), (bx + 8 + sg, 72)], OLC(br, 0.8), 2)
    ep(c, 40, 44, 29, 21, br, 0, fur=0.12, gloss=True, seed=7)
    c.line([(40, 24), (40, 65)], OLC(br))
    if frost:
        rnd = random.Random(3)
        for _ in range(40):
            c.put(rnd.uniform(14, 66), rnd.uniform(26, 56), (236, 244, 255, 255))
    c.line([(24, 30), (24, 58)], dark(br[1], 0.2))
    ep(c, 64, 46, 9, 15, make_ramp((80, 50, 34)), fur=0.15, seed=8)
    ep(c, 76, 52, 9, 8, make_ramp((62, 38, 28)))
    pp(c, [(74, 47), (79, 31), (89, 21), (92, 26), (85, 36), (83, 49)], (52, 32, 24))
    c.line([(79, 31), (89, 22)], (120, 80, 54, 255), 1)
    eye(c, 79, 49, 2.8, 3, tint=(220, 170, 130))
    return c.result()


def alien(frame):
    c = Canvas(100, 80, 1.25)
    layer = c.layer()
    ld = ImageDraw.Draw(layer)
    for r, a in ((36, 14), (29, 18), (22, 24)):
        ld.polygon(c.P(ell_pts(56, 38, r, r * 0.95)), fill=(126, 180, 136, a))
    c.comp(layer)
    lr = make_ramp((96, 86, 124))
    for i, bx in enumerate((24, 31, 38, 45)):
        pts = [(bx, 56)]
        for s in range(1, 6):
            pts.append((bx - 3 + math.sin(s * 1.3 + i + cyc(frame)) * 5 + (i - 1.5) * 2, 56 + s * 4.5))
        c.line(pts, OLC(lr, 0.9), 1)
        c.put(pts[-1][0], pts[-1][1], (150, 210, 140, 255))
    ep(c, 36, 51, 14, 9.5, lr, 0.12, fur=0.2, seed=9)
    c.put(36, 50, (176, 236, 160, 255))
    c.put(37, 50, (176, 236, 160, 255))
    ep(c, 48, 42, 5, 8, make_ramp((110, 100, 138)), -0.3)
    ep(c, 60, 33, 13, 19, make_ramp((132, 122, 162)), -0.22, fur=0.2, seed=10)
    ep(c, 53, 34, 2.9, 8.6, make_ramp((16, 14, 22)), 0.6, ol=False, rim=0)
    ep(c, 68, 32, 2.8, 8.4, make_ramp((16, 14, 22)), -0.6, ol=False, rim=0)
    c.put(52, 31, (190, 240, 170, 255))
    c.put(68.5, 29, (190, 240, 170, 255))
    for sx, sgn in ((55, -1), (66, 1)):
        t = wv(frame, 3)
        pts = [(sx, 17), (sx + sgn * 5 + t * 0.3 * sgn, 8), (sx + sgn * 8 + t * sgn, 4)]
        c.line(pts, OLC(lr, 0.9))
        ep(c, pts[-1][0], pts[-1][1], 2.2, 2.2, make_ramp((150, 210, 140)), ol=True, rim=0)
    return c.result()


def fireant(frame):
    return ant(frame, (190, 70, 30), (222, 100, 40), 1.3)


ENEMY_FUNCS = dict(ant=ant, spider=spider, wasp=wasp, mantis=mantis, beetle=beetle, hornet=hornet, alien=alien)


# ----------------------------------------------------------------- TORRES
def shadow_ell(c, cx, cy, rx, ry, a=70):
    layer = c.layer()
    ImageDraw.Draw(layer).polygon(c.P(ell_pts(cx, cy, rx, ry)), fill=(0, 0, 0, a))
    c.comp(layer)


def bark_fn(ramp, cx, hwf, seed, moss=None, moss_ramp=None):
    def fn(x, y, px, py):
        hw = hwf(y)
        u = max(-1.0, min(1.0, (x - cx) / hw))
        z = math.sqrt(1 - u * u)
        lam = u * LIGHT[0] + z * LIGHT[2] * 1.2
        t = 0.2 + 0.8 * max(0.0, lam) - 0.2 * abs(u) ** 4
        t += (fbm(x * 0.9, y * 0.09, seed) - 0.5) * 0.7
        if moss is not None and fbm(x * 0.07, y * 0.07, seed + 5) > moss(y):
            return pick(moss_ramp, t + 0.1, px, py)
        return pick(ramp, t, px, py)
    return fn


def hive():
    c = Canvas(140, 180)
    wood = make_ramp((128, 92, 54))
    shadow_ell(c, 70, 176, 66, 6)
    for lx in (18, 110):
        pp(c, [(lx, 158), (lx + 12, 158), (lx + 10, 178), (lx + 2, 178)], wood)
    plank = [(4, 150), (136, 150), (131, 164), (9, 164)]
    pp(c, plank, wood, fur=0.3, seed=2)
    for gx in range(14, 130, 17):
        c.line([(gx, 152), (gx + 2, 162)], wood[1])
    c.line([(5, 151), (135, 151)], wood[4])
    n = 9
    for i in range(n - 1, -1, -1):
        t = i / n
        rx = 54 * math.sqrt(max(0.0, 1 - t ** 2.0 * 0.92))
        cy = 142 - i * 14.5
        base = (206, 164, 90) if i % 2 == 0 else (182, 140, 72)
        ep(c, 70, cy, rx, 10.5, make_ramp(base), fur=0.55, seed=20 + i, tone=0.04 * i / n, rim=0.12)
        c.line([(70 - rx * 0.8, cy + 2.5), (70 + rx * 0.8, cy + 2.5)], make_ramp(base)[1])
    ep(c, 70, 24, 11, 8, make_ramp((206, 164, 90)), fur=0.5, seed=40)
    ep(c, 70, 15, 4, 5, make_ramp((160, 118, 60)), fur=0.4, seed=41)
    arch = [(53, 150), (53, 136), (58, 124), (70, 118), (82, 124), (87, 136), (87, 150)]
    glow = make_ramp((236, 168, 70))
    dk = make_ramp((54, 34, 20))

    def door(x, y, px, py):
        d = math.hypot((x - 70) / 22, (y - 150) / 34)
        return pick(glow + [], 1.0 - d * 1.1, px, py) if d < 0.5 else pick(dk, 0.9 - d * 0.7, px, py)
    c.paint(arch, door, OLC(make_ramp((130, 92, 40)), 0.6))
    c.line([(100, 108), (100, 32)], wood[1])
    pp(c, [(100, 32), (127, 38), (100, 50)], (178, 142, 62))
    for dx, dy in ((0, 0), (7, -4), (7, 4)):
        pts = [(108 + dx * 0.55 + 3.6 * math.cos(math.radians(60 * k + 30)),
                41 + dy * 0.7 + 3.6 * math.sin(math.radians(60 * k + 30))) for k in range(6)]
        c.poly(pts, (126, 88, 30, 255))
    for fx, col in ((8, (208, 120, 128)), (132, (232, 228, 214))):
        c.line([(fx, 178), (fx, 166)], (62, 110, 56, 255))
        for k in range(5):
            a = math.radians(k * 72)
            ep(c, fx + 3.4 * math.cos(a), 164 + 3.4 * math.sin(a), 2.6, 2.6, col, ol=False, rim=0)
        ep(c, fx, 164, 2.2, 2.2, (232, 190, 70), ol=False, rim=0)
    return c.result()


def anthill():
    c = Canvas(180, 140)
    soil = make_ramp((140, 104, 70))
    shadow_ell(c, 90, 126, 86, 7)
    pts = ell_pts(90, 118, 84, 62)

    def fn(x, y, px, py):
        dx, dy = (x - 90) / 84, (y - 118) / 62
        r2 = min(1.0, dx * dx + dy * dy)
        z = math.sqrt(1 - r2)
        lam = dx * LIGHT[0] + dy * LIGHT[1] + z * LIGHT[2]
        t = 0.2 + 0.8 * max(0.0, lam) - 0.25 * r2 ** 3 + (fbm(x * 0.22, y * 0.22, 4) - 0.5) * 0.65
        return pick(soil, t, px, py)
    c.paint(pts, fn, OLC(soil, 0.6))
    c.im.paste((0, 0, 0, 0), (0, int(124 * c.k), c.w, c.h))
    rnd = random.Random(8)
    for _ in range(22):
        x, y = rnd.uniform(24, 156), rnd.uniform(78, 120)
        if ((x - 90) / 82) ** 2 + ((y - 118) / 60) ** 2 < 0.85:
            ep(c, x, y, rnd.uniform(2, 4.2), rnd.uniform(1.6, 2.6), make_ramp((150, 144, 134)), fur=0.3, seed=int(x))
    dkr = make_ramp((44, 30, 22))
    for hx, hy in ((52, 100), (120, 92), (98, 78)):
        ep(c, hx, hy, 8, 4.6, dkr, ol=True, rim=0, tone=-0.1)
    arch = [(68, 124), (68, 110), (76, 102), (90, 99), (104, 102), (112, 110), (112, 124)]

    def door(x, y, px, py):
        return pick(dkr, 0.55 - 0.4 * (124 - y) / 26, px, py)
    c.paint(arch, door, OLC(soil, 0.6))
    c.line([(130, 118), (128, 62)], (96, 72, 46, 255))
    pp(c, [(128, 62), (154, 68), (146, 74), (154, 80), (128, 80)], (140, 58, 48), fur=0.3, seed=3)
    for tx in (14, 34, 146, 168):
        for dx in (-2, 0, 2):
            c.line([(tx + dx, 128), (tx + dx * 2.2, 119)], (82, 128, 62, 255))
    for lx, ly in ((60, 126), (118, 127)):
        pp(c, [(lx, ly), (lx + 8, ly - 2), (lx + 12, ly + 1), (lx + 4, ly + 3)], (92, 130, 68))
    return c.result()


def stump():
    c = Canvas(160, 200)
    bark = make_ramp((104, 76, 50))
    moss = make_ramp((78, 112, 56))
    shadow_ell(c, 82, 192, 62, 6)
    for rx_, flip in ((24, -1), (138, 1)):
        pp(c, [(rx_, 190), (rx_ + flip * 16, 196), (rx_ + flip * 6, 176)], bark)
    trunk = [(22, 190), (40, 128), (38, 68), (50, 52), (112, 52), (124, 68), (122, 128), (140, 190)]
    hwf = lambda y: 40 + 20 * max(0.0, min(1.0, (y - 128) / 62))
    c.paint(trunk, bark_fn(bark, 81, hwf, 3, lambda y: 0.6 if y > 110 else 0.66, moss), OLC(bark, 0.55))
    topc = make_ramp((146, 112, 74))

    def rings(x, y, px, py):
        d = math.hypot((x - 81) / 32, (y - 54) / 10)
        t = 0.55 + 0.25 * math.sin(d * 18) + (fbm(x * 0.5, y * 0.5, 9) - 0.5) * 0.3
        return pick(topc, t - 0.15 * d, px, py)
    c.paint(ell_pts(81, 54, 32, 10), rings, OLC(bark, 0.55))
    # forat fosc amb ulls
    dk = make_ramp((26, 18, 14))
    c.paint(ell_pts(80, 138, 18, 24), lambda x, y, px, py: pick(dk, 0.35 + 0.2 * (y - 114) / 48, px, py), OLC(bark, 0.5))
    layer = c.layer()
    ld = ImageDraw.Draw(layer)
    for ex in (74, 87):
        for r, a in ((6, 40), (4, 90)):
            ld.polygon(c.P(ell_pts(ex, 131, r, r * 0.8)), fill=(214, 70, 52, a))
    c.comp(layer)
    for ex in (74, 87):
        ep(c, ex, 131, 2.6, 2.0, make_ramp((230, 90, 60)), ol=False, rim=0)
        c.put(ex - 0.6, 130.5, (255, 230, 200, 255))
    # xampinyons
    for mx, my in ((34, 178), (122, 182)):
        c.line([(mx, my), (mx, my - 6)], (214, 206, 186, 255), 2)
        ep(c, mx, my - 7, 6, 4, make_ramp((176, 70, 60)), ol=True)
        c.put(mx - 2, my - 8, (240, 230, 214, 255))
        c.put(mx + 2, my - 7, (240, 230, 214, 255))
    # teranyina
    wl = c.layer()
    wd = ImageDraw.Draw(wl)
    cx, cy = 34, 56
    wc = (226, 226, 232, 200)
    for k in range(8):
        a = math.radians(-20 + k * 24)
        wd.line(c.P([(cx, cy), (cx + 62 * math.cos(a), cy + 62 * math.sin(a))]), fill=wc, width=1)
    for rr in (14, 26, 38, 50):
        pts = []
        for k in range(8):
            a = math.radians(-20 + k * 24)
            sag = 0.88 if k else 1
            pts.append((cx + rr * math.cos(a) * sag, cy + rr * math.sin(a) * sag))
        wd.line(c.P(pts), fill=wc, width=1)
    c.comp(wl)
    c.line([(128, 56), (128, 90)], (226, 226, 232, 255))
    ep(c, 128, 94, 4.4, 4.0, make_ramp((84, 64, 94)))
    for sgn in (-1, 1):
        c.line([(128, 94), (128 + sgn * 6, 90), (128 + sgn * 9, 100)], (44, 34, 52, 255))
        c.line([(128, 94), (128 + sgn * 7, 96), (128 + sgn * 10, 106)], (44, 34, 52, 255))
    return c.result()


def nest():
    c = Canvas(190, 230)
    wood = make_ramp((104, 80, 58))
    shadow_ell(c, 164, 226, 30, 4)
    trunk = [(150, 228), (156, 100), (160, 40), (168, 40), (172, 100), (180, 228)]
    c.paint(trunk, bark_fn(wood, 165, lambda y: 12 + 6 * max(0.0, (y - 100) / 128), 11), OLC(wood, 0.55))
    c.line([(160, 60), (120, 28), (60, 22)], wood[1], 3)
    c.line([(160, 59), (120, 27), (60, 21)], wood[3], 1)
    c.line([(146, 40), (130, 14)], wood[1], 2)
    c.line([(170, 80), (186, 62)], wood[1], 2)
    c.line([(76, 24), (76, 42)], wood[1], 2)
    for i in range(10, -1, -1):
        yy = 52 + i * 13.4
        t = (yy - 118) / 74
        rx = 52 * math.sqrt(max(0.05, 1 - t * t))
        base = (190, 178, 152) if i % 2 == 0 else (164, 152, 126)
        ep(c, 76, yy + 4, rx, 9.5, make_ramp(base), fur=0.5, seed=50 + i, tone=0.02 * (10 - i) / 10 - 0.04, rim=0.18)
    dk = make_ramp((30, 22, 18))
    c.paint(ell_pts(76, 186, 15, 11), lambda x, y, px, py: pick(dk, 0.4 - 0.2 * (y - 175) / 22, px, py),
            OLC(make_ramp((130, 118, 96)), 0.5))
    for ex in (71, 82):
        c.put(ex, 186, (214, 70, 52, 255))
    return c.result()


def moon(angry):
    c = Canvas(400, 400)
    cx = cy = 200
    R = 188
    layer = c.layer()
    ld = ImageDraw.Draw(layer)
    for r, a in ((199, 16), (194, 28), (190, 42)):
        ld.polygon(c.P(ell_pts(cx, cy, r, r, 0, 90)), fill=(214, 208, 184, a))
    c.comp(layer)
    ramp = make_ramp((186, 188, 200), 6)
    maria = [(130, 120, 70, 54), (292, 126, 50, 40), (92, 270, 40, 36), (300, 282, 56, 44), (212, 336, 34, 24),
             (338, 196, 28, 34), (210, 70, 40, 24)]
    craters = [(-120, -98, 28), (120, -118, 20), (136, 24, 24), (-142, 78, 18), (46, 146, 28), (-52, -150, 14),
               (150, -52, 12), (-84, 134, 12), (-20, 110, 10), (84, 60, 9), (-150, -20, 10), (60, -170, 12)]
    cr = [(cx + dx, cy + dy, r) for dx, dy, r in craters]

    def fn(x, y, px, py):
        dx, dy = (x - cx) / R, (y - cy) / R
        r2 = dx * dx + dy * dy
        if r2 > 1:
            return None
        z = math.sqrt(1 - r2)
        lam = dx * LIGHT[0] + dy * LIGHT[1] + z * LIGHT[2]
        t = 0.2 + 0.8 * max(0.0, lam) - 0.34 * r2 ** 3
        t += (fbm(x * 0.05, y * 0.05, 3) - 0.5) * 0.4 + (fbm(x * 0.2, y * 0.2, 7) - 0.5) * 0.12
        for mx, my, mrx, mry in maria:
            d = ((x - mx) / mrx) ** 2 + ((y - my) / mry) ** 2
            if d < 1:
                t -= 0.26 * (1 - d) ** 0.55
        for ccx, ccy, r in cr:
            d = math.hypot(x - ccx, y - ccy) / r
            if d < 0.88:
                ox, oy = (x - ccx) / r, (y - ccy) / r
                t += -0.1 + (ox + oy) * 0.18
            elif d < 1.1:
                ox, oy = (x - ccx) / r, (y - ccy) / r
                t += 0.16 - (ox + oy) * 0.16
        return pick(ramp, t, px, py)
    c.paint(ell_pts(cx, cy, R, R, 0, 120), fn, (74, 76, 92, 255))
    # --- cara esculpida en la roca
    rk = make_ramp((90, 92, 108))
    glow = (206, 84, 62) if angry else (176, 168, 128)
    bt = 12 if angry else 3
    for sgn, ex in ((-1, 140), (1, 262)):
        brow = [(ex + sgn * 54, 128), (ex - sgn * 50, 150 + bt), (ex - sgn * 50, 174 + bt), (ex + sgn * 54, 152)]
        pp(c, brow, rk, fur=0.2, seed=ex)
        socket = make_ramp((56, 58, 74))
        ep(c, ex, 190, 34, 25, socket, rim=0.1, tone=-0.1, ol=True)
        lay = c.layer()
        ImageDraw.Draw(lay).polygon(c.P(ell_pts(ex, 190, 24, 17)), fill=glow + (60 if angry else 36,))
        c.comp(lay)
        ep(c, ex, 190, 13, 10, make_ramp(glow), ol=False, rim=0.05)
        ep(c, ex + (3 if sgn < 0 else -3), 190, 3.4, 10, make_ramp((22, 20, 26)), ol=False, rim=0)
        c.put(ex - 6, 185, (255, 244, 220, 255))
    ep(c, 200, 238, 12, 16, make_ramp((116, 118, 132)), tone=-0.1)
    mouth = [(112, 302), (156, 312), (200, 316), (244, 312), (288, 302), (274, 324), (240, 338), (200, 342),
             (160, 338), (126, 324)]
    mk = make_ramp((36, 34, 46))
    c.paint(mouth, lambda x, y, px, py: pick(mk, 0.6 - 0.5 * (y - 300) / 44, px, py), (52, 52, 66, 255))
    tr = make_ramp((190, 190, 200))
    for k in range(5):
        tx = 140 + k * 26
        pp(c, [(tx, 308 + abs(k - 2) * 2), (tx + 18, 311 + abs(k - 2) * 2), (tx + 9, 324)], tr)
    for k in range(3):
        tx = 160 + k * 28
        pp(c, [(tx, 340 - abs(k - 1) * 2), (tx + 18, 340 - abs(k - 1) * 2), (tx + 9, 328)], tr)
    if angry:
        lay = c.layer()
        ld = ImageDraw.Draw(lay)
        for pts in ([(140, 214), (128, 250), (110, 282)], [(262, 214), (276, 252), (290, 284)],
                    [(200, 262), (196, 292), (204, 314)], [(120, 160), (96, 130), (80, 110)],
                    [(282, 160), (306, 130), (320, 112)]):
            ld.line(c.P(pts), fill=(226, 96, 66, 210), width=1)
            ld.line(c.P([(x + 1.2, y) for x, y in pts]), fill=(255, 190, 130, 120), width=1)
        c.comp(lay)
    return c.result()


# ----------------------------------------------------------------- NÚVOLS
def cloud_sprite(seed):
    c = Canvas(190, 64)
    rnd = random.Random(seed)
    ramp = [(150, 166, 192, 255), (188, 202, 220, 255), (222, 230, 240, 255), (244, 247, 251, 255), (255, 255, 255, 255)]
    blobs = [(30 + i * 24 + rnd.uniform(-6, 6), 38 + rnd.uniform(-8, 6), rnd.uniform(18, 28), rnd.uniform(12, 20))
             for i in range(6)]
    for x, y, rx, ry in sorted(blobs, key=lambda b: -b[1]):
        ep(c, x, y, rx, ry, ramp, ol=False, rim=0.14, tone=0.22)
    return c.result()


# --------------------------------------------------------------------- UI
def vgrad_dither(c, y0, y1, top, bot, levels=9):
    ys, ye = int(y0 * c.k), min(c.h, int(y1 * c.k))
    pix = c.im.load()
    n = max(1, ye - ys)
    for y in range(n):
        t = y / max(1, n - 1)
        for x in range(c.w):
            q = math.floor(t * (levels - 1) + (BAYER[y & 3][x & 3] + 0.5) / 16) / (levels - 1)
            q = min(1.0, max(0.0, q))
            pix[x, ys + y] = (int(top[0] + (bot[0] - top[0]) * q), int(top[1] + (bot[1] - top[1]) * q),
                              int(top[2] + (bot[2] - top[2]) * q), 255)


def ui_panel():
    c = Canvas(1000, 100)
    vgrad_dither(c, 0, 100, (64, 52, 42), (28, 22, 18), 7)
    r = 16
    for row in range(-1, 8):
        for col in range(-1, 36):
            x = col * r * 1.75 + (r * 0.875 if row % 2 else 0)
            y = row * r * 1.5 + 6
            pts = [(x + r * 0.95 * math.cos(math.radians(60 * k + 30)),
                    y + r * 0.95 * math.sin(math.radians(60 * k + 30))) for k in range(6)]
            c.line(pts + [pts[0]], (150, 118, 62, 255))
    # enfosquim les línies perquè el patró sigui subtil
    lay = Image.new("RGBA", c.im.size, (30, 24, 20, 150))
    c.comp(lay)
    c.poly([(0, 0), (1000, 0), (1000, 5), (0, 5)], (176, 140, 70, 255))
    c.poly([(0, 5), (1000, 5), (1000, 8), (0, 8)], (86, 62, 28, 255))
    c.poly([(0, 0), (1000, 0), (1000, 2), (0, 2)], (226, 196, 120, 255))
    return c.result()


def icon_honey():
    c = Canvas(32, 32)
    hr = make_ramp((214, 156, 44))
    drop = [(16, 2)] + [(16 + 9.5 * math.sin(a), 21 - 9.5 * math.cos(a)) for a in
                        [math.radians(d) for d in range(30, 331, 20)]]

    def fn(x, y, px, py):
        dx, dy = (x - 16) / 10, (y - 20) / 11
        r2 = min(1.0, dx * dx + dy * dy)
        z = math.sqrt(1 - r2)
        lam = dx * LIGHT[0] + dy * LIGHT[1] + z * LIGHT[2]
        return pick(hr, 0.25 + 0.75 * max(0.0, lam), px, py)
    c.paint(drop, fn, OLC(hr, 0.6))
    c.put(11, 17, (255, 240, 190, 255))
    c.put(11.8, 18.6, (255, 240, 190, 255))
    return c.result()


def icon_cannon():
    c = Canvas(56, 48)
    wr = make_ramp((130, 92, 56))
    ep(c, 14, 36, 9, 9, make_ramp((84, 64, 44)))
    ep(c, 14, 36, 4, 4, wr, ol=False, rim=0)
    pp(c, [(8, 28), (16, 36), (42, 14), (34, 6)], wr)
    ep(c, 42, 12, 8, 6.4, make_ramp((72, 52, 34)), -0.7)
    for (x, y, r) in ((46, 9, 4), (50, 4, 3), (52, 12, 3.4), (47, 15, 2.6)):
        ep(c, x, y, r, r, (226, 190, 80), ol=False, rim=0.1)
    return c.result()


def proj_mud():
    c = Canvas(16, 16)
    ep(c, 8, 8, 6.4, 6.4, (116, 82, 56), fur=0.5, seed=3)
    return c.result()


def proj_orb():
    c = Canvas(24, 24)
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for r, a in ((11, 50), (8, 110)):
        ld.polygon(c.P(ell_pts(12, 12, r, r)), fill=(140, 204, 130, a))
    c.comp(lay)
    ep(c, 12, 12, 5, 5, (176, 224, 160), ol=True, rim=0.1)
    c.put(10, 10, (255, 255, 240, 255))
    return c.result()


def proj_pollen():
    c = Canvas(16, 16)
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for r, a in ((7.5, 70), (5.5, 150)):
        ld.polygon(c.P(ell_pts(8, 8, r, r)), fill=(226, 190, 80, a))
    c.comp(lay)
    ep(c, 8, 8, 3.6, 3.6, (232, 198, 84), ol=False, rim=0.1)
    return c.result()


def proj_web():
    c = Canvas(16, 16)
    ep(c, 8, 8, 6, 6, (206, 206, 214), ol=True, rim=0.1)
    for a in range(0, 180, 45):
        r = math.radians(a)
        c.line([(8 - 6 * math.cos(r), 8 - 6 * math.sin(r)), (8 + 6 * math.cos(r), 8 + 6 * math.sin(r))],
               (120, 120, 134, 255))
    return c.result()


# ------------------------------------------------------------------ EFECTES
def _fx(w, h):
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def fx_burst(col=(255, 240, 190), n=4, size=28):
    out = []
    for i in range(n):
        im, d = _fx(size, size)
        cx = cy = size / 2
        L = 4 + i * size / 9
        a = int(255 * (1 - i * 0.2))
        for k in range(8):
            ang = k * math.pi / 4 + 0.2
            ll = L * (1.0 if k % 2 == 0 else 0.55)
            pts = [(cx + math.cos(ang - 0.17) * 2, cy + math.sin(ang - 0.17) * 2), (cx + math.cos(ang) * ll, cy + math.sin(ang) * ll),
                   (cx + math.cos(ang + 0.17) * 2, cy + math.sin(ang + 0.17) * 2)]
            d.polygon(pts, fill=col + (a,))
        r = max(1.0, 5 - i * 1.3)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 240, a))
        out.append(im)
    return out


def fx_crescent(col=(255, 244, 214), edge=(244, 196, 96), size=44, flip=False):
    out = []
    for i, prog in enumerate((0.35, 0.7, 1.0, 1.0)):
        im, d = _fx(size, size)
        cx, cy, R = size / 2 - 4, size / 2, size * 0.42
        a1 = math.radians(70 * prog)
        fade = 255 if i < 3 else 130
        outer, inner = [], []
        steps = 14
        for s in range(steps + 1):
            th = -a1 + 2 * a1 * s / steps
            outer.append((cx + R * math.cos(th), cy + R * math.sin(th)))
        for s in range(steps, -1, -1):
            th = -a1 + 2 * a1 * s / steps
            inner.append((cx - 7 + (R * 0.92) * math.cos(th), cy + (R * 0.92) * math.sin(th)))
        d.polygon(outer + inner, fill=edge + (fade,))
        inner2 = [(cx - 4 + (R * 0.97) * math.cos(-a1 + 2 * a1 * s / steps), cy + (R * 0.97) * math.sin(-a1 + 2 * a1 * s / steps))
                  for s in range(steps, -1, -1)]
        d.polygon(outer + inner2, fill=col + (fade,))
        out.append(im)
    return out


def fx_ring_frames(col=(240, 214, 140), w=72, h=26, n=5):
    out = []
    for i in range(n):
        im, d = _fx(w, h)
        t = (i + 1) / n
        rx, ry = 6 + t * (w / 2 - 8), 2 + t * (h / 2 - 3)
        a = int(255 * (1 - t * 0.75))
        d.ellipse((w / 2 - rx, h / 2 - ry, w / 2 + rx, h / 2 + ry), outline=col + (a,), width=2)
        d.ellipse((w / 2 - rx + 2, h / 2 - ry + 1, w / 2 + rx - 2, h / 2 + ry - 1), outline=col + (a // 2,), width=1)
        out.append(im)
    return out


def fx_bubbles(col=(150, 202, 100), n=4):
    out = []
    pos = [(6, 0.0), (13, 0.3), (9, 0.6)]
    for i in range(n):
        im, d = _fx(20, 30)
        for bx, ph in pos:
            t = (i / n + ph) % 1.0
            y = 26 - t * 22
            r = 2 + (1 - t) * 1.5
            a = int(230 * (1 - t * 0.6))
            d.ellipse((bx - r, y - r, bx + r, y + r), fill=col + (a,), outline=(70, 120, 50, a))
            d.point((int(bx - r / 2), int(y - r / 2)), fill=(240, 255, 220, a))
        out.append(im)
    return out


def fx_splat(col=(120, 86, 58), n=4):
    out = []
    rnd = random.Random(5)
    drops = [(rnd.uniform(0, 6.28), rnd.uniform(0.6, 1.0)) for _ in range(8)]
    for i in range(n):
        im, d = _fx(30, 26)
        cx, cy = 15, 14
        t = (i + 1) / n
        r = 3 + t * 6
        a = int(255 * (1 - 0.18 * i))
        d.ellipse((cx - r, cy - r * 0.7, cx + r, cy + r * 0.7), fill=col + (a,), outline=(66, 44, 30, a))
        for ang, f in drops:
            rr = r + 2 + t * 7 * f
            x, y = cx + math.cos(ang) * rr, cy + math.sin(ang) * rr * 0.7
            d.ellipse((x - 1.2, y - 1.2, x + 1.2, y + 1.2), fill=col + (a,))
        out.append(im)
    return out


def _star4(d, x, y, r, col):
    d.polygon([(x, y - r), (x + r * 0.3, y - r * 0.3), (x + r, y), (x + r * 0.3, y + r * 0.3), (x, y + r),
               (x - r * 0.3, y + r * 0.3), (x - r, y), (x - r * 0.3, y - r * 0.3)], fill=col)


def fx_sparkles(cols=((210, 255, 250), (255, 214, 236), (236, 255, 210)), n=4):
    out = []
    pts = [(8, 9, 0.0), (20, 8, 0.33), (14, 20, 0.66)]
    for i in range(n):
        im, d = _fx(28, 28)
        for (x, y, ph), col in zip(pts, cols):
            t = (i / n + ph) % 1.0
            r = 1 + 5 * math.sin(math.pi * t)
            _star4(d, x, y, r, col + (255,))
        out.append(im)
    return out


def fx_puff(col=(232, 198, 84), n=4):
    out = []
    rnd = random.Random(9)
    dots = [(rnd.uniform(0, 6.28), rnd.uniform(0.3, 1.0)) for _ in range(16)]
    for i in range(n):
        im, d = _fx(44, 36)
        cx, cy = 22, 18
        t = (i + 1) / n
        for ang, f in dots:
            rr = 3 + t * 15 * f
            x, y = cx + math.cos(ang) * rr, cy + math.sin(ang) * rr * 0.8
            a = int(240 * (1 - t * 0.6))
            d.ellipse((x - 2, y - 2, x + 2, y + 2), fill=col + (a,))
        d.ellipse((cx - 4, cy - 4, cx + 4, cy + 4), fill=(250, 232, 140, int(160 * (1 - t))))
        out.append(im)
    return out


def fx_critical(n=4):
    out = []
    rnd = random.Random(2)
    chips = [(rnd.uniform(0, 6.28), rnd.uniform(0.6, 1.0)) for _ in range(7)]
    for i in range(n):
        im, d = _fx(44, 44)
        cx = cy = 22
        t = (i + 1) / n
        a = int(255 * (1 - 0.2 * i))
        for k in range(10):
            ang = k * math.pi / 5
            ll = (7 + t * 12) * (1.0 if k % 2 == 0 else 0.6)
            d.polygon([(cx + math.cos(ang - 0.2) * 2, cy + math.sin(ang - 0.2) * 2), (cx + math.cos(ang) * ll, cy + math.sin(ang) * ll),
                       (cx + math.cos(ang + 0.2) * 2, cy + math.sin(ang + 0.2) * 2)], fill=(240, 90, 60, a))
        d.ellipse((cx - 5 + i, cy - 5 + i, cx + 5 - i, cy + 5 - i), fill=(255, 236, 200, a))
        for ang, f in chips:
            rr = 6 + t * 15 * f
            x, y = cx + math.cos(ang) * rr, cy + math.sin(ang) * rr
            d.rectangle((x - 1, y - 1, x + 1, y + 0), fill=(176, 126, 74, a))
        out.append(im)
    return out


def fx_claw(n=4):
    out = []
    for i in range(n):
        im, d = _fx(36, 36)
        for s in range(3):
            if i + 1 < s + 1:
                continue
            ox = 6 + s * 8
            prog = min(1.0, (i + 1 - s * 0.5) / 2)
            x0, y0 = ox, 4
            x1, y1 = ox + 14, 4 + 28 * prog
            fade = int(255 * (1 - max(0, i - 1) * 0.3))
            d.polygon([(x0, y0), (x1 + 2, y1), (x1 - 1, y1 + 1), (x0 - 1, y0 + 1)], fill=(255, 226, 214, fade))
            d.line([(x0, y0 + 1), (x1, y1)], fill=(222, 70, 60, fade), width=1)
        out.append(im)
    return out


def fx_web_frames(n=4):
    out = []
    for i in range(n):
        im, d = _fx(32, 32)
        a = int(240 * (1 - i * 0.18))
        cx = cy = 16
        R = 6 + i * 2.5
        for k in range(8):
            ang = k * math.pi / 4
            d.line([(cx, cy), (cx + R * math.cos(ang), cy + R * math.sin(ang))], fill=(226, 226, 234, a), width=1)
        for rr in (R * 0.4, R * 0.7, R):
            pts = [(cx + rr * math.cos(k * math.pi / 4), cy + rr * math.sin(k * math.pi / 4)) for k in range(9)]
            d.line(pts, fill=(226, 226, 234, a), width=1)
        out.append(im)
    return out


def fx_royal_frames(n=6):
    out = []
    for i in range(n):
        im, d = _fx(120, 46)
        t = (i + 1) / n
        rx, ry = 10 + t * 48, 3 + t * 17
        a = int(255 * (1 - t * 0.7))
        d.ellipse((60 - rx, 23 - ry, 60 + rx, 23 + ry), outline=(244, 208, 96, a), width=3)
        d.ellipse((60 - rx + 3, 23 - ry + 2, 60 + rx - 3, 23 + ry - 2), outline=(255, 246, 200, a // 2), width=1)
        for k in range(10):
            ang = k * math.pi / 5 + t
            x, y = 60 + math.cos(ang) * rx, 23 + math.sin(ang) * ry
            _star4(d, x, y, 2.2 + 2 * (1 - t), (255, 244, 190, a))
        out.append(im)
    return out


def fx_plus(n=4):
    out = []
    for i in range(n):
        im, d = _fx(18, 24)
        for bx, ph in ((5, 0.0), (12, 0.5)):
            t = (i / n + ph) % 1.0
            y = 20 - t * 16
            a = int(240 * (1 - t * 0.5))
            d.rectangle((bx - 1, y - 3, bx, y + 3), fill=(150, 226, 140, a))
            d.rectangle((bx - 3, y - 1, bx + 2, y), fill=(150, 226, 140, a))
        out.append(im)
    return out


def build_fx():
    out = {
        "fx_hit": fx_burst((255, 240, 190)),
        "fx_hit_g": fx_burst((190, 236, 140)),
        "fx_hit_r": fx_burst((255, 170, 150)),
        "fx_slash": fx_crescent(),
        "fx_slash_g": fx_crescent((236, 255, 214), (130, 200, 90)),
        "fx_ring": fx_ring_frames(),
        "fx_ring_big": fx_ring_frames((236, 196, 130), 110, 40),
        "fx_poison": fx_bubbles(),
        "fx_mud": fx_splat(),
        "fx_sparkle": fx_sparkles(),
        "fx_pollen": fx_puff(),
        "fx_crit": fx_critical(),
        "fx_claw": fx_claw(),
        "fx_web": fx_web_frames(),
        "fx_royal": fx_royal_frames(),
        "fx_heal": fx_plus(),
    }
    return {k: [up(f) for f in v] for k, v in out.items()}


# ------------------------------------------------------------------ FONS (per capes)
def up(im, pix=None):
    pix = PIX if pix is None else pix
    return im.resize((im.width * pix, im.height * pix), Image.NEAREST)


def hard(im):
    im = im.copy()
    im.putalpha(im.getchannel("A").point(lambda v: 0 if v < 40 else v))
    return im


def crop_union(frames):
    box = None
    for f in frames:
        b = f.getchannel("A").getbbox()
        if b:
            box = b if box is None else (min(box[0], b[0]), min(box[1], b[1]), max(box[2], b[2]), max(box[3], b[3]))
    return [f.crop(box) for f in frames]


def ridge(base, parts, seed):
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, 6) for _ in parts]
    return lambda x: base - sum(a * (0.5 + 0.5 * math.sin(f * x + p)) for (a, f), p in zip(parts, ph))


def hills(c, base, parts, ramp, seed, tex=0.3, depth=60, tone=0.0):
    f = ridge(base, parts, seed)
    pts = [(x, f(x)) for x in range(0, 1001, 4)] + [(1000, 440), (0, 440)]

    def fn(x, y, px, py):
        t = 0.74 - 0.42 * min(1.0, (y - f(x)) / depth) + tone + (fbm(x * 0.03, y * 0.06, seed) - 0.5) * tex
        return pick(ramp, t, px, py)
    c.paint(pts, fn, None)
    return f


def glow(c, cx, cy, radii, col, alphas):
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for r, a in zip(radii, alphas):
        ld.polygon(c.P(ell_pts(cx, cy, r, r, 0, 60)), fill=col + (a,))
    c.comp(lay)


def ground_layer(c, y0, base, seed, tex=0.5, ripple=0.0, tone=0.52, craters=()):
    ramp = make_ramp(base)
    pts = [(0, y0), (1000, y0), (1000, 440), (0, 440)]

    def fn(x, y, px, py):
        t = tone - 0.2 * ((y - y0) / (440 - y0)) + (fbm(x * 0.045, y * 0.14, seed) - 0.5) * tex
        if ripple:
            t += math.sin(x * 0.07 + y * 0.25) * ripple
        for cx, cy, rx, ry in craters:
            d = ((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2
            if d < 1:
                t += -0.14 + (cx - x) / rx * 0.06 - (y - cy) / ry * 0.06
            elif d < 1.4:
                t += 0.13 * (1.4 - d) / 0.4 * (1 if y < cy + ry * 0.2 else 0.5)
        return pick(ramp, t, px, py)
    c.paint(pts, fn, None)
    c.line([(0, y0), (1000, y0)], ramp[4])
    return ramp


def blades(c, y0, ramp, n, seed, hmin=4, hmax=9):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.uniform(0, 1000), rnd.uniform(y0 + 4, 438)
        c.line([(x, y), (x + rnd.uniform(-2, 2), y - rnd.uniform(hmin, hmax))], ramp[rnd.choice((1, 2, 3, 3))])


def flower(c, x, y, s, col):
    c.line([(x, y), (x, y - 10 * s)], (66, 108, 58, 255))
    for dx, dy in ((-3, 0), (3, 0), (0, -3), (0, 3)):
        c.put(x + dx * s, y - 11 * s + dy * s, col)
    c.put(x, y - 11 * s, (232, 196, 80, 255))


def tree_round(c, x, y, h, leaf, trunk):
    w = h * 0.07
    pp(c, [(x - w, y), (x - w * 0.6, y - h * 0.5), (x + w * 0.6, y - h * 0.5), (x + w, y)], trunk, ol=False)
    for dx, dy, rx, ry in ((0, -.72, .3, .26), (-.2, -.58, .22, .2), (.2, -.6, .23, .2), (0, -.88, .18, .15)):
        ep(c, x + dx * h, y + dy * h, rx * h, ry * h, leaf, fur=0.35, seed=int(x) + int(dy * 10), ol=False, rim=0.2)


def fir(c, x, y, h, ramp, trunk):
    pp(c, [(x - 2, y), (x - 1.5, y - h * 0.3), (x + 1.5, y - h * 0.3), (x + 2, y)], trunk, ol=False)
    for i in range(5):
        yy = y - h * (0.2 + 0.17 * i)
        rx = h * (0.3 - 0.05 * i)
        ep(c, x, yy, rx, rx * 0.55, ramp, fur=0.3, seed=int(x) + i, ol=False, rim=0.15)


def cactus(c, x, y, h, ramp):
    ep(c, x, y - h / 2, 5.5, h / 2, ramp, fur=0.2, seed=int(x), rim=0.25)
    ep(c, x - 11, y - h * 0.55, 3.6, h * 0.22, ramp, 0.0, fur=0.2, seed=int(x) + 1, rim=0.25)
    ep(c, x + 11, y - h * 0.4, 3.6, h * 0.2, ramp, 0.0, fur=0.2, seed=int(x) + 2, rim=0.25)
    c.line([(x - 5, y - h * 0.38), (x - 11, y - h * 0.38)], ramp[1], 1)
    c.line([(x + 5, y - h * 0.28), (x + 11, y - h * 0.28)], ramp[1], 1)
    for k in range(6):
        c.put(x - 2 + (k % 2) * 4, y - h * 0.9 + k * h * 0.14, ramp[4])


def mesa(c, pts, base, seed):
    ramp = make_ramp(base)
    ys, xs = [p[1] for p in pts], [p[0] for p in pts]
    y0, y1, x0, x1 = min(ys), max(ys), min(xs), max(xs)

    def fn(x, y, px, py):
        band = int((y - y0) / 6) % 3
        t = 0.6 - 0.25 * ((y - y0) / (y1 - y0 + 1e-6)) + (band - 1) * 0.08 + 0.18 * (1 - (x - x0) / (x1 - x0 + 1e-6)) - 0.1
        t += (fbm(x * 0.1, y * 0.3, seed) - 0.5) * 0.25
        return pick(ramp, t, px, py)
    c.paint(pts, fn, None)


def bg_meadow():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 340, (112, 156, 198), (212, 228, 226))
    sky.poly([(0, 340), (1000, 340), (1000, 440), (0, 440)], (212, 228, 226, 255))
    glow(sky, 820, 90, (74, 56, 44), (255, 240, 190), (22, 40, 70))
    ep(sky, 820, 90, 36, 36, make_ramp((255, 238, 176)), ol=False, rim=0, tone=0.5)
    mid = Canvas(1000, 440)
    hills(mid, 330, [(40, 0.006), (22, 0.013)], make_ramp((150, 184, 172)), 1, 0.25, 80)
    hills(mid, 362, [(34, 0.008), (16, 0.02)], make_ramp((104, 146, 98)), 2, 0.35, 50)
    lr, tr_ = make_ramp((70, 112, 68)), make_ramp((88, 66, 46))
    for x in range(20, 1000, 66):
        tree_round(mid, x + (x * 7) % 26, 376, 66 + (x * 3) % 28, lr, tr_)
    g = Canvas(1000, 440)
    gr = ground_layer(g, 372, (100, 140, 72), 3, 0.5)
    blades(g, 372, gr, 300, 4)
    rnd = random.Random(7)
    cols = [(206, 130, 138, 255), (226, 222, 208, 255), (214, 178, 90, 255), (156, 130, 190, 255)]
    for _ in range(22):
        y = rnd.uniform(382, 430)
        flower(g, rnd.uniform(0, 1000), y, 0.8 + (y - 380) / 60 * 0.5, rnd.choice(cols))
    fg = Canvas(1000, 440)
    dk = make_ramp((58, 92, 50))
    for x in range(-4, 1000, 7):
        h = random.Random(x).uniform(8, 22)
        fg.line([(x, 440), (x + random.Random(x + 1).uniform(-3, 3), 440 - h)], dk[random.Random(x + 2).choice((1, 2, 2, 3))])
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def bg_forest():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 340, (22, 28, 52), (108, 84, 108))
    sky.poly([(0, 340), (1000, 340), (1000, 440), (0, 440)], (108, 84, 108, 255))
    rnd = random.Random(5)
    for _ in range(70):
        sky.put(rnd.uniform(0, 1000), rnd.uniform(0, 210), (222, 222, 210, 255))
    ep(sky, 120, 80, 34, 34, make_ramp((236, 226, 190)), ol=False, rim=0, tone=0.4)
    sky.poly(ell_pts(138, 72, 32, 32), (40, 46, 74, 255))
    mid = Canvas(1000, 440)
    hills(mid, 340, [(30, 0.01), (14, 0.025)], make_ramp((50, 66, 82)), 3, 0.2, 60)
    far, near, tk = make_ramp((40, 58, 74)), make_ramp((30, 50, 54)), make_ramp((22, 30, 34))
    for x in range(-10, 1010, 46):
        fir(mid, x, 378, 110 + (x * 13) % 60, far, tk)
    lay = mid.layer()
    ld = ImageDraw.Draw(lay)
    for k in range(46):
        a = int(70 * (1 - k / 46))
        ld.rectangle((0, int((330 + k) * mid.k), lay.size[0], int((331 + k) * mid.k)), fill=(170, 176, 196, a))
    mid.comp(lay)
    for x in range(20, 1010, 84):
        fir(mid, x + 20, 394, 150 + (x * 7) % 70, near, tk)
    g = Canvas(1000, 440)
    gr = ground_layer(g, 374, (48, 78, 56), 8, 0.55)
    blades(g, 374, gr, 220, 9)
    rnd = random.Random(8)
    for _ in range(10):
        x, y = rnd.uniform(0, 1000), rnd.uniform(396, 434)
        s = 0.8 + (y - 395) / 40
        g.line([(x, y), (x, y - 6 * s)], (200, 194, 176, 255), 1)
        ep(g, x, y - 7 * s, 5 * s, 3.4 * s, make_ramp((166, 70, 62)), rim=0.1)
        g.put(x - 1.5 * s, y - 8 * s, (240, 232, 214, 255))
    fg = Canvas(1000, 440)
    dk = make_ramp((26, 44, 34))
    for x in range(-6, 1000, 11):
        r_ = random.Random(x)
        h = r_.uniform(10, 26)
        fg.line([(x, 440), (x + r_.uniform(-5, 5), 440 - h)], dk[r_.choice((0, 1, 1, 2))])
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def bg_desert():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 340, (168, 106, 90), (240, 212, 166))
    sky.poly([(0, 340), (1000, 340), (1000, 440), (0, 440)], (240, 212, 166, 255))
    glow(sky, 300, 270, (120, 96, 74), (250, 220, 170), (26, 44, 70))
    ep(sky, 300, 270, 64, 64, make_ramp((240, 128, 72)), ol=False, rim=0, tone=0.45)
    mid = Canvas(1000, 440)
    mesa(mid, [(520, 366), (540, 292), (592, 282), (642, 288), (662, 366)], (170, 98, 74), 1)
    mesa(mid, [(700, 366), (714, 312), (772, 304), (802, 366)], (160, 90, 70), 2)
    mesa(mid, [(30, 366), (58, 318), (132, 308), (164, 366)], (176, 104, 78), 3)
    mesa(mid, [(850, 366), (872, 300), (942, 296), (984, 330), (1000, 366)], (164, 94, 72), 4)
    hills(mid, 384, [(20, 0.008), (10, 0.02)], make_ramp((206, 170, 118)), 9, 0.3, 40)
    g = Canvas(1000, 440)
    gr = ground_layer(g, 376, (210, 176, 122), 2, 0.4, 0.07)
    rnd = random.Random(2)
    cr = make_ramp((84, 124, 78))
    for x in (90, 340, 620, 870):
        cactus(g, x, rnd.uniform(396, 414), rnd.uniform(40, 58), cr)
    for _ in range(18):
        x, y = rnd.uniform(0, 1000), rnd.uniform(386, 436)
        s = rnd.uniform(3, 8)
        ep(g, x, y, s * 1.4, s, make_ramp((150, 120, 92)), fur=0.3, seed=int(x), rim=0.2)
    blades(g, 376, gr, 80, 5, 3, 6)
    fg = Canvas(1000, 440)
    for x, s in ((120, 12), (540, 16), (900, 10)):
        ep(fg, x, 438, s * 1.6, s, make_ramp((120, 92, 72)), fur=0.4, seed=x, rim=0.2)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def bg_moon():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 380, (3, 3, 14), (26, 20, 52))
    sky.poly([(0, 380), (1000, 380), (1000, 440), (0, 440)], (26, 20, 52, 255))
    pix = sky.im.load()
    for y in range(0, min(sky.h, int(300 * sky.k))):
        for x in range(sky.w):
            ux, uy = x / sky.k, y / sky.k
            if abs(ux * 0.35 + uy - 230) < 80:
                n = fbm(ux * 0.012, uy * 0.02, 12)
                a = max(0.0, n - 0.48) * (1 - abs(ux * 0.35 + uy - 230) / 80) * 1.1
                if a > 0:
                    r, g_, b, _ = pix[x, y]
                    pix[x, y] = (min(255, int(r + 70 * a)), min(255, int(g_ + 30 * a)), min(255, int(b + 90 * a)), 255)
    rnd = random.Random(21)
    for _ in range(230):
        v = rnd.choice(((255, 255, 255), (255, 236, 200), (200, 214, 255)))
        sky.put(rnd.uniform(0, 1000), rnd.uniform(0, 360), v + (255,))
    for _ in range(10):
        x, y = rnd.uniform(0, 1000), rnd.uniform(0, 280)
        for dx, dy in ((0, 0), (-3, 0), (3, 0), (0, -3), (0, 3)):
            sky.put(x + dx, y + dy, (255, 255, 255, 255))
    glow(sky, 170, 130, (82, 74, 68), (110, 150, 200), (14, 24, 40))
    er, lr_ = make_ramp((44, 88, 150)), make_ramp((84, 124, 80))
    cx, cy, R = 170, 130, 60

    def earth(x, y, px, py):
        dx, dy = (x - cx) / R, (y - cy) / R
        r2 = min(1.0, dx * dx + dy * dy)
        z = math.sqrt(1 - r2)
        lam = dx * LIGHT[0] + dy * LIGHT[1] + z * LIGHT[2]
        t = 0.12 + 0.88 * max(0.0, lam) - 0.2 * r2 ** 3
        land = fbm(x * 0.045, y * 0.045, 31) > 0.55
        cl = fbm(x * 0.06 + 40, y * 0.09, 33) > 0.62
        if cl:
            return pick([(70, 80, 100, 255), (150, 160, 180, 255), (206, 212, 224, 255), (236, 240, 246, 255),
                         (252, 252, 255, 255)], t, px, py)
        return pick(lr_ if land else er, t, px, py)
    sky.paint(ell_pts(cx, cy, R, R, 0, 80), earth, (24, 44, 76, 255))
    mid = Canvas(1000, 440)
    hills(mid, 372, [(36, 0.009), (18, 0.022)], make_ramp((60, 62, 88)), 5, 0.25, 70)
    hills(mid, 392, [(18, 0.012), (8, 0.03)], make_ramp((92, 94, 118)), 6, 0.3, 40)
    g = Canvas(1000, 440)
    craters = [(130, 410, 56, 11), (430, 424, 70, 9), (700, 404, 48, 8), (880, 426, 60, 10), (270, 432, 36, 6)]
    gr = ground_layer(g, 380, (132, 134, 150), 3, 0.5, craters=craters)
    for _ in range(22):
        x, y = rnd.uniform(0, 1000), rnd.uniform(388, 436)
        s = rnd.uniform(2, 6)
        ep(g, x, y, s * 1.4, s, make_ramp((112, 114, 130)), fur=0.3, seed=int(x), rim=0.25)
    fg = Canvas(1000, 440)
    for x, s in ((60, 14), (480, 10), (800, 18), (960, 12)):
        ep(fg, x, 438, s * 1.7, s, make_ramp((70, 72, 90)), fur=0.4, seed=x, rim=0.25)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())




# ============================================================ NOUS ENEMICS
def frog(frame, scale=1.25, base=(104, 150, 78)):
    c = Canvas(100, 80, scale)
    gr, dr, bl = make_ramp(base), make_ramp(tuple(int(v * 0.68) for v in base)), make_ramp((212, 206, 156))
    ep(c, 22, 56, 14, 9, gr, -0.35, fur=0.15, seed=1)
    pp(c, [(6, 64), (30, 66), (36, 71), (4, 71)], gr)
    ep(c, 42, 50, 26, 17, gr, 0.0, fur=0.2, seed=2)
    ep(c, 46, 58, 18, 8, bl, ol=False, rim=0)
    for x, y, r in ((30, 42, 3.2), (42, 37, 2.6), (22, 50, 2.6), (36, 50, 2.2)):
        ep(c, x, y, r, r * 0.8, dr, ol=False, rim=0)
    pp(c, [(54, 56), (61, 56), (63, 70), (53, 70)], gr)
    ep(c, 66, 43, 15, 12, gr, 0.0, fur=0.15, seed=3)
    th = 0.5 + 0.5 * wv(frame, 1)
    ep(c, 70, 53 + th * 0.8, 8, 3.6 + th * 1.5, bl, ol=False, rim=0)
    c.line([(58, 49), (82, 48)], OLC(gr))
    for ex, ey, r in ((61, 32, 6.2), (74, 34, 5.2)):
        ep(c, ex, ey, r, r, gr)
        ep(c, ex + 0.5, ey, r * 0.78, r * 0.78, make_ramp((206, 176, 64)), ol=False, rim=0)
        c.put(ex + 1, ey, (24, 20, 16, 255))
        c.put(ex + 1, ey + 1, (24, 20, 16, 255))
        c.put(ex - 0.5, ey - 1.5, (255, 246, 210, 255))
    return c.result()


def dragonfly(frame):
    c = Canvas(100, 80, 1.25)
    bl = make_ramp((66, 136, 166))
    bands = [(bx, 3, make_ramp((30, 52, 70))) for bx in (10, 19, 28, 37, 46)]
    x0, x1, cy, hw = 0, 56, 47, 4.4
    tilt = -0.06
    ABD = rot(body_pts(x0, x1, cy, hw, 0.8, 1.4, 2.0), x1, cy, tilt)
    c.paint(ABD, sh_abd(x0, x1, cy, hw, 0.8, 1.4, 2.0, tilt, bl, bands, 0.1, True, 3), OLC(bl))
    ep(c, 60, 42, 8, 7.5, make_ramp((92, 158, 120)), fur=0.3, seed=2)
    for lx in (56, 61, 66):
        c.line([(lx, 47), (lx + 1, 53), (lx + 2 + (1 if wv(frame, 1) > 0.3 else 0), 59)], OLC(bl, 0.7))
    ep(c, 71, 41, 7, 6.5, make_ramp((70, 150, 150)))
    ep(c, 72.5, 39, 5.6, 5.6, make_ramp((52, 164, 176)), gloss=True)
    c.put(70.5, 37.5, (240, 255, 250, 255))
    fill, edge = (206, 228, 234, 86), (86, 120, 134, 210)
    wings(c, 59, 36, frame, 44, 7.5, fill, edge, ((100, 78), (126, 54), (150, 32)))
    wings(c, 64, 37, frame, 38, 6.5, fill, edge, ((88, 64), (112, 44), (136, 24)))
    return c.result()


def scorpion(frame, scale=1.0, base=(176, 128, 70), king=False):
    c = Canvas(100, 80, scale)
    r = make_ramp(base)
    dr = make_ramp(tuple(int(v * 0.6) for v in base))
    s = wv(frame, 3)
    for i, bx in enumerate((38, 46, 54, 62)):
        sg = s if i % 2 == 0 else -s
        c.line([(bx, 52), (bx + (i - 1.5) * 3 + sg * 0.4, 58), (bx + (i - 1.5) * 6 + sg, 69)], OLC(r, 0.8))
    path = [(24, 50), (13, 44), (8, 32), (12, 20), (22, 12), (34, 10), (44, 14)]
    for i in range(len(path) - 1, -1, -1):
        x, y = path[i]
        y += s * 0.5 * (i / 6)
        rad = 6.2 - i * 0.4
        ep(c, x, y, rad, rad * 0.9, r, fur=0.2, seed=20 + i, rim=0.2)
        if king and i % 2 == 1:
            pp(c, [(x - 2, y - rad), (x, y - rad - 5), (x + 2, y - rad)], dr, ol=True)
    sx, sy = path[-1][0] + s * 0.5, path[-1][1] + s * 0.5
    pp(c, [(sx + 2, sy + 1), (sx + 11, sy + 5), (sx + 3, sy + 8)], make_ramp((40, 30, 26)))
    ep(c, 48, 50, 20, 10, r, 0.0, fur=0.25, seed=4)
    for lx in (38, 46, 54):
        c.line([(lx, 42), (lx - 1, 59)], OLC(r))
    ep(c, 67, 48, 9, 8, r, fur=0.2, seed=5)
    eye(c, 70, 44, 1.8, 2.2, tint=(230, 200, 150))
    eye(c, 64, 43, 1.6, 2.0, tint=(230, 200, 150))
    for yy in (47, 53):
        c.line([(72, yy), (80, yy - 3 + s * 0.3), (86, yy - 6)], r[1], 2)
    op = s * 0.6
    pp(c, [(84, 38), (97, 36 + op), (92, 44), (87, 47)], dr)
    pp(c, [(84, 49), (96, 51 - op), (92, 46), (87, 45)], dr)
    if king:
        for k in range(4):
            pp(c, [(30 + k * 9, 41), (32 + k * 9, 33), (35 + k * 9, 41)], dr)
    return c.result()


def scorpion_king(frame):
    return scorpion(frame, 1.7, (112, 52, 44), True)


def centipede(frame):
    c = Canvas(100, 80, 1.3)
    r = make_ramp((158, 62, 46))
    leg = (214, 170, 72, 255)
    segs = 10
    pts = []
    for i in range(segs):
        x = 6 + i * 8.6
        y = 50 + math.sin(i * 0.75 + cyc(frame)) * 3
        pts.append((x, y))
    for x, y in pts:
        ph = x * 0.4 + cyc(frame) * 2
        c.line([(x, y + 4), (x - 2 + math.sin(ph) * 2.5, y + 11)], leg)
        c.line([(x + 2, y + 4), (x + 1 + math.sin(ph + 1.5) * 2.5, y + 11)], leg)
    for i, (x, y) in enumerate(pts):
        ep(c, x, y, 5.6, 5.8, r, fur=0.25, seed=30 + i, tone=0.03 * (i % 2), rim=0.2)
    hx, hy = pts[-1][0] + 7, pts[-1][1]
    ep(c, hx, hy, 7, 6.2, make_ramp((196, 88, 56)), fur=0.15, seed=40)
    pp(c, [(hx + 5, hy + 1), (hx + 12, hy + 5), (hx + 6, hy + 5)], make_ramp((140, 90, 40)))
    eye(c, hx + 3, hy - 1.5, 1.8, 2.0)
    for off in (0, 3):
        c.line([(hx + 2 + off, hy - 5), (hx + 8 + off, hy - 12), (hx + 15 + off, hy - 13)], OLC(r))
    return c.result()


def swallow(frame):
    c = Canvas(100, 80, 1.8)
    bl = make_ramp((46, 60, 108))
    cr = make_ramp((224, 210, 180))
    rd = make_ramp((184, 72, 52))
    pp(c, [(2, 40), (22, 42), (20, 46), (4, 52)], bl)
    pp(c, [(2, 56), (22, 48), (20, 52), (6, 62)], bl)
    tips = ((26, 4), (14, 24), (20, 66))
    tp = (tips[2][0] + (tips[0][0] - tips[2][0]) * wt(frame), tips[2][1] + (tips[0][1] - tips[2][1]) * wt(frame))
    up_ = wt(frame) > 0.4
    pp(c, [(54, 42), (36, 40), (tp[0] - 4, tp[1] + 4 if up_ else tp[1] - 6), tp,
           (tp[0] + 14, tp[1] + (12 if up_ else -10)), (60, 44)], bl)
    ep(c, 40, 47, 24, 10, bl, 0.0, fur=0.12, seed=3)
    ep(c, 42, 52, 18, 5.6, cr, ol=False, rim=0)
    ep(c, 64, 43, 9.5, 8.5, bl, fur=0.1, seed=4)
    ep(c, 66, 48, 5.5, 3.2, rd, ol=False, rim=0)
    pp(c, [(72, 42), (84, 44.5), (72, 47)], make_ramp((206, 170, 70)))
    eye(c, 66, 40.5, 2.3, 2.6)
    return c.result()


def hornet_guard(frame):
    return bee(HORNET, frame)


# ================================================================ TORRES NOVES
def swamp_base():
    c = Canvas(180, 150)
    mud = make_ramp((92, 98, 62))
    shadow_ell(c, 90, 138, 86, 7)
    wr = make_ramp((70, 110, 118))

    def water(x, y, px, py):
        t = 0.55 + math.sin(x * 0.4 + y * 0.9) * 0.12 - 0.2 * (y - 128) / 12
        return pick(wr, t, px, py)
    c.paint(ell_pts(120, 134, 50, 9), water, OLC(mud, 0.6))
    pts = ell_pts(70, 120, 66, 58)

    def fn(x, y, px, py):
        dx, dy = (x - 70) / 66, (y - 120) / 58
        r2 = min(1.0, dx * dx + dy * dy)
        z = math.sqrt(1 - r2)
        lam = dx * LIGHT[0] + dy * LIGHT[1] + z * LIGHT[2]
        t = 0.2 + 0.8 * max(0.0, lam) - 0.25 * r2 ** 3 + (fbm(x * 0.2, y * 0.2, 6) - 0.5) * 0.6
        if fbm(x * 0.06, y * 0.06, 9) > 0.58:
            return pick(make_ramp((78, 120, 56)), t + 0.05, px, py)
        return pick(mud, t, px, py)
    c.paint(pts, fn, OLC(mud, 0.6))
    c.im.paste((0, 0, 0, 0), (0, int(134 * c.k), c.w, c.h))
    dk = make_ramp((30, 28, 20))
    arch = [(46, 134), (46, 118), (54, 108), (70, 104), (86, 108), (94, 118), (94, 134)]
    c.paint(arch, lambda x, y, px, py: pick(dk, 0.45 - 0.25 * (134 - y) / 30, px, py), OLC(mud, 0.6))
    for ex in (62, 78):
        c.put(ex, 118, (232, 200, 80, 255))
    for rx_, h in ((132, 56), (142, 44), (152, 62), (162, 40), (26, 50), (14, 38)):
        c.line([(rx_, 134), (rx_ - 1, 134 - h)], (86, 116, 62, 255))
        ep(c, rx_ - 1, 134 - h - 3, 2.4, 6, make_ramp((104, 70, 46)), rim=0.2)
    for lx, ly in ((120, 132), (140, 133)):
        ep(c, lx, ly, 8, 2.6, make_ramp((74, 124, 66)), ol=False, rim=0)
    return c.result()


def crystal(c, x, y, h, w, tilt, base, seed=1):
    r = make_ramp(base)
    tx = x + tilt
    pts = [(x - w / 2, y), (x - w / 2 + tilt * 0.25, y - h * 0.78), (tx, y - h), (x + w / 2 + tilt * 0.25, y - h * 0.78),
           (x + w / 2, y)]

    def fn(xx, yy, px, py):
        cx = x + tilt * ((y - yy) / h)
        u = (xx - cx) / (w / 2)
        t = 0.34 if u > 0.1 else (0.8 - 0.1 * abs(u) if u < -0.1 else 0.58)
        t += 0.18 * ((y - yy) / h) + (h2(px, py, seed) - 0.5) * 0.08
        return pick(r, t, px, py)
    c.paint(pts, fn, OLC(r, 0.55))
    c.line([(x - w / 2 + 1, y - 2), (x - w / 2 + tilt * 0.25 + 1, y - h * 0.76)], r[4])


def crystal_base():
    c = Canvas(170, 160)
    shadow_ell(c, 85, 150, 78, 6)
    glow_l = c.layer()
    gd = ImageDraw.Draw(glow_l)
    for rr, a in ((70, 22), (54, 30), (38, 40)):
        gd.polygon(c.P(ell_pts(85, 96, rr, rr * 0.9)), fill=(160, 110, 230, a))
    c.comp(glow_l)
    rock = make_ramp((70, 62, 84))
    c.paint(ell_pts(85, 142, 70, 14), lambda x, y, px, py: pick(rock, 0.5 + (fbm(x * .2, y * .2, 2) - 0.5) * .6 - 0.2 * (y - 130) / 24, px, py),
            OLC(rock, 0.6))
    for (x, h, w, tl, col) in ((30, 52, 18, -8, (96, 130, 214)), (140, 60, 20, 9, (196, 100, 190)),
                               (58, 80, 24, -6, (140, 96, 214)), (112, 92, 26, 8, (110, 120, 220)),
                               (84, 124, 34, 2, (170, 110, 232)), (46, 38, 14, -12, (200, 110, 200)),
                               (126, 40, 14, 10, (96, 150, 220))):
        crystal(c, x, 142 + (3 if h < 60 else 0), h, w, tl, col, int(x))
    return c.result()


def volcano_base():
    c = Canvas(180, 190)
    shadow_ell(c, 90, 184, 84, 6)
    rock = make_ramp((70, 60, 66))
    lava = [(120, 28, 14, 255), (190, 56, 20, 255), (244, 120, 36, 255), (255, 190, 80, 255), (255, 236, 160, 255)]
    pts = [(14, 184), (52, 110), (66, 58), (84, 30), (100, 30), (116, 58), (130, 110), (166, 184)]

    def fn(x, y, px, py):
        u = (x - 90) / 76
        z = math.sqrt(max(0.0, 1 - u * u))
        lam = u * LIGHT[0] * 1.1 + z * LIGHT[2] * 1.3
        t = 0.2 + 0.8 * max(0.0, lam) + (fbm(x * 0.12, y * 0.09, 5) - 0.5) * 0.7 - 0.2 * abs(u) ** 3
        ridge = abs(fbm(x * 0.05 + 3, y * 0.07, 8) - 0.5)
        if ridge < 0.022 and y > 44:
            return pick(lava, 0.55 + (0.022 - ridge) * 18, px, py)
        return pick(rock, t, px, py)
    c.paint(pts, fn, OLC(rock, 0.5))
    c.paint(ell_pts(92, 30, 17, 6), lambda x, y, px, py: pick(lava, 0.6 + (30 - y) * 0.05 + (h2(px, py, 2) - 0.5) * 0.3, px, py),
            (60, 24, 14, 255))
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for i in range(6):
        ld.polygon(c.P(ell_pts(88 + i * 4 + (i % 2) * 3, 22 - i * 4.5, 6 + i * 1.8, 5 + i * 1.3)), fill=(70, 66, 74, 110 - i * 14))
    c.comp(lay)
    return c.result()


def tower_base():
    c = Canvas(170, 210)
    shadow_ell(c, 85, 204, 70, 5)
    st = make_ramp((126, 128, 142))
    body = [(48, 204), (52, 70), (122, 70), (126, 204)]

    def brick(x, y, px, py):
        row = int((y - 70) / 9)
        off = 7 if row % 2 else 0
        col = int((x + off) / 14)
        u = (x - 87) / 40
        z = math.sqrt(max(0.0, 1 - min(1.0, u * u)))
        lam = u * LIGHT[0] * 1.2 + z * LIGHT[2] * 1.2
        t = 0.2 + 0.8 * max(0.0, lam) - 0.15 * abs(u) ** 3
        t += (h2(col, row, 4) - 0.5) * 0.22 + (fbm(x * 0.3, y * 0.3, 3) - 0.5) * 0.25
        if (y - 70) % 9 < 1.2 or (x + off) % 14 < 1.2:
            t -= 0.28
        return pick(st, t, px, py)
    c.paint(body, brick, OLC(st, 0.5))
    for i in range(5):
        x = 48 + i * 17
        pp(c, [(x, 70), (x, 56), (x + 11, 56), (x + 11, 70)], st)
    for wy, glow_ in ((98, True), (140, False)):
        arch = [(78, wy + 22), (78, wy + 8), (82, wy), (92, wy), (96, wy + 8), (96, wy + 22)]
        wr = make_ramp((236, 190, 80)) if glow_ else make_ramp((40, 36, 48))
        c.paint(arch, lambda x, y, px, py, wr=wr: pick(wr, 0.7 - 0.3 * (y - 98) / 26, px, py), OLC(st, 0.4))
    c.line([(87, 56), (87, 18)], (60, 62, 74, 255))
    c.poly([(84, 18), (87, 8), (90, 18)], (60, 62, 74, 255))
    lay = c.layer()
    ImageDraw.Draw(lay).polygon(c.P(ell_pts(87, 10, 8, 8)), fill=(190, 210, 255, 90))
    c.comp(lay)
    for lx, ly, rr in ((30, 200, 8), (140, 198, 10), (22, 204, 5)):
        ep(c, lx, ly, rr * 1.4, rr * 0.8, st, fur=0.3, seed=lx)
    for x in (54, 70, 106, 118):
        c.line([(x, 80), (x + 1, 120)], (74, 110, 62, 255))
    return c.result()


# ============================================================ JEFE FINAL: VESPA REINA
QUEEN = dict(HORNET, abd_col=(184, 70, 40), bands=[(14, 6, (54, 28, 22)), (24, 6, (54, 28, 22)),
                                                    (34, 6, (54, 28, 22)), (44, 5, (54, 28, 22))],
             thx_col=(58, 30, 24), head_col=(204, 96, 44), eye_col=(110, 14, 10), scale=3.5,
             wing_fill=(150, 100, 70, 118), wing_edge=(80, 44, 24, 230), wing_len=46, wing_w=14)


def queen_lair(phase, frame):
    c = Canvas(420, 400)
    paper = (156, 132, 100)
    # niu enorme de fons
    for i in range(12, -1, -1):
        yy = 150 + i * 18
        t = (yy - 262) / 130
        rx = 170 * math.sqrt(max(0.05, 1 - t * t))
        base = (150, 126, 96) if i % 2 == 0 else (126, 104, 78)
        ep(c, 262, yy + 8, rx, 17, make_ramp(base), fur=0.55, seed=70 + i, tone=-0.05 + 0.02 * (12 - i) / 12, rim=0.15)
    dk = make_ramp((26, 18, 14))
    c.paint(ell_pts(300, 330, 42, 36), lambda x, y, px, py: pick(dk, 0.4 - 0.2 * (y - 300) / 60, px, py),
            OLC(make_ramp(paper), 0.4))
    # esquerdes segons la fase
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    cracks = [[(250, 170), (262, 200), (254, 230), (270, 262)], [(330, 190), (318, 224), (336, 252)],
              [(210, 280), (232, 296), (226, 320)], [(300, 150), (292, 176), (306, 196)]]
    if phase >= 1:
        for pts in cracks[:2 + (phase - 1) * 2]:
            ld.line(c.P(pts), fill=(36, 22, 16, 255), width=2)
            if phase == 2:
                ld.line(c.P([(x + 1.5, y) for x, y in pts]), fill=(238, 120, 48, 220), width=1)
    c.comp(lay)
    # reina
    if phase == 2:
        aura = c.layer()
        ad = ImageDraw.Draw(aura)
        for rr, a in ((120, 26), (100, 34), (80, 44)):
            ad.polygon(c.P(ell_pts(118, 150, rr, rr * 0.8)), fill=(230, 70, 40, a))
        c.comp(aura)
    q = bee(dict(QUEEN, eye_col=(150, 18, 12) if phase else (84, 20, 16)), frame)
    q = q.transpose(Image.FLIP_LEFT_RIGHT)
    qx, qy = 0, int(58)
    c.im.alpha_composite(q, (qx, qy))
    # corona i ulls brillants
    hx = qx + q.width - (70 + 2.6) * QUEEN["scale"] * F
    hy = qy + (43 - 0.8) * QUEEN["scale"] * F
    gold = make_ramp((226, 188, 70))
    for k in range(5):
        bx = hx - 15 + k * 7
        h_ = 20 if k % 2 == 0 else 12
        pp(c, [(bx / c.k, (hy - 14) / c.k), ((bx + 3.5) / c.k, (hy - 14 - h_) / c.k), ((bx + 7) / c.k, (hy - 14) / c.k)], gold)
    if phase:
        glow = c.layer()
        gd = ImageDraw.Draw(glow)
        for rr, a in ((12, 70), (8, 130)):
            gd.ellipse((hx - rr, hy - rr, hx + rr, hy + rr), fill=(255, 60, 40, a))
        c.comp(glow)
    return c.result()


# ================================================================ PROJECTIL I EFECTES NOUS
def proj_tongue():
    c = Canvas(16, 16)
    ep(c, 8, 8, 5.4, 4.2, make_ramp((214, 110, 120)), ol=True, rim=0.1)
    return c.result()


def fx_lava_frames(n=5):
    out = []
    for i in range(n):
        im, d = _fx(44, 84)
        t = (i + 1) / n
        h = int(10 + t * 64 * (1 if i < 4 else 0.7))
        a = 255 if i < 4 else 120
        w = 9 + (1 - abs(0.5 - t) * 1.4) * 8
        d.polygon([(22 - w, 84), (22 - w * 0.5, 84 - h), (22 + w * 0.5, 84 - h), (22 + w, 84)], fill=(230, 90, 30, a))
        d.polygon([(22 - w * 0.55, 84), (22 - w * 0.25, 84 - h * 0.9), (22 + w * 0.25, 84 - h * 0.9), (22 + w * 0.55, 84)],
                  fill=(255, 190, 80, a))
        d.ellipse((22 - w, 78, 22 + w, 86), fill=(255, 220, 130, a))
        rnd = random.Random(i)
        for _ in range(7):
            x, y = 22 + rnd.uniform(-w, w) * 1.4, 84 - rnd.uniform(0.3, 1.1) * h
            d.rectangle((x, y, x + 1, y + 1), fill=(255, 210, 110, a))
        out.append(im)
    return out


def fx_bolt_frames(n=4):
    out = []
    rnd = random.Random(7)
    pts = [(15, 0)]
    for k in range(1, 9):
        pts.append((15 + rnd.uniform(-9, 9), k * 13.5))
    for i in range(n):
        im, d = _fx(34, 120)
        a = 255 if i < 3 else 110
        d.line([(x + 2, y) for x, y in pts], fill=(150, 170, 255, a // 2), width=5)
        d.line(pts, fill=(236, 244, 255, a), width=2)
        d.ellipse((6, 108, 28, 120), fill=(230, 240, 255, a // 2))
        if i == 1:
            d.line([pts[4], (pts[4][0] + 9, pts[4][1] + 22)], fill=(236, 244, 255, a), width=1)
        out.append(im)
    return out


def fx_flames(n=4):
    out = []
    for i in range(n):
        im, d = _fx(20, 30)
        for bx, ph in ((6, 0.0), (13, 0.4)):
            t = (i / n + ph) % 1.0
            y = 26 - t * 18
            r = 3.4 * (1 - t * 0.6)
            d.ellipse((bx - r, y - r * 1.4, bx + r, y + r), fill=(246, 130, 40, 230))
            d.ellipse((bx - r * 0.5, y - r * 0.6, bx + r * 0.5, y + r * 0.6), fill=(255, 220, 120, 240))
        out.append(im)
    return out


def fx_sting_rain(n=5):
    out = []
    for i in range(n):
        im, d = _fx(34, 96)
        if i < 3:
            y = 10 + i * 30
            d.polygon([(17, y + 24), (13, y), (21, y)], fill=(48, 30, 24, 255))
            d.line([(17, y - 10), (17, y)], fill=(230, 100, 60, 180), width=1)
        else:
            a = 255 - (i - 3) * 110
            d.polygon([(17, 92), (12, 70), (22, 70)], fill=(48, 30, 24, a))
            for k in range(8):
                ang = k * math.pi / 4
                d.line([(17, 88), (17 + math.cos(ang) * (10 + i * 3), 88 + math.sin(ang) * (6 + i * 2))],
                       fill=(240, 120, 70, a), width=1)
        out.append(im)
    return out


def build_fx2():
    out = {"fx_lava": fx_lava_frames(), "fx_bolt": fx_bolt_frames(), "fx_burn": fx_flames(),
           "fx_stinger": fx_sting_rain()}
    return {k: [up(f) for f in v] for k, v in out.items()}


ENEMY_FUNCS.update(dict(frog=frog, dragonfly=dragonfly, scorpion=scorpion, scorpion_king=scorpion_king,
                        centipede=centipede, swallow=swallow, fireant=fireant))


# ================================================================ FONS NOUS
def fill_rect(c, y0, y1, col):
    c.poly([(0, y0), (1000, y0), (1000, y1), (0, y1)], col + (255,))


def bg_swamp():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 340, (84, 108, 102), (178, 192, 152))
    fill_rect(sky, 340, 440, (178, 192, 152))
    glow(sky, 760, 110, (74, 54, 38), (240, 236, 190), (16, 28, 48))
    ep(sky, 760, 110, 26, 26, make_ramp((244, 238, 196)), ol=False, rim=0, tone=0.5)
    mid = Canvas(1000, 440)
    hills(mid, 352, [(16, 0.01), (8, 0.03)], make_ramp((86, 108, 94)), 1, 0.2, 40)
    trunk, leaf = make_ramp((62, 58, 44)), make_ramp((50, 82, 60))
    rnd = random.Random(3)
    for x in range(30, 1000, 120):
        x += rnd.randint(-20, 20)
        top = rnd.randint(190, 250)
        pp(mid, [(x - 9, 384), (x - 4, top), (x + 4, top), (x + 9, 384)], trunk, ol=False, fur=0.3, seed=x)
        for dx, dy, rx, ry in ((0, 0, 34, 16), (-24, 8, 22, 12), (24, 10, 24, 12)):
            ep(mid, x + dx, top + dy, rx, ry, leaf, fur=0.4, seed=x + dx, ol=False, rim=0.2)
        for k in range(9):
            mx = x - 30 + k * 7
            mid.line([(mx, top + 8), (mx + rnd.uniform(-1, 1), top + 8 + rnd.uniform(14, 40))], (116, 136, 98, 255))
    lay = mid.layer()
    ld = ImageDraw.Draw(lay)
    for k in range(60):
        ld.rectangle((0, int((330 + k) * mid.k), lay.size[0], int((331 + k) * mid.k)), fill=(190, 204, 180, int(78 * (1 - abs(k - 30) / 30))))
    mid.comp(lay)
    g = Canvas(1000, 440)
    gr = ground_layer(g, 374, (86, 90, 58), 4, 0.6)
    wr = make_ramp((74, 112, 116))
    for x, y, rx in ((120, 410, 70), (400, 424, 90), (700, 408, 60), (900, 428, 80)):
        g.paint(ell_pts(x, y, rx, 9), lambda xx, yy, px, py: pick(wr, 0.55 + math.sin(xx * 0.5 + yy) * 0.1 - 0.2 * (yy - y) / 9, px, py), OLC(gr, 0.7))
    blades(g, 374, gr, 160, 6)
    fg = Canvas(1000, 440)
    for x in range(10, 1000, 34):
        r_ = random.Random(x)
        h = r_.uniform(36, 70)
        fg.line([(x, 440), (x + r_.uniform(-3, 3), 440 - h)], (50, 76, 44, 255))
        if r_.random() < 0.5:
            ep(fg, x, 440 - h - 4, 2.2, 7, make_ramp((104, 70, 46)), rim=0.2)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def bg_cave():
    sky = Canvas(1000, 440)
    wall = make_ramp((70, 58, 88))
    sky.paint([(0, 0), (1000, 0), (1000, 440), (0, 440)],
              lambda x, y, px, py: pick(wall, 0.42 - 0.22 * y / 440 + (fbm(x * 0.02, y * 0.03, 1) - 0.5) * 0.7 + (fbm(x * 0.12, y * 0.12, 4) - 0.5) * 0.2, px, py), None)
    rnd = random.Random(8)
    for _ in range(14):
        x = rnd.uniform(0, 1000)
        h = rnd.uniform(40, 110)
        w = rnd.uniform(14, 30)
        pp(sky, [(x - w, 0), (x, h), (x + w, 0)], make_ramp((52, 42, 68)), ol=False, fur=0.3, seed=int(x))
    for x, y, col in ((200, 150, (170, 110, 230)), (700, 120, (110, 150, 230)), (480, 190, (220, 120, 200))):
        glow(sky, x, y, (50, 36, 24), col, (14, 22, 34))
        crystal(sky, x, y + 10, 30, 10, -4, col, int(x))
        crystal(sky, x + 14, y + 12, 22, 8, 5, col, int(x) + 1)
    mid = Canvas(1000, 440)
    hills(mid, 378, [(40, 0.012), (24, 0.03)], make_ramp((52, 44, 70)), 2, 0.3, 60)
    for x, col in ((140, (150, 100, 230)), (420, (110, 140, 226)), (610, (210, 110, 200)), (860, (150, 100, 230))):
        glow(mid, x, 360, (60, 44, 28), col, (12, 20, 30))
        for dx, h, w, tl in ((-14, 34, 11, -5), (0, 52, 14, 2), (14, 30, 10, 6)):
            crystal(mid, x + dx, 384, h, w, tl, col, x + dx)
    g = Canvas(1000, 440)
    gr = ground_layer(g, 378, (76, 68, 94), 5, 0.6)
    rr = make_ramp((92, 84, 112))
    for _ in range(20):
        x, y = rnd.uniform(0, 1000), rnd.uniform(388, 436)
        s = rnd.uniform(2, 6)
        ep(g, x, y, s * 1.5, s, rr, fur=0.3, seed=int(x), rim=0.25)
    for x, col in ((70, (170, 110, 230)), (520, (110, 150, 230)), (930, (220, 120, 200))):
        crystal(g, x, 432, 22, 8, 3, col, x)
    fg = Canvas(1000, 440)
    st = make_ramp((36, 30, 50))
    for x in range(20, 1000, 110):
        w = random.Random(x).uniform(10, 22)
        pp(fg, [(x - w, 440), (x, 440 - random.Random(x + 1).uniform(24, 56)), (x + w, 440)], st, ol=False, fur=0.3, seed=x)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def bg_volcano():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 380, (26, 12, 16), (200, 88, 38))
    fill_rect(sky, 380, 440, (200, 88, 38))
    pix = sky.im.load()
    for y in range(0, int(300 * sky.k)):
        for x in range(sky.w):
            n = fbm(x / sky.k * 0.01, y / sky.k * 0.02, 12)
            if n > 0.5:
                a = (n - 0.5) * 1.6 * (1 - y / (300 * sky.k) * 0.6)
                r, g_, b, _ = pix[x, y]
                pix[x, y] = (int(r * (1 - a * 0.55)), int(g_ * (1 - a * 0.6)), int(b * (1 - a * 0.5)), 255)
    mid = Canvas(1000, 440)
    rock = make_ramp((54, 42, 50))
    lava = [(120, 28, 14, 255), (190, 56, 20, 255), (244, 120, 36, 255), (255, 190, 80, 255), (255, 236, 160, 255)]
    for (x0, apex, x1, ap_y) in ((60, 220, 480, 170), (520, 800, 1020, 200)):
        pts = [(x0, 392), (apex - 70, 260), (apex - 14, ap_y), (apex + 14, ap_y), (apex + 70, 262), (x1, 392)]

        def fn(x, y, px, py, apex=apex):
            u = (x - apex) / 220
            t = 0.5 - 0.26 * abs(u) - 0.1 * (y - 170) / 220 + (fbm(x * 0.05, y * 0.06, 5) - 0.5) * 0.45
            if abs(fbm(x * 0.03 + 3, y * 0.05, 8) - 0.5) < 0.016 and y > ap_y + 12:
                return pick(lava, 0.55, px, py)
            return pick(rock, t, px, py)
        mid.paint(pts, fn, None)
        glow(mid, apex, ap_y + 4, (46, 32, 20), (255, 140, 50), (30, 46, 70))
    hills(mid, 396, [(16, 0.012), (8, 0.03)], make_ramp((42, 34, 42)), 6, 0.3, 40)
    g = Canvas(1000, 440)
    ramp = make_ramp((58, 50, 58))

    def gfn(x, y, px, py):
        t = 0.5 - 0.2 * (y - 378) / 62 + (fbm(x * 0.05, y * 0.14, 3) - 0.5) * 0.55
        crack = abs(fbm(x * 0.035 + 9, y * 0.1, 11) - 0.5)
        if crack < 0.018:
            return pick(lava, 0.4 + (0.018 - crack) * 30, px, py)
        return pick(ramp, t, px, py)
    g.paint([(0, 378), (1000, 378), (1000, 440), (0, 440)], gfn, None)
    g.line([(0, 378), (1000, 378)], ramp[4])
    rnd = random.Random(9)
    for _ in range(16):
        x, y = rnd.uniform(0, 1000), rnd.uniform(388, 436)
        s = rnd.uniform(2, 6)
        ep(g, x, y, s * 1.5, s, make_ramp((74, 62, 70)), fur=0.3, seed=int(x), rim=0.25)
    fg = Canvas(1000, 440)
    for x, s in ((90, 16), (520, 12), (860, 18)):
        ep(fg, x, 438, s * 1.8, s, make_ramp((38, 30, 38)), fur=0.4, seed=x, rim=0.25)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def bg_storm():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 380, (24, 28, 42), (98, 106, 126))
    fill_rect(sky, 380, 440, (98, 106, 126))
    pix = sky.im.load()
    for y in range(0, int(300 * sky.k)):
        for x in range(sky.w):
            n = fbm(x / sky.k * 0.008, y / sky.k * 0.018, 21)
            a = max(0.0, n - 0.44) * 1.5
            if a > 0:
                r, g_, b, _ = pix[x, y]
                v = int(40 * a)
                pix[x, y] = (min(255, r + v), min(255, g_ + v), min(255, b + int(v * 1.2)), 255)
    mid = Canvas(1000, 440)
    hills(mid, 342, [(46, 0.008), (22, 0.02)], make_ramp((50, 56, 72)), 3, 0.3, 80)
    cliff = make_ramp((44, 48, 62))
    rnd = random.Random(5)
    for x in range(40, 1000, 190):
        w = rnd.uniform(50, 80)
        h = rnd.uniform(70, 140)
        pts = [(x - w, 392), (x - w * 0.7, 392 - h * 0.6), (x - w * 0.3, 392 - h), (x + w * 0.2, 392 - h * 0.85),
               (x + w * 0.6, 392 - h * 0.4), (x + w, 392)]
        pp(mid, pts, cliff, ol=False, fur=0.4, seed=x)
    g = Canvas(1000, 440)
    gr = ground_layer(g, 376, (60, 72, 64), 7, 0.55)
    wr = make_ramp((86, 100, 122))
    for x, y, rx in ((160, 414, 60), (480, 424, 80), (820, 410, 70)):
        g.paint(ell_pts(x, y, rx, 7), lambda xx, yy, px, py: pick(wr, 0.6 + math.sin(xx * 0.6) * 0.08, px, py), OLC(gr, 0.7))
    blades(g, 376, gr, 200, 8, 4, 9)
    fg = Canvas(1000, 440)
    for x in range(-4, 1000, 9):
        r_ = random.Random(x)
        h = r_.uniform(8, 20)
        fg.line([(x, 440), (x + r_.uniform(-3, 3), 440 - h)], (30, 42, 38, 255))
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def hex_edge(x, y, s):
    q = (x * 0.5773502692 - y / 3) / s
    r = (y * 2 / 3) / s
    cx_, cz = q, r
    cy_ = -cx_ - cz
    rx, ry, rz = round(cx_), round(cy_), round(cz)
    dx, dy, dz = abs(rx - cx_), abs(ry - cy_), abs(rz - cz)
    if dx > dy and dx > dz:
        rx = -ry - rz
    elif dy > dz:
        ry = -rx - rz
    else:
        rz = -rx - ry
    d = max(abs(cx_ - rx), abs(cy_ - ry), abs(cz - rz))
    return min(1.0, d * 2.0), (rx, rz)


def bg_lair():
    sky = Canvas(1000, 440)
    paper = make_ramp((124, 98, 70))

    def wall(x, y, px, py):
        e, cell = hex_edge(x, y, 30)
        t = 0.62 - 0.4 * e ** 2 + (h2(cell[0], cell[1], 3) - 0.5) * 0.18 - 0.22 * y / 440
        t += (fbm(x * 0.1, y * 0.1, 2) - 0.5) * 0.18
        if e < 0.34:
            t -= 0.22
        return pick(paper, t, px, py)
    sky.paint([(0, 0), (1000, 0), (1000, 440), (0, 440)], wall, None)
    lay = sky.layer()
    ImageDraw.Draw(lay).rectangle((0, 0, lay.size[0], lay.size[1]), fill=(20, 12, 8, 120))
    sky.comp(lay)
    mid = Canvas(1000, 440)
    pr = make_ramp((106, 84, 60))
    for x, w in ((60, 46), (330, 38), (610, 50), (900, 40)):
        pts = [(x - w, 392), (x - w * 0.8, 40), (x + w * 0.8, 40), (x + w, 392)]

        def fn(xx, yy, px, py, x=x, w=w):
            u = (xx - x) / w
            z = math.sqrt(max(0.0, 1 - min(1.0, u * u)))
            t = 0.2 + 0.8 * max(0.0, u * LIGHT[0] + z * LIGHT[2]) + (fbm(xx * 0.4, yy * 0.04, 7) - 0.5) * 0.45
            return pick(pr, t - 0.1, px, py)
        mid.paint(pts, fn, None)
        for k in range(5):
            yy = 80 + k * 60
            mid.paint(ell_pts(x, yy, w * 0.4, 7), lambda xx, yy_, px, py: pick(make_ramp((24, 16, 12)), 0.4, px, py), (60, 44, 30, 255))
    g = Canvas(1000, 440)
    gr = ground_layer(g, 380, (116, 94, 68), 11, 0.5)
    dk = make_ramp((30, 20, 16))
    for x, y in ((100, 410), (260, 424), (440, 412), (620, 428), (790, 410), (930, 426)):
        g.paint(ell_pts(x, y, 20, 5), lambda xx, yy, px, py: pick(dk, 0.45, px, py), (74, 54, 38, 255))
    fg = Canvas(1000, 440)
    for x in range(30, 1000, 130):
        r_ = random.Random(x)
        fg.line([(x, 0), (x + r_.uniform(-4, 4), r_.uniform(40, 90))], (60, 42, 30, 255), 2)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


# ============================================================ MÉS ENEMICS
def snail(frame):
    c = Canvas(100, 80, 1.3)
    br, sh = make_ramp((124, 134, 98)), make_ramp((178, 120, 74))
    st = 1.5 + 1.5 * wv(frame, 1)
    ep(c, 40, 61, 30 + st, 8, br, fur=0.2, seed=1)
    ep(c, 70 + st, 52, 9, 8, br)
    for dx in (2, 8):
        x0 = 70 + st + dx
        c.line([(x0, 46), (x0 + 2, 36 + wv(frame, 1.2))], OLC(br))
        ep(c, x0 + 2, 35 + wv(frame, 1.2), 2.0, 2.0, make_ramp((30, 28, 24)), ol=False, rim=0)
    ep(c, 34, 40, 22, 20, sh, 0.0, fur=0.12, gloss=True, seed=2)
    pts = [(34 + math.cos(t * 0.35) * (1.5 + t * 0.32) * 0.9, 40 + math.sin(t * 0.35) * (1.5 + t * 0.32) * 0.9)
           for t in range(60)]
    c.line(pts, OLC(sh, 0.9))
    return c.result()


def crab(frame, scale=1.2, base=(206, 96, 64)):
    c = Canvas(100, 80, scale)
    r = make_ramp(base)
    s = wv(frame, 3)
    for i, bx in enumerate((32, 40, 48, 56)):
        sg = s * (1 if i % 2 else -1)
        c.line([(bx, 56), (bx - 3 + sg * 0.4, 62), (bx - 7 + sg, 70)], OLC(r, 0.8))
    ep(c, 48, 52, 24, 13, r, 0.0, fur=0.2, seed=3)
    c.line([(60, 43), (60, 36)], OLC(r))
    c.line([(67, 43), (68, 36)], OLC(r))
    for ex in (60, 68):
        ep(c, ex, 34, 2.4, 2.4, make_ramp((240, 236, 220)), ol=True, rim=0)
        c.put(ex + 0.5, 34, (20, 18, 18, 255))
    op = 2 + 2 * wv(frame, 1)
    c.line([(70, 52), (80, 44), (86, 38)], r[1], 3)
    pp(c, [(84, 30), (97, 28 + op), (93, 37), (86, 39)], r)
    pp(c, [(84, 41), (97, 43 - op), (93, 37), (86, 36)], r)
    c.line([(68, 58), (76, 56), (80, 52)], r[1], 2)
    pp(c, [(78, 47), (88, 46 + op * 0.5), (84, 52)], make_ramp(tuple(int(v * 0.85) for v in base)))
    return c.result()


def mosquito(frame):
    c = Canvas(100, 80, 1.1)
    gr = make_ramp((116, 106, 96))
    x0, x1, cy, hw = 4, 48, 47, 4.2
    bands = [(bx, 2.5, make_ramp((226, 222, 214))) for bx in (14, 22, 30, 38)]
    ABD = rot(body_pts(x0, x1, cy, hw, 0.7, 1.4, 2.0), x1, cy, -0.12)
    c.paint(ABD, sh_abd(x0, x1, cy, hw, 0.7, 1.4, 2.0, -0.12, gr, bands, 0.15, False, 3), OLC(gr))
    for lx in (50, 55, 60):
        jj = wv(frame, 3) * (1 if lx % 2 else -1)
        c.line([(lx, 47), (lx - 6, 58), (lx - 8 + jj, 74)], OLC(gr, 0.7))
    ep(c, 54, 42, 6.5, 6, gr, fur=0.3, seed=2)
    ep(c, 64, 42, 5, 4.8, gr)
    eye(c, 65, 41, 2.4, 2.8, tint=(230, 200, 190))
    c.line([(68, 44), (88, 51)], OLC(gr), 1)
    wings(c, 53, 36, frame, 34, 6, (206, 214, 222, 90), (100, 108, 120, 210), ((100, 76), (124, 52), (150, 30)))
    return c.result()


def bat(frame):
    c = Canvas(100, 80, 1.25)
    br, mem = make_ramp((92, 78, 104)), make_ramp((62, 50, 76))
    states = (
        [(52, 44), (44, 40), (28, 6), (38, 16), (46, 8), (54, 22), (60, 36)],
        [(52, 44), (40, 42), (6, 26), (20, 36), (14, 46), (32, 48), (48, 50)],
        [(52, 46), (40, 48), (10, 70), (24, 62), (24, 74), (38, 64), (50, 54)])
    wings_ = lerp_pts(states[2], states[0], wt(frame))
    for off in (7, 0):
        poly = [(x + off * (0.6 if y < 60 else 0.3), y) for x, y in wings_]
        pp(c, poly, mem, fur=0.1, seed=off)
        c.line([poly[0], poly[2]], OLC(mem, 0.9))
        c.line([poly[0], poly[4]], OLC(mem, 0.9))
    ep(c, 52, 46, 9, 7.5, br, fur=0.3, seed=3)
    ep(c, 64, 43, 7, 6.5, br)
    for ex in (62, 67):
        pp(c, [(ex - 2, 38), (ex, 31), (ex + 2, 38)], br)
    c.put(66, 42, (222, 70, 60, 255))
    pp(c, [(66, 47), (68, 47), (67, 50)], make_ramp((236, 232, 220)), ol=False)
    c.line([(50, 52), (49, 58)], OLC(br))
    c.line([(55, 52), (56, 58)], OLC(br))
    return c.result()


def termite(frame):
    c = Canvas(100, 80, 1.0)
    tr = make_ramp((228, 208, 164))
    s = wv(frame, 3)
    for i, bx in enumerate((38, 46, 54)):
        sg = s if i % 2 == 0 else -s
        c.line([(bx, 54), (bx + (i - 1) * 3 + sg * 0.4, 60), (bx + (i - 1) * 6 + sg, 69)], OLC(tr, 0.85))
    ep(c, 24, 50, 17, 10.5, tr, 0.05, fur=0.3, seed=1)
    c.line([(18, 41), (17, 59)], OLC(tr))
    c.line([(26, 41), (25, 59)], OLC(tr))
    ep(c, 49, 48, 9, 7, tr, fur=0.2, seed=2)
    ep(c, 66, 47, 8, 7.2, make_ramp((196, 152, 100)), fur=0.15, seed=3)
    pp(c, [(72, 49), (82, 50), (78, 55)], make_ramp((92, 60, 40)))
    eye(c, 68, 44, 2.0, 2.4)
    c.line([(70, 41), (78, 34), (84, 35)], OLC(tr))
    return c.result()


def locust(frame, base=(124, 142, 66), long_ant=False):
    c = Canvas(100, 80, 1.25)
    gr = make_ramp(base)
    ext = 5 + 5 * wv(frame, 1)
    ep(c, 28, 52, 15, 6.5, gr, -0.55, fur=0.2, seed=2)
    c.line([(18, 44), (8 - ext * 0.3, 56), (4 - ext * 0.5, 68)], OLC(gr, 0.85), 2)
    x0, x1, cy, hw = 12, 54, 46, 7.5
    ABD = rot(body_pts(x0, x1, cy, hw, 0.62, 1.7, 2.2), x1, cy, -0.1)
    c.paint(ABD, sh_abd(x0, x1, cy, hw, 0.62, 1.7, 2.2, -0.1, gr, [], 0.2, False, 4), OLC(gr))
    ep(c, 38, 41, 20, 3.6, make_ramp((168, 150, 86)), -0.06, ol=False, rim=0.1)
    for lx in (50, 56):
        c.line([(lx, 52), (lx + 3, 60), (lx + 5 + ext * 0.2, 70)], OLC(gr, 0.85), 1)
    ep(c, 60, 44, 8.5, 8, gr, fur=0.15, seed=5)
    ep(c, 70, 44, 7.5, 9.5, make_ramp((136, 150, 74)), fur=0.15, seed=6)
    eye(c, 72, 41, 3.2, 4.0, tint=(220, 210, 160))
    al = 1.6 if long_ant else 1.0
    c.line([(72, 36), (72 + 8 * al, 28 - 4 * (al - 1) - wv(frame, 1.2)), (72 + 18 * al, 26 - 8 * (al - 1) + wv(frame, 2))], OLC(gr))
    c.line([(68, 36), (68 + 6 * al, 26), (68 + 14 * al, 22 - 4 * (al - 1) + wv(frame, 1.5, 1.0))], OLC(gr))
    return c.result()


def moth(frame):
    c = Canvas(100, 80, 1.3)
    mr, wr = make_ramp((152, 124, 94)), make_ramp((196, 166, 124))
    states = (
        [(52, 46), (42, 42), (24, 6), (40, 8), (56, 18), (64, 34)],
        [(52, 46), (40, 46), (8, 30), (12, 46), (24, 52), (50, 54)],
        [(52, 48), (40, 50), (12, 74), (28, 76), (44, 68), (56, 56)])
    polys = lerp_pts(states[2], states[0], wt(frame))
    for off in (6, 0):
        poly = [(x + off * 0.5, y) for x, y in polys]
        pp(c, poly, wr, fur=0.35, seed=off + 3)
        mx = sum(p[0] for p in poly[2:5]) / 3
        my = sum(p[1] for p in poly[2:5]) / 3
        ep(c, mx + 4, my + 4, 3.6, 3.6, make_ramp((236, 200, 84)), ol=True, rim=0)
        c.put(mx + 4, my + 4, (30, 24, 20, 255))
    ep(c, 52, 51, 10, 6.4, mr, fur=0.7, seed=4)
    ep(c, 63, 49, 6, 5.5, mr, fur=0.5, seed=5)
    eye(c, 65, 48, 2.2, 2.6, tint=(230, 210, 180))
    for off in (0, 4):
        c.line([(64 + off, 45), (68 + off, 36), (74 + off, 32)], OLC(mr))
    return c.result()


def stag(frame):
    c = Canvas(100, 80, 1.4)
    br = make_ramp((74, 44, 34))
    s = wv(frame, 3)
    for i, bx in enumerate((24, 36, 48)):
        sg = s if i % 2 == 0 else -s
        c.line([(bx, 58), (bx + 4 + sg * 0.4, 64), (bx + 8 + sg, 72)], OLC(br, 0.8), 2)
    ep(c, 38, 46, 26, 15, br, 0, fur=0.12, gloss=True, seed=7)
    c.line([(38, 32), (38, 60)], OLC(br))
    ep(c, 63, 47, 9, 12, make_ramp((58, 36, 28)), fur=0.15, seed=8)
    ep(c, 75, 51, 8, 8, make_ramp((52, 32, 26)))
    op = 2 + 2 * wv(frame, 1)
    pp(c, [(78, 46), (88, 36 - op), (98, 31), (99, 36), (92, 43), (84, 50)], make_ramp((66, 38, 28)))
    pp(c, [(78, 56), (88, 58 + op), (98, 53), (97, 58), (86, 62)], make_ramp((66, 38, 28)))
    pp(c, [(88, 38 - op), (90, 33 - op), (92, 40 - op)], make_ramp((96, 60, 44)), ol=False)
    eye(c, 77, 49, 2.4, 2.8, tint=(230, 190, 140))
    return c.result()


def tarantula(frame):
    return spider(frame, 2.0, (96, 70, 52), (110, 80, 60), (150, 110, 70), 0.7)


def widow(frame):
    return spider(frame, 1.2, (36, 32, 40), (52, 46, 58), (206, 52, 44), 0.25)


def frostbeetle(frame):
    return beetle(frame, 1.35, (86, 126, 168), True)


def mantis_king(frame):
    return mantis(frame, 1.9, (62, 96, 58), True)


def crab_king(frame):
    return crab(frame, 1.9, (150, 54, 44))


# ============================================================ MÉS ABELLES
def _cross(c, frame):
    for dx, dy, w, h in ((30, 41, 8, 3), (32.5, 38.5, 3, 8)):
        pp(c, [(dx, dy), (dx + w, dy), (dx + w, dy + h), (dx, dy + h)], (196, 60, 52), ol=False)


def _giant_mand(c, frame):
    """Mandíbules enormes: s'obren i es tanquen amb el vol i es claven en atacar."""
    pose = 0 if frame < NF else frame - NF + 1
    op = 0.5 + 0.5 * wv(frame, 1, 0.4) if pose == 0 else (1.4 if pose == 1 else -0.2)
    u = 6.5 * op
    col = (40, 34, 36)
    pp(c, [(80, 44 - u * 0.3), (96, 40 - u), (99, 47 - u * 0.7), (93, 52 - u * 0.3), (84, 51)], col)
    pp(c, [(80, 52 + u * 0.3), (95, 55 + u), (97, 61 + u), (86, 59 + u * 0.4)], col)
    c.put(90, 46 - u * 0.5, (150, 142, 130, 255))
    c.put(91, 56 + u * 0.6, (150, 142, 130, 255))


BEES.update({
    "miner": dict(abd=(8, 50, 49, 11), peak=0.6, abd_col=(130, 90, 58),
                  bands=[(22, 4, (200, 164, 112)), (32, 4, (200, 164, 112)), (42, 3.5, (200, 164, 112))],
                  thx=(55, 43, 11, 10), thx_col=(200, 114, 52), fuzz_thx=1, head=(69, 44, 7.5, 8),
                  head_col=(90, 64, 46), scale=1.0, wing_len=32, wing_w=10),
    "woolcarder": dict(abd=(6, 50, 49, 12.5), peak=0.56, n_tail=1.9, abd_col=(40, 38, 38), gloss=True,
                       bands=[(16, 3, (232, 198, 62)), (26, 3, (232, 198, 62)), (36, 3, (232, 198, 62)),
                              (45, 2.5, (232, 198, 62))],
                       thx=(55, 43, 11, 10), thx_col=(218, 182, 66), fuzz_thx=1, head=(69, 44, 7.5, 8),
                       head_col=(52, 48, 42), scale=1.05, wing_len=34, wing_w=11),
    "arctic": dict(abd=(2, 54, 50, 17), peak=0.55, n_tail=2.0, abd_col=(214, 224, 234), fur_abd=0.45, tufts_abd=1,
                   bands=[(34, 12, (112, 150, 196)), (14, 13, (236, 240, 246))],
                   thx=(60, 43, 13, 12), thx_col=(240, 244, 250), fuzz_thx=1, fur_thx=0.7,
                   head=(75, 46, 7.5, 8), head_col=(92, 114, 142), scale=1.25, wing_len=26, wing_w=9, tilt=-0.08,
                   wing_fill=(214, 232, 248, 112), wing_edge=(110, 140, 182, 225)),
    "nurse": dict(abd=(8, 52, 48, 11.5), peak=0.62, abd_col=(236, 224, 172),
                  bands=[(20, 4, (152, 192, 132)), (40, 4, (152, 192, 132))],
                  thx=(56, 43, 10.5, 9.5), thx_col=(216, 198, 142), fuzz_thx=1, head=(70, 44, 7.5, 8),
                  head_col=(164, 144, 104), scale=1.0, extra=_cross, wing_len=33, wing_w=11),
    "giant": dict(abd=(0, 56, 49, 15.5), peak=0.6, n_tail=1.8, abd_col=(42, 40, 48), gloss=True,
                  thx=(60, 43, 13, 12), thx_col=(70, 60, 56), fuzz_thx=1, head=(75, 44, 10, 10),
                  head_col=(46, 42, 46), scale=1.8, extra=_giant_mand, wing_len=42, wing_w=13,
                  heave=0.07, tilt_amp=0.09, leg_amp=4.0, leg_w=2, thx_bob=1.4, head_bob=1.0, wing_blur=1,
                  wing_fill=(124, 114, 134, 118), wing_edge=(66, 58, 72, 225)),
    "guard": dict(abd=(8, 52, 49, 13), peak=0.58, n_tail=1.8, abd_col=(132, 92, 40), gloss=True,
                  bands=[(18, 6, (44, 32, 24)), (30, 6, (44, 32, 24)), (42, 6, (44, 32, 24))],
                  thx=(56, 43, 12, 11), thx_col=(78, 58, 42), fuzz_thx=1, head=(71, 44, 8, 8.5),
                  head_col=(54, 42, 34), scale=1.2, wing_len=32, wing_w=10),
})

ENEMY_FUNCS.update(dict(snail=snail, crab=crab, mosquito=mosquito, bat=bat, termite=termite, locust=locust, moth=moth,
                        stag=stag, tarantula=tarantula, widow=widow, frostbeetle=frostbeetle,
                        mantis_king=mantis_king, crab_king=crab_king))


# ============================================================ MÉS EFECTES
def proj_dust():
    c = Canvas(16, 16)
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for r, a in ((7.5, 60), (5.5, 130)):
        ld.polygon(c.P(ell_pts(8, 8, r, r)), fill=(214, 190, 130, a))
    c.comp(lay)
    ep(c, 8, 8, 3.4, 3.4, (224, 204, 150), ol=False, rim=0.1)
    return c.result()


def fx_frost_frames(n=4):
    out = []
    for i in range(n):
        im, d = _fx(40, 40)
        cx = cy = 20
        t = (i + 1) / n
        a = int(255 * (1 - 0.18 * i))
        for k in range(6):
            ang = k * math.pi / 3
            L = 6 + t * 12
            x1, y1 = cx + math.cos(ang) * L, cy + math.sin(ang) * L
            d.line([(cx, cy), (x1, y1)], fill=(206, 236, 255, a), width=1)
            mx, my = cx + math.cos(ang) * L * 0.6, cy + math.sin(ang) * L * 0.6
            for sg in (-1, 1):
                d.line([(mx, my), (mx + math.cos(ang + sg * 0.9) * 4, my + math.sin(ang + sg * 0.9) * 4)],
                       fill=(226, 244, 255, a), width=1)
        d.ellipse((cx - 3, cy - 3, cx + 3, cy + 3), fill=(236, 248, 255, a))
        out.append(im)
    return out


def fx_rock_frames(n=5):
    out = []
    for i in range(n):
        im, d = _fx(40, 96)
        if i < 3:
            y = 6 + i * 26
            d.polygon([(10, y + 18), (14, y + 6), (24, y + 2), (32, y + 10), (30, y + 20), (18, y + 24)], fill=(112, 104, 100, 255),
                      outline=(54, 48, 46, 255))
            d.polygon([(14, y + 8), (22, y + 4), (24, y + 12), (16, y + 14)], fill=(150, 142, 134, 255))
        else:
            a = 255 - (i - 3) * 120
            rnd = random.Random(i)
            for _ in range(10):
                x, y = 20 + rnd.uniform(-14, 14) * (i - 1.5), 84 - rnd.uniform(0, 16) * (i - 1.5)
                d.ellipse((x - 3, y - 3, x + 3, y + 3), fill=(176, 164, 150, a))
            d.polygon([(8, 92), (14, 80), (22, 76), (30, 82), (32, 92)], fill=(112, 104, 100, a))
        out.append(im)
    return out


def fx_ice_frames(n=5):
    out = []
    for i in range(n):
        im, d = _fx(46, 70)
        t = (i + 1) / n
        a = 255 if i < 4 else 120
        for x, h, w in ((12, 40, 7), (23, 62, 9), (34, 34, 6)):
            hh = h * min(1.0, t * 1.3)
            d.polygon([(x - w, 68), (x, 68 - hh), (x + w, 68)], fill=(168, 212, 244, a), outline=(90, 140, 190, a))
            d.polygon([(x - w + 2, 68), (x - 1, 68 - hh * 0.9), (x, 68)], fill=(226, 244, 255, a))
        out.append(im)
    return out


def build_fx3():
    out = {"fx_frost": fx_frost_frames(), "fx_rock": fx_rock_frames(), "fx_ice": fx_ice_frames(),
           "fx_muzzle": fx_muzzle_frames()}
    return {k: [up(f) for f in v] for k, v in out.items()}


# ============================================================ NOUS FONS I TORRES (v4)
def palm(c, x, y, h, lean=10):
    tr = make_ramp((112, 84, 56))
    pp(c, [(x - 3, y), (x + lean - 2, y - h), (x + lean + 2, y - h), (x + 3, y)], tr, ol=False, fur=0.3, seed=int(x))
    leaf = make_ramp((64, 124, 70))
    px, py = x + lean, y - h
    for ang in (170, 140, 110, 70, 40, 10):
        pp(c, lens(px, py, ang, 36, 9), leaf, ol=False, fur=0.3, seed=ang)


def bg_beach():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 330, (80, 166, 206), (214, 232, 230))
    fill_rect(sky, 330, 440, (214, 232, 230))
    glow(sky, 200, 90, (70, 52, 40), (255, 244, 196), (20, 34, 60))
    ep(sky, 200, 90, 34, 34, make_ramp((255, 240, 190)), ol=False, rim=0, tone=0.5)
    mid = Canvas(1000, 440)
    hills(mid, 332, [(26, 0.006), (12, 0.02)], make_ramp((124, 154, 154)), 2, 0.25, 40)
    sea = make_ramp((54, 130, 176))

    def seafn(x, y, px, py):
        t = 0.66 - 0.42 * (y - 318) / 58 + math.sin(x * 0.09 + y * 0.7) * 0.06 + (fbm(x * 0.05, y * 0.4, 3) - 0.5) * 0.25
        if fbm(x * 0.12, y * 0.8, 9) > 0.72:
            return (232, 246, 255, 255)
        return pick(sea, t, px, py)
    mid.paint([(0, 318), (1000, 318), (1000, 380), (0, 380)], seafn, None)
    mid.line([(0, 318), (1000, 318)], sea[4])
    for x, h, ln in ((60, 90, 14), (300, 70, -10), (760, 96, 12), (930, 76, -12)):
        palm(mid, x, 384, h, ln)
    g = Canvas(1000, 440)
    gr = ground_layer(g, 378, (226, 204, 156), 5, 0.35, 0.05)
    foam = g.layer()
    ImageDraw.Draw(foam).rectangle((0, int(378 * g.k), foam.size[0], int(381 * g.k)), fill=(244, 252, 255, 200))
    g.comp(foam)
    rnd = random.Random(4)
    for _ in range(18):
        x, y = rnd.uniform(0, 1000), rnd.uniform(388, 436)
        s = rnd.uniform(2, 5)
        ep(g, x, y, s * 1.4, s, make_ramp(rnd.choice(((236, 196, 176), (230, 222, 206), (190, 150, 120)))), fur=0.3,
           seed=int(x), rim=0.2)
    for x, y in ((140, 420), (620, 428), (880, 414)):
        for k in range(5):
            a = math.radians(k * 72 - 90)
            g.line([(x, y), (x + math.cos(a) * 9, y + math.sin(a) * 9)], (216, 120, 84, 255), 2)
    fg = Canvas(1000, 440)
    for x in range(-4, 1000, 26):
        r_ = random.Random(x)
        for k in range(4):
            fg.line([(x + k * 2, 440), (x + k * 3 + r_.uniform(-4, 4), 440 - r_.uniform(14, 30))], (150, 160, 84, 255))
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def mountain(c, x, w, h, seed, ramp):
    pts = [(x - w, 392), (x - w * 0.4, 392 - h * 0.7), (x - w * 0.08, 392 - h * 0.93), (x, 392 - h),
           (x + w * 0.3, 392 - h * 0.66), (x + w * 0.62, 392 - h * 0.7), (x + w, 392)]
    snow = make_ramp((236, 242, 250))

    def fn(xx, yy, px, py):
        n = (fbm(xx * 0.06, yy * 0.06, seed) - 0.5) * 0.4
        side = 0.2 if xx < x else -0.15
        capline = 392 - h * 0.55 + n * 40
        if yy < capline:
            return pick(snow, 0.66 + side + n * 0.5, px, py)
        return pick(ramp, 0.5 + side + n - 0.15 * (yy - capline) / (h * 0.5), px, py)
    c.paint(pts, fn, None)


def bg_snow():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 330, (112, 134, 168), (214, 226, 238))
    fill_rect(sky, 330, 440, (214, 226, 238))
    glow(sky, 720, 120, (64, 48, 36), (250, 246, 230), (16, 30, 50))
    ep(sky, 720, 120, 26, 26, make_ramp((252, 248, 236)), ol=False, rim=0, tone=0.5)
    mid = Canvas(1000, 440)
    for x, w, h, ramp in ((160, 220, 190, make_ramp((120, 134, 164))), (520, 260, 230, make_ramp((116, 130, 160))),
                          (880, 230, 180, make_ramp((122, 138, 168)))):
        mountain(mid, x, w, h, int(x), ramp)
    for x, w, h in ((60, 150, 110), (340, 170, 130), (700, 190, 120), (960, 130, 100)):
        mountain(mid, x, w, h, int(x) + 3, make_ramp((86, 102, 132)))
    fr = make_ramp((52, 86, 84))
    for x in range(10, 1000, 70):
        h = 60 + (x * 7) % 40
        fir(mid, x, 388, h, fr, make_ramp((60, 46, 40)))
        for i in range(5):
            yy = 388 - h * (0.2 + 0.17 * i)
            rx = h * (0.3 - 0.05 * i)
            ep(mid, x, yy - rx * 0.28, rx * 0.8, rx * 0.26, make_ramp((236, 244, 252)), ol=False, rim=0.1)
    g = Canvas(1000, 440)
    gr = ground_layer(g, 376, (222, 232, 244), 6, 0.4)
    ice = make_ramp((168, 208, 236))
    for x, y, rx in ((200, 414, 60), (560, 424, 80), (860, 410, 54)):
        g.paint(ell_pts(x, y, rx, 7), lambda xx, yy, px, py: pick(ice, 0.6 + math.sin(xx * 0.5) * 0.08, px, py), OLC(gr, 0.7))
    rnd = random.Random(8)
    for _ in range(16):
        x, y = rnd.uniform(0, 1000), rnd.uniform(386, 436)
        ep(g, x, y, rnd.uniform(5, 12), rnd.uniform(2, 4), make_ramp((244, 248, 254)), ol=False, rim=0.15)
    fg = Canvas(1000, 440)
    for x, s in ((40, 22), (400, 16), (760, 24), (980, 18)):
        ep(fg, x, 444, s * 2.4, s, make_ramp((240, 246, 252)), ol=False, rim=0.2)
    for x in (220, 640):
        fg.line([(x, 440), (x + 4, 420), (x - 2, 408)], (74, 58, 50, 255))
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def column(c, x, y, h, w, broken, seed):
    st = make_ramp((158, 144, 128))
    top = y - h
    pts = [(x - w, y), (x - w, top + (6 if broken else 0)), (x - w * 0.3, top - (5 if broken else 0)),
           (x + w * 0.2, top + (8 if broken else 0)), (x + w, top + (2 if broken else 0)), (x + w, y)]

    def fn(xx, yy, px, py):
        u = (xx - x) / w
        z = math.sqrt(max(0.0, 1 - min(1.0, u * u)))
        t = 0.2 + 0.8 * max(0.0, u * LIGHT[0] + z * LIGHT[2]) + 0.06 * math.sin(u * 14) + (fbm(xx * 0.3, yy * 0.15, seed) - 0.5) * 0.4
        return pick(st, t - 0.08 * (yy - top) / h, px, py)
    c.paint(pts, fn, OLC(st, 0.5))
    pp(c, [(x - w - 3, y), (x - w - 3, y - 6), (x + w + 3, y - 6), (x + w + 3, y)], st)
    if not broken:
        pp(c, [(x - w - 3, top), (x - w - 3, top - 7), (x + w + 3, top - 7), (x + w + 3, top)], st)


def bg_ruins():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 340, (186, 140, 116), (110, 94, 106))
    fill_rect(sky, 340, 440, (110, 94, 106))
    glow(sky, 760, 250, (90, 66, 48), (255, 190, 120), (22, 36, 56))
    ep(sky, 760, 250, 34, 34, make_ramp((255, 200, 130)), ol=False, rim=0, tone=0.4)
    mid = Canvas(1000, 440)
    hills(mid, 352, [(30, 0.007), (14, 0.02)], make_ramp((104, 92, 100)), 2, 0.3, 50)
    for x, h, br in ((80, 120, False), (220, 80, True), (400, 140, False), (590, 70, True), (800, 130, False), (940, 90, True)):
        column(mid, x, 388, h, 11, br, int(x))
    arch = make_ramp((140, 126, 112))
    for x0 in (80, 400, 800):
        pts = [(x0, 262), (x0 + 160 if x0 != 800 else x0 + 100, 262), (x0 + 150 if x0 != 800 else x0 + 92, 248), (x0 + 10, 248)]
    for x in (82, 402, 802):
        pp(mid, [(x - 12, 388 - 118), (x + 14, 388 - 118), (x + 12, 388 - 126), (x - 10, 388 - 126)], arch)
    rnd = random.Random(2)
    for _ in range(40):
        x = rnd.choice((80, 400, 800)) + rnd.uniform(-10, 10)
        mid.line([(x, 388 - rnd.uniform(40, 120)), (x + rnd.uniform(-3, 3), 388 - rnd.uniform(10, 40))], (70, 110, 62, 255))
    g = Canvas(1000, 440)
    gr = ground_layer(g, 378, (128, 112, 90), 5, 0.5)
    stone = make_ramp((146, 132, 116))
    for row in range(4):
        for k in range(14):
            x, y = k * 76 + (row % 2) * 38 + rnd.uniform(-6, 6), 392 + row * 12
            ep(g, x, y, 24, 4.2, stone, fur=0.3, seed=row * 20 + k, ol=False, rim=0.2)
    blades(g, 378, make_ramp((74, 110, 62)), 90, 7, 3, 7)
    fg = Canvas(1000, 440)
    for x, s in ((90, 16), (520, 12), (900, 18)):
        ep(fg, x, 440, s * 2.0, s, make_ramp((112, 100, 90)), fur=0.4, seed=x, rim=0.25)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def tower_cyl(c, x, top, bot, w, ramp, seed):
    pts = [(x - w, bot), (x - w, top), (x + w, top), (x + w, bot)]

    def fn(xx, yy, px, py):
        u = (xx - x) / w
        z = math.sqrt(max(0.0, 1 - min(1.0, u * u)))
        t = 0.2 + 0.8 * max(0.0, u * LIGHT[0] + z * LIGHT[2]) + (fbm(xx * 0.5, yy * 0.5, seed) - 0.5) * 0.3
        if int((yy - top) / 7) % 2 == 0 and (yy - top) % 7 < 0.9:
            t -= 0.2
        return pick(ramp, t, px, py)
    c.paint(pts, fn, OLC(ramp, 0.55))
    n = 4
    for i in range(n):
        xx = x - w + i * (2 * w / n)
        pp(c, [(xx, top), (xx, top - 7), (xx + w / n * 1.1, top - 7), (xx + w / n * 1.1, top)], ramp)


def sandcastle():
    c = Canvas(170, 170)
    shadow_ell(c, 85, 164, 78, 5)
    sand = make_ramp((224, 198, 148))
    pts = [(10, 164), (22, 136), (148, 136), (160, 164)]
    pp(c, pts, sand, fur=0.4, seed=3)
    tower_cyl(c, 40, 78, 140, 17, sand, 4)
    tower_cyl(c, 130, 88, 140, 15, sand, 5)
    tower_cyl(c, 85, 52, 140, 22, sand, 6)
    for x, top in ((40, 78), (130, 88)):
        pp(c, [(x - 19, top - 7), (x, top - 28), (x + 19, top - 7)], make_ramp((196, 92, 70)))
    c.line([(85, 52), (85, 14)], (96, 72, 50, 255))
    pp(c, [(85, 14), (110, 20), (85, 28)], (196, 70, 60))
    dk = make_ramp((52, 40, 30))
    c.paint([(72, 140), (72, 116), (78, 108), (92, 108), (98, 116), (98, 140)],
            lambda x, y, px, py: pick(dk, 0.45 - 0.2 * (140 - y) / 34, px, py), OLC(sand, 0.5))
    for x, y in ((24, 160), (150, 160), (110, 164)):
        ep(c, x, y, 5, 3.6, make_ramp((236, 200, 184)), fur=0.3, seed=x, rim=0.2)
    return c.result()


def igloo():
    c = Canvas(180, 150)
    shadow_ell(c, 90, 142, 80, 5)
    ice = make_ramp((196, 224, 244))
    snow = make_ramp((236, 244, 252))
    ep(c, 90, 140, 84, 14, snow, ol=False, rim=0.2, fur=0.2, seed=2)

    def blocks(x, y, px, py):
        dx, dy = (x - 88) / 68, (y - 118) / 64
        r2 = min(1.0, dx * dx + dy * dy)
        z = math.sqrt(1 - r2)
        lam = dx * LIGHT[0] + dy * LIGHT[1] + z * LIGHT[2]
        t = 0.2 + 0.8 * max(0.0, lam) - 0.2 * r2 ** 3
        row = int((y - 50) / 11)
        col = int((x + (6 if row % 2 else 0)) / 16)
        t += (h2(col, row, 7) - 0.5) * 0.14
        if (y - 50) % 11 < 1.1 or (x + (6 if row % 2 else 0)) % 16 < 1.1:
            t -= 0.24
        return pick(ice, t, px, py)
    c.paint(ell_pts(88, 120, 68, 66), blocks, OLC(ice, 0.5))
    c.im.paste((0, 0, 0, 0), (0, int(138 * c.k), c.w, c.h))
    glow_r = make_ramp((244, 188, 96))
    dk = make_ramp((40, 34, 44))
    arch = [(70, 140), (70, 120), (78, 108), (98, 108), (106, 120), (106, 140)]
    c.paint(arch, lambda x, y, px, py: pick(glow_r, 0.9 - 0.7 * (140 - y) / 34, px, py) if abs(x - 88) < 8 and y > 124 else pick(dk, 0.4, px, py),
            OLC(ice, 0.5))
    for x in (60, 70, 108, 118):
        c.poly([(x - 1, 112), (x, 124), (x + 1, 112)], (214, 238, 252, 255))
    return c.result()


def ruins_temple():
    c = Canvas(190, 200)
    shadow_ell(c, 95, 194, 86, 5)
    st = make_ramp((150, 138, 122))
    pp(c, [(30, 150), (160, 150), (160, 194), (30, 194)], st, fur=0.4, seed=3)
    for x, y0, h, br in ((46, 190, 120, False), (144, 190, 84, True), (96, 190, 100, False)):
        column(c, x, y0, h, 11, br, int(x))
    pp(c, [(30, 82), (118, 82), (118, 70), (30, 70)], st, fur=0.3, seed=5)
    rune = make_ramp((120, 220, 190))
    dk = make_ramp((30, 40, 40))
    c.paint([(80, 190), (80, 150), (88, 140), (104, 140), (112, 150), (112, 190)],
            lambda x, y, px, py: pick(dk, 0.35, px, py), OLC(st, 0.5))
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for r_, a in ((14, 40), (9, 90)):
        ld.polygon(c.P(ell_pts(96, 160, r_, r_ * 1.2)), fill=(120, 230, 200, a))
    c.comp(lay)
    for k in range(4):
        c.put(92 + (k % 2) * 8, 154 + k * 3, rune[4])
    rnd = random.Random(3)
    for _ in range(12):
        x = rnd.choice((46, 144, 96)) + rnd.uniform(-10, 10)
        c.line([(x, 190 - rnd.uniform(30, 100)), (x + rnd.uniform(-2, 2), 190 - rnd.uniform(5, 30))], (70, 114, 62, 255))
    return c.result()


def cursed_tree():
    c = Canvas(170, 220)
    shadow_ell(c, 85, 214, 70, 5)
    bk = make_ramp((70, 56, 64))
    trunk = [(40, 212), (58, 140), (54, 70), (66, 40), (110, 40), (122, 74), (116, 140), (140, 212)]
    c.paint(trunk, bark_fn(bk, 88, lambda y: 34 + 26 * max(0.0, min(1.0, (y - 120) / 90)), 21), OLC(bk, 0.5))
    for pts in ([(70, 50), (40, 30), (22, 8)], [(100, 46), (124, 22), (150, 6)], [(86, 42), (84, 18), (96, 2)],
                [(60, 80), (30, 70), (10, 78)], [(120, 84), (146, 76), (164, 86)]):
        c.line(pts, bk[1], 3)
        c.line(pts, bk[3], 1)
    dk = make_ramp((14, 10, 20))
    c.paint(ell_pts(88, 120, 20, 28), lambda x, y, px, py: pick(dk, 0.3, px, py), OLC(bk, 0.5))
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for ex in (80, 96):
        for r_, a in ((8, 50), (5, 110)):
            ld.polygon(c.P(ell_pts(ex, 112, r_, r_ * 0.8)), fill=(190, 110, 255, a))
    c.comp(lay)
    for ex in (80, 96):
        ep(c, ex, 112, 3, 2.4, make_ramp((214, 150, 255)), ol=False, rim=0)
    for x, y in ((18, 40), (150, 30), (30, 90)):
        lay = c.layer()
        ImageDraw.Draw(lay).polygon(c.P(ell_pts(x, y + 8, 5, 5)), fill=(170, 110, 240, 110))
        c.comp(lay)
        c.line([(x, y - 6), (x, y + 4)], (60, 48, 60, 255))
        ep(c, x, y + 8, 3.2, 3.2, make_ramp((190, 140, 250)), ol=False, rim=0)
    return c.result()


# ============================================================ ENEMICS NOUS (v5)
def cricket(frame):
    return locust(frame, (96, 70, 44), True)


def toad_king(frame):
    return frog(frame, 1.9, (126, 102, 70))


def rhino(frame):
    return beetle(frame, 1.9, (60, 74, 58))


def earthworm(frame):
    c = Canvas(100, 80, 1.3)
    pk = make_ramp((218, 140, 130))
    n = 9
    pts = []
    for i in range(n):
        x = 8 + i * 9.4
        y = 58 + math.sin(i * 0.85 + cyc(frame)) * 4.5 - (i * 0.0)
        pts.append((x, y))
    for i in range(n - 1, -1, -1):
        x, y = pts[i]
        base = make_ramp((236, 168, 156)) if i == 6 else pk
        ep(c, x, y, 7.2, 6.4 - (1.2 if i < 1 else 0), base, fur=0.15, seed=60 + i, tone=0.03 * (i % 2), rim=0.2)
        c.line([(x - 3, y - 5), (x - 3.4, y + 5)], OLC(pk, 0.9))
    hx, hy = pts[-1]
    ep(c, hx + 5, hy - 1, 5, 4.6, make_ramp((226, 152, 140)))
    c.put(hx + 8, hy - 2, (40, 24, 24, 255))
    for k in range(3):
        c.put(hx - 20 + k * 22, pts[3][1] - 8, (255, 232, 222, 255))
    return c.result()


def _firefly_glow(c, frame):
    a = int(110 + 120 * wt(frame))
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for r, al in ((14, a // 4), (10, a // 2), (6, a)):
        ld.polygon(c.P(ell_pts(10, 52, r, r * 0.8)), fill=(226, 240, 100, min(255, al)))
    c.comp(lay)
    ep(c, 11, 51, 4, 3.2, make_ramp((246, 250, 140)), ol=False, rim=0)


FIREFLY = dict(abd=(6, 46, 48, 8.5), peak=0.62, n_tail=1.6, abd_col=(56, 48, 44), grooves=0, extra=_firefly_glow,
               thx=(54, 43, 9.5, 8.5), thx_col=(196, 86, 54), head=(66, 44, 6.5, 7), head_col=(44, 40, 38), scale=1.0,
               stinger=False, wing_len=28, wing_w=8, wing_fill=(206, 216, 226, 90), wing_edge=(96, 108, 120, 210))


def firefly(frame):
    return bee(FIREFLY, frame)


ENEMY_FUNCS.update(dict(cricket=cricket, toad_king=toad_king, rhino=rhino, earthworm=earthworm, firefly=firefly))


# ============================================================ FONS I TORRES NOUS (v5)
def brick_shader(ramp, cx, hw, y0, seed=4, bw=14, bh=9):
    def fn(x, y, px, py):
        row = int((y - y0) / bh)
        off = bw / 2 if row % 2 else 0
        col = int((x + off) / bw)
        u = (x - cx) / hw
        z = math.sqrt(max(0.0, 1 - min(1.0, u * u)))
        t = 0.2 + 0.8 * max(0.0, u * LIGHT[0] * 1.2 + z * LIGHT[2] * 1.2) - 0.15 * abs(u) ** 3
        t += (h2(col, row, seed) - 0.5) * 0.22 + (fbm(x * 0.3, y * 0.3, seed) - 0.5) * 0.25
        if (y - y0) % bh < 1.2 or (x + off) % bw < 1.2:
            t -= 0.28
        return pick(ramp, t, px, py)
    return fn


def bg_farm():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 330, (142, 184, 214), (240, 232, 190))
    fill_rect(sky, 330, 440, (240, 232, 190))
    glow(sky, 780, 100, (70, 50, 38), (255, 236, 170), (22, 38, 64))
    ep(sky, 780, 100, 32, 32, make_ramp((255, 238, 176)), ol=False, rim=0, tone=0.5)
    mid = Canvas(1000, 440)
    hills(mid, 338, [(24, 0.007), (12, 0.02)], make_ramp((204, 188, 128)), 1, 0.25, 50)
    red = make_ramp((164, 64, 50))
    pp(mid, [(110, 380), (110, 330), (190, 330), (190, 380)], red, fur=0.3, seed=3)
    pp(mid, [(100, 332), (150, 298), (200, 332)], make_ramp((92, 66, 56)))
    pp(mid, [(138, 380), (138, 350), (162, 350), (162, 380)], make_ramp((236, 226, 200)))
    wall = make_ramp((210, 196, 168))
    pp(mid, [(640, 380), (652, 300), (688, 300), (700, 380)], wall, fur=0.3, seed=5)
    pp(mid, [(644, 302), (670, 276), (696, 302)], make_ramp((150, 70, 54)))
    for ang in (30, 120, 210, 300):
        pp(mid, lens(670, 296, ang, 44, 7), make_ramp((146, 112, 76)), ol=True)
    wheat = make_ramp((222, 186, 84))

    def wfn(x, y, px, py):
        t = 0.58 + math.sin(x * 0.7) * 0.1 + (fbm(x * 0.2, y * 0.5, 2) - 0.5) * 0.4 - 0.25 * (y - 352) / 28
        return pick(wheat, t, px, py)
    mid.paint([(0, 352), (1000, 352), (1000, 380), (0, 380)], wfn, None)
    rnd = random.Random(6)
    for _ in range(420):
        x, y = rnd.uniform(0, 1000), rnd.uniform(350, 376)
        mid.line([(x, y), (x + rnd.uniform(-1, 1), y - rnd.uniform(5, 11))], wheat[rnd.choice((2, 3, 4))])
    g = Canvas(1000, 440)
    gr = ground_layer(g, 378, (150, 116, 78), 4, 0.5)
    for k in range(5):
        y = 388 + k * 10
        g.line([(0, y), (1000, y + 2)], gr[1])
        for x in range(0, 1000, 22):
            g.put(x + (k * 7) % 22, y - 2, (100, 140, 60, 255))
    fg = Canvas(1000, 440)
    for x in range(-4, 1000, 12):
        r_ = random.Random(x)
        h = r_.uniform(16, 36)
        fg.line([(x, 440), (x + r_.uniform(-3, 3), 440 - h)], wheat[r_.choice((1, 2, 3))])
        ep(fg, x, 440 - h - 2, 1.6, 4, wheat, ol=False, rim=0)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def scarecrow():
    c = Canvas(120, 190)
    shadow_ell(c, 60, 184, 44, 5)
    wood = make_ramp((124, 90, 54))
    bur = make_ramp((190, 162, 104))
    pp(c, [(56, 182), (56, 70), (64, 70), (64, 182)], wood, fur=0.3, seed=2)
    pp(c, [(8, 84), (112, 84), (112, 92), (8, 92)], wood, fur=0.3, seed=3)
    pp(c, [(34, 82), (86, 82), (80, 150), (40, 150)], bur, fur=0.4, seed=4)
    for (x, y, w, h) in ((44, 100, 10, 10), (64, 122, 12, 9)):
        pp(c, [(x, y), (x + w, y), (x + w, y + h), (x, y + h)], make_ramp((156, 84, 66)), ol=True)
    for x0 in (8, 100):
        for k in range(5):
            c.line([(x0 + k * 2, 90), (x0 + k * 2 + (-3 if x0 < 50 else 3), 104 + k)], bur[3])
    for k in range(5):
        c.line([(40 + k * 8, 150), (38 + k * 8, 166 + (k % 2) * 4)], bur[3])
    ep(c, 60, 56, 15, 15, make_ramp((206, 180, 124)), fur=0.3, seed=5)
    for ex in (54, 66):
        c.line([(ex - 2, 52), (ex + 2, 56)], (40, 28, 20, 255))
        c.line([(ex - 2, 56), (ex + 2, 52)], (40, 28, 20, 255))
    c.line([(52, 65), (56, 63), (60, 65), (64, 63), (68, 65)], (40, 28, 20, 255))
    ep(c, 60, 44, 26, 6, make_ramp((190, 150, 80)), fur=0.4, seed=6)
    pp(c, [(44, 42), (60, 18), (76, 42)], make_ramp((176, 136, 70)), fur=0.4, seed=7)
    pp(c, [(44, 40), (76, 40), (76, 36), (44, 36)], make_ramp((130, 56, 48)))
    ep(c, 98, 78, 6, 4.2, make_ramp((40, 40, 52)), fur=0.3, seed=8)
    pp(c, [(104, 77), (112, 79), (104, 80)], make_ramp((220, 170, 60)), ol=False)
    c.put(96, 76, (230, 230, 230, 255))
    return c.result()


def bg_jungle():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 340, (56, 104, 92), (168, 204, 148))
    fill_rect(sky, 340, 440, (168, 204, 148))
    lay = sky.layer()
    ld = ImageDraw.Draw(lay)
    for x in (120, 360, 640, 860):
        ld.polygon(sky.P([(x, 0), (x + 40, 0), (x + 120, 340), (x + 30, 340)]), fill=(255, 250, 200, 22))
    sky.comp(lay)
    mid = Canvas(1000, 440)
    hills(mid, 350, [(30, 0.008), (16, 0.02)], make_ramp((52, 98, 70)), 2, 0.3, 60)
    leaf, tk = make_ramp((44, 110, 60)), make_ramp((92, 70, 50))
    for x in (40, 300, 560, 840):
        mid.paint([(x - 20, 392), (x - 13, 90), (x + 13, 90), (x + 20, 392)],
                  bark_fn(tk, x, lambda y: 16 + 6 * (y - 90) / 300, int(x)), OLC(tk, 0.5))
        for dx, dy, rx, ry in ((0, 84, 56, 24), (-40, 96, 36, 18), (42, 98, 38, 18)):
            ep(mid, x + dx, dy, rx, ry, leaf, fur=0.4, seed=int(x) + dx, ol=False, rim=0.2)
        rnd = random.Random(int(x))
        for k in range(7):
            vx = x - 30 + k * 10
            mid.line([(vx, 100), (vx + rnd.uniform(-3, 3), 100 + rnd.uniform(60, 200))], (60, 112, 56, 255))
    g = Canvas(1000, 440)
    gr = ground_layer(g, 378, (60, 88, 52), 6, 0.6)
    rnd = random.Random(4)
    fern = make_ramp((52, 120, 62))
    for _ in range(22):
        x, y = rnd.uniform(0, 1000), rnd.uniform(386, 432)
        for a in (20, 60, 100, 140, 170):
            pp(g, lens(x, y, a, 14, 4), fern, ol=False)
    blades(g, 378, gr, 120, 5)
    fg = Canvas(1000, 440)
    big = make_ramp((36, 98, 52))
    for x, side in ((20, 1), (980, -1)):
        for a in (30, 60, 90, 120, 150):
            pp(fg, lens(x, 446, a if side > 0 else 180 - a, 78, 18), big, ol=True, fur=0.2, seed=a)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def tiki():
    c = Canvas(110, 200)
    shadow_ell(c, 55, 194, 44, 5)
    wd = make_ramp((140, 92, 52))
    st = make_ramp((118, 114, 104))
    pp(c, [(10, 196), (14, 176), (96, 176), (100, 196)], st, fur=0.4, seed=1)
    for k, (y0, y1) in enumerate(((120, 176), (70, 120), (22, 70))):
        wide = 38 - k * 4
        pts = [(55 - wide, y1), (55 - wide, y0), (55 + wide, y0), (55 + wide, y1)]

        def fn(x, y, px, py, wide=wide):
            u = (x - 55) / wide
            z = math.sqrt(max(0.0, 1 - min(1.0, u * u)))
            t = 0.2 + 0.8 * max(0.0, u * LIGHT[0] + z * LIGHT[2]) + (fbm(x * 0.5, y * 0.15, 3) - 0.5) * 0.35
            return pick(wd, t, px, py)
        c.paint(pts, fn, OLC(wd, 0.5))
        my = (y0 + y1) / 2
        for ex in (-14, 14):
            ep(c, 55 + ex, my - 8, 7, 5, make_ramp((30, 22, 16)), ol=True)
            lay = c.layer()
            ImageDraw.Draw(lay).polygon(c.P(ell_pts(55 + ex, my - 8, 9, 7)), fill=(255, 150, 50, 70))
            c.comp(lay)
            ep(c, 55 + ex, my - 8, 3, 2.4, make_ramp((255, 170, 60)), ol=False, rim=0)
        pp(c, [(55 - 14, my + 8), (55 + 14, my + 8), (55 + 10, my + 18), (55 - 10, my + 18)], make_ramp((46, 28, 20)))
        for tx in (-8, 0, 8):
            c.put(55 + tx, my + 9, (230, 220, 190, 255))
        c.line([(55 - wide, y0 + 3), (55 + wide, y0 + 3)], wd[1])
    for k, col in enumerate(((220, 80, 60), (60, 160, 90), (232, 188, 60))):
        pp(c, lens(55, 24, 70 + k * 20, 30, 7), make_ramp(col), ol=True)
    return c.result()


def bg_mine():
    sky = Canvas(1000, 440)
    rock = make_ramp((90, 68, 50))
    sky.paint([(0, 0), (1000, 0), (1000, 440), (0, 440)],
              lambda x, y, px, py: pick(rock, 0.4 - 0.16 * y / 440 + (fbm(x * 0.03, y * 0.04, 1) - 0.5) * 0.7 + (fbm(x * 0.15, y * 0.15, 5) - 0.5) * 0.25, px, py), None)
    wood = make_ramp((124, 88, 52))
    for x in (90, 400, 700, 950):
        pp(sky, [(x - 9, 392), (x - 9, 40), (x + 9, 40), (x + 9, 392)], wood, fur=0.3, seed=x)
    for x0, x1 in ((90, 400), (400, 700), (700, 950)):
        pp(sky, [(x0, 40), (x1, 40), (x1, 60), (x0, 60)], wood, fur=0.3, seed=x0)
        c_ = (x0 + x1) / 2
        sky.line([(x0 + 9, 60), (c_, 120), (x1 - 9, 60)], wood[1], 3)
    for x, y in ((250, 130), (550, 130), (825, 130)):
        glow(sky, x, y, (50, 36, 24), (255, 170, 70), (16, 26, 40))
        sky.line([(x, 62), (x, y - 10)], (60, 50, 44, 255))
        ep(sky, x, y, 5, 7, make_ramp((255, 196, 100)), ol=True, rim=0.05)
    mid = Canvas(1000, 440)
    hills(mid, 384, [(14, 0.012), (8, 0.03)], make_ramp((64, 48, 38)), 3, 0.3, 40)
    g = Canvas(1000, 440)
    gr = ground_layer(g, 380, (112, 88, 64), 7, 0.55)
    for x in range(0, 1000, 26):
        pp(g, [(x, 396), (x + 14, 396), (x + 14, 402), (x, 402)], make_ramp((102, 72, 44)), ol=False)
    g.line([(0, 398), (1000, 398)], (150, 150, 160, 255), 1)
    g.line([(0, 402), (1000, 402)], (110, 110, 124, 255), 1)
    rnd = random.Random(2)
    for _ in range(18):
        x, y = rnd.uniform(0, 1000), rnd.uniform(410, 436)
        ep(g, x, y, rnd.uniform(3, 8), rnd.uniform(2, 4), make_ramp((96, 80, 68)), fur=0.3, seed=int(x), rim=0.25)
    for x in (180, 620):
        ep(g, x, 421, 10, 5, make_ramp((236, 196, 70)), ol=True)
    fg = Canvas(1000, 440)
    for x, s in ((50, 16), (480, 12), (880, 18)):
        ep(fg, x, 440, s * 1.9, s, make_ramp((52, 40, 32)), fur=0.4, seed=x, rim=0.25)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def mine_entrance():
    c = Canvas(190, 170)
    shadow_ell(c, 95, 164, 86, 5)
    wood = make_ramp((130, 92, 54))
    rk = make_ramp((84, 70, 58))
    pp(c, [(14, 166), (30, 80), (160, 80), (176, 166)], rk, fur=0.5, seed=4)
    dk = make_ramp((18, 12, 10))
    glow_l = make_ramp((236, 170, 80))
    c.paint([(56, 166), (56, 74), (134, 74), (134, 166)],
            lambda x, y, px, py: pick(dk, 0.3 + 0.2 * (y - 74) / 92, px, py), OLC(wood, 0.5))
    for x in (50, 140):
        pp(c, [(x - 8, 168), (x - 8, 60), (x + 8, 60), (x + 8, 168)], wood, fur=0.3, seed=x)
    pp(c, [(38, 72), (152, 72), (152, 56), (38, 56)], wood, fur=0.3, seed=9)
    c.line([(50, 70), (68, 56)], wood[1], 3)
    c.line([(140, 70), (122, 56)], wood[1], 3)
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for r, a in ((26, 40), (16, 80)):
        ld.polygon(c.P(ell_pts(95, 56, r, r * 0.8)), fill=(255, 190, 90, a))
    c.comp(lay)
    c.line([(95, 56), (95, 48)], (60, 50, 44, 255))
    ep(c, 95, 66, 4, 5, make_ramp((255, 200, 110)), ol=True, rim=0.05)
    pp(c, [(20, 160), (20, 140), (60, 140), (66, 160)], make_ramp((100, 100, 112)))
    for dx in (28, 38, 48):
        ep(c, dx, 138, 4, 3, make_ramp((236, 196, 70)), ol=True, rim=0.1)
    for cx in (28, 56):
        ep(c, cx, 164, 5, 5, make_ramp((46, 46, 54)))
    for x in range(100, 170, 12):
        pp(c, [(x, 166), (x + 8, 166), (x + 8, 170), (x, 170)], make_ramp((100, 70, 42)), ol=False)
    return c.result()


def bg_graveyard():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 340, (8, 8, 28), (78, 56, 98))
    fill_rect(sky, 340, 440, (78, 56, 98))
    rnd = random.Random(12)
    for _ in range(90):
        sky.put(rnd.uniform(0, 1000), rnd.uniform(0, 230), (226, 226, 214, 255))
    glow(sky, 770, 120, (96, 76, 56), (226, 220, 190), (14, 24, 40))
    mr = make_ramp((236, 232, 206))
    ep(sky, 770, 120, 46, 46, mr, ol=False, rim=0.1, tone=0.2)
    for x, y, r_ in ((752, 108, 9), (790, 132, 12), (768, 140, 6)):
        ep(sky, x, y, r_, r_ * 0.85, make_ramp((190, 186, 166)), ol=False, rim=0.05, tone=-0.15)
    mid = Canvas(1000, 440)
    hills(mid, 356, [(30, 0.008), (14, 0.02)], make_ramp((50, 44, 72)), 2, 0.25, 60)
    stone = make_ramp((102, 104, 120))
    for x in range(30, 1000, 62):
        r_ = random.Random(x)
        h = r_.uniform(24, 44)
        if r_.random() < 0.4:
            pp(mid, [(x - 3, 388), (x - 3, 388 - h), (x + 3, 388 - h), (x + 3, 388)], stone, fur=0.3, seed=x)
            pp(mid, [(x - 10, 388 - h * 0.7), (x + 10, 388 - h * 0.7), (x + 10, 388 - h * 0.7 - 5), (x - 10, 388 - h * 0.7 - 5)], stone)
        else:
            pp(mid, [(x - 11, 388), (x - 11, 388 - h * 0.7), (x - 7, 388 - h), (x + 7, 388 - h), (x + 11, 388 - h * 0.7), (x + 11, 388)],
               stone, fur=0.4, seed=x)
    for x in (150, 520, 880):
        tr = make_ramp((36, 30, 40))
        mid.line([(x, 392), (x + 2, 300), (x - 4, 250)], tr[1], 4)
        for dx, dy in ((-26, -30), (24, -40), (-10, -60), (30, -64)):
            mid.line([(x + 2, 330), (x + dx, 330 + dy)], tr[1], 2)
    for x in range(0, 1000, 8):
        mid.line([(x, 392), (x, 372)], (40, 38, 52, 255))
    mid.line([(0, 380), (1000, 380)], (40, 38, 52, 255))
    lay = mid.layer()
    ld = ImageDraw.Draw(lay)
    for k in range(36):
        ld.rectangle((0, int((350 + k) * mid.k), lay.size[0], int((351 + k) * mid.k)), fill=(150, 150, 190, int(60 * (1 - abs(k - 18) / 18))))
    mid.comp(lay)
    g = Canvas(1000, 440)
    gr = ground_layer(g, 380, (44, 62, 48), 5, 0.55)
    blades(g, 380, gr, 200, 4)
    for x, y in ((220, 412), (580, 424), (860, 408)):
        ep(g, x, y, 30, 6, make_ramp((52, 56, 50)), fur=0.3, seed=x, rim=0.2)
    fg = Canvas(1000, 440)
    for x in range(-4, 1000, 9):
        r_ = random.Random(x)
        fg.line([(x, 440), (x + r_.uniform(-4, 4), 440 - r_.uniform(10, 26))], (26, 40, 32, 255))
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def crypt():
    c = Canvas(190, 190)
    shadow_ell(c, 95, 184, 84, 5)
    st = make_ramp((118, 120, 136))
    pp(c, [(10, 186), (10, 172), (180, 172), (180, 186)], st, fur=0.3, seed=2)
    pp(c, [(24, 172), (24, 160), (166, 160), (166, 172)], st, fur=0.3, seed=3)
    c.paint([(34, 160), (34, 80), (156, 80), (156, 160)], brick_shader(st, 95, 62, 80, 8), OLC(st, 0.5))
    pp(c, [(24, 82), (95, 22), (166, 82)], st, fur=0.3, seed=4)
    pp(c, [(52, 80), (95, 40), (138, 80)], make_ramp((96, 98, 114)), fur=0.3, seed=5)
    for x in (44, 146):
        column(c, x, 160, 76, 8, False, int(x))
    dk = make_ramp((14, 24, 22))
    arch = [(76, 160), (76, 118), (82, 106), (108, 106), (114, 118), (114, 160)]
    c.paint(arch, lambda x, y, px, py: pick(dk, 0.35, px, py), OLC(st, 0.4))
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for r_, a in ((20, 40), (12, 90)):
        ld.polygon(c.P(ell_pts(95, 138, r_, r_ * 1.3)), fill=(110, 240, 170, a))
    c.comp(lay)
    for k in range(3):
        c.put(92 + k * 3, 144 + k * 2, (200, 255, 220, 255))
    ep(c, 95, 62, 6, 7, make_ramp((222, 222, 210)), ol=True)
    c.put(93, 61, (20, 20, 24, 255))
    c.put(97, 61, (20, 20, 24, 255))
    return c.result()


def bg_glacier():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 340, (6, 12, 34), (44, 76, 110))
    fill_rect(sky, 340, 440, (44, 76, 110))
    pix = sky.im.load()
    for y in range(0, int(300 * sky.k)):
        for x in range(sky.w):
            ux, uy = x / sky.k, y / sky.k
            cy_ = 120 + 46 * math.sin(ux * 0.011 + fbm(ux * 0.004, 3, 7) * 4)
            a = math.exp(-((uy - cy_) / 26) ** 2) * (0.35 + 0.65 * fbm(ux * 0.01, uy * 0.03, 8))
            if a > 0.06:
                mix = 0.5 + 0.5 * math.sin(ux * 0.006)
                r, g_, b, _ = pix[x, y]
                pix[x, y] = (min(255, int(r + a * (60 + 100 * mix))), min(255, int(g_ + a * (240 - 60 * mix))),
                             min(255, int(b + a * (140 + 100 * mix))), 255)
    rnd = random.Random(14)
    for _ in range(140):
        sky.put(rnd.uniform(0, 1000), rnd.uniform(0, 250), (236, 240, 255, 255))
    mid = Canvas(1000, 440)
    for x, w, h, ramp in ((160, 220, 150, make_ramp((86, 124, 164))), (540, 260, 190, make_ramp((80, 118, 160))),
                          (900, 220, 140, make_ramp((90, 128, 168)))):
        mountain(mid, x, w, h, int(x), ramp)
    for x, w, h in ((20, 160, 90), (360, 180, 100), (720, 170, 96)):
        mountain(mid, x, w, h, int(x) + 5, make_ramp((70, 104, 146)))
    g = Canvas(1000, 440)
    gr = ground_layer(g, 378, (170, 206, 232), 9, 0.4)
    rnd = random.Random(15)
    for _ in range(26):
        x, y = rnd.uniform(0, 1000), rnd.uniform(386, 436)
        g.line([(x, y), (x + rnd.uniform(14, 40), y + rnd.uniform(-2, 2))], make_ramp((100, 150, 196))[1])
    for x, y in ((140, 414), (500, 426), (800, 410)):
        ep(g, x, y, 34, 6, make_ramp((196, 228, 248)), ol=False, rim=0.2)
    fg = Canvas(1000, 440)
    for x, h_, w_, tl, col in ((60, 46, 14, -6, (150, 200, 240)), (300, 30, 10, 4, (126, 180, 232)),
                              (640, 52, 16, -4, (150, 200, 240)), (940, 34, 12, 5, (126, 180, 232))):
        crystal(fg, x, 442, h_, w_, tl, col, int(x))
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def ice_spire():
    c = Canvas(150, 200)
    shadow_ell(c, 75, 194, 62, 5)
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for r_, a in ((70, 20), (52, 30), (36, 42)):
        ld.polygon(c.P(ell_pts(75, 110, r_, r_ * 1.3)), fill=(150, 220, 255, a))
    c.comp(lay)
    for (x, h, w, tl, col) in ((30, 80, 18, -8, (126, 182, 232)), (120, 96, 20, 8, (140, 196, 240)),
                               (52, 130, 24, -5, (150, 206, 244)), (98, 150, 26, 4, (120, 176, 228)),
                               (75, 190, 32, 0, (170, 224, 252)), (14, 46, 12, -10, (150, 206, 244)),
                               (136, 54, 12, 10, (126, 182, 232))):
        crystal(c, x, 192, h, w, tl, col, int(x))
    return c.result()


def bg_ash():
    sky = Canvas(1000, 440)
    vgrad_dither(sky, 0, 340, (40, 32, 38), (156, 100, 84))
    fill_rect(sky, 340, 440, (156, 100, 84))
    pix = sky.im.load()
    for y in range(0, int(300 * sky.k)):
        for x in range(sky.w):
            n = fbm(x / sky.k * 0.009, y / sky.k * 0.02, 31)
            if n > 0.48:
                a = (n - 0.48) * 1.7
                r, g_, b, _ = pix[x, y]
                pix[x, y] = (int(r * (1 - a * 0.5)), int(g_ * (1 - a * 0.5)), int(b * (1 - a * 0.45)), 255)
    glow(sky, 300, 270, (110, 88, 70), (240, 100, 60), (20, 34, 56))
    ep(sky, 300, 270, 40, 40, make_ramp((236, 96, 56)), ol=False, rim=0, tone=0.4)
    mid = Canvas(1000, 440)
    hills(mid, 372, [(26, 0.008), (12, 0.02)], make_ramp((86, 74, 78)), 4, 0.3, 60)
    tr = make_ramp((38, 32, 36))
    for x in range(40, 1000, 130):
        r_ = random.Random(x)
        mid.line([(x, 392), (x + r_.uniform(-3, 3), 330)], tr[1], 3)
        for k in range(4):
            mid.line([(x, 340 + k * 8), (x + r_.uniform(-26, 26), 322 + k * 4)], tr[1], 2)
    g = Canvas(1000, 440)
    ramp = make_ramp((88, 82, 84))
    lava = [(120, 28, 14, 255), (190, 56, 20, 255), (244, 120, 36, 255), (255, 190, 80, 255), (255, 236, 160, 255)]

    def gfn(x, y, px, py):
        t = 0.5 - 0.2 * (y - 380) / 60 + (fbm(x * 0.05, y * 0.14, 3) - 0.5) * 0.5
        cr = abs(fbm(x * 0.03 + 5, y * 0.1, 13) - 0.5)
        if cr < 0.014:
            return pick(lava, 0.4, px, py)
        return pick(ramp, t, px, py)
    g.paint([(0, 380), (1000, 380), (1000, 440), (0, 440)], gfn, None)
    g.line([(0, 380), (1000, 380)], ramp[4])
    rnd = random.Random(8)
    for _ in range(14):
        x, y = rnd.uniform(0, 1000), rnd.uniform(390, 436)
        ep(g, x, y, rnd.uniform(4, 10), rnd.uniform(2, 4), make_ramp((104, 98, 100)), fur=0.3, seed=int(x), rim=0.25)
    fg = Canvas(1000, 440)
    for x in (70, 500, 900):
        fg.line([(x, 440), (x + 6, 410), (x - 4, 392)], tr[1], 3)
        fg.line([(x + 6, 410), (x + 18, 400)], tr[1], 2)
    return dict(sky=sky.result(), mid=mid.result(), ground=g.result(), fg=fg.result())


def obelisk():
    c = Canvas(120, 200)
    shadow_ell(c, 60, 194, 50, 5)
    ob = make_ramp((44, 38, 52))
    pp(c, [(10, 196), (14, 180), (106, 180), (110, 196)], make_ramp((70, 64, 70)), fur=0.3, seed=1)
    pp(c, [(24, 180), (28, 168), (92, 168), (96, 180)], make_ramp((70, 64, 70)), fur=0.3, seed=2)
    pts = [(36, 168), (44, 40), (60, 10), (76, 40), (84, 168)]
    lava = [(120, 28, 14, 255), (190, 56, 20, 255), (244, 120, 36, 255), (255, 190, 80, 255), (255, 236, 160, 255)]

    def fn(x, y, px, py):
        u = (x - 60) / 26
        t = 0.2 + 0.8 * max(0.0, u * LIGHT[0] * 1.2 + math.sqrt(max(0.0, 1 - min(1.0, u * u))) * 1.0 * LIGHT[2]) \
            + (fbm(x * 0.2, y * 0.1, 3) - 0.5) * 0.3
        if abs(u) < 0.5 and y > 60 and int((y - 60) / 18) % 2 == 0 and 4 < (y - 60) % 18 < 12 and abs(((x - 60) * 0.5) % 6 - 3) < 1.4:
            return pick(lava, 0.6, px, py)
        return pick(ob, t, px, py)
    c.paint(pts, fn, OLC(ob, 0.5))
    lay = c.layer()
    ld = ImageDraw.Draw(lay)
    for r_, a in ((44, 20), (30, 32), (18, 46)):
        ld.polygon(c.P(ell_pts(60, 90, r_ * 0.6, r_)), fill=(255, 90, 40, a))
    c.comp(lay)
    for k in range(5):
        c.put(56 + (k % 3) * 4, 84 + k * 10, (255, 200, 120, 255))
    return c.result()


def hive_cannon():
    """Trompa de llautó que surt del cim del rusc: bufa núvols de pol·len (dibuix pixel a pixel)."""
    im = Image.new("RGBA", (40, 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    OUT = (36, 22, 8, 255)
    # bufador de cuir (a l'esquerra) i bossa de pol·len
    d.ellipse((1, 17, 11, 28), fill=(128, 84, 44, 255), outline=OUT)
    d.arc((3, 19, 9, 26), 200, 340, fill=(190, 140, 84, 255))
    d.line([(10, 22), (14, 22)], fill=OUT)
    # tub i campana (eix de la base A cap a la boca B)
    ax, ay, bx, by = 13.0, 24.0, 31.0, 7.0
    ln = math.hypot(bx - ax, by - ay)
    dx, dy = (bx - ax) / ln, (by - ay) / ln
    nx, ny = -dy, dx
    left, right = [], []
    for k in range(0, 21):
        t = k / 20.0
        r = 2.4 + 5.6 * (max(0.0, t - 0.35) / 0.65) ** 2.0
        px, py = ax + (bx - ax) * t, ay + (by - ay) * t
        left.append((px + nx * r, py + ny * r))
        right.append((px - nx * r, py - ny * r))
    d.polygon(left + right[::-1], fill=(214, 160, 62, 255), outline=OUT)
    hl = [(ax + (bx - ax) * (k / 20.0) + nx * (0.5 + 4.8 * (max(0.0, k / 20.0 - 0.35) / 0.65) ** 2.0 * 0.6),
           ay + (by - ay) * (k / 20.0) + ny * (0.5 + 4.8 * (max(0.0, k / 20.0 - 0.35) / 0.65) ** 2.0 * 0.6)) for k in range(2, 19)]
    d.line(hl, fill=(255, 226, 140, 255))
    # anells d'or
    for t in (0.34, 0.62):
        r = 2.4 + 5.6 * (max(0.0, t - 0.35) / 0.65) ** 2.0 + 0.9
        px, py = ax + (bx - ax) * t, ay + (by - ay) * t
        d.line([(px + nx * r, py + ny * r), (px - nx * r, py - ny * r)], fill=(250, 214, 110, 255), width=2)
    # boca amb la brillantor del pol·len
    r = 8.0
    d.ellipse((bx - 3.4, by - r, bx + 3.4, by + r), fill=(60, 30, 10, 255), outline=(250, 214, 110, 255))
    d.ellipse((bx - 1.6, by - 4.5, bx + 2.0, by + 4.5), fill=(255, 214, 80, 255))
    # coll i base sobre el rusc
    d.rectangle((9, 24, 17, 29), fill=(150, 96, 44, 255), outline=OUT)
    d.line([(10, 26), (16, 26)], fill=(200, 150, 80, 255))
    d.point((11, 28), fill=(250, 214, 110, 255))
    d.point((15, 28), fill=(250, 214, 110, 255))
    return im


def fx_muzzle_frames(n=5):
    out = []
    rnd = random.Random(4)
    puffs = [(rnd.uniform(0, 6.28), rnd.uniform(0.5, 1.0)) for _ in range(9)]
    for i in range(n):
        im, d = _fx(60, 60)
        t = (i + 1) / n
        cx = cy = 30
        if i < 3:
            for k in range(8):
                ang = k * math.pi / 4 + 0.3
                ll = (10 + t * 16) * (1.0 if k % 2 == 0 else 0.6)
                d.polygon([(cx + math.cos(ang - 0.25) * 3, cy + math.sin(ang - 0.25) * 3), (cx + math.cos(ang) * ll, cy + math.sin(ang) * ll),
                           (cx + math.cos(ang + 0.25) * 3, cy + math.sin(ang + 0.25) * 3)], fill=(255, 220, 110, 255 - i * 50))
            d.ellipse((cx - 8 + i * 2, cy - 8 + i * 2, cx + 8 - i * 2, cy + 8 - i * 2), fill=(255, 250, 220, 255))
        for ang, f in puffs:
            rr = 6 + t * 22 * f
            x, y = cx + math.cos(ang) * rr, cy + math.sin(ang) * rr
            a = int(200 * (1 - t * 0.8))
            d.ellipse((x - 5 * (0.6 + t), y - 5 * (0.6 + t), x + 5 * (0.6 + t), y + 5 * (0.6 + t)), fill=(220, 214, 200, a))
        out.append(im)
    return out
# ----------------------------------------------------------------- CONJUNT
def build_sprites(progress=None):
    """Genera TOTS els sprites. Retorna {nom: imatge PIL o [fotogrames]}."""
    out = {}
    total = len(BEES) + len(ENEMY_FUNCS) + 19 + 3 + 17 + 3 + 10
    n = [0]

    def tick():
        n[0] += 1
        if progress:
            progress(min(1.0, n[0] / total))
    global F, PIX, DITH, RAMP_N
    F, PIX, DITH, RAMP_N = 1.0, 1, 0.2, 9          # abelles i enemics: píxel fi i ombres suaus
    try:
        for k, sp in BEES.items():
            out["ally_" + k] = [up(f) for f in crop_union([pad(hard(bee(sp, f))) for f in range(NF + 2)])]
            tick()
        for k, fn in ENEMY_FUNCS.items():
            fr = [pad(hard(fn(f)), 12) for f in range(NF)]
            if k in ("wasp", "hornet"):
                fr += [pad(hard(fn(NF)), 12), pad(hard(fn(NF + 1)), 12)]
            else:
                fr += [lean(fr[0], -6), lean(fr[0], 10)]
            out["enemy_" + k] = [up(f) for f in crop_union(fr)]
            tick()
    finally:
        F, PIX, DITH, RAMP_N = 0.5, 2, 0.55, 5
    for name, fn in (("base_hive", hive), ("base_anthill", anthill), ("base_stump", stump), ("base_nest", nest),
                     ("base_swamp", swamp_base), ("base_crystal", crystal_base), ("base_volcano", volcano_base),
                     ("base_tower", tower_base), ("base_sandcastle", sandcastle), ("base_igloo", igloo),
                     ("base_ruins", ruins_temple), ("base_cursed", cursed_tree), ("base_scarecrow", scarecrow),
                     ("base_tiki", tiki), ("base_mine", mine_entrance), ("base_crypt", crypt),
                     ("base_icespire", ice_spire), ("base_obelisk", obelisk), ("hive_cannon", hive_cannon)):
        out[name] = up(hard(fn()))
        tick()
    for ph in range(3):
        out["base_queen_%d" % ph] = [up(hard(queen_lair(ph, f))) for f in (0, 2, 3)]
        tick()
    for nm, fn in (("meadow", bg_meadow), ("forest", bg_forest), ("desert", bg_desert), ("swamp", bg_swamp),
                   ("cave", bg_cave), ("volcano", bg_volcano), ("storm", bg_storm), ("lair", bg_lair),
                   ("beach", bg_beach), ("snow", bg_snow), ("ruins", bg_ruins), ("farm", bg_farm), ("jungle", bg_jungle),
                   ("mine", bg_mine), ("graveyard", bg_graveyard), ("glacier", bg_glacier), ("ash", bg_ash)):
        for layer, im in fn().items():
            out["bg_%s_%s" % (nm, layer)] = up(im)
        tick()
    for i in range(3):
        out["cloud_%d" % i] = up(hard(cloud_sprite(i + 1)))
        tick()
    out["ui_panel"] = up(ui_panel())
    for name, fn in (("icon_honey", icon_honey), ("icon_cannon", icon_cannon), ("proj_mud", proj_mud),
                     ("proj_orb", proj_orb), ("proj_pollen", proj_pollen), ("proj_web", proj_web),
                     ("proj_tongue", proj_tongue), ("proj_dust", proj_dust)):
        out[name] = up(hard(fn()))
    tick()
    out.update(build_fx())
    out.update(build_fx2())
    out.update(build_fx3())
    tick()
    if progress:
        progress(1.0)
    return out


# >>> ART_END
def _src_hash(start_tag, end_tag):
    """Hash del tros de codi entre dues etiquetes."""
    if WEB:
        return "web"
    try:
        with open(os.path.abspath(__file__), "r", encoding="utf-8") as f:
            txt = f.read()
        a = txt.index("# >>> " + start_tag)
        b_ = txt.index("# >>> " + end_tag)
        return hashlib.md5(txt[a:b_].encode("utf-8")).hexdigest()
    except Exception:
        return "x"


def _pack(v):
    if isinstance(v, list):
        return [_pack(x) for x in v]
    return (v.mode, v.size, zlib.compress(v.tobytes(), 4))


def _unpack(v):
    if isinstance(v, list):
        return [_unpack(x) for x in v]
    return Image.frombytes(v[0], v[1], zlib.decompress(v[2]))


def get_sprites(use_cache=True, progress=None):
    path = os.path.join(data_dir(), "sprites_cache.bin")
    h = _src_hash("ART_START", "ART_END")
    if use_cache:
        try:
            with open(path, "rb") as f:
                data = pickle.load(f)
            if data.get("hash") == h:
                return {k: _unpack(v) for k, v in data["imgs"].items()}
        except Exception:
            pass
    out = build_sprites(progress)
    if use_cache:
        try:
            with open(path, "wb") as f:
                pickle.dump(dict(hash=h, imgs={k: _pack(v) for k, v in out.items()}), f, protocol=4)
        except Exception:
            pass
    return out


def export_sprites(folder="sprites"):
    os.makedirs(folder, exist_ok=True)
    for name, v in build_sprites().items():
        if isinstance(v, list):
            for i, im in enumerate(v):
                im.save(os.path.join(folder, "%s_%d.png" % (name, i)))
        else:
            v.save(os.path.join(folder, name + ".png"))
    print("Sprites guardats a", os.path.abspath(folder))


# =====================================================================
#  SO I MÚSICA (sintetitzats per codi; es guarden en memòria cau)
# =====================================================================
# >>> AUDIO_START
SR = 16000
_TN = 2048
_SIN = [math.sin(2 * math.pi * i / _TN) for i in range(_TN)]


def _osc(kind, ph):
    x = ph - int(ph)
    if kind == "sine":
        return _SIN[int(x * _TN) & (_TN - 1)]
    if kind == "tri":
        return 4 * x - 1 if x < 0.5 else 3 - 4 * x
    if kind == "saw":
        return 2 * x - 1
    return 1.0 if x < 0.5 else -1.0


def tone(freq, dur, kind="sine", vol=0.5, f_end=None, attack=0.004, release=0.05, vib=0.0, noise=0.0, rnd=None):
    n = int(SR * dur)
    out = [0.0] * n
    ph = 0.0
    nr = rnd or random.Random(3)
    inv = 1.0 / SR
    for i in range(n):
        t = i * inv
        f = freq if f_end is None else freq + (f_end - freq) * (i / n)
        if vib:
            f *= 1 + vib * _SIN[int(t * 7 * _TN) & (_TN - 1)]
        ph += f * inv
        v = _osc(kind, ph)
        if noise:
            v = v * (1 - noise) + nr.uniform(-1, 1) * noise
        e = t / attack if t < attack else 1.0
        rem = dur - t
        if rem < release:
            e *= rem / release
        out[i] = v * e * vol
    return out


def cat(*parts):
    out = []
    for p in parts:
        out.extend(p)
    return out


def mix(*parts):
    n = max(len(p) for p in parts)
    out = [0.0] * n
    for p in parts:
        for i, v in enumerate(p):
            out[i] += v
    return out


def pcm(samples, gain=1.0):
    return array.array("h", [int(max(-1.0, min(1.0, s * gain)) * 30000) for s in samples]).tobytes()


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12.0)


def build_sfx():
    r = random.Random(5)
    s = {}
    s["click"] = tone(900, 0.04, "square", 0.22, 600, 0.001, 0.03)
    s["buzz"] = tone(150, 0.15, "saw", 0.2, 290, 0.01, 0.07, vib=0.06)
    s["hit"] = mix(tone(170, 0.06, "sine", 0.4, 90, 0.001, 0.04),
                   tone(1, 0.05, "sine", 0.22, None, 0.001, 0.04, noise=1.0, rnd=r))
    s["sting"] = tone(950, 0.09, "square", 0.16, 420, 0.001, 0.05)
    s["die"] = tone(420, 0.28, "tri", 0.34, 70, 0.002, 0.12)
    s["boom"] = mix(tone(70, 0.4, "sine", 0.5, 40, 0.002, 0.25),
                    tone(1, 0.4, "sine", 0.32, None, 0.001, 0.3, noise=1.0, rnd=r))
    s["cannon"] = mix(tone(240, 0.5, "saw", 0.26, 60, 0.002, 0.3),
                      tone(1, 0.18, "sine", 0.3, None, 0.001, 0.15, noise=1.0, rnd=r))
    s["coin"] = cat(tone(880, 0.07, "square", 0.18, None, 0.002, 0.03), tone(1320, 0.12, "square", 0.18, None, 0.002, 0.08))
    s["shake"] = tone(300, 0.05, "tri", 0.3, 200, 0.001, 0.03)
    s["reveal"] = cat(*[tone(hz(m), 0.1, "tri", 0.3, None, 0.004, 0.06) for m in (72, 76, 79, 84)])
    s["win"] = cat(*[tone(hz(m), 0.16, "tri", 0.3, None, 0.004, 0.08) for m in (72, 76, 79, 84, 79, 84)])
    s["lose"] = cat(*[tone(hz(m), 0.22, "tri", 0.3, None, 0.004, 0.1) for m in (69, 65, 62, 57)])
    s["warn"] = cat(tone(1000, 0.08, "square", 0.14, None, 0.002, 0.03), tone(0.001, 0.06, "sine", 0.0),
                    tone(1000, 0.08, "square", 0.14, None, 0.002, 0.03))
    s["roar"] = mix(tone(95, 0.7, "saw", 0.3, 55, 0.02, 0.3, vib=0.1),
                    tone(1, 0.5, "sine", 0.2, None, 0.01, 0.3, noise=1.0, rnd=r))
    s["heal"] = cat(tone(hz(76), 0.07, "sine", 0.2), tone(hz(83), 0.1, "sine", 0.2, None, 0.004, 0.07))
    s["slash"] = mix(tone(1, 0.09, "sine", 0.22, None, 0.001, 0.07, noise=1.0, rnd=r), tone(1500, 0.09, "saw", 0.1, 700, 0.001, 0.06))
    s["thud"] = mix(tone(95, 0.16, "sine", 0.5, 45, 0.001, 0.1), tone(1, 0.08, "sine", 0.2, None, 0.001, 0.06, noise=1.0, rnd=r))
    s["zap"] = cat(tone(1700, 0.06, "square", 0.14, 700, 0.001, 0.03), tone(900, 0.07, "square", 0.12, 1500, 0.001, 0.04))
    s["magic"] = cat(tone(hz(84), 0.05, "sine", 0.2), tone(hz(88), 0.05, "sine", 0.2), tone(hz(91), 0.08, "sine", 0.2, None, 0.004, 0.06))
    s["crit"] = mix(tone(320, 0.12, "saw", 0.3, 110, 0.001, 0.08), tone(1900, 0.07, "square", 0.14, 900, 0.001, 0.04))
    s["ability"] = cat(tone(420, 0.14, "saw", 0.22, 950, 0.004, 0.05), tone(950, 0.22, "tri", 0.26, None, 0.004, 0.12))
    s["levelup"] = cat(*[tone(hz(m), 0.09, "tri", 0.3, None, 0.003, 0.05) for m in (72, 76, 79, 84, 88)])
    s["confetti"] = tone(1, 0.35, "sine", 0.18, None, 0.01, 0.3, noise=1.0, rnd=r)
    return {k: pcm(v) for k, v in s.items()}


_MUSIC = {
    "calm": dict(bpm=92, root=60, prog=[(0, 4, 7), (5, 9, 12), (9, 12, 16), (7, 11, 14)], scale=[0, 2, 4, 7, 9], seed=1,
                 pad="sine", bass="tri", mel="sine", density=0.45),
    "tense": dict(bpm=76, root=57, prog=[(0, 3, 7), (8, 12, 15), (5, 8, 12), (7, 11, 14)], scale=[0, 3, 5, 7, 10], seed=2,
                  pad="tri", bass="sine", mel="tri", density=0.35),
    "epic": dict(bpm=118, root=62, prog=[(0, 3, 7), (-4, 0, 3), (-2, 2, 5), (-5, -1, 2)], scale=[0, 3, 5, 7, 10], seed=3,
                 pad="saw", bass="tri", mel="tri", density=0.55),
    "boss": dict(bpm=132, root=64, prog=[(0, 3, 7), (-4, 0, 3), (-7, -3, 0), (-5, -2, 2)], scale=[0, 3, 5, 6, 7, 10], seed=4,
                 pad="saw", bass="square", mel="saw", density=0.6),
}


def _note(buf, start, dur, freq, kind, vol, attack, release):
    i0 = int(start * SR)
    n = int(dur * SR)
    inv = 1.0 / SR
    ph = 0.0
    last = len(buf)
    for i in range(n):
        j = i0 + i
        if j >= last:
            break
        t = i * inv
        ph += freq * inv
        e = t / attack if t < attack else 1.0
        rem = dur - t
        if rem < release:
            e *= rem / release
        buf[j] += _osc(kind, ph) * e * vol


def make_music(kind):
    c = _MUSIC[kind]
    beat = 60.0 / c["bpm"]
    bars = 4
    total = bars * 4 * beat
    buf = [0.0] * int(total * SR)
    rnd = random.Random(c["seed"])
    for bar in range(bars):
        t0 = bar * 4 * beat
        chord = c["prog"][bar]
        for off in chord:
            _note(buf, t0, 4 * beat, hz(c["root"] + off), c["pad"], 0.05, 0.35, 0.45)
        for b in range(4):
            _note(buf, t0 + b * beat, beat * 0.85, hz(c["root"] + chord[0] - 24), c["bass"], 0.16, 0.01, 0.08)
        if kind in ("epic", "boss"):
            for b in range(8):
                _note(buf, t0 + b * beat * 0.5 + beat * 0.25, beat * 0.18, hz(c["root"] + chord[0] - 24), "square", 0.05,
                      0.005, 0.05)
        sc = c["scale"]
        for step in range(8):
            if rnd.random() < c["density"]:
                d = rnd.randrange(len(sc) * 2)
                m = c["root"] + 12 + sc[d % len(sc)] + 12 * (d // len(sc))
                _note(buf, t0 + step * beat * 0.5, beat * 0.42, hz(m), c["mel"], 0.07, 0.01, 0.12)
    peak = max(1e-6, max(abs(v) for v in buf))
    g = 0.55 / peak
    return pcm([v * g for v in buf])


def build_audio(progress=None):
    out = {"sfx": build_sfx(), "music": {}}
    for i, k in enumerate(_MUSIC):
        out["music"][k] = make_music(k)
        if progress:
            progress((i + 1) / len(_MUSIC))
    return out
# >>> AUDIO_END


def get_audio(progress=None):
    path = os.path.join(data_dir(), "sounds_cache.bin")
    h = _src_hash("AUDIO_START", "AUDIO_END")
    try:
        with open(path, "rb") as f:
            data = pickle.load(f)
        if data.get("hash") == h:
            return {"sfx": {k: zlib.decompress(v) for k, v in data["sfx"].items()},
                    "music": {k: zlib.decompress(v) for k, v in data["music"].items()}}
    except Exception:
        pass
    out = build_audio(progress)
    try:
        with open(path, "wb") as f:
            pickle.dump(dict(hash=h, sfx={k: zlib.compress(v, 3) for k, v in out["sfx"].items()},
                             music={k: zlib.compress(v, 3) for k, v in out["music"].items()}), f, protocol=4)
    except Exception:
        pass
    return out


# =====================================================================
#  JOC
# =====================================================================
import datetime
import json
import shutil

W, H = 1000, 540
STEP = 1.0 / 60.0                      # pas de lògica fix (60 Hz): partida determinista
screen = None
clock = None
FONT = FONT_S = FONT_M = FONT_B = None
IMG = {}
PF = "consolas,couriernew,dejavusansmono,monospace"

# paleta apagada
C_TXT = (232, 222, 196)
C_DARK = (38, 26, 14)
C_GOLD = (214, 190, 120)
C_BORDER = (20, 15, 12)
C_BTN = (190, 150, 70)
C_BTN_HOVER = (214, 176, 98)
C_BTN_OFF = (84, 74, 64)
C_RED = (176, 70, 60)
C_GREEN = (96, 160, 90)
C_WOOD = (122, 88, 48)
C_WOOD_D = (66, 44, 22)
C_WOOD_L = (170, 130, 74)
C_BG = (50, 58, 50)
C_HEX = (62, 72, 60)
C_CARD = (44, 38, 34)
RAR_COL = {"common": (150, 142, 124), "rare": (96, 136, 176), "legend": (222, 184, 74)}
RAR_NAME = {"common": "Comuna", "rare": "Rara", "legend": "Llegendària"}

GROUND = 392
UI_Y = 440
CAT_BASE_X = 78
ENEMY_BASE_X = W - 90
MAX_LV = 15
DECK_SIZE = 5
DECK_MAX = 6
WALLET_MAX = 8
MAX_CANNON = 8
CAT_BASE_HP = 3000
SAVE_VERSION = 11


# ------------------------------------------------------------ DADES
def B(key, name, rarity, cost, cd, hp, atk, rng, speed, atkcd, kb, r, hover, desc, style="sting", proj=None):
    cost = int(round(cost * 1.35 / 5.0) * 5)          # més cares...
    cd = round(cd * 1.35, 1)                          # ...i es carreguen més lentes...
    hp, atk = int(hp * 1.15), max(1, int(round(atk * 1.15)))   # ...però una mica més fortes
    return dict(key=key, name=name, rarity=rarity, cost=cost, cd=cd, hp=hp, atk=atk, range=rng, speed=speed,
                atkcd=atkcd, kb=kb, r=r, hover=hover, desc=desc, style=style, proj=proj,
                ranged=style in RANGED_STYLES)


RANGED_STYLES = ("mud", "pollen", "web", "orb", "tongue", "dust", "webvenom")
STYLE_NAME = {
    "sting": "Picada", "slice": "Tall ràpid", "slam": "Cop de cos (àrea)", "crit": "Mossegada crítica (25%)",
    "dash": "Embestida", "mud": "Bola de fang (alenteix)", "sparkle": "Espurnes (pot atordir)",
    "poison": "Verí (dany continu)", "pollen": "Pol·len (àrea)", "flurry": "Ràfega de 3 picades",
    "royal": "Pols reial (àrea + cura)", "bite": "Mossegada", "web": "Teranyina (alenteix)",
    "ram": "Embestida (empeny)", "venom": "Verí (dany continu)", "claw": "Doble garrotada",
    "stomp": "Trepitjada (àrea)", "orb": "Esfera d'energia (alenteix)",
    "tongue": "Llengua (t'estira)", "crunch": "Mossegada múltiple", "burn": "Foc (dany continu)",
    "dive": "Picat en vertical", "slime": "Bava (alenteix)", "drain": "Xucla vida",
    "joust": "Embestida (llança enrere)", "frost": "Gel (alenteix en àrea)", "burrow": "Excavació (àrea + atordeix)",
    "crush": "Aixafament (llança enrere)", "bash": "Escomesa (empeny)", "dust": "Pols d'escates (alenteix)",
    "webvenom": "Teranyina verinosa",
}

BEE_UNITS = [
    B("honey", "Abella de Mel", "common", 50, 2.0, 100, 8, 18, 60, 0.9, 3, 20, 26, "La clàssica. Barata i fiable.", "sting"),
    B("leafcutter", "Talladora de Fulles", "common", 30, 1.2, 50, 5, 16, 95, 0.7, 2, 15, 24,
      "Molt barata: ideal per fer eixam.", "slice"),
    B("bumble", "Borinot", "common", 100, 4.0, 550, 5, 20, 45, 1.1, 4, 24, 24,
      "Gran i resistent. Colpeja amb tot el cos.", "slam"),
    B("stingless", "Abella sense agulló", "common", 40, 1.5, 80, 6, 16, 80, 0.8, 2, 14, 24,
      "Petita i ràpida de recuperar.", "sting"),
    B("guard", "Abella guardiana", "common", 120, 5.0, 720, 6, 20, 42, 1.1, 5, 24, 24,
      "Escut viu: empeny els enemics.", "bash"),
    B("carpenter", "Abella Fustera", "rare", 150, 5.0, 170, 38, 22, 70, 1.2, 3, 24, 26,
      "Mossegada forta, de vegades crítica.", "crit"),
    B("sweat", "Abella de la Suor", "rare", 250, 8.0, 200, 40, 22, 150, 1.0, 2, 16, 28,
      "Velocíssima: s'abalança sobre l'enemic.", "dash"),
    B("mason", "Abella Paletera", "rare", 400, 10.0, 260, 55, 210, 55, 2.0, 2, 20, 26,
      "Llança fang des de lluny i alenteix.", "mud", "proj_mud"),
    B("orchid", "Abella de les orquídies", "rare", 200, 6.0, 180, 34, 20, 130, 0.9, 3, 18, 28,
      "Irisada: les seves espurnes atordeixen.", "sparkle"),
    B("cuckoo", "Abella cuc", "rare", 180, 6.0, 420, 18, 20, 60, 0.9, 4, 22, 26,
      "Dura de pelar, la seva picada enverina.", "poison"),
    B("bluebanded", "Abella zumbadora", "rare", 220, 7.0, 190, 26, 150, 60, 1.2, 2, 18, 26,
      "Zumbat de pol·len que fa mal en àrea.", "pollen", "proj_pollen"),
    B("miner", "Abella minera", "rare", 190, 6.0, 240, 30, 20, 65, 1.1, 3, 19, 22,
      "Excava: dany en àrea i atordeix.", "burrow"),
    B("woolcarder", "Abella cardadora", "rare", 210, 6.0, 220, 36, 22, 115, 1.0, 3, 20, 26,
      "Embestida territorial: llança enrere.", "joust"),
    B("arctic", "Borinot àrtic", "rare", 260, 8.0, 330, 22, 24, 55, 1.1, 4, 24, 24,
      "Gel que alenteix tots els propers.", "frost"),
    B("nurse", "Abella nodrissa", "rare", 220, 8.0, 260, 4, 18, 55, 1.2, 2, 18, 26,
      "Cura les abelles que té a prop.", "sting"),
    B("killer", "Abella africanitzada", "legend", 300, 9.0, 140, 70, 20, 100, 0.7, 2, 20, 26,
      "Fràgil, però llança picades a ràfega.", "flurry"),
    B("giant", "Abella gegant de Wallace", "legend", 700, 26.0, 2400, 95, 30, 48, 1.4, 5, 36, 28,
      "Aixafa tot el que troba.", "crush"),
    B("queen", "Abella Reina", "legend", 600, 22.0, 1600, 80, 28, 50, 1.1, 5, 30, 28,
      "El seu pols reial fereix i cura el rusc.", "royal"),
]
BEE_BY_KEY = {b["key"]: b for b in BEE_UNITS}
ROLE_OF = {"honey": "Atacant", "leafcutter": "Atacant", "bumble": "Tanc", "stingless": "Atacant", "guard": "Tanc",
           "carpenter": "Atacant", "sweat": "Atacant", "mason": "Tirador", "orchid": "Control", "cuckoo": "Atacant",
           "bluebanded": "Tirador", "miner": "Control", "woolcarder": "Atacant", "arctic": "Control", "nurse": "Suport",
           "killer": "Atacant", "giant": "Tanc", "queen": "Suport"}
ROLE_INFO = {"Tanc": "Els enemics l'ataquen primer", "Atacant": "Molt dany a prop",
             "Tirador": "Ataca de lluny i toca els voladors", "Control": "Alenteix o atordeix",
             "Suport": "Cura les aliades"}
AIR_KEYS = {"sweat", "orchid", "killer"}          # a més dels tiradors: fan dany ple als voladors
for _b in BEE_UNITS:
    _b["role"] = ROLE_OF[_b["key"]]
    _b["tank"] = _b["role"] == "Tanc"
    _b["air"] = _b["ranged"] or _b["key"] in AIR_KEYS

UPG_BASE = {"common": 80, "rare": 160, "legend": 320}

ENEMIES = {
    "ant": dict(name="Formiga", hp=70, atk=5, range=18, speed=42, atkcd=1.0, kb=1, r=20,
                reward=12, hover=0, ranged=False, style="bite"),
    "spider": dict(name="Aranya", hp=45, atk=4, range=85, speed=75, atkcd=1.4, kb=1, r=16,
                   reward=10, hover=0, ranged=True, style="web", proj="proj_web"),
    "beetle": dict(name="Escarabat", hp=420, atk=16, range=20, speed=55, atkcd=1.0, kb=2, r=22,
                   reward=35, hover=0, ranged=False, style="ram"),
    "wasp": dict(name="Vespa", hp=300, atk=20, range=20, speed=95, atkcd=0.9, kb=2, r=18,
                 reward=30, hover=22, ranged=False, style="venom"),
    "mantis": dict(name="Mantis", hp=700, atk=28, range=60, speed=50, atkcd=1.3, kb=2, r=22,
                   reward=60, hover=0, ranged=False, style="claw"),
    "hornet": dict(name="Vespa Asiàtica", hp=1600, atk=40, range=24, speed=30, atkcd=1.4, kb=3, r=34,
                   reward=120, hover=30, ranged=False, style="stomp"),
    "alien": dict(name="Alien", hp=700, atk=28, range=100, speed=50, atkcd=1.5, kb=2, r=22,
                  reward=60, hover=34, ranged=True, style="orb", proj="proj_orb"),
    "frog": dict(name="Granota", hp=260, atk=12, range=115, speed=48, atkcd=1.7, kb=2, r=24,
                 reward=28, hover=0, ranged=True, style="tongue", proj="proj_tongue"),
    "dragonfly": dict(name="Libèl·lula", hp=130, atk=13, range=20, speed=125, atkcd=0.7, kb=1, r=18,
                      reward=18, hover=40, ranged=False, style="sting"),
    "scorpion": dict(name="Escorpí", hp=950, atk=26, range=22, speed=40, atkcd=1.3, kb=3, r=26,
                     reward=55, hover=0, ranged=False, style="venom"),
    "centipede": dict(name="Centpeus", hp=1300, atk=16, range=24, speed=36, atkcd=0.9, kb=3, r=32,
                      reward=70, hover=0, ranged=False, style="crunch"),
    "fireant": dict(name="Formiga de foc", hp=120, atk=10, range=18, speed=62, atkcd=0.8, kb=1, r=20,
                    reward=16, hover=0, ranged=False, style="burn"),
    "scorpion_king": dict(name="Escorpí Rei", hp=5600, atk=52, range=30, speed=34, atkcd=1.5, kb=4, r=46,
                          reward=420, hover=0, ranged=False, style="venom"),
    "swallow": dict(name="Oreneta", hp=1900, atk=58, range=30, speed=115, atkcd=1.8, kb=3, r=32,
                    reward=220, hover=60, ranged=False, style="dive"),
    "hornet_guard": dict(name="Guàrdia Reial", hp=2200, atk=56, range=26, speed=40, atkcd=1.2, kb=4, r=38,
                         reward=160, hover=30, ranged=False, style="stomp", sprite="hornet"),
    "snail": dict(name="Cargol", hp=800, atk=7, range=18, speed=22, atkcd=1.3, kb=4, r=26,
                  reward=30, hover=0, ranged=False, style="slime"),
    "termite": dict(name="Tèrmit", hp=55, atk=5, range=16, speed=66, atkcd=0.7, kb=1, r=16,
                    reward=8, hover=0, ranged=False, style="bite"),
    "locust": dict(name="Llagosta", hp=160, atk=14, range=20, speed=105, atkcd=0.9, kb=2, r=20,
                   reward=20, hover=0, ranged=False, style="ram"),
    "crab": dict(name="Cranc", hp=430, atk=18, range=20, speed=46, atkcd=1.1, kb=3, r=24,
                 reward=32, hover=0, ranged=False, style="crunch"),
    "mosquito": dict(name="Mosquit", hp=80, atk=7, range=18, speed=100, atkcd=0.8, kb=1, r=16,
                     reward=14, hover=44, ranged=False, style="drain"),
    "crab_king": dict(name="Cranc Rei", hp=5400, atk=50, range=28, speed=32, atkcd=1.5, kb=4, r=44,
                      reward=400, hover=0, ranged=False, style="stomp"),
    "bat": dict(name="Rata penada", hp=230, atk=22, range=20, speed=105, atkcd=1.0, kb=2, r=18,
                reward=26, hover=46, ranged=False, style="dive"),
    "widow": dict(name="Vídua negra", hp=390, atk=20, range=90, speed=60, atkcd=1.3, kb=2, r=20,
                  reward=40, hover=0, ranged=True, style="webvenom", proj="proj_web"),
    "moth": dict(name="Arna", hp=270, atk=14, range=105, speed=62, atkcd=1.6, kb=2, r=20,
                 reward=32, hover=44, ranged=True, style="dust", proj="proj_dust"),
    "frostbeetle": dict(name="Escarabat de gel", hp=920, atk=24, range=20, speed=48, atkcd=1.1, kb=3, r=26,
                        reward=50, hover=0, ranged=False, style="frost"),
    "stag": dict(name="Cérvol volant", hp=1750, atk=46, range=24, speed=42, atkcd=1.3, kb=4, r=30,
                 reward=90, hover=0, ranged=False, style="joust"),
    "tarantula": dict(name="Taràntula", hp=5400, atk=44, range=110, speed=30, atkcd=1.6, kb=5, r=46,
                      reward=380, hover=0, ranged=True, style="webvenom", proj="proj_web"),
    "mantis_king": dict(name="Mantis Rei", hp=6200, atk=60, range=70, speed=36, atkcd=1.3, kb=5, r=46,
                        reward=430, hover=0, ranged=False, style="claw"),
    "cricket": dict(name="Grill", hp=190, atk=16, range=20, speed=100, atkcd=0.9, kb=2, r=20,
                    reward=22, hover=0, ranged=False, style="ram"),
    "earthworm": dict(name="Cuc de terra", hp=760, atk=9, range=18, speed=28, atkcd=1.3, kb=4, r=28,
                      reward=34, hover=0, ranged=False, style="slime"),
    "firefly": dict(name="Lluerna", hp=170, atk=22, range=95, speed=58, atkcd=1.4, kb=1, r=18,
                    reward=28, hover=40, ranged=True, style="orb", proj="proj_orb"),
    "rhino": dict(name="Escarabat rinoceront", hp=5800, atk=54, range=26, speed=34, atkcd=1.4, kb=5, r=48,
                  reward=420, hover=0, ranged=False, style="joust"),
    "toad_king": dict(name="Gripau Rei", hp=5600, atk=46, range=135, speed=30, atkcd=1.8, kb=5, r=48,
                      reward=420, hover=0, ranged=True, style="tongue", proj="proj_tongue"),
}

# spawns: (enemic, primer_segon, interval, màxim_total)  |  events: hordes i mini-caps en un segon concret
# rec = nivell d'abelles recomanat  |  par = temps (s) per a la 2a estrella  |  cada nivell té 3-4 varietats d'enemics
STAGES = [
    dict(name="1. El Prat de Flors", diff=1, rec=1, par=120, base_hp=1500, mult=1.0, amult=1.0, cap=10, boss=False,
         bg="bg_meadow", base="base_anthill", base_off=22, amb="pollen", clouds=True,
         spawns=[("ant", 2, 7, 99), ("spider", 10, 10, 8), ("snail", 18, 18, 5)], events=[]),
    dict(name="2. El Bosc Fosc", diff=2, rec=1, par=140, base_hp=3200, mult=1.15, amult=1.0, cap=10, boss=False,
         bg="bg_forest", base="base_stump", base_off=22, amb="fireflies", clouds=False,
         spawns=[("termite", 2, 4, 99), ("spider", 6, 9, 99), ("beetle", 26, 18, 99)],
         events=[dict(t=45, units=[("termite", 8)], msg="Horda de tèrmits!")]),
    dict(name="3. El Camp de Blat", diff=3, rec=2, par=260, base_hp=4300, mult=1.50, amult=1.25, cap=10, boss=False,
         bg="bg_farm", base="base_scarecrow", base_off=6, amb="pollen", clouds=True,
         spawns=[("cricket", 2, 5, 99), ("ant", 4, 7, 99), ("locust", 10, 9, 99), ("earthworm", 18, 20, 6)],
         events=[dict(t=50, units=[("locust", 8)], msg="Plaga de llagostes!")]),
    dict(name="4. El Desert", diff=4, rec=3, par=240, base_hp=5040, mult=1.35, amult=1.20, cap=11, boss=False,
         bg="bg_desert", base="base_nest", base_off=24, amb="dust", clouds=True,
         spawns=[("locust", 2, 6, 99), ("wasp", 8, 12, 99), ("scorpion", 25, 18, 99), ("mantis", 40, 22, 99)],
         events=[dict(t=60, units=[("wasp", 4)], msg="Atac de vespes!")]),
    dict(name="5. La Platja", diff=5, rec=4, par=200, base_hp=7701, mult=1.54, amult=1.19, cap=11, boss=False,
         bg="bg_beach", base="base_sandcastle", base_off=10, amb="pollen", clouds=True,
         spawns=[("crab", 4, 9, 99), ("mosquito", 6, 8, 99), ("dragonfly", 20, 12, 99)],
         events=[dict(t=50, units=[("mosquito", 7)], msg="Eixam de mosquits!"),
                 dict(t=100, units=[("crab_king", 1)], msg="ALERTA: Cranc Rei!")]),
    dict(name="6. La Selva", diff=6, rec=5, par=420, base_hp=19496, mult=3.46, amult=1.73, cap=12, boss=False,
         bg="bg_jungle", base="base_tiki", base_off=6, amb="fireflies", clouds=False,
         spawns=[("frog", 5, 10, 99), ("mosquito", 4, 8, 99), ("mantis", 22, 18, 99)],
         events=[dict(t=70, units=[("mosquito", 8)], msg="Eixam de mosquits!"),
                 dict(t=110, units=[("toad_king", 1)], msg="ALERTA: Gripau Rei!")]),
    dict(name="7. El Pantà", diff=7, rec=6, par=380, base_hp=19288, mult=3.17, amult=1.74, cap=12, boss=False,
         bg="bg_swamp", base="base_swamp", base_off=20, amb="fireflies", clouds=False,
         spawns=[("frog", 6, 11, 99), ("dragonfly", 10, 9, 99), ("mosquito", 4, 8, 99), ("centipede", 30, 24, 99)],
         events=[dict(t=60, units=[("dragonfly", 6)], msg="Eixam de libèl·lules!"),
                 dict(t=110, units=[("frog", 4)], msg="Les granotes salten!")]),
    dict(name="8. Les Mines Abandonades", diff=8, rec=7, par=360, base_hp=19760, mult=2.92, amult=1.78, cap=12, boss=False,
         cat_hp=3500, bg="bg_mine", base="base_mine", base_off=6, amb="dust", clouds=False,
         hazard=dict(kind="rock", every=12, count=1, dmg=160),
         spawns=[("earthworm", 6, 14, 99), ("termite", 3, 5, 99), ("bat", 10, 9, 99)],
         events=[dict(t=80, units=[("rhino", 1)], msg="ALERTA: Rinoceront!")]),
    dict(name="9. La Cova de Cristalls", diff=9, rec=8, par=300, base_hp=16366, mult=2.27, amult=1.40, cap=12, boss=False,
         cat_hp=3500, bg="bg_cave", base="base_crystal", base_off=14, amb="spores", clouds=False,
         hazard=dict(kind="rock", every=12, count=1, dmg=170),
         spawns=[("bat", 4, 8, 99), ("widow", 8, 12, 99), ("centipede", 20, 18, 99)],
         events=[dict(t=70, units=[("scorpion_king", 1)], msg="ALERTA: Escorpí Rei!"),
                 dict(t=130, units=[("bat", 6)], msg="Surten els ratpenats!")]),
    dict(name="10. La Muntanya Nevada", diff=10, rec=9, par=340, base_hp=20645, mult=2.44, amult=1.47, cap=12, boss=False,
         cat_hp=3500, bg="bg_snow", base="base_igloo", base_off=10, amb="snow", clouds=False,
         hazard=dict(kind="ice", every=10, count=1, dmg=160),
         spawns=[("moth", 5, 10, 99), ("frostbeetle", 12, 15, 99), ("bat", 20, 12, 99), ("stag", 35, 26, 99)],
         events=[dict(t=80, units=[("stag", 2)], msg="Cérvols volants!")]),
    dict(name="11. El Volcà", diff=11, rec=10, par=340, base_hp=18368, mult=2.21, amult=1.42, cap=13, boss=False,
         cat_hp=3500, bg="bg_volcano", base="base_volcano", base_off=10, amb="embers", clouds=False,
         hazard=dict(kind="lava", every=9, count=2, dmg=190),
         spawns=[("fireant", 3, 5, 99), ("scorpion", 15, 16, 99), ("stag", 30, 28, 99), ("hornet", 40, 34, 99)],
         events=[dict(t=60, units=[("fireant", 8)], msg="Horda de formigues de foc!"),
                 dict(t=120, units=[("hornet", 2)], msg="Vespes asiàtiques!")]),
    dict(name="12. El Cementiri", diff=12, rec=11, par=380, base_hp=46906, mult=4.48, amult=2.05, cap=13, boss=False,
         cat_hp=4500, bg="bg_graveyard", base="base_crypt", base_off=8, amb="fireflies", clouds=False,
         hazard=dict(kind="rock", every=11, count=1, dmg=190),
         spawns=[("firefly", 4, 8, 99), ("widow", 8, 12, 99), ("bat", 14, 10, 99), ("moth", 24, 14, 99)],
         events=[dict(t=60, units=[("firefly", 8)], msg="Eixam de lluernes!"),
                 dict(t=120, units=[("widow", 4)], msg="Surten les vídues!")]),
    dict(name="13. La Tempesta", diff=13, rec=12, par=420, base_hp=61271, mult=5.39, amult=2.19, cap=13, boss=False,
         cat_hp=4500, bg="bg_storm", base="base_tower", base_off=6, amb="rain", clouds=False,
         hazard=dict(kind="lightning", every=8, count=2, dmg=200),
         spawns=[("dragonfly", 4, 7, 99), ("wasp", 8, 10, 99), ("moth", 20, 14, 99)],
         events=[dict(t=55, units=[("swallow", 1)], msg="ALERTA: Oreneta!"),
                 dict(t=110, units=[("swallow", 2)], msg="Dues orenetes!")]),
    dict(name="14. Les Ruïnes Antigues", diff=14, rec=13, par=480, base_hp=43936, mult=4.92, amult=2.16, cap=13, boss=False,
         cat_hp=4500, bg="bg_ruins", base="base_ruins", base_off=8, amb="dust", clouds=False,
         hazard=dict(kind="rock", every=10, count=2, dmg=190),
         spawns=[("widow", 4, 8, 99), ("mantis", 14, 16, 99), ("termite", 3, 5, 99)],
         events=[dict(t=60, units=[("tarantula", 1)], msg="ALERTA: Taràntula gegant!"),
                 dict(t=140, units=[("tarantula", 2)], msg="Dues taràntules!")]),
    dict(name="15. La Glacera Boreal", diff=15, rec=14, par=380, base_hp=51534, mult=3.64, amult=1.88, cap=13, boss=False,
         cat_hp=4500, bg="bg_glacier", base="base_icespire", base_off=6, amb="snow", clouds=False,
         hazard=dict(kind="ice", every=9, count=2, dmg=190),
         spawns=[("frostbeetle", 5, 12, 99), ("moth", 10, 10, 99), ("stag", 30, 24, 99)],
         events=[dict(t=60, units=[("swallow", 1)], msg="ALERTA: Oreneta!"),
                 dict(t=120, units=[("swallow", 2)], msg="Dues orenetes!")]),
    dict(name="16. La Planura de Cendres", diff=16, rec=14, par=440, base_hp=34934, mult=3.54, amult=1.93, cap=13, boss=False,
         cat_hp=5000, bg="bg_ash", base="base_obelisk", base_off=6, amb="embers", clouds=False,
         hazard=dict(kind="lava", every=8, count=2, dmg=210),
         spawns=[("fireant", 3, 4, 99), ("scorpion", 14, 14, 99), ("hornet", 30, 26, 99)],
         events=[dict(t=70, units=[("scorpion_king", 1)], msg="ALERTA: Escorpí Rei!"),
                 dict(t=140, units=[("scorpion_king", 1), ("fireant", 8)], msg="El Rei i la seva horda!")]),
    dict(name="17. El Bosc Maleït", diff=17, rec=15, par=460, base_hp=35926, mult=3.71, amult=2.06, cap=13, boss=False,
         cat_hp=5000, bg="bg_forest", base="base_cursed", base_off=8, amb="spores", clouds=False,
         hazard=dict(kind="lightning", every=9, count=2, dmg=220),
         spawns=[("bat", 4, 8, 99), ("widow", 8, 12, 99), ("hornet", 30, 28, 99)],
         events=[dict(t=70, units=[("mantis_king", 1)], msg="ALERTA: Mantis Rei!"),
                 dict(t=140, units=[("mantis_king", 1), ("hornet", 2)], msg="El Rei no ve sol!")]),
    dict(name="18. La Platja a la Nit", diff=18, rec=15, par=440, base_hp=56430, mult=5.80, amult=2.55, cap=13, boss=False,
         cat_hp=5000, bg="bg_beach", base="base_sandcastle", base_off=10, amb="sparkle", clouds=False, night=True,
         spawns=[("crab", 4, 8, 99), ("mosquito", 6, 7, 99), ("dragonfly", 14, 10, 99)],
         events=[dict(t=75, units=[("crab_king", 1)], msg="ALERTA: Cranc Rei!")]),
    dict(name="19. El Camp en Flames", diff=19, rec=15, par=450, base_hp=71340, mult=7.31, amult=2.86, cap=13, boss=False,
         cat_hp=5000, bg="bg_farm", base="base_scarecrow", base_off=6, amb="embers", clouds=False,
         hazard=dict(kind="lava", every=8, count=2, dmg=215),
         spawns=[("fireant", 3, 4, 99), ("locust", 8, 7, 99), ("cricket", 12, 7, 99)],
         events=[dict(t=80, units=[("rhino", 1)], msg="ALERTA: Rinoceront!")]),
    dict(name="20. La Selva Tempestuosa", diff=20, rec=15, par=460, base_hp=54560, mult=6.98, amult=2.87, cap=13, boss=False,
         cat_hp=5000, bg="bg_jungle", base="base_tiki", base_off=6, amb="fireflies", clouds=False,
         hazard=dict(kind="lightning", every=8, count=2, dmg=225),
         spawns=[("frog", 5, 9, 99), ("mantis", 14, 14, 99), ("firefly", 10, 9, 99)],
         events=[dict(t=80, units=[("toad_king", 1)], msg="ALERTA: Gripau Rei!")]),
    dict(name="21. El Pantà Embruixat", diff=21, rec=15, par=470, base_hp=49438, mult=6.73, amult=2.90, cap=13, boss=False,
         cat_hp=5500, bg="bg_swamp", base="base_swamp", base_off=20, amb="fireflies", clouds=False, night=True,
         spawns=[("widow", 5, 9, 99), ("frog", 8, 10, 99), ("centipede", 25, 20, 99)],
         events=[dict(t=90, units=[("tarantula", 1)], msg="ALERTA: Taràntula gegant!")]),
    dict(name="22. Les Mines Profundes", diff=22, rec=15, par=480, base_hp=105000, mult=10.70, amult=3.57, cap=13, boss=False,
         cat_hp=5500, bg="bg_mine", base="base_mine", base_off=6, amb="dust", clouds=False,
         hazard=dict(kind="rock", every=9, count=2, dmg=215),
         spawns=[("bat", 4, 8, 99), ("scorpion", 12, 13, 99), ("termite", 3, 5, 99)],
         events=[dict(t=80, units=[("scorpion_king", 1)], msg="ALERTA: Escorpí Rei!"),
                 dict(t=150, units=[("scorpion_king", 1), ("termite", 8)], msg="El Rei i el seu eixam!")]),
    dict(name="23. El Cim Gelat", diff=23, rec=15, par=490, base_hp=45900, mult=4.59, amult=2.49, cap=13, boss=False,
         cat_hp=6000, bg="bg_glacier", base="base_icespire", base_off=6, amb="snow", clouds=False,
         hazard=dict(kind="ice", every=8, count=2, dmg=215),
         spawns=[("frostbeetle", 5, 10, 99), ("moth", 10, 9, 99), ("stag", 28, 22, 99)],
         events=[dict(t=70, units=[("swallow", 1)], msg="ALERTA: Oreneta!"), dict(t=130, units=[("swallow", 2)], msg="Dues orenetes!")]),
    dict(name="24. EL NIU DE LA VESPA REINA", diff=24, rec=15, par=420, base_hp=26988, mult=2.43, amult=1.65, cap=10,
         boss=True, cat_hp=6000, bg="bg_lair", base="base_queen_0", base_off=0, amb="dust", clouds=False,
         spawns=[("wasp", 6, 13, 99), ("stag", 16, 26, 99), ("hornet", 35, 30, 99), ("hornet_guard", 70, 55, 99)],
         events=[]),
]
STAGE_REWARD = [(390, 3),
                (585, 3),
                (780, 4),
                (1040, 5),
                (1300, 6),
                (1690, 7),
                (2080, 8),
                (2600, 9),
                (3250, 10),
                (3900, 12),
                (4810, 14),
                (5850, 16),
                (7020, 18),
                (8320, 20),
                (9880, 24),
                (11700, 28),
                (14300, 32),
                (15500, 36),
                (17000, 40),
                (18500, 44),
                (20000, 48),
                (21500, 52),
                (23000, 56),
                (30000, 80)]
# música per tipus de fons
MUSIC_BY_BG = {"bg_meadow": "calm", "bg_farm": "calm", "bg_beach": "calm", "bg_jungle": "calm", "bg_desert": "calm",
               "bg_snow": "calm", "bg_forest": "tense", "bg_swamp": "tense", "bg_mine": "tense", "bg_cave": "tense",
               "bg_graveyard": "tense", "bg_glacier": "tense", "bg_ruins": "tense", "bg_volcano": "epic",
               "bg_storm": "epic", "bg_ash": "epic", "bg_lair": "boss"}

# missions: kind "stage" (nivells superats) o "stat" (comptadors)
MISSIONS = [
    dict(id="clear1", text="Supera el nivell 1", kind="stage", val=1, bee="carpenter", pollen=3),
    dict(id="clear2", text="Supera el nivell 2", kind="stage", val=2, bee="guard", pollen=4),
    dict(id="clear3", text="Supera el nivell 3", kind="stage", val=3, bee="sweat", pollen=5),
    dict(id="clear4", text="Supera el nivell 4", kind="stage", val=4, pollen=6),
    dict(id="clear5", text="Supera el nivell 5", kind="stage", val=5, bee="mason", pollen=7),
    dict(id="clear6", text="Supera el nivell 6", kind="stage", val=6, pollen=8),
    dict(id="clear7", text="Supera el nivell 7", kind="stage", val=7, bee="orchid", pollen=9),
    dict(id="clear8", text="Supera el nivell 8", kind="stage", val=8, pollen=10),
    dict(id="clear9", text="Supera el nivell 9", kind="stage", val=9, bee="nurse", pollen=11),
    dict(id="clear10", text="Supera el nivell 10", kind="stage", val=10, bee="arctic", pollen=12),
    dict(id="clear11", text="Supera el nivell 11", kind="stage", val=11, bee="cuckoo", pollen=13),
    dict(id="clear12", text="Supera el nivell 12", kind="stage", val=12, pollen=14),
    dict(id="clear13", text="Supera el nivell 13", kind="stage", val=13, bee="bluebanded", pollen=15),
    dict(id="clear14", text="Supera el nivell 14", kind="stage", val=14, bee="miner", pollen=16),
    dict(id="clear15", text="Supera el nivell 15", kind="stage", val=15, bee="woolcarder", pollen=17),
    dict(id="clear16", text="Supera el nivell 16", kind="stage", val=16, pollen=18),
    dict(id="clear17", text="Supera el nivell 17", kind="stage", val=17, pollen=19),
    dict(id="clear18", text="Supera el nivell 18", kind="stage", val=18, pollen=20),
    dict(id="clear19", text="Supera el nivell 19", kind="stage", val=19, pollen=22),
    dict(id="clear20", text="Supera el nivell 20", kind="stage", val=20, pollen=24),
    dict(id="clear21", text="Supera el nivell 21", kind="stage", val=21, pollen=26),
    dict(id="clear22", text="Supera el nivell 22", kind="stage", val=22, pollen=28),
    dict(id="clear23", text="Supera el nivell 23", kind="stage", val=23, pollen=30),
    dict(id="clear24", text="Derrota la Vespa Reina", kind="stage", val=24, bee="queen", pollen=40),
    dict(id="kills50", text="Derrota 50 enemics", kind="stat", stat="kills", val=50, mel=300),
    dict(id="kills300", text="Derrota 300 enemics", kind="stat", stat="kills", val=300, pollen=5),
    dict(id="kills1000", text="Derrota 1000 enemics", kind="stat", stat="kills", val=1000, mel=1500),
    dict(id="kills2500", text="Derrota 2500 enemics", kind="stat", stat="kills", val=2500, bee="killer"),
    dict(id="spawn100", text="Genera 100 abelles", kind="stat", stat="spawned", val=100, mel=400),
    dict(id="spawn500", text="Genera 500 abelles", kind="stat", stat="spawned", val=500, pollen=6),
    dict(id="spawn1500", text="Genera 1500 abelles", kind="stat", stat="spawned", val=1500, bee="giant"),
    dict(id="cannon10", text="Dispara la trompa 10 cops", kind="stat", stat="cannons", val=10, pollen=3),
    dict(id="cannon50", text="Dispara la trompa 50 cops", kind="stat", stat="cannons", val=50, pollen=8),
    dict(id="upg5", text="Millora abelles 5 cops", kind="stat", stat="upgrades", val=5, mel=300),
    dict(id="upg25", text="Millora abelles 25 cops", kind="stat", stat="upgrades", val=25, pollen=5),
    dict(id="upg100", text="Millora abelles 100 cops", kind="stat", stat="upgrades", val=100, pollen=12),
    dict(id="caps5", text="Obre 5 càpsules", kind="stat", stat="capsules", val=5, pollen=5),
    dict(id="caps20", text="Obre 20 càpsules", kind="stat", stat="capsules", val=20, pollen=10),
]
MISSIONS += [
    dict(id="seen10", text="Descobreix 10 enemics", kind="calc", calc="seen", val=10, pollen=4),
    dict(id="seen20", text="Descobreix 20 enemics", kind="calc", calc="seen", val=20, pollen=8),
    dict(id="seen32", text="Completa el bestiari", kind="calc", calc="seen", val=32, pollen=15),
    dict(id="own6", text="Tingues 6 abelles", kind="calc", calc="owned", val=6, mel=800),
    dict(id="own12", text="Tingues 12 abelles", kind="calc", calc="owned", val=12, pollen=8),
    dict(id="own18", text="Completa la col·lecció d'abelles", kind="calc", calc="owned", val=18, pollen=20),
    dict(id="evo1", text="Evoluciona una abella", kind="calc", calc="evo", val=1, pollen=6),
    dict(id="evo3", text="Evoluciona 3 abelles", kind="calc", calc="evo", val=3, pollen=12),
    dict(id="surv180", text="Aguanta 3 minuts en supervivència", kind="calc", calc="surv", val=180, pollen=6),
    dict(id="surv420", text="Aguanta 7 minuts en supervivència", kind="calc", calc="surv", val=420, pollen=14),
    dict(id="stars18", text="Aconsegueix 18 estrelles", kind="calc", calc="stars", val=18, pollen=6),
    dict(id="stars40", text="Aconsegueix 40 estrelles", kind="calc", calc="stars", val=40, pollen=12),
    dict(id="stars72", text="Totes les estrelles!", kind="calc", calc="stars", val=72, pollen=30),
]
WEEKLY_POOL = [
    dict(id="w_wins", stat="wins", val=8, text="Guanya 8 nivells", pollen=10),
    dict(id="w_kills", stat="kills", val=500, text="Derrota 500 enemics", pollen=8),
    dict(id="w_spawn", stat="spawned", val=250, text="Genera 250 abelles", mel=1200),
    dict(id="w_caps", stat="capsules", val=6, text="Obre 6 càpsules", pollen=8),
    dict(id="w_upg", stat="upgrades", val=12, text="Millora abelles 12 cops", pollen=8),
    dict(id="w_cannon", stat="cannons", val=25, text="Dispara la trompa 25 cops", mel=1000),
]
WEEKLY_BY_ID = {m["id"]: m for m in WEEKLY_POOL}
EVENTS = [dict(id="mel", name="Setmana de la mel", desc="+25% de mel en acabar un nivell"),
          dict(id="pollen", name="Setmana del pol·len", desc="+1 pol·len en guanyar un nivell"),
          dict(id="swarm", name="Setmana de l'eixam", desc="Abelles amb -10% de recàrrega")]
EVO_MEL, EVO_POLLEN, EVO_MULT = 3000, 15, 1.35
FRAG_COST = {"common": 10, "rare": 25, "legend": 60}
FRAG_GAIN = {"common": 1, "rare": 2, "legend": 4}


def current_event():
    return EVENTS[datetime.date.today().isocalendar()[1] % len(EVENTS)]


MISS_PER_PAGE = 7
CAP_HITS = (0.45, 0.85, 1.2)
CAP_BREAK = 1.45
CAP_REVEAL = 1.7
CAP_NEED = {"common": 3, "rare": 4, "legend": 5}      # clics per trencar la bola segons la raresa

CAPSULES = [
    dict(name="Càpsula de Mel", cost=("mel", 300), top=(226, 152, 40), pity=50,
         odds=(("common", 0.80), ("rare", 0.18), ("legend", 0.02))),
    dict(name="Càpsula Reial", cost=("pollen", 8), top=(204, 96, 52), pity=12,
         odds=(("common", 0.40), ("rare", 0.48), ("legend", 0.12))),
]


HIVE_MAX = 10
HIVE_UPG = [
    dict(id="hp", name="Rusc reforçat", desc="+10% de vida del rusc", base=185, per=0.10),
    dict(id="income", name="Cartera ràpida", desc="+6% d'ingressos per segon", base=220, per=0.06),
    dict(id="bounty", name="Botí de guerra", desc="+8% de diners per enemic", base=205, per=0.08),
    dict(id="wallet", name="Cartera gran", desc="+10% de diners màxims", base=255, per=0.10),
    dict(id="cdr", name="Reina diligent", desc="-3% de recàrrega de les abelles", base=305, per=0.03),
    dict(id="cannon_dmg", name="Trompa potent", desc="+12% de dany de la trompa", base=340, per=0.12),
    dict(id="cannon_cd", name="Trompa ràpida", desc="-4% de recàrrega de la trompa", base=355, per=0.04),
    dict(id="reward", name="Mel de victòria", desc="+5% de mel en acabar", base=425, per=0.05),
    dict(id="regen", name="Reparació", desc="El rusc es cura sol (0,15%/s)", base=595, per=0.0015),
    dict(id="swarm", name="Eixam (Q)", desc="+1 abella/2 nivells, -2,5 s recàrrega", base=290, per=0.0),
    dict(id="heal", name="Cura (E)", desc="+2,5% de cura i -3,5 s de recàrrega", base=300, per=0.0),
]
HIVE_BY_ID = {u["id"]: u for u in HIVE_UPG}

SHOP_MEL = [(3, 300, 3), (10, 1100, 2), (30, 3600, 1)]      # (pol·len, mel, límit per dia)
SHOP_ITEMS = [
    dict(id="money", name="Diners inicials", desc="Comences amb 300 de diners", cost=6, n=3),
    dict(id="hp", name="Escut del rusc", desc="+30% de vida del rusc", cost=8, n=3),
    dict(id="cannon", name="Trompa carregada", desc="Comences amb la trompa a punt", cost=8, n=3),
]
SHOP_SLOT_COST = 90
BEE_PRICE = {"common": 20, "rare": 45, "legend": 140}

DAILY_POOL = [
    dict(id="d_kills", stat="kills", val=60, text="Derrota 60 enemics", mel=300),
    dict(id="d_wins", stat="wins", val=2, text="Guanya 2 nivells", pollen=3),
    dict(id="d_spawn", stat="spawned", val=40, text="Genera 40 abelles", mel=250),
    dict(id="d_caps", stat="capsules", val=1, text="Obre una càpsula", pollen=2),
    dict(id="d_cannon", stat="cannons", val=5, text="Dispara la trompa 5 cops", mel=250),
    dict(id="d_upg", stat="upgrades", val=2, text="Millora abelles 2 cops", pollen=2),
    dict(id="d_heavy", stat="kills", val=120, text="Derrota 120 enemics", pollen=3),
]
DAILY_POOL_BY_ID = {m["id"]: m for m in DAILY_POOL}

_TH = dict(bg=(54, 44, 30), hexc=(72, 59, 38), bar=(140, 98, 44))
THEMES = {k: dict(_TH) for k in ("base", "stages", "upgrade", "equip", "capsules", "bestiary", "missions", "shop",
                                 "hive", "stats", "options")}
# transicions: (estil, color, text)
TRANS = {"stages": ("hex", (214, 170, 70)), "upgrade": ("wipe_r", (200, 140, 50)), "equip": ("wipe_l", (200, 140, 50)),
         "capsules": ("iris", (200, 130, 40)), "bestiary": ("fade", (120, 84, 38)), "missions": ("hex", (190, 140, 56)),
         "shop": ("wipe_r", (214, 160, 60)), "hive": ("hex", (214, 170, 70)), "stats": ("wipe_l", (190, 140, 56)),
         "options": ("fade", (110, 80, 40)), "base": ("fade", (60, 44, 24)), "title": ("fade", (40, 30, 16)),
         "intro": ("fade", (20, 14, 8)), "win": ("drip", (214, 170, 60)), "lose": ("drip", (80, 40, 40)), "dialogue": ("fade", (30, 24, 14)), "tutorial": ("hex", (214, 170, 70)), "help": ("fade", (60, 44, 24))}

TIPS = [
    ("Supera nivells per", "desbloquejar abelles", "noves a Missions!"),
    ("Millora les abelles", "amb mel per fer-les", "més fortes."),
    ("Les càpsules poden", "donar abelles rares", "i llegendàries."),
    ("Equipa fins a 5", "abelles abans de", "començar la batalla."),
    ("Si repeteixes una abella", "puja un nivell", "(màxim %d)." % MAX_LV),
    ("Guanya amb poc temps", "o sense trompa per", "aconseguir estrelles!"),
    ("Prem TAB a la batalla", "per anar al doble", "de velocitat."),
    ("Compra millores del", "rusc: més vida,", "diners i trompa!"),
    ("Cada dia: regal gratis", "i tres missions", "diàries noves."),
]
PROTA = "Flor"
CONT_COST, CONT_MAX = 30, 2
LEVEL_DIALOGUES = {
    0: ["Hola! Sóc la Flor, la nova guardiana del Gran Rusc.", "Genera abelles amb 1-6 i protegeix el rusc. Jo us guiaré!"],
    2: ["Les llagostes ataquen en grup. Les abelles tanques els aguantaran el cop."],
    4: ["Ens espera un Cranc Rei a la platja... Porta tiradores per tocar els mosquits voladors."],
    7: ["Les mines! Cauen roques: no deixis totes les abelles juntes."],
    9: ["El fred alenteix les abelles. Les de control ens poden ajudar."],
    12: ["Les orenetes piquen en picat. Guarda la trompa de pol·len per a elles!"],
    15: ["Ja som a prop! Evoluciona les teves abelles de nivell 15 al Taller."],
    17: ["Aquests territoris són més perillosos. Les millores del Rusc seran clau."],
    20: ["Això és molt dur... Recorda que l'Eixam (Q) i la Cura (E) ens poden salvar."],
    23: ["Aquest és el niu de la Vespa Reina... Si perdem, el seu poder esborrarà la llum de les abelles que lluitin.",
         "Si caiem, podem pagar 30 de pol·len per continuar. Tu pots, guardiana!"],
}
INTRO_SCENES = [
    (6.0, "Fa molt de temps, al Prat de Flors, el Gran Rusc vivia en pau. Les abelles collien pol·len i feien la mel més dolça del món.",
     dict(snd="magic")),
    (6.0, "La Reina Melissa, mare de totes les abelles, vetllava pel rusc des del seu tron daurat.", dict()),
    (7.0, "Però un dia un núvol negre va tapar el sol... i un brogit de ales va omplir el cel.", dict(snd="roar")),
    (7.0, "Era la Vespa Reina, cruel i golafre. Va jurar quedar-se tota la mel del món.", dict(snd="boom")),
    (7.0, f"Els seus exèrcits van arrasar boscos, deserts, platges, mines i volcans. Fins a {len(STAGES)} territoris van caure!",
     dict(snd="warn")),
    (7.0, "El Gran Rusc va resistir fins a l'última gota de mel... però la Reina Melissa va quedar ferida.", dict(snd="lose")),
    (8.0, "Abans de caure, va confiar la seva llum a una jove abella: tu.", dict(snd="levelup")),
    (7.0, "Amb la llum de la Reina, abelles de totes les castes van tornar a l'alba per defensar la seva llar.", dict(snd="reveal")),
    (8.0, f"El camí té {len(STAGES)} territoris. Millora les abelles, reuneix l'eixam i derrota la Vespa Reina al seu niu. Estàs a punt?",
     dict(snd="ability")),
    (4.0, "", dict(snd="win")),
]
WIN_SCENES = [
    (6.0, "La Vespa Reina va deixar anar un últim udol... i el seu niu es va enfonsar entre flaixos de llum.", dict(snd="boom")),
    (6.0, f"El cel es va aclarir. Els {len(STAGES)} territoris van ser alliberats i tots els ruscs van tornar a zumzejar d'alegria.", dict(snd="win")),
    (7.0, "La Reina Melissa es va recuperar i va coronar la Flor com a Guardiana del Gran Rusc.", dict(snd="levelup")),
    (7.0, "El Prat de Flors va tornar a florir... però la mel sempre atrau perills. Aquesta història continua.", dict(snd="reveal")),
    (4.0, "", dict(snd="win")),
]
LOSE_SCENES = [
    (6.0, "La Vespa Reina va riure mentre el Gran Rusc s'enfonsava en la foscor.", dict(snd="lose")),
    (8.0, "El seu poder va esborrar la llum de les abelles que van lluitar: van perdre tots els nivells i van quedar captives.", dict(snd="roar")),
    (8.0, "Però la Flor no es va rendir. Per rescatar-les hauràs de derrotar enemics: cada abella necessita el seu nombre. Mira la pestanya Rescat de Missions.", dict(snd="levelup")),
]
RESCUE_NEED = {"common": 120, "rare": 220, "legend": 400}
INTRO_TOTAL = sum(sc[0] for sc in INTRO_SCENES)
INTRO_MUSIC = ("calm", "calm", "tense", "tense", "tense", "tense", "epic", "epic", "epic", "calm")
TUT_CARDS = [
    ("Genera abelles", ["Les abelles surten del teu rusc, a l'esquerra, i", "avancen soles cap al niu enemic.", "Prem 1-6 o clica un botó per generar-ne.", "Cada abella costa diners i triga a recarregar-se."]),
    ("Diners i moneder", ["Els diners pugen sols i també en derrotar enemics.", "Prem W per millorar el moneder: més ingressos,", "menys recàrrega de les abelles i més botí."]),
    ("La trompa de pol·len", ["Quan estigui carregada, prem ESPAI.", "El rusc bufa un gran núvol de pol·len que", "fereix tots els enemics i els fa retrocedir."]),
    ("Habilitats", ["Q: l'Eixam crida abelles gratis.", "E: la Cura sana les abelles i el rusc.", "Tenen una recàrrega llarga: usa-les bé.", "Les pots millorar al Rusc."]),
    ("Rols i voladors", ["Tanc, Atacant, Tirador, Control i Suport.", "Amb 3 rols diferents guanyes +8% de vida.", "Els voladors només els fereixen del tot", "les tiradores i les antiaèries."]),
    ("I després?", ["Guanya nivells per aconseguir abelles i pol·len.", "Millora-les al Taller, evoluciona-les al nivell 15,", "compra al Rusc i a la Botiga, obre càpsules", "i fes missions. Bona sort, guardiana!"]),
]
KEYS = [pygame.K_1, pygame.K_2, pygame.K_3, pygame.K_4, pygame.K_5, pygame.K_6]


DAY_LEN = 480.0


def night_amount(t):
    """0 = de dia, 1 = de nit. Si la batalla dura molt es fa de nit i, més tard, torna a ser de dia."""
    p = t % DAY_LEN
    if p < 120:
        return 0.0
    if p < 180:
        return (p - 120) / 60.0
    if p < 300:
        return 1.0
    if p < 360:
        return 1.0 - (p - 300) / 60.0
    return 0.0


def stage_enemy_ids(s):
    """Enemics d'un nivell, en ordre d'aparició (spawns + events)."""
    ids = [e[0] for e in sorted(s["spawns"], key=lambda e: e[1])]
    for ev in s["events"]:
        for u in ev["units"]:
            if u[0] not in ids:
                ids.append(u[0])
    return ids


def bestiary_order():
    """Tots els enemics en ordre de primera aparició pels nivells."""
    order = []
    for s in STAGES:
        for k in stage_enemy_ids(s):
            if k not in order:
                order.append(k)
    return order


# ------------------------------------------------------------ DESAT (atòmic, amb còpia de seguretat)
def save_path():
    return os.path.join(data_dir(), "savegame.json")


def default_opts():
    return dict(fullscreen=False, sfx=True, music=True, volume=0.6, flashes=True, bigfont=False)


def default_save():
    return dict(ver=SAVE_VERSION, mel=200, pollen=10, owned={"honey": 1, "leafcutter": 1, "bumble": 1},
                deck=["honey", "leafcutter", "bumble"], progress=0, cannon=1, claimed=[],
                stats=dict(kills=0, spawned=0, cannons=0, capsules=0, upgrades=0, time=0.0, wins=0, losses=0,
                           dmg=0, by_bee={}),
                stars={}, seen=[], pity={"0": 0, "1": 0}, daily="", streak=0, tutorial_done=False,
                hive={}, items={"money": 0, "hp": 0, "cannon": 0}, armed={"money": False, "hp": False, "cannon": False},
                slot6=False, captured={}, dlg_seen=[], intro_done=False, tut_done=False, surv_best=0.0, surv_kills=0, evo={}, frag=0, presets=[[], [], []],
                wk={"week": "", "ids": [], "claimed": [], "prog": {}},
                shop={"slot": "", "day": "", "bee_bought": False, "lvl_bought": False, "mel": {}},
                dm={"date": "", "ids": [], "claimed": [], "prog": {}}, opts=default_opts())


def _read_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_save():
    d = default_save()
    raw = None
    legacy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "savegame_bees_v5.json")
    for p in (save_path(), save_path() + ".bak", legacy):
        try:
            raw = _read_json(p)
            break
        except Exception:
            raw = None
    if isinstance(raw, dict):
        for k in d:
            if k in raw:
                d[k] = raw[k]
        st = default_save()["stats"]
        st.update(d.get("stats", {}))
        d["stats"] = st
        op = default_opts()
        op.update(d.get("opts", {}))
        d["opts"] = op
        pt = {"0": 0, "1": 0}
        pt.update(d.get("pity", {}))
        d["pity"] = pt
        base = default_save()
        for k in ("items", "armed", "shop", "dm", "wk"):
            v = dict(base[k])
            if isinstance(d.get(k), dict):
                v.update(d[k])
            d[k] = v
        if not isinstance(d.get("presets"), list) or len(d["presets"]) != 3:
            d["presets"] = [[], [], []]
        if not isinstance(d.get("evo"), dict):
            d["evo"] = {}
        if not isinstance(d.get("captured"), dict):
            d["captured"] = {}
        if not isinstance(d.get("dlg_seen"), list):
            d["dlg_seen"] = []
        if not isinstance(d.get("hive"), dict):
            d["hive"] = {}
    if isinstance(raw, dict) and raw.get("ver", 0) < 11:       # 6 nivells nous abans del cap final
        if d["progress"] >= 18:
            d["progress"] = 17
        if "17" in d["stars"]:
            d["stars"]["23"] = d["stars"].pop("17")
    d["ver"] = SAVE_VERSION
    d["owned"] = {k: min(MAX_LV, int(v)) for k, v in d["owned"].items() if k in BEE_BY_KEY}
    d["deck"] = [k for k in d["deck"] if k in d["owned"]][:(DECK_MAX if d.get("slot6") else DECK_SIZE)]
    if not d["owned"]:
        d = default_save()
    return d


def write_save(sv):
    path = save_path()
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(sv, f, indent=1)
        if os.path.exists(path):
            try:
                shutil.copyfile(path, path + ".bak")
            except OSError:
                pass
        os.replace(tmp, path)
    except OSError:
        pass


# ------------------------------------------------------------ FONTS, IMATGES I CACHES
def make_fonts(big=False):
    global FONT, FONT_S, FONT_M, FONT_B, FONT_T
    d = 2 if big else 0
    FONT = pygame.font.SysFont(PF, 17 + d, bold=True)
    FONT_S = pygame.font.SysFont(PF, 13 + d, bold=True)
    FONT_M = pygame.font.SysFont(PF, 24 + d, bold=True)
    FONT_B = pygame.font.SysFont(PF, 40, bold=True)
    FONT_T = pygame.font.SysFont(PF, 78, bold=True)


def surf(im):
    return pygame.image.frombuffer(im.tobytes(), im.size, "RGBA").convert_alpha()


def white_mask(img):
    m = pygame.mask.from_surface(img)
    return m.to_surface(setcolor=(255, 255, 255, 170), unsetcolor=(0, 0, 0, 0))


def load_images(progress=None):
    spr = get_sprites(progress=progress)
    img = {}
    for b in BEE_UNITS:
        k = b["key"]
        fr = [surf(f) for f in spr["ally_" + k]]
        img["ally_" + k] = fr
        img["beeicon_" + k] = fr[0]
        m = pygame.mask.from_surface(fr[0])
        img["sil_" + k] = m.to_surface(setcolor=(18, 14, 12, 255), unsetcolor=(0, 0, 0, 0))
    for k in sorted({e.get("sprite", n) for n, e in ENEMIES.items()}):
        fr = [pygame.transform.flip(surf(f), True, False) for f in spr["enemy_" + k]]
        img["enemy_" + k] = fr
        m = pygame.mask.from_surface(fr[0])
        img["esil_" + k] = m.to_surface(setcolor=(18, 14, 12, 255), unsetcolor=(0, 0, 0, 0))
    for n, v in spr.items():
        if n.startswith(("ally_", "enemy_")):
            continue
        img[n] = [surf(f) for f in v] if isinstance(v, list) else surf(v)
    return img


class HeadlessImg(dict):
    """Imatges falses per al mode --simulate (no hi ha pantalla)."""

    def __missing__(self, key):
        return [None] * 8


_FIT = {}
_SHADOW = {}
_POLLEN = {}
_PART = {}
_BAND = []


def fit(img, mw, mh):
    """Escala un sprite per cabre en (mw, mh): enter si puja, suau si baixa."""
    key = (id(img), mw, mh)
    if key not in _FIT:
        w, h = img.get_size()
        s = min(mw / w, mh / h)
        if s < 1:
            im = pygame.transform.smoothscale(img, (max(1, int(w * s)), max(1, int(h * s))))
        else:
            k = max(1, int(s))
            im = pygame.transform.scale(img, (w * k, h * k))
        _FIT[key] = im
    return _FIT[key]


def shadow_img(sw):
    if sw not in _SHADOW:
        base = pygame.Surface((80, 24), pygame.SRCALPHA)
        pygame.draw.ellipse(base, (0, 0, 0, 90), (0, 0, 80, 24))
        _SHADOW[sw] = pygame.transform.smoothscale(base, (sw, max(6, sw // 4)))
    return _SHADOW[sw]


def pollen_img(sc):
    k = max(4, int(16 * sc))
    k = (k // 4) * 4
    if k not in _POLLEN:
        _POLLEN[k] = pygame.transform.scale(IMG["proj_pollen"], (k, k))
    return _POLLEN[k]


def part_img(col, r, a):
    key = (col, r, a // 32)
    if key not in _PART:
        sf = pygame.Surface((14, 14), pygame.SRCALPHA)
        pygame.draw.circle(sf, tuple(col) + (min(255, (a // 32) * 32 + 16),), (7, 7), r)
        _PART[key] = sf
    return _PART[key]


def cannon_band():
    if not _BAND:
        band = pygame.Surface((300, UI_Y), pygame.SRCALPHA)
        for i in range(300):
            band.fill((214, 190, 100, int(100 * (i / 300) ** 1.5)), (i, 0, 1, UI_Y))
        _BAND.append(band)
    return _BAND[0]


def make_hex_bg(theme="base"):
    th = THEMES.get(theme, THEMES["base"])
    s = pygame.Surface((W, H))
    s.fill(th["bg"])
    r = 26
    for row in range(-1, H // int(r * 1.5) + 2):
        for col in range(-1, W // int(r * 1.75) + 2):
            x = col * r * 1.75 + (r * 0.875 if row % 2 else 0)
            y = row * r * 1.5
            pts = [(x + r * 0.96 * math.cos(math.radians(60 * k + 30)),
                    y + r * 0.96 * math.sin(math.radians(60 * k + 30))) for k in range(6)]
            pygame.draw.polygon(s, th["hexc"], pts, 2)
    return s


# ------------------------------------------------------------ DIBUIX BÀSIC
def txt(s, x, y, font=None, color=C_TXT, center=False, shadow=True, right=False):
    font = font or FONT
    if shadow:
        sh = font.render(s, True, (20, 14, 8))
        r = sh.get_rect()
        if center:
            r.center = (x + 1, y + 2)
        elif right:
            r.topright = (x + 1, y + 2)
        else:
            r.topleft = (x + 1, y + 2)
        screen.blit(sh, r)
    img = font.render(s, True, color)
    r = img.get_rect()
    if center:
        r.center = (x, y)
    elif right:
        r.topright = (x, y)
    else:
        r.topleft = (x, y)
    screen.blit(img, r)


def bar(x, y, w, h, frac, col=C_GREEN):
    pygame.draw.rect(screen, (40, 14, 10), (x - w / 2, y, w, h))
    pygame.draw.rect(screen, col, (x - w / 2, y, w * max(0, min(1, frac)), h))
    pygame.draw.rect(screen, (0, 0, 0), (x - w / 2, y, w, h), 1)


def button(r, col):
    pygame.draw.rect(screen, C_BORDER, r.inflate(4, 4))
    pygame.draw.rect(screen, col, r)
    pygame.draw.rect(screen, tuple(min(255, v + 30) for v in col), (r.x, r.y, r.w, 2))
    pygame.draw.rect(screen, tuple(int(v * 0.7) for v in col), (r.x, r.bottom - 3, r.w, 3))


def draw_capsule(cx, cy, r, top, shake=0.0):
    cx += shake
    pygame.draw.circle(screen, C_BORDER, (cx, cy), r + 3)
    pygame.draw.circle(screen, (226, 214, 184), (cx, cy), r)
    pygame.draw.circle(screen, top, (cx, cy), r, draw_top_left=True, draw_top_right=True)
    pygame.draw.rect(screen, C_BORDER, (cx - r, cy - 2, r * 2, 5))
    pygame.draw.circle(screen, (250, 244, 224), (cx - r // 3, cy - r // 2), max(3, r // 7))


def star_pts(cx, cy, r):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    return pts


def draw_star(cx, cy, r, filled):
    pts = star_pts(cx, cy, r)
    pygame.draw.polygon(screen, (236, 200, 70) if filled else (60, 52, 44), pts)
    pygame.draw.polygon(screen, (110, 84, 24) if filled else (30, 26, 22), pts, 1)


def rar_icon(x, y, rarity, s=7):
    """Símbol de raresa (forma + color): cercle = comuna, rombe = rara, estrella = llegendària."""
    col = RAR_COL[rarity]
    if rarity == "common":
        pygame.draw.circle(screen, col, (x, y), s - 1)
        pygame.draw.circle(screen, C_BORDER, (x, y), s - 1, 1)
    elif rarity == "rare":
        pts = [(x, y - s), (x + s, y), (x, y + s), (x - s, y)]
        pygame.draw.polygon(screen, col, pts)
        pygame.draw.polygon(screen, C_BORDER, pts, 1)
    else:
        pts = star_pts(x, y, s + 2)
        pygame.draw.polygon(screen, col, pts)
        pygame.draw.polygon(screen, C_BORDER, pts, 1)


def status_icons(u, x, top):
    icons = []
    if u.poison_t > 0:
        icons.append("burn" if u.pfx_name == "fx_burn" else "poison")
    if u.slow_t > 0:
        icons.append("slow")
    if u.stun_t > 0:
        icons.append("stun")
    x0 = x - (len(icons) - 1) * 7
    for i, k in enumerate(icons):
        cx, cy = int(x0 + i * 14), int(top)
        if k == "poison":
            pygame.draw.circle(screen, (130, 200, 90), (cx, cy), 4)
            pygame.draw.circle(screen, (30, 60, 20), (cx, cy), 4, 1)
        elif k == "burn":
            pts = [(cx, cy - 5), (cx - 4, cy + 3), (cx + 4, cy + 3)]
            pygame.draw.polygon(screen, (246, 140, 50), pts)
            pygame.draw.polygon(screen, (90, 30, 10), pts, 1)
        elif k == "slow":
            pts = [(cx, cy - 5), (cx + 4, cy), (cx, cy + 5), (cx - 4, cy)]
            pygame.draw.polygon(screen, (130, 190, 240), pts)
            pygame.draw.polygon(screen, (30, 60, 110), pts, 1)
        else:
            pygame.draw.rect(screen, (240, 220, 90), (cx - 1, cy - 5, 3, 10))
            pygame.draw.rect(screen, (240, 220, 90), (cx - 5, cy - 1, 10, 3))


def lvl_mult(lv):
    return 1 + 0.15 * (lv - 1)


# ------------------------------------------------------------ SO (execució)
AUDIO = dict(ok=False, sfx={}, music={}, cur=None, last={}, opts=None, chan=None)
SFX_GAP = {"hit": 70, "sting": 80, "buzz": 60, "die": 60, "heal": 200, "click": 30, "slash": 70, "thud": 90, "zap": 70, "magic": 90, "crit": 60}


def audio_init(data):
    try:
        def _init():
            try:
                pygame.mixer.init(SR, -16, 1, 512, allowedchanges=0)
            except TypeError:
                pygame.mixer.init(SR, -16, 1, 512)
        if not pygame.mixer.get_init():
            _init()
        fr, _size, ch = pygame.mixer.get_init()
        if fr != SR or ch != 1:
            pygame.mixer.quit()
            _init()
            fr, _size, ch = pygame.mixer.get_init()
            if fr != SR or ch != 1:
                return
        pygame.mixer.set_num_channels(12)
        pygame.mixer.set_reserved(1)
        AUDIO["sfx"] = {k: pygame.mixer.Sound(buffer=v) for k, v in data["sfx"].items()}
        AUDIO["music"] = {k: pygame.mixer.Sound(buffer=v) for k, v in data["music"].items()}
        AUDIO["chan"] = pygame.mixer.Channel(0)
        AUDIO["ok"] = True
    except Exception:
        AUDIO["ok"] = False


def sfx(name, vol=1.0):
    o = AUDIO["opts"]
    if not AUDIO["ok"] or not o or not o.get("sfx", True):
        return
    now = pygame.time.get_ticks()
    if now - AUDIO["last"].get(name, -1000) < SFX_GAP.get(name, 40):
        return
    AUDIO["last"][name] = now
    s = AUDIO["sfx"].get(name)
    if s:
        s.set_volume(min(1.0, o.get("volume", 0.6) * vol))
        s.play()


def music_play(name):
    if not AUDIO["ok"] or AUDIO["cur"] == name:
        return
    AUDIO["cur"] = name
    o = AUDIO["opts"] or {}
    ch = AUDIO["chan"]
    if not o.get("music", True):
        ch.stop()
        return
    snd = AUDIO["music"].get(name)
    if snd:
        snd.set_volume(o.get("volume", 0.6) * 0.55)
        ch.play(snd, loops=-1, fade_ms=500)


def apply_audio():
    """Torna a aplicar les opcions de so (volum / música activada)."""
    cur = AUDIO["cur"]
    AUDIO["cur"] = None
    if AUDIO["ok"]:
        AUDIO["chan"].stop()
        if cur:
            music_play(cur)


# ------------------------------------------------------------ ENTITATS
class Base:
    def __init__(self, x, hp, r):
        self.x, self.hp, self.max, self.r = x, hp, hp, r

    def damage(self, a):
        self.hp = max(0, self.hp - a)


SEQ = (0, 1, 2, 1)
LUNGE_AMP = {"dash": 30, "slam": 3, "ram": 16, "stomp": 4, "royal": 6}


def anim_img(lst, anim, rate=10, phase=0.0):
    if len(lst) >= NF + 2:
        return lst[int(anim * rate * 0.6 + phase) % NF]
    return lst[SEQ[int(anim * rate + phase) % 4] % len(lst)]


_VAR = {}


def variant(key, fr, kind):
    """Versions derivades d'un fotograma (flaix blanc / estela), creades només quan cal."""
    k = (key, fr, kind)
    if k not in _VAR:
        base = IMG[key][fr]
        if kind == "hit":
            _VAR[k] = white_mask(base)
        else:
            gh = base.copy()
            gh.set_alpha(90)
            _VAR[k] = gh
    return _VAR[k]


class Unit:
    def __init__(self, d, side, mult=1.0):
        self.d = d
        self.side = side              # 0 = abelles, 1 = enemics
        self.dir = 1 if side == 0 else -1
        self.r = d["r"]
        self.x = CAT_BASE_X + 50 if side == 0 else ENEMY_BASE_X - 70
        self.y = GROUND + random.randint(0, 28)
        self.max = d["hp"] * (mult if side == 1 else 1)
        self.hp = self.max
        self.cd = 0.0
        self.kb_t = 0.0
        self.kb_v = 0.0
        self.kb_done = 0
        self.lunge = 0.0
        self.lunge_len = 0.18
        self.hit_t = 0.0
        self.phase = random.uniform(0, 6)
        self.poison_t = self.poison_dps = self.pfx_t = 0.0
        self.slow_t = self.stun_t = self.dash_t = 0.0
        self.pfx_name = "fx_poison"
        self.heal_t = 1.0
        self.moving = False
        self.last_img = None
        self.last_c = (0, 0)
        self.key = ("ally_" + d["key"]) if side == 0 else ("enemy_" + d.get("sprite", d["id"]))

    def knock(self):
        self.kb_t = 0.35
        self.kb_v = 230

    def damage(self, amt):
        self.hp -= amt
        self.hit_t = 0.1
        if self.hp > 0:
            n = self.d["kb"]
            if (self.max - self.hp) / self.max * n >= self.kb_done + 1:
                self.kb_done += 1
                self.knock()

    def update(self, g, dt):
        self.hit_t = max(0, self.hit_t - dt)
        self.dash_t = max(0, self.dash_t - dt)
        if self.lunge > 0:
            self.lunge -= dt
        if self.poison_t > 0:
            self.poison_t -= dt
            self.hp -= self.poison_dps * dt
            self.pfx_t -= dt
            if self.pfx_t <= 0:
                self.pfx_t = 0.5
                g.spawn_fx(self.pfx_name, self.x, self.y - self.d["hover"] - 30)
        if self.slow_t > 0:
            self.slow_t -= dt
        if self.stun_t > 0:
            self.stun_t -= dt
            return
        if self.kb_t > 0:
            self.kb_t -= dt
            self.x -= self.dir * self.kb_v * dt
            self.kb_v *= 0.93
            return
        self.cd -= dt
        foes = g.enemies if self.side == 0 else g.cats
        target, best = None, 1e9
        tank_t, tank_best = None, 1e9
        for f in foes:
            dist = abs(f.x - self.x) - f.r - self.r
            if dist <= self.d["range"]:
                if dist < best:
                    best, target = dist, f
                if f.d.get("tank") and dist < tank_best:
                    tank_best, tank_t = dist, f
        if tank_t is not None and self.side == 1:
            target = tank_t
        base = g.enemy_base if self.side == 0 else g.cat_base
        base_in_range = abs(base.x - self.x) - base.r - self.r <= self.d["range"]
        if target or base_in_range:
            if self.cd <= 0:
                self.cd = self.d["atkcd"]
                self.lunge_len = 0.3 if self.d["style"] == "dash" else 0.24
                self.lunge = self.lunge_len
                g.do_attack(self, target or base)
            self.moving = False
        else:
            self.moving = True
            self.x += self.dir * self.d["speed"] * dt * (0.55 if self.slow_t > 0 else 1.0)

    def draw(self, g):
        frames = IMG[self.key]
        n = len(frames)
        rich = n >= NF + 2
        rate = (15.0 if self.d["hover"] else 5.0 + self.d["speed"] * 0.08) * (0.55 if self.slow_t > 0 else 1.0)
        if self.stun_t > 0 or self.kb_t > 0:
            fr = NF // 2 if rich else 2
        elif rich:
            fr = int(g.anim * rate + self.phase) % NF
            if self.lunge > 0:
                fr = NF if (1 - self.lunge / self.lunge_len) < 0.4 else NF + 1
        else:
            fr = SEQ[int(g.anim * 10 + self.phase) % 4] % n
        bob = math.sin(g.anim * 5 + self.phase) * 3 if self.d["hover"] else 0
        if not self.d["hover"] and self.moving and self.kb_t <= 0:
            bob = -abs(math.sin(g.anim * rate * math.pi * 2 / NF + self.phase)) * 2.5
        hop = math.sin((1 - self.kb_t / 0.35) * math.pi) * 20 if self.kb_t > 0 else 0
        amp = LUNGE_AMP.get(self.d["style"], 9)
        off = 0.0
        if self.lunge > 0:
            off = self.dir * amp * math.sin(math.pi * (1 - self.lunge / self.lunge_len))
        x = self.x + off
        sh = shadow_img(int(self.r * 2.4))
        screen.blit(sh, sh.get_rect(center=(x, self.y)))
        img = frames[fr]
        yb = self.y - self.d["hover"] - bob - hop
        if self.dash_t > 0:
            for i in (3, 2, 1):
                gh = variant(self.key, fr, "ghost")
                screen.blit(gh, gh.get_rect(midbottom=(x - self.dir * i * 12, yb)))
        rect = img.get_rect(midbottom=(x, yb))
        screen.blit(img, rect)
        self.last_img, self.last_c = img, rect.center
        if self.hit_t > 0:
            screen.blit(variant(self.key, fr, "hit"), rect)
        if self.hp < self.max:
            bar(x, rect.top - 9, 34, 5, self.hp / self.max, C_GREEN if self.side == 0 else C_RED)
        status_icons(self, x, rect.top - 20)
        if self.d.get("evo"):
            draw_star(int(x + 24), int(rect.top - 9), 6, True)


# ------------------------------------------------------------ ICONES, BOLA D'AMBRE, TRANSICIONS
def _mix(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def draw_gear(cx, cy, r, col=(236, 222, 190)):
    for k in range(8):
        a = k * math.pi / 4
        ca, sa = math.cos(a), math.sin(a)
        pa, pb = (-sa, ca), (ca, sa)
        hw = r * 0.2
        pts = [(cx + pb[0] * r * 0.55 + pa[0] * hw, cy + pb[1] * r * 0.55 + pa[1] * hw),
               (cx + pb[0] * r + pa[0] * hw * 0.8, cy + pb[1] * r + pa[1] * hw * 0.8),
               (cx + pb[0] * r - pa[0] * hw * 0.8, cy + pb[1] * r - pa[1] * hw * 0.8),
               (cx + pb[0] * r * 0.55 - pa[0] * hw, cy + pb[1] * r * 0.55 - pa[1] * hw)]
        pygame.draw.polygon(screen, col, pts)
    pygame.draw.circle(screen, col, (cx, cy), int(r * 0.72))
    pygame.draw.circle(screen, C_DARK, (cx, cy), int(r * 0.3))
    pygame.draw.circle(screen, C_BORDER, (cx, cy), int(r * 0.72), 1)


def draw_chart(cx, cy, s, col=(236, 222, 190)):
    for i, h in enumerate((0.5, 0.95, 0.7)):
        x = cx - s * 0.7 + i * s * 0.55
        pygame.draw.rect(screen, col, (x, cy + s * 0.6 - s * 1.2 * h, s * 0.4, s * 1.2 * h))
        pygame.draw.rect(screen, C_BORDER, (x, cy + s * 0.6 - s * 1.2 * h, s * 0.4, s * 1.2 * h), 1)
    pygame.draw.line(screen, C_BORDER, (cx - s * 0.85, cy + s * 0.62), (cx + s * 0.85, cy + s * 0.62), 2)


def draw_book(cx, cy, s, col=(236, 222, 190)):
    pygame.draw.rect(screen, (120, 70, 50), (cx - s * 0.8, cy - s * 0.65, s * 1.6, s * 1.3))
    pygame.draw.rect(screen, col, (cx - s * 0.7, cy - s * 0.55, s * 0.65, s * 1.1))
    pygame.draw.rect(screen, col, (cx + s * 0.05, cy - s * 0.55, s * 0.65, s * 1.1))
    pygame.draw.line(screen, C_BORDER, (cx, cy - s * 0.65), (cx, cy + s * 0.65), 2)
    for k in range(3):
        pygame.draw.line(screen, (150, 130, 100), (cx - s * 0.6, cy - s * 0.3 + k * s * 0.3), (cx - s * 0.15, cy - s * 0.3 + k * s * 0.3))


def draw_gift(cx, cy, s, col=(214, 90, 70)):
    pygame.draw.rect(screen, col, (cx - s * 0.7, cy - s * 0.15, s * 1.4, s * 0.85))
    pygame.draw.rect(screen, tuple(min(255, v + 30) for v in col), (cx - s * 0.78, cy - s * 0.45, s * 1.56, s * 0.35))
    pygame.draw.rect(screen, (240, 210, 90), (cx - s * 0.12, cy - s * 0.45, s * 0.24, s * 1.15))
    pygame.draw.circle(screen, (240, 210, 90), (cx - s * 0.2, cy - s * 0.6), int(s * 0.2), 2)
    pygame.draw.circle(screen, (240, 210, 90), (cx + s * 0.2, cy - s * 0.6), int(s * 0.2), 2)
    pygame.draw.rect(screen, C_BORDER, (cx - s * 0.7, cy - s * 0.15, s * 1.4, s * 0.85), 1)


def draw_bag(cx, cy, s):
    pygame.draw.polygon(screen, (150, 98, 54), [(cx - s * 0.55, cy - s * 0.2), (cx + s * 0.55, cy - s * 0.2),
                                                (cx + s * 0.8, cy + s * 0.7), (cx - s * 0.8, cy + s * 0.7)])
    pygame.draw.polygon(screen, C_BORDER, [(cx - s * 0.55, cy - s * 0.2), (cx + s * 0.55, cy - s * 0.2),
                                           (cx + s * 0.8, cy + s * 0.7), (cx - s * 0.8, cy + s * 0.7)], 2)
    pygame.draw.rect(screen, (120, 74, 40), (cx - s * 0.4, cy - s * 0.42, s * 0.8, s * 0.22))
    pygame.draw.circle(screen, (240, 200, 70), (cx, cy + s * 0.25), int(s * 0.28))
    pygame.draw.circle(screen, (150, 110, 20), (cx, cy + s * 0.25), int(s * 0.28), 2)


_CRACKS = [[(0.12, -0.95), (0.0, -0.55), (0.16, -0.2), (0.02, 0.12)],
           [(-0.8, 0.45), (-0.45, 0.28), (-0.38, -0.05), (-0.1, -0.12)],
           [(0.9, -0.25), (0.55, -0.08), (0.58, 0.28), (0.28, 0.5)],
           [(-0.3, 0.92), (-0.05, 0.55), (0.18, 0.62)],
           [(-0.6, -0.7), (-0.35, -0.4), (-0.5, -0.15)],
           [(0.45, 0.8), (0.3, 0.45), (0.5, 0.3)]]


def _egg(cx, cy, rx, ry, k=1.0, tilt=-0.14, n=44):
    """Contorn d'una gota d'ambre (ou una mica estret a dalt)."""
    ca, sa = math.cos(tilt), math.sin(tilt)
    pts = []
    for i in range(n):
        t = 2 * math.pi * i / n
        u = math.cos(t)
        x = rx * k * math.sin(t) * (0.80 - 0.30 * u)
        y = -ry * k * u
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def _ell(cx, cy, rx, ry, ang=0.0, n=18):
    ca, sa = math.cos(ang), math.sin(ang)
    return [(cx + rx * math.cos(2 * math.pi * i / n) * ca - ry * math.sin(2 * math.pi * i / n) * sa,
             cy + rx * math.cos(2 * math.pi * i / n) * sa + ry * math.sin(2 * math.pi * i / n) * ca) for i in range(n)]


_SPECKS = [(-0.34, -0.22, 2), (0.30, 0.10, 2), (0.06, 0.58, 2), (-0.38, 0.42, 1), (0.34, -0.46, 2), (0.12, -0.64, 1),
           (-0.12, 0.30, 1), (0.40, 0.45, 1), (-0.05, -0.38, 1)]
_BUBBLES = [(0.30, 0.52, 3), (-0.30, -0.50, 2), (0.46, 0.18, 2), (-0.44, 0.10, 2)]


def draw_amber(cx, cy, r, tint, cracks=0, shake=(0, 0), glow=0.0):
    """Gota d'ambre translúcida amb una abella fosilitzada a dins (es pot esquerdar)."""
    cx, cy = cx + shake[0], cy + shake[1]
    rx, ry = r * 0.84, r * 1.14
    rim = _mix(tint, (70, 22, 4), 0.62)
    core = _mix(tint, (255, 238, 130), 0.62)
    if glow > 0:
        for k in range(3):
            g_ = pygame.Surface((int(rx * 3.2), int(ry * 3.2)), pygame.SRCALPHA)
            pygame.draw.polygon(g_, tint + (int(40 * glow / (k + 1)),), _egg(rx * 1.6, ry * 1.6, rx, ry, 1.12 + 0.16 * k))
            screen.blit(g_, (int(cx - rx * 1.6), int(cy - ry * 1.6)))
    pygame.draw.polygon(screen, _mix(rim, (0, 0, 0), 0.45), _egg(cx, cy, rx, ry, 1.05))
    N = 16
    for k in range(N):
        t = k / (N - 1)
        col = _mix(rim, tint, min(1.0, t * 2)) if t < 0.5 else _mix(tint, core, (t - 0.5) * 2)
        pygame.draw.polygon(screen, col, _egg(cx - r * 0.04 * t, cy + r * 0.02 * t, rx, ry, 1.0 - 0.92 * t))
    # vetes de resina
    for a_, b_, c_, d_ in ((-0.55, -0.30, -0.1, 0.62), (0.52, -0.1, 0.2, 0.68)):
        pygame.draw.line(screen, _mix(tint, (255, 232, 150), 0.35), (cx + a_ * rx, cy + b_ * ry), (cx + c_ * rx, cy + d_ * ry), 1)
    for sx, sy, sz in _SPECKS:
        pygame.draw.circle(screen, (60, 30, 8), (int(cx + sx * rx), int(cy + sy * ry)), max(1, int(sz * r / 70)))
    for bx_, by_, bz in _BUBBLES:
        p = (int(cx + bx_ * rx), int(cy + by_ * ry))
        pygame.draw.circle(screen, _mix(tint, (255, 250, 220), 0.5), p, max(2, int(bz * r / 50)))
        pygame.draw.circle(screen, _mix(tint, (90, 40, 6), 0.4), p, max(2, int(bz * r / 50)), 1)
    # abella fosilitzada (mirant a la dreta, girada)
    ca, sa = math.cos(-0.42), math.sin(-0.42)

    def T(pts):
        return [(cx + (x * ca - y * sa) * r, cy + (x * sa + y * ca) * r) for x, y in pts]
    wing = _mix(tint, (255, 244, 200), 0.5)
    for wp in ([(0.06, -0.06), (-0.18, -0.46), (0.06, -0.52), (0.20, -0.12)], [(0.16, -0.06), (0.08, -0.38), (0.32, -0.34), (0.30, -0.08)]):
        pygame.draw.polygon(screen, wing, T(wp))
        pygame.draw.polygon(screen, _mix(tint, (80, 40, 8), 0.55), T(wp), 1)
    for lg in ([(0.08, 0.1), (0.02, 0.3)], [(0.14, 0.1), (0.14, 0.32)], [(0.2, 0.08), (0.28, 0.28)]):
        pygame.draw.lines(screen, (70, 38, 8), False, T(lg), 2)
    pygame.draw.polygon(screen, (78, 42, 10), T(_ell(-0.24, 0.02, 0.32, 0.17)))
    for bxx in (-0.34, -0.22, -0.10):
        pygame.draw.polygon(screen, _mix(tint, (200, 130, 20), 0.5), T([(bxx, -0.14), (bxx + 0.06, -0.14), (bxx + 0.06, 0.18), (bxx, 0.18)]))
    pygame.draw.polygon(screen, (60, 32, 8), T([(-0.56, 0.02), (-0.66, 0.06), (-0.56, 0.08)]))
    pygame.draw.polygon(screen, (110, 64, 18), T(_ell(0.14, 0.0, 0.13, 0.12)))
    pygame.draw.polygon(screen, (40, 22, 6), T(_ell(0.31, 0.02, 0.10, 0.09)))
    pygame.draw.circle(screen, (255, 230, 150), (int(T([(0.34, -0.01)])[0][0]), int(T([(0.34, -0.01)])[0][1])), max(1, int(r / 40)))
    pygame.draw.lines(screen, (60, 32, 8), False, T([(0.38, -0.06), (0.5, -0.2), (0.58, -0.22)]), 1)
    pygame.draw.lines(screen, (60, 32, 8), False, T([(0.36, -0.08), (0.42, -0.26), (0.5, -0.3)]), 1)
    # reflexos i vora
    arc = [(cx + (rx * 0.9) * math.cos(math.radians(a)) * 0.98, cy + (ry * 0.9) * math.sin(math.radians(a)) * 0.98) for a in range(205, 262, 6)]
    pygame.draw.lines(screen, (255, 246, 206), False, arc, 3)
    pygame.draw.polygon(screen, (255, 252, 232), _ell(cx - 0.42 * rx, cy - 0.55 * ry, r * 0.09, r * 0.05, -0.8))
    pygame.draw.polygon(screen, (60, 26, 6), _egg(cx, cy, rx, ry, 1.0), 3)
    for line in _CRACKS[:cracks * 2]:
        pts = [(cx + px * r * 0.92, cy + py * r * 0.92) for px, py in line]
        pygame.draw.lines(screen, (46, 22, 4), False, pts, 3)
        pygame.draw.lines(screen, (255, 236, 170), False, [(x + 1, y - 1) for x, y in pts], 1)


def draw_stall(cx, cy, s):
    """Parada de mercat amb tenda de ratlles (símbol de la botiga)."""
    for k in range(6):
        col = (206, 70, 56) if k % 2 == 0 else (244, 232, 200)
        x0 = cx - s * 0.9 + k * s * 0.3
        pygame.draw.polygon(screen, col, [(x0, cy - s * 0.1), (x0 + s * 0.3, cy - s * 0.1), (x0 + s * 0.34, cy - s * 0.55),
                                          (x0 - s * 0.04, cy - s * 0.55)])
        pygame.draw.circle(screen, col, (int(x0 + s * 0.15), int(cy - s * 0.1)), int(s * 0.15))
    pygame.draw.rect(screen, C_BORDER, (cx - s * 0.9, cy - s * 0.56, s * 1.8, s * 0.46), 1)
    pygame.draw.rect(screen, (150, 98, 54), (cx - s * 0.8, cy + s * 0.15, s * 1.6, s * 0.55))
    pygame.draw.rect(screen, C_BORDER, (cx - s * 0.8, cy + s * 0.15, s * 1.6, s * 0.55), 1)
    pygame.draw.line(screen, (200, 150, 80), (cx - s * 0.8, cy + s * 0.3), (cx + s * 0.8, cy + s * 0.3), 1)
    pygame.draw.circle(screen, (240, 200, 70), (int(cx), int(cy + s * 0.05)), int(s * 0.2))
    pygame.draw.circle(screen, (150, 110, 20), (int(cx), int(cy + s * 0.05)), int(s * 0.2), 1)


def draw_stinger(tipx, tipy, length=130):
    """Agulla (fibló) que pica la bola."""
    pygame.draw.polygon(screen, (40, 26, 16), [(tipx, tipy), (tipx + length, tipy - 8), (tipx + length, tipy + 8)])
    pygame.draw.line(screen, (150, 120, 90), (tipx + 6, tipy - 1), (tipx + length, tipy - 6), 2)
    pygame.draw.rect(screen, (214, 170, 60), (tipx + length, tipy - 12, 16, 24))
    pygame.draw.rect(screen, C_BORDER, (tipx + length, tipy - 12, 16, 24), 2)


def draw_transition(style, color, p, label=None):
    """p de 0 a 1: cobreix la pantalla fins a la meitat i la descobreix."""
    a = 1 - abs(2 * p - 1)
    if style == "fade":
        s = pygame.Surface((W, H))
        s.fill(color)
        s.set_alpha(int(255 * min(1.0, a * 1.5)))
        screen.blit(s, (0, 0))
    elif style in ("wipe_r", "wipe_l"):
        if p < 0.5:
            w = int(W * 2 * p)
            x = 0 if style == "wipe_r" else W - w
        else:
            w = int(W * (2 - 2 * p))
            x = W - w if style == "wipe_r" else 0
        pygame.draw.rect(screen, color, (x, 0, w, H))
        edge = x + w - 10 if (style == "wipe_r") == (p < 0.5) else x
        pygame.draw.rect(screen, _mix(color, (255, 255, 255), 0.35), (edge, 0, 10, H))
    elif style == "hex":
        r = 44
        for row in range(-1, int(H / (r * 1.5)) + 2):
            for col in range(-1, int(W / (r * 1.75)) + 2):
                x = col * r * 1.75 + (r * 0.875 if row % 2 else 0)
                y = row * r * 1.5
                sc = max(0.0, min(1.0, a * 1.7 - (x / W) * 0.7))
                if sc <= 0:
                    continue
                pts = [(x + r * 1.06 * sc * math.cos(math.radians(60 * k + 30)),
                        y + r * 1.06 * sc * math.sin(math.radians(60 * k + 30))) for k in range(6)]
                pygame.draw.polygon(screen, color if (row + col) % 2 else _mix(color, (0, 0, 0), 0.18), pts)
    elif style == "iris":
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        s.fill(color + (255,))
        hole = int((1 - a) * math.hypot(W, H) / 2)
        if hole > 0:
            pygame.draw.circle(s, (0, 0, 0, 0), (W // 2, H // 2), hole)
        screen.blit(s, (0, 0))
    else:  # drip: mel que regalima
        for i in range(0, W + 40, 40):
            k = ((i * 37) % 100) / 100.0
            ln = int(H * min(1.0, max(0.0, a * 1.6 - k * 0.55)))
            if ln <= 0:
                continue
            pygame.draw.rect(screen, color, (i - 20, 0, 41, ln))
            pygame.draw.circle(screen, color, (i, ln), 20)
            pygame.draw.circle(screen, _mix(color, (255, 255, 255), 0.4), (i - 7, max(0, ln - 6)), 5)
    if label and a > 0.75:
        txt(label, W // 2, H // 2, FONT_B, (255, 246, 220), center=True)


# ------------------------------------------------------------ PANTALLES I DIBUIX
def wrap_text(text, font, maxw):
    lines, cur = [], ""
    for w in text.split():
        trial = (cur + " " + w).strip()
        if cur and font.size(trial)[0] > maxw:
            lines.append(cur)
            cur = w
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


class GameUI:
    # =================================================== BOTONS I CONTENIDORS
    def btn(self, rect, action, enabled=True):
        self.hits.append((rect, action, enabled))

    def ui_button(self, r, label, action, enabled=True, font=None):
        font = font or FONT_M
        hov = enabled and r.collidepoint(pygame.mouse.get_pos())
        button(r, (C_BTN_HOVER if hov else C_BTN) if enabled else C_BTN_OFF)
        txt(label, r.centerx, r.centery, font, C_DARK if enabled else (126, 114, 100), center=True, shadow=False)
        self.btn(r, action, enabled)

    def card(self, r, rarity=None, hl=False):
        pygame.draw.rect(screen, C_BORDER, r.inflate(4, 4))
        pygame.draw.rect(screen, C_CARD, r)
        col = RAR_COL[rarity] if rarity else (90, 80, 70)
        pygame.draw.rect(screen, (240, 220, 140) if hl else col, r, 2)
        if rarity:
            rar_icon(r.right - 13, r.y + 13, rarity)

    def hexbg(self, theme):
        if theme not in self.hex_cache:
            self.hex_cache[theme] = make_hex_bg(theme)
        return self.hex_cache[theme]

    def chrome(self, title, back=True, theme="base", back_to="base"):
        th = THEMES.get(theme, THEMES["base"])
        screen.blit(self.hexbg(theme), (0, 0))
        bc = th["bar"]
        lt, dk = _mix(bc, (255, 255, 255), 0.25), _mix(bc, (0, 0, 0), 0.45)
        for y0 in (0, H - 48):
            pygame.draw.rect(screen, bc, (0, y0, W, 48))
        pygame.draw.rect(screen, lt, (0, 0, W, 3))
        pygame.draw.rect(screen, dk, (0, 45, W, 3))
        pygame.draw.rect(screen, lt, (0, H - 48, W, 3))
        txt(title, 16, 9, FONT_M, C_TXT)
        # les dues divises, juntes a dalt
        pygame.draw.rect(screen, dk, (W - 134, 8, 124, 32))
        screen.blit(fit(IMG["proj_pollen"], 32, 32), (W - 132, 8))
        txt(f"{self.sv['pollen']}", W - 18, 12, FONT_M, C_GOLD, right=True)
        pygame.draw.rect(screen, dk, (W - 306, 8, 164, 32))
        screen.blit(IMG["icon_honey"], (W - 304, 8))
        txt(f"{self.sv['mel']}", W - 150, 12, FONT_M, C_GOLD, right=True)
        for k, f in enumerate(self.ui_floats[-3:]):
            a = min(1.0, f[1] / 0.6)
            txt(f[0], W - 12, 52 + (1 - a) * -6 + k * 22, FONT, (min(255, int(250 * a + 40)), min(255, int(236 * a + 30)), min(255, int(150 * a + 20))), right=True)
        if back:
            self.ui_button(pygame.Rect(10, H - 42, 70, 36), "<", lambda: self.go(back_to), font=FONT_B)
        if self.toast[1] > 0:
            txt(self.toast[0], W // 2, H - 24, FONT, (250, 236, 180), center=True)

    def icon_button(self, r, fn, action, badge=0, enabled=True):
        hov = enabled and r.collidepoint(pygame.mouse.get_pos())
        button(r, (C_BTN_HOVER if hov else C_BTN) if enabled else C_BTN_OFF)
        fn(r.centerx, r.centery)
        if badge:
            pygame.draw.circle(screen, C_RED, (r.right - 4, r.y + 4), 11)
            txt(str(badge) if badge < 10 else "!", r.right - 4, r.y + 4, FONT_S, (255, 255, 255), center=True, shadow=False)
        self.btn(r, action, enabled)

    def page_ctl(self, attr, pages):
        cur = max(0, min(getattr(self, attr), pages - 1))
        setattr(self, attr, cur)
        if pages > 1:
            self.ui_button(pygame.Rect(92, H - 42, 52, 36), "<", lambda: setattr(self, attr, cur - 1), cur > 0, FONT_B)
            txt(f"{cur + 1}/{pages}", 172, H - 24, FONT, C_TXT, center=True)
            self.ui_button(pygame.Rect(200, H - 42, 52, 36), ">", lambda: setattr(self, attr, cur + 1), cur < pages - 1,
                           FONT_B)
        return cur

    # =================================================== BATALLA
    def draw_bases(self):
        b = self.cat_base
        img = IMG["base_hive"]
        hx, hy = b.x - img.get_width() // 2, GROUND + 28 - img.get_height()
        screen.blit(img, (hx, hy))
        # canó del rusc (retrocedeix quan dispara)
        k = max(0.0, self.kick) / 0.4
        rec = int(12 * math.sin(k * math.pi / 2)) if k > 0 else 0
        screen.blit(IMG["hive_cannon"], (hx + 46 - rec // 3, hy - 38 + rec // 2))
        mx, my = self.muzzle()
        if self.cannon >= self.cannon_time and self.kick <= 0:
            pl = 0.5 + 0.5 * math.sin(self.anim * 8)
            g_ = pygame.Surface((40, 40), pygame.SRCALPHA)
            pygame.draw.circle(g_, (255, 224, 120, int(60 + 90 * pl)), (20, 20), 12 + int(5 * pl))
            screen.blit(g_, (mx - 20, my - 20))
        bar(b.x, hy - 18, 90, 10, b.hp / b.max)
        txt(f"{int(b.hp)}/{int(b.max)}", b.x, hy - 30, FONT_S, center=True)

        e = self.enemy_base
        if self.stage.get("survival"):
            img = IMG[self.stage["base"]]
            screen.blit(img, img.get_rect(midbottom=(e.x, GROUND + self.stage["base_off"])))
            tm = int(self.time)
            txt("SUPERVIVÈNCIA  %d:%02d" % (tm // 60, tm % 60), e.x - 20, GROUND + self.stage["base_off"] - img.get_height() - 30,
                FONT, (250, 200, 130), center=True)
        elif self.stage["boss"]:
            frames = IMG["base_queen_%d" % self.phase]
            img = frames[SEQ[int(self.anim * 5) % 4] % len(frames)]
            screen.blit(img, (W - 420 + 24, 6 + math.sin(self.anim * 2) * 3))
            bar(W // 2, 14, 460, 14, e.hp / e.max, C_RED)
            for fr_ in (0.33, 0.66):
                pygame.draw.rect(screen, (0, 0, 0), (W // 2 - 230 + 460 * fr_, 12, 2, 18))
            txt(f"LA VESPA REINA   {int(e.hp)}/{int(e.max)}", W // 2, 42, FONT, center=True)
        else:
            img = IMG[self.stage["base"]]
            screen.blit(img, img.get_rect(midbottom=(e.x, GROUND + self.stage["base_off"])))
            top = GROUND + self.stage["base_off"] - img.get_height()
            bar(e.x, top - 18, 90, 10, e.hp / e.max, C_RED)
            txt(f"{int(e.hp)}/{int(e.max)}", e.x, top - 30, FONT_S, center=True)

    def draw_tooltip(self, d, r):
        lv = self.sv["owned"].get(d["key"], 1)
        hp, atk = self.bee_stats(d["key"], lv)
        lines = [f"{d['name']}  Nv{lv}", f"PV {hp}  ATQ {atk}  Rang {d['range']}  Cost {d['cost']}",
                 f"{d['role']}" + (" - toca els voladors" if d["air"] else "") + "  |  " + STYLE_NAME[d["style"]], d["desc"]]
        w = 16 + max(FONT_S.size(ln)[0] for ln in lines)
        h = 10 + 18 * len(lines)
        x = max(4, min(W - w - 4, r.x))
        y = r.y - h - 6
        pygame.draw.rect(screen, C_BORDER, (x - 2, y - 2, w + 4, h + 4))
        pygame.draw.rect(screen, (40, 34, 30), (x, y, w, h))
        for i, ln in enumerate(lines):
            txt(ln, x + 8, y + 6 + i * 18, FONT_S, C_GOLD if i == 0 else C_TXT, shadow=False)

    def draw_battle_ui(self):
        screen.blit(IMG["ui_panel"], (0, UI_Y))
        screen.blit(IMG["icon_honey"], (10, 6))
        txt(f"{int(self.money)} / {int(self.max_money)}", 50, 8, FONT_M, C_GOLD)
        txt(f"+{self.income:.0f}/s", 50 + FONT_M.size(f"{int(self.money)} / {int(self.max_money)}")[0] + 12, 12, FONT_S, (176, 214, 150))
        txt(self.stage["name"], W - 12 - FONT.size(self.stage["name"])[0], 10, FONT)
        # velocitat i pausa
        for r, label in ((self.btn_speed, "x2" if self.speed == 2 else "x1"), (self.btn_pause, "II")):
            button(r, C_BTN)
            txt(label, r.centerx, r.centery, FONT, C_DARK, center=True, shadow=False)
        for i, (r, lab, tot) in enumerate(((self.btn_abil[0], "[Q] Eixam", self.swarm_cd()), (self.btn_abil[1], "[E] Cura", self.heal_cd()))):
            cd = self.abil_cd[i]
            button(r, C_BTN if cd <= 0 else C_BTN_OFF)
            if cd > 0:
                sf = pygame.Surface((int(r.w * cd / tot) + 1, r.h), pygame.SRCALPHA)
                sf.fill((16, 10, 4, 150))
                screen.blit(sf, (r.x, r.y))
            txt(lab if cd <= 0 else f"{lab[4:]} {int(cd) + 1}s", r.centerx, r.centery, FONT_S, C_DARK if cd <= 0 else C_TXT, center=True, shadow=False)
        nxt = self.next_event()
        if self.stage["boss"] and self.phase < 2:
            pass
        elif nxt and nxt[0] <= 25:
            txt(f"Proper: {nxt[1]}  ({int(nxt[0])} s)", W // 2, 44, FONT_S, (250, 200, 130), center=True)
        mp = pygame.mouse.get_pos()
        tip = None
        for i, d in enumerate(self.deck):
            r = self.btn_units[i]
            can = self.cds[i] <= 0 and self.money >= d["cost"]
            col = C_BTN if can else C_BTN_OFF
            hov = r.collidepoint(mp)
            if can and hov:
                col = C_BTN_HOVER
            button(r, col)
            ic = fit(IMG["beeicon_" + d["key"]], 72, 40)
            screen.blit(ic, ic.get_rect(center=(r.centerx, r.y + 32)))
            txt(f"[{i + 1}]", r.x + 5, r.y + 3, FONT_S, C_DARK, shadow=False)
            txt(f"{d['cost']}", r.centerx, r.y + 68, FONT, C_DARK, center=True, shadow=False)
            if self.cds[i] > 0:
                h = int(r.h * self.cds[i] / d["cd"])
                sf = pygame.Surface((r.w, h), pygame.SRCALPHA)
                sf.fill((16, 10, 4, 160))
                screen.blit(sf, (r.x, r.y))
                txt(str(int(self.cds[i]) + 1), r.centerx, r.y + 36, FONT_M, (250, 240, 210), center=True)
            if hov:
                tip = (d, r)
        r = self.btn_wallet
        maxed = self.wallet >= WALLET_MAX
        can = not maxed and self.money >= self.wallet_cost
        button(r, C_BTN if can else C_BTN_OFF)
        txt("[W] Rusc", r.centerx, r.y + 16, FONT_S, C_DARK, center=True, shadow=False)
        txt(f"Nivell {self.wallet}", r.centerx, r.y + 40, FONT, C_DARK, center=True, shadow=False)
        txt("MAX" if maxed else f"{self.wallet_cost}", r.centerx, r.y + 64, FONT, C_DARK, center=True, shadow=False)
        r = self.btn_cannon
        ready = self.cannon >= self.cannon_time
        button(r, (176, 100, 60) if ready else (92, 62, 50))
        ic = fit(IMG["hive_cannon"], 60, 42)
        screen.blit(ic, (r.x + 6, r.y + 22))
        txt("[ESPAI]", r.x + 68, r.y + 10, FONT_S, C_TXT)
        txt("PREPARAT!" if ready else f"{int(self.cannon / self.cannon_time * 100)}%", r.x + 70, r.y + 44, FONT, C_TXT)
        pygame.draw.rect(screen, (30, 18, 8), (r.x + 8, r.bottom - 12, r.w - 16, 6))
        pygame.draw.rect(screen, C_GOLD, (r.x + 8, r.bottom - 12, (r.w - 16) * self.cannon / self.cannon_time, 6))
        if tip and not self.paused:
            self.draw_tooltip(*tip)
        elif self.btn_wallet.collidepoint(mp) and not self.paused:
            w = self.wallet
            lines = [f"Moneder nivell {w}/{WALLET_MAX}", f"Ingressos: {self.income:.0f}/s   Màxim: {int(self.max_money)}",
                     f"Recàrrega abelles: -{3 * (w - 1)}%   Botí: +{4 * (w - 1)}%",
                     "Següent nivell: +6/s, +150 màxim, -3% recàrrega, +4% botí" if w < WALLET_MAX else "Nivell màxim"]
            tw = 16 + max(FONT_S.size(ln)[0] for ln in lines)
            th = 10 + 18 * len(lines)
            r = self.btn_wallet
            x, y = max(4, min(W - tw - 4, r.x - tw // 2)), r.y - th - 6
            pygame.draw.rect(screen, C_BORDER, (x - 2, y - 2, tw + 4, th + 4))
            pygame.draw.rect(screen, (40, 34, 30), (x, y, tw, th))
            for i, ln in enumerate(lines):
                txt(ln, x + 8, y + 6 + i * 18, FONT_S, C_GOLD if i == 0 else C_TXT, shadow=False)

    def draw_world_bg(self):
        nm, t = self.stage["bg"], self.anim
        screen.blit(IMG[nm + "_sky"], (0, 0))
        amb = self.stage["amb"]
        if amb == "stars":
            for x, y, ph, sp in self.amb:
                if y < 300 and math.sin(t * sp * 2 + ph) > 0.5:
                    pygame.draw.rect(screen, (255, 255, 255), (int(x), int(y * 0.75), 2, 2))
        if self.stage["clouds"]:
            for i in range(3):
                screen.blit(IMG["cloud_%d" % i], (((t * (6 + i * 4) + i * 420) % (W + 380)) - 190, 26 + i * 46))
        screen.blit(IMG[nm + "_mid"], (0, 0))
        screen.blit(IMG[nm + "_ground"], (0, 0))
        if amb == "pollen":
            for x, y, ph, sp in self.amb:
                pygame.draw.rect(screen, (244, 232, 160),
                                 (int((x + t * 10 * sp) % W), int(250 + y % 170 + 8 * math.sin(t * sp + ph)), 2, 2))
        elif amb == "fireflies":
            for x, y, ph, sp in self.amb[:16]:
                a = (math.sin(t * 2 * sp + ph) + 1) / 2
                col = (int(240 * a), int(226 * a), int(110 * a))
                px, py = int(x + 40 * math.sin(t * 0.4 * sp + ph)), int(230 + y % 180 + 14 * math.sin(t * 0.7 * sp + ph * 2))
                pygame.draw.rect(screen, col, (px, py, 3, 3))
                pygame.draw.rect(screen, (int(col[0] * 0.4), int(col[1] * 0.4), int(col[2] * 0.4)), (px - 1, py - 1, 5, 5), 1)
        elif amb == "snow":
            for x, y, ph, sp in self.amb[:34]:
                px = (x + 14 * math.sin(t * 0.6 + ph)) % W
                py = (y * 1.1 + t * 38 * sp) % UI_Y
                pygame.draw.rect(screen, (240, 246, 252), (int(px), int(py), 2, 2))
        elif amb == "spores":
            for x, y, ph, sp in self.amb[:22]:
                a = (math.sin(t * sp + ph) + 1) / 2
                col = (int(176 * a), int(130 * a), int(232 * a))
                py = 60 + (y - t * 14 * sp) % 340
                pygame.draw.rect(screen, col, (int(x + 12 * math.sin(t * 0.5 + ph)), int(py), 3, 3))
        elif amb == "embers":
            for x, y, ph, sp in self.amb[:26]:
                py = 430 - ((t * 36 * sp + y) % 380)
                a = max(0.0, min(1.0, (py - 40) / 200))
                col = (int(255 * a), int(150 * a), int(60 * a))
                pygame.draw.rect(screen, col, (int(x + 16 * math.sin(t * 0.7 + ph)), int(py), 2, 2))
        elif amb == "rain":
            for x, y, ph, sp in self.amb[:34]:
                for k in range(2):
                    px = (x + k * 470 - t * 160 * sp) % W
                    py = (y * 1.2 + t * 520 * sp + k * 200) % UI_Y
                    pygame.draw.line(screen, (150, 168, 200), (px, py), (px - 4, py + 11))
        elif amb == "dust":
            for x, y, ph, sp in self.amb[:18]:
                pygame.draw.rect(screen, (222, 196, 154), (int((x + t * 70 * sp) % W), int(360 + y % 60), 3, 1))

    def draw_night(self):
        n = 0.0 if self.headless else night_amount(self.time)
        if self.stage.get("night") and not self.headless:
            n = max(n, 0.9)
        if n <= 0.01:
            return
        ov = pygame.Surface((W, UI_Y), pygame.SRCALPHA)
        ov.fill((6, 10, 46, int(150 * n)))
        screen.blit(ov, (0, 0))
        if n > 0.3:
            for x, y, ph, sp in self.amb[:26]:
                if y * 0.6 < 200:
                    c = int(255 * n * (0.5 + 0.5 * math.sin(self.anim * sp * 2 + ph)))
                    pygame.draw.rect(screen, (c, c, min(255, c + 30)), (int(x), int(y * 0.6), 2, 2))
            moon = pygame.Surface((120, 120), pygame.SRCALPHA)
            pygame.draw.circle(moon, (240, 240, 214, int(60 * n)), (60, 60), 56)
            pygame.draw.circle(moon, (240, 240, 214, int(230 * n)), (60, 60), 24)
            pygame.draw.circle(moon, (200, 200, 180, int(160 * n)), (52, 54), 5)
            pygame.draw.circle(moon, (200, 200, 180, int(160 * n)), (68, 66), 4)
            screen.blit(moon, (820, 20))

    def draw_play(self):
        self.draw_world_bg()
        self.draw_bases()
        for u in sorted(self.cats + self.enemies, key=lambda u: u.y):
            u.draw(self)
        for s in self.shots:
            t = s["t"] / s["dur"]
            x = s["x0"] + (s["x1"] - s["x0"]) * t
            y = s["y0"] + (s["y1"] - s["y0"]) * t - math.sin(t * math.pi) * 18
            screen.blit(s["img"], s["img"].get_rect(center=(x, y)))
        for dd in self.dying:
            im = pygame.transform.rotate(dd["img"], dd["rot"])
            im.set_alpha(max(0, int(255 * (1 - dd["t"] / 0.75))))
            screen.blit(im, im.get_rect(center=(dd["x"], dd["y"])))
        for f in self.fx:
            frs = IMG[f["name"]]
            im = frs[min(int(f["t"] * f["fps"]), len(frs) - 1)]
            if f["flip"]:
                im = pygame.transform.flip(im, True, False)
            screen.blit(im, im.get_rect(center=(f["x"], f["y"])))
        screen.blit(IMG[self.stage["bg"] + "_fg"], (0, 0))
        self.draw_night()
        for m in self.haz:
            k = m["kind"]
            col = {"lava": (255, 150, 60), "lightning": (214, 226, 255), "sting": (232, 70, 56),
                   "rock": (190, 164, 130), "ice": (150, 210, 255)}[k]
            pulse = 0.5 + 0.5 * math.sin(self.anim * 14)
            w_ = 110 - int(34 * (1 - m["t"] / m["t0"]))
            pygame.draw.ellipse(screen, col, (m["x"] - w_ // 2, GROUND + 4, w_, 24), 2 if pulse > 0.4 else 3)
            txt("!", m["x"], GROUND - 22 - int(6 * pulse), FONT_M, col, center=True)
        for p in self.parts:
            a = max(0, min(1, p[4] / 0.6))
            sf = part_img(p[6], max(1, int(p[5] * a)), int(220 * a))
            screen.blit(sf, (p[0] - 7, p[1] - 7))
        for f in self.floats:
            col = f[4] if len(f) > 4 else C_GOLD
            txt(f[3], f[0], f[1], FONT if (len(f) <= 4 or f[5]) else FONT_S, col, center=True)
        if self.cannon_vis > 0:
            t = 1 - self.cannon_vis / 0.8
            front = -80 + (W + 340) * t
            screen.blit(cannon_band(), (front - 300, 0))
            for ox, y, sc in self.pollen:
                x = front - ox
                if 0 <= x <= W:
                    screen.blit(pollen_img(sc), (x, y))
        if self.flash > 0 and self.sv["opts"].get("flashes", True):
            fl = pygame.Surface((W, UI_Y), pygame.SRCALPHA)
            fl.fill((255, 255, 255, int(190 * self.flash / 0.3)))
            screen.blit(fl, (0, 0))
        if self.banner[1] > 0:
            a_ = min(1.0, self.banner[1] / 0.8)
            txt(self.banner[0], W // 2, 96, FONT_B if len(self.banner[0]) < 22 else FONT_M,
                (255, int(120 + 100 * a_), int(100 + 90 * a_)), center=True)
        tt = self.tutorial_text()
        if tt:
            box = pygame.Rect(W // 2 - 280, 66, 560, 36)
            pygame.draw.rect(screen, C_BORDER, box.inflate(4, 4))
            pygame.draw.rect(screen, (60, 80, 70), box)
            txt(tt, box.centerx, box.centery, FONT_S, C_TXT, center=True, shadow=False)
        self.draw_battle_ui()

    def draw_continue(self):
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((20, 0, 0, 190))
        screen.blit(veil, (0, 0))
        txt("HAS CAIGUT!", W // 2, 120, FONT_B, (240, 90, 70), center=True)
        txt("Vols continuar? Els enemics retrocediran i tindràs el moneder ple.", W // 2, 176, FONT, C_TXT, center=True)
        txt("Continuacions restants: %d" % (CONT_MAX - self.continues), W // 2, 204, FONT_S, (250, 220, 130), center=True)
        ok = self.sv["pollen"] >= CONT_COST
        self.ui_button(pygame.Rect(W // 2 - 190, 250, 380, 58), "Continua  (%d pol·len)" % CONT_COST, self.accept_continue, ok, FONT_M)
        self.ui_button(pygame.Rect(W // 2 - 190, 322, 380, 50), "Abandona", self.decline_continue, True, FONT_M)
        txt("Tens %d pol·len" % self.sv["pollen"], W // 2, 396, FONT, C_GOLD, center=True)

    def draw_dialogue(self):
        d = self.dlg
        self._bg(d.get("bg", "bg_meadow"))
        self._veil(0.45, (10, 8, 6))
        a = self.anim
        self._glow(190, 330, 150, (255, 214, 90), 60 + 20 * math.sin(a * 2))
        self._walker("honey", 190, 400 + math.sin(a * 3) * 5, 250, 180, rate=12)
        panel = pygame.Rect(340, 250, 620, 200)
        pygame.draw.rect(screen, C_BORDER, panel.inflate(8, 8), border_radius=14)
        pygame.draw.rect(screen, (252, 246, 228), panel, border_radius=12)
        txt(PROTA, panel.x + 20, panel.y + 12, FONT_M, (150, 90, 20), shadow=False)
        line = d["lines"][min(d["i"], len(d["lines"]) - 1)]
        n = len(line) if d.get("full") else int(d["t"] * 30)
        left = n
        for i, ln in enumerate(wrap_text(line, FONT_M, panel.w - 44)[:4]):
            part = ln[:max(0, left)]
            left -= len(ln) + 1
            if part:
                txt(part, panel.x + 20, panel.y + 52 + i * 30, FONT_M, (50, 34, 20), shadow=False)
        done = n >= len(line)
        if done and int(a * 2) % 2 == 0:
            txt("Clica per continuar  >", panel.right - 18, panel.bottom - 24, FONT_S, (150, 90, 20), right=True, shadow=False)
        self.ui_button(pygame.Rect(W - 140, 16, 118, 34), "Salta >>", self.dlg_skip_all, True, FONT_S)

    def dlg_skip_all(self):
        self.dlg["i"] = len(self.dlg["lines"])
        self.dlg_finish()

    def draw_pause(self):
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 170))
        screen.blit(veil, (0, 0))
        txt("PAUSA", W // 2, 130, FONT_B, C_GOLD, center=True)
        self.ui_button(pygame.Rect(W // 2 - 160, 190, 320, 54), "Continua", self.resume, True, FONT_M)
        self.ui_button(pygame.Rect(W // 2 - 160, 256, 320, 54), "Velocitat: x%d" % self.speed, self.toggle_speed, True,
                       FONT_M)
        self.ui_button(pygame.Rect(W // 2 - 160, 322, 320, 54), "Abandona el nivell", self.abandon, True, FONT_M)
        txt("ESC o P per continuar", W // 2, 406, FONT_S, C_TXT, center=True)

    # =================================================== MENÚS
    def build_logo(self):
        def layered(text, size, top, bot, ow):
            font = pygame.font.SysFont(PF, size, bold=True)
            base = font.render(text, True, (255, 255, 255))
            w, h = base.get_size()
            surf = pygame.Surface((w + 2 * ow + 12, h + 2 * ow + 12), pygame.SRCALPHA)
            ox, oy = ow + 4, ow + 4
            sh = font.render(text, True, (22, 12, 4))
            surf.blit(sh, (ox + 6, oy + 7))
            ol = font.render(text, True, (52, 28, 8))
            for dx in range(-ow, ow + 1):
                for dy in range(-ow, ow + 1):
                    if dx * dx + dy * dy <= ow * ow + 1:
                        surf.blit(ol, (ox + dx, oy + dy))
            fill = font.render(text, True, (255, 255, 255))
            grad = pygame.Surface((w, h))
            for yy in range(h):
                t = yy / max(1, h - 1)
                col = _mix(top, bot, t)
                pygame.draw.line(grad, col, (0, yy), (w, yy))
            fill.blit(grad, (0, 0), special_flags=pygame.BLEND_RGBA_MULT)
            surf.blit(fill, (ox, oy))
            shine = font.render(text, True, (255, 244, 200))
            clip = pygame.Surface((w, h // 3), pygame.SRCALPHA)
            clip.blit(shine, (0, 0))
            clip.set_alpha(110)
            surf.blit(clip, (ox, oy))
            return surf
        the = layered("The", 54, (255, 236, 160), (232, 168, 40), 3)
        bb = layered("BattleBees", 104, (255, 232, 110), (230, 130, 20), 5)
        w = max(the.get_width(), bb.get_width()) + 20
        logo = pygame.Surface((w, the.get_height() + bb.get_height() - 18), pygame.SRCALPHA)
        logo.blit(the, (30, 0))
        logo.blit(bb, ((w - bb.get_width()) // 2, the.get_height() - 22))
        return logo

    def draw_title(self):
        st = self.stage
        self.stage = STAGES[0]
        self.draw_world_bg()
        self.stage = st
        keys = ["honey", "bumble", "carpenter", "sweat", "orchid", "leafcutter"]
        for i, k in enumerate(keys):
            x = ((self.anim * (46 + i * 9) + i * 190) % (W + 200)) - 100
            y = 90 + (i * 61) % 270 + math.sin(self.anim * 2 + i) * 10
            im = fit(anim_img(IMG["ally_" + k], self.anim + i, 14), 70, 50)
            screen.blit(im, im.get_rect(center=(x, y)))
        if self.logo is None:
            self.logo = self.build_logo()
        glow = pygame.Surface((760, 250), pygame.SRCALPHA)
        pygame.draw.ellipse(glow, (255, 214, 90, 46), (0, 0, 760, 250))
        screen.blit(glow, (W // 2 - 380, 20))
        screen.blit(self.logo, self.logo.get_rect(center=(W // 2, 128 + math.sin(self.anim * 1.6) * 4)))
        self.ui_button(pygame.Rect(W // 2 - 150, 262, 300, 66), "JUGAR", lambda: self.go("base"), True, FONT_B)
        self.ui_button(pygame.Rect(W // 2 - 150, 344, 300, 54), "SORTIR", self.quit_game, True, FONT_M)
        self.ui_button(pygame.Rect(W // 2 - 150, 410, 146, 40), "La història", lambda: self.start_intro(True, "title"), True, FONT_S)
        self.ui_button(pygame.Rect(W // 2 + 4, 410, 146, 40), "El tutorial", lambda: self.start_tutorial(True, "title"), True, FONT_S)
        self.icon_button(pygame.Rect(W - 72, H - 72, 58, 58), lambda x, y: draw_gear(x, y, 20, C_DARK),
                         lambda: self.go("options"))
        self.icon_button(pygame.Rect(14, H - 72, 58, 58), lambda x, y: draw_chart(x, y, 15, C_DARK),
                         lambda: self.go("stats"))
        self.icon_button(pygame.Rect(W // 2 - 29, H - 72, 58, 58), lambda x, y: txt("?", x, y, FONT_M, C_DARK, center=True, shadow=False),
                         lambda: self.go("help"))
        if self.toast[1] > 0:
            txt(self.toast[0], W // 2, H - 24, FONT, (250, 236, 180), center=True)

    def draw_base(self):
        self.chrome("Base del Rusc", back=True, theme="base", back_to="title")
        for i, (label, st) in enumerate((("Comença!!", "stages"), ("Millora", "upgrade"), ("Equipa", "equip"), ("Rusc", "hive"))):
            self.ui_button(pygame.Rect(24, 60 + i * 60, 350, 52), label, lambda s=st: self.go(s), font=FONT_M)
        tray = pygame.Rect(24, 306, 360, 146)
        pygame.draw.rect(screen, C_BORDER, tray.inflate(4, 4))
        pygame.draw.rect(screen, C_WOOD, tray)
        pygame.draw.rect(screen, C_WOOD_L, (tray.x, tray.y, tray.w, 3))
        # missions
        r = pygame.Rect(32, 316, 82, 126)
        self.card(r)
        pygame.draw.rect(screen, (214, 204, 170), (r.x + 22, r.y + 14, 38, 48))
        pygame.draw.rect(screen, C_BORDER, (r.x + 22, r.y + 14, 38, 48), 2)
        for k in range(4):
            pygame.draw.rect(screen, (150, 70, 60), (r.x + 27, r.y + 23 + k * 10, 5, 4))
            pygame.draw.rect(screen, (90, 84, 76), (r.x + 36, r.y + 24 + k * 10, 18, 3))
        txt("Missions", r.centerx, r.bottom - 22, FONT_S, C_TXT, center=True)
        self.btn(r, lambda: self.go("missions"))
        n = self.claimable() + self.daily_claimable()
        if n:
            pygame.draw.circle(screen, C_RED, (r.right - 8, r.y + 10), 12)
            txt(str(n), r.right - 8, r.y + 10, FONT_S, (255, 255, 255), center=True, shadow=False)
        for i, cap in enumerate(CAPSULES):
            r = pygame.Rect(120 + i * 86, 316, 82, 126)
            self.card(r, "rare" if i else "common")
            draw_amber(r.centerx, r.y + 50, 26, cap["top"])
            cur, cost = cap["cost"]
            txt("Càpsula" if i == 0 else "Reial", r.centerx, r.bottom - 36, FONT_S, C_TXT, center=True)
            txt(f"{cost} {'mel' if cur == 'mel' else 'pol'}", r.centerx, r.bottom - 16, FONT_S, C_GOLD, center=True)
            self.btn(r, lambda: self.go("capsules"))
        r = pygame.Rect(292, 316, 82, 126)
        self.card(r)
        draw_stall(r.centerx, r.y + 50, 26)
        txt("Botiga", r.centerx, r.bottom - 22, FONT_S, C_TXT, center=True)
        self.btn(r, lambda: self.go("shop"))
        ev = current_event()
        txt("Esdeveniment: " + ev["name"] + " (" + ev["desc"] + ")", 560, 52, FONT_S, (250, 220, 150))
        bub = pygame.Rect(560, 70, 400, 150)
        pygame.draw.rect(screen, C_BORDER, bub.inflate(6, 6))
        pygame.draw.rect(screen, (66, 80, 76), bub)
        pygame.draw.rect(screen, (150, 170, 160), bub, 2)
        pygame.draw.polygon(screen, (66, 80, 76), [(700, 220), (760, 220), (750, 262)])
        pygame.draw.lines(screen, (150, 170, 160), False, [(700, 220), (750, 262), (760, 220)], 2)
        for i, line in enumerate(TIPS[self.tip]):
            txt(line, bub.centerx, bub.y + 34 + i * 34, FONT, C_TXT, center=True)
        key = "queen" if "queen" in self.sv["owned"] else "honey"
        big = fit(anim_img(IMG["ally_" + key], self.anim, 6), 420, 230)
        screen.blit(big, big.get_rect(center=(790, 380 + math.sin(self.anim * 2) * 6)))
        bx = 92
        for fn, act, bd in ((lambda x, y: draw_book(x, y, 13, C_DARK), lambda: self.go("bestiary"), 0),
                            (lambda x, y: draw_gift(x, y, 12), self.claim_gift, 1 if self.gift_ready() else 0)):
            self.icon_button(pygame.Rect(bx, H - 42, 50, 36), fn, act, bd)
            bx += 58

    def draw_stages(self):
        self.chrome("Comença: tria nivell", theme="stages")
        unlocked = min(self.sv["progress"], len(STAGES) - 1)
        pg_ = self.page_ctl("spage", (len(STAGES) + 5) // 6)
        for j, s in enumerate(STAGES[pg_ * 6:(pg_ + 1) * 6]):
            i = pg_ * 6 + j
            col, row = j % 2, j // 2
            r = pygame.Rect(20 + col * 490, 56 + row * 100, 470, 92)
            ok = i <= unlocked
            cleared = self.sv["progress"] > i
            self.ui_button(r, "", (lambda i=i: self.begin_level(i)), ok)
            fcol = C_DARK if ok else (126, 114, 100)
            if ok:
                bi = IMG[s["base"]]
                bi = bi[0] if isinstance(bi, list) else bi
                bi = fit(bi, 100, 70)
                screen.blit(bi, bi.get_rect(center=(r.x + 56, r.centery)))
            txt(s["name"] if ok else "Bloquejat", r.x + 120, r.y + 8, FONT_M if len(s["name"]) <= 22 else FONT, fcol,
                shadow=False)
            if ok:
                st_n = self.sv["stars"].get(str(i), 0)
                for k in range(3):
                    draw_star(r.x + 132 + k * 22, r.y + 48, 8, k < st_n)
                txt(f"Nivell recomanat: {s['rec']}", r.x + 120, r.y + 62, FONT_S, fcol, shadow=False)
                mel, pol = STAGE_REWARD[i]
                sub = "SUPERAT" if cleared else f"1a vegada: {pol} pol·len"
                txt(f"{sub}  +{mel} mel", r.x + 120, r.y + 77, FONT_S, fcol, shadow=False)
                for q, eid in enumerate(stage_enemy_ids(s)[:4]):
                    ic = fit(IMG["enemy_" + ENEMIES[eid].get("sprite", eid)][0], 36, 36)
                    screen.blit(ic, ic.get_rect(center=(r.x + 330 + q * 40, r.y + 56)))
        txt("Equip actual:", 20, 404, FONT, C_TXT)
        for i, k in enumerate(self.sv["deck"]):
            rr = pygame.Rect(20 + i * 86, 426, 80, 56)
            self.card(rr, BEE_BY_KEY[k]["rarity"])
            ic = fit(IMG["beeicon_" + k], 70, 40)
            screen.blit(ic, ic.get_rect(center=rr.center))
        sr = pygame.Rect(884, 410, 106, 50)
        okS = self.sv["progress"] >= 3
        self.ui_button(sr, "Supervivència" if okS else "Bloquejat", self.begin_survival, okS, FONT_S)
        best = int(self.sv.get("surv_best", 0))
        txt("Rècord %d:%02d" % (best // 60, best % 60) if okS else "Supera 3 nivells", sr.centerx, sr.bottom + 12, FONT_S, C_TXT, center=True)
        txt("Consumibles:", 540, 404, FONT, C_TXT)
        for i, it in enumerate(SHOP_ITEMS):
            rr = pygame.Rect(540 + i * 112, 426, 106, 56)
            have = self.sv["items"].get(it["id"], 0)
            on = self.sv["armed"].get(it["id"], False) and have > 0
            self.card(rr, hl=on)
            txt(it["name"][:13], rr.centerx, rr.y + 16, FONT_S, C_GOLD if on else C_TXT, center=True)
            txt(("ACTIU  " if on else "") + f"x{have}", rr.centerx, rr.y + 38, FONT_S, C_TXT, center=True)
            self.btn(rr, (lambda k=it["id"]: self.toggle_armed(k)), have > 0)

    def bee_stats(self, key, lv):
        b = BEE_BY_KEY[key]
        m = lvl_mult(lv) * (EVO_MULT if self.sv["evo"].get(key) else 1.0)
        return int(b["hp"] * m), int(b["atk"] * m)

    def owned_bees(self):
        return [b for b in BEE_UNITS if b["key"] in self.sv["owned"]]

    def draw_upgrade(self):
        self.chrome("Taller: millora les abelles", theme="upgrade")
        own = self.owned_bees()
        pg_ = self.page_ctl("upage", (len(own) + 11) // 12)
        for idx, b in enumerate(own[pg_ * 12:(pg_ + 1) * 12]):
            k = b["key"]
            col, row = idx % 4, idx // 4
            r = pygame.Rect(12 + col * 247, 58 + row * 143, 237, 136)
            self.card(r, b["rarity"])
            lv = self.sv["owned"][k]
            ic = fit(IMG["beeicon_" + k], 96, 58)
            screen.blit(ic, ic.get_rect(center=(r.x + 54, r.y + 42)))
            txt(b["name"], r.x + 8, r.y + 6, FONT_S, C_TXT)
            txt(f"Nv {lv}/{MAX_LV}", r.x + 110, r.y + 26, FONT, C_GOLD)
            txt(b["role"] + (" - antiaèria" if b["air"] else ""), r.x + 8, r.y + 70, FONT_S, C_GOLD)
            txt(STYLE_NAME[b["style"]][:24], r.x + 8, r.y + 84, FONT_S, (176, 166, 140))
            hp, atk = self.bee_stats(k, lv)
            txt(f"PV  {hp}", r.x + 110, r.y + 46, FONT_S, C_TXT)
            txt(f"ATQ {atk}", r.x + 110, r.y + 58, FONT_S, C_TXT)
            if lv >= MAX_LV and self.sv["evo"].get(k):
                self.ui_button(pygame.Rect(r.x + 8, r.y + 100, r.w - 16, 28), "EVOLUCIONADA", lambda: None, False, FONT_S)
                draw_star(r.right - 14, r.y + 14, 8, True)
            elif lv >= MAX_LV:
                self.ui_button(pygame.Rect(r.x + 8, r.y + 100, r.w - 16, 28), f"Evoluciona {EVO_MEL} mel+{EVO_POLLEN} pol",
                               (lambda k=k: self.evolve(k)), self.sv["mel"] >= EVO_MEL and self.sv["pollen"] >= EVO_POLLEN, FONT_S)
            else:
                c = self.upg_cost(k)
                self.ui_button(pygame.Rect(r.x + 8, r.y + 100, r.w - 16, 28), f"Millora   {c} mel",
                               (lambda k=k: self.upgrade_bee(k)), self.sv["mel"] >= c, FONT)

    def draw_equip(self):
        self.chrome("Equip de batalla", theme="equip")
        own = self.owned_bees()
        pg_ = self.page_ctl("epage", (len(own) + 11) // 12)
        deck = self.sv["deck"]
        n = self.deck_size
        txt(f"Abelles que lluitaran ({len(deck)}/{n})", 24, 54, FONT, C_TXT)
        for i in range(n):
            cx = W // 2 + (i - (n - 1) / 2) * 160
            cy = 120
            pts = [(cx + 56 * math.cos(math.radians(60 * k - 30)), cy + 56 * math.sin(math.radians(60 * k - 30))) for k in range(6)]
            if i < len(deck):
                k = deck[i]
                pygame.draw.polygon(screen, C_CARD, pts)
                pygame.draw.polygon(screen, RAR_COL[BEE_BY_KEY[k]["rarity"]], pts, 3)
                ic = fit(IMG["beeicon_" + k], 84, 52)
                screen.blit(ic, ic.get_rect(center=(cx, cy - 4)))
                rar_icon(int(cx), int(cy - 44), BEE_BY_KEY[k]["rarity"], 6)
                txt(f"Nv{self.sv['owned'][k]} {BEE_BY_KEY[k]['name'][:14]}", cx, cy + 68, FONT_S, C_TXT, center=True)
                self.btn(pygame.Rect(int(cx - 52), int(cy - 52), 104, 104), lambda k=k: self.toggle_deck(k))
            else:
                pygame.draw.polygon(screen, (40, 66, 70), pts)
                pygame.draw.polygon(screen, (80, 120, 120), pts, 2)
                txt("buit", cx, cy, FONT_S, (110, 140, 140), center=True)
        for i in range(3):
            self.ui_button(pygame.Rect(280 + i * 190, H - 42, 80, 36), f"Desa {i + 1}", (lambda i=i: self.save_preset(i)), True, FONT_S)
            self.ui_button(pygame.Rect(364 + i * 190, H - 42, 100, 36), f"Carrega {i + 1}", (lambda i=i: self.load_preset(i)),
                           bool(self.sv["presets"][i]), FONT_S)
        txt("Les teves abelles (clica per afegir / treure)", 24, 196, FONT, C_TXT)
        roles = {BEE_BY_KEY[k]["role"] for k in deck}
        txt("Equip equilibrat: +8% de vida" if len(roles) >= 3 else "Combina 3 rols diferents: +8% de vida",
            W - 20, 198, FONT_S, C_GOLD if len(roles) >= 3 else (170, 160, 140), right=True)
        mp = pygame.mouse.get_pos()
        info = None
        for idx, b in enumerate(own[pg_ * 12:(pg_ + 1) * 12]):
            k = b["key"]
            col, row = idx % 6, idx // 6
            r = pygame.Rect(20 + col * 160, 222 + row * 124, 150, 114)
            owned = True
            self.card(r, b["rarity"], hl=(k in deck))
            if owned:
                ic = fit(IMG["beeicon_" + k], 130, 56)
                screen.blit(ic, ic.get_rect(center=(r.centerx, r.y + 40)))
                txt(b["name"], r.centerx, r.y + 82, FONT_S, C_TXT, center=True)
                txt(f"Nv {self.sv['owned'][k]}" + ("   EQUIPADA" if k in deck else ""), r.centerx, r.y + 98, FONT_S,
                    C_GOLD, center=True)
                self.btn(r, lambda k=k: self.toggle_deck(k))
                if r.collidepoint(mp):
                    info = k
            else:
                sil = fit(IMG["sil_" + k], 130, 56)
                screen.blit(sil, sil.get_rect(center=(r.centerx, r.y + 40)))
                txt("???", r.centerx, r.y + 90, FONT, (120, 110, 96), center=True)
        if info:
            b = BEE_BY_KEY[info]
            lv = self.sv["owned"][info]
            hp, atk = self.bee_stats(info, lv)
            txt(f"{b['name']} [{RAR_NAME[b['rarity']]}] - {b['role']}: {ROLE_INFO[b['role']]}  Cost {b['cost']}  PV {hp}  ATQ {atk}",
                20, 464, FONT_S, C_GOLD)
            txt("Atac: " + STYLE_NAME[b["style"]] + "  -  " + b["desc"], 20, 480, FONT_S, C_TXT)

    def draw_missions(self):
        self.chrome("Missions", theme="missions")
        tabs = [("Diàries", "daily", self.daily_claimable()), ("Setmanals", "weekly", self.weekly_claimable()),
                ("Històriques", "hist", self.claimable())]
        if self.sv["captured"]:
            tabs.append(("Rescat", "rescue", len(self.sv["captured"])))
        elif self.mtab == "rescue":
            self.mtab = "daily"
        for i, (lab, key, nn) in enumerate(tabs):
            r = pygame.Rect(20 + i * 180, 56, 172, 34)
            self.ui_button(r, lab + (f" ({nn})" if nn else ""), (lambda k=key: setattr(self, "mtab", k)), self.mtab != key, FONT)
        if self.mtab == "daily":
            dm = self.sv["dm"]
            def drank(mid):
                m_ = DAILY_POOL_BY_ID[mid]
                return 2 if mid in dm["claimed"] else (0 if self.daily_prog(m_) >= m_["val"] else 1)
            for i, mid in enumerate(sorted(dm["ids"], key=drank)):
                m = DAILY_POOL_BY_ID[mid]
                r = pygame.Rect(16, 104 + i * 62, 968, 54)
                self.card(r, hl=mid not in dm["claimed"] and self.daily_prog(m) >= m["val"])
                claimed = mid in dm["claimed"]
                txt(m["text"], r.x + 12, r.y + 17, FONT, C_TXT if not claimed else (130, 124, 110))
                txt(f"{self.daily_prog(m)}/{m['val']}", r.x + 340, r.y + 17, FONT, C_GOLD)
                rew = f"{m['mel']} mel" if m.get("mel") else f"{m['pollen']} pol·len"
                txt("Premi: " + rew, r.x + 450, r.y + 19, FONT_S, C_TXT)
                br = pygame.Rect(r.right - 124, r.y + 10, 112, 34)
                if claimed:
                    self.ui_button(br, "FET", lambda: None, False, FONT)
                elif self.daily_prog(m) >= m["val"]:
                    self.ui_button(br, "COBRA", (lambda mid=mid: self.claim_daily(mid)), True, FONT)
                else:
                    self.ui_button(br, "...", lambda: None, False, FONT)
            r = pygame.Rect(16, 304, 968, 78)
            self.card(r)
            draw_gift(r.x + 46, r.y + 40, 22)
            txt("Regal diari gratuït", r.x + 90, r.y + 14, FONT_M, C_TXT)
            txt(f"Ratxa: {self.sv.get('streak', 0)} dia(es). Com més dies seguits, més gran és el premi.", r.x + 90, r.y + 48, FONT_S, C_TXT)
            ready = self.gift_ready()
            self.ui_button(pygame.Rect(r.right - 190, r.y + 18, 176, 42), "RECULL" if ready else "JA RECOLLIT", self.claim_gift, ready, FONT)
            txt("Les missions diàries es renoven cada dia.", W // 2, 420, FONT_S, C_TXT, center=True)
            return
        if self.mtab == "rescue":
            txt("Derrota enemics a les batalles per rescatar-les", 560, 62, FONT_S, C_TXT)
            for i, (k, prog) in enumerate(list(self.sv["captured"].items())[:6]):
                b = BEE_BY_KEY[k]
                need = RESCUE_NEED[b["rarity"]]
                r = pygame.Rect(16, 104 + i * 62, 968, 54)
                self.card(r, b["rarity"])
                sl = fit(IMG["sil_" + k], 70, 44)
                screen.blit(sl, sl.get_rect(center=(r.x + 46, r.centery)))
                txt(b["name"], r.x + 94, r.y + 6, FONT, C_TXT)
                pygame.draw.rect(screen, (40, 14, 10), (r.x + 94, r.y + 32, 520, 14))
                pygame.draw.rect(screen, (170, 90, 220), (r.x + 94, r.y + 32, int(520 * min(1.0, prog / need)), 14))
                txt(f"{min(prog, need)}/{need} enemics derrotats", r.x + 640, r.y + 16, FONT, C_GOLD)
            return
        if self.mtab == "weekly":
            wk = self.sv["wk"]
            txt("Es renoven cada setmana", 440, 62, FONT_S, C_TXT)
            def wrank(mid):
                m_ = WEEKLY_BY_ID[mid]
                return 2 if mid in wk["claimed"] else (0 if self.weekly_prog(m_) >= m_["val"] else 1)
            for i, mid in enumerate(sorted(wk["ids"], key=wrank)):
                m = WEEKLY_BY_ID[mid]
                r = pygame.Rect(16, 104 + i * 62, 968, 54)
                done = self.weekly_prog(m) >= m["val"]
                self.card(r, hl=mid not in wk["claimed"] and done)
                claimed = mid in wk["claimed"]
                txt(m["text"], r.x + 12, r.y + 17, FONT, C_TXT if not claimed else (130, 124, 110))
                txt(f"{self.weekly_prog(m)}/{m['val']}", r.x + 340, r.y + 17, FONT, C_GOLD)
                txt("Premi: " + (f"{m['mel']} mel" if m.get("mel") else f"{m['pollen']} pol·len"), r.x + 450, r.y + 19, FONT_S, C_TXT)
                br = pygame.Rect(r.right - 124, r.y + 10, 112, 34)
                if claimed:
                    self.ui_button(br, "FET", lambda: None, False, FONT)
                elif done:
                    self.ui_button(br, "COBRA", (lambda mid=mid: self.claim_weekly(mid)), True, FONT)
                else:
                    self.ui_button(br, "...", lambda: None, False, FONT)
            ev = current_event()
            r = pygame.Rect(16, 304, 968, 78)
            self.card(r, "rare")
            txt("Esdeveniment d'aquesta setmana", r.x + 14, r.y + 10, FONT, C_GOLD)
            txt(ev["name"] + ": " + ev["desc"], r.x + 14, r.y + 44, FONT, C_TXT)
            return
        pages = (len(MISSIONS) + MISS_PER_PAGE - 1) // MISS_PER_PAGE
        self.mpage = max(0, min(self.mpage, pages - 1))
        def hrank(m_):
            if m_["id"] in self.sv["claimed"]:
                return 2
            return 0 if self.mission_done(m_) else 1
        ordered = sorted(MISSIONS, key=hrank)          # sorted és estable: es manté l'ordre original dins de cada grup
        chunk = ordered[self.mpage * MISS_PER_PAGE:(self.mpage + 1) * MISS_PER_PAGE]
        for i, m in enumerate(chunk):
            r = pygame.Rect(16, 98 + i * 54, 968, 48)
            self.card(r)
            done = self.mission_done(m)
            claimed = m["id"] in self.sv["claimed"]
            txt(m["text"], r.x + 12, r.y + 14, FONT, C_TXT if not claimed else (130, 124, 110))
            txt(f"{self.mission_progress(m)}/{m['val']}", r.x + 340, r.y + 14, FONT, C_GOLD)
            rew = []
            if m.get("bee"):
                rew.append(BEE_BY_KEY[m["bee"]]["name"])
            if m.get("mel"):
                rew.append(f"{m['mel']} mel")
            if m.get("pollen"):
                rew.append(f"{m['pollen']} pol·len")
            txt("Premi: " + " + ".join(rew), r.x + 440, r.y + 16, FONT_S, C_TXT)
            br = pygame.Rect(r.right - 120, r.y + 8, 112, 32)
            if claimed:
                self.ui_button(br, "FET", lambda: None, False, FONT)
            elif done:
                self.ui_button(br, "COBRA", (lambda m=m: self.claim(m)), True, FONT)
            else:
                self.ui_button(br, "...", lambda: None, False, FONT)
        self.ui_button(pygame.Rect(W // 2 - 150, H - 42, 60, 36), "<", lambda: self.set_mpage(-1), self.mpage > 0, FONT_B)
        txt(f"Pàgina {self.mpage + 1}/{pages}", W // 2, H - 24, FONT, C_TXT, center=True)
        self.ui_button(pygame.Rect(W // 2 + 90, H - 42, 60, 36), ">", lambda: self.set_mpage(1), self.mpage < pages - 1, FONT_B)

    def set_mpage(self, d):
        self.mpage += d

    # --- CÀPSULES
    def draw_capsules(self):
        self.chrome("Càpsules d'ambre", theme="capsules")
        for i, cap in enumerate(CAPSULES):
            r = pygame.Rect(70 + i * 450, 62, 410, 408)
            self.card(r, "rare" if i else "common")
            draw_amber(r.centerx, r.y + 112, 76, cap["top"], 0, (math.sin(self.anim * 2.4 + i) * 2, math.cos(self.anim * 3 + i) * 1.5),
                       0.6 + 0.4 * math.sin(self.anim * 2 + i))
            txt(cap["name"], r.centerx, r.y + 222, FONT_M, C_TXT, center=True)
            txt("Dins hi ha una abella...", r.centerx, r.y + 258, FONT_S, C_TXT, center=True)
            txt(f"Garantia llegendària: {self.sv['pity'][str(i)]}/{cap['pity']}", r.centerx, r.y + 292, FONT_S, C_GOLD, center=True)
            cur, cost = cap["cost"]
            have = self.sv[cur]
            unit = "mel" if cur == "mel" else "pol·len"
            self.ui_button(pygame.Rect(r.x + 24, r.bottom - 82, 172, 56), f"OBRE  {cost} {unit}",
                           (lambda i=i: self.open_capsules(i, 1)), have >= cost, FONT)
            self.ui_button(pygame.Rect(r.x + 208, r.bottom - 82, 178, 56), f"x10  {cost * 10} {unit}",
                           (lambda i=i: self.open_capsules(i, 10)), have >= cost * 10, FONT)

    def amber_scene(self, c):
        """Bola d'ambre que el fibló esquerda a cada clic. Torna True quan ja és trencada."""
        cap = CAPSULES[c["ci"]]
        cx, cy, r = W // 2, 250, 98
        bt = c.get("bt")
        if bt is None:
            hits, need, ht = c["hits"], c["need"], c["hit_t"]
            sh = (0, 0)
            if ht < 0.25:
                k = 1 - ht / 0.25
                sh = (random.uniform(-9, 9) * k, random.uniform(-6, 6) * k)
            cracks = 0 if hits == 0 else min(3, max(1, round(hits * 3 / need)))
            glow = (0.4 + 0.15 * hits) if need <= 3 else (0.5 + 0.25 * hits)
            draw_amber(cx, cy, r, cap["top"], cracks, sh, glow)
            if hits > 0 and ht < 0.4:
                if ht < 0.1:
                    x = cx + r + 170 - 100 * (ht / 0.1) ** 2
                else:
                    x = cx + r + 70 + 120 * min(1.0, (ht - 0.1) / 0.3)
                draw_stinger(int(x - 36), cy - 24 + ((hits - 1) % 3) * 24, 130)
            return False
        tt = bt
        if tt < 0.25:
            fl = pygame.Surface((W, H), pygame.SRCALPHA)
            fl.fill((255, 244, 210, int(220 * (1 - tt / 0.25))))
            screen.blit(fl, (0, 0))
        for ang, spd, size, rs in c["shards"]:
            if tt > 0.9:
                continue
            px = cx + math.cos(ang) * spd * tt
            py = cy + math.sin(ang) * spd * tt + 520 * tt * tt
            sz = size * (1 - tt / 0.9)
            a2 = tt * rs * 6
            pts = [(px + math.cos(a2 + k * 2.1) * sz, py + math.sin(a2 + k * 2.1) * sz) for k in range(3)]
            pygame.draw.polygon(screen, _mix(cap["top"], (255, 236, 170), (size % 7) / 10), pts)
            pygame.draw.polygon(screen, (70, 36, 8), pts, 1)
        return True

    def draw_reveal_card(self, key, res, label, action):
        b = BEE_BY_KEY[key]
        r = pygame.Rect(W // 2 - 190, 60, 380, 400)
        if b["rarity"] != "common":
            col = RAR_COL[b["rarity"]]
            pulse = 0.5 + 0.5 * math.sin(self.anim * 5)
            for k in range(4):
                rad = 260 + k * 28 + int(pulse * 12)
                gl = pygame.Surface((rad * 2, rad * 2), pygame.SRCALPHA)
                pygame.draw.circle(gl, col + (22 + (10 if b["rarity"] == "legend" else 0),), (rad, rad), rad)
                screen.blit(gl, (W // 2 - rad, 260 - rad))
        self.card(r, b["rarity"], hl=True)
        txt(RAR_NAME[b["rarity"]].upper(), r.centerx, r.y + 26, FONT_M, RAR_COL[b["rarity"]], center=True)
        big = fit(anim_img(IMG["ally_" + b["key"]], self.anim, 6), 300, 170)
        screen.blit(big, big.get_rect(center=(r.centerx, r.y + 150)))
        txt(b["name"], r.centerx, r.y + 250, FONT_M, C_TXT, center=True)
        msg = {"new": "NOVA ABELLA!", "up": f"Ja la tenies: nivell {self.sv['owned'][b['key']]}",
               "max": "Nivell màxim: +150 mel"}[res]
        txt(msg, r.centerx, r.y + 292, FONT, C_GOLD, center=True)
        txt(b["role"] + " - " + STYLE_NAME[b["style"]], r.centerx, r.y + 322, FONT_S, C_GOLD, center=True)
        txt(b["desc"], r.centerx, r.y + 344, FONT_S, C_TXT, center=True)
        self.ui_button(pygame.Rect(r.x + 80, r.bottom - 52, r.w - 160, 40), label, action, True, FONT)

    def draw_capsule_open(self):
        c = self.cap
        screen.blit(self.hexbg("capsules"), (0, 0))
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((10, 8, 6, 190))
        screen.blit(veil, (0, 0))
        self.amber_scene(c)
        if c["bt"] is None:
            txt("Clica per picar la bola!", W // 2, 412, FONT_M, C_TXT, center=True)
            if c["hits"] >= 3 and c["need"] > 3:
                txt("Sembla que és especial...", W // 2, 444, FONT, (250, 220, 130), center=True)
        elif c["bt"] >= 0.25:
            self.draw_reveal_card(c["key"], c["res"], "Continua", lambda: self.go("capsules"))

    def draw_capsule_multi(self):
        c = self.cap
        screen.blit(self.hexbg("capsules"), (0, 0))
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((10, 8, 6, 190))
        screen.blit(veil, (0, 0))
        n = len(c["results"])
        if c["idx"] < n:
            it = c["it"]
            th = (0.12, 0.26, 0.40)
            c["hits"] = sum(1 for x in th if it >= x)
            c["need"] = 4
            c["hit_t"] = it - th[c["hits"] - 1] if c["hits"] else 9.9
            c["bt"] = it - 0.5 if it >= 0.5 else None
            self.amber_scene(c)
            txt("Càpsula %d/%d" % (c["idx"] + 1, n), W // 2, 30, FONT_M, C_GOLD, center=True)
            if it >= 0.75:
                key, res = c["results"][c["idx"]]
                self.draw_reveal_card(key, res, "Següent (%d/%d)" % (c["idx"] + 1, n) if c["idx"] + 1 < n else "Veure el resum", self.cap_next)
            self.ui_button(pygame.Rect(W - 150, 14, 130, 32), "Salta tot", self.cap_skip_all, True, FONT_S)
            return
        txt("Resum de l'obertura", W // 2, 30, FONT_M, C_GOLD, center=True)
        for i, (key, res) in enumerate(c["results"]):
            b = BEE_BY_KEY[key]
            r = pygame.Rect(40 + (i % 5) * 188, 62 + (i // 5) * 172, 176, 160)
            self.card(r, b["rarity"], hl=(res == "new"))
            ic = fit(IMG["beeicon_" + key], 140, 70)
            screen.blit(ic, ic.get_rect(center=(r.centerx, r.y + 56)))
            txt(b["name"][:20], r.centerx, r.y + 112, FONT_S, C_TXT, center=True)
            lab = {"new": "NOVA!", "up": "+1 nivell", "max": "+150 mel"}[res]
            txt(lab, r.centerx, r.y + 134, FONT_S, C_GOLD if res == "new" else (170, 160, 140), center=True)
        cnt = {"common": 0, "rare": 0, "legend": 0}
        for key, _res in c["results"]:
            cnt[BEE_BY_KEY[key]["rarity"]] += 1
        txt(f"Comunes: {cnt['common']}   Rares: {cnt['rare']}   Llegendàries: {cnt['legend']}", W // 2, 420, FONT,
            C_TXT, center=True)
        self.ui_button(pygame.Rect(W // 2 - 110, 454, 220, 44), "Continua", lambda: self.go("capsules"), True, FONT)

    # --- BESTIARI, ESTADÍSTIQUES, OPCIONS
    def draw_bestiary(self):
        self.chrome("Bestiari", theme="bestiary")
        for i, (lab, key) in enumerate((("Enemics", "enemies"), ("Abelles", "bees"))):
            self.ui_button(pygame.Rect(20 + i * 190, 54, 180, 34), lab, (lambda k=key: self.set_btab(k)), self.btab != key, FONT)
        if self.btab == "bees":
            items = [b["key"] for b in BEE_UNITS]
            txt(f"Col·leccionades: {len(self.sv['owned'])}/{len(BEE_UNITS)}", 420, 62, FONT, C_TXT)
        else:
            items = bestiary_order()
            seen_n = len([k for k in items if k in set(self.sv["seen"])])
            txt(f"Descoberts: {seen_n}/{len(items)}", 420, 62, FONT, C_TXT)
        seen = set(self.sv["seen"])
        pg_ = self.page_ctl("bpage", (len(items) + 11) // 12)
        for idx, key in enumerate(items[pg_ * 12:(pg_ + 1) * 12]):
            col, row = idx % 4, idx // 4
            r = pygame.Rect(12 + col * 247, 96 + row * 130, 237, 124)
            if self.btab == "bees":
                b = BEE_BY_KEY[key]
                owned = key in self.sv["owned"]
                self.card(r, b["rarity"] if owned else None)
                if owned:
                    lv = self.sv["owned"][key]
                    hp, atk = self.bee_stats(key, lv)
                    ic = fit(IMG["beeicon_" + key], 96, 52)
                    screen.blit(ic, ic.get_rect(center=(r.x + 54, r.y + 40)))
                    txt(b["name"][:26], r.x + 8, r.y + 5, FONT_S, C_TXT)
                    txt(f"Nv {lv}", r.x + 110, r.y + 24, FONT_S, C_GOLD)
                    txt(f"PV  {hp}", r.x + 110, r.y + 40, FONT_S, C_TXT)
                    txt(f"ATQ {atk}", r.x + 110, r.y + 56, FONT_S, C_TXT)
                    txt(b["role"] + (" / antiaèria" if b["air"] else ""), r.x + 8, r.y + 82, FONT_S, C_GOLD)
                    txt(STYLE_NAME[b["style"]][:28], r.x + 8, r.y + 100, FONT_S, (176, 166, 140))
                else:
                    sil = fit(IMG["sil_" + key], 96, 52)
                    screen.blit(sil, sil.get_rect(center=(r.x + 54, r.y + 40)))
                    txt("???", r.x + 110, r.y + 30, FONT_M, (120, 110, 96))
                    txt("Missió o càpsula", r.x + 8, r.y + 98, FONT_S, (130, 120, 104))
                continue
            e = ENEMIES[key]
            sk = e.get("sprite", key)
            self.card(r)
            if key in seen:
                ic = fit(IMG["enemy_" + sk][0], 96, 52)
                screen.blit(ic, ic.get_rect(center=(r.x + 54, r.y + 42)))
                txt(e["name"][:24], r.x + 8, r.y + 5, FONT_S, C_TXT)
                txt(f"PV  {e['hp']}", r.x + 110, r.y + 26, FONT_S, C_TXT)
                txt(f"ATQ {e['atk']}", r.x + 110, r.y + 42, FONT_S, C_TXT)
                txt(f"Rang {e['range']}", r.x + 110, r.y + 58, FONT_S, C_TXT)
                txt(STYLE_NAME[e["style"]][:28], r.x + 8, r.y + 84, FONT_S, (176, 166, 140))
                txt("Vola: només les tirades i antiaèries el toquen sencer" if e["hover"] >= 30 else ("Vola" if e["hover"] else "Terra"),
                    r.x + 8, r.y + 102, FONT_S, (150, 150, 130))
            else:
                sil = fit(IMG["esil_" + sk], 96, 52)
                screen.blit(sil, sil.get_rect(center=(r.x + 54, r.y + 42)))
                txt("???", r.x + 110, r.y + 36, FONT_M, (120, 110, 96))
                txt("Derrota'l per descobrir-lo", r.x + 8, r.y + 100, FONT_S, (130, 120, 104))

    def set_btab(self, key):
        self.btab = key
        self.bpage = 0

    def draw_stats(self):
        self.chrome("Estadístiques", theme="stats", back_to="title")
        st = self.sv["stats"]
        secs = int(st.get("time", 0))
        lines = [
            ("Temps de batalla", f"{secs // 3600}h {(secs % 3600) // 60:02d}m {secs % 60:02d}s"),
            ("Nivells superats", f"{min(self.sv['progress'], len(STAGES))}/{len(STAGES)}"),
            ("Victòries / derrotes", f"{st.get('wins', 0)} / {st.get('losses', 0)}"),
            ("Estrelles", f"{sum(self.sv['stars'].values())}/{len(STAGES) * 3}"),
            ("Enemics derrotats", f"{st['kills']}"),
            ("Abelles generades", f"{st['spawned']}"),
            ("Dany total de les abelles", f"{int(st.get('dmg', 0))}"),
            ("Trompa disparada", f"{st['cannons']} cops"),
            ("Millores fetes", f"{st['upgrades']}"),
            ("Càpsules obertes", f"{st['capsules']}"),
            ("Abelles col·leccionades", f"{len(self.sv['owned'])}/{len(BEE_UNITS)}"),
            ("Bestiari", f"{len(self.sv['seen'])}/{len(bestiary_order())}"),
            ("Rècord supervivència", "%d:%02d  (%d enemics)" % (int(self.sv.get("surv_best", 0)) // 60, int(self.sv.get("surv_best", 0)) % 60, self.sv.get("surv_kills", 0))),
            ("Abelles evolucionades", f"{sum(1 for v in self.sv['evo'].values() if v)}"),
            ("Missions cobrades", f"{len(self.sv['claimed'])}/{len(MISSIONS)}"),
        ]
        for i, (k, v) in enumerate(lines):
            y = 56 + i * 29
            txt(k, 60, y, FONT, C_TXT)
            txt(v, 520, y, FONT, C_GOLD, right=True)
        txt("Abelles preferides", 620, 66, FONT_M, C_TXT)
        fav = sorted(st.get("by_bee", {}).items(), key=lambda kv: -kv[1])[:5]
        for i, (k, n) in enumerate(fav):
            if k not in BEE_BY_KEY:
                continue
            y = 110 + i * 62
            ic = fit(IMG["beeicon_" + k], 80, 44)
            screen.blit(ic, ic.get_rect(center=(660, y + 22)))
            txt(BEE_BY_KEY[k]["name"][:22], 720, y + 6, FONT_S, C_TXT)
            txt(f"{n} generades", 720, y + 26, FONT_S, C_GOLD)

    def draw_options(self):
        self.chrome("Opcions", theme="options", back_to="title")
        o = self.sv["opts"]
        rows = [
            (f"Pantalla completa: {'SÍ' if o['fullscreen'] else 'NO'}   (F11)", lambda: self.toggle_opt("fullscreen")),
            (f"Efectes de so: {'SÍ' if o['sfx'] else 'NO'}", lambda: self.toggle_opt("sfx")),
            (f"Música: {'SÍ' if o['music'] else 'NO'}", lambda: self.toggle_opt("music")),
            (f"Flaixos de llum (llamps, jefe): {'SÍ' if o['flashes'] else 'NO'}", lambda: self.toggle_opt("flashes")),
            (f"Lletra gran: {'SÍ' if o['bigfont'] else 'NO'}", lambda: self.toggle_opt("bigfont")),
        ]
        for i, (label, act) in enumerate(rows):
            self.ui_button(pygame.Rect(240, 66 + i * 60, 520, 50), label, act, True, FONT)
        y = 66 + len(rows) * 60
        txt(f"Volum: {int(o['volume'] * 100)}%", 300, y + 14, FONT_M, C_TXT)
        self.ui_button(pygame.Rect(560, y + 4, 60, 44), "-", lambda: self.vol_step(-0.1), o["volume"] > 0.05, FONT_B)
        self.ui_button(pygame.Rect(630, y + 4, 60, 44), "+", lambda: self.vol_step(0.1), o["volume"] < 0.99, FONT_B)
        lab = "Segur? Clica de nou per esborrar" if self.confirm_reset else "Esborrar partida"
        self.ui_button(pygame.Rect(240, y + 64, 520, 50), lab, self.reset_save, True, FONT)
        if not AUDIO["ok"]:
            txt("(No s'ha pogut iniciar l'àudio en aquest equip)", W // 2, 452, FONT_S, (200, 160, 120), center=True)

    # --- BOTIGA (tot es paga amb pol·len)
    def shelf(self, y, h, label, icon=None):
        pygame.draw.rect(screen, C_BORDER, (8, y - 2, W - 16, h + 4))
        pygame.draw.rect(screen, (92, 64, 34), (10, y, W - 20, h))
        pygame.draw.rect(screen, (150, 108, 56), (10, y, W - 20, 3))
        pygame.draw.rect(screen, (60, 40, 20), (10, y + h - 5, W - 20, 5))
        tab = pygame.Rect(10, y, 124, h)
        pygame.draw.rect(screen, (66, 44, 22), tab)
        pygame.draw.rect(screen, (150, 108, 56), tab, 2)
        txt(label, tab.centerx, tab.centery + 22, FONT_S, C_GOLD, center=True)
        if icon:
            icon(tab.centerx, tab.centery - 14)

    def draw_shop(self):
        self.chrome("Botiga", theme="shop")
        self.shop_check()
        sh = self.sv["shop"]
        ph = self.sv["pollen"]
        # --- categoria 1: abelles
        y = 54
        self.shelf(y, 104, "ABELLES", lambda x, yy: draw_book(x, yy, 14))
        for i, of in enumerate((self.shop_offer(), self.shop_offer2())):
            r = pygame.Rect(142 + i * 424, y + 8, 414, 88)
            self.card(r, BEE_BY_KEY[of["key"]]["rarity"])
            b = BEE_BY_KEY[of["key"]]
            ic = fit(anim_img(IMG["ally_" + of["key"]], self.anim, 6), 100, 58)
            screen.blit(ic, ic.get_rect(center=(r.x + 58, r.y + 40)))
            txt(b["name"][:24], r.x + 116, r.y + 8, FONT_S, C_TXT)
            txt(("Abella nova" if of["kind"] == "new" else "+1 nivell") + f"  |  {b['role']}", r.x + 116, r.y + 28, FONT_S, C_GOLD)
            txt("Canvia en " + self.shop_timer(), r.x + 116, r.y + 48, FONT_S, (176, 166, 140))
            done = sh["bee_bought"] if i == 0 else sh["lvl_bought"]
            self.ui_button(pygame.Rect(r.right - 150, r.y + 44, 140, 38), "COMPRADA" if done else f"{of['cost']} pol·len",
                           (self.buy_offer if i == 0 else self.buy_offer2), (not done) and ph >= of["cost"], FONT_S)
        # --- categoria 2: mel
        y += 110
        self.shelf(y, 104, "MEL", lambda x, yy: screen.blit(IMG["icon_honey"], (x - 16, yy - 16)))
        for i, (pol, mel, lim) in enumerate(SHOP_MEL):
            r = pygame.Rect(142 + i * 282, y + 8, 274, 88)
            self.card(r)
            used = sh["mel"].get(str(i), 0)
            txt(f"{mel} mel", r.x + 12, r.y + 8, FONT_M, C_GOLD)
            txt(f"Avui: {used}/{lim}", r.x + 12, r.y + 40, FONT_S, (176, 166, 140))
            self.ui_button(pygame.Rect(r.x + 12, r.y + 54, r.w - 24, 28), f"{pol} pol·len", (lambda i=i: self.buy_mel(i)),
                           used < lim and ph >= pol, FONT_S)
        # --- categoria 3: consumibles
        y += 110
        self.shelf(y, 104, "CONSUMIBLES", lambda x, yy: draw_gift(x, yy, 13, (190, 110, 50)))
        for i, it in enumerate(SHOP_ITEMS):
            r = pygame.Rect(142 + i * 282, y + 8, 274, 88)
            self.card(r)
            txt(it["name"], r.x + 12, r.y + 6, FONT_S, C_GOLD)
            txt(it["desc"][:32], r.x + 12, r.y + 24, FONT_S, C_TXT)
            txt(f"Tens: {self.sv['items'].get(it['id'], 0)}", r.x + 12, r.y + 40, FONT_S, (176, 166, 140))
            self.ui_button(pygame.Rect(r.x + 12, r.y + 56, r.w - 24, 26), f"x{it['n']}  {it['cost']} pol·len",
                           (lambda k=it["id"]: self.buy_item(k)), ph >= it["cost"], FONT_S)
        # --- categoria 4: equip
        y += 110
        self.shelf(y, 104, "EQUIP", lambda x, yy: draw_gear(x, yy, 14))
        r = pygame.Rect(142, y + 8, 414, 88)
        self.card(r)
        txt("6a abella a la batalla", r.x + 12, r.y + 8, FONT, C_GOLD)
        txt("Porta una abella més a l'equip", r.x + 12, r.y + 34, FONT_S, C_TXT)
        self.ui_button(pygame.Rect(r.right - 190, r.y + 44, 178, 38), "DESBLOQUEJADA" if self.sv["slot6"] else f"{SHOP_SLOT_COST} pol·len",
                       self.buy_slot, (not self.sv["slot6"]) and ph >= SHOP_SLOT_COST, FONT_S)
        r = pygame.Rect(566, y + 8, 414, 88)
        self.card(r)
        txt(f"Fragments d'ambre: {self.sv['frag']}  (els donen les repetides)", r.x + 12, r.y + 8, FONT_S, C_GOLD)
        for i, (rar, nm) in enumerate((("common", "Comuna"), ("rare", "Rara"), ("legend", "Llegend."))):
            self.ui_button(pygame.Rect(r.x + 10 + i * 133, r.y + 36, 126, 44), f"{nm} {FRAG_COST[rar]}", (lambda rr=rar: self.craft_bee(rr)),
                           self.sv["frag"] >= FRAG_COST[rar], FONT_S)

    # --- MILLORES DEL RUSC
    def draw_hive(self):
        self.chrome("Millores del Rusc", theme="hive")
        cards = [dict(id="cannon", name="Trompa de pol·len", desc="Més dany i menys recàrrega", mx=MAX_CANNON)] + \
                [dict(id=u["id"], name=u["name"], desc=u["desc"], mx=HIVE_MAX) for u in HIVE_UPG]
        for i, cd in enumerate(cards):
            col, row = i % 3, i // 3
            r = pygame.Rect(14 + col * 326, 56 + row * 104, 318, 96)
            self.card(r)
            lv = self.sv["cannon"] if cd["id"] == "cannon" else self.hive_lv(cd["id"])
            txt(cd["name"], r.x + 10, r.y + 6, FONT, C_GOLD)
            txt(cd["desc"], r.x + 10, r.y + 30, FONT_S, C_TXT)
            for k in range(cd["mx"]):
                pw = (r.w - 140) // cd["mx"]
                pygame.draw.rect(screen, C_GOLD if k < lv else (60, 50, 40), (r.x + 10 + k * pw, r.y + 54, pw - 3, 10))
            txt(f"Nv {lv}/{cd['mx']}", r.x + 10, r.y + 70, FONT_S, C_TXT)
            if lv >= cd["mx"]:
                self.ui_button(pygame.Rect(r.right - 122, r.y + 50, 110, 38), "MÀXIM", lambda: None, False, FONT_S)
            else:
                cost = self.cannon_cost() if cd["id"] == "cannon" else self.hive_cost(cd["id"])
                self.ui_button(pygame.Rect(r.right - 122, r.y + 50, 110, 38), f"{cost} mel", (lambda k=cd["id"]: self.buy_hive(k)),
                               self.sv["mel"] >= cost, FONT_S)

    def draw_newbee(self):
        key, back = self.newbee
        b = BEE_BY_KEY[key]
        screen.blit(self.hexbg("capsules"), (0, 0))
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((10, 8, 6, 170))
        screen.blit(veil, (0, 0))
        col = RAR_COL[b["rarity"]]
        for k in range(4):
            rad = 250 + k * 26 + int((0.5 + 0.5 * math.sin(self.anim * 4)) * 10)
            gl = pygame.Surface((rad * 2, rad * 2), pygame.SRCALPHA)
            pygame.draw.circle(gl, col + (24,), (rad, rad), rad)
            screen.blit(gl, (W // 2 - rad, 260 - rad))
        r = pygame.Rect(W // 2 - 200, 50, 400, 410)
        self.card(r, b["rarity"], hl=True)
        txt("NOVA ABELLA!", r.centerx, r.y + 28, FONT_M, C_GOLD, center=True)
        big = fit(anim_img(IMG["ally_" + key], self.anim, 6), 320, 180)
        screen.blit(big, big.get_rect(center=(r.centerx, r.y + 150 + math.sin(self.anim * 3) * 6)))
        txt(b["name"], r.centerx, r.y + 262, FONT_M, C_TXT, center=True)
        txt(f"{RAR_NAME[b['rarity']]}  |  {b['role']}", r.centerx, r.y + 296, FONT, RAR_COL[b["rarity"]], center=True)
        txt(STYLE_NAME[b["style"]], r.centerx, r.y + 322, FONT_S, C_GOLD, center=True)
        txt(b["desc"], r.centerx, r.y + 344, FONT_S, C_TXT, center=True)
        self.ui_button(pygame.Rect(r.x + 90, r.bottom - 52, r.w - 180, 40), "Continua", lambda: self.go(back), True, FONT)

    # ======================= HISTÒRIA INICIAL
    def story_list(self):
        return {"intro": INTRO_SCENES, "win": WIN_SCENES, "lose": LOSE_SCENES}[self.story_kind]

    def story_music(self):
        i = self.intro_scene()[0]
        if self.story_kind == "intro":
            return INTRO_MUSIC[min(i, len(INTRO_MUSIC) - 1)]
        if self.story_kind == "win":
            return "epic" if i < 2 else "calm"
        return "boss" if i == 0 else "tense"

    def start_story(self, kind):
        self.story_kind = kind
        self.intro_t = 0.0
        self.intro_i = 0
        self.intro_full = False
        self.intro_replay = False
        self.go("intro")
        self.intro_enter()

    def intro_scene(self):
        k = min(self.intro_i, len(self.story_list()) - 1)
        return k, self.intro_t, self.story_list()[k][0]

    def intro_enter(self):
        lst = self.story_list()
        sound = lst[min(self.intro_i, len(lst) - 1)][2].get("snd")
        if sound:
            sfx(sound)

    def intro_advance(self):
        """1r clic: mostra tot el text. 2n clic: passa a l'escena següent."""
        full = self.story_list()[self.intro_i][1]
        if full and not self.intro_full and int(self.intro_t * 32) < len(full):
            self.intro_full = True
            return
        if self.intro_i + 1 >= len(self.story_list()):
            self.finish_intro()
            return
        self.intro_i += 1
        self.intro_t = 0.0
        self.intro_full = False
        self.intro_enter()

    def start_intro(self, replay=False, back="help"):
        self.story_kind = "intro"
        self.story_back = back
        self.intro_t = 0.0
        self.intro_i = 0
        self.intro_full = False
        self.intro_replay = replay
        self.go("intro")
        self.intro_enter()

    def finish_intro(self):
        if self.state != "intro" and not self.trans:
            return
        if self.story_kind in ("win", "lose"):
            self.go(self.story_kind)
            return
        self.sv["intro_done"] = True
        self.save()
        if self.intro_replay:
            self.go(self.story_back)
        else:
            self.start_tutorial()

    def start_tutorial(self, replay=False, back="help"):
        self.story_back = back
        self.tut_i = 0
        self.tut_replay = replay
        self.go("tutorial")

    def finish_tutorial(self):
        self.sv["tut_done"] = True
        self.save()
        self.go(self.story_back if self.tut_replay else "title")

    def tut_step(self, d):
        n = self.tut_i + d
        if n >= len(TUT_CARDS):
            self.finish_tutorial()
        else:
            self.tut_i = max(0, n)

    def story_key(self, key):
        if self.state == "intro":
            if key == pygame.K_ESCAPE:
                self.finish_intro()
            elif key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_RIGHT):
                self.intro_advance()
        elif self.state == "tutorial":
            if key == pygame.K_ESCAPE:
                self.finish_tutorial()
            elif key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_RIGHT):
                self.tut_step(1)
            elif key == pygame.K_LEFT:
                self.tut_step(-1)

    def _bg(self, name, alpha=255):
        if alpha >= 255:
            for lay in ("_sky", "_mid", "_ground"):
                screen.blit(IMG[name + lay], (0, 0))
            return
        tmp = pygame.Surface((W, H))
        for lay in ("_sky", "_mid", "_ground"):
            tmp.blit(IMG[name + lay], (0, 0))
        tmp.set_alpha(max(0, min(255, int(alpha))))
        screen.blit(tmp, (0, 0))

    def _veil(self, a, col=(6, 10, 46)):
        if a > 0.01:
            ov = pygame.Surface((W, H), pygame.SRCALPHA)
            ov.fill(col + (int(min(1.0, a) * 255),))
            screen.blit(ov, (0, 0))

    def _walker(self, key, x, y, w, h, enemy=False, rate=12):
        frames = IMG[("enemy_" if enemy else "ally_") + key]
        im = fit(anim_img(frames, self.anim, rate, hash(key) % 5), w, h)
        screen.blit(im, im.get_rect(midbottom=(x, y)))

    def _glow(self, cx, cy, r, col, alpha):
        g_ = pygame.Surface((int(r * 2), int(r * 2)), pygame.SRCALPHA)
        for k in range(4):
            pygame.draw.circle(g_, col + (max(0, min(255, int(alpha * (k + 1) / 4))),), (int(r), int(r)), int(r * (1 - k * 0.22)))
        screen.blit(g_, (int(cx - r), int(cy - r)))

    def _sil(self, img):
        key = id(img)
        if key not in self.sil_cache:
            self.sil_cache[key] = pygame.mask.from_surface(img).to_surface(setcolor=(12, 8, 16, 255), unsetcolor=(0, 0, 0, 0))
        return self.sil_cache[key]

    def _bubble(self, x, y, who, text, t, who_col=(150, 90, 20), w=310):
        n = int(max(0.0, t - 0.5) * 28)
        if n <= 0:
            return
        lines = wrap_text(text, FONT_S, w - 26)
        h = 30 + 18 * len(lines)
        r = pygame.Rect(int(x - w / 2), int(y - h / 2), w, h)
        pygame.draw.rect(screen, C_BORDER, r.inflate(6, 6), border_radius=12)
        pygame.draw.rect(screen, (252, 246, 228), r, border_radius=10)
        pygame.draw.polygon(screen, C_BORDER, [(x - 14, r.bottom - 1), (x + 18, r.bottom - 1), (x + 30, r.bottom + 22)])
        pygame.draw.polygon(screen, (252, 246, 228), [(x - 10, r.bottom - 2), (x + 14, r.bottom - 2), (x + 26, r.bottom + 17)])
        txt(who, r.x + 12, r.y + 5, FONT_S, who_col, shadow=False)
        left = n
        for i, ln in enumerate(lines):
            part = ln[:max(0, left)]
            left -= len(ln) + 1
            if part:
                txt(part, r.x + 12, r.y + 24 + i * 18, FONT_S, (50, 34, 20), shadow=False)

    def _chapter(self, text, t):
        if t > 3.4:
            return
        a = min(1.0, t / 0.5) * min(1.0, (3.4 - t) / 0.7)
        band = pygame.Surface((W, 92), pygame.SRCALPHA)
        band.fill((0, 0, 0, int(150 * a)))
        screen.blit(band, (0, 150))
        img = FONT_B.render(text, True, (255, 232, 160))
        img.set_alpha(int(255 * a))
        screen.blit(img, img.get_rect(center=(W // 2, 196)))

    def _vignette(self):
        if self.vig is None:
            v = pygame.Surface((W, UI_Y), pygame.SRCALPHA)
            for i in range(30):
                pygame.draw.rect(v, (0, 0, 0, int(150 * (1 - i / 30.0) ** 2)), (i * 5, i * 3, W - i * 10, UI_Y - i * 6), 6)
            self.vig = v
        screen.blit(self.vig, (0, 0))

    def _ambient(self, kind, t):
        if kind == "embers":
            return self._embers(t)
        for x, y, ph, sp in self.amb[:30]:
            if kind == "snow":
                pygame.draw.rect(screen, (240, 246, 252), (int((x + 14 * math.sin(t * 0.6 + ph)) % W), int((y * 1.1 + t * 38 * sp) % UI_Y), 2, 2))
            elif kind == "spores":
                k = 0.5 + 0.5 * math.sin(t * sp + ph)
                pygame.draw.rect(screen, (int(150 * k), int(210 * k), int(120 * k)),
                                 (int(x + 20 * math.sin(t * 0.5 + ph)), int(60 + (y - t * 12 * sp) % 330), 3, 3))
            elif kind == "dust":
                pygame.draw.rect(screen, (222, 196, 154), (int((x + t * 70 * sp) % W), int(330 + y % 80), 3, 1))
            else:
                k = 0.5 + 0.5 * math.sin(t * 3 * sp + ph)
                pygame.draw.rect(screen, (int(255 * k), int(250 * k), int(210 * k)), (int(x), int(100 + y % 220), 2, 2))

    def _embers(self, t, col=(255, 150, 60), n=26):
        for k, (x, y, ph, sp) in enumerate(self.amb[:n]):
            py = UI_Y - ((t * 40 * sp + y) % (UI_Y - 30))
            fade = max(0.0, min(1.0, (py - 20) / 200))
            c = (int(col[0] * fade), int(col[1] * fade), int(col[2] * fade))
            pygame.draw.rect(screen, c, (int(x + 18 * math.sin(t * 0.8 + ph)), int(py), 3, 3))

    def _intro_scene_draw(self, sc, t, d):
        a = self.anim
        hive = IMG["base_hive"]
        hx, hy = 70, GROUND + 28 - hive.get_height()
        flashes = self.sv["opts"].get("flashes", True)
        if sc == 0:
            self._bg("bg_meadow")
            self._glow(150, 70, 100, (255, 236, 150), 90)
            for i in range(3):
                screen.blit(IMG["cloud_%d" % i], (((t * (6 + i * 4) + i * 420) % (W + 380)) - 190, 26 + i * 46))
            screen.blit(hive, (hx, hy))
            for i, k in enumerate(("honey", "bumble", "leafcutter", "carpenter", "orchid", "sweat")):
                x = 300 + i * 120 + 70 * math.sin(t * 1.1 + i)
                y = 170 + (i * 47) % 150 + 22 * math.sin(t * 2 + i)
                self._walker(k, x, y, 74, 54, rate=14)
            for x, y, ph, sp in self.amb[:22]:
                pygame.draw.rect(screen, (250, 238, 170), (int((x + t * 14 * sp) % W), int(240 + y % 160 + 8 * math.sin(t + ph)), 3, 3))
        elif sc == 1:
            self._bg("bg_meadow")
            screen.blit(hive, (hx, hy))
            self._glow(190, 170, 130, (255, 214, 90), 60 + 25 * math.sin(a * 2))
            for i, k in enumerate(("honey", "bumble", "leafcutter", "carpenter", "orchid", "sweat")):
                ang = a * 0.8 + i * 1.05
                self._walker(k, 190 + math.cos(ang) * 190, 190 + math.sin(ang * 1.3) * 50, 68, 50, rate=14)
            self._walker("queen", 190, 205 + math.sin(a * 2) * 6, 170, 124, rate=8)
            self._bubble(390, 80, "Reina Melissa", "Cuideu-vos les unes de les altres, filles meves.", t)
        elif sc == 2:
            self._bg("bg_meadow")
            self._veil(min(0.85, 0.3 + t / 5.0 * 0.55))
            screen.blit(hive, (hx, hy))
            for i in range(6):
                x = (i * 230 + t * 20) % (W + 300) - 150
                cl = pygame.Surface((300, 110), pygame.SRCALPHA)
                pygame.draw.ellipse(cl, (14, 12, 24, 190), (0, 30, 300, 70))
                pygame.draw.ellipse(cl, (22, 18, 34, 190), (40, 0, 200, 70))
                screen.blit(cl, (int(x), 10 + (i % 3) * 36))
            q0 = IMG["base_queen_0"]
            q0 = q0[0] if isinstance(q0, list) else q0
            qs = self._sil(fit(q0, 260, 220))
            screen.blit(qs, qs.get_rect(midbottom=(W - 150, 300)))
            for i in range(9):
                x = (W + 60 + i * 100 - t * 85) % (W + 500) - 100
                y = 70 + (i * 53) % 190 + 14 * math.sin(a * 3 + i)
                sl = self._sil(fit(IMG["enemy_wasp"][int(a * 14 + i) % len(IMG["enemy_wasp"])], 64, 44))
                screen.blit(sl, sl.get_rect(center=(x, y)))
            tt = t % 5.0
            if 1.5 < tt < 1.85 and flashes:
                fl = pygame.Surface((W, H), pygame.SRCALPHA)
                fl.fill((255, 255, 255, int(220 * (1 - (tt - 1.5) / 0.35))))
                screen.blit(fl, (0, 0))
                bx = 360 + int(t) % 4 * 120
                pygame.draw.lines(screen, (240, 240, 255), False, [(bx, 0), (bx - 22, 80), (bx + 12, 130), (bx - 18, 230)], 4)
        elif sc == 3:
            self._bg("bg_lair")
            self._veil(0.35, (70, 0, 12))
            pulse = 0.5 + 0.5 * math.sin(a * 3)
            self._glow(W // 2 + 40, 215, 250, (255, 40, 30), 50 + 40 * pulse)
            fr = IMG["base_queen_0"]
            fr = fr[int(a * 5) % len(fr)] if isinstance(fr, list) else fr
            vi = fit(fr, 520, 400)
            shk = 3 if int(a * 8) % 2 else -3
            screen.blit(vi, vi.get_rect(center=(W // 2 + 90 + shk, 215 + math.sin(a * 2) * 5)))
            self._bubble(270, 120, "Vespa Reina", "Tota la mel serà meva!", t, (170, 30, 30), 300)
            if t % 4.0 < 0.3 and flashes:
                fl = pygame.Surface((W, H), pygame.SRCALPHA)
                fl.fill((255, 80, 60, int(120 * (1 - (t % 4.0) / 0.3))))
                screen.blit(fl, (0, 0))
        elif sc == 4:
            terr = (("El Bosc Fosc", "bg_forest", ("spider", "beetle", "ant"), "spores"),
                    ("El Desert", "bg_desert", ("scorpion", "locust", "wasp"), "dust"),
                    ("La Platja", "bg_beach", ("crab", "mosquito", "dragonfly"), "sparkle"),
                    ("Les Mines", "bg_mine", ("bat", "termite", "earthworm"), "dust"),
                    ("El Volcà", "bg_volcano", ("fireant", "stag", "hornet"), "embers"),
                    ("La Muntanya Nevada", "bg_snow", ("frostbeetle", "moth", "mantis"), "snow"))
            SLOT = 3.2
            i = int(t / SLOT) % 6
            lt = t - int(t / SLOT) * SLOT
            name, bg, foes, amb = terr[i]
            self._bg(terr[(i - 1) % 6][1])
            self._bg(bg, min(1.0, lt / 0.7) * 255)
            self._veil(0.16, (70, 0, 12))
            self._ambient(amb, t)
            for k, fk in enumerate(foes):
                x = W + 90 + k * 170 - lt * 150            # avancen a poc a poc: es veu què són
                hov = ENEMIES[fk]["hover"]
                y = GROUND + 30 - ((hov * 1.4 + 6 * math.sin(a * 3 + k)) if hov else 0)
                if not hov:
                    sh = shadow_img(86)
                    screen.blit(sh, sh.get_rect(center=(x, GROUND + 32)))
                    for pj in range(3):
                        screen.blit(part_img((200, 184, 150), 4 - pj, 150 - pj * 40),
                                    (int(x + 30 + pj * 16 - 7), int(GROUND + 26 - pj * 3 - 7)))
                self._walker(fk, x, y, 96, 72, True, 7)
                txt(ENEMIES[fk]["name"], x, GROUND + 54, FONT_S, (250, 232, 200), center=True)
            bn = pygame.Rect(W // 2 - 190, 14, 380, 50)
            pygame.draw.rect(screen, C_BORDER, bn.inflate(6, 6), border_radius=10)
            pygame.draw.rect(screen, (70, 20, 18), bn, border_radius=8)
            pygame.draw.rect(screen, (214, 120, 90), bn, 2, border_radius=8)
            txt(name, W // 2, 39, FONT_M, (250, 224, 190), center=True)
            if lt > 1.8:
                txt("CONQUERIT", W // 2, 84, FONT_M, (240, 80, 64), center=True)
            conq = min(len(STAGES), 1 + int(t / SLOT * 3))
            nst = len(STAGES)
            for k in range(nst):
                px_ = W // 2 - (nst - 1) * 7 + k * 14
                pygame.draw.circle(screen, C_BORDER, (px_, 118), 6)
                pygame.draw.circle(screen, (230, 70, 60) if k < conq else (84, 64, 54), (px_, 118), 4)
            txt("Territoris conquerits: %d/%d" % (conq, nst), W // 2, 140, FONT_S, (250, 204, 184), center=True)
        elif sc == 5:
            self._bg("bg_meadow")
            self._veil(0.72)
            screen.blit(hive, (hx, hy))
            for k in range(4):
                ph_ = (t * 0.5 + k * 0.25) % 1.0
                smk = pygame.Surface((90, 90), pygame.SRCALPHA)
                pygame.draw.circle(smk, (60, 56, 62, int(110 * (1 - ph_))), (45, 45), 22 + int(ph_ * 22))
                screen.blit(smk, (int(hx + 70 + math.sin(t * 0.6 + k) * 10 - 45), int(hy - 20 - ph_ * 120)))
            self._embers(t, (255, 120, 40), 18)
            self._glow(210, 380, 90, (255, 190, 70), 30 + 20 * math.sin(a * 2))
            self._walker("queen", 210, 392 + math.sin(a * 1.4) * 3, 150, 110, rate=3)
            for i in range(4):
                x = (W + 80 + i * 130 - t * 28) % (W + 300) - 60
                sl = self._sil(fit(IMG["enemy_ant"][int(a * 8 + i) % len(IMG["enemy_ant"])], 70, 50))
                screen.blit(sl, sl.get_rect(midbottom=(x, GROUND + 30)))
        elif sc == 6:
            self._bg("bg_meadow")
            self._veil(max(0.35, 0.72 - t * 0.06))
            beam = pygame.Surface((W, H), pygame.SRCALPHA)
            pygame.draw.polygon(beam, (255, 230, 140, 40), [(430, 0), (640, 0), (800, UI_Y), (260, UI_Y)])
            screen.blit(beam, (0, 0))
            fa = max(0.0, 1.0 - t / 7.0)
            self._glow(250, 190, 120, (255, 220, 110), 60 * fa + 20)
            self._walker("queen", 250, 230 + math.sin(a * 2) * 5, 160, 118, rate=8)
            prog = min(1.0, max(0.0, (t - 1.2) / 3.0))
            if prog > 0:
                for k in range(14):
                    p = (prog * 1.2 - k * 0.04) % 1.0
                    if 0 < p < 1:
                        ox = 250 + (560 - 250) * p
                        oy = 200 + (270 - 200) * p - math.sin(p * math.pi) * 60
                        pygame.draw.circle(screen, (255, 236, 150), (int(ox), int(oy)), max(2, int(7 * (1 - p * 0.5))))
            glow_b = 40 + 140 * prog + (60 * math.sin(a * 6) if prog >= 1 else 0)
            self._glow(560, 255, 90 + 40 * prog, (255, 214, 90), max(0, glow_b))
            self._walker("honey", 560, 290 + math.sin(a * 3) * 5, 96 + int(44 * prog), 70 + int(30 * prog), rate=14)
            if t > 4.2:
                pygame.draw.circle(screen, (255, 240, 170), (560, 255), max(2, int(((t - 4.2) * 160) % 220)), 3)
            self._bubble(330, 90, "Reina Melissa", "Només tu pots salvar-nos... Agafa la meva llum.", t, (150, 90, 20), 330)
        elif sc == 7:
            self._bg("bg_meadow")
            self._veil(max(0.0, 0.5 - min(t, d) / d * 0.55), (20, 14, 8))
            screen.blit(hive, (hx, hy))
            glow = pygame.Surface((300, 300), pygame.SRCALPHA)
            for rr, al in ((140, 40), (100, 60), (60, 80)):
                pygame.draw.circle(glow, (255, 220, 110, int(al * min(1.0, t / 2.0))), (150, 150), rr)
            screen.blit(glow, (140 - 150 + 70, GROUND - 110 - 150 + 40))
            ks = ("honey", "bumble", "carpenter", "mason", "orchid", "arctic", "nurse", "sweat")
            e = min(1.0, t / 3.2)
            e = 1 - (1 - e) ** 2
            for i, k in enumerate(ks):
                sx = W + 60 if i % 2 else -60
                sy = 60 + (i * 41) % 200
                tx_ = 170 + (i % 4) * 78 + 60 * math.sin(a * 1.4 + i) * e
                ty_ = 190 + (i // 4) * 80 + 14 * math.sin(a * 2 + i)
                self._walker(k, sx + (tx_ - sx) * e, sy + (ty_ - sy) * e, 80, 60, rate=14)
            if t > 2.0:
                self._walker("queen", 300, 150 + math.sin(a * 2) * 6, 130, 96, rate=10)
        elif sc == 8:
            self._bg("bg_meadow")
            self._veil(0.5, (20, 14, 8))
            nst = len(STAGES)
            pts = [(60 + i * 38, 300 + 80 * math.sin(i * 0.55)) for i in range(nst)]
            for k in range(nst - 1):
                pygame.draw.line(screen, (60, 40, 20), pts[k], pts[k + 1], 7)
                pygame.draw.line(screen, (214, 176, 98), pts[k], pts[k + 1], 3)
            lit = min(nst, int(t / (d * 0.75) * nst) + 1)
            for k, p in enumerate(pts):
                pygame.draw.circle(screen, C_BORDER, (int(p[0]), int(p[1])), 12)
                pygame.draw.circle(screen, (240, 200, 70) if k < lit else (90, 78, 60), (int(p[0]), int(p[1])), 9)
            p = pts[lit - 1]
            self._walker("honey", p[0], p[1] - 14 + math.sin(a * 6) * 3, 56, 42, rate=14)
            q0 = IMG["base_queen_0"]
            qi = fit(q0[0] if isinstance(q0, list) else q0, 230, 190)
            qa = min(1.0, max(0.0, (t - 3.0) / 1.5))
            if qa > 0:
                tmp = qi.copy()
                tmp.set_alpha(int(255 * qa))
                screen.blit(tmp, tmp.get_rect(center=(W - 130, 150)))
        else:
            self._bg("bg_meadow")
            if self.logo is None:
                self.logo = self.build_logo()
            self._glow(W // 2, 220, 300, (255, 214, 90), 70)
            screen.blit(self.logo, self.logo.get_rect(center=(W // 2, 220 + math.sin(a * 1.6) * 4)))
            for i, k in enumerate(("honey", "bumble", "carpenter", "sweat", "orchid", "leafcutter")):
                x = ((a * (46 + i * 9) + i * 190) % (W + 200)) - 100
                self._walker(k, x, 360 + 30 * math.sin(a * 2 + i) - (i % 3) * 40, 70, 50, rate=14)
        self._vignette()
        self._veil(max(0.0, 1.0 - t / 0.6), (0, 0, 0))     # entrada des del negre

    def _end_scene_draw(self, kind, sc, t, d):
        a = self.anim
        hive = IMG["base_hive"]
        hx, hy = 70, GROUND + 28 - hive.get_height()
        flashes = self.sv["opts"].get("flashes", True)
        if kind == "win":
            if sc == 0:                                   # la Reina esclata
                self._bg("bg_lair")
                self._veil(0.25, (70, 0, 12))
                fr = IMG["base_queen_2"]
                fr = fr[int(a * 6) % len(fr)] if isinstance(fr, list) else fr
                vi = fit(fr, 520, 400)
                amp = 5 * max(0.0, 1 - t / 3.5)
                tmp = vi.copy()
                tmp.set_alpha(int(255 * max(0.0, 1 - max(0.0, t - 2.4) / 2.2)))
                screen.blit(tmp, tmp.get_rect(center=(W // 2 + random.uniform(-amp, amp), 215 + random.uniform(-amp, amp))))
                if t < 5.0:
                    for k in range(46):
                        ang = k * 0.137 + 0.4
                        sp_ = 80 + (k * 37) % 260
                        px = W // 2 + math.cos(ang) * sp_ * min(t, 3.0) * 0.9
                        py = 215 + math.sin(ang) * sp_ * min(t, 3.0) * 0.7 + 60 * min(t, 3.0) ** 2 * 0.3
                        col = ((255, 220, 90), (255, 140, 50), (255, 250, 230))[k % 3]
                        pygame.draw.circle(screen, col, (int(px), int(py)), max(1, int(7 * max(0.0, 1 - t / 4.5))))
                    pygame.draw.circle(screen, (255, 240, 200), (W // 2, 215), max(2, int((t * 240) % 520)), 4)
                    if flashes:
                        fl = pygame.Surface((W, H), pygame.SRCALPHA)
                        fl.fill((255, 250, 230, int(190 * max(0.0, 1 - ((t * 2.2) % 1.0) / 0.35))))
                        screen.blit(fl, (0, 0))
            elif sc == 1:                                 # el cel s'aclareix
                self._bg("bg_meadow")
                self._glow(150, 70, 120, (255, 236, 150), 110)
                for i in range(3):
                    screen.blit(IMG["cloud_%d" % i], (((t * (6 + i * 4) + i * 420) % (W + 380)) - 190, 26 + i * 46))
                screen.blit(hive, (hx, hy))
                for i, k in enumerate(("honey", "bumble", "carpenter", "mason", "orchid", "arctic", "nurse", "sweat", "killer", "queen")):
                    ang = a * 0.7 + i * 0.63
                    self._walker(k, 520 + math.cos(ang) * 300, 190 + math.sin(ang * 1.4) * 70 + 14 * math.sin(a * 5 + i), 78, 58, rate=14)
                conf = ((236, 200, 70), (220, 90, 70), (96, 170, 220), (120, 200, 110), (230, 140, 200), (250, 250, 240))
                for i, (x, y, ph, sp) in enumerate(self.amb):
                    px = (x * 1.3 + 40 * math.sin(a * 1.7 + ph)) % W
                    py = ((y * 1.7 + a * 90 * sp) % (UI_Y + 40)) - 20
                    pygame.draw.rect(screen, conf[i % 6], (int(px), int(py), 6, 10))
            elif sc == 2:                                 # la Flor és coronada
                self._bg("bg_meadow")
                screen.blit(hive, (hx, hy))
                beam = pygame.Surface((W, H), pygame.SRCALPHA)
                pygame.draw.polygon(beam, (255, 230, 140, 46), [(480, 0), (680, 0), (820, UI_Y), (330, UI_Y)])
                screen.blit(beam, (0, 0))
                self._glow(300, 250, 120, (255, 214, 90), 70)
                self._walker("queen", 300, 300 + math.sin(a * 2) * 5, 170, 124, rate=8)
                self._glow(580, 250, 130, (255, 236, 150), 90 + 40 * math.sin(a * 4))
                by = 310 + math.sin(a * 3) * 5
                self._walker("honey", 580, by, 150, 110, rate=14)
                cy_ = by - 112
                pygame.draw.polygon(screen, (60, 40, 8), [(556, cy_ + 2), (556, cy_ - 22), (568, cy_ - 10), (580, cy_ - 28), (592, cy_ - 10), (604, cy_ - 22), (604, cy_ + 2)])
                pygame.draw.polygon(screen, (250, 206, 70), [(559, cy_), (559, cy_ - 18), (569, cy_ - 8), (580, cy_ - 24), (591, cy_ - 8), (601, cy_ - 18), (601, cy_)])
                for gx, gc in ((569, (220, 60, 60)), (580, (90, 200, 230)), (591, (120, 220, 120))):
                    pygame.draw.circle(screen, gc, (gx, int(cy_ - 4)), 3)
                for k in range(16):
                    ang = a * 1.3 + k * 0.4
                    pygame.draw.rect(screen, (255, 244, 180), (int(580 + math.cos(ang) * (70 + 20 * math.sin(a + k))), int(by - 60 + math.sin(ang) * 60), 3, 3))
                self._bubble(300, 110, "Reina Melissa", "Has salvat el nostre món, Flor. La llum sempre va ser teva.", t, (150, 90, 20), 340)
            else:
                self._bg("bg_meadow")
                self._veil(0.28, (255, 140, 60))
                if self.logo is None:
                    self.logo = self.build_logo()
                self._glow(W // 2, 200, 300, (255, 214, 90), 70)
                screen.blit(self.logo, self.logo.get_rect(center=(W // 2, 190 + math.sin(a * 1.6) * 4)))
                for i, k in enumerate(("honey", "bumble", "carpenter", "sweat", "orchid", "leafcutter", "queen")):
                    x = ((a * (46 + i * 9) + i * 170) % (W + 200)) - 100
                    self._walker(k, x, 380 + 24 * math.sin(a * 2 + i) - (i % 3) * 36, 70, 50, rate=14)
                if sc == 4:
                    txt("Gràcies per jugar!", W // 2, 330, FONT_M, (255, 240, 200), center=True)
        else:                                             # DERROTA
            if sc == 0:
                self._bg("bg_meadow")
                self._veil(0.82, (30, 0, 10))
                shk = random.uniform(-2, 2)
                screen.blit(hive, (hx + shk, hy))
                self._embers(t, (255, 90, 40), 26)
                for k in range(4):
                    ph_ = (t * 0.5 + k * 0.25) % 1.0
                    smk = pygame.Surface((90, 90), pygame.SRCALPHA)
                    pygame.draw.circle(smk, (60, 56, 62, int(120 * (1 - ph_))), (45, 45), 22 + int(ph_ * 24))
                    screen.blit(smk, (int(hx + 60 + k * 16 - 45), int(hy - 20 - ph_ * 130)))
                q0 = IMG["base_queen_0"]
                q0 = q0[0] if isinstance(q0, list) else q0
                qs = self._sil(fit(q0, 420, 340))
                screen.blit(qs, qs.get_rect(center=(W - 230, 200 + math.sin(a * 5) * 6)))
                for ex_ in (-34, 34):
                    pygame.draw.circle(screen, (255, 50, 40), (W - 230 + ex_, 150), 6 + int(2 * math.sin(a * 6)))
                if t % 4.0 < 0.3 and flashes:
                    fl = pygame.Surface((W, H), pygame.SRCALPHA)
                    fl.fill((255, 255, 255, int(200 * (1 - (t % 4.0) / 0.3))))
                    screen.blit(fl, (0, 0))
            else:
                self._bg("bg_lair")
                self._veil(0.55, (30, 0, 50))
                keys = (self.captured_now or ["honey"])[:6]
                wave = min(1.0, t / 2.0)
                pygame.draw.circle(screen, (140, 60, 200), (W - 100, 200), int(wave * 1100), 6)
                for i, k in enumerate(keys):
                    x = 140 + i * 140
                    y = 330
                    gl = 0.5 + 0.5 * math.sin(a * 3 + i)
                    self._glow(x, y - 20, 70, (170, 80, 230), 40 + 40 * gl)
                    sl = fit(IMG["sil_" + k], 96, 64)
                    screen.blit(sl, sl.get_rect(center=(x, y - 20)))
                    for bx_ in range(-44, 45, 16):
                        pygame.draw.line(screen, (80, 66, 96), (x + bx_, y - 70), (x + bx_, y + 24), 3)
                    pygame.draw.line(screen, (80, 66, 96), (x - 48, y - 70), (x + 48, y - 70), 4)
                    pygame.draw.line(screen, (80, 66, 96), (x - 48, y + 24), (x + 48, y + 24), 4)
                    txt(BEE_BY_KEY[k]["name"][:14], x, y + 42, FONT_S, (210, 190, 240), center=True)
                if sc == 2:
                    self._glow(W // 2 + 20, 130, 110, (255, 214, 90), 70)
                    self._walker("honey", W // 2 + 20, 170 + math.sin(a * 3) * 5, 150, 110, rate=14)
                    self._bubble(W // 2 + 40, 40, PROTA, "Les rescatarem, una per una!", t, (150, 90, 20), 330)
        self._vignette()
        self._veil(max(0.0, 1.0 - t / 0.6), (0, 0, 0))

    def draw_intro(self):
        global screen
        sc, t, d = self.intro_scene()
        real = screen
        if self.intro_surf is None:
            self.intro_surf = pygame.Surface((W, UI_Y))
        screen = self.intro_surf            # l'escena es dibuixa a part i no queda tapada pel text
        try:
            if self.story_kind == "intro":
                self._intro_scene_draw(sc, t, d)
            else:
                self._end_scene_draw(self.story_kind, sc, t, d)
        finally:
            screen = real
        screen.fill((26, 18, 10))
        view = pygame.Rect(32, 8, 936, 412)
        pygame.draw.rect(screen, C_BORDER, view.inflate(10, 10))
        z = 1.0 + 0.07 * min(1.0, t / 9.0) + (0.08 * min(1.0, t / 6.0) if sc == 3 else 0.0)
        sw, sh = int(W / z), int(UI_Y / z)
        src = self.intro_surf.subsurface(pygame.Rect((W - sw) // 2, (UI_Y - sh) // 2, sw, sh))
        screen.blit(pygame.transform.smoothscale(src, (view.w, view.h)), view.topleft)
        pygame.draw.rect(screen, (214, 176, 98), view.inflate(6, 6), 2)
        panel = pygame.Rect(32, 430, 936, 100)
        pygame.draw.rect(screen, C_BORDER, panel.inflate(6, 6))
        pygame.draw.rect(screen, (40, 30, 18), panel)
        pygame.draw.rect(screen, (214, 176, 98), panel, 2)
        full = self.story_list()[sc][1]
        n = len(full) if self.intro_full else int(t * 32)
        done = n >= len(full)
        left = n
        for i, ln in enumerate(wrap_text(full, FONT_M, panel.w - 36)[:3]):
            part = ln[:max(0, left)]
            left -= len(ln) + 1
            if part:
                txt(part, panel.x + 18, panel.y + 8 + i * 28, FONT_M, C_TXT)
        if done and int(self.anim * 2) % 2 == 0:
            txt("Clica per continuar  >", panel.right - 16, panel.bottom - 22, FONT_S, (250, 220, 130), right=True)
        elif not done:
            txt("clica per mostrar tot el text", panel.right - 16, panel.bottom - 22, FONT_S, (176, 166, 140), right=True)
        self.ui_button(pygame.Rect(W - 140, 16, 118, 34), "Salta >>", self.finish_intro, True, FONT_S)

    # ======================= TUTORIAL
    def draw_tutorial(self):
        screen.blit(self.hexbg("base"), (0, 0))
        title, lines = TUT_CARDS[self.tut_i]
        pygame.draw.rect(screen, C_WOOD, (0, 0, W, 48))
        pygame.draw.rect(screen, C_WOOD_L, (0, 0, W, 3))
        txt("Tutorial  %d/%d" % (self.tut_i + 1, len(TUT_CARDS)), 16, 9, FONT_M, C_TXT)
        left = pygame.Rect(30, 70, 440, 330)
        self.card(left)
        self.tut_art(self.tut_i, left)
        right = pygame.Rect(490, 70, 480, 330)
        self.card(right, hl=True)
        txt(title, right.x + 20, right.y + 18, FONT_M, C_GOLD)
        for i, ln in enumerate(lines):
            txt(ln, right.x + 20, right.y + 74 + i * 30, FONT, C_TXT)
        for i in range(len(TUT_CARDS)):
            pygame.draw.circle(screen, C_GOLD if i == self.tut_i else (90, 78, 60), (W // 2 - 50 + i * 20, 430), 6)
        if int(self.anim * 2) % 2 == 0:
            txt("Clica per continuar  >", W // 2, 414, FONT_S, (250, 220, 130), center=True)
        self.ui_button(pygame.Rect(30, 456, 130, 44), "Enrere", lambda: self.tut_step(-1), self.tut_i > 0, FONT)
        last = self.tut_i == len(TUT_CARDS) - 1
        self.ui_button(pygame.Rect(W - 190, 456, 160, 44), "Comença!" if last else "Següent", lambda: self.tut_step(1), True, FONT)
        self.ui_button(pygame.Rect(W // 2 - 70, 456, 140, 44), "Salta", self.finish_tutorial, True, FONT)

    def tut_art(self, i, r):
        a = self.anim
        cx, cy = r.centerx, r.centery
        if i == 0:
            for k, key in enumerate(("honey", "bumble", "carpenter")):
                b = pygame.Rect(r.x + 30 + k * 130, r.y + 20, 110, 84)
                button(b, C_BTN)
                ic = fit(IMG["beeicon_" + key], 72, 44)
                screen.blit(ic, ic.get_rect(center=(b.centerx, b.y + 36)))
                txt("[%d]" % (k + 1), b.x + 6, b.y + 4, FONT_S, C_DARK, shadow=False)
                txt(str(BEE_BY_KEY[key]["cost"]), b.centerx, b.y + 68, FONT, C_DARK, center=True, shadow=False)
            gy = r.y + 250
            pygame.draw.rect(screen, (96, 130, 70), (r.x + 8, gy, r.w - 16, 40))
            hv = fit(IMG["base_hive"], 90, 110)
            screen.blit(hv, hv.get_rect(midbottom=(r.x + 60, gy + 38)))
            for k in range(3):
                x = r.x + 130 + ((a * 50 + k * 110) % (r.w - 150))
                self._walker(("honey", "bumble", "carpenter")[k], x, gy + 38, 60, 44, rate=10)
        elif i == 1:
            screen.blit(IMG["icon_honey"], (r.x + 40, r.y + 40))
            txt("Diners", r.x + 90, r.y + 48, FONT_M, C_GOLD)
            fill = (a * 0.25) % 1.0
            pygame.draw.rect(screen, (40, 14, 10), (r.x + 40, r.y + 100, 360, 22))
            pygame.draw.rect(screen, C_GOLD, (r.x + 40, r.y + 100, int(360 * fill), 22))
            txt("+16/s", r.x + 330, r.y + 48, FONT_M, (176, 214, 150))
            b = pygame.Rect(r.x + 40, r.y + 160, 150, 90)
            button(b, C_BTN)
            txt("[W] Rusc", b.centerx, b.y + 20, FONT_S, C_DARK, center=True, shadow=False)
            txt("Nivell 1", b.centerx, b.y + 46, FONT, C_DARK, center=True, shadow=False)
            txt("80", b.centerx, b.y + 70, FONT, C_DARK, center=True, shadow=False)
            for k, ln in enumerate(("més ingressos", "menys recàrrega", "més botí")):
                txt("+ " + ln, r.x + 220, r.y + 170 + k * 26, FONT, C_TXT)
        elif i == 2:
            hn = fit(IMG["hive_cannon"], 260, 190)
            screen.blit(hn, hn.get_rect(center=(cx - 40, cy + 10)))
            ph = (a * 0.5) % 1.0
            for k in range(14):
                ang = -0.7 + k * 0.1
                dd = ph * 190
                x = cx + 60 + math.cos(ang) * dd + k * 3
                y = cy - 70 + math.sin(ang) * dd * 0.6 + ph * 40
                pygame.draw.circle(screen, (244, 214, 90), (int(x), int(y)), max(2, int(5 * (1 - ph))))
            txt("[ESPAI]", cx, r.bottom - 30, FONT_M, C_GOLD, center=True)
        elif i == 3:
            for k, (lab, key) in enumerate((("[Q] Eixam", "honey"), ("[E] Cura", "nurse"))):
                b = pygame.Rect(r.x + 40, r.y + 40 + k * 140, 170, 40)
                button(b, C_BTN)
                txt(lab, b.centerx, b.centery, FONT, C_DARK, center=True, shadow=False)
                for j in range(4 if k == 0 else 3):
                    self._walker(key, r.x + 270 + j * 40, r.y + 100 + k * 140 + 4 * math.sin(a * 5 + j), 52, 40, rate=12)
        elif i == 4:
            for k, (role, key) in enumerate((("Tanc", "bumble"), ("Atacant", "honey"), ("Tirador", "mason"), ("Control", "arctic"), ("Suport", "nurse"))):
                y = r.y + 24 + k * 60
                pygame.draw.rect(screen, C_BORDER, (r.x + 20, y, 400, 50), 1)
                ic = fit(IMG["beeicon_" + key], 70, 40)
                screen.blit(ic, ic.get_rect(center=(r.x + 60, y + 25)))
                txt(role, r.x + 110, y + 14, FONT, C_GOLD)
                txt(ROLE_INFO[role][:34], r.x + 210, y + 16, FONT_S, C_TXT)
        else:
            items = ((lambda x, y: draw_book(x, y, 14), "Taller"), (lambda x, y: draw_gift(x, y, 13), "Missions"),
                     (lambda x, y: draw_amber(x, y, 16, (226, 152, 40)), "Càpsules"), (lambda x, y: draw_stall(x, y, 16), "Botiga"),
                     (lambda x, y: draw_gear(x, y, 16), "Rusc"), (lambda x, y: draw_star(x, y, 14, True), "Estrelles"))
            for k, (fn, lab) in enumerate(items):
                x, y = r.x + 70 + (k % 3) * 150, r.y + 80 + (k // 3) * 130
                self.card(pygame.Rect(x - 56, y - 50, 112, 110))
                fn(x, y - 6)
                txt(lab, x, y + 42, FONT_S, C_TXT, center=True)

    def draw_help(self):
        self.chrome("Com es juga", theme="base", back_to="title")
        left = [("Objectiu", ["Destrueix el niu enemic abans que", "ells destrueixin el teu rusc."]),
                ("Abelles i diners", ["Genera abelles amb 1-6 (costen diners).", "Els diners pugen sols i en matar.", "W millora el moneder: més ingressos,", "menys recàrrega i més botí."]),
                ("Vespa Reina", ["Si perds contra ella, les abelles que lluitin", "perden els nivells i les hauràs de rescatar", "derrotant enemics (Missions > Rescat)."]),
                ("Rols", ["Tanc: els enemics l'ataquen primer.", "Atacant: molt dany a prop.", "Tirador: de lluny i toca els voladors.", "Control: alenteix o atordeix. Suport: cura.", "3 rols diferents = +8% de vida."])]
        right = [("Trompa i habilitats", ["ESPAI: trompa de pol·len (dany a tots).", "Q: Eixam (4 abelles gratis).", "E: Cura (abelles i rusc)."]),
                 ("Voladors", ["Les abelles cos a cos fan -30% de dany als", "voladors. Les tiradores no."]),
                 ("Si caus", ["Pots continuar per 30 pol·len: els enemics", "retrocedeixen i tens el moneder ple."]),
                 ("Nit i dia", ["Si el nivell dura molt, es fa de nit i,", "més tard, torna a ser de dia."]),
                 ("Progrés", ["Millora abelles al Taller, evoluciona-les al 15,", "compra millores del Rusc i prova la", "Supervivència infinita."])]
        self.ui_button(pygame.Rect(280, H - 42, 230, 36), "Veure la història", lambda: self.start_intro(True), True, FONT_S)
        self.ui_button(pygame.Rect(520, H - 42, 230, 36), "Veure el tutorial", lambda: self.start_tutorial(True), True, FONT_S)
        for col, items, x in ((0, left, 24), (1, right, 520)):
            y = 62
            for title, lines in items:
                txt(title, x, y, FONT, C_GOLD)
                y += 24
                for ln in lines:
                    txt(ln, x + 8, y, FONT_S, C_TXT)
                    y += 18
                y += 12

    # --- RESULTAT
    def draw_result(self):
        self.draw_play()
        s = pygame.Surface((W, H), pygame.SRCALPHA)
        s.fill((0, 0, 0, 180))
        screen.blit(s, (0, 0))
        res = self.result
        if res.get("survival"):
            txt("SUPERVIVÈNCIA", W // 2, 70, FONT_B, C_GOLD, center=True)
            tm = int(res["time"])
            txt("Has aguantat %d:%02d" % (tm // 60, tm % 60), W // 2, 124, FONT_M, C_TXT, center=True)
            bt = int(self.sv.get("surv_best", 0))
            txt(("NOU RÈCORD!  " if res.get("record") else "Rècord: ") + "%d:%02d" % (bt // 60, bt % 60), W // 2, 160, FONT, (250, 236, 180), center=True)
        elif res["win"]:
            if self.stage["boss"]:
                txt("HAS DERROTAT LA VESPA REINA!", W // 2, 70, FONT_M, C_GOLD, center=True)
                txt("Has completat el joc!", W // 2, 112, FONT_B, C_GOLD, center=True)
            else:
                txt("VICTÒRIA!", W // 2, 92, FONT_B, C_GOLD, center=True)
            caps = ("Victòria", f"En menys de {self.stage['par']} s", "Sense disparar la trompa")
            for k in range(3):
                x = W // 2 - 190 + k * 190
                draw_star(x, 168, 22, res["flags"][k])
                txt(caps[k], x, 206, FONT_S, C_TXT if res["flags"][k] else (120, 112, 100), center=True)
        else:
            txt("DERROTA...", W // 2, 110, FONT_B, (200, 90, 80), center=True)
        lines = [f"Enemics derrotats: {res['kills']}", f"Temps: {int(res['time'])} s", f"Mel guanyada: +{res['mel']}"]
        if res["pollen"]:
            lines.append(f"Pol·len: +{res['pollen']}")
        for i, ln in enumerate(lines):
            txt(ln, 90, 250 + i * 34, FONT_M if i == 2 else FONT, C_GOLD if i >= 2 else C_TXT)
        n = self.claimable()
        yy = 250 + len(lines) * 34 + 8
        for k in res.get("rescued", []):
            txt("Has rescatat: " + BEE_BY_KEY[k]["name"], 90, yy, FONT, (150, 230, 150))
            yy += 28
        if n:
            txt(f"Tens {n} missió(ns) per cobrar!", 90, yy, FONT, (250, 236, 180))
        txt("Dany per abella", 560, 240, FONT, C_TXT)
        dm = res["dmg"]
        top = max([v for _k, v in dm] + [1])
        for i, (k, v) in enumerate(dm[:5]):
            y = 270 + i * 40
            ic = fit(IMG["beeicon_" + k], 56, 32)
            screen.blit(ic, ic.get_rect(center=(584, y + 14)))
            pygame.draw.rect(screen, (40, 30, 20), (620, y + 4, 280, 20))
            pygame.draw.rect(screen, C_GOLD, (620, y + 4, int(280 * v / top), 20))
            txt(str(int(v)), 626, y + 6, FONT_S, C_DARK, shadow=False)
        if res["win"]:
            conf = ((236, 200, 70), (220, 90, 70), (96, 170, 220), (120, 200, 110), (230, 140, 200), (250, 250, 240))
            for i, (x, y, ph, sp) in enumerate(self.amb):
                px = (x * 1.3 + 40 * math.sin(self.anim * 1.7 + ph)) % W
                py = ((y * 1.7 + self.anim * 90 * sp) % (H + 40)) - 20
                pygame.draw.rect(screen, conf[i % 6], (int(px), int(py), 6, 10))
            for i, d in enumerate(self.deck[:6]):
                bx = 60 + i * 76 if i < 3 else W - 60 - (i - 3) * 76
                by = 150 - abs(math.sin(self.anim * 5 + i)) * 26
                ic = fit(IMG["beeicon_" + d["key"]], 64, 44)
                screen.blit(ic, ic.get_rect(center=(bx, by)))
        elif not res.get("survival") or True:
            for i, h_ in enumerate(res.get("hints", [])):
                txt("Consell: " + h_, W // 2, 400 + i * 24, FONT_S, (250, 236, 180), center=True)
        self.ui_button(pygame.Rect(W // 2 - 140, 470, 280, 50), "Continua", self.after_result, True, FONT_M)

    # =================================================== DISTRIBUCIÓ
    def draw(self):
        global screen
        self.hits = []
        st = self.state
        shaken = st == "play" and self.shake > 0.02 and not self.headless
        if shaken:
            real = screen
            if self.world is None:
                self.world = pygame.Surface((W, H))
            screen = self.world
        try:
            self._draw_inner(st)
        finally:
            if shaken:
                screen = real
        if shaken:
            a = self.shake * 14
            real.fill((0, 0, 0))
            real.blit(self.world, (random.uniform(-a, a), random.uniform(-a, a)))

    def _draw_inner(self, st):
        if st == "title":
            self.draw_title()
        elif st == "play":
            self.draw_play()
            if self.cont_prompt:
                self.draw_continue()
            elif self.paused:
                self.draw_pause()
        elif st in ("win", "lose"):
            self.draw_result()
        elif st == "capsule_open":
            self.draw_capsule_open()
        elif st == "capsule_multi":
            self.draw_capsule_multi()
        else:
            getattr(self, "draw_" + st)()
        if self.trans:
            tr = self.trans
            draw_transition(tr["style"], tr["color"], min(1.0, tr["t"] / tr["dur"]), tr["label"])

    def click(self, pos):
        if self.trans:
            return True
        for r, action, en in reversed(self.hits):
            if en and r.collidepoint(pos):
                sfx("click")
                action()
                return True
        return False


# ------------------------------------------------------------ ATACS (taula estil -> funció)
def _a_sting(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_hit")


def _a_bite(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_hit_r")
    if u.d["style"] == "ram" and unit and random.random() < 0.5:
        t.knock()


def _a_slice(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_slash_g")


def _a_slam(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_hit")
    g.spawn_fx("fx_ring", tx, u.y + 4, fps=12)
    g.splash(u, tx, 55, 0.6, exclude=t)


def _a_crit(g, u, t, unit, tx, ty):
    if random.random() < 0.25:
        g.deal(u, t, 2.2, "fx_crit")
        g.floats.append([tx, ty - 26, 0.9, "CRÍTIC!", (255, 160, 60), True])
        g.add_shake(0.12)
        g.hitstop = max(g.hitstop, 0.05)
        sfx("crit")
    else:
        g.deal(u, t, 1.0, "fx_slash")


def _a_dash(g, u, t, unit, tx, ty):
    u.dash_t = 0.3
    g.deal(u, t, 1.0, "fx_hit")


def _a_flurry(g, u, t, unit, tx, ty):
    g.deal(u, t, 0.4, "fx_hit")
    g.after(0.09, lambda: g.deal(u, t, 0.4, "fx_hit"))
    g.after(0.18, lambda: g.deal(u, t, 0.4, "fx_hit"))


def _a_poison(g, u, t, unit, tx, ty):
    g.deal(u, t, 0.8, "fx_hit_g")
    if unit:
        t.poison_t = 3.0
        t.poison_dps = u.d["atk"] * 0.3
        t.pfx_name = "fx_poison"


def _a_slime(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_hit_g")
    if unit:
        t.slow_t = 2.5


def _a_drain(g, u, t, unit, tx, ty):
    g.deal(u, t, 0.8, "fx_hit_r")
    u.hp = min(u.max, u.hp + u.d["atk"] * 0.5)


def _a_joust(g, u, t, unit, tx, ty):
    u.dash_t = 0.3
    g.deal(u, t, 1.2, "fx_hit")
    if unit:
        t.knock()
        t.kb_v = 340


def _a_frost(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_frost")
    if unit:
        t.slow_t = 3.0
    for f in g.foes_of(u):
        if f is not t and f.hp > 0 and abs(f.x - tx) <= 55:
            g.hurt(u, f, u.d["atk"] * 0.5)
            f.slow_t = 3.0


def _a_burrow(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_hit")
    g.spawn_fx("fx_ring", tx, u.y + 4, fps=12)
    g.splash(u, tx, 50, 0.8, exclude=t)
    if unit:
        t.stun_t = 0.5


def _a_crush(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.8, "fx_crit")
    if unit:
        t.knock()
        t.slow_t = 2.0


def _a_bash(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_hit")
    if unit and random.random() < 0.7:
        t.knock()


def _a_burn(g, u, t, unit, tx, ty):
    g.deal(u, t, 0.8, "fx_hit_r")
    if unit:
        t.poison_t = 2.5
        t.poison_dps = u.d["atk"] * 0.4
        t.pfx_name = "fx_burn"


def _a_crunch(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_hit_r")
    g.splash(u, tx, 42, 0.7, exclude=t)


def _a_dive(g, u, t, unit, tx, ty):
    u.dash_t = 0.3
    g.deal(u, t, 1.4, "fx_hit_r")
    if unit:
        t.knock()


def _a_sparkle(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_sparkle")
    if unit and random.random() < 0.22:
        t.stun_t = 0.7
        t.knock()


def _a_royal(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_hit")
    g.spawn_fx("fx_royal", tx, u.y + 6, fps=11)
    g.splash(u, tx, 110, 0.7, exclude=t)
    for a in g.allies_of(u):
        if a is not u and abs(a.x - u.x) < 130 and a.hp > 0:
            a.hp = min(a.max, a.hp + a.max * 0.06)
            g.spawn_fx("fx_heal", a.x, a.y - a.d["hover"] - 40)


def _a_claw(g, u, t, unit, tx, ty):
    g.deal(u, t, 0.6, "fx_claw")
    g.after(0.14, lambda: g.deal(u, t, 0.6, "fx_claw"))


def _a_stomp(g, u, t, unit, tx, ty):
    g.deal(u, t, 1.0, "fx_hit_r")
    g.spawn_fx("fx_ring_big", tx, u.y + 4, fps=12)
    g.splash(u, tx, 70, 0.6, knock=True, exclude=t)


def _a_ranged(g, u, t, unit, tx, ty):
    g.shoot(u, t)


STYLE_SFX = {"slice": "slash", "claw": "slash", "crit": "slash", "flurry": "slash", "slam": "thud", "stomp": "thud", "crush": "thud",
             "bash": "thud", "ram": "thud", "joust": "thud", "sparkle": "zap", "orb": "zap", "frost": "zap", "pollen": "magic",
             "royal": "magic", "mud": "magic", "dust": "magic"}
ATTACK_TABLE = {
    "sting": _a_sting, "bite": _a_bite, "ram": _a_bite, "slice": _a_slice, "slam": _a_slam, "crit": _a_crit,
    "dash": _a_dash, "flurry": _a_flurry, "poison": _a_poison, "venom": _a_poison, "slime": _a_slime,
    "drain": _a_drain, "joust": _a_joust, "frost": _a_frost, "burrow": _a_burrow, "crush": _a_crush,
    "bash": _a_bash, "burn": _a_burn, "crunch": _a_crunch, "dive": _a_dive, "sparkle": _a_sparkle,
    "royal": _a_royal, "claw": _a_claw, "stomp": _a_stomp,
}
for _s in RANGED_STYLES:
    ATTACK_TABLE[_s] = _a_ranged


# ------------------------------------------------------------ JOC (lògica)
class Game(GameUI):
    def __init__(self, headless=False):
        self.headless = headless
        self.sv = default_save() if headless else load_save()
        self.state = "title"
        self.intro_t = 0.0
        self.story_kind = "intro"
        self.captured_now = []
        self.rescued_now = []
        self.story_back = "help"
        self.intro_i = 0
        self.intro_full = False
        self.intro_surf = None
        self.vig = None
        self.sil_cache = {}
        self.intro_replay = False
        self.tut_i = 0
        self.tut_replay = False
        self.quit_req = False
        self.trans = None
        self.logo = None
        self.shake = 0.0
        self.dlg = None
        self.continues = 0
        self.cont_prompt = False
        self.ui_floats = []
        self.hitstop = 0.0
        self.world = None
        self.newbee = None
        self.abil_cd = [0.0, 0.0]
        self.abil_used = 0
        self.t_full = 0.0
        self.air_spawned = 0
        self.btn_abil = [pygame.Rect(10, 40, 116, 26), pygame.Rect(132, 40, 116, 26)]
        self.btab = "enemies"
        self.daytag = "day"
        self.kick = 0.0
        self.mtab = "daily"
        self.hex_cache = {}
        self.anim = 0.0
        self.hits = []
        self.toast = ["", 0.0]
        self.tip = 0
        self.cap = None
        self.result = None
        self.btn_units = [pygame.Rect(8 + i * 100, UI_Y + 10, 94, 84) for i in range(DECK_MAX)]
        self.btn_wallet = pygame.Rect(624, UI_Y + 10, 112, 84)
        self.btn_cannon = pygame.Rect(W - 150, UI_Y + 10, 140, 84)
        self.btn_speed = pygame.Rect(W // 2 - 62, 6, 56, 26)
        self.btn_pause = pygame.Rect(W // 2 + 6, 6, 56, 26)
        self.stage_i = 0
        self.stage = STAGES[0]
        self.deck = []
        self.cats, self.enemies = [], []
        self.fx, self.events, self.dying, self.haz = [], [], [], []
        self.banner = ["", 0.0]
        self.flash = 0.0
        self.paused = False
        self.speed = 1
        self.confirm_reset = False
        self.mpage = self.spage = self.upage = self.epage = self.bpage = 0
        rr = random.Random(4)
        self.amb = [(rr.uniform(0, W), rr.uniform(40, 400), rr.uniform(0, 6.28), rr.uniform(0.6, 1.6))
                    for _ in range(34)]
        if not headless:
            AUDIO["opts"] = self.sv["opts"]
            self.refresh_daily()
            if not self.sv.get("intro_done"):
                self.state = "intro"
                self.intro_enter()
            elif not self.sv.get("tut_done"):
                self.tut_replay = False

    # --- utilitats generals
    def save(self):
        if not self.headless:
            write_save(self.sv)

    def go(self, state):
        if self.headless or self.trans or state == self.state:
            return self._go(state)
        style, color = TRANS.get(state, ("fade", (30, 24, 18)))
        self.trans = dict(t=0.0, dur=0.55, style=style, color=color, label=None, apply=lambda: self._go(state), done=False)

    def _go(self, state):
        self.state = state
        self.paused = False
        self.confirm_reset = False
        if state == "base":
            self.tip = random.randrange(len(TIPS))
        if state == "stages":
            self.spage = min(self.sv["progress"], len(STAGES) - 1) // 6
        if state in ("shop", "missions"):
            self.refresh_daily()

    def survival_stage(self):
        n = min(max(self.sv["progress"], 3), len(STAGES))
        base = STAGES[n - 1]
        pool = []
        for s_ in STAGES[:n]:
            for k in stage_enemy_ids(s_):
                if k not in pool:
                    pool.append(k)
        return dict(name="Supervivència", diff=99, rec=n, par=9999, base_hp=10 ** 9, mult=1.0, amult=1.0, cap=10,
                    boss=False, survival=True, cat_hp=3500 + 300 * n, bg=base["bg"], base=base["base"],
                    base_off=base["base_off"], amb=base["amb"], clouds=base["clouds"], spawns=[], events=[],
                    pool=[k for k in pool if ENEMIES[k]["reward"] < 200],
                    minis=[k for k in pool if ENEMIES[k]["reward"] >= 200],
                    mult0=max(1.0, base["mult"] * 0.55), amult0=max(1.0, base["amult"] * 0.7))

    def begin_survival(self):
        if not self.sv["deck"]:
            self.say("Equipa almenys una abella!")
            return
        if self.headless:
            return self.start(-1, self.survival_stage())
        self.trans = dict(t=0.0, dur=0.7, style="iris", color=(20, 14, 10), label="Supervivència",
                          apply=lambda: self.start(-1, self.survival_stage()), done=False)

    def begin_level(self, i):
        if not self.sv["deck"]:
            self.say("Equipa almenys una abella!")
            return
        if self.headless:
            return self.start(i)
        lines = LEVEL_DIALOGUES.get(i)
        boss = STAGES[i]["boss"]
        if lines and (boss or str(i) not in self.sv["dlg_seen"]):
            if not boss:
                self.sv["dlg_seen"].append(str(i))
                self.save()
            self.start_dialogue(lines, lambda: self._launch_level(i), STAGES[i]["bg"])
            return
        self._launch_level(i)

    def _launch_level(self, i):
        self.trans = dict(t=0.0, dur=0.7, style="iris", color=(20, 14, 10), label=STAGES[i]["name"],
                          apply=lambda: self.start(i), done=False)

    def start_dialogue(self, lines, after, bg="bg_meadow"):
        self.dlg = dict(lines=list(lines), i=0, t=0.0, full=False, after=after, bg=bg)
        self.go("dialogue")

    def dlg_advance(self):
        d = self.dlg
        if d["i"] >= len(d["lines"]):
            return
        if not d.get("full") and int(d["t"] * 30) < len(d["lines"][d["i"]]):
            d["full"] = True
            return
        d["i"] += 1
        d["t"] = 0.0
        d["full"] = False
        if d["i"] >= len(d["lines"]):
            self.dlg_finish()

    def dlg_finish(self):
        if self.state != "dialogue" or self.dlg.get("closing"):
            return
        self.dlg["closing"] = True
        after = self.dlg["after"]
        self.dlg["after"] = None
        if after:
            after()

    def after_result(self):
        """Després d'una derrota, la Flor de vegades dona un consell."""
        res = self.result
        hints = res.get("hints") if res else None
        if hints and not res.get("survival") and not self.headless and random.random() < 0.55:
            self.start_dialogue(["No pateixis! Crec que podem millorar:"] + hints[:2], lambda: self.go("stages"), self.stage["bg"])
        else:
            self.go("stages")

    # ---- continuar pagant pol·len
    def accept_continue(self):
        if self.sv["pollen"] < CONT_COST:
            self.say("Et falta pol·len per continuar.")
            return
        self.sv["pollen"] -= CONT_COST
        self.continues += 1
        self.cont_prompt = False
        self.cat_base.hp = self.cat_base.max * 0.5
        for e in self.enemies:
            e.x = min(ENEMY_BASE_X - 30, e.x + 380)       # els enemics retrocedeixen
            e.stun_t = 1.5
            e.kb_t = 0.0
        self.money = float(self.max_money)                # moneder ple per remuntar
        self.spawn_fx("fx_royal", CAT_BASE_X + 60, GROUND - 20, fps=11)
        self.banner_say("Torna-ho a provar!", "levelup")
        self.save()

    def decline_continue(self):
        self.cont_prompt = False
        self.finish(False)

    def quit_game(self):
        self.quit_req = True

    @property
    def deck_size(self):
        return DECK_MAX if self.sv.get("slot6") else DECK_SIZE

    def say(self, text, secs=3.0):
        self.toast = [text, secs]

    def tick_ui(self, dt):
        """Temporitzadors de la interfície (no de la batalla)."""
        if self.toast[1] > 0:
            self.toast[1] -= dt
        for f in self.ui_floats:
            f[1] -= dt
        self.ui_floats = [f for f in self.ui_floats if f[1] > 0]
        if self.state == "dialogue" and self.dlg and not self.trans:
            self.dlg["t"] += dt
        if self.state == "intro" and not self.trans:
            self.intro_t += dt
        tr = self.trans
        if tr:
            tr["t"] += dt
            if not tr["done"] and tr["t"] >= tr["dur"] / 2:
                tr["done"] = True
                if tr["apply"]:
                    tr["apply"]()
            if tr["t"] >= tr["dur"]:
                self.trans = None
        c = self.cap
        if self.state == "capsule_open" and c:
            c["hit_t"] += dt
            if c.get("bt") is not None:
                b0 = c["bt"]
                c["bt"] += dt
                if b0 < 0.25 <= c["bt"]:
                    sfx("reveal")
        elif self.state == "capsule_multi" and c and c["idx"] < len(c["results"]):
            b0 = c["it"]
            c["it"] += dt
            for tm, snd in ((0.12, "sting"), (0.26, "sting"), (0.40, "sting"), (0.5, "boom"), (0.75, "reveal")):
                if b0 < tm <= c["it"]:
                    sfx(snd)

    def gain_bee(self, key):
        self.sv["captured"].pop(key, None)
        o = self.sv["owned"]
        if key in o:
            if o[key] >= MAX_LV:
                self.sv["mel"] += 150
                return "max"
            o[key] += 1
            return "up"
        o[key] = 1
        if len(self.sv["deck"]) < self.deck_size:
            self.sv["deck"].append(key)
        return "new"

    def upg_cost(self, key):
        return UPG_BASE[BEE_BY_KEY[key]["rarity"]] * self.sv["owned"][key]

    def cannon_cost(self):
        return 130 * self.sv["cannon"]

    @property
    def cannon_time(self):
        return max(10.0, max(12.0, 25.0 - 1.5 * (self.sv["cannon"] - 1)) * (1 - 0.04 * self.hive_lv("cannon_cd")))

    @property
    def cannon_dmg(self):
        return 300 * (1 + 0.25 * (self.sv["cannon"] - 1)) * (1 + 0.12 * self.hive_lv("cannon_dmg"))

    def upgrade_bee(self, key):
        c = self.upg_cost(key)
        if self.sv["owned"][key] < MAX_LV and self.sv["mel"] >= c:
            self.sv["mel"] -= c
            self.sv["owned"][key] += 1
            self.sv["stats"]["upgrades"] += 1
            self.daily_add("upgrades")
            sfx("coin")
            self.save()

    def evolve(self, key):
        if self.sv["owned"].get(key, 0) < MAX_LV or self.sv["evo"].get(key):
            return
        if self.sv["mel"] < EVO_MEL or self.sv["pollen"] < EVO_POLLEN:
            self.say("Et falta mel o pol·len per evolucionar.")
            return
        self.sv["mel"] -= EVO_MEL
        self.sv["pollen"] -= EVO_POLLEN
        self.sv["evo"][key] = True
        self.say("%s ha evolucionat!" % BEE_BY_KEY[key]["name"])
        sfx("levelup")
        self.save()

    def upgrade_cannon(self):
        if self.sv["cannon"] < MAX_CANNON and self.sv["mel"] >= self.cannon_cost():
            self.sv["mel"] -= self.cannon_cost()
            self.sv["cannon"] += 1
            sfx("coin")
            self.save()

    def save_preset(self, i):
        self.sv["presets"][i] = list(self.sv["deck"])
        self.say("Equip %d desat." % (i + 1))
        self.save()

    def load_preset(self, i):
        p = [k for k in self.sv["presets"][i] if k in self.sv["owned"]][:self.deck_size]
        if not p:
            self.say("L'equip %d està buit: desa'l primer." % (i + 1))
            return
        self.sv["deck"] = p
        self.say("Equip %d carregat." % (i + 1))
        self.save()

    def toggle_deck(self, key):
        d = self.sv["deck"]
        if key in d:
            d.remove(key)
        elif len(d) < self.deck_size:
            d.append(key)
        else:
            self.say(f"L'equip està ple ({self.deck_size}). Treu-ne una primer.")
        self.save()

    def mission_progress(self, m):
        if m["kind"] == "stage":
            return min(m["val"], self.sv["progress"])
        if m["kind"] == "calc":
            return min(m["val"], self.calc_value(m["calc"]))
        return min(m["val"], self.sv["stats"].get(m["stat"], 0))

    def calc_value(self, key):
        if key == "seen":
            return len(self.sv["seen"])
        if key == "owned":
            return len(self.sv["owned"])
        if key == "evo":
            return sum(1 for v in self.sv["evo"].values() if v)
        if key == "surv":
            return int(self.sv.get("surv_best", 0))
        return sum(self.sv["stars"].values())

    def mission_done(self, m):
        return self.mission_progress(m) >= m["val"]

    def claimable(self):
        return sum(1 for m in MISSIONS if self.mission_done(m) and m["id"] not in self.sv["claimed"])

    def claim(self, m):
        if not self.mission_done(m) or m["id"] in self.sv["claimed"]:
            return
        self.sv["claimed"].append(m["id"])
        parts = []
        if m.get("bee"):
            res = self.gain_bee(m["bee"])
            nm = BEE_BY_KEY[m["bee"]]["name"]
            parts.append(nm if res == "new" else nm + " (+1 nivell)")
        if m.get("mel"):
            self.sv["mel"] += m["mel"]
            parts.append(f"{m['mel']} mel")
        if m.get("pollen"):
            self.sv["pollen"] += m["pollen"]
            parts.append(f"{m['pollen']} pol·len")
        self.ui_say("Has rebut: " + ", ".join(parts))
        sfx("coin")
        self.save()
        if m.get("bee") and res == "new":
            self.show_newbee(m["bee"], "missions")

    # --- càpsules (amb garantia i obertura x10)
    def roll_capsule(self, ci):
        cap = CAPSULES[ci]
        pk = str(ci)
        self.sv["pity"][pk] = self.sv["pity"].get(pk, 0) + 1
        self.sv["stats"]["capsules"] += 1
        rarity = "common"
        if self.sv["pity"][pk] >= cap["pity"]:
            rarity = "legend"
        else:
            roll, acc = random.random(), 0.0
            for name, p in cap["odds"]:
                acc += p
                if roll < acc:
                    rarity = name
                    break
        if rarity == "legend":
            self.sv["pity"][pk] = 0
        b = random.choice([x for x in BEE_UNITS if x["rarity"] == rarity])
        res = self.gain_bee(b["key"])
        if res != "new":
            self.sv["frag"] += FRAG_GAIN[rarity]
        return b["key"], res

    def craft_bee(self, rarity):
        cost = FRAG_COST[rarity]
        if self.sv["frag"] < cost:
            self.say("Et falten fragments d'ambre.")
            return
        missing = [b for b in BEE_UNITS if b["rarity"] == rarity and b["key"] not in self.sv["owned"]]
        if missing:
            b = random.choice(missing)
            self.sv["frag"] -= cost
            self.gain_bee(b["key"])
            sfx("levelup")
            self.save()
            self.show_newbee(b["key"], "shop")
            return
        low = [b for b in BEE_UNITS if b["rarity"] == rarity and self.sv["owned"].get(b["key"], 0) < MAX_LV]
        if low:
            b = random.choice(low)
            self.sv["frag"] -= cost
            self.sv["owned"][b["key"]] += 1
            self.say("Fragments canviats: +1 nivell a " + b["name"])
            sfx("coin")
            self.save()
        else:
            self.say("Ja tens totes les d'aquesta raresa al màxim.")

    def cap_tap(self):
        """Cada clic pica la bola d'ambre; en trencar-la surt l'abella."""
        c = self.cap
        if self.state != "capsule_open" or not c or c.get("bt") is not None:
            return
        c["hits"] += 1
        c["hit_t"] = 0.0
        sfx("sting")
        if c["hits"] >= c["need"]:
            c["bt"] = 0.0
            sfx("boom")

    def cap_next(self):
        c = self.cap
        c["idx"] += 1
        c["it"] = 0.0

    def cap_skip_all(self):
        self.cap["idx"] = len(self.cap["results"])

    def cap_multi_click(self):
        c = self.cap
        if c["idx"] >= len(c["results"]):
            return
        if c["it"] < 0.75:
            c["it"] = 0.75
        else:
            self.cap_next()

    def show_newbee(self, key, back):
        self.newbee = (key, back)
        self.go("newbee")

    def open_capsules(self, ci, n):
        cur, cost = CAPSULES[ci]["cost"]
        if self.sv[cur] < cost * n:
            self.say("No en tens prou per obrir-la.")
            return
        self.sv[cur] -= cost * n
        results = [self.roll_capsule(ci) for _ in range(n)]
        self.daily_add("capsules", n)
        shards = [(random.uniform(0, math.tau), random.uniform(120, 420), random.uniform(10, 26), random.uniform(-4, 4))
                  for _ in range(26)]
        if n == 1:
            need = CAP_NEED[BEE_BY_KEY[results[0][0]]["rarity"]]
            self.cap = dict(key=results[0][0], res=results[0][1], t=0.0, ci=ci, shards=shards, hits=0, need=need,
                            hit_t=9.9, bt=None)
            self.state = "capsule_open"
        else:
            self.cap = dict(results=results, t=0.0, ci=ci, shards=shards, idx=0, it=0.0, hits=0, need=4,
                            hit_t=9.9, bt=None)
            self.state = "capsule_multi"
        sfx("shake")
        self.save()

    # --- opcions
    def toggle_opt(self, key):
        o = self.sv["opts"]
        o[key] = not o[key]
        if key == "fullscreen" and not self.headless:
            try:
                pygame.display.toggle_fullscreen()
            except Exception:
                pass
        elif key == "bigfont":
            make_fonts(o["bigfont"])
        elif key in ("sfx", "music"):
            apply_audio()
        self.save()

    def vol_step(self, d):
        o = self.sv["opts"]
        o["volume"] = round(max(0.0, min(1.0, o["volume"] + d)), 2)
        apply_audio()
        sfx("click")
        self.save()

    def reset_save(self):
        if not self.confirm_reset:
            self.confirm_reset = True
            return
        keep = self.sv["opts"]
        self.sv = default_save()
        self.sv["opts"] = keep
        AUDIO["opts"] = self.sv["opts"]
        self.save()
        self.go("base")
        self.say("Partida esborrada.")

    # --- pausa
    def resume(self):
        self.paused = False

    def toggle_pause(self):
        if self.state == "play" and not self.cont_prompt:
            self.paused = not self.paused

    def toggle_speed(self):
        self.speed = 2 if self.speed == 1 else 1

    def abandon(self):
        if self.stage.get("survival"):
            self.paused = False
            return self.finish(False)
        self.daily_add("kills", self.kills)
        self.daily_add("spawned", self.spawned)
        self.daily_add("cannons", self.cannons_used)
        self.record_stats()
        self.sv["mel"] += self.mel_earned
        got = self.mel_earned
        self.save()
        self.go("stages")
        self.say(f"Nivell abandonat (+{got} mel)")

    # --- batalla
    def start(self, i, stage=None):
        if not self.sv["deck"]:
            self.say("Equipa almenys una abella!")
            return
        self.stage_i = i
        self.stage = stage or STAGES[i]
        self.deck = [BEE_BY_KEY[k] for k in self.sv["deck"]]
        self.daytag = "day"
        self.surv_t, self.surv_boss = 2.0, 70.0
        self.cats, self.enemies = [], []
        hp_mult = 1 + 0.10 * self.hive_lv("hp")
        self.cat_base = Base(CAT_BASE_X, self.stage.get("cat_hp", CAT_BASE_HP) * hp_mult, 40)
        armed = self.sv["armed"]
        self.used_items = []
        for k in ("money", "hp", "cannon"):
            if armed.get(k) and self.sv["items"].get(k, 0) > 0 and not self.headless:
                self.sv["items"][k] -= 1
                self.used_items.append(k)
        if "hp" in self.used_items:
            self.cat_base.hp = self.cat_base.max = self.cat_base.max * 1.3
        boss = self.stage["boss"]
        self.enemy_base = Base(ENEMY_BASE_X - (110 if boss else 0), self.stage["base_hp"], 95 if boss else 42)
        self.money = 300.0 if "money" in self.used_items else 0.0
        self.wallet = 1
        self.cds = [0.0] * len(self.deck)
        self.cannon = self.cannon_time if "cannon" in self.used_items else 0.0
        self.kick = 0.0
        self.time = 0.0
        self.spawn = [dict(t=s[1], n=0) for s in self.stage["spawns"]]
        self.cannon_vis = 0.0
        self.shots, self.parts, self.floats, self.pollen = [], [], [], []
        self.fx, self.events, self.haz, self.dying = [], [], [], []
        self.banner, self.flash = ["", 0.0], 0.0
        self.ev_done = set()
        self.haz_t = self.stage.get("hazard", {}).get("every", 0) * 0.6
        self.phase = 0
        self.boss_t = dict(barrage=14.0, spawn=14.0, guard=45.0)
        self.kills = self.spawned = self.cannons_used = self.mel_earned = 0
        self.rescued_now = []
        self.abil_cd = [12.0, 20.0]
        self.abil_used = 0
        self.continues = 0
        self.cont_prompt = False
        self.t_full = 0.0
        self.air_spawned = 0
        self.shake = self.hitstop = 0.0
        self.dmg_by, self.spawned_by = {}, {}
        self.paused = False
        self.state = "play"

    @property
    def max_money(self):
        return (450 + 150 * (self.wallet - 1)) * (1 + 0.10 * self.hive_lv("wallet"))

    @property
    def income(self):
        return (16 + 6 * (self.wallet - 1)) * (1 + 0.06 * self.hive_lv("income"))

    @property
    def wallet_cost(self):
        return 80 * self.wallet

    def wallet_cd(self):
        """Cada nivell de moneder: -3% de temps de recàrrega de les abelles."""
        ev = 0.9 if (not self.headless and current_event()["id"] == "swarm") else 1.0
        return (1.0 - 0.03 * (self.wallet - 1)) * ev

    def wallet_loot(self):
        """Cada nivell de moneder: +4% de diners per enemic derrotat."""
        return 1.0 + 0.04 * (self.wallet - 1)

    def add_shake(self, a):
        if not self.headless and self.sv["opts"].get("flashes", True):
            self.shake = max(self.shake, a)

    def swarm_cd(self):
        return max(25.0, 50.0 - 2.5 * self.hive_lv("swarm"))

    def heal_cd(self):
        return max(35.0, 70.0 - 3.5 * self.hive_lv("heal"))

    def use_swarm(self):
        if self.abil_cd[0] > 0 or not self.deck:
            return
        cheap = min(self.deck, key=lambda b: b["cost"])
        lv = self.hive_lv("swarm")
        for k in range(4 + lv // 2):
            d = dict(cheap)
            m = lvl_mult(self.sv["owned"].get(d["key"], 1)) * (EVO_MULT if self.sv["evo"].get(d["key"]) else 1.0)
            f = 0.8 + 0.03 * lv
            d["hp"], d["atk"], d["evo"] = cheap["hp"] * m * f, cheap["atk"] * m * f, False
            u = Unit(d, 0)
            u.x += k * 14
            self.cats.append(u)
        self.abil_cd[0] = self.swarm_cd()
        self.abil_used += 1
        self.spawn_fx("fx_royal", CAT_BASE_X + 60, GROUND - 20, fps=11)
        sfx("ability")

    def use_heal(self):
        if self.abil_cd[1] > 0:
            return
        lv = self.hive_lv("heal")
        for a in self.cats:
            a.hp = min(a.max, a.hp + a.max * (0.35 + 0.025 * lv))
            self.spawn_fx("fx_heal", a.x, a.y - a.d["hover"] - 40)
        self.cat_base.hp = min(self.cat_base.max, self.cat_base.hp + self.cat_base.max * (0.12 + 0.01 * lv))
        self.abil_cd[1] = self.heal_cd()
        self.abil_used += 1
        sfx("ability")

    def lose_hint(self):
        tips = []
        rec = self.stage.get("rec", 1)
        lvs = [self.sv["owned"].get(d["key"], 1) for d in self.deck] or [1]
        avg = sum(lvs) / len(lvs)
        if not self.stage.get("survival") and avg < rec - 0.5:
            tips.append("Les teves abelles són de nivell %d i es recomana %d: millora-les." % (avg, rec))
        if self.air_spawned >= 4 and not any(d["air"] for d in self.deck):
            tips.append("Hi havia voladors i no portaves tiradors ni antiaèries.")
        if self.time > 40 and self.t_full > 0.25 * self.time:
            tips.append("Tenies els diners al màxim molt de temps: gasta'ls o puja el moneder.")
        if self.cannons_used == 0 and self.time > 60:
            tips.append("No has usat la trompa de pol·len (ESPAI).")
        if self.abil_used == 0 and self.time > 60:
            tips.append("Prova l'Eixam (Q) i la Cura (E) per remuntar.")
        if len({d["role"] for d in self.deck}) < 3:
            tips.append("Combina 3 rols diferents per guanyar +8% de vida.")
        return tips[:2] or ["Torna-ho a provar amb una altra combinació!"]

    def synergy(self):
        return len({b["role"] for b in self.deck}) >= 3

    def spawn_bee(self, i):
        if i >= len(self.deck):
            return
        d0 = self.deck[i]
        if self.cds[i] <= 0 and self.money >= d0["cost"]:
            self.money -= d0["cost"]
            self.cds[i] = d0["cd"] * (1 - 0.03 * self.hive_lv("cdr")) * self.wallet_cd()
            d = dict(d0)
            m = lvl_mult(self.sv["owned"].get(d["key"], 1))
            d["evo"] = bool(self.sv["evo"].get(d["key"]))
            if d["evo"]:
                m *= EVO_MULT
            d["hp"] = d0["hp"] * m * (1.08 if self.synergy() else 1.0)
            d["atk"] = d0["atk"] * m
            self.cats.append(Unit(d, 0))
            self.spawned += 1
            self.spawned_by[d["key"]] = self.spawned_by.get(d["key"], 0) + 1
            sfx("buzz")

    def upgrade_wallet(self):
        if self.wallet < WALLET_MAX and self.money >= self.wallet_cost:
            self.money -= self.wallet_cost
            self.wallet += 1
            sfx("coin")

    def muzzle(self):
        return CAT_BASE_X - 70 + 108, GROUND + 28 - 180 - 24

    def fire_cannon(self):
        if self.cannon >= self.cannon_time:
            self.cannon = 0
            self.cannons_used += 1
            self.cannon_vis = 0.8
            self.kick = 0.4
            mx, my = self.muzzle()
            self.spawn_fx("fx_muzzle", mx + 14, my - 2, fps=14)
            self.puff(mx, my, (240, 214, 90), 16)
            self.puff(mx - 6, my + 4, (214, 208, 196), 6)
            self.shots.append(dict(x0=mx, y0=my, x1=self.enemy_base.x, y1=GROUND - 80, t=0.0, dur=0.5,
                                   img=None if self.headless else pollen_img(3.0), cb=lambda: None))
            self.pollen = [(random.uniform(0, 260), random.uniform(20, UI_Y - 20),
                            random.uniform(0.8, 2.0)) for _ in range(90)]
            for e in self.enemies:
                e.damage(self.cannon_dmg)
                e.knock()
            self.enemy_base.damage(self.cannon_dmg)
            self.spawn_fx("fx_hit", self.enemy_base.x, GROUND - 50)
            self.add_shake(0.5)
            sfx("cannon")

    # ----------------------------------------------------- ATACS
    def spawn_fx(self, name, x, y, flip=False, fps=14):
        self.fx.append(dict(name=name, x=x, y=y, t=0.0, fps=fps, flip=flip))

    def after(self, delay, fn):
        self.events.append([delay, fn])

    @staticmethod
    def tpos(t):
        if isinstance(t, Base):
            return t.x, GROUND - 50
        return t.x, t.y - t.d["hover"] - 22

    def foes_of(self, u):
        return self.enemies if u.side == 0 else self.cats

    def allies_of(self, u):
        return self.cats if u.side == 0 else self.enemies

    def hurt(self, u, t, amt):
        """Aplica dany i, si l'atacant és una abella, el compta per al resum."""
        if not isinstance(t, Base) and t.hp <= 0:
            return
        if u.side == 0 and not isinstance(t, Base) and t.d["hover"] >= 30 and not u.d.get("air"):
            amt *= 0.7                       # els voladors esquiven part dels atacs cos a cos
        t.damage(amt)
        if not self.headless and len(self.floats) < 36 and not isinstance(t, Base) and amt >= 1:
            tx_, ty_ = self.tpos(t)
            self.floats.append([tx_ + random.uniform(-12, 12), ty_ - 20, 0.55, str(int(amt)),
                                (255, 250, 232) if u.side == 0 else (255, 130, 120), False])
        if u.side == 0:
            k = u.d["key"]
            self.dmg_by[k] = self.dmg_by.get(k, 0) + amt

    def deal(self, u, t, mult=1.0, fx="fx_hit"):
        if not isinstance(t, Base) and t.hp <= 0:
            return
        self.hurt(u, t, u.d["atk"] * mult)
        x, y = self.tpos(t)
        self.spawn_fx(fx, x + random.uniform(-4, 4), y + random.uniform(-4, 4), flip=(u.side == 1))

    def splash(self, u, cx, radius, mult, knock=False, exclude=None):
        for f in self.foes_of(u):
            if f is not exclude and abs(f.x - cx) <= radius and f.hp > 0:
                self.hurt(u, f, u.d["atk"] * mult)
                if knock:
                    f.knock()

    def shoot(self, u, t):
        s = u.d["style"]
        x0, y0 = u.x + u.dir * 12, u.y - u.d["hover"] - 22
        x1, y1 = self.tpos(t)

        def land():
            unit = not isinstance(t, Base)
            if s == "mud":
                self.deal(u, t, 1.0, "fx_mud")
                if unit:
                    t.slow_t = 2.5
            elif s == "pollen":
                self.deal(u, t, 1.0, "fx_pollen")
                self.splash(u, t.x, 48, 0.5, exclude=t)
            elif s == "web":
                self.deal(u, t, 1.0, "fx_web")
                if unit:
                    t.slow_t = 2.2
            elif s == "dust":
                self.deal(u, t, 1.0, "fx_pollen")
                for f in self.foes_of(u):
                    if f.hp > 0 and abs(f.x - t.x) <= 45:
                        f.slow_t = 2.5
            elif s == "webvenom":
                self.deal(u, t, 1.0, "fx_web")
                if unit:
                    t.slow_t = 2.2
                    t.poison_t, t.poison_dps, t.pfx_name = 3.0, u.d["atk"] * 0.25, "fx_poison"
            elif s == "tongue":
                self.deal(u, t, 1.0, "fx_hit_r")
                if unit:
                    t.x += -u.dir * 42
            else:
                self.deal(u, t, 1.0, "fx_hit_g")
                if unit:
                    t.slow_t = 1.4
        self.shots.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, t=0.0, dur=0.16 + abs(x1 - x0) / 900,
                               img=IMG[u.d["proj"]], cb=land))

    def do_attack(self, u, t):
        unit = not isinstance(t, Base)
        tx, ty = self.tpos(t)
        ATTACK_TABLE.get(u.d["style"], _a_sting)(self, u, t, unit, tx, ty)
        sfx(STYLE_SFX.get(u.d["style"], "sting" if u.side == 0 else "hit"), 0.7)

    # ----------------------------------------------- NIVELLS: hordes, perills i jefe
    def banner_say(self, text, snd="warn"):
        self.banner = [text, 3.2]
        sfx(snd)

    def spawn_enemy(self, eid):
        d = dict(ENEMIES[eid])
        d["id"] = eid
        d["atk"] = d["atk"] * self.stage.get("amult", 1.0)
        self.enemies.append(Unit(d, 1, self.stage["mult"]))
        if d["hover"] >= 30:
            self.air_spawned += 1

    def spawn_group(self, units):
        k = 0
        for eid, n in units:
            for _ in range(n):
                self.after(k * 0.35, lambda e=eid: self.spawn_enemy(e))
                k += 1

    def add_marker(self, x, kind, dmg, delay=1.2):
        self.haz.append(dict(x=x, t=delay, t0=delay, kind=kind, dmg=dmg))
        sfx("warn")

    def barrage(self, n, dmg):
        for i in range(n):
            if self.cats and random.random() < 0.75:
                x = random.choice(self.cats).x + random.uniform(-22, 22)
            else:
                x = random.uniform(220, 720)
            self.add_marker(max(120, min(ENEMY_BASE_X - 60, x)), "sting", dmg, 1.1 + 0.12 * i)

    def trigger_marker(self, m):
        x, kind, dmg = m["x"], m["kind"], m["dmg"]
        if kind == "lava":
            self.spawn_fx("fx_lava", x, GROUND - 52)
            rad, both = 58, True
        elif kind == "lightning":
            self.spawn_fx("fx_bolt", x, GROUND - 100)
            self.flash = 0.22
            rad, both = 52, True
        elif kind == "rock":
            self.spawn_fx("fx_rock", x, GROUND - 40, fps=12)
            rad, both = 46, True
        elif kind == "ice":
            self.spawn_fx("fx_ice", x, GROUND - 30, fps=12)
            rad, both = 56, True
        else:
            self.spawn_fx("fx_stinger", x, GROUND - 82, fps=16)
            self.spawn_fx("fx_ring", x, GROUND + 14, fps=12)
            rad, both = 50, False
        sfx("boom")
        self.add_shake(0.25)
        victims = list(self.cats) + (list(self.enemies) if both else [])
        for u in victims:
            if u.hp > 0 and abs(u.x - x) <= rad:
                u.damage(dmg)
                u.knock()
                if kind == "lava":
                    u.poison_t, u.poison_dps, u.pfx_name = 2.0, 18.0, "fx_burn"
                elif kind == "ice":
                    u.slow_t = 3.0
                elif kind == "rock":
                    u.stun_t = 0.4

    def next_event(self):
        best = None
        for i, ev in enumerate(self.stage.get("events", [])):
            if i not in self.ev_done:
                rem = ev["t"] - self.time
                if best is None or rem < best[0]:
                    best = (rem, ev["msg"].replace("ALERTA: ", "").rstrip("!"))
        return best

    def tutorial_text(self):
        if self.sv.get("tutorial_done") or self.stage_i != 0 or self.state != "play" or self.headless:
            return None
        if self.spawned < 1:
            return "Prem 1 (o clica el botó) per generar una abella"
        if self.wallet < 2 and self.time < 60 and self.cannons_used < 1:
            return "Els diners pugen sols. Prem W per millorar el rusc i guanyar-ne més"
        if self.cannons_used < 1:
            return "Quan la trompa estigui carregada, prem ESPAI per disparar-lo!"
        self.sv["tutorial_done"] = True
        self.save()
        return None

    def update_level(self, dt):
        st = self.stage
        if st.get("survival"):
            t = self.time
            st["mult"] = st["mult0"] * (1 + t / 100.0)
            st["amult"] = st["amult0"] * (1 + t / 220.0)
            st["cap"] = min(18, 9 + int(t // 60))
            self.surv_t -= dt
            if self.surv_t <= 0 and len(self.enemies) < st["cap"]:
                self.surv_t = max(1.1, 5.0 - t / 70.0)
                self.spawn_enemy(random.choice(st["pool"]))
            self.surv_boss -= dt
            if self.surv_boss <= 0:
                self.surv_boss = 80.0
                if st["minis"]:
                    eid = random.choice(st["minis"])
                    self.banner_say("ALERTA: " + ENEMIES[eid]["name"] + "!")
                    self.spawn_enemy(eid)
                else:
                    self.banner_say("Horda!")
                    self.spawn_group([(random.choice(st["pool"]), 6)])
        for i, ev in enumerate(st.get("events", [])):
            if i not in self.ev_done and self.time >= ev["t"]:
                self.ev_done.add(i)
                self.banner_say(ev["msg"])
                self.spawn_group(ev["units"])
        hz = st.get("hazard")
        if hz:
            self.haz_t -= dt
            if self.haz_t <= 0:
                self.haz_t = hz["every"]
                for _ in range(hz["count"]):
                    self.add_marker(random.uniform(230, ENEMY_BASE_X - 130), hz["kind"], hz["dmg"])
        if st["boss"]:
            frac = self.enemy_base.hp / self.enemy_base.max
            ph = 0 if frac > 0.66 else (1 if frac > 0.33 else 2)
            if ph != self.phase:
                self.phase = ph
                self.banner_say(("", "FASE 2: LA REINA S'ENFURISMA!", "FASE 3: FÚRIA FINAL!")[ph], "roar")
                self.add_shake(0.5)
                self.flash = 0.3
                self.spawn_group([("wasp", 3 + 2 * ph)])
            b = self.boss_t
            b["barrage"] -= dt
            if b["barrage"] <= 0:
                b["barrage"] = (15.0, 11.0, 8.0)[ph]
                self.barrage((3, 4, 7)[ph], (100, 125, 150)[ph])
            b["spawn"] -= dt
            if b["spawn"] <= 0:
                b["spawn"] = (18.0, 14.0, 10.0)[ph]
                self.spawn_group([("wasp", (2, 3, 4)[ph])])
            if ph >= 1:
                b["guard"] -= dt
                if b["guard"] <= 0:
                    b["guard"] = 40.0 if ph == 1 else 28.0
                    self.spawn_group([("hornet_guard", 1)] + ([("wasp", 3)] if ph == 2 else []))
        for m in self.haz:
            m["t"] -= dt
        for m in [m for m in self.haz if m["t"] <= 0]:
            self.trigger_marker(m)
        self.haz = [m for m in self.haz if m["t"] > 0]
        self.banner[1] = max(0.0, self.banner[1] - dt)
        self.flash = max(0.0, self.flash - dt)

    def add_dying(self, u):
        if u.last_img is None:
            return
        self.dying.append(dict(img=u.last_img, x=float(u.last_c[0]), y=float(u.last_c[1]),
                               vx=-u.dir * random.uniform(30, 90), vy=random.uniform(-190, -110), rot=0.0,
                               rv=random.choice((-1, 1)) * random.uniform(240, 520), t=0.0))

    def puff(self, x, y, col, n=8):
        for _ in range(n):
            a = random.uniform(0, math.tau)
            s = random.uniform(30, 110)
            self.parts.append([x, y, math.cos(a) * s, math.sin(a) * s - 40,
                               random.uniform(0.4, 0.8), random.uniform(3, 6), col])

    def capture_deck(self):
        """Derrota final: les abelles que han lluitat perden tots els nivells i queden captives."""
        keys = [d["key"] for d in self.deck]
        self.captured_now = list(keys)
        for k in keys:
            if k in self.sv["owned"]:
                del self.sv["owned"][k]
                self.sv["evo"].pop(k, None)
                self.sv["captured"][k] = 0
        if not self.sv["owned"]:
            self.sv["owned"]["honey"] = 1
            self.sv["captured"].pop("honey", None)
        self.sv["deck"] = [k for k in self.sv["deck"] if k in self.sv["owned"]] or list(self.sv["owned"])[:3]

    def record_stats(self):
        for k in list(self.sv["captured"]):
            self.sv["captured"][k] += self.kills
            if self.sv["captured"][k] >= RESCUE_NEED[BEE_BY_KEY[k]["rarity"]]:
                self.sv["captured"].pop(k)
                self.gain_bee(k)
                self.rescued_now.append(k)
                self.ui_say("Has rescatat " + BEE_BY_KEY[k]["name"] + "!")
        st = self.sv["stats"]
        st["kills"] += self.kills
        st["spawned"] += self.spawned
        st["cannons"] += self.cannons_used
        st["time"] = st.get("time", 0.0) + self.time
        st["dmg"] = st.get("dmg", 0) + sum(self.dmg_by.values())
        bb = st.setdefault("by_bee", {})
        for k, n in self.spawned_by.items():
            bb[k] = bb.get(k, 0) + n
        self.kills = self.spawned = self.cannons_used = 0
        self.dmg_by, self.spawned_by = {}, {}

    def finish(self, win):
        dmg_list = sorted([(d["key"], self.dmg_by.get(d["key"], 0)) for d in self.deck], key=lambda kv: -kv[1])
        kills, tm = self.kills, self.time
        mel, pol, flags = self.mel_earned, 0, [False, False, False]
        i = self.stage_i
        if win:
            mel += int(STAGE_REWARD[i][0] * (1 + 0.05 * self.hive_lv("reward")))
            flags = [True, tm <= self.stage["par"], self.cannons_used == 0]
            stars = sum(flags)
            prev = self.sv["stars"].get(str(i), 0)
            if self.sv["progress"] < i + 1:
                self.sv["progress"] = i + 1
                pol += STAGE_REWARD[i][1]
            else:
                pol += 1                                   # repetició: petit premi
            pol += max(0, stars - max(prev, 1))            # estrelles noves
            if stars > prev:
                self.sv["stars"][str(i)] = stars
        survival = bool(self.stage.get("survival"))
        record = False
        ev = current_event()["id"] if not self.headless else ""
        if win and ev == "mel":
            mel = int(mel * 1.25)
        if win and ev == "pollen":
            pol += 1
        if survival and kills > self.sv.get("surv_kills", 0):
            self.sv["surv_kills"] = kills
        if survival:
            mel += int(tm * 3)
            pol += int(tm // 150)
            if tm > self.sv.get("surv_best", 0):
                self.sv["surv_best"] = tm
                record = True
        self.daily_add("kills", self.kills)
        self.daily_add("spawned", self.spawned)
        self.daily_add("cannons", self.cannons_used)
        if win:
            self.daily_add("wins")
        self.record_stats()
        st = self.sv["stats"]
        if not survival:
            st["wins" if win else "losses"] = st.get("wins" if win else "losses", 0) + 1
        self.sv["mel"] += mel
        self.sv["pollen"] += pol
        self.result = dict(win=win, mel=mel, pollen=pol, kills=kills, time=tm, flags=flags, dmg=dmg_list,
                           survival=survival, record=record,
                           hints=[] if win else self.lose_hint(), rescued=list(self.rescued_now))
        if self.stage.get("boss") and not survival and not self.headless:
            if not win:
                self.capture_deck()
            self.save()
            self.start_story("win" if win else "lose")
            return
        self.state = "win" if win else "lose"
        if not self.headless:
            self.trans = dict(t=0.35, dur=0.7, style="drip", color=(214, 170, 60) if win else (80, 40, 40),
                              label=None, apply=None, done=True)
        sfx("win" if win else "lose")
        self.save()

    def update(self, dt):
        self.time += dt
        self.shake = max(0.0, self.shake - dt * 1.6)
        self.abil_cd = [max(0.0, c - dt) for c in self.abil_cd]
        if self.money >= 0.95 * self.max_money:
            self.t_full += dt
        tag = "night" if (night_amount(self.time) > 0.6 or self.stage.get("night")) else "day"
        if tag != self.daytag:
            self.daytag = tag
            if not self.headless:
                self.banner_say("Es fa de nit..." if tag == "night" else "Surt el sol!", "warn")
        self.money = min(self.max_money, self.money + self.income * dt)
        self.cannon = min(self.cannon_time, self.cannon + dt)
        self.cds = [max(0, c - dt) for c in self.cds]
        self.cannon_vis = max(0, self.cannon_vis - dt)
        self.kick = max(0.0, self.kick - dt)
        rg = self.hive_lv("regen")
        if rg and self.cat_base.hp > 0:
            self.cat_base.hp = min(self.cat_base.max, self.cat_base.hp + self.cat_base.max * 0.0015 * rg * dt)

        for s, st in zip(self.stage["spawns"], self.spawn):
            if self.time >= st["t"] and st["n"] < s[3] and len(self.enemies) < self.stage["cap"]:
                self.spawn_enemy(s[0])
                st["n"] += 1
                st["t"] = self.time + s[2]
        self.update_level(dt)

        for u in self.cats + self.enemies:
            u.update(self, dt)
        for u in self.cats:
            if u.d["key"] == "nurse" and u.hp > 0:
                u.heal_t -= dt
                if u.heal_t <= 0:
                    u.heal_t = 2.0
                    healed = False
                    for a in self.cats:
                        if a is not u and a.hp > 0 and a.hp < a.max and abs(a.x - u.x) <= 150:
                            a.hp = min(a.max, a.hp + a.max * 0.10)
                            self.spawn_fx("fx_heal", a.x, a.y - a.d["hover"] - 40)
                            healed = True
                    if healed:
                        sfx("heal")

        for u in self.cats:
            if u.hp <= 0:
                self.puff(u.x, u.y - 25, (196, 170, 90))
                self.add_dying(u)
                sfx("die", 0.6)
        for e in self.enemies:
            if e.hp <= 0:
                self.add_dying(e)
                if e.d["reward"] >= 200:
                    self.add_shake(0.4)
                    self.hitstop = max(self.hitstop, 0.08)
                self.money = min(self.max_money, self.money + e.d["reward"] * (1 + 0.08 * self.hive_lv("bounty")) * self.wallet_loot())
                self.kills += 1
                self.mel_earned += max(1, e.d["reward"] // 2)
                if e.d["id"] not in self.sv["seen"]:
                    self.sv["seen"].append(e.d["id"])
                self.puff(e.x, e.y - 25, (120, 150, 100))
                self.floats.append([e.x, e.y - 50, 0.9, f"+{e.d['reward']}"])
                sfx("die", 0.5)
        self.cats = [c for c in self.cats if c.hp > 0]
        self.enemies = [e for e in self.enemies if e.hp > 0]
        for u in self.cats:
            u.x = max(CAT_BASE_X, u.x)
        for u in self.enemies:
            u.x = min(ENEMY_BASE_X, u.x)

        for p in self.parts:
            p[0] += p[2] * dt
            p[1] += p[3] * dt
            p[3] += 120 * dt
            p[4] -= dt
        self.parts = [p for p in self.parts if p[4] > 0]
        for f in self.floats:
            f[1] -= 30 * dt
            f[2] -= dt
        self.floats = [f for f in self.floats if f[2] > 0]
        for dd in self.dying:
            dd["t"] += dt
            dd["x"] += dd["vx"] * dt
            dd["y"] += dd["vy"] * dt
            dd["vy"] += 620 * dt
            dd["rot"] += dd["rv"] * dt
        self.dying = [dd for dd in self.dying if dd["t"] < 0.75]
        keep = []
        for s in self.shots:
            s["t"] += dt
            if s["t"] >= s["dur"]:
                s["cb"]()
            else:
                keep.append(s)
        self.shots = keep
        for e in self.events:
            e[0] -= dt
            if e[0] <= 0:
                e[1]()
        self.events = [e for e in self.events if e[0] > 0]
        for f in self.fx:
            f["t"] += dt
        self.fx = [f for f in self.fx if int(f["t"] * f["fps"]) < len(IMG[f["name"]])]

        if self.enemy_base.hp <= 0:
            self.finish(True)
        elif self.cat_base.hp <= 0:
            if not self.headless and self.continues < CONT_MAX:
                self.cont_prompt = True
                sfx("lose")
            else:
                self.finish(False)

    # ------------------------------------------------- RUSC, BOTIGA, DIÀRIES
    def hive_lv(self, key):
        return self.sv["hive"].get(key, 0)

    def hive_cost(self, key):
        u = HIVE_BY_ID[key]
        return int(u["base"] * (self.hive_lv(key) + 1) ** 1.45)

    def buy_hive(self, key):
        if key == "cannon":
            return self.upgrade_cannon()
        if self.hive_lv(key) >= HIVE_MAX or self.sv["mel"] < self.hive_cost(key):
            return
        self.sv["mel"] -= self.hive_cost(key)
        self.sv["hive"][key] = self.hive_lv(key) + 1
        sfx("coin")
        self.save()

    def toggle_armed(self, key):
        if self.sv["items"].get(key, 0) > 0:
            self.sv["armed"][key] = not self.sv["armed"].get(key, False)

    def refresh_daily(self):
        today = datetime.date.today().isoformat()
        dm = self.sv["dm"]
        if dm.get("date") != today:
            rnd = random.Random(today)
            self.sv["dm"] = dict(date=today, ids=[m["id"] for m in rnd.sample(DAILY_POOL, 3)], claimed=[], prog={})
        iso = datetime.date.today().isocalendar()
        wk_key = "%d-W%02d" % (iso[0], iso[1])
        if self.sv["wk"].get("week") != wk_key:
            rnd = random.Random(wk_key)
            self.sv["wk"] = dict(week=wk_key, ids=[m["id"] for m in rnd.sample(WEEKLY_POOL, 3)], claimed=[], prog={})
        self.shop_check()

    def daily_add(self, stat, n=1):
        if n:
            for key in ("dm", "wk"):
                p = self.sv[key]["prog"]
                p[stat] = p.get(stat, 0) + n

    def reward_text(self, m):
        parts = []
        if m.get("mel"):
            parts.append(f"{m['mel']} mel")
        if m.get("pollen"):
            parts.append(f"{m['pollen']} pol·len")
        return " i ".join(parts)

    def ui_say(self, text):
        self.ui_floats.append([text, 2.4])

    def weekly_prog(self, m):
        return min(m["val"], self.sv["wk"]["prog"].get(m["stat"], 0))

    def weekly_claimable(self):
        wk = self.sv["wk"]
        return sum(1 for mid in wk["ids"] if mid not in wk["claimed"] and self.weekly_prog(WEEKLY_BY_ID[mid]) >= WEEKLY_BY_ID[mid]["val"])

    def claim_weekly(self, mid):
        m = WEEKLY_BY_ID[mid]
        wk = self.sv["wk"]
        if mid in wk["claimed"] or self.weekly_prog(m) < m["val"]:
            return
        wk["claimed"].append(mid)
        self.sv["mel"] += m.get("mel", 0)
        self.sv["pollen"] += m.get("pollen", 0)
        self.ui_say("+" + self.reward_text(m))
        sfx("levelup")
        self.save()

    def daily_prog(self, m):
        return min(m["val"], self.sv["dm"]["prog"].get(m["stat"], 0))

    def daily_claimable(self):
        dm = self.sv["dm"]
        return sum(1 for mid in dm["ids"] if mid not in dm["claimed"] and self.daily_prog(DAILY_POOL_BY_ID[mid]) >= DAILY_POOL_BY_ID[mid]["val"])

    def claim_daily(self, mid):
        m = DAILY_POOL_BY_ID[mid]
        dm = self.sv["dm"]
        if mid in dm["claimed"] or self.daily_prog(m) < m["val"]:
            return
        dm["claimed"].append(mid)
        self.sv["mel"] += m.get("mel", 0)
        self.sv["pollen"] += m.get("pollen", 0)
        self.ui_say("+" + self.reward_text(m))
        sfx("coin")
        self.save()

    def gift_ready(self):
        return self.sv.get("daily", "") != datetime.date.today().isoformat()

    def claim_gift(self):
        today = datetime.date.today()
        if not self.gift_ready():
            self.say("Ja has recollit el regal d'avui.")
            return
        last = self.sv.get("daily", "")
        yest = (today - datetime.timedelta(days=1)).isoformat()
        self.sv["streak"] = self.sv.get("streak", 0) + 1 if last == yest else 1
        n = min(self.sv["streak"], 7)
        mel, pol = 100 + 50 * n, 1 + n // 3
        self.sv["mel"] += mel
        self.sv["pollen"] += pol
        self.sv["daily"] = today.isoformat()
        self.ui_say(f"Regal: +{mel} mel i +{pol} pol·len")
        sfx("reveal")
        self.save()

    # --- botiga (tot amb pol·len)
    def shop_slot(self):
        n = datetime.datetime.now()
        return "%s-%d" % (n.date().isoformat(), n.hour // 12)

    def shop_check(self):
        sh = self.sv["shop"]
        if sh.get("slot") != self.shop_slot():
            sh["slot"], sh["bee_bought"], sh["lvl_bought"] = self.shop_slot(), False, False
        today = datetime.date.today().isoformat()
        if sh.get("day") != today:
            sh["day"], sh["mel"] = today, {}

    def shop_timer(self):
        n = datetime.datetime.now()
        secs = (12 - n.hour % 12) * 3600 - n.minute * 60 - n.second
        return "%dh %02dm" % (secs // 3600, (secs % 3600) // 60)

    def shop_offer(self):
        rnd = random.Random(self.shop_slot())
        new = [b for b in BEE_UNITS if b["key"] not in self.sv["owned"]]
        if new:
            b = rnd.choice(new)
            return dict(key=b["key"], kind="new", cost=BEE_PRICE[b["rarity"]])
        low = [b for b in BEE_UNITS if self.sv["owned"].get(b["key"], 0) < MAX_LV] or BEE_UNITS
        return dict(key=rnd.choice(low)["key"], kind="lvl", cost=30)

    def shop_offer2(self):
        rnd = random.Random(self.shop_slot() + "b")
        low = [b for b in BEE_UNITS if 0 < self.sv["owned"].get(b["key"], 0) < MAX_LV]
        pick = rnd.choice(low) if low else BEE_UNITS[0]
        return dict(key=pick["key"], kind="lvl", cost=30)

    def buy_offer2(self):
        of = self.shop_offer2()
        sh = self.sv["shop"]
        if sh.get("lvl_bought") or self.sv["pollen"] < of["cost"] or of["key"] not in self.sv["owned"]:
            return
        if self.sv["owned"][of["key"]] >= MAX_LV:
            return
        self.sv["pollen"] -= of["cost"]
        sh["lvl_bought"] = True
        self.sv["owned"][of["key"]] += 1
        self.say("Compra feta: +1 nivell a " + BEE_BY_KEY[of["key"]]["name"])
        sfx("coin")
        self.save()

    def buy_offer(self):
        of = self.shop_offer()
        sh = self.sv["shop"]
        if sh["bee_bought"] or self.sv["pollen"] < of["cost"]:
            return
        self.sv["pollen"] -= of["cost"]
        sh["bee_bought"] = True
        if of["kind"] == "new":
            self.gain_bee(of["key"])
            self.sv["pollen"] = self.sv["pollen"]
            self.save()
            self.show_newbee(of["key"], "shop")
        elif self.sv["owned"].get(of["key"], 0) < MAX_LV:
            self.sv["owned"][of["key"]] += 1
        self.say("Compra feta: " + BEE_BY_KEY[of["key"]]["name"])
        sfx("coin")
        self.save()

    def buy_mel(self, i):
        pol, mel, lim = SHOP_MEL[i]
        used = self.sv["shop"]["mel"].get(str(i), 0)
        if used >= lim or self.sv["pollen"] < pol:
            return
        self.sv["pollen"] -= pol
        self.sv["mel"] += mel
        self.sv["shop"]["mel"][str(i)] = used + 1
        sfx("coin")
        self.save()

    def buy_item(self, key):
        it = next(x for x in SHOP_ITEMS if x["id"] == key)
        if self.sv["pollen"] < it["cost"]:
            return
        self.sv["pollen"] -= it["cost"]
        self.sv["items"][key] = self.sv["items"].get(key, 0) + it["n"]
        sfx("coin")
        self.save()

    def buy_slot(self):
        if self.sv["slot6"] or self.sv["pollen"] < SHOP_SLOT_COST:
            return
        self.sv["pollen"] -= SHOP_SLOT_COST
        self.sv["slot6"] = True
        self.say("Ara pots portar 6 abelles!")
        sfx("coin")
        self.save()



# ------------------------------------------------------------ MODE --simulate (sense gràfics)
def run_simulation(argv):
    """Juga cada nivell amb un bot i mostra % de victòries i temps. Serveix per equilibrar amb dades."""
    global IMG
    IMG = HeadlessImg()

    def arg(name, default):
        if name in argv:
            try:
                return int(argv[argv.index(name) + 1])
            except (ValueError, IndexError):
                return default
        return default
    runs, only, lv_over = arg("--runs", 5), arg("--stage", 0), arg("--lv", 0)
    legends = "--legends" in argv
    clear = {m["val"]: m["bee"] for m in MISSIONS if m["kind"] == "stage" and m.get("bee")}
    print("Nivell                          Nv  Victòries  Temps mitjà  Equip")
    for si, s in enumerate(STAGES):
        if only and si + 1 != only:
            continue
        own = ["honey", "leafcutter", "bumble"] + [clear[k] for k in sorted(clear) if k <= si]
        if legends:
            own += ["killer", "giant", "queen"]
        by_cost = sorted(own, key=lambda k: -BEE_BY_KEY[k]["cost"])
        top = [k for k in by_cost if k != "guard"][:4]
        tanks = sorted([k for k in own if k not in top], key=lambda k: -BEE_BY_KEY[k]["hp"])
        if tanks:
            top.append(tanks[0])
        deck = sorted(top[:5], key=lambda k: -BEE_BY_KEY[k]["cost"])
        lv = lv_over or s["rec"]
        wins, tsum = 0, 0.0
        for run in range(runs):
            random.seed(1000 * si + run)
            g = Game(headless=True)
            g.sv["owned"] = {k: lv for k in own}
            if si >= 17 or "--evo" in argv:
                g.sv["evo"] = {k: True for k in own}
            g.sv["deck"] = deck
            g.sv["cannon"] = min(MAX_CANNON, 1 + lv // 2)
            g.start(si)
            for _ in range(int(900 / STEP)):
                if g.wallet < 5:
                    g.upgrade_wallet()
                if g.cannon >= g.cannon_time and len(g.enemies) >= 3:
                    g.fire_cannon()
                for i in range(len(g.deck)):
                    if g.cds[i] <= 0:
                        if g.money >= g.deck[i]["cost"]:
                            g.spawn_bee(i)
                        elif g.money >= 0.7 * g.deck[i]["cost"]:
                            break          # estalvia uns segons per a l'abella cara
                g.update(STEP)
                if g.state != "play":
                    break
            if g.state == "win":
                wins += 1
                tsum += g.time
        avg = f"{tsum / wins:6.0f} s" if wins else "     -  "
        print(f"{s['name'][:30]:<30}  {lv:>2}  {100 * wins // runs:>7}%   {avg}    {','.join(deck)}")


# ------------------------------------------------------------ PRINCIPAL
def init_display():
    global screen, clock
    try:
        screen = pygame.display.set_mode((W, H), pygame.SCALED | pygame.RESIZABLE)
    except Exception:
        screen = pygame.display.set_mode((W, H))
    pygame.display.set_caption("The BattleBees")
    clock = pygame.time.Clock()


def loading_screen(frac, label):
    screen.fill((24, 20, 18))
    t = FONT_M.render(label, True, C_TXT)
    screen.blit(t, t.get_rect(center=(W // 2, H // 2)))
    t2 = FONT_S.render("(la primera vegada triga uns segons; després es desa i va a l'instant)", True, C_GOLD)
    screen.blit(t2, t2.get_rect(center=(W // 2, H // 2 + 36)))
    pygame.draw.rect(screen, C_BORDER, (W // 2 - 202, H // 2 + 62, 404, 24))
    pygame.draw.rect(screen, C_GOLD, (W // 2 - 200, H // 2 + 64, int(400 * frac), 20))
    bx, by = W // 2 - 200 + int(400 * frac), H // 2 + 116 + int(6 * math.sin(frac * 40))
    pygame.draw.ellipse(screen, (240, 190, 40), (bx - 16, by - 10, 32, 20))
    for k in range(3):
        pygame.draw.line(screen, (40, 28, 10), (bx - 8 + k * 8, by - 9), (bx - 8 + k * 8, by + 9), 3)
    pygame.draw.ellipse(screen, (200, 224, 255), (bx - 8, by - 26, 18, 16))
    pygame.draw.circle(screen, (40, 28, 10), (bx + 18, by - 2), 7)
    pygame.display.flip()
    pygame.event.pump()


async def main():
    global IMG
    argv = sys.argv
    if "--simulate" in argv:
        run_simulation(argv)
        return
    if "--export" in argv:
        export_sprites()
        return
    try:
        pygame.mixer.pre_init(SR, -16, 1, 512, allowedchanges=0)
    except TypeError:
        pygame.mixer.pre_init(SR, -16, 1, 512)
    pygame.init()
    init_display()
    make_fonts(False)
    IMG = load_images(lambda fr: loading_screen(fr, "Generant sprites..."))
    audio_init(get_audio(lambda fr: loading_screen(fr, "Generant so i música...")))
    g = Game()
    if g.sv["opts"]["bigfont"]:
        make_fonts(True)
    if g.sv["opts"]["fullscreen"]:
        try:
            pygame.display.toggle_fullscreen()
        except Exception:
            pass
    apply_audio()
    acc = 0.0
    try:
        while True:
            dt = min(clock.tick(60) / 1000, 0.1)
            g.anim += dt
            g.tick_ui(dt)
            for ev in pygame.event.get():
                if ev.type == pygame.QUIT:
                    return
                if ev.type == pygame.KEYDOWN:
                    if ev.key == pygame.K_F11:
                        g.toggle_opt("fullscreen")
                    elif g.state in ("intro", "tutorial"):
                        g.story_key(ev.key)
                    elif g.state == "dialogue" and ev.key == pygame.K_ESCAPE:
                        g.dlg_skip_all()
                    elif g.state == "capsule_open" and ev.key in (pygame.K_SPACE, pygame.K_RETURN):
                        g.cap_tap()
                    elif g.state == "capsule_multi" and ev.key in (pygame.K_SPACE, pygame.K_RETURN):
                        g.cap_multi_click()
                    elif ev.key in (pygame.K_ESCAPE, pygame.K_p, pygame.K_PAUSE):
                        if g.state == "play":
                            g.toggle_pause()
                        elif ev.key == pygame.K_ESCAPE:
                            if g.state in ("capsule_open", "capsule_multi"):
                                g.go("capsules")
                            elif g.state == "base" or g.state in ("stats", "options", "help"):
                                g.go("title")
                            elif g.state == "newbee":
                                g.go(g.newbee[1])
                            elif g.state not in ("title", "win", "lose"):
                                g.go("base")
                    elif g.state == "dialogue" and ev.key in (pygame.K_SPACE, pygame.K_RETURN, pygame.K_RIGHT):
                        g.dlg_advance()
                    elif g.state == "dialogue" and ev.key == pygame.K_ESCAPE:
                        g.dlg_skip_all()
                    elif g.state == "play" and not g.paused and not g.cont_prompt:
                        if ev.key in KEYS:
                            g.spawn_bee(KEYS.index(ev.key))
                        elif ev.key == pygame.K_w:
                            g.upgrade_wallet()
                        elif ev.key == pygame.K_q:
                            g.use_swarm()
                        elif ev.key == pygame.K_e:
                            g.use_heal()
                        elif ev.key == pygame.K_SPACE:
                            g.fire_cannon()
                        elif ev.key == pygame.K_TAB:
                            g.toggle_speed()
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    if g.trans:
                        pass
                    elif g.state == "dialogue":
                        if not g.click(ev.pos):
                            g.dlg_advance()
                    elif g.state == "play" and not g.paused and not g.cont_prompt:
                        if g.btn_speed.collidepoint(ev.pos):
                            g.toggle_speed()
                        elif g.btn_pause.collidepoint(ev.pos):
                            g.toggle_pause()
                        for i, r in enumerate(g.btn_units):
                            if r.collidepoint(ev.pos):
                                g.spawn_bee(i)
                        if g.btn_wallet.collidepoint(ev.pos):
                            g.upgrade_wallet()
                        if g.btn_cannon.collidepoint(ev.pos):
                            g.fire_cannon()
                        if g.btn_abil[0].collidepoint(ev.pos):
                            g.use_swarm()
                        if g.btn_abil[1].collidepoint(ev.pos):
                            g.use_heal()
                    elif g.state == "capsule_open":
                        if not g.click(ev.pos):
                            g.cap_tap()
                    elif g.state == "capsule_multi":
                        if not g.click(ev.pos):
                            g.cap_multi_click()
                    elif g.state in ("intro", "tutorial"):
                        if not g.click(ev.pos):
                            if g.state == "intro":
                                g.intro_advance()
                            else:
                                g.tut_step(1)
                    else:
                        g.click(ev.pos)
            if g.state == "play" and not g.paused and not g.trans and not g.cont_prompt and g.hitstop > 0:
                g.hitstop -= dt
            elif g.state == "play" and not g.paused and not g.trans and not g.cont_prompt:
                acc += dt * g.speed
                n = 0
                while acc >= STEP and n < 6 and g.state == "play":
                    g.update(STEP)
                    acc -= STEP
                    n += 1
                acc = min(acc, STEP * 2)
            else:
                acc = 0.0
            if g.quit_req:
                return
            if g.state == "intro":
                music_play(g.story_music())
            else:
                music_play(MUSIC_BY_BG.get(g.stage["bg"], "calm") if g.state in ("play", "win", "lose") else "calm")
            g.draw()
            pygame.display.flip()
            await asyncio.sleep(0)
    finally:
        g.save()
        pygame.quit()


if __name__ == "__main__":
     asyncio.run(main())
