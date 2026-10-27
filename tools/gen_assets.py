"""Genera las imágenes del juego (texturas, cielo, zombis, armas) en la carpeta assets/.
Se ejecuta una vez a mano: python tools/gen_assets.py   (necesita Pillow y numpy)"""
import os, math, random
import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")
os.makedirs(OUT, exist_ok=True)
rng = np.random.default_rng(7)
random.seed(7)


def save(img, name):
    img.save(os.path.join(OUT, name), optimize=True)


def noise(w, h, amp=12):
    return rng.normal(0, amp, (h, w, 1))


def to_img(arr):
    return Image.fromarray(np.clip(arr, 0, 255).astype("uint8"))


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


# ------------------------------------------------------------------ texturas de pared (64x64)
def brick():
    W = H = 64
    arr = np.zeros((H, W, 3))
    arr[:] = (176, 168, 156)                                  # mortero
    for row in range(8):
        off = 0 if row % 2 == 0 else 8
        for k in range(-1, 5):
            x0 = k * 16 + off
            tone = rng.uniform(-18, 18)
            col = np.array((150 + tone, 82 + tone * 0.6, 62 + tone * 0.5))
            y0, y1 = row * 8 + 1, row * 8 + 7
            xa, xb = max(0, x0 + 1), min(W, x0 + 15)
            if xb > xa:
                arr[y0:y1, xa:xb] = col
                arr[y0:y0 + 1, xa:xb] *= 1.12                  # luz arriba
                arr[y1 - 1:y1, xa:xb] *= 0.82                  # sombra abajo
    arr += noise(W, H, 9)
    grime = np.linspace(0.0, 0.18, H).reshape(H, 1, 1)
    arr *= (1 - grime)
    return to_img(arr)


def wood(w, h, base, vertical=True, planks=5):
    arr = np.zeros((h, w, 3))
    for i in range(planks):
        tone = rng.uniform(-14, 14)
        col = np.array(base) + tone
        if vertical:
            x0, x1 = i * w // planks, (i + 1) * w // planks
            arr[:, x0:x1] = col
            arr[:, x0:x0 + 1] *= 0.55
            for _ in range(5):                                  # vetas
                x = rng.integers(x0 + 1, max(x0 + 2, x1 - 1))
                arr[:, x:x + 1] *= rng.uniform(0.86, 0.95)
        else:
            y0, y1 = i * h // planks, (i + 1) * h // planks
            arr[y0:y1] = col
            arr[y0:y0 + 1] *= 0.55
    arr += noise(w, h, 6)
    return arr


def door():
    arr = wood(64, 64, (132, 86, 50), True, 5)
    arr[0:4] *= 0.6; arr[:, 0:3] *= 0.6; arr[:, 61:] *= 0.6   # marco
    for (x0, y0, x1, y1) in ((10, 8, 54, 28), (10, 34, 54, 58)):   # paneles
        arr[y0:y1, x0:x1] *= 0.86
        arr[y0:y0 + 1, x0:x1] *= 0.65; arr[y0:y1, x0:x0 + 1] *= 0.65
        arr[y1 - 1:y1, x0:x1] *= 1.18; arr[y0:y1, x1 - 1:x1] *= 1.18
    img = to_img(arr)
    d = ImageDraw.Draw(img)
    d.ellipse((48, 31, 54, 37), fill=(214, 178, 84), outline=(120, 90, 30))   # picaporte
    return img


def window():
    base = np.array(brick())
    img = Image.fromarray(base)
    d = ImageDraw.Draw(img)
    d.rectangle((10, 10, 53, 54), fill=(226, 224, 216))             # marco
    glass = Image.new("RGB", (36, 36))
    gd = ImageDraw.Draw(glass)
    for y in range(36):
        gd.line((0, y, 36, y), fill=lerp((118, 160, 190), (60, 92, 120), y / 35))
    gd.polygon([(2, 34), (16, 2), (24, 2), (10, 34)], fill=(168, 204, 224))   # reflejo
    img.paste(glass, (14, 14))
    d.rectangle((31, 14, 33, 49), fill=(226, 224, 216))
    d.rectangle((14, 30, 49, 33), fill=(226, 224, 216))
    d.rectangle((8, 54, 55, 58), fill=(190, 186, 176))                       # alféizar
    return img


