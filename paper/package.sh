#!/usr/bin/env sh
# Build the report and write the tarball arXiv compiles (see SUBMITTING.md).
set -eu
cd "$(dirname "$0")"
if [ ! -f author.tex ]; then
  echo "author.tex is missing: copy author.example.tex to author.tex and fill it in" >&2
  exit 1
fi
latexmk -pdf -interaction=nonstopmode -halt-on-error main.tex
tar -czf arxiv-upload.tar.gz main.tex author.tex author.example.tex
echo "wrote paper/main.pdf and paper/arxiv-upload.tar.gz"
