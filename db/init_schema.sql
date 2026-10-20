-- Operator OS System Registry and Package Database
-- Schema Version: 1.0.0

PRAGMA foreign_keys = ON;

-- System Settings Table
CREATE TABLE IF NOT EXISTS sys_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'string', -- 'string', 'int', 'bool', 'json'
    category TEXT NOT NULL DEFAULT 'general',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Installed Packages Registry
CREATE TABLE IF NOT EXISTS sys_packages (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT NOT NULL,
    architecture TEXT NOT NULL DEFAULT 'x86_64',
    runtime TEXT NOT NULL, -- 'native', 'java', 'python', 'web'
    entrypoint TEXT NOT NULL,
    description TEXT,
    author TEXT,
    installed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'active'
);

-- Users and Access Control
CREATE TABLE IF NOT EXISTS sys_users (
    uid INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    shell TEXT DEFAULT '/bin/opshell',
    home_dir TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user', -- 'root', 'user', 'service'
    memory_mb INTEGER NOT NULL DEFAULT 1024,
    quota_mb INTEGER NOT NULL DEFAULT 512,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS sys_auth (
    username TEXT PRIMARY KEY,
    pass_hash TEXT NOT NULL,
    role TEXT NOT NULL,
    salt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sys_passd_auth (
    username TEXT PRIMARY KEY,
    pass_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    iterations INTEGER NOT NULL
);

-- Process Audit & Execution Log
CREATE TABLE IF NOT EXISTS sys_process_log (
    pid INTEGER PRIMARY KEY AUTOINCREMENT,
    command TEXT NOT NULL,
    runtime TEXT NOT NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    exit_code INTEGER DEFAULT NULL
);

-- Seed Default Settings
INSERT OR REPLACE INTO sys_settings (key, value, type, category) VALUES
    ('os.name', 'Atlas OS', 'string', 'kernel'),
    ('os.version', '2.0.0-PRO', 'string', 'kernel'),
    ('os.build', '2026.10', 'string', 'kernel'),
    ('net.dns', '1.1.1.1', 'string', 'network'),
    ('shell.default', 'opshell', 'string', 'shell'),
    ('shell.allow_powershell', 'true', 'bool', 'shell'),
    ('shell.allow_wsl', 'true', 'bool', 'shell'),
    ('shell.allow_cmd', 'true', 'bool', 'shell');

-- Seed Core System Packages
INSERT OR REPLACE INTO sys_packages (id, name, version, runtime, entrypoint, description, author) VALUES
    ('core.kernel', 'Operator Kernel Engine', '1.0.0', 'native', 'bin/operator_kernel.exe', 'Core microkernel & memory manager', 'Operator System Team'),
    ('core.shell', 'Operator Polyglot Shell', '1.0.0', 'python', 'shell/opshell.py', 'Hybrid Shell Bridge (Linux/PS/CMD)', 'Operator System Team'),
    ('core.ovm', 'Operator Java Runtime', '1.0.0', 'java', 'runtime_java/OperatorRuntime.jar', 'OVM Application Lifecycle Framework', 'Operator System Team'),
    ('app.nano', 'Operator Code Editor', '10.0.0', 'python', 'apps/nano.py', 'Terminal code editor with syntax highlighting and installable language completion extensions', 'Operator System Team'),
    ('app.editor', 'Operator Code Editor', '10.0.0', 'python', 'apps/nano.py', 'Terminal code editor with syntax highlighting and installable language completion extensions', 'Operator System Team');

-- Seed Root and Default User (no password inserted here - UserManager seeds sys_auth with correct sha256)
INSERT OR IGNORE INTO sys_users (uid, username, shell, home_dir, role, memory_mb, quota_mb) VALUES
    (0, 'root', '/bin/opshell', '/Users/root/home', 'root', 2048, 1024),
    (1000, 'operator', '/bin/opshell', '/Users/operator/home', 'user', 1024, 512);
