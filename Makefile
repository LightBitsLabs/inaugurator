IMAGES_SOURCE=__undefined
IMAGES = $(IMAGES_SOURCE)/inaugurator.thin.initrd.img $(IMAGES_SOURCE)/inaugurator.fat.initrd.img $(IMAGES_SOURCE)/inaugurator.vmlinuz

all: build unittest check_convention

install: $(IMAGES)
	$(MAKE) install_nodeps

clean:
	rm -fr build docker-build docker-dist docker-dist-tmp remote dist inaugurator.egg-info

check_convention:
	pep8 inaugurator --max-line-length=109 --exclude=samplegrubconfigs.py
	sh/check_spelling.sh

UNITTESTS=$(shell find inaugurator -name 'test*.py' | sed 's@/@.@g' | sed 's/\(.*\)\.py/\1/' | sort)
unittest:
	PYTHONPATH=. python -m unittest $(UNITTESTS)

# pxelinux holds the kernel and the initrd together in the top usable memory region below
# 4GB. The smallest such region in the lab is 54.5MB (Supermicro SYS-220TP-HTTR); a pair
# that does not fit makes pxelinux stall at "Loading ...initrd...".
PXE_LOADER_BUDGET_BYTES=50000000
check_image: build/inaugurator.thin.initrd.dir build/inaugurator.thin.initrd.img build/inaugurator.vmlinuz
	PYTHONPATH=. python -m inaugurator.tests.image_check $<
	sh/check_image_size.sh build/inaugurator.vmlinuz build/inaugurator.thin.initrd.img $(PXE_LOADER_BUDGET_BYTES)

.PHONY: check_image_drivers
check_image_drivers:
	PYTHONPATH=. python -m inaugurator.tests.image_check build/inaugurator.thin.initrd.dir

integration_test:
	@echo "Note: For specific tests, run with TESTS=(Space seperated test names)."
	@PYTHONPATH=inaugurator python inaugurator/tests/integration_test.py $(TESTS)

include Makefile.build

uninstall:
	-sudo mkdir /usr/share/inaugurator
	-yes | sudo pip uninstall inaugurator

remote/%:
	sudo solvent bring --repositoryBasename=inaugurator --product build --destination=remote
	sudo cp $(subst ${IMAGES_SOURCE},remote/inaugurator/build,${IMAGES}) remote/

__undefined/%:
	$(error Please specify the environment variable IMAGES_SOURCE, to indicate how to obtain inaugurator images, as either 'build' (build images locally) or 'remote' (bring images from solvent object store))

.PHONY: submitclean
submitclean:
	SOLVENT_CLEAN=1 solvent submitbuild
	SOLVENT_CLEAN=1 solvent approve

install_nodeps:
	-sudo mkdir /usr/share/inaugurator
	-yes | sudo pip uninstall inaugurator
	python setup.py bdist
	sudo python setup.py install
	sudo cp $(IMAGES) /usr/share/inaugurator
	sudo chmod 644 /usr/share/inaugurator/*
	sudo chmod a+x /usr/share/inaugurator/execs/*

prepareForCleanBuild:
	sudo pip install pika
