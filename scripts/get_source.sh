#!/usr/bin/env bash
# Download Fisher Catalog 12 (D103182X012) and Catalog 14 (D103428X012) and check they are the
# editions this data was extracted from.
set -euo pipefail
cd "$(dirname "$0")/.."
BASE="https://www.emerson.com/is/content/emerson/en/final-control/flow-controls/documents"
mkdir -p data/source
fetch() {
  curl -sSL -o "data/source/$1" "$BASE/$1"
  echo "$2  data/source/$1" | sha256sum -c - || {
    echo "data/source/$1 differs from the edition used for data/ (Emerson may have published a new one)."
    echo "Re-run 'make data' and review the flags and second-reader checks before trusting the output."
    exit 1
  }
}
fetch d103182x012.pdf c40ea5fe30368b6e9f24e13d2a822425e62f361a3b2a27935cafafa510acf355
fetch d103428x012.pdf 869ca15dfa76a710d0048ef45f022fe99a9ea278ee4acde67c02207c692e542e
