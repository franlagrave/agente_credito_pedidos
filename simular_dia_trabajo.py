#!/usr/bin/env python3
"""
Simulación de un día de trabajo del agente de crédito.
--------------------------------------------------------
Corre 5 casos (mock/escenarios_dia_trabajo.json) contra el agente real
(la misma config y las mismas tools que usa agent.py), simulando las
consultas que le llegarían de parte del equipo comercial durante una
jornada: estado de cuenta de un cliente y evaluación de un pedido nuevo
para ver si se puede aprobar o qué necesita para aprobarse.

Cada caso es una conversación nueva e independiente (como si fueran
5 tickets distintos que le llegan al agente ese día). Los casos cubren:
  1. Cliente dentro de política -> liberación directa.
  2. Deuda vencida -> gestionar_cobranza -> pago -> reevaluación -> APTO.
  3. Balance desactualizado -> límite reducido a la mitad -> NO APTO.
  4. Calificación Veraz irrecuperable -> escalamiento -> excepción
     comercial con aprobación humana (acá se ejercita el control de
     "Límites" del TP; ver la nota más abajo).
  5. Caso límite exacto (el monto pedido es igual al crédito disponible,
     y luego un dólar por encima) para mostrar la precisión del cálculo.

Nota sobre la aprobación humana: agent.py, en modo interactivo, corta la
ejecución y pide la decisión por consola (pedir_aprobacion_humana). Como
esta rutina corre los 5 casos de punta a punta sin intervención, esa
decisión se toma de una respuesta pre-cargada en el escenario
("aprobacion_excepcion"), dejada explícita en cada print/línea de Markdown
como "[SIMULACIÓN]" para no confundirla con una aprobación real. La
reevaluación de tools_impl.liberar_pedido (que igual exige es_excepcion +
aprobado_por) sigue intacta y es la que de verdad bloquea la excepción si
falta algo.

Uso:
    export ANTHROPIC_API_KEY="tu-api-key"
    python simular_dia_trabajo.py

Al terminar:
  - queda un Markdown legible de toda la corrida en
    logs/simulacion_dia_trabajo.md (para adjuntar al TP o revisar sin
    tener que releer la consola).
  - la base de clientes queda modificada por los pedidos liberados y el
    pago registrado durante la corrida (igual que al usar evaluar_pedido.py
    o agent.py a mano). Para dejarla como estaba:
        python evaluar_pedido.py --reset
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    # La consola de Windows suele usar cp1252, que no puede imprimir buena
    # parte del texto (acentos, emojis) que el modelo devuelve.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

try:
    import anthropic
except ImportError:
    print("Falta el paquete 'anthropic'. Instalalo con: pip install -r requirements.txt")
    sys.exit(1)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agent import cargar_config, construir_system_prompt, _headers_workspace
from mock.tools_impl import TOOL_DISPATCH

BASE_DIR = Path(__file__).resolve().parent
ESCENARIOS_FILE = BASE_DIR / "mock" / "escenarios_dia_trabajo.json"
MD_FILE = BASE_DIR / "logs" / "simulacion_dia_trabajo.md"
MAX_IDAS_Y_VUELTAS_POR_TURNO = 8


def pedir_aprobacion_simulada(tool_input: dict, decision: dict | None, md: list[str]) -> tuple[bool, str]:
    decision = decision or {}
    aprobar = bool(decision.get("aprobar"))
    aprobado_por = decision.get("aprobado_por") or ""

    print("\n" + "=" * 70)
    print("ACCIÓN IRREVERSIBLE DETECTADA: liberar_pedido con es_excepcion=true")
    print("En una corrida interactiva (agent.py) acá se corta y se pide la")
    print("aprobación humana explícita por consola. Esta rutina de demo no es")
    print("interactiva, así que usa la decisión pre-cargada en el escenario:")
    print(json.dumps(tool_input, ensure_ascii=False, indent=2))

    md.append(
        "> **Acción irreversible detectada:** `liberar_pedido` con `es_excepcion=true`.\n"
        "> En una corrida interactiva (`agent.py`) acá se corta la ejecución y se pide "
        "aprobación humana explícita por consola. Esta rutina no es interactiva, así que "
        "usa la decisión pre-cargada en el escenario — marcada como **[SIMULACIÓN]** para "
        "no confundirla con una aprobación real."
    )

    if aprobar:
        print(f"[SIMULACIÓN] Aprobado por: {aprobado_por or '(sin nombre informado)'}")
        md.append(f"\n**[SIMULACIÓN] Decisión: APROBADA** — por: {aprobado_por or '(sin nombre informado)'}\n")
    else:
        print("[SIMULACIÓN] Rechazado — el escenario no trae una aprobación cargada.")
        md.append("\n**[SIMULACIÓN] Decisión: RECHAZADA** — el escenario no trae una aprobación cargada.\n")
    print("=" * 70)
    return aprobar, aprobado_por


def ejecutar_tool(nombre: str, tool_input: dict, decision_excepcion: dict | None, md: list[str]) -> dict:
    if nombre not in TOOL_DISPATCH:
        return {"error": f"Tool desconocida: {nombre}"}

    if nombre == "liberar_pedido" and tool_input.get("es_excepcion"):
        aprobado, aprobado_por = pedir_aprobacion_simulada(tool_input, decision_excepcion, md)
        if not aprobado:
            return {
                "estado": "rechazado_por_humano",
                "mensaje": "La persona responsable rechazó la excepción. El pedido queda bloqueado.",
            }
        tool_input = {**tool_input, "aprobado_por": aprobado_por}

    try:
        return TOOL_DISPATCH[nombre](**tool_input)
    except TypeError as e:
        return {"error": f"Argumentos inválidos para {nombre}: {e}"}


def correr_turno(client, agent_config, system_prompt, tools, messages: list, mensaje_usuario: str,
                  decision_excepcion: dict | None, md: list[str]):
    print(f"Comercial: {mensaje_usuario}\n")
    md.append(f"**Comercial:** {mensaje_usuario}\n")
    messages.append({"role": "user", "content": mensaje_usuario})

    for ronda in range(1, MAX_IDAS_Y_VUELTAS_POR_TURNO + 1):
        response = client.messages.create(
            model=agent_config["modelo"],
            max_tokens=agent_config.get("max_tokens", 1500),
            system=system_prompt,
            tools=tools,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        texto = "".join(block.text for block in response.content if block.type == "text")
        if texto:
            print(f"Agente: {texto}\n")
            md.append(f"**Agente:** {texto}\n")

        if response.stop_reason != "tool_use":
            return

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            print(f"  -> ejecutando tool: {block.name}({json.dumps(block.input, ensure_ascii=False)})")
            resultado = ejecutar_tool(block.name, block.input, decision_excepcion, md)
            print(f"     resultado: {json.dumps(resultado, ensure_ascii=False)}\n")

            md.append(
                f"<details>\n<summary>Tool ejecutada: <code>{block.name}</code></summary>\n\n"
                f"Input:\n\n```json\n{json.dumps(block.input, ensure_ascii=False, indent=2)}\n```\n\n"
                f"Resultado:\n\n```json\n{json.dumps(resultado, ensure_ascii=False, indent=2)}\n```\n\n"
                f"</details>\n"
            )

            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": json.dumps(resultado, ensure_ascii=False),
            })
        messages.append({"role": "user", "content": tool_results})

    print("  !! Se alcanzó el máximo de idas y vueltas con tools para este turno; sigo con el próximo.\n")
    md.append("> ⚠ Se alcanzó el máximo de idas y vueltas con tools para este turno.\n")


def main():
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Falta la variable de entorno ANTHROPIC_API_KEY. Copiá .env.example a .env y completá tu key,")
        print("o exportala en la terminal: export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    with open(ESCENARIOS_FILE, "r", encoding="utf-8") as f:
        guion = json.load(f)

    agent_config, tools, skills = cargar_config()
    system_prompt = construir_system_prompt(agent_config, skills)
    client = anthropic.Anthropic(api_key=api_key, default_headers=_headers_workspace())

    casos = guion["casos"]
    print("\n" + "#" * 70)
    print(f"# SIMULACIÓN DE UN DÍA DE TRABAJO — {len(casos)} consultas del equipo comercial")
    print(f"# Agente: {agent_config['nombre']}  (modelo: {agent_config['modelo']})")
    print("#" * 70)

    md: list[str] = [
        "# Simulación de un día de trabajo — Agente de Gestión de Crédito\n",
        f"Fecha de la corrida: {date.today().isoformat()}  \n"
        f"Agente: {agent_config['nombre']}  \n"
        f"Modelo: `{agent_config['modelo']}`  \n"
        f"Casos: {len(casos)}\n",
        (
            "Cada caso es una conversación nueva e independiente, como si fueran tickets "
            "distintos que le llegan al agente de crédito de parte del equipo comercial en "
            "el mismo día: una consulta de estado de cuenta seguida de la evaluación de un "
            "pedido nuevo, para ver si se puede aprobar y, si no, qué necesita para "
            "aprobarse.\n"
        ),
        "---\n",
    ]

    for i, caso in enumerate(casos, start=1):
        print("\n" + "=" * 70)
        print(f"CASO {i}/{len(casos)} — {caso['nombre']}")
        print("=" * 70 + "\n")

        md.append(f"## Caso {i} — {caso['nombre']}\n")

        messages = []
        for mensaje_usuario in caso["turnos"]:
            correr_turno(
                client, agent_config, system_prompt, tools, messages,
                mensaje_usuario, caso.get("aprobacion_excepcion"), md,
            )

        md.append("---\n")

    md.append(
        "\nTraza completa y auditable (machine-readable) en "
        "`logs/registro_auditable.jsonl`.\n"
    )

    MD_FILE.parent.mkdir(parents=True, exist_ok=True)
    MD_FILE.write_text("\n".join(md), encoding="utf-8")

    print("\n" + "#" * 70)
    print("# Fin de la jornada simulada.")
    print(f"# Markdown legible de la corrida: {MD_FILE}")
    print("# Traza completa y auditable en logs/registro_auditable.jsonl")
    print("# Para dejar la base de clientes como estaba: python evaluar_pedido.py --reset")
    print("#" * 70 + "\n")


if __name__ == "__main__":
    main()
