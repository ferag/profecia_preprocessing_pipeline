from __future__ import annotations

import json
import os
import re
import unittest
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from rdflib import Graph

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CRATE = ROOT / "resources/data_releases/profecia_inputs_all_available_v0/ro-crate"
CRATE = Path(os.environ.get("PROFECIA_CRATE", DEFAULT_CRATE))


def one_or_many(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def ids(value):
    return [item["@id"] for item in one_or_many(value) if isinstance(item, dict) and item.get("@id")]


def types(entity):
    return set(one_or_many(entity.get("@type")))


class TestProfeciaRoCrate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata_path = CRATE / "ro-crate-metadata.json"
        if not cls.metadata_path.exists() and "PROFECIA_CRATE" not in os.environ:
            raise unittest.SkipTest("Generate a scientific crate or set PROFECIA_CRATE to validate an existing one")
        cls.crate = json.loads(cls.metadata_path.read_text(encoding="utf-8"))
        cls.graph = cls.crate["@graph"]
        cls.by_id = {entity["@id"]: entity for entity in cls.graph}

    def test_01_json_valid(self):
        self.assertIsInstance(self.crate, dict)
        self.assertIsInstance(self.graph, list)

    def test_02_jsonld_expandible(self):
        graph = Graph().parse(data=json.dumps(self.crate), format="json-ld", publicID=CRATE.resolve().as_uri() + "/")
        self.assertGreater(len(graph), 1000)

    def test_03_ids_unique(self):
        all_ids = [entity["@id"] for entity in self.graph]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_04_no_broken_local_references(self):
        reference_keys = {
            "about", "agent", "conformsTo", "contactPoint", "contentLocation", "creator", "dcat:accessURL",
            "dcat:distribution", "dcat:downloadURL", "dcat:landingPage", "dcat:theme", "dcterms:author",
            "dcterms:conformsTo", "dcterms:contributor", "dcterms:creator", "dcterms:isPartOf", "dcterms:license",
            "dcterms:source", "environment", "exampleOfWork", "funder", "hasPart", "inDefinedTermSet", "input",
            "instrument", "isPartOf", "license", "mainEntity", "maintainer", "mentions", "object", "output",
            "profecia:implementedBy", "profecia:input", "profecia:output", "profecia:parameter", "profecia:qualityControl",
            "profecia:relatedWorkflowAction", "profecia:stepType", "profecia:wasPreprocessedBy", "provider",
            "prov:agent", "prov:generated", "prov:hadPlan", "prov:qualifiedAssociation", "prov:used",
            "prov:wasAssociatedWith", "prov:wasDerivedFrom", "prov:wasGeneratedBy", "publisher", "result",
            "skos:broader", "skos:hasTopConcept", "skos:inScheme", "skos:topConceptOf", "softwareRequirements",
            "subjectOf", "unitCode", "variableMeasured", "workExample",
        }
        broken = []
        for entity in self.graph:
            for key in reference_keys:
                for target in ids(entity.get(key)):
                    if target not in self.by_id and not target.startswith(("http://", "https://", "urn:", "mailto:")):
                        broken.append((entity["@id"], key, target))
        self.assertEqual(broken, [])

    def test_05_root_conformant(self):
        root = self.by_id["./"]
        for key in ("name", "description", "datePublished", "license", "identifier", "version", "mainEntity", "mentions", "hasPart"):
            self.assertIn(key, root)
        self.assertRegex(root["datePublished"], r"^\d{4}-\d{2}-\d{2}")
        self.assertIn("Dataset", types(root))
        self.assertIn("ro-crate-preview.html", ids(root["hasPart"]))
        self.assertTrue((CRATE / "ro-crate-preview.html").exists())

    def test_06_main_entity_valid(self):
        root = self.by_id["./"]
        workflow = self.by_id[ids(root["mainEntity"])[0]]
        self.assertTrue({"File", "SoftwareSourceCode", "ComputationalWorkflow"}.issubset(types(workflow)))
        self.assertIn("programmingLanguage", workflow)

    def test_07_profiles_compatible(self):
        expected = {
            "https://w3id.org/ro/crate/1.1",
            "https://w3id.org/workflowhub/workflow-ro-crate/1.0",
            "https://w3id.org/ro/wfrun/process/0.5",
            "https://w3id.org/ro/wfrun/workflow/0.5",
        }
        self.assertEqual(set(ids(self.by_id["./"]["conformsTo"])), expected)
        self.assertNotIn("https://reliance-eosc.github.io/reliance-ro-crate/", expected)

    def test_08_agents_have_valid_types(self):
        valid = {"Person", "Organization"}
        for action in (e for e in self.graph if "CreateAction" in types(e)):
            for agent_id in ids(action.get("agent")):
                self.assertTrue(types(self.by_id[agent_id]) & valid, (action["@id"], agent_id))
        self.assertIn("prov:SoftwareAgent", types(self.by_id["#workflow-snakemake"]))

    def test_09_scripts_are_not_agents(self):
        agent_targets = {target for e in self.graph for target in ids(e.get("agent")) + ids(e.get("prov:wasAssociatedWith")) + ids(e.get("prov:agent"))}
        bad = [target for target in agent_targets if target in self.by_id and "SoftwareSourceCode" in types(self.by_id[target]) and "prov:SoftwareAgent" not in types(self.by_id[target])]
        self.assertEqual(bad, [])

    def test_10_hadplan_only_on_association(self):
        self.assertTrue(any("prov:hadPlan" in e for e in self.graph))
        self.assertEqual([e["@id"] for e in self.graph if "prov:hadPlan" in e and "prov:Association" not in types(e)], [])

    def test_11_plans_not_activities(self):
        for entity in self.graph:
            if "prov:Plan" in types(entity):
                self.assertNotIn("prov:Activity", types(entity))

    def test_12_object_matches_used(self):
        for action in (e for e in self.graph if "CreateAction" in types(e)):
            self.assertEqual(set(ids(action.get("object"))), set(ids(action.get("prov:used"))), action["@id"])

    def test_13_result_matches_generated(self):
        for action in (e for e in self.graph if "CreateAction" in types(e)):
            self.assertEqual(set(ids(action.get("result"))), set(ids(action.get("prov:generated"))), action["@id"])

    def test_14_generation_inverses(self):
        for action in (e for e in self.graph if "CreateAction" in types(e)):
            for result in ids(action.get("result")):
                self.assertIn(action["@id"], ids(self.by_id[result].get("prov:wasGeneratedBy")), (action["@id"], result))

    def test_15_single_generator(self):
        for entity in self.graph:
            generators = ids(entity.get("prov:wasGeneratedBy"))
            self.assertLessEqual(len(set(generators)), 1, (entity["@id"], generators))

    def test_16_formal_parameters_mapped(self):
        workflow = self.by_id["workflow/Snakefile"]
        formal_ids = set(ids(workflow["input"]) + ids(workflow["output"]))
        self.assertNotIn("#user-settings", formal_ids)
        for parameter_id in formal_ids:
            parameter = self.by_id[parameter_id]
            for key in ("name", "description", "additionalType", "valueRequired", "conformsTo", "workExample"):
                self.assertIn(key, parameter)
            example_id = ids(parameter["workExample"])[0]
            self.assertIn(parameter_id, ids(self.by_id[example_id].get("exampleOfWork")))

    def test_17_common_step_shape(self):
        required = {"name", "description", "profecia:stepType", "profecia:input", "profecia:output", "profecia:method", "profecia:implementedBy", "profecia:relatedWorkflowAction", "profecia:status"}
        explanations = {"profecia:formula", "profecia:parameter", "profecia:rationale", "profecia:qualityControl"}
        for step in (e for e in self.graph if "profecia:PreprocessingStep" in types(e)):
            self.assertFalse(required - set(step), step["@id"])
            self.assertTrue(explanations & set(step), step["@id"])

    def test_18_conditional_step_shapes(self):
        for step in (e for e in self.graph if "profecia:PreprocessingStep" in types(e)):
            step_types = {value.rsplit("/", 1)[-1] for value in ids(step["profecia:stepType"])}
            parameters = {self.by_id[p].get("name") for p in ids(step.get("profecia:parameter"))}
            if "derived-variable" in step_types:
                self.assertIn("profecia:formula", step)
                self.assertTrue(parameters)
                for output_id in ids(step["profecia:output"]):
                    variables = ids(self.by_id[output_id].get("variableMeasured"))
                    self.assertTrue(variables)
                    self.assertTrue(all(self.by_id[v].get("unitText") for v in variables))
            if "temporal-aggregation" in step_types:
                self.assertTrue({"input_frequency", "output_frequency", "aggregation_function"}.issubset(parameters))
                self.assertIn("profecia:missingDataPolicy", step)

    def test_19_skos_scheme_complete(self):
        concepts = [e for e in self.graph if "skos:Concept" in types(e) and e["@id"].startswith("https://w3id.org/profecia/vocab/preprocessing-step-type/")]
        self.assertGreaterEqual(len(concepts), 24)
        for concept in concepts:
            labels = one_or_many(concept.get("skos:prefLabel"))
            self.assertEqual({label.get("@language") for label in labels}, {"en", "es"})
            self.assertIn("skos:definition", concept)
            self.assertIn("skos:inScheme", concept)

    def test_20_units_valid_or_justified(self):
        variables = [e for e in self.graph if "PropertyValue" in types(e) and e["@id"].startswith("#variable-")]
        for variable in variables:
            self.assertNotIn("value", variable)
            self.assertTrue(variable.get("unitCode") or variable.get("profecia:unitStatus"), variable["@id"])

    def test_21_sha256_valid(self):
        for entity in self.graph:
            for digest in one_or_many(entity.get("sha256")):
                self.assertRegex(str(digest), r"^[0-9a-f]{64}$", entity["@id"])

    def test_22_licenses_valid(self):
        licensed = [e for e in self.graph if "license" in e]
        self.assertTrue(licensed)
        for entity in licensed:
            for license_id in ids(entity["license"]):
                self.assertTrue(license_id.startswith("https://spdx.org/licenses/"), (entity["@id"], license_id))

    def test_23_urls_modelled(self):
        for entity in self.graph:
            for key in ("dcat:downloadURL", "dcat:accessURL", "dcat:landingPage"):
                for value in ids(entity.get(key)):
                    self.assertIn(urlparse(value).scheme, {"http", "https"}, (entity["@id"], key, value))

    def test_24_croissant_jsonld(self):
        path = CRATE / "fair/harmonized_netcdf_demo.croissant.jsonld"
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("@context", data)
        self.assertIn("distribution", data)
        Graph().parse(data=json.dumps(data), format="json-ld", publicID=path.resolve().as_uri())

    def test_25_compatibility_properties_equal(self):
        pairs = (("name", "dcterms:title"), ("description", "dcterms:description"), ("license", "dcterms:license"), ("isPartOf", "dcterms:isPartOf"), ("temporalCoverage", "dcterms:temporal"), ("profecia:formula", "mathExpression"))
        for entity in self.graph:
            for canonical, compatibility in pairs:
                if canonical in entity and compatibility in entity:
                    self.assertEqual(entity[canonical], entity[compatibility], (entity["@id"], canonical, compatibility))

    def test_26_profecia_vocabulary_valid(self):
        ttl = CRATE / "metadata/vocabulary/profecia.ttl"
        jsonld = CRATE / "metadata/vocabulary/profecia.jsonld"
        self.assertGreater(len(Graph().parse(ttl, format="turtle")), 100)
        self.assertGreater(len(Graph().parse(jsonld, format="json-ld")), 100)
        self.assertTrue((CRATE / "metadata/vocabulary/index.html").exists())
        self.assertTrue((CRATE / "metadata/vocabulary/shacl/preprocessing-step-common.ttl").exists())
        self.assertTrue((CRATE / "metadata/vocabulary/shacl/preprocessing-step-conditional.ttl").exists())

    def test_27_local_paths_are_not_sole_identifiers(self):
        for entity in self.graph:
            url = entity.get("contentUrl")
            if isinstance(url, str) and url.startswith("/"):
                for key in ("identifier", "description", "profecia:resolutionMethod"):
                    self.assertIn(key, entity, (entity["@id"], key))

    def test_hwsd2_and_aggregate_validation_regressions(self):
        monthly_actions = [e for e in self.graph if e["@id"].startswith("#action-local-hwsd2-monthly-") and e["@id"].endswith("-harmonize")]
        self.assertEqual(len(monthly_actions), 8)
        self.assertTrue(all(len(ids(action["result"])) == 1 for action in monthly_actions))
        release_slug = re.sub(r"[^a-z0-9]+", "-", self.by_id["./"]["identifier"].lower()).strip("-")
        self.assertEqual(ids(self.by_id["validation/harmonized_validation.json"]["prov:wasGeneratedBy"]), [f"#action-validate-harmonized-{release_slug}"])


if __name__ == "__main__":
    unittest.main()
