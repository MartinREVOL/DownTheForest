"""
Test minimal pour verifier que le rendu Ursina/Panda3D fonctionne
correctement sur cette machine, independamment de forest3d.py.

Lancer avec : python test_ursina_sanity.py

Attendu : une fenetre avec un fond gris fonce et un cube orange qui
tourne lentement au centre. Si meme CA c'est blanc, le probleme est
environnemental (pilote graphique / Panda3D), pas dans forest3d.py.
"""

from ursina import Ursina, Entity, color, camera, window, time

app = Ursina(title="sanity check", borderless=False, fullscreen=False)

window.color = color.rgb32(20, 20, 25)  # fond gris tres fonce

cube = Entity(model="cube", color=color.rgb32(230, 120, 40), scale=2)
camera.position = (0, 0, -8)


def update():
    cube.rotation_y += 30 * time.dt


app.run()
