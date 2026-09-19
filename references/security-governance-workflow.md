# Security Governance Workflow

Use this workflow when software development work involves security-sensitive paths or production-facing risk.

## Trigger conditions
- Authentication / authorization
- Sensitive or personal data
- File upload / download
- External API integration
- Admin features
- Secrets / tokens / credentials
- Deployment / environment config
- Database write path or destructive operations
- Public-facing endpoints or browser-executed scripts

## Mandatory role expectation
For non-trivial security-sensitive work, route through **Quality Gate Engineer** for explicit security review before declaring the task ready for release or completion.

## Mandatory checks
1. Security scope identification
   - what assets are sensitive
   - what trust boundaries are crossed
   - who can access what
2. Input / output safety
   - input validation
   - null/type/boundary handling
   - output encoding / exposure control
3. Access control
   - authentication
   - authorization
   - least privilege
   - admin-only behaviors
4. Secret and config handling
   - do not hardcode secrets
   - minimize exposure in logs/docs
   - validate environment separation
5. Dependency and integration risk
   - check dependency necessity
   - note external service trust assumptions
   - flag supply-chain or unsupported dependency risk
6. Auditability and rollback
   - key operations should be traceable when applicable
   - risky releases need rollback path
7. Security validation
   - add abuse cases / negative tests / permission tests
   - disclose unverified security assumptions

## Minimum security output
- Security-sensitive scope
- Main threats / misuse paths
- Mitigations in design or implementation
- Remaining risks
- Required tests and release gates

Use `references/security-assessment-template.md` when a structured Quality Gate Engineer security review is required.

## Prohibited behavior
- Assuming internal users are always trusted
- Shipping auth/permission changes without explicit review
- Logging secrets or sensitive payloads carelessly
- Hiding security assumptions or skipped checks
