# Agente de Gestión Inteligente de Crédito y Liberación de Pedidos

**Trabajo Práctico — Comisión A, Grupo 3**

---

## 1. Objetivo del trabajo

El objetivo de este trabajo fue diseñar e implementar un **agente de inteligencia artificial** capaz de resolver un problema concreto de la vida real dentro de una organización: la revisión de crédito y liberación de pedidos en el ciclo **Order-to-Cash** (del pedido al cobro).

En cualquier empresa que vende a cuenta corriente, cada pedido nuevo de un cliente tiene que pasar por un control: ¿el cliente tiene crédito disponible para esta compra? ¿tiene deudas vencidas? ¿su situación crediticia (Veraz) permite la operación? Hoy ese control suele hacerlo una persona a mano, revisando planillas y sistemas, lo que genera demoras, pedidos bloqueados innecesariamente y decisiones poco consistentes entre un analista y otro.

La propuesta fue construir un agente que:

- automatice ese análisis aplicando siempre la misma política de crédito, de forma consistente y auditable;
- explique cada decisión con el cálculo a la vista (nada de "caja negra");
- sepa cuándo **no** puede decidir solo — y en esos casos, se detenga y pida aprobación humana antes de ejecutar una acción irreversible.

Este último punto fue central en el trabajo: un agente que automatiza pero **no reemplaza el criterio humano en las decisiones de mayor riesgo** (liberar un pedido que incumple la política, modificar un límite de crédito, o aprobar una excepción comercial).

No hay conexión real a SAP ni a Veraz — se trabajó sobre una base ficticia de 10 clientes, pensada para poder mostrar el comportamiento del agente en distintos escenarios sin depender de sistemas productivos reales.

---

## 2. Herramientas utilizadas

| Herramienta | Qué es | Para qué se usó en este trabajo |
|---|---|---|
| **Python** | Lenguaje de programación de propósito general. | Es el lenguaje en el que está escrito todo el proyecto: el motor de cálculo de la política de crédito, los scripts de consola y el runner que conversa con la API de Claude. |
| **Visual Studio Code (VS Code)** | Editor de código fuente. | Entorno donde se escribió, organizó y probó el código del proyecto (archivos `.py`, `.json`, `.md`). |
| **Claude Code** | Asistente de IA para desarrollo de software, que corre integrado en la terminal / VS Code. | Se usó como copiloto de desarrollo: diseñar la arquitectura, escribir el código de cada script, generar los archivos de configuración (skills y tools), redactar la documentación (`CLAUDE.md`, este mismo archivo) y correr pruebas de validación en cada paso. |
| **API de Claude (Anthropic)** | Servicio en la nube que permite enviarle un mensaje a un modelo de lenguaje (Claude) y, opcionalmente, darle acceso a "herramientas" (tools) que puede decidir ejecutar. | Es el motor conversacional del agente: interpreta los pedidos en lenguaje natural del equipo comercial y decide qué tools ejecutar para resolverlos (ver sección 4). |
| **Git** | Sistema de control de versiones. | Historial de cambios del proyecto y control de qué archivos se modifican en cada etapa. |
| **JSON** | Formato de datos estructurado, legible por humanos y máquinas. | Formato elegido para toda la configuración del agente (política de crédito, definición de tools, definición de skills) y para la base de clientes ficticia — así los parámetros de negocio se pueden ajustar sin tocar código. |
| **openpyxl** (librería de Python) | Librería para leer y escribir archivos `.xlsx` de Excel. | Permite dar de alta clientes nuevos completando una planilla Excel, en lugar de editar el JSON a mano (ver sección 5). |
| **python-dotenv** (librería de Python) | Librería que carga variables de entorno desde un archivo `.env`. | Permite guardar la API key de Anthropic en un archivo local (`.env`, excluido de git) en lugar de tenerla escrita en el código o expuesta en el historial de versiones. |

---

