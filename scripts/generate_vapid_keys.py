#!/usr/bin/env python3
"""Generate VAPID key pair for Web Push notifications.

Usage:
    python scripts/generate_vapid_keys.py

Prints environment variables ready to add to .env file.
Requires: pip install py-vapid (included with pywebpush)
"""

import base64
import os


def generate_vapid_keys():
    """Generate VAPID keys using py_vapid."""
    try:
        from py_vapid import Vapid

        vapid = Vapid()
        vapid.generate_keys()

        # Get raw key bytes for URL-safe base64 encoding
        raw_private = vapid.private_key.private_numbers().private_value.to_bytes(32, "big")
        raw_public = vapid.public_key.public_bytes(
            encoding=__import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.X962,
            format=__import__("cryptography.hazmat.primitives.serialization", fromlist=["PublicFormat"]).PublicFormat.UncompressedPoint,
        )

        private_b64 = base64.urlsafe_b64encode(raw_private).decode().rstrip("=")
        public_b64 = base64.urlsafe_b64encode(raw_public).decode().rstrip("=")

        return private_b64, public_b64
    except ImportError:
        pass

    # Fallback: generate using cryptography directly
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization

    private_key = ec.generate_private_key(ec.SECP256R1())
    raw_private = private_key.private_numbers().private_value.to_bytes(32, "big")
    raw_public = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.X962,
        format=serialization.PublicFormat.UncompressedPoint,
    )

    private_b64 = base64.urlsafe_b64encode(raw_private).decode().rstrip("=")
    public_b64 = base64.urlsafe_b64encode(raw_public).decode().rstrip("=")

    return private_b64, public_b64


if __name__ == "__main__":
    private_key, public_key = generate_vapid_keys()

    print("# Web Push VAPID keys - add these to your .env file")
    print(f"PUSH_ENABLED=true")
    print(f"PUSH_VAPID_PRIVATE_KEY={private_key}")
    print(f"PUSH_VAPID_PUBLIC_KEY={public_key}")
    print(f"PUSH_VAPID_SUBJECT=mailto:admin@localhost")
    print()
    print("# To add to .env automatically:")
    print(f'# python scripts/generate_vapid_keys.py >> .env')
