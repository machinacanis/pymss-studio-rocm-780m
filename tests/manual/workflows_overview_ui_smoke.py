"""Headless UI smoke for workflow type grouping and overview hierarchy."""

import json

from playwright.sync_api import expect, sync_playwright


simple_definition = {
    "version": 1,
    "defaults": {"device": "auto", "output_format": "wav"},
    "steps": [
        {
            "id": "step1",
            "model": "simple-model.ckpt",
            "input": "input",
            "stems": ["Vocals", "Instrumental"],
            "save": {"Vocals": "Default", "Instrumental": "Default"},
        }
    ],
}
advanced_definition = {
    "last_node_id": 4,
    "last_link_id": 3,
    "version": 0.4,
    "nodes": [
        {"id": 1, "type": "input_audio", "inputs": [], "outputs": [], "widgets_values": []},
        {
            "id": 2,
            "type": "mss_separate",
            "inputs": [],
            "outputs": [],
            "widgets_values": ["advanced-model.ckpt", "auto", True, "modelscope", "0", False],
        },
        {"id": 3, "type": "pymss_audio_normalize", "inputs": [], "outputs": [], "widgets_values": []},
        {"id": 4, "type": "pymss_save_audio", "inputs": [], "outputs": [], "widgets_values": ["wav", "44100", "FLOAT", "PCM_24", "320k"]},
    ],
    "links": [[1, 1, 0, 2, 0, "AUDIO"], [2, 2, 0, 3, 0, "AUDIO"], [3, 3, 0, 4, 0, "AUDIO"]],
}
workflow_state = {
    "selectedWorkflowId": "advanced",
    "workflows": [
        {
            "id": "advanced",
            "name": "Advanced routing",
            "description": "A graph workflow with processing nodes.",
            "definition": advanced_definition,
            "format": "graph",
            "formatVersion": 1,
            "createdAt": 2,
            "updatedAt": 2,
        },
        {
            "id": "simple",
            "name": "Simple vocal split",
            "description": "A compact two-stem workflow.",
            "definition": simple_definition,
            "format": "simple",
            "formatVersion": 1,
            "createdAt": 1,
            "updatedAt": 1,
        },
    ],
}


with sync_playwright() as playwright:
    browser = playwright.chromium.launch(headless=True)
    page = browser.new_page(viewport={"width": 1440, "height": 1000})
    page.add_init_script(
        f"""(() => {{
          localStorage.setItem(
            'pymss-studio:app-settings',
            JSON.stringify({{ startupOnboardingSeen: true, locale: 'en' }}),
          )
          localStorage.setItem('pymss-studio:workflow-state', JSON.stringify({json.dumps(workflow_state)}))
        }})()"""
    )
    page.goto("http://localhost:1420/#/workflows")
    page.wait_for_load_state("networkidle")

    expect(page.locator(".wf-list-group__head", has_text="Simple workflows")).to_be_visible()
    expect(page.locator(".wf-list-group__head", has_text="Advanced workflows")).to_be_visible()
    expect(page.locator(".wf-row--simple")).to_contain_text("Simple")
    expect(page.locator(".wf-row--simple")).to_contain_text("Steps 1 · Outputs 2")
    expect(page.locator(".wf-row--advanced")).to_contain_text("Advanced")
    expect(page.locator(".wf-row--advanced")).to_contain_text("Nodes 4 · Outputs 1")

    page.locator(".wf-row--advanced").click()
    expect(page.locator(".wf-kind-badge--advanced")).to_have_text("Advanced")
    for label in ["Separation nodes", "Tools", "Save nodes", "Links"]:
        expect(page.locator(".wf-metric", has_text=label)).to_be_visible()
    expect(page.get_by_role("button", name="Edit node graph", exact=True)).to_be_visible()

    page.locator(".wf-type-filter button", has_text="Simple").click()
    expect(page.locator(".wf-row--simple")).to_be_visible()
    expect(page.locator(".wf-row--advanced")).to_have_count(0)
    expect(page.locator(".wf-kind-badge--simple")).to_have_text("Simple")
    expect(page.locator(".wf-metrics--three .wf-metric")).to_have_count(3)
    expect(page.get_by_role("button", name="Edit steps", exact=True)).to_be_visible()

    page.locator(".wf-type-filter button", has_text="All").click()
    page.locator(".wf-row--advanced").click()
    page.screenshot(path="data/outputs/workflows-overview-redesign.png", full_page=True)
    print(json.dumps({"groups": 2, "filters": 3, "simpleMetrics": 3}))
    print("workflows overview UI smoke passed")
    browser.close()
