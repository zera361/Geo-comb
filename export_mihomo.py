#!/usr/bin/env python3
"""
export_mihomo.py — конвертирует geosite.dat / geoip.dat (xray-протобаф,
собранные builder.py) в нативные для mihomo артефакты:

  1. <category>.mrs             — бинарный ruleset (behavior: domain / ipcidr)
  2. <category>-classical.yaml  — то, что в mrs не влезает (regex/keyword у geosite)
  3. rule-providers.snippet.yaml — готовый кусок конфига мимохо со ссылками

mrs поддерживает ТОЛЬКО behavior domain и ipcidr. Domain.Plain (keyword) и
Domain.Regex уходят в classical yaml — mihomo читает такой rule-provider
напрямую, без mrs-упаковки.

Использование:
  python export_mihomo.py \
      --geosite geosite.dat --geoip geoip.dat \
      --out-dir mihomo-out --mihomo-bin ./mihomo
"""

import argparse
import ipaddress
import os
import subprocess
import sys

import router_pb2


def split_geosite_entry(entry):
    domain_lines = []
    classical_lines = []
    for d in entry.domain:
        if d.type == router_pb2.Domain.Domain:
            domain_lines.append(f"+.{d.value}")
        elif d.type == router_pb2.Domain.Full:
            domain_lines.append(d.value)
        elif d.type == router_pb2.Domain.Plain:
            classical_lines.append(f"DOMAIN-KEYWORD,{d.value}")
        elif d.type == router_pb2.Domain.Regex:
            classical_lines.append(f"DOMAIN-REGEX,{d.value}")
    return domain_lines, classical_lines


def format_cidr_line(c):
    try:
        addr = ipaddress.ip_address(c.ip)
        return f"{addr}/{c.prefix}"
    except Exception:
        return None


def run_mihomo_convert(mihomo_bin, kind, src_txt, dst_mrs, log):
    cmd = [mihomo_bin, "convert-ruleset", kind, "text", src_txt, dst_mrs]
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
        return True
    except FileNotFoundError:
        log(f"❌ Бинарник mihomo не найден ('{mihomo_bin}'). Укажи --mihomo-bin /путь/до/mihomo")
        return False
    except subprocess.CalledProcessError as e:
        log(f"❌ mihomo convert-ruleset упал на {src_txt}: {e.stderr.strip()}")
        return False


def export_geosite(path, out_dir, mihomo_bin, log):
    with open(path, "rb") as f:
        parsed = router_pb2.GeoSiteList.FromString(f.read())

    providers = []
    for entry in parsed.entry:
        cat = entry.country_code.upper()
        domain_lines, classical_lines = split_geosite_entry(entry)

        if domain_lines:
            txt_path = os.path.join(out_dir, f"geosite-{cat}.txt")
            mrs_path = os.path.join(out_dir, f"geosite-{cat}.mrs")
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write("\n".join(domain_lines) + "\n")
            if run_mihomo_convert(mihomo_bin, "domain", txt_path, mrs_path, log):
                log(f"✓ geosite {cat}: {len(domain_lines)} правил -> {mrs_path}")
                providers.append((f"geosite-{cat}", "domain", mrs_path))

        if classical_lines:
            yaml_path = os.path.join(out_dir, f"geosite-{cat}-classical.yaml")
            with open(yaml_path, "w", encoding="utf-8") as f:
                f.write("payload:\n")
                for line in classical_lines:
                    f.write(f"  - {line}\n")
            log(f"✓ geosite {cat}: {len(classical_lines)} regex/keyword-правил -> {yaml_path}")
            providers.append((f"geosite-{cat}-classical", "classical", yaml_path))

    return providers


def export_geoip(path, out_dir, mihomo_bin, log):
    with open(path, "rb") as f:
        parsed = router_pb2.GeoIPList.FromString(f.read())

    providers = []
    for entry in parsed.entry:
        cat = entry.country_code.upper()
        lines = [x for x in (format_cidr_line(c) for c in entry.cidr) if x]
        if not lines:
            continue
        txt_path = os.path.join(out_dir, f"geoip-{cat}.txt")
        mrs_path = os.path.join(out_dir, f"geoip-{cat}.mrs")
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        if run_mihomo_convert(mihomo_bin, "ipcidr", txt_path, mrs_path, log):
            log(f"✓ geoip {cat}: {len(lines)} CIDR -> {mrs_path}")
            providers.append((f"geoip-{cat}", "ipcidr", mrs_path))

    return providers


def write_snippet(providers, out_dir, repo_slug):
    base_url = f"https://raw.githubusercontent.com/{repo_slug}/release"
    snippet_path = os.path.join(out_dir, "rule-providers.snippet.yaml")
    with open(snippet_path, "w", encoding="utf-8") as f:
        f.write("rule-providers:\n")
        for name, behavior, path in providers:
            fname = os.path.basename(path)
            if behavior == "classical":
                f.write(
                    f"  {name}:\n"
                    f"    type: http\n"
                    f"    behavior: classical\n"
                    f"    url: \"{base_url}/{fname}\"\n"
                    f"    path: ./rule-providers/{fname}\n"
                    f"    interval: 86400\n"
                )
            else:
                f.write(
                    f"  {name}:\n"
                    f"    type: http\n"
                    f"    behavior: {behavior}\n"
                    f"    format: mrs\n"
                    f"    url: \"{base_url}/{fname}\"\n"
                    f"    path: ./rule-providers/{fname}\n"
                    f"    interval: 86400\n"
                )
    return snippet_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geosite", default="geosite.dat")
    ap.add_argument("--geoip", default="geoip.dat")
    ap.add_argument("--out-dir", default="mihomo-out")
    ap.add_argument("--mihomo-bin", default="mihomo")
    ap.add_argument("--skip-geosite", action="store_true")
    ap.add_argument("--skip-geoip", action="store_true")
    ap.add_argument(
        "--repo-slug",
        default=os.environ.get("GITHUB_REPOSITORY", "USER/REPO"),
        help="user/repo для генерации URL в rule-providers.snippet.yaml "
             "(в GitHub Actions подставляется автоматически из $GITHUB_REPOSITORY)",
    )
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    log = print
    all_providers = []

    if not args.skip_geosite:
        if not os.path.exists(args.geosite):
            log(f"⚠️  {args.geosite} не найден, пропускаю geosite")
        else:
            all_providers += export_geosite(args.geosite, args.out_dir, args.mihomo_bin, log)

    if not args.skip_geoip:
        if not os.path.exists(args.geoip):
            log(f"⚠️  {args.geoip} не найден, пропускаю geoip")
        else:
            all_providers += export_geoip(args.geoip, args.out_dir, args.mihomo_bin, log)

    if all_providers:
        snippet = write_snippet(all_providers, args.out_dir, args.repo_slug)
        log(f"\n[ГОТОВО] {len(all_providers)} rule-provider'ов. Сниппет конфига: {snippet}")
    else:
        log("\n[ПУСТО] Ни одного провайдера не сгенерировано — проверь входные .dat")


if __name__ == "__main__":
    sys.exit(main())