def tree():
    W = H = 64
    arr = np.zeros((H, W, 3))
    arr[:] = (36, 84, 42)
    img = to_img(arr)
    d = ImageDraw.Draw(img)
    for _ in range(90):                                          # follaje
        x, y = rng.integers(-4, 68), rng.integers(-4, 44)
        r = rng.integers(4, 10)
        g = int(rng.integers(70, 130))
        d.ellipse((x - r, y - r, x + r, y + r), fill=(int(g * 0.35), g, int(g * 0.4)))
    d.rectangle((24, 38, 40, 64), fill=(86, 58, 36))             # tronco
    for x in range(26, 40, 4):
        d.line((x, 38, x + int(rng.integers(-2, 3)), 64), fill=(58, 38, 24), width=1)
    d.rectangle((0, 40, 22, 64), fill=(34, 78, 40))
    d.rectangle((42, 40, 64, 64), fill=(34, 78, 40))
    arr = np.array(img).astype(float) + noise(W, H, 8)
    return to_img(arr)


def metal_crate(base=(150, 108, 52)):
    arr = wood(64, 64, base, False, 4)
    arr[0:3] *= 0.6; arr[61:] *= 0.6; arr[:, 0:3] *= 0.6; arr[:, 61:] *= 0.6
    return to_img(arr)


# ------------------------------------------------------------------ cielo y suelo
def periodic_noise(w, h, cells, seed):
    r = np.random.default_rng(seed)
    g = r.random((cells[1], cells[0]))
    img = Image.fromarray((g * 255).astype("uint8")).resize((w, h), Image.BICUBIC)
    return np.array(img).astype(float) / 255.0


