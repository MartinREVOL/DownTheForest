"""
DownTheForest - phase 3D
Foret procedurale infinie. Pas de monstres. Pas de sortie.
Lancement : python forest3d.py [save.json]
"""

import json
import math
import os
import random
import sys

from ursina import (
    Ursina, Entity, Text, Vec2, Vec3, camera, scene, window, color,
    held_keys, time, application, destroy, invoke, clamp,
    load_model, Mesh, Color,
)
from ursina.prefabs.first_person_controller import FirstPersonController


def destroy_deep(entity):
    """destroy() tout court ne suffit plus : a partir d'ursina 8, il ne
    detruit plus les enfants d'une entite (la recursion sur
    entity.children a ete commentee dans le moteur - verifie en
    reproduisant le bug avec la meme version qu'en jeu : ursina 7 ne le
    fait pas, ursina 8.3.0 oui). Concretement : detruire un tronc d'arbre
    enleve bien le tronc de la scene, mais son feuillage (un enfant
    Panda3D separe) reste reference pour toujours dans scene.entities,
    invisible (son parent a disparu) mais jamais nettoye. C'est EXACTEMENT
    la fuite qui cause le ralentissement progressif et irreversible :
    verifie en rejouant les memes chiffres (scene.entities qui grimpe sans
    fin en explorant, chunks pourtant stable) dans un bac a sable avec la
    version exacte d'ursina utilisee en jeu.

    Cette fonction refait la recursion nous-memes et DOIT etre utilisee a
    la place de destroy() partout dans ce fichier des qu'une entite peut
    avoir des enfants (ce qui est le cas de presque tout : arbres,
    anomalies, torches...) - destroy() seule ne doit plus jamais etre
    appelee directement ici."""
    for child in list(entity.children):
        destroy_deep(child)
    destroy(entity)


# ----------------------------------------------------------------------
# Reglages (developer settings) : settings.json, a cote du script.
# On peut changer ces valeurs sans toucher au code Python. Le fichier est
# cree automatiquement avec les valeurs par defaut s'il n'existe pas.
# ----------------------------------------------------------------------

SETTINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

DEFAULT_SETTINGS = {
    "walk_speed": 4.0,          # vitesse de marche
    "mouse_sensitivity": 38.0,  # sensibilite de la souris
    "eye_height": 2.0,          # hauteur des yeux
    "gravity": 1.0,             # 0 = pas de gravite/saut, 1 = normal
    "jump_height": 1.5,         # hauteur du saut (metres)

    "chunk_size": 20.0,         # taille d'un chunk en metres
    "chunk_radius": 2,          # chunks charges autour du joueur (5x5) - baisser si ca rame
    "compute_radius": 3,        # limite dure : rien n'est simule au-dela de ce rayon de
                                 # chunks autour du joueur (collisions, lumiere de la
                                 # torche, ramassage, derive du decor), quoi qu'il arrive -
                                 # meme si chunk_radius est augmente.
    "trees_per_chunk": 14,      # densite de la foret

    "fog_calm": 0.045,          # brouillard de depart
    "fog_max": 0.11,            # brouillard a malaise = 1
    "fog_torch": 0.030,         # brouillard torche allumee
    "torch_seconds": 45.0,      # duree d'une torche

    "cold_start": 0.35,         # malaise a partir duquel le froid mord
    "cold_period": 9.0,         # secondes entre deux pertes de HP

    "path_length": 900.0,       # longueur du chemin qui mene a la fin "sentier"

    "torch_pickup_chance": 0.08,  # proba par chunk qu'une torche ramassable y apparaisse
}


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                for key in DEFAULT_SETTINGS:
                    if key in data:
                        settings[key] = data[key]
        except (ValueError, OSError):
            print("settings.json illisible, valeurs par defaut utilisees.")
    else:
        try:
            with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
                json.dump(DEFAULT_SETTINGS, f, indent=2, ensure_ascii=False)
        except OSError:
            pass
    return settings


SETTINGS = load_settings()

CHUNK = float(SETTINGS["chunk_size"])
CHUNK_RADIUS = int(SETTINGS["chunk_radius"])
# Limite dure et absolue : jamais plus large que CHUNK_RADIUS (ce qui est
# charge), et jamais plus large que la valeur du reglage, quoi qu'il arrive
# ailleurs dans le code (malaise, torche, nombre d'objets...).
COMPUTE_RADIUS = min(int(SETTINGS["compute_radius"]), CHUNK_RADIUS)
TREES_PER_CHUNK = int(SETTINGS["trees_per_chunk"])
EYE = float(SETTINGS["eye_height"])
WALK_SPEED = float(SETTINGS["walk_speed"])
MOUSE_SENSITIVITY = float(SETTINGS["mouse_sensitivity"])
GRAVITY = float(SETTINGS["gravity"])
JUMP_HEIGHT = float(SETTINGS["jump_height"])

FOG_CALM = float(SETTINGS["fog_calm"])
FOG_MAX = float(SETTINGS["fog_max"])
FOG_TORCH = float(SETTINGS["fog_torch"])
TORCH_SECONDS = float(SETTINGS["torch_seconds"])

COLD_START = float(SETTINGS["cold_start"])
COLD_PERIOD = float(SETTINGS["cold_period"])

# Palette : tout est presque noir. Le brouillard fait le reste.
C_GROUND = color.rgb32(14, 15, 13)
C_TRUNK = color.rgb32(26, 22, 19)
C_CANOPY = color.rgb32(17, 21, 17)
C_FOG_NIGHT = color.rgb32(4, 5, 6)
C_FOG_TORCH = color.rgb32(16, 11, 7)
C_ANOMALY = color.rgb32(38, 36, 33)
C_PALE = color.rgb32(96, 94, 88)

SEED = random.randint(0, 10**9)


# ----------------------------------------------------------------------
# Etat du joueur, importe depuis la phase terminal
# ----------------------------------------------------------------------

class State:
    def __init__(self):
        self.hp = 10
        self.inventory = []
        self.malaise = 0.0
        self.distance = 0.0
        self.torch = 0.0
        self.cold_timer = 0.0
        self.seen_anomalies = 0
        self.elapsed = 0.0


def load_state(path):
    # Pas de sauvegarde valide -> pas de phase 3D. On ne demarre pas
    # sans etre passe par le sentier du jeu terminal (python manager.py).
    if not path or not os.path.exists(path):
        print("Aucune sauvegarde trouvee.")
        print("Termine d'abord le sentier dans le jeu terminal : python manager.py")
        sys.exit(1)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (ValueError, OSError) as e:
        print(f"Sauvegarde illisible ({path}) : {e}")
        print("Relance python manager.py pour en generer une nouvelle.")
        sys.exit(1)

    st = State()
    st.hp = int(data.get("hp", 10))
    st.inventory = list(data.get("inventory", []))
    return st


# ----------------------------------------------------------------------
# Aleatoire deterministe par chunk : le meme chunk se regenere identique
# ----------------------------------------------------------------------

def chunk_rng(cx, cz, salt=0):
    h = (SEED * 73856093) ^ ((cx + 9999) * 19349663) ^ ((cz + 9999) * 83492791)
    return random.Random(h ^ (salt * 2654435761))


# ----------------------------------------------------------------------
# Briques de decor : uniquement des cubes et des spheres
# ----------------------------------------------------------------------

def _lightable(entity, children=()):
    """Marque une entite (et ses enfants visuels) comme reagissant a la
    torche : on retient sa couleur d'origine pour pouvoir la teinter puis
    y revenir. Voir update_torch_light()."""
    entity.base_color = entity.color
    entity.lit_children = list(children)
    for c in entity.lit_children:
        c.base_color = c.color
    return entity


_TREE_MODEL_CACHE = {}


def _cached_primitive_model(name):
    """Charge un modele primitif ("cube", "sphere"...) une seule fois et
    le garde en cache : voir _combine_tree pour pourquoi."""
    m = _TREE_MODEL_CACHE.get(name)
    if m is None:
        m = load_model(name, use_deepcopy=True)
        _TREE_MODEL_CACHE[name] = m
    return m


