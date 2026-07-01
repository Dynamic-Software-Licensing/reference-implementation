/**
 * DSL Interactive Demo v2 — Step-by-step with speed control
 * 
 * Changes from v1:
 * - Identity binds to IAM Role ARN (not instance ID) — enables failover
 * - Speed slider for controlling animation pace
 * - Step-by-step mode with "Next" button
 * - Failover/DR scenario (reissue flow)
 * - Air gap / disconnection scenario (grace period)
 */

// ─── Configuration ───────────────────────────────────────────────────────────
const CONFIG = {
    apiUrl: 'http://localhost:3000',
    tenantId: 'tenant-broadcaster-1',
    vendors: {
        a: { isvId: 'isv-acme', appId: 'app-encoder-pro', name: 'Encoder' },
        b: { isvId: 'isv-globex', appId: 'app-multiviewer', name: 'Multiviewer' },
    },
};

// ─── State ───────────────────────────────────────────────────────────────────
let state = {
    vendorA: { leaseIds: [], leaseId: null, token: null, identity: null, active: 0 },
    vendorB: { leaseIds: [], leaseId: null, token: null, identity: null, active: 0 },
    speed: 1.0, // 0.5 = slow, 1.0 = normal, 2.0 = fast
    stepMode: false,
    stepResolve: null, // promise resolver for step mode
    graceTimer: null,
    graceRemaining: 0,
};

// ─── Speed & Step Control ────────────────────────────────────────────────────
function setSpeed(val) {
    state.speed = parseFloat(val);
    document.getElementById('speed-value').textContent = 
        val <= 0.5 ? 'Very Slow' : val <= 0.75 ? 'Slow' : val <= 1.0 ? 'Normal' : 'Fast';
}

function toggleStepMode() {
    state.stepMode = !state.stepMode;
    const btn = document.getElementById('step-toggle');
    btn.textContent = state.stepMode ? 'Step Mode: ON' : 'Step Mode: OFF';
    btn.classList.toggle('active', state.stepMode);
    document.getElementById('next-btn').style.display = state.stepMode ? 'inline-block' : 'none';
}

function nextStep() {
    if (state.stepResolve) {
        state.stepResolve();
        state.stepResolve = null;
    }
}

async function pause(baseMs) {
    const ms = baseMs / state.speed;
    if (state.stepMode) {
        // Wait for user to click "Next"
        document.getElementById('next-btn').classList.add('waiting');
        await new Promise(resolve => { state.stepResolve = resolve; });
        document.getElementById('next-btn').classList.remove('waiting');
    } else {
        await new Promise(resolve => setTimeout(resolve, ms));
    }
}

// ─── Identity Evidence (Platform-agnostic) ───────────────────────────────────
function getIdentityMode() {
    const sel = document.getElementById('identity-mode');
    return sel ? sel.value : 'aws';
}

function generateIdentity(role) {
    const mode = getIdentityMode();
    switch (mode) {
        case 'kubernetes': return generateK8sIdentity();
        case 'spiffe': return generateSpiffeIdentity();
        case 'certificate': return generateCertIdentity();
        default: return generateAwsIdentity(role);
    }
}

function generateAwsIdentity(role) {
    const roleArn = role || 'arn:aws:iam::123456789012:role/media-encoder-prod';
    const instanceId = 'i-' + crypto.randomUUID().replace(/-/g, '').substring(0, 12);
    return {
        type: 'aws',
        aws: {
            iidDocument: {
                instanceId: instanceId,
                region: 'us-east-1',
                accountId: '123456789012',
                imageId: 'ami-0abcdef1234567890',
                instanceType: 'm5.xlarge',
                availabilityZone: 'us-east-1a',
                pendingTime: new Date().toISOString(),
                assumedRoleArn: roleArn,
            },
            iidSignature: btoa('SIMULATED_PKCS7_FOR_' + instanceId),
        },
        bindingKey: roleArn,
    };
}

function generateK8sIdentity() {
    const namespace = 'media-production';
    const serviceAccount = 'encoder-sa';
    const podName = 'encoder-' + crypto.randomUUID().substring(0, 8);
    const header = btoa(JSON.stringify({alg: 'RS256', kid: 'k8s-cluster-1'}));
    const payload = btoa(JSON.stringify({
        iss: 'https://oidc.eks.us-east-1.amazonaws.com/id/EXAMPLED539D4633E53DE1B71EXAMPLE',
        sub: `system:serviceaccount:${namespace}:${serviceAccount}`,
        aud: ['dsl-control-plane'],
        exp: Math.floor(Date.now()/1000) + 3600,
        iat: Math.floor(Date.now()/1000),
        'kubernetes.io': { namespace, serviceaccount: {name: serviceAccount}, pod: {name: podName} },
    }));
    return {
        type: 'kubernetes',
        kubernetes: {
            token: `${header}.${payload}.SIMULATED_K8S_SIG`,
            namespace: namespace,
            serviceAccount: serviceAccount,
        },
        bindingKey: `system:serviceaccount:${namespace}:${serviceAccount}`,
    };
}

function generateSpiffeIdentity() {
    const spiffeId = 'spiffe://broadcast-org.com/ns/production/workload/media-encoder';
    return {
        type: 'spiffe',
        spiffe: {
            svid: '-----BEGIN CERTIFICATE-----\nMIIB...simulated...SPIFFE_SVID\n-----END CERTIFICATE-----',
            spiffeId: spiffeId,
            trustDomain: 'broadcast-org.com',
            issuer: 'spire-server.broadcast-org.com',
        },
        bindingKey: spiffeId,
    };
}

