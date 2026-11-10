# Image-Template Computer Vision Automation

ULTK's image-template pack adds visual targeting for known icons and controls when OCR cannot read
their labels. It complements the OCR-backed desktop pack and the semantic browser pack. It does not
replace accessibility APIs or infer the meaning of arbitrary objects.

## Installation

Install the optional Python dependencies:

```bash
pip install -e '.[computer-vision]'
```

A supported interactive desktop session and screenshot backend are required. The pack uses PyAutoGUI
for screen capture and pointer input, NumPy for image arrays, and OpenCV for template matching.

Place host-approved reference images in a dedicated directory, for example:

```text
computer_templates/
  save_icon.png
  settings_gear.png
  close_button.png
```

Enable the pack:

```python
from ultk import ToolEngine

engine = ToolEngine(policy=my_policy)
engine.install_computer_vision_tools(
    template_root="./computer_templates",
    max_template_bytes=2_000_000,
    max_template_pixels=2_000_000,
)
```

## Tools

| Tool | Purpose | Capability |
|---|---|---|
| `computer_vision.match_template` | Return bounded visual candidates and coordinates | `computer:screen:read` |
| `computer_vision.click_template` | Click only when exactly one non-overlapping candidate is detected | `computer:screen:control` |
| `computer_vision.wait_for_template` | Poll for a matching template for up to 10 seconds | `computer:screen:read` |

Example candidate search:

```python
result = await engine.execute(
    "computer_vision.match_template",
    {"template": "save_icon.png", "min_score": 0.88, "max_matches": 5},
    granted_capabilities=frozenset({"computer:screen:read"}),
)
```

Example unique-match click:

```python
result = await engine.execute(
    "computer_vision.click_template",
    {"template": "save_icon.png", "min_score": 0.90},
    granted_capabilities=frozenset({"computer:screen:control"}),
)
```

## Matching behavior

- Uses grayscale normalized cross-correlation with five fixed scales: 0.80x, 0.90x, 1.00x,
  1.10x and 1.20x.
- Returns candidate bounding boxes, centers, scale and correlation score.
- Uses overlap suppression to reduce duplicate detections across adjacent positions and scales.
- The score is a normalized correlation value, **not a probability**. Calibrate thresholds against
  real screenshots for each UI, theme, zoom and display configuration.
- Clicks only if exactly one non-overlapping candidate survives the configured threshold.
  Zero matches and multiple matches fail closed.
- Waits are bounded to 10 seconds; each capture is capped at 16 megapixels.
- Template files are confined to the configured root directory, limited by extension and byte size.
  Template dimensions are checked after decoding.

## Security and limitations

- Templates are trusted host-provided files. The model can select a filename under the configured
  template root but cannot supply arbitrary image bytes or paths outside that root.
- Grant read and control capabilities separately. Clicking a detected icon can trigger an
  externally visible, financial, destructive or account-changing action; high-impact clicks should
  require human approval tied to the exact tool arguments.
- This is not a sandbox. Captures and clicks operate in the active desktop session under the host
  user's OS privileges.
- Template matching is not semantic object detection. It cannot reliably identify a new icon from
  its meaning, distinguish visually identical controls by intent, or generalize to arbitrary
  unseen layouts. Use OCR or accessibility-based targeting when those are more reliable.
- Scaling, DPI, theme, animation, anti-aliasing, localization and application updates can change
  appearance and reduce match scores. Multi-monitor coordinates follow the host screenshot backend.
- CPU cost grows with screenshot size, template size and number of scales. Keep capture regions
  narrow and templates small. No GPU acceleration, learned detector, screenshot streaming or
  background desktop session is included.
- Validate false positives, missed detections and click coordinates on each supported OS and
  screenshot backend before enabling unattended workflows.
