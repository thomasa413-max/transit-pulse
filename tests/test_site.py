"""Site checks: translations complete, SEO tags consistent, sitemap valid. Offline."""
import json
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

from pulse import config, i18n, site


class TestTranslations(unittest.TestCase):
    def test_every_key_in_every_language(self):
        for key, values in i18n.T.items():
            self.assertEqual(set(values), set(i18n.LANGS), key)
            for lang, v in values.items():
                self.assertTrue(v or (key == "translation_missing" and lang == "fr"), f"{key}/{lang} empty")

    def test_placeholders_match(self):
        for key, values in i18n.T.items():
            if not isinstance(values["en"], str):
                continue
            ref = set(re.findall(r"{(\w+)}", values["en"]))
            for lang, v in values.items():
                if v:
                    self.assertEqual(set(re.findall(r"{(\w+)}", v)), ref, f"{key}/{lang}")

    def test_swiss_german_spelling(self):
        for key, values in i18n.T.items():
            text = json.dumps(values["de"], ensure_ascii=False)
            self.assertNotIn("ß", text, key)

    def test_slugs_unique_per_language(self):
        for lang, slugs in i18n.SLUGS.items():
            self.assertEqual(len(set(slugs.values())), len(slugs), lang)


class TestBuiltSite(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = Path(tempfile.mkdtemp())
        cls.saved = config.PUBLIC
        config.PUBLIC = cls.tmp / "public"
        site.build()

    @classmethod
    def tearDownClass(cls):
        config.PUBLIC = cls.saved
        shutil.rmtree(cls.tmp)

    def pages(self):
        return [p for p in config.PUBLIC.rglob("*.html") if "admin" not in p.parts]

    def test_each_page_has_lang_title_description_canonical(self):
        for p in self.pages():
            html = p.read_text(encoding="utf-8")
            lang = p.relative_to(config.PUBLIC).parts[0]
            self.assertIn(f'<html lang="{lang}">', html, p)
            self.assertRegex(html, r"<title>[^<]{5,}</title>", p)
            self.assertRegex(html, r'<meta name="description" content="[^"]{30,}"', p)
            self.assertIn('rel="canonical"', html, p)
            self.assertEqual(html.count("<h1"), 1, f"one h1: {p}")

    def test_hreflang_is_reciprocal(self):
        index = {}
        for p in self.pages():
            if p.name == "404.html":
                continue
            html = p.read_text(encoding="utf-8")
            canon = re.search(r'rel="canonical" href="([^"]+)"', html).group(1)
            alts = dict(re.findall(r'hreflang="([\w-]+)" href="([^"]+)"', html))
            self.assertEqual(set(alts), set(i18n.LANGS) | {"x-default"}, p)
            index[canon] = alts
        for canon, alts in index.items():
            for lang in i18n.LANGS:
                self.assertIn(alts[lang], index, f"{canon} → {alts[lang]} missing")
                self.assertEqual(index[alts[lang]], alts, f"not reciprocal: {canon}")

    def test_jsonld_is_valid_json(self):
        for p in self.pages():
            for block in re.findall(r'<script type="application/ld\+json">(.*?)</script>', p.read_text(encoding="utf-8")):
                data = json.loads(block)
                self.assertEqual(data["@context"], "https://schema.org")

    def test_internal_links_resolve(self):
        for p in self.pages():
            for href in re.findall(r'href="(/[^"#?]*)', p.read_text(encoding="utf-8")):
                if href.startswith(("/api/", "/admin")) or href == "/":
                    continue
                target = config.PUBLIC / href.lstrip("/")
                ok = target.is_file() or (target / "index.html").is_file()
                self.assertTrue(ok, f"{p.relative_to(config.PUBLIC)} → {href}")

    def test_sitemap_and_robots(self):
        root = ET.parse(config.PUBLIC / "sitemap.xml").getroot()
        locs = [e.text for e in root.iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        self.assertEqual(len(locs), len(set(locs)))
        self.assertTrue(all(l.startswith(config.SITE_URL) for l in locs))
        robots = (config.PUBLIC / "robots.txt").read_text()
        if config.INDEXING:
            self.assertIn("Sitemap:", robots)
        else:
            self.assertIn("Disallow: /", robots)
            self.assertIn("noindex", (config.PUBLIC / "_headers").read_text())

    def test_no_inline_scripts_or_styles(self):
        for p in config.PUBLIC.rglob("*.html"):
            html = p.read_text(encoding="utf-8")
            for tag in re.findall(r"<script(?![^>]*\bsrc=)(?![^>]*application/(?:ld\+)?json)[^>]*>", html):
                self.fail(f"inline script in {p}: {tag}")
            self.assertNotRegex(html, r'\sstyle="', p)
            self.assertNotRegex(html, r"\son[a-z]+=", p)


if __name__ == "__main__":
    unittest.main()