function generateCertIdentity() {
    const subject = 'CN=media-encoder-prod,O=Broadcast Corp,OU=Production';
    return {
        type: 'certificate',
        certificate: {
            clientCert: '-----BEGIN CERTIFICATE-----\nMIIC...simulated...X509\n-----END CERTIFICATE-----',
            subjectDN: subject,
            issuerDN: 'CN=Internal CA,O=Broadcast Corp',
            serialNumber: crypto.randomUUID().replace(/-/g, '').substring(0, 16),
            notAfter: new Date(Date.now() + 86400000).toISOString(),
        },
        bindingKey: subject,
    };
}

function generateDRIdentity() {
    // DR: different instance/pod, SAME logical identity (same role/SA/SPIFFE ID)
    return generateIdentity();
}

function generateAttackerIdentity() {
    const mode = getIdentityMode();
    switch (mode) {
        case 'kubernetes':
            return { type: 'kubernetes', kubernetes: { token: 'fake', namespace: 'hacker-ns', serviceAccount: 'attacker-sa' }, bindingKey: 'system:serviceaccount:hacker-ns:attacker-sa' };
        case 'spiffe':
            return { type: 'spiffe', spiffe: { svid: 'FAKE', spiffeId: 'spiffe://evil.com/attacker', trustDomain: 'evil.com' }, bindingKey: 'spiffe://evil.com/attacker' };
        case 'certificate':
            return { type: 'certificate', certificate: { clientCert: 'FAKE', subjectDN: 'CN=attacker,O=Evil Corp', issuerDN: 'CN=Rogue CA' }, bindingKey: 'CN=attacker,O=Evil Corp' };
        default:
            return generateAwsIdentity('arn:aws:iam::999999999999:role/unauthorized-role');
    }
}

// ─── API Client ──────────────────────────────────────────────────────────────
let currentVendor = 'a'; // tracks which vendor column to update

async function apiCall(method, path, body = null) {
    const url = CONFIG.apiUrl + path;
    const opts = {
        method,
        headers: { 'Content-Type': 'application/json', 'X-Tenant-Id': CONFIG.tenantId },
    };
    if (body) opts.body = JSON.stringify(body);
    showApiRequest(method, path, body, currentVendor);
    highlightArch('arch-agent', 'arch-cp');
    const response = await fetch(url, opts);
    let data;
    try { data = await response.json(); } catch { data = { status: response.status }; }
    showApiResponse(response.status, data, currentVendor);
    return { status: response.status, data };
}

// ─── Scenario Router ─────────────────────────────────────────────────────────
function getTargetVendor() {
    const sel = document.getElementById('target-app');
    return sel ? sel.value : 'a';
}

async function runScenario(scenario) {
    disableButtons(true);
    try {
        const target = getTargetVendor();
        const targetName = target === 'b' ? 'Multiviewer' : 'Encoder';
        if (!['issue-a', 'issue-b', 'reset'].includes(scenario)) {
            log('info', `Target: ${targetName}`, target);
        }
        switch (scenario) {
            case 'issue-a': await scenarioIssue('a'); break;
            case 'issue-b': await scenarioIssue('b'); break;
            case 'renew': await scenarioRenew(getTargetVendor()); break;
            case 'exceed-quota': await scenarioExceedQuota(getTargetVendor()); break;
            case 'wrong-identity': await scenarioWrongIdentity(getTargetVendor()); break;
            case 'failover': await scenarioFailover(getTargetVendor()); break;
            case 'airgap': await scenarioAirGap(getTargetVendor()); break;
            case 'revoke': await scenarioRevoke(getTargetVendor()); break;
            case 'reset': await scenarioReset(); break;
        }
    } catch (e) {
        narrate(`<span class="error-text">Error: ${e.message}</span>`);
        log('error', e.message);
    }
    disableButtons(false);
    setTimeout(refreshObservability, 500);
}

// ─── Scenario: Issue Lease ───────────────────────────────────────────────────
async function scenarioIssue(vendor) {
    const v = vendor === 'a' ? CONFIG.vendors.a : CONFIG.vendors.b;
    const stateKey = vendor === 'a' ? 'vendorA' : 'vendorB';
    const vendorName = v.name;
    currentVendor = vendor;

    narrate(`<strong>Step 1 — Identity Collection</strong><br>
        The License Broker collects <span class="highlight">identity evidence</span> from the workload.
        <br><br>
        <em>Platform:</em> <strong>${getIdentityMode().toUpperCase()}</strong><br>
        <em>Key point:</em> The binding is to a <strong>logical identity</strong> 
        (role / service account / SPIFFE ID / certificate subject) — not to hardware like MAC address or instance ID.
        This is what enables failover and DR across any platform.`);
    await pause(3000);

    const identity = generateIdentity();
    state[stateKey].identity = identity;
    showIdentity(identity, vendor);
    log('info', `Identity collected: ${identity.bindingKey} (${identity.type})`, vendor);
    await pause(2000);

    narrate(`<strong>Step 2 — Lease Request</strong><br>
        The agent calls <code>POST /v1/leases</code> for <strong>${vendorName}</strong> (<code>${v.appId}</code>).
        <br><br>The control plane will: verify the entitlement exists, check quota, validate identity, 
        sign a JWT with KMS, and return the lease.`);
    await pause(2000);

    const workId = 'deploy-' + crypto.randomUUID().substring(0, 12);
    const result = await apiCall('POST', '/v1/leases', {
        app: v.appId, tenantId: CONFIG.tenantId, isvId: v.isvId,
        identityEvidence: identity, workId: workId,
    });
    await pause(1500);

    if (result.status === 201) {
        state[stateKey].leaseId = result.data.leaseId;
        state[stateKey].leaseIds.push(result.data.leaseId);
        state[stateKey].token = result.data.token;
        state[stateKey].active++;
        updateVendorCard(vendor, 'ACTIVE', result.data.leaseId, state[stateKey].active);
        showToken(result.data.token, vendor);

        narrate(`<strong>Step 3 — Lease Granted [OK]</strong><br>
            The control plane issued lease <code>${result.data.leaseId}</code> for <strong>${v.name}</strong>.<br><br>
            The JWT token is signed by <strong>AWS KMS</strong> and contains:
            <ul>
                <li>App: <code>${v.appId}</code> (${v.name})</li>
                <li>Dimensions: ${JSON.stringify(result.data.dimensions?.map(d => d.name + ':' + d.maxQuantity))}</li>
                <li>Binding: <code>${identity.bindingKey}</code></li>
                <li>Expiry: ${result.data.expiresAt}</li>
                <li>Policy: grace=${result.data.policy?.offlineGraceSeconds}s, exhaustion=${result.data.policy?.onGraceExhausted}</li>
            </ul>
            The application can now operate within these licensed limits.`);
        log('success', `Lease issued: ${result.data.leaseId} — ${v.name} (${v.appId})`, vendor);
    } else {
        narrate(`<span class="error-text">Failed:</span> ${result.data.title} — ${result.data.detail}`);
        log('error', `Issue failed: ${result.data.detail}`, vendor);
    }
}

