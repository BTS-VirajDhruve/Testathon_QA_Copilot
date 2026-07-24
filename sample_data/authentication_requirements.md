# Authentication Requirements — sample knowledge base document

## Sign In
Users must authenticate before accessing protected resources.
Supported methods: Email + Password, Google OAuth, Enterprise SSO, Self Registration.

## MFA Policy
MFA is required for privileged roles on password authentication.
MFA retry limit is 5 attempts before soft lock.

## OAuth
Callback must validate state. Provider failures must not create sessions.

## SSO
SAML and OIDC supported. Identity Provider failures must be handled gracefully.
