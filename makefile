# Define the default Python version as a constant
DEFAULT_PYTHON_VERSION = 3.13
PYTHON_VERSION ?= $(DEFAULT_PYTHON_VERSION)

.PHONY: dist repomix

PACKAGE_NAME = sentinel-tiles
ENVIRONMENT_NAME = $(PACKAGE_NAME)

clean:
	rm -rf *.o *.out *.log
	rm -rf build/
	rm -rf dist/
	rm -rf *.egg-info
	rm -rf .pytest_cache
	find . -type d -name "__pycache__" -exec rm -rf {} +

test:
	pytest

build:
	python -m build

twine-upload:
	twine upload dist/*

dist:
	make clean
	make build
	make twine-upload

remove-environment:
	mamba env remove -y -n $(ENVIRONMENT_NAME)

install:
	pip install -e .[dev]

uninstall:
	pip uninstall $(PACKAGE_NAME)

reinstall:
	make uninstall
	make install

environment:
	mamba create -y -n $(ENVIRONMENT_NAME) -c conda-forge python=$(PYTHON_VERSION)

repomix:
	npx repomix --ignore "**/*.geojson,LICENSE,.gitignore" --copy