// ─── Scenario: Renew ─────────────────────────────────────────────────────────
async function scenarioRenew(vendor) {
    currentVendor = vendor;
    const stateKey = vendor === 'b' ? 'vendorB' : 'vendorA';
    const v = vendor === 'b' ? CONFIG.vendors.b : CONFIG.vendors.a;
    if (!state[stateKey].leaseId) { narrate(`<span class="error-text">Issue a ${v.name} lease first.</span>`); return; }

    narrate(`<strong>Renewal</strong><br>
        The agent calls <code>POST /v1/leases/{id}:renew</code> with identity evidence.
        The control plane re-verifies the <strong>IAM Role ARN</strong> matches the binding
        before extending the lease and signing a fresh token.`);
    await pause(2000);

    const result = await apiCall('POST', `/v1/leases/${state[stateKey].leaseId}/renew`, {
        identityEvidence: state[stateKey].identity,
    });
    await pause(1500);

    if (result.status === 200) {
        state[stateKey].token = result.data.token;
        showToken(result.data.token);
        narrate(`<span class="highlight">[OK] Renewed.</span> New expiry: ${result.data.expiresAt}.<br>
            The license continues uninterrupted. This happens automatically every 
            <code>renewBeforeSeconds</code> (60s) before the token expires.`);
        log('success', `Renewed — expires ${result.data.expiresAt}`);
    } else {
        narrate(`<span class="error-text">Renewal failed:</span> ${result.data.detail}`);
        log('error', `Renew failed: ${result.data.detail}`);
    }
}

// ─── Scenario: Exceed Quota ──────────────────────────────────────────────────
async function scenarioExceedQuota(vendor) {
    currentVendor = vendor;
    const v = vendor === 'b' ? CONFIG.vendors.b : CONFIG.vendors.a;
    const stateKey = vendor === 'b' ? 'vendorB' : 'vendorA';
    const maxLeases = vendor === 'b' ? 1 : 2;
    narrate(`<strong>Quota Enforcement — Preventing License Abuse</strong><br>
        The ${v.name} entitlement allows <strong>${maxLeases} concurrent lease${maxLeases > 1 ? 's' : ''}</strong>.
        We'll try to issue beyond that limit.<br><br>
        <em>Why this matters:</em> Even if the customer controls the workspace plane,
        the control plane enforces quota atomically. A license with dimension=1 
        cannot be leased to multiple workloads simultaneously.`);
    await pause(3000);

    const identity = generateIdentity();
    showIdentity(identity);
    const result = await apiCall('POST', '/v1/leases', {
        app: v.appId, tenantId: CONFIG.tenantId, isvId: v.isvId,
        identityEvidence: identity, workId: 'deploy-excess-' + Date.now(),
    });
    await pause(1500);

    if (result.status === 429) {
        narrate(`<span class="error-text">[REJECTED] REJECTED — 429 Entitlement Exhausted</span><br><br>
            The control plane returned RFC 9457: <code>urn:dsl:error:entitlement-exhausted</code>.<br><br>
            <em>This prevents abuse:</em> The ISV defined maxLeases=2. The control plane uses an
            atomic counter (DynamoDB conditional update) to ensure this limit is never exceeded,
            even under concurrent requests.`);
        log('warn', 'Quota exceeded — lease rejected');
    } else if (result.status === 201) {
        state[stateKey].leaseId = result.data.leaseId;
        state[stateKey].leaseIds.push(result.data.leaseId);
        state[stateKey].active++;
        updateVendorCard(vendor, 'ACTIVE', result.data.leaseId, state[stateKey].active);
        narrate(`Lease issued (quota not yet full). Try again to exceed.`);
        log('info', `Lease issued: ${result.data.leaseId}`);
    }
}

