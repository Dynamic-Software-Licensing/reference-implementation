/**
 * DSL Glossary — Contextual info popovers for key concepts.
 * Each term includes a general definition and persona-specific guidance.
 */

const GLOSSARY = {
    'license-broker': {
        term: 'License Broker',
        definition: 'A functional component within the workspace plane that acts as an intermediary interface between applications and the Control Plane to coordinate requests like lease renewals or usage recording.',
        isv: 'You provide the broker as part of your product distribution (binary, container image, or package). It calls the control plane API on behalf of the application using your defined policies.',
        si: 'You deploy and configure the broker alongside the application in the system environment. Configuration includes the control plane endpoint, identity mode, and tenant credentials.',
        customer: 'The broker runs automatically with your application. You do not interact with it directly — it ensures licenses stay active, handles failover, and reports usage transparently.',
    },
    'application': {
        term: 'Media Function',
        definition: 'Following the DMF Reference Architecture, Media Functions are well-defined units of functionality that act on media streams, files or objects. In this demo, the Encoder and Multiviewer represent licensed media functions.',
        isv: 'You integrate the Application SDK into your product. The SDK validates tokens locally and exposes dimension claims. Your application logic decides what to do when limits are reached.',
        si: 'You deploy the media function in the system environment and ensure the License Broker is running alongside it. No licensing-specific code changes are needed from your side.',
        customer: 'This is the product you purchased. It operates within the licensed limits (channels, FPS, etc.) and responds to lifecycle events (grace period, revocation) as defined by the vendor policy.',
    },
    'control-plane': {
        term: 'Control Plane',
        definition: 'The central authority for entitlements, lease lifecycle management, cryptographic key operations, usage metering, and policy enforcement.',
        isv: 'You define your product catalog, dimensions, pricing, and policies here. The control plane enforces your licensing rules. You may operate it yourself or use a shared managed service.',
        si: 'You integrate with the control plane API for deployment automation (IaC). You do not operate it — but you configure the License Broker to connect to it.',
        customer: 'The control plane runs in the background. You interact with it through the End User Portal for visibility, or indirectly through the License Broker. It enforces the licensing terms you purchased.',
    },
    'token': {
        term: 'Token (JWT)',
        definition: 'A cryptographically signed artifact (JSON Web Token) that represents an active lease. It contains claims about dimensions, policy, identity binding, and expiry. Validated locally by the SDK without calling the control plane.',
        isv: 'Tokens are signed with your KMS key. They embed your policy (grace, renewal, exhaustion). The token format follows RFC 7519 (JWT) with RS256 signatures.',
        si: 'Tokens are delivered from the License Broker to the media function. You do not need to handle token management — the broker and SDK do this automatically.',
        customer: 'The token is what proves your application is licensed. It refreshes automatically on renewal. If the token expires and grace runs out, the application executes its exhaustion action.',
    },
    'claims': {
        term: 'Claims',
        definition: 'The data inside a JWT token — dimensions (what the license grants), policy (behavioral rules), binding (which workload identity), expiry (when it needs renewal), and identifiers (lease ID, tenant, app).',
        isv: 'You define which claims appear in the token through your entitlement catalog. Dimensions, policy defaults, and modality are all embedded as claims.',
        si: 'Claims are read-only from your perspective. The SDK extracts them and the application uses them. You can inspect claims for debugging.',
        customer: 'Claims tell your application what it is allowed to do — how many channels, what FPS, how long the grace period is. These match what you purchased in your entitlement.',
    },
    'grace-period': {
        term: 'Grace Period',
        definition: 'A deterministic, policy-defined temporal safety envelope that permits a media function to bypass strict enforcement and continue normal operations during transient connectivity loss to the licensing authority.',
        isv: 'You define the default grace period in your policy. Longer grace protects customer production; shorter grace limits unbilled usage. You decide whether tenants can override.',
        si: 'You should understand the grace period when planning network architecture. Ensure the customer knows how much time they have if connectivity is lost.',
        customer: 'During a network outage, your application keeps running for the grace duration. If connectivity returns, operation resumes automatically. If not, the exhaustion action (drain/degrade/stop) fires.',
    },
    'lease-id': {
        term: 'Lease',
        definition: 'An active, cryptographically signed, and time-bounded allocation of a specific entitlement to a designated executing media function or deployment context.',
        isv: 'The lease ID appears in your usage records and audit logs. It correlates all activity for a specific workload-entitlement binding.',
        si: 'You may reference lease IDs when troubleshooting licensing issues or when automating reissue/revocation via the API.',
        customer: 'Lease IDs appear in the End User Portal when viewing active licenses. Operations teams can monitor lease status and, where permitted by the vendor, request force-release of a stuck license.',
    },
    'entitlement': {
        term: 'Entitlement',
        definition: 'The legal and commercial right to use a software application, module, or specific feature set, as granted by a software publisher (ISV) to a customer organization.',
        isv: 'You define the entitlement catalog: products, dimensions, pricing tiers, and default policies. Entitlements are provisioned through sales, marketplace, or self-service.',
        si: 'You provision entitlements on behalf of customers during onboarding. You may also request changes (upgrades, additional capacity) through the API.',
        customer: 'Your entitlement is what you purchased. It defines your licensed limits. You can view utilization (how many of your entitled leases are active) in the End User Portal.',
    },
    'identity-evidence': {
        term: 'Identity-Based Binding',
        definition: 'A trust mechanism that binds an active license lease to a cryptographically verifiable software or platform identity token rather than legacy, static hardware properties.',
        isv: 'Your License Broker collects identity evidence from the runtime environment. The control plane verifies it against the configured trust anchor.',
        si: 'You ensure the workload has the correct identity configured (IAM role, service account, SPIFFE registration). This is part of deployment setup.',
        customer: 'Identity is automatic — your cloud platform or orchestrator provides it. It ensures only your authorized workloads can use your licenses.',
    },
};

