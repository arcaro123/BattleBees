# Publicar BattleBees al navegador (GitHub Pages)

El teu workflow actual ja construeix amb pygbag i publica, però **tal com està el joc no funcionaria al navegador**:
el bucle principal no és asíncron, necessita Pillow per dibuixar els sprites (i fer-ho al navegador trigaria una
eternitat), el desat va a un fitxer que es perd en tancar la pàgina i no hi ha cap font del sistema.
Aquest paquet ho arregla sense trencar la versió d'escriptori.

## Passos (un cop)

1. Copia al teu repositori, al costat de `main.py`: `make_web_ready.py`, la carpeta `fonts/`, `.gitignore`
   i `.github/workflows/main.yml` (substitueix el que tens).
2. Executa, des de la carpeta del repositori, `python make_web_ready.py`.
   Modifica `main.py` (deixa una còpia a `main.py.bak`). Si alguna peça no coincideix, no toca res i t'ho diu.
3. Prova a l'escriptori que continua anant: `python main.py`.
4. Fes `git add . && git commit -m "Versió web" && git push`.
5. A GitHub: **Settings → Pages → Build and deployment → Deploy from a branch → branca `gh-pages`, carpeta `/ (root)`**.
   (La branca `gh-pages` la crea el workflow la primera vegada que acaba bé; mira la pestanya **Actions**.)
6. El joc quedarà a `https://arcaro123.github.io/BattleBees/`.

## Què fa el workflow
- Calcula els sprites i el so al servidor (carpeta `web_assets/`, no es puja al repositori) i els empaqueta dins del joc.
- Construeix amb pygbag i publica `build/web` a la branca `gh-pages`.

## Què canvia al navegador
- El progrés es desa al **localStorage** del navegador (no es comparteix entre navegadors ni amb la versió d'escriptori).
- Es fa servir la font DejaVu Sans Mono Bold de `fonts/` (llicència lliure, inclosa).
- El so s'activa en el primer clic (és una norma dels navegadors).

## Coses que no he pogut comprovar
No he pogut executar pygbag ni obrir el joc en un navegador. Si el primer desplegament falla o va lent, passa'm
el registre de **Actions** o el que surti a la consola del navegador (F12) i ho ajustem. Punts a vigilar:
la mida de `web_assets/` (els fons són grans), el rendiment en navegadors lents i que el mòdul de so accepti 16 kHz.
