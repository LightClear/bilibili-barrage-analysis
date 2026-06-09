"""Check a saved AI provider config without printing secrets."""

from __future__ import annotations

import argparse
from pathlib import Path

from .ai_provider import AiProviderError, test_deepseek_provider
from .secure_provider_store import SecureProviderStore


def main() -> None:
    parser = argparse.ArgumentParser(description="Test an encrypted AI provider config.")
    parser.add_argument("--account", default="admin_demo")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    config = SecureProviderStore(root / "data" / "secure").get(args.account)
    if not config:
        raise SystemExit(f"No AI provider configured for account: {args.account}")
    try:
        result = test_deepseek_provider(config)
    except AiProviderError as exc:
        raise SystemExit(f"AI provider check failed: {exc}") from exc
    print(f"AI provider check ok: {result.get('message', 'ready')}")


if __name__ == "__main__":
    main()