def _combine_tree(trunk):
    """Fusionne trunk + ses enfants directs (canopy ou branches) en un
    seul maillage. Fait la meme chose qu'Entity.combine() (utilise dans
    une premiere version), mais en beaucoup plus rapide : verifie au
    profiler (cProfile sur 6 chargements de chunk, scene deja peuplee
    d'environ 500 entites) que combine() a elle seule prenait 90% du
    temps de chargement d'un chunk, pour deux raisons precises :

    1. Elle reparcourt TOUTE la scene (scene.entities, l'attribut
       has_ancestor()) pour retrouver les enfants de CHAQUE arbre fusionne
       - un cout qui grossit avec le nombre d'entites deja chargees. Ici,
       on connait deja les enfants : on vient de les creer juste au-dessus
       dans make_tree().
    2. Pour chaque piece fusionnee (tronc, feuillage...), elle recharge le
       modele primitif ("cube", "sphere") en le deep-copiant - ce qui
       reconstruit sa geometrie Panda3D en entier - meme quand un cube ou
       une sphere identique a deja servi cent fois. Avec ~15 arbres par
       chunk (30-45 pieces), ca fait autant de reconstructions inutiles
       d'un meme modele : la cause du freeze net a chaque chargement de
       chunk. Ici chaque forme n'est chargee qu'une fois pour toute la
       partie (_cached_primitive_model) : on ne fait que LIRE ses sommets/
       triangles/UV pour les recopier a la bonne position, jamais que la
       recharger."""
    parts = [trunk] + list(trunk.children)
    verts, tris, uvs, cols = [], [], [], []
    o = 0
    for e in parts:
        model = _cached_primitive_model(e.model.name)
        mat = e.getTransform(trunk).getMat()
        verts += [Vec3(*mat.xformPoint(v)) for v in model.vertices]

        if model.triangles:
            new_tris = []
            for t in model.triangles:
                if isinstance(t, int):
                    new_tris.append(t)
                elif len(t) == 3:
                    new_tris.extend(t)
                elif len(t) == 4:  # quad -> 2 triangles
                    new_tris.extend([t[0], t[1], t[2], t[2], t[3], t[0]])
        else:
            new_tris = list(range(len(model.vertices)))
        new_tris = [t + o for t in new_tris]
        tris += [(new_tris[i], new_tris[i + 1], new_tris[i + 2])
                 for i in range(0, len(new_tris) - 2, 3)]
        o += len(model.vertices)

        if model.uvs:
            uvs.extend([(Vec2(*uv) * e.texture_scale) + e.texture_offset for uv in model.uvs])
        else:
            uvs.extend([(0, 0) for _ in model.vertices])

        if model.colors:
            cols.extend([Color(*vcol) * e.color for vcol in model.colors])
        else:
            cols.extend((e.color,) * len(model.vertices))

    for e in list(trunk.children):
        destroy_deep(e)

    trunk.model = Mesh(vertices=verts, triangles=tris, uvs=uvs, colors=cols, mode="triangle")


def _lightable_combined(entity):
    """Comme _lightable, mais pour une entite qui vient d'etre fusionnee
    avec Entity.combine() (voir make_tree) : son maillage contient deja,
    figees dans les sommets, les couleurs d'origine de chacune de ses
    parties (tronc, feuillage...) - impossible de les re-teindre une par
    une separement puisqu'elles n'existent plus comme entites a part.

    entity.color redevient alors un multiplicateur (setColorScale de
    Panda3D) applique par-dessus ces couleurs figees plutot qu'une couleur
    de remplacement absolue : on repart donc de blanc neutre (aucun
    changement), pas de la couleur de fabrication du tronc. Voir
    _torch_lit_scale(), le pendant de _torch_lit_color() pour ce cas."""
    entity.color = color.rgba(1, 1, 1, 1)
    entity.base_color = entity.color
    entity.lit_children = []
    entity.combined = True
    return entity


def make_tree(x, z, rng, dead=False):
    h = rng.uniform(5.0, 11.0)
    lean = rng.uniform(-3.0, 3.0)
    r = rng.uniform(0.30, 0.55)
    trunk = Entity(
        model="cube",
        color=C_TRUNK,
        position=(x, h / 2, z),
        scale=(r, h, rng.uniform(0.30, 0.55)),
        rotation=(lean, rng.uniform(0, 360), lean * 0.5),
        unlit=True,
    )
    tree_radius = 0.6
    if not dead:
        # "icosphere" plutot que "sphere" : le modele "sphere" d'ursina
        # fait 2880 sommets (une sphere lissee, faite pour etre vue de
        # pres) contre 60 pour "icosphere" - la difference est invisible
        # ici (feuillage plat, sans lumiere, ecrase en ellipsoide, dans le
        # brouillard), mais _combine_tree() (voir plus bas) doit recopier
        # ces sommets un par un en Python a chaque arbre genere : avec
        # jusqu'a 14-18 arbres par chunk, la sphere lissee etait a elle
        # seule la moitie du temps de chargement d'un chunk (mesure au
        # profiler), donc du freeze ressenti a chaque chargement.
        #
        # ATTENTION : "sphere" fait un diametre de 1 unite dans les 3 axes
        # (rayon 0.5, une vraie sphere), alors que "icosphere" (mesure
        # directement sur le modele) fait 1.79 x 2.0 x 1.70 - presque le
        # double, et pas pareil sur chaque axe. Les valeurs de `scale`
        # ci-dessous ont ete calibrees a l'oeil pour "sphere" (diametre 1) :
        # sans cette division, chaque feuillage ressort ~2x plus gros que
        # prevu sur chaque arbre, au point de se chevaucher massivement
        # d'un arbre a l'autre et de former un "plafond" continu au-dessus
        # de la foret - exactement le bug rapporte.
        Entity(
            parent=trunk,
            model="icosphere",
            color=C_CANOPY,
            y=0.34,
            scale=((rng.uniform(4.0, 7.5) / max(trunk.scale_x, 0.01)) / 1.7889,
                   (rng.uniform(0.30, 0.50)) / 2.0,
                   (rng.uniform(4.0, 7.5) / max(trunk.scale_z, 0.01)) / 1.7013),
            unlit=True,
        )
    else:
        for _ in range(rng.randint(2, 4)):
            Entity(
                parent=trunk,
                model="cube",
                color=C_TRUNK,
                y=rng.uniform(0.15, 0.45),
                scale=(rng.uniform(3.0, 6.0), 0.06, 0.06),
                rotation=(0, rng.uniform(0, 360), rng.uniform(-25, 25)),
                unlit=True,
            )

    # Fusionne tronc + feuillage/branches en un seul maillage (voir
    # _combine_tree) : jusqu'a 14-18 arbres par chunk, chacun avec 1 a 4
    # enfants, ca fait vite 500+ entites/appels de rendu rien que pour les
    # arbres charges autour du joueur - la premiere chose qui plombe le
    # framerate avant meme toute fuite. Ca detruit les enfants et renvoie
    # un seul objet (moins de calculs, moins d'appels de rendu par frame),
    # au prix de ne plus pouvoir re-teindre le tronc et le feuillage
    # separement a l'approche de la torche (voir _lightable_combined).
    _combine_tree(trunk)
    trunk.tree_radius = tree_radius
    _lightable_combined(trunk)
    return trunk


def make_ground(cx, cz):
    ground = Entity(
        model="plane",
        color=C_GROUND,
        position=(cx * CHUNK, 0, cz * CHUNK),
        scale=(CHUNK, 1, CHUNK),
        unlit=True,
        collider="box",   # necessaire pour que la gravite/le saut trouvent le sol
    )
    return _lightable(ground)


# ----------------------------------------------------------------------
# Anomalies : statiques, rares, deniables
# ----------------------------------------------------------------------

