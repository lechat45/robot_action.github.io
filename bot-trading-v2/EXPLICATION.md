# EXPLICATION — Comment tout fonctionne

Ce fichier explique **tout** : ce que fait le bot, comment il décide, comment les
fichiers s'articulent, comment GitHub Actions l'exécute gratuitement, et l'audit
de sécurité complet.

---

## 1. C'est quoi, ce projet ?

Un bot d'investissement automatique qui analyse **des actions et des cryptos en
parallèle**, sélectionne les meilleures selon des stratégies quantitatives
professionnelles, et achète/vend sur un compte **Alpaca PAPER** — c'est-à-dire
avec **de l'argent 100% virtuel** (~100 000 $ fictifs). Aucun euro réel n'est
jamais en jeu. Il n'a **aucune interface** : tout s'écrit dans la console
(les logs GitHub Actions), et le suivi visuel se fait sur le dashboard d'Alpaca :
https://app.alpaca.markets/paper/dashboard/overview

---

## 2. L'architecture : des workers + un chef d'orchestre

```
                    ┌── univers/actions-1.txt ──► WORKER 1 ──► actions-1.json ──┐
GitHub Actions ─────┼── univers/actions-2.txt ──► WORKER 2 ──► actions-2.json ──┼──► TRADER
(toutes les 30 min) └── univers/crypto-1.txt  ──► WORKER 3 ──► crypto-1.json ───┘   (le seul
                        (chaque worker = sa propre machine, en parallèle)            qui trade)
```

- **Les workers (`analyse.py`)** : chacun reçoit UN fichier d'univers, télécharge
  les prix, calcule les scores, et écrit un JSON. Ils sont en **lecture seule** :
  un worker ne peut PAS passer d'ordre. Comme ils tournent en parallèle sur des
  machines séparées, on peut analyser des centaines d'actifs sans ralentir.
- **Le chef d'orchestre (`trader.py`)** : il attend que TOUS les workers aient
  fini, fusionne leurs classements en un classement global, applique la gestion
  des risques, et passe les ordres. C'est le **seul** script qui trade — donc
  aucun conflit possible sur le compte, même avec 50 workers.

## 3. Le rôle de chaque fichier

| Fichier | Rôle |
|---|---|
| `univers/*.txt` | Les listes d'actifs. **1 fichier = 1 worker parallèle.** Un ticker par ligne (`NVDA` = action, `BTC/USD` = crypto), `#` = commentaire. |
| `commun.py` | Les paramètres (fenêtres, seuils, limites de risque) et les fonctions partagées (momentum, RSI, sizing, garde-fous de sécurité). |
| `analyse.py` | Le worker : lit son fichier d'univers, calcule les scores, écrit `resultats/<nom>.json`. Lecture seule. |
| `trader.py` | Le chef d'orchestre : agrège les JSON, kill switch, stop-loss, sélection, ordres, résumé. |
| `.github/workflows/trading.yml` | L'orchestration : détecte les fichiers d'univers, lance un worker par fichier, puis le trader. |
| `requirements.txt` | Les dépendances Python, versions épinglées. |

## 4. Comment le bot décide (les stratégies)

Tout vient du document de référence sur le trading quantitatif institutionnel :

1. **Momentum ajusté du risque** (stratégie 3 du doc) — pour chaque actif :
   `Score = (rendement sur 60 jours, en excluant les 5 derniers) / volatilité réalisée`.
   On exclut les derniers jours car le très court terme a tendance à revenir en
   arrière (bruit). Diviser par la volatilité évite de favoriser les actifs qui
   montent juste parce qu'ils bougent énormément. Tous les actifs de tous les
   workers sont ensuite classés ensemble, du meilleur au pire score.
2. **Filtre RSI anti-surachat** (stratégie 4) — même avec un super momentum, si
   le RSI ≥ 75 (surachat extrême), on n'achète pas : le prix a de fortes chances
   de corriger à court terme.
3. **Volatility targeting** (stratégie 3 + section risk management) — la taille
   de chaque position est **inversement proportionnelle à la volatilité** de
   l'actif : plus c'est risqué (ex. DOGE), plus la position est petite, pour que
   chaque ligne contribue à peu près autant au risque total.
4. **Gestion des risques** (section finale du doc) :
   - **Stop-loss -7%** par position : une position qui perd 7% est fermée.
   - **Kill switch -3%/jour** : si le portefeuille perd 3% dans la journée,
     TOUT est liquidé et le bot s'arrête jusqu'au lendemain.
   - **Max 8 positions**, **max 12% du portefeuille par actif** : diversification.
   - **Momentum positif exigé** : si rien n'est attractif, le bot reste en cash.

## 5. Le déroulement d'un cycle (toutes les 30 min)

1. **Job « preparer »** : liste `univers/*.txt` et fabrique la « matrix ».
   C'est pour ça qu'ajouter un fichier suffit à créer un worker — rien à coder.
2. **Job « analyse » ×N** : un par fichier, en parallèle. Chaque console montre
   les scores de son univers. Les JSON sont publiés comme artefacts (gardés 1 jour).
