import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from foody_tool.collector import Collector


class ProvenanceTests(unittest.TestCase):
    def test_filtered_values_have_source_evidence(self):
        url = "https://www.foody.vn/ha-noi/test-provenance"
        body = b'<script>var initData = {"RestaurantID":1,"Name":"test","PriceMin":-5,"PriceMax":NaN,"Latitude":95,"OpeningTime":"bad"};</script>'
        with tempfile.TemporaryDirectory() as folder:
            collector = Collector(folder, fetcher=lambda *args: (
                200, {"content-type": "text/html; charset=utf-8"}, body), min_interval=0)
            collector.process(url)
            evidence = collector.progress[url]["source_keys"]
            self.assertEqual(evidence["PriceMin"]["raw"], -5)
            self.assertEqual(evidence["PriceMax"]["raw"], "NaN")
            self.assertEqual(evidence["Latitude"]["raw"], 95)
            self.assertEqual(evidence["OpeningTime"]["raw"], "bad")
            self.assertIsNone(collector.progress[url]["record"]["price_min_vnd"])
            json.loads(Path(collector.progress_path).read_text(encoding="utf-8"),
                       parse_constant=lambda token: self.fail(token))

    def test_retry_and_redirect_are_distinct(self):
        url = "https://www.foody.vn/ha-noi/test-provenance"
        body = b'<script>var initData = {"RestaurantID":1,"Name":"test"};</script>'
        responses = iter([(503, {}, b""),
                          (302, {"location": "/ha-noi/redirect-target"}, b""),
                          (200, {"content-type": "text/html; charset=utf-8"}, body)])
        with tempfile.TemporaryDirectory() as folder:
            collector = Collector(folder, fetcher=lambda *args: next(responses),
                                  min_interval=0, backoff=0)
            collector.process(url)
            self.assertEqual(collector.progress[url]["attempts"], 3)
            self.assertEqual(collector.progress[url]["retry_count"], 1)
            self.assertEqual(collector.progress[url]["redirect_count"], 1)

    def test_body_hash_cache_refresh_and_changed_cache(self):
        url = "https://www.foody.vn/ha-noi/test-provenance"
        text = '<script>var initData = ' + json.dumps({
            "RestaurantID": 1, "Name": "Quán thử", "PriceMin": 0,
            "PriceMax": 0, "OpeningTime": []}, ensure_ascii=False) + ';</script>'
        body = text.encode("utf-8")
        calls = []

        def fetch(*args):
            calls.append(args)
            return 200, {"content-type": "text/html; charset=utf-8"}, body

        with tempfile.TemporaryDirectory() as folder:
            collector = Collector(folder, fetcher=fetch, min_interval=0)
            self.assertEqual(collector.process(url), "ok")
            first = dict(collector.progress[url])
            self.assertEqual(first["raw_content_hash"], "sha256:" + hashlib.sha256(body).hexdigest())
            self.assertEqual(first["parser_version"], "0.3.0")
            self.assertTrue(first["field_presence"]["price_min_vnd"]["present"])
            self.assertFalse(first["field_presence"]["address"]["present"])
            self.assertEqual(collector.process(url), "ok")
            self.assertEqual(len(calls), 1)
            self.assertEqual(collector.progress[url]["raw_content_hash"], first["raw_content_hash"])
            self.assertEqual(collector.progress[url]["fetch_count"], 1)
            # A manually changed cache cannot inherit a previous HTTP-body hash.
            Path(collector.cache_path(url)).write_text(text + "\n", encoding="utf-8")
            collector.process(url)
            self.assertIsNone(collector.progress[url]["raw_content_hash"])
            self.assertEqual(collector.progress[url]["hash_basis"], "text_snapshot")
            collector.process(url, refresh=True)
            self.assertEqual(len(calls), 2)
            self.assertEqual(collector.progress[url]["fetch_count"], 2)


if __name__ == "__main__":
    unittest.main()
