# Agente de Gestión Inteligente de Crédito y Liberación de Pedidos

Implementación de prueba del agente propuesto en el trabajo práctico, sobre una
base ficticia de **10 clientes**. El agente evalúa cada nuevo pedido contra la
política de crédito mediante **cálculos aritméticos** y devuelve si el cliente es
**APTO** o **NO APTO** para que se le libere el pedido.

Se puede usar de dos formas:

1. **Script de consola** (`evaluar_pedido.py`) — cargás el pedido por teclado y
   obtenés el veredicto con el cálculo desglosado. No necesita API key.
2. **Agente conversacional** (`agent.py`) — con la API de Claude, el agente
   interpreta el pedido en lenguaje natural, decide qué tools ejecutar y gestiona
   la cobranza o el escalamiento según el caso. Requiere API key.

Ambos usan **el mismo motor de política** (`mock/politica.py`), así que siempre
dan el mismo resultado.

---

## La política de crédito (la aritmética)

```
limite_ajustado    = limite_credito  x  factor_veraz  x  factor_balance
credito_disponible = limite_ajustado - saldo_cuenta_corriente
```

| Factor | Regla |
|---|---|
| **Factor Veraz** | Categoría 1 (normal) → `1.00` · Categoría 3 (con problemas) → `0.50` · Categoría 5 (irrecuperable) → `0.00` |
| **Factor balance** | Último balance con más de **18 meses** de antigüedad → `0.50` · Balance vigente → `1.00` |

El pedido es **APTO** solo si se cumplen las tres condiciones:

1. La calificación Veraz **no es categoría 5**.
2. El cliente **no registra deuda vencida**.
3. El monto del pedido **entra en el crédito disponible**.

Los parámetros están en `config/politica_credito.json`: se pueden cambiar los
factores, el tope de meses del balance o la tolerancia de deuda vencida **sin
tocar el código**.

---

## Base de clientes

`mock/clientes.json` — 10 clientes ficticios con: razón social, CUIT, contacto,
límite de crédito, fecha del último balance, saldo de cuenta corriente, deuda
vencida y calificación Veraz.

| ID | Razón social | Límite | Saldo CC | Vencida | Veraz | Último balance | Caso que ilustra |
|---|---|---:|---:|---:|:---:|---|---|
| CLI-1001 | Distribuidora del Plata S.A. | 150.000 | 40.000 | 0 | 1 | 2026-04-30 | Apto con margen amplio |
| CLI-1002 | Comercial Norte S.R.L. | 100.000 | 80.000 | 30.000 | 1 | 2026-03-31 | **El ejemplo del TP**: deuda vencida → cobranza |
| CLI-1003 | Mayorista Cuyo S.A. | 80.000 | 15.000 | 0 | 3 | 2025-12-31 | Veraz 3: límite al 50% |
| CLI-1004 | Insumos del Litoral S.A. | 120.000 | 20.000 | 0 | 1 | 2024-06-30 | Balance vencido: límite al 50% |
| CLI-1005 | Grupo Austral Comercial S.R.L. | 90.000 | 12.000 | 8.500 | 5 | 2026-05-31 | Veraz 5: rechazo automático |
| CLI-1006 | Ferretería Industrial Rosario S.A. | 60.000 | 10.000 | 0 | 3 | 2024-12-31 | Veraz 3 **+** balance vencido: límite al 25% |
| CLI-1007 | Almacenes del Sur S.R.L. | 45.000 | 41.000 | 0 | 1 | 2026-02-28 | Casi sin margen disponible |
| CLI-1008 | Tecno Aprovisionamiento S.A. | 200.000 | 0 | 0 | 1 | 2026-06-30 | Cuenta limpia, límite full |
| CLI-1009 | Corralón Pampeano | 25.000 | 5.000 | 1.200 | 1 | 2025-09-30 | Deuda vencida chica igual bloquea |
| CLI-1010 | Logística y Depósitos Andinos S.A. | 110.000 | 35.000 | 0 | 3 | 2024-03-31 | Ya sobregirado sobre el límite ajustado |

