"""The fetch address policy: deny by default, one setting, checked on every hop, connection pinned."""
from __future__ import annotations

import httpx
import pytest

from resource_explorer.api_reference import fetch_policy as fp, live

OK_DOC = {"openapi": "3.0.0", "paths": {}}


def _res(mapping):
    calls = []

    def resolver(host, port):
        calls.append(host)
        if host not in mapping:
            raise OSError("nxdomain")
        v = mapping[host]
        return v.pop(0) if isinstance(v, list) and v and isinstance(v[0], list) else v
    resolver.calls = calls
    return resolver


def _fetch(url, allow, mapping=None, handler=None):
    seen = []

    def h(request):
        seen.append(request)
        return handler(request) if handler else httpx.Response(200, json=OK_DOC)
    r = live.fetch_openapi(url, allow=allow, resolver=_res(mapping or {}), transport=httpx.MockTransport(h))
    return r, seen


class TestParsing:
    def test_default_admits_localhost_only(self, monkeypatch):
        monkeypatch.delenv(fp.ENV, raising=False)
        assert [r.text for r in fp.effective_rules()] == ["localhost", "127.0.0.1", "::1"]
        assert fp.describe()["source"] == "default"
        assert fp.check_target("localhost", 8530, resolver=lambda h, p: ["127.0.0.1"]).ok
        assert not fp.check_target("example.com", 80, resolver=lambda h, p: ["93.184.216.34"]).ok
        assert not fp.check_target("10.0.0.5", 80).ok

    def test_json_list_comma_list_and_garbage_never_crash(self, monkeypatch):
        assert [r.text for r in fp.parse_allow('["a.com", "*.b.com"]')] == ["a.com", "*.b.com"]
        assert [r.text for r in fp.parse_allow("a.com, 10.0.0.0/8 ,::1")] == ["a.com", "10.0.0.0/8", "::1"]
        for junk in ("[", "[1,2", '{"a":1}', 5, None, "", "   ", "a b", "mid*dle.com", "*.", "a.com:99999", "a.com:x", [None, 3]):
            fp.parse_allow(junk)                                    # must not raise
        assert fp.parse_allow("mid*dle.com, *.x*.com") == []
        monkeypatch.setenv(fp.ENV, "[")
        assert fp.effective_rules() == [] or isinstance(fp.effective_rules(), list)

    def test_a_setting_with_no_valid_entry_denies_everything(self, monkeypatch):
        monkeypatch.setenv(fp.ENV, "mid*dle.com")
        assert not fp.check_target("localhost", 80, resolver=lambda h, p: ["127.0.0.1"]).ok

    def test_bracketed_ipv6_with_port(self):
        r = fp.parse_entry("[::1]:8530")
        assert r.kind == "net" and r.port == 8530


class TestRules:
    def test_exact_host(self):
        allow = ["api.example.com"]
        res = lambda h, p: ["93.184.216.34"]
        assert fp.check_target("api.example.com", 443, allow=allow, resolver=res).ok
        assert not fp.check_target("other.example.com", 443, allow=allow, resolver=res).ok

    def test_wildcard_matches_subdomains_not_the_bare_domain(self):
        allow = ["*.example.com"]
        res = lambda h, p: ["93.184.216.34"]
        assert fp.check_target("a.example.com", 80, allow=allow, resolver=res).ok
        assert fp.check_target("a.b.example.com", 80, allow=allow, resolver=res).ok
        assert not fp.check_target("example.com", 80, allow=allow, resolver=res).ok
        assert not fp.check_target("evilexample.com", 80, allow=allow, resolver=res).ok
        assert fp.check_target("example.com", 80, allow=["*.example.com", "example.com"], resolver=res).ok

    def test_cidr_and_ip_literal(self):
        assert fp.check_target("10.1.2.3", 80, allow=["10.0.0.0/8"]).ok
        assert not fp.check_target("11.1.2.3", 80, allow=["10.0.0.0/8"]).ok
        assert fp.check_target("::1", 80, allow=["::1"]).ok
        assert fp.check_target("192.168.1.5", 80, allow=["192.168.1.5"]).ok

    def test_a_name_resolving_into_a_cidr_is_admitted_by_the_cidr(self):
        assert fp.check_target("svc.internal", 80, allow=["10.0.0.0/8"], resolver=lambda h, p: ["10.2.2.2"]).ok
        assert not fp.check_target("svc.internal", 80, allow=["10.0.0.0/8"], resolver=lambda h, p: ["10.2.2.2", "8.8.8.8"]).ok

    def test_port_specific_and_portless(self):
        assert fp.check_target("localhost", 8530, allow=["localhost:8530"], resolver=lambda h, p: ["127.0.0.1"]).ok
        assert not fp.check_target("localhost", 8501, allow=["localhost:8530"], resolver=lambda h, p: ["127.0.0.1"]).ok
        assert fp.check_target("localhost", 1234, allow=["localhost"], resolver=lambda h, p: ["127.0.0.1"]).ok
        assert not fp.check_target("10.0.0.5", 81, allow=["10.0.0.0/8:80"]).ok

    def test_star_admits_any_host(self):
        assert fp.check_target("anything.example", 80, allow=["*"], resolver=lambda h, p: ["93.184.216.34"]).ok

    @pytest.mark.parametrize("ip", ["169.254.169.254", "169.254.1.1", "fe80::1", "0.0.0.1", "224.0.0.1", "ff02::1"])
    def test_always_denied_even_under_star(self, ip):
        t = fp.check_target(ip, 80, allow=["*"])
        assert not t.ok and t.reason == fp.NEVER_ALLOWED

    def test_a_name_that_resolves_to_metadata_is_denied_under_star(self):
        t = fp.check_target("sneaky.example", 80, allow=["*", "sneaky.example"], resolver=lambda h, p: ["169.254.169.254"])
        assert not t.ok and "169" not in t.reason

    def test_refusal_names_the_rule_not_the_resolution(self):
        t = fp.check_target("x.example", 80, allow=["localhost"], resolver=lambda h, p: ["93.184.216.34"])
        assert t.reason == "not in the allowed addresses (RE_API_FETCH_ALLOW)" and "93." not in t.reason

    def test_effective_list_is_described_for_the_admin_page(self, monkeypatch):
        monkeypatch.setenv(fp.ENV, '["a.com", "10.0.0.0/8:80"]')
        d = fp.describe()
        assert d["source"] == "environment" and d["allow"] == ["a.com", "10.0.0.0/8:80"]
        assert "169.254.0.0/16" in d["always_deny"]


