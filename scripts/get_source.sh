#!/usr/bin/env bash
# Download Fisher Catalog 12 (D103182X012) and check it is the edition this data was extracted from.
set -euo pipefail
cd "$(dirname "$0")/.."
URL="https://www.emerson.com/is/content/emerson/en/final-control/flow-controls/documents/d103182x012.pdf"
SHA256="c40ea5fe30368b6e9f24e13d2a822425e62f361a3b2a27935cafafa510acf355"
mkdir -p data/source
curl -sSL -o data/source/d103182x012.pdf "$URL"
echo "$SHA256  data/source/d103182x012.pdf" | sha256sum -c - || {
  echo "The downloaded PDF differs from the edition used for data/ (Emerson may have published a new one)."
  echo "Re-run 'make data' and review data/flags.csv and data/crosscheck.csv before trusting the output."
  exit 1
}
