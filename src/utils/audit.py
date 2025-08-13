"""
監査ログ出力ユーティリティ
 - Firestore の `audit_logs` コレクションへ書き込み
 - Cloud Logging は標準ロガーにも出力
"""
from typing import Optional, Dict, Any
from datetime import datetime
import logging
import os
from google.cloud import firestore


class AuditLogger:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.db = firestore.Client()
        self.collection = "audit_logs"
        self.enabled = os.getenv("ENABLE_AUDIT", "true").lower() == "true"

    def log(self,
            action: str,
            actor_email: Optional[str] = None,
            resource: Optional[str] = None,
            severity: str = "INFO",
            details: Optional[Dict[str, Any]] = None) -> bool:
        if not self.enabled:
            return False
        try:
            payload: Dict[str, Any] = {
                "timestamp": datetime.utcnow().isoformat(),
                "action": action,
                "actor_email": actor_email,
                "resource": resource,
                "severity": severity,
                "details": details or {},
            }
            self.db.collection(self.collection).add(payload)
            self.logger.info(f"AUDIT {severity} {action} actor={actor_email} resource={resource}")
            return True
        except Exception as e:
            self.logger.error(f"Failed to write audit log: {e}")
            return False


