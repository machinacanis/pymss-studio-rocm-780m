"""Headless UI smoke for the advanced workflow editor palette."""

from playwright.sync_api import expect, sync_playwright


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.add_init_script(
        """localStorage.setItem(
          'pymss-studio:app-settings',
          JSON.stringify({ startupOnboardingSeen: true, locale: 'en' }),
        )"""
    )
    page.goto("http://localhost:1420/#/workflow-node-editor?new=1")
    page.wait_for_load_state("networkidle")

    add_node = page.get_by_role("button", name="Add Node")
    expect(add_node).to_be_visible()
    add_node.click()
    palette = page.locator(".palette")
    expect(palette).to_be_visible()

    expected_nodes = [
        "Advanced Audio Save",
        "Trim Audio Duration",
        "Adjust Volume",
        "Empty Audio",
        "3-Band Equalizer",
        "String Substring",
        "Regex Extract",
    ]
    for label in expected_nodes:
        expect(palette.get_by_role("button", name=label, exact=True)).to_be_visible()

    palette.locator(".palette-input").fill("Advanced Audio Save")
    palette.get_by_role("button", name="Advanced Audio Save", exact=True).click()
    expect(palette).to_be_hidden()
    expect(page.locator("canvas.lg-canvas")).to_be_visible()
    print("advanced workflow editor UI smoke passed")
    browser.close()