def anomaly_ring(x, z, rng, chunk):
    """Des arbres en cercle trop parfait. Quelqu'un les a plantes."""
    n = rng.randint(7, 11)
    r = rng.uniform(5.0, 8.0)
    for i in range(n):
        a = (i / n) * math.tau
        chunk.trees.append(make_tree(x + math.cos(a) * r, z + math.sin(a) * r, rng))


def anomaly_row(x, z, rng, chunk):
    """Une ligne droite d'arbres, espacement au centimetre."""
    a = rng.uniform(0, math.tau)
    gap = rng.uniform(2.6, 3.2)
    for i in range(rng.randint(6, 10)):
        chunk.trees.append(
            make_tree(x + math.cos(a) * gap * i, z + math.sin(a) * gap * i, rng)
        )


def anomaly_chair(x, z, rng, chunk):
    """Une chaise seule au centre d'une clairiere. Tournee vers le joueur."""
    seat = Entity(model="cube", color=C_ANOMALY, position=(x, 0.45, z),
                  scale=(0.55, 0.07, 0.55), rotation_y=rng.uniform(0, 360), unlit=True)
    parts = [Entity(parent=seat, model="cube", color=C_ANOMALY, y=4.0, z=-0.45,
                     scale=(1, 9, 0.12), unlit=True)]
    for dx, dz in ((-.4, -.4), (.4, -.4), (-.4, .4), (.4, .4)):
        parts.append(Entity(parent=seat, model="cube", color=C_ANOMALY, x=dx, z=dz, y=-3.2,
                             scale=(0.12, 6.5, 0.12), unlit=True))
    seat.collide_radius = 0.65
    _lightable(seat, parts)
    chunk.props.append(seat)


def anomaly_stairs(x, z, rng, chunk):
    """Un escalier recouvert de moquette, au milieu des bois, qui ne mene nulle part."""
    steps = rng.randint(7, 13)
    a = rng.uniform(0, math.tau)
    carpet = color.rgb32(46, 26, 24)
    for i in range(steps):
        step = Entity(
            model="cube",
            color=carpet if i % 2 == 0 else C_ANOMALY,
            position=(x + math.cos(a) * i * 0.3, 0.18 * i, z + math.sin(a) * i * 0.3),
            scale=(1.5, 0.18, 0.32),
            rotation_y=math.degrees(a),
            unlit=True,
        )
        _lightable(step)
        chunk.props.append(step)   # sinon jamais nettoye au dechargement du chunk

    base = Entity(model="cube", color=C_ANOMALY, position=(x, 0.1, z),
                  scale=(1.6, 0.2, 0.4), unlit=True)
    base.collide_radius = max(1.0, steps * 0.3 * 0.55)
    _lightable(base)
    chunk.props.append(base)


def anomaly_dolls(x, z, rng, chunk):
    """Des poupees pendues aux branches. Il y en a toujours une de plus qu'on croyait."""
    for _ in range(rng.randint(2, 6)):
        px = x + rng.uniform(-6, 6)
        pz = z + rng.uniform(-6, 6)
        top = rng.uniform(2.6, 4.4)
        string = Entity(model="cube", color=C_TRUNK, position=(px, top + 0.35, pz),
                         scale=(0.03, 0.7, 0.03), unlit=True)
        _lightable(string)
        chunk.props.append(string)   # sinon jamais nettoye au dechargement du chunk

        body = Entity(model="cube", color=C_PALE, position=(px, top, pz),
                      scale=(0.16, 0.34, 0.1), rotation_y=rng.uniform(0, 360), unlit=True)
        head = Entity(parent=body, model="sphere", y=0.75, scale=(1.5, 0.7, 2.2),
               color=C_PALE, unlit=True)
        _lightable(body, [head])
        chunk.props.append(body)


def anomaly_tent(x, z, rng, chunk):
    """Une tente lacere de l'interieur. Vide."""
    t = Entity(model="cube", color=color.rgb32(52, 48, 40), position=(x, 0.55, z),
               scale=(2.4, 1.1, 3.2), rotation_y=rng.uniform(0, 360), unlit=True)
    slashes = []
    for _ in range(rng.randint(3, 6)):
        slashes.append(Entity(parent=t, model="cube", color=color.rgb32(2, 2, 2),
               x=rng.uniform(-.5, .5), y=rng.uniform(-.2, .3), z=0.51,
               scale=(rng.uniform(0.03, 0.07), rng.uniform(0.3, 0.8), 0.02),
               rotation_z=rng.uniform(-30, 30), unlit=True))
    t.collide_radius = 1.6
    _lightable(t, slashes)
    chunk.props.append(t)


def anomaly_door(x, z, rng, chunk):
    """Un chambranle de porte debout, seul. Fermee."""
    a = rng.uniform(0, 360)
    frame = Entity(model="cube", color=C_ANOMALY, position=(x, 1.05, z),
                   scale=(1.1, 2.1, 0.12), rotation_y=a, unlit=True)
    panel = Entity(parent=frame, model="cube", color=color.rgb32(30, 25, 22),
           scale=(0.86, 0.94, 1.6), unlit=True)
    frame.collide_radius = 0.6
    _lightable(frame, [panel])
    chunk.props.append(frame)


def anomaly_tile(x, z, rng, chunk):
    """Une dalle incrustee dans le sol, la ou personne n'a jamais rien construit."""
    tile = Entity(model="cube", color=color.rgb32(30, 28, 30), position=(x, 0.02, z),
                  scale=(0.9, 0.04, 0.6), rotation_y=rng.uniform(0, 360), unlit=True)
    stripes = []
    for i in range(3):
        stripes.append(Entity(parent=tile, model="cube", color=color.rgb32(60, 20, 18),
               y=0.6, z=(i - 1) * 0.28, scale=(0.75, 0.4, 0.06), unlit=True))
    _lightable(tile, stripes)
    chunk.props.append(tile)


def anomaly_fence(x, z, rng, chunk):
    """Une cloture. Elle commence nulle part et finit nulle part."""
    a = rng.uniform(0, math.tau)
    for i in range(rng.randint(8, 16)):
        post = Entity(model="cube", color=C_TRUNK,
               position=(x + math.cos(a) * i * 1.4, 0.55, z + math.sin(a) * i * 1.4),
               scale=(0.09, 1.1, 0.09), rotation=(rng.uniform(-6, 6), 0, rng.uniform(-8, 8)),
               unlit=True)
        post.collide_radius = 0.2
        _lightable(post)
        chunk.props.append(post)   # sinon jamais nettoye au dechargement du chunk


ANOMALIES = [
    anomaly_ring, anomaly_row, anomaly_chair, anomaly_stairs,
    anomaly_dolls, anomaly_tent, anomaly_door, anomaly_tile, anomaly_fence,
]

# Visibles seulement a la lumiere de la torche.
MARK_GLYPHS = ["6EQUJ5", "IIIIIIIIIIII", "22", "きさらぎ"]


def make_mark(x, z, rng):
    """Des marques gravees sur un tronc. On ne les voit qu'avec la torche."""
    m = Entity(model="cube", color=color.rgb32(74, 66, 52),
               position=(x, rng.uniform(1.3, 1.9), z),
               scale=(0.36, 0.20, 0.36), rotation_y=rng.uniform(0, 360), unlit=True)
    m.torch_only = True
    # Etat initial aligne sur la torche actuelle (pas juste False) : un
    # chunk peut se charger pendant que la torche est deja allumee, et
    # update_torch() ne re-balaie les marques que lors d'un changement
    # d'etat, pas a chaque frame (voir plus bas).
    m.enabled = state.torch > 0
    m.glyph = rng.choice(MARK_GLYPHS)
    _lightable(m)
    return m


# ----------------------------------------------------------------------
# Torches ramassables : au sol, visibles (pas besoin de la torche allumee
# pour les voir), avec un "[E] Ramasser" quand on est proche. Voir
# update_pickups()/try_pickup() plus bas pour la detection et la prise.
# ----------------------------------------------------------------------