def sky():
    W, H = 1024, 200
    top, bot = np.array((70, 128, 214)), np.array((186, 214, 240))
    t = np.linspace(0, 1, H).reshape(H, 1, 1)
    arr = top * (1 - t) + bot * t
    arr = np.repeat(arr, W, axis=1)
    cl = np.zeros((H, W))
    for k, (cx, cy, amp) in enumerate(((4, 3, 0.55), (8, 6, 0.3), (16, 12, 0.15))):
        # ruido que se repite a los lados (cielo continuo al girar)
        base = periodic_noise(W * 2, H * 2, (cx * 2, cy * 2), 11 + k)
        cl += base[H // 2:H // 2 + H, W // 2:W // 2 + W] * amp
        # costura: mezclar bordes
    seam = np.minimum(1, np.minimum(np.arange(W), W - 1 - np.arange(W)) / 60.0)
    cl = cl * seam + np.roll(cl, W // 2, axis=1) * (1 - seam)
    cl = np.clip((cl - 0.42) * 2.6, 0, 1) * np.linspace(1.0, 0.25, H).reshape(H, 1)
    arr = arr * (1 - cl[..., None]) + np.array((252, 252, 255)) * cl[..., None]
    return to_img(arr)


def ground(kind):
    W, H = 256, 48
    if kind == "grass":
        base = np.array((62, 100, 52)); amp = 14
    elif kind == "road":
        base = np.array((86, 86, 92)); amp = 9
    else:
        base = np.array((120, 94, 68)); amp = 8
    arr = np.zeros((H, W, 3)) + base
    arr += rng.normal(0, amp, (H, W, 1))
    for _ in range(260 if kind == "grass" else 90):
        x, y = rng.integers(0, W), rng.integers(0, H)
        arr[y, x] *= rng.uniform(0.6, 1.35)
        if kind == "grass" and y < H - 2:
            arr[y + 1, x] *= 1.1
    if kind == "road":
        arr[22:24, ::32] = (200, 190, 120)
    if kind == "floor":
        for x in range(0, W, 32):
            arr[:, x:x + 1] *= 0.6
        for y in range(0, H, 16):
            arr[y:y + 1, :] *= 0.7
    return to_img(arr)


# ------------------------------------------------------------------ zombis y jugadores
SS = 4


def zombie(cloth, pose="idle", skin=(122, 152, 112), pants=(44, 48, 66), tint=None, big=False, metal=False):
    W, H = 128 * SS, 256 * SS
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = SS
    skin_d = tuple(int(v * 0.72) for v in skin)
    cloth_d = tuple(int(v * 0.68) for v in cloth)
    cloth_l = tuple(min(255, int(v * 1.18)) for v in cloth)

    def poly(pts, fill):
        d.polygon([(x * s, y * s) for x, y in pts], fill=fill)

    # piernas
    poly([(40, 150), (62, 150), (60, 246), (42, 246)], pants)
    poly([(66, 150), (88, 150), (86, 246), (68, 246)], tuple(int(v * 0.85) for v in pants))
    poly([(40, 150), (46, 150), (46, 246), (42, 246)], tuple(int(v * 0.6) for v in pants))
    d.rectangle((36 * s, 240 * s, 62 * s, 252 * s), fill=(22, 22, 26))              # zapatos
    d.rectangle((66 * s, 240 * s, 92 * s, 252 * s), fill=(22, 22, 26))
    # torso
    poly([(34, 66), (94, 66), (92, 156), (36, 156)], cloth)
    poly([(34, 66), (52, 66), (50, 156), (36, 156)], cloth_d)
    poly([(76, 66), (94, 66), (92, 156), (80, 156)], cloth_l)
    for _ in range(9):                                                            # desgarros y manchas
        x, y = random.randint(38, 88), random.randint(80, 150)
        d.ellipse(((x - 5) * s, (y - 3) * s, (x + 5) * s, (y + 4) * s), fill=(86, 14, 14, 200))
    for _ in range(4):
        x, y = random.randint(40, 84), random.randint(76, 140)
        poly([(x, y), (x + 8, y + 2), (x + 3, y + 10)], (*skin_d, 255))
    # brazos
    if pose == "chase":                                                           # extendidos hacia ti
        for sx, side in ((26, -1), (102, 1)):
            poly([(sx - 10, 72), (sx + 10, 72), (sx + 6 * side + 8, 124), (sx + 6 * side - 8, 124)], cloth_d)
            d.ellipse(((sx + 6 * side - 11) * s, 116 * s, (sx + 6 * side + 11) * s, 142 * s), fill=skin)
            for f in range(4):
                fx = sx + 6 * side - 8 + f * 5
                d.line((fx * s, 134 * s, (fx + side) * s, 148 * s), fill=skin_d, width=2 * s)
    else:
        for sx in (24, 104):
            poly([(sx - 10, 70), (sx + 10, 70), (sx + 8, 146), (sx - 8, 146)], cloth_d)
            d.ellipse(((sx - 10) * s, 142 * s, (sx + 10) * s, 164 * s), fill=skin)
    # cabeza
    d.ellipse((46 * s, 12 * s, 82 * s, 62 * s), fill=skin)
    d.ellipse((46 * s, 12 * s, 66 * s, 62 * s), fill=skin_d)
    d.ellipse((50 * s, 18 * s, 80 * s, 56 * s), fill=skin)
    d.chord((46 * s, 10 * s, 82 * s, 40 * s), 180, 360, fill=(30, 26, 22))        # pelo
    for ex in (55, 71):                                                           # ojos
        d.ellipse(((ex - 5) * s, 30 * s, (ex + 5) * s, 41 * s), fill=(24, 12, 12))
        d.ellipse(((ex - 2) * s, 33 * s, (ex + 2) * s, 38 * s), fill=(235, 40, 30))
    d.rectangle((54 * s, 46 * s, 74 * s, 53 * s), fill=(70, 10, 10))              # boca
    for tx in range(55, 74, 4):
        d.rectangle((tx * s, 46 * s, (tx + 2) * s, 49 * s), fill=(225, 215, 190))
    d.ellipse((60 * s, 20 * s, 68 * s, 27 * s), fill=(90, 16, 16))                # herida
    if metal:                                                                     # hombreras
        for cx in (26, 102):
            d.ellipse(((cx - 17) * s, 56 * s, (cx + 17) * s, 88 * s), fill=(150, 152, 168), outline=(60, 60, 70), width=2 * s)
            d.ellipse(((cx - 8) * s, 62 * s, (cx + 8) * s, 76 * s), fill=(200, 140, 50))
    img = img.resize((128, 256), Image.LANCZOS)
    # ruido de sombreado suave
    a = np.array(img).astype(float)
    shade = np.linspace(1.08, 0.82, 256).reshape(256, 1, 1)
    a[..., :3] *= shade
    return Image.fromarray(np.clip(a, 0, 255).astype("uint8"))


# ------------------------------------------------------------------ armas en mano (vista del jugador)
def gradient_rect(d, box, c0, c1, horizontal=True):
    x0, y0, x1, y1 = box
    if horizontal:
        for x in range(x0, x1):
            d.line((x, y0, x, y1), fill=lerp(c0, c1, (x - x0) / max(1, x1 - x0 - 1)))
    else:
        for y in range(y0, y1):
            d.line((x0, y, x1, y), fill=lerp(c0, c1, (y - y0) / max(1, y1 - y0 - 1)))


def weapon(kind):
    W, H = 300, 520
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = W // 2
    skin, skin_d = (232, 196, 162), (190, 150, 118)
    sleeve = (58, 70, 96)

    def hand(x, y, r=34):
        d.ellipse((x - r, y - r, x + r, y + r), fill=skin, outline=skin_d, width=3)
        d.ellipse((x - r // 2, y - r // 2 - 6, x + r // 3, y), fill=(246, 214, 184))

    def forearm(x0, y0, x1, y1, w=46):
        d.polygon([(x0 - w // 2, y0), (x0 + w // 2, y0), (x1 + w // 2 - 6, y1), (x1 - w // 2 + 6, y1)], fill=sleeve)
        d.line((x0 - w // 2, y0, x1 - w // 2 + 6, y1), fill=(36, 44, 66), width=4)

    if kind in ("pistol", "smg", "shotgun", "rifle"):
        ln = {"pistol": 250, "smg": 300, "shotgun": 380, "rifle": 430}[kind]
        wd = {"pistol": 40, "smg": 44, "shotgun": 40, "rifle": 34}[kind]
        top = H - ln - 40
        metal0, metal1 = (28, 30, 34), (96, 100, 108)
        gradient_rect(d, (cx - wd // 2, top, cx + wd // 2, H - 90), metal0, metal1)
        d.rectangle((cx - wd // 2 - 5, top, cx + wd // 2 + 5, top + 34), fill=(22, 24, 28), outline=(70, 74, 80))
        d.rectangle((cx - 4, top - 16, cx + 4, top), fill=(18, 18, 20))                 # mira delantera
        d.rectangle((cx - wd // 2 + 4, H - 200, cx + wd // 2 - 4, H - 196), fill=(150, 154, 162))
        if kind in ("shotgun", "rifle"):
            gradient_rect(d, (cx - wd // 2 - 4, H - 300, cx + wd // 2 + 4, H - 80), (116, 74, 40), (170, 116, 66))
            for k in range(0, 220, 14):
                d.line((cx - wd // 2 - 4, H - 300 + k, cx + wd // 2 + 4, H - 296 + k), fill=(96, 60, 32), width=1)
        if kind == "rifle":
            d.rectangle((cx - 10, top + 90, cx + 10, top + 170), fill=(16, 16, 18), outline=(90, 94, 100), width=2)   # mira telescópica
            d.ellipse((cx - 14, top + 84, cx + 14, top + 100), fill=(30, 40, 60))
        if kind == "smg":
            d.rectangle((cx - 12, H - 220, cx + 12, H - 120), fill=(40, 42, 46), outline=(80, 84, 90))   # cargador
        d.rectangle((cx - wd // 2 + 2, H - 120, cx + wd // 2 - 2, H - 40), fill=(34, 34, 38))              # empuñadura
        for k in range(0, 80, 10):
            d.line((cx - wd // 2 + 4, H - 118 + k, cx + wd // 2 - 4, H - 118 + k), fill=(60, 60, 66), width=1)
        forearm(cx - 40, H - 40, cx - 70, H + 10)
        hand(cx - 8, H - 70)
        forearm(cx + 60, H - 160, cx + 90, H + 10, 40)
        hand(cx + 8, H - 190, 28)
    elif kind in ("bat", "axe", "knife", "pan", "rod"):
        if kind == "bat":
            gradient_rect(d, (cx - 10, 20, cx + 10, H - 70), (122, 82, 44), (190, 140, 84))
            d.ellipse((cx - 22, 6, cx + 22, 120), fill=(176, 128, 74), outline=(110, 74, 40))
            d.rectangle((cx - 8, H - 120, cx + 8, H - 70), fill=(36, 36, 40))
        elif kind == "axe":
            gradient_rect(d, (cx - 9, 80, cx + 9, H - 70), (110, 74, 40), (170, 120, 70))
            d.polygon([(cx + 6, 40), (cx + 90, 60), (cx + 96, 170), (cx + 6, 190)], fill=(160, 166, 176), outline=(70, 74, 82))
            d.polygon([(cx + 40, 70), (cx + 90, 70), (cx + 94, 160), (cx + 40, 170)], fill=(206, 212, 222))
        elif kind == "knife":
            d.polygon([(cx - 14, 60), (cx + 14, 60), (cx + 12, 300), (cx - 12, 300)], fill=(214, 218, 226), outline=(110, 114, 122))
            d.polygon([(cx - 14, 60), (cx, 10), (cx + 14, 60)], fill=(226, 230, 238), outline=(110, 114, 122))
            d.rectangle((cx - 22, 300, cx + 22, 316), fill=(70, 70, 76))
            d.rectangle((cx - 12, 316, cx + 12, H - 60), fill=(40, 30, 24))
        elif kind == "pan":
            gradient_rect(d, (cx - 8, 150, cx + 8, H - 70), (36, 36, 40), (80, 80, 86))
            d.ellipse((cx - 88, 10, cx + 88, 170), fill=(40, 40, 46), outline=(110, 110, 118), width=5)
            d.ellipse((cx - 70, 26, cx + 70, 154), fill=(26, 26, 30))
        else:                                                                      # caña
            d.line((cx - 40, H - 40, cx + 70, 10), fill=(120, 90, 56), width=10)
            d.line((cx + 70, 10, cx + 90, 120), fill=(210, 210, 210), width=2)
            d.rectangle((cx - 60, H - 150, cx - 20, H - 110), fill=(60, 60, 66))
        forearm(cx + 30, H - 70, cx + 50, H + 10)
        hand(cx, H - 90)
    else:                                                                          # puños
        hand(cx - 80, H - 60, 50)
        hand(cx + 80, H - 60, 50)
        forearm(cx - 80, H - 20, cx - 100, H + 20, 60)
        forearm(cx + 80, H - 20, cx + 100, H + 20, 60)
    return img


def main():
    save(brick(), "brick.png")
    save(door(), "door.png")
    save(window(), "window.png")
    save(tree(), "tree.png")
    save(sky(), "sky.png")
    for k in ("grass", "road", "floor"):
        save(ground(k), f"ground_{k}.png")
    cloth = [(70, 80, 110), (110, 70, 60), (60, 90, 70), (90, 90, 90), (120, 110, 60), (80, 60, 90)]
    for i, c in enumerate(cloth):
        for pose in ("idle", "chase"):
            save(zombie(c, pose), f"zombie_{i}_{pose}.png")
    for pose in ("idle", "chase"):
        save(zombie((95, 55, 55), pose, skin=(130, 110, 96)), f"zombie_brute_{pose}.png")
        save(zombie((70, 70, 88), pose, skin=(118, 128, 120), metal=True), f"zombie_breaker_{pose}.png")
        save(zombie((70, 120, 200), pose, skin=(230, 195, 160), pants=(50, 54, 70)), f"player_{pose}.png")
    for w in ("pistol", "smg", "shotgun", "rifle", "bat", "axe", "knife", "pan", "rod", "fists"):
        save(weapon(w), f"hand_{w}.png")
    print("assets generados en", OUT, "-", len(os.listdir(OUT)), "archivos")


if __name__ == "__main__":
    main()
