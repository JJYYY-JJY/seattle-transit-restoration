#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-${ROOT_DIR}/.env.data}"

if [[ -f "${ENV_FILE}" ]]; then
  # shellcheck disable=SC1090
  source "${ENV_FILE}"
fi

UTC_DATE="$(date -u +%F)"
UTC_TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
RAW_DIR="${ROOT_DIR}/data/raw"
LOG_FILE="${RAW_DIR}/download_log.csv"

mkdir -p \
  "${RAW_DIR}/gtfs_current" \
  "${RAW_DIR}/gtfs_archive" \
  "${RAW_DIR}/noaa" \
  "${RAW_DIR}/acs"

init_log() {
  if [[ ! -f "${LOG_FILE}" ]]; then
    echo "utc_timestamp,source,artifact,file_path,url" > "${LOG_FILE}"
  fi
}

log_download() {
  local source_name="$1"
  local artifact="$2"
  local file_path="$3"
  local url="$4"
  echo "${UTC_TS},${source_name},${artifact},${file_path},${url}" >> "${LOG_FILE}"
}

require_var() {
  local var_name="$1"
  if [[ -z "${!var_name:-}" ]]; then
    echo "Missing required environment variable: ${var_name}" >&2
    echo "Set it in ${ENV_FILE} (or export it before running)." >&2
    exit 1
  fi
}

download_kcm_static() {
  local outdir="${RAW_DIR}/gtfs_current"
  local url_main="https://metro.kingcounty.gov/GTFS/google_transit.zip"
  local url_daily="https://metro.kingcounty.gov/GTFS/google_daily_transit.zip"

  local main_zip="${outdir}/google_transit_${UTC_DATE}.zip"
  local daily_zip="${outdir}/google_daily_transit_${UTC_DATE}.zip"

  echo "Downloading official King County Metro static GTFS..."
  curl -fL --retry 3 --retry-delay 2 -o "${main_zip}" "${url_main}"
  cp -f "${main_zip}" "${outdir}/google_transit_current.zip"
  log_download "kcm_static" "google_transit" "${main_zip}" "${url_main}"

  echo "Downloading official King County Metro daily GTFS..."
  curl -fL --retry 3 --retry-delay 2 -o "${daily_zip}" "${url_daily}"
  cp -f "${daily_zip}" "${outdir}/google_daily_transit_current.zip"
  log_download "kcm_static" "google_daily_transit" "${daily_zip}" "${url_daily}"
}

download_noaa() {
  require_var NOAA_TOKEN

  local station_id="${NOAA_STATION_ID:-GHCND:USW00024233}"
  local start_date="${NOAA_START_DATE:-$(date -u +%Y)-01-01}"
  local end_date="${NOAA_END_DATE:-${UTC_DATE}}"
  local datatypes="${NOAA_DATATYPES:-PRCP TMAX TMIN AWND}"
  local outdir="${RAW_DIR}/noaa"
  local base="https://www.ncei.noaa.gov/cdo-web/api/v2"

  echo "Downloading NOAA station metadata..."
  local station_safe="${station_id//:/_}"
  local station_meta_file="${outdir}/station_${station_safe}.json"
  local station_meta_url="${base}/stations/${station_id}"
  curl -fL --retry 3 --retry-delay 2 -H "token: ${NOAA_TOKEN}" "${station_meta_url}" -o "${station_meta_file}"
  log_download "noaa" "station_metadata" "${station_meta_file}" "${station_meta_url}"

  echo "Downloading NOAA daily summaries (${start_date} to ${end_date})..."
  for datatype in ${datatypes}; do
    local noaa_url="${base}/data?datasetid=GHCND&stationid=${station_id}&datatypeid=${datatype}&startdate=${start_date}&enddate=${end_date}&units=metric&limit=1000"
    local out_file="${outdir}/${datatype}_${start_date}_${end_date}_${station_safe}.json"

    curl -fL --retry 3 --retry-delay 2 -H "token: ${NOAA_TOKEN}" "${noaa_url}" -o "${out_file}"
    log_download "noaa" "${datatype}" "${out_file}" "${noaa_url}"
  done
}

download_acs() {
  local year="${ACS_YEAR:-2023}"
  local state_fips="${ACS_STATE_FIPS:-53}"
  local county_fips="${ACS_COUNTY_FIPS:-033}"
  local acs_vars="${ACS_GET_VARS:-NAME,B01001_001E}"
  local outdir="${RAW_DIR}/acs"
  local base="https://api.census.gov/data/${year}/acs/acs5"

  local key_args=()
  if [[ -n "${CENSUS_KEY:-}" ]]; then
    key_args+=(--data-urlencode "key=${CENSUS_KEY}")
  fi

  echo "Downloading ACS tract-level data..."
  local tracts_file="${outdir}/acs5_${year}_state${state_fips}_county${county_fips}_tracts.json"
  curl -fsSLG "${base}" \
    --data-urlencode "get=${acs_vars}" \
    --data-urlencode "for=tract:*" \
    --data-urlencode "in=state:${state_fips}" \
    --data-urlencode "in=county:${county_fips}" \
    "${key_args[@]}" \
    -o "${tracts_file}"
  log_download "acs" "tracts" "${tracts_file}" "${base}?for=tract:*"

  echo "Downloading ACS block-group-level data..."
  local block_groups_file="${outdir}/acs5_${year}_state${state_fips}_county${county_fips}_block_groups.json"
  curl -fsSLG "${base}" \
    --data-urlencode "get=${acs_vars}" \
    --data-urlencode "for=block group:*" \
    --data-urlencode "in=state:${state_fips}" \
    --data-urlencode "in=county:${county_fips}" \
    --data-urlencode "in=tract:*" \
    "${key_args[@]}" \
    -o "${block_groups_file}"
  log_download "acs" "block_groups" "${block_groups_file}" "${base}?for=block%20group:*"

  echo "Downloading ACS variable catalog..."
  local vars_url="https://api.census.gov/data/${year}/acs/acs5/variables.html"
  local vars_file="${outdir}/acs5_${year}_variables.html"
  curl -fL --retry 3 --retry-delay 2 "${vars_url}" -o "${vars_file}"
  log_download "acs" "variables" "${vars_file}" "${vars_url}"
}

