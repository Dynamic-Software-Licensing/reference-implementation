"""Identity evidence generators for demo purposes."""

import json
import base64
import time
import uuid
from datetime import datetime, timezone


def generate_ec2_identity() -> dict:
    """Generate a simulated EC2 Instance Identity Document.

    In production, this would be fetched from the EC2 metadata service at:
    http://169.254.169.254/latest/dynamic/instance-identity/document
    """
    instance_id = f"i-{uuid.uuid4().hex[:12]}"
    document = {
        "instanceId": instance_id,
        "region": "us-east-1",
        "accountId": "123456789012",
        "imageId": "ami-0abcdef1234567890",
        "instanceType": "m5.xlarge",
        "availabilityZone": "us-east-1a",
        "pendingTime": datetime.now(timezone.utc).isoformat(),
        "architecture": "x86_64",
    }

    # Simulated PKCS7 signature (in production, this comes from the metadata service)
    simulated_signature = base64.b64encode(
        f"SIMULATED_PKCS7_SIGNATURE_FOR_{instance_id}".encode()
    ).decode()

    return {
        "type": "aws",
        "aws": {
            "iidDocument": document,
            "iidSignature": simulated_signature,
        },
    }


def generate_kubernetes_identity() -> dict:
    """Generate a simulated Kubernetes Service Account JWT.

    In production, this would be read from the mounted service account token at:
    /var/run/secrets/kubernetes.io/serviceaccount/token
    """
    namespace = "media-production"
    service_account = "encoder-sa"
    pod_name = f"encoder-{uuid.uuid4().hex[:8]}"

    # Build a simulated SA JWT (unsigned — for demo structure only)
    header = {"alg": "RS256", "kid": "k8s-cluster-key-1"}
    payload = {
        "iss": "https://kubernetes.default.svc.cluster.local",
        "sub": f"system:serviceaccount:{namespace}:{service_account}",
        "aud": ["dsl-control-plane"],
        "exp": int(time.time()) + 3600,
        "iat": int(time.time()),
        "nbf": int(time.time()),
        "kubernetes.io": {
            "namespace": namespace,
            "serviceaccount": {"name": service_account},
            "pod": {"name": pod_name},
        },
    }

    # Encode as JWT-like structure (no real signature for demo)
    def b64(data):
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    token = f"{b64(header)}.{b64(payload)}.SIMULATED_K8S_SIGNATURE"

    return {
        "type": "kubernetes",
        "kubernetes": {
            "token": token,
            "namespace": namespace,
            "serviceAccount": service_account,
        },
    }


def collect_identity(mode: str = "ec2") -> dict:
    """Collect identity evidence based on the configured mode.

    Args:
        mode: Either "ec2" or "kubernetes".

    Returns:
        Identity evidence dict ready to send to the control plane.
    """
    if mode == "kubernetes":
        return generate_kubernetes_identity()
    return generate_ec2_identity()
