""""
統合OCR処理モジュール
OpenAI Vision, EasyOCR, Tesseractを協調させてリッチなメタデータを生成する
条件付きでOCR機能を有効化し、利用できない場合は基本機能のみ動作
"""
from typing import List, Dict, Any, Optional
import logging
import hashlib
import os
import concurrent.futures
import time
import json

# 条件付きインポート
try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False
    logging.warning("OpenCV not available - OCR functionality will be limited")

try:
    import easyocr
    EASYOCR_AVAILABLE = True
except ImportError:
    EASYOCR_AVAILABLE = False
    logging.warning("EasyOCR not available - OCR functionality will be limited")

try:
    import pytesseract
    from PIL import Image
    TESSERACT_AVAILABLE = True
except ImportError:
    TESSERACT_AVAILABLE = False
    logging.warning("Tesseract not available - OCR functionality will be limited")

try:
    import openai
    import base64
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logging.warning("OpenAI not available - OCR functionality will be limited")

class UnifiedOCRProcessor:
    """
    統合OCRプロセッサー
    - OpenAI Vision API (GPT-5-mini) を主軸に、EasyOCRとTesseractでメタデータを補強する
    - 依存関係が利用できない場合は適切にフォールバック
    """
    
    def __init__(self, 
                 languages: List[str] = ['ja', 'en'],
                 enable_caching: bool = True,
                 max_workers: int = 3):
        """
        Args:
            languages: 対応言語リスト
            enable_caching: キャッシュ機能の有効化
            max_workers: 並列処理の最大ワーカー数
        """
        self.logger = logging.getLogger(__name__)
        self.languages = languages
        self.enable_caching = enable_caching
        self.max_workers = max_workers
        
        # 利用可能な機能をチェック
        self.openai_client = None
        self.easy_reader = None
        
        # キャッシュディレクトリの作成
        if enable_caching:
            self.cache_dir = "./ocr_cache"
            os.makedirs(self.cache_dir, exist_ok=True)
        
        # OpenAI クライアント初期化
        if OPENAI_AVAILABLE:
            try:
                api_key = os.getenv("OPENAI_API_KEY")
                if not api_key:
                    self.logger.warning("OPENAI_API_KEY environment variable not set")
                else:
                    self.openai_client = openai.OpenAI(api_key=api_key)
                    self.logger.info("OpenAI client initialized")
            except Exception as e:
                self.logger.warning(f"OpenAI client unavailable: {e}")
        
        # EasyOCR初期化
        if EASYOCR_AVAILABLE:
            try:
                self.easy_reader = easyocr.Reader(languages)
                self.logger.info("EasyOCR initialized")
            except Exception as e:
                self.logger.warning(f"EasyOCR unavailable: {e}")
        
        # 利用可能な機能をログ出力
        self._log_available_features()

    def _log_available_features(self):
        """利用可能な機能をログ出力"""
        features = []
        if self.openai_client:
            features.append("OpenAI Vision")
        if self.easy_reader:
            features.append("EasyOCR")
        if TESSERACT_AVAILABLE:
            features.append("Tesseract")
        
        if features:
            self.logger.info(f"Available OCR features: {', '.join(features)}")
        else:
            self.logger.warning("No OCR features available - basic functionality only")

    def is_ocr_available(self) -> bool:
        """OCR機能が利用可能かチェック"""
        return bool(self.openai_client or self.easy_reader or TESSERACT_AVAILABLE)

    def process_image(self, image_path: str) -> Dict[str, Any]:
        """
        画像からテキストとリッチなメタデータを抽出（統合処理）
        OCR機能が利用できない場合は基本情報のみ返す
        """
        # OCR機能が利用できない場合のフォールバック
        if not self.is_ocr_available():
            return self._fallback_image_processing(image_path)
        
        # キャッシュチェック
        if self.enable_caching:
            cache_key = self._generate_cache_key(image_path)
            cached_result = self._get_cached_result(cache_key)
            if cached_result:
                self.logger.info(f"Using cached OCR result for {image_path}")
                return cached_result

        # 画像読み込み
        if not CV2_AVAILABLE:
            return self._fallback_image_processing(image_path)
        
        image_for_ocr = cv2.imread(image_path)
        if image_for_ocr is None:
            return self._fallback_image_processing(image_path)

        base_result = {}
        supplemental_metadata = {}

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            # 主エンジン (OpenAI) を実行
            future_openai = executor.submit(self._process_with_openai_vision, image_path) if self.openai_client else None
            
            # 補助エンジン (EasyOCR, Tesseract) を実行
            future_easyocr = executor.submit(self._ocr_with_easyocr, image_for_ocr) if self.easy_reader else None
            future_tesseract = executor.submit(self._ocr_with_tesseract, image_for_ocr) if TESSERACT_AVAILABLE else None

            # OpenAIの結果を取得 (最優先)
            if future_openai:
                try:
                    base_result = future_openai.result(timeout=60)
                except Exception as e:
                    self.logger.error(f"OpenAI Vision processing failed: {e}")
                    base_result = {"text": "", "confidence": 0.0, "method": "openai_vision_failed", "metadata": {}}
            else:
                base_result = {"text": "", "confidence": 0.0, "method": "no_openai", "metadata": {}}

            # 補助エンジンの結果を収集
            if future_easyocr:
                try:
                    easyocr_result = future_easyocr.result(timeout=30)
                    if easyocr_result:
                        supplemental_metadata["easyocr_bbox"] = easyocr_result.get("metadata", {}).get("bbox", [])
                except Exception as e:
                    self.logger.warning(f"EasyOCR processing failed: {e}")

            if future_tesseract:
                try:
                    tesseract_result = future_tesseract.result(timeout=30)
                    if tesseract_result:
                        supplemental_metadata["tesseract_word_count"] = tesseract_result.get("metadata", {}).get("word_count", 0)
                except Exception as e:
                    self.logger.warning(f"Tesseract processing failed: {e}")

        # 結果の統合
        final_result = {
            "text": base_result.get("text", ""),
            "confidence": base_result.get("confidence", 0.0),
            "method": base_result.get("method", "unified_ocr"),
            "metadata": {
                **base_result.get("metadata", {}),
                **supplemental_metadata
            }
        }

        # キャッシュに保存
        if self.enable_caching:
            self._cache_result(cache_key, final_result)

        return final_result

    def _fallback_image_processing(self, image_path: str) -> Dict[str, Any]:
        """OCR機能が利用できない場合のフォールバック処理"""
        try:
            # 基本的なファイル情報のみ返す
            file_stat = os.stat(image_path)
            return {
                "text": "",
                "confidence": 0.0,
                "method": "fallback",
                "metadata": {
                    "file_name": os.path.basename(image_path),
                    "file_size": file_stat.st_size,
                    "creation_date": file_stat.st_ctime,
                    "modification_date": file_stat.st_mtime,
                    "ocr_available": False,
                    "message": "OCR functionality not available in this environment"
                }
            }
        except Exception as e:
            return {
                "text": "",
                "confidence": 0.0,
                "method": "fallback_error",
                "metadata": {
                    "error": str(e),
                    "ocr_available": False
                }
            }

    def _process_with_openai_vision(self, image_path: str) -> Dict[str, Any]:
        """
        OpenAI Vision APIを使用して画像を処理
        """
        if not self.openai_client:
            raise RuntimeError("OpenAI client not available")

        try:
            # 画像をbase64エンコード
            with open(image_path, "rb") as image_file:
                image_data = base64.b64encode(image_file.read()).decode('utf-8')

            # OpenAI Vision APIに送信
            response = self.openai_client.chat.completions.create(
                model="gpt-5-mini",  # GPT-5-miniに更新
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": """
                                この画像を分析して、以下のJSON形式で回答してください：
                                {
                                    "text": "画像から抽出されたテキスト",
                                    "confidence": 0.95,
                                    "description": "画像の内容の簡潔な説明",
                                    "keywords": ["検索に有効なキーワード1", "キーワード2"],
                                    "layout": "テキストの配置や構造の説明",
                                    "language": "検出された言語"
                                }
                                """
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                response_format={"type": "json_object"},
                max_tokens=1000
            )

            # レスポンスを解析
            content = response.choices[0].message.content
            result = json.loads(content)
            
            return {
                "text": result.get("text", ""),
                "confidence": result.get("confidence", 0.9),
                "method": "openai_vision",
                "metadata": {
                    "description": result.get("description", ""),
                    "keywords": result.get("keywords", []),
                    "layout": result.get("layout", ""),
                    "language": result.get("language", "unknown")
                }
            }

        except Exception as e:
            self.logger.error(f"OpenAI Vision processing failed: {e}")
            return {
                "text": "",
                "confidence": 0.0,
                "method": "openai_vision_failed",
                "metadata": {"error": str(e)}
            }

    def _generate_cache_key(self, image_path: str) -> str:
        """キャッシュキーを生成"""
        file_stat = os.stat(image_path)
        content = f"{image_path}_{file_stat.st_mtime}_{file_stat.st_size}"
        return hashlib.md5(content.encode()).hexdigest()

    def _get_cached_result(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """キャッシュから結果を取得"""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                self.logger.warning(f"Failed to load cache: {e}")
        return None

    def _cache_result(self, cache_key: str, result: Dict[str, Any]) -> None:
        """結果をキャッシュに保存"""
        cache_file = os.path.join(self.cache_dir, f"{cache_key}.json")
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning(f"Failed to save cache: {e}")

    def _ocr_with_easyocr(self, image: np.ndarray) -> Optional[Dict[str, Any]]:
        """EasyOCRを使用してOCR処理"""
        if not self.easy_reader or not CV2_AVAILABLE:
            return None

        try:
            results = self.easy_reader.readtext(image)
            if not results:
                return {"metadata": {"bbox": []}}

            bbox_list = []
            for (bbox, text, confidence) in results:
                bbox_list.append({
                    "coordinates": bbox.tolist(),
                    "text": text,
                    "confidence": float(confidence)
                })

            return {"metadata": {"bbox": bbox_list}}

        except Exception as e:
            self.logger.error(f"EasyOCR failed: {e}")
            return {"metadata": {"easyocr_error": str(e)}}

    def _ocr_with_tesseract(self, image: np.ndarray) -> Dict[str, Any]:
        """Tesseractを使用してOCR処理"""
        if not TESSERACT_AVAILABLE or not CV2_AVAILABLE:
            return {"metadata": {"tesseract_error": "Tesseract not available"}}

        try:
            # 画像をPIL形式に変換
            image_pil = Image.fromarray(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
            
            # TesseractでOCR実行
            text = pytesseract.image_to_string(image_pil, lang='jpn+eng')
            
            # 単語数をカウント
            word_count = len(text.split()) if text.strip() else 0
            
            return {
                "metadata": {
                    "word_count": word_count,
                    "tesseract_text": text.strip()
                }
            }
        except Exception as e:
            self.logger.error(f"Tesseract failed: {e}")
            return {"metadata": {"tesseract_error": str(e)}}