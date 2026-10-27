# Zomboid Py

Juego de supervivencia zombi en vista cenital (inspirado en Project Zomboid), hecho con Python y pygame.

## Jugar en el navegador (un jugador)
Cuando GitHub Pages esté activo, el juego está en:
`https://soydaef.github.io/zomboid/`
(la primera vez carga unos segundos; haz clic en la página para empezar).

## Jugar en PC (con modo online y LAN)
```
python -m pip install pygame
python zomboid.py
```
Servidor dedicado: `python zomboid.py server 5555`

## Controles
W A S D mover | Shift correr | C furtivo | Ratón apuntar | Clic izq. atacar | Clic der. apuntar pistola
E interactuar | F linterna | R recargar | I inventario | Tab cambiar arma | H venda | Q comer/beber
B construir | G (mantener) destruir | V lanzar botella | M minimapa | T chat | Esc menú
(todas las teclas se pueden cambiar en Ajustes)

## Nota
En el navegador no existe el modo online (los navegadores no permiten conexiones TCP directas).
