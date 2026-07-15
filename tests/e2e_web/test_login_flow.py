"""Login flow + dashboard rendering E2E tests.

Captures `docs/screenshots/` PNGs at every milestone:

* ``01-login.png`` — login form rendered (initial GET)
* ``02-login-failure.png`` — login form with error after bad password
* ``03-dashboard.png`` — authenticated dashboard
* ``04-logout.png`` — back at the login page after /logout
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def test_login_form_renders(live_server: str, page: Page, screenshot_path) -> None:
    response = page.goto(live_server + "/login")
    assert response is not None and response.status == 200
    expect(page.locator("input[name=username]")).to_be_visible()
    expect(page.locator("input[name=password]")).to_be_visible()
    page.screenshot(path=str(screenshot_path / "01-login.png"), full_page=True)


def test_login_with_bad_credentials_shows_error(
    live_server: str, page: Page, screenshot_path
) -> None:
    page.goto(live_server + "/login")
    page.fill("input[name=username]", "admin")
    page.fill("input[name=password]", "wrong-password")
    page.click("button[type=submit]")
    expect(page.locator("body")).to_contain_text("Invalid credentials")
    page.screenshot(path=str(screenshot_path / "02-login-failure.png"), full_page=True)


def test_login_with_valid_credentials_lands_dashboard(
    live_server: str, page: Page, screenshot_path, admin_credentials: dict[str, str]
) -> None:
    page.goto(live_server + "/login")
    page.fill("input[name=username]", admin_credentials["username"])
    page.fill("input[name=password]", admin_credentials["password"])
    page.click("button[type=submit]")
    page.wait_for_url(live_server + "/")
    expect(page.locator("h2")).to_contain_text("Managed hosts")
    page.screenshot(path=str(screenshot_path / "03-dashboard.png"), full_page=True)


def test_logout_clears_session(live_server: str, page: Page, screenshot_path, admin_credentials) -> None:
    page.goto(live_server + "/login")
    page.fill("input[name=username]", admin_credentials["username"])
    page.fill("input[name=password]", admin_credentials["password"])
    page.click("button[type=submit]")
    page.wait_for_url(live_server + "/")
    page.click("form[action='/logout'] button[type=submit]")
    page.wait_for_url("**/login")
    expect(page.locator("h2")).to_contain_text("Login")
    page.screenshot(path=str(screenshot_path / "04-logout.png"), full_page=True)
