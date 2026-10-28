"""Arte en píxeles de Last Refuge, generado por código (sin archivos de imagen).

- Suelos y paredes: tiles de 32x32 con volumen (borde superior, cara frontal de ladrillo y sombra).
- Personajes: sprites 2D de 32x32 (de frente, de espaldas y de lado), con contorno oscuro.
Todo se crea una sola vez y se guarda en caché."""
import math
import random

import pygame

T = 32
_c = {}


def _surf(w=T, h=T, alpha=True):
    return pygame.Surface((w, h), pygame.SRCALPHA) if alpha else pygame.Surface((w, h))


def R(s, x0, y0, x1, y1, c):
    """Rectángulo relleno (coordenadas incluidas)."""
    if x1 >= x0 and y1 >= y0:
        s.fill(c, (x0, y0, x1 - x0 + 1, y1 - y0 + 1))


def P(s, x, y, c):
    if 0 <= x < s.get_width() and 0 <= y < s.get_height():
        s.set_at((x, y), c)


def sh(c, f):
    return (max(0, min(255, int(c[0] * f))), max(0, min(255, int(c[1] * f))), max(0, min(255, int(c[2] * f))))


def jit(rng, c, a=8):
    k = rng.randint(-a, a)
    return (max(0, min(255, c[0] + k)), max(0, min(255, c[1] + k)), max(0, min(255, c[2] + k)))


def _cached(key, make):
    v = _c.get(key)
    if v is None:
        v = _c[key] = make()
    return v


# ---------------------------------------------------------------------------------------------- suelos
def grass(v):
    def make():
        rng = random.Random(100 + v)
        s = _surf(alpha=False)
        for y in range(T):
            for x in range(T):
                s.set_at((x, y), jit(rng, (78, 126, 62), 7))
        for _ in range(9):
            x, y = rng.randint(1, 30), rng.randint(3, 30)
            P(s, x, y, (104, 156, 76))
            P(s, x, y - 1, (110, 162, 80))
            P(s, x + 1, y, (60, 104, 52))
        if v % 3 == 0:
            P(s, rng.randint(3, 28), rng.randint(3, 28), rng.choice([(240, 230, 120), (240, 240, 240), (230, 130, 150)]))
        return s
    return _cached(("grass", v), make)


def water(v):
    def make():
        rng = random.Random(200 + v)
        s = _surf(alpha=False)
        for y in range(T):
            for x in range(T):
                s.set_at((x, y), jit(rng, (46, 96, 162), 6))
        for _ in range(3):
            x, y = rng.randint(2, 20), rng.randint(3, 28)
            R(s, x, y, x + rng.randint(3, 8), y, (112, 170, 228))
        return s
    return _cached(("water", v), make)


def road(v, dash=None):
    def make():
        rng = random.Random(300 + v)
        s = _surf(alpha=False)
        for y in range(T):
            for x in range(T):
                s.set_at((x, y), jit(rng, (72, 74, 82), 5))
        for _ in range(12):
            P(s, rng.randint(0, 31), rng.randint(0, 31), (58, 60, 66))
        if dash == "h":
            R(s, 4, 15, 21, 16, (214, 192, 96))
        elif dash == "v":
            R(s, 15, 4, 16, 21, (214, 192, 96))
        return s
    return _cached(("road", v, dash), make)


def floor(v):
    def make():
        rng = random.Random(400 + v)
        s = _surf(alpha=False)
        base = (160, 112, 70)
        for p in range(4):
            tone = jit(rng, base, 10)
            R(s, 0, p * 8, 31, p * 8 + 7, tone)
            R(s, 0, p * 8, 31, p * 8, sh(tone, 0.72))
            jx = (v * 11 + p * 9) % 28 + 2
            R(s, jx, p * 8, jx, p * 8 + 7, sh(tone, 0.72))
            for _ in range(3):
                P(s, rng.randint(0, 31), p * 8 + rng.randint(1, 6), sh(tone, 0.88))
        return s
    return _cached(("floor", v), make)


