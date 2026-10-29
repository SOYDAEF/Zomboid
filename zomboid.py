"""
ZOMBOID PY - survival zombi inspirado en Project Zomboid (juego propio, sin assets)
Vista cenital, mundo procedural nuevo en cada partida (con semilla, como Minecraft), día/noche,
linterna, ruido, hambre, sed, sangrado, infección, saqueo, construcción y destrucción.
Modos: SOLO, ONLINE COOPERATIVO (hasta 6 jugadores) y servidor dedicado.

Instalación:   python -m pip install pygame      (o pygame-ce)
Ejecución:     python zomboid.py                  (pantalla de inicio con menús)

Atajos por línea de comandos:
  python zomboid.py host [puerto] [semilla]   crea una partida online y juegas tú también
  python zomboid.py join IP[:puerto]          te unes a la partida de un amigo
  python zomboid.py server [puerto] [semilla] servidor dedicado (sin ventana)

NOVEDADES
  - Pantalla de inicio: Jugar solo / Modo online (crear o unirse) / Ajustes / Salir.
  - Ajustes: cambia TODAS las teclas, nombre, oscuridad nocturna, FPS, pantalla completa.
  - Zombis con habilidades: Corredores (rápidos, gritan y atraen a otros), Lanzadores (tiran
    rocas y botellas), Brutos (muy resistentes, rompen puertas rápido) y embestida de los normales.
  - Los zombis NO abren puertas: las DESTRUYEN a golpes.
  - Construir (B) y destruir (mantén G) casi todo: con las manos tarda mucho, con un hacha poco.
    Cada material tiene su dureza. Destruir da tablones; con ellos construyes paredes, puertas...
  - Las noches son muy oscuras; los zombis casi no se ven (solo sus ojos rojos) y se ven mejor
    bajo tu luz. De día desaparecen; de noche aparecen, pero nunca dentro de tu luz.
  - Botellas vacías (V): lánzalas para atraer zombis a otro lugar.
  - Mundo nuevo y distinto cada vez: lagos, bosques, parques, casas pequeñas, grandes y mansiones
    (las más grandes tienen mejor botín).

NOVEDADES v4
  - LAN: el anfitrión se anuncia solo; en "Modo online" los demás ven la partida en una lista y entran con un clic.
  - Caña de pescar: empiezas con una. Equípala (Tab o número), ponte frente a un lago y pulsa E; quieto, pescas
    peces para comer.
  - Inventario (I): usar, tirar objetos (se quedan en el suelo; recógelos con E). Los muebles y los cofres tienen
    inventario: al abrirlos eliges qué tomar (y puedes guardar cosas). Cofre propio: modo construir (B), pieza 8.
  - El botín reaparece: cada día nuevo, los muebles vaciados vuelven a tener objetos (tus cofres no).
  - Sombreros (Ajustes): leñador, policía, bombero o agricultor.
  - En los menús puedes moverte con flechas + Enter.

CONTROLES (todos se pueden cambiar en Ajustes)
  W A S D mover | Shift correr | C furtivo | Ratón apuntar | Clic izq. atacar | Clic der. apuntar arma de fuego | E subir/bajar de un auto
  Espacio empujar | E interactuar (puertas, saqueo, beber de lagos) | F linterna | R recargar
  I inventario | Tab cambiar arma | H venda | Q comer/beber | B modo construir (1-4 elige pieza, clic construye)
  G (mantener) destruir lo que apuntas | V lanzar botella | M minimapa | T chat | Esc menú
"""
import base64
import json
import math
import os
import random
import socket
import struct
import sys
import time
import zlib
from collections import deque

import pygame

import pixelart as PA

IS_WEB = sys.platform == "emscripten"      # True cuando corre dentro del navegador (pygbag)

# ----------------------------------------------------------------------------
# Configuración
# ----------------------------------------------------------------------------
W, H = 1100, 700
FPS = 60
LQ = 4                       # la capa de luz se calcula a 1/4 de resolución (mucho más rápido)
TS = 32                     # tamaño de tile en píxeles
MAP_K = 4                   # manzanas por lado (3 = 110 tiles, 4 = 143, 5 = 176, 6 = 209)
N = 33 * MAP_K + 11         # el mapa mide N x N tiles (se recalcula con set_map_size)


def set_map_size(k):
    global MAP_K, N
    MAP_K = int(k)
    N = 33 * MAP_K + 11
CH = 16                     # tiles por chunk (caché de render)

GRASS, ROAD, FLOOR, WALL, TREE, DOOR_C, DOOR_O, CONT, WINDOW, WATER = range(10)
SOLID = {WALL, TREE, DOOR_C, CONT, WINDOW, WATER}   # bloquean el paso
FLOW_BLOCK = {WALL, TREE, CONT, WINDOW, WATER}      # bloquean el pathfinding (las puertas no: se rompen)
LOS_BLOCK = {WALL, TREE, DOOR_C}                    # bloquean la vista y las balas

# dureza de lo que se puede destruir, y tablones que suelta
TILE_HP = {WALL: 120, DOOR_C: 50, DOOR_O: 50, WINDOW: 25, CONT: 40, TREE: 90, FLOOR: 18}
TILE_DROP = {WALL: 2, DOOR_C: 1, DOOR_O: 1, WINDOW: 1, CONT: 1, TREE: 2, FLOOR: 1}
TOOL_POWER = {"fists": 6, "knife": 9, "pan": 12, "bat": 20, "axe": 48, "pistol": 6}   # daño por segundo
HATS = ["none", "lumberjack", "police", "firefighter", "farmer"]
HAT_NAMES = {"none": "Sin sombrero", "lumberjack": "Leñador", "police": "Policía",
             "firefighter": "Bombero", "farmer": "Agricultor"}
BUILD_PIECES = [
    dict(id="wall", tile=WALL, cost=2, time=3.0, name="Pared"),
    dict(id="door", tile=DOOR_C, cost=2, time=2.5, name="Puerta"),
    dict(id="window", tile=WINDOW, cost=1, time=2.0, name="Ventana"),
    dict(id="floor", tile=FLOOR, cost=1, time=1.5, name="Suelo"),
    dict(id="chest", tile=CONT, cost=3, time=2.5, name="Cofre"),
]
REACH = 72                  # alcance para construir/destruir (px)

PLAYER_R = 9
WALK, RUN, SNEAK = 95.0, 165.0, 48.0
ACTIVE_R = 800              # solo se simulan zombis a menos de esta distancia
FLOW_R = 26                 # radio (en tiles) del campo de pathfinding
INTERACT_DIST = 58
ZOMBIE_DAY = 45             # zombis que quedan de día
ZOMBIE_NIGHT = 90 if IS_WEB else 160          # zombis que aparecen de noche
GAME_MIN_PER_SEC = 0.8      # minutos de juego por segundo real (1 hora = 75 s)
START_MINUTES = 8 * 60
SPAWN_TILE = (40, 40)

FATAL_BITES = True          # False = las mordidas solo hacen sangrar
BITE_CHANCE = 0.12
INFECTION_TIME = 240.0      # segundos hasta morir tras una mordida

CAR_R = 13                   # radio de colisión del auto
CAR_MAX, CAR_REV, CAR_ACC, CAR_TURN = 330.0, -110.0, 230.0, 2.3
N_CARS = 7 if IS_WEB else 10
CAR_COLORS = [(190, 50, 45), (50, 100, 180), (210, 190, 60), (230, 230, 235), (60, 150, 90), (60, 60, 68)]


PORT = 5555
SNAP_HZ = 20
INPUT_HZ = 30
VIEW_R = 780
MAX_PLAYERS = 6

CFG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zomboid_config.json")

# ----------------------------------------------------------------------------
# Objetos
# ----------------------------------------------------------------------------
ITEMS = {
    "pistol":     dict(name="Pistola", kind="weapon"),
    "axe":        dict(name="Hacha", kind="weapon"),
    "bat":        dict(name="Bate", kind="weapon"),
    "pan":        dict(name="Sartén", kind="weapon"),
    "knife":      dict(name="Cuchillo", kind="weapon"),
    "flashlight": dict(name="Linterna", kind="tool"),
    "backpack":   dict(name="Mochila", kind="tool"),
    "bandage":    dict(name="Venda", kind="med"),
    "medkit":     dict(name="Botiquín", kind="med"),
    "canned":     dict(name="Comida enlatada", kind="food", amount=40),
    "cookies":    dict(name="Galletas", kind="food", amount=20),
    "water":      dict(name="Botella de agua", kind="drink", amount=45),
    "soda":       dict(name="Refresco", kind="drink", amount=25),
    "battery":    dict(name="Pilas", kind="tool"),
    "ammo":       dict(name="Balas 9mm", kind="ammo"),
    "bottle":     dict(name="Botella vacía", kind="throw"),
    "planks":     dict(name="Tablones", kind="material"),
    "rod":        dict(name="Caña de pescar", kind="weapon"),
    "fish":       dict(name="Pescado", kind="food", amount=35),
    "smg":        dict(name="Subfusil", kind="weapon"),
    "shotgun":    dict(name="Escopeta", kind="weapon"),
    "rifle":      dict(name="Rifle de caza", kind="weapon"),
    "fuel":       dict(name="Bidón de gasolina", kind="fuel"),
    "shells":     dict(name="Cartuchos", kind="ammo"),
    "rifle_ammo": dict(name="Balas de rifle", kind="ammo"),
}
ITEM_WEIGHT = {   # kg
    "pistol": 1.2, "smg": 3.0, "shotgun": 3.5, "rifle": 4.0, "axe": 2.0, "bat": 1.5, "pan": 1.2, "knife": 0.4,
    "rod": 1.0, "flashlight": 0.5, "bandage": 0.1, "medkit": 0.8, "canned": 0.5, "cookies": 0.2, "fish": 0.4,
    "water": 0.6, "soda": 0.4, "battery": 0.2, "ammo": 0.03, "shells": 0.06, "rifle_ammo": 0.05, "fuel": 3.0,
    "bottle": 0.2, "planks": 0.5, "backpack": 1.0,
}
CAP = 22.0                  # kg que puedes llevar
BACKPACK_CAP = 14.0         # kg extra al llevar una mochila


def cap_of(inv):
    return CAP + (BACKPACK_CAP if inv.get("backpack", 0) > 0 else 0.0)


def inv_weight(inv):
    return sum(ITEM_WEIGHT.get(i, 0.5) * q for i, q in inv.items() if q > 0)


ITEM_DESC = {
    "pistol": "Dispara con clic der. (apuntar) + clic izq. Hace mucho ruido.",
    "axe": "Arma y herramienta: derriba paredes y puertas rápido.",
    "bat": "Arma cuerpo a cuerpo, golpea a 2 zombis.",
    "pan": "Sartén: golpe medio, algo ruidosa.",
    "knife": "Cuchillo: rápido y silencioso.",
    "rod": "Equípala y pulsa Interactuar frente a un lago para pescar.",
    "fish": "Pescado: quita hambre.",
    "flashlight": "Ilumina un cono delante de ti. Gasta pilas.",
    "backpack": "Mientras la lleves, puedes cargar 14 kg más.",
    "bandage": "Detiene el sangrado.",
    "medkit": "Cura 45 de salud y detiene el sangrado.",
    "canned": "Comida enlatada: quita mucha hambre.",
    "cookies": "Galletas: quitan un poco de hambre.",
    "water": "Agua: quita sed. Te deja una botella vacía.",
    "soda": "Refresco: quita algo de sed.",
    "battery": "Recarga la linterna.",
    "ammo": "Balas para la pistola (se cargan con Recargar).",
    "bottle": "Botella vacía: lánzala para distraer zombis.",
    "planks": "Material para construir y fabricar un cofre.",
    "smg": "Subfusil automático: mantén clic der. (apuntar) y clic izq. Gasta balas 9mm rápido. Muy ruidoso.",
    "shotgun": "Escopeta: dispara varios perdigones, devastadora de cerca. Usa cartuchos.",
    "rifle": "Rifle de caza: mucho alcance y atraviesa hasta 3 zombis. Usa balas de rifle.",
    "fuel": "Gasolina: acércate a un auto y úsala para llenarle el tanque.",
    "shells": "Cartuchos para la escopeta (se cargan con Recargar).",
    "rifle_ammo": "Balas para el rifle de caza (se cargan con Recargar).",
}
CONT_NAMES = {"gunrack": "Armero", "medcab": "Armario médico", "pantry": "Despensa",
              "toolbox": "Caja de herramientas", "fridge": "Nevera", "shelf": "Estante", "wardrobe": "Armario", "counter": "Mostrador",
              "cabinet": "Gabinete", "chest": "Cofre"}
ITEM_ORDER = ["rifle", "shotgun", "smg", "pistol", "axe", "bat", "pan", "knife", "rod", "flashlight", "bandage",
              "medkit", "canned", "cookies", "fish", "water", "soda", "battery", "ammo", "shells", "rifle_ammo",
              "fuel", "bottle", "planks", "backpack"]

WEAPONS = {
    "fists": dict(name="Puños", dmg=8, rng=34, arc=2.0, cd=0.45, noise=45, targets=1, dur=None, kb=140, stam=5),
    "knife": dict(name="Cuchillo", dmg=20, rng=38, arc=1.6, cd=0.35, noise=30, targets=1, dur=70, kb=90, stam=4),
    "pan":   dict(name="Sartén", dmg=24, rng=42, arc=1.8, cd=0.55, noise=75, targets=1, dur=90, kb=170, stam=6),
    "bat":   dict(name="Bate", dmg=34, rng=54, arc=2.2, cd=0.62, noise=110, targets=2, dur=110, kb=260, stam=9),
    "axe":   dict(name="Hacha", dmg=58, rng=52, arc=2.2, cd=0.85, noise=120, targets=2, dur=90, kb=240, stam=12),
    "rod":   dict(name="Caña de pescar", dmg=3, rng=60, arc=0.9, cd=0.6, noise=40, targets=1, dur=80, kb=50, stam=3),
}
GUNS = {   # armas de fuego: dmg por perdigón, cd = tiempo entre disparos, pierce = zombis que atraviesa
    "pistol":  dict(name="Pistola", ammo="ammo", dmg=50, cd=0.40, noise=650, mag=12, reload=1.5, pellets=1,
                    spread=0.025, rng=520, pierce=1, auto=False, kb=200),
    "smg":     dict(name="Subfusil", ammo="ammo", dmg=22, cd=0.10, noise=700, mag=30, reload=2.0, pellets=1,
                    spread=0.07, rng=480, pierce=1, auto=True, kb=110),
    "shotgun": dict(name="Escopeta", ammo="shells", dmg=17, cd=0.95, noise=800, mag=6, reload=2.4, pellets=7,
                    spread=0.20, rng=300, pierce=1, auto=False, kb=330),
    "rifle":   dict(name="Rifle de caza", ammo="rifle_ammo", dmg=110, cd=1.0, noise=900, mag=5, reload=2.2,
                    pellets=1, spread=0.008, rng=760, pierce=3, auto=False, kb=260),
}
PISTOL = GUNS["pistol"]
WEAPON_LEN = {"fists": 0, "knife": 16, "pan": 18, "bat": 26, "axe": 24, "pistol": 18, "rod": 30,
              "smg": 22, "shotgun": 30, "rifle": 36}

# --- modos y ajustes de partida -----------------------------------------------------------------------
MODES = {   # dmg = daño de zombis, bite = prob. de mordida, bk = frecuencia de rompemuros, revive = se puede reaparecer
    "normal":   dict(name="Normal", zi=1, li=2, ti=1, dmg=1.0, bite=1.0, bk=1.0, revive=True,
                     desc="La experiencia de siempre. Si mueres, reapareces (tu botín queda en tu cuerpo)."),
    "hard":     dict(name="Difícil", zi=2, li=1, ti=1, dmg=1.3, bite=1.3, bk=1.8, revive=True,
                     desc="Más zombis, menos botín, golpes más fuertes y más rompemuros."),
    "hardcore": dict(name="Hardcore", zi=3, li=0, ti=1, dmg=1.6, bite=1.6, bk=2.5, revive=False,
                     desc="Hordas, poco botín y MUERTE REAL: no puedes revivir."),
}
MAP_OPTS = [("Pequeño", 3), ("Mediano", 4), ("Grande", 5), ("Enorme", 6)]
Z_OPTS = [("Pocos", 0.4), ("Normal", 1.0), ("Muchos", 1.5), ("Horda", 2.2)]
LOOT_OPTS = [("Escaso", 0.4), ("Poco", 0.7), ("Normal", 1.0), ("Abundante", 1.6), ("Muy abundante", 2.5)]
TIME_OPTS = [("Lento", 0.5), ("Normal", 1.0), ("Rápido", 2.0), ("Muy rápido", 4.0)]


def norm_settings(d):
    """Valida los ajustes de partida (vienen de un archivo o de la red)."""
    d = d if isinstance(d, dict) else {}
    mode = d.get("mode") if d.get("mode") in MODES else "normal"
    out = dict(mode=mode)
    for key, opts in (("zi", Z_OPTS), ("li", LOOT_OPTS), ("ti", TIME_OPTS), ("ms", MAP_OPTS)):
        v = d.get(key)
        out[key] = v if isinstance(v, int) and not isinstance(v, bool) and 0 <= v < len(opts) \
            else MODES[mode].get(key, 1)
    return out

LOOT = {   # (objeto, peso, cantidad mínima, máxima)
    "fridge":   [("canned", 3, 1, 2), ("cookies", 2, 1, 2), ("water", 3, 1, 1), ("soda", 3, 1, 2), ("bottle", 1, 1, 1)],
    "shelf":    [("canned", 3, 1, 2), ("cookies", 3, 1, 2), ("battery", 2, 1, 1), ("ammo", 1, 4, 8), ("shells", 0.5, 2, 4), ("fuel", 0.9, 1, 1),
                 ("bandage", 1, 1, 1), ("planks", 2, 2, 4), ("bottle", 2, 1, 2)],
    "wardrobe": [("bandage", 3, 1, 2), ("bat", 1, 1, 1), ("flashlight", 1, 1, 1), ("medkit", 1, 1, 1),
                 ("water", 1, 1, 1), ("planks", 1, 1, 2), ("backpack", 0.7, 1, 1)],
    "counter":  [("knife", 2, 1, 1), ("pan", 2, 1, 1), ("canned", 2, 1, 1), ("water", 1, 1, 1),
                 ("cookies", 2, 1, 2), ("bottle", 2, 1, 2)],
    "cabinet":  [("medkit", 1, 1, 1), ("bandage", 2, 1, 2), ("ammo", 2, 4, 9), ("battery", 2, 1, 1),
                 ("pistol", 0.35, 1, 1), ("axe", 0.5, 1, 1), ("flashlight", 1, 1, 1), ("planks", 1, 2, 3),
                 ("rod", 0.5, 1, 1), ("backpack", 0.6, 1, 1), ("shotgun", 0.22, 1, 1), ("rifle", 0.14, 1, 1), ("smg", 0.10, 1, 1),
                 ("shells", 1.3, 3, 6), ("rifle_ammo", 0.9, 3, 6), ("fuel", 1.2, 1, 1)],
}
LOOT["gunrack"] = [("pistol", 3, 1, 1), ("smg", 1.0, 1, 1), ("shotgun", 1.8, 1, 1), ("rifle", 1.1, 1, 1),
                   ("ammo", 3, 6, 14), ("shells", 3, 4, 8), ("rifle_ammo", 2, 4, 8), ("bandage", 1, 1, 2),
                   ("flashlight", 1, 1, 1)]
LOOT["medcab"] = [("medkit", 3, 1, 1), ("bandage", 5, 1, 3), ("water", 1, 1, 2), ("cookies", 1, 1, 1)]
LOOT["pantry"] = [("canned", 5, 1, 3), ("cookies", 4, 1, 3), ("water", 4, 1, 2), ("soda", 4, 1, 3),
                  ("bottle", 1, 1, 2)]
LOOT["toolbox"] = [("axe", 1.6, 1, 1), ("bat", 1.6, 1, 1), ("planks", 4, 2, 5), ("fuel", 3, 1, 2),
                   ("battery", 2.5, 1, 2), ("knife", 1, 1, 1), ("flashlight", 1.2, 1, 1), ("pan", 0.8, 1, 1), ("backpack", 0.9, 1, 1)]
SPECIAL = {   # edificios especiales: tamaño (ancho, alto), calidad de botín, muebles que llevan
    "gas": dict(name="GASOLINERA", w=(11, 13), h=(8, 9), q=1, maxd=0, doors=2, bonus=1, roof=(196, 62, 52),
                cw=[("toolbox", 4), ("shelf", 2), ("fridge", 2)]),
    "supermarket": dict(name="SUPERMERCADO", w=(20, 24), h=(14, 17), q=2, maxd=2, doors=3, bonus=4,
                        roof=(58, 124, 92), cw=[("pantry", 5), ("fridge", 3), ("counter", 2)]),
    "police": dict(name="COMISARÍA", w=(14, 16), h=(11, 13), q=3, maxd=2, doors=2, bonus=2, roof=(52, 72, 132),
                   cw=[("gunrack", 4), ("cabinet", 2), ("counter", 2), ("wardrobe", 1)]),
    "hardware": dict(name="FERRETERÍA", w=(14, 17), h=(10, 12), q=2, maxd=1, doors=2, bonus=3, roof=(184, 132, 52),
                     cw=[("toolbox", 5), ("shelf", 3)]),
    "hospital": dict(name="HOSPITAL", w=(20, 24), h=(14, 17), q=3, maxd=3, doors=3, bonus=4, roof=(222, 222, 230),
                     cw=[("medcab", 5), ("fridge", 1), ("counter", 2), ("wardrobe", 1)]),
}
RARE_ITEMS = {"backpack", "pistol", "axe", "medkit", "ammo", "bat", "battery", "flashlight", "shotgun", "rifle", "smg",
              "shells", "rifle_ammo", "fuel"}
ITEM_COUNT_BY_QUALITY = [   # cuántos objetos da un mueble según la calidad del edificio
    [(0, 22), (1, 40), (2, 28), (3, 10)],
    [(0, 12), (1, 30), (2, 38), (3, 20)],
    [(0, 6), (1, 22), (2, 36), (3, 26), (4, 10)],
    [(0, 3), (1, 12), (2, 30), (3, 32), (4, 23)],
]
CONT_WEIGHTS = [("fridge", 2), ("shelf", 3), ("wardrobe", 2), ("counter", 3), ("cabinet", 2)]
CONT_COLORS = {"gunrack": (66, 78, 58), "medcab": (236, 242, 246), "pantry": (206, 154, 84),
               "toolbox": (190, 62, 52), "fridge": (222, 228, 238), "shelf": (160, 112, 62), "wardrobe": (96, 62, 42),
               "counter": (172, 162, 142), "cabinet": (122, 128, 140), "chest": (150, 108, 52)}
ROOF_COLORS = [(140, 70, 60), (112, 92, 72), (88, 100, 122), (122, 60, 72), (98, 112, 92)]
ACTIONS = {"click", "shove", "interact", "reload", "flash", "cycle", "bandage", "consume", "use",
           "respawn", "build", "throw", "take", "put", "drop", "closec", "hat"}

# ----------------------------------------------------------------------------
# Zombis: tipos y habilidades
# ----------------------------------------------------------------------------
KINDS = ["walker", "runner", "thrower", "brute", "breaker"]
BREAKABLE = {WALL, WINDOW, DOOR_C}                   # lo que un Rompemuros puede derribar andando
ZK = {
    "walker":  dict(name="Normal", hp=(45, 70), spd=(38, 52), r=10, dmg=1.0),
    "runner":  dict(name="Corredor", hp=(28, 42), spd=(105, 125), r=9, dmg=0.8),
    "thrower": dict(name="Lanzador", hp=(40, 60), spd=(40, 50), r=10, dmg=0.8),
    "brute":   dict(name="Bruto", hp=(200, 260), spd=(34, 42), r=14, dmg=1.7),
    "breaker": dict(name="Rompemuros", hp=(300, 380), spd=(36, 42), r=14, dmg=1.5),
}

# ----------------------------------------------------------------------------
# Teclas configurables
# ----------------------------------------------------------------------------
BIND_LABELS = [
    ("up", "Avanzar"), ("down", "Retroceder"), ("left", "Izquierda"), ("right", "Derecha"),
    ("run", "Correr"), ("sneak", "Furtivo"), ("interact", "Interactuar"), ("flash", "Linterna"),
    ("reload", "Recargar"), ("cycle", "Cambiar arma"), ("shove", "Empujar"), ("bandage", "Usar venda"),
    ("consume", "Comer / beber"), ("build", "Modo construir"), ("demolish", "Destruir (mantener)"),
    ("throw", "Lanzar botella"), ("inventory", "Inventario"), ("map", "Minimapa"), ("chat", "Chat"),
    ("pause", "Pausa (solo)"),
]


def default_binds():
    k = pygame
    return dict(up=k.K_w, down=k.K_s, left=k.K_a, right=k.K_d, run=k.K_LSHIFT, sneak=k.K_c,
                interact=k.K_e, flash=k.K_f, reload=k.K_r, cycle=k.K_TAB, shove=k.K_SPACE,
                bandage=k.K_h, consume=k.K_q, build=k.K_b, demolish=k.K_g, throw=k.K_v,
                map=k.K_m, chat=k.K_t, pause=k.K_p, inventory=k.K_i)


def default_name():
    try:
        import getpass
        return (getpass.getuser() or "Superviviente")[:14]
    except Exception:
        return "Superviviente"


def load_cfg():
    cfg = dict(name=default_name(), port=PORT, dark=1.0, fps=False, fullscreen=False,
               minimap=True, hat="none", keys=default_binds(), game=norm_settings(None), fp=False)
    try:
        with open(CFG_PATH, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data.get("name"), str) and data["name"].strip():
            cfg["name"] = data["name"].strip()[:14]
        if isinstance(data.get("port"), int) and 1024 <= data["port"] <= 65535:
            cfg["port"] = data["port"]
        if isinstance(data.get("dark"), (int, float)):
            cfg["dark"] = max(0.5, min(1.0, float(data["dark"])))
        if data.get("hat") in HATS:
            cfg["hat"] = data["hat"]
        if isinstance(data.get("game"), dict):
            cfg["game"] = norm_settings(data["game"])
        for k in ("fps", "fullscreen", "minimap"):
            if isinstance(data.get(k), bool):
                cfg[k] = data[k]
        for k, v in (data.get("keys") or {}).items():
            if k in cfg["keys"] and isinstance(v, int):
                cfg["keys"][k] = v
    except (OSError, ValueError, AttributeError):
        pass
    return cfg


SAVE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "lastrefuge_save.dat")
SAVE_KEY = "lastrefuge_save"


def store_write(text):
    """Guarda la partida: en el navegador usa el almacenamiento local; en PC, un archivo junto al juego."""
    try:
        if IS_WEB:
            import platform
            platform.window.localStorage.setItem(SAVE_KEY, text)
        else:
            with open(SAVE_PATH, "w", encoding="ascii") as f:
                f.write(text)
        return True
    except Exception:
        return False


def store_read():
    try:
        if IS_WEB:
            import platform
            v = platform.window.localStorage.getItem(SAVE_KEY)
            return str(v) if v else None
        with open(SAVE_PATH, "r", encoding="ascii") as f:
            return f.read() or None
    except Exception:
        return None


def save_exists():
    return bool(store_read())


def save_cfg(cfg):
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=1)
    except OSError:
        pass


def parse_seed(text):
    text = (text or "").strip()
    if not text:
        return random.randrange(10 ** 9)
    try:
        return int(text) % (10 ** 9)
    except ValueError:
        return zlib.crc32(text.encode()) % (10 ** 9)


