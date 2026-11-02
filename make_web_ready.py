"""
Adapta el main.py de BattleBees perquè funcioni al navegador (pygbag) SENSE deixar de funcionar a l'escriptori.

Ús (des de la carpeta del repositori):
    python make_web_ready.py            # modifica main.py (en desa una còpia com a main.py.bak)

Si alguna peça no es troba exactament una vegada, no toca res i t'ho diu.
"""
import os
import shutil
import sys

PATH = sys.argv[1] if len(sys.argv) > 1 else "main.py"

PATCHES = []


def patch(old, new, count=1):
    PATCHES.append((old, new, count))


# 1) PIL opcional + asyncio + detecció del navegador + font empaquetada
patch('from PIL import Image, ImageDraw  # pip install pillow',
      '''import asyncio

IS_WEB = sys.platform == "emscripten"      # True quan corre dins el navegador (pygbag)
try:
    from PIL import Image, ImageDraw       # pip install pillow
except ImportError:                        # al navegador no cal: els sprites arriben precalculats
    Image = ImageDraw = None


def mkfont(size, bold=True):
    """Al navegador no hi ha fonts del sistema: s'usa la que ve al repositori (fonts/)."""
    if IS_WEB:
        for base in (os.path.dirname(os.path.abspath(__file__)), os.getcwd()):
            p = os.path.join(base, "fonts", "DejaVuSansMono-Bold.ttf")
            if os.path.exists(p):
                return pygame.font.Font(p, max(8, int(size * 0.92)))
    return pygame.font.SysFont("consolas,couriernew,dejavusansmono,monospace", size, bold=bold)''')

# 2) carpeta de dades: variable d'entorn (CI) / web_assets (navegador) / ~/.bee_battle (escriptori)
patch('    d = os.path.join(os.path.expanduser("~"), ".bee_battle")\n',
      '''    env = os.environ.get("BATTLEBEES_DATA")
    if env:
        d = env
    elif IS_WEB:
        d = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web_assets")
        if not os.path.isdir(d):
            d = os.path.join(os.getcwd(), "web_assets")
    else:
        d = os.path.join(os.path.expanduser("~"), ".bee_battle")
''')

# 3) la memòria cau de sprites es pot llegir sense PIL
patch('''def _unpack(v):
    if isinstance(v, list):
        return [_unpack(x) for x in v]
    return Image.frombytes(v[0], v[1], zlib.decompress(v[2]))''',
      '''class RawImg:
    """Imatge mínima (mida + bytes RGBA) per quan no hi ha PIL (navegador)."""

    def __init__(self, size, data):
        self.size = tuple(size)
        self._d = data

    def tobytes(self):
        return self._d


def _unpack(v):
    if isinstance(v, list):
        return [_unpack(x) for x in v]
    if Image is None:
        return RawImg(v[1], zlib.decompress(v[2]))
    return Image.frombytes(v[0], v[1], zlib.decompress(v[2]))''')

# 4) fonts
patch('pygame.font.SysFont(PF, ', 'mkfont(', count=6)

# 5) desat persistent al navegador (localStorage)
patch('    if isinstance(raw, dict):\n        for k in d:\n            if k in raw:',
      '''    if IS_WEB:
        try:
            import platform
            s = platform.window.localStorage.getItem("battlebees_save")
            if s:
                raw = json.loads(str(s))
        except Exception:
            pass
    if isinstance(raw, dict):
        for k in d:
            if k in raw:''')
patch('def write_save(sv):\n    path = save_path()\n',
      '''def write_save(sv):
    if IS_WEB:
        try:
            import platform
            platform.window.localStorage.setItem("battlebees_save", json.dumps(sv))
        except Exception:
            pass
        return
    path = save_path()
''')

# 6) bucle principal asíncron (obligatori per pygbag)
patch('def main():\n    global IMG\n    argv = sys.argv', 'async def main():\n    global IMG\n    argv = sys.argv')
patch('            g.draw()\n            pygame.display.flip()\n    finally:',
      '            g.draw()\n            pygame.display.flip()\n            await asyncio.sleep(0)   # cedeix el control al navegador\n    finally:')
patch('if __name__ == "__main__":\n    main()', 'if __name__ == "__main__" or IS_WEB:\n    asyncio.run(main())')


def main():
    with open(PATH, "r", encoding="utf-8") as f:
        txt = f.read()
    if "IS_WEB" in txt:
        print("Aquest main.py ja està adaptat. No cal fer res.")
        return
    bad = []
    for old, new, count in PATCHES:
        n = txt.count(old)
        if n != count:
            bad.append((old.splitlines()[0][:70], n, count))
    if bad:
        print("NO s'ha modificat res. Aquestes peces no coincideixen (trobades / esperades):")
        for first, n, c in bad:
            print(f"  - {first!r}: {n} / {c}")
        sys.exit(1)
    for old, new, count in PATCHES:
        txt = txt.replace(old, new)
    shutil.copyfile(PATH, PATH + ".bak")
    with open(PATH, "w", encoding="utf-8") as f:
        f.write(txt)
    print("Fet! main.py adaptat (còpia de l'original: %s.bak)" % PATH)


if __name__ == "__main__":
    main()
