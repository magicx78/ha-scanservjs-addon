.PHONY: test test-verbose test-coverage test-quick clean help

# Test-Targets für KI-Module

help:
	@echo "KI-Module Test-Targets:"
	@echo "  make test           - Alle Tests ausführen"
	@echo "  make test-verbose   - Tests mit verbose Output"
	@echo "  make test-coverage  - Tests mit Coverage-Report (HTML)"
	@echo "  make test-quick     - Schnelle Tests ohne Coverage"
	@echo "  make test-watch     - Tests im Watch-Mode (pytest-watch)"
	@echo "  make clean          - Cleanup Test-Artifacts"

test:
	cd tests && pytest -v

test-verbose:
	cd tests && pytest -vv -s

test-coverage:
	cd tests && pytest -v --cov=../ --cov-report=term-missing --cov-report=html --cov-fail-under=80
	@echo "Coverage-Report: tests/htmlcov/index.html"

test-quick:
	cd tests && pytest -q --tb=short

test-watch:
	cd tests && ptw -- -v

test-unit:
	cd tests && pytest -v -m unit

test-mock:
	cd tests && pytest -v -m mock

clean:
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	rm -rf tests/.pytest_cache tests/htmlcov tests/.coverage
