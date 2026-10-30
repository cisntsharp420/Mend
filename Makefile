PY ?= python3
# LLM backend for the llm-* targets: llm (Claude) or llm_openai (OpenAI).
AGENT ?= llm
# Load .env if present (for ANTHROPIC_API_KEY).
-include .env
export

.PHONY: install wheels up down status test baselines llm-dev llm-heldout ablations report clean

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

llm-dev:            ## LLM agent on the dev split
	$(PY) -m recovery run --agent $(AGENT) --scenarios dev --tag $(AGENT)-dev

llm-heldout:        ## LLM agent on the held-out split, 2 repeats
	$(PY) -m recovery run --agent $(AGENT) --scenarios heldout --repeats 2 --tag $(AGENT)-heldout

ablations:          ## LLM ablations on the held-out split
	for v in no_verify no_changes no_diagnostics minimal_prompt; do \
	  $(PY) -m recovery run --agent $(AGENT) --variant $$v --scenarios heldout --tag $(AGENT)-ablation-$$v; done

report:             ## regenerate docs/results.md from the runs in runs/
	$(PY) -m recovery report $(TAGS) --out docs/results.md

clean:
	rm -rf sandbox/.runtime
