# The BattleBees 🐝

Joc d'estratègia en temps real estil *Battle Cats*, fet amb **Pygame**, on defenses el teu rusc contra
exèrcits d'insectes.

> Joc original d'[arcaro123](https://github.com/arcaro123/BattleBees). Aquesta còpia en corregeix alguns errors (botiga, rescat, mutacions...).

## ▶ Juga-hi al navegador
**https://abelber07.github.io/BattleBees/**

(La primera càrrega pot trigar uns segons. La partida es desa al navegador.)

## Característiques
- 30 nivells (24 de campanya fins a la **Vespa Reina** + 6 de post-joc) i mode **Supervivència** infinit
- 20 abelles amb rols (Tanc, Atacant, Tirador, Control, Suport), millores, evolució i mutacions
- Càpsules d'ambre, botiga, missions diàries i setmanals, esdeveniments per temps limitat
- Torres del rusc amb avantatges, habilitats (Eixam i Cura), trompa de pol·len
- Història animada, tutorial interactiu, rescat d'abelles i La Cau per domesticar enemics

## Com jugar-hi a l'ordinador
Cal Python 3.10 o superior.

```bash
pip install -r requirements.txt   # pygame-ce i Pillow
python main.py
```

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

## Per a qui edita el codi
- `python main.py --simulate --runs 5 --stage 10 --lv 8` simula un nivell sense gràfics (equilibri).
- `python main.py --export` guarda tots els sprites a `./sprites/`.
- **`python main.py --bake`** regenera `assets/sprites.bin` i `assets/sounds.bin`. La versió web no pot
  generar sprites (no té Pillow), així que carrega aquests fitxers: **torna'ls a generar i puja'ls cada cop
  que canviïs els dibuixos o el so.**
- A cada `push` a `main`, GitHub Actions compila la versió web i la publica a la branca `gh-pages`.
