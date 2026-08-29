"""
Motor de política de crédito.

Contiene la aritmética que decide si un pedido es APTO o NO APTO.
Es la única fuente de verdad del cálculo: la usan tanto el script de consola
(evaluar_pedido.py) como la tool evaluar_politica_credito del agente
(mock/tools_impl.py), para que ambos den siempre el mismo resultado.

Fórmula:
    limite_ajustado    = limite_credito x factor_veraz x factor_balance
    credito_disponible = limite_ajustado - saldo_cuenta_corriente
    APTO  si  (veraz != 5)  y  (deuda_vencida <= tolerancia)  y  (monto_pedido <= credito_disponible)
"""

import json
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
POLITICA_FILE = BASE_DIR.parent / "config" / "politica_credito.json"
CLIENTES_FILE = BASE_DIR / "clientes.json"


def cargar_politica() -> dict:
    with open(POLITICA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def cargar_clientes() -> dict:
    with open(CLIENTES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)["clientes"]


def meses_entre(fecha_iso: str, hasta: date | None = None) -> int:
    """Antigüedad en meses completos entre una fecha ISO (YYYY-MM-DD) y hoy."""
    hasta = hasta or date.today()
    d = date.fromisoformat(fecha_iso)
    meses = (hasta.year - d.year) * 12 + (hasta.month - d.month)
    if hasta.day < d.day:
        meses -= 1
    return max(meses, 0)


def _accion_sugerida(apto: bool, cond_veraz: bool, cond_deuda: bool, cond_monto: bool) -> str:
    """Traduce el resultado del cálculo en el próximo paso del flujo del agente."""
    if apto:
        return "liberar_pedido"
    if not cond_veraz:
        # Categoría 5: no hay vía normal de regularización, solo excepción aprobada.
        return "escalar_a_aprobacion_humana"
    if not cond_deuda:
        # Hay deuda vencida: el camino normal es la gestión de cobranza.
        return "gestionar_cobranza"
    # Sin deuda vencida pero el monto excede el disponible: reducir el pedido o escalar.
    return "reducir_pedido_o_escalar_a_aprobacion_humana"


def evaluar(cliente: dict, monto_pedido: float, politica: dict | None = None,
            hoy: date | None = None) -> dict:
    """
    Aplica la política de crédito a un pedido y devuelve el detalle completo
    del cálculo (para que el resultado sea auditable y explicable).
    """
    politica = politica or cargar_politica()
    hoy = hoy or date.today()

    limite = float(cliente["limite_credito"])
    saldo = float(cliente["saldo_cuenta_corriente"])
    vencida = float(cliente["deuda_vencida"])
    veraz = int(cliente["calificacion_veraz"])

    # --- Factor por calificación Veraz ---
    factor_veraz = float(politica["factor_por_calificacion_veraz"][str(veraz)])

    # --- Factor por antigüedad del último balance ---
    antiguedad = meses_entre(cliente["fecha_ultimo_balance"], hoy)
    tope_meses = int(politica["balance"]["antiguedad_maxima_meses"])
    balance_vencido = antiguedad > tope_meses
    factor_balance = float(politica["balance"]["factor_si_vencido"]) if balance_vencido else 1.0

    # --- Aritmética principal ---
    limite_ajustado = round(limite * factor_veraz * factor_balance, 2)
    credito_disponible = round(max(limite_ajustado - saldo, 0.0), 2)
    excedente = round(max(monto_pedido - credito_disponible, 0.0), 2)

    # --- Condiciones de aptitud ---
    tolerancia = float(politica.get("tolerancia_deuda_vencida", 0))
    cond_veraz = veraz != 5
    cond_deuda = vencida <= tolerancia
    cond_monto = monto_pedido <= credito_disponible
    apto = cond_veraz and cond_deuda and cond_monto

    motivos = []
    if not cond_veraz:
        motivos.append(
            f"calificación Veraz categoría {veraz} (irrecuperable): no se habilita crédito"
        )
    if not cond_deuda:
        motivos.append(f"registra USD {vencida:,.2f} de deuda vencida")
    if not cond_monto:
        motivos.append(
            f"el pedido (USD {monto_pedido:,.2f}) excede el crédito disponible "
            f"(USD {credito_disponible:,.2f}) en USD {excedente:,.2f}"
        )

    return {
        "cliente_id": cliente.get("cliente_id"),
        "razon_social": cliente.get("razon_social"),
        "cuit": cliente.get("cuit"),
        "apto": apto,
        "monto_pedido": round(monto_pedido, 2),
        "calculo": {
            "limite_credito": limite,
            "calificacion_veraz": veraz,
            "factor_veraz": factor_veraz,
            "fecha_ultimo_balance": cliente["fecha_ultimo_balance"],
            "antiguedad_balance_meses": antiguedad,
            "balance_vencido": balance_vencido,
            "factor_balance": factor_balance,
            "limite_ajustado": limite_ajustado,
            "saldo_cuenta_corriente": saldo,
            "credito_disponible": credito_disponible,
            "deuda_vencida": vencida,
            "excedente": excedente,
        },
        "condiciones": {
            "veraz_habilitado": cond_veraz,
            "sin_deuda_vencida": cond_deuda,
            "monto_dentro_del_disponible": cond_monto,
        },
        "motivo": (
            "APTO — cumple la política de crédito vigente."
            if apto
            else "NO APTO — " + "; ".join(motivos) + "."
        ),
        "accion_sugerida": _accion_sugerida(apto, cond_veraz, cond_deuda, cond_monto),
    }


def formatear_reporte(r: dict) -> str:
    """Devuelve el resultado de evaluar() como texto legible para consola."""
    c = r["calculo"]
    estado = "APTO" if r["apto"] else "NO APTO"
    marca = lambda ok: "OK  " if ok else "FALLA"

    lineas = [
        "=" * 68,
        f"  EVALUACIÓN DE PEDIDO — {r['razon_social']}",
        f"  CUIT: {r['cuit']}    Cliente: {r['cliente_id']}",
        "=" * 68,
        "",
        "  DATOS DEL CLIENTE",
        f"    Límite de crédito ................. USD {c['limite_credito']:>12,.2f}",
        f"    Saldo cuenta corriente ............ USD {c['saldo_cuenta_corriente']:>12,.2f}",
        f"    Deuda vencida ..................... USD {c['deuda_vencida']:>12,.2f}",
        f"    Calificación Veraz ................ categoría {c['calificacion_veraz']}",
        f"    Último balance presentado ......... {c['fecha_ultimo_balance']} "
        f"({c['antiguedad_balance_meses']} meses de antigüedad)",
        "",
        "  CÁLCULO",
        f"    Límite de crédito ................. USD {c['limite_credito']:>12,.2f}",
        f"    x Factor Veraz (cat. {c['calificacion_veraz']}) ............ {c['factor_veraz']:>12.2f}",
        f"    x Factor balance {'(vencido)' if c['balance_vencido'] else '(vigente)'} ......... {c['factor_balance']:>12.2f}",
        f"    = Límite ajustado ................. USD {c['limite_ajustado']:>12,.2f}",
        f"    - Saldo cuenta corriente .......... USD {c['saldo_cuenta_corriente']:>12,.2f}",
        f"    = CRÉDITO DISPONIBLE .............. USD {c['credito_disponible']:>12,.2f}",
        "",
        f"    Monto del pedido .................. USD {r['monto_pedido']:>12,.2f}",
    ]
    if c["excedente"] > 0:
        lineas.append(f"    Excedente sobre el disponible ..... USD {c['excedente']:>12,.2f}")
    else:
        lineas.append(
            f"    Margen remanente .................. USD {c['credito_disponible'] - r['monto_pedido']:>12,.2f}"
        )

    lineas += [
        "",
        "  CONDICIONES",
        f"    [{marca(r['condiciones']['veraz_habilitado'])}] Calificación Veraz habilitada (distinta de 5)",
        f"    [{marca(r['condiciones']['sin_deuda_vencida'])}] Sin deuda vencida",
        f"    [{marca(r['condiciones']['monto_dentro_del_disponible'])}] Pedido dentro del crédito disponible",
        "",
        "-" * 68,
        f"  RESULTADO: {estado}",
        f"  {r['motivo']}",
        f"  Acción sugerida: {r['accion_sugerida']}",
        "=" * 68,
    ]
    return "\n".join(lineas)
