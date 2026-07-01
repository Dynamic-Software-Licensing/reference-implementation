# DSL Reference Implementation — Local Mode

Run the full DSL demo without an AWS account. The mock control plane runs on your laptop and provides the same API as the real AWS deployment.

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Start the mock control plane
python mock_control_plane.py

# 3. In another terminal, serve the dashboard
cd ../workspace-plane/dashboard
python -m http.server 8080

# 4. Open browser
open http://localhost:8080
```

Then set the **Control Plane URL** in the dashboard to:
```
http://localhost:3000
```

Click "Connect" and run the scenarios.

## What's Different from AWS Mode

| Aspect | Local Mode | AWS Mode |
|---|---|---|
| Token signing | Local RSA key (in-memory) | AWS KMS (hardware-backed) |
| Storage | Python dict (in-memory) | DynamoDB |
| API Gateway | Python http.server | AWS API Gateway |
| WebSocket | Not supported (polling only) | AWS API Gateway WebSocket |
| Persistence | Lost on restart | Persistent |
| Cost | Free | AWS charges apply |
| Setup time | 60 seconds | ~5 minutes (CDK deploy) |

The token format, API paths, error responses, and licensing flow are identical in both modes.