class TestFetchHops:
    def test_default_refuses_an_unlisted_host_before_any_request(self, monkeypatch):
        monkeypatch.delenv(fp.ENV, raising=False)
        r, seen = _fetch("http://api.example.com/o", None, {"api.example.com": ["93.184.216.34"]})
        assert not r.ok and "allowed addresses" in r.reason and seen == []

    def test_link_local_never_connects(self):
        r, seen = _fetch("http://169.254.169.254/latest", ["*"])
        assert not r.ok and r.reason == fp.NEVER_ALLOWED and seen == []

    def test_redirect_to_a_disallowed_host_is_refused_at_that_hop(self):
        r, seen = _fetch("http://good.test/o", ["good.test"], {"good.test": ["10.1.1.1"], "evil.test": ["10.2.2.2"]},
                         handler=lambda q: httpx.Response(302, headers={"location": "http://evil.test/o"}))
        assert not r.ok and "allowed addresses" in r.reason and len(seen) == 1

    def test_redirect_into_metadata_is_refused(self):
        r, seen = _fetch("http://good.test/o", ["*"], {"good.test": ["10.1.1.1"]},
                         handler=lambda q: httpx.Response(302, headers={"location": "http://169.254.169.254/x"}))
        assert not r.ok and r.reason == fp.NEVER_ALLOWED and len(seen) == 1

    def test_the_connection_is_pinned_to_the_checked_address_and_the_name_kept(self):
        r, seen = _fetch("http://good.test:8530/o", ["good.test"], {"good.test": ["10.1.1.1"]})
        assert r.ok
        assert seen[0].url.host == "10.1.1.1" and seen[0].url.port == 8530
        assert seen[0].headers["host"] == "good.test:8530"

    def test_https_keeps_the_name_for_tls(self):
        r, seen = _fetch("https://good.test/o", ["good.test"], {"good.test": ["10.1.1.1"]})
        assert r.ok and seen[0].extensions.get("sni_hostname") == "good.test"

    def test_dns_rebinding_is_defeated_by_resolving_once(self):
        # first answer is allowed, every later answer is the metadata address
        answers = [["10.1.1.1"], ["169.254.169.254"], ["169.254.169.254"]]
        calls = []

        def resolver(host, port):
            calls.append(host)
            return answers.pop(0)
        seen = []
        r = live.fetch_openapi("http://rebind.test/o", allow=["rebind.test"], resolver=resolver,
                               transport=httpx.MockTransport(lambda q: seen.append(q) or httpx.Response(200, json=OK_DOC)))
        assert r.ok and calls == ["rebind.test"] and seen[0].url.host == "10.1.1.1"

    def test_a_name_that_first_resolves_to_a_denied_address_is_refused(self):
        r, seen = _fetch("http://rebind.test/o", ["rebind.test"], {"rebind.test": ["169.254.169.254"]})
        assert not r.ok and seen == []

    def test_unresolvable_allowed_name_is_could_not_connect(self):
        r, seen = _fetch("http://nowhere.test/o", ["nowhere.test"], {})
        assert not r.ok and r.reason == "could not connect" and seen == []

    def test_loopback_literals_follow_the_list(self):
        for u in ("http://127.0.0.1:8530/o", "http://[::1]:8530/o", "http://localhost:8530/o"):
            r, _ = _fetch(u, None, {"localhost": ["127.0.0.1"]})
            assert r.ok, (u, r.reason)
        r, _ = _fetch("http://10.0.0.5/o", None)
        assert not r.ok
