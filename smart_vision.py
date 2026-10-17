import base64
import io
import re
from typing import List, Optional, Tuple

import cv2
import numpy as np
from PIL import Image, ImageGrab

try:
    import winocr
    HAS_WINOCR = True
except ImportError:
    HAS_WINOCR = False


def grab_full_screen_pil(screen_bounds: dict) -> Image.Image:
    """Capture the full virtual screen as a PIL RGB Image."""
    ox = screen_bounds.get("origin_x", 0)
    oy = screen_bounds.get("origin_y", 0)
    w = screen_bounds.get("width", 1920)
    h = screen_bounds.get("height", 1080)
    bbox = (ox, oy, ox + w, oy + h)
    try:
        return ImageGrab.grab(bbox=bbox, all_screens=True).convert("RGB")
    except Exception:
        return ImageGrab.grab().convert("RGB")


def crop_around_point(
    img: Image.Image, cx: int, cy: int, half_w: int = 120, half_h: int = 26, origin_x: int = 0, origin_y: int = 0
) -> Tuple[Image.Image, Tuple[int, int, int, int]]:
    """Crop a rectangular patch centered at screen coordinates (cx, cy)."""
    rel_x = cx - origin_x
    rel_y = cy - origin_y
    w, h = img.size
    left = max(0, rel_x - half_w)
    top = max(0, rel_y - half_h)
    right = min(w, rel_x + half_w)
    bottom = min(h, rel_y + half_h)
    return img.crop((left, top, right, bottom)), (left, top, right, bottom)


