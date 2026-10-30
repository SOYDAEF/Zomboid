# Zomboid Py

Juego de supervivencia zombi en vista cenital (inspirado en Project Zomboid), hecho con Python y pygame.

## Jugar en el navegador (un jugador)
Cuando GitHub Pages esté activo, el juego está en:
`https://soydaef.github.io/Zomboid/`
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
B construir | G (mantener) destruir | V lanzar (botella o explosivo; elige cuál con «Preparar» en el inventario) | M minimapa | T chat | Esc menú
(todas las teclas se pueden cambiar en Ajustes)

## Nota
Ahora sí hay modo online para amigos

## Prueba de conexión entre navegadores (WebRTC)
`rtc-test/` contiene una prueba de conexión directa entre navegadores con código de sala
(`znet.js`). Una vez publicada la página: `https://soydaef.github.io/Zomboid/rtc-test/`

## Explosivos y mochilas
- Explosivos: granada, cóctel molotov, dinamita y petardos (se lanzan con V).
- Mochilas (se equipan en la ranura de espalda del inventario): pequeña +8 kg, normal +14, de montaña +24, militar +28 (máximo 50 kg en total).
- Las listas del inventario y de los cofres tienen scroll (rueda del ratón, barra arrastrable, flechas y Re Pág/Av Pág).

## Luz y zombis
- Antorchas: «Usar» la clava en el suelo (iluminan y ningún zombi aparece a su alrededor); Interactuar la recoge.
- Cada casa tiene un interruptor de luz junto a la esquina norte interior: Interactuar lo enciende/apaga. Con la luz encendida el interior se ve y no aparecen zombis dentro.
