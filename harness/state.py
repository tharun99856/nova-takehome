"""State management using SQLite.

Persistent storage for documents, extracted entities, and findings across
fresh process invocations. All mutations are transactional.
"""
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def _hash_content(data: bytes) -> str:
    """SHA256 hash for deduplication."""
    return hashlib.sha256(data).hexdigest()


class State:
    """Persistent state manager."""
    
    def __init__(self, state_dir: str):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = self.state_dir / "state.db"
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self._init_schema()
    
    def _init_schema(self):
        """Create tables if they don't exist."""
        with self.conn:
            # Core document tracking
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    batch TEXT NOT NULL,
                    file TEXT NOT NULL,
                    received_date TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    doc_type TEXT,
                    is_scan INTEGER DEFAULT 0,
                    raw_text TEXT,
                    PRIMARY KEY (batch, file)
                )
            """)
            
            # Extracted text cache per document page
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS document_pages (
                    doc_ref TEXT NOT NULL,
                    page_num INTEGER NOT NULL,
                    page_text TEXT NOT NULL,
                    PRIMARY KEY (doc_ref, page_num)
                )
            """)
            
            # Structured entities extracted from documents
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS entities (
                    entity_id TEXT PRIMARY KEY,
                    entity_type TEXT NOT NULL,
                    data JSON NOT NULL,
                    source_doc TEXT NOT NULL,
                    batch TEXT NOT NULL,
                    received_date TEXT NOT NULL
                )
            """)
            
            # Findings per key
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS findings (
                    finding_key TEXT PRIMARY KEY,
                    batch TEXT NOT NULL,
                    as_of TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    verdict TEXT NOT NULL,
                    amount_usd TEXT,
                    action TEXT NOT NULL,
                    confidence REAL NOT NULL,
                    evidence JSON NOT NULL,
                    data JSON NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            
            # Feedback facts
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback_facts (
                    fact_id TEXT PRIMARY KEY,
                    batch TEXT NOT NULL,
                    fact_type TEXT NOT NULL,
                    scope_kind TEXT NOT NULL,
                    applies_to JSON NOT NULL,
                    valid_from TEXT,
                    valid_to TEXT,
                    value JSON NOT NULL,
                    decided_at TEXT NOT NULL
                )
            """)
            
            # Indexes for common queries
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_batch ON documents(batch)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_documents_date ON documents(received_date)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_type ON entities(entity_type)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_entities_batch ON entities(batch)")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_findings_batch ON findings(batch)")
    
    def add_document(self, batch: str, file: str, received_date: str, 
                     content: bytes, doc_type: str = None, is_scan: bool = False) -> str:
        """Store document metadata. Returns content hash. Idempotent."""
        content_hash = _hash_content(content)
        
        with self.conn:
            self.conn.execute("""
                INSERT OR IGNORE INTO documents 
                (batch, file, received_date, content_hash, doc_type, is_scan)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (batch, file, received_date, content_hash, doc_type, int(is_scan)))
        
        return content_hash
    
    def add_document_pages(self, doc_ref: str, pages: list[str]):
        """Store extracted page text for a document."""
        with self.conn:
            for page_num, page_text in enumerate(pages, start=1):
                self.conn.execute("""
                    INSERT OR REPLACE INTO document_pages (doc_ref, page_num, page_text)
                    VALUES (?, ?, ?)
                """, (doc_ref, page_num, page_text))
    
    def get_document_pages(self, doc_ref: str) -> list[str] | None:
        """Retrieve cached page text."""
        cursor = self.conn.execute("""
            SELECT page_text FROM document_pages 
            WHERE doc_ref = ? ORDER BY page_num
        """, (doc_ref,))
        rows = cursor.fetchall()
        return [row[0] for row in rows] if rows else None
    
    def add_entity(self, entity_id: str, entity_type: str, data: dict,
                   source_doc: str, batch: str, received_date: str):
        """Store extracted entity. Idempotent by entity_id."""
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO entities 
                (entity_id, entity_type, data, source_doc, batch, received_date)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (entity_id, entity_type, json.dumps(data), source_doc, batch, received_date))
    
    def get_entities(self, entity_type: str = None, as_of: str = None) -> list[dict]:
        """Retrieve entities, optionally filtered by type and as_of date."""
        query = "SELECT * FROM entities WHERE 1=1"
        params = []
        
        if entity_type:
            query += " AND entity_type = ?"
            params.append(entity_type)
        
        if as_of:
            query += " AND received_date <= ?"
            params.append(as_of)
        
        query += " ORDER BY received_date, batch"
        
        cursor = self.conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]
    
    def add_finding(self, finding_key: str, batch: str, as_of: str, mode: str,
                    verdict: str, amount_usd: str | None, action: str,
                    confidence: float, evidence: list, data: dict):
        """Store or update finding."""
        from datetime import datetime
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO findings 
                (finding_key, batch, as_of, mode, verdict, amount_usd, action, 
                 confidence, evidence, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (finding_key, batch, as_of, mode, verdict, amount_usd, action,
                  confidence, json.dumps(evidence), json.dumps(data),
                  datetime.utcnow().isoformat()))
    
    def get_findings(self, as_of: str = None, mode: str = None) -> list[dict]:
        """Retrieve findings, optionally filtered."""
        query = "SELECT * FROM findings WHERE 1=1"
        params = []
        
        if as_of:
            query += " AND as_of <= ?"
            params.append(as_of)
        
        if mode:
            query += " AND mode = ?"
            params.append(mode)
        
        query += " ORDER BY batch, finding_key"
        
        cursor = self.conn.execute(query, params)
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d['evidence'] = json.loads(d['evidence'])
            d['data'] = json.loads(d['data'])
            results.append(d)
        return results
    
    def add_feedback_fact(self, fact_id: str, batch: str, fact_type: str,
                          scope_kind: str, applies_to: dict, valid_from: str | None,
                          valid_to: str | None, value: dict, decided_at: str):
        """Store feedback fact."""
        with self.conn:
            self.conn.execute("""
                INSERT OR REPLACE INTO feedback_facts 
                (fact_id, batch, fact_type, scope_kind, applies_to, 
                 valid_from, valid_to, value, decided_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (fact_id, batch, fact_type, scope_kind, json.dumps(applies_to),
                  valid_from, valid_to, json.dumps(value), decided_at))
    
    def get_feedback_facts(self, fact_type: str = None) -> list[dict]:
        """Retrieve feedback facts."""
        query = "SELECT * FROM feedback_facts"
        params = []
        
        if fact_type:
            query += " WHERE fact_type = ?"
            params.append(fact_type)
        
        query += " ORDER BY decided_at"
        
        cursor = self.conn.execute(query, params)
        results = []
        for row in cursor.fetchall():
            d = dict(row)
            d['applies_to'] = json.loads(d['applies_to'])
            d['value'] = json.loads(d['value'])
            results.append(d)
        return results
    
    def get_batches_seen(self, as_of: str = None) -> list[str]:
        """Get list of batches ingested, optionally up to as_of date."""
        query = "SELECT DISTINCT batch FROM documents"
        params = []
        
        if as_of:
            query += " WHERE received_date <= ?"
            params.append(as_of)
        
        query += " ORDER BY batch"
        
        cursor = self.conn.execute(query, params)
        return [row[0] for row in cursor.fetchall()]
    
    def close(self):
        """Close database connection."""
        self.conn.close()
