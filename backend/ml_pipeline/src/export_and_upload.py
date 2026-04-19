"""
Package model artifacts and upload them to the S3 model artifacts bucket.

By default the script also rolls the SageMaker endpoint forward to the new
artifact unless --skip-endpoint-update is provided.
"""
from __future__ import annotations

import argparse
import logging
import os
import pathlib
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from typing import Optional

import boto3
from botocore.exceptions import ClientError

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DEFAULT_S3_KEY = "models/nimbus-asl/model.tar.gz"
DEFAULT_ENDPOINT_NAME = os.environ.get("SAGEMAKER_ENDPOINT_NAME", "asl-endpoint")
DEFAULT_INSTANCE_TYPE = os.environ.get("SAGEMAKER_INSTANCE_TYPE", "ml.g5.xlarge")
DEFAULT_CONTAINER_IMAGE = os.environ.get(
    "SAGEMAKER_CONTAINER_IMAGE",
    "763104351884.dkr.ecr.us-west-2.amazonaws.com/pytorch-inference:2.1.0-gpu-py310",
)
DEFAULT_TIMEOUT_S = 20 * 60
DEFAULT_POLL_INTERVAL_S = 15

DEFAULT_STACK_NAME = os.environ.get("NIMBUS_STACK_NAME", "nimbus")
MODEL_ARTIFACTS_OUTPUT_KEY = "ModelArtifactsBucketName"


def resolve_bucket_from_stack(
    stack_name: str,
    output_key: str,
    region: Optional[str],
) -> Optional[str]:
    """Look up a bucket name from a CloudFormation stack's outputs.

    SAM templates suffix bucket names with AccountId/Region, so hard-coded
    names from PROTOCOLS.md will miss the real bucket. Calling describe_stacks
    at runtime keeps the script aligned with whatever `sam deploy` produced.
    """
    session = boto3.session.Session(region_name=region)
    cfn = session.client("cloudformation")
    try:
        response = cfn.describe_stacks(StackName=stack_name)
    except ClientError as exc:
        logger.warning(
            "CloudFormation describe_stacks failed for %s: %s",
            stack_name,
            exc.response.get("Error", {}).get("Message", str(exc)),
        )
        return None

    for stack in response.get("Stacks", []):
        for output in stack.get("Outputs", []) or []:
            if output.get("OutputKey") == output_key:
                value = output.get("OutputValue")
                if value:
                    logger.info(
                        "Resolved %s from stack %s -> %s",
                        output_key,
                        stack_name,
                        value,
                    )
                    return value
    logger.warning(
        "Output %s not found on stack %s; falling back to env/args.",
        output_key,
        stack_name,
    )
    return None


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def split_s3_uri(s3_uri: str) -> tuple[str, str]:
    if not s3_uri.startswith("s3://"):
        raise ValueError(f"Expected s3:// URI, got {s3_uri}")
    bucket_and_key = s3_uri[5:]
    bucket, _, key = bucket_and_key.partition("/")
    if not bucket or not key:
        raise ValueError(f"Expected s3://bucket/key format, got {s3_uri}")
    return bucket, key


def resolve_s3_target(
    bucket: Optional[str],
    key: str,
    s3_uri: Optional[str],
    stack_name: Optional[str] = None,
    region: Optional[str] = None,
) -> tuple[str, str]:
    if s3_uri:
        return split_s3_uri(s3_uri)
    if bucket:
        return bucket, key

    for env_name in ("MODEL_ARTIFACTS_BUCKET", "MODEL_ARTIFACTS_BUCKET_NAME", "NIMBUS_MODEL_ARTIFACTS_BUCKET"):
        env_value = os.environ.get(env_name)
        if env_value:
            return env_value, key

    # SAM generates account/region-suffixed bucket names; read the real one
    # from the stack outputs instead of guessing from PROTOCOLS.md.
    if stack_name:
        resolved = resolve_bucket_from_stack(
            stack_name=stack_name,
            output_key=MODEL_ARTIFACTS_OUTPUT_KEY,
            region=region,
        )
        if resolved:
            return resolved, key

    raise ValueError(
        "Could not resolve the model artifacts bucket. Provide --bucket/--s3-uri, "
        "set MODEL_ARTIFACTS_BUCKET, or deploy the SAM stack and pass --stack-name."
    )


