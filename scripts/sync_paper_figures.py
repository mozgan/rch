#!/usr/bin/env python3
"""Copy manuscript-referenced generated figures before compiling the paper.

All references are checked before copying. This neither runs experiments nor
rewrites manuscript text; missing generated assets fail explicitly.
"""
from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sync_figures(manuscript: Path, generated: Path, destination: Path) -> list[str]:
    # The manuscript uses literal includegraphics paths in its figures/ directory.
    text = re.sub(r'(?<!\\)%[^\n]*', '', manuscript.read_text())
    names = re.findall(r'\\includegraphics\*?\s*(?:\[[^\]]*\]\s*)?\{([^{}]+)\}', text)
    if not names:
        raise ValueError('no literal figure references found')
    sources: dict[str, Path] = {}
    for name in names:
        path = Path(name)
        if path.name != name or path.suffix not in ('.eps', '.pdf', '.png', '.jpg', '.jpeg'):
            raise ValueError(f'expected a literal figure filename with extension: {name}')
        source = generated / name
        if not source.is_file():
            raise FileNotFoundError(f'missing generated figure {source}; run make paper-artifacts first')
        sources[name] = source
        if path.suffix == '.eps' and source.with_suffix('.pdf').is_file():
            sources[path.with_suffix('.pdf').name] = source.with_suffix('.pdf')
    destination.mkdir(parents=True, exist_ok=True)
    for name, source in sources.items():
        target = destination / name
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            shutil.copyfile(source, target)
    return sorted(sources)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manuscript', type=Path, default=ROOT / 'paper/manuscript.tex')
    parser.add_argument('--generated-dir', type=Path, default=ROOT / 'analysis/generated/figures')
    parser.add_argument('--destination', type=Path, default=ROOT / 'paper/figures')
    args = parser.parse_args()
    names = sync_figures(args.manuscript, args.generated_dir, args.destination)
    print(f'Synchronized {len(names)} manuscript figure assets; manuscript text unchanged')


if __name__ == '__main__':
    main()
