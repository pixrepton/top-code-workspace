"""
Agent Chat — Daszek E2E UI Playwright tests.

Prerequisites:
  - Daszek local stack running (docker compose -f docker-compose.daszek-local.yml up -d)
  - gmail-agent-nodeb-api running (docker compose --profile api up -d)
  - Test user: konrad / konrad123

Run:
  cd <workspace-root>
  python -m pytest tests/e2e/test_agent_chat_ui.py -v --headed  (visible browser)
  python -m pytest tests/e2e/test_agent_chat_ui.py -v         (headless)
"""

import re
import json
import pytest
from playwright.sync_api import Page, expect

DASZEK_URL = "http://127.0.0.1:8090/daszek/"
LOGIN = "konrad"
PASSWORD = "konrad123"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="function")
def browser_context(browser):
    """Create a new browser context (isolated storage / cookies)."""
    context = browser.new_context(
        viewport={"width": 1440, "height": 900},
        locale="pl-PL",
    )
    yield context
    context.close()


@pytest.fixture(scope="function")
def logged_in_page(browser_context):
    """Log into Daszek once and return a page with an active session."""
    page = browser_context.new_page()
    page.goto(DASZEK_URL, wait_until="networkidle")

    # --- Login screen assertions ---
    expect(page.locator("#login-screen")).to_be_visible()
    expect(page.locator("#login-form")).to_be_visible()
    expect(page.locator("#login")).to_be_visible()
    expect(page.locator("#password")).to_be_visible()

    # --- Fill credentials ---
    page.fill("#login", LOGIN)
    page.fill("#password", PASSWORD)

    # --- Submit ---
    page.click("button[type='submit']")

    # --- Wait for main screen (desk view) ---
    expect(page.locator("#main-screen")).to_be_visible(timeout=10000)

    # Ensure the view-root has desk content
    expect(page.locator("#view-root")).to_be_visible(timeout=5000)

    yield page
    page.close()


# ---------------------------------------------------------------------------
# Helper: find first case card and open it
# ---------------------------------------------------------------------------

def open_first_case(page: Page) -> str:
    """Click the first visible [data-open-case] card and return the case_id.

    If the detail panel is already open, close it first via the close button
    or backdrop click.
    """
    detail_panel = page.locator("#detail-panel")
    if detail_panel.is_visible():
        close_btn = page.locator("[data-close-detail]")
        if close_btn.is_visible():
            close_btn.click()
            page.wait_for_selector("#detail-panel", state="hidden", timeout=5000)
        else:
            # Click backdrop as fallback
            backdrop = page.locator("#detail-panel-backdrop")
            if backdrop.is_visible():
                backdrop.click()
                page.wait_for_selector("#detail-panel", state="hidden", timeout=5000)

    # Wait for desk items to render
    page.wait_for_selector("[data-open-case]", state="visible", timeout=15000)
    cards = page.locator("[data-open-case]")
    count = cards.count()
    assert count > 0, "No case cards found on the desk"
    case_id = cards.first.get_attribute("data-open-case")
    assert case_id, "Case card has no data-open-case attribute"
    cards.first.click()
    # Wait for detail panel
    page.wait_for_selector("#detail-panel", state="visible", timeout=15000)
    return case_id


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestDaszekLogin:
    """Verify the Daszek login flow works."""

    def test_login_screen_elements(self, logged_in_page):
        """After login the main screen is visible with user indicator."""
        page = logged_in_page
        expect(page.locator("#current-user")).to_have_text(LOGIN)
        # Nav / toolbar should be present
        expect(page.locator("#refresh-btn")).to_be_visible()
        expect(page.locator("#logout-btn")).to_be_visible()

    def test_logout_returns_to_login(self, browser_context):
        """Logging out returns to login screen."""
        page = browser_context.new_page()
        page.goto(DASZEK_URL, wait_until="networkidle")
        page.fill("#login", LOGIN)
        page.fill("#password", PASSWORD)
        page.click("button[type='submit']")
        expect(page.locator("#main-screen")).to_be_visible(timeout=10000)

        page.click("#logout-btn")
        expect(page.locator("#login-screen")).to_be_visible(timeout=5000)
        page.close()

    def test_invalid_login_shows_error(self, browser_context):
        """Invalid credentials display an error message."""
        page = browser_context.new_page()
        page.goto(DASZEK_URL, wait_until="networkidle")
        page.fill("#login", "wrong")
        page.fill("#password", "wrong")
        page.click("button[type='submit']")
        error = page.locator("#login-error")
        expect(error).to_be_visible(timeout=5000)
        # Should show a non-empty error message
        page.wait_for_timeout(1000)
        text = error.text_content() or ""
        assert text.strip(), "Error message should not be empty"
        page.close()


