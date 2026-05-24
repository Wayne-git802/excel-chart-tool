"""模板数据库 - SQLite"""
import sqlite3
import json
import os


class TemplateDB:
    """图表模板存储"""
    
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_db()
    
    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS chart_templates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                chart_type TEXT NOT NULL,
                x_column TEXT NOT NULL,
                y_columns TEXT NOT NULL,
                config TEXT DEFAULT '{}',
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()
    
    def save_template(self, name: str, chart_type: str, x_column: str,
                      y_columns: str, config: str) -> int:
        cursor = self.conn.execute(
            "INSERT INTO chart_templates (name, chart_type, x_column, y_columns, config) VALUES (?, ?, ?, ?, ?)",
            (name, chart_type, x_column, y_columns, config)
        )
        self.conn.commit()
        return cursor.lastrowid
    
    def list_templates(self) -> list:
        cursor = self.conn.execute(
            "SELECT id, name, chart_type, x_column, y_columns, config, created_at "
            "FROM chart_templates ORDER BY created_at DESC LIMIT 50"
        )
        rows = cursor.fetchall()
        return [
            {
                "id": r[0], "name": r[1], "chart_type": r[2],
                "x_column": r[3], "y_columns": r[4], "config": r[5],
                "created_at": r[6]
            }
            for r in rows
        ]
    
    def delete_template(self, template_id: int):
        self.conn.execute("DELETE FROM chart_templates WHERE id = ?", (template_id,))
        self.conn.commit()
