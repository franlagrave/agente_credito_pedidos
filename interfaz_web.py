#!/usr/bin/env python3
"""
Interfaz web local para ver en vivo la conversación entre Comercial y el
agente de crédito.
----------------------------------------------------------------------
Es la misma lógica de agent.py (config, tools, política de crédito), pero
en vez de correr por consola, se sirve como una página de chat en el
navegador. Cada paso del agente (texto, tool ejecutada, resultado, pedido
de aprobación humana) se transmite al navegador en tiempo real por
Server-Sent Events (SSE) a medida que ocurre, en lugar de esperar a que
termine todo el turno.

Pensada para correr en local, para una sola persona/conversación a la vez
(no maneja múltiples sesiones ni pestañas concurrentes) — alcanza para
mostrar en vivo cómo trabaja el agente, que es el objetivo de esta demo.

Uso:
    export ANTHROPIC_API_KEY="tu-api-key"
    python interfaz_web.py
    -> abrir http://127.0.0.1:5000 en el navegador
"""

import json
import os
import queue
import sys
import threading

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

try:
    import anthropic
except ImportError:
    print("Falta el paquete 'anthropic'. Instalalo con: pip install -r requirements.txt")
    sys.exit(1)

try:
    from flask import Flask, Response, render_template, request
except ImportError:
    print("Falta el paquete 'flask'. Instalalo con: pip install -r requirements.txt")
    sys.exit(1)

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

from agent import cargar_config, construir_system_prompt, _headers_workspace
from mock.tools_impl import TOOL_DISPATCH

MAX_IDAS_Y_VUELTAS_POR_TURNO = 8

api_key = os.environ.get("ANTHROPIC_API_KEY")
if not api_key:
    print("Falta la variable de entorno ANTHROPIC_API_KEY. Copiá .env.example a .env y completá tu key,")
    print("o exportala en la terminal: export ANTHROPIC_API_KEY=sk-ant-...")
    sys.exit(1)

agent_config, tools, skills = cargar_config()
system_prompt = construir_system_prompt(agent_config, skills)
client = anthropic.Anthropic(api_key=api_key, default_headers=_headers_workspace())

app = Flask(__name__)

# Estado global: una sola conversación activa a la vez (ver docstring).
messages: list = []
eventos: "queue.Queue[dict]" = queue.Queue()
aprobacion_pendiente = {"event": None, "decision": None}


def emitir(tipo: str, **datos):
    eventos.put({"tipo": tipo, **datos})


def pedir_aprobacion_web(tool_input: dict) -> tuple[bool, str]:
    """Reemplaza a pedir_aprobacion_humana() de agent.py: en vez de cortar
    en un input() de consola, avisa al navegador por SSE y bloquea este
    hilo hasta que llegue la decisión por POST /aprobar."""
    ev = threading.Event()
    aprobacion_pendiente["event"] = ev
    aprobacion_pendiente["decision"] = None
    emitir("aprobacion_requerida", tool_input=tool_input)
    ev.wait()
    decision = aprobacion_pendiente["decision"] or {}
    return bool(decision.get("aprobar")), decision.get("aprobado_por") or ""


def ejecutar_tool(nombre: str, tool_input: dict) -> dict:
    if nombre not in TOOL_DISPATCH:
        return {"error": f"Tool desconocida: {nombre}"}

    if nombre == "liberar_pedido" and tool_input.get("es_excepcion"):
        aprobado, aprobado_por = pedir_aprobacion_web(tool_input)
        emitir("aprobacion_resuelta", aprobado=aprobado, aprobado_por=aprobado_por)
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


def procesar_turno(mensaje_usuario: str):
    messages.append({"role": "user", "content": mensaje_usuario})
    try:
        for _ in range(MAX_IDAS_Y_VUELTAS_POR_TURNO):
            emitir("pensando")
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
                emitir("agente_texto", texto=texto)

            if response.stop_reason != "tool_use":
                break

            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                emitir("tool_llamada", nombre=block.name, input=block.input)
                resultado = ejecutar_tool(block.name, block.input)
                emitir("tool_resultado", nombre=block.name, resultado=resultado)
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(resultado, ensure_ascii=False),
                })
            messages.append({"role": "user", "content": tool_results})
        else:
            emitir("error", mensaje="Se alcanzó el máximo de idas y vueltas con tools para este turno.")
    except Exception as e:
        emitir("error", mensaje=str(e))
    finally:
        emitir("fin_turno")


@app.route("/")
def index():
    return render_template("chat.html", nombre_agente=agent_config["nombre"], modelo=agent_config["modelo"])


@app.route("/enviar", methods=["POST"])
def enviar():
    mensaje = (request.get_json(silent=True) or {}).get("mensaje", "").strip()
    if not mensaje:
        return {"ok": False, "error": "mensaje vacío"}, 400
    emitir("usuario", texto=mensaje)
    threading.Thread(target=procesar_turno, args=(mensaje,), daemon=True).start()
    return {"ok": True}


@app.route("/aprobar", methods=["POST"])
def aprobar():
    data = request.get_json(silent=True) or {}
    ev = aprobacion_pendiente.get("event")
    if ev is None:
        return {"ok": False, "error": "no hay ninguna aprobación pendiente"}, 400
    aprobacion_pendiente["decision"] = {
        "aprobar": bool(data.get("aprobar")),
        "aprobado_por": (data.get("aprobado_por") or "").strip(),
    }
    ev.set()
    return {"ok": True}


@app.route("/reiniciar", methods=["POST"])
def reiniciar():
    messages.clear()
    emitir("reiniciado")
    return {"ok": True}


@app.route("/stream")
def stream():
    def generar():
        yield ": conectado\n\n"
        while True:
            evento = eventos.get()
            yield f"data: {json.dumps(evento, ensure_ascii=False)}\n\n"

    return Response(generar(), mimetype="text/event-stream")


if __name__ == "__main__":
    puerto = int(os.environ.get("PORT", 5000))
    host = "0.0.0.0" if "PORT" in os.environ else "127.0.0.1"
    print(f"\nAgente: {agent_config['nombre']}  (modelo: {agent_config['modelo']})")
    print(f"Interfaz web disponible en http://{host}:{puerto}  (Ctrl+C para cortar)\n")
    app.run(host=host, port=puerto, debug=False, threaded=True)
