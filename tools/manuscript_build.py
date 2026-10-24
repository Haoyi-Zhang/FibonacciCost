"""Build and validate the current Elsevier research article and supplement.

Run from this directory with ``python build.py``.  The script does not install
software or alter publisher style files.  It regenerates data-derived tables,
validates the bibliography integration, performs a clean XeLaTeX/BibTeX build,
and records page, reference, font-embedding, and hash checks. The matched
current manuscript uses XeLaTeX; obsolete AAAI page/style limits do not apply.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

GENERATED_SUFFIXES = (".aux", ".bbl", ".blg", ".log", ".out", ".toc")
EXPECTED_BIBITEMS = {"main": 52, "supplement": 2}
REQUIRED_SOURCES = ("main.tex", "supplement.tex", "supplement-proofs.tex")
EXPECTED_STYLE_SHA256 = {
    "elsarticle.cls": "01addb492c5d075b320636ac3a30d8a5762fa937220dea07a5e107042d25384d",
}
FORBIDDEN_SOURCE_PATTERNS = {
    r"\\usepackage(?:\[[^]]*\])?\{geometry\}": "geometry package",
    r"\\usepackage(?:\[[^]]*\])?\{savetrees\}": "savetrees package",
    r"\\usepackage(?:\[[^]]*\])?\{setspace\}": "setspace package",
    r"\\usepackage(?:\[[^]]*\])?\{titlesec\}": "titlesec package",
    r"\\enlargethispage": "manual page enlargement",
    r"\\vspace\s*\{\s*-": "negative vertical spacing",
    r"\\linespread": "manual line spacing",
    r"\\renewcommand\s*\{\\baselinestretch\}": "manual baseline stretch",
}


def run(command: list[str], *, cwd: Path, timeout: int = 60) -> str:
    done = subprocess.run(
        command,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if done.returncode:
        print(done.stdout[-24000:], file=sys.stderr)
        raise SystemExit(done.returncode)
    return done.stdout


def pdf_pages(pdfinfo: str, path: Path) -> int:
    output = run([pdfinfo, str(path)], cwd=path.parent)
    match = re.search(r"(?m)^Pages:\s+(\d+)\s*$", output)
    if not match:
        raise SystemExit(f"could not read PDF page count: {path}")
    return int(match.group(1))


def font_audit(pdffonts: str, path: Path) -> dict:
    output = run([pdffonts, str(path)], cwd=path.parent)
    rows = []
    for line in output.splitlines()[2:]:
        if not line.strip():
            continue
        cols = re.split(r"\s{2,}", line.strip())
        if len(cols) < 6:
            raise SystemExit(f"unexpected pdffonts row in {path.name}: {line}")
        flags = cols[3].split()
        if len(flags) != 3:
            raise SystemExit(f"unexpected pdffonts flags in {path.name}: {line}")
        rows.append({"name": cols[0], "type": cols[1], "encoding": cols[2],
                     "embedded": flags[0], "subset": flags[1], "unicode": flags[2]})
    if not rows or any(row["embedded"] != "yes" for row in rows):
        raise SystemExit(f"unembedded or missing fonts in {path.name}")
    font_types = sorted({row["type"] for row in rows})
    if any("Type 3" in font_type for font_type in font_types) or "Type 3" in output:
        raise SystemExit(f"Type 3 font found in {path.name}")
    return {"font_count": len(rows), "all_embedded": True,
            "type3_fonts": 0, "font_types": font_types}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def validate_bibliography(name: str, bbl: str, expected_keys: set[str]) -> int:
    bibkeys = re.findall(r"\\bibitem(?:\[.*?\])?\{([^}]+)\}", bbl, re.S)
    expected = EXPECTED_BIBITEMS[name]
    if len(bibkeys) != expected:
        raise SystemExit(f"{name}: expected {expected} bibliography items, found {len(bibkeys)}")
    if set(bibkeys) != expected_keys:
        raise SystemExit(f"{name}: typeset bibliography keys differ from the included sources")
    return len(bibkeys)


def validate_source_bibliography(artifact: Path) -> dict:
    """Compare canonical metadata with the actual included publisher sources."""
    output = run([sys.executable, "-B", str(artifact / "tests" / "check_bibliography.py"),
                  "--paper-dir", str(Path(globals().get("MANUSCRIPT_DIR", Path(__file__).resolve().parents[2] / "paper"))), "--out", "-"], cwd=artifact)
    bibliography_check = json.loads(output)
    if not bibliography_check["publisher_documents_validated"]:
        raise SystemExit("publisher source coverage was not validated")
    expected_keys = bibliography_check["publisher_citation_keys"]
    if {name: len(keys) for name, keys in expected_keys.items()} != EXPECTED_BIBITEMS:
        raise SystemExit("publisher source citation counts differ from the expected selection")
    return bibliography_check


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check-environment",
        action="store_true",
        help="validate the supported Linux/Python and document toolchain without building",
    )
    parser.add_argument("--out", type=Path, help="new build-report path; existing results are not overwritten")
    args = parser.parse_args()

    root = Path(globals().get("MANUSCRIPT_DIR", Path(__file__).resolve().parents[2] / "paper"))
    project = root.parent
    artifact = project / "artifact"
    sys.path.insert(0, str(artifact / "src"))
    from platform_support import environment_record, require_supported_environment

    resource = require_supported_environment("paper/build.py")
    runtime = environment_record("paper/build.py", resource)
    latex = shutil.which("xelatex")
    bib = shutil.which("bibtex") or shutil.which("bibtex.original")
    pdfinfo = shutil.which("pdfinfo")
    pdffonts = shutil.which("pdffonts")
    tools = {
        "xelatex": latex,
        "bibtex": bib,
        "pdfinfo": pdfinfo,
        "pdffonts": pdffonts,
    }
    missing = [name for name, path in tools.items() if path is None]
    if missing:
        raise SystemExit(
            "required document tools are missing: " + ", ".join(missing)
            + "; install them inside the supported Linux/WSL environment"
        )
    if args.check_environment:
        print(json.dumps({"environment": runtime, "required_commands": tools}, indent=2, sort_keys=True))
        return

    style_hashes = {name: sha256(root / name) for name in EXPECTED_STYLE_SHA256}
    if style_hashes != EXPECTED_STYLE_SHA256:
        raise SystemExit(f"publisher style hash mismatch: {style_hashes}")
    for source_name in REQUIRED_SOURCES:
        source_path = root / source_name
        if not source_path.is_file():
            raise SystemExit(f"missing publisher source: {source_name}")
        source = source_path.read_text(encoding="utf-8")
        for pattern, description in FORBIDDEN_SOURCE_PATTERNS.items():
            if re.search(pattern, source):
                raise SystemExit(f"{source_name}: forbidden {description}")

    if args.out is None:
        parser.error("--out is required for a new build report")
    out = args.out.resolve()
    if out.is_relative_to(root):
        parser.error("Build evidence must be written outside the paper tree; use artifact/paper_support or a separate work directory.")
    if out.exists():
        raise SystemExit(f"build-report path already exists: {out}")

    start = time.perf_counter()
    # Validate source-level reference coverage before LaTeX can hide an omission.
    bibliography_check = validate_source_bibliography(artifact)
    expected_keys = bibliography_check["publisher_citation_keys"]
    run([sys.executable, str(artifact / "make_tables.py"),
         "--results", str(artifact / "results"), "--out", str(root / "figures")], cwd=root)

    run([sys.executable, str(artifact / "figures" / "draw_schematics.py"),
         "--out", str(root / "figures")], cwd=root)

    targets = ["main", "supplement"]
    records: dict[str, dict] = {}
    for name in targets:
        for suffix in GENERATED_SUFFIXES:
            (root / f"{name}{suffix}").unlink(missing_ok=True)
        commands = [
            [latex, "-no-shell-escape", "-halt-on-error", "-file-line-error", "-interaction=nonstopmode", f"{name}.tex"],
            [bib, name],
            [latex, "-no-shell-escape", "-halt-on-error", "-file-line-error", "-interaction=nonstopmode", f"{name}.tex"],
            [latex, "-no-shell-escape", "-halt-on-error", "-file-line-error", "-interaction=nonstopmode", f"{name}.tex"],
        ]
        for command in commands:
            run(command, cwd=root, timeout=90)

        log = (root / f"{name}.log").read_text(encoding="utf-8", errors="replace")
        blg = (root / f"{name}.blg").read_text(encoding="utf-8", errors="replace")
        fatal_fragments = (
            "Overfull \\hbox", "Overfull \\vbox", "There were undefined references",
            "Citation(s) may have changed", "undefined citations", "Label(s) may have changed",
        )
        if any(fragment.lower() in log.lower() for fragment in fatal_fragments):
            raise SystemExit(f"layout or unresolved-reference warning in {name}.log")
        if "Warning--" in blg:
            raise SystemExit(f"bibliography warning in {name}.blg:\n{blg}")

        bbl = (root / f"{name}.bbl").read_text(encoding="utf-8", errors="replace")
        bibitems = validate_bibliography(name, bbl, set(expected_keys[name]))
        pdf = root / f"{name}.pdf"
        pages = pdf_pages(pdfinfo, pdf)
        # Report measured size without inventing an AIJ page or file-size rule.
        if pages < 1:
            raise SystemExit(f"{name}: empty PDF")
        fonts = font_audit(pdffonts, pdf)
        records[name] = {
            "pages": pages,
            "bibliography_items": bibitems,
            "bytes": pdf.stat().st_size,
            "sha256": sha256(pdf),
            **fonts,
        }
        print(f"{name}.pdf built: {pages} pages, {bibitems} references")

    child = resource.getrusage(resource.RUSAGE_CHILDREN)
    result = {
        "status": "passed",
        "environment": runtime,
        "documents": records,
        "bibliography_source_metadata_matches": True,
        "bibliography_validation": bibliography_check,
        "publisher_style_hashes": style_hashes,
        "publisher_class_matches_retained_current_class": True,
        "source_spacing_and_margin_override_scan": "passed",
        "format": "elsarticle preprint research article",
        "venue_numeric_limits_validated": False,
        "wall_seconds": time.perf_counter() - start,
        "child_cpu_seconds": child.ru_utime + child.ru_stime,
        "child_peak_rss_kib": child.ru_maxrss,
        "toolchain": {
            "xelatex": Path(latex).name,
            "bibtex": Path(bib).name,
            "pdfinfo": Path(pdfinfo).name,
            "pdffonts": Path(pdffonts).name,
        },
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