TORCH_PICKUP_CHANCE = float(SETTINGS["torch_pickup_chance"])
TORCH_PICKUP_COLOR = color.rgb32(235, 150, 60)   # meme teinte que l'icone de la barre


def make_torch_pickup(x, z, rng, chunk):
    """Une torche eteinte, posee au sol : un manche brun et une tete de
    la meme couleur que son icone dans la barre, pour qu'on la reconnaisse
    tout de suite."""
    handle = Entity(model="cube", color=C_TRUNK, position=(x, 0.075, z),
                     scale=(0.62, 0.09, 0.09), rotation_y=rng.uniform(0, 360), unlit=True)
    tip = Entity(parent=handle, model="cube", color=TORCH_PICKUP_COLOR,
                 x=0.46, scale=(0.14, 1.4, 1.4), unlit=True)
    handle.pickup_kind = "🕯️"
    handle.pickup_label = "une torche"
    handle.pickup_radius = 1.3
    _lightable(handle, [tip])
    chunk.props.append(handle)
    return handle


# ----------------------------------------------------------------------
# Le chemin : une des fins du jeu. Une piste procedurale, generee une
# fois au lancement (deterministe via SEED), qui avance globalement tout
# droit (le cap de depart, +Z, est celui du joueur a l'arrivee en 3D) avec
# de petits virages, et ne boucle jamais sur elle-meme. La suivre jusqu'au
# bout, sans devier, est la fin la plus simple du jeu.
#
# Contrairement au reste du decor (qui n'est "jamais tout a fait le meme"
# d'un passage a l'autre, voir update_chunks), les bornes du chemin sont
# recalculees identiques a chaque reconstruction de chunk : c'est la seule
# chose de la foret sur laquelle on peut compter.
# ----------------------------------------------------------------------

PATH_LENGTH = float(SETTINGS["path_length"])
PATH_STEP = 9.0          # distance entre deux virages possibles (m)
PATH_TURN_MAX = 16.0     # deviation de cap max a chaque pas (degres)
PATH_HEADING_LIMIT = 65.0  # cap total jamais plus de X degres depuis +Z
PATH_MARK_GAP = 2.6      # espacement des bornes visuelles au sol (m)
PATH_END_RADIUS = 3.0    # distance a laquelle on declenche la fin


def _build_path():
    """Suite de points (x, z) du spawn (0, 0) jusqu'a la fin du chemin.
    Le cap est clampe (PATH_HEADING_LIMIT) plutot que libre : sans ca,
    une derive aleatoire non bornee peut, sur des centaines de metres,
    revenir sur elle-meme ou se recroiser. Ici le chemin serpente un peu
    mais avance toujours, net, loin du point de depart."""
    rng = random.Random(SEED ^ 0xDEC0DE)
    heading = 0.0  # +Z : le cap de depart du joueur en arrivant en 3D
    x, z = 0.0, 0.0
    points = [(x, z)]
    travelled = 0.0
    while travelled < PATH_LENGTH:
        heading += rng.uniform(-PATH_TURN_MAX, PATH_TURN_MAX)
        heading = clamp(heading, -PATH_HEADING_LIMIT, PATH_HEADING_LIMIT)
        rad = math.radians(heading)
        x += math.sin(rad) * PATH_STEP
        z += math.cos(rad) * PATH_STEP
        points.append((x, z))
        travelled += PATH_STEP
    return points


def _densify_path(waypoints, gap):
    """Reinterpole les virages en points regulierement espaces de `gap`,
    pour poser des bornes au sol sans trou ni amas."""
    dense = [waypoints[0]]
    for (x0, z0), (x1, z1) in zip(waypoints, waypoints[1:]):
        seg = math.dist((x0, z0), (x1, z1))
        steps = max(1, int(seg / gap))
        for i in range(1, steps + 1):
            t = i / steps
            dense.append((x0 + (x1 - x0) * t, z0 + (z1 - z0) * t))
    return dense


PATH_WAYPOINTS = _build_path()
PATH_END = PATH_WAYPOINTS[-1]
PATH_MARKS = _densify_path(PATH_WAYPOINTS, PATH_MARK_GAP)

# Index par chunk : pour chaque case (cx, cz), les points du chemin qui y
# tombent. Construit une fois ; consulte a chaque Chunk.build().
PATH_BY_CHUNK = {}
for _i, (_px, _pz) in enumerate(PATH_MARKS):
    _key = (round(_px / CHUNK), round(_pz / CHUNK))
    PATH_BY_CHUNK.setdefault(_key, []).append((_i, _px, _pz))


def make_path_mark(x, z, i):
    """Une borne pale au sol, sur le chemin. Position et forme fixes,
    derivees de SEED + i (pas de chunk_rng/malaise) : elle ne change jamais,
    contrairement au reste du decor."""
    rng = random.Random(SEED ^ 0xB0A1D ^ i)
    m = Entity(model="cube", color=C_PALE,
               position=(x + rng.uniform(-0.25, 0.25), 0.035, z + rng.uniform(-0.25, 0.25)),
               scale=(rng.uniform(0.5, 0.8), 0.05, rng.uniform(0.4, 0.65)),
               rotation_y=rng.uniform(0, 360), unlit=True)
    return _lightable(m)


def make_path_end_marker(x, z):
    """Un petit cairn de pierres claires : le seul repere fixe de toute la
    foret, pose la ou le chemin s'arrete."""
    base = Entity(model="cube", color=C_PALE, position=(x, 0.25, z),
                  scale=(1.4, 0.5, 1.4), unlit=True)
    mid = Entity(parent=base, model="cube", color=C_PALE, y=0.55,
                 scale=(0.7, 0.55, 0.7), rotation_y=22, unlit=True)
    top = Entity(parent=base, model="cube", color=C_PALE, y=1.0,
                 scale=(0.34, 0.5, 0.34), rotation_y=48, unlit=True)
    return _lightable(base, [mid, top])


# ----------------------------------------------------------------------
# Chunks
# ----------------------------------------------------------------------

class Chunk:
    def __init__(self, cx, cz, malaise):
        self.cx, self.cz = cx, cz
        self.trees = []
        self.props = []
        self.marks = []
        self.ground = make_ground(cx, cz)
        self.build(malaise)

    def build(self, malaise):
        rng = chunk_rng(self.cx, self.cz, salt=int(malaise * 8))
        ox, oz = self.cx * CHUNK, self.cz * CHUNK

        count = int(TREES_PER_CHUNK * rng.uniform(0.7, 1.3))
        for _ in range(count):
            x = ox + rng.uniform(-CHUNK / 2, CHUNK / 2)
            z = oz + rng.uniform(-CHUNK / 2, CHUNK / 2)
            self.trees.append(make_tree(x, z, rng, dead=rng.random() < 0.10 + malaise * 0.25))

        if rng.random() < 0.05 + malaise * 0.30:
            ax = ox + rng.uniform(-CHUNK / 4, CHUNK / 4)
            az = oz + rng.uniform(-CHUNK / 4, CHUNK / 4)
            rng.choice(ANOMALIES)(ax, az, rng, self)

        if rng.random() < 0.12 + malaise * 0.3:
            mk = make_mark(ox + rng.uniform(-CHUNK / 2, CHUNK / 2),
                           oz + rng.uniform(-CHUNK / 2, CHUNK / 2), rng)
            self.marks.append(mk)

        # Plus de torches a mesure que le malaise (et donc le froid) monte.
        if rng.random() < TORCH_PICKUP_CHANCE + malaise * 0.05:
            tx = ox + rng.uniform(-CHUNK / 2, CHUNK / 2)
            tz = oz + rng.uniform(-CHUNK / 2, CHUNK / 2)
            make_torch_pickup(tx, tz, rng, self)

        # Bornes du chemin qui traversent cette case, s'il y en a. Position
        # fixe (voir make_path_mark) : contrairement au reste, identiques a
        # chaque reconstruction du chunk.
        for i, px, pz in PATH_BY_CHUNK.get((self.cx, self.cz), ()):
            self.props.append(make_path_mark(px, pz, i))

    def entities(self):
        return self.trees + self.props + self.marks + [self.ground]

    def destroy(self):
        for e in self.entities():
            destroy_deep(e)


