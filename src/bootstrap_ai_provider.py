"""Bootstrap an encrypted AI provider config for a local account.

Usage:
    python -m src.bootstrap_ai_provider --account admin_demo --api-key sk-...

The API key is validated and immediately written to ``data/secure`` through
``SecureProviderStore``. The command never prints the key.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from .ai_provider import normalize_provider_config
from .secure_provider_store import SecureProviderStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Save an encrypted AI provider config.")
    parser.add_argument("--account", default="admin_demo")
    parser.add_argument("--provider", default="deepseek")
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--base-url", default="https://api.deepseek.com")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    config = normalize_provider_config({
        "provider": args.provider,
        "api_key": args.api_key,
        "base_url": args.base_url,
        "model": args.model,
        "timeout": args.timeout,
    })
    SecureProviderStore(root / "data" / "secure").set(args.account, config)
    print(f"AI provider saved for account: {args.account}")


if __name__ == "__main__":
    main()
