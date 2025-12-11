# ServiceNow Change Request Poller

This repo provides a small Python helper to poll the ServiceNow Table API and check if a change request (CR) already exists.

## Setup
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Provide ServiceNow credentials via environment variables or CLI flags:
   - `SERVICENOW_INSTANCE_URL` (e.g., `https://example.service-now.com`)
   - `SERVICENOW_USERNAME`
   - `SERVICENOW_PASSWORD`
   - `SERVICENOW_CA_BUNDLE` (optional, path to your private PKI bundle)

## Usage
The `servicenow_poll.py` script supports one-shot checks and polling mode.

### Poll until a CR appears
```bash
python servicenow_poll.py --change-number CHG0030001 \
  --max-attempts 15 --interval-seconds 20
```
The script will poll the `change_request` table until the CR is found or attempts are exhausted. On success, the matching record is printed as formatted JSON.

### Single check
```bash
python servicenow_poll.py --change-number CHG0030001 --one-shot
```
The script exits with status code `0` if the CR exists and `1` if not found, which makes it easy to integrate into CI/CD or automation pipelines.

## Notes
- Authentication uses basic auth via the provided username and password.
- Requests are made against the `/api/now/table/change_request` endpoint with a query filtered by the provided change number.
- Use `--ca-bundle` or `SERVICENOW_CA_BUNDLE` to point to a custom CA file when your ServiceNow instance uses a private PKI.
