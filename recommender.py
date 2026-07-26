"""
Moteur de recommandation — évolution prévue :

Niveau 1 (actuel) : SQL scoring     → déjà dans routes/recommendations.py
Niveau 2 (50+ users)  : TF-IDF      → similarité textuelle entre annonces
Niveau 3 (500+ users) : Collaborative filtering → "les gens comme toi aiment ça"

Ce fichier sera enrichi à chaque niveau.
"""


def score_listing(views: int, favorites: int, days_old: int) -> float:
    """
    Score simple de pertinence d'une annonce.
    Plus elle est récente, vue et mise en favori → meilleur score.

    Formule :
    - vues comptent 1 point chacune
    - favoris comptent 3 points chacun (intention plus forte)
    - ancienneté réduit le score (divise par racine des jours)
    """
    import math
    raw_score = views + (favorites * 3)
    age_penalty = math.sqrt(max(days_old, 1))
    return raw_score / age_penalty