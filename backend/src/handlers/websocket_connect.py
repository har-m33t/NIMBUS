"""
Lambda handler for establishing WebSocket connection.
"""

def handler(event, context):
    return {"statusCode": 200, "body": "Connected."}