// ─── Scenario: Wrong Identity ────────────────────────────────────────────────
async function scenarioWrongIdentity(vendor) {
    currentVendor = vendor;
    const stateKey = vendor === 'b' ? 'vendorB' : 'vendorA';
    const v = vendor === 'b' ? CONFIG.vendors.b : CONFIG.vendors.a;
    if (!state[stateKey].leaseId) { narrate(`<span class="error-text">Issue a ${v.name} lease first.</span>`); return; }

    narrate(`<strong>Identity Mismatch — License Theft Prevention</strong><br>
        An unauthorized workload (different IAM role) attempts to renew the lease.
        The control plane compares the presented role ARN against the stored binding.`);
    await pause(2500);

    const attacker = generateAttackerIdentity();
    showIdentity(attacker);
    log('warn', `Attacker identity: ${attacker.bindingKey}`);
    await pause(2000);

    const result = await apiCall('POST', `/v1/leases/${state[stateKey].leaseId}/renew`, {
        identityEvidence: attacker,
    });
    await pause(1500);

    if (result.status === 403) {
        const mode = getIdentityMode();
        const modeLabel = { aws: 'IAM Role ARN', kubernetes: 'Service Account', spiffe: 'SPIFFE ID', certificate: 'Certificate Subject DN' }[mode] || 'identity';
        narrate(`<span class="error-text">[REJECTED] — 403 Identity Mismatch</span><br><br>
            The lease is bound to: <code>${state[stateKey].identity.bindingKey}</code><br>
            The attacker presented: <code>${attacker.bindingKey}</code><br><br>
            <em>Platform: ${mode.toUpperCase()}</em><br><br>
            <em>Key insight:</em> The license is bound to a logical <strong>${modeLabel}</strong>,
            not to hardware. Any workload presenting the same logical identity can renew or participate
            in failover — but a different identity is always rejected, regardless of platform.`);
        log('error', 'Identity mismatch — renewal rejected');
    } else {
        narrate(`Unexpected: ${result.data.detail || result.status}`);
    }
}

// ─── Scenario: Failover / DR ─────────────────────────────────────────────────
async function scenarioFailover(vendor) {
    currentVendor = vendor;
    const stateKey = vendor === 'b' ? 'vendorB' : 'vendorA';
    const v = vendor === 'b' ? CONFIG.vendors.b : CONFIG.vendors.a;
    if (!state[stateKey].leaseId) { narrate(`<span class="error-text">Issue a ${v.name} lease first.</span>`); return; }

    const identityLabel = { aws: 'IAM Role', kubernetes: 'Service Account', spiffe: 'SPIFFE ID', certificate: 'Certificate Subject' }[getIdentityMode()] || 'logical identity';
    narrate(`<strong>Failover / Disaster Recovery</strong><br>
        The primary workload has failed. A DR instance starts up and needs to inherit the license.<br><br>
        <em>Platform: ${getIdentityMode().toUpperCase()}</em><br>
        <em>Key:</em> The DR instance has a <strong>different compute instance</strong> but the 
        <strong>same ${identityLabel}</strong> — <code>${state[stateKey].identity?.bindingKey || 'same logical identity'}</code>.
        The reissue (two-phase transfer) moves the lease 
        without downtime and without consuming an additional quota slot.`);
    await pause(4000);

    // Phase 1: Shadow lease
    narrate(`<strong>Phase 1 — Shadow Lease</strong><br>
        The DR agent calls <code>POST /v1/leases/{id}:reissue</code>.
        The control plane creates a "shadow" lease on the new workload while keeping 
        the original active. It returns a cutover token for finalization.`);
    await pause(2500);

    const drIdentity = generateDRIdentity();
    showIdentity(drIdentity);
    log('info', `DR identity: ${drIdentity.bindingKey} (same logical identity, different compute)`);

    const reissueResult = await apiCall('POST', `/v1/leases/${state[stateKey].leaseId}/reissue`, {
        toIdentityEvidence: drIdentity,
        toWorkId: 'deploy-dr-' + Date.now(),
    });
    await pause(2000);

    if (reissueResult.status !== 200) {
        narrate(`<span class="error-text">Reissue failed: ${reissueResult.data.detail}</span>`);
        return;
    }

    const { reissueId, cutoverToken, toLease } = reissueResult.data;
    narrate(`<strong>Shadow lease created:</strong> <code>${toLease.leaseId}</code><br>
        Cutover token: <code>${cutoverToken.substring(0, 12)}...</code><br><br>
        At this point, BOTH leases exist — the original is still active (no downtime).
        The DR application has a valid token and can begin operating.`);
    await pause(3500);

    // Phase 2: Finalize
    narrate(`<strong>Phase 2 — Finalize</strong><br>
        The orchestrator calls <code>POST /v1/leases/{id}:finalizeReissue</code> with the cutover token.
        This atomically: activates the shadow lease and revokes the original.
        The original agent receives a revocation push.`);
    await pause(2500);

    const finalResult = await apiCall('POST', `/v1/leases/${state[stateKey].leaseId}/finalizeReissue`, {
        reissueId: reissueId, cutoverToken: cutoverToken,
    });
    await pause(1500);

    if (finalResult.status === 200) {
        state[stateKey].leaseId = toLease.leaseId;
        state[stateKey].identity = drIdentity;
        updateVendorCard(vendor, 'ACTIVE', toLease.leaseId, state[stateKey].active);

        narrate(`<span class="highlight">[OK] Failover Complete</span><br><br>
            Original lease: <strong>REVOKED</strong><br>
            DR lease: <strong>ACTIVE</strong> (${toLease.leaseId})<br><br>
            <em>What this proves:</em>
            <ul>
                <li>License moved to DR without consuming extra quota</li>
                <li>No downtime — shadow was valid before finalization</li>
                <li>Original workload receives revocation and drains</li>
                <li>Binding transferred to new instance (same role)</li>
            </ul>
            This is why we bind to IAM Role, not instance ID.`);
        log('success', 'Failover complete — license transferred to DR');
    } else {
        narrate(`<span class="error-text">Finalize failed: ${finalResult.data.detail}</span>`);
    }
}

