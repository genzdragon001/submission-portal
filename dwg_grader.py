"""
DWG (AutoCAD) File Auto-Grader
Analyzes .dwg files and scores them on CAD drawing quality standards.
Designed for BES 102 (Engineering Drawing / CAD) coursework.

Since DWG 2018+ (AC1032) is a proprietary binary format with no native
Python parser, this grader uses heuristic analysis:
  - File integrity (magic bytes, version, corruption checks)
  - Embedded preview extraction (PNG thumbnail quality/size)
  - File complexity (size-based heuristics, section count)
  - Metadata extraction (strings, object references)
  - Structural analysis (sentinel patterns, section markers)

Grading rubric (100 pts):
  1. File Integrity & Format       — 15 pts
  2. Drawing Complexity & Content  — 30 pts
  3. Presentation & Polishing      — 20 pts
  4. Layers & Organization         — 15 pts
  5. Dimensions & Annotation       — 10 pts
  6. Compliance & Best Practices   — 10 pts
  Bonus: Advanced Features          — +5 pts
"""

import re
import os
import struct
import io


# ──────────────────────────────────────────────
# DWG version table (AutoCAD release years)
# ──────────────────────────────────────────────
DWG_VERSIONS = {
    'AC1032': {'name': 'AutoCAD 2018-2024', 'year': 2018, 'modern': True},
    'AC1027': {'name': 'AutoCAD 2013-2017', 'year': 2013, 'modern': True},
    'AC1024': {'name': 'AutoCAD 2010-2012', 'year': 2010, 'modern': False},
    'AC1021': {'name': 'AutoCAD 2007-2009', 'year': 2007, 'modern': False},
    'AC1018': {'name': 'AutoCAD 2004-2006', 'year': 2004, 'modern': False},
    'AC1015': {'name': 'AutoCAD 2000-2002', 'year': 2000, 'modern': False},
    'AC1014': {'name': 'AutoCAD R14', 'year': 1997, 'modern': False},
    'AC1012': {'name': 'AutoCAD R13', 'year': 1994, 'modern': False},
}

# Known DWG section/page markers (for AC1032 format)
SECTION_MARKERS = [
    b'AcDb:Header',
    b'AcDb:Classes',
    b'AcDb:SummaryInfo',
    b'AcDb:Preview',
    b'AcDb:AppInfo',
    b'AcDb:FileDepList',
    b'AcDb:RevHistory',
    b'AcDb:Security',
    b'AcDb:AcDbObjects',
    b'AcDb:ObjFreeSpace',
    b'AcDb:Template',
    b'AcDb:Handles',
    b'AcDb:AcDsPrototype',
]

# Entity class names (search in binary)
ENTITY_CLASSES = [
    (b'LINE', 'Lines'),
    (b'LWPOLYLINE', 'Lightweight Polylines'),
    (b'CIRCLE', 'Circles'),
    (b'ARC', 'Arcs'),
    (b'ELLIPSE', 'Ellipses'),
    (b'SPLINE', 'Splines'),
    (b'MTEXT', 'Multi-line Text'),
    (b'TEXT', 'Single-line Text'),
    (b'INSERT', 'Block Inserts'),
    (b'HATCH', 'Hatches'),
    (b'DIMENSION', 'Dimensions'),
    (b'LEADER', 'Leaders'),
    (b'3DFACE', '3D Faces'),
    (b'SOLID', 'Solids'),
    (b'3DSOLID', '3D Solids'),
    (b'POLYLINE', 'Polylines'),
    (b'POINT', 'Points'),
    (b'RAY', 'Rays'),
    (b'XLINE', 'Construction Lines'),
    (b'MLINE', 'Multi-lines'),
    (b'REGION', 'Regions'),
    (b'SURFACE', 'Surfaces'),
    (b'MESH', 'Meshes'),
    (b'TABLE', 'Tables'),
    (b'VIEWPORT', 'Viewports'),
    (b'IMAGE', 'Raster Images'),
]


def _extract_preview(data):
    """Extract embedded PNG preview from DWG file."""
    png_start = data.find(b'\x89PNG\r\n\x1a\n')
    if png_start >= 0:
        png_end = data.find(b'IEND\xaeB`\x82', png_start)
        if png_end >= 0:
            png_end += 8
            return png_start, png_end, data[png_start:png_end]
    return None, None, None


