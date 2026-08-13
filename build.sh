#!/usr/bin/env bash
# Полный пайплайн: скачать mihomo (если нет) -> собрать geosite/geoip.dat -> сгенерировать .mrs
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

CONFIG="${1:-config/config.json}"
OUT_DIR="output"
BIN_DIR="bin"
MIHOMO_BIN="${MIHOMO_BIN:-$BIN_DIR/mihomo}"

mkdir -p "$OUT_DIR" "$BIN_DIR"

# 1. Скачиваем mihomo, если бинарника ещё нет (нужен только convert-ruleset, версия не критична)
if [ ! -x "$MIHOMO_BIN" ]; then
    echo "[build.sh] Бинарник mihomo не найден, качаю latest linux-amd64..."
    ASSET_URL=$(curl -s https://api.github.com/repos/MetaCubeX/mihomo/releases/latest \
        | grep "browser_download_url" \
        | grep "linux-amd64" \
        | grep -v "go120" \
        | grep -v ".sha256" \
        | head -n1 \
        | cut -d '"' -f4)

    if [ -z "$ASSET_URL" ]; then
        echo "[build.sh] ❌ Не удалось найти release asset mihomo. Скачай вручную и положи в $MIHOMO_BIN"
        exit 1
    fi

    echo "[build.sh] Качаю: $ASSET_URL"
    curl -sL "$ASSET_URL" -o "$BIN_DIR/mihomo.gz"
    gunzip -f "$BIN_DIR/mihomo.gz"
    mv "$BIN_DIR"/mihomo* "$MIHOMO_BIN" 2>/dev/null || true
    chmod +x "$MIHOMO_BIN"
fi

"$MIHOMO_BIN" -v || true

# 2. Сборка geosite.dat / geoip.dat из источников (правила -- в config/config.json)
echo "[build.sh] === Этап 1: builder.py ==="
python builder.py "$CONFIG"

mv -f geosite.dat "$OUT_DIR/geosite.dat" 2>/dev/null || true
mv -f geoip.dat "$OUT_DIR/geoip.dat" 2>/dev/null || true

# 3. Конвертация в нативные mihomo-форматы (.mrs + classical.yaml)
echo "[build.sh] === Этап 2: export_mihomo.py ==="
python export_mihomo.py \
    --geosite "$OUT_DIR/geosite.dat" \
    --geoip "$OUT_DIR/geoip.dat" \
    --out-dir "$OUT_DIR" \
    --mihomo-bin "$MIHOMO_BIN" \
    --repo-slug "${GITHUB_REPOSITORY:-USER/REPO}"

echo "[build.sh] Готово. Все артефакты лежат в $OUT_DIR/"
ls -la "$OUT_DIR"
