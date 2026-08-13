# geo-combine

Свой комбайн для сборки geosite/geoip из нескольких источников (v2ray/xray `.dat`)
и конвертации их в форматы, которые нативно понимает **mihomo**: `.mrs` (domain/ipcidr)
и `classical.yaml` (regex/keyword — то, что в `.mrs` не упаковывается).

Пайплайн из трёх шагов:

```
builder.py  →  geosite.dat / geoip.dat   (xray-протобаф, слияние источников по правилам)
export_mihomo.py  →  *.mrs + *-classical.yaml + rule-providers.snippet.yaml
build.sh  →  обвязка, которая гоняет всё сразу и качает бинарник mihomo, если его нет
```

Плюс `tools/parser.py` — вспомогательный инструмент, который просто разворачивает
любой `.dat` в читаемые `.lst`-списки по категориям (для инспекции источников,
на выход пайплайна не влияет).

---

## 1. Структура репозитория

```
geo-combine/
├── builder.py                  # сборщик geosite.dat / geoip.dat из источников
├── export_mihomo.py            # конвертация .dat -> .mrs / classical.yaml
├── build.sh                    # оркестратор всего пайплайна
├── router.proto                # proto-схема xray (Domain/CIDR/GeoIP/GeoSite)
├── router_pb2.py                # скомпилированная из router.proto Python-обвязка
├── requirements.txt
├── config/
│   └── config.json             # ТВОИ правила: какие источники -> в какие категории
├── tools/
│   └── parser.py                # инспекция .dat файлов (не обязателен для сборки)
└── .github/workflows/build.yml # автосборка + публикация по расписанию
```

`router_pb2.py` уже скомпилирован и лежит в репозитории — protoc/grpc-tools
на этапе сборки НЕ нужен. Трогать его нужно только если меняешь `router.proto`
(см. раздел 7).

---

## 2. Быстрый локальный тест перед пушем на GitHub

```bash
git clone <твой-репозиторий>
cd geo-combine
pip install -r requirements.txt
chmod +x build.sh
./build.sh config/config.json
```

Скрипт сам скачает бинарник `mihomo` (linux-amd64, последний релиз) в `bin/mihomo`,
если его там ещё нет, соберёт `geosite.dat` / `geoip.dat` и разложит результат в `output/`:

```
output/
├── geosite.dat
├── geoip.dat
├── geosite-GEOGAGA-DIRECT.mrs
├── geosite-GEOGAGA-PROXY.mrs
├── geosite-GEOGAGA-BLOCK.mrs
├── geoip-GEOGAGA-DIRECT.mrs
├── geoip-GEOGAGA-PROXY.mrs
├── geosite-GEOGAGA-BLOCK-classical.yaml   # если там были regex/keyword-правила
└── rule-providers.snippet.yaml
```

Если под рукой уже есть свой бинарник mihomo (например, на роутере или в другой
архитектуре) — укажи путь явно: `MIHOMO_BIN=/путь/до/mihomo ./build.sh`.

---

## 3. Настройка правил под себя

Всё, что реально меняется от запуска к запуску — это `config/config.json`.
Формат: список источников, у каждого — список правил `{src: [...], dst: "..."}`,
которые мапят категории источника в твои целевые категории.

```json
{
  "geosite": [
    {
      "url": "https://.../geosite.dat",
      "rules": [
        {"src": ["category-ru", "apple", "steam"], "dst": "GEOGAGA-DIRECT"},
        {"src": ["category-ads-all"], "dst": "GEOGAGA-BLOCK"}
      ]
    }
  ],
  "geoip": [ /* аналогично, cidr вместо domain */ ]
}
```

Поддерживаются источники трёх типов (тип определяется по расширению URL):
- `.dat` — protobuf v2ray/xray формат
- `.json` — провайдер → cidr/asn (geoip) или категория → список доменов (geosite)
- `.lst` / `.txt` — plain-текст, `"*"` в `src` берёт всё из файла целиком

Категории, начинающиеся с `GEOGAGA-`, автоматически проходят через
`optimize_domains()` / `optimize_ips()` — схлопывание CIDR и удаление доменов,
уже покрытых родительским доменом. Остальные категории просто дедуплицируются.

Файлы с `custom-additions` в URL — это твои собственные добавления; при их
обработке скрипт логирует конфликты с апстрим-источниками в `tools/review.log`
(полезно, чтобы не дублировать вручную то, что уже приезжает откуда-то ещё).

---

## 4. Публикация на GitHub

### 4.1 Создание репозитория

1. На GitHub: New repository → `geo-combine` (или как хочешь).
   **Публичный** — это важно: `raw.githubusercontent.com` бесплатно и без
   авторизации отдаёт файлы только из публичных репозиториев. Если репозиторий
   приватный, mihomo не сможет скачать `.mrs` по прямой ссылке (решения — см. раздел 6).
2. Залей всё содержимое этой папки в `main`:

```bash
cd geo-combine
git init
git add .
git commit -m "init"
git branch -M main
git remote add origin https://github.com/<user>/<repo>.git
git push -u origin main
```

### 4.2 Разрешить Actions пушить в репозиторий

Settings → Actions → General → Workflow permissions →
**Read and write permissions** → Save.

Без этого шага `git push` из workflow в ветку `release` упадёт с 403 —
дефолтный `GITHUB_TOKEN` в новых репозиториях имеет только read-доступ.

### 4.3 Запуск

Workflow `.github/workflows/build.yml` триггерится:
- по расписанию (`cron: "0 3 * * *"` — каждый день в 03:00 UTC, поправь под себя),
- вручную (Actions → Build geo rules → Run workflow),
- при пуше изменений в `config/`, `builder.py`, `export_mihomo.py`, `build.sh`.

