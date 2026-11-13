PDF := data/source/d103182x012.pdf
PDF14 := data/source/d103428x012.pdf

.PHONY: source data test

source:            ## download the catalog PDF and check its hash
	scripts/get_source.sh

data: $(PDF) $(PDF14)  ## extract, validate and cross-check (needs pdfplumber and poppler-utils)
	python3 extract/parse_tables.py $(PDF) docs/page_inventory.csv data data/extract_report.json
	python3 extract/validate.py data
	python3 extract/crosscheck.py $(PDF) data
	python3 extract/reference_tables.py $(PDF) data/reference
	python3 extract/digitize_charts.py $(PDF) data/reference
	python3 extract/catalog14_tables.py $(PDF14) data/catalog14
	python3 extract/catalog14_dp.py $(PDF14) data/catalog14
	python3 extract/catalog14_force.py $(PDF14) data/catalog14/force
	python3 extract/catalog14_torque.py $(PDF14) data/catalog14/torque
	python3 extract/catalog14_values.py $(PDF14) data/catalog14
	python3 extract/catalog14_torque_factors.py data/catalog14
	python3 extract/catalog14_actuator_torque.py data/catalog14
	python3 extract/link_catalogs.py data/links
	python3 extract/build_db.py data/fisher.db docs/DATA_MODEL.md

test:              ## run the tests (standard library only)
	python3 -m unittest discover -s tests -t .

$(PDF) $(PDF14):
	scripts/get_source.sh
