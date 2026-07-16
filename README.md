# Bot de trading parallèle — Alpaca Paper Trading

Architecture distribuée sur GitHub Actions (100% gratuit, repo public) :
plusieurs **workers d'analyse** tournent **en parallèle** sur des machines
séparées, puis un **chef d'orchestre** unique agrège tout et passe les ordres
sur le compte **paper** Alpaca (argent virtuel uniquement).

```
univers/actions-1.txt ──► worker 1 (machine 1) ──► resultats/actions-1.json ─┐
univers/actions-2.txt ──► worker 2 (machine 2) ──► resultats/actions-2.json ─┼─► trader.py
univers/crypto-1.txt  ──► worker 3 (machine 3) ──► resultats/crypto-1.json ──┘   (seul à trader)
```

## ➕ Ajouter des actions ou des cryptos (LE point important)

**Ajouter un actif** → ouvre un fichier dans `univers/` et ajoute une ligne :
```
NVDA          ← une action : juste le ticker
BTC/USD       ← une crypto : toujours avec /USD
# ceci est un commentaire, ignoré
```

**Ajouter un worker parallèle entier** → crée simplement un nouveau fichier,
par exemple `univers/actions-3.txt` avec tes tickers dedans. C'est tout :
le workflow détecte automatiquement les fichiers et lance une machine par
fichier. **Aucune modification de code ni de workflow.**

Conseil : ~10 à 30 actifs par fichier, et crée un nouveau fichier au-delà,
pour garder des workers rapides et rester loin des limites de l'API Alpaca.

## Rôles des fichiers

| Fichier | Rôle |
|---|---|
| `univers/*.txt` | Listes d'actifs — 1 fichier = 1 worker parallèle |
| `commun.py` | Paramètres + indicateurs (momentum, RSI, sizing) |
| `analyse.py` | Worker : analyse, **lecture seule**, écrit un JSON |
| `trader.py` | Chef d'orchestre : agrège, risk management, **seul à passer des ordres** |
| `.github/workflows/trading.yml` | Orchestration (matrix dynamique) |

## Stratégies (document de référence)

Momentum cross-sectionnel ajusté du risque (§3) sur l'univers global fusionné,
filtre RSI anti-surachat (§4), volatility targeting pour le sizing, stop-loss
-7% par position, kill switch -3%/jour, max 8 positions, max 12% par actif.

## Déploiement (0 €)

1. Compte Alpaca gratuit → clés **Paper Trading**.
2. Repo GitHub **public** avec ces fichiers.
3. Settings → Secrets and variables → Actions : `ALPACA_API_KEY` et `ALPACA_SECRET_KEY`.
4. Le bot tourne toutes les 30 min. Logs : onglet **Actions** (chaque worker a
   sa console, et le job « trading » montre l'agrégation + les ordres).

## En local

```bash
pip install -r requirements.txt
export ALPACA_API_KEY="..." ALPACA_SECRET_KEY="..."
python analyse.py univers/actions-1.txt
python analyse.py univers/crypto-1.txt
python trader.py
```

⚠️ Pédagogique. `PAPER = True` dans `commun.py` ne doit **jamais** passer à `False`.
