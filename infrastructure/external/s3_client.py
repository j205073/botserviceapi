"""
AWS S3 客戶端封裝
處理稽核日誌的上傳、下載和管理
"""
import asyncio
import boto3
from botocore.exceptions import ClientError, NoCredentialsError
from typing import List, Dict, Any, Optional, BinaryIO
import gzip
import json
import os
from datetime import datetime
import pytz

from config.settings import AppConfig
from shared.exceptions import S3ServiceError
from shared.utils.helpers import get_taiwan_time


class S3Client:
    """AWS S3 客戶端封裝"""
    
    def __init__(self, config: AppConfig):
        self.config = config
        self.bucket_name = config.s3.bucket_name
        self.region = config.s3.region
        
        # 初始化 S3 客戶端
        self._client = None
        self._initialize_client()
    
    def _initialize_client(self):
        """初始化 S3 客戶端"""
        try:
            if self.config.s3.access_key and self.config.s3.secret_key:
                self._client = boto3.client(
                    's3',
                    aws_access_key_id=self.config.s3.access_key,
                    aws_secret_access_key=self.config.s3.secret_key,
                    region_name=self.region
                )
            else:
                # 使用默認憑證（環境變數或 IAM 角色）
                self._client = boto3.client('s3', region_name=self.region)
                
            print("✅ S3 客戶端初始化成功")
            
        except Exception as e:
            print(f"❌ S3 客戶端初始化失敗: {e}")
            self._client = None
    
    @property
    def client(self):
        """獲取 S3 客戶端"""
        if not self._client:
            raise S3ServiceError("S3 客戶端未初始化")
        return self._client
    
    async def upload_file(
        self, 
        file_path: str, 
        s3_key: str, 
        compress: bool = True,
        metadata: Optional[Dict[str, str]] = None
    ) -> bool:
        """上傳文件到 S3"""
        try:
            if not os.path.exists(file_path):
                raise S3ServiceError(f"文件不存在: {file_path}")
            
            if not self.bucket_name:
                raise S3ServiceError("S3 儲存桶名稱未設置")
            
            # 準備上傳參數
            upload_args = {}
            
            if compress and file_path.endswith('.json'):
                # 壓縮 JSON 文件
                compressed_key = f"{s3_key}.gz"
                temp_compressed_file = f"{file_path}.gz"
                
                # 壓縮文件
                with open(file_path, 'rb') as f_in:
                    with gzip.open(temp_compressed_file, 'wb') as f_out:
                        f_out.write(f_in.read())
                
                upload_file_path = temp_compressed_file
                final_s3_key = compressed_key
                upload_args['ContentType'] = 'application/gzip'
                upload_args['ContentEncoding'] = 'gzip'
            else:
                upload_file_path = file_path
                final_s3_key = s3_key
                
                # 根據文件擴展名設置 Content-Type
                if file_path.endswith('.json'):
                    upload_args['ContentType'] = 'application/json'
                elif file_path.endswith('.txt'):
                    upload_args['ContentType'] = 'text/plain'
            
            # 設置元數據
            if metadata:
                upload_args['Metadata'] = metadata
            
            # 執行上傳
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.upload_file(
                    upload_file_path,
                    self.bucket_name,
                    final_s3_key,
                    ExtraArgs=upload_args
                )
            )
            
            # 清理臨時壓縮文件
            if compress and file_path.endswith('.json') and os.path.exists(temp_compressed_file):
                os.remove(temp_compressed_file)
            
            print(f"✅ 文件上傳成功: {final_s3_key}")
            return True
            
        except ClientError as e:
            error_msg = f"S3 上傳失敗: {str(e)}"
            print(f"❌ {error_msg}")
            raise S3ServiceError(error_msg) from e
        except Exception as e:
            error_msg = f"上傳文件時發生錯誤: {str(e)}"
            print(f"❌ {error_msg}")
            raise S3ServiceError(error_msg) from e
    
    async def download_file(self, s3_key: str, local_path: str) -> bool:
        """從 S3 下載文件"""
        try:
            if not self.bucket_name:
                raise S3ServiceError("S3 儲存桶名稱未設置")
            
            # 確保本地目錄存在
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.download_file(
                    self.bucket_name,
                    s3_key,
                    local_path
                )
            )
            
            print(f"✅ 文件下載成功: {s3_key} -> {local_path}")
            return True
            
        except ClientError as e:
            error_msg = f"S3 下載失敗: {str(e)}"
            print(f"❌ {error_msg}")
            raise S3ServiceError(error_msg) from e
        except Exception as e:
            error_msg = f"下載文件時發生錯誤: {str(e)}"
            print(f"❌ {error_msg}")
            raise S3ServiceError(error_msg) from e
    
    async def list_objects(
        self, 
        prefix: str = "", 
        max_keys: int = 1000
    ) -> List[Dict[str, Any]]:
        """列出 S3 物件"""
        try:
            if not self.bucket_name:
                raise S3ServiceError("S3 儲存桶名稱未設置")
            
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.list_objects_v2(
                    Bucket=self.bucket_name,
                    Prefix=prefix,
                    MaxKeys=max_keys
                )
            )
            
            objects = []
            for obj in response.get('Contents', []):
                objects.append({
                    'key': obj['Key'],
                    'size': obj['Size'],
                    'last_modified': obj['LastModified'].isoformat(),
                    'etag': obj['ETag'].strip('"')
                })
            
            return objects
            
        except ClientError as e:
            error_msg = f"列出 S3 物件失敗: {str(e)}"
            print(f"❌ {error_msg}")
            raise S3ServiceError(error_msg) from e
    
    async def delete_object(self, s3_key: str) -> bool:
        """刪除 S3 物件"""
        try:
            if not self.bucket_name:
                raise S3ServiceError("S3 儲存桶名稱未設置")
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.delete_object(
                    Bucket=self.bucket_name,
                    Key=s3_key
                )
            )
            
            print(f"✅ 物件刪除成功: {s3_key}")
            return True
            
        except ClientError as e:
            error_msg = f"刪除 S3 物件失敗: {str(e)}"
            print(f"❌ {error_msg}")
            raise S3ServiceError(error_msg) from e
    
    async def generate_presigned_url(
        self, 
        s3_key: str, 
        expiration: int = 3600,
        method: str = 'get_object'
    ) -> str:
        """生成預簽名 URL"""
        try:
            if not self.bucket_name:
                raise S3ServiceError("S3 儲存桶名稱未設置")
            
            loop = asyncio.get_event_loop()
            url = await loop.run_in_executor(
                None,
                lambda: self.client.generate_presigned_url(
                    method,
                    Params={'Bucket': self.bucket_name, 'Key': s3_key},
                    ExpiresIn=expiration
                )
            )
            
            return url
            
        except ClientError as e:
            error_msg = f"生成預簽名 URL 失敗: {str(e)}"
            print(f"❌ {error_msg}")
            raise S3ServiceError(error_msg) from e
    
    async def object_exists(self, s3_key: str) -> bool:
        """檢查物件是否存在"""
        try:
            if not self.bucket_name:
                return False
            
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.head_object(
                    Bucket=self.bucket_name,
                    Key=s3_key
                )
            )
            return True
            
        except ClientError as e:
            if e.response['Error']['Code'] == '404':
                return False
            raise S3ServiceError(f"檢查物件存在性失敗: {str(e)}") from e
    
    async def get_bucket_info(self) -> Dict[str, Any]:
        """獲取儲存桶資訊"""
        try:
            if not self.bucket_name:
                raise S3ServiceError("S3 儲存桶名稱未設置")
            
            loop = asyncio.get_event_loop()
            
            # 獲取儲存桶位置
            location = await loop.run_in_executor(
                None,
                lambda: self.client.get_bucket_location(Bucket=self.bucket_name)
            )
            
            # 獲取儲存桶大小（通過列出物件計算）
            response = await loop.run_in_executor(
                None,
                lambda: self.client.list_objects_v2(Bucket=self.bucket_name)
            )
            
            total_size = sum(obj['Size'] for obj in response.get('Contents', []))
            object_count = len(response.get('Contents', []))
            
            return {
                'bucket_name': self.bucket_name,
                'region': location.get('LocationConstraint', 'us-east-1'),
                'total_objects': object_count,
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2)
            }
            
        except ClientError as e:
            error_msg = f"獲取儲存桶資訊失敗: {str(e)}"
            print(f"❌ {error_msg}")
            raise S3ServiceError(error_msg) from e
    
    async def test_connection(self) -> Dict[str, Any]:
        """測試 S3 連接"""
        try:
            if not self._client:
                return {
                    "success": False,
                    "error": "S3 客戶端未初始化",
                    "configured": bool(self.config.s3.access_key and self.config.s3.secret_key)
                }
            
            if not self.bucket_name:
                return {
                    "success": False,
                    "error": "S3 儲存桶名稱未設置",
                    "configured": False
                }
            
            # 測試列出物件（限制為 1 個以減少開銷）
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.client.list_objects_v2(
                    Bucket=self.bucket_name,
                    MaxKeys=1
                )
            )
            
            return {
                "success": True,
                "message": "S3 連接測試成功",
                "bucket_name": self.bucket_name,
                "region": self.region,
                "object_count": response.get('KeyCount', 0)
            }
            
        except NoCredentialsError:
            return {
                "success": False,
                "error": "AWS 憑證未配置",
                "configured": False
            }
        except ClientError as e:
            return {
                "success": False,
                "error": f"S3 連接失敗: {str(e)}",
                "configured": True
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"S3 測試異常: {str(e)}",
                "configured": bool(self.config.s3.access_key)
            }
    
    def create_audit_log_key(self, user_mail: str, timestamp: Optional[datetime] = None) -> str:
        """創建稽核日誌的 S3 鍵名"""
        if not timestamp:
            timestamp = get_taiwan_time()
        
        # 格式: audit-logs/YYYY/MM/DD/user_mail_YYYYMMDD_HHMMSS.json.gz
        date_str = timestamp.strftime("%Y/%m/%d")
        filename = f"{user_mail}_{timestamp.strftime('%Y%m%d_%H%M%S')}.json.gz"
        
        return f"audit-logs/{date_str}/{filename}"