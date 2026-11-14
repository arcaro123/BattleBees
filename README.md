# The BattleBees 🐝

Joc d'estratègia en temps real estil *Battle Cats*, fet amb **Pygame**, on defenses el teu rusc contra
exèrcits d'insectes. Tot el joc (codi, dibuixos i so) està en un sol fitxer: `main.py`.
Els sprites i el so es generen per codi la primera vegada que s'obre.

## Característiques
- 30 nivells (24 de campanya fins a la **Vespa Reina** + 6 de post-joc) i mode **Supervivència** infinit
- 20 abelles amb rols (Tanc, Atacant, Tirador, Control, Suport), millores, evolució i mutacions
- Càpsules d'ambre, botiga, missions diàries i setmanals, esdeveniments per temps limitat
- Torres del rusc amb avantatges, habilitats (Eixam i Cura), trompa de pol·len
- Història animada, tutorial interactiu, rescat d'abelles i La Cau per domesticar enemics

## Com jugar-hi
Cal Python 3.10 o superior.

```bash
pip install -r requirements.txt
python main.py
```

La primera vegada triga uns segons a generar els sprites i el so (després queden desats a la carpeta
`.bee_battle` de l'usuari, amb la partida).

### Controls a la batalla
| Tecla | Acció |
|---|---|
| 1–6 / clic | Generar abelles (7 = aliat salvatge) |
| W | Millorar el moneder |
| Espai | Trompa de pol·len |
| Q / E | Eixam / Cura |
| Tab | Velocitat x1 / x2 |
| Esc o P | Pausa |
| F11 | Pantalla completa |

## Opcions de la línia d'ordres
- `python main.py --export` guarda tots els sprites a `./sprites/`
- `python main.py --simulate --runs 5 --stage 10 --lv 8` simula un nivell sense gràfics (equilibri)
