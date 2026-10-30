PY ?= python3
# Runs that reports and the web app are built from (override: make webapp TAGS="baseline-rules llm-heldout").
TAGS ?= baseline-noop baseline-restart_all baseline-rules
# Load .env if present (for ANTHROPIC_API_KEY).
-include .env
export

.PHONY: install wheels up down status test baselines llm-dev llm-heldout ablations report reports webapp clean

install:            ## install python dependencies
	$(PY) -m pip install -e '.[dev,export]'

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

llm-dev:            ## LLM agent on the dev split
	$(PY) -m recovery run --agent llm --scenarios dev --tag llm-dev

llm-heldout:        ## LLM agent on the held-out split, 2 repeats
	$(PY) -m recovery run --agent llm --scenarios heldout --repeats 2 --tag llm-heldout

ablations:          ## LLM ablations on the held-out split
	for v in no_verify no_changes no_diagnostics minimal_prompt; do \
	  $(PY) -m recovery run --agent llm --variant $$v --scenarios heldout --tag ablation-$$v; done

report:             ## regenerate docs/results.md from the runs in runs/
	$(PY) -m recovery report $(TAGS) --out docs/results.md

reports:            ## CSV + PDF incident reports for the baseline runs (docs/reports/)
	$(PY) -m recovery export $(TAGS)

webapp:             ## rebuild the Mend web app (docs/mend.html) from the runs in runs/
	$(PY) webapp/build.py $(TAGS)

clean:
	rm -rf sandbox/.runtime
