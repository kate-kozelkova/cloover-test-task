"""Daily support-ticket digest, posted to Slack.

Built by CS as an internal tool: reads the day's tickets from a CSV export
and posts a short summary to a Slack channel via webhook.
"""
import csv
import os

import requests


def load_tickets(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def summarize(tickets):
    open_count = sum(1 for t in tickets if t["status"] == "open")
    closed_count = sum(1 for t in tickets if t["status"] == "closed")
    urgent = [t for t in tickets if t["priority"] == "urgent"]

    lines = [
        f"*Daily ticket digest* — {len(tickets)} tickets, "
        f"{open_count} open, {closed_count} closed today"
    ]
    for t in urgent:
        lines.append(f"- URGENT: {t['subject']} (#{t['id']})")
    return "\n".join(lines)


def post_to_slack(message, webhook_url):
    requests.post(webhook_url, json={"text": message}, timeout=10)


def main():
    webhook_url = os.environ["SLACK_WEBHOOK_URL"]
    tickets = load_tickets("tickets.csv")
    message = summarize(tickets)
    post_to_slack(message, webhook_url)


if __name__ == "__main__":
    main()
