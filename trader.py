#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trader.py — CHEF D'ORCHESTRE. Le SEUL script autorisé à passer des ordres.

Il lit tous les JSON produits par les workers dans resultats/, fusionne le
classement global, applique les filtres et le risk management, puis rebalance
le portefeuille PAPER Alpaca (argent virtuel).
"""

import json
import os
import sys
from pathlib import Path

from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

from commun import (DOSSIER_RESULTATS, LIMITE_PERTE_JOUR_PCT, NB_MAX_POSITIONS, PAPER,
                    RSI_SURACHAT, SCORE_MINIMUM, STOP_LOSS_PCT, log, masquer,
                    separateur, taille_position, verifier_cle_paper)


def charger_resultats() -> list:
    """Fusionne les scores de tous les workers (fichiers resultats/*.json)."""
    dossier = Path(DOSSIER_RESULTATS)
    fichiers = sorted(dossier.glob("**/*.json"))
    if not fichiers:
        log(f"❌ Aucun résultat trouvé dans {dossier}/ — les workers ont-ils tourné ?")
        sys.exit(1)
    scores, vus = [], set()
    for f in fichiers:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        log(f"   Worker « {data['worker']} » : {data['nb_analyses']} actifs analysés "
            f"({data['horodatage'][:16]})")
        for s in data["scores"]:
            if s["symbole"] not in vus:  # dédoublonnage si un symbole est dans 2 fichiers
                vus.add(s["symbole"])
                scores.append(s)
    return scores


def verifier_kill_switch(trading: TradingClient) -> bool:
    compte = trading.get_account()
    equity, veille = float(compte.equity), float(compte.last_equity)
    if veille <= 0:
        return False
    perf = equity / veille - 1
    log(f"Performance du jour : {perf * 100:+.2f}% (limite : {LIMITE_PERTE_JOUR_PCT * 100:.0f}%)")
    if perf <= LIMITE_PERTE_JOUR_PCT:
        log("🛑 KILL SWITCH — perte quotidienne dépassée. Liquidation totale et arrêt.")
        trading.close_all_positions(cancel_orders=True)
        return True
    return False


def appliquer_stop_loss(trading: TradingClient):
    for pos in trading.get_all_positions():
        pnl = float(pos.unrealized_plpc)
        if pnl <= STOP_LOSS_PCT:
            log(f"🛑 STOP-LOSS {pos.symbol} : {pnl * 100:+.2f}% -> fermeture.")
            trading.close_position(pos.symbol)
        else:
            log(f"   {pos.symbol:<10} PnL latent {pnl * 100:+.2f}% (OK)")


def main():
    separateur("CHEF D'ORCHESTRE — AGRÉGATION + TRADING (mode PAPER, argent virtuel)")

    api_key = os.environ.get("ALPACA_API_KEY")
    secret = os.environ.get("ALPACA_SECRET_KEY")
    if not api_key or not secret:
        log("❌ ERREUR : ALPACA_API_KEY / ALPACA_SECRET_KEY absentes.")
        sys.exit(1)
    verifier_cle_paper(api_key)

    trading = TradingClient(api_key, secret, paper=PAPER)
    compte = trading.get_account()
    equity = float(compte.equity)
    log(f"✅ Compte PAPER n° {masquer(compte.account_number)} | Equity ${equity:,.2f} | "
        f"Cash ${float(compte.cash):,.2f}")

    # --- 1. Agrégation des workers ---
    separateur("1/5 — AGRÉGATION DES RÉSULTATS DES WORKERS")
    scores = charger_resultats()
    log(f"→ Classement global : {len(scores)} actifs uniques analysés en parallèle.")

    # --- 2. Kill switch ---
    separateur("2/5 — RISQUE : KILL SWITCH QUOTIDIEN")
    if verifier_kill_switch(trading):
        return

    # --- 3. Stop-loss ---
    separateur("3/5 — RISQUE : STOP-LOSS PAR POSITION")
    if trading.get_all_positions():
        appliquer_stop_loss(trading)
    else:
        log("Aucune position ouverte.")

    # --- 4. Sélection ---
    separateur("4/5 — SÉLECTION DU PORTEFEUILLE CIBLE")
    marche_ouvert = trading.get_clock().is_open
    log(f"Marché actions US : {'OUVERT' if marche_ouvert else 'FERMÉ'} (crypto : 24/7)")

    classement = sorted(scores, key=lambda r: r["score"], reverse=True)
    cibles = []
    for r in classement:
        if len(cibles) >= NB_MAX_POSITIONS:
            break
        if r["score"] <= SCORE_MINIMUM:
            continue
        if r["rsi"] >= RSI_SURACHAT:
            log(f"   ⚠️  {r['symbole']} écarté : RSI {r['rsi']:.1f} en surachat extrême.")
            continue
        if not r["crypto"] and not marche_ouvert:
            log(f"   ⏸  {r['symbole']} écarté ce cycle : marché actions fermé.")
            continue
        cibles.append(r)

    if cibles:
        log(f"Cible ({len(cibles)}/{NB_MAX_POSITIONS}) : " + ", ".join(c["symbole"] for c in cibles))
    else:
        log("Aucun actif ne passe les filtres — on reste en cash ce cycle.")

    symboles_cibles = {c["symbole"].replace("/", "") for c in cibles}

    # --- 5. Rebalancement ---
    separateur("5/5 — REBALANCEMENT")
    for pos in trading.get_all_positions():
        if pos.symbol not in symboles_cibles:
            log(f"   VENTE {pos.symbol} (sorti du classement) — ${float(pos.market_value):,.2f}")
            try:
                trading.close_position(pos.symbol)
            except Exception as e:
                log(f"   ⚠️  Échec vente {pos.symbol} : {e}")

    detenus = {p.symbol for p in trading.get_all_positions()}
    for c in cibles:
        sym = c["symbole"]
        if sym.replace("/", "") in detenus:
            log(f"   {sym} déjà en portefeuille, conservé.")
            continue
        notionnel = taille_position(equity, c["vol_annualisee"])
        if notionnel < 10:
            continue
        try:
            ordre = MarketOrderRequest(
                symbol=sym, notional=notionnel, side=OrderSide.BUY,
                time_in_force=TimeInForce.GTC if c["crypto"] else TimeInForce.DAY,
            )
            r = trading.submit_order(ordre)
            log(f"   ✅ ACHAT {sym} pour ${notionnel:,.2f} "
                f"(vol {c['vol_annualisee'] * 100:.1f}%) — ordre {r.id}")
        except Exception as e:
            log(f"   ⚠️  Échec achat {sym} : {e}")

    # --- Résumé ---
    separateur("RÉSUMÉ DU CYCLE")
    compte = trading.get_account()
    log(f"Equity finale : ${float(compte.equity):,.2f} | Cash : ${float(compte.cash):,.2f}")
    for pos in trading.get_all_positions():
        log(f"   {pos.symbol:<10} valeur ${float(pos.market_value):,.2f} | "
            f"PnL {float(pos.unrealized_plpc) * 100:+.2f}%")
    log("Suivi visuel : https://app.alpaca.markets/paper/dashboard/overview")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"❌ ERREUR FATALE : {e}")
        sys.exit(1)
