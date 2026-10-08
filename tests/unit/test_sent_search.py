"""Unit tests for Gmail Sent folder cold outreach search."""

from unittest.mock import MagicMock

from jobpilot.gmail.sent_search import check_prior_outreach


def test_check_prior_outreach_no_domains() -> None:
    service = MagicMock()
    has_outreach, domain = check_prior_outreach(service, [])
    assert has_outreach is False
    assert domain is None
    assert service.users.called is False


def test_check_prior_outreach_found() -> None:
    service = MagicMock()
    messages_mock = MagicMock()
    service.users.return_value.messages.return_value = messages_mock
    messages_mock.list.return_value.execute.return_value = {"messages": [{"id": "msg_123"}]}

    has_outreach, domain = check_prior_outreach(service, ["stripe.com"])
    assert has_outreach is True
    assert domain == "stripe.com"
    messages_mock.list.assert_called_once_with(
        userId="me",
        q="to:stripe.com newer_than:60d",
        maxResults=5,
    )


def test_check_prior_outreach_not_found() -> None:
    service = MagicMock()
    messages_mock = MagicMock()
    service.users.return_value.messages.return_value = messages_mock
    messages_mock.list.return_value.execute.return_value = {"messages": []}

    has_outreach, domain = check_prior_outreach(service, ["openai.com", "stripe.com"])
    assert has_outreach is False
    assert domain is None
    assert messages_mock.list.call_count == 2


def test_check_prior_outreach_handles_api_exception() -> None:
    service = MagicMock()
    messages_mock = MagicMock()
    service.users.return_value.messages.return_value = messages_mock
    messages_mock.list.return_value.execute.side_effect = Exception("API rate limited")

    has_outreach, domain = check_prior_outreach(service, ["stripe.com"])
    assert has_outreach is False
    assert domain is None
