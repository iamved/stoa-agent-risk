VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip
ENGINE := $(VENV)/bin/stoa-engine

.PHONY: help venv install sample test demo gaps clean

help:
	@echo "make install   - create venv and install package (with dev extras)"
	@echo "make sample    - regenerate examples/sample_submission.json"
	@echo "make test      - run pytest"
	@echo "make demo      - export the sample packet (--template all) and print gaps"
	@echo "make gaps      - print the gap report for the sample"
	@echo "make clean     - remove build artifacts and ./packet"

$(VENV):
	python3 -m venv $(VENV)

venv: $(VENV)

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

sample:
	$(PY) examples/_gen_sample.py

test:
	$(VENV)/bin/pytest -q

demo:
	$(ENGINE) export --input examples/sample_submission.json --template all --out ./packet
	@echo ""
	@echo "Gap report:"
	$(ENGINE) gaps --input examples/sample_submission.json --template all

gaps:
	$(ENGINE) gaps --input examples/sample_submission.json --template all

clean:
	rm -rf ./packet build dist *.egg-info stoa_engine/__pycache__ tests/__pycache__
