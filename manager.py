import json
import os
import random
import subprocess
import sys
import time
from forest import generer_foret
from house import generer_maison

LARGEUR = 40
HAUTEUR = 15
NB_MAISONS = 4

etat = "foret"
carte, maisons = generer_foret(LARGEUR, HAUTEUR, NB_MAISONS)
player_x, player_y = 0, HAUTEUR // 2

carte_maison, entree_x, entree_y = None, None, None
loot_boxes = {}  # Coordonnées des boîtes dans la maison
last_house_pos = None

move_counter = 0
hp = 10
inventory = []
torch_duration = 0

# Affichage
def afficher(carte, vision_limitee=False, rayon=2, message=None, hp=None, inventory=None, extra_message=None):
    os.system('cls' if os.name == 'nt' else 'clear')

    if message:
        print(message)
    if extra_message:
        print(extra_message)
    print()

    for y, ligne in enumerate(carte):
        row = ""
        for x, char in enumerate(ligne):
            if (x, y) == (player_x, player_y):
                row += "🧍"
            elif vision_limitee and (abs(x - player_x) > rayon or abs(y - player_y) > rayon):
                row += "⬛"
            else:
                row += char
        print(row)

    inv_text = " ".join(inventory) if inventory else "empty"
    print(f"\n❤️ HP: {hp}/10     🧺 Inventory: {inv_text}")

# Déplacement possible ?
def est_valide(carte, x, y):
    if 0 <= x < len(carte[0]) and 0 <= y < len(carte):
        return carte[y][x] in ["🟫", "🏚️", "🚪", "  ", "📦"]
    return False

# Passage a la phase 3D
def lancer_3d():
    with open("save.json", "w", encoding="utf-8") as f:
        json.dump({"hp": hp, "inventory": inventory}, f, ensure_ascii=False)

    os.system('cls' if os.name == 'nt' else 'clear')
    for ligne in ["...", "The path ends here.", "But the forest doesn't."]:
        print(ligne)
        time.sleep(1.8)

    subprocess.run([sys.executable, "forest3d.py", "save.json"])

# Mode test : python manager.py --skip (ou -s) saute directement la 2D
# et lance la 3D. Par defaut : 10 HP, inventaire vide.
# --torch (ou -t), repetable, ajoute une torche par occurrence.
# --torch=N ajoute N torches d'un coup. On peut cumuler les deux.
if "--skip" in sys.argv or "-s" in sys.argv:
    for arg in sys.argv:
        if arg in ("--torch", "-t"):
            inventory.append("🕯️")
        elif arg.startswith("--torch="):
            try:
                n = int(arg.split("=", 1)[1])
            except ValueError:
                n = 0
            inventory.extend(["🕯️"] * max(0, n))
    lancer_3d()
    sys.exit(0)

# Boucle principale
while True:
    extra_msg = None
    torch_active = torch_duration > 0
    rayon = 10

    # === FORÊT ===
    if etat == "foret":
        if torch_active:
            torch_duration -= 1
            msg = "🕯️ Your torch lights the way..."
            rayon = 5
        elif move_counter < 10:
            msg = "🌕 The moon is shining..."
            rayon = 10
        elif move_counter < 20:
            msg = "🌖 The moon shines less brightly..."
            rayon = 4
        elif move_counter < 30:
            msg = "🌘 The moon shines less and less..."
            rayon = 2
        else:
            msg = "🌑 Everything is dark..."
            extra_msg = "❄️  It's freezing out there..."
            rayon = 1

            if not torch_active:
                hp -= 1
                if hp <= 0:
                    afficher(carte, vision_limitee=True, rayon=1, message=msg, extra_message=extra_msg, hp=0, inventory=inventory)
                    print("\n💀 You froze to death...\n")
                    break

        afficher(carte, vision_limitee=(rayon < 10), rayon=rayon, message=msg, extra_message=extra_msg, hp=hp, inventory=inventory)

    # === MAISON ===
    else:
        afficher(carte_maison, vision_limitee=True, rayon=2, hp=hp, inventory=inventory)

    move = input("\nDéplacement : (Z/W) haut, (S) bas, (Q/A) gauche, (D) droite — (L) allumer une torche : ").lower()
    new_x, new_y = player_x, player_y

    if move in ("z", "w"): new_y -= 1
    elif move == "s": new_y += 1
    elif move in ("q", "a"): new_x -= 1
    elif move == "d": new_x += 1
    elif move == "l":
        if "🕯️" in inventory:
            inventory.remove("🕯️")
            torch_duration = 10
            print("\n🔥 You light a torch. It will last for 10 turns.")
        else:
            print("\n❌ You don't have a torch to light.")
        input("Press enter to continue...")
        continue

    current_carte = carte if etat == "foret" else carte_maison

    if est_valide(current_carte, new_x, new_y):
        player_x, player_y = new_x, new_y

        if etat == "foret":
            move_counter += 1

        # Fin du sentier : bascule en 3D
        if etat == "foret" and player_x >= LARGEUR - 1:
            lancer_3d()
            break

        # Entrer dans une maison
        if etat == "foret" and current_carte[player_y][player_x] == "🏚️":
            etat = "maison"
            carte_maison, entree_x, entree_y, loot_boxes = generer_maison()
            last_house_pos = (player_x, player_y)
            player_x, player_y = entree_x, entree_y

        # Ouvrir une boîte dans la maison
        if etat == "maison" and (player_x, player_y) in loot_boxes:
            contenu = loot_boxes.pop((player_x, player_y))
            if contenu == "🕯️":
                print("\n🎁 You found a torch in the box!")
                inventory.append("🕯️")
            else:
                print("\n📦 The box was empty... or useless.")
            carte_maison[player_y][player_x] = "  "
            input("Press enter to continue...")

        # Sortir de la maison
        elif etat == "maison" and current_carte[player_y][player_x] == "🚪":
            etat = "foret"
            player_x, player_y = last_house_pos
