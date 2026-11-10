# AI Visual Grounding Automation

ULTK's visual-grounding pack lets a model target a desktop element from a natural-language
description, without requiring a saved reference image. For example:

> the settings gear in the upper-right corner

The pack is provider-independent. The host supplies a synchronous visual-grounding adapter that
accepts PNG screenshot bytes and the target description, then returns candidate bounding boxes.
ULTK validates the adapter output, applies confidence filtering, and only clicks when exactly one
candidate remains above the configured threshold.

## Architecture

```text
Natural-language target
          |
          v
ULTK captures bounded screenshot
          |
          v
Host VisualGrounder adapter
  (local or hosted vision model)
          |
          v
Candidate boxes + confidence
          |
          v
ULTK validates coordinates, bounds,
candidate count and confidence values
          |
      +---+---+
      |       |
  Inspect   Unique candidate?
  results      |
           yes | no
               v
          Click center
```

The adapter is injected by the application. ULTK does not select a model, bundle model weights,
manage provider credentials, or make network requests on the host's behalf. A local backend can
keep screenshots on-device; a hosted backend may transmit screen contents externally and must be
configured with the application's privacy and data-handling requirements.

## Installation

Install the optional desktop dependencies:

```bash
pip install -e '.[computer]'
```

Install the provider/model dependencies required by your adapter separately.

## Adapter contract

The adapter is a callable with this interface:

```python
def grounder(screenshot_png: bytes, target_description: str) -> list[dict]:
    return [
        {
            "label": "settings gear",
            "x": 820,
            "y": 24,
            "width": 28,
            "height": 28,
            "confidence": 0.93,
        }
    ]
```

Coordinates are pixels relative to the supplied screenshot, with the origin at its top-left.
Confidence is a backend-reported value in the inclusive range 0–1. The adapter is responsible for
translating provider-specific output into this stable contract. Every candidate must contain
numeric x/y/width/height/confidence fields; width and height must be positive and the entire box
must lie inside the screenshot. A label is optional.

## Enable the pack

```python
from ultk import ToolEngine

engine = ToolEngine(policy=my_policy)
engine.install_computer_grounding_tools(
    grounder=my_visual_grounder,
    max_screenshot_pixels=16_000_000,
    max_screenshot_bytes=12_000_000,
    max_candidates=10,
)
```

## Tools

| Tool | Purpose | Capability |
|---|---|---|
| `computer_grounding.locate_target` | Return candidate boxes for a natural-language desktop target | `computer:screen:read` |
| `computer_grounding.click_target` | Click only when exactly one candidate exceeds the confidence threshold | `computer:screen:control` |

Example inspection:

```python
result = await engine.execute(
    "computer_grounding.locate_target",
    {
        "target_description": "the settings gear in the upper-right corner",
        "confidence_threshold": 0.70,
        "region": [0, 0, 1200, 800],
    },
    granted_capabilities=frozenset({"computer:screen:read"}),
)
```

Example unique-target click:

```python
result = await engine.execute(
    "computer_grounding.click_target",
    {
        "target_description": "the settings gear in the upper-right corner",
        "confidence_threshold": 0.85,
    },
    granted_capabilities=frozenset({"computer:screen:control"}),
)
```

The click operation captures a fresh screenshot and runs grounding again; it does not click stale
coordinates returned by an earlier inspection.

## Bounds and fail-closed behavior

- Screenshot capture is limited to 16 megapixels and 12 MB by default. The capture region is
  optional and uses virtual-screen pixel coordinates.
- Target descriptions are limited to 500 characters.
- At most 10 candidates may be returned by the adapter.
- Confidence thresholds are limited to 0.50–0.99.
- Candidate boxes outside the screenshot, malformed values, non-finite numbers, invalid
  confidence values and excessive candidate counts are rejected.
- The locate tool returns all candidates at or above the threshold, sorted by reported confidence.
- The click tool issues no click unless exactly one candidate exceeds the threshold. Zero or
  multiple candidates fail closed.
- Read and control capabilities are separate. ULTK's normal policy and approval layers still apply.

## Security, privacy and limitations

- Vision-model output is untrusted. Bounding-box validation prevents out-of-screenshot coordinates,
  but does not prove that the model identified the intended control.
- Backend confidence is not necessarily calibrated and is not a probability or safety guarantee.
  Thresholds must be evaluated against representative screens and UI states.
- Similar-looking controls, overlays, animations, occlusion, scaling and unusual layouts can cause
  false positives or missed detections. A unique candidate can still be the wrong element.
- A click may submit data, change an account, trigger a purchase or perform a destructive action.
  Production hosts should require approval bound to the exact target description, fresh screenshot
  context, candidate coordinates and action arguments for high-impact operations.
- Screenshots may contain credentials, personal data, messages or confidential business content.
  Apply least privilege, retention controls and redaction where feasible. Hosted model adapters
  must disclose and enforce their external data-transfer behavior.
- This pack does not provide an OS sandbox, model runtime, provider credential manager, visual
  reasoning chain, multi-step autonomous agent or guaranteed grounding accuracy.
- The backend callable runs inside the ULTK host process. Treat it as trusted application code and
  enforce its own network, timeout, memory and resource constraints.
- Validate model quality, latency, privacy behavior and coordinate transforms on each supported OS
  and screenshot backend before enabling unattended automation.
