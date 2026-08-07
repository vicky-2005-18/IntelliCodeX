"""
Database & Persistent Storage Module (Phase 7)
Provides MongoDB document persistence with fallback to local JSON disk storage
when MongoDB is not reachable.
"""
import os
import json
import logging
from typing import Dict, Any, List, Optional
from backend.config import settings

logger = logging.getLogger("intellicodex.database")

# Check for pymongo
try:
    import pymongo
    HAS_PYMONGO = True
except ImportError:
    HAS_PYMONGO = False


class LocalDiskStore:
    """File-backed fallback database when MongoDB is offline."""
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._data: Dict[str, List[Dict[str, Any]]] = {
            "users": [],
            "repositories": [],
            "metadata": [],
            "chunks": [],
            "chat_history": [],
            "bug_reports": [],
            "generated_patches": [],
        }
        self._load()

    def _load(self):
        if os.path.exists(self.db_path):
            try:
                with open(self.db_path, "r", encoding="utf-8") as f:
                    self._data.update(json.load(f))
            except Exception as e:
                logger.warning(f"Failed to load local DB file: {e}")

    def _save(self):
        try:
            with open(self.db_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save local DB file: {e}")

    def insert_one(self, collection: str, document: Dict[str, Any]):
        if collection not in self._data:
            self._data[collection] = []
        self._data[collection].append(document)
        self._save()

    def find(self, collection: str, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        docs = self._data.get(collection, [])
        if not query:
            return docs
        results = []
        for doc in docs:
            match = True
            for k, v in query.items():
                if doc.get(k) != v:
                    match = False
                    break
            if match:
                results.append(doc)
        return results

    def find_one(self, collection: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        results = self.find(collection, query)
        return results[0] if results else None

    def update_one(self, collection: str, query: Dict[str, Any], update: Dict[str, Any]):
        doc = self.find_one(collection, query)
        if doc and "$set" in update:
            doc.update(update["$set"])
            self._save()


class DatabaseManager:
    def __init__(self):
        self.use_mongo = False
        self.client = None
        self.db = None
        self.fallback_store = LocalDiskStore(os.path.join(settings.STORAGE_DIR, "db.json"))
        
        if HAS_PYMONGO:
            try:
                self.client = pymongo.MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=1000)
                # Quick ping to check connection
                self.client.admin.command('ping')
                self.db = self.client[settings.MONGO_DB_NAME]
                self.use_mongo = True
                logger.info("Successfully connected to MongoDB.")
            except Exception as e:
                logger.info(f"MongoDB connection offline ({e}). Using persistent local disk store.")

    def insert(self, collection: str, document: Dict[str, Any]):
        if self.use_mongo:
            self.db[collection].insert_one(document.copy())
        else:
            self.fallback_store.insert_one(collection, document)

    def find_one(self, collection: str, query: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        if self.use_mongo:
            res = self.db[collection].find_one(query)
            if res and "_id" in res:
                res["_id"] = str(res["_id"])
            return res
        return self.fallback_store.find_one(collection, query)

    def find(self, collection: str, query: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        if self.use_mongo:
            cursor = self.db[collection].find(query or {})
            results = []
            for doc in cursor:
                if "_id" in doc:
                    doc["_id"] = str(doc["_id"])
                results.append(doc)
            return results
        return self.fallback_store.find(collection, query)

    def update(self, collection: str, query: Dict[str, Any], update_data: Dict[str, Any]):
        if self.use_mongo:
            self.db[collection].update_one(query, {"$set": update_data}, upsert=True)
        else:
            self.fallback_store.update_one(collection, query, {"$set": update_data})


db_manager = DatabaseManager()