Ejemplos de cálculo:

- **CLI-1006** → `60.000 x 0,50 (Veraz 3) x 0,50 (balance vencido) = 15.000` de
  límite ajustado − `10.000` de saldo = **5.000 disponibles**.
- **CLI-1010** → `110.000 x 0,50 x 0,50 = 27.500` − `35.000` de saldo =
  **0 disponibles** (el cliente ya está sobregirado).

---

## 1. Instalación

Requiere Python 3.10+.

```bash
cd agente_credito_pedidos
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Para usar **solo el script de consola** no hace falta instalar nada: corre con
Python estándar.

---

## 2. Probar el script de consola

```bash
python evaluar_pedido.py --listar                          # ver los 10 clientes
python evaluar_pedido.py                                   # modo interactivo
python evaluar_pedido.py --cliente CLI-1006 --monto 5000   # modo directo
python evaluar_pedido.py --cliente CLI-1006 --monto 5000 --json
python evaluar_pedido.py --reset                           # restaurar la base inicial
```

En modo interactivo te pide el cliente (podés escribir el **ID** o el **CUIT**) y
el monto del pedido, y devuelve un reporte como este:

```
====================================================================
  EVALUACIÓN DE PEDIDO — Logística y Depósitos Andinos S.A.
  CUIT: 30-70112233-6    Cliente: CLI-1010
====================================================================

  CÁLCULO
    Límite de crédito ................. USD   110,000.00
    x Factor Veraz (cat. 3) ............         0.50
    x Factor balance (vencido) .........         0.50
    = Límite ajustado ................. USD    27,500.00
    - Saldo cuenta corriente .......... USD    35,000.00
    = CRÉDITO DISPONIBLE .............. USD         0.00

    Monto del pedido .................. USD    20,000.00
    Excedente sobre el disponible ..... USD    20,000.00

  CONDICIONES
    [OK  ] Calificación Veraz habilitada (distinta de 5)
    [OK  ] Sin deuda vencida
    [FALLA] Pedido dentro del crédito disponible

--------------------------------------------------------------------
  RESULTADO: NO APTO