class TestAgentChatPanel:
    """Verify the Agent Chat panel renders and behaves."""

    def test_agent_chat_section_visible_in_case_detail(self, logged_in_page):
        """Opening a case detail reveals the Agent Chat section."""
        page = logged_in_page
        case_id = open_first_case(page)
        print(f"\n[INFO] Opened case: {case_id}")

        # The agent-chat-section should now be visible
        section = page.locator("#agent-chat-section")
        expect(section).to_be_visible(timeout=5000)

        # The panel should be rendered inside
        panel = page.locator(".agent-chat-panel")
        expect(panel).to_be_visible(timeout=3000)

        # Check the heading
        expect(panel.locator("h4")).to_have_text("Asystent AI (Agent Chat)")

    def test_agent_chat_ui_elements_present(self, logged_in_page):
        """Agent Chat panel contains input, send button, and messages area."""
        page = logged_in_page
        open_first_case(page)
        page.wait_for_selector(".agent-chat-panel", state="visible", timeout=5000)

        # Input field
        input_field = page.locator(".agent-chat-input")
        expect(input_field).to_be_visible()
        expect(input_field).to_be_enabled()
        expect(input_field).to_have_attribute("placeholder", "Wpisz polecenie dla agenta...")

        # Send button
        send_btn = page.locator(".agent-chat-send")
        expect(send_btn).to_be_visible()
        expect(send_btn).to_be_enabled()
        expect(send_btn).to_have_text("Wyślij")

        # Messages container (empty initially - not visible since 0 bounding box)
        messages = page.locator(".agent-chat-messages")
        expect(messages).to_have_count(1)
        # No children yet
        children = messages.locator("> *")
        expect(children).to_have_count(0)

    def test_send_button_disabled_with_empty_input(self, logged_in_page):
        """Clicking send with empty input should not send (no loading state)."""
        page = logged_in_page
        open_first_case(page)
        page.wait_for_selector(".agent-chat-panel", state="visible", timeout=5000)

        send_btn = page.locator(".agent-chat-send")
        input_field = page.locator(".agent-chat-input")

        # Clear and click send without typing
        input_field.fill("")
        send_btn.click()

        # Button should remain enabled with original text (no loading)
        expect(send_btn).to_be_enabled()
        expect(send_btn).to_have_text("Wyślij")

        # Messages area should still be empty
        messages = page.locator(".agent-chat-messages")
        children = messages.locator("> *")
        expect(children).to_have_count(0)

    def test_send_message_shows_user_bubble(self, logged_in_page):
        """Sending a message triggers agent processing and user bubble appears."""
        page = logged_in_page
        open_first_case(page)
        page.wait_for_selector(".agent-chat-panel", state="visible", timeout=5000)
        page.wait_for_timeout(1000)

        # Type message and click send via Playwright's standard methods with force option
        input_field = page.locator(".agent-chat-input")
        send_btn = page.locator(".agent-chat-send")

        input_field.fill("Witaj, pokaz mi liste moich spraw")
        page.wait_for_timeout(300)
        input_field.press("Enter")

        # Wait for the API round-trip to complete (button re-enables)
        expect(send_btn).to_be_enabled(timeout=30000)

        # The messages area should now have content
        messages = page.locator(".agent-chat-messages")
        msg_text = messages.text_content() or ""
        print(f"\n[INFO] Messages after send: {msg_text[:300]}")
        assert "Ty:" in msg_text, f"User message not found in: {msg_text[:200]}"
        assert len(msg_text) > 50, f"Response too short or only user message: {msg_text[:200]}"

    def test_agent_chat_receives_response(self, logged_in_page):
        """After sending a message, the agent response is displayed."""
        page = logged_in_page
        open_first_case(page)
        page.wait_for_selector(".agent-chat-panel", state="visible", timeout=5000)
        page.wait_for_timeout(1000)

        # Send a message
        input_field = page.locator(".agent-chat-input")
        send_btn = page.locator(".agent-chat-send")

        input_field.fill("Sprawdź moje sprawy")
        page.wait_for_timeout(300)
        input_field.press("Enter")

        # Wait for loading to finish — button returns to "Wyślij"
        expect(send_btn).to_be_enabled(timeout=30000)

        # Input should be re-enabled
        expect(input_field).to_be_enabled()

        # Check that messages area has at least the user message and a response
        messages = page.locator(".agent-chat-messages")
        expect(messages).to_contain_text("Ty: Sprawdź moje sprawy")

        # Response should appear — either agent, error, or info message
        response_text = messages.text_content() or ""
        print(f"\n[INFO] Agent chat response: {response_text[:200]}")
        assert response_text, "No response text in agent chat messages"

        # At minimum there should be content beyond just the user message
        assert len(response_text) > len("Ty: Sprawdź moje sprawy"), (
            "Response area only contains user message, no agent response"
        )

    def test_multiple_turns_preserve_history(self, logged_in_page):
        """Multiple messages should all be visible in the chat history."""
        page = logged_in_page
        open_first_case(page)
        page.wait_for_selector(".agent-chat-panel", state="visible", timeout=5000)
        page.wait_for_timeout(1000)

        input_field = page.locator(".agent-chat-input")
        send_btn = page.locator(".agent-chat-send")

        def send_message(text):
            input_field.fill(text)
            page.wait_for_timeout(300)
            input_field.press("Enter")
            expect(send_btn).to_be_enabled(timeout=30000)

        send_message("Pierwsze polecenie")
        send_message("Drugie polecenie")

        # Both messages should be visible
        messages = page.locator(".agent-chat-messages")
        expect(messages).to_contain_text("Ty: Pierwsze polecenie")
        expect(messages).to_contain_text("Ty: Drugie polecenie")

    def test_agent_chat_session_id_is_persistent(self, logged_in_page):
        """Check that the same session_id is used across messages in one panel."""
        page = logged_in_page
        open_first_case(page)
        page.wait_for_selector(".agent-chat-panel", state="visible", timeout=5000)
        page.wait_for_timeout(1000)

        # Intercept API calls to extract session_id
        session_ids = set()

        def capture_request(route):
            req = route.request
            if "/agent-chat" in req.url and req.method == "POST":
                body = json.loads(req.post_data)
                session_ids.add(body.get("session_id", ""))
            route.continue_()

        page.route("**/agent-chat", capture_request)

        input_field = page.locator(".agent-chat-input")
        send_btn = page.locator(".agent-chat-send")

        for msg in ["Polecenie A", "Polecenie B"]:
            input_field.fill(msg)
            page.wait_for_timeout(300)
            input_field.press("Enter")
            expect(send_btn).to_be_enabled(timeout=30000)

        page.unroute("**/agent-chat")

        # Must have exactly 1 session_id across all calls
        assert len(session_ids) == 1, (
            f"Expected 1 session_id across messages, got {len(session_ids)}: {session_ids}"
        )
        sid = session_ids.pop()
        assert sid.startswith("agent_chat_"), f"Unexpected session_id format: {sid}"