def create_archive(model_dir: pathlib.Path, archive_path: pathlib.Path) -> pathlib.Path:
    model_path = model_dir / "model.pth"
    label_map_path = model_dir / "label_map.json"
    for required_path in (model_path, label_map_path):
        if not required_path.exists():
            raise FileNotFoundError(f"Required artifact not found: {required_path}")

    inference_entrypoint = pathlib.Path(__file__).resolve().parent / "inference" / "endpoint_handler.py"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "w:gz") as tar:
        tar.add(model_path, arcname="model.pth")
        tar.add(label_map_path, arcname="label_map.json")
        if inference_entrypoint.exists():
            tar.add(inference_entrypoint, arcname="code/inference.py")
    logger.info("Created archive -> %s", archive_path)
    return archive_path


def upload_archive(archive_path: pathlib.Path, bucket: str, key: str, region: Optional[str]) -> str:
    session = boto3.session.Session(region_name=region)
    s3 = session.client("s3")
    s3.upload_file(
        str(archive_path),
        bucket,
        key,
        ExtraArgs={"ServerSideEncryption": "AES256"},
    )
    s3_uri = f"s3://{bucket}/{key}"
    logger.info("Uploaded archive -> %s", s3_uri)
    return s3_uri


def endpoint_exists(sm_client, endpoint_name: str) -> bool:
    try:
        sm_client.describe_endpoint(EndpointName=endpoint_name)
        return True
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in {"ValidationException", "ResourceNotFound"}:
            return False
        raise


def create_model_and_config(
    sm_client,
    role_arn: str,
    s3_uri: str,
    instance_type: str,
    container_image: str,
) -> tuple[str, str]:
    stamp = utc_stamp()
    model_name = f"asl-model-{stamp}"
    endpoint_config_name = f"asl-endpoint-config-{stamp}"

    sm_client.create_model(
        ModelName=model_name,
        PrimaryContainer={
            "Image": container_image,
            "ModelDataUrl": s3_uri,
            "Environment": {"SAGEMAKER_PROGRAM": "inference.py"},
        },
        ExecutionRoleArn=role_arn,
    )
    sm_client.create_endpoint_config(
        EndpointConfigName=endpoint_config_name,
        ProductionVariants=[
            {
                "VariantName": "AllTraffic",
                "ModelName": model_name,
                "InstanceType": instance_type,
                "InitialInstanceCount": 1,
                "InitialVariantWeight": 1.0,
            }
        ],
    )
    logger.info("Created SageMaker model %s and endpoint config %s", model_name, endpoint_config_name)
    return model_name, endpoint_config_name


