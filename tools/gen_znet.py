"""Genera znet_js.py (znet.js empaquetado como texto para que pygbag lo incluya en el juego)."""
import os
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
src = open(os.path.join(root, "znet.js"), encoding="utf-8").read()
open(os.path.join(root, "znet_js.py"), "w", encoding="utf-8").write(
    "# Archivo generado por tools/gen_znet.py - no editar a mano\nSOURCE = " + repr(src) + "\n")
print("znet_js.py generado")
