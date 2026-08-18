================================================================================
LNG OPS TOOL
================================================================================

################################################################################
#                              ENGLISH VERSION                               #
################################################################################

--------------------------------------------------------------------------------
1. WHAT THIS PROJECT IS
--------------------------------------------------------------------------------

LNG Ops Tool is a simulation of the day-to-day work of an LNG Scheduler and
Asset Optimizer at a commodity trading house (e.g. Vitol, Gunvor, Trafigura)
or an energy major (e.g. TotalEnergies, Shell).

It manages a small fleet of LNG carriers end to end:
  - assigning cargoes to vessels
  - computing real maritime routes (great-circle + chokepoints + canals)
  - detecting scheduling conflicts (draft, laycan, terminal slot overlaps)
  - optimizing which destination each cargo should sail to, based on live
    market prices (JKM / TTF / Henry Hub)
  - simulating day-to-day spot trading decisions for idle vessels
  - simulating disruptions (vessel delay, terminal outage, chokepoint closure)
    and their dollar impact
  - modeling upstream liquefaction train performance and the cargoes it
    produces

This is a portfolio project built to demonstrate the kind of reasoning and
tooling used in LNG scheduling / asset optimization roles.

--------------------------------------------------------------------------------
2. KEY FEATURES (application pages)
--------------------------------------------------------------------------------