def door_open(v):
    def make():
        s = floor(v).copy()
        R(s, 1, 2, 7, 29, (96, 62, 36))
        R(s, 2, 3, 6, 28, (138, 92, 52))
        R(s, 2, 3, 2, 28, (176, 124, 72))
        R(s, 5, 14, 5, 17, (232, 196, 90))
        return s
    return _cached(("dopen", v), make)


def shadow_top():
    """Franja de sombra que cae sobre el suelo pegado a una pared (por el sur)."""
    def make():
        s = _surf(T, 8)
        for i, a in enumerate((110, 85, 60, 40, 24, 12)):
            R(s, 0, i, 31, i, (0, 0, 0, a))
        return s
    return _cached(("shadow_top",), make)


# ---------------------------------------------------------------------------------------------- paredes
def wall(face, window=False, door=False, v=0):
    """face=True: se ve el borde superior y la cara de ladrillo (no hay pared al sur).
    face=False: solo el techo de la pared (hay otra pared debajo)."""
    def make():
        rng = random.Random(500 + v)
        s = _surf(alpha=False)
        cap = (104, 76, 58)
        if not face:
            R(s, 0, 0, 31, 31, cap)
            for y in range(0, 32, 8):
                R(s, 0, y, 31, y, sh(cap, 0.85))
            R(s, 0, 0, 31, 0, (146, 112, 84))
            R(s, 0, 0, 0, 31, (128, 96, 72))
            R(s, 31, 0, 31, 31, (76, 54, 42))
            for _ in range(10):
                P(s, rng.randint(1, 30), rng.randint(1, 30), sh(cap, 0.9))
            if window:
                R(s, 6, 11, 25, 20, (226, 224, 214))
                R(s, 8, 13, 23, 18, (92, 134, 168))
                R(s, 9, 14, 13, 14, (170, 208, 230))
            elif door:
                R(s, 4, 4, 27, 27, (96, 62, 36))
                R(s, 6, 6, 25, 25, (140, 92, 52))
                R(s, 15, 6, 16, 25, (96, 62, 36))
                R(s, 21, 15, 23, 17, (232, 196, 90))
            return s
        cap_h = 10
        R(s, 0, 0, 31, cap_h - 1, cap)
        R(s, 0, 0, 31, 0, (146, 112, 84))
        R(s, 0, cap_h - 1, 31, cap_h - 1, (70, 50, 40))
        for x in range(0, 32, 6):
            P(s, x, 4, (88, 64, 50))
        for r in range(5):
            yy = cap_h + r * 4
            off = 4 if r % 2 else 0
            for b in range(-1, 5):
                bx = off + b * 8
                tone = jit(rng, (158, 78, 60), 14)
                xa, xb = max(0, bx + 1), min(31, bx + 7)
                if xb >= xa:
                    R(s, xa, yy, xb, yy + 2, tone)
                    R(s, xa, yy, xb, yy, sh(tone, 1.15))
                    R(s, xa, yy + 2, xb, yy + 2, sh(tone, 0.8))
            R(s, 0, yy + 3, 31, yy + 3, (176, 164, 148))
        R(s, 0, 30, 31, 31, (96, 44, 36))
        if window:
            R(s, 6, cap_h + 2, 25, 27, (226, 224, 214))
            R(s, 8, cap_h + 4, 23, 25, (92, 134, 168))
            for i in range(6):
                P(s, 9 + i * 2, cap_h + 5 + i, (170, 208, 230))
                P(s, 10 + i * 2, cap_h + 5 + i, (170, 208, 230))
            R(s, 15, cap_h + 4, 16, 25, (226, 224, 214))
            R(s, 8, 15, 23, 16, (226, 224, 214))
            R(s, 5, 27, 26, 29, (190, 186, 176))
        if door:
            R(s, 4, 2, 27, 31, (96, 62, 36))
            R(s, 6, 4, 25, 31, (140, 92, 52))
            for yy in (8, 19):
                R(s, 9, yy, 22, yy + 8, (120, 78, 42))
                R(s, 9, yy, 22, yy, (88, 56, 30))
            R(s, 21, 17, 23, 19, (232, 196, 90))
        return s
    return _cached(("wall", face, window, door, v), make)