## 3. Cómo se creó y desarrolló el agente

### 3.1. Decisión de arquitectura: dos frentes, un solo motor de cálculo

Desde el principio se decidió separar el proyecto en dos frentes que **comparten la misma lógica de cálculo**, para poder mostrar el trabajo de dos maneras distintas:

1. **`evaluar_pedido.py`** — un script de consola simple, sin necesidad de API key. Se le indica un cliente y un monto, y devuelve APTO / NO APTO con el cálculo desglosado. Sirve para probar la aritmética de la política de crédito de forma aislada y sin costo.
2. **`agent.py`** — el agente conversacional propiamente dicho, que usa la API de Claude con *tool use* para interpretar pedidos en lenguaje natural y orquestar todo el proceso de principio a fin.

La razón de compartir un único motor de cálculo (`mock/politica.py`) es evitar el peor bug posible en un proyecto así: que el script de consola y el agente conversacional den **resultados distintos** para el mismo caso. Por eso toda la aritmética vive en un solo lugar, y tanto `evaluar_pedido.py` como la tool `evaluar_politica_credito` (que usa el agente) llaman exactamente a la misma función.

### 3.2. La política de crédito

El corazón del negocio es esta fórmula, definida en `config/politica_credito.json` (parámetros) y aplicada en `mock/politica.py` (cálculo):

```
límite_ajustado    = límite_credito × factor_veraz × factor_balance
crédito_disponible = límite_ajustado − saldo_cuenta_corriente
```

- **factor_veraz**: categoría 1 (normal) → 1.00 | categoría 3 (con problemas) → 0.50 | categoría 5 (irrecuperable) → 0.00
- **factor_balance**: 0.50 si el último balance presentado tiene más de 18 meses de antigüedad, 1.00 si está vigente

Un pedido es **APTO** solo si se cumplen las tres condiciones a la vez: la calificación Veraz no es 5, el cliente no tiene deuda vencida, y el monto del pedido entra dentro del crédito disponible.

Que estos parámetros vivan en un JSON aparte (y no "hardcodeados" en el código) permite ajustar la política de negocio — por ejemplo, cambiar el umbral de 18 meses, o los factores de Veraz — sin tocar una sola línea de Python.

### 3.3. Skills: las "competencias" del agente

Siguiendo el documento del TP, el comportamiento del agente se organizó en **skills** (`config/skills.json`): unidades de competencia que orquestan una o más tools para resolver una parte del proceso. Se definieron 6:

| Skill | Qué hace | Se activa cuando |
|---|---|---|
| **Comprensión y Extracción de Solicitudes** | Interpreta el pedido en lenguaje natural (cliente, número de pedido, monto) y lo normaliza. | Llega una nueva solicitud comercial. |
| **Evaluación de Riesgo Crediticio** | Consulta la ficha del cliente y aplica la política de crédito, mostrando el cálculo completo. | Al recibir un pedido, y cada vez que hay que reevaluar tras una gestión o un pago. |
| **Gestión de Cobranza y Seguimiento de Compromisos** | Notifica a Ventas, fija un plazo de regularización y registra pagos acreditados. | El pedido no es apto por deuda vencida. |
| **Liberación y Documentación de Pedidos** | Genera el documento de venta en el ERP e imputa el monto a la cuenta corriente. | El pedido es apto, o una excepción fue aprobada. |
| **Gestión de Excepciones y Escalamiento** | Detecta cuándo la única salida es una acción irreversible, arma el resumen del caso y pide aprobación humana explícita. | Veraz categoría 5, deuda sin regularizar, o monto sin margen — y **requiere aprobación humana**. |
| **Trazabilidad y Reporte de Desempeño** | Deja registrado cada cierre de caso para poder auditar y medir desempeño. | En cada cierre de ciclo. |

Cada skill le dice al modelo **cuándo activarse**, **qué tools puede usar** y **qué instrucciones seguir** — esa descripción se inyecta en el *system prompt* del agente (`agent.py`, función `construir_system_prompt`).

