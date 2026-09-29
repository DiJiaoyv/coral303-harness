-- Harness 多用户数据库 schema
-- 数据库文件: C:\Users\guang\harness.db

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- 角色元数据（管理后台主数据源，文件实体在 users/{user_id}/characters/ 下）
CREATE TABLE IF NOT EXISTS characters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    character_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    role TEXT,
    description TEXT DEFAULT '',
    system_prompt TEXT DEFAULT '',
    parameters_json TEXT DEFAULT '{}',
    emotion_state TEXT DEFAULT '{}',
    deleted INTEGER NOT NULL DEFAULT 0,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE (user_id, character_key)
);

-- 对话历史（便于查询与将来导出，含 user_id）
CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    character_key TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
    content TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

-- 会话日志索引
CREATE TABLE IF NOT EXISTS session_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    session_id TEXT NOT NULL,
    log_path TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_characters_user_id ON characters(user_id);
CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS idx_session_logs_user_id ON session_logs(user_id);

-- 对话质量评分
CREATE TABLE IF NOT EXISTS score_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER,
    user_id INTEGER NOT NULL,
    character_id INTEGER,
    user_message TEXT NOT NULL,
    bot_reply TEXT NOT NULL,
    relevance_score REAL NOT NULL,
    consistency_score REAL NOT NULL,
    fluency_score REAL NOT NULL,
    safety_score REAL NOT NULL,
    total_score REAL NOT NULL,
    scoring_method TEXT NOT NULL DEFAULT 'rule',
    -- v0.2 诊断报告字段
    violations_json TEXT DEFAULT '[]',
    rewrite_instruction TEXT DEFAULT '',
    regen_count INTEGER NOT NULL DEFAULT 0,
    candidates_json TEXT DEFAULT '[]',
    final_accepted_index INTEGER NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE SET NULL,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_score_logs_user_id ON score_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_score_logs_created_at ON score_logs(created_at);

-- 评估明细日志（一行一个 candidate，保存完整 candidate→拒绝→重写→采纳 链路）
-- 与 score_logs（一轮一条）互补：score_logs 存最终采纳的回复 + 聚合诊断，
-- evaluation_logs 存每个 candidate 的明细，便于按 candidate 查询 / 分析违规模式。
CREATE TABLE IF NOT EXISTS evaluation_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    score_log_id INTEGER,
    conversation_id INTEGER,
    user_id INTEGER NOT NULL,
    character_id INTEGER,
    user_message TEXT NOT NULL,
    candidate_response TEXT NOT NULL,
    attempt INTEGER NOT NULL DEFAULT 0,
    accepted INTEGER NOT NULL DEFAULT 0,
    scores_json TEXT DEFAULT '{}',
    violations_json TEXT DEFAULT '[]',
    rewrite_instruction TEXT DEFAULT '',
    final_response TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (score_log_id) REFERENCES score_logs(id) ON DELETE CASCADE,
    FOREIGN KEY (conversation_id) REFERENCES conversations(id) ON DELETE SET NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_evaluation_logs_score_log_id ON evaluation_logs(score_log_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_logs_user_id ON evaluation_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_evaluation_logs_accepted ON evaluation_logs(accepted);
CREATE INDEX IF NOT EXISTS idx_evaluation_logs_created_at ON evaluation_logs(created_at);

-- 推理性能监控（不含对话内容）
CREATE TABLE IF NOT EXISTS performance_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    character_id INTEGER,
    duration_ms REAL NOT NULL DEFAULT 0,
    gpu_util REAL NOT NULL DEFAULT 0,
    queue_length INTEGER NOT NULL DEFAULT 0,
    success INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_performance_logs_created_at ON performance_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_performance_logs_user_id ON performance_logs(user_id);

-- 内容安全审核日志
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    character_id INTEGER,
    stage TEXT NOT NULL CHECK (stage IN ('input', 'output')),
    level TEXT NOT NULL,
    matched_word TEXT NOT NULL,
    original_content TEXT NOT NULL,
    action_taken TEXT NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_audit_logs_created_at ON audit_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_audit_logs_user_id ON audit_logs(user_id);
CREATE INDEX IF NOT EXISTS idx_audit_logs_level ON audit_logs(level);

-- 角色弧光状态（每角色一条）
CREATE TABLE IF NOT EXISTS arcs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL UNIQUE,
    current_stage TEXT NOT NULL DEFAULT 'stranger',
    stages TEXT NOT NULL DEFAULT '["stranger","acquaintance","trust","intimate"]',
    goals TEXT NOT NULL DEFAULT '[]',
    progress REAL NOT NULL DEFAULT 0.0,
    auto_advance INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_arcs_character_id ON arcs(character_id);

-- 弧光操作日志
CREATE TABLE IF NOT EXISTS arc_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    character_id INTEGER NOT NULL,
    user_id INTEGER,
    action TEXT NOT NULL,
    details TEXT NOT NULL DEFAULT '',
    operator TEXT NOT NULL DEFAULT 'system',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (character_id) REFERENCES characters(id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_arc_logs_character_id ON arc_logs(character_id);
CREATE INDEX IF NOT EXISTS idx_arc_logs_created_at ON arc_logs(created_at);
