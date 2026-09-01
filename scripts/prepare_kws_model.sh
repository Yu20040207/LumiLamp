#!/usr/bin/env bash
set -euo pipefail

MODEL_URL='https://github.com/k2-fsa/sherpa-onnx/releases/download/kws-models/sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20.tar.bz2'
MODEL_NAME='sherpa-onnx-kws-zipformer-zh-en-3M-2025-12-20'

usage() {
    printf 'Usage: %s DESTINATION\n' "${0##*/}" >&2
    exit 2
}

fail() {
    printf 'Error: %s\n' "$*" >&2
    exit 1
}

[[ $# -eq 1 ]] || usage
destination=$1
destination_parent=$(dirname -- "$destination")

[[ ! -e "$destination" ]] || fail "destination already exists: $destination"
[[ -d "$destination_parent" ]] || fail "destination parent does not exist: $destination_parent"

temporary_dir=$(mktemp -d)
staging_dir=$(mktemp -d -- "$destination_parent/.${MODEL_NAME}.staging.XXXXXX")
trap 'rm -rf -- "$temporary_dir" "$staging_dir"' EXIT
archive="$temporary_dir/$MODEL_NAME.tar.bz2"
model_dir="$temporary_dir/$MODEL_NAME"
keywords_file="$model_dir/keywords_lumilamp.txt"
raw_keywords_file="$temporary_dir/keywords_lumilamp.raw"
staged_model_dir="$staging_dir/$MODEL_NAME"

curl --fail --location --output "$archive" "$MODEL_URL"
tar -xjf "$archive" -C "$temporary_dir"

[[ -d "$model_dir" ]] || fail "archive did not contain $MODEL_NAME"

for model_file in \
    encoder-epoch-13-avg-2-chunk-8-left-64.int8.onnx \
    decoder-epoch-13-avg-2-chunk-8-left-64.onnx \
    joiner-epoch-13-avg-2-chunk-8-left-64.int8.onnx \
    tokens.txt \
    en.phone; do
    [[ -f "$model_dir/$model_file" ]] || fail "model file is missing: $model_file"
done

printf '露米 @露米\n你好露米 @你好露米\n' > "$raw_keywords_file"
sherpa-onnx-cli text2token \
    --tokens "$model_dir/tokens.txt" \
    --tokens-type phone+ppinyin \
    --lexicon "$model_dir/en.phone" \
    "$raw_keywords_file" \
    "$keywords_file"

validate_keyword_line() {
    local line=$1
    local expected_label=$2
    local token
    local index
    local -a fields

    read -r -a fields <<< "$line"
    [[ ${#fields[@]} -gt 1 ]] || fail "keyword line has no phoneme tokens"
    [[ ${fields[${#fields[@]} - 1]} == "$expected_label" ]] || \
        fail "keyword label is missing or invalid: $expected_label"

    for ((index = 0; index < ${#fields[@]} - 1; index++)); do
        token=${fields[index]}
        case "$token" in
            :*|\#*) continue ;;
        esac
        awk -v token="$token" '$1 == token { found = 1 } END { exit !found }' \
            "$model_dir/tokens.txt" || fail "token is missing from tokens.txt: $token"
    done
}

mapfile -t keyword_lines < "$keywords_file"
[[ ${#keyword_lines[@]} -eq 2 ]] || fail "keyword file must contain exactly two lines"
validate_keyword_line "${keyword_lines[0]}" '@露米'
validate_keyword_line "${keyword_lines[1]}" '@你好露米'

[[ -f "$keywords_file" ]] || fail "keyword file was not created"
cp -a -- "$model_dir" "$staging_dir"
mv --no-clobber --no-target-directory -- "$staged_model_dir" "$destination"
[[ ! -e "$staged_model_dir" ]] || fail "destination already exists: $destination"
printf 'Prepared KWS model at %s\n' "$destination"