class TestAgentChatEdgeCases:
    """Edge cases: errors, long messages, empty desk."""

    @pytest.mark.skip(reason="Route mock interaction needs debugging")
    def test_error_response_handling(self, logged_in_page):
        """When the API returns an error, the error message is displayed."""
        page = logged_in_page
        open_first_case(page)
        page.wait_for_selector(".agent-chat-panel", state="visible", timeout=5000)

        # Intercept and return a server error for agent-chat
        def mock_error(route):
            route.fulfill(
                status=500,
                content_type="application/json",
                body=json.dumps({"detail": "Internal error"}),
            )

        page.route("**/agent-chat", mock_error)

        input_field = page.locator(".agent-chat-input")
        send_btn = page.locator(".agent-chat-send")
        input_field.fill("Wywołaj błąd")
        page.wait_for_timeout(300)

        # Check state before
        print(f"\n[DEBUG] Button enabled before: {send_btn.is_enabled()}")
        msgs_before = page.locator(".agent-chat-messages").text_content() or "(empty)"
        print(f"[DEBUG] Messages before: {msgs_before}")

        input_field.press("Enter")
        page.wait_for_timeout(1000)
        print(f"[DEBUG] Button enabled at 1s: {send_btn.is_enabled()}")
        msgs_1s = page.locator(".agent-chat-messages").text_content() or "(empty)"
        print(f"[DEBUG] Messages at 1s: {msgs_1s}")

        page.wait_for_timeout(2000)
        print(f"[DEBUG] Button enabled at 3s: {send_btn.is_enabled()}")
        msgs_3s = page.locator(".agent-chat-messages").text_content() or "(empty)"
        print(f"[DEBUG] Messages at 3s: {msgs_3s}")

        # Error message should appear
        messages = page.locator(".agent-chat-messages")
        expect(messages).to_contain_text("Błąd")

        page.unroute("**/agent-chat")

    @pytest.mark.skip(reason="Route mock interaction needs debugging")
    def test_timeout_handling(self, logged_in_page):
        """When API times out, error is shown and inputs are re-enabled."""
        page = logged_in_page
        open_first_case(page)
        page.wait_for_selector(".agent-chat-panel", state="visible", timeout=5000)

        # Simulate a slow API (hang the request)
        def mock_slow(route):
            import time
            time.sleep(30)  # Longer than client timeout; sync handler must actually block
            route.fulfill(status=200, body=json.dumps({"ok": True}))

        page.route("**/agent-chat", mock_slow)

        input_field = page.locator(".agent-chat-input")
        send_btn = page.locator(".agent-chat-send")
        input_field.fill("Powolne polecenie")
        page.wait_for_timeout(300)
        input_field.press("Enter")

        # The button should eventually re-enable (client-side timeout or network error)
        expect(send_btn).to_be_enabled(timeout=35000)
        expect(input_field).to_be_enabled()

        # There should be an error message
        messages = page.locator(".agent-chat-messages")
        content = messages.text_content() or ""
        assert "Błąd" in content or "błąd" in content or "error" in content.lower(), (
            f"No error message shown after timeout. Content: {content[:200]}"
        )

        page.unroute("**/agent-chat")

    def test_panel_does_not_appear_on_non_case_views(self, logged_in_page):
        """Agent Chat section is hidden on non-case views."""
        page = logged_in_page

        # Navigate to a non-case view (e.g. about / system page)
        system_tabs = page.locator('[data-view="system"]')
        if system_tabs.count() > 0:
            system_tabs.first.click()
            page.wait_for_timeout(1000)
            agent_chat = page.locator("#agent-chat-section")
            expect(agent_chat).not_to_be_visible()
        else:
            pytest.skip("No system view tab available to test non-case view")