def _extract_bmp_preview(data):
    """Extract embedded BMP preview from DWG file."""
    # BMP starts with 'BM' + size
    for i in range(len(data) - 4):
        if data[i:i+2] == b'BM':
            try:
                bmp_size = struct.unpack('<I', data[i+2:i+6])[0]
                if 1000 < bmp_size < 10 * 1024 * 1024:  # reasonable BMP size
                    if i + bmp_size <= len(data):
                        return i, i + bmp_size, data[i:i+bmp_size]
            except Exception:
                pass
    return None, None, None


def _count_sentinel_patterns(data):
    """Count DWG sentinel structures (indicator of drawing complexity)."""
    # DWG 2018 uses sentinel-based page format
    # Each sentinel is ~256 bytes with a F-type identifier
    sentinel_count = 0
    offset = 0
    while offset < len(data) - 16:
        chunk = data[offset:offset+16]
        # Check for typical sentinel pattern: 8 bytes F-type, 8 bytes
        patterns = [
            b'\x46',  # F-type sentinels start with 0x46
        ]
        # More robust: count CRC-like patterns at 256-byte boundaries
        offset += 256
    # Alternative heuristic: count section-like structures
    section_hits = 0
    for marker in SECTION_MARKERS:
        section_hits += data.count(marker)
    return section_hits


def _find_ascii_strings(data, min_len=4):
    """Extract printable ASCII strings from binary data."""
    strings = []
    cur = []
    for b in data:
        if 32 <= b < 127:
            cur.append(chr(b))
        else:
            if len(cur) >= min_len:
                s = ''.join(cur)
                strings.append(s)
            cur = []
    if len(cur) >= min_len:
        strings.append(''.join(cur))
    return strings


def _classify_drawing_type(filename, data):
    """Heuristically determine if this is a 2D or 3D drawing."""
    name_lower = filename.lower()

    # Check filename clues (case-insensitive)
    is_2d = any(kw in name_lower for kw in ['2d', 'floor_plan', 'floorplan', 'elevation', 'section',
                                              'plan', 'layout_plan'])
    is_3d = any(kw in name_lower for kw in ['3d', 'modeling', 'rendering', 'render', 'solid', 'mesh'])

    # Check binary content for 3D-specific markers
    # "3DSolid_ASM_" appears in all DWGs as internal reference — ignore it
    # Look for actual 3D entity class usage
    has_3d_entity = bool(re.search(
        rb'3DSOLID(?!_ASM_)|ACDB3DSOLID|AcDbSurface(?!_ASM)|'
        rb'AcDbSubDMesh|AcDbPolyFaceMesh|AcDbMesh(?!Style)',
        data, re.I))

    if has_3d_entity:
        return '3D'
    elif is_2d and not is_3d:
        return '2D'
    elif is_3d and not is_2d:
        return '3D'
    elif is_3d:
        return '3D'
    elif is_2d:
        return '2D'
    else:
        return 'unknown'


