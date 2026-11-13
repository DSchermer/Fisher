PDF := data/source/d103182x012.pdf

.PHONY: source data test

source:            ## download the catalog PDF and check its hash
	scripts/get_source.sh

data: $(PDF)       ## extract, validate and cross-check (needs pdfplumber and poppler-utils)
	python3 extract/parse_tables.py $(PDF) docs/page_inventory.csv data data/extract_report.json
	python3 extract/validate.py data
	python3 extract/crosscheck.py $(PDF) data
	python3 extract/reference_tables.py $(PDF) data/reference

test:              ## run the tests (standard library only)
	python3 -m unittest discover -s tests -t .

$(PDF):
	scripts/get_source.sh