Что он делает:
1. Собирает пайплайн так же, как `./build.sh` локально.
2. Инициализирует git **заново внутри `output/`** и делает один-единственный
   commit → `git push --force` в ветку `release`. Благодаря `--force` ветка
   `release` всегда содержит только последнюю сборку одним коммитом — история
   не разрастается на гигабайты бинарных `.dat`/`.mrs` при ежедневных запусках.
3. Кладёт `tools/review.log` (дубликаты между кастомными и апстрим-источниками)
   как artifact запуска — глянуть можно во вкладке Actions конкретного ран.

После первого успешного запуска в репозитории появится ветка `release` с
файлами, доступными по адресам вида:

```
https://raw.githubusercontent.com/<user>/<repo>/release/geosite-GEOGAGA-DIRECT.mrs
https://raw.githubusercontent.com/<user>/<repo>/release/geoip-GEOGAGA-PROXY.mrs
https://raw.githubusercontent.com/<user>/<repo>/release/geosite.dat
```

---

## 5. Подключение к конфигу mihomo

### Вариант А — сразу нативный `.mrs` (рекомендуется)

`output/rule-providers.snippet.yaml` после сборки уже содержит готовый блок —
просто скопируй нужные провайдеры в свой `config.yaml`:

```yaml
rule-providers:
  geosite-GEOGAGA-DIRECT:
    type: http
    behavior: domain
    format: mrs
    url: "https://raw.githubusercontent.com/<user>/<repo>/release/geosite-GEOGAGA-DIRECT.mrs"
    path: ./rule-providers/geosite-GEOGAGA-DIRECT.mrs
    interval: 86400

  geoip-GEOGAGA-PROXY:
    type: http
    behavior: ipcidr
    format: mrs
    url: "https://raw.githubusercontent.com/<user>/<repo>/release/geoip-GEOGAGA-PROXY.mrs"
    path: ./rule-providers/geoip-GEOGAGA-PROXY.mrs
    interval: 86400

rules:
  - RULE-SET,geosite-GEOGAGA-BLOCK,REJECT
  - RULE-SET,geosite-GEOGAGA-DIRECT,DIRECT
  - RULE-SET,geoip-GEOGAGA-PROXY,PROXY
  - RULE-SET,geosite-GEOGAGA-PROXY,PROXY
  - MATCH,DIRECT
```

Если где-то в категории были regex/keyword-правила — появится ещё
`geosite-GEOGAGA-XXX-classical` с `behavior: classical` (без `format: mrs`) —
его тоже нужно прописать отдельным rule-provider и добавить в `rules:`.

### Вариант Б — как обычный geosite.dat/geoip.dat (без .mrs)

Если пока не хочешь возиться с rule-providers, mihomo умеет читать и сырой
xray-формат напрямую через `geox-url`:

```yaml
geodata-mode: true
geox-url:
  geosite: "https://raw.githubusercontent.com/<user>/<repo>/release/geosite.dat"
  geoip: "https://raw.githubusercontent.com/<user>/<repo>/release/geoip.dat"

rules:
  - GEOSITE,GEOGAGA-BLOCK,REJECT
  - GEOSITE,GEOGAGA-DIRECT,DIRECT
  - GEOIP,GEOGAGA-PROXY,PROXY
  - GEOSITE,GEOGAGA-PROXY,PROXY
  - MATCH,DIRECT
```

`.mrs` грузится и матчится в разы быстрее, чем polygon-парсинг protobuf на
каждый чих, так что для роутера (ER605) вариант А предпочтительнее в долгую.

---

## 6. Если репозиторий приватный

`raw.githubusercontent.com` для приватных репо без токена не отдаёт файлы.
Варианты:
- держать репозиторий с кодом приватным, а публиковать `output/` в **отдельный
  публичный** репозиторий (двух-репозиторийная схема, добавь второй remote и
  пуш туда);
- публиковать через GitHub Releases (`softprops/action-gh-release`) и раздавать
  по `release-assets.githubusercontent.com` — но там URL меняется от релиза к
  релизу, придётся или использовать фиксированный тег (`latest`, с
  `--clobber`), или обновлять URL в конфиге mihomo вручную;
- проксировать через свой nginx/Cloudflare Worker с GitHub PAT — если уже есть
  инфраструктура (vasyan.xyz), можно отдавать `output/` с одной из VPS вместо
  GitHub вообще.

---

## 7. Если меняешь router.proto

Нужен только если Xray когда-нибудь поменяет формат `.dat` (пока стабилен
годами). Локально:

```bash
pip install grpcio-tools
python -m grpc_tools.protoc -I. --python_out=. router.proto
```

Закоммить обновлённый `router_pb2.py` — CI его просто использует, компиляция
на каждый запуск не нужна.

---

## 8. Troubleshooting

- **`git push` в release падает с 403`** — не включено "Read and write
  permissions" для Actions (см. 4.2).
- **ASN-резолв через RIPE не работает / много warning в логе** —
  `stat.ripe.net` иногда лимитирует по rate; в `builder.py` уже есть retry с
  backoff (3 попытки), но при системном 403 просто теряется часть ASN-based
  CIDR — не фатально, остальные источники соберутся нормально.
- **mihomo binary not found в build.sh** — GitHub API отдал rate-limit при
  поиске latest-релиза (бывает на shared раннерах при параллельных запусках) —
  просто перезапусти workflow вручную (Run workflow), либо захардкодь версию
  в `build.sh` вместо автоопределения через `releases/latest`.
- **`ValidateProtobufRuntimeVersion` ошибка** — версия `protobuf` в
  `requirements.txt` должна совпадать с той, которой скомпилирован
  `router_pb2.py` (сейчас `7.35.1`, см. заголовок файла).
