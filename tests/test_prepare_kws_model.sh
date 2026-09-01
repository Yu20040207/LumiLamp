#!/usr/bin/env bash
set -euo pipefail

repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
script="$repo_root/scripts/prepare_kws_model.sh"
temporary_dir=$(mktemp -d)
trap 'rm -rf -- "$temporary_dir"' EXIT
fake_bin="$temporary_dir/fake-bin"
mkdir -- "$fake_bin"

make_fake_commands() {
    printf '%s\n' \
        '#!/usr/bin/env bash' \
        'set -euo pipefail' \
        'output=' \
        'while [[ $# -gt 0 ]]; do' \
        '    case $1 in' \
        '        --output) output=$2; shift 2 ;;' \
        '        *) shift ;;' \
        '    esac' \
        'done' \
        'printf archive > "$output"' > "$fake_bin/curl"

    printf '%s\n' \
        '#!/usr/bin/env bash' \
        'set -euo pipefail' \
        'destination=' \
        'while [[ $# -gt 0 ]]; do' \
        '    case $1 in' \
        '        -C) destination=$2; shift 2 ;;' \
        '        *) shift ;;' \
        '    esac' \
        'done' \
        'model="$destination/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20"' \
        'mkdir -p -- "$model"' \
        ': > "$model/encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx"' \
        ': > "$model/decoder-epoch-13-avg-2-chunk-8-left-64.onnx"' \
        ': > "$model/joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx"' \
        'printf '\''l 1\nu 2\nm 3\ni 4\nn 5\nh 6\nao 7\n'\'' > "$model/tokens.txt"' \
        ': > "$model/en.phone"' > "$fake_bin/tar"

    printf '%s\n' \
        '#!/usr/bin/env bash' \
        'set -euo pipefail' \
        '[[ ${1:-} == text2token ]] || exit 20' \
        'shift' \
        '[[ ${1:-} == --tokens && ${2:-} == */tokens.txt ]] || exit 21' \
        'shift 2' \
        '[[ ${1:-} == --tokens-type && ${2:-} == phone+ppinyin ]] || exit 22' \
        'shift 2' \
        '[[ ${1:-} == --lexicon && ${2:-} == */en.phone ]] || exit 23' \
        'shift 2' \
        '[[ $# -eq 2 ]] || exit 24' \
        'raw=$1' \
        'output=$2' \
        '[[ $(sed -n '\''1p'\'' "$raw") == '\''露米 @露米'\'' ]] || exit 25' \
        '[[ $(sed -n '\''2p'\'' "$raw") == '\''你好露米 @你好露米'\'' ]] || exit 26' \
        '[[ $(sed -n '\''3p'\'' "$raw") == "" ]] || exit 27' \
        'printf '\''l u m i @露米\nn i h ao l u m i @你好露米\n'\'' > "$output"' \
        > "$fake_bin/sherpa-onnx-cli"

    printf '%s\n' \
        '#!/usr/bin/env bash' \
        'set -euo pipefail' \
        'destination=${!#}' \
        'if [[ ${FINAL_DESTINATION:-} == "$destination" ]]; then' \
        '    mkdir -- "$destination"' \
        '    printf occupied > "$destination/sentinel"' \
        'fi' \
        'exec /bin/cp "$@"' > "$fake_bin/cp"

    printf '%s\n' \
        '#!/usr/bin/env bash' \
        'set -euo pipefail' \
        'destination=${!#}' \
        'if [[ ${PUBLISH_DESTINATION:-} == "$destination" ]]; then' \
        '    mkdir -- "$destination"' \
        '    printf occupied > "$destination/sentinel"' \
        'fi' \
        'exec /bin/mv "$@"' > "$fake_bin/mv"

    chmod +x "$fake_bin/curl" "$fake_bin/tar" "$fake_bin/sherpa-onnx-cli" \
        "$fake_bin/cp" "$fake_bin/mv"
}

fail() {
    printf 'FAIL: %s\n' "$*" >&2
    exit 1
}

make_fake_commands

test_refuses_destination_created_at_publish() {
    local destination="$temporary_dir/published model"

    if PATH="$fake_bin:$PATH" FINAL_DESTINATION="$destination" \
        PUBLISH_DESTINATION="$destination" "$script" "$destination"; then
        fail 'script succeeded after destination appeared at publication'
    fi

    [[ -f "$destination/sentinel" ]] || fail 'test did not create competing destination'
    [[ ! -e "$destination/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20" ]] || \
        fail 'script wrote a model into the competing destination'
}

test_generates_phone_keywords_with_labels() {
    local destination="$temporary_dir/phone-keyword-model"

    PATH="$fake_bin:$PATH" "$script" "$destination"

    cmp -s <(printf 'l u m i @露米\nn i h ao l u m i @你好露米\n') \
        "$destination/keywords_lumilamp.txt" || \
        fail 'script did not publish the expected phone+ppinyin keyword lines'
}

test_accepts_dash_prefixed_destination_with_spaces() {
    local working_dir="$temporary_dir/dash destination"
    local destination='-prepared model'
    mkdir -- "$working_dir"

    (
        cd -- "$working_dir"
        PATH="$fake_bin:$PATH" "$script" "$destination"
    )

    [[ -f "$working_dir/$destination/tokens.txt" ]] || \
        fail 'dash-prefixed destination was not prepared'
}

test_generates_phone_keywords_with_labels
test_refuses_destination_created_at_publish
test_accepts_dash_prefixed_destination_with_spaces
printf 'PASS: prepare_kws_model shell behavior\n'
