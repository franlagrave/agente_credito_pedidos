"""
Implementación simulada (mock) de las tools del Agente de Gestión Inteligente
de Crédito y Liberación de Pedidos.

No se conecta a SAP ni a Veraz: lee la base ficticia de 10 clientes en
mock/clientes.json y aplica la política definida en config/politica_credito.json
a través del motor compartido mock/politica.py, de modo que el agente y el
script de consola evaluar_pedido.py den siempre exactamente el mismo resultado.

Cada función corresponde 1 a 1 con una tool declarada en config/tools.json.
"""

import json
import random
import string
from datetime import date, timedelta
from pathlib import Path

from .politica import cargar_clientes, cargar_politica, evaluar, meses_entre

BASE_DIR = Path(__file__).resolve().parent
CLIENTES_FILE = BASE_DIR / "clientes.json"
COBRANZAS_FILE = BASE_DIR / "cobranzas_estado.json"
LOG_FILE = BASE_DIR.parent / "logs" / "registro_auditable.jsonl"


# --------------------------------------------------------------------------
# Utilidades internas
# --------------------------------------------------------------------------

def _cargar_json(path, default):
    if not path.exists():
        return default
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _guardar_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def _log_auditable(evento: dict):
    """Registra cada acción para trazabilidad (skill Trazabilidad y Reporte)."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(json.dumps({"timestamp": date.today().isoformat(), **evento}, ensure_ascii=False) + "\n")


def _resolver_cliente(cliente_id: str):
    """Acepta un ID (CLI-1002) o un CUIT y devuelve (clave, datos) o (None, None)."""
    clientes = cargar_clientes()
    clave = cliente_id.strip().upper()
    if clave in clientes:
        return clave, clientes[clave]
    buscado = cliente_id.replace("-", "").replace(" ", "")
    for cid, c in clientes.items():
        if c["cuit"].replace("-", "") == buscado:
            return cid, c
    return None, None


def _actualizar_cliente(cliente_id: str, cambios: dict):
    """Persiste cambios de saldo/deuda en la base mock."""
    data = _cargar_json(CLIENTES_FILE, {"clientes": {}})
    data["clientes"][cliente_id].update(cambios)
    _guardar_json(CLIENTES_FILE, data)


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------

def consultar_credito_cliente(cliente_id: str) -> dict:
    clave, c = _resolver_cliente(cliente_id)
    if clave is None:
        resultado = {"error": f"Cliente '{cliente_id}' no encontrado en la base. Usá listar_clientes para ver la cartera."}
    else:
        antiguedad = meses_entre(c["fecha_ultimo_balance"])
        resultado = {
            "cliente_id": clave,
            "razon_social": c["razon_social"],
            "cuit": c["cuit"],
            "contacto": c["contacto"],
            "limite_credito": c["limite_credito"],
            "fecha_ultimo_balance": c["fecha_ultimo_balance"],
            "antiguedad_balance_meses": antiguedad,
            "saldo_cuenta_corriente": c["saldo_cuenta_corriente"],
            "deuda_vencida": c["deuda_vencida"],
            "calificacion_veraz": c["calificacion_veraz"],
        }
    _log_auditable({"tool": "consultar_credito_cliente", "input": {"cliente_id": cliente_id}, "output": resultado})
    return resultado


def listar_clientes(filtro: str | None = None) -> dict:
    clientes = cargar_clientes()
    filas = []
    for cid, c in clientes.items():
        if filtro:
            texto = f"{cid} {c['razon_social']} {c['cuit']}".lower()
            if filtro.lower() not in texto:
                continue
        filas.append({
            "cliente_id": cid,
            "razon_social": c["razon_social"],
            "cuit": c["cuit"],
            "limite_credito": c["limite_credito"],
            "saldo_cuenta_corriente": c["saldo_cuenta_corriente"],
            "deuda_vencida": c["deuda_vencida"],
            "calificacion_veraz": c["calificacion_veraz"],
            "fecha_ultimo_balance": c["fecha_ultimo_balance"],
        })
    resultado = {"cantidad": len(filas), "clientes": filas}
    _log_auditable({"tool": "listar_clientes", "input": {"filtro": filtro}, "output": {"cantidad": len(filas)}})
    return resultado


def evaluar_politica_credito(cliente_id: str, monto_pedido: float) -> dict:
    clave, c = _resolver_cliente(cliente_id)
    if clave is None:
        resultado = {"error": f"Cliente '{cliente_id}' no encontrado en la base."}
    else:
        cliente = {"cliente_id": clave, **c}
        resultado = evaluar(cliente, float(monto_pedido), cargar_politica())
    _log_auditable({
        "tool": "evaluar_politica_credito",
        "input": {"cliente_id": cliente_id, "monto_pedido": monto_pedido},
        "output": resultado,
    })
    return resultado


def gestionar_cobranza(cliente_id: str, monto_pedido: float, deuda_vencida: float, plazo_dias: int = 5) -> dict:
    clave, c = _resolver_cliente(cliente_id)
    if clave is None:
        resultado = {"error": f"Cliente '{cliente_id}' no encontrado en la base."}
        _log_auditable({"tool": "gestionar_cobranza", "input": {"cliente_id": cliente_id}, "output": resultado})
        return resultado

    estado = _cargar_json(COBRANZAS_FILE, {})
    fecha_limite = (date.today() + timedelta(days=plazo_dias)).isoformat()
    estado[clave] = {
        "razon_social": c["razon_social"],
        "monto_pedido": monto_pedido,
        "deuda_vencida": deuda_vencida,
        "fecha_limite": fecha_limite,
        "estado": "pendiente_respuesta",
    }
    _guardar_json(COBRANZAS_FILE, estado)

    resultado = {
        "cliente_id": clave,
        "razon_social": c["razon_social"],
        "accion": "gestion_cobranza_registrada",
        "deuda_vencida": deuda_vencida,
        "fecha_limite_compromiso": fecha_limite,
        "contacto_notificado": c["contacto"],
        "mensaje": (
            f"Se notificó a Ventas y se contactó a {c['razon_social']} ({c['contacto']}) "
            f"solicitando la acreditación de USD {deuda_vencida:,.2f} o un compromiso de pago "
            f"antes del {fecha_limite}."
        ),
    }
    _log_auditable({
        "tool": "gestionar_cobranza",
        "input": {"cliente_id": cliente_id, "monto_pedido": monto_pedido,
                  "deuda_vencida": deuda_vencida, "plazo_dias": plazo_dias},
        "output": resultado,
    })
    return resultado


def registrar_pago(cliente_id: str, monto_pago: float) -> dict:
    clave, c = _resolver_cliente(cliente_id)
    if clave is None:
        resultado = {"error": f"Cliente '{cliente_id}' no encontrado en la base."}
        _log_auditable({"tool": "registrar_pago", "input": {"cliente_id": cliente_id}, "output": resultado})
        return resultado

    monto_pago = float(monto_pago)
    vencida_previa = float(c["deuda_vencida"])
    saldo_previo = float(c["saldo_cuenta_corriente"])

    # El pago se imputa primero a la deuda vencida, el remanente al saldo.
    aplicado_a_vencida = min(monto_pago, vencida_previa)
    nueva_vencida = round(vencida_previa - aplicado_a_vencida, 2)
    nuevo_saldo = round(max(saldo_previo - monto_pago, 0.0), 2)

    _actualizar_cliente(clave, {"deuda_vencida": nueva_vencida, "saldo_cuenta_corriente": nuevo_saldo})

    resultado = {
        "cliente_id": clave,
        "razon_social": c["razon_social"],
        "monto_pago": monto_pago,
        "deuda_vencida_anterior": vencida_previa,
        "deuda_vencida_actual": nueva_vencida,
        "saldo_anterior": saldo_previo,
        "saldo_actual": nuevo_saldo,
        "mensaje": (
            f"Pago de USD {monto_pago:,.2f} acreditado. Deuda vencida: USD {vencida_previa:,.2f} "
            f"-> USD {nueva_vencida:,.2f}. Saldo cuenta corriente: USD {saldo_previo:,.2f} "
            f"-> USD {nuevo_saldo:,.2f}. Corresponde reevaluar el pedido."
        ),
    }
    _log_auditable({
        "tool": "registrar_pago",
        "input": {"cliente_id": cliente_id, "monto_pago": monto_pago},
        "output": resultado,
    })
    return resultado


def liberar_pedido(
    cliente_id: str,
    pedido_id: str,
    monto_pedido: float,
    es_excepcion: bool = False,
    aprobado_por: str | None = None,
) -> dict:
    entrada = {
        "cliente_id": cliente_id,
        "pedido_id": pedido_id,
        "monto_pedido": monto_pedido,
        "es_excepcion": es_excepcion,
        "aprobado_por": aprobado_por,
    }

    clave, c = _resolver_cliente(cliente_id)
    if clave is None:
        resultado = {"error": f"Cliente '{cliente_id}' no encontrado en la base."}
        _log_auditable({"tool": "liberar_pedido", "input": entrada, "output": resultado})
        return resultado

    if es_excepcion and not aprobado_por:
        resultado = {"error": "es_excepcion=true requiere indicar 'aprobado_por' (quién aprobó la excepción)."}
        _log_auditable({"tool": "liberar_pedido", "input": entrada, "output": resultado})
        return resultado

    # Control de seguridad: si el pedido NO es apto y no se declaró excepción, se rechaza.
    evaluacion = evaluar({"cliente_id": clave, **c}, float(monto_pedido), cargar_politica())
    if not evaluacion["apto"] and not es_excepcion:
        resultado = {
            "estado": "rechazado",
            "cliente_id": clave,
            "pedido_id": pedido_id,
            "mensaje": (
                "No se puede liberar: el pedido NO es apto según la política de crédito. "
                f"{evaluacion['motivo']} Para liberarlo igual se requiere una excepción "
                "aprobada por una persona (es_excepcion=true + aprobado_por)."
            ),
            "evaluacion": evaluacion,
        }
        _log_auditable({"tool": "liberar_pedido", "input": entrada, "output": resultado})
        return resultado

    # Imputa el pedido al saldo de cuenta corriente del cliente.
    nuevo_saldo = round(float(c["saldo_cuenta_corriente"]) + float(monto_pedido), 2)
    _actualizar_cliente(clave, {"saldo_cuenta_corriente": nuevo_saldo})

    numero_erp = "ERP-" + "".join(random.choices(string.digits, k=6))
    resultado = {
        "cliente_id": clave,
        "razon_social": c["razon_social"],
        "pedido_id": pedido_id,
        "monto_pedido": monto_pedido,
        "estado": "liberado_por_excepcion" if es_excepcion else "liberado",
        "numero_documento_erp": numero_erp,
        "aprobado_por": aprobado_por,
        "saldo_cuenta_corriente_actualizado": nuevo_saldo,
        "mensaje": (
            f"Pedido {pedido_id} de {c['razon_social']} liberado por USD {monto_pedido:,.2f}. "
            f"Documento ERP {numero_erp} generado. Nuevo saldo de cuenta corriente: USD {nuevo_saldo:,.2f}. "
            "Continúa con entrega y facturación."
        ),
    }
    _log_auditable({"tool": "liberar_pedido", "input": entrada, "output": resultado})
    return resultado


# Despachador: nombre de tool (tal como la llama el modelo) -> función Python
TOOL_DISPATCH = {
    "consultar_credito_cliente": consultar_credito_cliente,
    "listar_clientes": listar_clientes,
    "evaluar_politica_credito": evaluar_politica_credito,
    "gestionar_cobranza": gestionar_cobranza,
    "registrar_pago": registrar_pago,
    "liberar_pedido": liberar_pedido,
}
