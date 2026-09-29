# Security

KindleGlance is designed for self-hosted deployment. Only expose the administrator interface through a trusted network or HTTPS. The collector has no published port and stores OAuth credentials in its own volume. Board images can contain private information; their signed URLs must be treated as temporary secrets.

Do not post secrets or an exploitable private deployment configuration in public issues. Use GitHub private vulnerability reporting when the repository's Security tab offers it. If that channel is unavailable, open a minimal issue requesting a private contact without including exploit details or private data.

Keep the host, reverse proxy and KOReader up to date. HTTPS in the plugin fails closed when its CA bundle, hostname or certificate validation fails. Do not work around a certificate error by disabling verification. Import a trusted CA file and correct the device clock instead.

See `docs/COMPATIBILITY.md` for the boundary between automated tests and physical-device verification.