### 3.4. Tools: las acciones atómicas

Las skills orquestan **tools** (`config/tools.json`): funciones concretas que el modelo puede pedir ejecutar, con un esquema de parámetros bien definido (formato *tool use* de la API de Claude). Se implementaron 6, todas con su función Python correspondiente en `mock/tools_impl.py`:

1. `consultar_credito_cliente` — trae la ficha crediticia completa de un cliente.
2. `listar_clientes` — devuelve la cartera completa (o filtrada por nombre/CUIT).
3. `evaluar_politica_credito` — corre el cálculo de la política y devuelve APTO/NO APTO con el detalle.
4. `gestionar_cobranza` — registra la gestión de cobranza cuando hay deuda vencida.
5. `registrar_pago` — acredita un pago informado, imputándolo primero a la deuda vencida y el remanente al saldo.
6. `liberar_pedido` — genera el documento de venta e imputa el pedido a la cuenta corriente del cliente.

El modelo nunca calcula nada "de cabeza": las instrucciones del agente son explícitas en que el límite, el saldo, la deuda y el veredicto APTO/NO APTO **siempre** tienen que salir de estas tools, nunca ser estimados por el modelo. Esto es lo que hace que el resultado sea auditable — cada número que el agente muestra viene de una ejecución real y trazada.

### 3.5. El control de acciones irreversibles

El documento del TP (sección "Límites") exige que tres acciones queden bloqueadas hasta que una persona las apruebe explícitamente:

1. Liberar un pedido que incumple la política de crédito.
2. Modificar un límite de crédito.
3. Aprobar una excepción comercial.

Esto se implementó en **dos capas independientes**, a propósito, para que ninguna falle sola:

- **`mock/tools_impl.py` → `liberar_pedido()`**: reevalúa la política internamente y rechaza el pedido si no es apto y no vino marcado como excepción con quién la aprobó (`es_excepcion=true` + `aprobado_por`). Esta capa protege incluso si el modelo "se equivoca" y llama a la tool sin la aprobación correspondiente.
- **`agent.py` → `pedir_aprobacion_humana()`**: intercepta la llamada *antes* de ejecutarla y pide confirmación explícita por consola. Esta capa evita siquiera intentar la acción sin que una persona la haya visto.

### 3.6. Paso a paso de construcción

En términos generales, el desarrollo siguió este orden:

1. Se definió la base ficticia de clientes (`mock/clientes.json`, 10 casos con distintas combinaciones de límite, saldo, deuda y calificación Veraz) y una copia prístina (`mock/clientes_base.json`) para poder restaurar el estado tras cada prueba.
2. Se implementó el motor de cálculo puro (`mock/politica.py`) y se validó con `evaluar_pedido.py` contra una tabla de casos de referencia (ver sección 6.1 de este documento), antes de conectar nada con IA.
3. Se definieron las tools (`config/tools.json`) y su implementación (`mock/tools_impl.py`), reutilizando siempre el mismo motor de cálculo.
4. Se definieron las skills (`config/skills.json`) que orquestan esas tools según la situación.
5. Se armó `agent.py`: carga la configuración, arma el *system prompt*, corre el loop de conversación con la API de Claude, despacha las tools que el modelo pide ejecutar, e intercepta las acciones irreversibles para pedir aprobación humana.
6. Se agregaron utilidades complementarias: un importador de clientes desde Excel (sección 5) y una rutina de simulación de un día de trabajo (sección 7).

---

## 4. Para qué se usó la API de Claude

La API de Claude es lo que le da al agente su capacidad de **entender lenguaje natural y decidir qué hacer**, algo que el script de consola (`evaluar_pedido.py`) no tiene — ese script solo sabe ejecutar el cálculo si vos le decís exactamente el cliente y el monto.

