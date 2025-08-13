"""
チャットのトークン使用量トラッカー（Firestore）
 24時間の使用量取得と記録
"""
from typing import Dict, Any
from datetime import datetime, timedelta
from google.cloud import firestore
import logging


class UsageTracker:
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.db = firestore.Client()
        self.collection = "chat_token_usage"

    def record(self, email: str, input_tokens: int, output_tokens: int) -> bool:
        try:
            now = datetime.utcnow()
            day_key = now.strftime("%Y-%m-%d")
            doc_id = f"{email}:{day_key}"
            ref = self.db.collection(self.collection).document(doc_id)
            snap = ref.get()
            base = {"email": email, "day": day_key, "input_tokens": 0, "output_tokens": 0, "updated_at": now}
            if snap.exists:
                base.update(snap.to_dict())
            base["input_tokens"] = int(base.get("input_tokens", 0)) + int(max(0, input_tokens))
            base["output_tokens"] = int(base.get("output_tokens", 0)) + int(max(0, output_tokens))
            base["updated_at"] = now
            ref.set(base, merge=True)
            return True
        except Exception as e:
            self.logger.error(f"Failed to record usage: {e}")
            return False

    def get_24h(self, email: str) -> Dict[str, int]:
        try:
            now = datetime.utcnow()
            yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            today = now.strftime("%Y-%m-%d")
            totals = {"input_tokens": 0, "output_tokens": 0}
            for day_key in [yesterday, today]:
                doc_id = f"{email}:{day_key}"
                snap = self.db.collection(self.collection).document(doc_id).get()
                if snap.exists:
                    d = snap.to_dict()
                    totals["input_tokens"] += int(d.get("input_tokens", 0))
                    totals["output_tokens"] += int(d.get("output_tokens", 0))
            return totals
        except Exception as e:
            self.logger.error(f"Failed to read usage: {e}")
            return {"input_tokens": 0, "output_tokens": 0}


