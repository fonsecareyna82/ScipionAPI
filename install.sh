#!/usr/bin/env bash
set -euo pipefail

# ScipionWeb guided installer.
#
# This script is intentionally standalone. It validates host prerequisites,
# resolves and downloads a paired ScipionAPI + ScipionWeb release, extracts the
# API into a stable installation directory, and delegates the actual runtime
# installation to `scripts/scipionapi provision`.

DEFAULT_BASE_URL="https://scipion.cnb.csic.es/downloads/scipion/scipionWeb/"
DEFAULT_INSTALL_DIR="${HOME}/scipionweb"
DEFAULT_VERSION="latest"
INSTALL_MARKER_NAME=".scipionweb-installation"
CLI_ALIAS_BEGIN="# >>> ScipionWeb scipionapi >>>"
CLI_ALIAS_END="# <<< ScipionWeb scipionapi <<<"

BASE_URL="${SCIPIONWEB_DOWNLOAD_BASE_URL:-${DEFAULT_BASE_URL}}"
INSTALL_DIR="${SCIPIONWEB_INSTALL_DIR:-${DEFAULT_INSTALL_DIR}}"
REQUESTED_VERSION="${SCIPIONWEB_VERSION:-${DEFAULT_VERSION}}"
ADMIN_USER="${SCIPIONWEB_ADMIN_USER:-}"
ADMIN_EMAIL="${SCIPIONWEB_ADMIN_EMAIL:-}"
API_PORT="${SCIPIONWEB_API_PORT:-}"
CREATE_CLI_ALIAS="${SCIPIONWEB_CREATE_ALIAS:-}"
CLI_ALIAS_CREATED=0
CHECK_ONLY=0
NON_INTERACTIVE=0
INSTALL_DIR_EXPLICIT=0

DOWNLOAD_TOOL=""
CONDA_EXE=""
CONDA_PYTHON=""
TMP_DIR=""
INSTALL_STARTED=0

MISSING_REQUIREMENTS=()
FAILED_REQUIREMENTS=()

print_line() { printf '%s\n' "$*"; }
print_header() {
  cat <<'HEADER'
============================================================
                  ScipionWeb Installer
============================================================
HEADER
}
print_step() { printf '\n--> %s\n' "$1"; }
print_ok() { printf '[OK]     %s\n' "$1"; }
print_warn() { printf '[WARN]   %s\n' "$1"; }
print_error() { printf '[ERROR]  %s\n' "$1" >&2; }

usage() {
  cat <<USAGE
Usage:
  ./install.sh [OPTIONS]

Interactive installation is the default.

Options:
  --install-dir PATH   Installation directory. Default: ${DEFAULT_INSTALL_DIR}
  --user USER          ScipionWeb administrator username.
  --email EMAIL        ScipionWeb administrator email.
  --version VERSION    Release to install, e.g. v4.0.0. Default: latest
  --base-url URL       Release download base URL.
  --api-port PORT      Optional fixed API/Web port. If omitted, provision decides.
  --create-alias       Add a managed 'scipionapi' alias to ~/.bashrc.
  --no-create-alias    Do not create the shell alias.
  --check-only         Only validate system prerequisites and exit.
  --non-interactive    Do not prompt for missing values. Password must be supplied
                       through SCIPIONWEB_ADMIN_PASSWORD.
  -h, --help           Show this help and exit.

Environment equivalents:
  SCIPIONWEB_INSTALL_DIR
  SCIPIONWEB_ADMIN_USER
  SCIPIONWEB_ADMIN_EMAIL
  SCIPIONWEB_ADMIN_PASSWORD
  SCIPIONWEB_VERSION
  SCIPIONWEB_DOWNLOAD_BASE_URL
  SCIPIONWEB_API_PORT
  SCIPIONAPI_CONDA_EXE
  SCIPIONWEB_CREATE_ALIAS


Examples:
  ./install.sh
  ./install.sh --check-only
  ./install.sh --install-dir /data/scipionweb --version v4.0.0

For unattended installation:
  SCIPIONWEB_ADMIN_PASSWORD='secret' ./install.sh \\
    --non-interactive \\
    --install-dir /data/scipionweb \\
    --user admin \\
    --email admin@example.org
USAGE
}

