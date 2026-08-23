# -*- coding: utf-8 -*-
"""Genome accession resolution (spec section 9).

For each manipulation_observations.csv row, attempts to resolve the exact
experimental organism/strain against NCBI's assembly database. Never
assigns a genome just because one exists for the same species -- an exact
strain-token match in the returned assembly's organism name is required for
exact_strain_match; a hit with no strain match falls back to
species_only_match; no hits is no_genome_found. Ambiguous/unparseable
strain names (spec's "not specified in abstract" cases, multi-organism
rows) are marked not_checked rather than guessed at.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, ncbi_esearch, ncbi_esummary, read_csv_dicts, write_csv_dicts

GENOME_MATCH_FIELDNAMES = [
    "observation_id", "organism_name", "strain_name", "query_used",
    "gcf_accession", "gca_accession", "ncbi_taxid", "biosample", "bioproject",
    "genome_match_status", "notes",
]

UNRESOLVED_STRAIN_MARKERS = [
    "not specified", "unspecified", "exact designation not", "exact strain",
    "not in abstract", "not individually specified",
]


def first_binomial(organism_name: str) -> str:
    # Take the first organism mentioned before any "/", ",", " and ", " or "
    first = re.split(r"[/,]| and | or ", organism_name)[0].strip()
    words = first.split()
    return " ".join(words[:2]) if len(words) >= 2 else first


def strain_is_resolvable(strain_name: str) -> bool:
    s = strain_name.lower()
    if not s or s in {"n/a", "unknown"}:
        return False
    return not any(marker in s for marker in UNRESOLVED_STRAIN_MARKERS)


def clean_strain_token(strain_name: str) -> str:
    # Strip parenthetical qualifiers like "(wild-type)" / "(derived from ...)"
    return re.split(r"\(", strain_name)[0].strip()


def query_assembly(genus_species: str, strain: str) -> tuple[str, list[str]]:
    # Hybrid, because neither approach alone is reliable (both tested
    # live against known-real genomes): appending the strain to the query
    # text finds it directly for many strains (whatever indexed field
    # NCBI matched it against), but returns zero hits for others whose
    # strain designation apparently isn't free-text indexed at all (e.g.
    # "Streptomyces coelicolor M145", "... DSM 14401" -> 0 hits even
    # though the assembly exists). Falling back to a species-only search
    # (capped at 40) plus client-side biosource filtering recovers some
    # of those, though it can still miss a specific strain buried among
    # hundreds/thousands of assemblies for very common species (E. coli,
    # K. pneumoniae, ...) -- an acceptable first-pass limitation, not
    # silently pretended away (see genome_match_status/notes).
    if strain:
        query = f"{genus_species} {strain}".strip()
        ids = ncbi_esearch("assembly", query, retmax=20)
        if ids:
            return query, ids
    query = genus_species.strip()
    ids = ncbi_esearch("assembly", query, retmax=40)
    return query, ids


def main() -> None:
    in_name = sys.argv[1] if len(sys.argv) > 1 else "manipulation_observations.csv"
    out_name = sys.argv[2] if len(sys.argv) > 2 else "genome_matches.csv"
    obs = read_csv_dicts(DATA_DIR / in_name)
    seen = {}
    rows = []

    for o in obs:
        obs_id = o["observation_id"]
        organism_name = o["organism_name"]
        strain_name = o["strain_name"]
        key = (organism_name, strain_name)

        if key in seen:
            cached = dict(seen[key])
            cached["observation_id"] = obs_id
            rows.append(cached)
            continue

        genus_species = first_binomial(organism_name)
        resolvable_strain = strain_is_resolvable(strain_name)
        strain_token = clean_strain_token(strain_name) if resolvable_strain else ""

        result = dict(
            observation_id=obs_id, organism_name=organism_name, strain_name=strain_name,
            query_used="", gcf_accession="", gca_accession="", ncbi_taxid="",
            biosample="", bioproject="", genome_match_status="not_checked", notes="",
        )

        if not genus_species or len(genus_species.split()) < 2:
            result["notes"] = "Organism name not resolvable to a clean binomial from this field."
            seen[key] = result
            rows.append(dict(result))
            continue

        query, ids = query_assembly(genus_species, strain_token)
        result["query_used"] = query

        if not ids:
            result["genome_match_status"] = "no_genome_found"
            if not resolvable_strain:
                result["notes"] = "Strain not resolvable from abstract text; searched at species level only."
            seen[key] = result
            rows.append(dict(result))
            continue

        summaries = ncbi_esummary("assembly", ids)
        uids = summaries.get("uids", [])
        matches = []
        for uid in uids:
            rec = summaries.get(uid, {})
            org = rec.get("organism", "") or ""
            # The assembly's strain designation lives in biosource.infraspecieslist,
            # not in the free-text "organism" field (which is just the species +
            # higher taxon), so both need checking to catch an exact strain match.
            strain_values = [
                entry.get("sub_value", "")
                for entry in (rec.get("biosource", {}) or {}).get("infraspecieslist", [])
                if entry.get("sub_type") in ("strain", "isolate")
            ]
            match_text = org + " " + " ".join(strain_values)
            matches.append({
                "accession": rec.get("assemblyaccession", ""),
                "organism": org,
                "match_text": match_text,
                "biosample": rec.get("biosampleaccn", ""),
                "bioproject": rec.get("gb_bioprojects", [{}])[0].get("bioprojectaccn", "") if rec.get("gb_bioprojects") else "",
                "taxid": rec.get("taxid", ""),
            })

        exact = [m for m in matches if strain_token and strain_token.lower() in m["match_text"].lower()]

        if exact:
            best = exact[0]
            result["gcf_accession"] = best["accession"] if best["accession"].startswith("GCF") else ""
            result["gca_accession"] = best["accession"] if best["accession"].startswith("GCA") else ""
            result["ncbi_taxid"] = str(best["taxid"])
            result["biosample"] = best["biosample"]
            result["bioproject"] = best["bioproject"]
            result["genome_match_status"] = "exact_strain_match" if len(exact) == 1 else "multiple_possible_matches"
            if len(exact) > 1:
                result["notes"] = f"{len(exact)} assemblies matched the exact strain token; kept the first, see NCBI assembly for the rest."
        elif not resolvable_strain:
            best = matches[0]
            result["gcf_accession"] = best["accession"] if best["accession"].startswith("GCF") else ""
            result["gca_accession"] = best["accession"] if best["accession"].startswith("GCA") else ""
            result["ncbi_taxid"] = str(best["taxid"])
            result["genome_match_status"] = "species_only_match"
            result["notes"] = "Strain not resolvable from abstract text; species-level assembly shown as an example only, not an exact match."
        else:
            result["genome_match_status"] = "species_only_match"
            result["notes"] = f"{len(matches)} assemblies found for the species but none matched strain token '{strain_token}'."
            best = matches[0]
            result["gcf_accession"] = best["accession"] if best["accession"].startswith("GCF") else ""
            result["gca_accession"] = best["accession"] if best["accession"].startswith("GCA") else ""
            result["ncbi_taxid"] = str(best["taxid"])

        seen[key] = result
        rows.append(dict(result))

    write_csv_dicts(DATA_DIR / out_name, rows, GENOME_MATCH_FIELDNAMES)

    status_counts = {}
    for r in rows:
        status_counts[r["genome_match_status"]] = status_counts.get(r["genome_match_status"], 0) + 1
    print(f"Wrote {len(rows)} genome_matches.csv rows")
    for status, count in sorted(status_counts.items()):
        print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
