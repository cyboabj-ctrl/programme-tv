# Programme TV

Le programme des chaînes françaises sur une seule page : ce soir, en ce moment, et la journée complète de chaque chaîne, sur 7 jours.

- **Page** : `docs/index.html`, publiée avec GitHub Pages (dossier `docs/` de la branche `main`).
- **Données** : `docs/data/`, régénérées automatiquement deux fois par jour par le workflow `.github/workflows/guide.yml`.
- **Script** : `scripts/build_guide.py` télécharge le guide XMLTV public de [xmltvfr.fr](https://xmltvfr.fr) et le découpe en fichiers JSON légers (un par jour).

## Mettre à jour à la main

Onglet **Actions** du dépôt > « Mise à jour du guide TV » > **Run workflow**.

## Installer sur le téléphone

Ouvrir la page dans Chrome, menu ⋮ > **Ajouter à l'écran d'accueil**.

## Changer de source

Définir la variable `SOURCE_URLS` (adresses séparées par des espaces) dans le workflow, par exemple l'adresse du guide (EPG) d'un abonnement IPTV.
