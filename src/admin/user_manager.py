"""
ユーザー管理モジュール
Firestoreにユーザー情報（ロール/最大機密度/テナント）を保存・更新
"""
from typing import Optional, Dict, Any, List
from datetime import datetime
import logging
from google.cloud import firestore


class UserManager:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.db = firestore.Client()
        self.collection = "users"

    def get_user(self, email: str) -> Optional[Dict[str, Any]]:
        try:
            doc = self.db.collection(self.collection).document(email).get()
            return doc.to_dict() if doc.exists else None
        except Exception as e:
            self.logger.error(f"Failed to get user {email}: {e}")
            return None

    def ensure_user(self, email: str, defaults: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        defaults = defaults or {"role": "user", "max_conf_level": 0}
        now = datetime.utcnow()
        payload = {"email": email, **defaults, "updated_at": now}
        try:
            ref = self.db.collection(self.collection).document(email)
            if not ref.get().exists:
                payload["created_at"] = now
            ref.set(payload, merge=True)
            return payload
        except Exception as e:
            self.logger.error(f"Failed to ensure user {email}: {e}")
            return defaults

    def upsert_user(self, email: str, role: str, max_conf_level: int, tenant_id: Optional[str] = None) -> bool:
        try:
            max_conf_level = int(max_conf_level)
            if max_conf_level < 0: max_conf_level = 0
            if max_conf_level > 3: max_conf_level = 3
            payload: Dict[str, Any] = {
                "email": email,
                "role": role,
                "max_conf_level": max_conf_level,
                "status": "active",
                "updated_at": datetime.utcnow(),
            }
            if tenant_id:
                payload["tenant_id"] = tenant_id
            ref = self.db.collection(self.collection).document(email)
            if not ref.get().exists:
                payload["created_at"] = datetime.utcnow()
            ref.set(payload, merge=True)
            return True
        except Exception as e:
            self.logger.error(f"Failed to upsert user {email}: {e}")
            return False

    def list_users(self) -> List[Dict[str, Any]]:
        try:
            return [d.to_dict() for d in self.db.collection(self.collection).limit(500).stream()]
        except Exception as e:
            self.logger.error(f"Failed to list users: {e}")
            return []

    def set_status(self, email: str, status: str) -> bool:
        """status: active | disabled | deleted(論理)"""
        if status not in ["active", "disabled", "deleted"]:
            return False
        try:
            self.db.collection(self.collection).document(email).set({
                "status": status,
                "updated_at": datetime.utcnow()
            }, merge=True)
            return True
        except Exception as e:
            self.logger.error(f"Failed to set status for {email}: {e}")
            return False