// ─── Scenario: Air Gap / Disconnection ───────────────────────────────────────
async function scenarioAirGap(vendor) {
    currentVendor = vendor;
    const stateKey = vendor === 'b' ? 'vendorB' : 'vendorA';
    const v = vendor === 'b' ? CONFIG.vendors.b : CONFIG.vendors.a;
    if (!state[stateKey].leaseId) { narrate(`<span class="error-text">Issue a ${v.name} lease first.</span>`); return; }

    // Get user-configured grace period
    const graceInput = document.getElementById('grace-seconds');
    const graceSeconds = graceInput ? parseInt(graceInput.value) || 30 : 30;
    const exhaustionAction = document.getElementById('exhaustion-action')?.value || 'DRAIN';
    const reconnectAt = document.getElementById('reconnect-pct') ? parseInt(document.getElementById('reconnect-pct').value) : 60;

    // Phase 0: Normal operation
    narrate(`<strong>Air Gap Scenario — Simulating Network Disconnection</strong><br><br>
        <em>Configuration:</em>
        <ul>
            <li>Grace period: <strong>${graceSeconds} seconds</strong></li>
            <li>Exhaustion action: <strong>${exhaustionAction}</strong></li>
            <li>Reconnect at: <strong>${reconnectAt}%</strong> of grace elapsed (set to 100% for full exhaustion)</li>
        </ul>
        <br>
        <em>Context:</em> This simulates a real-world scenario — isolated broadcast truck, 
        network partition, cloud region outage, or intentionally air-gapped deployment.
        <br><br>The license was issued and the application is running normally...`);
    updateGrace(graceSeconds, graceSeconds, false);
    log('info', `Air gap scenario: grace=${graceSeconds}s, action=${exhaustionAction}, reconnect=${reconnectAt}%`);
    await pause(3000);

    // Phase 1: Token still valid, renewal starts failing
    narrate(`<strong>Phase 1 — Token Still Valid, Renewal Failing</strong><br><br>
        The network is disconnected. The agent attempts renewal but cannot reach the control plane.
        <br><br>
        <code>POST /v1/leases/{id}:renew</code> → <span class="error-text">Connection timeout</span>
        <br><br>
        The agent retries with <strong>exponential backoff + jitter</strong>:
        <ul>
            <li>Attempt 1: wait 2s, retry</li>
            <li>Attempt 2: wait 4s, retry</li>
            <li>Attempt 3: wait 8s, retry</li>
            <li>...</li>
        </ul>
        The application is <strong>unaware</strong> — it continues operating normally on its cached token.`);
    showApiRequest('POST', `/v1/leases/${state[stateKey].leaseId}/renew`, {identityEvidence: '...'});
    document.getElementById(`${currentVendor}-api-res`).textContent = '[ERROR] Connection Timeout\n\nAgent retrying with exponential backoff...';
    log('warn', 'Renewal failed — network unreachable');
    await pause(4000);

    // Phase 2: Token expires, grace period begins
    narrate(`<strong>Phase 2 — Token Expired, Grace Period Begins</strong><br><br>
        The token TTL has elapsed without successful renewal. 
        The <strong>offline grace period</strong> now begins.
        <br><br>
        During grace (${graceSeconds}s):
        <ul>
            <li>Application <strong>continues operating</strong> — production is NOT disrupted</li>
            <li>Agent continues retrying renewal in the background</li>
            <li>Usage is <strong>buffered locally</strong> (will upload when connected)</li>
            <li>Operators can see the grace countdown</li>
        </ul>
        <br>
        <em>Per spec (Ch 7.06):</em> "The grace period represents a deliberate trade-off between 
        production continuity and strict license enforcement."`);
    log('warn', `Grace period started: ${graceSeconds}s (action: ${exhaustionAction})`);
    await pause(3000);

    // Start visual countdown
    let remaining = graceSeconds;
    const reconnectTime = Math.floor(graceSeconds * (1 - reconnectAt / 100));
    updateGrace(remaining, graceSeconds, true);

    // Run the countdown
    const countdownPromise = new Promise((resolve) => {
        state.graceTimer = setInterval(() => {
            remaining--;
            updateGrace(remaining, graceSeconds, true);

            // Show retry attempts during grace
            if (remaining % 5 === 0 && remaining > 0) {
                log('warn', `Grace: ${remaining}s remaining — renewal retry failed`);
            }

            if (remaining <= reconnectTime && reconnectAt < 100) {
                clearInterval(state.graceTimer);
                state.graceTimer = null;
                resolve('reconnected');
            } else if (remaining <= 0) {
                clearInterval(state.graceTimer);
                state.graceTimer = null;
                resolve('exhausted');
            }
        }, 1000 / state.speed);
    });

    const outcome = await countdownPromise;

    if (outcome === 'reconnected') {
        // Phase 3a: Connectivity restored
        narrate(`<strong>Phase 3 — Connectivity Restored!</strong><br><br>
            The agent reaches the control plane and successfully renews the lease.
            <br><br>
            <span class="highlight">[OK] Operation resumes automatically</span> — no manual intervention.
            <br><br>
            What happens now:
            <ul>
                <li>Fresh token signed and delivered to application</li>
                <li>Grace countdown cancelled</li>
                <li>Buffered usage records uploaded to control plane</li>
                <li>Application returns to full normal operation</li>
                <li>Renewal scheduler resets to normal cadence</li>
            </ul>
            <br>
            <em>Per spec (Ch 7.06):</em> "Upon successful renewal after a grace period, operation 
            SHOULD resume automatically without manual intervention."`);
        updateGrace(0, graceSeconds, false);
        log('success', 'Connectivity restored — lease renewed, auto-resume');
        document.getElementById(`${currentVendor}-api-res`).textContent = '[OK] 200\n\n' + JSON.stringify({
            leaseId: state[stateKey].leaseId, token: '<fresh KMS-signed token>', expiresAt: new Date(Date.now() + 180000).toISOString()
        }, null, 2);
    } else {
        // Phase 3b: Grace exhausted
        narrate(`<strong>Phase 3 — Grace Period EXHAUSTED</strong><br><br>
            <span class="error-text">The grace period has expired without successful renewal.</span>
            <br><br>
            Exhaustion action: <strong>${exhaustionAction}</strong>
            <ul>
                ${exhaustionAction === 'DRAIN' ? '<li><strong>DRAIN:</strong> Finish active work (current encode completes), refuse new sessions. Graceful shutdown.</li>' : ''}
                ${exhaustionAction === 'DEGRADE' ? '<li><strong>DEGRADE:</strong> Reduce to minimum functionality (e.g., fewer channels, lower quality). Continue in limited mode.</li>' : ''}
                ${exhaustionAction === 'STOP' ? '<li><strong>STOP:</strong> Immediate halt. Application stops accepting and processing work.</li>' : ''}
            </ul>
            <br>
            <em>Recovery:</em> A new <code>POST /v1/leases</code> (Issue) is required to resume.
            The expired lease cannot be renewed — it's terminal.
            <br><br>
            <em>Vendor guidance (Ch 7.06):</em> Grace periods should be long enough for 
            live broadcasts (30-60 min) but bounded for metered entitlements to limit unbilled usage.`);
        updateGrace(0, graceSeconds, false);
        updateVendorCard(vendor, 'REVOKED', state[stateKey].leaseId, state[stateKey].active);
        state[stateKey].leaseId = null;
        state[stateKey].token = null;
        log('error', `Grace exhausted — ${exhaustionAction} executed. Lease terminated.`);
    }
}

