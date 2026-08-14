"""
PDF Auto-Grader for AutoCAD / Engineering Drawing submissions
Analyzes vector content in PDF files and scores them on CAD drawing standards.
Designed for BES 102 (Engineering Drawing / CAD) coursework.

Uses PyMuPDF (fitz) to extract:
  - Vector paths (lines, curves, rectangles)
  - Text labels and annotations
  - Fill colors, stroke properties
  - Shape detection via connected-line grouping

Grading rubric (100 pts):
  1. Drawing Completeness    — 30 pts
  2. Shape Accuracy          — 25 pts
  3. Labeling & Annotation   — 20 pts
  4. Layout & Organization   — 15 pts
  5. Technical Precision     — 10 pts
  Bonus: Extra Features      — +5 pts
"""

import re
import os
import math
from collections import defaultdict

try:
    import fitz  # PyMuPDF
    HAS_FITZ = True
except ImportError:
    HAS_FITZ = False


# ──────────────────────────────────────────────
# Shape name mapping (vertex count → polygon name)
# ──────────────────────────────────────────────
POLYGON_NAMES = {
    3: 'triangle',
    4: 'square',
    5: 'pentagon',
    6: 'hexagon',
    7: 'heptagon',
    8: 'octagon',
    9: 'nonagon',
    10: 'decagon',
    11: 'hendecagon',
    12: 'dodecagon',
}

# Common misspellings students make
TYPO_MAP = {
    'hextagon': 'hexagon',
    'heptagon': 'heptagon',
    'septagon': 'heptagon',
    'nonagon': 'nonagon',
    'nonagen': 'nonagon',
    'decargon': 'decagon',
    'hectagon': 'heptagon',
    'lexagon': 'hexagon',
    'heptagone': 'heptagon',
    'ocatgon': 'octagon',
    'octagn': 'octagon',
    'pendagon': 'pentagon',
    'pentagone': 'pentagon',
}


def _normalize_label(text):
    """Normalize a text label to lowercase, strip, and fix common typos."""
    t = text.strip().lower()
    return TYPO_MAP.get(t, t)


def _near(a, b, tol=3.0):
    """Check if two 2D points are within tolerance."""
    return abs(a[0] - b[0]) < tol and abs(a[1] - b[1]) < tol


