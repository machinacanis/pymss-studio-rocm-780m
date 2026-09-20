"""Verify node positions and viewport restore after closing and reopening a workflow."""

import json

from playwright.sync_api import expect, sync_playwright


EXPECTED_POSITIONS = {
    "pymss_load_audio": [321, 234],
    "pymss_mss_params": [125, 567],
    "mss_separate": [654, 345],
    "pymss_save_audio": [1012, 456],
}
EXPECTED_VIEWPORT = {"scale": 1.23, "offset": [77, -36]}


def canvas_state(page):
    return page.locator("canvas.lg-canvas").evaluate(
        """canvas => ({
          positions: Object.fromEntries(canvas.data.graph.nodes.map(node => [node.type, [...node.pos]])),
          viewport: { scale: canvas.data.ds.scale, offset: [...canvas.data.ds.offset] },
        })"""
    )


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
    canvas = page.locator("canvas.lg-canvas")
    expect(canvas).to_be_visible()
    page.wait_for_function(
        "document.querySelector('canvas.lg-canvas')?.data?.graph?.nodes?.length === 4"
    )

    canvas.evaluate(
        """(canvas, payload) => {
          for (const node of canvas.data.graph.nodes) {
            const position = payload.positions[node.type]
            if (position) node.pos = [...position]
          }
          canvas.data.ds.scale = payload.viewport.scale
          canvas.data.ds.offset = [...payload.viewport.offset]
          canvas.data.graph.afterChange()
          canvas.data.setDirty(true, true)
        }""",
        {"positions": EXPECTED_POSITIONS, "viewport": EXPECTED_VIEWPORT},
    )

    page.locator(".toolbar").get_by_role("button", name="Save", exact=True).click()
    page.wait_for_function(
        "Boolean(JSON.parse(localStorage.getItem('pymss-studio:workflow-state') || '{}').workflows?.length)"
    )
    stored = page.evaluate(
        "JSON.parse(localStorage.getItem('pymss-studio:workflow-state')).workflows[0]"
    )
    workflow_id = stored["id"]
    stored_positions = {node["type"]: node["pos"] for node in stored["definition"]["nodes"]}
    assert stored_positions == EXPECTED_POSITIONS, stored_positions
    assert stored["definition"]["extra"]["ds"] == EXPECTED_VIEWPORT

    page.locator(".toolbar").get_by_role("button", name="Close", exact=True).click()
    page.wait_for_url("**/#/workflows")
    page.evaluate(f"location.hash = '#/workflow-node-editor?workflowId={workflow_id}'")
    page.wait_for_url(f"**/#/workflow-node-editor?workflowId={workflow_id}")
    expect(page.locator("canvas.lg-canvas")).to_be_visible()
    page.wait_for_function(
        "document.querySelector('canvas.lg-canvas')?.data?.graph?.nodes?.length === 4"
    )

    restored = canvas_state(page)
    assert restored["positions"] == EXPECTED_POSITIONS, restored
    assert abs(restored["viewport"]["scale"] - EXPECTED_VIEWPORT["scale"]) < 1e-9, restored
    assert restored["viewport"]["offset"] == EXPECTED_VIEWPORT["offset"], restored
    print(json.dumps(restored, ensure_ascii=False))
    print("advanced workflow position restore smoke passed")
    browser.close()
