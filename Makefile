PY ?= python3
.PHONY: install wheels up down status test baselines reasoner-dev reasoner-heldout ablations diagnose report clean

install:            ## install python dependencies
	$(PY) -m pip install -e '.[dev]'

wheels:             ## pre-download Alpine wheels for offline / proxied docker builds
	$(PY) -m pip download -q --dest sandbox/api/wheels --only-binary=:all: --platform musllinux_1_2_x86_64 \
	  --python-version 3.12 --implementation cp -r sandbox/api/requirements.txt "typing-extensions>=4.6"

up:                 ## build and start the ShopStack sandbox
	$(PY) -m recovery up

down:
	$(PY) -m recovery down

status:
	$(PY) -m recovery status

test:               ## unit tests (no docker, no API key)
	$(PY) -m pytest -q

baselines:          ## noop / restart_all / rules on all 22 scenarios
	for a in noop restart_all rules; do $(PY) -m recovery run --agent $$a --scenarios all --tag baseline-$$a; done

reasoner-dev:       ## reasoner agent on the dev split
	$(PY) -m recovery run --agent reasoner --scenarios dev --tag reasoner-dev

reasoner-heldout:   ## reasoner agent on the held-out split, 2 repeats
	$(PY) -m recovery run --agent reasoner --scenarios heldout --repeats 2 --tag reasoner-heldout

ablations:          ## reasoner ablations on the held-out split (one evidence source switched off each)
	for v in no_logs no_metrics no_diagnostics no_changes single_pass; do \
	  $(PY) -m recovery run --agent reasoner --variant $$v --scenarios heldout --tag ablation-$$v; done

diagnose:           ## read-only: print the recommended solution for the live system
	$(PY) -m recovery diagnose

report:             ## regenerate docs/results.md from the runs in runs/
	$(PY) -m recovery report $(TAGS) --out docs/results.md

clean:
	rm -rf sandbox/.runtime
