import argparse
import json
import os
import time
from typing import Dict, Optional

import requests


class ServiceNowClient:
    """Thin wrapper around the ServiceNow Table API for change requests."""

    def __init__(
        self,
        instance_url: str,
        username: str,
        password: str,
        verify: Optional[str] = None,
    ):
        if not instance_url:
            raise ValueError("instance_url is required")
        if not username or not password:
            raise ValueError("username and password are required")
        if verify and not os.path.exists(verify):
            raise ValueError(f"CA bundle path does not exist: {verify}")

        self.base_url = instance_url.rstrip("/")
        self.session = requests.Session()
        self.session.auth = (username, password)
        self.session.headers.update({"Accept": "application/json"})
        self.session.verify = verify if verify is not None else True

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

    def create_change_task(
        self,
        change_request_sys_id: str,
        short_description: str,
        work_notes: Optional[str] = None,
        description: Optional[str] = None,
        assignment_group: Optional[str] = None,
        change_task_type: str = "Implementation",
    ) -> Dict[str, str]:
        """Create a change task attached to the provided change request."""

        payload = {
            "change_request": change_request_sys_id,
            "short_description": short_description,
            "change_task_type": change_task_type,
        }
        if work_notes:
            payload["work_notes"] = work_notes
        if description:
            payload["description"] = description
        if assignment_group:
            payload["assignment_group"] = assignment_group

        response = self.session.post(
            f"{self.base_url}/api/now/table/change_task", json=payload, timeout=30
        )
        response.raise_for_status()
        body = response.json()
        return body.get("result", {})

    def update_change_request(
        self, change_request_sys_id: str, fields: Dict[str, str]
    ) -> Dict[str, str]:
        response = self.session.patch(
            f"{self.base_url}/api/now/table/change_request/{change_request_sys_id}",
            json=fields,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        return body.get("result", {})

    def add_work_note_to_change_request(
        self, change_request_sys_id: str, note: str
    ) -> Dict[str, str]:
        return self.update_change_request(change_request_sys_id, {"work_notes": note})

    def close_change_task(
        self, change_task_sys_id: str, close_notes: Optional[str] = None
    ) -> Dict[str, str]:
        """Close a change task by moving it to a closed state with optional notes."""

        payload = {"state": "3"}  # 3 corresponds to "Closed Complete" in ServiceNow
        if close_notes:
            payload["close_notes"] = close_notes

        response = self.session.patch(
            f"{self.base_url}/api/now/table/change_task/{change_task_sys_id}",
            json=payload,
            timeout=30,
        )
        response.raise_for_status()
        body = response.json()
        return body.get("result", {})


def normalize_change_request_state(state_value: Optional[str]) -> str:
    """Return a normalized state value for comparison."""

    if state_value is None:
        return ""

    state_str = str(state_value).strip().lower()
    numeric_map = {"4": "scheduled", "5": "implement"}
    if state_str in numeric_map:
        return numeric_map[state_str]

    if state_str.startswith("sched"):
        return "scheduled"
    if state_str.startswith("implement"):
        return "implement"

    return ""


def prepare_change_request_for_task(
    client: ServiceNowClient, change_request: dict
) -> Optional[dict]:
    """Ensure the change request is in Implement state before creating tasks."""

    normalized_state = normalize_change_request_state(change_request.get("state"))
    if normalized_state == "scheduled":
        updated_request = client.update_change_request(
            change_request["sys_id"], {"state": "5"}
        )
        change_request.update(updated_request)
        change_request["state"] = updated_request.get("state", "5")
        return change_request

    if normalized_state == "implement":
        return change_request

    return None


def create_and_close_change_task(
    client: ServiceNowClient,
    change_request: dict,
    short_description: str,
    description: str,
    work_notes: str,
    close_notes: str,
) -> tuple[dict, dict]:
    """Create a change task under a change request, add notes, then close it."""

    change_task_assignment_group = change_request.get("assignment_group")

    change_task = client.create_change_task(
        change_request["sys_id"],
        short_description,
        description=description,
        assignment_group=change_task_assignment_group,
        work_notes=work_notes,
    )
    change_task_sys_id = change_task.get("sys_id")
    if not change_task_sys_id:
        raise RuntimeError("ServiceNow response did not include a change task sys_id.")

    change_task_number = change_task.get("number", "the new change task")
    client.add_work_note_to_change_request(
        change_request["sys_id"],
        f"Automation created change task {change_task_number} for this change.",
    )

    closed_task = client.close_change_task(change_task_sys_id, close_notes=close_notes)
    return change_task, closed_task


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
        "--ca-bundle",
        default=os.getenv("SERVICENOW_CA_BUNDLE"),
        help="Path to a CA bundle file for private PKI validation",
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
    parser.add_argument(
        "--create-task",
        action="store_true",
        help=(
            "When the change request is found, create a child change task, add notes, "
            "and close it."
        ),
    )
    parser.add_argument(
        "--task-short-description",
        default="Automated change task",
        help="Short description to use for the created change task",
    )
    parser.add_argument(
        "--task-description",
        default="Automation-generated change task description.",
        help="Detailed description to use for the created change task",
    )
    parser.add_argument(
        "--task-work-notes",
        default="Change task created automatically.",
        help="Work notes to add to the created change task",
    )
    parser.add_argument(
        "--task-close-notes",
        default="Task closed automatically after creation.",
        help="Close notes to add when closing the created change task",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.instance_url:
        raise SystemExit("--instance-url or SERVICENOW_INSTANCE_URL is required")
    if not args.username or not args.password:
        raise SystemExit("ServiceNow credentials are required")

    client = ServiceNowClient(
        args.instance_url, args.username, args.password, verify=args.ca_bundle
    )

    if args.one_shot:
        record = client.fetch_change_request(args.change_number)
        if not record:
            print(f"Change request {args.change_number} not found.")
            if args.create_task:
                print("Cannot create change task because the change request is not valid.")
            return 1

        print(f"Change request {args.change_number} already exists.")
        print(json.dumps(record, indent=2, sort_keys=True))

        if not args.create_task:
            return 0

        original_state = normalize_change_request_state(record.get("state"))
        prepared_request = prepare_change_request_for_task(client, record)
        if not prepared_request:
            print("Change request is not in the right state (Implement or Scheduled).")
            return 1
        if original_state == "scheduled":
            print(
                "Change request is Scheduled; moving it to Implement before creating tasks."
            )

        change_task, closed_task = create_and_close_change_task(
            client,
            prepared_request,
            args.task_short_description,
            args.task_description,
            args.task_work_notes,
            args.task_close_notes,
        )
        print("Change task created:")
        print(json.dumps(change_task, indent=2, sort_keys=True))
        print("Change task closed:")
        print(json.dumps(closed_task, indent=2, sort_keys=True))

        return 0

    print(
        f"Polling for change request {args.change_number} "
        f"(attempts: {args.max_attempts}, interval: {args.interval_seconds}s)..."
    )
    record = client.poll_change_request(
        args.change_number, max_attempts=args.max_attempts, interval_seconds=args.interval_seconds
    )
    if not record:
        print("Change request was not found before the maximum attempts were reached.")
        if args.create_task:
            print("Cannot create change task because the change request is not valid.")
        return 1

    print("Change request found:")
    print(json.dumps(record, indent=2, sort_keys=True))

    if not args.create_task:
        return 0

    original_state = normalize_change_request_state(record.get("state"))
    prepared_request = prepare_change_request_for_task(client, record)
    if not prepared_request:
        print("Change request is not in the right state (Implement or Scheduled).")
        return 1
    if original_state == "scheduled":
        print("Change request is Scheduled; moving it to Implement before creating tasks.")

    change_task, closed_task = create_and_close_change_task(
        client,
        prepared_request,
        args.task_short_description,
        args.task_description,
        args.task_work_notes,
        args.task_close_notes,
    )
    print("Change task created:")
    print(json.dumps(change_task, indent=2, sort_keys=True))
    print("Change task closed:")
    print(json.dumps(closed_task, indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
