import random

def generer_foret(largeur, hauteur, nb_maisons):
    carte = [["🌳" if random.random() < 0.5 else "🌲" if random.random() < 0.8 else "  "
              for _ in range(largeur)] for _ in range(hauteur)]
    
    sentier_y = hauteur // 2
    sentier_pos = []
    for x in range(largeur):
        carte[sentier_y][x] = "🟫"
        sentier_pos.append((x, sentier_y))
        if random.random() < 0.3 and sentier_y > 1:
            sentier_y -= 1
            carte[sentier_y][x] = "🟫"
            sentier_pos.append((x, sentier_y))
        elif random.random() > 0.7 and sentier_y < hauteur - 2:
            sentier_y += 1
            carte[sentier_y][x] = "🟫"
            sentier_pos.append((x, sentier_y))

    maisons = []
    for _ in range(nb_maisons):
        while True:
            x = random.randint(5, largeur - 5)
            y = random.randint(1, hauteur - 2)
            if carte[y][x] not in ["🟫", "🏚️"]:
                carte[y][x] = "🏚️"
                maisons.append((x, y))
                break

    for mx, my in maisons:
        cx, cy = min(sentier_pos, key=lambda p: abs(p[0] - mx) + abs(p[1] - my))
        tracer_chemin(carte, mx, my, cx, cy)

    return carte, maisons

def tracer_chemin(carte, x1, y1, x2, y2):
    x, y = x1, y1
    while x != x2:
        x += 1 if x2 > x else -1
        if carte[y][x] not in ["🏚️"]:
            carte[y][x] = "🟫"
    while y != y2:
        y += 1 if y2 > y else -1
        if carte[y][x] not in ["🏚️"]:
            carte[y][x] = "🟫"
