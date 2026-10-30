# cs2-data

Сборщик истории продаж CSFloat для CS2: цена, float и номер паттерна последних продаж по скинам с редкими паттернами
и по ходовым предметам. Работает по расписанию в GitHub Actions, данные — в релизе
[data](../../releases/tag/data): `sales.json.gz`, `items.json`, `status.json`.

Формат `sales.json.gz`: `{"sales": {"название предмета": [[время продажи (unix), цена $, float, номер паттерна, наклейки $], ...]}, "fetched": {...}, "updated": ...}`.