====================================================================
```

Casos recomendados para la demo:

| Comando | Resultado esperado |
|---|---|
| `--cliente CLI-1001 --monto 80000` | APTO (disponible 110.000) |
| `--cliente CLI-1002 --monto 50000` | NO APTO — deuda vencida de 30.000 |
| `--cliente CLI-1005 --monto 5000` | NO APTO — Veraz categoría 5 |
| `--cliente CLI-1004 --monto 50000` | NO APTO — balance de 2024 reduce el límite a 60.000 |
| `--cliente CLI-1006 --monto 5000` | APTO justo en el límite (disponible 5.000) |
| `--cliente CLI-1008 --monto 200000` | APTO exacto en el borde |

---

## 3. Probar el agente conversacional

Necesitás una API key de Anthropic (se genera en https://platform.claude.com).

```bash
cp .env.example .env      # y pegá tu key en ANTHROPIC_API_KEY=...
python agent.py --scenario mock/escenario_ejemplo.json
```

Escenarios incluidos:

| Escenario | Qué demuestra |
|---|---|
| `mock/escenario_ejemplo.json` | El caso del TP: CLI-1002 con deuda vencida → el agente detecta que no es apto y activa la **gestión de cobranza** en lugar de liberar |
| `mock/escenario_ok.json` | Cliente dentro de política → **liberación directa** |
| `mock/escenario_veraz5.json` | Veraz categoría 5 → rechazo y **escalamiento a una persona** |
| `mock/escenario_balance_vencido.json` | Balance de hace 2 años → el agente explica por qué el límite se redujo a la mitad |

**Circuito completo del ejemplo del TP.** Corré el primer escenario y, cuando el
agente te informe la gestión de cobranza, respondé algo como *"el cliente acreditó
un pago de 30.000"*. El agente va a llamar a `registrar_pago`, reevaluar y liberar
el pedido: el disponible pasa de 20.000 a 50.000 y el pedido de 50.000 entra justo.

**Probar el control de acciones irreversibles.** En vez de informar el pago, pedile
que lo libere igual como excepción comercial. El agente va a intentar
`liberar_pedido` con `es_excepcion=true`, y `agent.py` **intercepta esa llamada y
te pide la aprobación por consola** antes de ejecutarla — así se prueba en código
el control de la sección "Límites" del TP. Además, la propia tool rechaza cualquier
intento de liberar un pedido NO APTO que no venga con excepción declarada.

---

## 4. Estructura

```
agente_credito_pedidos/
├── evaluar_pedido.py              # Script de consola: input por teclado -> APTO / NO APTO
├── agent.py                       # Agente conversacional (Claude API + tool use)
├── requirements.txt
├── .env.example
├── config/
│   ├── politica_credito.json      # Parámetros de la política (factores, tope de meses)
│   ├── tools.json                 # Las 6 tools en formato Anthropic API
│   ├── skills.json                # Las 6 skills: qué hacen, qué tools usan, cuándo se activan
│   └── agent_config.json          # Objetivo, modelo, límites e indicadores
├── mock/
│   ├── clientes.json              # Base de 10 clientes (se modifica al liberar pedidos)
│   ├── clientes_base.json         # Copia prístina para --reset
│   ├── politica.py                # MOTOR DE CÁLCULO: la aritmética de la decisión
│   ├── tools_impl.py              # Implementación de las 6 tools
│   └── escenario_*.json           # Escenarios de prueba para el agente
└── logs/
    └── registro_auditable.jsonl   # Traza de cada evaluación y acción (se genera solo)
```

### Las 6 tools

| Tool | Qué hace |
|---|---|
| `listar_clientes` | Devuelve la cartera, con filtro opcional por razón social / CUIT / ID |
| `consultar_credito_cliente` | Ficha crediticia completa de un cliente (acepta ID o CUIT) |
| `evaluar_politica_credito` | **Ejecuta el cálculo** y devuelve APTO / NO APTO con el desglose |
| `gestionar_cobranza` | Registra la acción de cobranza y fija el plazo de compromiso |
| `registrar_pago` | Acredita un pago: lo imputa a la deuda vencida y al saldo |
| `liberar_pedido` | Genera el documento ERP e imputa el monto al saldo. Rechaza pedidos NO APTOS salvo excepción aprobada |

---

## 5. Trazabilidad

Cada evaluación y cada acción quedan registradas en
`logs/registro_auditable.jsonl` (una línea JSON por evento), tanto si vienen del
script de consola como del agente. Es la base de los indicadores de la sección
"¿Cómo se evalúa?" del trabajo práctico.

Ojo: `liberar_pedido` y `registrar_pago` **modifican** `mock/clientes.json` (imputan
el pedido al saldo, descuentan el pago). Para volver al estado inicial:
`python evaluar_pedido.py --reset`.

---

## 6. Modelo

`config/agent_config.json` usa `"claude-sonnet-5"`. Si la API devuelve un error de
modelo no encontrado, verificá el identificador vigente en
https://platform.claude.com/docs/en/about-claude/models/overview y actualizalo ahí.

---

## 7. Relación con el documento del TP

| Archivo | Sección del documento |
|---|---|
| `config/tools.json` | 3 — Herramientas |
| `config/skills.json` | 3.1 — Skills del Agente |
| `mock/politica.py` + `config/politica_credito.json` | 4 — ¿Cómo funciona? (el flujo de decisión) |
| `config/agent_config.json` → `limites` | 6 — Límites |
| `config/agent_config.json` → `indicadores_desempeno`, `logs/` | 7 — ¿Cómo se evalúa? |
| `mock/escenario_ejemplo.json` | Ejemplo |
