import random

ELEMENTS = ["🪑", "🛏️", "📚", "🪞", "🍽️"]

def generer_maison():
    largeur = random.randint(8, 15)
    hauteur = random.randint(6, 10)

    carte = [["⬛" for _ in range(largeur)] for _ in range(hauteur)]

    for y in range(1, hauteur - 1):
        for x in range(1, largeur - 1):
            carte[y][x] = "  "

    entree_x = 0
    entree_y = hauteur // 2
    carte[entree_y][entree_x] = "🚪"

    # Objets décoratifs
    for _ in range(random.randint(3, 6)):
        x = random.randint(2, largeur - 2)
        y = random.randint(1, hauteur - 2)
        if carte[y][x] == "  ":
            carte[y][x] = random.choice(ELEMENTS)

    # Boîtes avec loot possible (📦)
    loot_boxes = {}
    for _ in range(random.randint(1, 3)):
        x = random.randint(2, largeur - 2)
        y = random.randint(1, hauteur - 2)
        if carte[y][x] == "  ":
            carte[y][x] = "📦"
            loot_boxes[(x, y)] = "🕯️" if random.random() < 0.5 else None  # 50% torche

    return carte, entree_x, entree_y, loot_boxes
