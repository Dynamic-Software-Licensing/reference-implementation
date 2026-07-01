"""Identity evidence verification (simplified for demo)."""


def verify_identity_evidence(evidence: dict) -> bool:
    """Verify that identity evidence has a valid structure.

    In production, this would cryptographically verify the evidence
    (e.g., validate EC2 IID signature against AWS public key, or
    validate K8s SA JWT against the cluster OIDC issuer,
    validate SPIFFE SVID against the trust bundle,
    validate X.509 cert against the internal CA).

    For the reference implementation, we verify structure only.
    """
    if not isinstance(evidence, dict):
        return False

    # AWS EC2 IID format
    if "aws" in evidence:
        aws_data = evidence["aws"]
        if "iidDocument" in aws_data and "iidSignature" in aws_data:
            doc = aws_data["iidDocument"]
            if isinstance(doc, dict) and ("instanceId" in doc or "assumedRoleArn" in doc):
                return True
            if isinstance(doc, str) and len(doc) > 0:
                return True

    # Kubernetes Service Account format
    if "kubernetes" in evidence:
        k8s_data = evidence["kubernetes"]
        if "token" in k8s_data and "namespace" in k8s_data and "serviceAccount" in k8s_data:
            return True

    # SPIFFE/SPIRE format
    if "spiffe" in evidence:
        spiffe_data = evidence["spiffe"]
        if "spiffeId" in spiffe_data:
            return True

    # X.509 Client Certificate format
    if "certificate" in evidence:
        cert_data = evidence["certificate"]
        if "subjectDN" in cert_data:
            return True

    # Generic/simulated format (for demo flexibility)
    if "type" in evidence:
        return True

    return False


def extract_binding(evidence: dict) -> dict:
    """Extract the binding identity from identity evidence.

    The binding is the LOGICAL identity that the lease is tied to.
    This is NOT hardware-specific — it's a role, service account,
    SPIFFE ID, or certificate subject that survives failover.
    """
    # AWS: bind to IAM Role ARN (not instance ID)
    if "aws" in evidence:
        aws_data = evidence["aws"]
        doc = aws_data.get("iidDocument", {})
        if isinstance(doc, dict):
            # Prefer role ARN over instance ID for binding
            role_arn = doc.get("assumedRoleArn", "")
            if role_arn:
                return {
                    "type": "aws-role",
                    "roleArn": role_arn,
                    "region": doc.get("region", ""),
                    "accountId": doc.get("accountId", ""),
                }
            # Fallback to instance (not recommended)
            return {
                "type": "ec2-instance",
                "instanceId": doc.get("instanceId", ""),
                "region": doc.get("region", ""),
            }
        return {"type": "aws", "raw": str(doc)[:64]}

    # Kubernetes: bind to namespace + service account
    if "kubernetes" in evidence:
        k8s_data = evidence["kubernetes"]
        namespace = k8s_data.get("namespace", "")
        sa = k8s_data.get("serviceAccount", "")
        return {
            "type": "kubernetes-sa",
            "binding": f"system:serviceaccount:{namespace}:{sa}",
            "namespace": namespace,
            "serviceAccount": sa,
        }

    # SPIFFE: bind to SPIFFE ID
    if "spiffe" in evidence:
        spiffe_data = evidence["spiffe"]
        return {
            "type": "spiffe",
            "spiffeId": spiffe_data.get("spiffeId", ""),
            "trustDomain": spiffe_data.get("trustDomain", ""),
        }

    # X.509 Certificate: bind to subject DN
    if "certificate" in evidence:
        cert_data = evidence["certificate"]
        return {
            "type": "x509",
            "subjectDN": cert_data.get("subjectDN", ""),
            "issuerDN": cert_data.get("issuerDN", ""),
        }

    # Generic fallback
    return {"type": evidence.get("type", "unknown"), "id": str(evidence)[:64]}