En `agent.py`, cada consulta del equipo comercial (por ejemplo: *"nos llegó un pedido de Comercial Norte por USD 50.000, ¿es apto?"*) se envía como mensaje a la API (`client.messages.create`), junto con:

- el **system prompt**, que define quién es el agente, la política de crédito vigente y las reglas fijas (nunca inventar datos, siempre correr las tools, nunca liberar sin aprobación);
- las **tools disponibles** (`config/tools.json`), con sus esquemas de entrada;
- el **historial de la conversación**.

El modelo interpreta el pedido, decide qué tool ejecutar primero (por ejemplo `consultar_credito_cliente`), recibe el resultado, decide el siguiente paso (`evaluar_politica_credito`), y así sucesivamente hasta poder darle una respuesta completa a la persona — todo esto es el patrón de **tool use** (o *function calling*): el modelo no ejecuta código directamente, sino que pide que el programa ejecute una función y le devuelva el resultado para seguir razonando.

En síntesis: la política de crédito y el cálculo son 100% determinísticos y no usan IA — la API de Claude se usa exclusivamente para la capa conversacional: entender la solicitud, orquestar las tools en el orden correcto, y explicarle el resultado a una persona en lenguaje claro.

---

## 5. La base de clientes ficticia

Como no hay conexión real a sistemas como SAP o Veraz, se construyó una **base ficticia de 10 clientes** (`mock/clientes.json`) con datos inventados con fines académicos: razón social, CUIT, contacto, límite de crédito, fecha del último balance, saldo de cuenta corriente, deuda vencida y calificación Veraz.

Esta base ficticia cumple dos propósitos:

- Permite **probar el agente sin ningún costo ni riesgo**, ya que ningún dato real de clientes ni ninguna operación real está en juego.
- Se armó deliberadamente con **variedad de situaciones** (clientes al día, con deuda vencida, con balance desactualizado, con la peor calificación Veraz, casos límite exactos) para poder mostrar todos los caminos posibles del agente: liberación directa, cobranza, escalamiento, excepción aprobada.

Como el agente **modifica** esta base al liberar pedidos o registrar pagos (imputa el pedido al saldo, descuenta el pago), se guardó una copia prístina (`mock/clientes_base.json`) y un comando de reseteo (`python evaluar_pedido.py --reset`) para volver al estado inicial después de cada tanda de pruebas.

Para completar el circuito de alta de clientes, se agregó **`mock/importar_clientes_xlsx.py`**: un script que lee un archivo `.xlsx` (plantilla generable con `--plantilla`) con las columnas de un cliente, valida los datos (fechas, montos, categoría Veraz) y los vuelca tanto a `clientes.json` como a `clientes_base.json` — así una persona puede dar de alta o actualizar un cliente completando una planilla Excel, sin tocar el JSON a mano ni escribir código.

---

## 6. Validación de la política de crédito

Antes de conectar el motor de cálculo con la API de Claude, se validó con una tabla de casos de referencia que cubre los distintos caminos de la política:

| Cliente | Monto | Resultado esperado |
|---|---:|---|
| CLI-1001 | 80.000 | APTO (disponible 110.000) |
| CLI-1002 | 50.000 | NO APTO — deuda vencida 30.000 → gestionar cobranza |
| CLI-1005 | 5.000 | NO APTO — Veraz categoría 5 → escalar a aprobación humana |
| CLI-1004 | 50.000 | NO APTO — balance vencido reduce el límite a 60.000 |
| CLI-1006 | 5.000 | APTO justo en el borde (disponible exacto 5.000) |
| CLI-1008 | 200.000 | APTO exacto; con 200.001 pasa a NO APTO |

Esta tabla también sirvió de base para diseñar los escenarios de la simulación de un día de trabajo (sección 7): los mismos clientes y montos, pero conversados en lenguaje natural con el agente real.

---

## 7. Simulación de un día de trabajo