# ----------------------------------------------------------------------
# Application
# ----------------------------------------------------------------------

app = Ursina(title="", borderless=False, fullscreen=False, development_mode=True)
window.color = C_FOG_NIGHT
window.editor_ui.enabled = False

scene.fog_color = C_FOG_NIGHT
scene.fog_density = FOG_CALM
camera.clip_plane_far = 320

state = load_state(sys.argv[1] if len(sys.argv) > 1 else "save.json")

player = FirstPersonController(position=(0, 0, 0), speed=WALK_SPEED)
player.height = EYE               # utilise par le raycast de gravite
player.camera_pivot.y = EYE       # hauteur reelle de la camera (fixee a la construction)
player.gravity = GRAVITY
player.jump_height = JUMP_HEIGHT
player.cursor.visible = False
player.mouse_sensitivity = Vec2(MOUSE_SENSITIVITY, MOUSE_SENSITIVITY)

chunks = {}
silhouette = None
hill = None
path_ended = False

# Le repere fixe au bout du chemin. Une seule entite, jamais dechargee
# (contrairement au decor streame) : elle est loin, donc gratuite tant
# qu'on ne s'en approche pas, et c'est la seule chose de la foret garantie
# d'etre encore la quand on l'atteint.
path_end_marker = make_path_end_marker(*PATH_END)

# Halo de lumiere au sol, sous le joueur, quand la torche est allumee.
# Parente au joueur (qui ne tourne qu'en Y) : un disque est symetrique en Y,
# pas besoin de le repositionner/reorienter a la main chaque frame.
HALO_RADIUS = 4.2
HALO_TINT = (255, 185, 110)
HALO_MAX_ALPHA = 100
torch_halo = Entity(
    parent=player,
    model="circle",
    rotation_x=90,
    y=0.03,                      # legerement au-dessus du sol, evite le z-fighting
    scale=HALO_RADIUS * 2,
    color=color.rgba32(*HALO_TINT, 0),
    unlit=True,
    double_sided=True,           # visible quel que soit le sens de la rotation
)

whisper = Text(text="", origin=(0, 0), position=(0, -0.32),
               scale=0.9, color=color.rgb32(70, 68, 64))

# Invite de ramassage ("[E] Ramasser : ..."), au-dessus du viseur.
pickup_prompt = Text(text="", origin=(0, 0), position=(0, -0.05),
                      scale=1.15, color=color.rgb32(224, 214, 190))
nearby_pickup = None   # (chunk, entite) le plus proche a portee, ou None


# ----------------------------------------------------------------------
# Barre d'inventaire + coeurs de vie, a la Minecraft.
# En geometrie (quads colores), pas en emoji/glyphes : la police du jeu
# n'a pas ces caracteres et les affiche en carre vide (voir zalgo plus haut).
# ----------------------------------------------------------------------

MAX_HP = 10
HOTBAR_SLOTS = 6
SLOT_SIZE = 0.075
SLOT_GAP = 0.014
HOTBAR_Y = -0.44
HEARTS_Y = -0.375

HEART_FULL = color.rgb32(178, 40, 40)
HEART_EMPTY = color.rgb32(40, 20, 20)
SLOT_BG = color.rgba32(20, 18, 16, 215)
SLOT_BG_EMPTY = color.rgba32(20, 18, 16, 120)
SELECTOR_COLOR = color.rgb32(232, 222, 180)   # cadre du slot selectionne
ITEM_COLORS = {
    "🕯️": color.rgb32(235, 150, 60),   # torche : lueur chaude
}
ITEM_COLOR_DEFAULT = color.rgb32(170, 168, 160)

selected_slot = 0   # slot actif, change a la molette


def _row_x(i, total, size, gap):
    """Position x (UI, -aspect/2..aspect/2 dans les faits geres par ursina)
    du i-eme element d'une rangee centree de `total` elements."""
    width = total * size + (total - 1) * gap
    start = -width / 2 + size / 2
    return start + i * (size + gap)


hearts = [
    Entity(parent=camera.ui, model="quad", scale=0.03,
           position=(_row_x(i, MAX_HP, 0.034, 0.006), HEARTS_Y, -1),
           color=HEART_FULL)
    for i in range(MAX_HP)
]

# Cadre du slot selectionne : un seul quad, repositionne chaque frame,
# affiche juste derriere le fond du slot (donc visible tout autour).
selector = Entity(parent=camera.ui, model="quad", scale=SLOT_SIZE * 1.25,
                   position=(_row_x(0, HOTBAR_SLOTS, SLOT_SIZE, SLOT_GAP), HOTBAR_Y, 0),
                   color=SELECTOR_COLOR)

hotbar_bg = []
hotbar_icon = []
hotbar_count = []
for i in range(HOTBAR_SLOTS):
    sx = _row_x(i, HOTBAR_SLOTS, SLOT_SIZE, SLOT_GAP)
    bg = Entity(parent=camera.ui, model="quad", scale=SLOT_SIZE,
                position=(sx, HOTBAR_Y, -1), color=SLOT_BG_EMPTY)
    icon = Entity(parent=camera.ui, model="quad", scale=SLOT_SIZE * 0.55,
                  position=(sx, HOTBAR_Y, -2), color=ITEM_COLOR_DEFAULT,
                  enabled=False)
    count = Text(parent=camera.ui, text="", origin=(0.5, -0.5), scale=0.65,
                 position=(sx + SLOT_SIZE * 0.34, HOTBAR_Y - SLOT_SIZE * 0.34, -3),
                 color=color.rgb32(225, 222, 212))
    hotbar_bg.append(bg)
    hotbar_icon.append(icon)
    hotbar_count.append(count)


def update_hearts():
    for i, heart in enumerate(hearts):
        heart.color = HEART_FULL if i < state.hp else HEART_EMPTY


def hotbar_items():
    """Inventaire groupe par type d'objet : [(item, quantite), ...],
    dans l'ordre de premiere apparition. Le slot i correspond a items[i]."""
    counts = {}
    order = []
    for item in state.inventory:
        if item not in counts:
            order.append(item)
        counts[item] = counts.get(item, 0) + 1
    return [(item, counts[item]) for item in order]


def update_hotbar():
    items = hotbar_items()

    selector.x = _row_x(selected_slot, HOTBAR_SLOTS, SLOT_SIZE, SLOT_GAP)

    for i in range(HOTBAR_SLOTS):
        if i < len(items):
            item, n = items[i]
            hotbar_bg[i].color = SLOT_BG
            hotbar_icon[i].color = ITEM_COLORS.get(item, ITEM_COLOR_DEFAULT)
            hotbar_icon[i].enabled = True
            hotbar_count[i].text = str(n) if n > 1 else ""
        else:
            hotbar_bg[i].color = SLOT_BG_EMPTY
            hotbar_icon[i].enabled = False
            hotbar_count[i].text = ""


# La police par defaut du jeu (OpenSans) ne connait que 6 des 112 marques
# combinantes de la plage 0x300-0x36F. Les autres s'affichent en carre vide
# ("tofu"). On se limite a celles qu'elle sait vraiment dessiner.
ZALGO_MARKS = [0x0300, 0x0301, 0x0303, 0x0309, 0x030F, 0x0323]


def zalgo(txt, amount):
    """Corruption progressive du texte, pilotee par le malaise."""
    if amount <= 0:
        return txt
    out = []
    for ch in txt:
        out.append(ch)
        if random.random() < amount:
            for _ in range(random.randint(1, 1 + int(amount * 4))):
                out.append(chr(random.choice(ZALGO_MARKS)))
    return "".join(out)


