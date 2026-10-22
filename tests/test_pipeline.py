"""Offline tests: no network, no API key. Run with `python -m unittest -v`."""
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

os.environ["PULSE_FAKE_LLM"] = "1"

from pulse import config, disruptions, factcheck, istdaten  # noqa: E402

FIX = Path(__file__).parent / "fixtures"
DAY = date(2026, 10, 21)


class TestMeasure(unittest.TestCase):
    def row(self, **kw):
        base = {"HALTESTELLEN_NAME": "Lausanne", "ABFAHRTSZEIT": "21.10.2026 08:00",
                "AB_PROGNOSE": "21.10.2026 08:02:30", "AB_PROGNOSE_STATUS": "REAL",
                "FAELLT_AUS_TF": "false", "DURCHFAHRT_TF": "false", "PRODUKT_ID": "Zug"}
        base.update(kw)
        return base

    def test_real_departure(self):
        kind, delay, hour = istdaten.measure(self.row())
        self.assertEqual((kind, round(delay, 1), hour), ("measured", 2.5, 8))

    def test_estimated_is_not_measured(self):
        self.assertEqual(istdaten.measure(self.row(AB_PROGNOSE_STATUS="ESTIMATED"))[0], "unmeasured")

    def test_cancelled(self):
        self.assertEqual(istdaten.measure(self.row(FAELLT_AUS_TF="true"))[0], "cancelled")

    def test_pass_through_skipped(self):
        self.assertEqual(istdaten.measure(self.row(DURCHFAHRT_TF="true"))[0], "skip")

    def test_arrival_used_at_terminus(self):
        r = self.row(ABFAHRTSZEIT="", AB_PROGNOSE="", AB_PROGNOSE_STATUS="",
                     ANKUNFTSZEIT="21.10.2026 09:00", AN_PROGNOSE="21.10.2026 09:04:00", AN_PROGNOSE_STATUS="REAL")
        kind, delay, _ = istdaten.measure(r)
        self.assertEqual((kind, delay), ("measured", 4.0))

    def test_implausible_delay_dropped(self):
        self.assertEqual(istdaten.measure(self.row(AB_PROGNOSE="22.10.2026 08:00:00"))[0], "unmeasured")


class TestAggregate(unittest.TestCase):
    def test_sample_file(self):
        with (FIX / "sample_istdaten.csv").open(encoding="utf-8-sig") as fh:
            agg = istdaten.aggregate(istdaten.parse_lines(fh, istdaten.lausanne_line_filter), DAY)
        t = agg["total"]
        self.assertGreater(t["mesures"], 1000)
        self.assertTrue(0 < t["ponctualite_pct"] <= 100)
        # "Renens VD" is outside the area and must be ignored.
        self.assertNotIn("Renens VD", [s["arret"] for s in agg["arrets_moins_ponctuels"]])
        self.assertTrue(agg["lignes_moins_ponctuelles"])

    def test_streamed_bytes(self):
        raw = [b"\xef\xbb\xbfHALTESTELLEN_NAME;ABFAHRTSZEIT;AB_PROGNOSE;AB_PROGNOSE_STATUS;PRODUKT_ID\r",
               "Lausanne, Ch\u00e8vres;21.10.2026 08:00;21.10.2026 08:05:00;REAL;Bus".encode()]
        agg = istdaten.aggregate(istdaten.parse_lines(istdaten.decode_lines(raw)), DAY)
        self.assertEqual(agg["total"]["mesures"], 1)
        self.assertEqual(agg["total"]["ponctualite_pct"], 0.0)

    def test_comma_delimiter(self):
        lines = ["HALTESTELLEN_NAME,ABFAHRTSZEIT,AB_PROGNOSE,AB_PROGNOSE_STATUS,PRODUKT_ID",
                 "Lausanne,21.10.2026 08:00,21.10.2026 08:01:00,REAL,Bus"]
        agg = istdaten.aggregate(istdaten.parse_lines(iter(lines)), DAY)
        self.assertEqual(agg["total"]["mesures"], 1)
        self.assertEqual(agg["total"]["ponctualite_pct"], 100.0)


class TestFindLinks(unittest.TestCase):
    def test_dataset_page_links(self):
        html = ('<a href="https://data.opentransportdata.swiss/en/dataset/febff1f3/resource/aa/download/2026-10-21_istdaten.csv">x</a>'
                '<a href="https://data.opentransportdata.swiss/en/dataset/febff1f3/resource/bb/download/2026-10-20_IstDaten.csv">y</a>')
        links = istdaten.find_links(html)
        self.assertEqual(sorted(links), ["2026-10-20", "2026-10-21"])
        self.assertTrue(links["2026-10-21"].endswith("/aa/download/2026-10-21_istdaten.csv"))