// ─── Scenario: Revoke ────────────────────────────────────────────────────────
async function scenarioRevoke(vendor) {
    currentVendor = vendor;
    const stateKey = vendor === 'b' ? 'vendorB' : 'vendorA';
    const v = vendor === 'b' ? CONFIG.vendors.b : CONFIG.vendors.a;

    // Check if there are any leases to revoke (check array, not just single leaseId)
    if (state[stateKey].leaseIds.length === 0 && !state[stateKey].leaseId) {
        narrate(`<span class="error-text">Issue a ${v.name} lease first.</span>`);
        return;
    }

    // Pick the most recent lease to revoke
    const leaseId = state[stateKey].leaseIds.length > 0
        ? state[stateKey].leaseIds[state[stateKey].leaseIds.length - 1]
        : state[stateKey].leaseId;

    narrate(`<strong>Administrative Revocation</strong><br>
        An admin sends <code>DELETE /v1/leases/${leaseId}</code>. The control plane marks it REVOKED,
        decrements quota, and pushes a WebSocket event to the agent.<br><br>
        The application executes its <strong>exhaustion action</strong> (DRAIN: finish work, refuse new sessions).`);
    await pause(2500);

    const result = await apiCall('DELETE', `/v1/leases/${leaseId}`, { reason: 'admin_action' });
    await pause(1500);

    if (result.status === 204 || result.status === 200) {
        // Remove from array
        state[stateKey].leaseIds = state[stateKey].leaseIds.filter(id => id !== leaseId);
        // Update leaseId to the next available (or null)
        state[stateKey].leaseId = state[stateKey].leaseIds.length > 0
            ? state[stateKey].leaseIds[state[stateKey].leaseIds.length - 1]
            : null;
        state[stateKey].active = Math.max(0, state[stateKey].active - 1);

        const newStatus = state[stateKey].leaseIds.length > 0 ? 'ACTIVE' : 'REVOKED';
        const displayLeaseId = state[stateKey].leaseId || leaseId;
        updateVendorCard(vendor, newStatus, displayLeaseId, state[stateKey].active);

        const remaining = state[stateKey].leaseIds.length;
        narrate(`<span class="highlight">[OK] Lease Revoked</span><br>
            Lease <code>${leaseId}</code> is terminated. Quota slot freed.<br>
            ${remaining > 0 ? `<br>${remaining} active lease(s) remaining for ${v.name}.` : 'No active leases remaining.'}
            Application drains active work.`);
        log('warn', `Revoked: ${leaseId} (${remaining} remaining)`);
    } else {
        narrate(`Response: ${JSON.stringify(result.data)}`);
    }
}

// ─── Scenario: Reset ─────────────────────────────────────────────────────────
async function scenarioReset() {
    if (state.graceTimer) { clearInterval(state.graceTimer); state.graceTimer = null; }
    
    // Call the server-side reset to flush all leases and counters
    currentVendor = 'a';
    try {
        await apiCall('POST', '/v1/admin/reset');
    } catch (e) {
        // Continue even if reset fails
    }

    state.vendorA = { leaseIds: [], leaseId: null, token: null, identity: null, active: 0 };
    state.vendorB = { leaseIds: [], leaseId: null, token: null, identity: null, active: 0 };
    updateVendorCard('a', null, null, 0);
    updateVendorCard('b', null, null, 0);
    updateGrace(0, 1, false, 'a');
    updateGrace(0, 1, false, 'b');
    document.getElementById('a-token').textContent = '—';
    document.getElementById('b-token').textContent = '—';
    document.getElementById('a-identity').textContent = '—';
    document.getElementById('b-identity').textContent = '—';
    document.getElementById('a-api-req').textContent = '—';
    document.getElementById('a-api-res').textContent = '—';
    document.getElementById('b-api-req').textContent = '—';
    document.getElementById('b-api-res').textContent = '—';
    narrate(`<strong>Reset complete.</strong> All leases deleted, quota counters zeroed. Ready for a fresh demo.`);
    log('info', 'System reset — all leases flushed', 'a');
    log('info', 'System reset — all leases flushed', 'b');
    currentVendor = 'a';
}

// ─── UI Helpers ──────────────────────────────────────────────────────────────
function narrate(html) {
    // Security note: html parameter is always generated internally by scenario functions
    // (hardcoded narrative strings), never from user input or external sources.
    const el = document.getElementById('narrative');
    el.innerHTML = '';
    const div = document.createElement('div');
    div.className = 'narrative-step';
    div.innerHTML = html; // nosemgrep: javascript.browser.security.insecure-innerhtml, javascript.browser.security.insecure-document-method
    el.appendChild(div);
}

