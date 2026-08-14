"""
C++ Code Auto-Grader
Analyzes .cpp files and scores them on university-level C++ standards.
Designed for CPE 121 (Object-Oriented Programming) coursework.
"""

import re
import os


def grade_cpp_file(filepath):
    """
    Analyze a C++ source file and return a score breakdown.

    Grading rubric (100 pts):
      1. Compilation & Syntax     — 15 pts
      2. Correctness & Completeness — 25 pts
      3. Code Quality & Standards  — 30 pts
      4. Input Validation          — 15 pts
      5. Efficiency & Best Practices — 10 pts
      6. Documentation             —  5 pts
      Bonus: OOP Concepts          — +5 pts

    Returns dict:
        score, max_score, bonus, breakdown (list of str), details (dict)
    """
    with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
        code = f.read()

    lines = code.split('\n')
    non_empty = [l.strip() for l in lines if l.strip() and not l.strip().startswith('//')]
    all_stripped = [l.strip() for l in lines]
    full_text = '\n'.join(all_stripped)

    score = 0
    breakdown = []

    # ───────────────────────────────────────────────
    # SECTION 1: Compilation & Syntax (15 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    # 1a. Required includes (5 pts)
    has_iostream = bool(re.search(r'#include\s*<\s*iostream\s*>', code))
    has_cstdlib = bool(re.search(r'#include\s*<\s*cstdlib\s*>', code))
    include_count = len(re.findall(r'#include\s*<', code))
    if has_iostream:
        section_score += 3
    else:
        breakdown.append("- Missing #include <iostream> (1a: -3)")
    if include_count >= 2 or has_iostream:
        section_score += 2
    elif include_count == 1 and has_iostream:
        section_score += 2
    else:
        breakdown.append("- No standard library includes (1a: -2)")

    # 1b. Balanced braces at file level (5 pts)
    open_braces = code.count('{')
    close_braces = code.count('}')
    if open_braces == close_braces:
        section_score += 5
    else:
        diff = open_braces - close_braces
        breakdown.append(f"- Unbalanced braces: {abs(diff)} extra {'open' if diff > 0 else 'close'} brace(s) (1b: -5)")

    # 1c. Proper main() signature (5 pts)
    if re.search(r'int\s+main\s*\(\s*\)', code):
        section_score += 5
    elif re.search(r'int\s+main\s*\(', code):
        section_score += 4
        breakdown.append("- main() should be int main() — argc/argv not needed for basic programs (1c: -1)")
    elif 'main' in code:
        section_score += 2
        breakdown.append("- Non-standard main() signature; use int main() (1c: -3)")
    else:
        breakdown.append("- No main() function found (1c: -5)")

    score += section_score
    breakdown.insert(0, f"[1] Compilation & Syntax: {section_score}/15")

    # ───────────────────────────────────────────────
    # SECTION 2: Correctness & Completeness (25 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    # 2a. return 0; present (5 pts)
    if re.search(r'return\s+0\s*;', code):
        section_score += 5
    else:
        breakdown.append("- Missing 'return 0;' at end of main (2a: -5)")

    # 2b. Handles input via cin (5 pts)
    has_cin = bool(re.search(r'\bcin\s*>>', code))
    if has_cin:
        section_score += 5
    else:
        # Some programs are self-contained (e.g., compute constants)
        section_score += 3
        breakdown.append("- No user input (cin) — program has no interactivity (2b: -2)")

    # 2c. Produces output via cout (5 pts)
    has_cout = bool(re.search(r'\bcout\s*<<', code))
    if has_cout:
        section_score += 5
    else:
        breakdown.append("- No output (cout) — program produces no visible result (2c: -5)")

    # 2d. Variables declared properly (5 pts)
    # Check for use-before-declare (approximate — look for identifiers used before a type decl)
    score_2d = 5
    # Simple heuristic: check for obvious undeclared variables
    identifiers = set(re.findall(r'\b([a-zA-Z_]\w*)\b', code))
    declared = set(re.findall(r'(?:int|float|double|char|bool|string|auto)\s+([a-zA-Z_]\w*)', code))
    # Remove keywords
    keywords = {'if', 'else', 'for', 'while', 'do', 'return', 'cout', 'cin', 'endl',
                'include', 'using', 'namespace', 'std', 'int', 'float', 'double', 'char',
                'bool', 'void', 'main', 'string', 'auto', 'const', 'true', 'false', 'break',
                'continue', 'switch', 'case', 'default', 'class', 'public', 'private',
                'protected', 'struct', 'new', 'delete', 'this', 'virtual', 'override',
                'static', 'sizeof', 'typedef', 'unsigned', 'signed', 'long', 'short'}
    potential_undeclared = identifiers - declared - keywords
    # Filter out things that look like function calls (have parens after them elsewhere)
    suspicious = []
    for uid in potential_undeclared:
        if len(uid) > 1 and not uid.startswith('_'):
            # Check if it appears before any type declaration
            suspicious.append(uid)
    if len(suspicious) > 5:
        score_2d -= 2
        breakdown.append(f"- Possible undeclared variables: {', '.join(list(suspicious)[:5])}... (2d: -2)")
    section_score += score_2d

    # 2e. Program is substantive (5 pts)
    code_lines = len([l for l in non_empty if not l.startswith('#')])
    if code_lines >= 15:
        section_score += 5
    elif code_lines >= 8:
        section_score += 3
        breakdown.append(f"- Program is short ({code_lines} lines); consider more logic (2e: -2)")
    else:
        section_score += 1
        breakdown.append(f"- Program is too short ({code_lines} lines); trivial solution (2e: -4)")

    score += section_score
    breakdown.insert(1, f"[2] Correctness & Completeness: {section_score}/25")

    # ───────────────────────────────────────────────
    # SECTION 3: Code Quality & Standards (30 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    # 3a. No Variable-Length Arrays (10 pts) — major C++ standard violation
    vla_pattern = re.compile(r'(?:int|float|double|char)\s+\w+\s*\[\s*[a-zA-Z_]\w*\s*\]')
    vla_matches = vla_pattern.findall(code)
    has_vla = len(vla_matches) > 0
    if not has_vla:
        section_score += 10
    else:
        breakdown.append(f"- Variable-Length Array (VLA) detected: {vla_matches[0].strip()} — "
                         f"not standard C++, use std::vector (3a: -10)")

    # 3b. No 'using namespace std' at global scope (5 pts)
    using_std = bool(re.search(r'using\s+namespace\s+std\s*;', code))
    if not using_std:
        section_score += 5
    else:
        section_score += 2
        breakdown.append("- 'using namespace std;' — pollutes global namespace; prefer std:: prefix (3b: -3)")

    # 3c. Consistent indentation (5 pts)
    indent_chars = set()
    for l in lines:
        if l and l[0] in (' ', '\t'):
            indent_chars.add(l[0])
    if len(indent_chars) <= 1:
        section_score += 5
    else:
        section_score += 2
        breakdown.append("- Mixed spaces and tabs for indentation (3c: -3)")

    # 3d. Meaningful variable names (5 pts)
    var_decls_raw = re.findall(r'\b(?:int|float|double|char|bool|string)\s+([a-zA-Z_]\w*)', code)
    # Allow single letters for loop vars i, j, k, x, y, n, m
    allowed_single = {'i', 'j', 'k', 'n', 'm', 'x', 'y', 'z', 'a', 'b', 'c', 't'}
    bad_names = [v for v in var_decls_raw if len(v) == 1 and v not in allowed_single]
    if len(bad_names) == 0:
        section_score += 5
    elif len(bad_names) <= 2 and len(var_decls_raw) > 5:
        section_score += 3
        breakdown.append(f"- Non-descriptive single-letter variable(s): {', '.join(bad_names)} (3d: -2)")
    else:
        section_score += 1
        breakdown.append(f"- Many non-descriptive variables: {', '.join(bad_names[:5])} (3d: -4)")

    # 3e. No C-style casts (5 pts)
    c_casts = re.findall(r'\(\s*(?:int|float|double|char|long|short)\s*\)\s*\w', code)
    if not c_casts:
        section_score += 5
    else:
        section_score += 2
        breakdown.append("- C-style cast used — prefer static_cast<type>(value) (3e: -3)")

    score += section_score
    breakdown.insert(2, f"[3] Code Quality & Standards: {section_score}/30")

    # ───────────────────────────────────────────────
    # SECTION 4: Input Validation & Robustness (15 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    # 4a. Validates input range (5 pts)
    has_range_check = bool(re.search(
        r'if\s*\(\s*\w+\s*(<|>|<=|>=|==)\s*\d+\s*\)|'
        r'if\s*\(\s*\w+\s*(<|>|<=|>=|==)\s*\d+\s*\|\|',
        code))
    if has_range_check:
        section_score += 5
    elif has_cin:
        section_score += 1
        breakdown.append("- No input validation — negative/zero values not checked (4a: -4)")

    # 4b. Checks cin stream state (5 pts)
    has_cin_check = bool(re.search(r'cin\s*\.\s*(?:fail|good|bad|eof|clear|ignore)', code))
    if has_cin_check:
        section_score += 5
    elif has_cin:
        breakdown.append("- No cin error checking — invalid input will break program (4b: -5)")
    # else: no input needed, no deduction

    # 4c. Edge case handling (5 pts)
    edge_checks = len(re.findall(r'if\s*\(\s*\w+\s*(==|!=|<=|>=)\s*0', code))
    has_constants = bool(re.search(r'\bconst\b', code))
    if edge_checks >= 2:
        section_score += 5
    elif edge_checks >= 1 or has_constants:
        section_score += 3
        breakdown.append("- Minimal edge case handling (4c: -2)")
    else:
        section_score += 0
        if has_cin:
            breakdown.append("- No edge case handling — division by zero, empty input not checked (4c: -5)")

    score += section_score
    breakdown.insert(3, f"[4] Input Validation & Robustness: {section_score}/15")

    # ───────────────────────────────────────────────
    # SECTION 5: Efficiency & Best Practices (10 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    # 5a. Appropriate data types (3 pts)
    # Check if sum uses int when accumulating doubles, or vice versa
    uses_double = bool(re.search(r'\bdouble\b', code))
    uses_int_sum = bool(re.search(r'int\s+\w*\s*sum', code))
    has_double_input = bool(re.search(r'double\s+\w+', code))
    if not (uses_int_sum and has_double_input):
        section_score += 3
    else:
        section_score += 1
        breakdown.append("- int used for sum but inputs are doubles — precision loss (5a: -2)")

    # 5b. No duplicate/unnecessary loops (4 pts)
    for_loops = re.findall(r'for\s*\(', code)
    # Check for same-range loops that could be merged
    loop_ranges = re.findall(r'for\s*\(\s*(?:int\s+)?(\w+)\s*=\s*(\d+)\s*;\s*\1\s*<\s*(\w+)', code)
    if len(loop_ranges) == len(set(loop_ranges)):
        section_score += 4
    elif len(for_loops) <= 1:
        section_score += 4
    else:
        section_score += 2
        breakdown.append("- Multiple loops over same range — could be consolidated (5b: -2)")

    # 5c. Uses const where appropriate (3 pts)
    if has_constants:
        section_score += 3
    else:
        # Only dock if there are values that should be const
        has_magic_numbers = bool(re.search(r'=\s*\d{2,}\s*;', code))
        if has_magic_numbers:
            breakdown.append("- Magic numbers without const — use named constants (5c: -3)")
        else:
            section_score += 3

    score += section_score
    breakdown.insert(4, f"[5] Efficiency & Best Practices: {section_score}/10")

    # ───────────────────────────────────────────────
    # SECTION 6: Documentation (5 pts)
    # ───────────────────────────────────────────────
    section_score = 0

    has_comments = bool(re.search(r'//|/\*', code))
    comment_lines = len([l for l in all_stripped if l.startswith('//') or l.startswith('/*')])

    if comment_lines >= 3:
        section_score += 3
    elif has_comments:
        section_score += 2
        breakdown.append("- Minimal comments — explain algorithm steps (6: -1)")
    else:
        breakdown.append("- No comments — add documentation explaining the logic (6: -3)")

    # Descriptive prompts
    prompts = re.findall(r'cout\s*<<\s*"([^"]*)"', code)
    good_prompts = [p for p in prompts if len(p) >= 10]
    if len(good_prompts) >= 2:
        section_score += 2
    elif len(good_prompts) >= 1:
        section_score += 1
        breakdown.append("- Brief output prompts — be more descriptive (6: -1)")
    else:
        breakdown.append("- No descriptive prompts — user doesn't know what to enter (6: -2)")

    score += section_score
    breakdown.insert(5, f"[6] Documentation: {section_score}/5")

    # ───────────────────────────────────────────────
    # BONUS: OOP Concepts (+5 pts)
    # ───────────────────────────────────────────────
    bonus = 0
    has_class = bool(re.search(r'\bclass\s+\w+', code))
    has_access_specifier = bool(re.search(r'\b(?:public|private|protected)\s*:', code))
    has_constructor = bool(re.search(r'(\w+)\s*::\s*\1\s*\(', code)) or \
                      bool(re.search(r'(\w+)\s*\(\s*\)\s*(?:const\s*)?\{[^}]*\}', code))

    if has_class and has_access_specifier:
        bonus = 5
        breakdown.append("⭐ BONUS: Used OOP class with access specifiers (+5)")
    elif has_class:
        bonus = 3
        breakdown.append("⭐ BONUS: Used a class/structure (+3)")
    elif re.search(r'\bstruct\s+\w+', code):
        bonus = 2
        breakdown.append("⭐ BONUS: Used a struct (+2)")

    # ───────────────────────────────────────────────
    # FINAL SCORE
    # ───────────────────────────────────────────────
    final_score = min(score + bonus, 110)
    grade_pct = min(final_score, 100)

    return {
        'score': grade_pct,
        'raw_score': score,
        'max_score': 100,
        'bonus': bonus,
        'breakdown': breakdown,
        'details': {
            'has_iostream': has_iostream,
            'balanced_braces': open_braces == close_braces,
            'proper_main': bool(re.search(r'int\s+main\s*\(\s*\)', code)),
            'has_return': bool(re.search(r'return\s+0\s*;', code)),
            'has_cin': has_cin,
            'has_cout': has_cout,
            'line_count': len(non_empty),
            'has_vla': has_vla,
            'using_namespace_std': using_std,
            'has_comments': has_comments,
            'comment_lines': comment_lines,
            'has_oop': bool(has_class),
            'has_validation': has_range_check or has_cin_check,
            'c_casts': len(c_casts),
        }
    }


def format_grade_report(result):
    """Format the grading result as a readable multi-line string."""
    lines = []
    lines.append(f"SCORE: {result['score']}/100" +
                 (f" (incl. +{result['bonus']} bonus)" if result['bonus'] else ""))
    lines.append("-" * 45)
    for b in result['breakdown']:
        lines.append(b)
    lines.append("-" * 45)
    lines.append(f"Details: includes={result['details']['has_iostream']}, "
                 f"balanced={result['details']['balanced_braces']}, "
                 f"vla={result['details']['has_vla']}, "
                 f"using_std={result['details']['using_namespace_std']}, "
                 f"comments={result['details']['comment_lines']} lines, "
                 f"oop={result['details']['has_oop']}")
    return '\n'.join(lines)