The app is a multi-page Streamlit dashboard. Pages, selectable from the
sidebar:

  - Overview
      Landing page with live fleet metrics and a navigation guide.

  - Fleet Map
      Animated 45-day map (Plotly). Vessels move along their real routes at
      their actual speed; tank fill level drops with boil-off (exponential
      decay). Sidebar filters by vessel class and lets you close maritime
      chokepoints (Suez, Hormuz, Panama, ...) to see routes reroute live.

  - KPI Dashboard
      Fleet utilization, boil-off (BOG) loss, bunker savings, net margin,
      plus a 30-day Gantt chart of vessel assignments.

  - P&L
      For each assigned cargo, compares all candidate destinations
      (price, revenue, costs, net margin) and explains the chosen decision
      in plain text.

  - Disruption Simulator
      Three scenarios: vessel delay, terminal offline, chokepoint closure.
      Shows the baseline vs. the disrupted scenario, which cargoes are
      affected, and the dollar impact.

  - Fleet Management
      Add vessels to the fleet for the current session (in-memory only,
      never persisted to disk).

  - Spot Trading
      Simulates a daily spot market (JKM / TTF / Henry Hub) with
      mean-reverting, partially correlated regional prices. Idle vessels
      are dispatched on the most profitable route found each day; tracks
      both the *expected* margin (decided with today's price) and the
      *realized* margin (once the vessel actually arrives).

  - Train Performance (upstream)
      Models a liquefaction train (Ras Laffan, Qatar): thermal derating,
      continuous load-factor ramp based on breakeven economics, optimized
      maintenance scheduling, unplanned outages, and the cargoes the train
      generates over time.

--------------------------------------------------------------------------------
3. PROJECT STRUCTURE
--------------------------------------------------------------------------------

The codebase is organized in strict layers. A lower layer never depends on
a higher one (config -> data -> core -> ui).

  config.py                  All physical and market parameters (no logic)
  app.py                     Streamlit entry point / page router

  data/
    terminals.py             6 terminals (Ras Laffan, Sabine Pass, Futtsu,
                              Zeebrugge, Gate Rotterdam, Al Zour)
    vessels.py                5 vessels (2 Q-Flex, 2 TFDE, 1 Q-Max)
    cargoes.py                6 cargoes with laycans and delivery windows
    waypoints.py              10 maritime chokepoints (Suez, Hormuz, ...)

  core/
    physics.py                Boil-off, heel, ETA, laycan, demurrage
    constraints.py             Draft, laycan compliance, slot overlap checks
    routing.py                 Dynamic routing between any terminal pair
    optimizer.py                Cargo -> vessel + destination assignment (MILP)
    disruption.py                Vessel delay / terminal outage / dollar impact
    pnl.py                        Net margin per (cargo, vessel, destination)
    market.py                      Market prices: config fallback + live sources
    spot.py                          Daily spot trading simulation

  ui/
    overview.py, theme.py, gantt.py, map.py, alerts.py, kpi.py, pnl.py,
    disruption.py, fleet.py, fleet_state.py, spot.py
                                Streamlit pages, wired to core/ only.

  train_ops/                 Self-contained package (upstream production).
                              Its own config/data/core/ui layers, connected
                              to the rest of the app only through app.py.

Each core module ends with a `if __name__ == "__main__":` self-test block
that proves it runs correctly on its own.

--------------------------------------------------------------------------------
4. TECH STACK
--------------------------------------------------------------------------------

  - Python 3.13 (developed and tested on 3.13.7)
  - Streamlit  >= 1.58.0   - web UI framework
  - Plotly     >= 6.8.0    - maps, Gantt chart, animations
  - Pandas     >= 2.0.0    - tabular data handling
  - PuLP       >= 2.7.0    - MILP solver (CBC) for the optimizer
  - Requests   >= 2.31.0   - live market data calls (FX, Brent)

  Optional:
  - yfinance   - only required for live Brent oil price
                 (core.market.get_brent_price(use_live=True)); not installed
                 by default and not required to run the app.

--------------------------------------------------------------------------------
5. INSTALLATION
--------------------------------------------------------------------------------

Requirements: Python 3.10+ (project developed on 3.13).

  1. Clone or download the project.

  2. Create and activate a virtual environment (recommended):

       python -m venv venv

       # Windows
       venv\Scripts\activate

       # macOS / Linux
       source venv/bin/activate

  3. Install dependencies:

       pip install -r requirements.txt

  4. (Optional) Enable live Brent oil pricing:

       pip install yfinance

--------------------------------------------------------------------------------
6. RUNNING THE APP
--------------------------------------------------------------------------------

From the project root, with the virtual environment activated:

       streamlit run app.py

Streamlit will open the dashboard in your default browser
(usually http://localhost:8501).

Each individual module can also be run standalone to execute its self-test,
e.g.:

       python core/routing.py
       python core/optimizer.py

--------------------------------------------------------------------------------
7. LIVE MARKET DATA (OPTIONAL)
--------------------------------------------------------------------------------

By default, all market prices (JKM, TTF, Henry Hub, Brent, FX) fall back to
static values in config.py, so the app runs fully offline and
deterministically.

Live data sources, when enabled:
  - Brent   : yfinance (ticker BZ=F) - working, requires `pip install yfinance`
  - FX      : frankfurter.app - working, free, no API key needed
  - Henry Hub : EIA API v2 - requires an EIA_API_KEY environment variable
                (never hard-code API keys in the source code)
  - TTF     : not implemented - no reliable free live source identified;
              calling it with use_live=True raises a documented
              NotImplementedError and falls back to the static price.

--------------------------------------------------------------------------------
8. KNOWN LIMITATIONS
--------------------------------------------------------------------------------

  - Only one liquefaction train is modeled in train_ops (Ras Laffan, Qatar);
    the architecture supports adding more (data/trains.py is a list) with
    no logic changes.
  - Spot trading always dispatches the single most profitable route found
    each day (greedy), which concentrates most spot voyages on one axis
    given the current price data.
  - TTF has no live price source (see section 7).
  - Maintenance-window optimization is purely economic; it does not model
    real-world constraints (crew/parts availability, buyer agreements).
  - The upstream train_ops package runs on the real current date, while the
    rest of the app uses a fixed simulation date (1 March 2025) for
    reproducibility - the two calendars are intentionally not reconciled
    yet (see the "Preview" button in the Train Performance page).

--------------------------------------------------------------------------------
9. PROJECT CONTEXT
--------------------------------------------------------------------------------

Portfolio project built while completing an engineering degree at
CentraleSupelec (graduating August 2027), alongside a work-study program
(alternance) in LNG electrical engineering at Technip Energies.

A detailed internal technical log (design decisions, gotchas, rationale for
non-obvious choices) is kept in CONTEXT.md at the project root.



################################################################################
#                              VERSION FRANCAISE                             #
################################################################################

--------------------------------------------------------------------------------
1. PRESENTATION DU PROJET
--------------------------------------------------------------------------------

LNG Ops Tool est une simulation du travail quotidien d'un LNG Scheduler et
d'un Asset Optimizer chez un trader de matières premières (ex. Vitol,
Gunvor, Trafigura) ou un major de l'énergie (ex. TotalEnergies, Shell).

L'outil gère une petite flotte de méthaniers de bout en bout :
  - assignation des cargaisons aux navires
  - calcul de routes maritimes réelles (grand cercle + chokepoints + canaux)
  - détection des conflits de planning (tirant d'eau, laycan, chevauchements
    de créneaux terminal)
  - optimisation de la destination de chaque cargaison selon les prix de
    marché en direct (JKM / TTF / Henry Hub)
  - simulation des décisions de trading spot au jour le jour pour les
    navires disponibles
  - simulation de perturbations (retard navire, terminal hors service,
    fermeture de chokepoint) et de leur impact chiffré en dollars
  - modélisation de la performance d'un train de liquéfaction en amont et
    des cargaisons qu'il produit

Il s'agit d'un projet portfolio conçu pour démontrer le type de
raisonnement et d'outils utilisés dans un poste de scheduling LNG /
d'optimisation d'actifs.

--------------------------------------------------------------------------------
2. FONCTIONNALITES PRINCIPALES (pages de l'application)
--------------------------------------------------------------------------------

L'application est un tableau de bord Streamlit multi-pages. Pages
accessibles depuis la barre latérale :

  - Overview
      Page d'accueil avec les métriques de la flotte en direct et un guide
      de navigation.

  - Fleet Map
      Carte animée sur 45 jours (Plotly). Les navires se déplacent le long
      de leurs vraies routes à leur vitesse réelle ; le niveau de
      remplissage des cuves diminue avec le boil-off (décroissance
      exponentielle). Filtres par classe de navire et possibilité de fermer
      des chokepoints maritimes (Suez, Hormuz, Panama, ...) pour voir les
      routes se recalculer en direct.

  - KPI Dashboard
      Taux d'utilisation de la flotte, pertes de boil-off (BOG), économies
      de soutage, marge nette, ainsi qu'un diagramme de Gantt sur 30 jours
      des affectations de navires.

  - P&L
      Pour chaque cargaison assignée, comparaison de toutes les
      destinations candidates (prix, revenus, coûts, marge nette) avec une
      explication en texte de la décision retenue.

  - Disruption Simulator
      Trois scénarios : retard de navire, terminal hors service, fermeture
      de chokepoint. Compare le scénario de référence au scénario perturbé,
      identifie les cargaisons affectées et chiffre l'impact en dollars.

  - Fleet Management
      Permet d'ajouter des navires à la flotte pour la session en cours
      (uniquement en mémoire, jamais enregistré sur disque).

  - Spot Trading
      Simule un marché spot quotidien (JKM / TTF / Henry Hub) avec des prix
      régionaux à retour à la moyenne, partiellement corrélés. Les navires
      disponibles sont affectés à la route la plus rentable trouvée chaque
      jour ; suit séparément la marge "attendue" (décidée au prix du jour)
      et la marge "réalisée" (une fois le navire réellement arrivé).

  - Train Performance (upstream)
      Modélise un train de liquéfaction (Ras Laffan, Qatar) : derating
      thermique, rampe continue du taux de charge basée sur l'économie du
      breakeven, planification optimisée de la maintenance, pannes non
      planifiées, et les cargaisons générées par le train dans le temps.

--------------------------------------------------------------------------------
3. STRUCTURE DU PROJET
--------------------------------------------------------------------------------

Le code est organisé en couches strictes. Une couche inférieure ne dépend
jamais d'une couche supérieure (config -> data -> core -> ui).

  config.py                  Tous les paramètres physiques et de marché
                              (aucune logique)
  app.py                     Point d'entrée Streamlit / routage des pages

  data/
    terminals.py              6 terminaux (Ras Laffan, Sabine Pass, Futtsu,
                               Zeebrugge, Gate Rotterdam, Al Zour)
    vessels.py                 5 navires (2 Q-Flex, 2 TFDE, 1 Q-Max)
    cargoes.py                  6 cargaisons avec laycans et fenêtres de
                                 livraison
    waypoints.py                 10 chokepoints maritimes (Suez, Hormuz, ...)

  core/
    physics.py                 Boil-off, heel, ETA, laycan, demurrage
    constraints.py               Tirant d'eau, conformité laycan,
                                  chevauchement de créneaux
    routing.py                    Routage dynamique entre n'importe quelle
                                   paire de terminaux
    optimizer.py                   Assignation cargaison -> navire +
                                    destination (MILP)
    disruption.py                   Retard navire / terminal hors service /
                                     impact chiffré
    pnl.py                            Marge nette par (cargaison, navire,
                                       destination)
    market.py                          Prix de marché : repli config +
                                        sources en direct
    spot.py                              Simulation du trading spot
                                          quotidien

  ui/
    overview.py, theme.py, gantt.py, map.py, alerts.py, kpi.py, pnl.py,
    disruption.py, fleet.py, fleet_state.py, spot.py
                                Pages Streamlit, branchées uniquement sur
                                core/.

  train_ops/                 Package autonome (production amont). Ses
                              propres couches config/data/core/ui, relié au
                              reste de l'application uniquement via app.py.

Chaque module de core/ se termine par un bloc `if __name__ == "__main__":`
qui prouve qu'il fonctionne seul, sans erreur (auto-test).

--------------------------------------------------------------------------------
4. STACK TECHNIQUE
--------------------------------------------------------------------------------

  - Python 3.13 (développé et testé en 3.13.7)
  - Streamlit  >= 1.58.0   - framework d'interface web
  - Plotly     >= 6.8.0    - cartes, Gantt, animations
  - Pandas     >= 2.0.0    - manipulation de données tabulaires
  - PuLP       >= 2.7.0    - solveur MILP (CBC) pour l'optimiseur
  - Requests   >= 2.31.0   - appels aux données de marché en direct (FX, Brent)

  Optionnel :
  - yfinance   - requis uniquement pour le prix Brent en direct
                 (core.market.get_brent_price(use_live=True)) ; non installé
                 par défaut et non nécessaire pour lancer l'application.

--------------------------------------------------------------------------------
5. INSTALLATION
--------------------------------------------------------------------------------

Prérequis : Python 3.10+ (projet développé en 3.13).

  1. Cloner ou télécharger le projet.

  2. Créer et activer un environnement virtuel (recommandé) :

       python -m venv venv

       # Windows
       venv\Scripts\activate

       # macOS / Linux
       source venv/bin/activate

  3. Installer les dépendances :

       pip install -r requirements.txt

  4. (Optionnel) Activer le prix Brent en direct :

       pip install yfinance

--------------------------------------------------------------------------------
6. LANCEMENT DE L'APPLICATION
--------------------------------------------------------------------------------

Depuis la racine du projet, environnement virtuel activé :

       streamlit run app.py

Streamlit ouvre le tableau de bord dans le navigateur par défaut
(généralement http://localhost:8501).

Chaque module peut aussi être exécuté seul pour lancer son auto-test,
par exemple :

       python core/routing.py
       python core/optimizer.py

--------------------------------------------------------------------------------
7. DONNEES DE MARCHE EN DIRECT (OPTIONNEL)
--------------------------------------------------------------------------------

Par défaut, tous les prix de marché (JKM, TTF, Henry Hub, Brent, FX)
utilisent des valeurs statiques de repli dans config.py : l'application
fonctionne donc entièrement hors ligne et de façon déterministe.

Sources en direct, si activées :
  - Brent     : yfinance (ticker BZ=F) - fonctionnel, nécessite
                `pip install yfinance`
  - FX        : frankfurter.app - fonctionnel, gratuit, sans clé API
  - Henry Hub : API EIA v2 - nécessite une variable d'environnement
                EIA_API_KEY (ne jamais mettre de clé API en dur dans le code)
  - TTF       : non implémenté - aucune source gratuite fiable identifiée ;
                l'appeler avec use_live=True lève une NotImplementedError
                documentée et retombe sur le prix statique.

--------------------------------------------------------------------------------
8. LIMITES CONNUES
--------------------------------------------------------------------------------

  - Un seul train de liquéfaction est modélisé dans train_ops (Ras Laffan,
    Qatar) ; l'architecture permet d'en ajouter d'autres (data/trains.py
    est une liste) sans changement de logique.
  - Le trading spot affecte toujours la route la plus rentable trouvée
    chaque jour (glouton), ce qui concentre la plupart des voyages spot sur
    un seul axe avec le jeu de données actuel.
  - TTF n'a pas de source de prix en direct (voir section 7).
  - L'optimisation de la fenêtre de maintenance est purement économique ;
    elle ne modélise pas les contraintes réelles (disponibilité des
    équipes/pièces, accords avec l'acheteur).
  - Le package amont train_ops tourne sur la date réelle actuelle, alors
    que le reste de l'application utilise une date de simulation fixe
    (1er mars 2025) pour la reproductibilité - les deux calendriers ne sont
    volontairement pas encore réconciliés (voir le bouton "Preview" de la
    page Train Performance).

--------------------------------------------------------------------------------
9. CONTEXTE DU PROJET
--------------------------------------------------------------------------------

Projet portfolio réalisé en parallèle d'un cursus d'ingénieur à
CentraleSupélec (diplôme prévu août 2027) et d'une alternance en
électrotechnique LNG chez Technip Energies.

Un journal technique interne détaillé (décisions de conception, pièges
rencontrés, justification des choix non évidents) est tenu à jour dans
CONTEXT.md à la racine du projet.
