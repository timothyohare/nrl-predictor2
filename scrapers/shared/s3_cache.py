import boto3
from botocore.exceptions import ClientError


def save_raw(bucket: str, key: str, body: str, content_type: str = "application/json") -> None:
    boto3.client("s3").put_object(
        Bucket=bucket,
        Key=key,
        Body=body.encode(),
        ContentType=content_type,
    )


def load_raw(bucket: str, key: str) -> str | None:
    try:
        response = boto3.client("s3").get_object(Bucket=bucket, Key=key)
        return response["Body"].read().decode()
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return None
        raise
