"""Command to generate merged output."""

import argparse
import collections
import json
import logging
from pathlib import Path

import yaml

_LOGGER = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
INTENTS_DIR = ROOT / "intents"

IMPORTANT_INTENTS = {"HassTurnOn", "HassTurnOff"}


def convert_slot_combination_group(
    group: dict, combo_name: str, combo_info: dict
) -> dict:
    """Convert a single new-format data group into the old hassil data format.

    The new slot-combination format keeps domain information in ``name_domains``
    / ``inferred_domain`` and relies on ``intents.yaml`` for ``context_area``.
    The old format expects this to be expressed through ``slots`` and
    ``requires_context`` instead. This mirrors the conversion done in
    ``intents/tests/test_slot_combinations.py``.

    ``name_domains`` may be a string naming a reusable set defined in
    ``intents.yaml`` (``name_domain_groups``); it is resolved to a concrete
    list of domains here so the exported JSON only ever contains lists.
    """
    slots = dict(group.get("slots", {}))
    requires_context = dict(group.get("requires_context", {}))
    metadata = dict(group.get("metadata", {}))

    name_domains = group.get("name_domains")
    inferred_domain = group.get("inferred_domain")
    if name_domains:
        if isinstance(name_domains, str):
            # Named group defined in intents.yaml (name_domain_groups)
            name_domains = combo_info["name_domain_groups"][name_domains]
        # {name} is restricted to entities with one of these domains
        requires_context["domain"] = name_domains
    elif inferred_domain:
        # Domain is inferred from the words in the sentence
        slots["domain"] = inferred_domain

    if combo_info.get("context_area"):
        # Area comes from the voice satellite's context
        requires_context["area"] = {"slot": True}

    # Record the slot combination so consumers (and tests) can identify it
    metadata["slot_combination"] = combo_name

    entry: dict = {"sentences": list(group["sentences"]), "metadata": metadata}
    if slots:
        entry["slots"] = slots
    if requires_context:
        entry["requires_context"] = requires_context
    if "response" in group:
        entry["response"] = group["response"]

    return entry


def partition_speech_to_phrase(groups: list) -> tuple:
    """Split a combo's data groups into (home_assistant, speech_to_phrase).

    Mirrors ``partition_speech_to_phrase`` in the intents repo. A
    ``speech_to_phrase``-tagged group is a lean subset of its richer untagged
    sibling, so Home Assistant drops it when such a sibling exists; when every
    group is tagged (a combo already lean enough for both), they serve both.

    Speech-to-Phrase always consumes the tagged groups.
    """
    untagged = [g for g in groups if not g.get("speech_to_phrase")]
    tagged = [g for g in groups if g.get("speech_to_phrase")]
    ha_groups = untagged if untagged else tagged
    return ha_groups, tagged


def convert_slot_combinations(lang_dir: Path, intent_info: dict) -> tuple:
    """Convert new-format slot-combination dirs into old-format intent data.

    Returns ``(ha_converted, s2p_converted)``, each a mapping of intent name ->
    {"data": [...]}. ``ha_converted`` holds the blocks Home Assistant's grammar
    uses; ``s2p_converted`` holds the ``speech_to_phrase``-tagged blocks for the
    constrained Speech-to-Phrase grammar (see ``partition_speech_to_phrase``).
    """
    ha_converted: dict = {}
    s2p_converted: dict = {}
    for intent_dir in sorted(p for p in lang_dir.iterdir() if p.is_dir()):
        intent_name = intent_dir.name
        combos = intent_info.get(intent_name, {}).get("slot_combinations", {})

        ha_data: list = []
        s2p_data: list = []
        for combo_file in sorted(intent_dir.glob("*.yaml")):
            combo_name = combo_file.stem
            combo_info = combos.get(combo_name, {})
            combo_dict = yaml.safe_load(combo_file.read_text())
            groups = [g for g in combo_dict.get("data", []) if g.get("sentences")]
            ha_groups, s2p_groups = partition_speech_to_phrase(groups)
            for group in ha_groups:
                ha_data.append(
                    convert_slot_combination_group(group, combo_name, combo_info)
                )
            for group in s2p_groups:
                s2p_data.append(
                    convert_slot_combination_group(group, combo_name, combo_info)
                )

        if ha_data:
            ha_converted[intent_name] = {"data": ha_data}
        if s2p_data:
            s2p_converted[intent_name] = {"data": s2p_data}

    return ha_converted, s2p_converted