def grade_dwg_file(filepath):
    """
    Analyze a DWG file and return a score breakdown.

    Returns dict:
        score, raw_score, max_score, bonus, breakdown (list of str), details (dict)
    """
    filename = os.path.basename(filepath)
    with open(filepath, 'rb') as f:
        data = f.read()

    file_size = len(data)
    score = 0
    breakdown = []
    details = {}

    # Determine if DWG
    magic = data[:6].decode('ascii', errors='replace')
    is_dwg = magic in DWG_VERSIONS
    version_info = DWG_VERSIONS.get(magic, {'name': 'Unknown', 'year': 0, 'modern': False})

    # Classify drawing type
    drawing_type = _classify_drawing_type(filename, data)

    # Extract preview
    png_start, png_end, png_data = _extract_preview(data)
    bmp_start, bmp_end, bmp_data = _extract_bmp_preview(data)

    # Section markers
    section_count = 0
    for marker in SECTION_MARKERS:
        if marker in data:
            section_count += 1

    # String extraction
    all_strings = _find_ascii_strings(data, min_len=4)
    unique_strings = list(set(all_strings))

    # Entity class detection
    entity_class_hits = {}
    for pattern, label in ENTITY_CLASSES:
        count = data.count(pattern)
        if count > 0:
            entity_class_hits[label] = count

    # Find layer-like names (capitalized, short names)
    layer_candidates = set()
    for s in unique_strings:
        if 2 <= len(s) <= 40 and s[0].isupper() and s.replace('_', '').replace('-', '').isalnum():
            if not s.startswith(('AcDb', 'AcDs', 'AcRx', 'ASM', 'AcGi')):
                layer_candidates.add(s)

    # ─────────────────────────────────────────────
    # SECTION 1: File Integrity & Format (15 pts)
    # ─────────────────────────────────────────────
    section_score = 0

    # 1a. Valid DWG magic (5 pts)
    if is_dwg:
        section_score += 5
        details['dwg_version'] = magic
        details['version_name'] = version_info['name']
    else:
        breakdown.append("- Not a recognized DWG file (1a: -5)")
        details['dwg_version'] = magic
        details['version_name'] = 'Unknown'

    # 1b. Reasonable file size (5 pts)
    if file_size >= 100 * 1024:  # 100 KB+
        section_score += 5
    elif file_size >= 40 * 1024:  # 40 KB+
        section_score += 3
        breakdown.append(f"- Small DWG file ({file_size/1024:.0f}KB) — may be incomplete (1b: -2)")
    else:
        section_score += 1
        breakdown.append(f"- DWG file too small ({file_size/1024:.0f}KB) — likely empty or corrupted (1b: -4)")

    # 1c. No truncation/corruption (5 pts)
    # Check for abrupt endings, missing EOF markers
    eof_chunk = data[-32:] if len(data) >= 32 else data
    has_garbage_end = sum(1 for b in eof_chunk if b == 0) > 20  # excessive nulls at end
    if not has_garbage_end and file_size > 200:
        section_score += 5
    elif file_size <= 200:
        section_score += 0
        breakdown.append("- File is essentially empty (1c: -5)")
    else:
        section_score += 3
        breakdown.append("- Possible file truncation detected (1c: -2)")

    score += section_score
    breakdown.insert(0, f"[1] File Integrity & Format: {section_score}/15")
    details['section1_score'] = section_score

    # ─────────────────────────────────────────────
    # SECTION 2: Drawing Complexity & Content (30 pts)
    # ─────────────────────────────────────────────
    section_score = 0

    # 2a. Entity diversity (10 pts)
    entity_types_found = len(entity_class_hits)
    if entity_types_found >= 6:
        section_score += 10
    elif entity_types_found >= 3:
        section_score += 7
        breakdown.append(f"- Only {entity_types_found} entity types found — use more variety (2a: -3)")
    elif entity_types_found >= 1:
        section_score += 4
        breakdown.append(f"- Very limited entity types ({entity_types_found}) — drawing too simple (2a: -6)")
    else:
        # Size-based fallback: larger files likely have more content
        if file_size > 150 * 1024:
            section_score += 6
            breakdown.append("- Entity types not detectable but file size suggests complex drawing (2a: -4)")
        elif file_size > 60 * 1024:
            section_score += 3
            breakdown.append("- Content complexity low — add more drawing elements (2a: -7)")
        else:
            section_score += 0
            breakdown.append("- Drawing appears empty or minimal — no detectable entities (2a: -10)")

    # 2b. Drawing density (10 pts)
    # Use raw string diversity as proxy for content
    string_density = len(unique_strings)
    if string_density >= 100:
        section_score += 10
    elif string_density >= 40:
        section_score += 7
        breakdown.append(f"- Moderate drawing complexity ({string_density} unique elements) (2b: -3)")
    elif string_density >= 10:
        section_score += 4
        breakdown.append(f"- Low drawing complexity — sparse content (2b: -6)")
    else:
        section_score += 1
        breakdown.append("- Very sparse drawing — add more objects (2b: -9)")

    # 2c. Appropriate file size for drawing type (10 pts)
    # 3D models typically larger; 2D floor plans typically smaller
    if drawing_type == '3D':
        if file_size > 300 * 1024:
            section_score += 10
        elif file_size > 120 * 1024:
            section_score += 7
            breakdown.append(f"- 3D file size ({file_size/1024:.0f}KB) could be larger (2c: -3)")
        else:
            section_score += 4
            breakdown.append(f"- 3D drawing seems incomplete at {file_size/1024:.0f}KB (2c: -6)")
    else:
        if file_size > 100 * 1024:
            section_score += 10
        elif file_size > 50 * 1024:
            section_score += 7
            breakdown.append(f"- Drawing could include more detail (2c: -3)")
        else:
            section_score += 4
            breakdown.append(f"- Minimal drawing content at {file_size/1024:.0f}KB (2c: -6)")

    details['entity_types_found'] = entity_types_found
    details['entity_classes'] = entity_class_hits
    details['string_density'] = string_density

    score += section_score
    breakdown.insert(1, f"[2] Drawing Complexity & Content: {section_score}/30")
    details['section2_score'] = section_score

    # ─────────────────────────────────────────────
    # SECTION 3: Presentation & Polishing (20 pts)
    # ─────────────────────────────────────────────
    section_score = 0

    # 3a. Embedded preview/thumbnail (8 pts)
    if png_data:
        png_size_kb = len(png_data) / 1024
        if png_size_kb >= 10:
            section_score += 8
        elif png_size_kb >= 3:
            section_score += 6
            breakdown.append(f"- Small preview thumbnail ({png_size_kb:.0f}KB) (3a: -2)")
        else:
            section_score += 4
            breakdown.append(f"- Minimal preview thumbnail ({png_size_kb:.0f}KB) (3a: -4)")
        details['preview_type'] = 'PNG'
        details['preview_size_kb'] = round(png_size_kb, 1)
    elif bmp_data:
        bmp_size_kb = len(bmp_data) / 1024
        section_score += 4
        breakdown.append(f"- BMP preview ({bmp_size_kb:.0f}KB) — PNG preferred (3a: -4)")
        details['preview_type'] = 'BMP'
        details['preview_size_kb'] = round(bmp_size_kb, 1)
    else:
        breakdown.append("- No embedded preview thumbnail — quality presentation missing (3a: -8)")
        details['preview_type'] = None
        details['preview_size_kb'] = 0

    # 3b. Modern version (4 pts)
    if version_info.get('modern', False):
        section_score += 4
        details['modern_format'] = True
    else:
        section_score += 1
        breakdown.append(f"- Legacy format ({magic}) — use current AutoCAD version (3b: -3)")
        details['modern_format'] = False

    # 3c. Drawing organization (8 pts)
    # Use section marker count as proxy for organization
    if section_count >= 3:
        section_score += 8
    elif section_count >= 1:
        section_score += 5
        breakdown.append(f"- Minimal DWG structure ({section_count} section(s)) (3c: -3)")
    else:
        section_score += 2
        breakdown.append("- No DWG sections detected — poorly structured (3c: -6)")

    details['section_count'] = section_count

    score += section_score
    breakdown.insert(2, f"[3] Presentation & Polishing: {section_score}/20")
    details['section3_score'] = section_score

    # ─────────────────────────────────────────────
    # SECTION 4: Layers & Organization (15 pts)
    # ─────────────────────────────────────────────
    section_score = 0

    # Layer count heuristic from layer-like strings
    layer_count = len(layer_candidates)
    details['layer_estimate'] = layer_count
    details['layer_candidates'] = sorted(list(layer_candidates))[:30]

    if layer_count >= 8:
        section_score += 15
    elif layer_count >= 4:
        section_score += 11
        breakdown.append(f"- Only ~{layer_count} layers detected — use more layers for organization (4: -4)")
    elif layer_count >= 1:
        section_score += 6
        breakdown.append(f"- Very few layers (~{layer_count}) — organize drawing with layers (4: -9)")
    else:
        breakdown.append("- No layers detected — essential for CAD organization (4: -15)")

    score += section_score
    breakdown.insert(3, f"[4] Layers & Organization: {section_score}/15")
    details['section4_score'] = section_score

    # ─────────────────────────────────────────────
    # SECTION 5: Dimensions & Annotation (10 pts)
    # ─────────────────────────────────────────────
    section_score = 0

    has_dims = 'Dimensions' in entity_class_hits or bool(re.search(rb'DIMENSION|DIMSTYLE|AcDbDim', data, re.I))
    has_text = 'Multi-line Text' in entity_class_hits or 'Single-line Text' in entity_class_hits
    has_text |= bool(re.search(rb'MTEXT|TEXT|AcDbText|AcDbMText', data, re.I))
    has_blocks = 'Block Inserts' in entity_class_hits or bool(re.search(rb'INSERT|BLOCK|AcDbBlock', data, re.I))

    details['has_dimensions'] = has_dims
    details['has_text'] = has_text
    details['has_blocks'] = has_blocks

    if has_dims:
        section_score += 5
    else:
        breakdown.append("- No dimensions detected — add measurements (5: -5)")

    if has_text:
        section_score += 5
    else:
        breakdown.append("- No text annotations — add labels and notes (5: -5)")

    score += section_score
    breakdown.insert(4, f"[5] Dimensions & Annotation: {section_score}/10")
    details['section5_score'] = section_score

    # ─────────────────────────────────────────────
    # SECTION 6: Compliance & Best Practices (10 pts)
    # ─────────────────────────────────────────────
    section_score = 0

    # 6a. No duplicate filename issues (3 pts)
    section_score += 3

    # 6b. File naming convention (3 pts)
    # Good: descriptive, includes student name or exercise number
    clean_name = os.path.splitext(filename)[0]
    has_student_info = any(c.isdigit() for c in clean_name)
    has_descriptive_name = len(clean_name) > 10
    if has_descriptive_name:
        section_score += 3
    else:
        section_score += 1
        breakdown.append("- Non-descriptive filename — use meaningful names (6b: -2)")

    # 6c. Not a template/empty file (4 pts)
    if file_size > 50 * 1024:
        section_score += 4
    elif file_size > 30 * 1024:
        section_score += 2
        breakdown.append("- File near auto-generated template size — ensure custom content (6c: -2)")
    else:
        section_score += 0
        breakdown.append("- File appears to be an empty template (6c: -4)")

    score += section_score
    breakdown.insert(5, f"[6] Compliance & Best Practices: {section_score}/10")
    details['section6_score'] = section_score

    # ─────────────────────────────────────────────
    # BONUS: Advanced Features (+5 pts)
    # ─────────────────────────────────────────────
    bonus = 0

    # 3D modeling bonus
    if drawing_type == '3D':
        has_3d_solid = '3D Solids' in entity_class_hits
        has_surface = 'Surfaces' in entity_class_hits
        if has_3d_solid or has_surface:
            bonus = 5
            breakdown.append("⭐ BONUS: Advanced 3D modeling (+5)")
        else:
            bonus = 3
            breakdown.append("⭐ BONUS: 3D drawing submitted (+3)")

    # Block/Xref usage
    elif has_blocks:
        bonus = 3
        breakdown.append("⭐ BONUS: Used blocks/xrefs (+3)")

    # Large, complex 2D drawing
    elif file_size > 250 * 1024 and entity_types_found >= 3:
        bonus = 2
        breakdown.append("⭐ BONUS: Complex multi-element drawing (+2)")

    details['drawing_type'] = drawing_type
    details['bonus'] = bonus
    details['file_size'] = file_size

    # ─────────────────────────────────────────────
    # FINAL SCORE
    # ─────────────────────────────────────────────
    raw_score = score
    final_score = min(score + bonus, 110)
    grade_pct = min(final_score, 100)

    return {
        'score': grade_pct,
        'raw_score': raw_score,
        'max_score': 100,
        'bonus': bonus,
        'breakdown': breakdown,
        'details': details,
    }


