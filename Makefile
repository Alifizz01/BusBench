# Thin wrapper around the Python runner, which builds the C half too and works
# on any OS (gcc, clang or MSVC). `make` is optional.
PYTHON ?= python

.PHONY: test test-py sanitize trace studio serve clean

test:
	$(PYTHON) -m busbench test

test-py:
	$(PYTHON) -m busbench test --py

sanitize:
	$(PYTHON) -m busbench test --sanitize

trace:
	$(PYTHON) -m pytest -q --junitxml=build/junit.xml
	$(PYTHON) -m busbench trace --requirements requirements/busbench_requirements.csv \
	    --results build/junit.xml --source busbench/*/test tests --out build/trace_report.md

studio:
	$(PYTHON) -m busbench studio

serve:
	$(PYTHON) -m busbench serve

clean:
	rm -rf build busbench/*/build