def wait_for_endpoint(sm_client, endpoint_name: str, timeout_s: int, poll_interval_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        response = sm_client.describe_endpoint(EndpointName=endpoint_name)
        status = response["EndpointStatus"]
        logger.info("Endpoint %s status: %s", endpoint_name, status)
        if status == "InService":
            return
        if status == "Failed":
            reason = response.get("FailureReason", "unknown")
            raise RuntimeError(f"Endpoint {endpoint_name} failed: {reason}")
        time.sleep(poll_interval_s)
    raise TimeoutError(f"Endpoint {endpoint_name} did not become InService within {timeout_s} seconds.")


def update_endpoint(
    s3_uri: str,
    endpoint_name: str,
    role_arn: str,
    instance_type: str,
    container_image: str,
    region: Optional[str],
    timeout_s: int,
    poll_interval_s: int,
) -> None:
    session = boto3.session.Session(region_name=region)
    sm_client = session.client("sagemaker")
    _model_name, endpoint_config_name = create_model_and_config(
        sm_client=sm_client,
        role_arn=role_arn,
        s3_uri=s3_uri,
        instance_type=instance_type,
        container_image=container_image,
    )

    if endpoint_exists(sm_client, endpoint_name):
        sm_client.update_endpoint(
            EndpointName=endpoint_name,
            EndpointConfigName=endpoint_config_name,
        )
        logger.info("Updating existing SageMaker endpoint %s", endpoint_name)
    else:
        sm_client.create_endpoint(
            EndpointName=endpoint_name,
            EndpointConfigName=endpoint_config_name,
        )
        logger.info("Creating SageMaker endpoint %s", endpoint_name)

    wait_for_endpoint(
        sm_client=sm_client,
        endpoint_name=endpoint_name,
        timeout_s=timeout_s,
        poll_interval_s=poll_interval_s,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Package model artifacts, upload to S3, and optionally update SageMaker.")
    parser.add_argument("--model-dir", default="./model", help="Directory containing model.pth and label_map.json.")
    parser.add_argument("--archive-path", default=None, help="Optional path for the generated .tar.gz archive.")
    parser.add_argument("--bucket", default=None, help="S3 bucket for model artifacts.")
    parser.add_argument("--key", default=DEFAULT_S3_KEY, help="S3 object key for the uploaded archive.")
    parser.add_argument("--s3-uri", default=None, help="Full S3 URI override, for example s3://bucket/models/nimbus-asl/model.tar.gz.")
    parser.add_argument("--region", default=os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION"))

    parser.add_argument(
        "--stack-name",
        default=DEFAULT_STACK_NAME,
        help="CloudFormation/SAM stack name used to resolve the model artifacts bucket when --bucket/--s3-uri is not provided.",
    )
    parser.add_argument("--archive-only", action="store_true", help="Create the .tar.gz archive locally and stop before uploading.")
    parser.add_argument("--skip-endpoint-update", action="store_true", help="Upload only; do not create/update the SageMaker endpoint.")
    parser.add_argument("--endpoint-name", default=DEFAULT_ENDPOINT_NAME, help="SageMaker endpoint name.")
    parser.add_argument("--instance-type", default=DEFAULT_INSTANCE_TYPE, help="SageMaker instance type for the endpoint.")
    parser.add_argument("--container-image", default=DEFAULT_CONTAINER_IMAGE, help="SageMaker inference container image.")
    parser.add_argument("--role-arn", default=os.environ.get("SAGEMAKER_ROLE_ARN"), help="SageMaker execution role ARN.")
    parser.add_argument("--timeout-s", type=int, default=DEFAULT_TIMEOUT_S)
    parser.add_argument("--poll-interval-s", type=int, default=DEFAULT_POLL_INTERVAL_S)
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()

    model_dir = pathlib.Path(args.model_dir).resolve()
    if not model_dir.exists():
        raise FileNotFoundError(f"Model directory not found: {model_dir}")

    archive_target = (
        pathlib.Path(args.archive_path).resolve()
        if args.archive_path
        else (model_dir / "model.tar.gz" if args.archive_only else None)
    )

    if args.archive_only:
        if archive_target is None:
            raise ValueError("archive-only mode requires a persistent archive path.")
        create_archive(model_dir=model_dir, archive_path=archive_target)
        logger.info("Archive ready at %s", archive_target)
        return

    bucket, key = resolve_s3_target(
        bucket=args.bucket,
        key=args.key,
        s3_uri=args.s3_uri,
        stack_name=args.stack_name,
        region=args.region,
    )

    with tempfile.TemporaryDirectory(prefix="nimbus-model-") as temp_dir:
        archive_path = archive_target if archive_target else pathlib.Path(temp_dir) / "model.tar.gz"
        create_archive(model_dir=model_dir, archive_path=archive_path)
        s3_uri = upload_archive(archive_path=archive_path, bucket=bucket, key=key, region=args.region)

    if args.skip_endpoint_update:
        logger.info("Endpoint update skipped; uploaded artifact available at %s", s3_uri)
        return

    if not args.role_arn:
        raise ValueError("SAGEMAKER_ROLE_ARN or --role-arn is required to update the endpoint.")

    update_endpoint(
        s3_uri=s3_uri,
        endpoint_name=args.endpoint_name,
        role_arn=args.role_arn,
        instance_type=args.instance_type,
        container_image=args.container_image,
        region=args.region,
        timeout_s=args.timeout_s,
        poll_interval_s=args.poll_interval_s,
    )
    logger.info("SageMaker endpoint %s is InService with %s", args.endpoint_name, s3_uri)


if __name__ == "__main__":
    main()
