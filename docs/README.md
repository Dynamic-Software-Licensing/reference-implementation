# DSL Reference Implementation

A working reference implementation of the [Dynamic Software Licensing Best Practices](https://github.com/Dynamic-Software-Licensing/Dynamic-Software-Licensing---Best-Practices) — chapters 7 (Reference Model) and 10 (Canonical API).

## Two Modes

### Local Mode (no AWS required)

Try the full demo in 60 seconds:

```bash
cd local-mode
pip install -r requirements.txt
python mock_control_plane.py
```

Then in another terminal:

```bash
cd workspace-plane/dashboard
python -m http.server 8080
```

Open `http://localhost:8080`, set the Control Plane URL to `http://localhost:3000`, click Connect, and run the scenarios.

### AWS Mode (production-grade)

Deploy real infrastructure (API Gateway, Lambda, DynamoDB, KMS):

```bash
cd infrastructure
npm install
cdk bootstrap   # First time only
cdk deploy
```

Then serve the dashboard and paste your API URL from the CDK output.

## Architecture

**Hybrid design:**
- **Control Plane** — either local Python mock OR deployed to AWS (API Gateway + Lambda + DynamoDB + KMS)
- **Dashboard** — browser-based interactive demo with real-time visualization (vanilla HTML/JS)

## Prerequisites

- AWS CLI configured with credentials (`aws sts get-caller-identity` should work)
- Node.js 18+ and npm
- Python 3.11+
- AWS CDK CLI (`npm install -g aws-cdk`)

## Quick Start

### 1. Deploy the Control Plane

```bash
cd infrastructure
npm install
cdk bootstrap   # First time only
cdk deploy
```

Note the outputs:
```
DslReferenceStack.RestApiUrl = https://xxxxx.execute-api.us-east-1.amazonaws.com
DslReferenceStack.WsApiUrl = wss://xxxxx.execute-api.us-east-1.amazonaws.com/prod
DslReferenceStack.JwksUrl = https://xxxxx.execute-api.us-east-1.amazonaws.com/.well-known/jwks.json
```

### 2. Install the Workspace Plane

```bash
cd workspace-plane
pip install -e agent/ sdk/
```

### 3. Configure and Run the Agent

```bash
export DSL_API_URL=https://xxxxx.execute-api.us-east-1.amazonaws.com
export DSL_WS_URL=wss://xxxxx.execute-api.us-east-1.amazonaws.com/prod
export DSL_TENANT_ID=tenant-broadcaster-1
export DSL_APP_ID=app-encoder-pro
export DSL_ISV_ID=isv-acme

dsl-agent start
```

### 4. Open the Dashboard

Open `workspace-plane/dashboard/index.html` in your browser. It connects to the agent's local WebSocket at `ws://localhost:8765`.

## Demo Scenarios

| Command | What it demonstrates |
|---|---|
| `dsl-agent start` | Normal flow: identity → issue → renewal loop |
| `dsl-agent revoke --lease-id <id>` | Admin revocation + WebSocket push |
| Set `DSL_API_URL` to unreachable host | Grace period countdown + exhaustion |

## Project Structure

```
dsl-reference-implementation/
├── infrastructure/        # CDK stack (TypeScript)
├── control-plane/         # Lambda handlers (Python)
│   ├── lambdas/           # lease_handler, usage_handler, jwks_handler, ws_handler
│   └── shared/            # RFC 9457 errors, data models, tracing
├── workspace-plane/
│   ├── agent/             # License agent (Python CLI)
│   ├── sdk/               # Application SDK (Python library)
│   ├── app/               # Sample media processor
│   └── dashboard/         # Web dashboard (HTML/JS)
└── docs/                  # Documentation
```

## API Endpoints (Chapter 10 Conformance)

| Operation | Endpoint | Method |
|---|---|---|
| Issue | `/v1/leases` | POST |
| Renew | `/v1/leases/{leaseId}/renew` | POST |
| Reissue | `/v1/leases/{leaseId}/reissue` | POST |
| Finalize Reissue | `/v1/leases/{leaseId}/finalizeReissue` | POST |
| Revoke | `/v1/leases/{leaseId}` | DELETE |
| Usage | `/v1/usage-records` | POST |
| JWKS | `/.well-known/jwks.json` | GET |

> Note: API Gateway HTTP API doesn't support `:` in paths. The canonical form (`:renew`) is mapped as `/renew` at the gateway level.

## Standards Implemented

- Google AIP custom methods for URL design
- RFC 9457 (Problem Details) for error responses
- RFC 7517 (JWK) for key discovery
- W3C Trace Context for distributed tracing
- JWT (RS256 via KMS) for lease tokens

## Cleanup

```bash
cd infrastructure
cdk destroy
```
