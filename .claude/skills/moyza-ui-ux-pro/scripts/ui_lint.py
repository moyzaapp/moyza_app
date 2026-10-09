#!/usr/bin/env python3
"""Linter de consistencia de interfaz para las plantillas Jinja de MOYZA.

Detecta desviaciones del sistema de diseño (references/tokens.md y ux-rules.md).
No modifica nada. Uso:

    python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates
    python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates/alerts/list.html
    python .claude/skills/moyza-ui-ux-pro/scripts/ui_lint.py backend/app/web/templates --json

Salida: una línea por aviso `ruta:línea: [regla] mensaje`, y un resumen por regla.
Código de salida 1 si hay avisos (para usarlo en CI si se quiere).

Las reglas son heurísticas por expresión regular, pensadas para señalar, no para
bloquear. Un falso positivo puntual se silencia con el comentario `{# ui-lint: off #}`
en la misma línea.
"""
import argparse
import json
import re
import sys
from pathlib import Path

# Reglas informativas: cosméticas, se muestran solo con --all
INFO_RULES = {"heroicon-stroke-2", "tab-styles", "focus-ring"}

RULES = [
    # (id, regex, mensaje, por qué)
    ("primary-color",
     r"\b(bg-black|bg-blue-600|bg-indigo-600|bg-gray-800)\b(?=[^>]*\b(hover:bg-|text-white)\b)",
     "botón con color fuera del sistema; el primario es bg-gray-900",
     "Hoy conviven negro, azul, índigo y gris-800 como botón principal."),
    ("yellow-vs-amber",
     r"\b(bg|text|border|ring)-yellow-\d{2,3}\b",
     "usa amber-* para avisos, no yellow-*",
     "El aviso es ámbar en todo el sistema."),
    ("focus-ring",
     r"\bfocus:ring-(gray-200|indigo-500|black|blue-200)\b",
     "anillo de foco fuera del sistema; usa focus:ring-blue-500/40 focus:border-blue-500",
     "Cinco anillos distintos confunden."),
    ("modal-no-role",
     r"<div[^>]*\bfixed inset-0\b[^>]*\bz-50\b(?![^>]*role=\"dialog\")[^>]*>",
     "modal sin role=\"dialog\" aria-modal=\"true\"",
     "Sin role el lector de pantalla no sabe que hay un diálogo abierto."),
    ("modal-hidden-flex",
     r"class=\"[^\"]*\bhidden\b[^\"]*\bflex\b[^\"]*\bfixed\b|class=\"[^\"]*\bfixed\b[^\"]*\bhidden\b[^\"]*\bflex\b",
     "modal con 'hidden' y 'flex' a la vez; usa el patrón de components.md",
     "Dependiendo del orden de las clases el modal se ve u oculta mal."),
    ("label-no-for",
     r"<label(?![^>]*\bfor=)[^>]*>(?![\s\S]{0,200}?<(input|select|textarea)[^>]*>[\s\S]{0,200}?</label>)",
     "label sin 'for' (y no envuelve al control)",
     "Sin asociación, el clic en la etiqueta no enfoca el campo y el lector no la anuncia."),
    ("onclick-interp",
     r"onclick=\"[^\"]*\('\{\{\s*[^}|]+\s*\}\}'",
     "dato interpolado dentro de onclick sin tojson; usa data-* con | tojson",
     "Se rompe con un apóstrofo y permite inyección."),
    ("emoji-icon",
     r"[\U0001F300-\U0001FAFF☀-➿⭐✅❌]",
     "emoji o símbolo de texto usado como icono; usa Heroicons",
     "Los emojis cambian según el sistema y no se pueden colorear."),
    ("double-padding",
     r"class=\"[^\"]*\bp-4 sm:p-6 lg:p-8\b",
     "padding de página duplicado; <main> ya lo aplica",
     "Deja 64 px por lado en escritorio."),
    ("user-scalable",
     r"user-scalable\s*=\s*no|maximum-scale\s*=\s*1",
     "viewport bloquea el zoom",
     "Impide ampliar texto en móvil."),
    ("text-10px",
     r"\btext-\[10px\]",
     "texto por debajo de text-xs",
     "No se lee en móvil."),
    ("role-in-template",
     r"request\.state\.user\.role",
     "lectura del rol en la plantilla; pasa is_admin desde el route",
     "Se repite la condición y es fácil equivocarse."),
    ("native-alert",
     r"\balert\(",
     "alert() nativo; usa banner o flash",
     "No se puede estilar ni leer con calma."),
    ("tab-styles",
     r"rounded-t-lg[^\"]*border-b-white|border-b-white[^\"]*rounded-t-lg",
     "pestaña tipo carpeta; el sistema usa subrayado",
     "Hay tres estilos de pestaña."),
    ("heroicon-stroke-2",
     r"stroke-width=\"2\"",
     "icono con stroke-width 2; el sistema usa 1.5",
     "Mezcla de grosores entre pantallas."),
]

COMPILED = [(rid, re.compile(rx), msg, why) for rid, rx, msg, why in RULES]
IGNORE_MARK = "ui-lint: off"
TABLE_RX = re.compile(r"<table\b")


def _add(findings, path, lines, text, pos, rid, msg, why):
    line_no = text.count("\n", 0, pos) + 1
    line = lines[line_no - 1] if line_no - 1 < len(lines) else ""
    if IGNORE_MARK in line:
        return
    findings.append({"file": str(path), "line": line_no, "rule": rid, "message": msg, "why": why,
                     "level": "info" if rid in INFO_RULES else "warn"})


def lint_file(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    findings = []
    for rid, rx, msg, why in COMPILED:
        for m in rx.finditer(text):
            _add(findings, path, lines, text, m.start(), rid, msg, why)

    # Tabla sin envoltorio con scroll horizontal: se mira lo que hay ANTES de <table>
    for m in TABLE_RX.finditer(text):
        before = text[max(0, m.start() - 600):m.start()]
        if "overflow-x-auto" not in before:
            _add(findings, path, lines, text, m.start(), "table-no-scroll",
                 "tabla sin envoltorio overflow-x-auto cerca", "En móvil la tabla se recorta.")
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="+", help="archivos .html o carpetas")
    parser.add_argument("--json", action="store_true", help="salida JSON")
    parser.add_argument("--rule", action="append", help="limitar a estas reglas (repetible)")
    parser.add_argument("--all", action="store_true", help="incluir también las reglas informativas (cosméticas)")
    args = parser.parse_args()

    files = []
    for p in args.paths:
        path = Path(p)
        if path.is_dir():
            files.extend(sorted(path.rglob("*.html")))
        elif path.exists():
            files.append(path)
        else:
            print(f"no existe: {p}", file=sys.stderr)

    findings = []
    for f in files:
        findings.extend(lint_file(f))
    if args.rule:
        findings = [x for x in findings if x["rule"] in set(args.rule)]
    elif not args.all:
        findings = [x for x in findings if x["level"] == "warn"]

    findings.sort(key=lambda x: (x["file"], x["line"]))

    if args.json:
        print(json.dumps(findings, ensure_ascii=False, indent=2))
    else:
        for x in findings:
            print(f"{x['file']}:{x['line']}: [{x['rule']}] {x['message']}")
        summary = {}
        for x in findings:
            summary[x["rule"]] = summary.get(x["rule"], 0) + 1
        print()
        print(f"{len(findings)} avisos en {len(files)} archivos" + ("" if args.all or args.rule else " (sin reglas informativas; añade --all)"))
        for rid, n in sorted(summary.items(), key=lambda kv: -kv[1]):
            print(f"  {n:4d}  {rid}")

    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
