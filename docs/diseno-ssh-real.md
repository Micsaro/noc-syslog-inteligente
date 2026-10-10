# Diseño: conexión SSH real para la consola (NO implementada en el MVP)

En v0.2.0 la consola es simulada y de solo lectura. Este documento describe cómo se
conectaría a equipos reales sin perder el control.

## Principios
1. **Humano en el circuito.** Ningún agente de IA ni proceso automático ejecuta comandos
   por su cuenta: solo puede *proponerlos*.
2. **Denegar por defecto.** Mismo motor de política que la consola simulada (lista de
   permitidos por fabricante, lista de bloqueados que siempre gana, sin abreviaturas).
3. **Los logs son datos.** El texto de un log o de una salida de equipo nunca se convierte en comando.

## Flujo obligatorio
Evento detectado → Validación → Propuesta de acción → Revisión humana → Aprobación →
Ejecución autorizada → Verificación → Auditoría.

## Componentes
- **Backend SSH autorizado**: único punto de salida hacia los equipos. El navegador nunca
  recibe credenciales. Salto por un bastión con IP fija y ACL en los equipos.
- **Credenciales**: en un gestor de secretos (nunca en código, base de datos ni logs).
  Cuentas de solo lectura por equipo; claves de corta duración.
- **Roles**: `lector` (comandos de lectura permitidos), `operador` (propone cambios),
  `aprobador` (aprueba; distinto de quien propone), `administrador` (política y usuarios).
  Principio de menor privilegio y MFA para operador, aprobador y administrador.
- **Aprobación humana**: todo comando fuera de la lista de lectura exige propuesta con
  motivo, aprobación de una segunda persona, ventana de tiempo y un solo uso.
- **Auditoría**: cada intento (permitido, bloqueado, aprobado, rechazado) con actor,
  equipo, comando, motivo y resultado; registros solo de adición, enviados al SIEM.
- **Límites**: tiempo máximo de sesión, tasa de comandos por usuario, cierre ante
  actividad anómala y un interruptor de emergencia que bloquea toda ejecución.
- **Verificación posterior**: tras una acción aprobada se ejecuta un comando de lectura
  predefinido para confirmar el efecto y se adjunta al registro.

## Riesgos y mitigaciones
| Riesgo | Mitigación |
|---|---|
| Inyección de comandos en un log o salida | Los logs son solo datos; whitelist de caracteres; sin shell |
| Agente de IA que escala acciones | Solo propone; ejecución con aprobación humana y un solo uso |
| Robo de credenciales | Gestor de secretos, cuentas de solo lectura, rotación |
| Macro maliciosa | Validación al crear y en cada ejecución; se detiene al primer bloqueo |
| IP falsificada en Syslog UDP | Syslog sobre TLS, ACL de origen, listas permitidas |