def _group_shapes(lines, tol=3.0):
    """
    Group connected line segments into closed/open shapes using Union-Find.
    Returns a list of shape dicts with vertices, line count, bounding box, and closed flag.
    """
    if not lines:
        return []

    parent = list(range(len(lines)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        pi, pj = find(i), find(j)
        if pi != pj:
            parent[pi] = pj

    # Union lines sharing endpoints
    for i in range(len(lines)):
        for j in range(i + 1, len(lines)):
            for ei in range(2):
                for ej in range(2):
                    if _near(lines[i][ei], lines[j][ej], tol):
                        union(i, j)

    # Group by root
    groups = defaultdict(list)
    for i in range(len(lines)):
        groups[find(i)].append(lines[i])

    shapes = []
    for root, group_lines in groups.items():
        # Collect unique vertices
        verts = []
        seen = set()
        for p1, p2 in group_lines:
            for p in (p1, p2):
                key = (round(p[0], 1), round(p[1], 1))
                if key not in seen:
                    seen.add(key)
                    verts.append(p)

        # Bounding box
        xs = [p[0] for p in verts]
        ys = [p[1] for p in verts]
        bbox = (min(xs), min(ys), max(xs), max(ys))
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]

        # Check if closed polygon:
        # A closed polygon with N vertices has N edges (lines) connecting them.
        # An open polyline with N vertices has N-1 edges.
        # Also check if any vertex pair is close enough to form a closure point.
        is_closed = False
        if len(verts) >= 3:
            # Method 1: lines == vertices (each vertex connects to next, plus closing edge)
            if len(group_lines) >= len(verts):
                is_closed = True
            # Method 2: any two vertices within tolerance (gap closing)
            elif any(_near(verts[i], verts[j], tol * 2)
                     for i in range(len(verts)) for j in range(i + 1, len(verts))):
                is_closed = True

        shapes.append({
            'lines': len(group_lines),
            'vertices': verts,
            'vertex_count': len(verts),
            'bbox': bbox,
            'width': width,
            'height': height,
            'is_closed': is_closed,
            'shape_type': POLYGON_NAMES.get(len(verts), f'{len(verts)}-gon') if len(verts) >= 3 else 'line/unclosed',
        })

    return shapes


def _check_symmetry(shape):
    """Check if a shape is roughly symmetric (reflective symmetry on both axes)."""
    verts = shape['vertices']
    if len(verts) < 3:
        return False, 0.0

    cx = sum(v[0] for v in verts) / len(verts)
    cy = sum(v[1] for v in verts) / len(verts)

    # Horizontal symmetry: for each vertex, there should be one mirrored across the vertical axis
    tol = max(shape['width'], shape['height']) * 0.1
    h_sym = 0
    for v in verts:
        mirrored = (2 * cx - v[0], v[1])
        if any(_near(v2, mirrored, tol) for v2 in verts):
            h_sym += 1

    # Vertical symmetry
    v_sym = 0
    for v in verts:
        mirrored = (v[0], 2 * cy - v[1])
        if any(_near(v2, mirrored, tol) for v2 in verts):
            v_sym += 1

    h_ratio = h_sym / len(verts)
    v_ratio = v_sym / len(verts)
    score = (h_ratio + v_ratio) / 2

    return score >= 0.7, score


def _shapes_overlap(s1, s2):
    """Check if two shapes' bounding boxes significantly overlap."""
    ax0, ay0, ax1, ay1 = s1['bbox']
    bx0, by0, bx1, by1 = s2['bbox']

    overlap_x = max(0, min(ax1, bx1) - max(ax0, bx0))
    overlap_y = max(0, min(ay1, by1) - max(ay0, by0))
    overlap_area = overlap_x * overlap_y

    area1 = s1['width'] * s1['height']
    area2 = s2['width'] * s2['height']

    if area1 == 0 or area2 == 0:
        return False

    return overlap_area / min(area1, area2) > 0.3


def grade_pdf_file(filepath):
    """
    Analyze a PDF file and return a CAD drawing score breakdown.

    Returns dict:
        score, raw_score, max_score, bonus, breakdown (list of str), details (dict)
    """
    if not HAS_FITZ:
        return {
            'score': 0, 'raw_score': 0, 'max_score': 100, 'bonus': 0,
            'breakdown': ['ERROR: PyMuPDF (fitz) not installed'],
            'details': {}
        }

    doc = fitz.open(filepath)
    page_count = len(doc)

    # ───────────────────────────────────────────────
    # Extract vector and text content from all pages
    # ───────────────────────────────────────────────
    all_lines = []          # [(p1, p2), ...] in page coords
    all_curves = 0
    all_rects = 0
    all_fills = 0
    all_strokes = 0
    all_text_labels = []    # list of text strings
    total_images = 0
    page_widths = []
    page_heights = []

    for page in doc:
        pw, ph = page.rect.width, page.rect.height
        page_widths.append(pw)
        page_heights.append(ph)

        # Vector drawings
        drawings = page.get_drawings()
        page_fills = 0
        for d in drawings:
            for item in d['items']:
                if item[0] == 'l':  # line
                    p1, p2 = item[1], item[2]
                    all_lines.append(((p1.x, p1.y), (p2.x, p2.y)))
                elif item[0] == 'c':  # bezier curve
                    all_curves += 1
                elif item[0] == 're':  # rectangle
                    all_rects += 1
            if d.get('fill'):
                page_fills += 1
            if d.get('stroke'):
                all_strokes += 1
        all_fills += page_fills

        # Text labels
        text = page.get_text("text")
        labels = [l.strip() for l in text.split('\n') if l.strip()]
        all_text_labels.extend(labels)

        # Images
        total_images += len(page.get_images(full=True))

    doc.close()

    # ───────────────────────────────────────────────
    # Analyze shapes
    # ───────────────────────────────────────────────
    shapes = _group_shapes(all_lines)
    closed_shapes = [s for s in shapes if s['is_closed'] and s['vertex_count'] >= 3]
    open_shapes = [s for s in shapes if not s['is_closed']]

    # Normalize labels
    norm_labels = [_normalize_label(l) for l in all_text_labels]

    # Match labels to shapes
    matched_labels = 0
    unmatched_labels = []
    for label in norm_labels:
        # Check if any shape's type matches this label
        if any(label == s['shape_type'] for s in closed_shapes):
            matched_labels += 1
        elif label in POLYGON_NAMES.values():
            unmatched_labels.append(label)

    # Count overlaps
    overlap_count = 0
    for i in range(len(shapes)):
        for j in range(i + 1, len(shapes)):
            if _shapes_overlap(shapes[i], shapes[j]):
                overlap_count += 1

    # Check symmetry for each closed shape
    sym_scores = []
    for s in closed_shapes:
        _, score = _check_symmetry(s)
        sym_scores.append(score)

    # Overall drawing area usage
    if shapes and page_widths and page_heights:
        all_xs = [s['bbox'][0] for s in shapes] + [s['bbox'][2] for s in shapes]
        all_ys = [s['bbox'][1] for s in shapes] + [s['bbox'][3] for s in shapes]
        drawing_width = max(all_xs) - min(all_xs)
        drawing_height = max(all_ys) - min(all_ys)
        page_area = page_widths[0] * page_heights[0]
        drawing_area = drawing_width * drawing_height
        area_usage = drawing_area / page_area if page_area > 0 else 0
    else:
        area_usage = 0

    score = 0
    breakdown = []
    details = {
        'page_count': page_count,
        'line_count': len(all_lines),
        'curve_count': all_curves,
        'rect_count': all_rects,
        'fill_count': all_fills,
        'stroke_count': all_strokes,
        'image_count': total_images,
        'shape_count': len(shapes),
        'closed_shape_count': len(closed_shapes),
        'label_count': len(all_text_labels),
        'matched_labels': matched_labels,
        'overlap_count': overlap_count,
        'area_usage': round(area_usage, 2),
        'shapes': [s['shape_type'] for s in closed_shapes],
        'labels': all_text_labels,
    }

    # ───────────────────────────────────────────────
    # SECTION 1: Drawing Completeness (30 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    # 1a. Number of shapes detected (15 pts)
    shape_count = len(closed_shapes)
    if shape_count >= 8:
        section_score += 15
    elif shape_count >= 6:
        section_score += 12
        breakdown.append(f"- Only {shape_count} shapes drawn, expected 8+ (1a: -3)")
    elif shape_count >= 4:
        section_score += 8
        breakdown.append(f"- Partial submission: {shape_count} shapes (1a: -7)")
    elif shape_count >= 1:
        section_score += 4
        breakdown.append(f"- Incomplete: only {shape_count} shape(s) (1a: -11)")
    else:
        if len(all_lines) > 0:
            section_score += 2
            breakdown.append("- Lines detected but no closed shapes (1a: -13)")
        else:
            breakdown.append("- No shapes detected (1a: -15)")

    # 1b. Variety of shapes — different polygon types (10 pts)
    shape_types = set(s['shape_type'] for s in closed_shapes)
    if shape_count >= 8:
        section_score += 10
    elif len(shape_types) >= 6:
        section_score += 8
        breakdown.append(f"- Good variety: {len(shape_types)} different shapes (1b: -2)")
    elif len(shape_types) >= 4:
        section_score += 5
        breakdown.append(f"- Limited variety: {len(shape_types)} shape types (1b: -5)")
    elif len(shape_types) >= 1:
        section_score += 2
        breakdown.append(f"- Very limited: {len(shape_types)} shape type(s) (1b: -8)")
    else:
        breakdown.append("- No identifiable shape types (1b: -10)")

    # 1c. Line count / detail (5 pts)
    if len(all_lines) >= 52:  # triangle(3)+square(4)+pentagon(5)+...+decagon(10) = 52
        section_score += 5
    elif len(all_lines) >= 30:
        section_score += 3
        breakdown.append(f"- {len(all_lines)} lines drawn, expected 52+ for 8 polygons (1c: -2)")
    elif len(all_lines) >= 10:
        section_score += 1
        breakdown.append(f"- Only {len(all_lines)} lines (1c: -4)")
    else:
        breakdown.append(f"- Very few lines: {len(all_lines)} (1c: -5)")

    score += section_score
    breakdown.insert(0, f"[1] Drawing Completeness: {section_score}/30")
    details['section1_score'] = section_score

    # ───────────────────────────────────────────────
    # SECTION 2: Shape Accuracy (25 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    # 2a. Closed shapes ratio (10 pts)
    if shapes:
        close_ratio = len(closed_shapes) / len(shapes)
        if close_ratio >= 0.9:
            section_score += 10
        elif close_ratio >= 0.7:
            section_score += 7
            breakdown.append(f"- Some unclosed shapes: {len(open_shapes)} open (2a: -3)")
        elif close_ratio >= 0.5:
            section_score += 4
            breakdown.append(f"- Many unclosed shapes: {len(open_shapes)} open (2a: -6)")
        else:
            section_score += 1
            breakdown.append(f"- Most shapes are open/unclosed (2a: -9)")
    else:
        breakdown.append("- No shapes to evaluate (2a: -10)")

    # 2b. Correct vertex counts for polygon types (10 pts)
    correct_verts = 0
    for s in closed_shapes:
        if s['vertex_count'] in POLYGON_NAMES:
            correct_verts += 1
    if len(closed_shapes) > 0:
        vert_ratio = correct_verts / len(closed_shapes)
        if vert_ratio >= 0.9:
            section_score += 10
        elif vert_ratio >= 0.7:
            section_score += 7
            breakdown.append(f"- Some shapes have extra/missing vertices (2b: -3)")
        elif vert_ratio >= 0.5:
            section_score += 4
            breakdown.append(f"- Many shapes have incorrect vertex counts (2b: -6)")
        else:
            section_score += 1
            breakdown.append(f"- Most shapes have wrong vertex counts (2b: -9)")
    else:
        breakdown.append("- Cannot verify vertex counts (2b: -10)")

    # 2c. Symmetry (5 pts)
    if sym_scores:
        avg_sym = sum(sym_scores) / len(sym_scores)
        if avg_sym >= 0.7:
            section_score += 5
        elif avg_sym >= 0.5:
            section_score += 3
            breakdown.append(f"- Some shapes lack symmetry (2c: -2)")
        else:
            section_score += 1
            breakdown.append(f"- Poor symmetry: avg {avg_sym:.1%} (2c: -4)")
    else:
        section_score += 2
        breakdown.append("- No closed shapes to check symmetry (2c: -3)")

    score += section_score
    breakdown.insert(1, f"[2] Shape Accuracy: {section_score}/25")
    details['section2_score'] = section_score

    # ───────────────────────────────────────────────
    # SECTION 3: Labeling & Annotation (20 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    # 3a. Labels present (10 pts)
    label_count = len(all_text_labels)
    if label_count >= 8:
        section_score += 10
    elif label_count >= 6:
        section_score += 7
        breakdown.append(f"- Only {label_count} labels, expected 8+ (3a: -3)")
    elif label_count >= 3:
        section_score += 4
        breakdown.append(f"- Partial labeling: {label_count} labels (3a: -6)")
    elif label_count >= 1:
        section_score += 2
        breakdown.append(f"- Minimal labeling: {label_count} label(s) (3a: -8)")
    else:
        if len(all_lines) > 0:
            section_score += 0
            breakdown.append("- No text labels found on drawing (3a: -10)")
        else:
            # No drawing at all - scanned/image PDF
            breakdown.append("- No text or drawing content detected (3a: -10)")

    # 3b. Labels match shapes (7 pts)
    if closed_shapes and label_count > 0:
        match_ratio = matched_labels / max(label_count, 1)
        if match_ratio >= 0.8:
            section_score += 7
        elif match_ratio >= 0.5:
            section_score += 4
            breakdown.append(f"- Some labels don't match shapes: {matched_labels}/{label_count} (3b: -3)")
        else:
            section_score += 1
            breakdown.append(f"- Most labels don't match drawn shapes: {matched_labels}/{label_count} (3b: -6)")
    elif label_count > 0 and not closed_shapes:
        # Has labels but no detected shapes (maybe shapes are there but hard to group)
        section_score += 3
        breakdown.append("- Labels present but shapes hard to detect (3b: -4)")
    else:
        breakdown.append("- Cannot verify label-shape matching (3b: -7)")

    # 3c. Label spelling (3 pts)
    if all_text_labels:
        misspelled = []
        for label in all_text_labels:
            norm = _normalize_label(label)
            if norm in POLYGON_NAMES.values():
                continue
            # Check if it's close to a known polygon name
            closest = min(POLYGON_NAMES.values(), key=lambda n: _levenshtein(norm, n))
            dist = _levenshtein(norm, closest)
            if dist > 0 and dist <= 2 and norm not in ('', ):
                misspelled.append((label.strip(), closest))
        if not misspelled:
            section_score += 3
        elif len(misspelled) <= 2:
            section_score += 2
            breakdown.append(f"- Minor spelling: {', '.join(m[0] for m in misspelled)} (3c: -1)")
        else:
            section_score += 1
            breakdown.append(f"- Several misspelled labels: {', '.join(m[0] for m in misspelled[:4])} (3c: -2)")
    else:
        breakdown.append("- No labels to check spelling (3c: -3)")

    score += section_score
    breakdown.insert(2, f"[3] Labeling & Annotation: {section_score}/20")
    details['section3_score'] = section_score

    # ───────────────────────────────────────────────
    # SECTION 4: Layout & Organization (15 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    # 4a. Shapes don't overlap (8 pts)
    if len(shapes) >= 2:
        if overlap_count == 0:
            section_score += 8
        elif overlap_count <= 2:
            section_score += 5
            breakdown.append(f"- {overlap_count} overlapping shape(s) (4a: -3)")
        else:
            section_score += 2
            breakdown.append(f"- {overlap_count} overlapping shapes, poor spacing (4a: -6)")
    else:
        section_score += 4
        breakdown.append("- Too few shapes to evaluate layout (4a: -4)")

    # 4b. Good use of page space (4 pts)
    if 0.3 <= area_usage <= 0.85:
        section_score += 4
    elif area_usage > 0.85:
        section_score += 2
        breakdown.append(f"- Drawing fills {area_usage:.0%} of page, too crowded (4b: -2)")
    elif area_usage >= 0.1:
        section_score += 2
        breakdown.append(f"- Drawing uses only {area_usage:.0%} of page (4b: -2)")
    else:
        section_score += 1
        breakdown.append(f"- Very poor space usage: {area_usage:.0%} (4b: -3)")

    # 4c. Consistent spacing (3 pts) — check if shapes are evenly distributed
    if len(closed_shapes) >= 3:
        centers = []
        for s in closed_shapes:
            cx = (s['bbox'][0] + s['bbox'][2]) / 2
            cy = (s['bbox'][1] + s['bbox'][3]) / 2
            centers.append((cx, cy))
        # Compute distances between consecutive shapes (sorted by position)
        centers.sort()
        dists = []
        for i in range(1, len(centers)):
            dx = centers[i][0] - centers[i-1][0]
            dy = centers[i][1] - centers[i-1][1]
            dists.append(math.sqrt(dx*dx + dy*dy))
        if dists:
            avg_d = sum(dists) / len(dists)
            variance = sum((d - avg_d)**2 for d in dists) / len(dists)
            cv = math.sqrt(variance) / avg_d if avg_d > 0 else 1
            if cv <= 0.3:
                section_score += 3
            elif cv <= 0.6:
                section_score += 2
                breakdown.append(f"- Inconsistent spacing between shapes (4c: -1)")
            else:
                section_score += 1
                breakdown.append(f"- Irregular spacing: CV={cv:.2f} (4c: -2)")
        else:
            section_score += 1
    else:
        section_score += 1
        breakdown.append("- Too few shapes for spacing analysis (4c: -2)")

    score += section_score
    breakdown.insert(3, f"[4] Layout & Organization: {section_score}/15")
    details['section4_score'] = section_score

    # ───────────────────────────────────────────────
    # SECTION 5: Technical Precision (10 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    # 5a. Line quality — all shapes should use straight lines for polygons (5 pts)
    if len(all_lines) > 0 and all_curves == 0:
        section_score += 5
    elif all_curves > 0 and len(all_lines) > all_curves * 2:
        section_score += 3
        breakdown.append(f"- {all_curves} curve(s) detected in polygon drawing (5a: -2)")
    elif all_curves > 0:
        section_score += 1
        breakdown.append(f"- Excessive curves: {all_curves} for polygon exercise (5a: -4)")
    else:
        section_score += 2
        breakdown.append("- No lines detected (5a: -3)")

    # 5b. Shape consistency — similar polygon types should have similar sizes (3 pts)
    if len(closed_shapes) >= 4:
        sizes = [s['width'] * s['height'] for s in closed_shapes if s['width'] > 0 and s['height'] > 0]
        if sizes:
            avg_size = sum(sizes) / len(sizes)
            size_var = sum((s - avg_size)**2 for s in sizes) / len(sizes)
            size_cv = math.sqrt(size_var) / avg_size if avg_size > 0 else 1
            if size_cv <= 0.5:
                section_score += 3
            elif size_cv <= 1.0:
                section_score += 2
                breakdown.append(f"- Inconsistent shape sizes (5b: -1)")
            else:
                section_score += 1
                breakdown.append(f"- Very inconsistent shape sizes (5b: -2)")
    else:
        section_score += 1
        breakdown.append("- Too few shapes for size analysis (5b: -2)")

    # 5c. Page orientation (2 pts) — standard A4 or Letter
    if page_widths and page_heights:
        w, h = page_widths[0], page_heights[0]
        is_a4 = abs(w - 595) < 10 or abs(h - 595) < 10
        is_letter = abs(w - 612) < 10 or abs(h - 612) < 10
        is_a3 = abs(w - 842) < 10 or abs(h - 842) < 10
        if is_a4 or is_letter or is_a3:
            section_score += 2
        else:
            section_score += 1
            breakdown.append(f"- Non-standard page size: {w:.0f}x{h:.0f}pt (5c: -1)")
    else:
        breakdown.append("- Cannot determine page size (5c: -2)")

    score += section_score
    breakdown.insert(4, f"[5] Technical Precision: {section_score}/10")
    details['section5_score'] = section_score

    # ───────────────────────────────────────────────
    # BONUS: Extra Features (+5 pts)
    # ───────────────────────────────────────────────
    bonus = 0

    # Extra shapes beyond the standard 8
    if len(closed_shapes) > 8:
        extra = len(closed_shapes) - 8
        bonus += min(extra, 2)
        breakdown.append(f"\u2B50 BONUS: {extra} extra shape(s) beyond standard 8 (+{min(extra, 2)})")

    # Fills / hatching
    if all_fills > 0:
        bonus += 1
        breakdown.append(f"\u2B50 BONUS: Fill/hatch applied to shapes (+1)")

    # Dimensions or extra annotations
    has_dim = any(re.search(r'\b(dim|dimension|scale|unit|mm|cm|angle)\b', l, re.IGNORECASE)
                  for l in all_text_labels)
    if has_dim:
        bonus += 1
        breakdown.append("\u2B50 BONUS: Dimension/annotation text detected (+1)")

    # Multiple pages
    if page_count >= 2:
        bonus += 1
        breakdown.append(f"\u2B50 BONUS: Multi-page submission ({page_count} pages) (+1)")

    bonus = min(bonus, 5)

    # ───────────────────────────────────────────────
    # FINAL SCORE
    # ───────────────────────────────────────────────
    final_score = min(score + bonus, 110)
    grade_pct = min(final_score, 100)

    details['bonus'] = bonus
    details['avg_symmetry'] = round(sum(sym_scores) / len(sym_scores), 2) if sym_scores else 0

    return {
        'score': grade_pct,
        'raw_score': score,
        'max_score': 100,
        'bonus': bonus,
        'breakdown': breakdown,
        'details': details,
    }


def _levenshtein(s1, s2):
    """Compute Levenshtein distance between two strings."""
    if len(s1) < len(s2):
        return _levenshtein(s2, s1)
    if len(s2) == 0:
        return len(s1)
    prev_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        curr_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = prev_row[j + 1] + 1
            deletions = curr_row[j] + 1
            substitutions = prev_row[j] + (c1 != c2)
            curr_row.append(min(insertions, deletions, substitutions))
        prev_row = curr_row
    return prev_row[-1]


def format_grade_report(result):
    """Format the PDF grading result as a readable multi-line string."""
    lines = []
    d = result['details']
    lines.append(f"AUTOCAD PDF GRADE: {result['score']}/100" +
                 (f" (incl. +{result['bonus']} bonus)" if result['bonus'] else ""))
    lines.append("-" * 50)
    for b in result['breakdown']:
        lines.append(b)
    lines.append("-" * 50)
    lines.append(f"Pages: {d.get('page_count', 0)} | "
                 f"Lines: {d.get('line_count', 0)} | "
                 f"Curves: {d.get('curve_count', 0)} | "
                 f"Fills: {d.get('fill_count', 0)}")
    lines.append(f"Shapes: {d.get('closed_shape_count', 0)} closed / "
                 f"{d.get('shape_count', 0)} total | "
                 f"Labels: {d.get('label_count', 0)} ({d.get('matched_labels', 0)} matched)")
    lines.append(f"Overlaps: {d.get('overlap_count', 0)} | "
                 f"Area usage: {d.get('area_usage', 0):.0%} | "
                 f"Symmetry: {d.get('avg_symmetry', 0):.0%}")
    if d.get('shapes'):
        lines.append(f"Shapes drawn: {', '.join(d['shapes'])}")
    if d.get('labels'):
        lines.append(f"Labels: {', '.join(d['labels'][:10])}")
    lines.append("")
    lines.append("NOTE: Auto-graded from PDF vector analysis. Manual review recommended.")
    return '\n'.join(lines)