/**
 * Render an info icon that shows a popover on click.
 * Usage in HTML: <span class="info-icon" data-term="license-agent"></span>
 */
function initGlossary() {
    document.querySelectorAll('.info-icon').forEach(icon => {
        const termKey = icon.dataset.term;
        const entry = GLOSSARY[termKey];
        if (!entry) return;

        icon.textContent = '(i)';
        icon.title = entry.term;
        icon.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            showGlossaryPopover(icon, entry);
        });
    });

    // Close popover on outside click
    document.addEventListener('click', (e) => {
        if (e.target.closest('.glossary-popover') || e.target.closest('.info-icon')) return;
        const existing = document.querySelector('.glossary-popover');
        if (existing) existing.remove();
    });
}

function showGlossaryPopover(anchor, entry) {
    // Remove any existing popover
    const existing = document.querySelector('.glossary-popover');
    if (existing) existing.remove();

    const popover = document.createElement('div');
    popover.className = 'glossary-popover';
    // Security note: All content comes from the hardcoded GLOSSARY_TERMS object
    // defined in this file — never from user input or external sources.
    popover.innerHTML = ` <!-- nosemgrep: javascript.browser.security.insecure-innerhtml, javascript.browser.security.insecure-document-method -->
        <div class="glossary-title">${entry.term}</div>
        <div class="glossary-definition">${entry.definition}</div>
        <div class="glossary-personas">
            <div class="glossary-persona"><span class="persona-label">For ISVs:</span> ${entry.isv}</div>
            <div class="glossary-persona"><span class="persona-label">For SIs:</span> ${entry.si}</div>
            <div class="glossary-persona"><span class="persona-label">For Customers:</span> ${entry.customer}</div>
        </div>
        <div class="glossary-close">Click anywhere outside to close</div>
    `;

    document.body.appendChild(popover);

    // Position near the anchor
    const rect = anchor.getBoundingClientRect();
    const popoverWidth = 360;
    let left = rect.left + window.scrollX - (popoverWidth / 2) + 7;
    left = Math.max(10, Math.min(left, window.innerWidth - popoverWidth - 20));
    popover.style.top = (rect.bottom + window.scrollY + 8) + 'px';
    popover.style.left = left + 'px';
}

// Initialize on page load
document.addEventListener('DOMContentLoaded', initGlossary);