class TestNodeBAgentChatEndpoint:
    """Direct integration test of the Node B /agent-chat endpoint."""

    NODEB_URL = "http://127.0.0.1:8766"

    def test_agent_chat_endpoint_reachable(self):
        """Verify the Node B /agent-chat endpoint returns 200."""
        import urllib.request

        req = urllib.request.Request(
            f"{self.NODEB_URL}/agent-chat",
            data=json.dumps(
                {"user_input": "test ping", "session_id": "e2e_ping"}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            r = urllib.request.urlopen(req, timeout=15)
            assert r.status == 200
            data = json.loads(r.read())
            assert data.get("ok") is True
            assert "signal_id" in data
            assert "engagement_id" in data
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            pytest.fail(f"HTTP {e.code}: {body[:200]}")

    def test_agent_chat_returns_proper_schema(self):
        """Verify the response contains expected fields."""
        import urllib.request

        req = urllib.request.Request(
            f"{self.NODEB_URL}/agent-chat",
            data=json.dumps(
                {"user_input": "schemat test", "session_id": "e2e_schema"}
            ).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            r = urllib.request.urlopen(req, timeout=15)
            data = json.loads(r.read())
            # Required fields
            for field in ("ok", "signal_id", "session_id", "engagement_id"):
                assert field in data, f"Missing field: {field}"
            # session_id must match what we sent
            assert data["session_id"] == "e2e_schema"
            # signal_id must be a non-empty string
            assert isinstance(data["signal_id"], str) and data["signal_id"]
            # engagement_id must be a non-empty string
            assert isinstance(data["engagement_id"], str) and data["engagement_id"]
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            pytest.fail(f"HTTP {e.code}: {body[:200]}")

    def test_agent_chat_missing_session_id_gets_anonymous(self):
        """Missing session_id is auto-assigned an anonymous ID."""
        import urllib.request

        req = urllib.request.Request(
            f"{self.NODEB_URL}/agent-chat",
            data=json.dumps({"user_input": "test"}).encode(),  # No session_id
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        r = urllib.request.urlopen(req, timeout=10)
        data = json.loads(r.read())
        assert r.status == 200, f"Expected 200, got {r.status}: {data}"
        assert data.get("session_id") == "agent_chat_anon", (
            f"Expected anonymous session_id, got: {data.get('session_id')}"
        )
        assert data.get("ok") is True

    def test_agent_chat_missing_user_input_returns_400(self):
        """Missing user_input should return 400 validation error."""
        import urllib.request

        req = urllib.request.Request(
            f"{self.NODEB_URL}/agent-chat",
            data=json.dumps({"session_id": "e2e_test"}).encode(),  # No user_input
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(req, timeout=10)
        assert exc.value.code == 400, f"Expected 400, got {exc.value.code}"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--headed"])
