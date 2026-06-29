"""
SQLite 기반 대화 기록 저장소.
기존 MariaDB 대신 로컬 SQLite(data/chats.db)를 사용하여 테스트를 진행한다.
"""
import os
import json
import sqlite3
from contextlib import contextmanager

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "chats.db")

@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # foreign key support is not enabled by default in sqlite
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.commit()
        conn.close()


def init_db():
    """테이블이 없으면 생성한다. 앱 시작 시 1회 호출."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS chats (
                id VARCHAR(36) PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                chat_type VARCHAR(50) DEFAULT 'health',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            cur.execute("ALTER TABLE chats ADD COLUMN chat_type VARCHAR(50) DEFAULT 'health'")
        except sqlite3.OperationalError:
            pass
            
        cur.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id VARCHAR(36) NOT NULL,
                role VARCHAR(20) NOT NULL,
                content TEXT NOT NULL,
                sources TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                CONSTRAINT fk_messages_chat
                    FOREIGN KEY (chat_id) REFERENCES chats(id)
                    ON DELETE CASCADE
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_chat_id ON messages (chat_id)")
        
        cur.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key VARCHAR(100) PRIMARY KEY,
                value TEXT
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username VARCHAR(50) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(20) DEFAULT 'user'
            )
        """)
        
        # 기본 계정 생성 (테이블이 비어있을 경우)
        cur.execute("SELECT COUNT(*) as cnt FROM users")
        if cur.fetchone()["cnt"] == 0:
            import bcrypt
            # 관리자 계정 생성
            admin_pwd = bcrypt.hashpw("admin1234".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", ("admin", admin_pwd, "admin"))
            # 테스트 계정 생성
            test_pwd = bcrypt.hashpw("test1234".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
            cur.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", ("test", test_pwd, "user"))

import bcrypt

def verify_user(username, password):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM users WHERE username = ?", (username,))
        row = cur.fetchone()
        if row:
            if bcrypt.checkpw(password.encode('utf-8'), row["password_hash"].encode('utf-8')):
                return {"id": row["id"], "username": row["username"], "role": row["role"]}
        return None

def get_user_by_id(user_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if row:
            return {"id": row["id"], "username": row["username"], "role": row["role"]}
        return None

def create_user(username, password, role="user"):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE username = ?", (username,))
        if cur.fetchone():
            return False, "이미 존재하는 아이디입니다."
            
        hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        cur.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)", (username, hashed, role))
        return True, "계정이 생성되었습니다."

def get_all_users():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, username, role FROM users ORDER BY id ASC")
        return [dict(row) for row in cur.fetchall()]

def delete_user(user_id):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM users WHERE id = ?", (user_id,))

def get_setting(key: str, default: str = "") -> str:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cur.fetchone()
        return row["value"] if row else default

def set_setting(key: str, value: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))

def get_all_chats() -> dict:
    chats = {}
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, chat_type FROM chats ORDER BY created_at ASC, id ASC")
        for row in cur.fetchall():
            chats[row["id"]] = {"name": row["name"], "chat_type": row["chat_type"] or "health", "messages": []}

        if not chats:
            return chats

        cur.execute("SELECT id, chat_id, role, content, sources FROM messages ORDER BY id ASC")
        for row in cur.fetchall():
            cid = row["chat_id"]
            if cid not in chats:
                continue
            sources = row["sources"]
            if isinstance(sources, str):
                sources = json.loads(sources) if sources else []
            elif sources is None:
                sources = []
            chats[cid]["messages"].append({
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "sources": sources,
            })
    return chats


def create_chat(chat_id: str, name: str, welcome_message: str, chat_type: str = "health"):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO chats (id, name, chat_type) VALUES (?, ?, ?)", (chat_id, name, chat_type)
        )
        cur.execute(
            "INSERT INTO messages (chat_id, role, content, sources) VALUES (?, ?, ?, ?)",
            (chat_id, "assistant", welcome_message, json.dumps([])),
        )


def add_message(chat_id: str, role: str, content: str, sources: list) -> int:
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO messages (chat_id, role, content, sources) VALUES (?, ?, ?, ?)",
            (chat_id, role, content, json.dumps(sources or [], ensure_ascii=False)),
        )
        return cur.lastrowid

def update_message(msg_id: int, content: str, sources: list):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE messages SET content = ?, sources = ? WHERE id = ?",
            (content, json.dumps(sources or [], ensure_ascii=False), msg_id)
        )


def rename_chat(chat_id: str, name: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE chats SET name = ? WHERE id = ?", (name, chat_id)
        )


def delete_chat(chat_id: str):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM chats WHERE id = ?", (chat_id,))
