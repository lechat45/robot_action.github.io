#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
analyse.py — WORKER D'ANALYSE (lecture seule, ne passe JAMAIS d'ordre).

Usage : python analyse.py univers/actions-1.txt

Chaque worker tourne sur sa propre machine GitHub Actions en parallèle,
analyse la liste de symboles de son fichier, et écrit ses scores dans
resultats/<nom-du-fichier>.json. Le script trader.py agrège ensuite tout.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from alpaca.data.historical import StockHistoricalDataClient, CryptoHistoricalDataClient
from alpaca.data.requests import StockBarsRequest, CryptoBarsRequest
from alpaca.data.timeframe import TimeFrame

from commun import (DOSSIER_RESULTATS, EXCLUSION_RECENTE_J, LOOKBACK_MOMENTUM_J,
                    est_crypto, lire_fichier_univers, log, score_momentum,
                    separateur, verifier_cle_paper)


def recuperer_series(api_key: str, secret: str, actions: list, cryptos: list) -> dict:
    """Récupère les clôtures quotidiennes en UNE requête groupée par type (limite API respectée)."""
    series = {}
    fin_c = datetime.now(timezone.utc)
    debut = fin_c - timedelta(days=LOOKBACK_MOMENTUM_J * 2 + 30)

    if actions:
        client = StockHistoricalDataClient(api_key, secret)
        req = StockBarsRequest(symbol_or_symbols=actions, timeframe=TimeFrame.Day,
                               start=debut, end=fin_c - timedelta(minutes=20))
        df = client.get_stock_bars(req).df
        for s in actions:
            try:
                series[s] = df.xs(s, level="symbol")["close"]
            except KeyError:
                log(f"⚠️  Pas de données pour l'action {s}, ignorée.")

    if cryptos:
        client = CryptoHistoricalDataClient(api_key, secret)
        req = CryptoBarsRequest(symbol_or_symbols=cryptos, timeframe=TimeFrame.Day,
                                start=debut, end=fin_c)
        df = client.get_crypto_bars(req).df
        for s in cryptos:
            try:
                series[s] = df.xs(s, level="symbol")["close"]
            except KeyError:
                log(f"⚠️  Pas de données pour la crypto {s}, ignorée.")

    return series


def main():
    if len(sys.argv) != 2:
        log("Usage : python analyse.py <fichier_univers.txt>")
        sys.exit(1)

    fichier = sys.argv[1]
    nom = Path(fichier).stem
    separateur(f"WORKER D'ANALYSE — {nom} (lecture seule, aucun ordre passé)")

    api_key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret:
        log("❌ ERREUR : ALPACA_API_KEY / ALPACA_SECRET_KEY absentes.")
        sys.exit(1)
    verifier_cle_paper(api_key)

    symboles = lire_fichier_univers(fichier)
    actions = [s for s in symboles if not est_crypto(s)]
    cryptos = [s for s in symboles if est_crypto(s)]
    log(f"Univers de ce worker : {len(actions)} actions + {len(cryptos)} cryptos = {len(symboles)} actifs")

    series = recuperer_series(api_key, secret, actions, cryptos)

    scores = []
    for symbole, prix in series.items():
        res = score_momentum(prix)
        if res is None:
            log(f"   {symbole:<10} historique insuffisant, ignoré.")
            continue
        res["symbole"] = symbole
        res["crypto"] = est_crypto(symbole)
        scores.append(res)
        log(f"   {symbole:<10} momentum {res['momentum'] * 100:+7.2f}% | "
            f"vol {res['vol_annualisee'] * 100:5.1f}% | score {res['score']:+.3f} | "
            f"RSI {res['rsi']:5.1f} | prix {res['dernier_prix']:.2f}")

    Path(DOSSIER_RESULTATS).mkdir(exist_ok=True)
    sortie = Path(DOSSIER_RESULTATS) / f"{nom}.json"
    with open(sortie, "w", encoding="utf-8") as f:
        json.dump({
            "worker": nom,
            "horodatage": datetime.now(timezone.utc).isoformat(),
            "nb_analyses": len(scores),
            "scores": scores,
        }, f, ensure_ascii=False, indent=2)

    log(f"✅ {len(scores)} scores écrits dans {sortie}")


if __name__ == "__main__":
    main()
