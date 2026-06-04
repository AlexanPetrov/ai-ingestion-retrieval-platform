# Make a token for testing purposes.
# Run this in a secure environment and keep the token secret.

import secrets

print(secrets.token_urlsafe(48))