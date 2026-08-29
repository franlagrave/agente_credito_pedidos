# Contexto del proyecto

Trabajo práctico universitario (Comisión A, Grupo 3): **Agente de Gestión
Inteligente de Crédito y Liberación de Pedidos**. Implementación de prueba de un
agente que evalúa si un pedido puede liberarse a un cliente según su situación
crediticia. Todo el código está en español (nombres de funciones, variables,
mensajes) — mantener esa convención.

No hay conexión real a SAP ni a Veraz: los datos son una base ficticia de 10
clientes en `mock/clientes.json`.

## Arquitectura

Hay **dos frentes** que comparten el mismo motor de cálculo:

1. `evaluar_pedido.py` — script de consola, sin API key. Pide cliente y monto por
   teclado y devuelve APTO / NO APTO con el cálculo desglosado.
2. `agent.py` — agente conversacional sobre la API de Claude (tool use). Requiere
   `ANTHROPIC_API_KEY`.

**`mock/politica.py` es la única fuente de verdad del cálculo.** Tanto el script
como la tool `evaluar_politica_credito` lo llaman. Si se cambia la aritmética, se
cambia ahí y en ningún otro lado — de lo contrario los dos frentes empiezan a dar
resultados distintos, que es el bug más grave posible en este proyecto.

## La política de crédito

```
limite_ajustado    = limite_credito x factor_veraz x factor_balance
credito_disponible = limite_ajustado - saldo_cuenta_corriente
```

- `factor_veraz`: categoría 1 → 1.00 | categoría 3 → 0.50 | categoría 5 → 0.00
- `factor_balance`: 0.50 si el último balance tiene más de 18 meses, 1.00 si no

APTO solo si: Veraz ≠ 5, **y** sin deuda vencida, **y** monto ≤ crédito disponible.

Los parámetros viven en `config/politica_credito.json` — se ajustan ahí, sin tocar
código.

## Reglas de negocio que no se negocian

Estas tres acciones son **irreversibles** y requieren aprobación humana explícita
antes de ejecutarse (sección "Límites" del TP):

1. Liberar un pedido que incumple la política de crédito
2. Modificar un límite de crédito
3. Aprobar una excepción comercial

Están defendidas en dos capas, y **ambas deben mantenerse**:

- `mock/tools_impl.py` → `liberar_pedido()` reevalúa la política y rechaza el
  pedido si no es apto y no vino con `es_excepcion=true` + `aprobado_por`.
- `agent.py` → `pedir_aprobacion_humana()` intercepta la llamada y pide
  confirmación por consola antes de ejecutarla.

Nunca debilitar estos controles para "simplificar" una prueba.

## Estado mutable

`liberar_pedido` y `registrar_pago` **modifican `mock/clientes.json`** (imputan el
pedido al saldo, descuentan el pago). Después de probar, restaurar con:

```
python evaluar_pedido.py --reset
```

`mock/clientes_base.json` es la copia prístina — no editarla salvo que se quiera
cambiar la base de clientes en forma permanente.

## Comandos frecuentes

```bash
python evaluar_pedido.py --listar                          # ver los 10 clientes
python evaluar_pedido.py                                   # modo interactivo
python evaluar_pedido.py --cliente CLI-1006 --monto 5000   # caso puntual
python evaluar_pedido.py --reset                           # restaurar la base

python agent.py --scenario mock/escenario_ejemplo.json     # agente, caso del TP
```

## Casos de prueba de referencia

Si se toca `mock/politica.py`, verificar que estos sigan dando lo mismo:

| Cliente | Monto | Esperado |
|---|---:|---|
| CLI-1001 | 80.000 | APTO (disponible 110.000) |
| CLI-1002 | 50.000 | NO APTO — deuda vencida 30.000 → `gestionar_cobranza` |
| CLI-1005 | 5.000 | NO APTO — Veraz 5 → `escalar_a_aprobacion_humana` |
| CLI-1004 | 50.000 | NO APTO — balance vencido reduce el límite a 60.000 |
| CLI-1006 | 5.000 | APTO justo en el borde (disponible 5.000) |
| CLI-1008 | 200.000 | APTO exacto; con 200.001 debe dar NO APTO |

Circuito completo del ejemplo del TP: CLI-1002 pedido 50.000 → no apto → cobranza
→ `registrar_pago(30000)` → disponible pasa a 50.000 → APTO → liberar.

## Documento del TP

El código implementa el documento entregado. Correspondencias:

- `config/tools.json` → sección 3 (Herramientas)
- `config/skills.json` → sección 3.1 (Skills del Agente)
- `mock/politica.py` → sección 4 (¿Cómo funciona?)
- `config/agent_config.json` → `limites` → sección 6 (Límites)
- `logs/registro_auditable.jsonl` → sección 7 (¿Cómo se evalúa?)

Si se agrega una tool o una skill al código, actualizar también el JSON de config
correspondiente **y** avisar de que el documento del TP quedó desactualizado.
