# Define the default Python version as a constant
DEFAULT_PYTHON_VERSION = 3.10

.PHONY: dist

PACKAGE_NAME = sentinel-tiles
ENVIRONMENT_NAME = $(PACKAGE_NAME)
DOCKER_IMAGE_NAME = $(PACKAGE_NAME)

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
	@PYTHON_VERSION=${PYTHON_VERSION:=$(DEFAULT_PYTHON_VERSION)} \
	mamba create -y -n $(ENVIRONMENT_NAME) -c conda-forge python=$$PYTHON_VERSION

colima-start:
	colima start -m 16 -a x86_64 -d 100 

docker-build:
	docker build -t $(DOCKER_IMAGE_NAME):latest .

docker-build-environment:
	docker build --target environment -t $(DOCKER_IMAGE_NAME):latest .

docker-build-installation:
	docker build --target installation -t $(DOCKER_IMAGE_NAME):latest .

docker-interactive:
	docker run -it $(DOCKER_IMAGE_NAME) fish 

docker-remove:
	docker rmi -f $(DOCKER_IMAGE_NAME)
