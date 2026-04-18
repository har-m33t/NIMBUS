"""Validate that the deployed DynamoDB tables match PROTOCOLS.md §5.3."""
from __future__ import annotations

import boto3
import pytest


@pytest.fixture(scope="module")
def ddb_client(aws_region):
    return boto3.client("dynamodb", region_name=aws_region)


def _describe(ddb_client, name):
    return ddb_client.describe_table(TableName=name)["Table"]


def _key_schema_map(table) -> dict[str, str]:
    return {k["KeyType"]: k["AttributeName"] for k in table["KeySchema"]}


def test_sessions_table_has_composite_key(ddb_client, sessions_table_name):
    table = _describe(ddb_client, sessions_table_name)
    keys = _key_schema_map(table)
    assert keys == {"HASH": "sessionId", "RANGE": "sk"}


def test_rooms_table_has_composite_key(ddb_client, rooms_table_name):
    table = _describe(ddb_client, rooms_table_name)
    keys = _key_schema_map(table)
    assert keys == {"HASH": "roomId", "RANGE": "connectionId"}


def test_sessions_table_has_ttl_enabled(ddb_client, sessions_table_name):
    ttl = ddb_client.describe_time_to_live(TableName=sessions_table_name)
    spec = ttl["TimeToLiveDescription"]
    assert spec.get("TimeToLiveStatus") in {"ENABLED", "ENABLING"}
    assert spec.get("AttributeName") == "ttl"


def test_rooms_table_has_ttl_enabled(ddb_client, rooms_table_name):
    ttl = ddb_client.describe_time_to_live(TableName=rooms_table_name)
    spec = ttl["TimeToLiveDescription"]
    assert spec.get("TimeToLiveStatus") in {"ENABLED", "ENABLING"}
    assert spec.get("AttributeName") == "ttl"
