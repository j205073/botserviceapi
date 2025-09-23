"""
稽核日誌業務邏輯服務
重構自原始 app.py 中的稽核日誌相關功能
"""
from typing import List, Dict, Any, Optional
import os
import json
import logging
from datetime import datetime, timedelta

from domain.models.audit import AuditLog, AuditLogEntry, MessageRole
from domain.repositories.audit_repository import AuditRepository
from config.settings import AppConfig
from shared.exceptions import BusinessLogicError
from shared.utils.helpers import get_taiwan_time


class AuditService:
    """稽核日誌業務邏輯服務"""
    
    def __init__(self, config: AppConfig, audit_repository: AuditRepository, s3_client=None):
        self.config = config
        self.audit_repository = audit_repository
        self.s3_client = s3_client
        self._logger = logging.getLogger(__name__)
    
    async def log_user_message(
        self, 
        conversation_id: str,
        user_mail: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLogEntry:
        """記錄用戶訊息到稽核日誌"""
        entry = await self.audit_repository.create_entry(
            conversation_id=conversation_id,
            user_mail=user_mail,
            role=MessageRole.USER,
            content=content,
            metadata=metadata or {}
        )
        # 即時增量寫入本地檔案
        self._append_local_log_entry(user_mail, entry)
        return entry
    
    async def log_assistant_message(
        self, 
        conversation_id: str,
        user_mail: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLogEntry:
        """記錄助手訊息到稽核日誌"""
        entry = await self.audit_repository.create_entry(
            conversation_id=conversation_id,
            user_mail=user_mail,
            role=MessageRole.ASSISTANT,
            content=content,
            metadata=metadata or {}
        )
        self._append_local_log_entry(user_mail, entry)
        return entry
    
    async def log_system_action(
        self, 
        conversation_id: str,
        user_mail: str,
        action_description: str,
        metadata: Optional[Dict[str, Any]] = None
    ) -> AuditLogEntry:
        """記錄系統動作到稽核日誌"""
        entry = await self.audit_repository.create_entry(
            conversation_id=conversation_id,
            user_mail=user_mail,
            role=MessageRole.SYSTEM,
            content=action_description,
            metadata=metadata or {}
        )
        self._append_local_log_entry(user_mail, entry)
        return entry
    
    async def log_admin_action(
        self, 
        admin_mail: str,
        action: str,
        target_user: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ) -> AuditLogEntry:
        """記錄管理員操作"""
        metadata = {
            "admin_action": True,
            "target_user": target_user,
            "details": details or {}
        }
        
        content = f"管理員動作: {action}"
        if target_user:
            content += f" (目標用戶: {target_user})"
        
        return await self.audit_repository.create_entry(
            conversation_id="ADMIN_ACTION",
            user_mail=admin_mail,
            role=MessageRole.SYSTEM,
            content=content,
            metadata=metadata
        )
    
    async def get_user_audit_log(self, user_mail: str) -> Optional[AuditLog]:
        """獲取用戶的稽核日誌"""
        return await self.audit_repository.get_user_log(user_mail)
    
    async def get_conversation_history(self, conversation_id: str) -> List[AuditLogEntry]:
        """獲取對話的完整歷史記錄"""
        return await self.audit_repository.get_entries_by_conversation(conversation_id)
    
    async def get_user_recent_activity(
        self, 
        user_mail: str, 
        hours: int = 24
    ) -> List[AuditLogEntry]:
        """獲取用戶最近的活動記錄"""
        since_time = get_taiwan_time() - timedelta(hours=hours)
        return await self.audit_repository.get_entries_by_user_after(user_mail, since_time)
    
    async def get_audit_summary(self) -> Dict[str, Any]:
        """獲取所有用戶稽核日誌摘要（系統層級）"""
        users = await self.audit_repository.get_all_users_with_logs()

        summary_users: List[Dict[str, Any]] = []
        total_pending = 0

        for user_mail in users:
            user_log = await self.audit_repository.get_user_log(user_mail)
            pending = len(user_log.entries) if user_log else 0
            total_pending += pending
            last_updated = user_log.last_updated.isoformat() if user_log and user_log.last_updated else None
            if pending:
                summary_users.append({
                    "user_mail": user_mail,
                    "pending_logs": pending,
                    "last_activity": last_updated,
                })

        return {
            "total_users": len(users),
            "total_pending_logs": total_pending,
            "retention_days": self.config.database.retention_days,
            "s3_bucket": self.config.s3.bucket_name,
            "users": summary_users,
        }
    
    async def export_user_audit_logs(self, user_mail: str) -> List[Dict[str, Any]]:
        """匯出用戶稽核日誌"""
        return await self.audit_repository.export_user_logs(user_mail)
    
    async def clean_old_audit_logs(
        self, 
        user_mail: str, 
        retention_days: Optional[int] = None
    ) -> int:
        """清理用戶的舊稽核日誌"""
        days = retention_days or self.config.database.retention_days
        cutoff_time = get_taiwan_time() - timedelta(days=days)
        
        return await self.audit_repository.clear_user_entries_before(user_mail, cutoff_time)
    
    async def get_all_users_with_logs(self) -> List[str]:
        """獲取所有有稽核日誌的用戶"""
        return await self.audit_repository.get_all_users_with_logs()
    
    async def get_system_audit_overview(self) -> Dict[str, Any]:
        """獲取系統稽核總覽"""
        all_users = await self.get_all_users_with_logs()
        
        overview = {
            "total_users": len(all_users),
            "users": [],
            "total_entries": 0,
            "last_24h_entries": 0,
            "timestamp": get_taiwan_time().isoformat()
        }
        
        # 統計各用戶的日誌摘要
        for user_mail in all_users:
            user_summary = await self.audit_repository.get_user_log_summary(user_mail)
            overview["users"].append(user_summary)
            overview["total_entries"] += user_summary.get("total_entries", 0)
        
        # 統計最近 24 小時的活動
        day_ago = get_taiwan_time() - timedelta(hours=24)
        for user_mail in all_users:
            recent_entries = await self.audit_repository.get_entries_by_user_after(user_mail, day_ago)
            overview["last_24h_entries"] += len(recent_entries)
        
        return overview
    
    async def search_audit_logs(
        self, 
        user_mail: Optional[str] = None,
        conversation_id: Optional[str] = None,
        role: Optional[MessageRole] = None,
        keyword: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 100
    ) -> List[AuditLogEntry]:
        """搜索稽核日誌"""
        # 這是一個簡化的搜索實現
        # 在生產環境中，應該考慮更高效的搜索機制
        
        if conversation_id:
            entries = await self.get_conversation_history(conversation_id)
        elif user_mail:
            user_log = await self.get_user_audit_log(user_mail)
            entries = user_log.entries if user_log else []
        else:
            # 搜索所有用戶（性能考量，實際使用時應該分頁）
            all_users = await self.get_all_users_with_logs()
            entries = []
            for u_mail in all_users[:10]:  # 限制搜索前10個用戶
                user_log = await self.get_user_audit_log(u_mail)
                if user_log:
                    entries.extend(user_log.entries)
        
        # 應用過濾條件
        filtered_entries = entries
        
        if role:
            filtered_entries = [e for e in filtered_entries if e.role == role]
        
        if keyword:
            keyword_lower = keyword.lower()
            filtered_entries = [
                e for e in filtered_entries 
                if keyword_lower in e.content.lower()
            ]
        
        if date_from:
            filtered_entries = [
                e for e in filtered_entries 
                if e.timestamp >= date_from
            ]
        
        if date_to:
            filtered_entries = [
                e for e in filtered_entries 
                if e.timestamp <= date_to
            ]
        
        # 按時間排序並限制結果數量
        filtered_entries.sort(key=lambda x: x.timestamp, reverse=True)
        return filtered_entries[:limit]
    
    async def get_audit_stats_by_date_range(
        self, 
        user_mail: str,
        days: int = 7
    ) -> Dict[str, Any]:
        """獲取指定日期範圍內的稽核統計"""
        since_date = get_taiwan_time() - timedelta(days=days)
        entries = await self.audit_repository.get_entries_by_user_after(user_mail, since_date)
        
        # 按角色統計
        role_stats = {}
        date_stats = {}
        
        for entry in entries:
            # 角色統計
            role_key = entry.role.value
            role_stats[role_key] = role_stats.get(role_key, 0) + 1
            
            # 日期統計
            date_key = entry.timestamp.strftime('%Y-%m-%d')
            date_stats[date_key] = date_stats.get(date_key, 0) + 1
        
        return {
            "user_mail": user_mail,
            "date_range_days": days,
            "total_entries": len(entries),
            "role_stats": role_stats,
            "daily_stats": date_stats,
            "average_daily": len(entries) / max(days, 1)
        }

    # === 兼容 app_bak.py 的擴充方法 ===

    async def log_message(self, conversation_id: str, message: Dict[str, Any], user_mail: str) -> AuditLogEntry:
        """通用記錄方法（兼容舊版呼叫）。

        message 需包含 keys: role(user|assistant|system), content。
        """
        role = (message.get("role") or "").lower()
        content = message.get("content", "")
        metadata = {k: v for k, v in message.items() if k not in {"role", "content"}}

        if role == "user":
            return await self.log_user_message(conversation_id, user_mail, content, metadata)
        elif role == "assistant":
            return await self.log_assistant_message(conversation_id, user_mail, content, metadata)
        else:
            return await self.log_system_action(conversation_id, user_mail, content, metadata)

    async def get_user_audit_status(self, user_mail: str) -> Dict[str, Any]:
        """查詢用戶稽核日誌狀態（待上傳數、最近時間）。"""
        user_log = await self.audit_repository.get_user_log(user_mail)
        pending = len(user_log.entries) if user_log else 0
        last_activity = user_log.last_updated.isoformat() if user_log and user_log.last_updated else None
        return {
            "user_mail": user_mail,
            "pending_logs": pending,
            "last_activity": last_activity,
            "retention_days": self.config.database.retention_days,
        }

    async def upload_user_audit_logs(self, user_mail: str) -> Dict[str, Any]:
        """上傳指定用戶的稽核日誌到 S3，並清空已上傳的記錄。"""
        if not self.s3_client:
            raise BusinessLogicError("S3 客戶端未初始化，無法上傳稽核日誌")

        logs = await self.audit_repository.export_user_logs(user_mail)
        if not logs:
            return {"success": False, "message": "沒有找到該用戶的稽核日誌"}

        # 先將完整內容寫入本地檔案（方便稽核與除錯）
        taiwan_now = get_taiwan_time()
        date_str = taiwan_now.strftime("%Y-%m-%d")
        os.makedirs("./local_audit_logs", exist_ok=True)
        file_path = os.path.join("./local_audit_logs", f"{user_mail}_{date_str}.json")
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(logs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            return {"success": False, "message": f"保存稽核日誌檔案失敗: {e}"}

        # 照原本做法：以 AES ZIP（密碼 rinnai）上傳到 trgpt/{user_mail}/{YYYY-MM-DD}/
        try:
            import pyzipper  # type: ignore
        except Exception as e:
            return {"success": False, "message": f"zip 模組載入失敗: {e}"}

        timestamp_str = taiwan_now.strftime("%Y%m%d_%H%M%S")
        base_filename = os.path.basename(file_path)
        name_without_ext = os.path.splitext(base_filename)[0]
        s3_filename_noext = f"{name_without_ext}_{timestamp_str}"
        s3_key = f"trgpt/{user_mail}/{date_str}/{s3_filename_noext}.json.zip"

        zip_path = f"{file_path}.zip"
        try:
            with pyzipper.AESZipFile(
                zip_path,
                "w",
                compression=pyzipper.ZIP_DEFLATED,
                encryption=pyzipper.WZ_AES,
            ) as zf:
                zf.setpassword(b"rinnai")
                with open(file_path, "rb") as src:
                    data = src.read()
                zf.writestr(os.path.basename(file_path), data)

            # 透過 S3 原生 client 上傳 zip
            loop = __import__("asyncio").get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.s3_client.client.upload_file(
                    zip_path,
                    self.s3_client.bucket_name,
                    s3_key,
                    ExtraArgs={"ContentType": "application/zip"},
                ),
            )
            ok = True
        except Exception as e:
            ok = False
            upload_err = e
        finally:
            # 刪除本地檔案（原始與壓縮）
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
                if os.path.exists(zip_path):
                    os.remove(zip_path)
            except Exception as e:
                self._logger.warning(f"清理本地檔案失敗: {e}")

        if not ok:
            return {"success": False, "message": f"上傳到 S3 失敗: {upload_err}"}

        if ok:
            # 清空已上傳的記錄
            try:
                await self.audit_repository.clear_uploaded_logs([user_mail])
            except Exception:
                pass
            return {"success": True, "message": f"成功上傳 {user_mail} 的稽核日誌", "s3_key": s3_key}
        else:
            return {"success": False, "message": "上傳到 S3 失敗"}

    async def upload_all_users_audit_logs(self) -> Dict[str, Any]:
        """上傳所有用戶的稽核日誌到 S3。"""
        if not self.s3_client:
            raise BusinessLogicError("S3 客戶端未初始化，無法上傳稽核日誌")

        # 收集要上傳的所有使用者及其日誌
        try:
            logs_map = await self.audit_repository.get_logs_for_upload()  # type: ignore[attr-defined]
        except AttributeError:
            # 後備方案：逐一讀取使用者日誌
            logs_map = {}
            for u in await self.audit_repository.get_all_users_with_logs():
                user_log = await self.audit_repository.export_user_logs(u)
                if user_log:
                    logs_map[u] = user_log

        results: List[Dict[str, Any]] = []
        total_files = 0
        total_success = 0
        total_failed = 0
        users_processed: List[str] = []

        for user_mail, logs in logs_map.items():
            if not logs:
                continue
            users_processed.append(user_mail)
            total_files += 1
            result = await self.upload_user_audit_logs(user_mail)
            if result.get("success"):
                total_success += 1
            else:
                total_failed += 1
            results.append({"user_mail": user_mail, **result})

        message = f"處理完成，共 {total_files} 個檔案，成功 {total_success}，失敗 {total_failed}"
        return {
            "success": total_failed == 0,
            "message": message,
            "users_processed": users_processed,
            "total_files": total_files,
            "success_files": total_success,
            "failed_files": total_failed,
            "details": results,
        }

    async def list_audit_files(
        self,
        user_mail: Optional[str] = None,
        date_filter: Optional[str] = None,
        include_download_url: bool = False,
        expiration: int = 3600,
    ) -> List[Dict[str, Any]]:
        """列出 S3 中的稽核日誌檔案。

        若提供 user_mail/date_filter，嘗試加上前綴過濾；否則列出 audit-logs/ 整體清單。
        """
        if not self.s3_client:
            raise BusinessLogicError("S3 客戶端未初始化，無法列出檔案")

        # 決定要查詢的前綴候選（優先舊 -> 新，確保兼容舊資料）
        prefixes: List[str]
        if user_mail and date_filter:
            prefixes = [f"trgpt/{user_mail}/{date_filter}/", "audit-logs/"]
        elif user_mail:
            prefixes = [f"trgpt/{user_mail}/", "audit-logs/"]
        else:
            prefixes = ["audit-logs/", "trgpt/"]

        seen_keys = set()
        objects: List[Dict[str, Any]] = []
        for p in prefixes:
            try:
                resp = await self.s3_client.list_objects(prefix=p)
            except Exception:
                resp = []
            for obj in resp:
                k = obj.get("key") or obj.get("Key")
                if not k or k in seen_keys:
                    continue
                seen_keys.add(k)
                objects.append(obj)

        files: List[Dict[str, Any]] = []
        for obj in objects:
            key = obj.get("key") or obj.get("Key")
            if not key:
                continue
            if not (key.endswith(".json") or key.endswith(".json.gz") or key.endswith(".gz") or key.endswith(".zip")):
                continue
            info: Dict[str, Any] = {
                "key": key,
                "size": obj.get("size"),
                "last_modified": obj.get("last_modified"),
            }

            # 嘗試解析舊的 key 結構：trgpt/user_mail/date/filename
            parts = key.split("/")
            if len(parts) >= 4 and parts[0] == "trgpt":
                info.update({
                    "user_mail": parts[1],
                    "date": parts[2],
                    "filename": parts[3],
                })

            if include_download_url:
                try:
                    info["presigned_download_url"] = await self.s3_client.generate_presigned_url(key, expiration)
                except Exception:
                    info["presigned_download_url"] = None

            files.append(info)

        # 依最後修改時間排序（若可用）
        files.sort(key=lambda x: x.get("last_modified", ""), reverse=True)
        return files

    async def generate_download_url(self, s3_key: str, expiration: int = 3600) -> str:
        """取得指定 S3 物件的預簽名下載 URL。"""
        if not self.s3_client:
            raise BusinessLogicError("S3 客戶端未初始化，無法生成下載連結")
        exists = await self.s3_client.object_exists(s3_key)
        if not exists:
            from shared.exceptions import NotFoundError
            raise NotFoundError(f"檔案不存在: {s3_key}")
        return await self.s3_client.generate_presigned_url(s3_key, expiration)

    async def get_s3_bucket_info(self) -> Dict[str, Any]:
        """獲取 S3 Bucket 資訊。"""
        if not self.s3_client:
            raise BusinessLogicError("S3 客戶端未初始化，無法取得桶資訊")
        return await self.s3_client.get_bucket_info()

    async def get_local_audit_files(self) -> List[Dict[str, Any]]:
        """查看本地稽核日誌檔案狀態（./local_audit_logs）。"""
        log_dir = "./local_audit_logs"
        files: List[Dict[str, Any]] = []
        if os.path.exists(log_dir):
            for filename in os.listdir(log_dir):
                if not filename.endswith(".json"):
                    continue
                file_path = os.path.join(log_dir, filename)
                try:
                    stats = os.stat(file_path)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            logs = json.load(f)
                            record_count = len(logs) if isinstance(logs, list) else 0
                    except Exception:
                        record_count = -1
                    files.append({
                        "filename": filename,
                        "path": file_path,
                        "size": stats.st_size,
                        "modified": datetime.fromtimestamp(stats.st_mtime).isoformat(),
                        "record_count": record_count,
                    })
                except Exception:
                    continue
        return sorted(files, key=lambda x: x.get("modified", ""), reverse=True)

    # 內部：增量寫入本地稽核檔案（每日一檔）
    def _append_local_log_entry(self, user_mail: str, entry: AuditLogEntry) -> None:
        try:
            taiwan_now = get_taiwan_time()
            date_str = taiwan_now.strftime("%Y-%m-%d")
            log_dir = "./local_audit_logs"
            os.makedirs(log_dir, exist_ok=True)
            file_path = os.path.join(log_dir, f"{user_mail}_{date_str}.json")

            existing_logs = []
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        existing_logs = json.load(f)
                        if not isinstance(existing_logs, list):
                            existing_logs = []
                except Exception:
                    existing_logs = []

            existing_logs.append(entry.to_dict())

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(existing_logs, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self._logger.warning(f"寫入本地稽核檔失敗: {e}")
    
    async def validate_audit_integrity(self, user_mail: str) -> Dict[str, Any]:
        """驗證稽核日誌完整性"""
        user_log = await self.get_user_audit_log(user_mail)
        if not user_log:
            return {
                "user_mail": user_mail,
                "status": "no_logs",
                "issues": []
            }
        
        issues = []
        
        # 檢查時間序列是否正確
        entries = sorted(user_log.entries, key=lambda x: x.timestamp)
        for i in range(1, len(entries)):
            if entries[i].timestamp < entries[i-1].timestamp:
                issues.append(f"時間序列異常: 條目 {entries[i].id}")
        
        # 檢查是否有空內容
        empty_content = [e.id for e in entries if not e.content.strip()]
        if empty_content:
            issues.append(f"空內容條目: {len(empty_content)} 個")
        
        # 檢查對話ID格式
        invalid_conversation_ids = [
            e.id for e in entries 
            if not e.conversation_id or len(e.conversation_id) < 5
        ]
        if invalid_conversation_ids:
            issues.append(f"無效對話ID: {len(invalid_conversation_ids)} 個")
        
        return {
            "user_mail": user_mail,
            "total_entries": len(entries),
            "status": "valid" if not issues else "issues_found",
            "issues": issues,
            "validated_at": get_taiwan_time().isoformat()
        }
    
    async def generate_download_url(self, s3_key: str, expiration: int = 3600) -> Optional[str]:
        """生成S3檔案的預簽名下載URL"""
        try:
            if self.s3_client:
                # 使用S3客戶端生成預簽名URL
                return await self.s3_client.generate_presigned_url(s3_key, expiration)
            return None
        except Exception:
            return None
    
    async def get_local_audit_files(self) -> List[Dict[str, Any]]:
        """獲取本地稽核檔案列表"""
        import os
        import json
        from datetime import datetime
        
        try:
            log_dir = "./local_audit_logs"
            files = []
            
            if os.path.exists(log_dir):
                for filename in os.listdir(log_dir):
                    if filename.endswith(".json"):
                        file_path = os.path.join(log_dir, filename)
                        file_stats = os.stat(file_path)
                        
                        # 讀取檔案內容以獲取記錄數量
                        try:
                            with open(file_path, "r", encoding="utf-8") as f:
                                logs = json.load(f)
                                record_count = len(logs) if isinstance(logs, list) else 0
                        except:
                            record_count = -1
                        
                        files.append({
                            "filename": filename,
                            "path": file_path,
                            "size": file_stats.st_size,
                            "modified": datetime.fromtimestamp(file_stats.st_mtime).isoformat(),
                            "record_count": record_count
                        })
            
            return files
            
        except Exception:
            return []