def angdiff(a, b):
    return (a - b + math.pi) % (2 * math.pi) - math.pi


def weighted(rnd, table, wi=1):
    total = sum(t[wi] for t in table)
    r = rnd.random() * total
    for t in table:
        r -= t[wi]
        if r <= 0:
            return t
    return table[-1]


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


LAN_PORT = 5556


class LanBeacon:
    """El anfitrión avisa por UDP (broadcast) cada ~1,5 s para que otros lo vean en su lista."""

    def __init__(self, get_info):
        self.get_info = get_info
        self.t = 0.0
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            self.sock.setblocking(False)
        except OSError:
            self.sock = None

    def tick(self, dt):
        if not self.sock:
            return
        self.t -= dt
        if self.t > 0:
            return
        self.t = 1.5
        try:
            data = json.dumps(dict(g="zomboid", **self.get_info())).encode()
        except (TypeError, ValueError):
            return
        for dest in ("255.255.255.255",):
            try:
                self.sock.sendto(data, (dest, LAN_PORT))
            except OSError:
                pass

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None


class LanScanner:
    """Escucha los avisos de partidas en la red local."""

    def __init__(self):
        self.found = {}                                  # (ip, puerto) -> dict(name, n, seen)
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if hasattr(socket, "SO_REUSEPORT"):
                try:
                    self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
                except OSError:
                    pass
            self.sock.bind(("", LAN_PORT))
            self.sock.setblocking(False)
        except OSError:
            self.sock = None

    def poll(self):
        now = time.time()
        if self.sock:
            for _ in range(20):
                try:
                    data, addr = self.sock.recvfrom(2048)
                except (BlockingIOError, InterruptedError):
                    break
                except OSError:
                    break
                try:
                    m = json.loads(data.decode())
                    if m.get("g") != "zomboid":
                        continue
                    port = int(m["port"])
                    name = "".join(ch for ch in str(m.get("name", "Partida")) if ch.isprintable())[:20]
                    self.found[(addr[0], port)] = dict(name=name, n=int(m.get("n", 1)), seen=now)
                except (ValueError, KeyError, TypeError, UnicodeDecodeError):
                    continue
        for k in [k for k, v in self.found.items() if now - v["seen"] > 5.0]:
            del self.found[k]
        return sorted(self.found.items(), key=lambda kv: kv[1]["name"])

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None


def vnoise(x, y, seed):
    """Ruido de valor suave 2D (0..1), determinista por semilla."""
    xi, yi = math.floor(x), math.floor(y)
    fx, fy = x - xi, y - yi

    def h(ix, iy):
        n = (ix * 374761393 + iy * 668265263 + seed * 2147483647) & 0xFFFFFFFF
        n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
        return ((n ^ (n >> 16)) & 0xFFFF) / 65535.0

    u, v = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    a, b, c, d = h(xi, yi), h(xi + 1, yi), h(xi, yi + 1), h(xi + 1, yi + 1)
    top, bot = a + (b - a) * u, c + (d - c) * u
    return top + (bot - top) * v