def pil_to_base64(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def base64_to_pil(b64_str: str) -> Optional[Image.Image]:
    if not b64_str:
        return None
    try:
        raw = base64.b64decode(b64_str)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        return None


def has_sufficient_visual_detail(img: Image.Image, min_std: float = 16.0) -> bool:
    """Return True only if the image patch has real visual edges/detail (not a blank solid box)."""
    try:
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        return float(np.std(gray)) >= min_std
    except Exception:
        return False


def extract_anchor_info_at_cursor(
    screen_img: Image.Image,
    cx: int,
    cy: int,
    domain_hint: str = "nariwal.shop",
    secondary_email_hint: str = "mobile.j3pro@gmail.com",
    custom_target_hint: str = "",
    allow_any_text: bool = False,
    origin_x: int = 0,
    origin_y: int = 0,
) -> dict:
    """
    Inspect the screen around (cx, cy) using Windows Native OCR + Visual Template Crop.
    - When `allow_any_text=False` (normal mouse clicks), ONLY locks onto dynamic list targets
      (`@nariwal.shop`, `mobile.j3pro@gmail.com`, `Add new contact info`, or `custom_target_hint`)
      so static buttons are never hijacked by partial OCR words or blank templates.
    - When `allow_any_text=True` (explicit `[F3]` Smart Target Click), locks onto whatever
      button label or visual element is under the cursor.
    """
    result = {
        "anchor_text": "",
        "raw_text": "",
        "template_b64": "",
        "is_dynamic_domain_target": False,
    }

    # 1. Capture visual template crop (136x38 px around cursor)
    tmpl_patch, _ = crop_around_point(
        screen_img, cx, cy, half_w=68, half_h=19, origin_x=origin_x, origin_y=origin_y
    )

    # 2. Capture wider OCR patch (340x60 px around cursor) to read full email/button label
    ocr_patch, (o_left, o_top, _, _) = crop_around_point(
        screen_img, cx, cy, half_w=170, half_h=30, origin_x=origin_x, origin_y=origin_y
    )

    clean_domain = domain_hint.strip().lstrip("@").lower() or "nariwal.shop"
    clean_sec = secondary_email_hint.strip().lower() or "mobile.j3pro@gmail.com"
    clean_custom = custom_target_hint.strip().lower()

    if HAS_WINOCR:
        try:
            ow, oh = ocr_patch.size
            upscaled = ocr_patch.resize((ow * 2, oh * 2), Image.Resampling.BICUBIC)
            ocr_res = winocr.recognize_pil_sync(upscaled, "en")
            lines = ocr_res.get("lines", [])

            rel_cy = (cy - origin_y - o_top) * 2

            best_line_text = ""
            best_dist = 999999.0

            for line in lines:
                ltxt = line.get("text", "").strip()
                if not ltxt:
                    continue
                words = line.get("words", [])
                if not words:
                    continue
                ly1 = min(w["bounding_rect"]["y"] for w in words)
                ly2 = max(w["bounding_rect"]["y"] + w["bounding_rect"]["height"] for w in words)
                mid_y = (ly1 + ly2) / 2.0
                dist_y = abs(mid_y - rel_cy)
                if dist_y < best_dist:
                    best_dist = dist_y
                    best_line_text = ltxt

            if best_line_text and best_dist <= 38.0:
                result["raw_text"] = best_line_text
                low_txt = best_line_text.lower()
                low_nospace = re.sub(r"\s+", "", low_txt)

                if clean_domain in low_txt or clean_domain in low_nospace:
                    # Generalize any random email like 'muse15@nariwal.shop' -> '@nariwal.shop'
                    result["anchor_text"] = f"@{clean_domain}"
                    result["is_dynamic_domain_target"] = True
                elif clean_sec in low_txt or clean_sec in low_nospace or "j3pro@" in low_nospace:
                    result["anchor_text"] = clean_sec
                elif "add new contact" in low_txt or "new contact info" in low_txt:
                    result["anchor_text"] = "Add new contact info"
                elif clean_custom and clean_custom in low_txt:
                    result["anchor_text"] = custom_target_hint.strip()
                elif allow_any_text:
                    # Strip leading icon/punctuation noise (like ':ontact info' or 'O Login')
                    cleaned = re.sub(r"^[^a-zA-Z0-9@]+", "", best_line_text).strip()
                    cleaned = re.sub(r"^[A-Z0-9]\s+(?=[A-Z][a-z])", "", cleaned).strip()
                    if len(cleaned) >= 4:
                        result["anchor_text"] = cleaned
        except Exception:
            pass

    # Only save visual template when explicitly requested ([F3]) and the patch has real visual detail
    if allow_any_text and not result["is_dynamic_domain_target"] and has_sufficient_visual_detail(tmpl_patch):
        result["template_b64"] = pil_to_base64(tmpl_patch)

    return result


def find_text_on_screen_ocr(
    screen_img: Image.Image,
    target_text: str,
    expected_x: int,
    expected_y: int,
    origin_x: int = 0,
    origin_y: int = 0,
    search_region: Optional[Tuple[int, int, int, int]] = None,
    upscale_2x: bool = True,
) -> Optional[Tuple[int, int, str]]:
    """
    Find `target_text` on `screen_img` using Windows Native OCR (`winocr`).
    Uses 2x bicubic upscaling on regional searches so small 12px UI fonts are read with 100% accuracy.
    Returns `(screen_x, screen_y, matched_line_text)` or None.
    """
    if not HAS_WINOCR or not target_text or not target_text.strip():
        return None

    query = target_text.strip().lower()
    query_nospace = re.sub(r"\s+", "", query)

    if search_region:
        rx1, ry1, rx2, ry2 = search_region
        sub_img = screen_img.crop((rx1, ry1, rx2, ry2))
        off_x, off_y = origin_x + rx1, origin_y + ry1
    else:
        sub_img = screen_img
        off_x, off_y = origin_x, origin_y

    scale = 1
    if upscale_2x and (sub_img.size[0] * sub_img.size[1] <= 950000):
        scale = 2
        sub_img = sub_img.resize((sub_img.size[0] * 2, sub_img.size[1] * 2), Image.Resampling.BICUBIC)

    try:
        ocr_res = winocr.recognize_pil_sync(sub_img, "en")
    except Exception:
        return None

    candidates: List[Tuple[float, int, int, str]] = []

    for line in ocr_res.get("lines", []):
        line_text = line.get("text", "").strip()
        if not line_text:
            continue
        low_line = line_text.lower()
        low_line_nospace = re.sub(r"\s+", "", low_line)

        matched = False
        if query in low_line or query_nospace in low_line_nospace:
            matched = True
        else:
            q_tokens = [t for t in re.split(r"\s+", query) if len(t) >= 3]
            if len(q_tokens) >= 2 and all(t in low_line for t in q_tokens):
                matched = True

        if not matched:
            continue

        words = line.get("words", [])
        if not words:
            continue

        matching_words = [
            w for w in words
            if query in w.get("text", "").lower() or query_nospace in w.get("text", "").lower()
        ]
        target_words = matching_words if matching_words else words

        x1 = min(w["bounding_rect"]["x"] for w in target_words) / scale
        y1 = min(w["bounding_rect"]["y"] for w in target_words) / scale
        x2 = max(w["bounding_rect"]["x"] + w["bounding_rect"]["width"] for w in target_words) / scale
        y2 = max(w["bounding_rect"]["y"] + w["bounding_rect"]["height"] for w in target_words) / scale

        center_x = int(round(off_x + (x1 + x2) / 2.0))
        center_y = int(round(off_y + (y1 + y2) / 2.0))

        # Weight horizontal distance more heavily so vertical list shifts in the same column win
        dist = (((center_x - expected_x) * 1.5) ** 2 + (center_y - expected_y) ** 2) ** 0.5
        candidates.append((dist, center_x, center_y, line_text))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0])
    _, best_x, best_y, best_txt = candidates[0]
    return best_x, best_y, best_txt


