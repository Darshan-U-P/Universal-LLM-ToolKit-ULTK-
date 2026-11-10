# Visual Computer Automation

This increment adds OCR-backed GUI targeting to the existing computer, computer-advanced, and
computer-OS packs. It does not replace monitor/window management or the existing desktop workflow.
The new factory is installed separately through `ToolEngine.install_computer_visual_tools()`.

## Installation

Install the Python extra:

    pip install "universal-llm-toolkit[computer-visual]"

Install the **Tesseract OCR executable** and the language data files on the host operating system
separately. The Python `pytesseract` package is only a wrapper; it does not install the Tesseract
binary. On headless systems, a GUI desktop session and a supported screenshot backend are still
required.

## Tools

| Tool | Purpose | Capability |
|---|---|---|
| `computer_visual.ocr_screen` | Extract visible text lines and screen-space bounding boxes | `computer:screen:read` |
| `computer_visual.find_text` | Find exact OCR line matches without interacting | `computer:screen:read` |
| `computer_visual.click_text` | Click the center of exactly one matching visible text line | `computer:screen:control` |
| `computer_visual.wait_for_text` | Poll until an exact visible line appears or timeout | `computer:screen:read` |
| `computer_visual.scroll` | Scroll at a bounded virtual-screen coordinate | `computer:mouse:scroll` |
| `computer_visual.drag` | Drag between bounded virtual-screen coordinates | `computer:mouse:drag` |
| `computer_visual.desktop_workflow` | Run a prevalidated bounded sequence of OCR and pointer/keyboard actions | `computer:workflow:visual` |

## Usage

    from ultk import ToolEngine

    engine = ToolEngine(policy=my_policy)
    engine.install_computer_visual_tools(
        allowed_ocr_languages=("eng",),
        max_ocr_lines=100,
    )

    result = await engine.execute(
        "computer_visual.find_text",
        {"text": "Save changes", "language": "eng"},
        granted_capabilities=frozenset({"computer:screen:read"}),
    )

    clicked = await engine.execute(
        "computer_visual.click_text",
        {"text": "Save changes", "language": "eng"},
        granted_capabilities=frozenset({"computer:screen:control"}),
    )

The host policy must independently authorize the tool and its capability. The tool engine remains
deny-by-default unless the host configures a policy that grants access.

## Matching and coordinate semantics

- OCR groups Tesseract word boxes into visible text lines and returns bounded text, bounding boxes,
  and average OCR confidence.
- Text targeting is exact after whitespace normalization and case folding. It does not silently
  use fuzzy matching.
- A click is performed only when exactly one line matches. Zero or multiple matches fail closed.
- OCR languages are fixed by the host at installation. Model arguments cannot request arbitrary
  language packs.
- Regions use `[x, y, width, height]` in the PyAutoGUI screen-coordinate space. Region origins may
  be negative for virtual desktops; width and height are positive and the captured area is capped
  at 40 megapixels.
- When no region is supplied, the screenshot backend determines the captured desktop extent and
  the returned origin is (0, 0). For multi-monitor targeting, pass an explicit region in the
  coordinate space supported by the host screenshot backend.

## Workflow semantics

The visual workflow accepts up to 30 steps: `scroll`, `drag`, `click_text`, `wait_text`,
`type`, `press`, `hotkey`, and `wait`. The complete step structure, bounds, OCR language
allowlist, and aggregate wait budget (maximum 30 seconds) are validated before the first action.
At runtime, OCR text must still be uniquely visible when a click is reached. If a runtime action
fails, the workflow stops and reports the failed step and number of completed prior steps. Earlier
desktop actions are not rolled back; this is bounded sequencing, not a transaction.

Secure-attention key sequence Ctrl+Alt+Delete is rejected. Coordinates, drag duration, scroll
amount, text length, step count, OCR output and waits are bounded.

## Security and limitations

- Screen OCR can expose passwords, private messages, account details, and other visible sensitive
  information. Grant `computer:screen:read` only to trusted workflows and avoid storing raw OCR
  output in logs.
- Clicking text, dragging, scrolling and typing change the active desktop. Gate these capabilities
  with host policy and human approval where appropriate.
- OCR can misread text, omit controls, or return stale coordinates. Exact unique matching reduces
  ambiguity but does not guarantee the target's meaning or safety.
- The pack interacts with the currently active desktop session under the host user's OS privileges.
  It is not an OS sandbox and does not isolate applications.
- OCR requires a compatible Tesseract binary and language data. This increment does not provide
  image-template matching, semantic object recognition, screenshot streaming, or unattended
  background desktop sessions.
- Wayland, macOS permissions, remote desktops, display scaling, and multi-monitor capture require
  platform-specific integration testing. OCR region coordinates follow the host's screenshot
  backend, not an assumed universal display coordinate convention.
