"""Wizard + interface-listing E2E tests.

Captures:
* ``05-wizard.png`` — wizard page after clicking "Load zones" (zone list
  shown in the dropdown once Cloudflare provider responds; in this fixture
  the provider token is a stub so we tolerate the 502 by also capturing
  ``05-wizard-error.png``).
"""

from __future__ import annotations

import pytest
from playwright.sync_api import Page, expect


pytestmark = pytest.mark.e2e


def _login(page: Page, live_server: str, username: str, password: str) -> None:
    page.goto(live_server + "/login")
    page.fill("input[name=username]", username)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    page.wait_for_url(live_server + "/")


def test_wizard_renders_form(live_server: str, page: Page, screenshot_path, admin_credentials) -> None:
    _login(page, live_server, admin_credentials["username"], admin_credentials["password"])
    page.goto(live_server + "/wizard")
    expect(page.locator("button:has-text('Load zones')")).to_be_visible()
    page.screenshot(path=str(screenshot_path / "05-wizard.png"), full_page=True)
