# Dynamic Software Licensing — Reference Implementation

## What This Is

An interactive tool that lets you explore, test, and understand modern software licensing workflows through hands-on scenarios. You can issue licenses, simulate failover, test network disconnections, observe token structures, and see how multi-vendor isolation works — all from your browser.

This reference implementation demonstrates the concepts defined in Chapters 7 (Reference Model) and 10 (Canonical API Model) of the [Dynamic Software Licensing (DSL) Best Practices](https://github.com/Dynamic-Software-Licensing/Dynamic-Software-Licensing---Best-Practices). Rather than reading the specification in isolation, you can run the scenarios yourself and observe every step of the licensing workflow.

## Why This Exists

Traditional software licensing in broadcast and media workflows relies on mechanisms designed for a different era:

- **MAC address binding** — breaks when workloads move between instances, containers, or regions
- **Hardware dongles** — incompatible with cloud, virtualized, and containerized deployments
- **Node-locked keys** — prevent failover, auto-scaling, and disaster recovery
- **Vendor-specific portals** — create friction in multi-vendor environments where customers run products from many ISVs simultaneously

These approaches assume stable hardware, single-site deployments, and manual license management. They do not work in environments where workloads are ephemeral, infrastructure is elastic, and operations are automated.

This tool demonstrates an alternative approach that addresses these challenges through identity-based binding, API-driven lifecycle management, and cryptographically signed tokens — designed for cloud, hybrid, on-premises, and air-gapped environments.

## What You Can Explore

The interactive demo provides the following scenarios:

| Scenario | What it demonstrates | Challenge it addresses |
|---|---|---|
| **Issue a license** | Application starts, presents workload identity, receives a signed token with granted dimensions | Replacing hardware-bound licensing with identity-based licensing |
| **Multi-vendor isolation** | Two ISV applications (Encoder + Multiviewer) operating independently with separate entitlements and quotas | Managing multiple vendor licenses through a single system |
| **Failover / DR** | Primary application fails, backup inherits the license seamlessly via two-phase transfer | Licenses that survive instance failure without manual re-binding |
| **Air gap / disconnection** | Application loses network connectivity, operates under grace period, recovers automatically | Licensing that works in isolated or intermittently connected environments |
| **Quota enforcement** | Attempting to exceed the licensed number of concurrent instances — rejected by the system | Preventing license abuse while enabling legitimate scaling |
| **Identity mismatch** | Unauthorized workload attempts to use a license — rejected | Protecting ISV revenue without hardware lock-in |
| **Revocation** | Administrator terminates a license immediately; application drains gracefully | Responding to policy violations or contract changes |
| **Renewal** | License agent transparently extends the lease before expiry | Continuous operation without manual license management |

## How It Works

The system consists of two parts:

**Control Plane** — the licensing backend that manages entitlements, issues and renews leases, signs tokens, records usage, and enforces policy. In this demo, it runs either locally (Python mock server) or on AWS (Lambda + DynamoDB + KMS).

**Workspace Plane** — where applications run. A License Agent sits alongside each application, handles identity collection, communicates with the control plane, and delivers signed tokens to the application. The application validates tokens locally and operates within the granted limits.

The demo's browser interface simulates the workspace plane, making every step of the interaction visible: what identity evidence looks like, what the API calls contain, what the signed token holds, and how the system responds to failures.

## Identity: Not Hardware, Not Instance — Workload Role

A key design principle: licenses bind to a **logical identity** (who the workload is), not to hardware (where it runs). The tool lets you switch between identity types to see this in practice:

| Platform | What the license binds to | Why it works for failover |
|---|---|---|
| AWS | IAM Role ARN | Any instance assuming that role can hold the license |
| Kubernetes | Service Account | Any pod with that service account can hold the license |
| SPIFFE/SPIRE | SPIFFE ID | Any workload with that SPIFFE identity, across any infrastructure |
| On-premises | X.509 Certificate Subject | Any server presenting that certificate from the internal CA |

## Quick Start

### Local Mode (no cloud account required)

```bash
cd local-mode
pip install -r requirements.txt
python3 mock_control_plane.py
```

In another terminal:

```bash
cd workspace-plane/dashboard
python3 -m http.server 8080
```

Open `http://localhost:8080`, set Control Plane URL to `http://localhost:3000`, click Connect, and explore the scenarios.

### AWS Mode (production-grade infrastructure)

```bash
cd infrastructure
npm install
cdk bootstrap   # First time only
cdk deploy
```

Then serve the dashboard and paste your API Gateway URL from the CDK output.

## Who This Is For

- **ISVs** exploring how to modernize their licensing for cloud and hybrid customers
- **System Integrators** understanding how licensing integrates into automated deployments
- **Broadcast engineers** evaluating how licensing behaves during production scenarios (failover, network loss)
- **Standards contributors** validating the DSL best practices against a working system

## Project Structure

```
├── local-mode/              # Mock control plane (Python, no cloud needed)
│   └── mock_control_plane.py
├── infrastructure/          # AWS CDK stack (TypeScript)
│   └── lib/dsl-api-stack.ts
├── control-plane/           # Lambda handlers (Python)
│   └── lambdas/
├── workspace-plane/
│   └── dashboard/           # Interactive browser demo (HTML/JS)
└── docs/
```

## Relationship to the DSL Best Practices

This tool implements concepts from:

- **Chapter 7** — Reference Model (architecture, components, trust model, responsibility boundaries)
- **Chapter 10** — Canonical API Model (lease lifecycle, token structure, error handling)

It is an educational reference — not production software. A production implementation would add authentication, operational monitoring, persistence guarantees, and security hardening appropriate to the deployment environment.

## Contributing

This repo is maintained by the [Dynamic Software Licensing](https://github.com/Dynamic-Software-Licensing) working group. To contribute, open a pull request or issue.
