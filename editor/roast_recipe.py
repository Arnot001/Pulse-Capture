"""Source-aware JSON roast recipes, compiled into the existing Pulse Edit Plan v2.

A roast recipe is an ordinary v2 pulse-edit-plan. The original JSON never
changes. The opened video's real fingerprint is calculated by the caller;
re-binding is explicit and never implies identical footage.
"""
from copy import deepcopy
import math

from .pulse_plan import validate_pulse_plan


def reference_mismatch(plan, identity):
    """Return the aspects of the reference footage that differ from the open MP4."""
    source = plan.get("source", {}) if isinstance(plan, dict) else {}
    reasons = []
    if source.get("sha256") != identity["sha256"]:
        reasons.append("video content hash")
    if source.get("name") != identity["name"]:
        reasons.append("filename")
    if not isinstance(source.get("duration"), (int, float)) or abs(source["duration"] - identity["duration"]) > .05:
        reasons.append("duration")
    if source.get("width") != identity["width"] or source.get("height") != identity["height"]:
        reasons.append("dimensions")
    if not isinstance(source.get("fps"), (int, float)) or abs(source["fps"] - identity["fps"]) > .001:
        reasons.append("frame rate")
    return reasons


def inspect_coverage(plan, media, offset=0.0):
    """Check all referenced source moments before generating any files."""
    if not isinstance(plan, dict) or plan.get("format") != "pulse-edit-plan" or plan.get("version") != 2:
        raise ValueError("Roast Studio imports Pulse Edit Plan v2 JSON only.")
    if not isinstance(plan.get("source"), dict):
        raise ValueError("The recipe has no source reference.")
    if type(offset) not in (int, float) or not math.isfinite(offset) or abs(offset) > 86400:
        raise ValueError("Source offset must be a finite number of seconds.")
    # The assembly clock is 30 FPS; shift as an exact output frame to
    # preserve each shot duration and avoid floating-point drift.
    offset = round(offset * 30) / 30
    if not isinstance(plan.get("timeline"), list) or not plan["timeline"]:
        raise ValueError("Recipe has no timeline.")
    missing = []
    for index, item in enumerate(plan["timeline"]):
        if not isinstance(item, dict):
            raise ValueError(f"Invalid element {index + 1}.")
        if item.get("kind") == "shot":
            if not all(type(item.get(key)) in (int, float) and math.isfinite(item[key])
                       for key in ("start", "end")):
                raise ValueError(f"Invalid shot times at element {index + 1}.")
            start, end = item["start"] + offset, item["end"] + offset
            if start < -.00001 or end > media.duration + .0005 or end <= start:
                missing.append((index + 1, start, end))
        elif item.get("kind") == "freeze":
            at = item.get("source_time")
            if type(at) not in (int, float) or not math.isfinite(at):
                raise ValueError(f"Invalid freeze time at element {index + 1}.")
            at += offset
            if at < -.00001 or at > media.duration - 1 / media.fps + .0005:
                missing.append((index + 1, at, at))
        elif item.get("kind") != "title":
            raise ValueError(f"Unknown timeline element {index + 1}.")
    if missing:
        index, start, end = missing[0]
        raise ValueError(
            f"Element {index} needs source {start:.2f}–{end:.2f}s, "
            f"but your video is {media.duration:.2f}s. "
            "Select the full recording or adjust Source offset. "
            "Do not change the duration in JSON.")
    return offset


def bind_roast_recipe(plan, media, identity, *, offset=0.0, confirm_mismatch=False,
                      captions_in_bands=True):
    """Return a separately validated, source-bound plan; never alter the original.

    If the bytes or metadata are different, the caller must explicitly confirm
    that the moments line up. Even then the caller must review the rendered cut.
    """
    media.validate()
    if not isinstance(identity, dict) or identity.get("name") != media.path.name:
        raise ValueError("Source fingerprint does not belong to the open recording.")
    for field, actual in (("duration", media.duration), ("width", media.width),
                          ("height", media.height), ("fps", media.fps)):
        if identity.get(field) != actual:
            raise ValueError("Source metadata changed while building this recipe.")
    sha = identity.get("sha256")
    if not isinstance(sha, str) or len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
        raise ValueError("Source SHA-256 is invalid.")

    offset = inspect_coverage(plan, media, offset)
    mismatch = reference_mismatch(plan, identity)
    if mismatch and not confirm_mismatch:
        raise ValueError("Different source (" + ", ".join(mismatch) +
                         "). Review the footage and explicitly approve rebinding.")
    rebound = deepcopy(plan)
    rebound["source"] = dict(identity)
    for element in rebound["timeline"]:
        if element["kind"] == "shot":
            for key in ("start", "end"):
                element[key] = round(element[key] + offset, 9)
                # Frame fields are cross-checks, not commands to bypass the new
                # source's frame rate. Recompute only if originally supplied.
                frame_key = key + "_frame"
                if frame_key in element:
                    element[frame_key] = round(element[key] * media.fps)
        elif element["kind"] == "freeze":
            element["source_time"] = round(element["source_time"] + offset, 9)
    if captions_in_bands:
        # The existing renderer enforces BOTH comedy band geometry and
        # three-line/mobile-readable text sizing for every caption.
        rebound["output"]["framing"] = "comedy_bands"
        for overlay in rebound.get("overlays", []):
            # Prevent emoji/GIF overlays from hiding gameplay.
            if overlay.get("zone", "canvas") == "canvas":
                overlay["zone"] = "bottom"
    suffix = ("\nROAST STUDIO: rebound to the video selected in Quick Edit. "
              "Source content differs from the recipe reference; verify "
              "every shot, freeze and caption before exporting." if mismatch else
              "\nROAST STUDIO: exact source reference verified.")
    if offset:
        suffix += f" Source timestamps shifted by {offset:+.3f}s."
    rebound["notes"] = (rebound.get("notes", "") + suffix)[-4000:]
    validate_pulse_plan(rebound, media)
    return rebound
