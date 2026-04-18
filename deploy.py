"""
NIMBUS ASL — SageMaker endpoint deployment script.
Creates model resource, endpoint config, endpoint, and writes ARN to SSM.
Credentials via default AWS credential chain (no hardcoded keys).
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone

import boto3

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

INSTANCE_TYPE = "ml.g5.xlarge"
ENDPOINT_NAME = "asl-endpoint"
POLL_INTERVAL_S = 15
TIMEOUT_S = 20 * 60  # 20 minutes

# SageMaker execution role ARN — must be set in the environment
ROLE_ARN = os.environ["SAGEMAKER_ROLE_ARN"]

# PyTorch inference container image — override via env if needed
CONTAINER_IMAGE = os.environ.get(
    "SAGEMAKER_CONTAINER_IMAGE",
    "763104351884.dkr.ecr.us-west-2.amazonaws.com/pytorch-inference:2.1.0-gpu-py310",
)


def _sm() -> boto3.client:
    return boto3.client("sagemaker")


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def create_model(s3_uri: str) -> str:
    """Register a SageMaker Model resource pointing at s3_uri.

    Args:
        s3_uri: S3 URI of the model.tar.gz artifact.

    Returns:
        SageMaker model name.
    """
    model_name = f"asl-model-{_stamp()}"
    _sm().create_model(
        ModelName=model_name,
        PrimaryContainer={
            "Image": CONTAINER_IMAGE,
            "ModelDataUrl": s3_uri,
            "Environment": {"SAGEMAKER_PROGRAM": "inference.py"},
        },
        ExecutionRoleArn=ROLE_ARN,
    )
    logger.info("Created SageMaker model: %s", model_name)
    return model_name


def create_endpoint_config(model_name: str) -> str:
    """Create an endpoint config for model_name using ml.g5.xlarge × 1.

    Args:
        model_name: Name returned by create_model.

    Returns:
        Endpoint config name.
    """
    config_name = f"asl-endpoint-config-{_stamp()}"
    _sm().create_endpoint_config(
        EndpointConfigName=config_name,
        ProductionVariants=[
            {
                "VariantName": "AllTraffic",
                "ModelName": model_name,
                "InstanceType": INSTANCE_TYPE,
                "InitialInstanceCount": 1,
                "InitialVariantWeight": 1.0,
            }
        ],
    )
    logger.info("Created endpoint config: %s", config_name)
    return config_name


def deploy(config_name: str) -> None:
    """Create the SageMaker endpoint named 'asl-endpoint'.

    Args:
        config_name: Endpoint config name returned by create_endpoint_config.
    """
    _sm().create_endpoint(
        EndpointName=ENDPOINT_NAME,
        EndpointConfigName=config_name,
    )
    logger.info("Endpoint creation initiated: %s", ENDPOINT_NAME)


def poll_until_ready(endpoint_name: str) -> None:
    """Poll describe_endpoint every 15 s until InService or timeout.

    Args:
        endpoint_name: Name of the endpoint to poll.

    Raises:
        RuntimeError: If status reaches Failed or 20-minute timeout expires.
    """
    sm = _sm()
    deadline = time.monotonic() + TIMEOUT_S
    while time.monotonic() < deadline:
        resp = sm.describe_endpoint(EndpointName=endpoint_name)
        status = resp["EndpointStatus"]
        logger.info("Endpoint %s status: %s", endpoint_name, status)
        if status == "InService":
            return
        if status == "Failed":
            reason = resp.get("FailureReason", "unknown")
            raise RuntimeError(f"Endpoint {endpoint_name} failed: {reason}")
        time.sleep(POLL_INTERVAL_S)
    raise RuntimeError(
        f"Endpoint {endpoint_name} did not reach InService within {TIMEOUT_S // 60} minutes"
    )


if __name__ == "__main__":
    s3_uri = "s3://asl-hackathon-usw2/models/v1/model.tar.gz"

    model_name = create_model(s3_uri)
    config_name = create_endpoint_config(model_name)
    deploy(config_name)
    poll_until_ready(ENDPOINT_NAME)

    sm = boto3.client("sagemaker")
    arn = sm.describe_endpoint(EndpointName=ENDPOINT_NAME)["EndpointArn"]

    boto3.client("ssm").put_parameter(
        Name="/asl/sagemaker/endpoint-arn",
        Value=arn,
        Type="String",
        Overwrite=True,
    )
    print(f"HANDOFF READY: {arn}")