3. **Job « trading »** : télécharge tous les artefacts, fusionne (avec
   dédoublonnage si un ticker apparaît dans deux fichiers), applique les étapes
   1→5 (agrégation, kill switch, stop-loss, sélection, rebalancement) et affiche
   le résumé final : equity, positions, PnL.

Pour tout voir : onglet **Actions** du repo → clique sur une exécution → chaque
job a sa console. Le bot peut aussi tourner en local (voir README).

## 6. Ajouter des actifs (rappel)

- **Ajouter un actif** : ouvre un fichier de `univers/`, ajoute une ligne.
- **Ajouter un worker** : crée un nouveau fichier `univers/mon-fichier.txt`.
- Conseil : 10 à 30 actifs par fichier.

---

## 7. AUDIT DE SÉCURITÉ

Le code est déployé sur un **repo public** (nécessaire pour les minutes GitHub
Actions gratuites illimitées). Conséquence : **le code ET les logs sont visibles
par tout le monde**. L'audit ci-dessous couvre chaque risque et sa protection.

### ✅ Failles vérifiées et corrigées

| # | Risque | Protection en place |
|---|---|---|
| 1 | **Fuite des clés API** | Les clés ne sont JAMAIS dans le code : elles vivent dans GitHub **Secrets** (chiffrés, invisibles même pour toi une fois enregistrés). GitHub masque automatiquement toute valeur de secret qui apparaîtrait dans un log (`***`). Aucun script n'affiche les clés. |
| 2 | **Trader en argent réel par accident** | Triple verrou : (a) `PAPER = True` codé en dur dans `commun.py`, (b) connexion forcée à l'endpoint paper d'Alpaca, (c) **garde-fou `verifier_cle_paper()`** : les clés paper d'Alpaca commencent par `PK`, les clés réelles par `AK` — le bot **refuse de démarrer** si la clé ne commence pas par `PK`, même si quelqu'un mettait une clé réelle dans les Secrets. |
| 3 | **Deux exécutions en même temps → ordres en double** | Bloc `concurrency` dans le workflow : si un cycle est encore en cours quand le suivant démarre (cron + lancement manuel par exemple), le second attend. Jamais deux traders simultanés. |
| 4 | **Injection de commande shell** | Les noms de fichiers de la matrix passent par des **variables d'environnement** (`$FICHIER_UNIVERS`) et jamais par interpolation directe dans le shell — un nom de fichier piégé ne peut pas exécuter de commande. |
| 5 | **Token GitHub trop puissant** | `permissions: contents: read` : le token automatique du workflow ne peut QUE lire le code. Même compromis, il ne peut rien écrire, ni toucher aux Secrets ni aux autres repos. |
| 6 | **Attaque via pull request** | Le workflow ne se déclenche QUE sur `schedule` et `workflow_dispatch`. Une pull request d'un inconnu ne déclenche rien, et de toute façon GitHub ne donne pas les Secrets aux PR venant de forks. Seul quelqu'un avec accès en écriture au repo peut modifier le code exécuté. |
| 7 | **Dépendances piégées (supply chain)** | Versions **épinglées** (`==`) dans `requirements.txt` : pas de mise à jour automatique silencieuse d'une bibliothèque. Actions officielles GitHub (`actions/checkout`, etc.) uniquement. |
| 8 | **Infos sensibles dans les logs publics** | Le numéro de compte est **masqué** (`****1234`). Les artefacts JSON ne contiennent que des scores calculés sur des prix publics. L'equity affichée est de l'argent virtuel — aucune donnée personnelle nulle part. |
| 9 | **Bot devenu fou (bug, données aberrantes)** | Kill switch -3%/jour, stop-loss par position, plafond par actif, nombre max de positions, `timeout-minutes: 10` sur chaque job (un script bloqué est tué), et `fail-fast: false` (un worker en panne n'empêche pas les autres). |
| 10 | **Perte de contrôle** | Tu peux tout arrêter en 2 clics : onglet Actions → « Disable workflow », ou révoquer les clés dans Alpaca. Les artefacts expirent en 1 jour. |

### ⚠️ Points de vigilance (à savoir, pas des failles du code)

- **Ne partage JAMAIS tes clés**, même paper, dans un chat, un commit ou une
  capture d'écran. Si ça arrive : régénère-les immédiatement dans Alpaca.
- **Protège ton compte GitHub** (mot de passe fort + 2FA) : quelqu'un qui
  contrôle ton compte contrôle le bot.
- Si un jour tu ajoutes des **collaborateurs** au repo, ils pourront modifier le
  code exécuté avec tes secrets — n'ajoute que des gens de confiance.
- Les limites API d'Alpaca (~200 requêtes/min) sont respectées grâce aux
  requêtes groupées par worker ; si tu crées des dizaines de workers, garde des
  fichiers de taille raisonnable.

---

*Projet pédagogique — paper trading uniquement. Ce n'est pas un conseil en
investissement, et les performances passées d'une stratégie ne garantissent rien.*