def format_grade_report(result):
    """Format the DWG grading result as a readable multi-line string."""
    lines = []
    d = result['details']
    lines.append(f"AUTOCAD DWG GRADE: {result['score']}/100" +
                 (f" (incl. +{result['bonus']} bonus)" if result['bonus'] else ""))
    lines.append("-" * 55)
    for b in result['breakdown']:
        lines.append(b)
    lines.append("-" * 55)
    lines.append(f"File: {d.get('dwg_version', '?')} ({d.get('version_name', 'Unknown')})")
    lines.append(f"Type: {d.get('drawing_type', 'unknown')} | "
                 f"Size: {d.get('file_size', 0) / 1024:.1f} KB | "
                 f"Sections: {d.get('section_count', 0)}")
    lines.append(f"Entities: {d.get('entity_types_found', 0)} types | "
                 f"Layers: ~{d.get('layer_estimate', 0)} | "
                 f"Strings: {d.get('string_density', 0)}")
    lines.append(f"Preview: {d.get('preview_type', 'None')} "
                 f"({d.get('preview_size_kb', 0)} KB)")
    lines.append(f"Dims: {'Yes' if d.get('has_dimensions') else 'No'} | "
                 f"Text: {'Yes' if d.get('has_text') else 'No'} | "
                 f"Blocks: {'Yes' if d.get('has_blocks') else 'No'}")
    if d.get('entity_classes'):
        lines.append(f"Entity classes: {', '.join(f'{k}({v})' for k, v in d['entity_classes'].items())}")
    lines.append("")
    lines.append("NOTE: DWG 2018+ is a proprietary binary format.")
    lines.append("This is a heuristic auto-grade. Manual review recommended.")
    return '\n'.join(lines)