def tree(v):
    def make():
        rng = random.Random(600 + v)
        s = grass(v).copy()
        sw = _surf(T, T)
        pygame.draw.ellipse(sw, (0, 0, 0, 70), (6, 20, 24, 10))
        s.blit(sw, (0, 0))
        R(s, 14, 18, 18, 29, (96, 64, 40))
        R(s, 14, 18, 15, 29, (70, 46, 30))
        R(s, 17, 18, 18, 29, (118, 80, 50))
        for (cx, cy, r, col) in ((16, 14, 12, (36, 92, 46)), (9, 17, 7, (40, 100, 50)), (23, 17, 7, (34, 86, 44)),
                                 (16, 8, 8, (52, 120, 60)), (12, 9, 4, (66, 142, 72))):
            pygame.draw.circle(s, col, (cx, cy), r)
        for _ in range(30):
            a, rr = rng.random() * math.tau, rng.random() * 11
            P(s, 16 + int(math.cos(a) * rr), 12 + int(math.sin(a) * rr * 0.8),
              rng.choice([(84, 168, 86), (30, 76, 40), (96, 180, 90)]))
        return s
    return _cached(("tree", v), make)


# ---------------------------------------------------------------------------------------------- muebles
def cont(kind, looted, v=0):
    def make():
        s = floor(v).copy()
        sw = _surf(T, T)
        R(sw, 3, 27, 30, 30, (0, 0, 0, 60))
        s.blit(sw, (0, 0))
        rng = random.Random(700 + v)
        if kind == "fridge":
            R(s, 4, 2, 27, 29, (210, 214, 220)); R(s, 4, 2, 27, 9, (234, 238, 242)); R(s, 4, 2, 27, 2, (255, 255, 255))
            R(s, 4, 10, 27, 10, (130, 134, 142)); R(s, 23, 4, 24, 8, (110, 114, 122)); R(s, 23, 13, 24, 22, (110, 114, 122))
            R(s, 4, 26, 27, 29, (170, 174, 182))
        elif kind == "shelf":
            R(s, 2, 3, 29, 29, (112, 76, 48)); R(s, 2, 3, 29, 4, (150, 104, 66))
            for ys in (6, 16):
                R(s, 4, ys, 27, ys + 8, (66, 44, 30))
                for i in range(5):
                    col = rng.choice([(210, 70, 60), (230, 190, 70), (90, 150, 210), (230, 230, 230), (110, 190, 100)])
                    R(s, 5 + i * 5, ys + 2, 8 + i * 5, ys + 8, col); R(s, 5 + i * 5, ys + 2, 8 + i * 5, ys + 2, sh(col, 1.25))
                R(s, 2, ys + 9, 29, ys + 10, (140, 96, 60))
        elif kind == "wardrobe":
            R(s, 3, 1, 28, 29, (90, 58, 38)); R(s, 3, 1, 28, 2, (130, 88, 58)); R(s, 5, 4, 15, 27, (110, 72, 46)); R(s, 16, 4, 26, 27, (110, 72, 46))
            R(s, 15, 4, 15, 27, (60, 38, 24)); R(s, 13, 14, 14, 17, (232, 196, 90)); R(s, 17, 14, 18, 17, (232, 196, 90))
        elif kind == "counter":
            R(s, 1, 6, 30, 29, (150, 140, 120)); R(s, 1, 6, 30, 12, (200, 192, 172)); R(s, 1, 6, 30, 6, (232, 226, 208))
            R(s, 1, 12, 30, 12, (110, 102, 88)); R(s, 6, 16, 12, 24, (130, 120, 100)); R(s, 19, 16, 25, 24, (130, 120, 100))
        elif kind == "cabinet":
            R(s, 4, 2, 27, 29, (118, 124, 136)); R(s, 4, 2, 27, 3, (164, 170, 182))
            for ys in (5, 12, 19):
                R(s, 6, ys, 25, ys + 5, (96, 102, 114)); R(s, 14, ys + 2, 17, ys + 3, (210, 214, 224))
        elif kind == "chest":
            R(s, 3, 8, 28, 28, (150, 104, 52)); R(s, 3, 8, 28, 13, (186, 134, 74)); R(s, 3, 8, 28, 8, (214, 164, 96))
            R(s, 3, 18, 28, 19, (70, 70, 78)); R(s, 14, 15, 17, 22, (232, 196, 90))
        elif kind == "toolbox":
            R(s, 3, 10, 28, 28, (190, 62, 52)); R(s, 3, 10, 28, 14, (224, 92, 78)); R(s, 3, 10, 28, 10, (244, 130, 116))
            R(s, 9, 6, 22, 8, (60, 60, 66)); R(s, 9, 6, 10, 10, (60, 60, 66)); R(s, 21, 6, 22, 10, (60, 60, 66))
            R(s, 13, 18, 18, 21, (232, 196, 90))
        elif kind == "gunrack":
            R(s, 2, 3, 29, 29, (66, 78, 58)); R(s, 2, 3, 29, 4, (100, 116, 86))
            for i in range(4):
                R(s, 6 + i * 6, 7, 7 + i * 6, 24, (36, 36, 40)); R(s, 5 + i * 6, 22, 8 + i * 6, 25, (110, 76, 44))
        elif kind == "medcab":
            R(s, 4, 2, 27, 29, (236, 242, 246)); R(s, 4, 2, 27, 3, (255, 255, 255)); R(s, 4, 28, 27, 29, (176, 184, 192))
            R(s, 14, 9, 17, 22, (214, 52, 52)); R(s, 9, 14, 22, 17, (214, 52, 52))
        elif kind == "pantry":
            R(s, 3, 2, 28, 29, (206, 154, 84)); R(s, 3, 2, 28, 3, (236, 190, 116))
            for ys in (6, 16):
                for i in range(5):
                    col = rng.choice([(200, 70, 60), (90, 160, 90), (230, 200, 90), (150, 150, 160)])
                    R(s, 5 + i * 5, ys, 8 + i * 5, ys + 8, col); R(s, 5 + i * 5, ys, 8 + i * 5, ys + 1, sh(col, 1.3))
                R(s, 3, ys + 9, 28, ys + 10, (140, 100, 56))
        else:
            R(s, 4, 4, 27, 27, (150, 108, 52))
        if looted:
            ov = _surf()
            ov.fill((20, 16, 24, 120))
            s.blit(ov, (0, 0))
        return s
    return _cached(("cont", kind, looted, v), make)


