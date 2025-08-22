import os
import json
import gzip
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from datetime import datetime
import pytz
from typing import Dict, List, Optional, Any
import time


class S3Manager:
    def __init__(
        self,
        aws_access_key: str = None,
        aws_secret_key: str = None,
        bucket_name: str = None,
        region: str = None,
    ):
        """
        初始化 S3 管理器

        Args:
            aws_access_key: AWS Access Key
            aws_secret_key: AWS Secret Key
            bucket_name: S3 Bucket 名稱
            region: AWS Region
        """
        # 從環境變數或參數取得設定
        self.aws_access_key = aws_access_key or os.getenv("AWS_ACCESS_KEY", "")
        self.aws_secret_key = aws_secret_key or os.getenv("AWS_SECRET_KEY", "")
        self.bucket_name = bucket_name or os.getenv("S3_BUCKET_NAME", "")
        self.region = region or os.getenv("S3_REGION", "ap-northeast-1")

        # 台灣時區
        self.taiwan_tz = pytz.timezone("Asia/Taipei")

        # 初始化 S3 客戶端
        self.s3_client = self._initialize_s3_client()

    def _initialize_s3_client(self):
        """初始化 S3 客戶端"""
        try:
            s3_client = boto3.client(
                "s3",
                aws_access_key_id=self.aws_access_key,
                aws_secret_access_key=self.aws_secret_key,
                region_name=self.region,
            )
            print("S3 客戶端初始化成功")
            return s3_client
        except Exception as e:
            print(f"S3 客戶端初始化失敗: {str(e)}")
            return None

    def save_audit_log_to_file(
        self, user_mail: str, audit_logs: List[Dict]
    ) -> Optional[str]:
        """
        將用戶的稽核日誌保存到本地 JSON 檔案（增量更新）

        Args:
            user_mail: 使用者信箱
            audit_logs: 稽核日誌清單

        Returns:
            str: 檔案路徑，失敗則回傳 None
        """
        if not audit_logs:
            return None

        taiwan_now = datetime.now(self.taiwan_tz)
        date_str = taiwan_now.strftime("%Y-%m-%d")

        # 創建統一的本地儲存目錄
        log_dir = "./local_audit_logs"
        os.makedirs(log_dir, exist_ok=True)

        # 檔案路徑：使用 mail_日期.json 格式
        filename = f"{user_mail}_{date_str}.json"
        file_path = os.path.join(log_dir, filename)

        # 保存為 JSON（完全覆蓋，因為 audit_logs 包含所有記錄）
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(audit_logs, f, ensure_ascii=False, indent=2)

            print(f"稽核日誌已更新到: {file_path}")
            return file_path
        except Exception as e:
            print(f"保存稽核日誌失敗: {str(e)}")
            return None

    def append_single_log_to_file(
        self, user_mail: str, log_entry: Dict
    ) -> Optional[str]:
        """
        將單一日誌項目增量添加到本地 JSON 檔案

        Args:
            user_mail: 使用者信箱
            log_entry: 單一日誌條目

        Returns:
            str: 檔案路徑，失敗則回傳 None
        """
        taiwan_now = datetime.now(self.taiwan_tz)
        date_str = taiwan_now.strftime("%Y-%m-%d")

        # 創建統一的本地儲存目錄
        log_dir = "./local_audit_logs"
        os.makedirs(log_dir, exist_ok=True)

        # 檔案路徑：使用 mail_日期.json 格式
        filename = f"{user_mail}_{date_str}.json"
        file_path = os.path.join(log_dir, filename)

        try:
            # 讀取現有檔案（如果存在）
            existing_logs = []
            if os.path.exists(file_path):
                with open(file_path, "r", encoding="utf-8") as f:
                    existing_logs = json.load(f)

            # 添加新的日誌條目
            existing_logs.append(log_entry)

            # 寫回檔案
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(existing_logs, f, ensure_ascii=False, indent=2)

            print(f"日誌已增量添加到: {file_path}")
            return file_path

        except Exception as e:
            print(f"增量添加日誌失敗: {str(e)}")
            return None

    async def upload_file_to_s3(self, user_mail: str, file_path: str) -> bool:
        """
        上傳檔案到 S3

        Args:
            user_mail: 使用者信箱
            file_path: 本地檔案路徑

        Returns:
            bool: 上傳成功與否
        """
        if not self.s3_client or not file_path or not os.path.exists(file_path):
            return False

        try:
            taiwan_now = datetime.now(self.taiwan_tz)
            date_str = taiwan_now.strftime("%Y-%m-%d")
            timestamp_str = taiwan_now.strftime("%Y%m%d_%H%M%S")  # 精確到秒的時間戳

            # 本地檔案格式：mail_日期.json（例如：user@example.com_2025-08-22.json）
            # S3 檔案格式：mail_日期_時分秒.json.gz（例如：user@example.com_2025-08-22_143025.json.gz）
            base_filename = os.path.basename(
                file_path
            )  # 獲取檔名，格式如 mail_日期.json
            name_without_ext = os.path.splitext(base_filename)[0]  # 移除 .json 副檔名
            s3_filename = f"{name_without_ext}_{timestamp_str}.json"  # 加上時間戳

            s3_key = f"trgpt/{user_mail}/{date_str}/{s3_filename}"

            # 壓縮檔案
            compressed_file_path = f"{file_path}.gz"
            with open(file_path, "rb") as f_in:
                with gzip.open(compressed_file_path, "wb") as f_out:
                    f_out.writelines(f_in)

            # 上傳到 S3
            self.s3_client.upload_file(
                compressed_file_path,
                self.bucket_name,
                f"{s3_key}.gz",
                ExtraArgs={"ContentType": "application/gzip"},
            )

            print(f"成功上傳到 S3: s3://{self.bucket_name}/{s3_key}.gz")

            # 刪除本地檔案
            try:
                os.remove(file_path)
                os.remove(compressed_file_path)
                print(f"已刪除本地檔案: {file_path}")
            except Exception as e:
                print(f"刪除本地檔案失敗: {str(e)}")

            return True

        except Exception as e:
            print(f"上傳到 S3 失敗: {str(e)}")
            return False

    async def upload_audit_logs(
        self, user_mail: str, audit_logs: List[Dict]
    ) -> Dict[str, Any]:
        """
        上傳指定用戶的稽核日誌到 S3

        Args:
            user_mail: 使用者信箱
            audit_logs: 稽核日誌清單

        Returns:
            Dict: 上傳結果
        """
        if not audit_logs:
            return {"success": False, "message": "沒有找到該用戶的稽核日誌"}

        # 保存到檔案
        file_path = self.save_audit_log_to_file(user_mail, audit_logs)
        if not file_path:
            return {"success": False, "message": "保存稽核日誌檔案失敗"}

        # 上傳到 S3
        upload_success = await self.upload_file_to_s3(user_mail, file_path)

        if upload_success:
            return {"success": True, "message": f"成功上傳 {user_mail} 的稽核日誌"}
        else:
            return {"success": False, "message": "上傳到 S3 失敗"}

    def list_s3_audit_files(
        self, user_mail: str = None, date_filter: str = None
    ) -> List[Dict]:
        """
        列出 S3 中的稽核日誌檔案

        Args:
            user_mail: 特定使用者信箱 (可選)
            date_filter: 日期過濾 YYYY-MM-DD (可選)

        Returns:
            List[Dict]: 檔案清單
        """
        if not self.s3_client:
            return []

        try:
            prefix = "trgpt/"
            if user_mail and date_filter:
                prefix = f"trgpt/{user_mail}/{date_filter}/"
            elif user_mail:
                prefix = f"trgpt/{user_mail}/"

            response = self.s3_client.list_objects_v2(
                Bucket=self.bucket_name, Prefix=prefix
            )

            files = []
            if "Contents" in response:
                for obj in response["Contents"]:
                    if obj["Key"].endswith(".gz"):
                        # 解析 S3 key 格式: trgpt/user_mail/date/filename.gz
                        key_parts = obj["Key"].split("/")
                        if len(key_parts) >= 4 and key_parts[0] == "trgpt":
                            files.append(
                                {
                                    "key": obj["Key"],
                                    "user_mail": key_parts[1],
                                    "date": key_parts[2],
                                    "filename": key_parts[3],
                                    "size": obj["Size"],
                                    "last_modified": obj["LastModified"].strftime(
                                        "%Y-%m-%d %H:%M:%S"
                                    ),
                                    "download_url": f"s3://{self.bucket_name}/{obj['Key']}",
                                }
                            )

            return sorted(files, key=lambda x: x["last_modified"], reverse=True)

        except Exception as e:
            print(f"列出 S3 檔案失敗: {str(e)}")
            return []

    def download_audit_file_from_s3(self, s3_key: str) -> Optional[bytes]:
        """
        從 S3 下載稽核日誌檔案

        Args:
            s3_key: S3 檔案 key

        Returns:
            bytes: 解壓縮後的檔案內容，失敗則回傳 None
        """
        if not self.s3_client:
            return None

        try:
            # 下載檔案到記憶體
            response = self.s3_client.get_object(Bucket=self.bucket_name, Key=s3_key)
            compressed_data = response["Body"].read()

            # 解壓縮
            if s3_key.endswith(".gz"):
                decompressed_data = gzip.decompress(compressed_data)
                return decompressed_data
            else:
                return compressed_data

        except Exception as e:
            print(f"從 S3 下載檔案失敗: {str(e)}")
            return None

    def generate_presigned_download_url(
        self, s3_key: str, expiration: int = 3600
    ) -> Optional[str]:
        """
        生成 Pre-Signed URL 用於下載檔案

        Args:
            s3_key: S3 檔案 key
            expiration: URL 過期時間（秒），默認 1 小時

        Returns:
            str: Pre-Signed URL，失敗則回傳 None
        """
        if not self.s3_client:
            return None

        try:
            response = self.s3_client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket_name, "Key": s3_key},
                ExpiresIn=expiration,
            )
            return response
        except Exception as e:
            print(f"生成 Pre-Signed URL 失敗: {str(e)}")
            return None

    def get_bucket_info(self) -> Dict[str, Any]:
        """
        取得 S3 Bucket 資訊

        Returns:
            Dict: Bucket 資訊
        """
        info = {
            "bucket_name": self.bucket_name,
            "region": self.region,
            "client_initialized": self.s3_client is not None,
            "total_files": 0,
            "total_size": 0,
        }

        if self.s3_client:
            try:
                response = self.s3_client.list_objects_v2(Bucket=self.bucket_name)
                if "Contents" in response:
                    info["total_files"] = len(response["Contents"])
                    info["total_size"] = sum(
                        obj["Size"] for obj in response["Contents"]
                    )
            except Exception as e:
                info["error"] = str(e)

        return info
