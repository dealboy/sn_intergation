import argparse
import json
import os
import time
from typing import Optional

import requests


class ServiceNowClient:
    """Thin wrapper around the ServiceNow Table API for change requests."""

    def __init__(self, instance_url: str, username: str, password: str):
        if not instance_url:
            raise ValueError("instance_url is required")
        if not username or not password:
            raise ValueError("username and password are required")

        self.base_url = instance_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update({"Accept": "application/json"})

    def fetch_change_request(self, number: str) -> Optional[dict]:
        """Return the first change request matching the number, if any."""
        response = self.session.get(
            f"{self.base_url}/api/now/table/change_request",
            params={"sysparm_query": f"number={number}", "sysparm_limit": 1},
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        results = body.get("result") or []
        return results[0] if results else None

    def change_request_exists(self, number: str) -> bool:
        return self.fetch_change_request(number) is not None

    def poll_change_request(
        self, number: str, max_attempts: int = 10, interval_seconds: float = 30.0
    ) -> Optional[dict]:
        """Poll for a change request until it exists or attempts are exhausted."""
        for attempt in range(1, max_attempts + 1):
            record = self.fetch_change_request(number)
            if record:
                return record
            if attempt < max_attempts:
                time.sleep(interval_seconds)
        return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Poll the ServiceNow change_request table until a change number exists, "
            "or exit early if it is already present."
        )
    )
    parser.add_argument(
        "--instance-url",
        default=os.getenv("SERVICENOW_INSTANCE_URL"),
        help="Full ServiceNow instance URL, e.g. https://example.service-now.com",
        required=False,
    )
    parser.add_argument(
        "--username",
        default=os.getenv("SERVICENOW_USERNAME"),
        help="ServiceNow username (or set SERVICENOW_USERNAME)",
    )
    parser.add_argument(
        "--password",
        default=os.getenv("SERVICENOW_PASSWORD"),
        help="ServiceNow password (or set SERVICENOW_PASSWORD)",
    )
    parser.add_argument(
        "--change-number",
        required=True,
        help="Change request number to look for (e.g. CHG0030001)",
    )
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=10,
        help="Number of poll attempts before giving up (default: 10)",
    )
    parser.add_argument(
        "--interval-seconds",
        type=float,
        default=30.0,
        help="Seconds to wait between poll attempts (default: 30)",
    )
    parser.add_argument(
        "--one-shot",
        action="store_true",
        help="Check once instead of polling until the change request exists",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.instance_url:
        raise SystemExit("--instance-url or SERVICENOW_INSTANCE_URL is required")
    if not args.username or not args.password:
        raise SystemExit("ServiceNow credentials are required")

    client = ServiceNowClient(args.instance_url, args.username, args.password)

    if args.one_shot:
        exists = client.change_request_exists(args.change_number)
        message = (
            f"Change request {args.change_number} already exists."
            if exists
            else f"Change request {args.change_number} not found."
        )
        print(message)
        return 0 if exists else 1

    print(
        f"Polling for change request {args.change_number} "
        f"(attempts: {args.max_attempts}, interval: {args.interval_seconds}s)..."
    )
    record = client.poll_change_request(
        args.change_number, max_attempts=args.max_attempts, interval_seconds=args.interval_seconds
    )
    if record:
        print("Change request found:")
        print(json.dumps(record, indent=2, sort_keys=True))
        return 0

    print("Change request was not found before the maximum attempts were reached.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