def is_visible(pos, margin=0.15):
    """Le joueur regarde-t-il dans cette direction ?"""
    d = Vec3(pos.x - camera.world_position.x, 0, pos.z - camera.world_position.z)
    dist = math.sqrt(d.x * d.x + d.z * d.z)
    if dist < 0.001:
        return True
    fwd = camera.forward
    flat = math.sqrt(fwd.x * fwd.x + fwd.z * fwd.z) or 1.0
    dot = (d.x / dist) * (fwd.x / flat) + (d.z / dist) * (fwd.z / flat)
    return dot > margin


def view_distance():
    return 3.0 / max(scene.fog_density, 0.001)


# ----------------------------------------------------------------------
# Streaming du monde
# ----------------------------------------------------------------------

def update_chunks():
    pcx = int(round(player.x / CHUNK))
    pcz = int(round(player.z / CHUNK))
    wanted = set()
    for dx in range(-CHUNK_RADIUS, CHUNK_RADIUS + 1):
        for dz in range(-CHUNK_RADIUS, CHUNK_RADIUS + 1):
            wanted.add((pcx + dx, pcz + dz))

    for key in list(chunks):
        if key not in wanted:
            chunks.pop(key).destroy()

    for key in wanted:
        if key not in chunks:
            # Le chemin du retour n'est jamais tout a fait le meme.
            chunks[key] = Chunk(key[0], key[1], state.malaise)


def _push_out_of(entity, radius):
    dx = player.x - entity.x
    dz = player.z - entity.z
    d2 = dx * dx + dz * dz
    if d2 < radius * radius and d2 > 0.0001:
        d = math.sqrt(d2)
        player.x += (dx / d) * (radius - d)
        player.z += (dz / d) * (radius - d)


def _nearby_chunks(radius=1):
    """Chunks autour de celui du joueur (grille (2*radius+1)^2). Utilise
    PARTOUT ou quelque chose est simule chaque frame (collision, torche,
    ramassage, derive du decor) : c'est la SEULE maniere d'atteindre des
    chunks dans tout le fichier - aucune boucle n'a le droit d'iterer
    `chunks` directement.

    `radius` est TOUJOURS borne a COMPUTE_RADIUS (3 chunks par defaut,
    reglable) : meme un appelant qui en demande plus ne l'obtient jamais.
    Limite dure et inconditionnelle, quoi qu'il se passe par ailleurs
    (malaise, torche, densite du decor, exploration...). Avant, plusieurs
    boucles parcouraient TOUS les chunks charges (jusqu'a (2*CHUNK_RADIUS+1)^2,
    25 par defaut) a chaque frame : de plus en plus lourd a mesure que le
    decor (clotures, escaliers...) s'accumulait avec le malaise en
    explorant."""
    radius = min(radius, COMPUTE_RADIUS)
    pcx = round(player.x / CHUNK)
    pcz = round(player.z / CHUNK)
    for dx in range(-radius, radius + 1):
        for dz in range(-radius, radius + 1):
            chunk = chunks.get((pcx + dx, pcz + dz))
            if chunk is not None:
                yield chunk


def collide(dt):
    """Arbres et objets (chaise, escalier, tente, porte, cloture...)
    arretent le joueur. Pas de colliders Ursina dessus (trop instable sur
    du decor streame) : on repousse manuellement, par rayon."""
    for chunk in _nearby_chunks():
        for t in chunk.trees:
            _push_out_of(t, getattr(t, "tree_radius", 0.6))
        for p in chunk.props:
            r = getattr(p, "collide_radius", None)
            if r:
                _push_out_of(p, r)


# ----------------------------------------------------------------------
# Ce qui bouge : uniquement ce qui ne peut pas, et jamais sous les yeux
# ----------------------------------------------------------------------

def shift_geometry():
    """Les arbres derive. Les collines poussent. Toujours dans le dos."""
    moved = 0
    budget = 1 + int(state.malaise * 4)
    # Plafond du nombre d'arbres EXAMINES (pas juste deplaces) par frame :
    # sans ca, une fois la plupart des arbres visibles/hors-zone (donc
    # "continue"), la boucle peut parcourir tout le decor charge en entier
    # chaque frame rien que pour trouver de quoi remplir le budget - de plus
    # en plus couteux a mesure que le nombre d'arbres charges augmente.
    scan_budget = 60
    scanned = 0
    # Limite dure : seuls les chunks a COMPUTE_RADIUS du joueur sont
    # consideres, jamais tout le decor charge (voir _nearby_chunks). La
    # derive du decor veut un peu plus de portee que la collision/lumiere
    # (radius=1 par defaut ailleurs) donc on demande le plafond max
    # autorise explicitement - jamais plus.
    nearby = list(_nearby_chunks(COMPUTE_RADIUS))
    random.shuffle(nearby)
    for chunk in nearby:
        # Copie de la liste : des arbres peuvent en etre retires (destroy)
        # pendant l'iteration.
        for t in list(chunk.trees):
            if moved >= budget or scanned >= scan_budget:
                return
            scanned += 1
            if is_visible(t.position):
                continue
            d = math.dist((t.x, t.z), (player.x, player.z))
            if d > view_distance() * 1.6 or d < 3.0:
                continue
            if random.random() < 0.35:
                t.x += random.uniform(-1.6, 1.6) * (0.4 + state.malaise)
                t.z += random.uniform(-1.6, 1.6) * (0.4 + state.malaise)
                moved += 1
            elif random.random() < 0.05 * state.malaise:
                # Detruit vraiment l'arbre (et son feuillage/ses branches,
                # enfants Panda3D) au lieu de juste le desactiver : sinon il
                # reste a jamais dans chunk.trees, re-parcouru chaque frame
                # par collide()/shift_geometry()/update_torch_light() tant
                # que le chunk est charge, et ca fait de plus en plus de
                # travail (et de lag) au fil de la partie.
                chunk.trees.remove(t)
                destroy_deep(t)
                moved += 1


def grow_hill():
    """Une colline se souleve derriere le joueur. Elle etait la avant, forcement."""
    global hill
    if hill is not None and hill.enabled:
        if not is_visible(hill.position):
            hill.scale_y = min(hill.scale_y + 6 * time.dt, hill.target_h)
        d = math.dist((hill.x, hill.z), (player.x, player.z))
        # Rayon approximatif de son empreinte au sol (sphere aplatie :
        # rayon = moitie de son diametre). Sans collider (trop instable sur
        # du decor streame, comme le reste), elle doit disparaitre avant
        # d'etre atteinte, sinon le joueur marche a travers un decor qui a
        # l'air solide.
        footprint = max(hill.scale_x, hill.scale_z) * 0.5
        if d > 140 or d < footprint + 6.0:
            destroy_deep(hill)
            hill = None
        return
    if random.random() > 0.004 + state.malaise * 0.01:
        return
    a = math.radians(camera.world_rotation_y + random.uniform(120, 240))
    dist = random.uniform(55, 95)
    hill = Entity(
        model="sphere",
        color=color.rgb32(9, 10, 10),
        position=(player.x + math.cos(a) * dist, -6, player.z + math.sin(a) * dist),
        scale=(random.uniform(45, 80), 1, random.uniform(45, 80)),
        unlit=True,
    )
    hill.target_h = random.uniform(14, 26)


def place_silhouette():
    """Une forme, a la limite exacte du brouillard. Elle ne bouge jamais.
    Elle n'existe plus quand on ne la regarde plus. C'etait un arbre."""
    global silhouette
    if silhouette is not None:
        if not is_visible(silhouette.position, margin=0.55):
            destroy_deep(silhouette)
            silhouette = None
        elif math.dist((silhouette.x, silhouette.z), (player.x, player.z)) < 14:
            destroy_deep(silhouette)
            silhouette = None
        return
    if state.malaise < 0.2 or random.random() > 0.002 + state.malaise * 0.006:
        return
    a = math.radians(camera.world_rotation_y + random.uniform(-40, 40))
    dist = view_distance() * random.uniform(0.88, 1.0)
    h = random.uniform(1.9, 2.4) if random.random() > state.malaise * 0.4 else random.uniform(3.4, 8.0)
    silhouette = Entity(
        model="cube",
        color=color.rgb32(3, 3, 4),
        position=(player.x + math.sin(a) * dist, h / 2, player.z + math.cos(a) * dist),
        scale=(0.42, h, 0.42),
        unlit=True,
    )


