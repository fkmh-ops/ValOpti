# ValOpti — The Draft Maker

Prototype du site pour recruteurs esport Valorant.

## Contenu

- `index.html` : le site complet (HTML, CSS et JS dans un seul fichier). Double-cliquez dessus pour l'ouvrir dans un navigateur, aucune installation nécessaire.
- `sql/schema.sql` : le schéma de la base (fourni par l'équipe).
- `sql/valopti_app.sql` : les requêtes de chaque écran, les tables à ajouter (`compositions`, `composition_slots`, `predictions`, `prediction_maps`) et le remplissage de `agents.role`. À exécuter après `schema.sql`.
- `assets/logo_valopti.png` : le logo d'origine (le site utilise une version SVG redessinée, intégrée dans `index.html`).

## Écrans

Accueil, Scouting, Draft Maker, Prédictions, Classement. Navigation par ancre (`index.html#draft`, `#predictions`…).

## Données

Les équipes, joueurs et matchs affichés sont **fictifs**, générés dans le script (section 1 de `index.html`) avec la même structure que les tables du schéma. Pour brancher la vraie base, remplacer cette section par des appels à l'API qui exécutent les requêtes de `sql/valopti_app.sql`. Le bouton « Afficher les tables SQL » en bas de page indique la table source de chaque bloc.

Les compositions sauvegardées sont stockées dans le navigateur (localStorage), en attendant la table `compositions`.

## Polices

Teko, Barlow et JetBrains Mono, chargées depuis Google Fonts (connexion internet nécessaire, sinon polices système de secours).
