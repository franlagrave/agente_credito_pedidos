#!/usr/bin/env python3
"""
Alta de clientes desde un Excel.
--------------------------------
Lee un .xlsx con altas o modificaciones de clientes y las vuelca a la base
ficticia que usan evaluar_pedido.py y agent.py (mock/clientes.json).

No es una conexión en vivo: corré este script después de guardar el Excel,
cuando quieras que los cambios se reflejen en el agente.

Generar la plantilla vacía:
    python mock/importar_clientes_xlsx.py --plantilla mock/clientes_nuevos.xlsx

Importar un Excel ya cargado:
    python mock/importar_clientes_xlsx.py mock/clientes_nuevos.xlsx

Columnas esperadas (primera fila, en este orden):
    id | razon_social | cuit | contacto | limite_credito |
    fecha_ultimo_balance | saldo_cuenta_corriente | deuda_vencida |
    calificacion_veraz

- id: identificador del cliente (ej: CLI-1011). Si ya existe en la base, se
  actualiza ese cliente; si no existe, se da de alta.
- fecha_ultimo_balance: formato YYYY-MM-DD.
- calificacion_veraz: 1, 3 o 5 (las únicas categorías que reconoce la
  política de crédito, ver config/politica_credito.json).

Un alta o modificación por este medio se considera permanente: se escribe
tanto en mock/clientes.json como en mock/clientes_base.json, para que
sobreviva a un `python evaluar_pedido.py --reset`.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from openpyxl import Workbook, load_workbook

BASE_DIR = Path(__file__).resolve().parent
CLIENTES_FILE = BASE_DIR / "clientes.json"
CLIENTES_BASE_FILE = BASE_DIR / "clientes_base.json"

COLUMNAS = [
    "id",
    "razon_social",
    "cuit",
    "contacto",
    "limite_credito",
    "fecha_ultimo_balance",
    "saldo_cuenta_corriente",
    "deuda_vencida",
    "calificacion_veraz",
]

VERAZ_VALIDOS = {1, 3, 5}


def generar_plantilla(destino: Path):
    wb = Workbook()
    ws = wb.active
    ws.title = "clientes"
    ws.append(COLUMNAS)
    ws.append([
        "CLI-1011", "Ejemplo S.A.", "30-12345678-9", "Nombre — email — teléfono",
        100000, "2026-01-31", 20000, 0, 1,
    ])
    destino.parent.mkdir(parents=True, exist_ok=True)
    wb.save(destino)
    print(f"Plantilla generada en {destino}. Completá una fila por cliente y volvé a correr el script con esa ruta.")


def leer_filas(origen: Path) -> list[dict]:
    wb = load_workbook(origen, data_only=True)
    ws = wb.active

    encabezado = [str(c.value).strip() if c.value is not None else "" for c in next(ws.iter_rows(min_row=1, max_row=1))]
    if encabezado[: len(COLUMNAS)] != COLUMNAS:
        raise ValueError(
            "El encabezado del Excel no coincide con el esperado.\n"
            f"  Esperado: {COLUMNAS}\n"
            f"  Encontrado: {encabezado[: len(COLUMNAS)]}\n"
            "Generá la plantilla con --plantilla y completá sobre esa base."
        )

    filas = []
    for i, fila in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        if fila is None or all(v is None for v in fila[: len(COLUMNAS)]):
            continue
        valores = dict(zip(COLUMNAS, fila))
        filas.append((i, valores))
    return filas


def validar_fila(num_fila: int, v: dict) -> dict:
    errores = []

    cid = str(v.get("id") or "").strip().upper()
    if not cid:
        errores.append("falta 'id'")

    razon_social = str(v.get("razon_social") or "").strip()
    if not razon_social:
        errores.append("falta 'razon_social'")

    cuit = str(v.get("cuit") or "").strip()
    if not cuit:
        errores.append("falta 'cuit'")

    contacto = str(v.get("contacto") or "").strip()

    def a_numero(campo, minimo=None):
        val = v.get(campo)
        if val is None or val == "":
            errores.append(f"falta '{campo}'")
            return None
        try:
            num = float(val)
        except (TypeError, ValueError):
            errores.append(f"'{campo}' no es numérico: {val!r}")
            return None
        if minimo is not None and num < minimo:
            errores.append(f"'{campo}' no puede ser negativo: {num}")
            return None
        return num

    limite_credito = a_numero("limite_credito", minimo=0)
    saldo_cuenta_corriente = a_numero("saldo_cuenta_corriente", minimo=0)
    deuda_vencida = a_numero("deuda_vencida", minimo=0)

    fecha_raw = v.get("fecha_ultimo_balance")
    fecha_ultimo_balance = None
    if fecha_raw is None or fecha_raw == "":
        errores.append("falta 'fecha_ultimo_balance'")
    elif hasattr(fecha_raw, "isoformat"):
        fecha_ultimo_balance = fecha_raw.date().isoformat() if hasattr(fecha_raw, "date") else fecha_raw.isoformat()
    else:
        try:
            fecha_ultimo_balance = date.fromisoformat(str(fecha_raw).strip()).isoformat()
        except ValueError:
            errores.append(f"'fecha_ultimo_balance' inválida (usar YYYY-MM-DD): {fecha_raw!r}")

    veraz_raw = v.get("calificacion_veraz")
    calificacion_veraz = None
    if veraz_raw is None or veraz_raw == "":
        errores.append("falta 'calificacion_veraz'")
    else:
        try:
            calificacion_veraz = int(veraz_raw)
        except (TypeError, ValueError):
            errores.append(f"'calificacion_veraz' no es entero: {veraz_raw!r}")
        else:
            if calificacion_veraz not in VERAZ_VALIDOS:
                errores.append(
                    f"'calificacion_veraz' debe ser 1, 3 o 5 (vino {calificacion_veraz})"
                )

    if errores:
        raise ValueError(f"fila {num_fila}: " + "; ".join(errores))

    return {
        "id": cid,
        "razon_social": razon_social,
        "cuit": cuit,
        "contacto": contacto,
        "limite_credito": limite_credito,
        "fecha_ultimo_balance": fecha_ultimo_balance,
        "saldo_cuenta_corriente": saldo_cuenta_corriente,
        "deuda_vencida": deuda_vencida,
        "calificacion_veraz": calificacion_veraz,
    }


def importar(origen: Path, aplicar: bool):
    filas = leer_filas(origen)
    if not filas:
        print("El Excel no tiene filas de datos (además del encabezado).")
        return

    registros = []
    errores = []
    for num_fila, valores in filas:
        try:
            registros.append(validar_fila(num_fila, valores))
        except ValueError as e:
            errores.append(str(e))

    if errores:
        print(f"Se encontraron {len(errores)} error(es). No se modificó ninguna base:")
        for e in errores:
            print(f"  - {e}")
        sys.exit(1)

    with open(CLIENTES_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    with open(CLIENTES_BASE_FILE, "r", encoding="utf-8") as f:
        data_base = json.load(f)

    altas, actualizaciones = [], []
    for r in registros:
        cid = r.pop("id")
        destino = data["clientes"]
        destino_base = data_base["clientes"]
        (actualizaciones if cid in destino else altas).append(cid)
        destino[cid] = r
        destino_base[cid] = dict(r)

    print(f"Leídas {len(registros)} fila(s) de {origen.name}: "
          f"{len(altas)} alta(s), {len(actualizaciones)} actualización(es).")
    for cid in altas:
        print(f"  + {cid} — {data['clientes'][cid]['razon_social']}")
    for cid in actualizaciones:
        print(f"  ~ {cid} — {data['clientes'][cid]['razon_social']}")

    if not aplicar:
        print("\nModo simulación (no se escribió nada). Corré con --aplicar para confirmar los cambios.")
        return

    with open(CLIENTES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    with open(CLIENTES_BASE_FILE, "w", encoding="utf-8") as f:
        json.dump(data_base, f, ensure_ascii=False, indent=2)

    print(f"\nBase actualizada en {CLIENTES_FILE} y {CLIENTES_BASE_FILE}.")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("excel", nargs="?", help="Ruta al .xlsx con las altas/modificaciones de clientes.")
    parser.add_argument("--plantilla", metavar="RUTA",
                        help="En lugar de importar, genera un .xlsx de plantilla en la ruta indicada y termina.")
    parser.add_argument("--aplicar", action="store_true",
                        help="Escribe los cambios en la base. Sin este flag, solo se valida y se muestra qué haría (dry-run).")
    args = parser.parse_args()

    if args.plantilla:
        generar_plantilla(Path(args.plantilla))
        return

    if not args.excel:
        parser.error("indicá la ruta al .xlsx a importar, o usá --plantilla para generar uno de ejemplo.")

    origen = Path(args.excel)
    if not origen.exists():
        print(f"No encuentro el archivo {origen}.")
        sys.exit(1)

    importar(origen, aplicar=args.aplicar)


if __name__ == "__main__":
    main()