class TestFactCheck(unittest.TestCase):
    facts = {"global": {"ponctualite_pct": 92.4, "mesures": 1234}, "lignes": [{"ligne": "9", "heure": 8}]}

    def test_numbers_in_text(self):
        self.assertEqual(factcheck.numbers_in_text("92,4 % sur 1'234 passages, ligne M2 à 8 h"), [92.4, 1234.0, 8.0])
        self.assertEqual(factcheck.numbers_in_text("à 7:00 puis 07:15"), [7.0, 7.0, 15.0])

    def test_known_numbers_pass(self):
        text = "Le 21 octobre 2026, 92,4 % des 1'234 passages étaient à l'heure ; la ligne 9 souffre à 8 h."
        self.assertEqual(factcheck.unknown_numbers(text, self.facts, DAY), [])

    def test_rounding_allowed(self):
        self.assertEqual(factcheck.unknown_numbers("environ 92 %", self.facts, DAY), [])

    def test_invented_number_flagged(self):
        self.assertEqual(factcheck.unknown_numbers("88,1 % à l'heure", self.facts, DAY), [88.1])

    def test_translation_numbers(self):
        ok, _, _ = factcheck.same_numbers("92,4 % à 8 h", "92.4% at 8:00")
        self.assertTrue(ok)
        ok, missing, extra = factcheck.same_numbers("92,4 % à 8 h", "92.4% at 9:00")
        self.assertFalse(ok)
        self.assertEqual((missing, extra), ([8.0], [9.0]))


class TestTranslationKeys(unittest.TestCase):
    def test_translated_keys_are_normalised(self):
        from pulse.agents import _normalise_keys
        b = _normalise_keys({"titel": "T", "paragraphen": '["a", "b"]'})
        self.assertEqual(b, {"titre": "T", "paragraphes": ["a", "b"]})
        self.assertEqual(_normalise_keys({"title": "T", "paragraphs": ["x"]})["paragraphes"], ["x"])


class TestDisruptions(unittest.TestCase):
    def test_parse_filters_lausanne_active(self):
        at = datetime(2026, 10, 22, 12, tzinfo=timezone.utc)
        with (FIX / "sample_siri_sx.xml").open("rb") as fh:
            res = disruptions.parse_feed(fh, at)
        self.assertEqual(res["situations_suisse"], 3)
        self.assertEqual(res["actives_suisse"], 2)
        self.assertEqual(len(res["lausanne"]), 1)
        s = res["lausanne"][0]
        self.assertEqual(s["titre"], "Travaux à Lausanne, Bel-Air")
        self.assertTrue(s["planifie"])
        self.assertEqual(s["lignes"], ["9"])


class TestEndToEnd(unittest.TestCase):
    """Daily job + site build with the fake model, in a temporary data folder."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.saved = {k: getattr(config, k) for k in
                      ("DATA", "DAILY_DIR", "BULLETIN_DIR", "DISRUPTION_FILE", "RUN_LOG", "PUBLIC")}
        config.DATA = self.tmp / "data"
        config.DAILY_DIR = config.DATA / "daily"
        config.BULLETIN_DIR = config.DATA / "bulletins"
        config.DISRUPTION_FILE = config.DATA / "disruptions" / "latest.json"
        config.RUN_LOG = config.DATA / "runs.jsonl"
        config.PUBLIC = self.tmp / "public"

    def tearDown(self):
        for k, v in self.saved.items():
            setattr(config, k, v)
        shutil.rmtree(self.tmp)

    def test_daily_then_site(self):
        from pulse import daily, site, util
        code = daily.run(DAY, sample=FIX / "sample_istdaten.csv")
        self.assertEqual(code, 0)
        b = util.read_json(config.BULLETIN_DIR / "2026-10-21.json")
        self.assertEqual(b["statut"], "publie")
        self.assertEqual(sorted(k for k in ("de", "it", "en") if k in b), ["de", "en", "it"])
        # Running again is a no-op.
        self.assertEqual(daily.run(DAY, sample=FIX / "sample_istdaten.csv"), 0)
        site.build()
        for p in ("index.html", "bulletin/index.html", "bulletin/2026-10-21/index.html",
                  "agents/index.html", "qualite/index.html", "couts/index.html", "a-propos/index.html", "_headers"):
            self.assertTrue((config.PUBLIC / p).exists(), p)
        html = (config.PUBLIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('lang="fr"', html)
        self.assertIn("noindex", html)


if __name__ == "__main__":
    unittest.main()
