-- Modelo de datos NOC Syslog Inteligente v0.2.0
-- Principio: todo log recibido es un DATO NO CONFIABLE, nunca una instruccion.

PRAGMA foreign_keys = ON;

-- 1. Inventario de equipos
CREATE TABLE IF NOT EXISTS devices (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    name         TEXT NOT NULL UNIQUE,
    ip_address   TEXT NOT NULL,
    vendor       TEXT NOT NULL CHECK (vendor IN ('cisco','fortinet','huawei','other')),
    model        TEXT,
    os_version   TEXT,
    location     TEXT,
    status       TEXT NOT NULL DEFAULT 'active'
                 CHECK (status IN ('active','inactive','maintenance')),
    is_simulated INTEGER NOT NULL DEFAULT 1,      -- 1 = dato de demostraci�n
    updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
);

-- 2. Eventos Syslog (RFC 5424: facility 0-23, severity 0-7)
CREATE TABLE IF NOT EXISTS syslog_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id    INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    source_ip    TEXT,
    hostname     TEXT,
    received_at  TEXT NOT NULL DEFAULT (datetime('now')),
    event_time   TEXT,
    facility     INTEGER CHECK (facility BETWEEN 0 AND 23),
    severity     INTEGER NOT NULL CHECK (severity BETWEEN 0 AND 7),
    message      TEXT NOT NULL,       -- mensaje saneado, solo para mostrar
    raw_message  TEXT,                -- original sin modificar (evidencia)
    dedup_hash   TEXT,                -- para deduplicaci�n / control de tormentas
    tags         TEXT DEFAULT '',     -- etiquetas separadas por coma
    is_simulated INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_events_received ON syslog_events(received_at);
CREATE INDEX IF NOT EXISTS idx_events_severity ON syslog_events(severity);
CREATE INDEX IF NOT EXISTS idx_events_device   ON syslog_events(device_id);
CREATE INDEX IF NOT EXISTS idx_events_hash     ON syslog_events(dedup_hash);

-- 3. Incidentes
CREATE TABLE IF NOT EXISTS incidents (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT NOT NULL,
    description TEXT,
    severity    INTEGER NOT NULL CHECK (severity BETWEEN 0 AND 7),
    status      TEXT NOT NULL DEFAULT 'open'
                CHECK (status IN ('open','assigned','in_progress','resolved','closed')),
    device_id   INTEGER REFERENCES devices(id) ON DELETE SET NULL,
    assigned_to TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    closed_at   TEXT
);

-- 4. Relacion incidente <-> eventos que lo originaron
CREATE TABLE IF NOT EXISTS incident_events (
    incident_id INTEGER NOT NULL REFERENCES incidents(id) ON DELETE CASCADE,
    event_id    INTEGER NOT NULL REFERENCES syslog_events(id) ON DELETE CASCADE,
    PRIMARY KEY (incident_id, event_id)
);

-- 5. Auditoria (flujo: ... Aprobacion -> Ejecucion -> Verificacion -> Auditoria)
CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp   TEXT NOT NULL DEFAULT (datetime('now')),
    actor       TEXT NOT NULL,        -- usuario humano o 'system'
    action      TEXT NOT NULL,        -- ej: 'device.create', 'command.approved'
    entity      TEXT,
    entity_id   INTEGER,
    details     TEXT
);