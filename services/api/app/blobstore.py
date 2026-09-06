from __future__ import annotations

import hashlib
import os
import uuid
from abc import ABC, abstractmethod
from pathlib import Path, PurePosixPath


class BlobNotFound(FileNotFoundError):
    pass


class BlobAlreadyExists(FileExistsError):
    pass


class BlobStore(ABC):
    """Small object-store boundary used by the API and worker.

    Keys, never host paths, cross this interface. An S3-compatible adapter can
    implement the same contract without changing the domain layer.
    """

    @abstractmethod
    def put(self, key: str, data: bytes, *, immutable: bool = False) -> None: ...

    @abstractmethod
    def get(self, key: str) -> bytes: ...

    @abstractmethod
    def exists(self, key: str) -> bool: ...

    @abstractmethod
    def delete(self, key: str) -> None: ...

    @abstractmethod
    def promote(self, source_key: str, destination_key: str) -> None: ...


class LocalBlobStore(BlobStore):
    def __init__(self, root: Path):
        self.root = root.resolve()

    def _path(self, key: str) -> Path:
        pure = PurePosixPath(key)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError("invalid opaque blob key")
        path = self.root.joinpath(*pure.parts).resolve()
        if path != self.root and self.root not in path.parents:
            raise ValueError("blob key escapes configured root")
        return path

    def put(self, key: str, data: bytes, *, immutable: bool = False) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        if immutable:
            try:
                with path.open("xb") as handle:
                    handle.write(data)
                return
            except FileExistsError as exc:
                raise BlobAlreadyExists(key) from exc
        # A process id is not unique across concurrent requests in one API
        # process.  A per-write nonce prevents duplicate PUT deliveries from
        # racing on (and replacing) the same temporary file.
        temporary = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)

    def get(self, key: str) -> bytes:
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as exc:
            raise BlobNotFound(key) from exc

    def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            return
        parent = path.parent
        while parent != self.root:
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent

    def promote(self, source_key: str, destination_key: str) -> None:
        data = self.get(source_key)
        destination = self._path(destination_key)
        if destination.exists():
            if hashlib.sha256(destination.read_bytes()).digest() == hashlib.sha256(data).digest():
                self.delete(source_key)
                return
            raise BlobAlreadyExists(destination_key)
        self.put(destination_key, data, immutable=True)
        self.delete(source_key)


class S3BlobStore(BlobStore):
    """S3-compatible implementation, imported lazily when explicitly selected."""

    def __init__(
        self,
        *,
        bucket: str,
        endpoint_url: str | None = None,
        region: str = "us-east-1",
        access_key_id: str | None = None,
        secret_access_key: str | None = None,
        prefix: str = "pocket-demo",
    ):
        try:
            import boto3
            from botocore.exceptions import ClientError
        except ImportError as exc:  # pragma: no cover - exercised without optional extra
            raise RuntimeError(
                "BLOB_STORE_BACKEND=s3 requires the optional boto3 dependency"
            ) from exc
        if not bucket:
            raise RuntimeError("S3_BUCKET is required when BLOB_STORE_BACKEND=s3")
        self.bucket = bucket
        self.prefix = prefix.strip("/")
        self._client_error = ClientError
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
        )

    def _key(self, key: str) -> str:
        pure = PurePosixPath(key)
        if pure.is_absolute() or ".." in pure.parts or not pure.parts:
            raise ValueError("invalid opaque blob key")
        suffix = "/".join(pure.parts)
        return f"{self.prefix}/{suffix}" if self.prefix else suffix

    def put(self, key: str, data: bytes, *, immutable: bool = False) -> None:
        if immutable and self.exists(key):
            raise BlobAlreadyExists(key)
        self.client.put_object(Bucket=self.bucket, Key=self._key(key), Body=data)

    def get(self, key: str) -> bytes:
        try:
            response = self.client.get_object(Bucket=self.bucket, Key=self._key(key))
        except self._client_error as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                raise BlobNotFound(key) from exc
            raise
        return response["Body"].read()

    def exists(self, key: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(key))
            return True
        except self._client_error as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            if code in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(key))

    def promote(self, source_key: str, destination_key: str) -> None:
        if self.exists(destination_key):
            if (
                hashlib.sha256(self.get(destination_key)).digest()
                == hashlib.sha256(self.get(source_key)).digest()
            ):
                self.delete(source_key)
                return
            raise BlobAlreadyExists(destination_key)
        self.client.copy_object(
            Bucket=self.bucket,
            Key=self._key(destination_key),
            CopySource={"Bucket": self.bucket, "Key": self._key(source_key)},
        )
        self.delete(source_key)


def create_blob_store(settings: object) -> BlobStore:
    backend = settings.blob_store_backend
    if backend == "filesystem":
        return LocalBlobStore(settings.blob_root)
    if backend == "s3":
        return S3BlobStore(
            bucket=settings.s3_bucket,
            endpoint_url=settings.s3_endpoint_url,
            region=settings.s3_region,
            access_key_id=settings.s3_access_key_id,
            secret_access_key=settings.s3_secret_access_key,
            prefix=settings.s3_key_prefix,
        )
    raise RuntimeError(f"Unsupported BLOB_STORE_BACKEND={backend!r}; use 'filesystem' or 's3'")
