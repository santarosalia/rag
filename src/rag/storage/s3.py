import uuid
from dataclasses import dataclass

import boto3
from botocore.client import Config

from rag.config import get_settings


@dataclass
class StoredObject:
    key: str
    bucket: str
    url: str


class ObjectStorage:
    def __init__(self) -> None:
        settings = get_settings()
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            use_ssl=settings.s3_use_ssl,
            config=Config(signature_version="s3v4"),
        )

    def upload(self, data: bytes, filename: str, doc_id: uuid.UUID | None = None) -> StoredObject:
        doc_id = doc_id or uuid.uuid4()
        safe_name = filename.replace("/", "_")
        key = f"documents/{doc_id}/{safe_name}"
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType="application/octet-stream",
        )
        return StoredObject(key=key, bucket=self.bucket, url=f"s3://{self.bucket}/{key}")

    def download(self, key: str) -> bytes:
        response = self.client.get_object(Bucket=self.bucket, Key=key)
        return response["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)
