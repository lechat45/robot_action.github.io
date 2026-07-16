#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
commun.py — configuration et indicateurs partagés entre analyse.py et trader.py.
Toutes les stratégies viennent du document de référence (momentum §3, mean reversion §4,
volatility targeting + risk management, section finale).
"""

import math
import sys
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ============================== PARAMÈTRES ==============================

LOOKBACK_MOMENTUM_J   = 60      # fenêtre de momentum (jours)
EXCLUSION_RECENTE_J   = 5       # exclusion des derniers jours (bruit court terme)
FENETRE_VOL_J         = 20      # fenêtre de volatilité réalisée
FENETRE_RSI           = 14
RSI_SURACHAT          = 75.0    # filtre : pas d'achat en surachat extrême

NB_MAX_POSITIONS      = 8       # diversification globale
PART_MAX_PAR_ACTIF    = 0.12    # max 12% du portefeuille par actif
VOL_CIBLE_ANNUALISEE  = 0.20    # volatility targeting
STOP_LOSS_PCT         = -0.07   # stop-loss par position
LIMITE_PERTE_JOUR_PCT = -0.03   # kill switch quotidien
SCORE_MINIMUM         = 0.0     # momentum positif requis

PAPER = True  # NE JAMAIS PASSER À False : argent virtuel uniquement

DOSSIER_RESULTATS = "resultats"


def log(msg: str):
    print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC] {msg}", flush=True)


def separateur(titre: str):
    print("\n" + "=" * 70, flush=True)
    print(f"  {titre}", flush=True)
    print("=" * 70, flush=True)


def verifier_cle_paper(api_key: str):
    """
    SÉCURITÉ : les clés PAPER d'Alpaca commencent par « PK », les clés RÉELLES
    par « AK ». Ce garde-fou refuse toute clé qui n'est pas une clé paper,
    rendant impossible un trade en argent réel même par erreur de configuration.
    """
    if not api_key.startswith("PK"):
        log("❌ SÉCURITÉ : la clé fournie ne ressemble pas à une clé PAPER "
            "(elle doit commencer par « PK »). Arrêt immédiat — ce bot refuse "
            "de fonctionner avec une clé de compte réel.")
        sys.exit(1)


def masquer(valeur: str) -> str:
    """Masque un identifiant dans les logs (les logs d'un repo public sont publics)."""
    v = str(valeur)
    return "****" + v[-4:] if len(v) > 4 else "****"


def lire_fichier_univers(chemin: str) -> list:
    """Lit un fichier de symboles : un par ligne, lignes vides et # commentaires ignorés."""
    symboles = []
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            s = ligne.split("#")[0].strip().upper()
            if s:
                symboles.append(s)
    return symboles


def est_crypto(symbole: str) -> bool:
    """Les cryptos s'écrivent avec un slash : BTC/USD. Les actions sans : AAPL."""
    return "/" in symbole


# ============================== INDICATEURS ==============================

def rsi(prix: pd.Series, n: int = FENETRE_RSI) -> float:
    delta = prix.diff()
    gains = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    pertes = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = gains / pertes.replace(0, np.nan)
    r = 100 - 100 / (1 + rs)
    return float(r.iloc[-1]) if not math.isnan(r.iloc[-1]) else 50.0


def score_momentum(prix: pd.Series) -> dict | None:
    """Momentum ajusté du risque : Score = Mom / vol_réalisée (doc §3.3)."""
    if len(prix) < LOOKBACK_MOMENTUM_J + EXCLUSION_RECENTE_J + 5:
        return None
    p_fin = prix.iloc[-(EXCLUSION_RECENTE_J + 1)]
    p_debut = prix.iloc[-(LOOKBACK_MOMENTUM_J + EXCLUSION_RECENTE_J + 1)]
    mom = p_fin / p_debut - 1
    rend = prix.pct_change().dropna()
    vol_ann = float(rend.tail(FENETRE_VOL_J).std() * math.sqrt(252))
    if vol_ann <= 0 or math.isnan(vol_ann):
        return None
    return {
        "momentum": float(mom),
        "vol_annualisee": vol_ann,
        "score": float(mom) / vol_ann,
        "rsi": rsi(prix),
        "dernier_prix": float(prix.iloc[-1]),
    }


def taille_position(equity: float, vol_annualisee: float) -> float:
    """Volatility targeting : notionnel plafonné, inversement proportionnel à la vol."""
    facteur = min(1.0, VOL_CIBLE_ANNUALISEE / vol_annualisee)
    return round(equity * PART_MAX_PAR_ACTIF * facteur, 2)