Para mostrar cómo funcionaría el agente en la práctica — atendiendo, en una misma jornada, distintas solicitudes del equipo comercial — se construyó **`simular_dia_trabajo.py`**, que corre 5 casos guionados (`mock/escenarios_dia_trabajo.json`) contra el agente real (misma configuración y tools que usa `agent.py`).

Cada caso es una conversación nueva e independiente, como si fueran 5 tickets distintos que le llegan al agente el mismo día, y combina una consulta de estado de cuenta con la evaluación de un pedido nuevo:

1. **Cliente dentro de política** → liberación directa.
2. **Deuda vencida** → propuesta de gestión de cobranza → se acredita el pago → se registra → se reevalúa → queda APTO → se libera. Es el circuito completo que describe el documento del TP.
3. **Balance desactualizado** → el límite se reduce a la mitad → NO APTO, con las alternativas explicadas.
4. **Calificación Veraz irrecuperable (categoría 5)** → NO APTO automático → escalamiento → una persona aprueba la excepción comercial → se libera por excepción. Este caso ejercita en vivo el control de aprobación humana descrito en la sección 3.5.
5. **Caso límite exacto**: un pedido de exactamente el crédito disponible es APTO; un dólar más ya es NO APTO — para mostrar que la política se aplica con precisión matemática, sin margen de tolerancia.

Como la rutina corre los 5 casos de punta a punta sin que haya una persona esperando frente a la consola, la decisión de aprobar o rechazar una excepción (caso 4) se toma de una respuesta pre-cargada en el propio escenario, señalada explícitamente como **`[SIMULACIÓN]`** en la transcripción — para dejar claro que no reemplaza el control real: en el uso interactivo (`agent.py`), esa misma acción sigue deteniéndose a pedir la aprobación por consola.

Al finalizar, la rutina genera dos salidas:

- **`logs/registro_auditable.jsonl`**: la traza completa, máquina-legible, de cada tool ejecutada (igual que en cualquier corrida normal del agente).
- **`logs/simulacion_dia_trabajo.md`**: una transcripción legible en Markdown de toda la jornada simulada — cada mensaje del equipo comercial, cada respuesta del agente, y cada tool ejecutada con su input y su resultado — pensada para poder revisar o adjuntar la corrida sin tener que releer la consola.

---

## 8. Correspondencia con el documento del trabajo práctico

| Elemento del código | Sección del documento del TP |
|---|---|
| `config/tools.json` | Sección 3 — Herramientas |
| `config/skills.json` | Sección 3.1 — Skills del Agente |
| `mock/politica.py` | Sección 4 — ¿Cómo funciona? |
| `config/agent_config.json` → `limites` | Sección 6 — Límites |
| `logs/registro_auditable.jsonl` | Sección 7 — ¿Cómo se evalúa? |

---

## 9. Posibles próximos pasos

Algunas ideas que quedan fuera del alcance de esta entrega, pero que serían un paso natural si el proyecto avanzara hacia un caso de uso real:

- **Conexión real a las fuentes de datos**: reemplazar `mock/clientes.json` por una integración real con SAP (o el ERP que corresponda) y con un buró de crédito real (Veraz u otro), sin tocar el motor de cálculo ni las tools.
- **Persistencia robusta**: hoy el estado se guarda en archivos JSON planos, adecuados para una prueba de concepto; una implementación productiva necesitaría una base de datos con control de concurrencia (dos pedidos del mismo cliente al mismo tiempo, por ejemplo).
- **Interfaz para el equipo comercial**: hoy el agente se usa por consola; un canal como Slack, correo o un chat interno bajaría todavía más la fricción de uso.
- **Métricas de desempeño**: `agent_config.json` ya define los indicadores que le interesarían al negocio (tiempo promedio de liberación, pedidos bloqueados, porcentaje liberado automáticamente); el siguiente paso sería procesar `logs/registro_auditable.jsonl` para calcularlos de verdad.