cleanup() {
  local exit_code=$?

  if [[ -n "${TMP_DIR}" && -d "${TMP_DIR}" ]]; then
    rm -rf "${TMP_DIR}" || true
  fi

  if [[ ${exit_code} -ne 0 && ${INSTALL_STARTED} -eq 1 ]]; then
    echo >&2
    print_error "Installation did not complete."
    print_error "The installation directory was preserved for inspection: ${INSTALL_DIR}"
    if [[ -d "${INSTALL_DIR}/scipion_home/logs" ]]; then
      print_error "Logs: ${INSTALL_DIR}/scipion_home/logs"
    fi
  fi

  exit "${exit_code}"
}
trap cleanup EXIT

need_arg() {
  local option="$1"
  local value="${2:-}"
  if [[ -z "${value}" ]]; then
    print_error "${option} requires a value."
    usage >&2
    exit 2
  fi
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --install-dir) need_arg "$1" "${2:-}"; INSTALL_DIR="$2"; INSTALL_DIR_EXPLICIT=1; shift 2 ;;
    --user) need_arg "$1" "${2:-}"; ADMIN_USER="$2"; shift 2 ;;
    --email) need_arg "$1" "${2:-}"; ADMIN_EMAIL="$2"; shift 2 ;;
    --version) need_arg "$1" "${2:-}"; REQUESTED_VERSION="$2"; shift 2 ;;
    --base-url) need_arg "$1" "${2:-}"; BASE_URL="$2"; shift 2 ;;
    --api-port) need_arg "$1" "${2:-}"; API_PORT="$2"; shift 2 ;;
    --create-alias) CREATE_CLI_ALIAS="1"; shift ;;
    --no-create-alias) CREATE_CLI_ALIAS="0"; shift ;;
    --check-only) CHECK_ONLY=1; shift ;;
    --non-interactive) NON_INTERACTIVE=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) print_error "Unknown option: $1"; usage >&2; exit 2 ;;
  esac
done

normalize_base_url() { BASE_URL="${BASE_URL%/}/"; }

resolve_conda() {
  local candidate=""
  local candidates=(
    "${SCIPIONAPI_CONDA_EXE:-}"
    "${CONDA_EXE:-}"
    "$(command -v conda 2>/dev/null || true)"
    "${HOME}/miniconda3/bin/conda"
    "${HOME}/anaconda3/bin/conda"
  )

  for candidate in "${candidates[@]}"; do
    [[ -z "${candidate}" ]] && continue
    if [[ -x "${candidate}" ]] && "${candidate}" --version >/dev/null 2>&1; then
      CONDA_EXE="${candidate}"
      return 0
    fi
  done
  return 1
}

resolve_conda_python() {
  local conda_base=""
  conda_base="$("${CONDA_EXE}" info --base 2>/dev/null || true)"
  if [[ -n "${conda_base}" && -x "${conda_base}/bin/python" ]]; then
    CONDA_PYTHON="${conda_base}/bin/python"
    return 0
  fi
  return 1
}

command_missing() { MISSING_REQUIREMENTS+=("$1"); }
service_failed() { FAILED_REQUIREMENTS+=("$1"); }