# ----------------------------------------------------------------------
# Torche, froid, HUD
# ----------------------------------------------------------------------

def light_torch():
    """Utilise l'objet du slot actuellement selectionne dans la barre."""
    items = hotbar_items()
    if selected_slot >= len(items):
        flash("Rien a allumer.")
        return

    item, _ = items[selected_slot]
    if item == "🕯️":
        state.inventory.remove(item)
        state.torch = TORCH_SECONDS
        flash("...")
    else:
        flash("Rien a allumer.")


def flash(txt, seconds=2.5):
    whisper.text = zalgo(txt, state.malaise * 0.35)
    invoke(setattr, whisper, "text", "", delay=seconds)


TORCH_SNUFF_MIN_TIME = 8.0    # secondes garanties depuis l'allumage, jamais d'extinction avant
TORCH_SNUFF_RATE = 0.02       # probabilite d'extinction par seconde ecoulee, apres la fenetre garantie
_marks_lit = False            # dernier etat balaye (voir update_torch)


def update_torch(dt):
    if state.torch > 0:
        state.torch -= dt
        elapsed = TORCH_SECONDS - state.torch
        # Elle peut s'eteindre seule, mais jamais avant TORCH_SNUFF_MIN_TIME,
        # et la probabilite est exprimee par seconde (via dt) plutot que par
        # frame : sinon un framerate eleve la fait s'eteindre bien plus vite
        # qu'un framerate bas, et la torche pouvait mourir en quelques
        # secondes a peine.
        if elapsed > TORCH_SNUFF_MIN_TIME and state.torch > 1.0:
            snuff_chance = TORCH_SNUFF_RATE * (1 + state.malaise) * dt
            if random.random() < snuff_chance:
                state.torch = 0.0
                flash("La flamme s'est couchee.")

    target_fog = FOG_CALM + (FOG_MAX - FOG_CALM) * state.malaise
    if state.torch > 0:
        target_fog = FOG_TORCH
        scene.fog_color = C_FOG_TORCH
        window.color = C_FOG_TORCH
    else:
        scene.fog_color = C_FOG_NIGHT
        window.color = C_FOG_NIGHT
    scene.fog_density += (target_fog - scene.fog_density) * min(dt * 1.5, 1.0)

    # Les marques ne changent d'etat (visible/invisible) qu'au moment ou la
    # torche s'allume ou s'eteint : inutile de reparcourir tous les chunks
    # charges pour ca a chaque frame, seulement sur ce changement-la.
    global _marks_lit
    lit = state.torch > 0
    if lit != _marks_lit:
        _marks_lit = lit
        for chunk in chunks.values():
            for m in chunk.marks:
                m.enabled = lit


TORCH_LIGHT_RADIUS = 9.0                     # portee de la lueur autour du joueur
TORCH_TINT = color.rgb32(255, 185, 110)      # teinte chaude de la flamme
TORCH_LIGHT_STEPS = 14  # quantification du degrade (voir _torch_lit_color)


def _torch_lit_color(base_color, dist):
    """Melange base_color vers TORCH_TINT, d'autant plus fort que dist est
    petit. A distance >= TORCH_LIGHT_RADIUS ou torche eteinte : couleur
    d'origine, inchangee.

    `strength` est arrondi a un petit nombre de paliers fixes (14) plutot
    que laisse continu. Sans ca, chaque entite proche du joueur recoit une
    couleur legerement differente a chaque frame (la distance change en
    permanence), et .color = ... passe par setColorScale() de Panda3D, qui
    met en cache un "etat de rendu" par valeur exacte de couleur - un cache
    interne au moteur, pas une liste Python qu'on controle. Avec une valeur
    quasiment jamais repetee, ce cache grossit sans fin sur toute la duree
    de la partie (au rythme de l'exploration, jamais nettoye a l'arret) :
    ca correspond exactement au ralentissement progressif et irreversible
    observe. En arrondissant, seule une poignee de couleurs (paliers x
    couleurs de base) est jamais produite, et Panda3D les reutilise au lieu
    d'en recreer sans arret."""
    if state.torch <= 0 or dist >= TORCH_LIGHT_RADIUS:
        return base_color
    strength = (1.0 - dist / TORCH_LIGHT_RADIUS) ** 2
    strength = round(strength * TORCH_LIGHT_STEPS) / TORCH_LIGHT_STEPS
    return color.rgba(
        base_color[0] + (TORCH_TINT[0] - base_color[0]) * strength,
        base_color[1] + (TORCH_TINT[1] - base_color[1]) * strength,
        base_color[2] + (TORCH_TINT[2] - base_color[2]) * strength,
        base_color[3],
    )


def _torch_lit_scale(dist):
    """Pendant de _torch_lit_color() pour une entite fusionnee (voir
    make_tree/_lightable_combined) : son maillage garde en dur, par sommet,
    la couleur de chaque partie fondue ensemble, donc entity.color n'est
    plus une couleur de remplacement mais un multiplicateur par-dessus.
    On va ici de blanc neutre (1,1,1,1, aucun changement) vers TORCH_TINT
    (deja exprime en 0-1, voir color.rgb32) au lieu de faire un melange
    absolu comme _torch_lit_color - ca rechauffe l'ensemble du maillage
    en gardant la difference de teinte entre ses parties d'origine."""
    if state.torch <= 0 or dist >= TORCH_LIGHT_RADIUS:
        return color.rgba(1, 1, 1, 1)
    strength = (1.0 - dist / TORCH_LIGHT_RADIUS) ** 2
    strength = round(strength * TORCH_LIGHT_STEPS) / TORCH_LIGHT_STEPS
    return color.rgba(
        1 + (TORCH_TINT[0] - 1) * strength,
        1 + (TORCH_TINT[1] - 1) * strength,
        1 + (TORCH_TINT[2] - 1) * strength,
        1,
    )


# Entites actuellement teintees par la torche. Sert a les eteindre sans
# avoir a reparcourir tout le decor charge : voir update_torch_light().
_lit_entities = []


def _relight(entity, dist):
    base = getattr(entity, "base_color", None)
    if base is None:
        return
    if state.torch > 0 and dist < TORCH_LIGHT_RADIUS:
        if getattr(entity, "combined", False):
            entity.color = _torch_lit_scale(dist)
        else:
            entity.color = _torch_lit_color(base, dist)
        _lit_entities.append(entity)
    # sinon : rien a faire, elle est deja a sa couleur de base (voir
    # _revert_torch_light, qui l'y aura remise si elle l'avait quittee).


def _revert_torch_light():
    for e in _lit_entities:
        base = getattr(e, "base_color", None)
        if base is not None:
            e.color = base
    _lit_entities.clear()


