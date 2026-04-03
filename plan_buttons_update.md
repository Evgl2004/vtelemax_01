# План обновления кнопок согласия и документов

## Цель
Заменить ссылки на согласие на рассылку и добавить вторую кнопку-ссылку в меню ознакомления с политикой конфиденциальности, с учётом уникальных URL для каждого бота (Telegram, VK, Max).

## Текущее состояние
1. **Ссылка на согласие на рассылку** (уведомления) используется в:
   - `core/guest_content.py`: `build_notifications_consent_screen()` — URL `https://sagur.24vds.ru/notifications/#`
   - `adapters/telegram/menu.py`: константа `NOTIFICATIONS_DOCS_URL` — тот же URL
   - Адаптеры VK и Max используют core-функцию, поэтому URL берётся из core.

2. **Ссылка на документы правил** (согласие на обработку персональных данных) используется в:
   - `core/guest_content.py`: `build_start_rules_screen()` — URL `https://sagur.24vds.ru/agreement/#`
   - `adapters/telegram/menu.py`: константа `DOCS_URL` — тот же URL.

3. **Меню правил** содержит две кнопки:
   - Кнопка-ссылка на документ (с текущим URL)
   - Кнопка «✅ Согласен»

## Требования
1. Заменить ссылку на согласие на рассылку на платформо-специфичные:
   - Telegram: `https://sagur.24vds.ru/mailing-consent/tg/`
   - VK: `https://sagur.24vds.ru/mailing-consent/vk/`
   - Max: `https://sagur.24vds.ru/mailing-consent/max/`

2. Добавить вторую кнопку-ссылку в меню правил (start_rules_screen) на политику конфиденциальности.
   - Всего должно быть три кнопки:
     1. Ссылка на «Согласие на передачу и обработку персональных данных»
     2. Ссылка на «Политика конфиденциальности»
     3. Кнопка «✅ Согласен» (без изменений)

3. Использовать уникальные URL для каждого бота:
   - **Согласие на передачу и обработку персональных данных**:
     - TG: `https://sagur.24vds.ru/personal-data-consent/tg/`
     - VK: `https://sagur.24vds.ru/personal-data-consent/vk/`
     - Max: `https://sagur.24vds.ru/personal-data-consent/max/`
   - **Политика конфиденциальности**:
     - TG: `https://sagur.24vds.ru/privacy-policy/tg/`
     - VK: `https://sagur.24vds.ru/privacy-policy/vk/`
     - Max: `https://sagur.24vds.ru/privacy-policy/max/`

## Архитектурные решения
- Добавить параметр `platform` (`"telegram"`, `"vk"`, `"max"`) в функции `build_start_rules_screen()` и `build_notifications_consent_screen()`.
- В core добавить словари `PERSONAL_DATA_CONSENT_URLS`, `PRIVACY_POLICY_URLS`, `MAILING_CONSENT_URLS`.
- Обновить адаптеры Telegram, VK, Max для передачи платформы при вызове core-функций.
- Адаптер Telegram в настоящее время использует собственные константы `DOCS_URL` и `NOTIFICATIONS_DOCS_URL`. Их нужно заменить на URL из core (или удалить и использовать core). Предлагается унифицировать подход: адаптер Telegram также должен использовать core с параметром платформы.

## Детальный план изменений

### 1. Обновление `core/guest_content.py`
- Добавить константы:
  ```python
  PERSONAL_DATA_CONSENT_URLS = {
      "telegram": "https://sagur.24vds.ru/personal-data-consent/tg/",
      "vk": "https://sagur.24vds.ru/personal-data-consent/vk/",
      "max": "https://sagur.24vds.ru/personal-data-consent/max/",
  }
  PRIVACY_POLICY_URLS = {
      "telegram": "https://sagur.24vds.ru/privacy-policy/tg/",
      "vk": "https://sagur.24vds.ru/privacy-policy/vk/",
      "max": "https://sagur.24vds.ru/privacy-policy/max/",
  }
  MAILING_CONSENT_URLS = {
      "telegram": "https://sagur.24vds.ru/mailing-consent/tg/",
      "vk": "https://sagur.24vds.ru/mailing-consent/vk/",
      "max": "https://sagur.24vds.ru/mailing-consent/max/",
  }
  ```
- Добавить подписи кнопок:
  ```python
  BUTTON_PERSONAL_DATA_CONSENT_LINK = "📄 Согласие на ПД"
  BUTTON_PRIVACY_POLICY_LINK = "📄 Политика конфиденциальности"
  ```
- Изменить `build_start_rules_screen(platform: str = "telegram")`:
  - Возвращать три кнопки:
    1. `MenuButtonContract` с `url=PERSONAL_DATA_CONSENT_URLS[platform]`, `label=BUTTON_PERSONAL_DATA_CONSENT_LINK`
    2. `MenuButtonContract` с `url=PRIVACY_POLICY_URLS[platform]`, `label=BUTTON_PRIVACY_POLICY_LINK`
    3. `MenuButtonContract` с `action=GuestMenuAction.ACCEPT_RULES`, `label=BUTTON_ACCEPT_RULES`
- Изменить `build_notifications_consent_screen(platform: str = "telegram", profile_text: str | None = None)`:
  - Использовать `url=MAILING_CONSENT_URLS[platform]` для кнопки `BUTTON_NOTIFICATIONS_DOCS`.

### 2. Обновление адаптеров
#### Адаптер VK (`adapters/vk/menu_adapter.py`)
- В методах `build_start_rules_screen()` и `build_notifications_consent_screen()` передавать платформу `"vk"` в core-функции.

#### Адаптер Max (`adapters/max/menu_adapter.py`)
- Аналогично передавать платформу `"max"`.

#### Адаптер Telegram (`adapters/telegram/menu.py`)
- Удалить константы `DOCS_URL` и `NOTIFICATIONS_DOCS_URL`.
- Изменить функции `build_rules_consent_inline_keyboard()` и `build_notifications_consent_inline_keyboard()`:
  - Использовать core-функции `build_start_rules_screen(platform="telegram")` и `build_notifications_consent_screen(platform="telegram")` для получения URL.
  - Альтернативно можно оставить константы, но обновить их на новые URL. Однако для единообразия лучше использовать core.

### 3. Тестирование
- Запустить существующие unit-тесты для guest_content и адаптеров.
- Проверить, что новые URL корректно подставляются.
- Убедиться, что меню правил отображает три кнопки, а меню уведомлений — одну ссылку с правильным URL.

### 4. Коммиты
Разбить изменения на логические коммиты:
1. Добавление констант и обновление core.
2. Обновление адаптеров VK и Max.
3. Обновление адаптера Telegram.
4. При необходимости — обновление тестов.

## Риски
- Изменение сигнатур core-функций может сломать существующие вызовы, но они используются только адаптерами, которые мы же и обновляем.
- Длина кнопок: предложенные подписи «📄 Согласие на ПД» и «📄 Политика конфиденциальности» могут не поместиться в интерфейсе VK/Telegram. Можно сократить до «Согласие на ПД» и «Политика». Нужно согласовать с пользователем.
- Ошибка в словарях URL (опечатка) приведёт к нерабочим ссылкам. Необходимо тщательно проверить.

## Вопросы к пользователю
1. Устраивают ли предложенные подписи кнопок? Если нет, предложите альтернативы.
2. Нужно ли также обновить текст экрана правил (заменить «по ссылке ниже» на «по ссылкам ниже»)?
3. Можно ли приступить к реализации?

## Следующие шаги
После утверждения плана переключиться в режим Code и выполнить изменения.