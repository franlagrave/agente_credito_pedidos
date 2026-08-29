"""
Agente de Gestión Inteligente de Crédito y Liberación de Pedidos
------------------------------------------------------------------
Runner de prueba en consola, usando la API de Claude (Anthropic) con tool use.

Uso:
    export ANTHROPIC_API_KEY="tu-api-key"
    pip install -r requirements.txt
    python agent.py
    python agent.py --scenario mock/escenario_ejemplo.json   # arranca con un caso predefinido

Este script:
  1) Carga la config del agente (config/agent_config.json), las tools
     (config/tools.json) y las skills (config/skills.json).
  2) Arma el system prompt combinando el objetivo, las reglas fijas y la
     descripción de cada skill.
  3) Corre el loop de conversación con tool use: cuando el modelo pide
     ejecutar una tool, la despacha a mock/tools_impl.py (datos simulados).
  4) Antes de liberar un pedido en excepción (es_excepcion=true), pide
     aprobación humana por consola -- así se prueba el punto de control
     descrito en la sección "Límites" del trabajo práctico.
"""

import argparse
import json
import os
import sys
from pathlib import Path

try:
    import anthropic
except ImportError:
    print("Falta el paquete 'anthropic'. Instalalo con: pip install -r requirements.txt")
    sys.exit(1)

try:
    from dotenv import load_dotenv

    load_dotenv()  # carga ANTHROPIC_API_KEY desde un archivo .env si existe (opcional)
except ImportError:
    pass  # python-dotenv es opcional; si no está instalado, usá variables de entorno del sistema

from mock.tools_impl import TOOL_DISPATCH

BASE_DIR = Path(__file__).resolve().parent
CONFIG_DIR = BASE_DIR / "config"


def cargar_config():
    with open(CONFIG_DIR / "agent_config.json", "r", encoding="utf-8") as f:
        agent_config = json.load(f)
    with open(CONFIG_DIR / "tools.json", "r", encoding="utf-8") as f:
        tools = json.load(f)
    with open(CONFIG_DIR / "skills.json", "r", encoding="utf-8") as f:
        skills = json.load(f)
    return agent_config, tools, skills


def construir_system_prompt(agent_config, skills):
    base = agent_config["system_prompt_base"].format(
        nombre=agent_config["nombre"], objetivo=agent_config["objetivo"]
    )
    lineas_skills = ["\nSkills disponibles:"]
    for s in skills:
        tools_str = ", ".join(s["tools"]) if s["tools"] else "(ninguna — capacidad de lenguaje propia)"
        alerta = " [REQUIERE APROBACIÓN HUMANA]" if s.get("requiere_aprobacion_humana") else ""
        lineas_skills.append(
            f"- {s['nombre']}{alerta}: {s['descripcion']}\n"
            f"  Tools: {tools_str}\n"
            f"  Se activa cuando: {s['activa_cuando']}\n"
            f"  Instrucciones: {s['instrucciones']}"
        )
    return base + "\n" + "\n".join(lineas_skills)


def pedir_aprobacion_humana(tool_input: dict) -> tuple[bool, str]:
    print("\n" + "=" * 70)
    print("ACCIÓN IRREVERSIBLE DETECTADA: liberar_pedido con es_excepcion=true")
    print("El agente necesita aprobación humana antes de continuar.")
    print(json.dumps(tool_input, ensure_ascii=False, indent=2))
    print("=" * 70)
    respuesta = input("¿Aprobás esta excepción? (aprobar / rechazar): ").strip().lower()
    if respuesta.startswith("aprob"):
        aprobado_por = input("Tu nombre o rol (para dejarlo registrado): ").strip() or "Gestor de Crédito"
        return True, aprobado_por
    return False, ""


def ejecutar_tool(nombre: str, tool_input: dict) -> dict:
    if nombre not in TOOL_DISPATCH:
        return {"error": f"Tool desconocida: {nombre}"}

    if nombre == "liberar_pedido" and tool_input.get("es_excepcion"):
        aprobado, aprobado_por = pedir_aprobacion_humana(tool_input)
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", help="Path a un JSON con el mensaje inicial (ver mock/escenario_ejemplo.json)")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("Falta la variable de entorno ANTHROPIC_API_KEY. Copiá .env.example a .env y completá tu key,")
        print("o exportala en la terminal: export ANTHROPIC_API_KEY=sk-ant-...")
        sys.exit(1)

    agent_config, tools, skills = cargar_config()
    system_prompt = construir_system_prompt(agent_config, skills)
    client = anthropic.Anthropic(api_key=api_key)

    messages = []

    if args.scenario:
        with open(args.scenario, "r", encoding="utf-8") as f:
            escenario = json.load(f)
        primer_mensaje = escenario["mensaje_inicial"]
        print(f"\n[Escenario: {escenario.get('nombre', args.scenario)}]")
        print(f"Usuario: {primer_mensaje}\n")
        messages.append({"role": "user", "content": primer_mensaje})
    else:
        primer_mensaje = input("Usuario (describí el pedido a evaluar): ").strip()
        messages.append({"role": "user", "content": primer_mensaje})

    print(f"\n[Agente: {agent_config['nombre']}]  (modelo: {agent_config['modelo']})")
    print("Escribí 'salir' en cualquier momento para terminar.\n")

    while True:
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

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                print(f"  -> ejecutando tool: {block.name}({json.dumps(block.input, ensure_ascii=False)})")
                resultado = ejecutar_tool(block.name, block.input)
                print(f"     resultado: {json.dumps(resultado, ensure_ascii=False)}\n")
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": json.dumps(resultado, ensure_ascii=False),
                    }
                )
            messages.append({"role": "user", "content": tool_results})
            continue  # volvemos a llamar al modelo con los resultados, sin pedir input nuevo

        # stop_reason == "end_turn": el agente terminó de responder, pedimos el próximo mensaje humano
        siguiente = input("Usuario: ").strip()
        if siguiente.lower() in {"salir", "exit", "quit"}:
            print("Fin de la sesión. Revisá logs/registro_auditable.jsonl para ver la traza completa.")
            break
        messages.append({"role": "user", "content": siguiente})


if __name__ == "__main__":
    main()