def update_torch_light():
    """Fait 'briller' ce qui est proche du joueur quand la torche est
    allumee : troncs/feuillages, objets, marques (le sol ne l'est pas, voir
    plus bas). Des qu'une entite sort de portee ou que la torche s'eteint,
    elle revient a sa couleur d'origine.

    Ne fait du travail que sur les chunks qui peuvent geometriquement
    contenir un point a moins de TORCH_LIGHT_RADIUS (9m) du joueur - une
    grille 3x3 de chunks de 20m suffit largement - et seulement quand la
    torche est allumee. Avant, on reassignait .color de TOUTES les
    entites de TOUS les chunks charges (jusqu'a 25 par defaut) a CHAQUE
    frame, meme torche eteinte et meme a 50m du joueur : un vrai-faux
    "petit calcul" qui grossissait avec chaque cloture/escalier ajoute au
    decor, et donc avec le malaise - la cause probable du lag qui empire
    en avancant dans la partie."""
    _revert_torch_light()
    if state.torch <= 0:
        return

    # Le sol n'est pas teinte : chaque dalle est une seule grande entite
    # (20x20m), la distance au joueur se mesurerait depuis son centre et
    # donnerait un eclairage par blocs, pas un halo autour du joueur.
    for chunk in _nearby_chunks():
        for t in chunk.trees:
            d = math.dist((t.x, t.z), (player.x, player.z))
            _relight(t, d)
            for c in t.lit_children:
                _relight(c, d)

        for p in chunk.props:
            d = math.dist((p.x, p.z), (player.x, player.z))
            _relight(p, d)
            for c in getattr(p, "lit_children", ()):
                _relight(c, d)

        for m in chunk.marks:
            if m.enabled:
                d = math.dist((m.x, m.z), (player.x, player.z))
                _relight(m, d)


HALO_ALPHA_STEP = 6  # quantification de l'opacite, meme raison que TORCH_LIGHT_STEPS :
                      # sans ca, cette entite recoit une opacite differente a chaque
                      # frame (le scintillement + le fondu), pour toute la duree de la
                      # partie, meme immobile torche allumee - un autre generateur de
                      # couleurs jamais repetees, jamais nettoyees a l'arret.

# Valeur continue (non quantifiee) de l'opacite du halo. HALO_ALPHA_STEP
# quantifie uniquement ce qui est affiche (torch_halo.color), pas l'etat
# qu'on fait evoluer : en relisant l'opacite deja affichee (donc deja
# arrondie) comme "etat actuel" a chaque frame, l'ancienne version bouclait
# sur elle-meme et se figeait sur un palier non nul (6) au lieu de
# descendre jusqu'a 0 - le halo restait visible en permanence apres avoir
# eteint la torche.
_halo_alpha = 0.0


def update_torch_halo(dt):
    """Flaque de lumiere au sol sous le joueur (le sol lui-meme n'est pas
    teinte par update_torch_light, voir sa docstring)."""
    global _halo_alpha
    if state.torch > 0:
        target_a = HALO_MAX_ALPHA + random.uniform(-12, 8)  # leger scintillement
        target_a = clamp(target_a, 0, 255)
    else:
        target_a = 0
    _halo_alpha += (target_a - _halo_alpha) * min(dt * 5.0, 1.0)
    if _halo_alpha < 0.5:  # evite un palier fantome, voir plus haut
        _halo_alpha = 0.0
    displayed = round(_halo_alpha / HALO_ALPHA_STEP) * HALO_ALPHA_STEP
    torch_halo.color = color.rgba32(*HALO_TINT, max(0, min(255, displayed)))


def update_pickups():
    """Cherche l'objet ramassable le plus proche, parmi les chunks
    physiquement proches du joueur seulement (voir _nearby_chunks) : pas
    besoin de scanner tout le decor charge pour un rayon de ramassage de
    1-2m. Met a jour l'invite affichee au-dessus du viseur."""
    global nearby_pickup
    nearby_pickup = None
    best_d = None
    for chunk in _nearby_chunks():
        for p in chunk.props:
            kind = getattr(p, "pickup_kind", None)
            if kind is None:
                continue
            d = math.dist((p.x, p.z), (player.x, player.z))
            if d <= p.pickup_radius and (best_d is None or d < best_d):
                best_d = d
                nearby_pickup = (chunk, p)

    if nearby_pickup is not None:
        pickup_prompt.text = f"[E] Ramasser : {nearby_pickup[1].pickup_label}"
    else:
        pickup_prompt.text = ""


def try_pickup():
    global nearby_pickup
    if nearby_pickup is None:
        return
    chunk, item = nearby_pickup
    state.inventory.append(item.pickup_kind)
    flash(f"Tu ramasses {item.pickup_label}.")
    if item in chunk.props:
        chunk.props.remove(item)
    destroy_deep(item)
    nearby_pickup = None
    pickup_prompt.text = ""


def update_cold(dt):
    if state.malaise < COLD_START or state.torch > 0:
        state.cold_timer = 0.0
        return
    state.cold_timer += dt
    if state.cold_timer >= COLD_PERIOD:
        state.cold_timer = 0.0
        state.hp -= 1
        if state.hp <= 0:
            die()


def _hide_hud():
    for bg in hotbar_bg:
        bg.enabled = False
    for icon in hotbar_icon:
        icon.enabled = False
    for count in hotbar_count:
        count.text = ""
    for heart in hearts:
        heart.enabled = False
    selector.enabled = False
    pickup_prompt.text = ""


def _discard_save():
    try:
        os.remove(sys.argv[1] if len(sys.argv) > 1 else "save.json")
    except OSError:
        pass


def die():
    """Killswitch : la sauvegarde ne survit pas."""
    _discard_save()
    _hide_hud()
    whisper.text = zalgo("Tu es reste trop longtemps.", 0.8)
    player.enabled = False
    invoke(application.quit, delay=4)


def check_path_end():
    """Fin 'sentier' : arrivee au bout du chemin, sans devier."""
    global path_ended
    if path_ended:
        return
    if math.dist((player.x, player.z), PATH_END) < PATH_END_RADIUS:
        end_path()


def end_path():
    global path_ended
    path_ended = True
    _discard_save()
    _hide_hud()
    whisper.text = "Le chemin s'arrete ici.\nTu es alle jusqu'au bout."
    player.enabled = False
    invoke(application.quit, delay=6)


# ----------------------------------------------------------------------
# Boucle
# ----------------------------------------------------------------------

_last_pos = Vec3(0, 0, 0)
_debug_timer = 0.0


def update_debug(dt):
    """Rien a voir avec le jeu : juste un etat des lieux dans la console
    toutes les 5s, pour verifier objectivement ce qui grossit (ou pas) si
    le ralentissement revient. scene.entities est le meilleur indicateur
    d'une vraie fuite d'entites Python/Panda3D (pas juste un cache moteur) :
    s'il reste stable dans le temps, la cause est ailleurs (ex : le cache
    de rendu de Panda3D, voir _torch_lit_color)."""
    global _debug_timer
    _debug_timer += dt
    if _debug_timer < 5.0:
        return
    _debug_timer = 0.0
    print(
        f"[debug] t={state.elapsed:6.0f}s  dist={state.distance:6.0f}m  "
        f"malaise={state.malaise:.2f}  chunks={len(chunks):3d}  "
        f"scene.entities={len(scene.entities):4d}  fps~={1.0 / max(dt, 1e-6):5.0f}"
    )


def update():
    global _last_pos
    dt = time.dt

    # AZERTY + QWERTY
    held_keys["w"] = max(held_keys["w"], held_keys["z"])
    held_keys["a"] = max(held_keys["a"], held_keys["q"])

    moved = math.dist((player.x, player.z), (_last_pos.x, _last_pos.z))
    _last_pos = Vec3(player.position)
    state.distance += moved
    state.elapsed += dt

    # Le malaise ne redescend jamais.
    state.malaise = clamp(state.distance / 900.0 + state.elapsed / 600.0, 0.0, 1.0)

    update_chunks()
    collide(dt)
    shift_geometry()
    grow_hill()
    place_silhouette()
    update_torch(dt)
    update_torch_light()
    update_torch_halo(dt)
    update_cold(dt)
    check_path_end()
    update_pickups()
    update_hearts()
    update_hotbar()
    update_debug(dt)


def input(key):
    global selected_slot
    if key == "l":
        light_torch()
    elif key == "e":
        try_pickup()
    elif key == "scroll up":
        selected_slot = (selected_slot - 1) % HOTBAR_SLOTS
    elif key == "scroll down":
        selected_slot = (selected_slot + 1) % HOTBAR_SLOTS


update_chunks()
app.run()