# ---------------------------------------------------------------------------------------------- techos
def roof(w, h, color):
    def make():
        rng = random.Random(w * 31 + h)
        s = _surf(w, h, alpha=False)
        s.fill(color)
        dark = sh(color, 0.78)
        light = sh(color, 1.14)
        for y in range(0, h, 6):
            R(s, 0, y, w - 1, y, dark)
            off = 0 if (y // 6) % 2 == 0 else 6
            for x in range(off, w, 12):
                R(s, x, y, x, min(h - 1, y + 5), dark)
        for _ in range(w * h // 90):
            P(s, rng.randrange(w), rng.randrange(h), rng.choice((dark, light)))
        R(s, 0, 0, w - 1, 2, light)
        R(s, 0, h - 3, w - 1, h - 1, sh(color, 0.6))
        R(s, 0, 0, 2, h - 1, light)
        R(s, w - 3, 0, w - 1, h - 1, sh(color, 0.62))
        mx = w // 2
        R(s, mx - 2, 0, mx + 1, h - 1, sh(color, 0.66))
        R(s, mx - 3, 0, mx - 3, h - 1, light)
        return s
    return _cached(("roof", w, h, color), make)


# ---------------------------------------------------------------------------------------------- personajes
def _outline(s, col=(24, 20, 28)):
    w, h = s.get_size()
    out = s.copy()
    for y in range(h):
        for x in range(w):
            if s.get_at((x, y))[3] == 0:
                for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    nx, ny = x + dx, y + dy
                    if 0 <= nx < w and 0 <= ny < h and s.get_at((nx, ny))[3] > 200:
                        out.set_at((x, y), col + (255,))
                        break
    return out


def _hat(s, hat, d):
    if hat == "lumberjack":
        R(s, 10, 1, 21, 5, (170, 30, 30))
        for x in range(11, 21, 3):
            R(s, x, 1, x, 5, (30, 30, 30))
        R(s, 10, 3, 10, 9, (150, 26, 26)); R(s, 21, 3, 21, 9, (150, 26, 26))
    elif hat == "police":
        R(s, 10, 1, 21, 4, (28, 40, 90))
        if d == "side":
            R(s, 14, 5, 25, 6, (12, 12, 20))
        elif d == "down":
            R(s, 10, 5, 21, 6, (12, 12, 20)); R(s, 15, 2, 16, 3, (225, 200, 80))
    elif hat == "firefighter":
        R(s, 10, 0, 21, 5, (210, 42, 32)); R(s, 10, 3, 21, 3, (250, 220, 60)); R(s, 8, 5, 23, 6, (150, 25, 20))
    elif hat == "farmer":
        R(s, 12, 0, 19, 3, (238, 212, 136)); R(s, 12, 3, 19, 3, (140, 72, 40)); R(s, 5, 4, 26, 5, (228, 198, 112))
        R(s, 5, 5, 26, 5, (170, 128, 60))


def person(shirt, pants, skin, hair, d="down", frame=0, zombie=False, blood=0, hat="none", kind="walker",
           swing=False):
    """Sprite 32x32 de una persona. d: 'down' (de frente), 'up' (de espaldas), 'side' (mira a la derecha)."""
    key = ("person", shirt, pants, skin, hair, d, frame, zombie, blood, hat, kind, swing)

    def make():
        rng = random.Random(hash((shirt, skin)) & 0xffff)
        s = _surf()
        step = 1 if frame else 0
        big = kind in ("brute", "breaker")
        if d == "side":
            R(s, 12, 22, 16, 29 - step, pants); R(s, 15, 22, 19, 28 + step, sh(pants, 0.8))
            R(s, 12, 29 - step, 17, 30 - step, (36, 30, 34)); R(s, 15, 28 + step, 20, 29 + step, (36, 30, 34))
            R(s, 11, 12, 20, 22, shirt); R(s, 11, 12, 13, 22, sh(shirt, 0.8)); R(s, 11, 21, 20, 22, sh(shirt, 0.7))
            R(s, 12, 3, 20, 12, skin); R(s, 11, 2, 19, 6, hair); R(s, 11, 6, 13, 9, hair)
            P(s, 18, 8, (220, 40, 36) if zombie else (30, 30, 40))
            R(s, 18, 11, 20, 11, (70, 14, 14) if zombie else sh(skin, 0.7))
            if zombie:
                R(s, 18, 13, 27, 15, sh(shirt, 0.8)); R(s, 26, 13, 29, 16, skin)
                R(s, 18, 17, 25, 19, sh(shirt, 0.8)); R(s, 24, 17, 27, 20, skin)
            else:
                R(s, 18, 14, 25, 16, sh(shirt, 1.1)); R(s, 24, 14, 27, 16, skin)
        else:
            ll, lr = 29 - step, 28 + step
            R(s, 11, 22, 14, ll, pants); R(s, 17, 22, 20, lr, sh(pants, 0.82))
            R(s, 11, ll, 14, ll + 1, (36, 30, 34)); R(s, 17, lr, 20, lr + 1, (36, 30, 34))
            R(s, 9, 12, 22, 22, shirt); R(s, 9, 12, 12, 22, sh(shirt, 0.82)); R(s, 19, 12, 22, 22, sh(shirt, 1.12))
            R(s, 9, 21, 22, 22, sh(shirt, 0.7))
            if zombie:
                R(s, 5, 13, 8, 22, sh(shirt, 0.78)); R(s, 23, 13, 26, 22, sh(shirt, 0.78))
                R(s, 5, 21, 8, 24, skin); R(s, 23, 21, 26, 24, skin)
            else:
                R(s, 6, 13, 8, 21 + step, sh(shirt, 0.8)); R(s, 23, 13, 25, 21 - step + 1, sh(shirt, 0.8))
                R(s, 6, 22 + step, 8, 24 + step, skin); R(s, 23, 22 - step + 1, 25, 24 - step + 1, skin)
            R(s, 11, 3, 20, 12, skin); R(s, 11, 3, 12, 12, sh(skin, 0.86))
            if d == "up":
                R(s, 11, 2, 20, 11, hair)
            else:
                R(s, 11, 2, 20, 5, hair); R(s, 10, 4, 10, 7, hair); R(s, 21, 4, 21, 7, hair)
                if zombie:
                    P(s, 13, 8, (220, 40, 36)); P(s, 18, 8, (220, 40, 36)); R(s, 14, 11, 17, 11, (70, 14, 14))
                else:
                    P(s, 13, 8, (30, 30, 40)); P(s, 18, 8, (30, 30, 40)); R(s, 14, 11, 17, 11, sh(skin, 0.7))
        if kind == "breaker":
            for cx in ((6, 25) if d != "side" else (13, 19)):
                R(s, cx - 2, 10, cx + 3, 14, (150, 152, 168)); R(s, cx - 1, 11, cx + 2, 12, (214, 150, 60))
        elif kind == "brute":
            R(s, 7, 11, 24, 12, sh(shirt, 1.25))
        elif kind == "thrower":
            R(s, 20, 15, 25, 22, (110, 80, 50)); R(s, 20, 15, 25, 15, (150, 112, 70))
        for _ in range(blood):
            P(s, rng.randint(10, 21), rng.randint(13, 21), (120, 18, 18))
        if hat != "none":
            _hat(s, hat, d)
        return _outline(s)
    return _cached(key, make)


def shadow():
    def make():
        s = _surf(22, 8)
        pygame.draw.ellipse(s, (0, 0, 0, 80), (0, 0, 22, 8))
        return s
    return _cached(("shadow",), make)


# ---------------------------------------------------------------------------------------------- autos
def car(color, damaged=False):
    """Auto visto desde arriba, mirando a la derecha (44x26)."""
    def make():
        w, h = 44, 26
        s = _surf(w, h)
        col = sh(color, 0.62) if damaged else color
        R(s, 2, 3, 41, 22, (20, 20, 24))
        for wx in (7, 31):                                     # ruedas
            R(s, wx, 1, wx + 8, 4, (16, 16, 18)); R(s, wx, 21, wx + 8, 24, (16, 16, 18))
        R(s, 2, 4, 41, 21, col)
        R(s, 2, 4, 41, 6, sh(col, 1.25)); R(s, 2, 19, 41, 21, sh(col, 0.65))
        R(s, 15, 6, 29, 19, sh(col, 0.88))                     # techo
        R(s, 15, 6, 29, 7, sh(col, 1.2))
        R(s, 28, 7, 33, 18, (52, 66, 88)); R(s, 29, 8, 31, 12, (110, 138, 168))     # parabrisas
        R(s, 10, 7, 13, 18, (46, 58, 78))                      # luneta trasera
        R(s, 40, 6, 42, 9, (255, 244, 190)); R(s, 40, 16, 42, 19, (255, 244, 190))   # faros
        R(s, 1, 6, 2, 9, (226, 56, 48)); R(s, 1, 16, 2, 19, (226, 56, 48))
        R(s, 34, 11, 39, 14, sh(col, 0.75))                    # capó
        return _outline(s)
    return _cached(("car", color, damaged), make)
