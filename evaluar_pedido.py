#!/usr/bin/env python3
"""
Evaluación de un nuevo pedido contra la política de crédito.
------------------------------------------------------------
Script de consola: pide por teclado el cliente y el monto del pedido, aplica
los cálculos aritméticos definidos en config/politica_credito.json sobre la
base de clientes de mock/clientes.json, y devuelve si el cliente es APTO o
NO APTO para que se le libere el pedido.

Este script es a la vez:
  - una herramienta de prueba manual (lo corrés vos), y
  - la lógica que ejecuta el agente cuando llama a la tool
    evaluar_politica_credito (ver mock/tools_impl.py).

Uso interactivo:
    python evaluar_pedido.py

Uso directo (sin preguntar nada, útil para probar varios casos):
    python evaluar_pedido.py --cliente CLI-1002 --monto 30000
    python evaluar_pedido.py --cliente CLI-1002 --monto 30000 --json

Listar la base de clientes:
    python evaluar_pedido.py --listar
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mock.politica import (
    cargar_clientes,
    cargar_politica,
    evaluar,
    formatear_reporte,
    meses_entre,
)

LOG_FILE = Path(__file__).resolve().parent / "logs" / "registro_auditable.jsonl"


def registrar(evento: dict):
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": date.today().isoformat(), **evento}, ensure_ascii=False) + "\n")


def resetear_base():
    """Restaura clientes.json desde la copia prístina y borra el estado de pruebas."""
    raiz = Path(__file__).resolve().parent
    base = raiz / "mock" / "clientes_base.json"
    destino = raiz / "mock" / "clientes.json"
    if not base.exists():
        print("No encuentro mock/clientes_base.json — no puedo restaurar la base.")
        return
    destino.write_text(base.read_text(encoding="utf-8"), encoding="utf-8")
    for f in [raiz / "mock" / "cobranzas_estado.json", raiz / "logs" / "registro_auditable.jsonl"]:
        if f.exists():
            f.unlink()
    print("Base de clientes restaurada al estado inicial. Log de auditoría y cobranzas pendientes borrados.")


def listar_clientes(clientes: dict):
    print("\n" + "=" * 112)
    print(f"  BASE DE CLIENTES ({len(clientes)})")
    print("=" * 112)
    print(
        f"  {'ID':<10} {'RAZÓN SOCIAL':<36} {'CUIT':<15} {'LÍMITE':>11} "
        f"{'SALDO CC':>11} {'VENCIDA':>10} {'VERAZ':>6} {'BALANCE':>11}"
    )
    print("  " + "-" * 108)
    for cid, c in clientes.items():
        ant = meses_entre(c["fecha_ultimo_balance"])
        marca_bal = "!" if ant > 18 else " "
        print(
            f"  {cid:<10} {c['razon_social'][:35]:<36} {c['cuit']:<15} "
            f"{c['limite_credito']:>11,.0f} {c['saldo_cuenta_corriente']:>11,.0f} "
            f"{c['deuda_vencida']:>10,.0f} {c['calificacion_veraz']:>6} "
            f"{c['fecha_ultimo_balance']:>11}{marca_bal}"
        )
    print("=" * 112)
    print("  Veraz: 1 = normal (100% del límite) | 3 = con problemas (50%) | 5 = irrecuperable (0%)")
    print("  '!' = último balance con más de 18 meses de antigüedad (el límite habilitado se reduce al 50%)\n")


def pedir_cliente(clientes: dict) -> tuple[str, dict]:
    while True:
        entrada = input("  Cliente (ID o CUIT, 'listar' para ver la base, 'salir' para terminar): ").strip()
        if entrada.lower() in {"salir", "exit", "quit", "q"}:
            sys.exit(0)
        if entrada.lower() in {"listar", "l", "ls"}:
            listar_clientes(clientes)
            continue
        clave = entrada.upper()
        if clave in clientes:
            return clave, clientes[clave]
        # búsqueda por CUIT
        for cid, c in clientes.items():
            if c["cuit"].replace("-", "") == entrada.replace("-", ""):
                return cid, c
        print(f"  >> No encontré el cliente '{entrada}'. Probá con 'listar'.\n")


def pedir_monto() -> float:
    while True:
        entrada = input("  Monto del pedido en USD: ").strip().replace(",", "").replace("$", "")
        try:
            monto = float(entrada)
        except ValueError:
            print("  >> Ingresá un número válido (ej: 30000).\n")
            continue
        if monto <= 0:
            print("  >> El monto debe ser mayor a cero.\n")
            continue
        return monto


def main():
    parser = argparse.ArgumentParser(description="Evalúa si un pedido puede liberarse según la política de crédito.")
    parser.add_argument("--cliente", help="ID del cliente (ej: CLI-1002) o su CUIT.")
    parser.add_argument("--monto", type=float, help="Monto del pedido en USD.")
    parser.add_argument("--json", action="store_true", help="Devuelve el resultado en JSON en lugar del reporte legible.")
    parser.add_argument("--listar", action="store_true", help="Muestra la base de clientes y termina.")
    parser.add_argument("--reset", action="store_true",
                        help="Restaura la base de clientes a su estado inicial (deshace pagos y pedidos liberados de pruebas anteriores).")
    args = parser.parse_args()

    if args.reset:
        resetear_base()
        return

    clientes = cargar_clientes()
    politica = cargar_politica()

    if args.listar:
        listar_clientes(clientes)
        return

    # ---- Modo directo (por argumentos) ----
    if args.cliente and args.monto is not None:
        clave = args.cliente.upper()
        if clave not in clientes:
            coincidencias = [
                cid for cid, c in clientes.items()
                if c["cuit"].replace("-", "") == args.cliente.replace("-", "")
            ]
            if not coincidencias:
                print(f"Cliente '{args.cliente}' no encontrado. Usá --listar para ver la base.")
                sys.exit(1)
            clave = coincidencias[0]
        cliente = {"cliente_id": clave, **clientes[clave]}
        resultado = evaluar(cliente, args.monto, politica)
        registrar({"origen": "evaluar_pedido.py", "cliente_id": clave, "monto_pedido": args.monto, "resultado": resultado})
        print(json.dumps(resultado, ensure_ascii=False, indent=2) if args.json else formatear_reporte(resultado))
        return

    # ---- Modo interactivo ----
    print("\n" + "=" * 68)
    print("  AGENTE DE GESTIÓN DE CRÉDITO — Evaluación de nuevo pedido")
    print("=" * 68)
    print("  Cargá los datos del pedido para verificar si el cliente es apto.\n")

    while True:
        clave, datos = pedir_cliente(clientes)
        print(f"  -> {datos['razon_social']} (CUIT {datos['cuit']})")
        print(f"     Contacto: {datos['contacto']}\n")

        monto = pedir_monto()

        cliente = {"cliente_id": clave, **datos}
        resultado = evaluar(cliente, monto, politica)
        registrar({"origen": "evaluar_pedido.py", "cliente_id": clave, "monto_pedido": monto, "resultado": resultado})

        print("\n" + formatear_reporte(resultado) + "\n")

        otro = input("  ¿Evaluar otro pedido? (s/n): ").strip().lower()
        if not otro.startswith("s"):
            print("\n  Traza completa en logs/registro_auditable.jsonl\n")
            break
        print()


if __name__ == "__main__":
    main()
