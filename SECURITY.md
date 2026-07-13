# Security policy

SYMconnect is for authorized remote-support sessions only.

## Required consent

- The remote user must intentionally share the current session ID and password.
- Mouse and keyboard control remains disabled until the remote user approves the native confirmation dialog.
- Closing SYMconnect ends the host session and invalidates its credentials.
- The project does not provide stealth mode, credential capture, hidden persistence, or approval bypasses.

## Production deployment

- Use a stable `wss://` relay endpoint with a valid TLS certificate.
- Run one relay process unless session state is moved to a shared store such as Redis.
- Keep the relay and Windows installer updated.
- Code-sign public Windows installers before broad distribution.
- Restrict relay administration and deployment credentials to trusted maintainers.

## Reporting a vulnerability

Do not publish credentials, active session IDs, or exploit details in a public issue. Contact the repository owner privately first, then coordinate a fix and disclosure timeline.
