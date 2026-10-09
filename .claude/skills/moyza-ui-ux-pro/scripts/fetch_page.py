#!/usr/bin/env python3
"""Descarga una página de la app renderizada como admin, sin navegador.

Se ejecuta desde el host y usa `docker exec` contra el contenedor `moyza_backend`
(que tiene las dependencias y la clave para firmar el token). Sirve para comprobar que
una plantilla renderiza (200), ver el HTML resultante y buscar en él.

Uso:
    python .claude/skills/moyza-ui-ux-pro/scripts/fetch_page.py /alerts
    python .claude/skills/moyza-ui-ux-pro/scripts/fetch_page.py /buyers/12?tab=matches --company MOES
    python .claude/skills/moyza-ui-ux-pro/scripts/fetch_page.py /properties --grep "rounded-2xl" --grep "dupBanner"
    python .claude/skills/moyza-ui-ux-pro/scripts/fetch_page.py /alerts --out /tmp/alerts.html

Variables: MOYZA_TEST_ADMIN_EMAIL (por defecto admin@moyza.com), MOYZA_CONTAINER
(por defecto moyza_backend), MOYZA_TEST_BASE_URL (por defecto http://localhost:8000,
visto desde dentro del contenedor).
"""
import argparse
import json
import os
import subprocess
import sys

INNER = r'''
import json, sys, urllib.request, urllib.error
import app.db.base  # noqa
from app.core.security import create_access_token
path, company, email, base = sys.argv[1:5]
tok = create_access_token({"sub": email})
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None
opener = urllib.request.build_opener(NoRedirect)
req = urllib.request.Request(base + path)
req.add_header("Cookie", f"access_token={tok}; active_company={company}")
try:
    r = opener.open(req, timeout=20)
    status, body, location = r.status, r.read().decode("utf-8", "replace"), r.headers.get("location", "")
except urllib.error.HTTPError as e:
    status, body, location = e.code, e.read().decode("utf-8", "replace"), e.headers.get("location", "")
print(json.dumps({"status": status, "location": location, "body": body}))
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("path", help="ruta de la app, p.ej. /alerts")
    parser.add_argument("--company", default="MOYZA", help="MOYZA o MOES")
    parser.add_argument("--grep", action="append", default=[], help="texto a buscar en el HTML (repetible)")
    parser.add_argument("--out", help="guardar el HTML en este archivo")
    parser.add_argument("--print", action="store_true", help="imprimir el HTML completo")
    args = parser.parse_args()

    container = os.getenv("MOYZA_CONTAINER", "moyza_backend")
    email = os.getenv("MOYZA_TEST_ADMIN_EMAIL", "admin@moyza.com")
    base = os.getenv("MOYZA_TEST_BASE_URL", "http://localhost:8000")

    cmd = ["docker", "exec", "-i", container, "python", "-", args.path, args.company, email, base]
    proc = subprocess.run(cmd, input=INNER, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stderr.strip() or "error al ejecutar dentro del contenedor", file=sys.stderr)
        return 2

    data = json.loads(proc.stdout.strip().splitlines()[-1])
    status, body = data["status"], data["body"]
    print(f"{args.path} [{args.company}] -> {status}" + (f" (redirige a {data['location']})" if data.get("location") else ""))

    for needle in args.grep:
        print(f"  {'OK ' if needle in body else 'NO '} {needle!r}" + (f" x{body.count(needle)}" if needle in body else ""))

    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(body)
        print(f"  HTML guardado en {args.out} ({len(body)} bytes)")

    if args.print:
        print(body)

    return 0 if status == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