def merge_dict(base_dict, new_dict):
    """Merges new_dict into base_dict."""
    for key, value in new_dict.items():
        if key in base_dict:
            old_value = base_dict[key]
            if isinstance(old_value, collections.abc.MutableMapping):
                # Combine dictionary
                assert isinstance(
                    value, collections.abc.Mapping
                ), f"Not a dict: {value}"
                merge_dict(old_value, value)
            elif isinstance(old_value, collections.abc.MutableSequence):
                # Combine list
                assert isinstance(
                    value, collections.abc.Sequence
                ), f"Not a list: {value}"
                old_value.extend(value)
            else:
                # Overwrite
                base_dict[key] = value
        else:
            base_dict[key] = value


def filter_lang_intents(intents_dict: dict, supported_intents: set) -> dict:
    """Keep supported intents with at least one non-empty sentence group."""
    result: dict = {}
    for intent, info in intents_dict.items():
        if intent not in supported_intents:
            continue
        data = [d for d in info["data"] if len(d["sentences"]) > 0]
        if not data:
            continue
        result[intent] = {**info, "data": data}
    return result


def main() -> None:
    logging.basicConfig(level=logging.INFO)

    parser = argparse.ArgumentParser()
    parser.add_argument("target", help="Output directory for Home Assistant JSON")
    parser.add_argument(
        "--intents-dir", default=INTENTS_DIR, help="Intents repo directory"
    )
    parser.add_argument(
        "--speech-to-phrase-target",
        default=None,
        help="Output directory for Speech-to-Phrase JSON "
        "(default: <target>/../speech_to_phrase)",
    )
    args = parser.parse_args()

    intents_dir = Path(args.intents_dir)
    sentence_dir = intents_dir / "sentences"
    response_dir = intents_dir / "responses"
    lists_dir = intents_dir / "lists"
    rules_dir = intents_dir / "rules"
    intents_path = intents_dir / "intents.yaml"
    languages = sorted(p.name for p in sentence_dir.iterdir() if p.is_dir())

    target = Path(args.target)
    target.mkdir(parents=True, exist_ok=True)

    s2p_target = (
        Path(args.speech_to_phrase_target)
        if args.speech_to_phrase_target
        else target.parent / "speech_to_phrase"
    )
    s2p_target.mkdir(parents=True, exist_ok=True)

    with open(intents_path, "r", encoding="utf-8") as intents_file:
        intent_info = yaml.safe_load(intents_file)

    # Write all intents info
    intents_json_path = target / "intents.json"
    with open(intents_json_path, "w", encoding="utf-8") as intents_json_file:
        json.dump(intent_info, intents_json_file)

    # Skip intents that are not supported in Home Assistant
    supported_intents = set(
        intent for intent, info in intent_info.items() if info.get("supported")
    )

    # Create one JSON file per language
    num_processed_languages = 0
    for language in languages:
        # Merge language's sentence template YAML files
        merged_sentences: dict = {}
        for sentence_file in (sentence_dir / language).glob("*.yaml"):
            merge_dict(merged_sentences, yaml.safe_load(sentence_file.read_text()))

        # Convert new-format slot-combination sentences into the old format.
        # These live in sentences/<language>/<intent>/<slot_combination>.yaml
        # instead of a single sentences/<language>/<...>.yaml file.
        #
        # Migrating an intent means deleting its old-format file(s) and adding a
        # new-format directory. While both exist (a partially-migrated language)
        # the old-format files remain authoritative, so the new directory only
        # takes effect for an intent once its old-format data is gone.
        ha_converted, s2p_converted = convert_slot_combinations(
            sentence_dir / language, intent_info
        )
        lang_intent_data = merged_sentences.setdefault("intents", {})
        activated_new_format = False
        for intent_name, intent_dict in ha_converted.items():
            if intent_name in lang_intent_data:
                # Not yet migrated: old-format file(s) still present
                continue
            lang_intent_data[intent_name] = intent_dict
            activated_new_format = True

        # The Speech-to-Phrase grammar always comes from the (new-format) tagged
        # blocks, so it needs the dedicated lists/ and rules/ even if no HA
        # intent newly activated the new format this pass.
        if activated_new_format or s2p_converted:
            # Migrated intents keep their lists and expansion rules in the
            # dedicated lists/ and rules/ directories instead of _common.yaml.
            # These are authoritative for the new sentences, so they take
            # precedence over anything merged from _common.yaml.
            merged_lists = merged_sentences.setdefault("lists", {})
            for list_file in sorted(lists_dir.glob("*.yaml")):  # shared lists
                merged_lists.update(yaml.safe_load(list_file.read_text())["lists"])
            for list_file in sorted((lists_dir / language).glob("*.yaml")):
                merged_lists.update(yaml.safe_load(list_file.read_text())["lists"])

            merged_rules = merged_sentences.setdefault("expansion_rules", {})
            for rule_file in sorted((rules_dir / language).glob("*.yaml")):
                merged_rules.update(
                    yaml.safe_load(rule_file.read_text())["expansion_rules"]
                )

        # Merge language's response YAML files
        merged_responses: dict = {}
        for response_file in (response_dir / language).glob("*.yaml"):
            merge_dict(merged_responses, yaml.safe_load(response_file.read_text()))

        errors_translated = not any(
            translation.startswith("TODO ")
            for translation in merged_sentences["responses"]["errors"].values()
        )
        if not errors_translated:
            _LOGGER.warning(
                "Skipping language %s because it doesn't have all errors translated",
                language,
            )
            continue

        skip_language = False
        lang_intents: dict = {}
        for intent, info in merged_sentences["intents"].items():
            if intent not in supported_intents:
                continue

            num_intent_sentences = 0
            data = []
            for data_set in info["data"]:
                if len(data_set["sentences"]) > 0:
                    data.append(data_set)
                    num_intent_sentences += len(data_set["sentences"])

            if (num_intent_sentences == 0) and (intent in IMPORTANT_INTENTS):
                skip_language = True
                _LOGGER.warning(
                    "Skipping language %s because it doesn't have sentences for %s",
                    language,
                    intent,
                )
                break

            if not data:
                # No sentence templates
                continue

            lang_intents[intent] = {
                **info,
                "data": data,
            }

        if skip_language:
            # Not usable
            continue

        lang_responses = {
            intent: info
            for intent, info in merged_responses["responses"]["intents"].items()
            if intent in supported_intents
        }

        if not lang_intents and not lang_responses:
            # Nothing to export
            continue

        output: dict = {
            "language": language,
            **merged_sentences,
            "intents": lang_intents,
        }

        if lang_responses:
            # Do this separately because merged_sentences contains error responses
            output.setdefault("responses", {})["intents"] = lang_responses

        # Write as JSON
        target_path = target / f"{language}.json"
        with target_path.open("w", encoding="utf-8") as target_file:
            json.dump(output, target_file, ensure_ascii=False, indent=2)

        num_processed_languages += 1

        # Speech-to-Phrase artifact: the lean, tagged subset only. Same schema as
        # the Home Assistant JSON (including responses) so the Speech-to-Phrase
        # app can load it with hassil the same way, but carrying only the blocks
        # its constrained grammar should enumerate.
        s2p_lang_intents = filter_lang_intents(s2p_converted, supported_intents)
        if s2p_lang_intents:
            s2p_output: dict = {
                "language": language,
                "intents": s2p_lang_intents,
            }
            for shared_key in ("lists", "expansion_rules", "skip_words"):
                if shared_key in merged_sentences:
                    s2p_output[shared_key] = merged_sentences[shared_key]

            # Responses, mirroring the Home Assistant JSON: shared error
            # responses plus the per-intent responses.
            s2p_responses: dict = {}
            error_responses = merged_sentences.get("responses", {}).get("errors")
            if error_responses:
                s2p_responses["errors"] = error_responses
            if lang_responses:
                s2p_responses["intents"] = lang_responses
            if s2p_responses:
                s2p_output["responses"] = s2p_responses

            s2p_path = s2p_target / f"{language}.json"
            with s2p_path.open("w", encoding="utf-8") as s2p_file:
                json.dump(s2p_output, s2p_file, ensure_ascii=False, indent=2)

    num_languages = len(languages)
    if num_processed_languages < num_languages:
        _LOGGER.warning(
            "Skipped %s out of %s language(s)",
            num_languages - num_processed_languages,
            num_languages,
        )


if __name__ == "__main__":
    main()