download_transitland_versions() {
  require_var TRANSITLAND_API_KEY

  local feed_id="${TRANSITLAND_FEED_ID:-f-c23-metrokingcounty}"
  local limit="${TRANSITLAND_LIMIT:-20}"
  local outdir="${RAW_DIR}/gtfs_archive"
  local url="https://transit.land/api/v2/rest/feeds/${feed_id}/feed_versions?apikey=${TRANSITLAND_API_KEY}&limit=${limit}"
  local out_file="${outdir}/transitland_${feed_id}_feed_versions_${UTC_DATE}.json"

  echo "Listing Transitland feed versions..."
  curl -fL --retry 3 --retry-delay 2 "${url}" -o "${out_file}"
  log_download "transitland" "feed_versions" "${out_file}" "${url}"
}

download_transitland_latest() {
  require_var TRANSITLAND_API_KEY

  local feed_id="${TRANSITLAND_FEED_ID:-f-c23-metrokingcounty}"
  local outdir="${RAW_DIR}/gtfs_archive"
  local url="https://transit.land/api/v2/rest/feeds/${feed_id}/download_latest_feed_version?apikey=${TRANSITLAND_API_KEY}"
  local out_file="${outdir}/kcm_latest_from_transitland_${UTC_DATE}.zip"

  echo "Downloading latest Transitland GTFS archive for ${feed_id}..."
  curl -fL --retry 3 --retry-delay 2 "${url}" -o "${out_file}"
  log_download "transitland" "latest_feed_version" "${out_file}" "${url}"
}

download_transitland_version() {
  require_var TRANSITLAND_API_KEY

  local feed_version_key="$1"
  local outdir="${RAW_DIR}/gtfs_archive"
  local url="https://transit.land/api/v2/rest/feed_versions/${feed_version_key}/download?apikey=${TRANSITLAND_API_KEY}"
  local out_file="${outdir}/kcm_${UTC_DATE}_${feed_version_key}.zip"

  echo "Downloading Transitland historic GTFS version ${feed_version_key}..."
  curl -fL --retry 3 --retry-delay 2 "${url}" -o "${out_file}"
  log_download "transitland" "historic_feed_version" "${out_file}" "${url}"
}

print_usage() {
  cat <<'EOF'
Usage:
  scripts/download_data.sh [command] [args]

Commands:
  all                          Download KCM static, NOAA, ACS, and Transitland latest+versions (if key exists)
  kcm-static                   Download official KCM static GTFS zips
  noaa                         Download NOAA station metadata + PRCP/TMAX/TMIN/AWND JSONs
  acs                          Download ACS tract + block group + variables catalog
  transitland-versions         List Transitland feed versions for KCM
  transitland-latest           Download latest Transitland feed version for KCM
  transitland-version <sha1>   Download one specific Transitland feed version by key

Environment loading:
  Copy scripts/data_sources.env.example to .env.data and fill values,
  or export variables directly in your shell.
EOF
}

main() {
  local command="${1:-all}"

  case "${command}" in
    help|-h|--help)
      print_usage
      return 0
      ;;
  esac

  init_log

  case "${command}" in
    all)
      download_kcm_static
      download_noaa
      download_acs
      if [[ -n "${TRANSITLAND_API_KEY:-}" ]]; then
        download_transitland_versions
        download_transitland_latest
      else
        echo "TRANSITLAND_API_KEY is not set; skipping Transitland steps."
      fi
      ;;
    kcm-static)
      download_kcm_static
      ;;
    noaa)
      download_noaa
      ;;
    acs)
      download_acs
      ;;
    transitland-versions)
      download_transitland_versions
      ;;
    transitland-latest)
      download_transitland_latest
      ;;
    transitland-version)
      if [[ $# -lt 2 ]]; then
        echo "Missing feed_version_key. Example:" >&2
        echo "  scripts/download_data.sh transitland-version 979571bcf26a6fc5f1f2f10b710b545b0fbeea24" >&2
        exit 1
      fi
      download_transitland_version "$2"
      ;;
    *)
      echo "Unknown command: ${command}" >&2
      print_usage
      exit 1
      ;;
  esac

  echo "Done. Download log: ${LOG_FILE}"
}

main "$@"
