# Security Model

Minimum production controls:

- OAuth2/OIDC authentication
- MFA required for trading users
- Biometric unlock on mobile
- PIN fallback
- Broker tokens encrypted server-side only
- No broker API secrets stored on the mobile device
- Role-based access control
- Device registration and revocation
- Full audit logs for login, analysis, order preview, order approval, and order submission
- Emergency stop switch
- Daily loss limit
- Position size limit
- Rate limiting
- WAF
- Encrypted databases
- Secrets Manager or Vault
- Private networking for backend databases

Live trading should remain disabled until paper trading results, security review, and compliance review are complete.