check_prerequisites() {
  print_step "Checking system requirements"

  if [[ "$(uname -s 2>/dev/null || true)" == "Linux" ]]; then
    print_ok "Linux"
  else
    service_failed "Linux is required for the supported ScipionWeb runtime."
    print_error "Linux"
  fi

  if command -v curl >/dev/null 2>&1; then
    DOWNLOAD_TOOL="curl"; print_ok "curl"
  elif command -v wget >/dev/null 2>&1; then
    DOWNLOAD_TOOL="wget"; print_ok "wget"
  else
    command_missing "curl or wget"; print_error "curl or wget is required"
  fi

  if command -v unzip >/dev/null 2>&1; then print_ok "unzip"; else command_missing "unzip"; print_error "unzip"; fi
  if command -v sudo >/dev/null 2>&1; then print_ok "sudo"; else command_missing "sudo"; print_error "sudo"; fi

  if resolve_conda; then
    print_ok "conda ($("${CONDA_EXE}" --version 2>/dev/null))"
    if resolve_conda_python; then
      print_ok "Conda base Python"
    else
      service_failed "Conda was found, but its base Python executable could not be resolved."
      print_error "Conda base Python"
    fi
  else
    command_missing "conda"; print_error "conda"
  fi

  if command -v psql >/dev/null 2>&1; then print_ok "PostgreSQL client (psql)"; else command_missing "PostgreSQL (psql)"; print_error "PostgreSQL client (psql)"; fi
  if command -v redis-cli >/dev/null 2>&1; then print_ok "Redis client (redis-cli)"; else command_missing "Redis (redis-cli)"; print_error "Redis client (redis-cli)"; fi

  if command -v redis-cli >/dev/null 2>&1; then
    if [[ "$(redis-cli ping 2>/dev/null || true)" == "PONG" ]]; then
      print_ok "Redis server is responding"
    else
      service_failed "Redis is installed but the server is not responding."
      print_error "Redis server is not responding"
    fi
  fi

  if command -v sudo >/dev/null 2>&1 && command -v psql >/dev/null 2>&1; then
    print_line "[INFO]   Checking PostgreSQL administrative access; sudo may prompt once."
    if sudo -v >/dev/null 2>&1; then
      if sudo -u postgres psql -d postgres -c "SELECT 1;" >/dev/null 2>&1; then
        print_ok "PostgreSQL server and postgres sudo access"
      else
        service_failed "PostgreSQL is installed, but local administrative access through 'sudo -u postgres psql' failed."
        print_error "PostgreSQL administrative access failed"
      fi
    else
      service_failed "sudo authentication failed; PostgreSQL bootstrap requires sudo access."
      print_error "sudo authentication failed"
    fi
  fi

  if [[ ${#MISSING_REQUIREMENTS[@]} -eq 0 && ${#FAILED_REQUIREMENTS[@]} -eq 0 ]]; then
    print_line
    print_ok "All required system prerequisites are ready."
    return 0
  fi

  echo
  print_error "System requirements are not ready."

  if [[ ${#MISSING_REQUIREMENTS[@]} -gt 0 ]]; then
    echo
    print_line "Missing software:"
    local item
    for item in "${MISSING_REQUIREMENTS[@]}"; do print_line "  - ${item}"; done
  fi

  if [[ ${#FAILED_REQUIREMENTS[@]} -gt 0 ]]; then
    echo
    print_line "Configuration/service problems:"
    local problem
    for problem in "${FAILED_REQUIREMENTS[@]}"; do print_line "  - ${problem}"; done
  fi

  cat <<'HINTS'

Ubuntu/Debian example for common system packages:
  sudo apt update
  sudo apt install -y postgresql postgresql-contrib redis-server unzip curl

Then ensure services are running:
  sudo systemctl enable --now postgresql
  sudo systemctl enable --now redis-server

If Conda is missing, install Miniconda or Anaconda first, reopen your shell,
and run this installer again. You may also set:
  SCIPIONAPI_CONDA_EXE=/absolute/path/to/conda
HINTS
  return 1
}

download_quiet() {
  local url="$1" destination="$2"
  if [[ "${DOWNLOAD_TOOL}" == "curl" ]]; then
    curl -fsSL --retry 3 --connect-timeout 20 -o "${destination}" "${url}"
  else
    wget -q --tries=3 --timeout=30 -O "${destination}" "${url}"
  fi
}

download_file() {
  local url="$1" destination="$2"
  print_line "  ${url}"
  if [[ "${DOWNLOAD_TOOL}" == "curl" ]]; then
    curl -fL --retry 3 --connect-timeout 20 --progress-bar -o "${destination}" "${url}"
  else
    wget --tries=3 --timeout=30 -O "${destination}" "${url}"
  fi
}

asset_url() {
  local value="$1"
  if [[ "${value}" =~ ^https?:// ]]; then printf '%s\n' "${value}"; else printf '%s%s\n' "${BASE_URL}" "${value}"; fi
}

normalize_version() {
  local value="$1"
  if [[ "${value}" == "latest" ]]; then printf '%s\n' "latest"; return 0; fi
  if [[ "${value}" =~ ^[0-9]+(\.[0-9]+){1,3}([-._A-Za-z0-9]*)?$ ]]; then printf 'v%s\n' "${value}"; return 0; fi
  if [[ "${value}" =~ ^v[0-9]+(\.[0-9]+){1,3}([-._A-Za-z0-9]*)?$ ]]; then printf '%s\n' "${value}"; return 0; fi
  print_error "Invalid release version: ${value}. Expected latest or values like v4.0.0."
  exit 2
}

resolve_release_from_manifest() {
  local manifest_path="$1" requested_version="$2"
  "${CONDA_PYTHON}" - "${manifest_path}" "${requested_version}" <<'PY'
import json
import re
import sys
from pathlib import Path

manifest_path = Path(sys.argv[1])
requested = sys.argv[2].strip()
with manifest_path.open("r", encoding="utf-8") as handle:
    manifest = json.load(handle)
if not isinstance(manifest, dict):
    raise SystemExit("manifest.json is not a JSON object")
version = str(manifest.get("latest") or "").strip() if requested == "latest" else requested
if version and not version.startswith("v") and re.match(r"^[0-9]+(?:\.[0-9]+){1,3}(?:[-._A-Za-z0-9]*)?$", version):
    version = f"v{version}"
if not version:
    raise SystemExit("manifest.json does not define a release version")
releases = manifest.get("releases")
if not isinstance(releases, dict):
    raise SystemExit("manifest.json does not contain a releases object")
release = releases.get(version)
if not isinstance(release, dict):
    raise SystemExit(f"release {version} is not present in manifest.json")

def parse_entry(value, fallback):
    if isinstance(value, str):
        return value, ""
    if isinstance(value, dict):
        file_name = value.get("file") or value.get("filename") or value.get("url") or fallback
        return str(file_name), str(value.get("sha256") or "")
    return fallback, ""

api_file, api_sha = parse_entry(release.get("api"), f"ScipionAPI-{version}.zip")
web_file, web_sha = parse_entry(release.get("web"), f"ScipionWeb-{version}-dist.zip")
for value in (version, api_file, api_sha, web_file, web_sha):
    print(value)
PY
}

resolve_latest_from_listing() {
  local listing_path="$1"
  "${CONDA_PYTHON}" - "${listing_path}" <<'PY'
import re
import sys
from pathlib import Path
text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
pattern = re.compile(r"ScipionAPI-(v?[0-9]+(?:\.[0-9]+){1,3}(?:[-._A-Za-z0-9]*)?)\.zip")
versions = set(pattern.findall(text))
def normalize(value): return value if value.startswith("v") else f"v{value}"
def key(value):
    value = normalize(value)
    match = re.match(r"^v?([0-9]+)(?:\.([0-9]+))?(?:\.([0-9]+))?(?:\.([0-9]+))?(.*)$", value)
    if not match: return (0, 0, 0, 0, value)
    nums = [int(match.group(i) or 0) for i in range(1, 5)]
    return (*nums, match.group(5) or "")
if not versions: raise SystemExit("no ScipionAPI release archives were found")
print(normalize(sorted(versions, key=key)[-1]))
PY
}

resolve_release() {
  local requested_version manifest_path="${TMP_DIR}/manifest.json" listing_path="${TMP_DIR}/downloads.html"
  requested_version="$(normalize_version "${REQUESTED_VERSION}")"

  print_step "Resolving ScipionWeb release"
  print_line "Base URL: ${BASE_URL}"
  print_line "Requested version: ${requested_version}"

  local manifest_ok=0
  if download_quiet "${BASE_URL}manifest.json" "${manifest_path}" 2>/dev/null; then manifest_ok=1; fi

  RELEASE_VERSION=""; API_FILE=""; API_SHA256=""; WEB_FILE=""; WEB_SHA256=""

  if [[ ${manifest_ok} -eq 1 ]]; then
    local release_values=()
    if mapfile -t release_values < <(resolve_release_from_manifest "${manifest_path}" "${requested_version}"); then
      if [[ ${#release_values[@]} -eq 5 ]]; then
        RELEASE_VERSION="${release_values[0]}"
        API_FILE="${release_values[1]}"
        API_SHA256="${release_values[2]}"
        WEB_FILE="${release_values[3]}"
        WEB_SHA256="${release_values[4]}"
      fi
    fi
  fi

  if [[ -z "${RELEASE_VERSION}" ]]; then
    print_warn "manifest.json could not resolve the requested release; using archive naming fallback."
    if [[ "${requested_version}" == "latest" ]]; then
      if ! download_quiet "${BASE_URL}" "${listing_path}"; then print_error "Could not retrieve the release directory listing."; exit 1; fi
      RELEASE_VERSION="$(resolve_latest_from_listing "${listing_path}")"
    else
      RELEASE_VERSION="${requested_version}"
    fi
    API_FILE="ScipionAPI-${RELEASE_VERSION}.zip"
    WEB_FILE="ScipionWeb-${RELEASE_VERSION}-dist.zip"
  fi

  print_ok "Resolved release: ${RELEASE_VERSION}"
  print_line "  API: ${API_FILE}"
  print_line "  Web: ${WEB_FILE}"
}

verify_sha256() {
  local file_path="$1" expected="$2"
  if [[ -z "${expected}" ]]; then
    print_warn "No published SHA256 available for $(basename "${file_path}"); skipping checksum comparison."
    return 0
  fi

  local actual
  actual="$("${CONDA_PYTHON}" - "${file_path}" <<'PY'
import hashlib, sys
digest = hashlib.sha256()
with open(sys.argv[1], "rb") as handle:
    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
        digest.update(chunk)
print(digest.hexdigest())
PY
)"

  if [[ "${actual,,}" != "${expected,,}" ]]; then
    print_error "SHA256 mismatch for $(basename "${file_path}")."
    print_error "Expected: ${expected}"
    print_error "Actual:   ${actual}"
    exit 1
  fi
  print_ok "Checksum verified: $(basename "${file_path}")"
}

normalize_install_dir() {
  INSTALL_DIR="$("${CONDA_PYTHON}" - "${INSTALL_DIR}" <<'PY'
import sys
from pathlib import Path
print(Path(sys.argv[1]).expanduser().resolve())
PY
)"
}

validate_install_dir() {
  normalize_install_dir
  if [[ -d "${INSTALL_DIR}" ]]; then
    if [[ -x "${INSTALL_DIR}/scripts/scipionapi" && -f "${INSTALL_DIR}/pyproject.toml" ]]; then
      print_error "A ScipionWeb/ScipionAPI installation already exists at: ${INSTALL_DIR}"
      print_error "Use its update command instead:"
      print_error "  cd ${INSTALL_DIR} && ./scripts/scipionapi update"
      exit 1
    fi
    if [[ -n "$(find "${INSTALL_DIR}" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null || true)" ]]; then
      print_error "Installation directory is not empty: ${INSTALL_DIR}"
      print_error "Choose an empty directory to avoid overwriting unrelated files."
      exit 1
    fi
  else
    mkdir -p "${INSTALL_DIR}" 2>/dev/null || {
      print_error "Could not create installation directory: ${INSTALL_DIR}"
      print_error "Create it with suitable ownership/permissions and run the installer again."
      exit 1
    }
  fi
  if [[ ! -w "${INSTALL_DIR}" ]]; then print_error "Installation directory is not writable: ${INSTALL_DIR}"; exit 1; fi
}

prompt_value() {
  local variable_name="$1" prompt="$2" default_value="${3:-}" current_value=""
  printf -v current_value '%s' "${!variable_name:-}"
  if [[ -n "${current_value}" ]]; then return 0; fi
  if [[ ${NON_INTERACTIVE} -eq 1 ]]; then print_error "Missing required value in non-interactive mode: ${variable_name}"; exit 2; fi

  local answer=""
  if [[ -n "${default_value}" ]]; then
    read -r -p "${prompt} [${default_value}]: " answer
    answer="${answer:-${default_value}}"
  else
    while [[ -z "${answer}" ]]; do read -r -p "${prompt}: " answer; done
  fi
  printf -v "${variable_name}" '%s' "${answer}"
}

prompt_admin_password() {
  ADMIN_PASSWORD="${SCIPIONWEB_ADMIN_PASSWORD:-}"
  if [[ -n "${ADMIN_PASSWORD}" ]]; then return 0; fi
  if [[ ${NON_INTERACTIVE} -eq 1 ]]; then print_error "SCIPIONWEB_ADMIN_PASSWORD must be set in non-interactive mode."; exit 2; fi

  local first="" second=""
  while true; do
    read -r -s -p "Admin password: " first; echo
    if [[ -z "${first}" ]]; then print_error "Password cannot be empty."; continue; fi
    read -r -s -p "Confirm password: " second; echo
    if [[ "${first}" != "${second}" ]]; then print_error "Passwords do not match. Try again."; continue; fi
    ADMIN_PASSWORD="${first}"
    return 0
  done
}

resolve_cli_alias_choice() {
  local normalized="${CREATE_CLI_ALIAS,,}"
  local answer=""

  case "${normalized}" in
    1|true|yes|y|on)
      CREATE_CLI_ALIAS=1
      return 0
      ;;
    0|false|no|n|off)
      CREATE_CLI_ALIAS=0
      return 0
      ;;
    "")
      ;;
    *)
      print_error "Invalid SCIPIONWEB_CREATE_ALIAS value: ${CREATE_CLI_ALIAS}"
      print_error "Use 1/0, true/false, yes/no, or --create-alias/--no-create-alias."
      exit 2
      ;;
  esac

  if [[ ${NON_INTERACTIVE} -eq 1 ]]; then
    CREATE_CLI_ALIAS=0
    return 0
  fi

  while true; do
    read -r -p "Create 'scipionapi' alias in ~/.bashrc? [Y/n]: " answer

    case "${answer,,}" in
      ""|y|yes)
        CREATE_CLI_ALIAS=1
        return 0
        ;;
      n|no)
        CREATE_CLI_ALIAS=0
        return 0
        ;;
      *)
        print_warn "Please answer yes or no."
        ;;
    esac
  done
}

validate_inputs() {
  if [[ ! "${ADMIN_EMAIL}" =~ ^[^[:space:]@]+@[^[:space:]@]+$ ]]; then print_error "Invalid administrator email: ${ADMIN_EMAIL}"; exit 2; fi
  if [[ -n "${API_PORT}" ]]; then
    if [[ ! "${API_PORT}" =~ ^[0-9]+$ ]]; then
      print_error "Invalid --api-port value: ${API_PORT}. Expected 1-65535."
      exit 2
    fi
    local port_number=$((10#${API_PORT}))
    if (( port_number < 1 || port_number > 65535 )); then
      print_error "Invalid --api-port value: ${API_PORT}. Expected 1-65535."
      exit 2
    fi
    API_PORT="${port_number}"
  fi
}

collect_install_inputs() {
  print_step "Installation settings"
  if [[ ${NON_INTERACTIVE} -eq 0 && ${INSTALL_DIR_EXPLICIT} -eq 0 ]]; then
    local answer=""
    read -r -p "Installation directory [${INSTALL_DIR}]: " answer
    INSTALL_DIR="${answer:-${INSTALL_DIR}}"
  fi

  prompt_value ADMIN_USER "Admin username" "admin"
  prompt_value ADMIN_EMAIL "Admin email"
  prompt_admin_password
  validate_inputs
  validate_install_dir
  resolve_cli_alias_choice

  print_line
  print_line "Installation directory: ${INSTALL_DIR}"
  print_line "Admin username:       ${ADMIN_USER}"
  print_line "Admin email:          ${ADMIN_EMAIL}"
  print_line "CLI alias:            $([[ ${CREATE_CLI_ALIAS} -eq 1 ]] && echo yes || echo no)"
  print_line "Release:              ${REQUESTED_VERSION}"
  if [[ -n "${API_PORT}" ]]; then print_line "API/Web port:         ${API_PORT}"; else print_line "API/Web port:         automatic / provision default"; fi
}

extract_api() {
  local api_zip="$1" extract_dir="${TMP_DIR}/api-extracted" marker="" api_root=""
  print_step "Extracting ScipionAPI"
  mkdir -p "${extract_dir}"
  unzip -q "${api_zip}" -d "${extract_dir}"

  if [[ -f "${extract_dir}/pyproject.toml" && -f "${extract_dir}/alembic.ini" ]]; then
    api_root="${extract_dir}"
  else
    marker="$(find "${extract_dir}" -mindepth 2 -maxdepth 4 -type f -name pyproject.toml -print -quit || true)"
    if [[ -n "${marker}" ]]; then api_root="$(dirname "${marker}")"; fi
  fi

  if [[ -z "${api_root}" || ! -f "${api_root}/pyproject.toml" || ! -f "${api_root}/alembic.ini" || ! -d "${api_root}/app" || ! -d "${api_root}/scipionapi_cli" || ! -f "${api_root}/scripts/scipionapi" ]]; then
    print_error "Downloaded ScipionAPI archive does not have the expected layout."
    exit 1
  fi

  cp -a "${api_root}/." "${INSTALL_DIR}/"
  chmod +x "${INSTALL_DIR}/scripts/scipionapi"
  print_ok "ScipionAPI extracted to ${INSTALL_DIR}"
}

configure_cli_alias() {
  CLI_ALIAS_CREATED=0

  if [[ "${CREATE_CLI_ALIAS}" != "1" ]]; then
    return 0
  fi

  local bashrc_path="${HOME}/.bashrc"
  local cli_target="${INSTALL_DIR}/scripts/scipionapi"
  local escaped_target=""
  local begin_count=0
  local end_count=0
  local tmp_file=""

  if [[ ! -x "${cli_target}" ]]; then
    print_warn "Cannot create CLI alias because the wrapper was not found: ${cli_target}"
    return 0
  fi

  if ! touch "${bashrc_path}" 2>/dev/null; then
    print_warn "Could not write ${bashrc_path}; skipping CLI alias."
    return 0
  fi

  begin_count="$(grep -Fxc -- "${CLI_ALIAS_BEGIN}" "${bashrc_path}" || true)"
  end_count="$(grep -Fxc -- "${CLI_ALIAS_END}" "${bashrc_path}" || true)"

  if [[ "${begin_count}" != "${end_count}" ]]; then
    print_warn "Found a malformed ScipionWeb alias block in ${bashrc_path}; leaving it unchanged."
    return 0
  fi

  printf -v escaped_target '%q' "${cli_target}"

  tmp_file="$(mktemp -t scipionweb-bashrc-XXXXXX)"

  awk \
    -v begin="${CLI_ALIAS_BEGIN}" \
    -v end="${CLI_ALIAS_END}" '
      $0 == begin {
        inside = 1
        next
      }

      inside && $0 == end {
        inside = 0
        next
      }

      !inside {
        print
      }
    ' "${bashrc_path}" > "${tmp_file}"

  {
    cat "${tmp_file}"
    printf '\n%s\n' "${CLI_ALIAS_BEGIN}"
    printf '# installation: %s\n' "${INSTALL_DIR}"
    printf 'alias scipionapi=%s\n' "${escaped_target}"
    printf '%s\n' "${CLI_ALIAS_END}"
  } > "${tmp_file}.new"

  if ! cat "${tmp_file}.new" > "${bashrc_path}"; then
    rm -f "${tmp_file}" "${tmp_file}.new"
    print_warn "Could not update ${bashrc_path}; skipping CLI alias."
    return 0
  fi

  rm -f "${tmp_file}" "${tmp_file}.new"

  CLI_ALIAS_CREATED=1
  print_ok "CLI alias installed in ${bashrc_path}: scipionapi"
}

write_install_marker() {
  local marker_path="${INSTALL_DIR}/${INSTALL_MARKER_NAME}"

  cat > "${marker_path}" <<EOF
FORMAT=1
INSTALL_TYPE=guided
INSTALL_ROOT=${INSTALL_DIR}
SCIPION_HOME=${INSTALL_DIR}/scipion_home
VERSION=${RELEASE_VERSION}
EOF

  chmod 0644 "${marker_path}"
  print_ok "Guided installation marker created: ${marker_path}"
}

run_provision() {
  local web_zip="$1"
  local provision_args=(provision --user "${ADMIN_USER}" --email "${ADMIN_EMAIL}" --password-env SCIPIONWEB_INSTALL_ADMIN_PASS --web-dist "${web_zip}")
  if [[ -n "${API_PORT}" ]]; then provision_args+=(--api-port "${API_PORT}"); fi

  print_step "Running ScipionWeb provision"
  print_line "The installer now delegates bootstrap, database setup, migrations,"
  print_line "web deployment and service startup to scripts/scipionapi provision."

  INSTALL_STARTED=1
  export SCIPIONAPI_CONDA_EXE="${CONDA_EXE}"
  export CONDA_EXE="${CONDA_EXE}"
  export SCIPION_HOME="${INSTALL_DIR}/scipion_home"
  export SCIPIONWEB_INSTALL_ADMIN_PASS="${ADMIN_PASSWORD}"

  (cd "${INSTALL_DIR}" && ./scripts/scipionapi "${provision_args[@]}")

  unset SCIPIONWEB_INSTALL_ADMIN_PASS
  ADMIN_PASSWORD=""
}

read_env_value() {
  local key="$1" env_file="${INSTALL_DIR}/scipion_home/.env"
  if [[ ! -f "${env_file}" ]]; then return 0; fi
  grep -E "^${key}=" "${env_file}" | tail -n 1 | cut -d= -f2- || true
}

print_success_summary() {
  local api_port serve_web hostname_value
  api_port="$(read_env_value API_PORT)"
  serve_web="$(read_env_value SERVE_WEB)"
  hostname_value="$(hostname -f 2>/dev/null || hostname 2>/dev/null || true)"

  echo
  cat <<'SUCCESS'
============================================================
              ScipionWeb installed successfully
============================================================
SUCCESS
  print_line "Version:      ${RELEASE_VERSION}"
  print_line "Installation: ${INSTALL_DIR}"

  if [[ -n "${api_port}" ]]; then
    print_line "Web (local):  http://127.0.0.1:${api_port}/"
    print_line "API docs:     http://127.0.0.1:${api_port}/api/docs"
    if [[ -n "${hostname_value}" && "${hostname_value}" != "localhost" ]]; then
      print_line "Web (server): http://${hostname_value}:${api_port}/  (if reachable from your network)"
    fi
  fi

  if [[ "${serve_web}" != "1" ]]; then print_warn "SERVE_WEB is not enabled in the final environment. Check provision output."; fi

  if [[ ${CLI_ALIAS_CREATED} -eq 1 ]]; then
  cat <<SUMMARY

CLI shortcut installed:
  scipionapi

Open a new terminal or run:
  source ~/.bashrc

Useful commands:
  scipionapi status
  scipionapi logs
  scipionapi restart
  scipionapi stop
  scipionapi update
  scipionapi uninstall --full
============================================================
SUMMARY
else
  cat <<SUMMARY

Useful commands:
  cd ${INSTALL_DIR}
  ./scripts/scipionapi status
  ./scripts/scipionapi logs
  ./scripts/scipionapi restart
  ./scripts/scipionapi stop
  ./scripts/scipionapi update
  ./scripts/scipionapi uninstall --full
============================================================
SUMMARY
fi
}

main() {
  if [[ -n "${SCIPIONWEB_INSTALL_DIR:-}" ]]; then INSTALL_DIR_EXPLICIT=1; fi
  normalize_base_url
  print_header

  if [[ ${CHECK_ONLY} -eq 0 && ${EUID} -eq 0 ]]; then
    print_error "Do not run the whole installer as root or with sudo."
    print_error "Run it as the target user; it will request sudo only when PostgreSQL setup needs it."
    exit 1
  fi

  if ! check_prerequisites; then exit 1; fi
  if [[ ${CHECK_ONLY} -eq 1 ]]; then echo; print_ok "Prerequisite check completed successfully."; exit 0; fi

  collect_install_inputs
  TMP_DIR="$(mktemp -d -t scipionweb-install-XXXXXX)"
  resolve_release

  local api_zip="${TMP_DIR}/${API_FILE##*/}"
  local web_zip="${TMP_DIR}/${WEB_FILE##*/}"

  print_step "Downloading ScipionWeb release ${RELEASE_VERSION}"
  print_line "ScipionAPI:"
  download_file "$(asset_url "${API_FILE}")" "${api_zip}"
  print_line "ScipionWeb:"
  download_file "$(asset_url "${WEB_FILE}")" "${web_zip}"

  print_step "Verifying release archives"
  verify_sha256 "${api_zip}" "${API_SHA256}"
  verify_sha256 "${web_zip}" "${WEB_SHA256}"

  extract_api "${api_zip}"
  run_provision "${web_zip}"
  write_install_marker
  configure_cli_alias
  print_success_summary
}

main "$@"