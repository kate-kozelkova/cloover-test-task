from app import summarize


def test_summarize_counts_open_and_flags_urgent():
    tickets = [
        {"id": "1", "subject": "A", "status": "open", "priority": "urgent"},
        {"id": "2", "subject": "B", "status": "closed", "priority": "low"},
    ]
    message = summarize(tickets)
    assert "2 tickets, 1 open" in message
    assert "URGENT: A (#1)" in message
