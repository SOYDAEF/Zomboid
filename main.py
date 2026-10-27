# /// script
# dependencies = [
#  "pygame-ce",
# ]
# ///
"""Punto de entrada para el navegador (pygbag). En PC ejecuta mejor: python zomboid.py"""
import asyncio

import pygame  # noqa: F401  (pygbag detecta aquí que el juego usa pygame)

import zomboid


async def main():
    app = zomboid.App()
    await app.run_async()


asyncio.run(main())