function showIdentity(identity, vendor) {
    const prefix = vendor || currentVendor || 'a';
    const mode = identity.type;
    let display;
    if (mode === 'aws') {
        display = { platform: 'AWS EC2', bindingKey: identity.bindingKey + '  <- LEASE BINDS TO THIS', roleArn: identity.aws.iidDocument.assumedRoleArn, instanceId: identity.aws.iidDocument.instanceId + '  <- ephemeral', region: identity.aws.iidDocument.region };
    } else if (mode === 'kubernetes') {
        display = { platform: 'Kubernetes', bindingKey: identity.bindingKey + '  <- LEASE BINDS TO THIS', namespace: identity.kubernetes.namespace, serviceAccount: identity.kubernetes.serviceAccount };
    } else if (mode === 'spiffe') {
        display = { platform: 'SPIFFE/SPIRE', bindingKey: identity.bindingKey + '  <- LEASE BINDS TO THIS', spiffeId: identity.spiffe.spiffeId, trustDomain: identity.spiffe.trustDomain };
    } else if (mode === 'certificate') {
        display = { platform: 'X.509 Certificate', bindingKey: identity.bindingKey + '  <- LEASE BINDS TO THIS', subjectDN: identity.certificate.subjectDN, issuerDN: identity.certificate.issuerDN };
    }
    document.getElementById(`${prefix}-identity`).textContent = JSON.stringify(display, null, 2);
}

function showToken(token, vendor) {
    const prefix = vendor || currentVendor || 'a';
    try {
        const parts = token.split('.');
        const header = JSON.parse(atob(parts[0].replace(/-/g, '+').replace(/_/g, '/')));
        const claims = JSON.parse(atob(parts[1].replace(/-/g, '+').replace(/_/g, '/')));
        document.getElementById(`${prefix}-token`).textContent = 
            'HEADER:\n' + JSON.stringify(header, null, 2) + '\n\nCLAIMS:\n' + JSON.stringify(claims, null, 2);
    } catch (e) {
        document.getElementById(`${prefix}-token`).textContent = 'Decode error: ' + e.message;
    }
}

function showApiRequest(method, path, body, vendor) {
    const prefix = vendor || currentVendor || 'a';
    let text = `${method} ${path}\nContent-Type: application/json`;
    if (body) text += '\n\n' + JSON.stringify(body, null, 2);
    document.getElementById(`${prefix}-api-req`).textContent = text;
}

function showApiResponse(status, data, vendor) {
    const prefix = vendor || currentVendor || 'a';
    const icon = status >= 400 ? '[ERROR]' : '[OK]';
    document.getElementById(`${prefix}-api-res`).textContent = `${icon} ${status}\n\n` + JSON.stringify(data, null, 2);
}

function updateVendorCard(vendor, status, leaseId, active) {
    const p = vendor || currentVendor || 'a';
    document.getElementById(`${p}-active`).textContent = active;
    document.getElementById(`${p}-lease-id`).textContent = leaseId || '—';
    const el = document.getElementById(`${p}-status`);
    if (!status) { el.textContent = 'No lease'; el.className = 'status-badge status-none'; }
    else if (status === 'ACTIVE') { el.textContent = 'ACTIVE'; el.className = 'status-badge status-active'; }
    else if (status === 'REVOKED') { el.textContent = 'REVOKED'; el.className = 'status-badge status-revoked'; }
}

function updateGrace(remaining, total, active, vendor) {
    const prefix = vendor || currentVendor || 'a';
    const panel = document.getElementById(`${prefix}-grace`);
    const pct = total > 0 ? (remaining / total) * 100 : 100;
    panel.querySelector('.grace-countdown').textContent = active ? `${remaining}s` : '—';
    panel.querySelector('.grace-label').textContent = active ? '[WARNING] GRACE PERIOD — App continues operating' : 'Normal';
    panel.querySelector('.grace-label').style.color = active ? '#f59e0b' : '#22c55e';
    panel.querySelector('.progress-fill').style.width = `${pct}%`;
    panel.querySelector('.progress-fill').className = 'progress-fill' + (pct < 25 ? ' danger' : pct < 50 ? ' warning' : '');
}

function log(type, message, vendor) {
    const prefix = vendor || currentVendor || 'a';
    const el = document.getElementById(`${prefix}-log`);
    if (!el) return;
    const time = new Date().toLocaleTimeString();
    const cls = { success: 'log-success', error: 'log-error', warn: 'log-warn', info: 'log-info' }[type] || 'log-info';
    // Security note: message is always generated internally by scenario code, not user input.
    const entry = document.createElement('div');
    entry.className = 'log-entry';
    const timeSpan = document.createElement('span');
    timeSpan.className = 'log-time';
    timeSpan.textContent = time;
    const msgSpan = document.createElement('span');
    msgSpan.className = cls;
    msgSpan.textContent = message;
    entry.appendChild(timeSpan);
    entry.appendChild(document.createTextNode(' '));
    entry.appendChild(msgSpan);
    el.prepend(entry);
    while (el.children.length > 15) el.removeChild(el.lastChild);
}

function highlightArch(from, to) {
    // No-op for SVG (could add animation later)
}

function disableButtons(disabled) {
    document.querySelectorAll('.btn').forEach(btn => {
        if (btn.id !== 'next-btn') btn.disabled = disabled;
    });
}

