# -*- coding: utf-8 -*-
"""First-pass manual extraction pass (spec sections 5-8).

This is the actual analyst extraction step, expressed as code for
reproducibility/auditability rather than a spreadsheet: each row below was
produced by reading the abstract (and, where noted, title) of a shortlisted
paper (extraction_shortlist_details.json) and transcribing the verbatim
sentence(s) describing a specific organism/strain manipulation attempt.
Evidence text is copied exactly from the source abstract -- never
paraphrased -- per spec section 6.

Only a subset of the ~60-paper shortlist yielded genuine per-strain
manipulation observations; papers that were pure epidemiology/genomics,
too aggregate (hundreds of strains, no single one identifiable), or
generic/no named strain were routed to manual_review.csv instead (see
SKIPPED below) rather than silently dropped.

Note on evidence_text fidelity: source abstracts carry HTML <sup>/<sub>
markup (e.g. "10<sup>-5</sup>") that plain CSV text can't represent;
exponents are normalized to "10^-5" notation (unambiguous, value-preserving)
rather than left as concatenated digits ("10-5"), which would silently
misstate the quantity. No other rewording was applied anywhere below.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import DATA_DIR, make_observation_id, write_csv_dicts

OBS_FIELDNAMES = [
    "observation_id", "paper_id", "organism_name", "strain_name", "organism_domain",
    "wild_type_status", "wild_type_evidence",
    "manipulation_category", "manipulation_detail",
    "outcome", "failure_reason",
    "evidence_text", "section_name",
    "genome_accession", "genome_match_status",
    "marine_status", "isolation_source", "environment",
    "qc_flags", "notes",
]

MANUAL_REVIEW_FIELDNAMES = ["paper_id", "title", "issue_type", "description", "notes"]

# Each tuple: (paper_id, [row-dicts without observation_id/paper_id])
RAW = [
("Pe0c17d2ce8ba", [
    dict(organism_name="Synechococcus elongatus", strain_name="PCC 7942", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Axenic reference cyanobacterial strain from the Pasteur Culture Collection, used as the recipient of exogenous plasmids; not a lab-engineered derivative.",
         manipulation_category="conjugation", manipulation_detail="Interphylum conjugation of proteobacterial conjugative plasmids (RP4, pKM101, R388, R64, F) from E. coli into S. elongatus, via BioBrick-compatible mobilizable shuttle vectors based on the pANL replication origin.",
         outcome="mixed", failure_reason="MPFF- and MPFI-type conjugative systems could not deliver DNA across phyla.",
         evidence_text="Not only broad-host-range plasmids, such as RP4 and R388, but also narrower-host-range plasmids, such as pKM101, all encoding MPFT-type IV secretion systems, were able to transfer plasmid DNA from E. coli to S. elongatus by conjugation. Neither MPFF nor MPFI could be used as interphylum DNA delivery agents.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes="Multiple plasmid systems tested in one paper; success/failure split by MPF type, not by strain."),
]),
("Peb4d11db8eb8", [
    dict(organism_name="Streptomyces rimosus", strain_name="M527", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Described only as 'a bacterial strain which exhibits strong antagonistic activity against a broad range of plant-pathogenic fungi'; no domestication markers mentioned.",
         manipulation_category="conjugation", manipulation_detail="Intergeneric conjugation-based genetic transformation system developed and optimized (conjugative media, donor:recipient ratio, heat shock, incubation time).",
         outcome="success", failure_reason="",
         evidence_text="Under the optimal conditions, a maximal conjugation frequency of 3.05×10^-5 per recipient was obtained.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes=""),
]),
("P46eb6e7e064b", [
    dict(organism_name="Streptomyces coelicolor", strain_name="M145", organism_domain="bacteria",
         wild_type_status="no", wild_type_evidence="M145 is the standard plasmid-cured laboratory derivative of S. coelicolor A3(2), not a fresh wild-type isolate.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="Standard-level Cas9 expression for CRISPR-Cas9-mediated recombination/genome editing.",
         outcome="failure", failure_reason="Cas9 protein levels themselves were toxic to the host.",
         evidence_text="we provide evidence of how Cas9 levels are toxic for the model actinomycetes Streptomyces coelicolor M145 and Streptomyces lividans TK24, which show delayed or absence of growth.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes="Keep as secondary/mechanistic per spec section 8 (engineered lab derivative, not wild-type)."),
    dict(organism_name="Streptomyces coelicolor / Streptomyces lividans", strain_name="M145 / TK24", organism_domain="bacteria",
         wild_type_status="no", wild_type_evidence="Same engineered lab derivatives as above.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="Cas9 expression tuned via theophylline-inducible or constitutive promoters at lowered levels; targeting validated on the glycerol uptake operon and actinorhodin biosynthesis gene cluster.",
         outcome="success", failure_reason="",
         evidence_text="We overcame this toxicity by lowering Cas9 levels and have generated a set of plasmids in which Cas9 expression is either controlled by theophylline-inducible or constitutive promoters.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes=""),
]),
("Pa3a4d09b374c", [
    dict(organism_name="Acinetobacter sp.", strain_name="Tol 5", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Explicitly described as 'an environmentally isolated Gram-negative bacterium'.",
         manipulation_category="electroporation", manipulation_detail="Electroporation-based transformation of the unmodified wild-type strain.",
         outcome="partial", failure_reason="Genetic manipulation was hindered by low transformation efficiency.",
         evidence_text="its genetic manipulation has been hindered by low transformation efficiency via electroporation, rendering the process laborious and time-consuming.",
         section_name="abstract", marine_status="unknown", isolation_source="environmental isolate", environment="unknown",
         qc_flags="", notes="Paired WT vs. restriction-deficient-derivative comparison, spec section 8 example."),
    dict(organism_name="Acinetobacter sp.", strain_name="Tol 5 Δrestriction-I Δrestriction-III", organism_domain="bacteria",
         wild_type_status="no", wild_type_evidence="Engineered double deletion of type I and type III restriction-enzyme genes from wild-type Tol 5.",
         manipulation_category="electroporation", manipulation_detail="Electroporation of the restriction-deficient derivative strain.",
         outcome="success", failure_reason="",
         evidence_text="We deleted two genes encoding type I and type III restriction enzymes. The resulting mutant strain not only exhibited marked efficiency of electrotransformation but also proved receptive to both in vitro and in vivo DNA assembly technologies",
         section_name="abstract", marine_status="unknown", isolation_source="environmental isolate", environment="unknown",
         qc_flags="", notes="Secondary/engineered-derivative record per spec section 8, paired with WT row above."),
    dict(organism_name="Acinetobacter sp.", strain_name="Tol 5 Δrestriction-I Δrestriction-III", organism_domain="bacteria",
         wild_type_status="no", wild_type_evidence="Same restriction-deficient derivative as above.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="CRISPR-Cas9-based base editing adapted from a platform developed for other Acinetobacter species.",
         outcome="success", failure_reason="",
         evidence_text="we successfully adapted a CRISPR-Cas9-based base-editing platform developed for other Acinetobacter species.",
         section_name="abstract", marine_status="unknown", isolation_source="environmental isolate", environment="unknown",
         qc_flags="", notes=""),
]),
("P2a4a3b3d85c8", [
    dict(organism_name="Bacillus subtilis and other Bacillus spp. (B. amyloliquefaciens, B. licheniformis, B. thuringiensis)", strain_name="wild environmental isolates", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Explicitly 'wild B. subtilis isolates from natural environments and other Bacillus species'.",
         manipulation_category="natural transformation", manipulation_detail="Cell-to-Cell Natural Transformation for Plasmid Transfer (CTCNT-P): co-culturing donor/recipient under antibiotic stress.",
         outcome="success", failure_reason="",
         evidence_text="we demonstrate that CTCNT-P is applicable for plasmid transformation in wild Bacillus subtilis isolates from natural environments and other Bacillus species, including Bacillus amyloliquefaciens, Bacillus licheniformis, and Bacillus thuringiensis.",
         section_name="abstract", marine_status="unknown", isolation_source="soil/natural environment", environment="soil",
         qc_flags="", notes=""),
]),
("P5d6b55c91c6d", [
    dict(organism_name="Vibrio campbellii", strain_name="ATCC BAA-1116", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Reference type-culture strain of a naturally isolated marine bacterium; genetically tractable model but not a lab-domesticated derivative.",
         manipulation_category="electroporation", manipulation_detail="New electroporation protocol (10 kV/cm, 400 Ω, 25 μF), tuned for growth phase, DNA amount, recovery conditions.",
         outcome="success", failure_reason="",
         evidence_text="An electroporation efficiency of up to 3 × 10^4 CFU/μg DNA was demonstrated using derived parameters (10 kV/cm, 400 Ω, 25 μF)",
         section_name="abstract", marine_status="marine", isolation_source="marine isolate", environment="marine",
         qc_flags="", notes="Paired with strain-panel failure row below."),
    dict(organism_name="Vibrio campbellii (and sister species V. harveyi)", strain_name="5 of 8 additional strains tested (more heavily lab-passaged)", organism_domain="bacteria",
         wild_type_status="unclear", wild_type_evidence="Passage history relative to original environmental isolation is not fully specified per strain.",
         manipulation_category="electroporation", manipulation_detail="Same electroporation protocol applied across a panel of 8 additional V. campbellii/V. harveyi strains.",
         outcome="failure", failure_reason="Not amenable to electroporation-mediated transformation; only the most recent environmental isolates with fewest lab passages worked.",
         evidence_text="of the eight other V. campbellii strains tested, only three others, which also happened to be the three most recent environmental isolates with the fewest number of laboratory passages, were amenable to electroporation-mediated transformation.",
         section_name="abstract", marine_status="marine", isolation_source="marine isolate", environment="marine",
         qc_flags="strain_uncertain", notes="Exact identities of the 5 non-amenable strains not given in the abstract; needs full text for strain-level resolution."),
]),
("P76647c572525", [
    dict(organism_name="Picochlorum celeri", strain_name="not specified in abstract", organism_domain="eukaryota",
         wild_type_status="unclear", wild_type_evidence="Described as 'new highly productive strains of algae'; specific ancestry of the transformed strain not given in the abstract.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="CRoxP system: Cas9 RNPs plus inducible Cre-loxP for marker-free, multiplexed LHCII/LHCI knockouts.",
         outcome="success", failure_reason="",
         evidence_text="In P. celeri, transformants were generated with a turnaround time as short as 21 days between transformation and being ready for another round of transformation with the same selection marker by using the CRoxP system.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="strain_uncertain", notes="Microalga (unicellular eukaryote) -- kept per spec section 12, not folded into the bacterial set."),
]),
("Pb5aeedee757f", [
    dict(organism_name="Bacillus subtilis", strain_name="wild-type (unspecified designation)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Explicitly 'Wild-type Bacillus strains'.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="Standard CRISPR/Cas9 genome editing without toxicity mitigation.",
         outcome="failure", failure_reason="Cas9/sgRNA activity is cellularly toxic in wild-type strains, crippling transformation and editing.",
         evidence_text="the practical application of CRISPR/Cas9 in most wild-type Bacillus strains remains challenging due to cellular toxicity resulting from Cas9/sgRNA activity.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes="Paired with anti-CRISPR-rescued success row below."),
    dict(organism_name="Bacillus subtilis", strain_name="wild-type (unspecified designation)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Same wild-type strains as above.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="CRISPR/anti-CRISPR (CAC) plasmid: AcrIIA4 anti-CRISPR protein co-expressed with Cas9 under separate inducible promoters (Pspac/Pxyl).",
         outcome="success", failure_reason="",
         evidence_text="Under xylose induction, the CAC plasmid led to a remarkable 139-fold increase in the transformation efficiency of wild-type Bacillus subtilis compared to a plasmid lacking anti-CRISPR. ... Upon IPTG induction, the genome editing efficiency in wild-type B. subtilis increased from 0 to 95.8% in transformants carrying the CAC plasmid.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes=""),
    dict(organism_name="Bacillus pumilus, Bacillus mojavensis, Bacillus tequilensis, Paenibacillus polymyxa", strain_name="wild-type (unspecified designation)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Extension of the wild-type Bacillus-strain CAC approach to additional wild-type species.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="CAC (Cas9 + AcrIIA4) system used to generate spo0A knockout mutants.",
         outcome="success", failure_reason="",
         evidence_text="we demonstrated that the CAC system successfully enabled the generation of spo0A mutants in Bacillus mojavensis, Bacillus tequilensis, and Paenibacillus polymyxa.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="strain_uncertain", notes="Exact strain designations not given in abstract."),
]),
("Pbff6c5debde9", [
    dict(organism_name="Vibrio fischeri", strain_name="non-canonical strain (exact designation not in abstract; recipient of ES114-derived DNA)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Contrasted explicitly with the 'laboratory-adapted strain ES114' as a 'non-canonical' strain.",
         manipulation_category="natural transformation", manipulation_detail="Genomic DNA carrying a Tn7 attTn7-site insertion (built first in surrogate strain ES114) used to transform a non-canonical strain via induced natural transformation.",
         outcome="success", failure_reason="",
         evidence_text="Genomic DNA extracted from the resulting strain is used as template for transformation of another strain, in which natural transformation is induced. As a proof of principle, this approach is used to complement an rpoN mutant with an IPTG-inducible rpoN construct in trans.",
         section_name="abstract", marine_status="marine", isolation_source="host-associated (squid symbiont)", environment="host-associated",
         qc_flags="strain_uncertain", notes="Exact recipient strain name not given in the abstract; needs full text."),
]),
("Pcd8678c9705e", [
    dict(organism_name="Escherichia coli", strain_name="clinical isolate O55", organism_domain="bacteria",
         wild_type_status="unclear", wild_type_evidence="Described as a 'clinical isolate'; not explicitly confirmed free of prior lab domestication.",
         manipulation_category="plasmid transformation", manipulation_detail="Attempted transformation of each of two cryptic native plasmids independently.",
         outcome="failure", failure_reason="Plasmids depend on each other to replicate; independent transformation could not establish either plasmid alone.",
         evidence_text="Attempts to transform the plasmids independently were unsuccessful; however, they remained stable when the cells were co-transformed.",
         section_name="abstract", marine_status="unknown", isolation_source="clinical isolate", environment="host-associated",
         qc_flags="", notes="Paired failure/success pair from the same paper."),
    dict(organism_name="Escherichia coli", strain_name="clinical isolate O55", organism_domain="bacteria",
         wild_type_status="unclear", wild_type_evidence="Same clinical isolate as above.",
         manipulation_category="plasmid transformation", manipulation_detail="Co-transformation of both cryptic plasmids together.",
         outcome="success", failure_reason="",
         evidence_text="they remained stable when the cells were co-transformed.",
         section_name="abstract", marine_status="unknown", isolation_source="clinical isolate", environment="host-associated",
         qc_flags="", notes=""),
]),
("P4210ed091a8b", [
    dict(organism_name="Synechocystis sp., Synechococcus elongatus, Synechococcus sp.", strain_name="PCC 6803 / PCC 7942 / UTEX 3153", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Standard axenic reference cyanobacterial culture-collection strains, not lab-engineered derivatives.",
         manipulation_category="plasmid transformation", manipulation_detail="BPP Bioportide (protein-based DNA delivery) transformation of plasmid and linear DNA, tested with as little as 10 ng DNA input.",
         outcome="success", failure_reason="",
         evidence_text="BPP Bioportide™ variants BP-17 and BP-12 significantly improved transformation efficiency of both plasmid and linear DNA, even with minimal DNA input of 10 ng, surpassing conventional methods and enabling modification of previously non-model strains.",
         section_name="abstract", marine_status="freshwater/marine (mixed cyanobacterial strains)", isolation_source="culture collection", environment="unknown",
         qc_flags="", notes="Also reports successful double homologous recombination and genomic segregation (colony-PCR validated) but with no explicit failure quote."),
]),
("P87aebc2e178f", [
    dict(organism_name="Synechocystis sp.", strain_name="PCC 6803 (PSI-kd/ΔPBS background strain)", organism_domain="bacteria",
         wild_type_status="no", wild_type_evidence="Mutants were made in a purpose-built engineered background strain (PSI knockdown + phycobilisome knockout), not directly in wild-type PCC 6803.",
         manipulation_category="gene knock-in", manipulation_detail="Site-directed mutagenesis at PsbH Thr5 in an engineered PSI-kd/ΔPBS background.",
         outcome="success", failure_reason="",
         evidence_text="All mutants were capable of heterotrophic growth (without noticeable differences from wild-type), indicating the PSII function remains intact.",
         section_name="abstract", marine_status="unknown", isolation_source="culture collection", environment="unknown",
         qc_flags="", notes="Secondary/engineered-background record per spec section 8; original WT PCC 6803 tractability not directly re-tested here."),
]),
("P903c532e3aeb", [
    dict(organism_name="Pseudoalteromonas flavipulchra", strain_name="DSM 14401", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Deposited type/reference strain (DSM culture collection number), used directly as the editing target.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="RECC: Red/ET recombineering combined with CRISPR/Cas9 cleavage in one Gibson-assembled construct; used to replace the native promoter of a silent NRPS-PKS gene cluster.",
         outcome="success", failure_reason="",
         evidence_text="Using Pseudoalteromonas flavipulchra DSM 14401 as a model, we employed RECC to replace the native promoter of a silent nonribosomal peptide synthetase-polyketide synthase (NRPS-PKS) hybrid gene cluster with a strong constitutive promoter. This targeted activation led to the production of a series of previously unknown cyclolipopeptides",
         section_name="abstract", marine_status="marine", isolation_source="marine isolate", environment="marine",
         qc_flags="", notes=""),
]),
("P9d7287ce9040", [
    dict(organism_name="Acinetobacter baumannii", strain_name="A2485 (donor) to ATCC 17978 (recipient)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Clinical isolate donor and a standard reference clinical-isolate-lineage recipient strain, not artificially domesticated derivatives.",
         manipulation_category="plasmid maintenance", manipulation_detail="Outer-membrane-vesicle (OMV)-mediated transfer of a blaOXA-72 plasmid from a high-OMV-producing clinical isolate into a recipient strain.",
         outcome="success", failure_reason="",
         evidence_text="OMVs from A2485 transferred the blaOXA-72 plasmid to ATCC 17978 at 1.9 × 10−7 transformants per CFU, exceeding direct supernatant transfer at 3.2 × 10−8 transformants per CFU, and conferred resistance to meropenem, ceftazidime, and cefoperazone/sulbactam.",
         section_name="abstract", marine_status="unknown", isolation_source="clinical isolate", environment="host-associated",
         qc_flags="", notes="Paired with cross-species failure row below."),
    dict(organism_name="13 non-Acinetobacter baumannii strains", strain_name="not individually specified in abstract", organism_domain="bacteria",
         wild_type_status="unclear", wild_type_evidence="Recipient panel composition (species/strain identities) not detailed in the abstract.",
         manipulation_category="plasmid maintenance", manipulation_detail="Same OMV-mediated plasmid-transfer attempt, tested across 13 non-A. baumannii recipient strains.",
         outcome="failure", failure_reason="Strong cross-species barrier; transfer restricted to A. baumannii only.",
         evidence_text="Transfer was strictly donor-specific, with no transmission observed across 13 non-A. baumannii strains, and recipient strains failed to retransmit the plasmid, indicating a strong cross-species barrier and a non-reciprocal, donor-dependent process.",
         section_name="abstract", marine_status="unknown", isolation_source="clinical isolate", environment="host-associated",
         qc_flags="strain_uncertain", notes="Full text needed to identify the 13 recipient strains individually."),
]),
("P55b1d34001d5", [
    dict(organism_name="Streptomyces hygroscopicus", strain_name="SIPI-054", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Described as an industrial production strain distinct from the model S. coelicolor system; no domestication markers given.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="Standard SpCas9- or FnCpf1-based genome editing.",
         outcome="failure", failure_reason="Editing tool ineffective in this strain.",
         evidence_text="AsCas12f1 was successfully extended to Streptomyces hygroscopicus SIPI-054 for efficient genome editing, in which SpCas9/FnCpf1 does not work well.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes="Paired with AsCas12f1 success row below."),
    dict(organism_name="Streptomyces hygroscopicus", strain_name="SIPI-054", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Same strain as above.",
         manipulation_category="other CRISPR-Cas systems", manipulation_detail="Miniature Type V-F CRISPR/Cas nuclease AsCas12f1-based genome editing.",
         outcome="success", failure_reason="",
         evidence_text="AsCas12f1 was successfully extended to Streptomyces hygroscopicus SIPI-054 for efficient genome editing",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes=""),
    dict(organism_name="Streptomyces coelicolor", strain_name="not specified in abstract", organism_domain="bacteria",
         wild_type_status="unclear", wild_type_evidence="Likely the standard M145-type lab derivative given the field convention, but not stated in the abstract.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="AsCas12f1 all-in-one editing tool for single/double gene or gene-cluster deletion.",
         outcome="success", failure_reason="",
         evidence_text="we achieved 100% efficiency for single gene or gene cluster deletion and 46.7 and 40% efficiency for simultaneous deletion of two genes and two gene clusters, respectively.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="strain_uncertain wild_type_uncertain", notes=""),
]),
("Pc02adabb613e", [
    dict(organism_name="Ureaplasma parvum", strain_name="three serovars (exact numbers not in abstract)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="No domestication described; standard serovar reference strains.",
         manipulation_category="transposon mutagenesis", manipulation_detail="PEG-transformation-enhanced delivery of a Tn4001-based mini-transposon plasmid (gentamicin resistance marker).",
         outcome="success", failure_reason="",
         evidence_text="Using a polyethylene glycol-transformation enhancing protocol, we were able to transform three separate serovars of Ureaplasma parvum with a Tn4001-based mini-transposon plasmid containing a gentamicin resistance selection marker.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="host-associated",
         qc_flags="strain_uncertain", notes="Contrasts directly with U. urealyticum failure row below -- a close relative with the same protocol."),
    dict(organism_name="Ureaplasma urealyticum", strain_name="multiple strains (exact designations not in abstract)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="No domestication described.",
         manipulation_category="transposon mutagenesis", manipulation_detail="Same Tn4001-based mini-transposon protocol attempted in parallel.",
         outcome="failure", failure_reason="Despite large sequence homology to the successfully-transformed U. parvum, transformation failed for all but one isolate.",
         evidence_text="Despite the large degree of homology between Ureaplasma parvum and Ureaplasma urealyticum, all attempts to transform the latter in parallel failed, with the exception of a single clinical U. urealyticum isolate.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="host-associated",
         qc_flags="strain_uncertain", notes="Paired failure/single-exception-success set, matches spec's Vibrio-sp.-X worked example."),
    dict(organism_name="Ureaplasma urealyticum", strain_name="single clinical isolate (exact designation not in abstract)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Described as a clinical isolate; no domestication markers.",
         manipulation_category="transposon mutagenesis", manipulation_detail="Same Tn4001-based mini-transposon protocol; this one isolate succeeded where all sibling strains failed.",
         outcome="success", failure_reason="",
         evidence_text="all attempts to transform the latter in parallel failed, with the exception of a single clinical U. urealyticum isolate.",
         section_name="abstract", marine_status="unknown", isolation_source="clinical isolate", environment="host-associated",
         qc_flags="strain_uncertain", notes=""),
]),
("Pf198f9eb69d2", [
    dict(organism_name="Chlamydia trachomatis", strain_name="not specified in abstract (protocol chapter)", organism_domain="bacteria",
         wild_type_status="unclear", wild_type_evidence="Protocol/methods chapter; specific strain lineage not stated in the abstract, though FRAEM is an established method in this field.",
         manipulation_category="allelic exchange", manipulation_detail="Fluorescence-Reported Allelic Exchange Mutagenesis (FRAEM) using suicide vector pSUmC for complete chromosomal gene deletions.",
         outcome="success", failure_reason="",
         evidence_text="Fluorescence-reported allelic exchange mutagenesis (FRAEM), using the suicide vector pSUmC, enables targeted deletion of desired chromosomal DNA.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="host-associated",
         qc_flags="strain_uncertain wild_type_uncertain", notes="Methods-in-Molecular-Biology protocol chapter, not a primary results paper; kept because it documents a specific established successful method rather than being a pure review."),
]),
("Pcd139fa7a701", [
    dict(organism_name="Clostridium thermocellum", strain_name="not specified in abstract", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Described as lagging model organisms in genetic tractability, i.e., a non-model wild-type-derived strain; no domestication markers given.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="Native Type I-B CRISPR system repurposed for genome editing; introduces a nonsense mutation into pyrF via homology-directed repair, combined with novel thermophilic recombinases (Acidithiobacillus caldus exo/beta homologs).",
         outcome="success", failure_reason="",
         evidence_text="For the Type I-B system an engineered strain, termed LL1586, yielded 40% genome editing efficiency at the pyrF locus and when recombineering machinery was expressed this increased to 71%.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes="Paired with heterologous Type II system below."),
    dict(organism_name="Clostridium thermocellum", strain_name="not specified in abstract", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Same species/background as above.",
         manipulation_category="other CRISPR-Cas systems", manipulation_detail="Heterologous Type II GeoCas9 (from Geobacillus stearothermophilus) tested among three thermophilic Cas9 variants.",
         outcome="success", failure_reason="",
         evidence_text="We tested three thermophilic Cas9 variants (Type II) and found that GeoCas9, isolated from Geobacillus stearothermophilus, is active in C. thermocellum. ... For the Type II GeoCas9 system, 12.5% genome editing efficiency was observed and when recombineering machinery was expressed, this increased to 94%.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes="Also notes homologous recombination was the rate-limiting step for both editing systems -- mechanistic failure detail worth a full-text follow-up."),
]),
("P39329395b93b", [
    dict(organism_name="Clostridium cellulovorans", strain_name="743B (wild-type)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Explicitly 'the C. cellulovorans wildtype strain 743B'.",
         manipulation_category="conjugation", manipulation_detail="Attempted conjugative plasmid transfer into the unmodified wild-type recipient.",
         outcome="failure", failure_reason="Native SMC-like Wadjet system (jetABCD) restricts plasmid uptake by conjugation.",
         evidence_text="This study demonstrates the impact of a Structure Maintenance of Chromosome (SMC)-like Wadjet system on the horizontal gene transfer of plasmids by conjugation to a recipient that naturally containing such a system for the first time.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes="Textbook WT-vs-engineered-derivative pair, spec section 8 example; paired with ΔjetABCD success row below."),
    dict(organism_name="Clostridium cellulovorans", strain_name="ΔjetABCD (derived from wildtype 743B)", organism_domain="bacteria",
         wild_type_status="no", wild_type_evidence="Engineered markerless chromosomal deletion of jetABCD from the wild-type 743B strain.",
         manipulation_category="conjugation", manipulation_detail="Conjugative plasmid transfer into the jetABCD deletion mutant.",
         outcome="success", failure_reason="",
         evidence_text="The transconjugation frequency of the jetABCD mutant was increased by about five orders of magnitude compared to wildtype C. cellulovorans recipient cells.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="unknown",
         qc_flags="", notes="Secondary/engineered-derivative record per spec section 8."),
]),
("P784f53e48d7c", [
    dict(organism_name="brown algae (Ectocarpus and 3 other species)", strain_name="not specified in abstract", organism_domain="eukaryota",
         wild_type_status="unclear", wild_type_evidence="Wild/natural strain status not explicitly confirmed in the abstract, though described as a previously recalcitrant non-model lineage.",
         manipulation_category="other CRISPR-Cas systems", manipulation_detail="PEG-mediated Cas12 RNP delivery (temperature-tolerant Cas12 variant), transgene-free, applied across 4 brown algal species including kelps.",
         outcome="success", failure_reason="Prior methods were inadequate; kelps were 'long considered recalcitrant to transformation'.",
         evidence_text="The protocol was readily transferrable to other species, including kelps long considered recalcitrant to transformation.",
         section_name="abstract", marine_status="marine", isolation_source="marine", environment="marine",
         qc_flags="strain_uncertain", notes="Multicellular marine algae, not strictly unicellular; kept per spec's broad microbial-eukaryote allowance but flagged for domain review."),
]),
("Pc2aeffefadb1", [
    dict(organism_name="Leuconostoc mesenteroides", strain_name="H32-02 Ksu", organism_domain="bacteria",
         wild_type_status="unclear", wild_type_evidence="Described as a food-biotechnology production strain; not explicitly confirmed free of prior lab adaptation.",
         manipulation_category="electroporation", manipulation_detail="Electroporation protocol optimization (cell-wall weakening, osmotic protection, pulse tuning, plasmid methylation matching to host restriction profile).",
         outcome="success", failure_reason="Baseline protocols were inconsistent/irreproducible before optimization.",
         evidence_text="even widely accepted electroporation methodologies often yield inconsistent or irreproducible transformation results ... The combined optimization resulted in an approximately 40-fold increase in transformation efficiency compared to the baseline level and, for the first time, provided consistently reproducible access to transformants of this strain.",
         section_name="abstract", marine_status="unknown", isolation_source="food/industrial", environment="industrial",
         qc_flags="wild_type_uncertain", notes=""),
]),
("Pcb4a6fe7dfb6", [
    dict(organism_name="Chlamydia trachomatis", strain_name="plasmid-free recipient (exact designation not in abstract)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Plasmid-free reference recipient strain used directly for transformation; no domestication described.",
         manipulation_category="plasmid transformation", manipulation_detail="Transformation attempt with an engineered plasmid lacking the Pgp2 β-hairpin motif (11 amino acids deleted).",
         outcome="failure", failure_reason="Deletion of the Pgp2 β-hairpin motif abolished the replication initiator's iteron-binding function needed for plasmid replication.",
         evidence_text="Although this deletion did not alter the overall structure of Pgp2, the mutated plasmid failed to transform plasmid-free C. trachomatis.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="host-associated",
         qc_flags="strain_uncertain", notes="Failure attributable to the plasmid construct, not the recipient strain's intrinsic competence."),
]),
("Pfbb0f2088e38", [
    dict(organism_name="Alcaligenes faecalis", strain_name="J481", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Described as 'an environmentally significant bacterium'; no domestication markers given.",
         manipulation_category="other CRISPR-Cas systems", manipulation_detail="Heterologous CRISPR-Cas systems attempted prior to this study.",
         outcome="failure", failure_reason="Cytotoxicity of the heterologous CRISPR-Cas system.",
         evidence_text="technologies based on heterologous CRISPR-Cas systems failed due to cytotoxicity.",
         section_name="abstract", marine_status="unknown", isolation_source="environmental isolate", environment="unknown",
         qc_flags="", notes="Paired with native-system success row below."),
    dict(organism_name="Alcaligenes faecalis", strain_name="J481", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Same strain as above.",
         manipulation_category="other CRISPR-Cas systems", manipulation_detail="Endogenous type I-F CRISPR-Cas system repurposed for genome editing; PheS-mutant counterselection marker for plasmid curing.",
         outcome="success", failure_reason="",
         evidence_text="The toolkit enables efficient single-gene knockout and accomplishes the previously unattainable precise deletion of large genomic fragments. By engineering a PheS-mutant counterselection marker, we achieved rapid plasmid curing, allowing two rounds of large-fragment removal (~47 kb total) within 5 days.",
         section_name="abstract", marine_status="unknown", isolation_source="environmental isolate", environment="unknown",
         qc_flags="", notes=""),
]),
("Pf1aff6378733", [
    dict(organism_name="Escherichia coli", strain_name="Nissle 1917 (wild-type)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Explicitly 'wild-type EcN' as the comparator to the engineered landing-pad strain.",
         manipulation_category="electroporation", manipulation_detail="Direct electroporation of large (17-29 kb) exogenous DNA fragments.",
         outcome="failure", failure_reason="Could not stably maintain large plasmids after direct electroporation.",
         evidence_text="direct electroporation failed to stably maintain large plasmids in wild-type EcN.",
         section_name="abstract", marine_status="unknown", isolation_source="probiotic/host-associated", environment="host-associated",
         qc_flags="", notes="Paired with engineered-landing-pad success row below."),
    dict(organism_name="Escherichia coli", strain_name="Nissle 1917 EcN-lox (engineered landing-pad derivative)", organism_domain="bacteria",
         wild_type_status="no", wild_type_evidence="EcN-lox carries an engineered loxP-hyg-lox5171 cassette replacing native clbB, built specifically as a recombination landing pad.",
         manipulation_category="stable genomic integration", manipulation_detail="Recombinase-mediated cassette exchange (RMCE) to integrate large DNA fragments (17 kb, 29 kb; ultimately a 10-kb astaxanthin operon) at the engineered landing pad.",
         outcome="success", failure_reason="",
         evidence_text="this RMCE system exhibited superior efficiency in integrating large exogenous DNA fragments, successfully mediating the integration of 17 kb and 29 kb gene cluster segments, while direct electroporation failed to stably maintain large plasmids in wild-type EcN.",
         section_name="abstract", marine_status="unknown", isolation_source="probiotic/host-associated", environment="host-associated",
         qc_flags="", notes="Secondary/engineered-derivative record per spec section 8."),
]),
("Pe96591953493", [
    dict(organism_name="Bifidobacterium animalis subsp. lactis", strain_name="6 commercial strains (exact designations not in abstract)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Commercial probiotic strains; described as 'this species remains difficult to engineer' with no stated prior domestication.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="Endogenous Type I-G CRISPR-Cas system leveraged for genome editing; redesigned backbone plasmids (pBC1 origin, chloramphenicol marker) tested across 6 strains for transformation efficiency.",
         outcome="success", failure_reason="",
         evidence_text="A vector carrying the pBC1 origin coupled with a chloramphenicol resistance marker improved transformation in most strains. ... we generated knockouts in three glycoside hydrolases within the Balac 1593-1601 cluster",
         section_name="abstract", marine_status="unknown", isolation_source="probiotic/host-associated", environment="host-associated",
         qc_flags="strain_uncertain", notes="Individual commercial strain designations not given in abstract."),
]),
("Pc0e19cb63463", [
    dict(organism_name="Aspergillus calidoustus", strain_name="not specified in abstract", organism_domain="eukaryota",
         wild_type_status="unclear", wild_type_evidence="Described as 'a non-model environmental mold'; exact strain lineage not given.",
         manipulation_category="CRISPR-Cas9", manipulation_detail="Expression-free CRISPR/Cas9-directed mutagenesis (short homology regions guiding integration of a nourseothricin-resistance cassette at CRISPR/Cas9-induced double-strand breaks) targeting pyrG.",
         outcome="success", failure_reason="",
         evidence_text="we have deleted A. calidoustus pyrG, encoding orotidine-5'-phosphate decarboxylase, using short regions of homology to guide on-target integration of a nourseothricin resistance cassette (NatR) to CRISPR/Cas9-induced double strand breaks. We genotypically and phenotypically validated two A. calidoustus ΔpyrG deletion strains",
         section_name="abstract", marine_status="unknown", isolation_source="soil", environment="soil",
         qc_flags="strain_uncertain", notes="Filamentous soil mold (eukaryote), kept per spec section 12 as a non-bacterial record."),
]),
("P22d90c522a7c", [
    dict(organism_name="Rhizobium etli", strain_name="strain carrying native plasmid p42d", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="No domestication described; standard R. etli strain carrying its native repABC plasmid.",
         manipulation_category="plasmid introduction", manipulation_detail="Attempted introduction of a minimal repC-based replicon (from the same p42d repABC system) into a strain already carrying native p42d.",
         outcome="failure", failure_reason="Incompatibility: RepC of the same origin acts as an incompatibility factor, blocking introduction of a second copy.",
         evidence_text="The minimal replicon could not be introduced into R. etli strain containing p42d, but similar constructs that carried repC from Sinorhizobium meliloti pSymA or the linear chromosome of Agrobacterium tumefaciens replicated in the presence or absence of p42d, indicating that RepC is an incompatibility factor.",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="soil",
         qc_flags="", notes="Paired with heterologous-replicon success row below."),
    dict(organism_name="Rhizobium etli", strain_name="strain carrying native plasmid p42d", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Same strain background as above.",
         manipulation_category="plasmid introduction", manipulation_detail="Introduction of a repC-based minimal replicon carrying repC from a heterologous source (Sinorhizobium meliloti pSymA or Agrobacterium tumefaciens linear chromosome).",
         outcome="success", failure_reason="",
         evidence_text="similar constructs that carried repC from Sinorhizobium meliloti pSymA or the linear chromosome of Agrobacterium tumefaciens replicated in the presence or absence of p42d",
         section_name="abstract", marine_status="unknown", isolation_source="unknown", environment="soil",
         qc_flags="", notes=""),
]),
("P27ec52fc562a", [
    dict(organism_name="Salmonella enterica serovar Enteritidis", strain_name="SH12G706-C (transformant) / CRSE isolate panel", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Clinical/food-source CRSE isolates from an epidemiological survey; no domestication described.",
         manipulation_category="conjugation", manipulation_detail="Conjugation and chemical-transformation experiments used to demonstrate mobility of blaCTX-M-55-carrying plasmids.",
         outcome="success", failure_reason="",
         evidence_text="Conjugation and transformation experiments along with plasmid replicon typing revealed that blaCTX-M-55 was located on plasmids of various replicon types with sizes ranging from 76.8 to 138.9 kb.",
         section_name="abstract", marine_status="unknown", isolation_source="clinical/food isolate", environment="host-associated",
         qc_flags="strain_uncertain", notes="AMR-surveillance paper; conjugation/transformation used as a mechanistic confirmation step rather than the paper's central aim, but a genuine successful manipulation attempt nonetheless."),
]),
("P26462f6ed9b0", [
    dict(organism_name="Klebsiella pneumoniae", strain_name="KPTCM", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Clinical bloodstream-infection isolate; no domestication described.",
         manipulation_category="conjugation", manipulation_detail="Conjugation and chemical transformation experiments performed as part of strain characterization.",
         outcome="success", failure_reason="",
         evidence_text="Conjugation, chemical transformation, string test and Galleria mellonella infection model experiments were also conducted.",
         section_name="abstract", marine_status="unknown", isolation_source="clinical isolate", environment="host-associated",
         qc_flags="strain_uncertain outcome_uncertain", notes="Abstract confirms the experiments were run but does not state the conjugation/transformation result explicitly; outcome inferred as attempted/likely successful given downstream WGS of a resulting construct. Flagged for full-text confirmation."),
]),
("Peee22fa6dc9e", [
    dict(organism_name="Klebsiella pneumoniae", strain_name="3 KPC-14-producing CRKP isolates (exact designations not in abstract)", organism_domain="bacteria",
         wild_type_status="yes", wild_type_evidence="Clinical isolates from ICU patients; no domestication described.",
         manipulation_category="conjugation", manipulation_detail="Conjugation experiments testing horizontal transfer of an IncFII/IncR plasmid carrying blaKPC-14 into E. coli EC600, alone vs. co-transfer with a second plasmid-borne tet(A) gene.",
         outcome="mixed", failure_reason="Single-gene transfer of blaKPC-14 alone on the IncFII/IncR plasmid failed; only co-transfer with the tet(A)-carrying element succeeded.",
         evidence_text="The horizontal transferability of these integrated plasmids to Escherichia coli EC600 was confirmed by the cotransmission of tet(A) and blaKPC-14 genes, but the single transfer of blaKPC-14 on the IncFII/IncR plasmid failed.",
         section_name="abstract", marine_status="unknown", isolation_source="clinical isolate", environment="host-associated",
         qc_flags="strain_uncertain", notes="Direct example of a documented conjugation failure alongside a successful co-transfer, from a clinical AMR paper."),
]),
]

SKIPPED = [
    ("P99f66ce8a541", "Genome Editing Methods for Bacillus subtilis",
     "review_only_evidence", "Methods-in-Molecular-Biology protocol chapter describing multiple methods generically; no single strain/experiment/outcome to anchor an observation.", ""),
    ("Pd10f315292cc", "A global survey of Salmonella plasmids and their associations with antimicrobial resistance",
     "review_only_evidence", "Europe PMC returned no abstract text for this record; appears to be a bioinformatics/genomics survey with no manipulation attempt.", "Needs full text or direct journal check."),
    ("P4ce71d3fe20f", "Plasmid-Mediated Transmission of KPC-2 Carbapenemase in Enterobacteriaceae in Critically Ill Patients",
     "outcome_uncertain", "Abstract confirms transconjugants existed (implying successful conjugation was performed) but does not name the exact recipient/donor strains used in the lab conjugation step.", "Candidate for full-text extraction."),
    ("P0f31d735a2d2", "Intragenomic conflicts with plasmids and chromosomal mobile genetic elements drive the evolution of natural transformation within species",
     "strain_uncertain", "Aggregate natural-competence survey across 786 Legionella pneumophila and 496 Acinetobacter baumannii strains; no single strain's result is stated in the abstract, so it does not fit the per-strain observation schema without full-text/supplementary-table extraction.", "Good candidate for a dedicated large-panel extraction pass later."),
    ("P64f75ba0b78b", "Genetic Manipulation of Neisseria gonorrhoeae and Commensal Neisseria Species",
     "review_only_evidence", "Current Protocols methods article describing established techniques generically (no single new strain/outcome reported in the abstract).", "High background value as a discovery source; revisit with full text for named strains."),
    ("Pd453e0841397", "Naturally competent bacteria and their genetic parasites-a battle for control over horizontal gene transfer?",
     "review_only_evidence", "Review paper (already captured in review_seeds.csv); excluded from the evidence table per spec.", ""),
    ("P31cd342b502e", "The virulence regulator CovR boosts CRISPR-Cas9 immunity in Group B Streptococcus",
     "review_only_evidence", "Describes CRISPR-Cas9 as a naturally occurring bacterial immune system regulated by CovR, not a researcher-driven genome-engineering attempt -- excluded per spec section 2.", ""),
    ("P9021453ce99e", "Mobilizable Rolling-Circle Replicating Plasmids from Gram-Positive Bacteria: A Low-Cost Conjugative Transfer",
     "review_only_evidence", "Framed and written as a review of existing plasmid families/mechanisms rather than a new manipulation attempt.", ""),
    ("P3e526c951d55", "Synthetically designed anti-defense proteins overcome barriers to bacterial transformation and phage infection",
     "strain_uncertain", "Abstract describes the general approach (de novo anti-defense proteins enabling transformation of otherwise-restrictive bacteria) but names no specific organism/strain.", "High-value candidate; needs full text for strain identities."),
    ("Pf6df18e8f504", "Genetic modification of intractable bacterial clones by heat shock-facilitated phage transduction",
     "strain_uncertain", "Describes success across 'non-Staphylococcus aureus (NAS) staphylococci' and other Bacillota/Actinomycetota generically; no individual strain identifiers given in the abstract.", "High-value candidate; needs full text for strain identities."),
    ("Pfd79065d79b3", "Plasmodium berghei High-Throughput (PbHiT): a CRISPR-Cas9 System to Study Genes at Scale",
     "strain_uncertain", "Unicellular eukaryotic parasite (apicomplexan) kept in candidate_papers.csv per spec section 12, but abstract names no specific strain (ANKA is field-standard but not stated here) and is a generic protocol description.", "organism_domain=eukaryota if revisited."),
]


def main() -> None:
    obs_rows = []
    for paper_id, rows in RAW:
        for i, row in enumerate(rows, start=1):
            row = dict(row)
            row["observation_id"] = make_observation_id(paper_id, i)
            row["paper_id"] = paper_id
            row["genome_accession"] = ""
            row["genome_match_status"] = "not_checked"
            obs_rows.append(row)

    write_csv_dicts(DATA_DIR / "manipulation_observations.csv", obs_rows, OBS_FIELDNAMES)

    manual_review_rows = [
        dict(paper_id=pid, title=title, issue_type=issue, description=desc, notes=notes)
        for pid, title, issue, desc, notes in SKIPPED
    ]
    write_csv_dicts(DATA_DIR / "manual_review.csv", manual_review_rows, MANUAL_REVIEW_FIELDNAMES)

    n_papers = len(set(r["paper_id"] for r in obs_rows))
    print(f"Wrote {len(obs_rows)} manipulation observations from {n_papers} papers")
    print(f"Wrote {len(manual_review_rows)} manual_review rows")


if __name__ == "__main__":
    main()