def find_template_on_screen_cv2(
    screen_img: Image.Image,
    template_b64: str,
    expected_x: int,
    expected_y: int,
    origin_x: int = 0,
    origin_y: int = 0,
    threshold: float = 0.88,
) -> Optional[Tuple[int, int, float]]:
    """
    Find a visual reference image patch (`template_b64`) on `screen_img`
    using OpenCV `cv2.matchTemplate` (`TM_CCOEFF_NORMED`).
    Ignores low-detail/blank templates to prevent false-positive jumps.
    """
    tmpl_pil = base64_to_pil(template_b64)
    if tmpl_pil is None or not has_sufficient_visual_detail(tmpl_pil, min_std=16.0):
        return None

    try:
        screen_np = cv2.cvtColor(np.array(screen_img), cv2.COLOR_RGB2GRAY)
        tmpl_np = cv2.cvtColor(np.array(tmpl_pil), cv2.COLOR_RGB2GRAY)

        th, tw = tmpl_np.shape[:2]
        sh, sw = screen_np.shape[:2]
        if th >= sh or tw >= sw or th < 8 or tw < 8:
            return None

        res = cv2.matchTemplate(screen_np, tmpl_np, cv2.TM_CCOEFF_NORMED)
        loc = np.where(res >= threshold)
        pts = list(zip(*loc[::-1]))
        if not pts:
            _, max_val, _, max_loc = cv2.minMaxLoc(res)
            if max_val >= threshold:
                cx = int(origin_x + max_loc[0] + tw // 2)
                cy = int(origin_y + max_loc[1] + th // 2)
                return cx, cy, float(max_val)
            return None

        best_pt = None
        best_score = -1e9
        for px, py in pts[::2]:
            conf = float(res[py, px])
            cx = int(origin_x + px + tw // 2)
            cy = int(origin_y + py + th // 2)
            dist = ((cx - expected_x) ** 2 + (cy - expected_y) ** 2) ** 0.5
            score = conf - (dist * 0.00025)
            if score > best_score:
                best_score = score
                best_pt = (cx, cy, conf)

        return best_pt
    except Exception:
        return None


def smart_locate_target_on_screen(
    screen_bounds: dict,
    expected_x: int,
    expected_y: int,
    anchor_text: str = "",
    template_b64: str = "",
    current_test_email: Optional[str] = None,
    domain_hint: str = "nariwal.shop",
    vertical_list_mode: bool = False,
) -> Optional[Tuple[int, int, str]]:
    """
    Master Smart Target Locator:
    1. Searches a 2x-upscaled vertical column strip around `(expected_x, expected_y)` (±260px X, ±340px Y)
       for ultra-accurate detection of moved list rows (`@nariwal.shop`, `mobile.j3pro@gmail.com`, `Add new contact info`).
    2. If `vertical_list_mode=True`, keeps the horizontal click position near `expected_x` and only shifts Y
       to the moved row so it never clicks off-target horizontally.
    """
    screen_img = grab_full_screen_pil(screen_bounds)
    ox = screen_bounds.get("origin_x", 0)
    oy = screen_bounds.get("origin_y", 0)
    sw, sh = screen_img.size

    queries: List[str] = []
    if anchor_text:
        clean_dom = domain_hint.strip().lstrip("@").lower() or "nariwal.shop"
        if anchor_text.strip().lower() in ("{current_email}", f"@{clean_dom}", clean_dom):
            if current_test_email and clean_dom in current_test_email.lower():
                queries.append(current_test_email)
            queries.append(f"@{clean_dom}")
        else:
            queries.append(anchor_text.strip())

    rel_ex = expected_x - ox
    rel_ey = expected_y - oy
    band_region = (
        max(0, rel_ex - 260),
        max(0, rel_ey - 340),
        min(sw, rel_ex + 260),
        min(sh, rel_ey + 340),
    )

    for q in queries:
        found = find_text_on_screen_ocr(
            screen_img,
            q,
            expected_x,
            expected_y,
            origin_x=ox,
            origin_y=oy,
            search_region=band_region,
            upscale_2x=True,
        )
        if not found and not vertical_list_mode:
            found = find_text_on_screen_ocr(
                screen_img,
                q,
                expected_x,
                expected_y,
                origin_x=ox,
                origin_y=oy,
                search_region=None,
                upscale_2x=False,
            )
        if found:
            fx, fy, matched_txt = found
            if vertical_list_mode:
                # In vertical list mode, keep user's exact horizontal X click alignment if within the same column
                if abs(fx - expected_x) <= 180:
                    fx = expected_x
            return fx, fy, f"OCR Text '{matched_txt}'"

    if template_b64 and not vertical_list_mode:
        t_found = find_template_on_screen_cv2(
            screen_img, template_b64, expected_x, expected_y, origin_x=ox, origin_y=oy, threshold=0.88
        )
        if t_found:
            fx, fy, conf = t_found
            return fx, fy, f"Visual Match ({conf*100:.0f}%)"

    return None