# ----------------------------------------------------------------------------
# Mapa: generación procedural + render por chunks con caché
# ----------------------------------------------------------------------------
class GameMap:
    def __init__(self, seed=None, k=None):
        self.k = k or MAP_K
        set_map_size(self.k)
        self.mods = {}                    # casillas cambiadas durante la partida (para guardar)
        self.seed = seed if seed is not None else random.randrange(10 ** 9)
        self.rnd = random.Random(self.seed)
        self.t = [[GRASS] * N for _ in range(N)]
        self.road = [[0] * N for _ in range(N)]
        self.buildings = []
        self.containers = {}
        self.chunks = {}
        self.generate()

    # --- serialización (el servidor envía el mapa exacto a los clientes) ---------
    def to_dict(self):
        flat = bytes(v for row in self.t for v in row)
        roads = bytes(v for row in self.road for v in row)
        return dict(
            t=base64.b64encode(zlib.compress(flat)).decode(),
            r=base64.b64encode(zlib.compress(roads)).decode(),
            b=[[b["x0"], b["y0"], b["x1"], b["y1"], list(b["roof"]), b["q"], b.get("kind")] for b in self.buildings],
            k=self.k,
            c=[[x, y, c["kind"], int(c["looted"]), c.get("q", 0)] for (x, y), c in self.containers.items()],
            s=self.seed,
        )

    @classmethod
    def from_dict(cls, d):
        m = cls.__new__(cls)
        m.k = d.get("k", 3)
        set_map_size(m.k)
        m.seed = d.get("s", 0)
        m.rnd = random.Random(0)
        flat = zlib.decompress(base64.b64decode(d["t"]))
        roads = zlib.decompress(base64.b64decode(d["r"]))
        m.t = [list(flat[y * N:(y + 1) * N]) for y in range(N)]
        m.road = [list(roads[y * N:(y + 1) * N]) for y in range(N)]
        m.buildings = [dict(x0=b[0], y0=b[1], x1=b[2], y1=b[3], roof=tuple(b[4]), q=b[5],
                           kind=b[6] if len(b) > 6 else None) for b in d["b"]]
        m.containers = {(c[0], c[1]): dict(kind=c[2], looted=bool(c[3]), q=c[4]) for c in d["c"]}
        m.chunks = {}
        return m

    # --- consultas ---------------------------------------------------------------
    def tile(self, x, y):
        if 0 <= x < N and 0 <= y < N:
            return self.t[y][x]
        return WALL

    def set_tile(self, x, y, v):
        self.t[y][x] = v
        self.mods[(x, y)] = v
        self.chunks.pop((x // CH, y // CH), None)

    def free(self, px, py, r):
        x0, x1 = int((px - r) // TS), int((px + r) // TS)
        y0, y1 = int((py - r) // TS), int((py + r) // TS)
        for ty in range(y0, y1 + 1):
            for tx in range(x0, x1 + 1):
                if self.tile(tx, ty) in SOLID:
                    return False
        return True

    def line_clear(self, x1, y1, x2, y2):
        dx, dy = x2 - x1, y2 - y1
        steps = int(math.hypot(dx, dy) / 10) + 1
        for i in range(1, steps):
            px = x1 + dx * i / steps
            py = y1 + dy * i / steps
            if self.tile(int(px // TS), int(py // TS)) in LOS_BLOCK:
                return False
        return True

    def ray_distance(self, x, y, ang, maxd):
        c, s = math.cos(ang), math.sin(ang)
        for i in range(1, int(maxd / 6) + 1):
            d = i * 6
            if self.tile(int((x + c * d) // TS), int((y + s * d) // TS)) in LOS_BLOCK:
                return d
        return maxd

    def building_at(self, tx, ty):
        for b in self.buildings:
            if b["x0"] <= tx <= b["x1"] and b["y0"] <= ty <= b["y1"]:
                return b
        return None

    # --- generación ---------------------------------------------------------------
    def generate(self):
        rnd, t = self.rnd, self.t
        s_lake, s_forest = rnd.randint(1, 10 ** 6), rnd.randint(1, 10 ** 6)
        K = self.k
        for r in [5 + 33 * i for i in range(K + 1)]:     # carreteras (4 tiles de ancho)
            for y in range(r, r + 4):
                for x in range(N):
                    t[y][x] = ROAD
                    self.road[y][x] |= 1
            for x in range(r, r + 4):
                for y in range(N):
                    t[y][x] = ROAD
                    self.road[y][x] |= 2

        blocks = [(9 + 33 * i, 9 + 33 * j) for i in range(K) for j in range(K)]
        rnd.shuffle(blocks)
        guaranteed = list(SPECIAL)[:min(len(SPECIAL), max(1, len(blocks) // 3))]   # siempre hay de cada tipo
        for bx, by in blocks:
            if guaranteed:
                self.make_special(bx, by, guaranteed.pop(0))
                continue
            roll = rnd.random()
            if roll < 0.12:                              # edificio especial al azar
                self.make_special(bx, by, rnd.choice(list(SPECIAL)))
            elif roll < 0.28:                            # mansión / almacén: ocupa toda la manzana
                w, h = rnd.randint(20, 25), rnd.randint(20, 25)
                self.make_building(bx + rnd.randint(1, 29 - w - 1), by + rnd.randint(1, 29 - h - 1),
                                   w, h, q=3, maxd=3, doors=rnd.randint(2, 3))
            elif roll < 0.38:                            # parque / bosque: sin casas
                continue
            else:
                for ox in (0, 15):
                    for oy in (0, 15):
                        if rnd.random() < 0.85:
                            self.make_house(bx + ox, by + oy, 14, 14)

        near = [[False] * N for _ in range(N)]           # margen alrededor de los edificios
        for b in self.buildings:
            for y in range(max(0, b["y0"] - 3), min(N, b["y1"] + 4)):
                for x in range(max(0, b["x0"] - 3), min(N, b["x1"] + 4)):
                    near[y][x] = True

        for y in range(N):                               # lagos y bosques con ruido
            for x in range(N):
                if t[y][x] != GRASS or near[y][x]:
                    continue
                edge = x < 4 or y < 4 or x >= N - 4 or y >= N - 4
                if vnoise(x / 13.0, y / 13.0, s_lake) > 0.70 and not edge and not self.road_near(x, y, 2):
                    t[y][x] = WATER
                    continue
                f = vnoise(x / 8.0, y / 8.0, s_forest)
                p = 0.025 + max(0.0, f - 0.55) * 1.1
                if (edge and rnd.random() < 0.85) or rnd.random() < p:
                    t[y][x] = TREE

    def road_near(self, x, y, r):
        for yy in range(max(0, y - r), min(N, y + r + 1)):
            for xx in range(max(0, x - r), min(N, x + r + 1)):
                if self.road[yy][xx]:
                    return True
        return False

    def make_special(self, bx, by, kind):
        rnd, sp = self.rnd, SPECIAL[kind]
        w, h = rnd.randint(*sp["w"]), rnd.randint(*sp["h"])
        self.make_building(bx + rnd.randint(1, 29 - w - 1), by + rnd.randint(1, 29 - h - 1), w, h,
                           q=sp["q"], maxd=sp["maxd"], doors=sp["doors"], skind=kind)

    def make_house(self, lx, ly, lw, lh):
        rnd = self.rnd
        tier = weighted(rnd, [(0, 50), (1, 35), (2, 15)])[0]
        size = {0: (8, 9), 1: (10, 11), 2: (12, 13)}[tier]
        w, h = rnd.randint(*size), rnd.randint(*size)
        x0 = lx + rnd.randint(0, lw - w)
        y0 = ly + rnd.randint(0, lh - h)
        self.make_building(x0, y0, w, h, q=tier, maxd=1 if tier < 2 else 2, doors=1 if tier == 0 else rnd.randint(1, 2))

    def split_room(self, ix0, iy0, ix1, iy1, depth, maxd, part_doors):
        """Divide un cuarto con una pared y un hueco (BSP): todos los cuartos quedan conectados."""
        rnd, t = self.rnd, self.t
        w, h = ix1 - ix0 + 1, iy1 - iy0 + 1
        if depth >= maxd or (w < 7 and h < 7):
            return
        if w >= h and w >= 7:
            wx = rnd.randint(ix0 + 3, ix1 - 3)
            for y in range(iy0, iy1 + 1):
                t[y][wx] = WALL
            dy = rnd.randint(iy0 + 1, iy1 - 1)
            t[dy][wx] = DOOR_O
            part_doors.append((wx, dy, "v"))
            self.split_room(ix0, iy0, wx - 1, iy1, depth + 1, maxd, part_doors)
            self.split_room(wx + 1, iy0, ix1, iy1, depth + 1, maxd, part_doors)
        elif h >= 7:
            wy = rnd.randint(iy0 + 3, iy1 - 3)
            for x in range(ix0, ix1 + 1):
                t[wy][x] = WALL
            dx = rnd.randint(ix0 + 1, ix1 - 1)
            t[wy][dx] = DOOR_O
            part_doors.append((dx, wy, "h"))
            self.split_room(ix0, iy0, ix1, wy - 1, depth + 1, maxd, part_doors)
            self.split_room(ix0, wy + 1, ix1, iy1, depth + 1, maxd, part_doors)

    def keeps_access(self, x, y):
        """True si poner un mueble en (x, y) deja un lado libre a él y a los muebles vecinos."""
        t = self.t
        dirs = ((1, 0), (-1, 0), (0, 1), (0, -1))

        def free_sides(cx, cy, ignore):
            return sum(1 for dx, dy in dirs if (cx + dx, cy + dy) != ignore
                       and t[cy + dy][cx + dx] in (FLOOR, DOOR_O, DOOR_C))

        if free_sides(x, y, None) < 1:
            return False
        for dx, dy in dirs:
            nx, ny = x + dx, y + dy
            if t[ny][nx] == CONT and free_sides(nx, ny, (x, y)) < 1:
                return False
        return True

    def make_building(self, x0, y0, w, h, q, maxd, doors, skind=None):
        rnd, t = self.rnd, self.t
        x1, y1 = x0 + w - 1, y0 + h - 1
        for y in range(y0, y1 + 1):
            for x in range(x0, x1 + 1):
                edge = x in (x0, x1) or y in (y0, y1)
                corner = x in (x0, x1) and y in (y0, y1)
                if edge and not corner and rnd.random() < 0.3:
                    t[y][x] = WINDOW
                else:
                    t[y][x] = WALL if edge else FLOOR

        part_doors = []
        self.split_room(x0 + 1, y0 + 1, x1 - 1, y1 - 1, 0, maxd, part_doors)
        for dx, dy, orient in part_doors:                # que ninguna pared tape un hueco
            for ax, ay in (((dx - 1, dy), (dx + 1, dy)) if orient == "v" else ((dx, dy - 1), (dx, dy + 1))):
                if t[ay][ax] == WALL:
                    t[ay][ax] = DOOR_O

        ring = []                                        # puertas exteriores (hacia un tile de suelo)
        for x in range(x0 + 1, x1):
            ring += [(x, y0, 0, 1), (x, y1, 0, -1)]
        for y in range(y0 + 1, y1):
            ring += [(x0, y, 1, 0), (x1, y, -1, 0)]
        rnd.shuffle(ring)
        placed = []
        for x, y, ix, iy in ring:
            if len(placed) >= doors:
                break
            if t[y + iy][x + ix] != FLOOR:
                continue
            if any(abs(x - px) + abs(y - py) < 4 for px, py in placed):
                continue
            t[y][x] = DOOR_C if rnd.random() < 0.7 else DOOR_O
            placed.append((x, y))
        if not placed:                                   # garantía: siempre hay una entrada
            x, y, _, _ = next(r for r in ring if t[r[1] + r[3]][r[0] + r[2]] == FLOOR)
            t[y][x] = DOOR_O

        all_doors = [(x, y) for y in range(y0, y1 + 1) for x in range(x0, x1 + 1)
                     if t[y][x] in (DOOR_C, DOOR_O)]
        cand = []
        for y in range(y0 + 1, y1):                      # muebles junto a las paredes
            for x in range(x0 + 1, x1):
                if t[y][x] != FLOOR:
                    continue
                if not any(t[y + dy][x + dx] == WALL for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))):
                    continue
                if any(max(abs(x - dx), abs(y - dy)) <= 2 for dx, dy in all_doors):
                    continue
                cand.append((x, y))
        rnd.shuffle(cand)
        count = [(3, 5), (4, 7), (6, 10), (10, 15)][q]
        weights = CONT_WEIGHTS if q < 2 else [(k, wgt + (2 if k in ("cabinet", "shelf", "wardrobe") else 0))
                                              for k, wgt in CONT_WEIGHTS]
        placed_c, want = 0, rnd.randint(*count)
        if skind:
            weights = SPECIAL[skind]["cw"]
            want += SPECIAL[skind]["bonus"]
        for x, y in cand:
            if placed_c >= want:
                break
            if not self.keeps_access(x, y):              # no tapar ni encerrar otros muebles
                continue
            t[y][x] = CONT
            self.containers[(x, y)] = dict(kind=weighted(rnd, weights)[0], looted=False, q=q,
                                           rolled=False, inv={})
            placed_c += 1

        self.buildings.append(dict(x0=x0, y0=y0, x1=x1, y1=y1, kind=skind,
                                   roof=SPECIAL[skind]["roof"] if skind else rnd.choice(ROOF_COLORS), q=q))

    # --- dibujo (cacheado por chunk) -------------------------------------------------
    def get_chunk(self, cx, cy):
        s = self.chunks.get((cx, cy))
        if s is None:
            s = pygame.Surface((CH * TS, CH * TS))
            for ty in range(cy * CH, cy * CH + CH):
                for tx in range(cx * CH, cx * CH + CH):
                    self.draw_tile(s, tx, ty, (tx - cx * CH) * TS, (ty - cy * CH) * TS)
            s = s.convert()
            self.chunks[(cx, cy)] = s
        return s

    def draw_tile(self, s, tx, ty, px, py):
        t = self.tile(tx, ty)
        j = ((tx * 73856093) ^ (ty * 19349663)) & 15
        v = j & 3
        solid = (WALL, WINDOW, DOOR_C)
        if t == GRASS:
            s.blit(PA.grass(v), (px, py))
        elif t == TREE:
            s.blit(PA.tree(v), (px, py))
        elif t == WATER:
            s.blit(PA.water(v), (px, py))
        elif t == ROAD:
            r = self.road[ty][tx]
            dash = None
            if r == 1 and (ty - 5) % 33 == 2 and tx % 2 == 0:
                dash = "h"
            elif r == 2 and (tx - 5) % 33 == 2 and ty % 2 == 0:
                dash = "v"
            s.blit(PA.road(v, dash), (px, py))
        elif t in (FLOOR, DOOR_O, CONT):
            if t == DOOR_O:
                s.blit(PA.door_open(v), (px, py))
            elif t == CONT:
                c = self.containers.get((tx, ty), dict(kind="shelf", looted=False))
                s.blit(PA.cont(c["kind"], bool(c["looted"]), v), (px, py))
            else:
                s.blit(PA.floor(v), (px, py))
        elif t in solid:
            face = self.tile(tx, ty + 1) not in solid
            s.blit(PA.wall(face, window=(t == WINDOW), door=(t == DOOR_C), v=v), (px, py))
        if t not in solid and self.tile(tx, ty - 1) in solid:       # sombra que proyecta la pared
            s.blit(PA.shadow_top(), (px, py))

    def minimap(self, size=150):
        mm = pygame.Surface((N, N))
        cols = {GRASS: (70, 112, 60), ROAD: (86, 86, 92), FLOOR: (150, 115, 80), WALL: (58, 42, 36),
                TREE: (40, 82, 42), DOOR_C: (130, 90, 50), DOOR_O: (150, 115, 80),
                CONT: (150, 115, 80), WINDOW: (110, 150, 170), WATER: (50, 110, 190)}
        for y in range(N):
            for x in range(N):
                mm.set_at((x, y), cols[self.t[y][x]])
        return pygame.transform.scale(mm, (size, size))


# ----------------------------------------------------------------------------
# Entidades
# ----------------------------------------------------------------------------
class Player:
    def __init__(self, x, y, pid=0, name="Jugador", remote=False):
        self.x, self.y = x, y
        self.pid, self.name, self.remote = pid, name, remote
        self.angle = 0.0
        self.hp = 100.0
        self.hunger = 10.0
        self.thirst = 10.0
        self.stamina = 100.0
        self.exhausted = False
        self.bleeding = False
        self.bleed_t = 0.0
        self.infected = False
        self.inf_t = 0.0
        self.inv = {"bandage": 1, "water": 1, "canned": 1, "flashlight": 1, "planks": 6, "rod": 1}
        self.cond = {}
        self.weapon = "fists"
        self.mag = 0
        self.mags = {}                  # balas cargadas en cada arma de fuego que no tienes en la mano
        self.flash_on = False
        self.battery = 100.0
        self.sneak = False
        self.aiming = False
        self.moving = False
        self.running = False
        self.atk_cd = 0.0
        self.reload_t = 0.0
        self.swing_t = 0.0
        self.noise_t = 0.0
        self.throw_cd = 0.0
        self.drink_cd = 0.0
        self.demo_noise = 0.0
        self.tool_wear = 0.0
        self.search = None
        self.fish = None                # [tx, ty, tiempo, espera] mientras pescas
        self.open = None                # (tx, ty) del mueble abierto
        self.cview = None               # contenido del mueble abierto (vista de cliente)
        self.hat = "none"
        self.work = None                # ["build", tx, ty, progreso, pieza] o ["demo", tx, ty, progreso]
        self.kills = 0
        self.alive = True
        self.cause = ""
        self.hurt_t = 0.0
        self.msgs = []
        self.outbox = []
        self.inp = dict(x=x, y=y, a=0.0, mv=0, run=0, aim=0, hold=0, sn=0, mx=x, my=y, dm=0, dv=(0.0, 0.0))
        self.car = None                 # id del auto que conduces (None = a pie)
        self.fix = False
        self.hurt_ev = False
        self.tx, self.ty = x, y

    def reset(self, x, y):
        msgs, outbox, inp, hat = self.msgs, self.outbox, self.inp, self.hat
        self.__init__(x, y, self.pid, self.name, self.remote)
        self.msgs, self.outbox, self.inp, self.hat = msgs, outbox, inp, hat
        self.inp.update(x=x, y=y)
        self.fix = True


class Zombie:
    SKINS = [(122, 152, 112), (136, 160, 122), (110, 140, 105)]
    CLOTHES = [(70, 80, 110), (110, 70, 60), (60, 90, 70), (90, 90, 90), (120, 110, 60), (80, 60, 90)]

    def __init__(self, zid, x, y, rnd, kind="walker"):
        self.id = zid
        self.x, self.y = x, y
        self.kind = kind
        k = ZK[kind]
        self.r = k["r"]
        self.dmg_mult = k["dmg"]
        self.speed = rnd.uniform(*k["spd"])
        self.max_hp = rnd.uniform(*k["hp"])
        self.hp = self.max_hp
        self.state = "idle"
        self.tx = self.ty = 0.0
        self.to_player = False
        self.angle = rnd.uniform(0, math.tau)
        self.stagger = 0.0
        self.kx = self.ky = 0.0
        self.atk_cd = 0.0
        self.look_t = rnd.random() * 0.4
        self.sees = False
        self.lost_t = 0.0
        self.wander_t = rnd.random() * 3
        self.wdir = None
        self.stuck_t = 0.0
        self.steer_t = 0.0
        self.steer_a = 0.0
        self.throw_cd = rnd.uniform(1.0, 3.0)
        self.lunge_t = 0.0
        self.lunge_cd = rnd.uniform(0.0, 3.0)
        self.scream_cd = 0.0
        self.bash_noise = 0.0
        self.d = 9999.0
        self.tp = None
        self.alive = True
        self.skin_i = rnd.randrange(len(self.SKINS))
        self.cloth_i = rnd.randrange(len(self.CLOTHES))
        self.skin = self.SKINS[self.skin_i]
        self.cloth = self.CLOTHES[self.cloth_i]


class Car:
    """Auto: lo simula el servidor (o el que juega solo). Conducción simple vista desde arriba."""

    def __init__(self, cid, x, y, ang, color_i, fuel):
        self.id, self.x, self.y, self.angle = cid, x, y, ang
        self.v = 0.0
        self.fuel = fuel
        self.hp = 100.0
        self.driver = None
        self.ci = color_i
        self.color = CAR_COLORS[color_i % len(CAR_COLORS)]
        self.thr = self.steer = 0.0
        self.noise_t = 0.0


class CarView:
    """Auto tal como lo ve un cliente (interpolado)."""

    def __init__(self, cid, x, y, ang):
        self.id = cid
        self.x = self.tx = x
        self.y = self.ty = y
        self.angle = self.ta = ang
        self.fuel, self.hp, self.driver, self.v = 0, 100, None, 0
        self.ci = 0
        self.color = CAR_COLORS[0]


class ZView:
    """Zombi tal como lo ve un cliente (posición interpolada)."""
    max_hp = 100.0

    def __init__(self, zid, x, y, kind="walker"):
        self.id = zid
        self.x = self.tx = x
        self.y = self.ty = y
        self.kind = kind
        self.r = ZK[kind]["r"]
        self.angle = 0.0
        self.state = "idle"
        self.hp = 100.0
        self.skin = Zombie.SKINS[0]
        self.cloth = Zombie.CLOTHES[0]


# ----------------------------------------------------------------------------
# Lógica del juego (no dibuja nada). Sirve para solo, anfitrión y servidor dedicado.
# ----------------------------------------------------------------------------
class Game:
    def __init__(self, seed=None, local=True, name="Tú", hat="none", settings=None):
        self.set_settings(settings)
        self.seed = seed if seed is not None else random.randrange(10 ** 9)
        self.rnd = random.Random(self.seed + 1)
        self.map = GameMap(self.seed, self.k)
        self.players = {}
        self.next_pid = 0
        self.p = None
        self.minutes = float(START_MINUTES)
        self.zombies = []
        self.next_zid = 0
        self.corpses = deque(maxlen=260)
        self.tracers = []
        self.projs = []                  # proyectiles: [x, y, vx, vy, ttl, tipo, dueño]  tipo 0 roca, 1 botella, 2 botella del jugador
        self.fx = []                     # efectos visuales: [x, y, tipo, ttl]
        self.tile_hp = {}
        self.shake = 0.0
        self.flows = {}
        self.flow_ts = {}
        self.flow_tile = {}
        self.flow_age = {}
        self.zt = 0
        self.pop_t = 0.0
        self.dark_now = 0.0
        self.items = {}                  # objetos en el suelo: id -> [x, y, objeto, cantidad, id]
        self.next_iid = 0
        self.last_day = 1
        self.ev_tracers, self.ev_corpses, self.ev_tiles, self.ev_loot, self.ev_fx = [], [], [], [], []
        self.ev_cont = []
        self.populate()
        self.cars = []
        self.next_cid = 0
        self.populate_cars()
        if local:
            self.p = self.add_player(name)
            self.p.hat = hat if hat in HATS else "none"
            self.msg("Sobrevive. Tienes una caña de pescar: equípala y pesca en un lago para comer.",
                     (255, 255, 255), self.p)

    PLAYER_SAVE = ("x", "y", "angle", "hp", "hunger", "thirst", "stamina", "exhausted", "bleeding", "bleed_t",
                   "infected", "inf_t", "inv", "cond", "weapon", "mag", "mags", "flash_on", "battery", "sneak",
                   "kills")

    def to_save(self):
        """Estado de la partida (modo solo) como datos simples para guardar."""
        p, m = self.p, self.map
        conts = [[x, y, c["kind"], c.get("q", 0), bool(c["looted"]), bool(c.get("rolled")), c.get("inv", {})]
                 for (x, y), c in m.containers.items()]
        return dict(
            v=1, seed=self.seed, settings=self.settings, minutes=self.minutes, last_day=self.last_day,
            player={k: getattr(p, k) for k in self.PLAYER_SAVE}, car=p.car,
            tiles=[[x, y, v] for (x, y), v in m.mods.items()],
            tile_hp=[[x, y, hp] for (x, y), hp in self.tile_hp.items()],
            conts=conts,
            zombies=[[round(z.x, 1), round(z.y, 1), z.kind, round(z.hp, 1), round(z.max_hp, 1)]
                     for z in self.zombies if z.alive],
            cars=[[c.id, round(c.x, 1), round(c.y, 1), round(c.angle, 3), c.ci, round(c.fuel, 1), round(c.hp, 1),
                   c.driver] for c in self.cars],
            items=[[round(it[0], 1), round(it[1], 1), it[2], it[3]] for it in self.items.values()],
            corpses=[[round(x, 1), round(y, 1), round(a, 2), list(col)] for x, y, a, col in self.corpses],
        )

    @staticmethod
    def from_save(d, name, hat):
        g = Game(seed=d["seed"], name=name, hat=hat, settings=d["settings"])
        m, p = g.map, g.p
        g.minutes, g.last_day = float(d["minutes"]), int(d.get("last_day", 1))
        for x, y, v in d["tiles"]:
            m.set_tile(x, y, v)
        g.tile_hp = {(x, y): hp for x, y, hp in d["tile_hp"]}
        for row in d["conts"]:
            if len(row) == 5:                                  # formato antiguo: solo cambios sobre el mundo generado
                x, y, looted, rolled, inv = row
                c = m.containers.get((x, y))
                if c is not None:
                    c["looted"], c["rolled"], c["inv"] = looted, rolled, {k: int(v) for k, v in inv.items()}
            else:                                              # incluye los cofres que construiste
                x, y, kind, q, looted, rolled, inv = row
                m.containers[(x, y)] = dict(kind=kind, looted=looted, q=q, rolled=rolled,
                                            inv={k: int(v) for k, v in inv.items()})
        for key in [k for k in m.containers if m.t[k[1]][k[0]] != CONT]:      # muebles que destruiste
            del m.containers[key]
        m.chunks.clear()
        for k, v in d["player"].items():
            setattr(p, k, v)
        p.alive = p.hp > 0
        g.zombies.clear()
        for x, y, kind, hp, mhp in d["zombies"]:
            z = g.new_zombie(x, y, kind)
            z.hp, z.max_hp = hp, mhp
        g.cars.clear()
        for cid, x, y, ang, ci, fuel, hp, driver in d["cars"]:
            c = Car(cid, x, y, ang, ci, fuel)
            c.hp, c.driver = hp, driver
            g.cars.append(c)
            g.next_cid = max(g.next_cid, cid + 1)
        p.car = d.get("car")
        g.items.clear()
        for x, y, item, qty in d["items"]:
            g.spawn_item(x, y, item, qty)
        g.corpses.clear()
        for x, y, a, col in d["corpses"]:
            g.corpses.append((x, y, a, tuple(col)))
        p.msgs.clear()
        g.msg("Partida cargada.", (200, 255, 200), p)
        return g

    def set_settings(self, settings):
        self.settings = norm_settings(settings)
        st = self.settings
        mo = MODES[st["mode"]]
        self.zmul, self.lmul, self.tmul = Z_OPTS[st["zi"]][1], LOOT_OPTS[st["li"]][1], TIME_OPTS[st["ti"]][1]
        self.k = MAP_OPTS[st["ms"]][1]
        if not hasattr(self, "map"):
            set_map_size(self.k)
        self.dmgm, self.bitem, self.bkm, self.revive = mo["dmg"], mo["bite"], mo["bk"], mo["revive"]
        area = (self.k * self.k / 9.0) ** 0.7              # mapa más grande = más zombis (sin llegar a proporcional)
        self.zday = min(190, max(6, int(ZOMBIE_DAY * self.zmul * area)))
        self.znight = min(420, max(10, int(ZOMBIE_NIGHT * self.zmul * area)))

    # --- jugadores -------------------------------------------------------------------
    def spawn_pos(self):
        for _ in range(40):
            x = (SPAWN_TILE[0] + 0.5) * TS + self.rnd.uniform(-60, 60)
            y = (SPAWN_TILE[1] + 0.5) * TS + self.rnd.uniform(-60, 60)
            if self.map.free(x, y, PLAYER_R):
                return x, y
        return (SPAWN_TILE[0] + 0.5) * TS, (SPAWN_TILE[1] + 0.5) * TS

    def add_player(self, name, remote=False):
        x, y = self.spawn_pos()
        pid = self.next_pid
        self.next_pid += 1
        pl = Player(x, y, pid, name, remote)
        self.players[pid] = pl
        return pl

    def respawn_player(self, p):
        if not p.alive and not self.revive:
            self.msg("Hardcore: no puedes revivir.", (255, 140, 120), p)
            return
        if not p.alive:
            self.release_car(p.pid)
            p.reset(*self.spawn_pos())
            self.msg(f"{p.name} ha vuelto a la partida.", (200, 255, 200))

    def other_players(self):
        return [pl for pl in self.players.values() if pl is not self.p and pl.alive]

    # --- utilidades ---------------------------------------------------------------------
    def msg(self, text, color=(255, 255, 255), p=None):
        targets = [p] if p else list(self.players.values())
        for t in targets:
            t.msgs.append([text, 5.0, color])
            del t.msgs[:-5]
            if t.remote:
                t.outbox.append([text, list(color)])
                del t.outbox[:-12]

    def darkness(self):
        h = (self.minutes / 60.0) % 24
        if 7 <= h < 18:
            return 0.0
        if 18 <= h < 21:
            return (h - 18) / 3
        if h >= 21 or h < 5:
            return 1.0
        return 1 - (h - 5) / 2

    def day(self):
        return int(self.minutes // 1440) + 1

    def clock(self):
        m = int(self.minutes % 1440)
        return f"{m // 60:02d}:{m % 60:02d}"

    def owned(self, p=None):
        p = p or self.p
        return [i for i in ITEM_ORDER if p.inv.get(i, 0) > 0]

    def set_tile(self, x, y, v):
        self.map.set_tile(x, y, v)
        self.ev_tiles.append([x, y, v])

    def add_tracer(self, x1, y1, x2, y2, col, width):
        self.tracers.append([x1, y1, x2, y2, col, width, 0.08])
        self.ev_tracers.append([round(x1, 1), round(y1, 1), round(x2, 1), round(y2, 1), list(col), width])

    def add_corpse(self, x, y, ang, col):
        self.corpses.append((x, y, ang, col))
        self.ev_corpses.append([round(x, 1), round(y, 1), round(ang, 2), list(col)])

    def add_fx(self, x, y, kind):
        self.fx.append([x, y, kind, 0.6])
        self.ev_fx.append([round(x, 1), round(y, 1), kind])

    def clear_events(self):
        self.ev_tracers, self.ev_corpses, self.ev_tiles, self.ev_loot, self.ev_fx = [], [], [], [], []
        self.ev_cont = []

    def is_lit(self, x, y):
        """¿Hay luz en este punto? (sol o la luz de algún jugador). Los zombis no aparecen con luz."""
        if self.darkness() < 0.25:
            return True
        for pl in self.players.values():
            if not pl.alive:
                continue
            d = math.hypot(x - pl.x, y - pl.y)
            if d < 130:
                return True
            if pl.flash_on and pl.battery > 0 and d < 320 and \
                    abs(angdiff(math.atan2(y - pl.y, x - pl.x), pl.angle)) < 0.65:
                return True
        return False

    # --- población ---------------------------------------------------------------------------
    def pick_kind(self, dark):
        table = [("walker", 70), ("runner", 6 + 24 * dark), ("thrower", 5 + 13 * dark), ("brute", 2 + 8 * dark),
                 ("breaker", (1.0 + 5 * dark) * self.bkm)]
        return weighted(self.rnd, table)[0]

    def new_zombie(self, x, y, kind=None):
        kind = kind or self.pick_kind(self.darkness())
        z = Zombie(self.next_zid, x, y, self.rnd, kind)
        self.next_zid += 1
        self.zombies.append(z)
        return z

    def populate(self):
        rnd, m = self.rnd, self.map
        sx, sy = (SPAWN_TILE[0] + 0.5) * TS, (SPAWN_TILE[1] + 0.5) * TS
        tries = 0
        while len(self.zombies) < self.zday + 15 and tries < 6000:
            tries += 1
            tx, ty = rnd.randint(4, N - 5), rnd.randint(4, N - 5)
            want = (FLOOR,) if rnd.random() < 0.45 else (GRASS, ROAD)
            if m.tile(tx, ty) not in want:
                continue
            x, y = (tx + 0.5) * TS, (ty + 0.5) * TS
            if math.hypot(x - sx, y - sy) < 550:
                continue
            self.new_zombie(x, y, "walker" if rnd.random() < 0.85 else None)

    def populate_cars(self):
        rnd, m = self.rnd, self.map
        sx, sy = (SPAWN_TILE[0] + 0.5) * TS, (SPAWN_TILE[1] + 0.5) * TS
        tries = 0
        want = min(26, max(4, round(N_CARS * self.k * self.k / 9)))
        while len(self.cars) < want and tries < 6000:
            tries += 1
            tx, ty = rnd.randint(4, N - 5), rnd.randint(4, N - 5)
            if m.tile(tx, ty) != ROAD:
                continue
            x, y = (tx + 0.5) * TS, (ty + 0.5) * TS
            first = len(self.cars) == 0
            dist = math.hypot(x - sx, y - sy)
            if (first and not 250 < dist < 700) or (not first and dist < 150):
                continue
            if any(math.hypot(x - c.x, y - c.y) < 260 for c in self.cars) or not m.free(x, y, CAR_R + 3):
                continue
            opts = [(m.ray_distance(x, y, a, 300) + rnd.random() * 30, a)      # mirando hacia donde hay más calle libre
                    for a in (0.0, math.pi / 2, math.pi, -math.pi / 2)]
            ang = max(opts)[1]
            self.cars.append(Car(self.next_cid, x, y, ang, rnd.randrange(len(CAR_COLORS)),
                                 70.0 if first else rnd.uniform(10, 65)))
            self.next_cid += 1

    def car_by_id(self, cid):
        for c in self.cars:
            if c.id == cid:
                return c
        return None

    def my_car(self):
        p = self.p
        return self.car_by_id(p.car) if p is not None and p.car is not None else None

    def car_near(self, p, dist=50):
        best = None
        for c in self.cars:
            if c.driver is None:
                d = math.hypot(c.x - p.x, c.y - p.y)
                if d <= dist and (best is None or d < best[0]):
                    best = (d, c)
        return best[1] if best else None

    def enter_car(self, p, c):
        p.car, c.driver = c.id, p.pid
        p.search = p.fish = p.work = p.open = None
        p.flash_on = False
        p.fix = True
        p.x, p.y, p.angle = c.x, c.y, c.angle
        self.msg("Subiste al auto: W acelera, S frena/reversa, A/D giran. [E] para bajar.", (200, 230, 255), p)

    def release_car(self, pid):
        """El jugador deja de conducir (sin moverlo)."""
        p = self.players.get(pid)
        for c in self.cars:
            if c.driver == pid:
                c.driver, c.thr, c.steer = None, 0.0, 0.0
        if p is not None:
            p.car = None

    def exit_car(self, p):
        c = self.car_by_id(p.car)
        self.release_car(p.pid)
        if c is None:
            return
        for side in (math.pi / 2, -math.pi / 2, math.pi, 0.0):
            a = c.angle + side
            x, y = c.x + math.cos(a) * (CAR_R + PLAYER_R + 4), c.y + math.sin(a) * (CAR_R + PLAYER_R + 4)
            if self.map.free(x, y, PLAYER_R):
                p.x, p.y = x, y
                break
        else:
            p.x, p.y = c.x, c.y
        p.fix = True

    def set_drive(self, p, thr, steer):
        c = self.car_by_id(p.car)
        if c is not None:
            c.thr = max(-1.0, min(1.0, float(thr)))
            c.steer = max(-1.0, min(1.0, float(steer)))

    def refuel(self, p, c):
        c.fuel = min(100.0, c.fuel + 45.0)
        self.remove_item(p, "fuel")
        self.msg(f"Llenaste el tanque ({int(c.fuel)}%).", (200, 255, 200), p)

    def explode_car(self, c, d):
        self.add_fx(c.x, c.y, "crash")
        self.make_noise(c.x, c.y, 650)
        for z in self.zombies:
            if z.alive and math.hypot(z.x - c.x, z.y - c.y) < 95 and d is not None:
                self.hit_zombie(z, 170, math.atan2(z.y - c.y, z.x - c.x), 320, d, 0.8)
        if c in self.cars:
            self.cars.remove(c)
        if d is not None:
            self.release_car(d.pid)
            d.x, d.y, d.fix = c.x, c.y, True
            self.hurt_player(d, 45, "Explosión del auto")
        self.msg("¡El auto explotó!", (255, 170, 90))

    def update_cars(self, dt):
        for c in list(self.cars):
            d = self.players.get(c.driver) if c.driver is not None else None
            if c.driver is not None and (d is None or not d.alive):
                self.release_car(c.driver)
                d = None
            thr = c.thr if d else 0.0
            if c.fuel <= 0:
                thr = 0.0
            if thr:
                if thr > 0:
                    c.v += thr * CAR_ACC * dt * (2.0 if c.v < 0 else 1.0)
                else:
                    c.v += thr * CAR_ACC * dt * (2.2 if c.v > 0 else 1.0)
                c.fuel -= abs(thr) * 2.2 * dt
            else:
                f = (120.0 if d else 200.0) * dt
                c.v = 0.0 if abs(c.v) <= f else c.v - math.copysign(f, c.v)
                if d:
                    c.fuel -= 0.05 * dt
            c.v = max(CAR_REV, min(CAR_MAX, c.v))
            c.fuel = max(0.0, c.fuel)
            if d:
                c.angle += c.steer * CAR_TURN * max(-1.0, min(1.0, c.v / 110.0)) * dt
            if abs(c.v) > 0.5:
                ca, sa = math.cos(c.angle), math.sin(c.angle)
                nx, ny = c.x + ca * c.v * dt, c.y + sa * c.v * dt
                if self.map.free(nx, ny, CAR_R):
                    c.x, c.y = nx, ny
                else:
                    ft = self.map.tile(int((c.x + ca * (CAR_R + 6)) // TS), int((c.y + sa * (CAR_R + 6)) // TS))
                    sp = abs(c.v)
                    if sp > 90:
                        c.hp -= sp * 0.10
                        self.make_noise(c.x, c.y, 320)
                        self.add_fx(c.x + ca * CAR_R, c.y + sa * CAR_R, "crash")
                        if d is not None and sp > 200:
                            self.hurt_player(d, (sp - 200) * 0.12, "Choque")
                        if ft in (DOOR_C, WINDOW) and sp > 120:
                            self.damage_tile(int((c.x + ca * (CAR_R + 6)) // TS),
                                             int((c.y + sa * (CAR_R + 6)) // TS), sp * 0.6, None)
                    c.v *= -0.25 if sp > 90 else 0.0
                # atropellar zombis
                if d is not None and abs(c.v) > 70:
                    for z in self.zombies:
                        if z.alive and z.stagger < 0.2 and math.hypot(z.x - c.x, z.y - c.y) <= CAR_R + z.r + 2:
                            self.hit_zombie(z, abs(c.v) * 0.5, c.angle, 300, d, 0.7)
                            heavy = z.kind in ("brute", "breaker")
                            c.v *= 0.78 if heavy else 0.965
                            c.hp -= 6 if heavy else 1.2
                            if not z.alive:
                                self.add_fx(z.x, z.y, "crash")
            if d is not None:
                d.x, d.y, d.angle, d.moving = c.x, c.y, c.angle, False
                c.noise_t -= dt
                if c.noise_t <= 0:
                    c.noise_t = 0.6
                    self.make_noise(c.x, c.y, 120 + abs(c.v) * 0.9)
            if d is not None and abs(c.v) > 100:                 # atropellar a jugadores a pie
                for pl in self.players.values():
                    if pl is d or not pl.alive or pl.car is not None or pl.hurt_t > 0:
                        continue
                    if math.hypot(pl.x - c.x, pl.y - c.y) <= CAR_R + 10:
                        self.hurt_player(pl, (abs(c.v) - 60) * 0.12, "Atropellado")
                        c.v *= 0.9
                        self.add_fx(pl.x, pl.y, "crash")
            if c.hp <= 0:
                self.explode_car(c, d)
        self.car_collisions()

    def car_collisions(self):
        """Los autos chocan entre sí: se separan, se frenan, se dañan y avisan con ruido."""
        cs = self.cars
        rr = CAR_R * 2 + 2
        for i in range(len(cs)):
            a = cs[i]
            for j in range(i + 1, len(cs)):
                b = cs[j]
                dx, dy = b.x - a.x, b.y - a.y
                dist = math.hypot(dx, dy)
                if dist >= rr:
                    continue
                if dist < 0.01:
                    dx, dy, dist = 1.0, 0.0, 1.0
                nx, ny = dx / dist, dy / dist
                avx, avy = math.cos(a.angle) * a.v, math.sin(a.angle) * a.v
                bvx, bvy = math.cos(b.angle) * b.v, math.sin(b.angle) * b.v
                rel = (avx - bvx) * nx + (avy - bvy) * ny          # > 0: se están acercando
                push = rr - dist
                for car, sg in ((a, -1.0), (b, 1.0)):                # separar a los dos
                    x2, y2 = car.x + nx * push * 0.55 * sg, car.y + ny * push * 0.55 * sg
                    if self.map.free(x2, y2, CAR_R):
                        car.x, car.y = x2, y2
                    else:                                            # contra un muro: que se mueva solo el otro
                        o = b if car is a else a
                        x3, y3 = o.x - nx * push * 1.1 * sg, o.y - ny * push * 1.1 * sg
                        if self.map.free(x3, y3, CAR_R):
                            o.x, o.y = x3, y3
                if rel > 25:
                    ma = avx * math.cos(b.angle) + avy * math.sin(b.angle)     # empuje de A sobre B
                    mb = bvx * math.cos(a.angle) + bvy * math.sin(a.angle)
                    a.v = max(CAR_REV, min(CAR_MAX, a.v * 0.3 + mb * 0.55))
                    b.v = max(CAR_REV, min(CAR_MAX, b.v * 0.3 + ma * 0.55))
                    if rel > 90:
                        dmg = rel * 0.09
                        a.hp -= dmg
                        b.hp -= dmg
                        mx, my = (a.x + b.x) / 2, (a.y + b.y) / 2
                        self.make_noise(mx, my, 340)
                        self.add_fx(mx, my, "crash")
                        for car in (a, b):
                            dr = self.players.get(car.driver) if car.driver is not None else None
                            if dr is not None and rel > 200:
                                self.hurt_player(dr, (rel - 200) * 0.12, "Choque")

    def manage_population(self, dt):
        """De noche aparecen zombis (nunca bajo una luz); de día desaparecen."""
        self.pop_t -= dt
        if self.pop_t > 0:
            return
        self.pop_t = 1.0
        alive = [pl for pl in self.players.values() if pl.alive]
        if not alive:
            return
        dark = self.darkness()
        target = self.zday + int((self.znight - self.zday) * dark)
        n = len(self.zombies)
        if n > target:
            cand = [z for z in self.zombies if z.state != "chase" and z.d > 420]
            self.rnd.shuffle(cand)
            for z in cand[:max(1, (n - target) // 5 + 1)]:
                z.alive = False
        elif n < target and dark > 0.25:
            for _ in range(min(5, target - n)):
                self.try_spawn(alive, dark)
        if dark < 0.15:                                  # a plena luz, los tranquilos se desvanecen
            for z in self.zombies:
                if z.state == "idle" and z.d > 260 and self.rnd.random() < 0.04:
                    z.alive = False

    def try_spawn(self, alive, dark):
        rnd = self.rnd
        for _ in range(25):
            p = rnd.choice(alive)
            a, d = rnd.uniform(0, math.tau), rnd.uniform(520, 1000)
            x, y = p.x + math.cos(a) * d, p.y + math.sin(a) * d
            tx, ty = int(x // TS), int(y // TS)
            if self.map.tile(tx, ty) not in (GRASS, ROAD, FLOOR):
                continue
            cx, cy = (tx + 0.5) * TS, (ty + 0.5) * TS
            if self.is_lit(cx, cy) or any(math.hypot(cx - o.x, cy - o.y) < 380 for o in alive):
                continue
            self.new_zombie(cx, cy)
            return True
        return False

    # --- ruido --------------------------------------------------------------------------------
    def make_noise(self, x, y, radius):
        for z in self.zombies:
            if math.hypot(z.x - x, z.y - y) < radius and not (z.state == "chase" and z.sees):
                z.state = "chase"
                z.tx, z.ty = x, y
                z.to_player = False
                z.lost_t = 7.0

    def move_entity(self, e, dx, dy, r):
        mx = my = False
        if dx:
            nx = e.x + dx
            if self.map.free(nx, e.y, r):
                e.x = nx
                mx = True
        if dy:
            ny = e.y + dy
            if self.map.free(e.x, ny, r):
                e.y = ny
                my = True
        return mx, my

    # --- bucle principal -------------------------------------------------------------------------
    def tick_effects(self, dt):
        for f in self.tracers:
            f[6] -= dt
        self.tracers = [f for f in self.tracers if f[6] > 0]
        for f in self.fx:
            f[3] -= dt
        self.fx = [f for f in self.fx if f[3] > 0]
        for pl in self.players.values():
            for f in pl.msgs:
                f[1] -= dt
            pl.msgs = [f for f in pl.msgs if f[1] > 0]
        self.shake = max(0.0, self.shake - dt)

    def update(self, dt, inp):
        self.tick_effects(dt)
        alive_any = any(pl.alive for pl in self.players.values())
        if alive_any:
            self.minutes += dt * GAME_MIN_PER_SEC * self.tmul
            if self.day() != self.last_day:
                self.last_day = self.day()
                self.restock()
        for pl in list(self.players.values()):
            if pl.alive:
                self.update_player(pl, dt, inp if pl is self.p else None)
        self.update_cars(dt)
        self.update_zombies(dt)
        self.update_projectiles(dt)
        if alive_any:
            self.manage_population(dt)

    # --- jugador ---------------------------------------------------------------------------------
    def control_move(self, p, dt, inp):
        """Movimiento del jugador que controla esta máquina (local o cliente)."""
        mx, my = inp["mouse"]
        p.angle = math.atan2(my - p.y, mx - p.x)
        dx, dy = inp["move"]
        p.moving = bool(dx or dy)
        if p.moving:
            n = math.hypot(dx, dy)
            dx, dy = dx / n, dy / n
        p.sneak = bool(inp.get("sneak"))
        p.aiming = bool(inp["aim"]) and p.weapon in GUNS
        p.running = (bool(inp["run"]) and p.moving and not p.sneak and not p.exhausted
                     and p.stamina > 0 and not p.aiming)
        speed = SNEAK if p.sneak else (RUN if p.running else WALK)
        if p.aiming:
            speed *= 0.6
        speed *= self.load_factor(p)
        if p.moving:
            self.move_entity(p, dx * speed * dt, dy * speed * dt, PLAYER_R)

    def update_player(self, p, dt, inp):
        if p.car is not None:                            # conduciendo: el auto manda la posición
            if p.remote:
                dv = p.inp.get("dv", (0.0, 0.0))
                self.set_drive(p, dv[0], dv[1])
                mouse = (p.inp["mx"], p.inp["my"])
            else:
                mvx, mvy = inp["move"]
                self.set_drive(p, -mvy, mvx)
                mouse = inp["mouse"]
            p.moving = p.sneak = p.aiming = p.running = False
            hold = demo_held = False
        elif p.remote:                                   # el cliente manda su posición; se valida
            i = p.inp
            p.angle = i["a"]
            p.moving = bool(i["mv"])
            p.sneak = bool(i["sn"])
            p.aiming = bool(i["aim"]) and p.weapon in GUNS
            p.running = (bool(i["run"]) and p.moving and not p.sneak and not p.exhausted
                         and p.stamina > 0 and not p.aiming)
            nx, ny = i["x"], i["y"]
            if (nx, ny) != (p.x, p.y):
                if math.hypot(nx - p.x, ny - p.y) < 200 and self.map.free(nx, ny, PLAYER_R):
                    p.x, p.y = nx, ny
                else:
                    p.fix = True
            hold = bool(i["hold"])
            demo_held = bool(i["dm"])
            mouse = (i["mx"], i["my"])
        else:
            self.control_move(p, dt, inp)
            hold = bool(inp["attack_held"])
            demo_held = bool(inp.get("demolish"))
            mouse = inp["mouse"]

        if p.moving and p.search:
            p.search = None
            self.msg("Dejaste de buscar.", (200, 200, 200), p)
        if p.moving and p.fish:
            p.fish = None
            self.msg("Dejaste de pescar.", (200, 200, 200), p)
        if p.fish:
            self.update_fishing(p, dt)
        if p.open:
            if (p.open not in self.map.containers or
                    math.hypot((p.open[0] + 0.5) * TS - p.x, (p.open[1] + 0.5) * TS - p.y) > INTERACT_DIST + 40):
                p.open = None

        if p.running:
            p.stamina -= 14 * dt / max(0.5, self.load_factor(p))
            if p.stamina <= 0:
                p.stamina, p.exhausted = 0.0, True
                self.msg("¡Estás agotado!", (255, 190, 90), p)
        else:
            p.stamina = min(100.0, p.stamina + (12 if p.moving else 24) * dt)
            if p.exhausted and p.stamina > 25:
                p.exhausted = False

        p.noise_t -= dt
        if p.moving and p.noise_t <= 0:
            self.make_noise(p.x, p.y, 190 if p.running else (22 if p.sneak else 65))
            p.noise_t = 0.5

        p.atk_cd -= dt
        p.swing_t -= dt
        p.hurt_t -= dt
        p.throw_cd -= dt
        p.drink_cd -= dt
        if hold and p.weapon not in GUNS and p.atk_cd <= 0 and not (p.work and p.work[0] == "build"):
            self.melee_attack(p)
        elif hold and p.weapon in GUNS and GUNS[p.weapon]["auto"] and p.aiming and p.atk_cd <= 0 \
                and p.reload_t <= 0:
            self.shoot(p)                                # armas automáticas: mantener el gatillo

        if p.work and p.work[0] == "build":              # construir / destruir
            self.update_build(p, dt)
        elif demo_held and not p.search:
            self.update_demolish(p, dt, mouse)
        elif p.work:
            p.work = None

        if p.reload_t > 0:
            p.reload_t -= dt
            if p.reload_t <= 0 and p.weapon in GUNS:
                gun = GUNS[p.weapon]
                take = min(gun["mag"] - p.mag, p.inv.get(gun["ammo"], 0))
                p.mag += take
                self.remove_item(p, gun["ammo"], take)
                self.msg(f"Recargada ({p.mag}/{gun['mag']}).", (200, 220, 255), p)

        if p.search:
            p.search[2] += dt
            if p.search[2] >= p.search[3]:
                tx, ty = p.search[0], p.search[1]
                p.search = None
                self.finish_search(p, tx, ty)

        if p.flash_on:
            p.battery -= 0.35 * dt
            if p.battery <= 0:
                p.battery, p.flash_on = 0.0, False
                self.msg("La linterna se quedó sin pilas.", (255, 190, 90), p)

        p.hunger = min(100.0, p.hunger + 0.085 * dt)     # necesidades
        p.thirst = min(100.0, p.thirst + 0.13 * dt)
        drain = 0.0
        if p.hunger >= 90:
            drain += 0.25
            p.cause = "Hambre"
        if p.thirst >= 90:
            drain += 0.4
            p.cause = "Sed"
        if p.bleeding:
            drain += 1.0
            p.cause = "Desangrado"
            p.bleed_t -= dt
            if p.bleed_t <= 0:
                p.bleeding = False
                self.msg("Tu herida dejó de sangrar.", (200, 255, 200), p)
        if drain:
            p.hp -= drain * dt
        elif p.hunger < 60 and p.thirst < 60 and p.hp < 100:
            p.hp = min(100.0, p.hp + 0.15 * dt)
        if p.infected:
            p.inf_t -= dt
            if p.inf_t <= 0:
                p.hp = 0
                p.cause = "Infección zombi"
        if p.hp <= 0.05:
            p.hp, p.alive, p.search, p.work = 0.0, False, None, None
            p.fish = p.open = None
            self.msg(f"{p.name} ha muerto ({p.cause or 'causa desconocida'}).", (255, 120, 120))
            if p.car is not None:
                self.release_car(p.pid)
            self.drop_body(p)
            if not self.revive:
                self.msg(f"HARDCORE: {p.name} no puede revivir.", (255, 90, 90))

    def drop_body(self, p):
        """Al morir, todo lo que llevabas queda en el suelo junto a tu cuerpo (cualquiera puede recogerlo)."""
        if p.weapon in GUNS:
            p.mags[p.weapon] = p.mag
        pile = dict(p.inv)
        for w, n in p.mags.items():                       # las balas que tenían cargadas las armas
            if n > 0 and w in GUNS:
                pile[GUNS[w]["ammo"]] = pile.get(GUNS[w]["ammo"], 0) + n
        for item, qty in pile.items():
            if qty > 0 and item in ITEMS:
                a, d = self.rnd.uniform(0, math.tau), self.rnd.uniform(4, 20)
                self.spawn_item(p.x + math.cos(a) * d, p.y + math.sin(a) * d, item, qty)
        p.inv, p.mags, p.mag, p.weapon, p.flash_on = {}, {}, 0, "fists", False
        self.add_corpse(p.x, p.y, p.angle, (70, 120, 200))
        if pile:
            self.msg("Tus cosas quedaron junto a tu cuerpo.", (255, 200, 140), p)

    def hurt_player(self, P, dmg, cause):
        if P.car is not None and cause == "Zombi":
            dmg *= 0.35                                   # la carrocería te protege
        P.hp -= dmg
        P.cause = cause
        P.search = None
        P.fish = None
        if P.work and P.work[0] == "build":
            P.work = None
        P.hurt_t = 0.3
        if P is self.p:
            self.shake = 0.25
        else:
            P.hurt_ev = True

    # --- construir y destruir -------------------------------------------------------------------------
    def damage_tile(self, tx, ty, dmg, by=None):
        """Daña un tile. Devuelve la fracción de vida restante (0 = destruido) o None si no se puede."""
        t = self.map.tile(tx, ty)
        mx = TILE_HP.get(t)
        if mx is None or not (1 <= tx < N - 1 and 1 <= ty < N - 1):
            return None
        hp = self.tile_hp.get((tx, ty), mx) - dmg
        if hp <= 0:
            self.destroy_tile(tx, ty, t, by)
            return 0.0
        self.tile_hp[(tx, ty)] = hp
        return hp / mx

    def destroy_tile(self, tx, ty, t, by):
        self.tile_hp.pop((tx, ty), None)
        if t == CONT:
            c = self.map.containers.pop((tx, ty), None)
            if c:
                if not c.get("rolled", True):
                    self.roll_loot(c)
                for item, qty in c["inv"].items():
                    self.spawn_item((tx + 0.5) * TS + self.rnd.uniform(-10, 10),
                                    (ty + 0.5) * TS + self.rnd.uniform(-10, 10), item, qty)
            for pl in self.players.values():
                if pl.open == (tx, ty):
                    pl.open = None
        self.set_tile(tx, ty, GRASS if t in (TREE, FLOOR) else FLOOR)
        cx, cy = (tx + 0.5) * TS, (ty + 0.5) * TS
        self.add_fx(cx, cy, "crash")
        self.make_noise(cx, cy, 190)
        if by is not None:
            qty = TILE_DROP[t]
            self.give(by, "planks", qty)
            self.msg(f"+{qty} tablón(es)", (210, 190, 140), by)

    def update_demolish(self, p, dt, mouse):
        tx, ty = int(mouse[0] // TS), int(mouse[1] // TS)
        cx, cy = (tx + 0.5) * TS, (ty + 0.5) * TS
        if self.map.tile(tx, ty) not in TILE_HP or math.hypot(cx - p.x, cy - p.y) > REACH:
            p.work = None
            return
        power = TOOL_POWER.get(p.weapon, 6)
        frac = self.damage_tile(tx, ty, power * dt, p)
        if frac is None or frac <= 0:
            p.work = None
        else:
            p.work = ["demo", tx, ty, round(1 - frac, 2)]
        p.demo_noise -= dt
        if p.demo_noise <= 0:
            p.demo_noise = 0.7
            self.make_noise(p.x, p.y, 70 + power * 1.8)
        if p.weapon not in ("fists",) + tuple(GUNS):
            p.tool_wear += dt
            if p.tool_wear >= 2.0:
                p.tool_wear = 0.0
                self.wear_weapon(p, 1)

    def can_build(self, p, tx, ty, pc):
        if not (2 <= tx < N - 2 and 2 <= ty < N - 2):
            return False
        cx, cy = (tx + 0.5) * TS, (ty + 0.5) * TS
        if math.hypot(cx - p.x, cy - p.y) > REACH:
            return False
        t = self.map.tile(tx, ty)
        if t not in ((GRASS, ROAD) if pc["id"] == "floor" else (GRASS, ROAD, FLOOR)):
            return False
        if pc["id"] != "floor":
            for e in [pl for pl in self.players.values() if pl.alive] + self.zombies:
                if math.hypot(e.x - cx, e.y - cy) < 22:
                    return False
        return True

    def start_build(self, p, tx, ty, pi):
        if not (0 <= pi < len(BUILD_PIECES)):
            return
        pc = BUILD_PIECES[pi]
        if p.inv.get("planks", 0) < pc["cost"]:
            self.msg(f"Necesitas {pc['cost']} tablones.", (255, 190, 90), p)
        elif not self.can_build(p, tx, ty, pc):
            self.msg("No puedes construir ahí.", (255, 190, 90), p)
        else:
            p.search = None
            p.work = ["build", tx, ty, 0.0, pi]

    def update_build(self, p, dt):
        w = p.work
        tx, ty, pi = w[1], w[2], w[4]
        pc = BUILD_PIECES[pi]
        if p.moving:
            p.work = None
            self.msg("Construcción cancelada.", (200, 200, 200), p)
            return
        if p.inv.get("planks", 0) < pc["cost"] or not self.can_build(p, tx, ty, pc):
            p.work = None
            self.msg("No se puede construir ahí.", (255, 190, 90), p)
            return
        w[3] += dt / pc["time"]
        if w[3] >= 1.0:
            self.remove_item(p, "planks", pc["cost"])
            self.tile_hp.pop((tx, ty), None)
            self.set_tile(tx, ty, pc["tile"])
            if pc["id"] == "chest":
                self.map.containers[(tx, ty)] = dict(kind="chest", looted=True, q=0, rolled=True, inv={})
                self.ev_cont.append([tx, ty, "chest", 1])
            self.make_noise(p.x, p.y, 110)
            self.add_fx((tx + 0.5) * TS, (ty + 0.5) * TS, "build")
            p.work = None

    # --- acciones (las usan el jugador local y los clientes remotos) ---------------------------------
    def do_action(self, p, a, arg=None):
        if a not in ACTIONS:
            return
        if a == "respawn":
            self.respawn_player(p)
            return
        if not p.alive:
            return
        if p.car is not None and a not in ("interact", "hat"):
            return                                        # conduciendo: solo puedes bajar
        if a == "click":
            self.on_click(p)
        elif a == "shove":
            self.shove(p)
        elif a == "interact":
            self.interact(p)
        elif a == "reload":
            self.reload(p)
        elif a == "flash":
            self.toggle_flash(p)
        elif a == "cycle":
            self.cycle_weapon(p)
        elif a == "bandage":
            self.use_bandage(p)
        elif a == "consume":
            self.auto_consume(p)
        elif a == "use" and isinstance(arg, str) and arg in ITEMS:
            self.use_item(p, arg)
        elif a == "take":
            self.take_item(p, arg)
        elif a == "put":
            self.put_item(p, arg)
        elif a == "drop":
            self.drop_item(p, arg)
        elif a == "closec":
            p.open = None
        elif a == "hat" and arg in HATS:
            p.hat = arg
        elif a == "build" and isinstance(arg, (list, tuple)) and len(arg) == 3:
            try:
                self.start_build(p, int(arg[0]), int(arg[1]), int(arg[2]))
            except (TypeError, ValueError):
                pass
        elif a == "throw" and isinstance(arg, (list, tuple)) and len(arg) == 2:
            try:
                x, y = float(arg[0]), float(arg[1])
            except (TypeError, ValueError):
                return
            if math.isfinite(x) and math.isfinite(y):
                self.throw_bottle(p, x, y)

    # --- combate -------------------------------------------------------------------------------------
    def hit_zombie(self, z, dmg, ang, kb, p, stagger=0.45):
        z.hp -= dmg
        z.kx, z.ky = math.cos(ang) * kb, math.sin(ang) * kb
        z.stagger = stagger * (0.4 if z.kind in ("brute", "breaker") else 1.0)
        z.state, z.to_player, z.lost_t = "chase", True, 7.0
        z.tx, z.ty = p.x, p.y
        if z.hp <= 0 and z.alive:
            z.alive = False
            p.kills += 1
            self.add_corpse(z.x, z.y, ang, z.cloth)

    def set_weapon(self, p, w):
        """Cambia de arma guardando las balas cargadas de la de fuego que sueltas."""
        if w == p.weapon:
            return
        if p.weapon in GUNS:
            p.mags[p.weapon] = p.mag
        p.weapon = w
        p.mag = p.mags.get(w, 0) if w in GUNS else 0
        p.reload_t = 0.0

    def wear_weapon(self, p, n=1):
        if p.weapon not in WEAPONS or p.weapon == "fists":
            return
        w = WEAPONS[p.weapon]
        p.cond[p.weapon] = p.cond.get(p.weapon, w["dur"]) - n
        if p.cond[p.weapon] <= 0:
            broken = p.weapon
            self.remove_item(p, broken, 1)
            self.msg(f"Tu {w['name'].lower()} se rompió.", (255, 150, 120), p)
            if p.inv.get(broken, 0) > 0:
                p.cond[broken] = w["dur"]
                p.weapon = broken
            else:
                self.set_weapon(p, "fists")

    def melee_attack(self, p):
        if p.atk_cd > 0:
            return
        w = WEAPONS[p.weapon]
        p.stamina = max(0.0, p.stamina - w["stam"])
        p.atk_cd = w["cd"] * (1.5 if p.stamina < 10 else 1.0)
        p.swing_t = 0.14
        p.search = None
        p.fish = None
        self.make_noise(p.x, p.y, w["noise"])
        cands = []
        for z in self.zombies:
            if not z.alive:
                continue
            d = math.hypot(z.x - p.x, z.y - p.y)
            if d > w["rng"] + z.r:
                continue
            if abs(angdiff(math.atan2(z.y - p.y, z.x - p.x), p.angle)) > w["arc"] / 2:
                continue
            if not self.map.line_clear(p.x, p.y, z.x, z.y):
                continue
            cands.append((d, z))
        cands.sort(key=lambda c: c[0])
        hits = 0
        for _, z in cands[:w["targets"]]:
            self.hit_zombie(z, w["dmg"] * self.rnd.uniform(0.85, 1.15), p.angle, w["kb"], p)
            hits += 1
        if hits:
            self.wear_weapon(p, 1)

    def shove(self, p):
        if p.atk_cd > 0 or p.stamina < 5:
            return
        p.stamina -= 12
        p.atk_cd = 0.7
        p.swing_t = 0.12
        p.search = None
        self.make_noise(p.x, p.y, 80)
        for z in self.zombies:
            if not z.alive:
                continue
            if math.hypot(z.x - p.x, z.y - p.y) <= 46 + z.r - 10 and \
                    abs(angdiff(math.atan2(z.y - p.y, z.x - p.x), p.angle)) <= 1.2:
                f = 0.35 if z.kind in ("brute", "breaker") else 1.0
                z.kx, z.ky = math.cos(p.angle) * 420 * f, math.sin(p.angle) * 420 * f
                z.stagger = 1.1 * f
                z.state, z.to_player = "chase", True
                z.tx, z.ty = p.x, p.y

    def shoot(self, p):
        gun = GUNS.get(p.weapon)
        if not gun or p.atk_cd > 0 or p.reload_t > 0:
            return
        if p.mag <= 0:
            self.msg("Sin munición. Pulsa R para recargar.", (255, 190, 90), p)
            p.atk_cd = 0.3
            return
        p.mag -= 1
        p.atk_cd = gun["cd"]
        p.search = None
        sp = gun["spread"] + ((0.04 if p.moving else 0.0) if gun["pellets"] == 1 else 0.02 if p.moving else 0.0)
        hits = {}                                        # zombi -> [daño acumulado, ángulo]
        for _ in range(gun["pellets"]):
            ang = p.angle + self.rnd.gauss(0, sp)
            c, s = math.cos(ang), math.sin(ang)
            end = self.map.ray_distance(p.x, p.y, ang, gun["rng"])
            cand = []
            for z in self.zombies:
                if not z.alive:
                    continue
                rx, ry = z.x - p.x, z.y - p.y
                t = rx * c + ry * s
                if 0 < t < end and abs(-rx * s + ry * c) < z.r + 2:
                    cand.append((t, z))
            cand.sort(key=lambda a: a[0])
            taken = cand[:gun["pierce"]]
            for k, (t, z) in enumerate(taken):
                h = hits.setdefault(z, [0.0, ang])
                h[0] += gun["dmg"] * (0.8 ** k)
            if taken:
                end = taken[-1][0]
            self.add_tracer(p.x + c * 14, p.y + s * 14, p.x + c * end, p.y + s * end, (255, 235, 150), 2)
        for z, (dmg, ang) in hits.items():
            self.hit_zombie(z, dmg, ang, gun["kb"], p, 0.6)
        self.make_noise(p.x, p.y, gun["noise"])
        p.swing_t = 0.06
        if p is self.p:
            self.shake = max(self.shake, 0.08 + 0.05 * (gun["pellets"] > 1))

    def reload(self, p):
        gun = GUNS.get(p.weapon)
        if not gun or p.reload_t > 0 or p.mag >= gun["mag"]:
            return
        if p.inv.get(gun["ammo"], 0) <= 0:
            self.msg(f"No tienes {ITEMS[gun['ammo']]['name'].lower()}.", (255, 190, 90), p)
            return
        p.reload_t = gun["reload"]
        p.search = None
        self.msg("Recargando...", (200, 220, 255), p)

    def on_click(self, p):
        if p.weapon in GUNS:
            if p.aiming:
                self.shoot(p)
            else:
                self.msg("Mantén el clic derecho para apuntar.", (200, 200, 200), p)
        else:
            self.melee_attack(p)

    def throw_bottle(self, p, x, y):
        if p.throw_cd > 0:
            return
        if p.inv.get("bottle", 0) <= 0:
            self.msg("No tienes botellas vacías.", (255, 190, 90), p)
            return
        ang = math.atan2(y - p.y, x - p.x)
        dist = min(380.0, math.hypot(x - p.x, y - p.y))
        free = self.map.ray_distance(p.x, p.y, ang, dist)
        if free < dist:
            dist = max(10.0, free - 8)
        speed = 380.0
        self.projs.append([p.x, p.y, math.cos(ang) * speed, math.sin(ang) * speed,
                           max(0.05, dist / speed), 2, p.pid])
        self.remove_item(p, "bottle", 1)
        p.throw_cd = 0.6
        p.swing_t = 0.1
        p.search = None

    # --- proyectiles ---------------------------------------------------------------------------------------
    def update_projectiles(self, dt):
        keep = []
        alive = [pl for pl in self.players.values() if pl.alive]
        for pr in self.projs:
            x, y, vx, vy, ttl, kind, owner = pr
            nx, ny = x + vx * dt, y + vy * dt
            pr[4] = ttl - dt
            blocked = self.map.tile(int(nx // TS), int(ny // TS)) in LOS_BLOCK
            if kind == 2:                                # botella del jugador: al caer hace ruido
                if blocked or pr[4] <= 0:
                    lx, ly = (x, y) if blocked else (nx, ny)
                    self.make_noise(lx, ly, 560)
                    self.add_fx(lx, ly, "glass")
                else:
                    pr[0], pr[1] = nx, ny
                    keep.append(pr)
                continue
            if blocked or pr[4] <= 0:
                continue
            hit = None
            for pl in alive:
                if math.hypot(nx - pl.x, ny - pl.y) < PLAYER_R + 5:
                    hit = pl
                    break
            if hit:
                self.hurt_player(hit, self.rnd.uniform(6, 10), "Proyectil zombi")
                if self.rnd.random() < 0.25 and not hit.bleeding:
                    hit.bleeding, hit.bleed_t = True, 30.0
                    self.msg("¡Te golpearon y sangras!", (255, 120, 120), hit)
                continue
            pr[0], pr[1] = nx, ny
            keep.append(pr)
        self.projs = keep

    # --- zombis ---------------------------------------------------------------------------------------------
    def zombie_sees(self, z, P):
        dark = self.dark_now
        rng = 380 * (1 - 0.55 * dark)
        if P.sneak:
            rng *= 0.55
        if P.flash_on and dark > 0.3:
            rng *= 1.5
        if z.d > rng:
            return False
        if z.d > 70 and abs(angdiff(math.atan2(P.y - z.y, P.x - z.x), z.angle)) > 1.2:
            return False
        return self.map.line_clear(z.x, z.y, P.x, P.y)

    def compute_flow(self, P):
        m = self.map
        start = (int(P.x // TS), int(P.y // TS))
        dist = {start: 0}
        dq = deque([start])
        rows, block, lim = m.t, FLOW_BLOCK, FLOW_R
        while dq:
            x, y = dq.popleft()
            d = dist[(x, y)]
            if d >= lim:
                continue
            d += 1
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < N and 0 <= ny < N and (nx, ny) not in dist and rows[ny][nx] not in block:
                    dist[(nx, ny)] = d
                    dq.append((nx, ny))
        return dist

    def flow_dir(self, z, P):
        flow = self.flows.get(P.pid)
        if not flow:
            return None
        tx, ty = int(z.x // TS), int(z.y // TS)
        d0 = flow.get((tx, ty))
        if d0 is None:
            return None
        m, best, bd = self.map, None, d0
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if not (dx or dy):
                    continue
                dn = flow.get((tx + dx, ty + dy))
                if dn is None or dn >= bd:
                    continue
                if dx and dy and (m.tile(tx + dx, ty) in FLOW_BLOCK or m.tile(tx, ty + dy) in FLOW_BLOCK):
                    continue
                best, bd = (tx + dx, ty + dy), dn
        if best is None:
            return None
        return (best[0] + 0.5) * TS, (best[1] + 0.5) * TS

    def update_zombies(self, dt):
        self.zombies = [z for z in self.zombies if z.alive]
        self.dark_now = self.darkness()
        alive = [pl for pl in self.players.values() if pl.alive]
        if not alive:
            return
        active = []
        for z in self.zombies:
            best, bd = None, 1e9
            for pl in alive:
                d = math.hypot(z.x - pl.x, z.y - pl.y)
                if d < bd:
                    best, bd = pl, d
            z.tp, z.d = best, bd
            if bd < ACTIVE_R:
                active.append(z)
        for pl in alive:
            t = self.flow_ts.get(pl.pid, 0.0) - dt
            age = self.flow_age.get(pl.pid, 99.0) + dt
            if t <= 0 and any(z.tp is pl and z.state == "chase" and z.d < FLOW_R * TS * 0.8 for z in active):
                tile = (int(pl.x // TS), int(pl.y // TS))
                # solo se recalcula si te moviste de casilla (o cada 3 s, por si cambió algún muro)
                if tile != self.flow_tile.get(pl.pid) or age > 3.0 or pl.pid not in self.flows:
                    self.flows[pl.pid] = self.compute_flow(pl)
                    self.flow_tile[pl.pid] = tile
                    age = 0.0
                    t = 0.6
                else:
                    t = 0.2
            self.flow_ts[pl.pid] = t
            self.flow_age[pl.pid] = age
        self.zt += 1
        near = []
        for z in active:                                 # los lejanos se simulan menos veces (con dt mayor)
            lod = 1 if z.d < 450 else (2 if z.d < 650 else 3)
            if lod == 1:
                self.update_zombie(z, dt, z.tp)
                near.append(z)
            elif (self.zt + z.id) % lod == 0:
                self.update_zombie(z, dt * lod, z.tp)

        if self.zt % 2:                                  # la separación entre zombis se calcula cada 2 ticks
            return
        grid = {}                                        # (hash espacial)
        for z in near:
            grid.setdefault((int(z.x // 40), int(z.y // 40)), []).append(z)
        k = min(1.0, dt * 16)
        sqrt = math.sqrt
        for z in near:
            cx, cy = int(z.x // 40), int(z.y // 40)
            zx, zy, zr = z.x, z.y, z.r
            px = py = 0.0
            for gx in (cx - 1, cx, cx + 1):
                for gy in (cy - 1, cy, cy + 1):
                    cell = grid.get((gx, gy))
                    if not cell:
                        continue
                    for o in cell:
                        if o is z:
                            continue
                        dx, dy = zx - o.x, zy - o.y
                        d2 = dx * dx + dy * dy
                        lim = (zr + o.r) * 0.85
                        if 1e-4 < d2 < lim * lim:
                            d = sqrt(d2)
                            f = (lim - d) * 0.5 / d
                            px += dx * f
                            py += dy * f
            if px or py:
                self.move_entity(z, px * k, py * k, zr)

    def zombie_attack(self, z, P):
        z.atk_cd = 1.3 + self.rnd.random() * 0.4
        if self.rnd.random() > 0.78:
            return
        self.hurt_player(P, self.rnd.uniform(6, 12) * z.dmg_mult * self.dmgm, "Zombi")
        r = self.rnd.random()
        if r < BITE_CHANCE * self.bitem:
            if FATAL_BITES and not P.infected:
                P.infected, P.inf_t = True, INFECTION_TIME
                self.msg("¡Te mordió! Estás infectado.", (255, 80, 80), P)
            else:
                self.msg("¡Te mordió!", (255, 80, 80), P)
            P.bleeding, P.bleed_t = True, 45.0
        elif r < BITE_CHANCE * self.bitem + 0.30:
            if not P.bleeding:
                self.msg("Estás sangrando. Usa una venda.", (255, 120, 120), P)
            P.bleeding, P.bleed_t = True, 45.0

    def zombie_throw(self, z, P):
        """Habilidad del Lanzador: tira una roca o una botella al jugador."""
        ang = math.atan2(P.y - z.y, P.x - z.x) + self.rnd.gauss(0, 0.05)
        speed = 300.0
        self.projs.append([z.x, z.y, math.cos(ang) * speed, math.sin(ang) * speed, 1.3,
                           self.rnd.choice((0, 1)), -1])

    def update_zombie(self, z, dt, P):
        m = self.map
        z.throw_cd -= dt
        z.lunge_cd -= dt
        z.scream_cd -= dt
        if z.stagger > 0:
            z.stagger -= dt
            self.move_entity(z, z.kx * dt, z.ky * dt, z.r)
            decay = max(0.0, 1 - 8 * dt)
            z.kx *= decay
            z.ky *= decay
            return
        z.atk_cd -= dt
        z.look_t -= dt
        if z.look_t <= 0:
            z.look_t = 0.25 + self.rnd.random() * 0.15
            was = z.sees
            z.sees = self.zombie_sees(z, P)
            if z.sees and not was and z.kind == "runner" and z.scream_cd <= 0 and self.rnd.random() < 0.5:
                z.scream_cd = 12.0                       # el Corredor grita y atrae a otros
                self.make_noise(z.x, z.y, 420)
                self.add_fx(z.x, z.y, "scream")
        if z.sees:
            z.state, z.to_player, z.lost_t = "chase", True, 7.0
            z.tx, z.ty = P.x, P.y

        if z.state == "chase":
            if not z.sees:
                z.lost_t -= dt
                if z.lost_t <= 0:
                    z.state = "idle"
                    return
                if z.to_player:
                    z.tx, z.ty = P.x, P.y
            if z.d < z.r + PLAYER_R + 5:
                z.angle = math.atan2(P.y - z.y, P.x - z.x)
                if z.atk_cd <= 0:
                    self.zombie_attack(z, P)
                return
            if z.kind == "thrower" and z.sees and 130 < z.d < 300:
                z.angle = math.atan2(P.y - z.y, P.x - z.x)
                if z.throw_cd <= 0:
                    z.throw_cd = self.rnd.uniform(2.2, 3.6)
                    self.zombie_throw(z, P)
                return
            ang = math.atan2(z.ty - z.y, z.tx - z.x)
            if z.to_player and not z.sees and z.kind != "breaker":   # el Rompemuros va en línea recta
                step = self.flow_dir(z, P)
                if step:
                    ang = math.atan2(step[1] - z.y, step[0] - z.x)
            elif not z.to_player and math.hypot(z.tx - z.x, z.ty - z.y) < 14:
                z.state = "idle"
                return
            if z.steer_t > 0:
                z.steer_t -= dt
                ang += z.steer_a
            z.angle = ang
            speed = z.speed * (1 + 0.15 * self.dark_now)
            if z.lunge_t > 0:                            # embestida: habilidad de normales y brutos
                z.lunge_t -= dt
                speed *= 1.9
            elif z.sees and z.d < 95 and z.lunge_cd <= 0 and z.kind in ("walker", "brute"):
                z.lunge_t, z.lunge_cd = 0.45, 4.0
            c, s = math.cos(ang), math.sin(ang)
            ax, ay = int((z.x + c * (z.r + 6)) // TS), int((z.y + s * (z.r + 6)) // TS)
            ahead = m.tile(ax, ay)
            if ahead == DOOR_C or (z.kind == "breaker" and ahead in BREAKABLE):
                # los zombis NO abren puertas: las destruyen; el Rompemuros también derriba paredes y ventanas
                power = 60.0 if z.kind == "breaker" else (40.0 if z.kind == "brute" else 14.0)
                if self.damage_tile(ax, ay, power * dt, None) == 0.0 and z.kind == "breaker":
                    self.add_fx(z.x, z.y, "scream")
                z.bash_noise -= dt
                if z.bash_noise <= 0:
                    z.bash_noise = 0.8
                    self.make_noise(z.x, z.y, 150)
                return
            mx, my = self.move_entity(z, c * speed * dt, s * speed * dt, z.r)
            if mx or my:
                z.stuck_t = max(0.0, z.stuck_t - dt)
            else:
                z.stuck_t += dt
                if z.stuck_t > 0.35 and z.steer_t <= 0:
                    z.steer_t = 0.6
                    z.steer_a = self.rnd.choice((-1, 1)) * self.rnd.uniform(0.9, 1.8)
                    z.stuck_t = 0.0
        else:
            z.wander_t -= dt
            if z.wander_t <= 0:
                z.wander_t = self.rnd.uniform(2, 5)
                z.wdir = None if self.rnd.random() < 0.4 else self.rnd.uniform(0, math.tau)
            if z.wdir is not None:
                z.angle = z.wdir
                mx, my = self.move_entity(z, math.cos(z.wdir) * z.speed * 0.45 * dt,
                                          math.sin(z.wdir) * z.speed * 0.45 * dt, z.r)
                if not (mx or my):
                    z.wander_t = 0

    # --- inventario e interacción ---------------------------------------------------------------------------------
    def load_factor(self, p):
        """Factor de velocidad por el peso: sin penalización hasta la mitad de la capacidad."""
        r = inv_weight(p.inv) / cap_of(p.inv)
        return 1.0 if r <= 0.5 else 1.0 - 0.35 * min(1.4, (r - 0.5) / 0.5)

    def room_for(self, p, item, qty):
        """Cuántas unidades de ese objeto aún te caben."""
        wt = ITEM_WEIGHT.get(item, 0.5)
        return max(0, min(qty, int((cap_of(p.inv) - inv_weight(p.inv)) / wt + 1e-9)))

    def give(self, p, item, qty=1):
        p.inv[item] = p.inv.get(item, 0) + qty
        if item in WEAPONS and item not in p.cond:
            p.cond[item] = WEAPONS[item]["dur"]

    def remove_item(self, p, item, qty=1):
        if qty <= 0:
            return
        p.inv[item] = p.inv.get(item, 0) - qty
        if p.inv[item] <= 0:
            p.inv.pop(item, None)
            if p.weapon == item:
                self.set_weapon(p, "fists")
            if item == "flashlight":
                p.flash_on = False

    def use_item(self, p, item):
        if p.inv.get(item, 0) <= 0 or not p.alive:
            return
        kind = ITEMS[item]["kind"]
        if kind == "weapon":
            self.set_weapon(p, item)
            self.msg(f"Equipado: {ITEMS[item]['name']}", (200, 220, 255), p)
        elif item == "flashlight":
            self.toggle_flash(p)
        elif kind == "food":
            if p.hunger < 8:
                self.msg("No tienes hambre.", (200, 200, 200), p)
                return
            p.hunger = max(0.0, p.hunger - ITEMS[item]["amount"])
            self.remove_item(p, item)
        elif kind == "drink":
            if p.thirst < 8:
                self.msg("No tienes sed.", (200, 200, 200), p)
                return
            p.thirst = max(0.0, p.thirst - ITEMS[item]["amount"])
            if item == "soda":
                p.hunger = max(0.0, p.hunger - 5)
            self.remove_item(p, item)
            if item == "water":
                self.give(p, "bottle", 1)                # te queda la botella vacía para lanzar
        elif item == "bandage":
            self.use_bandage(p)
        elif item == "medkit":
            p.hp = min(100.0, p.hp + 45)
            p.bleeding = False
            self.remove_item(p, item)
            self.msg("Te curaste con el botiquín.", (160, 255, 170), p)
        elif item == "battery":
            if p.inv.get("flashlight", 0) <= 0:
                self.msg("No tienes linterna.", (200, 200, 200), p)
                return
            p.battery = 100.0
            self.remove_item(p, item)
            self.msg("Cambiaste las pilas.", (200, 220, 255), p)
        elif kind == "fuel":
            car = self.car_near(p, 70)
            if car:
                self.refuel(p, car)
            else:
                self.msg("Acércate a un auto para echarle gasolina.", (200, 200, 200), p)
        elif kind == "ammo":
            self.msg("La munición se carga con la tecla de recargar (con el arma de fuego equipada).",
                     (200, 200, 200), p)
        elif item == "bottle":
            self.msg("Lánzala con su tecla (V) para atraer zombis.", (200, 200, 200), p)
        elif item == "planks":
            self.msg("Con los tablones construyes: modo construir (B).", (200, 200, 200), p)

    def use_bandage(self, p):
        if p.inv.get("bandage", 0) <= 0:
            self.msg("No tienes vendas.", (255, 190, 90), p)
        elif not p.bleeding:
            self.msg("No estás sangrando.", (200, 200, 200), p)
        else:
            p.bleeding = False
            self.remove_item(p, "bandage")
            self.msg("Te pusiste una venda.", (160, 255, 170), p)

    def auto_consume(self, p):
        order = (["water", "soda", "canned", "fish", "cookies"] if p.thirst >= p.hunger
                 else ["canned", "fish", "cookies", "water", "soda"])
        for item in order:
            if p.inv.get(item, 0) > 0:
                self.use_item(p, item)
                return
        self.msg("No tienes comida ni bebida.", (255, 190, 90), p)

    def cycle_weapon(self, p):
        opts = ["fists"] + [i for i in ("rod", "knife", "pan", "bat", "axe", "pistol", "smg", "shotgun", "rifle")
                            if p.inv.get(i, 0) > 0]
        self.set_weapon(p, opts[(opts.index(p.weapon) + 1) % len(opts)] if p.weapon in opts else "fists")

    def toggle_flash(self, p):
        if p.inv.get("flashlight", 0) <= 0:
            self.msg("No tienes linterna.", (200, 200, 200), p)
        elif p.battery <= 0:
            self.msg("La linterna no tiene pilas.", (255, 190, 90), p)
        else:
            p.flash_on = not p.flash_on

    def find_interact(self, p=None):
        p = p or self.p
        m = self.map
        ptx, pty = int(p.x // TS), int(p.y // TS)
        best = None
        for ty in range(pty - 2, pty + 3):
            for tx in range(ptx - 2, ptx + 3):
                t = m.tile(tx, ty)
                if t not in (DOOR_C, DOOR_O, CONT, WATER):
                    continue
                cx, cy = (tx + 0.5) * TS, (ty + 0.5) * TS
                d = math.hypot(cx - p.x, cy - p.y)
                if d > INTERACT_DIST:
                    continue
                if d > 34 and abs(angdiff(math.atan2(cy - p.y, cx - p.x), p.angle)) > 1.1:
                    continue
                if best is None or d < best[0]:
                    best = (d, tx, ty, t)
        return best

    def find_ground(self, p):
        best = None
        for it in self.items.values():
            d = math.hypot(it[0] - p.x, it[1] - p.y)
            if d <= 40 and (best is None or d < best[0]):
                best = (d, it)
        return best

    def interact_text(self, p=None):
        p = p or self.p
        if p.car is not None:
            return "[E] Bajar del auto"
        car = self.car_near(p)
        if car:
            return f"[E] Subir al auto  (gasolina {int(car.fuel)}%)" + ("  - usa un bidón para llenarlo"
                                                                       if car.fuel < 15 else "")
        gnd = self.find_ground(p)
        b = self.find_interact(p)
        if gnd and (not b or gnd[0] <= b[0]):
            it = gnd[1]
            return f"[E] Recoger {ITEMS[it[2]]['name']}" + (f" x{it[3]}" if it[3] > 1 else "")
        if not b:
            return ""
        if b[3] == DOOR_C:
            return "[E] Abrir puerta"
        if b[3] == DOOR_O:
            return "[E] Cerrar puerta"
        if b[3] == WATER:
            return "[E] Pescar" if p.weapon == "rod" else "[E] Beber agua del lago"
        c = self.map.containers.get((b[1], b[2]))
        name = CONT_NAMES.get(c["kind"], "mueble") if c else "mueble"
        return f"[E] Abrir {name.lower()}" + (" (vacío)" if c and c["looted"] else "")

    def interact(self, p):
        if p.car is not None:
            self.exit_car(p)
            return
        car = self.car_near(p)
        if car:
            self.enter_car(p, car)
            return
        gnd = self.find_ground(p)
        b = self.find_interact(p)
        if gnd and (not b or gnd[0] <= b[0]):
            self.pickup(p, gnd[1])
            return
        if not b:
            return
        _, tx, ty, t = b
        if t == DOOR_C:
            self.set_tile(tx, ty, DOOR_O)
            self.make_noise((tx + 0.5) * TS, (ty + 0.5) * TS, 90)
        elif t == DOOR_O:
            cx, cy = (tx + 0.5) * TS, (ty + 0.5) * TS
            blockers = list(self.players.values()) + self.zombies
            if any(math.hypot(e.x - cx, e.y - cy) < 22 for e in blockers):
                self.msg("Hay alguien en la puerta.", (255, 190, 90), p)
            else:
                self.set_tile(tx, ty, DOOR_C)
        elif t == WATER:
            if p.weapon == "rod":
                if not p.fish:
                    p.work = p.search = None
                    p.fish = [tx, ty, 0.0, self.rnd.uniform(4.0, 8.0)]
                    self.make_noise(p.x, p.y, 35)
                    self.msg("Lanzas la caña... espera sin moverte.", (150, 200, 255), p)
            elif p.drink_cd <= 0:
                p.drink_cd = 1.0
                p.thirst = max(0.0, p.thirst - 18)
                self.msg("Bebes agua del lago.", (150, 200, 255), p)
        else:
            c = self.map.containers.get((tx, ty))
            if c is None:
                return
            p.work = p.fish = None
            if not c["rolled"]:
                if not p.search:                          # la primera vez hay que revolverlo
                    p.search = [tx, ty, 0.0, 1.4]
                    self.make_noise(p.x, p.y, 50)
            else:
                self.open_container(p, tx, ty)

    def update_fishing(self, p, dt):
        f = p.fish
        if p.weapon != "rod" or self.map.tile(f[0], f[1]) != WATER:
            p.fish = None
            return
        f[2] += dt
        if f[2] < f[3]:
            return
        p.fish = None
        r = self.rnd.random()
        if r < 0.62:
            self.give(p, "fish", 1)
            self.msg("¡Pescaste un pez!", (150, 230, 255), p)
        elif r < 0.74:
            self.give(p, "bottle", 1)
            self.msg("Pescaste una botella vacía.", (190, 220, 235), p)
        else:
            self.msg("Se escapó... vuelve a lanzar.", (200, 200, 200), p)
        self.wear_weapon(p, 1)

    # --- objetos en el suelo -------------------------------------------------------------------------
    def spawn_item(self, x, y, item, qty):
        if qty <= 0:
            return
        for it in self.items.values():                       # se apilan con los cercanos
            if it[2] == item and math.hypot(it[0] - x, it[1] - y) < 14:
                it[3] += qty
                return
        iid = self.next_iid
        self.next_iid += 1
        self.items[iid] = [x, y, item, qty, iid]
        if len(self.items) > 400:
            del self.items[min(self.items)]

    def pickup(self, p, it):
        if it[4] not in self.items:
            return
        orig = it[3]
        n = self.room_for(p, it[2], orig)
        if n <= 0:
            self.msg("Llevas demasiado peso. Suelta algo para recoger esto.", (255, 190, 90), p)
            return
        if n < orig:
            it[3] -= n
        else:
            del self.items[it[4]]
        self.give(p, it[2], n)
        self.msg(f"Recoges {ITEMS[it[2]]['name']}" + (f" x{n}" if n > 1 else "") +
                 (" (no te cabe todo)" if n < orig else ""), (170, 255, 190), p)

    def _item_arg(self, arg):
        try:
            item, qty = arg
            qty = int(qty)
        except (TypeError, ValueError):
            return None
        if not isinstance(item, str) or item not in ITEMS or not 0 <= qty <= 9999:
            return None
        return item, qty

    def drop_item(self, p, arg):
        a = self._item_arg(arg)
        if not a:
            return
        item, qty = a
        have = p.inv.get(item, 0)
        n = have if qty == 0 else min(qty, have)
        if n <= 0:
            return
        self.remove_item(p, item, n)
        ang = p.angle
        x, y = p.x + math.cos(ang) * 18, p.y + math.sin(ang) * 18
        if not self.map.free(x, y, 3):
            x, y = p.x, p.y
        self.spawn_item(x, y, item, n)
        self.msg(f"Tiras {ITEMS[item]['name']}" + (f" x{n}" if n > 1 else ""), (200, 200, 200), p)

    # --- muebles con inventario ----------------------------------------------------------------------
    def roll_loot(self, c):
        rnd = self.rnd
        q = c.get("q", 0)
        n = weighted(rnd, ITEM_COUNT_BY_QUALITY[q])[0] * self.lmul
        n = int(n) + (1 if rnd.random() < n - int(n) else 0)
        table = [(i, wt * (1 + 1.2 * q if i in RARE_ITEMS else 1), lo, hi) for i, wt, lo, hi in LOOT[c["kind"]]]
        for _ in range(n):
            item, _, lo, hi = weighted(rnd, table)
            qty = rnd.randint(lo, hi) + (1 if item in ("ammo", "planks") and q >= 2 else 0)
            c["inv"][item] = c["inv"].get(item, 0) + qty
        c["rolled"] = True

    def sync_container(self, tx, ty, c):
        """Actualiza el aspecto (vacío o no) del mueble y avisa a los clientes."""
        empty = not c["inv"]
        if c["looted"] != empty:
            c["looted"] = empty
            self.map.chunks.pop((tx // CH, ty // CH), None)
            self.ev_loot.append([tx, ty, int(empty)])

    def open_container(self, p, tx, ty):
        c = self.map.containers.get((tx, ty))
        if c is None:
            return
        if not c["rolled"]:
            self.roll_loot(c)
            self.sync_container(tx, ty, c)
        p.open = (tx, ty)
        p.search = None

    def finish_search(self, p, tx, ty):
        self.open_container(p, tx, ty)

    def take_item(self, p, arg):
        a = self._item_arg(arg)
        c = self.map.containers.get(p.open) if p.open else None
        if not a or c is None:
            return
        item, qty = a
        have = c["inv"].get(item, 0)
        n = have if qty == 0 else min(qty, have)
        fit = self.room_for(p, item, n)
        if fit < n:
            self.msg("No puedes cargar tanto peso." if fit <= 0 else "Solo te cabe una parte.", (255, 190, 90), p)
        n = fit
        if n <= 0:
            return
        if have - n > 0:
            c["inv"][item] = have - n
        else:
            del c["inv"][item]
        self.give(p, item, n)
        self.sync_container(p.open[0], p.open[1], c)

    def put_item(self, p, arg):
        a = self._item_arg(arg)
        c = self.map.containers.get(p.open) if p.open else None
        if not a or c is None:
            return
        item, qty = a
        have = p.inv.get(item, 0)
        n = have if qty == 0 else min(qty, have)
        if n <= 0:
            return
        self.remove_item(p, item, n)
        c["inv"][item] = c["inv"].get(item, 0) + n
        self.sync_container(p.open[0], p.open[1], c)

    def restock(self):
        """Cada día nuevo, los muebles que quedaron vacíos vuelven a tener botín."""
        n = 0
        for (x, y), c in self.map.containers.items():
            if c["kind"] != "chest" and c["looted"]:
                c["rolled"], c["looted"] = False, False
                self.map.chunks.pop((x // CH, y // CH), None)
                self.ev_loot.append([x, y, 0])
                n += 1
        if n:
            self.msg(f"Amanece el día {self.day()}: {n} muebles tienen botín nuevo.", (255, 235, 150))


# ----------------------------------------------------------------------------
# Red: mensajes JSON con prefijo de longitud sobre TCP no bloqueante
# ----------------------------------------------------------------------------
class Conn:
    def __init__(self, sock):
        sock.setblocking(False)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        self.sock = sock
        self.rbuf = bytearray()
        self.wbuf = bytearray()
        self.dead = False
        self.pid = None
        self.t0 = time.time()

    def send(self, obj):
        data = json.dumps(obj, separators=(",", ":")).encode()
        self.wbuf += struct.pack(">I", len(data)) + data

    def pump(self):
        if self.dead:
            return
        try:
            while True:
                chunk = self.sock.recv(65536)
                if not chunk:
                    self.dead = True
                    break
                self.rbuf += chunk
        except (BlockingIOError, InterruptedError):
            pass
        except OSError:
            self.dead = True
        if self.wbuf and not self.dead:
            try:
                n = self.sock.send(self.wbuf)
                del self.wbuf[:n]
            except (BlockingIOError, InterruptedError):
                pass
            except OSError:
                self.dead = True
        if len(self.wbuf) > 4_000_000:
            self.dead = True

    def messages(self):
        out = []
        while len(self.rbuf) >= 4:
            n = struct.unpack(">I", self.rbuf[:4])[0]
            if n > 8_000_000:
                self.dead = True
                break
            if len(self.rbuf) < 4 + n:
                break
            data = bytes(self.rbuf[4:4 + n])
            del self.rbuf[:4 + n]
            try:
                out.append(json.loads(data))
            except ValueError:
                pass
        return out

    def close(self):
        self.dead = True
        try:
            self.sock.close()
        except OSError:
            pass


class Server:
    """Servidor autoritativo: simula el mundo y envía snapshots a cada cliente."""

    def __init__(self, game, port=PORT):
        self.game = game
        self.port = port
        self.lsock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.lsock.bind(("0.0.0.0", port))
        self.lsock.listen(8)
        self.lsock.setblocking(False)
        self.pending = []
        self.clients = {}
        self.snap_t = 0.0
        self.label = "Partida"
        self.beacon = LanBeacon(lambda: dict(name=self.label, port=self.port, n=len(self.game.players)))

    def close(self):
        if getattr(self, "beacon", None):
            self.beacon.close()
        for c in list(self.clients.values()) + self.pending:
            c.close()
        try:
            self.lsock.close()
        except OSError:
            pass

    def poll(self, dt):
        self.beacon.tick(dt)
        while True:
            try:
                s, _ = self.lsock.accept()
            except (BlockingIOError, InterruptedError):
                break
            except OSError:
                break
            self.pending.append(Conn(s))
        self.service()

    def service(self):
        """Atiende a los clientes ya conectados (sirve igual para sockets y para WebRTC)."""
        for c in list(self.pending):
            c.pump()
            for m in c.messages():
                if m.get("t") == "hello":
                    self.accept_client(c, m)
                    break
            if c in self.pending and (c.dead or time.time() - c.t0 > 10):
                self.pending.remove(c)
                c.close()
        for pid, c in list(self.clients.items()):
            c.pump()
            p = self.game.players.get(pid)
            if p is not None:
                for m in c.messages():
                    self.handle(p, m)
            if c.dead:
                self.drop(pid)

    def accept_client(self, c, m):
        self.pending.remove(c)
        g = self.game
        if len(g.players) >= MAX_PLAYERS:
            c.send({"t": "full"})
            c.pump()
            c.close()
            return
        name = "".join(ch for ch in str(m.get("name", "Jugador")) if ch.isprintable())[:14].strip() or "Jugador"
        p = g.add_player(name, remote=True)
        if m.get("hat") in HATS:
            p.hat = m["hat"]
        c.pid = p.pid
        self.clients[p.pid] = c
        c.send({"t": "welcome", "pid": p.pid, "pos": [p.x, p.y], "name": p.name,
                "m": g.minutes, "map": g.map.to_dict(), "gs": g.settings})
        c.pump()
        g.msg(f"{p.name} se unió a la partida.", (170, 255, 190))

    def handle(self, p, m):
        t = m.get("t")
        if t == "in":
            try:
                v = dict(x=float(m["x"]), y=float(m["y"]), a=float(m["a"]), mv=int(m["mv"]),
                         run=int(m["run"]), aim=int(m["aim"]), hold=int(m["hold"]), sn=int(m["sn"]),
                         mx=float(m["mx"]), my=float(m["my"]), dm=int(m["dm"]))
                dv = m.get("dv") or (0, 0)
                v["dv"] = (max(-1.0, min(1.0, float(dv[0]))), max(-1.0, min(1.0, float(dv[1]))))
            except (KeyError, ValueError, TypeError, IndexError):
                return
            if all(math.isfinite(v[k]) for k in ("x", "y", "a", "mx", "my")):
                p.inp = v
        elif t == "act":
            self.game.do_action(p, m.get("a"), m.get("arg"))
        elif t == "chat":
            text = str(m.get("x", ""))[:80].strip()
            if text:
                self.game.msg(f"{p.name}: {text}", (255, 255, 170))

    def drop(self, pid):
        c = self.clients.pop(pid, None)
        if c:
            c.close()
        p = self.game.players.pop(pid, None)
        if p:
            self.game.release_car(pid)
            self.game.msg(f"{p.name} se desconectó.", (255, 190, 90))

    def snapshot(self, pl):
        g = self.game
        me = dict(hp=round(pl.hp, 1), hunger=round(pl.hunger, 1), thirst=round(pl.thirst, 1),
                  stamina=round(pl.stamina, 1), exh=int(pl.exhausted), bl=int(pl.bleeding),
                  inf=int(pl.infected), it=round(pl.inf_t, 1), wp=pl.weapon, mag=pl.mag,
                  fl=int(pl.flash_on), bat=round(pl.battery, 1), k=pl.kills, al=int(pl.alive),
                  cs=pl.cause, rl=round(pl.reload_t, 2), inv=pl.inv, cond=pl.cond,
                  se=pl.search, wk=pl.work, sw=int(pl.swing_t > 0), hu=int(pl.hurt_ev),
                  fs=pl.fish, hat=pl.hat, car=-1 if pl.car is None else pl.car)
        if pl.open and pl.open in g.map.containers:
            c = g.map.containers[pl.open]
            me["cv"] = [pl.open[0], pl.open[1], c["kind"], c["inv"]]
        if pl.fix:
            me["fx"] = [round(pl.x, 1), round(pl.y, 1)]
            pl.fix = False
        pl.hurt_ev = False
        others = [[o.pid, round(o.x, 1), round(o.y, 1), round(o.angle, 2), o.weapon, int(o.flash_on),
                   int(o.sneak), int(o.swing_t > 0), int(o.hp), o.name, o.hat]
                  for o in g.players.values() if o is not pl and o.alive]
        zs = []
        for z in g.zombies:
            if abs(z.x - pl.x) < VIEW_R and abs(z.y - pl.y) < VIEW_R:
                zs.append([z.id, round(z.x, 1), round(z.y, 1), round(z.angle, 2),
                           1 if z.state == "chase" else 0, int(100 * max(0.0, z.hp) / z.max_hp),
                           z.skin_i, z.cloth_i, KINDS.index(z.kind)])
                if len(zs) >= 180:
                    break
        prs = [[round(pr[0], 1), round(pr[1], 1), pr[5]] for pr in g.projs
               if abs(pr[0] - pl.x) < VIEW_R and abs(pr[1] - pl.y) < VIEW_R]
        gi = [[it[4], round(it[0]), round(it[1]), it[2], it[3]] for it in g.items.values()
              if abs(it[0] - pl.x) < VIEW_R and abs(it[1] - pl.y) < VIEW_R][:120]
        cars = [[c.id, round(c.x, 1), round(c.y, 1), round(c.angle, 2), int(c.fuel), int(c.hp),
                 -1 if c.driver is None else c.driver, c.ci, int(c.v)]
                for c in g.cars if abs(c.x - pl.x) < VIEW_R + 200 and abs(c.y - pl.y) < VIEW_R + 200]
        msgs, pl.outbox = pl.outbox, []
        return {"t": "snap", "cars": cars, "gi": gi, "m": round(g.minutes, 2), "me": me, "pl": others, "z": zs, "pr": prs, "msg": msgs,
                "ev": {"tr": g.ev_tracers, "co": g.ev_corpses, "ti": g.ev_tiles, "lo": g.ev_loot,
                       "fx": g.ev_fx, "ct": g.ev_cont}}

    def broadcast(self, dt):
        self.snap_t -= dt
        if self.snap_t > 0:
            return
        self.snap_t = 1.0 / SNAP_HZ
        g = self.game
        for pid, c in list(self.clients.items()):
            p = g.players.get(pid)
            if p is not None and not c.dead and not getattr(c, "congested", lambda: False)():
                c.send(self.snapshot(p))
                c.pump()
        g.clear_events()


class Client:
    def __init__(self, ip, port, name, hat="none"):
        sock = socket.create_connection((ip, port), timeout=6)
        self.conn = Conn(sock)
        self.conn.send({"t": "hello", "name": name, "v": 4, "hat": hat})
        self.backlog = []

    def wait_welcome(self, timeout=12.0):
        t0 = time.time()
        while time.time() - t0 < timeout:
            self.conn.pump()
            msgs = self.conn.messages()
            for i, m in enumerate(msgs):
                if m.get("t") == "welcome":
                    self.backlog = msgs[i + 1:]
                    return m
                if m.get("t") == "full":
                    raise ConnectionError("la partida está llena")
            if self.conn.dead:
                raise ConnectionError("el servidor cerró la conexión")
            try:
                pygame.event.pump()
            except Exception:
                pass
            time.sleep(0.02)
        raise ConnectionError("tiempo de espera agotado")

    def send(self, obj):
        self.conn.send(obj)
        self.conn.pump()

    def poll(self):
        self.conn.pump()
        msgs = self.backlog + self.conn.messages()
        self.backlog = []
        return msgs

    def close(self):
        self.conn.close()


# ----------------------------------------------------------------------------
# Red para el navegador: WebRTC a través de znet.js (sin sockets TCP)
# ----------------------------------------------------------------------------
_ZNET = None


def get_znet():
    """Devuelve el objeto JavaScript ZNet (znet.js), cargándolo la primera vez (solo en el navegador)."""
    global _ZNET
    if _ZNET is None:
        import platform
        win = platform.window
        if str(win.eval("typeof window.ZNet")) != "object":
            import znet_js
            win.eval(znet_js.SOURCE)
        _ZNET = win.ZNet
    return _ZNET


class WebConn:
    """Igual que Conn, pero los mensajes viajan por un canal WebRTC."""

    def __init__(self, hub, peer_id):
        self.hub = hub
        self.id = peer_id
        self.inq = []
        self.dead = False
        self.pid = None
        self.t0 = time.time()

    def send(self, obj):
        if not self.dead:
            self.hub.send_to(self.id, json.dumps(obj, separators=(",", ":")))

    def pump(self):
        pass

    def messages(self):
        out, self.inq = self.inq, []
        return out

    def congested(self):
        try:
            return int(self.hub.z.buffered()) > 300000      # el otro jugador va lento: saltamos snapshots
        except Exception:
            return False

    def close(self):
        self.dead = True


class WebServer(Server):
    """Servidor que corre en el navegador del anfitrión; los jugadores entran con un código de sala."""

    def __init__(self, game, znet=None):
        self.game = game
        self.port = 0
        self.pending = []
        self.clients = {}
        self.snap_t = 0.0
        self.label = "Partida"
        self.beacon = None
        self.z = znet or get_znet()
        self.code = str(self.z.host())
        self.conns = {}

    def send_to(self, peer_id, text):
        self.z.send(text, peer_id)

    def close(self):
        for c in list(self.clients.values()) + self.pending:
            c.close()
        try:
            self.z.close()
        except Exception:
            pass

    def drain(self):
        for _ in range(400):                                 # límite por fotograma
            raw = str(self.z.pop())
            if not raw:
                break
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            pid = m.get("from")
            if m.get("sys") == "join":
                c = WebConn(self, pid)
                self.conns[pid] = c
                self.pending.append(c)
            elif m.get("sys") == "leave":
                c = self.conns.pop(pid, None)
                if c:
                    c.dead = True
            elif "data" in m:
                c = self.conns.get(pid)
                if c:
                    try:
                        c.inq.append(json.loads(m["data"]))
                    except ValueError:
                        pass

    def poll(self, dt):
        self.drain()
        self.service()


class WebClient:
    """Cliente que entra a una sala con su código. La conexión es asíncrona: se avanza con advance()."""

    def __init__(self, code, name, hat="none", znet=None):
        self.z = znet or get_znet()
        self.name, self.hat = name, hat
        self.conn = WebConn(self, "host")
        self.hello_sent = False
        self.welcome = None
        self.backlog = []
        self.t_start = time.time()
        self.z.join(str(code))

    def send_to(self, peer_id, text):
        self.z.send(text, "")

    def _drain(self):
        for _ in range(400):
            raw = str(self.z.pop())
            if not raw:
                break
            try:
                m = json.loads(raw)
            except ValueError:
                continue
            if m.get("sys") == "leave":
                self.conn.dead = True
            elif "data" in m:
                try:
                    self.conn.inq.append(json.loads(m["data"]))
                except ValueError:
                    pass
        if str(self.z.status()).startswith("error"):
            self.conn.dead = True

    def advance(self):
        """Devuelve 'wait', 'ok' o un texto de error."""
        st = str(self.z.status())
        if st.startswith("error"):
            return st[6:] or "error de conexión"
        if time.time() - self.t_start > 60:
            return "tiempo de espera agotado"
        if st == "connected" and not self.hello_sent:
            self.hello_sent = True
            self.conn.send({"t": "hello", "name": self.name, "v": 4, "hat": self.hat})
        self._drain()
        msgs = self.conn.messages()
        for i, m in enumerate(msgs):
            if m.get("t") == "welcome":
                self.welcome = m
                self.backlog = msgs[i + 1:]
                return "ok"
            if m.get("t") == "full":
                return "la partida está llena"
        return "wait"

    def send(self, obj):
        self.conn.send(obj)

    def poll(self):
        self._drain()
        msgs = self.backlog + self.conn.messages()
        self.backlog = []
        return msgs

    def close(self):
        self.conn.dead = True
        try:
            self.z.close()
        except Exception:
            pass


class ClientGame(Game):
    """Vista del mundo en un cliente: se rellena con los snapshots del servidor."""

    def __init__(self, welcome):
        self.map = GameMap.from_dict(welcome["map"])
        self.seed = self.map.seed
        self.pid = welcome["pid"]
        self.p = Player(welcome["pos"][0], welcome["pos"][1], self.pid, welcome["name"])
        self.players = {self.pid: self.p}
        self.others = {}
        self.zombies = []
        self._zmap = {}
        self.corpses = deque(maxlen=260)
        self.tracers = []
        self.projs = []
        self.fx = []
        self.set_settings(welcome.get("gs"))
        self.cars = []
        self._cmap = {}
        self.minutes = float(welcome["m"])
        self.shake = 0.0
        self.items = {}
        self.ev_cont = []
        self.msg("Conectado. ¡Sobrevive!", (170, 255, 190), self.p)

    def other_players(self):
        return list(self.others.values())

    def update(self, dt, inp):
        self.tick_effects(dt)
        self.minutes += dt * GAME_MIN_PER_SEC * self.tmul
        p = self.p
        k = min(1.0, dt * 14)
        for c in self.cars:
            c.x += (c.tx - c.x) * k
            c.y += (c.ty - c.y) * k
            c.angle += ((c.ta - c.angle + math.pi) % math.tau - math.pi) * k
        mine = self.my_car()
        if p.alive and mine is None:
            self.control_move(p, dt, inp)
        elif p.alive:
            p.x, p.y, p.angle, p.moving = mine.x, mine.y, mine.angle, False
        p.swing_t -= dt
        p.hurt_t -= dt
        for z in self.zombies:
            z.x += (z.tx - z.x) * k
            z.y += (z.ty - z.y) * k
        for o in self.others.values():
            o.x += (o.tx - o.x) * k
            o.y += (o.ty - o.y) * k
            o.swing_t -= dt

    def apply_snap(self, s):
        self.minutes = float(s["m"])
        me, p = s["me"], self.p
        p.hp, p.hunger, p.thirst, p.stamina = me["hp"], me["hunger"], me["thirst"], me["stamina"]
        p.exhausted, p.bleeding, p.infected, p.inf_t = bool(me["exh"]), bool(me["bl"]), bool(me["inf"]), me["it"]
        p.weapon, p.mag, p.flash_on, p.battery = me["wp"], me["mag"], bool(me["fl"]), me["bat"]
        p.kills, p.alive, p.cause, p.reload_t = me["k"], bool(me["al"]), me["cs"], me["rl"]
        p.inv, p.cond, p.search, p.work = me["inv"], me["cond"], me["se"], me.get("wk")
        p.fish, p.hat = me.get("fs"), me.get("hat", p.hat)
        cv = me.get("cv")
        p.open = (cv[0], cv[1]) if cv else None
        p.cview = cv
        self.items = {g[0]: [g[1], g[2], g[3], g[4], g[0]] for g in s.get("gi", [])}
        cid = me.get("car", -1)
        p.car = None if cid < 0 else cid
        if "fx" in me:
            p.x, p.y = me["fx"]
        if me["sw"]:
            p.swing_t = 0.14
        if me["hu"]:
            p.hurt_t, self.shake = 0.3, 0.25

        seen = set()
        for pid, x, y, a, wp, fl, sn, sw, hp, name, hat in s["pl"]:
            o = self.others.get(pid)
            if o is None:
                o = Player(x, y, pid, name)
                self.others[pid] = o
            o.hat = hat if hat in HATS else "none"
            o.tx, o.ty, o.angle, o.weapon = x, y, a, wp
            o.flash_on, o.sneak, o.hp = bool(fl), bool(sn), hp
            if sw:
                o.swing_t = 0.14
            seen.add(pid)
        for pid in [k for k in self.others if k not in seen]:
            del self.others[pid]

        zm, new = {}, []
        for zid, x, y, a, st, hpp, si, ci, ki in s["z"]:
            z = self._zmap.get(zid)
            kind = KINDS[ki % len(KINDS)]
            if z is None:
                z = ZView(zid, x, y, kind)
            z.tx, z.ty, z.angle = x, y, a
            z.state = "chase" if st else "idle"
            z.hp = float(hpp)
            z.skin, z.cloth = Zombie.SKINS[si % len(Zombie.SKINS)], Zombie.CLOTHES[ci % len(Zombie.CLOTHES)]
            zm[zid] = z
            new.append(z)
        self.zombies, self._zmap = new, zm
        self.projs = [[x, y, 0, 0, 0, k, 0] for x, y, k in s.get("pr", [])]
        cm, cnew = {}, []
        for cid2, x, y, a, fu, hp, dr, ci, v in s.get("cars", []):
            c = self._cmap.get(cid2)
            if c is None:
                c = CarView(cid2, x, y, a)
            c.tx, c.ty, c.ta = x, y, a
            c.fuel, c.hp, c.driver, c.ci, c.v = fu, hp, (None if dr < 0 else dr), ci, v
            c.color = CAR_COLORS[ci % len(CAR_COLORS)]
            cm[cid2] = c
            cnew.append(c)
        self.cars, self._cmap = cnew, cm

        for text, col in s["msg"]:
            p.msgs.append([text, 5.0, tuple(col)])
            del p.msgs[:-5]
        ev = s["ev"]
        for x1, y1, x2, y2, col, w in ev["tr"]:
            self.tracers.append([x1, y1, x2, y2, tuple(col), w, 0.08])
        for x, y, a, col in ev["co"]:
            self.corpses.append((x, y, a, tuple(col)))
        for x, y, v in ev["ti"]:
            self.map.set_tile(x, y, v)
        for x, y, empty in ev["lo"]:
            c = self.map.containers.get((x, y))
            if c:
                c["looted"] = bool(empty)
                self.map.chunks.pop((x // CH, y // CH), None)
        for x, y, kind, _ in ev.get("ct", []):
            self.map.containers[(x, y)] = dict(kind=kind, looted=True, q=0, rolled=True, inv={})
        for x, y, kind in ev.get("fx", []):
            self.fx.append([x, y, kind, 0.6])


def run_dedicated(port, seed=None, settings=None):
    g = Game(seed=seed, local=False, settings=settings)
    srv = Server(g, port)
    print(f"Servidor Zomboid Py en el puerto TCP {port}  (semilla {g.seed}, Ctrl+C para salir)")
    last, report = time.time(), 0.0
    try:
        while True:
            now = time.time()
            dt = min(now - last, 0.05)
            last = now
            srv.poll(dt)
            g.update(dt, None)
            srv.broadcast(dt)
            report -= dt
            if report <= 0:
                report = 30.0
                print(f"[{g.clock()}] jugadores: {len(g.players)}  zombis: {len(g.zombies)}")
            time.sleep(max(0.0, 1 / 30 - (time.time() - now)))
    except KeyboardInterrupt:
        srv.close()


# ----------------------------------------------------------------------------
# Interfaz: menús (modo inmediato), ajustes, dibujo del mundo y HUD
# ----------------------------------------------------------------------------
ITEM_COLORS = {"weapon": (205, 205, 215), "food": (225, 150, 60), "drink": (80, 150, 230),
               "material": (170, 125, 70)}

FIELD_RULES = {                      # campo -> (caracteres permitidos o None, longitud máxima)
    "room": ("ABCDEFGHJKLMNPQRSTUVWXYZ23456789abcdefghjklmnpqrstuvwxyz", 6),
    "name": (None, 14), "port": ("0123456789", 5), "seed": (None, 20), "sseed": (None, 20),
    "ip": ("0123456789.:abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ-", 40),
}


class App:
    def __init__(self, auto=None):
        pygame.init()
        pygame.display.set_caption("Zomboid Py")
        self.cfg = load_cfg()
        self.gs = self.cfg["game"]
        self.last_dt = 0.016
        self.gset_back = "solo"
        self.bind = self.cfg["keys"]
        self.fonts = {}
        self.screen = None
        self.apply_display()
        self.clock = pygame.time.Clock()
        self.state = "title"                # title | solo | online | settings | play
        self.mode = "solo"                  # solo | host | client
        self.menu_open = False              # menú de pausa dentro de la partida
        self.menu_page = "pause"            # pause | settings
        self.back_to = "title"
        self.show_map = self.cfg["minimap"]
        self.sneak = False
        self.attack_held = False
        self.build_mode = False
        self.build_piece = 0
        self.inv_rows = []
        self.fields = dict(name=self.cfg["name"], port=str(self.cfg["port"]), seed="", sseed="", ip="127.0.0.1",
                           room="")
        self.room_code = ""
        self.focus = None
        self.rebind = None
        self.net_msg = ""
        self.has_save = save_exists()
        self.chat = None
        self.server = None
        self.client = None
        self.scanner = None
        self.inv_open = False
        self.inv_by_cont = False
        self.inv_panel = 0
        self.inv_sel = [0, 0]
        self.cont_prev = None
        self.cont_ignore = 0.0
        self.cam = (0, 0)
        self.kb_idx = -1
        self.nav_n = 0
        self.nav_i = 0
        self.kb_activate = False
        self._nav_sig = None
        self.my_ip = "" if IS_WEB else lan_ip()
        self.send_t = 0.0
        self.click = None
        self.press = None
        self.mouse_pos = (0, 0)
        self.mouse_world = (0, 0)
        self.t = 0.0
        self.make_light_sprites()
        self.light_lo = pygame.Surface((W // LQ, H // LQ), 0, 32)
        self.light_full = pygame.Surface((W, H), 0, 32)
        self.fast_light = IS_WEB
        self.txt_cache = {}
        self.prof = {}
        self.game = None
        self.minimap = None
        self.walkers = [[random.uniform(0, W), random.uniform(25, 55), random.uniform(15, 40)] for _ in range(7)]
        if auto:
            if auto[0] == "host":
                self.start_host(auto[1], auto[2] if len(auto) > 2 else None)
            elif auto[0] == "join":
                self.start_join(auto[1])

    def apply_display(self):
        flags = (pygame.FULLSCREEN | pygame.SCALED) if self.cfg["fullscreen"] else 0
        try:
            self.screen = pygame.display.set_mode((W, H), flags)
        except Exception:
            self.screen = pygame.display.set_mode((W, H))

    @property
    def name(self):
        return (self.fields["name"].strip() or default_name())[:14]

    def save_settings(self):
        self.cfg["name"] = self.name
        try:
            port = int(self.fields["port"])
            if 1024 <= port <= 65535:
                self.cfg["port"] = port
        except ValueError:
            pass
        self.cfg["keys"] = self.bind
        self.cfg["minimap"] = self.show_map
        save_cfg(self.cfg)

    # --- iniciar / terminar partidas -------------------------------------------------------
    def stop_net(self):
        if self.server:
            self.server.close()
        if self.client:
            self.client.close()
        self.server = self.client = None

    def begin(self, game, mode):
        self.game = game
        self.mode = mode
        self.minimap = game.map.minimap(150)
        self.menu_open = False
        self.menu_page = "pause"
        self.build_mode = False
        self.sneak = False
        self.chat = None
        self.state = "play"
        self.net_msg = ""
        self.inv_open = self.inv_by_cont = False
        self.cont_prev = None
        if self.scanner:
            self.scanner.close()
            self.scanner = None
        self.act("hat", self.cfg["hat"])

    def start_solo(self, seed_text=""):
        self.stop_net()
        self.begin(Game(seed=parse_seed(seed_text), name=self.name, hat=self.cfg["hat"], settings=self.gs), "solo")

    def save_game(self):
        g = self.game
        if self.mode != "solo" or g is None or not g.p.alive:
            return False
        try:
            text = base64.b64encode(zlib.compress(json.dumps(g.to_save(), separators=(",", ":")).encode(), 6)).decode()
        except Exception:
            return False
        ok = store_write(text)
        g.msg("Partida guardada." if ok else "No se pudo guardar la partida.", (200, 255, 200) if ok else (255, 150, 130), g.p)
        return ok

    def load_game(self):
        text = store_read()
        if not text:
            self.net_msg = "No hay ninguna partida guardada."
            return
        try:
            data = json.loads(zlib.decompress(base64.b64decode(text)).decode())
            self.stop_net()
            self.begin(Game.from_save(data, self.name, self.cfg["hat"]), "solo")
        except Exception as ex:
            self.net_msg = f"No se pudo cargar la partida: {ex}"

    def start_host(self, port=None, seed_text=""):
        self.stop_net()
        try:
            port = int(port if port is not None else self.fields["port"])
        except ValueError:
            self.net_msg = "El puerto debe ser un número (1024-65535)."
            self.state = "online"
            return
        game = Game(seed=parse_seed(seed_text), name=self.name, hat=self.cfg["hat"], settings=self.gs)
        try:
            self.server = Server(game, port)
            self.server.label = f"Partida de {self.name}"
        except OSError as ex:
            self.net_msg = f"No se pudo abrir el puerto {port}: {ex}"
            self.state = "online"
            return
        self.begin(game, "host")

    def start_join(self, text):
        self.stop_net()
        ip, port = text.strip() or "127.0.0.1", PORT
        if ":" in ip:
            ip, ps = ip.rsplit(":", 1)
            try:
                port = int(ps)
            except ValueError:
                pass
        self.net_msg = f"Conectando a {ip}:{port} ..."
        self.draw_online()
        pygame.display.flip()
        try:
            cl = Client(ip, port, self.name, self.cfg["hat"])
            welcome = cl.wait_welcome()
        except (OSError, ConnectionError, ValueError) as ex:
            self.net_msg = f"No se pudo conectar: {ex}"
            self.state = "online"
            return
        self.client = cl
        self.begin(ClientGame(welcome), "client")

    def back_to_title(self, msg=""):
        self.stop_net()
        self.state = "title"
        self.net_msg = msg
        self.chat = None
        self.menu_open = False
        self.game = None
        self.has_save = save_exists()

    def act(self, a, arg=None):
        if self.mode == "client":
            if self.client:
                self.client.send({"t": "act", "a": a, "arg": arg})
        else:
            self.game.do_action(self.game.p, a, arg)

    # --- luces -----------------------------------------------------------------------------------
    def make_light_sprites(self):
        R = 300                                                  # cono de la linterna
        cone = pygame.Surface((2 * R, 2 * R), 0, 32)
        cone.fill((0, 0, 0))
        half = math.radians(26)
        layers = 16
        for i in range(layers):
            rad = R * (1 - i / layers)
            a = int(40 + 215 * (i / (layers - 1)))
            pts = [(R, R)] + [(R + math.cos(-half + 2 * half * k / 14) * rad,
                               R + math.sin(-half + 2 * half * k / 14) * rad) for k in range(15)]
            pygame.draw.polygon(cone, (a, a, a), pts)
        self.cone = pygame.transform.smoothscale(cone, (2 * R // LQ, 2 * R // LQ))
        AR = 62                                                  # luz ambiente pequeña: de noche casi no ves
        amb = pygame.Surface((2 * AR, 2 * AR), 0, 32)
        amb.fill((0, 0, 0))
        for i in range(10):
            v = int(255 * (i + 1) / 10)
            pygame.draw.circle(amb, (v, v, v), (AR, AR), int(AR * (1 - i / 10)))
        self.amb = pygame.transform.smoothscale(amb, (2 * AR // LQ, 2 * AR // LQ))

    def net_text(self, y):
        """Mensaje de red en varias líneas (los errores largos no caben en una)."""
        words, lines, cur = (self.net_msg or "").split(), [], ""
        for w in words:
            if len(cur) + len(w) + 1 > 70:
                lines.append(cur)
                cur = w
            else:
                cur = (cur + " " + w).strip()
        if cur:
            lines.append(cur)
        for i, ln in enumerate(lines[:4]):
            self.text(ln, 24, (W // 2, y + i * 26), (255, 170, 130), center=True)

    def text(self, txt, size, pos, color=(255, 255, 255), center=False, shadow=True):
        if not txt:
            return
        key = (txt, size, tuple(color), shadow)
        hit = self.txt_cache.get(key)
        if hit is None:
            font = self.fonts.get(size)
            if font is None:
                try:
                    font = pygame.font.Font(None, size)
                except Exception:
                    font = pygame.font.SysFont("sans", max(8, int(size * 0.75)))
                self.fonts[size] = font
            hit = (font.render(txt, True, color), font.render(txt, True, (0, 0, 0)) if shadow else None)
            if len(self.txt_cache) > 700:
                self.txt_cache.clear()
            self.txt_cache[key] = hit
        img, sh = hit
        rect = img.get_rect()
        if center:
            rect.center = pos
        else:
            rect.topleft = pos
        if sh is not None:
            self.screen.blit(sh, rect.move(1, 1))
        self.screen.blit(img, rect)

    # --- widgets de menú (modo inmediato) ----------------------------------------------------------
    def nav_reg(self):
        """Registra un elemento navegable con el teclado (flechas + Enter)."""
        i = self.nav_i
        self.nav_i += 1
        sel = (i == self.kb_idx)
        return sel, (sel and self.kb_activate)

    def ui_btn(self, x, y, w, h, label, key=None, size=34, enabled=True, color=(58, 64, 86), nav=True):
        r = pygame.Rect(x, y, w, h)
        sel = act = False
        if enabled and nav:
            sel, act = self.nav_reg()
        hover = enabled and (r.collidepoint(self.mouse_pos) or sel)
        col = color if enabled else (40, 42, 50)
        if hover:
            col = tuple(min(255, c + 28) for c in col)
        pygame.draw.rect(self.screen, col, r, border_radius=8)
        pygame.draw.rect(self.screen, (255, 210, 90) if sel else ((120, 130, 160) if hover else (20, 22, 30)),
                         r, 3 if sel else 2, border_radius=8)
        self.text(label, size, r.center, (255, 255, 255) if enabled else (130, 130, 135), center=True)
        hit = False
        if enabled:
            if self.click and r.collidepoint(self.click):
                hit = True
            elif act:
                hit = True
                self.kb_activate = False
            elif key is not None and self.press == key:
                hit = True
        if hit:
            self.click = self.press = None
        return hit

    def ui_field(self, key, x, y, w, label):
        r = pygame.Rect(x, y + 24, w, 36)
        self.text(label, 24, (x, y), (200, 205, 220))
        sel, act = self.nav_reg()
        if (self.click and r.collidepoint(self.click)) or act:
            self.focus = key
            self.click = None
            self.kb_activate = False
        pygame.draw.rect(self.screen, (28, 31, 42), r, border_radius=6)
        pygame.draw.rect(self.screen, (255, 210, 90) if (self.focus == key or sel) else (70, 76, 96), r, 2,
                         border_radius=6)
        cursor = "_" if self.focus == key and int(self.t * 2) % 2 == 0 else ""
        self.text(self.fields[key] + cursor, 30, (x + 10, y + 31), (255, 255, 255), shadow=False)

    def ui_panel(self, x, y, w, h):
        pygame.draw.rect(self.screen, (24, 26, 36), (x, y, w, h), border_radius=12)
        pygame.draw.rect(self.screen, (60, 66, 88), (x, y, w, h), 2, border_radius=12)

    def type_into_field(self, e):
        if e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_ESCAPE, pygame.K_TAB):
            self.focus = None
            return
        if e.key == pygame.K_BACKSPACE:
            self.fields[self.focus] = self.fields[self.focus][:-1]
            return
        allowed, maxlen = FIELD_RULES[self.focus]
        ch = e.unicode
        if ch and ch.isprintable() and (allowed is None or ch in allowed) and len(self.fields[self.focus]) < maxlen:
            self.fields[self.focus] += ch

    # --- pantallas de menú -------------------------------------------------------------------------------
    def draw_menu_bg(self):
        s = self.screen
        s.fill((14, 16, 22))
        for i in range(0, H, 4):                                  # degradado rojizo abajo
            c = int(40 * max(0.0, (i - H * 0.45) / (H * 0.55)))
            pygame.draw.rect(s, (14 + c, 16, 22), (0, i, W, 4))
        for wk in self.walkers:                                  # zombis caminando de fondo
            wk[0] = (wk[0] + wk[2] * 0.016) % (W + 80)
            x, y = int(wk[0]) - 40, H - 40 - int(wk[1] * 0.6)
            pygame.draw.circle(s, (22, 30, 22), (x, y), 14)
            for side in (-1, 1):
                pygame.draw.line(s, (22, 30, 22), (x, y), (x + 24, y + side * 8), 5)

    def draw_title(self):
        self.draw_menu_bg()
        self.text("ZOMBOID PY", 130, (W // 2, 120), (225, 60, 55), center=True)
        self.text("Sobrevive al pueblo infestado - solo o con amigos", 32, (W // 2, 200), (225, 225, 235), center=True)
        bx = W // 2 - 190
        y = 250
        if self.ui_btn(bx, y, 380, 58, "Jugar solo", pygame.K_1):
            self.state = "solo"
            self.focus = None
        y += 68
        if self.has_save:
            if self.ui_btn(bx, y, 380, 58, "Continuar partida guardada", pygame.K_c, color=(60, 110, 80)):
                self.load_game()
            y += 68
        if self.ui_btn(bx, y, 380, 58, "Modo online", pygame.K_2):
            self.state = "online"
            self.focus = None
        y += 68
        if self.ui_btn(bx, y, 380, 58, "Ajustes", pygame.K_3):
            self.back_to = "title"
            self.state = "settings"
            self.focus = None
        y += 68
        if self.ui_btn(bx, y, 380, 58, "Salir", pygame.K_4, color=(110, 50, 50)):
            self.quit()
        self.net_text(640)
        self.text("Cada partida crea un mundo nuevo - Atajos: 1 Solo, 2 Online, 3 Ajustes, 4 Salir", 24,
                  (W // 2, H - 30), (150, 155, 175), center=True)

    def settings_btn(self, x, y, w, h):
        """Botón que abre la pantalla de ajustes de partida (modo, zombis, botín, tiempo)."""
        if self.ui_btn(x, y, w, h, f"Modo {MODES[self.gs['mode']]['name']} - Ajustes de partida", None, size=26,
                       color=(90, 75, 40)):
            self.gset_back = self.state
            self.state = "gset"
            self.focus = None

    def draw_gset(self):
        self.draw_menu_bg()
        gs = self.gs
        cx = W // 2
        self.text("AJUSTES DE PARTIDA", 60, (cx, 50), (255, 220, 120), center=True)
        self.ui_panel(cx - 380, 100, 760, 520)
        self.text("MODO DE JUEGO", 26, (cx - 350, 116), (200, 205, 220))
        for i, (k, mo) in enumerate(MODES.items()):
            col = [(50, 120, 70), (190, 120, 40), (150, 40, 40)][i] if gs["mode"] == k else (58, 64, 86)
            if self.ui_btn(cx - 350 + i * 240, 146, 230, 52, mo["name"], None, size=32, color=col):
                self.gs = gs = norm_settings(dict(mode=k))
                self.cfg["game"] = gs
                save_cfg(self.cfg)
        self.text(MODES[gs["mode"]]["desc"], 22, (cx, 220), (230, 210, 160), center=True)
        rows = (("Tamaño del mapa (más grande = más edificios, tarda más en crearse)", "ms", MAP_OPTS),
                ("Cantidad de zombis", "zi", Z_OPTS), ("Botín en los muebles", "li", LOOT_OPTS),
                ("Paso del tiempo (1 día dura ~30 min en Normal)", "ti", TIME_OPTS))
        for r, (label, key, opts) in enumerate(rows):
            y = 244 + r * 76
            self.text(label, 26, (cx - 350, y), (225, 225, 235))
            n = len(opts)
            w = (700 - 8 * (n - 1)) // n
            for j, (nm, _) in enumerate(opts):
                col = (60, 110, 170) if gs[key] == j else (58, 64, 86)
                if self.ui_btn(cx - 350 + j * (w + 8), y + 32, w, 42, nm, None, size=22, color=col):
                    gs[key] = j
                    self.cfg["game"] = gs
                    save_cfg(self.cfg)
        self.text("Cambiar el modo restablece las opciones de abajo; luego puedes ajustarlas a tu gusto.", 20,
                  (cx, 566), (150, 155, 175), center=True)
        self.text("Al jugar online, estos ajustes los decide el anfitrión.", 20, (cx, 592), (150, 155, 175), center=True)
        if self.ui_btn(cx - 150, 626, 300, 54, "Listo", pygame.K_ESCAPE, size=34, color=(50, 120, 70)):
            self.state = self.gset_back
            self.focus = None

    def draw_solo(self):
        self.draw_menu_bg()
        self.ui_panel(W // 2 - 300, 130, 600, 380)
        self.text("JUGAR SOLO", 56, (W // 2, 180), (255, 220, 120), center=True)
        self.text("Se genera un mundo nuevo con lagos, bosques y casas.", 26, (W // 2, 232), (200, 205, 220), center=True)
        self.ui_field("sseed", W // 2 - 250, 270, 500, "Semilla del mundo (vacío = aleatoria)")
        self.settings_btn(W // 2 - 250, 338, 500, 44)
        if self.ui_btn(W // 2 - 250, 392, 500, 60, "Crear mundo y jugar", pygame.K_RETURN, color=(50, 120, 70)):
            self.start_solo(self.fields["sseed"])
        if self.ui_btn(W // 2 - 250, 460, 500, 44, "Volver", pygame.K_ESCAPE, size=28):
            self.state = "title"
            self.focus = None

    def start_host_web(self):
        self.stop_net()
        game = Game(seed=parse_seed(self.fields["seed"]), name=self.name, hat=self.cfg["hat"], settings=self.gs)
        try:
            self.server = WebServer(game)
        except Exception as ex:
            self.net_msg = f"No se pudo crear la sala: {ex}"
            self.state = "online"
            return
        self.server.label = f"Partida de {self.name}"
        self.begin(game, "host")

    def start_join_web(self, code):
        self.stop_net()
        code = "".join(ch for ch in code.upper() if ch.isalnum())
        if len(code) != 6:
            self.net_msg = "El código de sala tiene 6 caracteres."
            return
        try:
            self.client = WebClient(code, self.name, self.cfg["hat"])
        except Exception as ex:
            self.net_msg = f"No se pudo conectar: {ex}"
            return
        self.room_code = code
        self.net_msg = ""
        self.state = "connecting"

    def draw_connecting(self):
        self.draw_menu_bg()
        self.ui_panel(W // 2 - 300, 200, 600, 260)
        self.text("CONECTANDO...", 56, (W // 2, 250), (255, 220, 120), center=True)
        self.text(f"Sala {self.room_code}", 40, (W // 2, 310), (255, 255, 255), center=True)
        self.text("Buscando al anfitrión (puede tardar unos segundos)", 24, (W // 2, 355), (190, 195, 215), center=True)
        cl = self.client
        res = cl.advance() if cl else "cancelado"
        if res == "ok":
            self.begin(ClientGame(cl.welcome), "client")
            return
        if res != "wait":
            self.stop_net()
            self.net_msg = f"No se pudo conectar: {res}"
            self.state = "online"
            return
        if self.ui_btn(W // 2 - 120, 390, 240, 50, "Cancelar", pygame.K_ESCAPE, size=30):
            self.stop_net()
            self.state = "online"

    def draw_online_web(self):
        self.draw_menu_bg()
        self.text("MODO ONLINE", 64, (W // 2, 60), (255, 220, 120), center=True)
        self.ui_field("name", W // 2 - 200, 100, 400, "Tu nombre")
        self.ui_panel(40, 190, 500, 300)
        self.text("CREAR SALA (anfitrión)", 34, (60, 205), (170, 255, 190))
        self.ui_field("seed", 60, 250, 460, "Semilla (opcional)")
        self.text("Recibirás un código de 6 caracteres para tus amigos.", 22, (60, 345), (170, 175, 195))
        self.text("Deja esta pestaña abierta y visible mientras juegan.", 22, (60, 370), (255, 200, 120))
        self.settings_btn(60, 398, 460, 36)
        if self.ui_btn(60, 440, 460, 44, "Crear sala y jugar", None, size=30, color=(50, 120, 70)):
            self.start_host_web()
        self.ui_panel(560, 190, 500, 300)
        self.text("UNIRSE A UNA SALA", 34, (580, 205), (170, 200, 255))
        self.ui_field("room", 580, 250, 460, "Código de sala (6 caracteres)")
        self.text("Pídele el código al anfitrión.", 22, (580, 345), (170, 175, 195))
        if self.ui_btn(580, 410, 460, 64, "Unirse", None, color=(55, 90, 150)):
            self.start_join_web(self.fields["room"])
        if self.ui_btn(W // 2 - 150, 530, 300, 54, "Volver", pygame.K_ESCAPE, size=32):
            self.state = "title"
            self.focus = None
        self.net_text(620)

    def draw_online(self):
        if IS_WEB:
            return self.draw_online_web()
        self.draw_menu_bg()
        self.text("MODO ONLINE", 64, (W // 2, 60), (255, 220, 120), center=True)
        self.ui_field("name", W // 2 - 200, 100, 400, "Tu nombre")
        self.ui_panel(40, 190, 500, 330)
        self.text("CREAR PARTIDA (anfitrión)", 34, (60, 205), (170, 255, 190))
        self.ui_field("port", 60, 250, 200, "Puerto")
        self.ui_field("seed", 280, 250, 240, "Semilla (opcional)")
        self.text(f"Tu IP local: {self.my_ip}", 26, (60, 345), (170, 230, 255))
        self.text("En la misma red (LAN) tus amigos te verán solos en su lista.", 22, (60, 370), (170, 175, 195))
        self.settings_btn(60, 398, 460, 42)
        if self.ui_btn(60, 450, 460, 58, "Crear partida y jugar", None, color=(50, 120, 70)):
            self.start_host(self.fields["port"], self.fields["seed"])
        self.ui_panel(560, 190, 500, 330)
        self.text("UNIRSE A UNA PARTIDA", 34, (580, 205), (170, 200, 255))
        self.ui_field("ip", 580, 236, 460, "IP del anfitrión (ej. 192.168.1.20 o 192.168.1.20:5555)")
        if self.scanner is None:
            self.scanner = LanScanner()
        found = self.scanner.poll()
        self.text("PARTIDAS ENCONTRADAS EN TU RED (LAN)", 22, (580, 308), (170, 230, 255))
        if not found:
            self.text("Buscando... (el anfitrión debe estar en la misma red)", 22, (580, 340), (150, 155, 175))
        for i, ((ip, port), info) in enumerate(found[:3]):
            if self.ui_btn(580, 336 + i * 40, 460, 36, f"{info['name']}  -  {ip}:{port}  ({info['n']} jug.)",
                           None, size=24, color=(50, 100, 120)):
                self.start_join(f"{ip}:{port}")
                return
        if self.ui_btn(580, 464, 460, 46, "Unirse a la IP escrita", None, size=30, color=(55, 90, 150)):
            self.start_join(self.fields["ip"])
        if self.ui_btn(W // 2 - 150, 560, 300, 54, "Volver", pygame.K_ESCAPE, size=32):
            self.state = "title"
            self.focus = None
        self.text("Por internet: abre el puerto TCP en el router del anfitrión o usad una VPN (Radmin, ZeroTier...).",
                  20, (W // 2, 532), (150, 155, 175), center=True)
        self.net_text(640)

    def draw_settings(self):
        self.draw_menu_bg()
        self.text("AJUSTES", 60, (W // 2, 44), (255, 220, 120), center=True)
        self.ui_panel(20, 84, 700, 520)
        self.text("CONTROLES  (clic en una tecla y pulsa la nueva; Esc cancela)", 24, (36, 94), (200, 205, 220))
        for i, (action, label) in enumerate(BIND_LABELS):
            col, row = divmod(i, 10)
            x, y = 36 + col * 345, 126 + row * 46
            self.text(label, 25, (x, y + 8), (225, 225, 235))
            waiting = self.rebind == action
            code = self.bind[action]
            try:
                kn = str(pygame.key.name(code)).upper()
            except Exception:
                kn = str(code)
            if self.ui_btn(x + 175, y, 150, 38, "Pulsa tecla..." if waiting else kn, None, size=24,
                           color=(150, 110, 40) if waiting else (58, 64, 86)):
                self.rebind = action
                self.focus = None
        self.ui_panel(740, 84, 340, 520)
        self.text("GENERAL", 26, (760, 94), (200, 205, 220))
        self.ui_field("name", 760, 126, 300, "Nombre (online)")
        self.text(f"Oscuridad nocturna: {int(self.cfg['dark'] * 100)}%", 26, (760, 215), (225, 225, 235))
        if self.ui_btn(760, 250, 60, 40, "-", None, size=34):
            self.cfg["dark"] = max(0.5, round(self.cfg["dark"] - 0.1, 1))
        if self.ui_btn(830, 250, 60, 40, "+", None, size=34):
            self.cfg["dark"] = min(1.0, round(self.cfg["dark"] + 0.1, 1))
        if self.ui_btn(760, 315, 300, 42, "Mostrar FPS: " + ("SÍ" if self.cfg["fps"] else "NO"), None, size=26):
            self.cfg["fps"] = not self.cfg["fps"]
        if self.ui_btn(760, 368, 300, 42, "Pantalla completa: " + ("SÍ" if self.cfg["fullscreen"] else "NO"),
                       None, size=26):
            self.cfg["fullscreen"] = not self.cfg["fullscreen"]
            self.apply_display()
        if self.ui_btn(760, 421, 300, 42, "Minimapa: " + ("SÍ" if self.show_map else "NO"), None, size=26):
            self.show_map = not self.show_map
        hi = HATS.index(self.cfg["hat"]) if self.cfg["hat"] in HATS else 0
        if self.ui_btn(760, 474, 300, 42, "Sombrero: " + HAT_NAMES[HATS[hi]], None, size=26):
            self.cfg["hat"] = HATS[(hi + 1) % len(HATS)]
        self.text("Flechas + Enter: moverte por los menús.", 20, (760, 540), (150, 155, 175))
        pygame.draw.circle(self.screen, (15, 20, 40), (1000, 255), PLAYER_R + 2)
        pygame.draw.circle(self.screen, (70, 120, 200), (1000, 255), PLAYER_R)
        self.draw_hat(1000, 255, -0.6, self.cfg["hat"])
        if self.ui_btn(30, 625, 300, 54, "Restaurar controles", None, size=28, color=(110, 70, 50)):
            self.bind.update(default_binds())
        if self.ui_btn(W - 380, 625, 350, 54, "Guardar y volver", pygame.K_ESCAPE, size=30, color=(50, 120, 70)):
            if self.rebind is None:
                self.save_settings()
                self.focus = None
                if self.back_to == "pause":
                    self.act("hat", self.cfg["hat"])
                    self.state, self.menu_open, self.menu_page = "play", True, "pause"
                else:
                    self.state = "title"

    def draw_pause_menu(self):
        s = self.screen
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 170))
        s.blit(veil, (0, 0))
        self.ui_panel(W // 2 - 240, 150, 480, 400)
        self.text("PAUSA" if self.mode == "solo" else "MENÚ (el mundo sigue)", 50, (W // 2, 195),
                  (255, 220, 120), center=True)
        if self.game.seed is not None:
            self.text(f"Semilla del mundo: {self.game.seed}", 24, (W // 2, 238), (170, 175, 195), center=True)
        if self.ui_btn(W // 2 - 190, 258, 380, 56, "Continuar", pygame.K_ESCAPE):
            self.menu_open = False
        by = 322
        if self.mode == "solo":
            if self.ui_btn(W // 2 - 190, by, 380, 56, "Guardar partida" if self.game.p.alive else "Guardar (no disponible)",
                           None, color=(60, 110, 80)):
                self.save_game()
                self.has_save = save_exists()
            by += 64
        if self.ui_btn(W // 2 - 190, by, 380, 56, "Ajustes", None):
            self.back_to = "pause"
            self.state = "settings"
            self.menu_open = False
        by += 64
        if self.ui_btn(W // 2 - 190, by, 380, 56, "Salir al menú principal", None, color=(110, 50, 50), size=30):
            self.back_to_title("Saliste de la partida." + (" (Lo no guardado se pierde)" if self.mode == "solo" else ""))
        if self.game is not None and self.mode == "solo" and self.game.p.msgs:
            self.text(self.game.p.msgs[-1][0], 24, (W // 2, 530), (200, 255, 200), center=True)

    # --- entrada del juego ---------------------------------------------------------------------------------
    def on_key(self, key):
        g, b = self.game, self.bind
        p = g.p
        if key == pygame.K_ESCAPE:
            self.build_mode = False
            self.menu_open = True
            self.menu_page = "pause"
            self.attack_held = False
            return
        if key == b["map"]:
            self.show_map = not self.show_map
            return
        if key == b["inventory"] and p.alive:
            self.inv_open, self.inv_by_cont, self.inv_panel = True, False, 0
            return
        if key == b["pause"] and self.mode == "solo":
            self.menu_open = True
            self.menu_page = "pause"
            return
        if key == b["chat"] and self.mode != "solo":
            self.chat = ""
            return
        if not p.alive:
            if key in (pygame.K_r, pygame.K_RETURN, b["reload"]):
                if self.mode == "solo":
                    self.start_solo("")
                elif self.game.revive:
                    self.act("respawn")
            return
        if key == b["sneak"] or key == pygame.K_LCTRL:
            self.sneak = not self.sneak
        elif key == b["interact"]:
            self.act("interact")
        elif key == b["flash"]:
            self.act("flash")
        elif key == b["reload"]:
            self.act("reload")
        elif key == b["cycle"]:
            self.act("cycle")
        elif key == b["shove"]:
            self.act("shove")
        elif key == b["bandage"]:
            self.act("bandage")
        elif key == b["consume"]:
            self.act("consume")
        elif key == b["build"]:
            self.build_mode = not self.build_mode
        elif key == b["throw"]:
            self.act("throw", [round(self.mouse_world[0], 1), round(self.mouse_world[1], 1)])
        elif pygame.K_1 <= key <= pygame.K_9:
            i = key - pygame.K_1
            if self.build_mode:
                if i < len(BUILD_PIECES):
                    self.build_piece = i
            else:
                owned = g.owned()
                if i < len(owned):
                    self.act("use", owned[i])

    def on_mouse_down(self, pos):
        g = self.game
        if not g.p.alive:
            return
        for rect, item in self.inv_rows:
            if rect.collidepoint(pos):
                self.act("use", item)
                return
        if self.build_mode:
            tx, ty = int(self.mouse_world[0] // TS), int(self.mouse_world[1] // TS)
            self.act("build", [tx, ty, self.build_piece])
            return
        self.attack_held = True
        self.act("click")

    def on_chat_key(self, e):
        if e.key == pygame.K_ESCAPE:
            self.chat = None
        elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
            text = self.chat.strip()
            self.chat = None
            if text:
                if self.mode == "client" and self.client:
                    self.client.send({"t": "chat", "x": text})
                elif self.mode == "host":
                    self.game.msg(f"{self.name}: {text}", (255, 255, 170))
        elif e.key == pygame.K_BACKSPACE:
            self.chat = self.chat[:-1]
        elif e.unicode and e.unicode.isprintable() and len(self.chat) < 70:
            self.chat += e.unicode

    def camera(self):
        p = self.game.p
        cx = max(0, min(N * TS - W, p.x - W / 2))
        cy = max(0, min(N * TS - H, p.y - H / 2))
        if self.game.shake > 0:
            k = min(1.0, self.game.shake * 4)
            cx += random.uniform(-4, 4) * k
            cy += random.uniform(-4, 4) * k
        return cx, cy

    def build_input(self, cam):
        k = pygame.key.get_pressed()
        b = self.bind
        mx, my = pygame.mouse.get_pos()
        btn = pygame.mouse.get_pressed()
        self.mouse_world = (mx + cam[0], my + cam[1])
        if not btn[0]:
            self.attack_held = False
        locked = self.chat is not None or self.menu_open or self.inv_open
        inp = dict(
            move=(0, 0) if locked else
            ((k[b["right"]] or k[pygame.K_RIGHT]) - (k[b["left"]] or k[pygame.K_LEFT]),
             (k[b["down"]] or k[pygame.K_DOWN]) - (k[b["up"]] or k[pygame.K_UP])),
            run=bool(k[b["run"]] or k[pygame.K_RSHIFT]) and not locked,
            aim=btn[2] and not locked,
            attack_held=self.attack_held and not locked,
            demolish=bool(k[b["demolish"]]) and not locked,
            sneak=self.sneak,
            mouse=self.mouse_world,
        )
        return inp

    # --- inventario y contenedores --------------------------------------------------------------------------
    def cont_view(self):
        p = self.game.p
        if not p.open:
            return None
        if self.mode == "client":
            cv = p.cview
            return (cv[2], cv[3]) if cv else None
        c = self.game.map.containers.get(p.open)
        return (c["kind"], c["inv"]) if c else None

    def cont_rows(self):
        cv = self.cont_view()
        if not cv:
            return []
        return [(i, cv[1][i]) for i in ITEM_ORDER if cv[1].get(i, 0) > 0]

    def inv_close(self):
        self.inv_open = False
        p = self.game.p
        if p.open:
            self.act("closec")
            if self.mode == "client":
                p.open = p.cview = None
            self.cont_prev = None
            self.cont_ignore = self.t + 0.7

    def on_inv_key(self, e):
        k, b = e.key, self.bind
        g = self.game
        p = g.p
        if k == pygame.K_ESCAPE or k == b["inventory"]:
            self.inv_close()
            return
        left = [(i, p.inv[i]) for i in g.owned()]
        right = self.cont_rows()
        has = self.cont_view() is not None
        if not has:
            self.inv_panel = 0
        pan = self.inv_panel
        rows = left if pan == 0 else right
        sel = self.inv_sel[pan]
        if k in (pygame.K_UP, b["up"]):
            self.inv_sel[pan] = max(0, sel - 1)
        elif k in (pygame.K_DOWN, b["down"]):
            self.inv_sel[pan] = min(max(0, len(rows) - 1), sel + 1)
        elif has and k in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_TAB, b["left"], b["right"]):
            self.inv_panel = 1 - pan
        elif sel < len(rows):
            item = rows[sel][0]
            if pan == 0:
                if k in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_u):
                    self.act("use", item)
                elif k in (pygame.K_SPACE, pygame.K_BACKSPACE, pygame.K_DELETE):
                    self.act("drop", [item, 1])
                elif k == pygame.K_x:
                    self.act("drop", [item, 0])
                elif k == pygame.K_g and has:
                    self.act("put", [item, 0])
            else:
                if k in (pygame.K_RETURN, pygame.K_KP_ENTER):
                    self.act("take", [item, 0])
                elif k == pygame.K_SPACE:
                    self.act("take", [item, 1])

    def draw_inventory(self):
        s, g = self.screen, self.game
        p = g.p
        veil = pygame.Surface((W, H), pygame.SRCALPHA)
        veil.fill((0, 0, 0, 160))
        s.blit(veil, (0, 0))
        cv = self.cont_view()
        left = [(i, p.inv[i]) for i in g.owned()]
        right = self.cont_rows()
        if cv is None:
            self.inv_panel = 0
        self.text("INVENTARIO", 44, (W // 2, 30), (255, 220, 120), center=True)
        for pan, (x, title, rows) in enumerate((
                (30, f"TUS OBJETOS ({len(left)})   Peso {inv_weight(p.inv):.1f}/{cap_of(p.inv):.0f} kg", left),
                (570, f"{CONT_NAMES.get(cv[0], 'MUEBLE').upper()} ({len(right)})" if cv else "MUEBLE", right))):
            self.ui_panel(x, 56, 500, 510)
            self.text(title, 26, (x + 14, 66), (255, 255, 255) if self.inv_panel == pan else (170, 175, 195))
            if pan == 1 and cv is None:
                self.text("Ningún mueble abierto.", 24, (x + 14, 110), (170, 175, 195))
                self.text("Acércate a uno y pulsa Interactuar.", 22, (x + 14, 140), (150, 155, 175))
                continue
            sel = max(0, min(self.inv_sel[pan], len(rows) - 1))
            self.inv_sel[pan] = sel
            start = max(0, min(sel - 4, len(rows) - 10))
            if not rows:
                self.text("(vacío)", 26, (x + 14, 110), (150, 155, 175))
            for n, (item, qty) in enumerate(rows[start:start + 10]):
                idx = start + n
                ry = 100 + n * 46
                rect = pygame.Rect(x + 8, ry, 484, 42)
                chosen = idx == sel and self.inv_panel == pan
                pygame.draw.rect(s, (70, 90, 60) if chosen else (34, 37, 50), rect, border_radius=6)
                if idx == sel:
                    pygame.draw.rect(s, (255, 210, 90) if chosen else (90, 96, 120), rect, 2, border_radius=6)
                col = ITEM_COLORS.get(ITEMS[item]["kind"], (180, 180, 120))
                pygame.draw.rect(s, col, (rect.x + 8, rect.y + 12, 18, 18), border_radius=3)
                label = ITEMS[item]["name"] + (f" x{qty}" if qty > 1 else "")
                if pan == 0 and item == p.weapon:
                    label += " (equipado)"
                self.text(label, 22, (rect.x + 34, rect.y + 11), (255, 255, 255))
                clicked = False
                if pan == 0:
                    bx = rect.right - 6
                    btns = [("Usar", 54), ("Tirar", 58), ("Tirar todo", 84)] + ([("Guardar", 70)] if cv else [])
                    acts = [("use", item), ("drop", [item, 1]), ("drop", [item, 0])] + \
                           ([("put", [item, 0])] if cv else [])
                    for (lab, w), (a, arg) in reversed(list(zip(btns, acts))):
                        bx -= w + 4
                        if self.ui_btn(bx, rect.y + 5, w, 32, lab, None, size=20, nav=False):
                            self.inv_panel, self.inv_sel[0] = 0, idx
                            self.act(a, arg)
                            clicked = True
                else:
                    bx = rect.right - 6
                    for (lab, w), (a, arg) in reversed(list(zip((("Tomar 1", 74), ("Tomar todo", 90)),
                                                              (("take", [item, 1]), ("take", [item, 0]))))):
                        bx -= w + 4
                        if self.ui_btn(bx, rect.y + 5, w, 32, lab, None, size=20, nav=False,
                                       color=(60, 100, 70)):
                            self.inv_panel, self.inv_sel[1] = 1, idx
                            self.act(a, arg)
                            clicked = True
                if not clicked and self.click and rect.collidepoint(self.click):
                    self.inv_panel, self.inv_sel[pan] = pan, idx
                    self.click = None
            if len(rows) > 10:
                self.text(f"{sel + 1}/{len(rows)}", 20, (x + 440, 70), (170, 175, 195))
        pan = self.inv_panel
        rows = left if pan == 0 else right
        if rows:
            item = rows[max(0, min(self.inv_sel[pan], len(rows) - 1))][0]
            self.text(ITEMS[item]["name"] + ": " + ITEM_DESC.get(item, ""), 24, (W // 2, 584), (255, 240, 190),
                      center=True)
        if pan == 0:
            hint = "Flechas: elegir | Enter: usar | Espacio: tirar 1 | X: tirar todo" + (
                " | G: guardar | Tab: cambiar a mueble" if cv else "")
        else:
            hint = "Flechas: elegir | Enter: tomar todo | Espacio: tomar 1 | Tab: volver a tus objetos"
        self.text(hint + " | I/Esc: cerrar", 20, (W // 2, 616), (170, 175, 195), center=True)
        if self.ui_btn(W // 2 - 110, 640, 220, 44, "Cerrar", None, size=28, nav=False):
            self.inv_close()

    # --- sombreros, objetos del suelo, pesca ----------------------------------------------------------------------
    def draw_hat(self, x, y, ang, hat):
        if hat not in HATS or hat == "none":
            return
        s = self.screen
        r = PLAYER_R
        c, sn = math.cos(ang), math.sin(ang)
        x, y = int(x), int(y)
        if hat == "lumberjack":                               # gorro de cuadros rojo y negro
            pygame.draw.circle(s, (170, 30, 30), (x, y), r - 1)
            for k in (-6, -2, 2, 6):
                pygame.draw.line(s, (30, 30, 30), (x - r + 3, y + k), (x + r - 3, y + k), 1)
                pygame.draw.line(s, (30, 30, 30), (x + k, y - r + 3), (x + k, y + r - 3), 1)
            pygame.draw.circle(s, (90, 15, 15), (x, y), r - 1, 2)
        elif hat == "police":                                 # gorra azul oscuro con visera y placa
            pygame.draw.line(s, (12, 12, 20), (int(x + c * (r - 4)), int(y + sn * (r - 4))),
                             (int(x + c * (r + 5)), int(y + sn * (r + 5))), 8)
            pygame.draw.circle(s, (28, 40, 90), (x, y), r - 1)
            pygame.draw.circle(s, (15, 22, 55), (x, y), r - 1, 2)
            pygame.draw.circle(s, (225, 200, 80), (int(x + c * 3), int(y + sn * 3)), 3)
        elif hat == "firefighter":                            # casco rojo con franja amarilla
            pygame.draw.line(s, (150, 25, 20), (int(x - c * (r - 3)), int(y - sn * (r - 3))),
                             (int(x - c * (r + 6)), int(y - sn * (r + 6))), 9)
            pygame.draw.circle(s, (210, 42, 32), (x, y), r)
            pygame.draw.line(s, (250, 220, 60), (int(x - c * (r - 2)), int(y - sn * (r - 2))),
                             (int(x + c * (r - 2)), int(y + sn * (r - 2))), 4)
            pygame.draw.circle(s, (250, 220, 60), (int(x + c * 4), int(y + sn * 4)), 3)
            pygame.draw.circle(s, (120, 20, 15), (x, y), r, 2)
        elif hat == "farmer":                                 # sombrero de paja de ala ancha
            pygame.draw.circle(s, (228, 198, 112), (x, y), r + 6)
            pygame.draw.circle(s, (170, 128, 60), (x, y), r + 6, 2)
            pygame.draw.circle(s, (238, 212, 136), (x, y), r - 3)
            pygame.draw.circle(s, (140, 72, 40), (x, y), r - 3, 3)

    def draw_ground_items(self, ox, oy):
        s, g = self.screen, self.game
        p = g.p
        for it in g.items.values():
            x, y = it[0] - ox, it[1] - oy
            if not (-20 < x < W + 20 and -20 < y < H + 20):
                continue
            col = ITEM_COLORS.get(ITEMS[it[2]]["kind"], (180, 180, 120))
            pygame.draw.rect(s, (20, 20, 25), (x - 7, y - 7, 14, 14), border_radius=3)
            pygame.draw.rect(s, col, (x - 5, y - 5, 10, 10), border_radius=2)
            if math.hypot(it[0] - p.x, it[1] - p.y) < 40:
                self.text(ITEMS[it[2]]["name"] + (f" x{it[3]}" if it[3] > 1 else ""), 18, (x, y - 16),
                          (255, 255, 255), center=True)

    def draw_fishing(self, p, ox, oy):
        if not p.fish or not p.alive:
            return
        s = self.screen
        tx, ty = p.fish[0], p.fish[1]
        bx, by = (tx + 0.5) * TS - ox, (ty + 0.5) * TS - oy + math.sin(self.t * 3) * 2
        pygame.draw.line(s, (235, 235, 235), (p.x - ox, p.y - oy), (bx, by), 1)
        pygame.draw.circle(s, (250, 250, 250), (int(bx), int(by)), 5)
        pygame.draw.circle(s, (220, 40, 40), (int(bx), int(by) - 2), 3)
        pygame.draw.circle(s, (200, 230, 255), (int(bx), int(by)), 10 + int(self.t * 6) % 6, 1)
        self.text("Pescando... no te muevas", 22, (p.x - ox, p.y - oy - 30), (190, 230, 255), center=True)



    # --- actualización por modo -----------------------------------------------------------------------------
    def step(self, dt, inp):
        if self.mode == "client":
            cl = self.client
            for m in cl.poll():
                if m.get("t") == "snap":
                    self.game.apply_snap(m)
            if cl.conn.dead:
                self.back_to_title("Conexión perdida con el servidor.")
                return
            self.game.update(dt, inp)
            self.send_t -= dt
            if self.send_t <= 0:
                self.send_t = 1.0 / INPUT_HZ
                p = self.game.p
                cl.send({"t": "in", "x": round(p.x, 1), "y": round(p.y, 1), "a": round(p.angle, 3),
                         "mv": int(p.moving), "run": int(bool(inp["run"])), "aim": int(bool(inp["aim"])),
                         "hold": int(bool(inp["attack_held"])), "sn": int(self.sneak),
                         "mx": round(inp["mouse"][0], 1), "my": round(inp["mouse"][1], 1),
                         "dm": int(bool(inp["demolish"])),
                         "dv": [-inp["move"][1], inp["move"][0]] if p.car is not None else [0, 0]})
        else:
            if self.server:
                self.server.poll(dt)
            self.game.update(dt, inp)
            if self.server:
                self.server.broadcast(dt)

    # --- dibujo del mundo -----------------------------------------------------------------------------------
    def draw_world(self, cam):
        s, g = self.screen, self.game
        p, m = g.p, g.map
        ox, oy = cam
        cs = CH * TS
        for cy in range(int(oy // cs), int((oy + H) // cs) + 1):
            for cx in range(int(ox // cs), int((ox + W) // cs) + 1):
                if 0 <= cx <= (N - 1) // CH and 0 <= cy <= (N - 1) // CH:
                    s.blit(m.get_chunk(cx, cy), (cx * cs - ox, cy * cs - oy))

        for x, y, ang, col in g.corpses:                      # cuerpos y sangre
            if -20 < x - ox < W + 20 and -20 < y - oy < H + 20:
                pygame.draw.ellipse(s, (95, 18, 18), (x - ox - 14, y - oy - 9, 28, 18))
                body = PA.person(tuple(int(c * 0.7) for c in col), (44, 48, 66), (110, 138, 104), (36, 30, 26), "down", 0, True)
                s.blit(pygame.transform.rotate(body, 90 + (int(ang * 57) % 40 - 20)), (x - ox - 16, y - oy - 16))

        for cy in range(int(oy // cs) - 1, int((oy + H) // cs) + 2):     # precarga: 1 trozo por fotograma
            done = False
            for cx in range(int(ox // cs) - 1, int((ox + W) // cs) + 2):
                if 0 <= cx <= (N - 1) // CH and 0 <= cy <= (N - 1) // CH and (cx, cy) not in m.chunks:
                    m.get_chunk(cx, cy)
                    done = True
                    break
            if done:
                break
        self.draw_ground_items(ox, oy)
        for c in g.cars:
            if -60 < c.x - ox < W + 60 and -60 < c.y - oy < H + 60:
                self.draw_car(c, ox, oy)
        drivers = {c.driver for c in g.cars if c.driver is not None}
        actors = []
        for z in g.zombies:
            if -30 < z.x - ox < W + 30 and -30 < z.y - oy < H + 30:
                actors.append((z.y, 0, z))
        for o in g.other_players():
            if o.pid not in drivers:
                actors.append((o.y, 1, o))
        if p.alive and p.car is None:
            actors.append((p.y, 2, p))
        actors.sort(key=lambda a: a[0])
        for _, kind, a in actors:                             # los de más abajo se dibujan encima
            if kind == 0:
                self.draw_zombie(a, ox, oy)
            else:
                self.draw_player(a, ox, oy, local=(kind == 2))

        for x1, y1, x2, y2, col, width, _ in g.tracers:
            pygame.draw.line(s, col, (x1 - ox, y1 - oy), (x2 - ox, y2 - oy), width)
        for pr in g.projs:                                    # rocas y botellas en el aire
            x, y, kind = pr[0] - ox, pr[1] - oy, pr[5]
            if kind == 0:
                pygame.draw.circle(s, (120, 120, 125), (int(x), int(y)), 4)
            elif kind == 1:
                pygame.draw.circle(s, (70, 150, 90), (int(x), int(y)), 4)
                pygame.draw.circle(s, (170, 230, 190), (int(x) - 1, int(y) - 1), 1)
            else:
                pygame.draw.circle(s, (180, 220, 240), (int(x), int(y)), 4)
                pygame.draw.circle(s, (255, 255, 255), (int(x) - 1, int(y) - 1), 1)
        if p.aiming and p.alive:                              # láser de puntería
            d = m.ray_distance(p.x, p.y, p.angle, 520)
            pygame.draw.line(s, (255, 60, 60), (p.x - ox, p.y - oy),
                             (p.x + math.cos(p.angle) * d - ox, p.y + math.sin(p.angle) * d - oy), 1)

        inside = m.building_at(int(p.x // TS), int(p.y // TS))     # tejados (se ocultan al entrar)
        for b in m.buildings:
            if b is inside:
                continue
            rx, ry = (b["x0"] + 1) * TS - ox, (b["y0"] + 1) * TS - oy
            rw, rh = (b["x1"] - b["x0"] - 1) * TS, (b["y1"] - b["y0"] - 1) * TS
            if rx > W or ry > H or rx + rw < 0 or ry + rh < 0:
                continue
            s.blit(PA.roof(int(rw), int(rh), tuple(b["roof"])), (int(rx), int(ry)))
            if b["q"] >= 2:                                   # marca de edificio grande (mejor botín)
                pygame.draw.circle(s, (255, 215, 90) if b["q"] == 3 else (210, 210, 220),
                                   (int(rx + rw / 2), int(ry + rh / 2)), 7 if b["q"] == 3 else 5)
            if b.get("kind") in SPECIAL:                      # rótulo del edificio especial
                self.text(SPECIAL[b["kind"]]["name"], 26, (rx + rw / 2, ry + rh / 2 - 26),
                          (30, 30, 36) if b["kind"] == "hospital" else (255, 255, 255), center=True)

        for f in g.fx:                                        # efectos: cristales, gritos, escombros
            x, y, kind, ttl = f[0] - ox, f[1] - oy, f[2], f[3]
            k = 1 - ttl / 0.6
            if kind == "glass":
                pygame.draw.circle(s, (190, 230, 255), (int(x), int(y)), int(8 + 50 * k), 2)
            elif kind == "scream":
                pygame.draw.circle(s, (230, 70, 60), (int(x), int(y)), int(10 + 90 * k), 2)
            elif kind == "crash":
                for a in range(0, 360, 60):
                    pygame.draw.circle(s, (140, 105, 70), (int(x + math.cos(math.radians(a)) * 18 * k),
                                                           int(y + math.sin(math.radians(a)) * 18 * k)), 4)
            elif kind == "build":
                pygame.draw.circle(s, (200, 190, 150), (int(x), int(y)), int(6 + 12 * k), 2)

        for o in g.other_players():                           # nombres
            self.text(o.name, 20, (o.x - ox, o.y - oy - 22), (170, 255, 190), center=True)
        self.draw_work(p, ox, oy)

    def draw_work(self, p, ox, oy):
        s = self.screen
        if self.build_mode and p.alive:                       # fantasma de construcción
            tx, ty = int(self.mouse_world[0] // TS), int(self.mouse_world[1] // TS)
            pc = BUILD_PIECES[self.build_piece]
            ok = self.game.can_build(p, tx, ty, pc) and p.inv.get("planks", 0) >= pc["cost"]
            col = (90, 255, 120) if ok else (255, 90, 90)
            pygame.draw.rect(s, col, (tx * TS - ox, ty * TS - oy, TS, TS), 3)
            self.text(f"{pc['name']} ({pc['cost']} tablones)", 20, ((tx + 0.5) * TS - ox, ty * TS - oy - 10),
                      col, center=True)
        self.draw_fishing(p, ox, oy)
        w = p.work
        if w and p.alive:                                     # barra de progreso de construir/destruir
            tx, ty, prog = w[1], w[2], w[3]
            bx, by = tx * TS - ox, ty * TS - oy - 8
            pygame.draw.rect(s, (25, 25, 30), (bx - 1, by - 1, TS + 2, 8))
            pygame.draw.rect(s, (230, 150, 60) if w[0] == "demo" else (120, 200, 255),
                             (bx, by, int(TS * max(0.0, min(1.0, prog))), 6))
            pygame.draw.rect(s, (255, 255, 255), (tx * TS - ox, ty * TS - oy, TS, TS), 1)

    def draw_car(self, c, ox, oy):
        s = self.screen
        x, y = c.x - ox, c.y - oy
        deg = int(round(-math.degrees(c.angle) / 7.5)) * 7.5            # 48 ángulos: se mantiene el aspecto de píxeles
        key = ("carrot", c.color, c.hp <= 30, deg)
        spr = PA._c.get(key)
        if spr is None:
            if len(PA._c) > 900:
                PA._c.clear()
            spr = PA._c[key] = pygame.transform.rotate(PA.car(c.color, c.hp <= 30), deg)
        sw = pygame.Surface((46, 22), pygame.SRCALPHA)
        pygame.draw.ellipse(sw, (0, 0, 0, 70), (0, 0, 46, 22))
        s.blit(sw, (int(x - 21), int(y - 3)))
        s.blit(spr, (int(x - spr.get_width() / 2), int(y - spr.get_height() / 2)))
        if c.hp < 40:                                         # humo del motor
            ca, sa = math.cos(c.angle), math.sin(c.angle)
            for k in range(3):
                pygame.draw.circle(s, (70 + 20 * k, 70 + 20 * k, 70 + 20 * k),
                                   (int(x + ca * (20 + 5 * k) + math.sin(self.t * 6 + k) * 3),
                                    int(y + sa * (20 + 5 * k) - 4 * k)), 3 + k)

    @staticmethod
    def sprite_dir(ang):
        """Vista del sprite según hacia dónde mira: (dirección, espejo)."""
        c, sn = math.cos(ang), math.sin(ang)
        if abs(c) > abs(sn) * 1.15:
            return "side", c < 0
        return ("down" if sn > 0 else "up"), False

    def draw_sprite(self, spr, x, y, flip=False):
        s = self.screen
        s.blit(PA.shadow(), (x - 11, y + 4))
        if flip:
            spr = pygame.transform.flip(spr, True, False)
        s.blit(spr, (x - 16, y - 21))

    def draw_zombie(self, z, ox, oy):
        x, y, r = int(z.x - ox), int(z.y - oy), z.r
        kind = z.kind
        shirt = z.cloth
        if kind == "runner":
            shirt = tuple(min(255, c + 50) for c in z.cloth)
        elif kind == "brute":
            shirt = (95, 55, 55)
        elif kind == "breaker":
            shirt = (70, 70, 88)
        d, flip = self.sprite_dir(z.angle)
        frame = int(self.t * (9 if kind == "runner" else 5) + z.id) & 1
        spr = PA.person(tuple(shirt), (44, 48, 66), tuple(z.skin), (36, 30, 26), d, frame, True, 4, "none", kind)
        self.draw_sprite(spr, x, y, flip)
        if z.hp < z.max_hp:
            frac = max(0.0, z.hp / z.max_hp)
            pygame.draw.rect(self.screen, (110, 20, 20), (x - 10, y - 26, 20, 3))
            pygame.draw.rect(self.screen, (80, 220, 80), (x - 10, y - 26, int(20 * frac), 3))

    def draw_player(self, pl, ox, oy, local=True):
        s = self.screen
        x, y = int(pl.x - ox), int(pl.y - oy)
        c, sn = math.cos(pl.angle), math.sin(pl.angle)
        wlen = WEAPON_LEN.get(pl.weapon, 0)
        d, flip = self.sprite_dir(pl.angle)
        shirt = (70, 120, 200) if local else (80, 170, 110)
        if pl.sneak:
            shirt = tuple(int(v * 0.8) for v in shirt)
        frame = int(self.t * (12 if pl.running else 8)) & 1 if pl.moving else 0
        spr = PA.person(shirt, (50, 54, 72), (232, 196, 160), (86, 56, 36), d, frame, False, 0, pl.hat)
        if wlen and d == "up":                                  # el arma queda detrás del cuerpo
            pygame.draw.line(s, (40, 40, 40), (x, y - 4), (x + c * (PLAYER_R + wlen), y - 4 + sn * (PLAYER_R + wlen)), 3)
        self.draw_sprite(spr, x, y, flip)
        if wlen and d != "up":
            pygame.draw.line(s, (40, 40, 40), (x, y - 4), (x + c * (PLAYER_R + wlen), y - 4 + sn * (PLAYER_R + wlen)), 3)
        if pl.swing_t > 0 and pl.weapon in WEAPONS:
            w = WEAPONS[pl.weapon]
            pts = [(x + math.cos(pl.angle + w["arc"] * (k / 8 - 0.5)) * (w["rng"] + 6),
                    y + math.sin(pl.angle + w["arc"] * (k / 8 - 0.5)) * (w["rng"] + 6)) for k in range(9)]
            pygame.draw.lines(s, (255, 255, 255), False, pts, 2)

    def draw_darkness(self, cam):
        g = self.game
        alpha = g.darkness() * 246 * self.cfg["dark"]
        if alpha < 6:
            return
        m = 1.0 - alpha / 255.0                                   # brillo mínimo (0 = negro total)
        lo = self.light_lo
        lo.fill((int(255 * m * 0.95), int(255 * m * 0.98), min(255, int(255 * m * 1.06))))
        lit = ([g.p] if g.p.alive else []) + g.other_players()
        for pl in lit:
            sx, sy = (pl.x - cam[0]) / LQ, (pl.y - cam[1]) / LQ
            lo.blit(self.amb, (int(sx - self.amb.get_width() / 2), int(sy - self.amb.get_height() / 2)),
                    special_flags=pygame.BLEND_RGB_ADD)
            if pl.flash_on and pl.battery > 0:
                rot = pygame.transform.rotate(self.cone, -math.degrees(pl.angle))
                lo.blit(rot, (int(sx - rot.get_width() / 2), int(sy - rot.get_height() / 2)),
                        special_flags=pygame.BLEND_RGB_ADD)
        for c in g.cars:                                  # faros de los autos con conductor
            if c.driver is not None and c.fuel > 0:
                sx, sy = (c.x - cam[0]) / LQ, (c.y - cam[1]) / LQ
                if -300 < sx < W / LQ + 300 and -300 < sy < H / LQ + 300:
                    rot = pygame.transform.rotate(self.cone, -math.degrees(c.angle))
                    lo.blit(rot, (int(sx - rot.get_width() / 2), int(sy - rot.get_height() / 2)),
                            special_flags=pygame.BLEND_RGB_ADD)
        fps = self.clock.get_fps()
        if fps:                                           # histéresis: si va lento, escala sin suavizar
            if fps < 22:
                self.fast_light = True
            elif fps > 40:
                self.fast_light = False
        if self.fast_light:
            pygame.transform.scale(lo, (W, H), self.light_full)
        else:
            pygame.transform.smoothscale(lo, (W, H), self.light_full)
        self.screen.blit(self.light_full, (0, 0), special_flags=pygame.BLEND_RGB_MULT)

    def draw_eyes(self, cam):
        """De noche los zombis casi no se ven: solo brillan sus ojos rojos cuando te cazan o están muy cerca."""
        g = self.game
        if g.darkness() < 0.35:
            return
        p = g.p
        for z in g.zombies:
            x, y = z.x - cam[0], z.y - cam[1]
            if not (-20 < x < W + 20 and -20 < y < H + 20):
                continue
            d = math.hypot(z.x - p.x, z.y - p.y)
            if (z.state == "chase" and d < 420) or d < 140:
                for side in (-0.45, 0.45):
                    ex = x + math.cos(z.angle + side) * 5
                    ey = y + math.sin(z.angle + side) * 5
                    pygame.draw.circle(self.screen, (120, 0, 0), (int(ex), int(ey)), 3)
                    pygame.draw.circle(self.screen, (255, 40, 30), (int(ex), int(ey)), 1)

    # --- HUD ------------------------------------------------------------------------------------------------------
    def bar(self, x, y, label, value, color, w=170):
        pygame.draw.rect(self.screen, (25, 25, 30), (x - 2, y - 2, w + 4, 18), border_radius=4)
        pygame.draw.rect(self.screen, color, (x, y, int(w * max(0.0, min(1.0, value / 100))), 14), border_radius=3)
        self.text(label, 20, (x + 6, y + 1), (255, 255, 255))

    def draw_hud(self):
        s, g = self.screen, self.game
        p = g.p
        if p.alive and (p.hp < 40 or p.hurt_t > 0):
            a = int(110 * (1 - p.hp / 40)) if p.hp < 40 else 0
            a = max(a, int(160 * max(0.0, p.hurt_t) / 0.3))
            if a > 0:
                s.fill((int(a * 0.9), 0, 0), special_flags=pygame.BLEND_RGB_ADD)

        self.bar(14, H - 94, "Salud", p.hp, (200, 50, 50))
        self.bar(14, H - 72, "Hambre", p.hunger, (220, 150, 50))
        self.bar(14, H - 50, "Sed", p.thirst, (60, 130, 220))
        self.bar(14, H - 28, "Aguante", p.stamina, (220, 210, 70))

        w = WEAPONS.get(p.weapon)
        if p.weapon in GUNS:
            gun = GUNS[p.weapon]
            wtxt = f"{gun['name']}  {p.mag}/{gun['mag']}  (+{p.inv.get(gun['ammo'], 0)})"
        else:
            wtxt = w["name"] + (f"  {p.cond.get(p.weapon, w['dur'])}/{w['dur']}" if w["dur"] else "")
        mtag = "" if g.settings["mode"] == "normal" else f"   [{MODES[g.settings['mode']]['name'].upper()}]"
        self.text(f"Día {g.day()}   {g.clock()}{mtag}", 34, (14, 10), (255, 235, 150))
        car = g.my_car()
        if car:
            wtxt = f"Conduciendo  {abs(int(car.v * 0.11))} km/h"
            self.bar(W - 214, H - 72, "Gasolina", car.fuel, (230, 170, 50))
            self.bar(W - 214, H - 50, "Carrocería", car.hp, (170, 170, 190))
            if car.fuel <= 0:
                self.text("SIN GASOLINA", 40, (W // 2, 90), (255, 120, 90), center=True)
        self.text("Arma: " + wtxt, 24, (14, 40), (230, 230, 240))
        wr = inv_weight(p.inv) / cap_of(p.inv)
        self.text(f"Tablones: {p.inv.get('planks', 0)}   Peso: {inv_weight(p.inv):.1f}/{cap_of(p.inv):.0f} kg" +
                  ("  (cargado: vas más lento)" if wr > 0.5 else ""), 22, (14, 62),
                  (255, 170, 120) if wr > 0.85 else (215, 190, 140))
        if p.flash_on:
            self.text(f"Linterna {int(p.battery)}%", 22, (14, 82), (255, 240, 160))

        if self.mode != "solo":
            n = len(g.other_players()) + 1
            if self.mode == "host":
                if getattr(self.server, "code", ""):
                    info = f"ONLINE - código de sala: {self.server.code} - {n} jugador(es)"
                else:
                    info = f"ONLINE - anfitrión {self.my_ip}:{self.server.port} - {n} jugador(es)"
            else:
                info = f"ONLINE - {n} jugador(es)   (chat, Esc menú)"
            self.text(info, 22, (W // 2, 14), (170, 230, 255), center=True)
            for i, o in enumerate(g.other_players()):
                self.text(f"{o.name}  {int(o.hp)}%", 20, (14, 106 + i * 18), (170, 255, 190))
        if self.cfg["fps"]:
            pf = self.prof
            self.text(f"FPS {int(self.clock.get_fps())}   (ms: lógica {pf.get('logica', 0) * 1000:.1f} | "
                      f"mundo {pf.get('mundo', 0) * 1000:.1f} | luz {pf.get('luz', 0) * 1000:.1f} | "
                      f"HUD {pf.get('hud', 0) * 1000:.1f} | pantalla {pf.get('flip', 0) * 1000:.1f})",
                      20, (W // 2 - 260, 40), (255, 255, 120))

        moodles = []
        if p.infected:
            moodles.append((f"INFECTADO {int(p.inf_t)}s", (255, 80, 80)))
        if p.bleeding:
            moodles.append(("Sangrando (venda)", (255, 110, 110)))
        if p.hunger >= 50:
            moodles.append(("Hambriento" if p.hunger < 80 else "¡Muy hambriento!", (240, 170, 70)))
        if p.thirst >= 50:
            moodles.append(("Sediento" if p.thirst < 80 else "¡Muy sediento!", (110, 170, 240)))
        if p.exhausted:
            moodles.append(("Agotado", (240, 220, 90)))
        if self.sneak:
            moodles.append(("Furtivo", (170, 220, 170)))
        for i, (txt, col) in enumerate(moodles):
            self.text(txt, 24, (200, H - 94 + i * 20 - max(0, len(moodles) - 4) * 20), col)

        self.inv_rows = []
        owned = g.owned()
        x, y = W - 200, 176 if self.show_map else 24
        if owned:
            self.text("INVENTARIO (I = abrir)", 20, (x, y - 18), (190, 190, 205))
        for i, item in enumerate(owned):
            rect = pygame.Rect(x, y + i * 22, 190, 20)
            equipped = (item == p.weapon)
            pygame.draw.rect(s, (60, 110, 70) if equipped else (30, 32, 42), rect, border_radius=4)
            label = f"{i + 1 if i < 9 else ' '} {ITEMS[item]['name']}"
            if p.inv[item] > 1:
                label += f" x{p.inv[item]}"
            self.text(label, 20, (rect.x + 6, rect.y + 3), (190, 255, 200) if equipped else (255, 255, 255))
            self.inv_rows.append((rect, item))

        if self.show_map:
            s.blit(self.minimap, (W - 160, 10))
            pygame.draw.rect(s, (20, 20, 25), (W - 160, 10, 150, 150), 2)
            for o in g.other_players():
                pygame.draw.circle(s, (120, 255, 150), (int(W - 160 + o.x / (N * TS) * 150),
                                                        int(10 + o.y / (N * TS) * 150)), 2)
            pygame.draw.circle(s, (255, 230, 80), (int(W - 160 + p.x / (N * TS) * 150),
                                                   int(10 + p.y / (N * TS) * 150)), 3)

        if self.build_mode:
            parts = [f"{i + 1} {pc['name']} ({pc['cost']})" for i, pc in enumerate(BUILD_PIECES)]
            pygame.draw.rect(s, (20, 22, 30), (W // 2 - 400, H - 70, 800, 50), border_radius=8)
            self.text("MODO CONSTRUIR:  " + "   ".join(parts), 22, (W // 2, H - 56), (190, 235, 255), center=True)
            self.text("Clic = construir  |  mantén la tecla de destruir sobre un bloque para derribarlo", 20,
                      (W // 2, H - 34), (170, 175, 195), center=True)
        prompt = g.interact_text(p) if p.alive and not p.search and not p.fish else ""
        if prompt and not self.build_mode:
            self.text(prompt, 28, (W // 2, H - 150), (255, 255, 255), center=True)
        if p.search:
            frac = p.search[2] / p.search[3]
            pygame.draw.rect(s, (25, 25, 30), (W // 2 - 82, H - 180, 164, 18), border_radius=4)
            pygame.draw.rect(s, (230, 200, 90), (W // 2 - 80, H - 178, int(160 * frac), 14), border_radius=3)
            self.text("Buscando...", 20, (W // 2, H - 171), (30, 25, 10), center=True, shadow=False)
        for i, (txt, ttl, col) in enumerate(p.msgs[-4:]):
            self.text(txt, 26, (W // 2, H - 120 + i * 24 - 24), col, center=True)
        if self.chat is not None:
            pygame.draw.rect(s, (15, 15, 20), (W // 2 - 260, H - 46, 520, 30), border_radius=6)
            self.text("Chat: " + self.chat + ("_" if int(self.t * 2) % 2 == 0 else ""), 26,
                      (W // 2 - 250, H - 40), (255, 255, 200))

    def draw_overlay(self):
        s, g = self.screen, self.game
        p = g.p
        if not p.alive:
            veil = pygame.Surface((W, H), pygame.SRCALPHA)
            veil.fill((60, 0, 0, 190))
            s.blit(veil, (0, 0))
            elapsed = g.minutes - START_MINUTES
            days, hours = int(elapsed // 1440), int((elapsed % 1440) // 60)
            self.text("HAS MUERTO", 110, (W // 2, 220), (230, 60, 50), center=True)
            self.text(f"Causa: {p.cause or 'Desconocida'}", 36, (W // 2, 300), center=True)
            self.text(f"El mundo lleva {days} días y {hours} horas", 40, (W // 2, 350), (255, 235, 150), center=True)
            self.text(f"Zombis eliminados: {p.kills}", 34, (W // 2, 395), center=True)
            if self.mode != "solo" and not g.revive:
                self.text("HARDCORE: no puedes revivir  -  Esc para el menú", 32, (W // 2, 470),
                          (255, 150, 130), center=True)
            else:
                again = "crear un mundo nuevo" if self.mode == "solo" else "reaparecer"
                self.text(f"Pulsa ENTER o R para {again}  -  Esc para el menú", 30, (W // 2, 470),
                          (230, 230, 240), center=True)
            self.text("Tus cosas quedaron junto a tu cuerpo." if self.mode != "solo" and g.revive
                      else "", 24, (W // 2, 510), (255, 200, 140), center=True)

    # --- bucle principal -----------------------------------------------------------------------------------------------
    def quit(self):
        self.stop_net()
        pygame.quit()
        sys.exit()

    def run(self):
        while True:
            self.run_frame()

    async def run_async(self):
        """Bucle para el navegador (pygbag): cede el control al navegador en cada fotograma."""
        import asyncio
        while True:
            self.run_frame()
            await asyncio.sleep(0)

    def run_frame(self):
        if True:
            dt = min(self.clock.tick(FPS) / 1000.0, 0.05)
            self.t += dt
            self.click = self.press = None
            self.mouse_pos = pygame.mouse.get_pos()
            for e in pygame.event.get():
                if e.type == pygame.QUIT:
                    self.quit()
                elif e.type == pygame.KEYDOWN:
                    self.on_keydown(e)
                elif e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                    if self.state == "play" and not self.menu_open and self.chat is None and not self.inv_open:
                        self.on_mouse_down(e.pos)
                    else:
                        self.click = e.pos
                        self.kb_idx = -1
            self.frame(dt)
            t0 = time.perf_counter()
            pygame.display.flip()
            self.prof["flip"] = self.prof.get("flip", 0.0) * 0.9 + (time.perf_counter() - t0) * 0.1

    def on_keydown(self, e):
        if self.rebind:                                       # esperando la nueva tecla
            if e.key != pygame.K_ESCAPE:
                for a, k in list(self.bind.items()):
                    if k == e.key and a != self.rebind:
                        self.bind[a] = self.bind[self.rebind]
                self.bind[self.rebind] = e.key
            self.rebind = None
            return
        in_menu = self.state != "play" or self.menu_open
        if in_menu:
            if self.focus:
                self.type_into_field(e)
            elif e.key in (pygame.K_DOWN, pygame.K_TAB):
                self.kb_idx = (self.kb_idx + 1) % max(1, self.nav_n)
            elif e.key == pygame.K_UP:
                self.kb_idx = (self.kb_idx - 1) % max(1, self.nav_n)
            elif e.key in (pygame.K_RETURN, pygame.K_KP_ENTER, pygame.K_SPACE) and self.kb_idx >= 0:
                self.kb_activate = True
            else:
                self.press = e.key
        elif self.chat is not None:
            self.on_chat_key(e)
        elif self.inv_open:
            self.on_inv_key(e)
        else:
            self.on_key(e.key)

    def frame(self, dt):
        st = self.state
        sig = (st, self.menu_open, self.menu_page)
        if sig != self._nav_sig:
            self._nav_sig = sig
            self.kb_idx = -1
            self.kb_activate = False
        self.nav_i = 0
        try:
            self.frame_inner(dt)
        finally:
            self.nav_n = self.nav_i
            self.kb_activate = False

    def frame_inner(self, dt):
        st = self.state
        self.last_dt = dt
        if st == "title":
            self.draw_title()
        elif st == "solo":
            self.draw_solo()
        elif st == "online":
            self.draw_online()
        elif st == "connecting":
            self.draw_connecting()
        elif st == "gset":
            self.draw_gset()
        elif st == "settings":
            self.draw_settings()
        elif st == "play":
            cam = self.camera()
            self.cam = cam
            p = self.game.p
            if not p.alive:
                self.inv_open = False
            cur = p.open
            if cur and cur != self.cont_prev and self.t >= self.cont_ignore:
                self.inv_open, self.inv_by_cont, self.inv_panel = True, True, 1
                self.inv_sel[1] = 0
                self.cont_prev = cur
            elif not cur and self.cont_prev:
                self.cont_prev = None
                self.inv_panel = 0
                if self.inv_by_cont:
                    self.inv_open = False
            inp = self.build_input(cam)
            t0 = time.perf_counter()
            if not (self.mode == "solo" and (self.menu_open or self.inv_open)):
                self.step(dt, inp)
                if self.state != "play":
                    return
            t1 = time.perf_counter()
            self.draw_world(cam)
            t2 = time.perf_counter()
            self.draw_darkness(cam)
            t3 = time.perf_counter()
            self.draw_eyes(cam)
            self.draw_hud()
            t4 = time.perf_counter()
            for k, v in (("logica", t1 - t0), ("mundo", t2 - t1), ("luz", t3 - t2), ("hud", t4 - t3)):
                self.prof[k] = self.prof.get(k, v) * 0.9 + v * 0.1
            self.draw_overlay()
            if self.inv_open and not self.menu_open:
                self.draw_inventory()
            if self.menu_open:
                self.draw_pause_menu()


def main():
    try:
        _main()
    except SystemExit:
        raise
    except BaseException:
        import traceback
        err = traceback.format_exc()
        try:
            with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "zomboid_error.txt"), "w") as f:
                f.write(err)
        except OSError:
            pass
        print(err)
        raise


def _main():
    args = sys.argv[1:]
    if args and args[0] == "server":
        port = int(args[1]) if len(args) > 1 else PORT
        run_dedicated(port, parse_seed(args[2]) if len(args) > 2 else None,
                      dict(mode=args[3]) if len(args) > 3 else load_cfg()["game"])
    elif args and args[0] == "host":
        port = int(args[1]) if len(args) > 1 else PORT
        App(("host", port, args[2] if len(args) > 2 else "")).run()
    elif args and args[0] == "join" and len(args) > 1:
        App(("join", args[1])).run()
    else:
        App().run()


if __name__ == "__main__":
    main()