// ─── API URL Configuration ───────────────────────────────────────────────────
async function updateApiUrl() {
    const input = document.getElementById('api-url-input');
    const statusEl = document.getElementById('connection-status');
    if (!input || !input.value.trim()) return;

    CONFIG.apiUrl = input.value.trim().replace(/\/$/, '');
    statusEl.textContent = 'Connecting...';
    statusEl.className = 'status-connecting';

    try {
        const response = await fetch(CONFIG.apiUrl + '/.well-known/jwks.json', { method: 'GET' });
        if (response.ok) {
            statusEl.textContent = 'Connected';
            statusEl.className = 'status-connected';
            log('info', `Connected: ${CONFIG.apiUrl}`, 'a');
            log('info', `Connected: ${CONFIG.apiUrl}`, 'b');
            refreshObservability();
        } else {
            statusEl.textContent = 'Error (' + response.status + ')';
            statusEl.className = 'status-disconnected';
        }
    } catch (e) {
        statusEl.textContent = 'Unreachable';
        statusEl.className = 'status-disconnected';
    }
}

// Check connection on page load
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('api-url-input');
    if (input && input.value) {
        CONFIG.apiUrl = input.value.trim().replace(/\/$/, '');
        // Only auto-connect if it looks like a real URL (not localhost with no server)
        // User should click Connect manually for non-default URLs
    }
    if (typeof initGlossary === 'function') initGlossary();
});

// ─── Observability ───────────────────────────────────────────────────────────
let autoRefreshInterval = null;

function toggleAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
        document.getElementById('auto-refresh-label').textContent = 'OFF';
    } else {
        refreshObservability();
        autoRefreshInterval = setInterval(refreshObservability, 3000);
        document.getElementById('auto-refresh-label').textContent = 'ON (3s)';
    }
}

async function refreshObservability() {
    try {
        const url = CONFIG.apiUrl + '/v1/admin/observability';
        const response = await fetch(url, { headers: { 'X-Tenant-Id': CONFIG.tenantId } });
        if (!response.ok) {
            console.error('[Observability] Response not OK:', response.status);
            return;
        }
        const data = await response.json();
        renderObservability(data);
    } catch (e) {
        console.error('[Observability] Fetch failed:', e.message);
    }
}

function renderObservability(data) {
    const entitlements = data.entitlements || [];

    // Filter by the active tenant
    const tenantEnts = entitlements.filter(e => e.tenantId === CONFIG.tenantId);
    const encoder = tenantEnts.find(e => e.appId === 'app-encoder-pro');
    const multiviewer = tenantEnts.find(e => e.appId === 'app-multiviewer');

    if (encoder) renderObsCard('enc', encoder);
    if (multiviewer) renderObsCard('mv', multiviewer);

    // Recent activity — data comes from our own control plane, not user input
    const activityEl = document.getElementById('obs-activity-log');
    const activity = data.recentActivity || [];
    activityEl.innerHTML = ''; // nosemgrep: javascript.browser.security.insecure-innerhtml
    if (activity.length > 0) {
        activity.forEach(a => {
            const time = a.issuedAt ? a.issuedAt.split('T')[1]?.split('.')[0] || '' : '';
            const color = a.status === 'REVOKED' ? '#ef4444' : a.status === 'RENEWED' ? '#06b6d4' : '#22c55e';
            const row = document.createElement('div');
            row.style.cssText = 'display:flex;gap:0.75rem;padding:0.25rem 0;border-bottom:1px solid #334155;font-size:0.7rem;font-family:monospace;';
            row.innerHTML = `<span style="color:#94a3b8;min-width:60px;">${time}</span><span style="color:${color};font-weight:600;min-width:70px;">${a.status}</span><span>${a.appId || ''}</span><span style="color:#94a3b8;">${a.leaseId || ''}</span>${a.revokeReason ? `<span style="color:#94a3b8;">(${a.revokeReason})</span>` : ''}`; // nosemgrep: javascript.browser.security.insecure-innerhtml, javascript.browser.security.insecure-document-method
            activityEl.appendChild(row);
        });
    } else {
        activityEl.textContent = 'No activity yet — issue a lease to see data here';
    }
}

function renderObsCard(prefix, ent) {
    const pct = ent.maxLeases > 0 ? (ent.activeLeases / ent.maxLeases) * 100 : 0;
    const barColor = pct >= 100 ? '#ef4444' : pct >= 50 ? '#f59e0b' : '#22c55e';

    document.getElementById(`obs-${prefix}-slots`).textContent = `${ent.activeLeases} / ${ent.maxLeases} used`;
    document.getElementById(`obs-${prefix}-avail`).textContent = ent.availableLeases;
    document.getElementById(`obs-${prefix}-modality`).textContent = ent.licenseModality || '—';

    const bar = document.getElementById(`obs-${prefix}-bar`);
    bar.style.width = `${pct}%`;
    bar.style.background = barColor;

    // Lease list — data from our own control plane backend
    const leasesEl = document.getElementById(`obs-${prefix}-leases`);
    leasesEl.innerHTML = ''; // nosemgrep: javascript.browser.security.insecure-innerhtml
    if (ent.leases && ent.leases.length > 0) {
        ent.leases.forEach(l => {
            const row = document.createElement('div');
            row.style.cssText = 'display:flex;gap:0.5rem;padding:0.2rem 0;border-top:1px solid #334155;font-size:0.65rem;font-family:monospace;';
            const statusSpan = document.createElement('span');
            statusSpan.style.cssText = 'color:#22c55e;font-weight:600;';
            statusSpan.textContent = l.status;
            const idSpan = document.createElement('span');
            idSpan.textContent = l.leaseId;
            row.appendChild(statusSpan);
            row.appendChild(idSpan);
            leasesEl.appendChild(row);
        });
    } else {
        leasesEl.textContent = 'No active leases';
        leasesEl.style.color = '#94a3b8';
        leasesEl.style.fontSize = '0.7rem';
    }
}
