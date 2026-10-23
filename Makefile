# Results -> paper and README.
#
#   make results   run the registered analyses; writes results/*.json (needs the raw data)
#   make figures   build the registered figures
#   make publish   render paper/numbers.tex, paper/tables/*.tex and README.md from results/
#   make check     fail if a generated file differs from a fresh render (what CI runs)
#   make paper     build paper/hidden_options_market.pdf
#   make all       all of the above, in that order
#
# `publish` and `check` read only results/ and docs/readme.template.md, so they run on a
# checkout without the raw data. Edit docs/readme.template.md, never README.md.

PY ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
HIDDEN_OPTIONS = $(PY) -m hidden_options.cli

.PHONY: all results figures publish check paper
.NOTPARALLEL:

all: results figures publish check paper

results:
	$(HIDDEN_OPTIONS) results

figures:
	$(HIDDEN_OPTIONS) figures

publish:
	$(HIDDEN_OPTIONS) publish

check:
	$(HIDDEN_OPTIONS) check

# tectonic writes the PDF beside the source; paper/*.pdf is git-ignored.
paper:
	tectonic paper/hidden_options_market.tex
