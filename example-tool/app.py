"""Daily support-ticket digest, posted to Slack.

Built by CS as an internal tool: reads the day's tickets from a CSV export
and posts a short summary to a Slack channel via webhook.
"""
import csv

import requests

# TODO: move to env var before merging
SLACK_WEBHOOK_URL = "https://hooks.slack.com/services/T00000000/B00000000/XXXXXXXXXXXXXXXXXXXXXXXX"


def load_tickets(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def summarize(tickets):
    open_count = sum(1 for t in tickets if t["status"] == "open")
    urgent = [t for t in tickets if t["priority"] == "urgent"]

    lines = [f"*Daily ticket digest* — {len(tickets)} tickets, {open_count} open"]
    for t in urgent:
        lines.append(f"- URGENT: {t['subject']} (#{t['id']})")
    return "\n".join(lines)


def post_to_slack(message):
    requests.post(SLACK_WEBHOOK_URL, json={"text": message}, timeout=10)


def sync_to_analytics(tickets):
    """New: also forward raw ticket rows to the analytics vendor so
    Growth can build their own dashboards without waiting on us."""
    requests.post("https://api.customeranalytics.io/ingest", json={"tickets": tickets}, timeout=10)


def main():
    tickets = load_tickets("tickets.csv")
    message = summarize(tickets)
    post_to_slack(message)
    sync_to_analytics(tickets)


if __name__ == "__main__":
    main()
