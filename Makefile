.PHONY: install run chat eval budget markup test

PAIR_A=data/samples/pair_001_lift_gas_KA901_A.pdf
PAIR_B=data/samples/pair_001_export_gas_KA902_B.pdf
OUT=output/pair_001

install:
	python -m pip install -r requirements.txt

run:
	python -m src.cli run --a $(PAIR_A) --b $(PAIR_B) \
		--pid-a pair_001:lift_gas:A --pid-b pair_001:export_gas:B \
		--rev-a "Lift Gas KA-901" --rev-b "Export Gas KA-902" --out $(OUT)

chat:
	python -m src.cli chat --session $(OUT)

eval:
	python -m eval.run_eval

budget:
	python -m eval.cost_latency_report

markup:
	@echo "Delta markup overlay is a bonus item and is not implemented in this cut."
	@echo "See README 'What we cut and why' for the intended design (draw boxes from"
	@echo "delta.json bboxes back onto the PID B page using PyMuPDF annotations)."

test:
	python -m pytest tests -q
